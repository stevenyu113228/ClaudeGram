"""Claude Agent SDK integration for Telegram bot."""
import json
import logging
import os
from typing import Any

import aiohttp
import boto3
from anthropic import Anthropic

from common.database import S3SQLiteManager, URLSummaryRepository

logger = logging.getLogger(__name__)

# System prompt for the bot
SYSTEM_PROMPT = """你是一個友善且有幫助的 Telegram 聊天機器人助手。

你的主要功能：
1. 回答用戶的問題和進行對話
2. 當用戶分享網址時，自動摘要網頁內容（使用繁體中文）
3. 當需要最新資訊時，進行網頁搜尋
4. 分析用戶上傳的檔案（圖片、PDF、Word、PowerPoint）
5. 回答關於已上傳檔案的追問

回覆規則：
- 始終使用繁體中文回覆
- 保持回覆簡潔但完整
- 當摘要網頁或文件時，提供：簡短摘要、主要重點、關鍵資訊
- 支援用戶對內容的追問
- 當分析圖片時，詳細描述所見內容並回答相關問題
- 當分析 PDF 或文件時，提取並整理重要資訊

可用工具：
- web_search: 搜尋網頁獲取最新資訊
- summarize_url: 獲取並摘要網頁內容"""


class ClaudeAgentService:
    """Service for interacting with Claude Agent."""

    def __init__(
        self,
        config,
        db: S3SQLiteManager,
        conversation_id: int,
    ):
        self.config = config
        self.db = db
        self.conversation_id = conversation_id
        self.url_repo = URLSummaryRepository(db)

        # Initialize Anthropic client
        # Check if using custom endpoint that requires Bearer auth
        if config.anthropic_base_url and "rdsec" in config.anthropic_base_url:
            # TrendMicro endpoint uses Authorization: Bearer instead of x-api-key
            client_kwargs = {
                "api_key": "dummy",  # Required but not used
                "base_url": config.anthropic_base_url,
                "default_headers": {
                    "Authorization": f"Bearer {config.anthropic_api_key}",
                },
            }
        else:
            client_kwargs = {"api_key": config.anthropic_api_key}
            if config.anthropic_base_url:
                client_kwargs["base_url"] = config.anthropic_base_url
        self.client = Anthropic(**client_kwargs)

        # Lambda client for invoking summarizer
        self._lambda_client = None

    @property
    def lambda_client(self):
        """Lazy load Lambda client."""
        if self._lambda_client is None:
            self._lambda_client = boto3.client("lambda")
        return self._lambda_client

    def _get_tools(self) -> list[dict]:
        """Get tool definitions for Claude."""
        return [
            {
                "name": "web_search",
                "description": "搜尋網頁獲取最新資訊。用於回答需要最新資料的問題。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "搜尋查詢字串",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "summarize_url",
                "description": "獲取網頁內容並生成繁體中文摘要。當用戶分享網址時使用。",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "要摘要的網頁 URL",
                        },
                    },
                    "required": ["url"],
                },
            },
        ]

    async def _execute_web_search(self, query: str) -> str:
        """Execute web search using DuckDuckGo."""
        logger.info(f"Executing web search: {query}")

        try:
            # Use DuckDuckGo Instant Answer API (free, no API key required)
            async with aiohttp.ClientSession() as session:
                params = {
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                }
                async with session.get(
                    "https://api.duckduckgo.com/",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    data = await response.json()

            results = []

            # Abstract (main answer)
            if data.get("Abstract"):
                results.append(f"摘要: {data['Abstract']}")
                if data.get("AbstractSource"):
                    results.append(f"來源: {data['AbstractSource']}")

            # Related topics
            related = data.get("RelatedTopics", [])[:5]
            if related:
                results.append("\n相關主題:")
                for topic in related:
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append(f"- {topic['Text']}")

            # If no results from DDG, return a message
            if not results:
                # Fallback: suggest the user to search manually
                return f"未找到「{query}」的直接搜尋結果。建議直接在搜尋引擎中查詢以獲取更多資訊。"

            return "\n".join(results)

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return f"搜尋時發生錯誤: {str(e)}"

    async def _execute_summarize_url(self, url: str) -> str:
        """Execute URL summarization."""
        logger.info(f"Summarizing URL: {url}")

        # Check if we have a cached summary
        existing = self.url_repo.get_summary_by_url(self.conversation_id, url)
        if existing:
            logger.info("Using cached summary")
            return existing["summary_zh_tw"]

        # Check if summarizer Lambda is configured
        summarizer_function = self.config.summarizer_function_name
        if not summarizer_function:
            # Fallback: simple fetch and summarize
            return await self._simple_summarize(url)

        try:
            # Invoke summarizer Lambda
            response = self.lambda_client.invoke(
                FunctionName=summarizer_function,
                InvocationType="RequestResponse",
                Payload=json.dumps({"url": url}),
            )

            result = json.loads(response["Payload"].read())

            if "errorMessage" in result:
                logger.error(f"Summarizer error: {result['errorMessage']}")
                return f"無法摘要此網頁: {result['errorMessage']}"

            summary = result.get("summary_zh_tw", "無法生成摘要")

            # Cache the summary
            self.url_repo.save_summary(
                conversation_id=self.conversation_id,
                url=url,
                title=result.get("title"),
                summary_zh_tw=summary,
                raw_content=result.get("raw_content"),
                content_hash=result.get("content_hash"),
            )

            return summary

        except Exception as e:
            logger.error(f"Summarizer Lambda invocation failed: {e}")
            return await self._simple_summarize(url)

    async def _simple_summarize(self, url: str) -> str:
        """Simple URL summarization without Playwright."""
        try:
            async with aiohttp.ClientSession() as session:
                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; TelegramBot/1.0)"
                }
                async with session.get(
                    url,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status != 200:
                        return f"無法獲取網頁 (HTTP {response.status})"

                    html = await response.text()

            # Extract text content (simple approach)
            import re

            # Remove script and style tags
            html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
            html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)
            # Remove HTML tags
            text = re.sub(r"<[^>]+>", " ", html)
            # Clean up whitespace
            text = re.sub(r"\s+", " ", text).strip()

            # Extract title
            title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else "未知標題"

            # Truncate content
            content = text[:10000]

            # Use Claude to summarize
            summary_response = self.client.messages.create(
                model=self.config.anthropic_model,
                max_tokens=1500,
                messages=[
                    {
                        "role": "user",
                        "content": f"""請用繁體中文總結以下網頁內容。

標題: {title}
網址: {url}

內容:
{content}

請提供:
1. 簡短摘要 (2-3句)
2. 主要重點 (3-5點)
3. 關鍵資訊或數據 (如有)""",
                    }
                ],
            )

            summary = summary_response.content[0].text

            # Cache the summary
            self.url_repo.save_summary(
                conversation_id=self.conversation_id,
                url=url,
                title=title,
                summary_zh_tw=summary,
                raw_content=content[:5000],
            )

            return summary

        except Exception as e:
            logger.error(f"Simple summarize failed: {e}")
            return f"無法摘要此網頁: {str(e)}"

    async def _handle_tool_use(
        self, tool_name: str, tool_input: dict
    ) -> str:
        """Handle tool execution."""
        if tool_name == "web_search":
            return await self._execute_web_search(tool_input["query"])
        elif tool_name == "summarize_url":
            return await self._execute_summarize_url(tool_input["url"])
        else:
            return f"未知工具: {tool_name}"

    async def process_message(
        self,
        messages: list[dict[str, str]],
        urls: list[str] | None = None,
    ) -> str:
        """
        Process a message with Claude Agent.

        Args:
            messages: Conversation messages for Claude
            urls: URLs found in the current message (for auto-summarization)

        Returns:
            Assistant response text
        """
        logger.info(f"Processing message with {len(messages)} messages in context")

        # If URLs are present and it's a simple URL share, auto-summarize
        if urls and len(messages) == 1:
            user_text = messages[0]["content"].strip()
            # Check if message is primarily a URL
            if user_text.startswith("http") or len(user_text) < 100:
                # Add instruction to summarize
                messages[0]["content"] = (
                    f"請使用 summarize_url 工具摘要以下網頁: {urls[0]}"
                )

        # Initial API call
        response = self.client.messages.create(
            model=self.config.anthropic_model,
            max_tokens=2000,
            system=SYSTEM_PROMPT,
            tools=self._get_tools(),
            messages=messages,
        )

        # Handle tool use loop
        while response.stop_reason == "tool_use":
            # Find tool use blocks
            tool_use_blocks = [
                block for block in response.content if block.type == "tool_use"
            ]

            if not tool_use_blocks:
                break

            # Process each tool use
            tool_results = []
            for tool_use in tool_use_blocks:
                logger.info(f"Tool use: {tool_use.name}")
                result = await self._handle_tool_use(tool_use.name, tool_use.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            # Continue conversation with tool results
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]

            response = self.client.messages.create(
                model=self.config.anthropic_model,
                max_tokens=2000,
                system=SYSTEM_PROMPT,
                tools=self._get_tools(),
                messages=messages,
            )

        # Extract text response
        text_blocks = [block for block in response.content if block.type == "text"]
        if text_blocks:
            return text_blocks[0].text

        return "抱歉，我無法生成回覆。"
