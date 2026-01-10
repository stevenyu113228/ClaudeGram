#!/usr/bin/env python3
"""Script to set up Telegram webhook."""
import argparse
import sys

import requests


def setup_webhook(bot_token: str, webhook_url: str, secret_token: str) -> bool:
    """
    Set up Telegram webhook.

    Args:
        bot_token: Telegram Bot API token
        webhook_url: URL for webhook (API Gateway endpoint)
        secret_token: Secret token for webhook verification

    Returns:
        True if successful, False otherwise
    """
    api_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"

    payload = {
        "url": webhook_url,
        "secret_token": secret_token,
        "allowed_updates": ["message"],  # Only receive message updates
    }

    print(f"Setting webhook to: {webhook_url}")

    response = requests.post(api_url, json=payload)
    result = response.json()

    if result.get("ok"):
        print("Webhook set successfully!")
        print(f"Response: {result}")
        return True
    else:
        print(f"Failed to set webhook: {result}")
        return False


def get_webhook_info(bot_token: str) -> dict:
    """Get current webhook info."""
    api_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    response = requests.get(api_url)
    return response.json()


def delete_webhook(bot_token: str) -> bool:
    """Delete current webhook."""
    api_url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    response = requests.post(api_url)
    result = response.json()

    if result.get("ok"):
        print("Webhook deleted successfully!")
        return True
    else:
        print(f"Failed to delete webhook: {result}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Manage Telegram Bot Webhook")
    parser.add_argument("--token", required=True, help="Telegram Bot Token")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Set webhook
    set_parser = subparsers.add_parser("set", help="Set webhook")
    set_parser.add_argument("--url", required=True, help="Webhook URL")
    set_parser.add_argument("--secret", required=True, help="Secret token")

    # Get webhook info
    subparsers.add_parser("info", help="Get webhook info")

    # Delete webhook
    subparsers.add_parser("delete", help="Delete webhook")

    args = parser.parse_args()

    if args.command == "set":
        success = setup_webhook(args.token, args.url, args.secret)
        sys.exit(0 if success else 1)
    elif args.command == "info":
        info = get_webhook_info(args.token)
        print("Webhook Info:")
        print(f"  URL: {info.get('result', {}).get('url', 'Not set')}")
        print(f"  Has custom certificate: {info.get('result', {}).get('has_custom_certificate', False)}")
        print(f"  Pending update count: {info.get('result', {}).get('pending_update_count', 0)}")
        if info.get("result", {}).get("last_error_message"):
            print(f"  Last error: {info['result']['last_error_message']}")
    elif args.command == "delete":
        success = delete_webhook(args.token)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
