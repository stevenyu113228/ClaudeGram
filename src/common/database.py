"""S3-backed SQLite database manager for serverless environments."""
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# SQL schema for initializing the database
SCHEMA_SQL = """
-- Users allowed to interact with the bot
CREATE TABLE IF NOT EXISTS allowed_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    display_name TEXT,
    added_by TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- Groups where the bot is allowed to respond
CREATE TABLE IF NOT EXISTS allowed_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_group_id INTEGER UNIQUE NOT NULL,
    group_name TEXT,
    added_by TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- Conversation sessions (tracks reply chains)
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_chat_id INTEGER NOT NULL,
    root_message_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    UNIQUE(telegram_chat_id, root_message_id)
);

-- Individual messages within conversations
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    telegram_message_id INTEGER NOT NULL,
    telegram_user_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    reply_to_message_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

-- URL summaries for follow-up questions
CREATE TABLE IF NOT EXISTS url_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    content_hash TEXT,
    summary_zh_tw TEXT NOT NULL,
    raw_content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

-- Admin session tokens
CREATE TABLE IF NOT EXISTS admin_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_token TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    ip_address TEXT
);

-- Application logs (stored in DB for admin viewing)
CREATE TABLE IF NOT EXISTS app_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL CHECK(level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR')),
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    telegram_user_id INTEGER,
    telegram_chat_id INTEGER,
    metadata TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Processed updates for idempotency (prevent duplicate processing)
CREATE TABLE IF NOT EXISTS processed_updates (
    update_id INTEGER PRIMARY KEY,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_conversations_chat ON conversations(telegram_chat_id);
CREATE INDEX IF NOT EXISTS idx_conversations_root ON conversations(telegram_chat_id, root_message_id);
CREATE INDEX IF NOT EXISTS idx_url_summaries_conversation ON url_summaries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_app_logs_created ON app_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_app_logs_level ON app_logs(level, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_token ON admin_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires ON admin_sessions(expires_at);
"""


class S3SQLiteManager:
    """
    Manages SQLite database persistence on S3.

    Pattern: Download from S3 -> Perform operations -> Upload back to S3

    This is suitable for low-to-medium traffic applications where
    concurrent write conflicts are rare.
    """

    def __init__(
        self,
        bucket: str,
        key: str,
        local_path: str | None = None,
        s3_client: Any | None = None,
    ):
        """
        Initialize S3 SQLite manager.

        Args:
            bucket: S3 bucket name
            key: S3 object key for the database file
            local_path: Local path to store the database (default: /tmp/<key>)
            s3_client: Optional boto3 S3 client (for testing)
        """
        self.bucket = bucket
        self.key = key
        self.local_path = local_path or f"/tmp/{os.path.basename(key)}"
        self._s3 = s3_client or boto3.client("s3")
        self._downloaded = False
        self._db_exists_in_s3 = None

    def _download_if_needed(self) -> None:
        """Download database from S3 if not already downloaded."""
        if self._downloaded:
            return

        try:
            logger.info(f"Downloading database from s3://{self.bucket}/{self.key}")
            self._s3.download_file(self.bucket, self.key, self.local_path)
            self._db_exists_in_s3 = True
            logger.info("Database downloaded successfully")
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                logger.info("Database not found in S3, will create new one")
                self._db_exists_in_s3 = False
                self._init_database()
            else:
                logger.error(f"Failed to download database: {e}")
                raise
        except Exception as e:
            logger.error(f"Unexpected error downloading database: {e}")
            raise

        self._downloaded = True

    def _init_database(self) -> None:
        """Initialize a new database with schema."""
        logger.info("Initializing new database with schema")
        conn = sqlite3.connect(self.local_path)
        try:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            logger.info("Database schema created successfully")
        finally:
            conn.close()

    def _upload(self) -> None:
        """Upload database to S3."""
        try:
            logger.info(f"Uploading database to s3://{self.bucket}/{self.key}")
            self._s3.upload_file(self.local_path, self.bucket, self.key)
            logger.info("Database uploaded successfully")
        except Exception as e:
            logger.error(f"Failed to upload database: {e}")
            raise

    @contextmanager
    def connection(
        self, upload_on_close: bool = True, readonly: bool = False
    ) -> Generator[sqlite3.Connection, None, None]:
        """
        Get a database connection context manager.

        Args:
            upload_on_close: Whether to upload database to S3 after operations
            readonly: If True, don't upload even if upload_on_close is True

        Yields:
            SQLite connection with Row factory

        Example:
            with db.connection() as conn:
                cursor = conn.execute("SELECT * FROM users")
                rows = cursor.fetchall()
        """
        # Always download fresh for readonly operations to ensure we have latest data
        # This is important for authorization checks in warm Lambda instances
        if readonly:
            self._downloaded = False
        self._download_if_needed()

        conn = sqlite3.connect(self.local_path)
        conn.row_factory = sqlite3.Row
        # Enable foreign keys
        conn.execute("PRAGMA foreign_keys = ON")

        try:
            yield conn
            conn.commit()
            if upload_on_close and not readonly:
                self._upload()
        except Exception as e:
            conn.rollback()
            logger.error(f"Database operation failed: {e}")
            raise
        finally:
            conn.close()

    def reset_download_state(self) -> None:
        """Reset download state to force re-download on next connection."""
        self._downloaded = False


# Repository classes for cleaner data access


class UserRepository:
    """Repository for user management operations."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db

    def is_user_allowed(self, telegram_user_id: int) -> bool:
        """Check if a user is allowed to use the bot."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM allowed_users WHERE telegram_user_id = ? AND is_active = 1",
                (telegram_user_id,),
            )
            return cursor.fetchone() is not None

    def add_user(
        self,
        telegram_user_id: int,
        username: str | None = None,
        display_name: str | None = None,
        added_by: str | None = None,
    ) -> dict[str, Any]:
        """Add a new allowed user."""
        with self.db.connection() as conn:
            # Try to insert, ignore if exists
            conn.execute(
                """
                INSERT OR IGNORE INTO allowed_users (telegram_user_id, username, display_name, added_by)
                VALUES (?, ?, ?, ?)
                """,
                (telegram_user_id, username, display_name, added_by),
            )
            # Update if already exists
            conn.execute(
                """
                UPDATE allowed_users SET username = ?, display_name = ?, is_active = 1
                WHERE telegram_user_id = ?
                """,
                (username, display_name, telegram_user_id),
            )
            # Fetch the result
            cursor = conn.execute(
                "SELECT * FROM allowed_users WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            row = cursor.fetchone()
            return dict(row)

    def remove_user(self, telegram_user_id: int) -> bool:
        """Deactivate a user (soft delete)."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE allowed_users SET is_active = 0 WHERE telegram_user_id = ?",
                (telegram_user_id,),
            )
            return cursor.rowcount > 0

    def list_users(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        """List all allowed users."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            query = "SELECT * FROM allowed_users"
            if not include_inactive:
                query += " WHERE is_active = 1"
            query += " ORDER BY added_at DESC"
            cursor = conn.execute(query)
            return [dict(row) for row in cursor.fetchall()]


class GroupRepository:
    """Repository for group management operations."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db

    def is_group_allowed(self, telegram_group_id: int) -> bool:
        """Check if a group is allowed."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM allowed_groups WHERE telegram_group_id = ? AND is_active = 1",
                (telegram_group_id,),
            )
            return cursor.fetchone() is not None

    def add_group(
        self,
        telegram_group_id: int,
        group_name: str | None = None,
        added_by: str | None = None,
    ) -> dict[str, Any]:
        """Add a new allowed group."""
        with self.db.connection() as conn:
            # Try to insert, ignore if exists
            conn.execute(
                """
                INSERT OR IGNORE INTO allowed_groups (telegram_group_id, group_name, added_by)
                VALUES (?, ?, ?)
                """,
                (telegram_group_id, group_name, added_by),
            )
            # Update if already exists
            conn.execute(
                """
                UPDATE allowed_groups SET group_name = ?, is_active = 1
                WHERE telegram_group_id = ?
                """,
                (group_name, telegram_group_id),
            )
            # Fetch the result
            cursor = conn.execute(
                "SELECT * FROM allowed_groups WHERE telegram_group_id = ?",
                (telegram_group_id,),
            )
            row = cursor.fetchone()
            return dict(row)

    def remove_group(self, telegram_group_id: int) -> bool:
        """Deactivate a group (soft delete)."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "UPDATE allowed_groups SET is_active = 0 WHERE telegram_group_id = ?",
                (telegram_group_id,),
            )
            return cursor.rowcount > 0

    def list_groups(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        """List all allowed groups."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            query = "SELECT * FROM allowed_groups"
            if not include_inactive:
                query += " WHERE is_active = 1"
            query += " ORDER BY added_at DESC"
            cursor = conn.execute(query)
            return [dict(row) for row in cursor.fetchall()]


class ConversationRepository:
    """Repository for conversation and message operations."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db

    def get_or_create_conversation(
        self,
        telegram_chat_id: int,
        message_id: int,
        reply_to_message_id: int | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """
        Get or create a conversation based on reply chain.

        Returns:
            Tuple of (conversation_id, list of previous messages in conversation)
        """
        with self.db.connection() as conn:
            conversation_id = None
            messages = []

            if reply_to_message_id:
                # Check if replying to an existing conversation
                cursor = conn.execute(
                    """
                    SELECT c.id FROM conversations c
                    JOIN messages m ON c.id = m.conversation_id
                    WHERE c.telegram_chat_id = ? AND m.telegram_message_id = ?
                    LIMIT 1
                    """,
                    (telegram_chat_id, reply_to_message_id),
                )
                row = cursor.fetchone()
                if row:
                    conversation_id = row["id"]
                    # Update conversation timestamp
                    conn.execute(
                        "UPDATE conversations SET updated_at = ? WHERE id = ?",
                        (datetime.utcnow().isoformat(), conversation_id),
                    )
                    # Fetch existing messages
                    cursor = conn.execute(
                        """
                        SELECT role, content FROM messages
                        WHERE conversation_id = ?
                        ORDER BY created_at ASC
                        """,
                        (conversation_id,),
                    )
                    messages = [dict(row) for row in cursor.fetchall()]

            if conversation_id is None:
                # Create new conversation
                root_id = reply_to_message_id if reply_to_message_id else message_id
                # Use INSERT OR IGNORE then SELECT to handle conflicts
                conn.execute(
                    """
                    INSERT OR IGNORE INTO conversations (telegram_chat_id, root_message_id)
                    VALUES (?, ?)
                    """,
                    (telegram_chat_id, root_id),
                )
                cursor = conn.execute(
                    """
                    SELECT id FROM conversations
                    WHERE telegram_chat_id = ? AND root_message_id = ?
                    """,
                    (telegram_chat_id, root_id),
                )
                conversation_id = cursor.fetchone()["id"]

            return conversation_id, messages

    def add_message(
        self,
        conversation_id: int,
        telegram_message_id: int,
        telegram_user_id: int,
        role: str,
        content: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a message to a conversation."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO messages
                (conversation_id, telegram_message_id, telegram_user_id, role, content, reply_to_message_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    telegram_message_id,
                    telegram_user_id,
                    role,
                    content,
                    reply_to_message_id,
                ),
            )
            message_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            cursor = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
            return dict(cursor.fetchone())

    def get_conversation_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        """Get all messages in a conversation."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            cursor = conn.execute(
                """
                SELECT role, content FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                """,
                (conversation_id,),
            )
            return [dict(row) for row in cursor.fetchall()]


class URLSummaryRepository:
    """Repository for URL summary operations."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db

    def save_summary(
        self,
        conversation_id: int,
        url: str,
        title: str | None,
        summary_zh_tw: str,
        raw_content: str | None = None,
        content_hash: str | None = None,
    ) -> dict[str, Any]:
        """Save a URL summary."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO url_summaries
                (conversation_id, url, title, summary_zh_tw, raw_content, content_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, url, title, summary_zh_tw, raw_content, content_hash),
            )
            summary_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            cursor = conn.execute("SELECT * FROM url_summaries WHERE id = ?", (summary_id,))
            return dict(cursor.fetchone())

    def get_summary_by_url(
        self, conversation_id: int, url: str
    ) -> dict[str, Any] | None:
        """Get summary for a URL in a conversation."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            cursor = conn.execute(
                """
                SELECT * FROM url_summaries
                WHERE conversation_id = ? AND url = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (conversation_id, url),
            )
            row = cursor.fetchone()
            return dict(row) if row else None


class LogRepository:
    """Repository for application log operations."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db

    def add_log(
        self,
        level: str,
        source: str,
        message: str,
        telegram_user_id: int | None = None,
        telegram_chat_id: int | None = None,
        metadata: str | None = None,
    ) -> None:
        """Add a log entry."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO app_logs
                (level, source, message, telegram_user_id, telegram_chat_id, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (level, source, message, telegram_user_id, telegram_chat_id, metadata),
            )

    def get_logs(
        self,
        level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get logs with optional filtering."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            # Build query
            where_clause = ""
            params: list[Any] = []
            if level:
                where_clause = "WHERE level = ?"
                params.append(level)

            # Get total count
            count_query = f"SELECT COUNT(*) FROM app_logs {where_clause}"
            cursor = conn.execute(count_query, params)
            total = cursor.fetchone()[0]

            # Get logs
            query = f"""
                SELECT * FROM app_logs {where_clause}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
            """
            params.extend([limit, offset])
            cursor = conn.execute(query, params)
            logs = [dict(row) for row in cursor.fetchall()]

            return logs, total


class AdminSessionRepository:
    """Repository for admin session operations."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db

    def create_session(
        self, session_token: str, expires_at: datetime, ip_address: str | None = None
    ) -> None:
        """Create a new admin session."""
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO admin_sessions (session_token, expires_at, ip_address)
                VALUES (?, ?, ?)
                """,
                (session_token, expires_at.isoformat(), ip_address),
            )

    def validate_session(self, session_token: str) -> bool:
        """Check if a session token is valid."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            cursor = conn.execute(
                """
                SELECT 1 FROM admin_sessions
                WHERE session_token = ? AND expires_at > datetime('now')
                """,
                (session_token,),
            )
            return cursor.fetchone() is not None

    def delete_session(self, session_token: str) -> None:
        """Delete a session."""
        with self.db.connection() as conn:
            conn.execute(
                "DELETE FROM admin_sessions WHERE session_token = ?",
                (session_token,),
            )

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= datetime('now')"
            )
            return cursor.rowcount

    def count_recent_sessions_by_ip(self, ip_address: str, minutes: int = 15) -> int:
        """Count sessions created from an IP in the last N minutes (for rate limiting)."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            cursor = conn.execute(
                """
                SELECT COUNT(*) FROM admin_sessions
                WHERE ip_address = ? AND created_at > datetime('now', ? || ' minutes')
                """,
                (ip_address, f"-{minutes}"),
            )
            return cursor.fetchone()[0]


class ProcessedUpdateRepository:
    """Repository for tracking processed Telegram updates (idempotency)."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db

    def is_processed(self, update_id: int) -> bool:
        """Check if an update has already been processed."""
        with self.db.connection(upload_on_close=False, readonly=True) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM processed_updates WHERE update_id = ?",
                (update_id,),
            )
            return cursor.fetchone() is not None

    def mark_processed(self, update_id: int) -> None:
        """Mark an update as processed."""
        with self.db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO processed_updates (update_id) VALUES (?)",
                (update_id,),
            )

    def cleanup_old_updates(self, hours: int = 24) -> int:
        """Remove old processed update records to prevent table bloat."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "DELETE FROM processed_updates WHERE processed_at < datetime('now', ? || ' hours')",
                (f"-{hours}",),
            )
            return cursor.rowcount
