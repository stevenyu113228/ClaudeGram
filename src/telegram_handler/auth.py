"""Authorization module for Telegram bot."""
import logging

from common.database import GroupRepository, S3SQLiteManager, UserRepository

logger = logging.getLogger(__name__)


class AuthorizationService:
    """Service for checking user and group authorization."""

    def __init__(self, db: S3SQLiteManager):
        self.user_repo = UserRepository(db)
        self.group_repo = GroupRepository(db)

    def is_authorized(
        self,
        telegram_user_id: int,
        telegram_chat_id: int,
        chat_type: str,
    ) -> bool:
        """
        Check if a user/group is authorized to use the bot.

        Args:
            telegram_user_id: User's Telegram ID
            telegram_chat_id: Chat's Telegram ID (same as user_id for private chats)
            chat_type: Type of chat ('private', 'group', 'supergroup', 'channel')

        Returns:
            True if authorized, False otherwise
        """
        # Check if user is allowed
        if self.user_repo.is_user_allowed(telegram_user_id):
            logger.info(f"User {telegram_user_id} authorized via user allowlist")
            return True

        # For group chats, also check if the group is allowed
        if chat_type in ("group", "supergroup"):
            if self.group_repo.is_group_allowed(telegram_chat_id):
                logger.info(
                    f"User {telegram_user_id} authorized via group {telegram_chat_id} allowlist"
                )
                return True

        logger.warning(
            f"User {telegram_user_id} in chat {telegram_chat_id} ({chat_type}) not authorized"
        )
        return False


def verify_webhook_token(received_token: str | None, expected_token: str) -> bool:
    """
    Verify the Telegram webhook secret token.

    Args:
        received_token: Token from X-Telegram-Bot-Api-Secret-Token header
        expected_token: Expected token from configuration

    Returns:
        True if tokens match, False otherwise
    """
    if not received_token:
        logger.warning("No webhook token provided in request")
        return False

    is_valid = received_token == expected_token
    if not is_valid:
        logger.warning("Invalid webhook token received")

    return is_valid
