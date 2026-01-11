"""Conversation context management for Telegram bot."""
import logging
import re
from dataclasses import dataclass
from typing import Any

from common.database import ConversationRepository, S3SQLiteManager, URLSummaryRepository

logger = logging.getLogger(__name__)

# URL regex pattern
URL_PATTERN = re.compile(
    r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*",
    re.IGNORECASE,
)


@dataclass
class ConversationContext:
    """Context for a conversation including history and metadata."""

    conversation_id: int
    messages: list[dict[str, Any]]
    urls_in_message: list[str]


class ConversationService:
    """Service for managing conversation context."""

    def __init__(self, db: S3SQLiteManager):
        self.conv_repo = ConversationRepository(db)
        self.url_repo = URLSummaryRepository(db)

    def get_context(
        self,
        telegram_chat_id: int,
        message_id: int,
        reply_to_message_id: int | None,
        user_message: str,
    ) -> ConversationContext:
        """
        Get or create conversation context based on reply chain.

        Args:
            telegram_chat_id: Telegram chat ID
            message_id: Current message ID
            reply_to_message_id: ID of message being replied to (if any)
            user_message: The user's message text

        Returns:
            ConversationContext with history and metadata
        """
        # Get or create conversation
        conversation_id, messages = self.conv_repo.get_or_create_conversation(
            telegram_chat_id=telegram_chat_id,
            message_id=message_id,
            reply_to_message_id=reply_to_message_id,
        )

        # Extract URLs from message
        urls = URL_PATTERN.findall(user_message)

        logger.info(
            f"Conversation {conversation_id}: {len(messages)} previous messages, "
            f"{len(urls)} URLs found"
        )

        return ConversationContext(
            conversation_id=conversation_id,
            messages=messages,
            urls_in_message=urls,
        )

    def add_user_message(
        self,
        conversation_id: int,
        telegram_message_id: int,
        telegram_user_id: int,
        content: str,
        reply_to_message_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a user message to the conversation and return the saved message."""
        return self.conv_repo.add_message(
            conversation_id=conversation_id,
            telegram_message_id=telegram_message_id,
            telegram_user_id=telegram_user_id,
            role="user",
            content=content,
            reply_to_message_id=reply_to_message_id,
        )

    def add_assistant_message(
        self,
        conversation_id: int,
        telegram_message_id: int,
        content: str,
    ) -> None:
        """Add an assistant message to the conversation."""
        self.conv_repo.add_message(
            conversation_id=conversation_id,
            telegram_message_id=telegram_message_id,
            telegram_user_id=0,  # Bot has no user ID
            role="assistant",
            content=content,
        )

    def save_url_summary(
        self,
        conversation_id: int,
        url: str,
        title: str | None,
        summary: str,
        raw_content: str | None = None,
        content_hash: str | None = None,
    ) -> None:
        """Save a URL summary for future reference."""
        self.url_repo.save_summary(
            conversation_id=conversation_id,
            url=url,
            title=title,
            summary_zh_tw=summary,
            raw_content=raw_content,
            content_hash=content_hash,
        )

    def get_url_summary(self, conversation_id: int, url: str) -> dict[str, Any] | None:
        """Get existing summary for a URL in conversation."""
        return self.url_repo.get_summary_by_url(conversation_id, url)


def build_claude_messages(
    conversation_history: list[dict[str, Any]],
    current_message: str,
    current_file: Any | None = None,
) -> list[dict]:
    """
    Build message list for Claude API, including file attachments.

    Args:
        conversation_history: Previous messages in conversation
        current_message: Current user message
        current_file: Optional ProcessedFile object for current message

    Returns:
        List of messages formatted for Claude API (may include multimodal content)
    """
    messages = []

    # Add conversation history (text only for now)
    for msg in conversation_history:
        messages.append({
            "role": msg["role"],
            "content": msg["content"],
        })

    # Add current message with optional file
    if current_file:
        content_blocks = _build_content_blocks(current_message, current_file)
        messages.append({
            "role": "user",
            "content": content_blocks,
        })
    else:
        messages.append({
            "role": "user",
            "content": current_message,
        })

    return messages


def _build_content_blocks(text: str, processed_file: Any) -> list[dict]:
    """
    Build Claude API content blocks for a message with file.

    Args:
        text: User's text message
        processed_file: ProcessedFile object

    Returns:
        List of content blocks for Claude API
    """
    # Import here to avoid circular imports
    from .file_handler import FileType

    blocks = []

    if processed_file.file_type == FileType.IMAGE:
        # Image block - Claude Vision
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": processed_file.mime_type,
                "data": processed_file.base64_data,
            }
        })

    elif processed_file.file_type == FileType.PDF:
        # Document block for PDF - Claude native support
        blocks.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": processed_file.base64_data,
            },
        })

    elif processed_file.file_type in (FileType.DOCX, FileType.PPTX):
        # For extracted text, prepend as context
        doc_type = "Word 文件" if processed_file.file_type == FileType.DOCX else "PowerPoint 簡報"
        file_context = (
            f"[{doc_type}: {processed_file.file_name}]\n\n"
            f"{processed_file.extracted_text}"
        )
        blocks.append({
            "type": "text",
            "text": file_context,
        })

    # Add user's text message
    if text and text.strip():
        blocks.append({
            "type": "text",
            "text": text,
        })
    else:
        # Default prompt for file without text
        if processed_file.file_type == FileType.IMAGE:
            blocks.append({
                "type": "text",
                "text": "請描述這張圖片的內容。",
            })
        else:
            blocks.append({
                "type": "text",
                "text": "請摘要這個檔案的內容。",
            })

    return blocks
