"""Content summarization using Claude."""
import logging
import os
from typing import Optional

from anthropic import Anthropic

logger = logging.getLogger(__name__)


def get_anthropic_client() -> Anthropic:
    """Create Anthropic client from environment variables."""
    api_key = os.environ["ANTHROPIC_API_KEY"]
    base_url = os.environ.get("ANTHROPIC_BASE_URL")

    # Check if using TrendMicro RDSEC endpoint (uses Bearer auth)
    if base_url and "rdsec" in base_url:
        kwargs = {
            "api_key": "dummy",  # Required but not used
            "base_url": base_url,
            "default_headers": {
                "Authorization": f"Bearer {api_key}",
            },
        }
    else:
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url

    return Anthropic(**kwargs)


def summarize_content(
    content: str,
    title: str,
    url: str,
    model: Optional[str] = None,
) -> str:
    """
    Summarize content in Traditional Chinese using Claude.

    Args:
        content: The extracted web page content
        title: Page title
        url: Original URL
        model: Claude model to use

    Returns:
        Summary in Traditional Chinese
    """
    client = get_anthropic_client()
    model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")

    # Truncate content if too long
    max_content_length = 30000
    truncated_content = content[:max_content_length]
    if len(content) > max_content_length:
        truncated_content += "\n\n[內容已截斷...]"

    prompt = f"""請用繁體中文總結以下網頁內容。

標題: {title}
網址: {url}

內容:
{truncated_content}

請提供以下格式的摘要：

## 📋 簡短摘要
（2-3句話概述主要內容）

## 🔑 主要重點
（列出3-5個重點）

## 📊 關鍵資訊
（如有數據、日期、名稱等關鍵資訊，請列出）

注意：
- 使用繁體中文
- 保持客觀中立
- 如果內容是新聞，標註發布日期（如有）
- 如果是技術文章，保留重要的技術術語"""

    logger.info(f"Summarizing content with model: {model}")

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    summary = response.content[0].text
    logger.info(f"Generated summary: {len(summary)} characters")

    return summary
