"""Admin authentication module."""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from common.database import AdminSessionRepository, S3SQLiteManager

logger = logging.getLogger(__name__)

# Session expiration time
SESSION_EXPIRY_HOURS = 24

# Rate limit: max sessions per IP in 15 minutes
MAX_LOGIN_ATTEMPTS = 5
RATE_LIMIT_MINUTES = 15


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 (simple approach for environment variable storage)."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, stored_password: str) -> bool:
    """Verify a password against stored password (plain text comparison for env vars)."""
    return password == stored_password


class AdminAuthService:
    """Service for admin authentication."""

    def __init__(self, db: S3SQLiteManager, admin_password: str):
        self.session_repo = AdminSessionRepository(db)
        self.admin_password = admin_password

    def login(self, password: str, ip_address: str | None = None) -> str | None:
        """
        Authenticate admin and create session.

        Args:
            password: The password to verify
            ip_address: Client IP for rate limiting

        Returns:
            Session token if successful, None otherwise
        """
        # Rate limiting
        if ip_address:
            recent_attempts = self.session_repo.count_recent_sessions_by_ip(
                ip_address, RATE_LIMIT_MINUTES
            )
            if recent_attempts >= MAX_LOGIN_ATTEMPTS:
                logger.warning(f"Rate limit exceeded for IP: {ip_address}")
                return None

        # Verify password
        if not verify_password(password, self.admin_password):
            logger.warning("Invalid admin password")
            return None

        # Create session
        session_token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=SESSION_EXPIRY_HOURS)

        self.session_repo.create_session(
            session_token=session_token,
            expires_at=expires_at,
            ip_address=ip_address,
        )

        logger.info(f"Admin session created, expires at {expires_at}")
        return session_token

    def validate_session(self, session_token: str | None) -> bool:
        """
        Validate a session token.

        Args:
            session_token: Token to validate

        Returns:
            True if valid, False otherwise
        """
        if not session_token:
            return False
        return self.session_repo.validate_session(session_token)

    def logout(self, session_token: str) -> None:
        """
        Invalidate a session.

        Args:
            session_token: Token to invalidate
        """
        self.session_repo.delete_session(session_token)
        logger.info("Admin session invalidated")

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions."""
        count = self.session_repo.cleanup_expired_sessions()
        if count > 0:
            logger.info(f"Cleaned up {count} expired sessions")
        return count


def get_session_from_cookie(cookie_header: str | None) -> str | None:
    """Extract session token from Cookie header."""
    if not cookie_header:
        return None

    for cookie in cookie_header.split(";"):
        cookie = cookie.strip()
        if cookie.startswith("session="):
            return cookie[8:]

    return None
