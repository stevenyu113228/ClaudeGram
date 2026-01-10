"""Admin API route handlers."""
import json
import logging
from typing import Any

from common.database import (
    GroupRepository,
    LogRepository,
    S3SQLiteManager,
    UserRepository,
)

logger = logging.getLogger(__name__)


class AdminRoutes:
    """Handlers for admin API routes."""

    def __init__(self, db: S3SQLiteManager):
        self.db = db
        self.user_repo = UserRepository(db)
        self.group_repo = GroupRepository(db)
        self.log_repo = LogRepository(db)

    # User management

    def list_users(self) -> dict[str, Any]:
        """List all allowed users."""
        users = self.user_repo.list_users(include_inactive=True)
        return {
            "statusCode": 200,
            "body": json.dumps({"users": users}, default=str),
        }

    def add_user(self, body: dict) -> dict[str, Any]:
        """Add a new allowed user."""
        telegram_user_id = body.get("telegram_user_id")
        if not telegram_user_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "telegram_user_id is required"}),
            }

        try:
            telegram_user_id = int(telegram_user_id)
        except ValueError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "telegram_user_id must be a number"}),
            }

        user = self.user_repo.add_user(
            telegram_user_id=telegram_user_id,
            username=body.get("username"),
            display_name=body.get("display_name"),
            added_by="admin",
        )

        logger.info(f"Added user: {telegram_user_id}")
        return {
            "statusCode": 201,
            "body": json.dumps({"success": True, "user": user}, default=str),
        }

    def remove_user(self, telegram_user_id: str) -> dict[str, Any]:
        """Remove (deactivate) a user."""
        try:
            user_id = int(telegram_user_id)
        except ValueError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid user ID"}),
            }

        success = self.user_repo.remove_user(user_id)
        if success:
            logger.info(f"Removed user: {user_id}")
            return {
                "statusCode": 200,
                "body": json.dumps({"success": True}),
            }
        else:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "User not found"}),
            }

    # Group management

    def list_groups(self) -> dict[str, Any]:
        """List all allowed groups."""
        groups = self.group_repo.list_groups(include_inactive=True)
        return {
            "statusCode": 200,
            "body": json.dumps({"groups": groups}, default=str),
        }

    def add_group(self, body: dict) -> dict[str, Any]:
        """Add a new allowed group."""
        telegram_group_id = body.get("telegram_group_id")
        if not telegram_group_id:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "telegram_group_id is required"}),
            }

        try:
            telegram_group_id = int(telegram_group_id)
        except ValueError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "telegram_group_id must be a number"}),
            }

        group = self.group_repo.add_group(
            telegram_group_id=telegram_group_id,
            group_name=body.get("group_name"),
            added_by="admin",
        )

        logger.info(f"Added group: {telegram_group_id}")
        return {
            "statusCode": 201,
            "body": json.dumps({"success": True, "group": group}, default=str),
        }

    def remove_group(self, telegram_group_id: str) -> dict[str, Any]:
        """Remove (deactivate) a group."""
        try:
            group_id = int(telegram_group_id)
        except ValueError:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Invalid group ID"}),
            }

        success = self.group_repo.remove_group(group_id)
        if success:
            logger.info(f"Removed group: {group_id}")
            return {
                "statusCode": 200,
                "body": json.dumps({"success": True}),
            }
        else:
            return {
                "statusCode": 404,
                "body": json.dumps({"error": "Group not found"}),
            }

    # Logs

    def get_logs(
        self,
        level: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Get application logs."""
        logs, total = self.log_repo.get_logs(
            level=level,
            limit=min(limit, 500),  # Cap at 500
            offset=offset,
        )
        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "logs": logs,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                },
                default=str,
            ),
        }
