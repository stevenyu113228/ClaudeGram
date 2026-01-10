# ClaudeGram

[繁體中文](README.md) | English

A Telegram chatbot built on AWS Lambda + API Gateway, integrated with Claude AI for intelligent conversations, web search, and URL summarization.

## Features

- **Intelligent Conversations**: Natural language dialogue powered by Claude AI
- **Context Tracking**: Maintains conversation context through Telegram reply chains
- **Web Search**: Search the web for up-to-date information
- **URL Summarization**: Automatically summarizes shared web pages (Traditional Chinese)
- **User Management**: Restrict bot usage to specific users or groups
- **Admin Panel**: Web-based management interface for users, groups, and logs

## Architecture

```
┌──────────────┐     ┌─────────────────┐     ┌─────────────────────────────┐
│   Telegram   │────▶│   API Gateway   │────▶│      Lambda Functions       │
│   Bot API    │     │  /webhook       │     │  - telegram_handler         │
└──────────────┘     │  /admin/*       │     │  - admin_handler            │
                     └─────────────────┘     └─────────────────────────────┘
┌──────────────┐            │                              │
│    Admin     │────────────┘                              ▼
│   Browser    │                             ┌─────────────────────────────┐
└──────────────┘                             │      S3 (SQLite DB)         │
                                             └─────────────────────────────┘
```

## Tech Stack

- **Runtime**: Python 3.11
- **Infrastructure as Code**: AWS CDK (Python)
- **Database**: SQLite on S3
- **AI**: Anthropic Claude API
- **Messaging**: Telegram Bot API

## Project Structure

```
claudegram/
├── cdk/                           # AWS CDK Infrastructure
│   ├── app.py                     # CDK application entry point
│   ├── requirements.txt           # CDK dependencies
│   └── stacks/
│       └── bot_stack.py           # Main stack definition
├── src/
│   ├── common/                    # Shared modules
│   │   ├── config.py              # Environment variable management
│   │   └── database.py            # S3-SQLite manager
│   ├── telegram_handler/          # Telegram webhook Lambda
│   │   ├── handler.py             # Lambda entry point
│   │   ├── auth.py                # User authentication
│   │   ├── conversation.py        # Conversation management
│   │   └── claude_agent.py        # Claude SDK integration
│   └── admin_handler/             # Admin panel Lambda
│       ├── handler.py             # Lambda entry point
│       └── auth.py                # Admin authentication
├── requirements.txt               # Python dependencies
├── requirements-dev.txt           # Development dependencies
└── README.md
```

## Prerequisites

- Python 3.11+
- Node.js 18+ (for AWS CDK)
- AWS CLI (with configured credentials)
- AWS CDK CLI (`npm install -g aws-cdk`)

## Deployment Guide

### 1. Clone the Repository

```bash
git clone <repository-url>
cd claude-telegram-bot
```

### 2. Create a Telegram Bot

1. Find [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` to create a new bot
3. Save the Bot Token (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### 3. Install Dependencies

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install Python dependencies
pip install -r requirements.txt

# Install CDK dependencies
cd cdk
pip install -r requirements.txt
cd ..

# Install Lambda Layer dependencies
mkdir -p .lambda-layer/python
pip install -r requirements.txt -t .lambda-layer/python \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --python-version 3.11
```

### 4. Configure AWS Credentials

Ensure AWS CLI is configured with credentials:

```bash
aws configure --profile your-profile-name
# Or use environment variables
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=ap-east-2
```

### 5. Deploy CDK Stack

```bash
cd cdk

# Bootstrap CDK (required for first deployment)
cdk bootstrap --profile your-profile-name

# Deploy stack
cdk deploy --profile your-profile-name \
  -c telegram_bot_token='YOUR_TELEGRAM_BOT_TOKEN' \
  -c webhook_secret='YOUR_RANDOM_SECRET' \
  -c anthropic_api_key='YOUR_ANTHROPIC_API_KEY' \
  -c anthropic_base_url='https://api.anthropic.com' \
  -c anthropic_model='claude-sonnet-4-20250514' \
  -c admin_password='YOUR_ADMIN_PASSWORD'
```

#### Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `telegram_bot_token` | Telegram Bot Token | `123456789:ABCdef...` |
| `webhook_secret` | Webhook verification secret (random string) | `openssl rand -hex 32` |
| `anthropic_api_key` | Anthropic API Key | `sk-ant-api03-...` |
| `anthropic_base_url` | Anthropic API Base URL (optional) | `https://api.anthropic.com` |
| `anthropic_model` | Claude model name | `claude-sonnet-4-20250514` |
| `admin_password` | Admin panel password | `your-secure-password` |

### 6. Configure Telegram Webhook

After deployment, you'll receive the Webhook URL. Configure it using:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "<YOUR_WEBHOOK_URL>",
    "secret_token": "<YOUR_WEBHOOK_SECRET>"
  }'
```

Example:
```bash
curl -X POST "https://api.telegram.org/bot123456789:ABCdef.../setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://xxx.execute-api.ap-east-2.amazonaws.com/prod/webhook",
    "secret_token": "your-webhook-secret"
  }'
```

### 7. Add Allowed Users

1. Get your Telegram User ID:
   - Find [@userinfobot](https://t.me/userinfobot) on Telegram
   - Send any message, the bot will reply with your User ID

2. Add user via admin panel:
   - Open Admin URL (from deployment output `AdminUrl`)
   - Login to admin panel
   - Add User ID in "User Management" page

Or initialize database via AWS CLI:

```bash
# Download SQLite file
aws s3 cp s3://YOUR_BUCKET_NAME/chatbot.db ./chatbot.db --profile your-profile-name

# Add user with sqlite3
sqlite3 chatbot.db "INSERT INTO allowed_users (telegram_user_id, display_name, added_by) VALUES (YOUR_USER_ID, 'Your Name', 'init');"

# Upload back to S3
aws s3 cp ./chatbot.db s3://YOUR_BUCKET_NAME/chatbot.db --profile your-profile-name
```

## Usage

### Telegram Bot

1. **Start a conversation**: Send a message directly to the bot
2. **Continue conversation**: Reply to the bot's message to maintain context
3. **Share URLs**: Send a message containing a URL, the bot will auto-summarize
4. **Follow-up questions**: Reply to summary messages to ask about the content

### Admin Panel

Access the Admin URL to enter the management interface:

- **User Management**: Add/remove users allowed to use the bot
- **Group Management**: Add/remove groups allowed to use the bot
- **System Logs**: View bot operation logs

## Database Schema

```sql
-- Allowed users
allowed_users (
    id, telegram_user_id, username, display_name,
    added_by, added_at, is_active
)

-- Allowed groups
allowed_groups (
    id, telegram_group_id, group_name,
    added_by, added_at, is_active
)

-- Conversation sessions
conversations (
    id, telegram_chat_id, root_message_id,
    created_at, updated_at, is_active
)

-- Conversation messages
messages (
    id, conversation_id, telegram_message_id, telegram_user_id,
    role, content, reply_to_message_id, created_at
)

-- URL summary cache
url_summaries (
    id, conversation_id, url, title,
    summary_zh_tw, raw_content, content_hash, created_at
)

-- Admin sessions
admin_sessions (
    id, session_token, created_at, expires_at, ip_address
)

-- Application logs
app_logs (
    id, level, source, message,
    telegram_user_id, metadata, created_at
)
```

## Troubleshooting

### Common Issues

#### 1. Bot not responding

- Verify webhook is correctly configured
- Verify user is in the allowed list
- Check CloudWatch Logs for error messages

```bash
# Check webhook status
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

#### 2. "Unauthorized" error

- Verify `webhook_secret` matches the Telegram configuration
- Reconfigure the webhook

#### 3. Claude API errors

- Verify API Key is correct
- Verify API Base URL is correct
- If using custom endpoint, verify authentication method is correct

#### 4. SQLite syntax errors

Lambda environment uses an older SQLite version with limitations:
- `RETURNING` clause not supported
- `ON CONFLICT ... DO UPDATE` may have restrictions

#### 5. Admin panel login failed

- Clear browser cookies and retry
- Check if login attempt limit exceeded (max 5 attempts per 15 minutes)
- Verify password is correct

### View Logs

```bash
# View Telegram Handler logs
aws logs tail /aws/lambda/TelegramBotStack-TelegramHandler... \
  --profile your-profile-name --follow

# View Admin Handler logs
aws logs tail /aws/lambda/TelegramBotStack-AdminHandler... \
  --profile your-profile-name --follow
```

## Updating Deployment

After modifying code, redeploy:

```bash
cd cdk
cdk deploy --profile your-profile-name \
  -c telegram_bot_token='...' \
  -c webhook_secret='...' \
  -c anthropic_api_key='...' \
  -c admin_password='...'
```

## Cleanup Resources

```bash
cd cdk
cdk destroy --profile your-profile-name
```

Note: S3 Bucket is set to `RETAIN` and won't be automatically deleted. Manually empty and delete the bucket if needed.

## Security Recommendations

1. **Use strong passwords**: Admin password should be strong
2. **Rotate tokens regularly**: Periodically rotate Webhook Secret and API Key
3. **Limit users**: Only allow necessary users to use the bot
4. **Monitor logs**: Regularly check system logs
5. **Never expose credentials**: Never commit tokens or passwords to version control

## License

MIT License
