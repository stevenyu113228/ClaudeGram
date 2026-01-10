"""Lambda handler for URL summarization."""
import json
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for URL summarization.

    Args:
        event: Contains 'url' to summarize
        context: Lambda context

    Returns:
        Summary result or error
    """
    logger.info(f"Received event: {json.dumps(event)}")

    # Get URL from event
    url = event.get("url")
    if not url:
        return {
            "statusCode": 400,
            "errorMessage": "Missing 'url' parameter",
        }

    # Validate URL
    if not url.startswith(("http://", "https://")):
        return {
            "statusCode": 400,
            "errorMessage": "Invalid URL format",
        }

    try:
        # Import here to avoid issues if Playwright not available
        from extractor import extract_content
        from summarizer import summarize_content

        # Extract content
        logger.info(f"Extracting content from: {url}")
        extracted = extract_content(url)

        # Summarize content
        logger.info("Summarizing content")
        summary = summarize_content(
            content=extracted.content,
            title=extracted.title,
            url=url,
        )

        return {
            "statusCode": 200,
            "url": url,
            "title": extracted.title,
            "content_hash": extracted.content_hash,
            "summary_zh_tw": summary,
            "raw_content": extracted.content[:10000],  # Store truncated for follow-ups
        }

    except Exception as e:
        logger.error(f"Error summarizing URL: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "errorMessage": str(e),
        }


# For local testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        test_url = "https://example.com"

    result = lambda_handler({"url": test_url}, None)
    print(json.dumps(result, ensure_ascii=False, indent=2))
