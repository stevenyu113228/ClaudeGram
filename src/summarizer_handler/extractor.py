"""Content extraction from web pages using Playwright."""
import hashlib
import logging
import time
from dataclasses import dataclass

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    """Extracted content from a web page."""

    url: str
    title: str
    content: str
    content_hash: str


def extract_content(url: str, timeout_ms: int = 30000) -> ExtractedContent:
    """
    Extract main content from a URL using Playwright.

    Args:
        url: URL to extract content from
        timeout_ms: Timeout in milliseconds

    Returns:
        ExtractedContent with title, content, and hash
    """
    logger.info(f"Extracting content from: {url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-gpu",
                "--single-process",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--no-zygote",
            ],
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
        )

        page = context.new_page()

        try:
            # Navigate to page
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Wait for JavaScript to render content
            time.sleep(3)

            # Get title
            title = page.title() or "未知標題"

            # Extract main content using JavaScript
            content = page.evaluate(
                """
                () => {
                    // Remove unwanted elements
                    const removeSelectors = [
                        'script', 'style', 'nav', 'footer', 'header',
                        'aside', 'iframe', 'noscript', '.nav', '.footer',
                        '.header', '.sidebar', '.advertisement', '.ad',
                        '[role="navigation"]', '[role="banner"]',
                        '[role="contentinfo"]', '.cookie-banner',
                        '.popup', '.modal'
                    ];

                    removeSelectors.forEach(selector => {
                        document.querySelectorAll(selector).forEach(el => el.remove());
                    });

                    // Try to find main content area
                    const contentSelectors = [
                        'article',
                        'main',
                        '[role="main"]',
                        '.content',
                        '.post-content',
                        '.article-content',
                        '.entry-content',
                        '#content',
                        '#main',
                        '.main-content'
                    ];

                    for (const selector of contentSelectors) {
                        const element = document.querySelector(selector);
                        if (element && element.innerText.trim().length > 200) {
                            return element.innerText.trim();
                        }
                    }

                    // Fallback to body
                    return document.body.innerText.trim();
                }
            """
            )

            # Clean up content
            content = " ".join(content.split())  # Normalize whitespace

            # Limit content length
            max_length = 50000
            if len(content) > max_length:
                content = content[:max_length] + "..."

            # Generate content hash
            content_hash = hashlib.md5(content.encode()).hexdigest()

            logger.info(
                f"Extracted {len(content)} characters, hash: {content_hash[:8]}"
            )

            return ExtractedContent(
                url=url,
                title=title,
                content=content,
                content_hash=content_hash,
            )

        except PlaywrightTimeout:
            logger.error(f"Timeout extracting content from {url}")
            raise
        except Exception as e:
            logger.error(f"Error extracting content: {e}")
            raise
        finally:
            context.close()
            browser.close()
