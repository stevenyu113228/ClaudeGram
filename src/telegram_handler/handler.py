"""Lambda handler for Telegram webhook."""
import json
import logging
import os
import sys

# Add src to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import get_config
from common.database import LogRepository, S3SQLiteManager

from .auth import AuthorizationService, verify_webhook_token
from .claude_agent import ClaudeAgentService
from .conversation import ConversationService, build_claude_messages

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global instances (reused across Lambda invocations)
_db: S3SQLiteManager | None = None
_config = None


def get_db() -> S3SQLiteManager:
    """Get or create database instance."""
    global _db
    if _db is None:
        config = get_config()
        _db = S3SQLiteManager(
            bucket=config.database_bucket,
            key=config.database_key,
        )
    return _db


async def send_telegram_message(
    bot_token: str,
    chat_id: int,
    text: str,
    reply_to_message_id: int | None = None,
) -> dict | None:
    """Send a message via Telegram Bot API."""
    import aiohttp

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                result = await response.json()
                if not result.get("ok"):
                    logger.error(f"Telegram API error: {result}")
                    # Retry without markdown if parsing failed
                    if "can't parse" in str(result.get("description", "")).lower():
                        payload["parse_mode"] = None
                        async with session.post(url, json=payload) as retry_response:
                            result = await retry_response.json()
                return result
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None


async def send_typing_action(bot_token: str, chat_id: int) -> None:
    """Send typing indicator to show bot is processing."""
    import aiohttp

    url = f"https://api.telegram.org/bot{bot_token}/sendChatAction"
    payload = {
        "chat_id": chat_id,
        "action": "typing",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                await response.json()
    except Exception as e:
        logger.warning(f"Failed to send typing action: {e}")


async def process_message(
    update: dict,
    config,
    db: S3SQLiteManager,
) -> dict:
    """Process an incoming Telegram message."""
    message = update.get("message", {})
    chat = message.get("chat", {})
    user = message.get("from", {})
    text = message.get("text", "")

    chat_id = chat.get("id")
    chat_type = chat.get("type", "private")
    user_id = user.get("id")
    message_id = message.get("message_id")
    reply_to = message.get("reply_to_message", {})
    reply_to_message_id = reply_to.get("message_id") if reply_to else None

    logger.info(
        f"Processing message from user {user_id} in chat {chat_id} ({chat_type})"
    )

    # Check authorization
    auth_service = AuthorizationService(db)
    if not auth_service.is_authorized(user_id, chat_id, chat_type):
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        # Optionally send a message to unauthorized users
        # await send_telegram_message(
        #     config.telegram_bot_token,
        #     chat_id,
        #     "抱歉，您沒有權限使用此機器人。",
        #     message_id,
        # )
        return {"statusCode": 200, "body": "Unauthorized user"}

    # Skip empty messages
    if not text.strip():
        return {"statusCode": 200, "body": "Empty message"}

    # Send typing indicator
    await send_typing_action(config.telegram_bot_token, chat_id)

    # Get conversation context
    conv_service = ConversationService(db)
    context = conv_service.get_context(
        telegram_chat_id=chat_id,
        message_id=message_id,
        reply_to_message_id=reply_to_message_id,
        user_message=text,
    )

    # Save user message
    conv_service.add_user_message(
        conversation_id=context.conversation_id,
        telegram_message_id=message_id,
        telegram_user_id=user_id,
        content=text,
        reply_to_message_id=reply_to_message_id,
    )

    # Build messages for Claude
    claude_messages = build_claude_messages(
        conversation_history=context.messages,
        current_message=text,
    )

    # Process with Claude Agent
    agent_service = ClaudeAgentService(
        config=config,
        db=db,
        conversation_id=context.conversation_id,
    )

    try:
        response_text = await agent_service.process_message(
            messages=claude_messages,
            urls=context.urls_in_message,
        )
    except Exception as e:
        logger.error(f"Claude Agent error: {e}")
        response_text = "抱歉，處理您的訊息時發生錯誤。請稍後再試。"

    # Send response
    result = await send_telegram_message(
        config.telegram_bot_token,
        chat_id,
        response_text,
        message_id,
    )

    # Save assistant message
    if result and result.get("ok"):
        response_message_id = result.get("result", {}).get("message_id")
        if response_message_id:
            conv_service.add_assistant_message(
                conversation_id=context.conversation_id,
                telegram_message_id=response_message_id,
                content=response_text,
            )

    return {"statusCode": 200, "body": "OK"}


def lambda_handler(event: dict, context) -> dict:
    """
    AWS Lambda handler for Telegram webhook.

    Args:
        event: API Gateway event
        context: Lambda context

    Returns:
        API Gateway response
    """
    import asyncio

    logger.info(f"Received event: {json.dumps(event)[:500]}...")

    try:
        config = get_config()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Configuration error"}),
        }

    # Verify webhook token
    headers = event.get("headers", {})
    # Headers can be case-insensitive
    webhook_token = (
        headers.get("x-telegram-bot-api-secret-token")
        or headers.get("X-Telegram-Bot-Api-Secret-Token")
    )

    if not verify_webhook_token(webhook_token, config.webhook_secret):
        logger.warning("Invalid webhook token")
        return {
            "statusCode": 401,
            "body": json.dumps({"error": "Unauthorized"}),
        }

    # Parse body
    try:
        body = event.get("body", "{}")
        if isinstance(body, str):
            update = json.loads(body)
        else:
            update = body
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse body: {e}")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "Invalid JSON"}),
        }

    # Only handle message updates for now
    if "message" not in update:
        logger.info("Ignoring non-message update")
        return {"statusCode": 200, "body": "OK"}

    # Process the message
    db = get_db()

    # Log the request
    try:
        log_repo = LogRepository(db)
        log_repo.add_log(
            level="INFO",
            source="telegram_handler",
            message=f"Received message update",
            telegram_user_id=update.get("message", {}).get("from", {}).get("id"),
            telegram_chat_id=update.get("message", {}).get("chat", {}).get("id"),
            metadata=json.dumps({"update_id": update.get("update_id")}),
        )
    except Exception as e:
        logger.warning(f"Failed to log request: {e}")

    # Run async handler
    try:
        result = asyncio.get_event_loop().run_until_complete(
            process_message(update, config, db)
        )
        return result
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)

        # Log error
        try:
            log_repo = LogRepository(db)
            log_repo.add_log(
                level="ERROR",
                source="telegram_handler",
                message=str(e),
                telegram_user_id=update.get("message", {}).get("from", {}).get("id"),
                telegram_chat_id=update.get("message", {}).get("chat", {}).get("id"),
            )
        except Exception:
            pass

        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"}),
        }
