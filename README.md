# ClaudeGram

[English](README_en.md) | 繁體中文

基於 AWS Lambda + API Gateway 的 Telegram 聊天機器人，整合 Claude AI 提供智慧對話、網頁搜尋和網址摘要功能。

## 功能特色

- **智慧對話**: 使用 Claude AI 進行自然語言對話
- **對話上下文追蹤**: 透過 Telegram reply chain 維持對話脈絡
- **檔案分析**: 上傳圖片、PDF、Word、PowerPoint 進行內容分析和摘要
- **網頁搜尋**: 可搜尋網路獲取最新資訊
- **網址摘要**: 自動摘要分享的網頁內容（繁體中文），4 層內容提取 pipeline + Playwright fallback
- **用戶管理**: 只允許特定用戶或群組使用
- **管理介面**: Web-based 管理面板，可管理用戶、群組和查看日誌

### 支援的檔案類型

| 類型 | 格式 | 處理方式 |
|------|------|----------|
| 圖片 | JPG, PNG, GIF, WEBP | Claude Vision (base64) |
| PDF | .pdf | Claude 原生 PDF 支援 (base64) |
| Word | .docx | 文字擷取 (python-docx) |
| PowerPoint | .pptx | 文字擷取 (python-pptx) |

## 系統架構

```
┌──────────────┐     ┌─────────────────┐     ┌─────────────────────────────┐
│   Telegram   │────▶│   API Gateway   │────▶│      Lambda Functions       │
│   Bot API    │     │  /webhook       │     │  - telegram_handler         │
└──────────────┘     │  /admin/*       │     │  - admin_handler            │
                     └─────────────────┘     │  - summarizer_handler       │
┌──────────────┐            │                └─────────────────────────────┘
│    Admin     │────────────┘                              │
│   Browser    │                                           ▼
└──────────────┘                             ┌─────────────────────────────┐
                                             │      S3 (SQLite DB)         │
                                             └─────────────────────────────┘
```

### 網址摘要：4 層內容提取 Pipeline

使用純 heuristics 的 4 層 data source discovery pipeline，無需 LLM 判斷即可決定內容是否足夠，大幅減少 Playwright 調用：

```
HTTP GET (aiohttp) → 原始 HTML
         │
    Layer 1: 語意 HTML 提取（BeautifulSoup）
         │   - <article>, <main>, [role="main"] 等語意標籤
         │   - 移除 nav/footer/header/ads 等雜訊
         │   - 提取 metadata: og:tags, description, author
         │
    Layer 2: 嵌入式資料提取
         │   - __NEXT_DATA__ (Next.js SSR JSON)
         │   - __NUXT__ / __NUXT_DATA__ (Nuxt.js)
         │   - JSON-LD (application/ld+json)
         │
    Layer 3: 內容品質評分（純 heuristics，無 LLM）
         │   - 字數 / 段落結構 / 資料源信心 / Metadata 完整度
         │   - 負面訊號扣分 (loading..., template placeholders)
         │   → sufficient (≥40) / insufficient (15-39) / unprocessable (<15)
         │
    Layer 4: 決策路由
         ├─ sufficient → 直接送 Claude 摘要（~5s）
         ├─ insufficient + 可靠來源 → 直接摘要
         ├─ insufficient + 不可靠來源 → Playwright fallback
         └─ unprocessable → Playwright fallback 或明確告知用戶
```

| 場景 | 處理方式 | 預計耗時 |
|------|----------|----------|
| 有 `<article>` 的靜態網頁 | 直接摘要 | ~5s |
| Next.js / Nuxt.js SSR 網站 | 從 `__NEXT_DATA__` 提取後摘要 | ~5s |
| 有 JSON-LD 的新聞網站 | 從 structured data 提取後摘要 | ~5s |
| 真正的 SPA（無 SSR） | Playwright fallback | ~60-90s |
| Cloudflare 保護的網站 | Playwright fallback（HTTP 被擋） | ~60-90s |

## 技術棧

- **Runtime**: Python 3.11
- **Infrastructure as Code**: AWS CDK (Python)
- **Database**: SQLite on S3
- **AI**: Anthropic Claude API
- **Messaging**: Telegram Bot API
- **Browser Automation**: Playwright (Docker Lambda)

## 專案結構

```
claudegram/
├── cdk/                           # AWS CDK 基礎設施
│   ├── app.py                     # CDK 應用程式入口
│   ├── requirements.txt           # CDK 依賴
│   └── stacks/
│       └── bot_stack.py           # 主要 Stack 定義
├── src/
│   ├── common/                    # 共用模組
│   │   ├── config.py              # 環境變數管理
│   │   └── database.py            # S3-SQLite 管理器
│   ├── telegram_handler/          # Telegram webhook Lambda
│   │   ├── handler.py             # Lambda 入口點
│   │   ├── auth.py                # 用戶認證
│   │   ├── conversation.py        # 對話管理
│   │   ├── claude_agent.py        # Claude SDK 整合（含內容提取 pipeline）
│   │   ├── content_extractor.py   # 4 層 HTML 內容提取 pipeline
│   │   └── file_handler.py        # 檔案處理（下載、擷取文字）
│   ├── summarizer_handler/        # Playwright 摘要 Lambda (Docker)
│   │   ├── Dockerfile             # Lambda Container 定義
│   │   ├── handler.py             # Lambda 入口點
│   │   ├── extractor.py           # Playwright 網頁內容擷取
│   │   ├── summarizer.py          # Claude 摘要生成
│   │   └── requirements.txt       # Summarizer 依賴
│   └── admin_handler/             # 管理介面 Lambda
│       ├── handler.py             # Lambda 入口點
│       └── auth.py                # 管理員認證
├── requirements.txt               # Python 依賴
├── requirements-dev.txt           # 開發依賴
└── README.md
```

## 環境需求

- Python 3.11+
- Node.js 18+ (for AWS CDK)
- Docker (for Playwright Lambda)
- AWS CLI (已設定 credentials)
- AWS CDK CLI (`npm install -g aws-cdk`)

## 部署指南

### 1. Clone 專案

```bash
git clone <repository-url>
cd claude-telegram-bot
```

### 2. 建立 Telegram Bot

1. 在 Telegram 中找到 [@BotFather](https://t.me/BotFather)
2. 發送 `/newbot` 建立新 Bot
3. 記下 Bot Token（格式：`123456789:ABCdefGHIjklMNOpqrsTUVwxyz`）

### 3. 安裝依賴

```bash
# 建立虛擬環境
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# 安裝 Python 依賴
pip install -r requirements.txt

# 安裝 CDK 依賴
cd cdk
pip install -r requirements.txt
cd ..

# 安裝 Lambda Layer 依賴
mkdir -p .lambda-layer/python
pip install -r requirements.txt -t .lambda-layer/python \
    --platform manylinux2014_x86_64 \
    --only-binary=:all: \
    --python-version 3.11
```

### 4. 設定 AWS Credentials

確保 AWS CLI 已設定好 credentials：

```bash
aws configure --profile your-profile-name
# 或使用環境變數
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=ap-east-2
```

### 5. 部署 CDK Stack

```bash
cd cdk

# Bootstrap CDK（首次部署需要）
cdk bootstrap --profile your-profile-name

# 部署 Stack
cdk deploy --profile your-profile-name \
  -c telegram_bot_token='YOUR_TELEGRAM_BOT_TOKEN' \
  -c webhook_secret='YOUR_RANDOM_SECRET' \
  -c anthropic_api_key='YOUR_ANTHROPIC_API_KEY' \
  -c anthropic_base_url='https://api.anthropic.com' \
  -c anthropic_model='claude-sonnet-4-20250514' \
  -c admin_password='YOUR_ADMIN_PASSWORD'
```

#### 參數說明

| 參數 | 說明 | 範例 |
|------|------|------|
| `telegram_bot_token` | Telegram Bot Token | `123456789:ABCdef...` |
| `webhook_secret` | Webhook 驗證密鑰（隨機字串） | `openssl rand -hex 32` |
| `anthropic_api_key` | Anthropic API Key | `sk-ant-api03-...` |
| `anthropic_base_url` | Anthropic API Base URL（可選） | `https://api.anthropic.com` |
| `anthropic_model` | Claude 模型名稱 | `claude-sonnet-4-20250514` |
| `admin_password` | 管理介面密碼 | `your-secure-password` |

### 6. 設定 Telegram Webhook

部署完成後，會輸出 Webhook URL。使用以下指令設定：

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "<YOUR_WEBHOOK_URL>",
    "secret_token": "<YOUR_WEBHOOK_SECRET>"
  }'
```

範例：
```bash
curl -X POST "https://api.telegram.org/bot123456789:ABCdef.../setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://xxx.execute-api.ap-east-2.amazonaws.com/prod/webhook",
    "secret_token": "your-webhook-secret"
  }'
```

### 7. 新增允許的用戶

1. 獲取你的 Telegram User ID：
   - 在 Telegram 中找到 [@userinfobot](https://t.me/userinfobot)
   - 發送任意訊息，Bot 會回覆你的 User ID

2. 透過管理介面新增用戶：
   - 開啟 Admin URL（部署時輸出的 `AdminUrl`）
   - 登入管理介面
   - 在「用戶管理」頁面新增 User ID

或使用 AWS CLI 初始化資料庫：

```bash
# 下載 SQLite 檔案
aws s3 cp s3://YOUR_BUCKET_NAME/chatbot.db ./chatbot.db --profile your-profile-name

# 使用 sqlite3 新增用戶
sqlite3 chatbot.db "INSERT INTO allowed_users (telegram_user_id, display_name, added_by) VALUES (YOUR_USER_ID, 'Your Name', 'init');"

# 上傳回 S3
aws s3 cp ./chatbot.db s3://YOUR_BUCKET_NAME/chatbot.db --profile your-profile-name
```

## 使用說明

### Telegram Bot 使用

1. **開始對話**: 直接發送訊息給 Bot
2. **繼續對話**: 回覆 Bot 的訊息以維持上下文
3. **分享網址**: 發送包含 URL 的訊息，Bot 會自動摘要
4. **追問內容**: 回覆摘要訊息可以針對該網頁內容追問
5. **上傳檔案**: 傳送圖片、PDF、Word 或 PowerPoint 檔案
   - 圖片：Bot 會描述圖片內容
   - PDF/Word/PPT：Bot 會提供文件摘要
   - 可附加文字說明或問題（使用 caption）
   - 回覆檔案訊息可針對該檔案追問

### 管理介面

訪問 Admin URL 進入管理介面：

- **用戶管理**: 新增/刪除允許使用 Bot 的用戶
- **群組管理**: 新增/刪除允許使用 Bot 的群組
- **系統日誌**: 查看 Bot 運行日誌

## 資料庫結構

```sql
-- 允許的用戶
allowed_users (
    id, telegram_user_id, username, display_name,
    added_by, added_at, is_active
)

-- 允許的群組
allowed_groups (
    id, telegram_group_id, group_name,
    added_by, added_at, is_active
)

-- 對話 session
conversations (
    id, telegram_chat_id, root_message_id,
    created_at, updated_at, is_active
)

-- 對話訊息
messages (
    id, conversation_id, telegram_message_id, telegram_user_id,
    role, content, reply_to_message_id, created_at
)

-- 網址摘要快取
url_summaries (
    id, conversation_id, url, title,
    summary_zh_tw, raw_content, content_hash, created_at
)

-- 檔案附件
file_attachments (
    id, message_id, conversation_id, telegram_file_id,
    file_type, file_name, mime_type, file_size,
    base64_data, extracted_text, content_hash, created_at
)

-- 管理員 session
admin_sessions (
    id, session_token, created_at, expires_at, ip_address
)

-- 應用程式日誌
app_logs (
    id, level, source, message,
    telegram_user_id, metadata, created_at
)
```

## 故障排除

### 常見問題

#### 1. Bot 沒有回應

- 確認 Webhook 已正確設定
- 確認用戶已加入允許清單
- 檢查 CloudWatch Logs 中的錯誤訊息

```bash
# 檢查 Webhook 狀態
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
```

#### 2. "Unauthorized" 錯誤

- 確認 `webhook_secret` 與 Telegram 設定的一致
- 重新設定 Webhook

#### 3. Claude API 錯誤

- 確認 API Key 正確
- 確認 API Base URL 正確
- 如使用自訂端點，確認認證方式正確

#### 4. SQLite 語法錯誤

Lambda 環境的 SQLite 版本較舊，不支援某些新語法：
- 不支援 `RETURNING` 子句
- `ON CONFLICT ... DO UPDATE` 可能有限制

#### 5. 管理介面登入失敗

- 確認密碼正確
- 清除瀏覽器 Cookie 後重試
- 檢查是否超過登入次數限制（15 分鐘內最多 5 次）

### 查看日誌

```bash
# 查看 Telegram Handler 日誌
aws logs tail /aws/lambda/TelegramBotStack-TelegramHandler... \
  --profile your-profile-name --follow

# 查看 Admin Handler 日誌
aws logs tail /aws/lambda/TelegramBotStack-AdminHandler... \
  --profile your-profile-name --follow
```

## 更新部署

修改程式碼後重新部署：

```bash
cd cdk
cdk deploy --profile your-profile-name \
  -c telegram_bot_token='...' \
  -c webhook_secret='...' \
  -c anthropic_api_key='...' \
  -c admin_password='...'
```

## 清理資源

```bash
cd cdk
cdk destroy --profile your-profile-name
```

注意：S3 Bucket 設定為 `RETAIN`，不會自動刪除。如需刪除，請手動清空並刪除 Bucket。

## 安全建議

1. **使用強密碼**: Admin 密碼應使用強密碼
2. **定期更換 Token**: 定期更換 Webhook Secret 和 API Key
3. **限制用戶**: 只允許必要的用戶使用 Bot
4. **監控日誌**: 定期檢查系統日誌
5. **不要公開 Credentials**: 不要將任何 Token 或密碼提交到版本控制

## License

MIT License
