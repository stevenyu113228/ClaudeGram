"""Content extraction pipeline for URL summarization.

4-layer data source discovery pipeline that extracts structured content
from raw HTML, eliminating the need for LLM-based SPA detection and
reducing Playwright usage by 80%+.

Layers:
    1. Semantic HTML extraction (BeautifulSoup)
    2. Embedded data extraction (Next.js, Nuxt.js, JSON-LD)
    3. Content quality scoring (pure heuristics)
    4. Result assembly or graceful degradation
"""

import json
import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class ExtractedMetadata:
    """Metadata extracted from HTML meta tags and OG tags."""

    title: str = ""
    description: str = ""
    author: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    og_site_name: str = ""
    published_time: str = ""


@dataclass
class ExtractedContent:
    """Result of the content extraction pipeline."""

    text: str = ""
    title: str = ""
    metadata: ExtractedMetadata = field(default_factory=ExtractedMetadata)
    sources: list[str] = field(default_factory=list)
    quality_score: int = 0
    decision: str = "unprocessable"  # sufficient / insufficient / unprocessable
    decision_reason: str = ""


# --- Layer 1: Semantic HTML Extraction ---

_NOISE_TAGS = {"nav", "footer", "header", "aside", "script", "style", "noscript", "iframe"}
_NOISE_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
_NOISE_CLASSES = re.compile(
    r"(sidebar|menu|nav|footer|header|ads?|advert|banner|cookie|popup|modal|comment|share|social|related|recommend)",
    re.IGNORECASE,
)


def _extract_semantic_content(soup: BeautifulSoup) -> tuple[str, str]:
    """Layer 1: Extract main content using semantic HTML tags.

    Looks for <article>, <main>, [role="main"], and similar semantic
    containers. Falls back to <body> with noise removal.

    Returns:
        Tuple of (extracted_text, source_label)
    """
    # Try semantic containers in priority order
    candidates = [
        (soup.find("article"), "semantic:article"),
        (soup.find("main"), "semantic:main"),
        (soup.find(attrs={"role": "main"}), "semantic:role-main"),
        (soup.find(attrs={"id": re.compile(r"^(content|article|post|entry|story)", re.I)}), "semantic:id-match"),
        (soup.find(attrs={"class": re.compile(r"(article|post|entry|story|content)[-_]?(body|text|content)?", re.I)}), "semantic:class-match"),
    ]

    for element, source in candidates:
        if element is None:
            continue
        # Remove noise elements within the container
        for noise in element.find_all(_NOISE_TAGS):
            noise.decompose()
        for noise in element.find_all(attrs={"role": lambda v: v and v.lower() in _NOISE_ROLES}):
            noise.decompose()
        for noise in element.find_all(attrs={"class": _NOISE_CLASSES}):
            noise.decompose()

        text = element.get_text(separator="\n", strip=True)
        if len(text) >= 100:
            return text, source

    # Fallback: use body with noise removal
    body = soup.find("body")
    if body:
        body_copy = BeautifulSoup(str(body), "html.parser")
        for noise in body_copy.find_all(_NOISE_TAGS):
            noise.decompose()
        for noise in body_copy.find_all(attrs={"role": lambda v: v and v.lower() in _NOISE_ROLES}):
            noise.decompose()
        for noise in body_copy.find_all(attrs={"class": _NOISE_CLASSES}):
            noise.decompose()
        text = body_copy.get_text(separator="\n", strip=True)
        if len(text) >= 50:
            return text, "fallback:body"

    return "", "none"


# --- Layer 2: Embedded Data Extraction ---


def _deep_extract_text(obj: object, max_depth: int = 5) -> str:
    """Recursively extract text content from nested JSON structures.

    Walks dicts and lists, collecting string values that look like
    meaningful content (length >= 20 chars, not URLs).

    Args:
        obj: JSON-parsed object (dict, list, or primitive)
        max_depth: Maximum recursion depth to prevent stack overflow
    """
    if max_depth <= 0:
        return ""

    texts = []
    if isinstance(obj, str):
        # Only collect strings that look like content
        if len(obj) >= 20 and not obj.startswith(("http://", "https://", "data:", "/")):
            texts.append(obj)
    elif isinstance(obj, dict):
        # Prioritize known content keys
        for key in ("body", "content", "text", "description", "articleBody",
                     "abstract", "summary", "excerpt"):
            if key in obj and isinstance(obj[key], str) and len(obj[key]) >= 20:
                texts.append(obj[key])
        # Then recurse into all values
        for value in obj.values():
            texts.append(_deep_extract_text(value, max_depth - 1))
    elif isinstance(obj, list):
        for item in obj:
            texts.append(_deep_extract_text(item, max_depth - 1))

    return "\n".join(t for t in texts if t)


def _extract_next_data(soup: BeautifulSoup) -> tuple[str, str]:
    """Layer 2: Extract content from Next.js __NEXT_DATA__ script tag.

    Returns:
        Tuple of (extracted_text, source_label) or ("", "") if not found
    """
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return "", ""

    try:
        data = json.loads(script.string)
        page_props = data.get("props", {}).get("pageProps", {})
        text = _deep_extract_text(page_props)
        if len(text) >= 100:
            return text, "next_data"
    except (json.JSONDecodeError, AttributeError) as e:
        logger.debug(f"Failed to parse __NEXT_DATA__: {e}")

    return "", ""


def _extract_nuxt_data(soup: BeautifulSoup) -> tuple[str, str]:
    """Layer 2: Extract content from Nuxt.js embedded data.

    Handles both __NUXT__ (Nuxt 2) and __NUXT_DATA__ (Nuxt 3) formats.

    Returns:
        Tuple of (extracted_text, source_label) or ("", "") if not found
    """
    # Nuxt 3: look for script with id="__NUXT_DATA__"
    nuxt3_script = soup.find("script", id="__NUXT_DATA__")
    if nuxt3_script and nuxt3_script.string:
        try:
            data = json.loads(nuxt3_script.string)
            text = _deep_extract_text(data)
            if len(text) >= 100:
                return text, "nuxt_data"
        except (json.JSONDecodeError, AttributeError) as e:
            logger.debug(f"Failed to parse __NUXT_DATA__: {e}")

    # Nuxt 2: look for window.__NUXT__ in script tags
    for script in soup.find_all("script"):
        if script.string and "__NUXT__" in script.string:
            # Try to extract JSON from window.__NUXT__ assignment
            match = re.search(r"window\.__NUXT__\s*=\s*(\{.+\})\s*;?\s*$", script.string, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    text = _deep_extract_text(data)
                    if len(text) >= 100:
                        return text, "nuxt_data"
                except (json.JSONDecodeError, AttributeError):
                    pass

    return "", ""


def _extract_json_ld(soup: BeautifulSoup) -> tuple[str, str]:
    """Layer 2: Extract content from JSON-LD structured data.

    Looks for application/ld+json script tags containing Article,
    NewsArticle, BlogPosting, or similar content types.

    Returns:
        Tuple of (extracted_text, source_label) or ("", "") if not found
    """
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
            # Handle both single objects and arrays
            items = data if isinstance(data, list) else [data]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Check for article-like types
                item_type = item.get("@type", "")
                if isinstance(item_type, list):
                    item_type = " ".join(item_type)
                article_types = ("Article", "NewsArticle", "BlogPosting",
                                 "WebPage", "Report", "TechArticle",
                                 "ScholarlyArticle")
                if any(t in item_type for t in article_types):
                    # Extract articleBody or text
                    body = item.get("articleBody", "") or item.get("text", "")
                    if isinstance(body, str) and len(body) >= 100:
                        return body, "json_ld"
                    # Try deep extraction
                    text = _deep_extract_text(item)
                    if len(text) >= 100:
                        return text, "json_ld"
        except (json.JSONDecodeError, AttributeError) as e:
            logger.debug(f"Failed to parse JSON-LD: {e}")

    return "", ""


# --- Metadata Extraction ---


def _extract_metadata(soup: BeautifulSoup) -> ExtractedMetadata:
    """Extract metadata from HTML meta tags, OG tags, and title element."""
    meta = ExtractedMetadata()

    # Title
    title_tag = soup.find("title")
    if title_tag:
        meta.title = title_tag.get_text(strip=True)

    # Standard meta tags
    for tag in soup.find_all("meta"):
        name = (tag.get("name", "") or tag.get("property", "")).lower()
        content = tag.get("content", "")
        if not content:
            continue
        if name == "description":
            meta.description = content
        elif name == "author":
            meta.author = content
        elif name == "og:title":
            meta.og_title = content
        elif name == "og:description":
            meta.og_description = content
        elif name == "og:image":
            meta.og_image = content
        elif name == "og:site_name":
            meta.og_site_name = content
        elif name in ("article:published_time", "pubdate", "publishdate"):
            meta.published_time = content

    return meta


# --- Layer 3: Content Quality Scoring ---

_NEGATIVE_PATTERNS = re.compile(
    r"(loading\.{2,}|please wait|javascript (is )?required|enable javascript|"
    r"\{\{[\w.]+\}\}|<%[^%]+%>|{%[^%]+%}|\[object object\])",
    re.IGNORECASE,
)


def _assess_quality(text: str, sources: list[str], metadata: ExtractedMetadata) -> tuple[int, str, str]:
    """Layer 3: Deterministic quality scoring of extracted content.

    Scoring breakdown (0-100):
        - Word count: 0-40 points
        - Paragraph structure: 0-20 points
        - Data source confidence: 0-25 points
        - Metadata completeness: 0-15 points
        - Negative signals: up to -30 points

    Returns:
        Tuple of (score, decision, reason)
        Decision: "sufficient" (>=40), "insufficient" (15-39), "unprocessable" (<15)
    """
    score = 0
    reasons = []

    # --- Word count (0-40) ---
    word_count = len(text.split())
    if word_count >= 500:
        score += 40
        reasons.append(f"word_count={word_count} (+40)")
    elif word_count >= 200:
        score += 30
        reasons.append(f"word_count={word_count} (+30)")
    elif word_count >= 100:
        score += 20
        reasons.append(f"word_count={word_count} (+20)")
    elif word_count >= 50:
        score += 10
        reasons.append(f"word_count={word_count} (+10)")
    else:
        reasons.append(f"word_count={word_count} (+0)")

    # --- Paragraph structure (0-20) ---
    paragraphs = [p for p in text.split("\n") if len(p.strip()) >= 30]
    if len(paragraphs) >= 5:
        score += 20
        reasons.append(f"paragraphs={len(paragraphs)} (+20)")
    elif len(paragraphs) >= 3:
        score += 15
        reasons.append(f"paragraphs={len(paragraphs)} (+15)")
    elif len(paragraphs) >= 1:
        score += 5
        reasons.append(f"paragraphs={len(paragraphs)} (+5)")
    else:
        reasons.append(f"paragraphs={len(paragraphs)} (+0)")

    # --- Data source confidence (0-25) ---
    high_confidence_sources = {"next_data", "nuxt_data", "json_ld", "semantic:article"}
    medium_confidence_sources = {"semantic:main", "semantic:role-main", "semantic:id-match", "semantic:class-match"}

    if any(s in high_confidence_sources for s in sources):
        score += 25
        reasons.append("high_confidence_source (+25)")
    elif any(s in medium_confidence_sources for s in sources):
        score += 15
        reasons.append("medium_confidence_source (+15)")
    elif "fallback:body" in sources:
        score += 5
        reasons.append("fallback_source (+5)")
    else:
        reasons.append("no_source (+0)")

    # --- Metadata completeness (0-15) ---
    meta_score = 0
    if metadata.title or metadata.og_title:
        meta_score += 5
    if metadata.description or metadata.og_description:
        meta_score += 5
    if metadata.author or metadata.published_time:
        meta_score += 5
    score += meta_score
    reasons.append(f"metadata (+{meta_score})")

    # --- Negative signals (up to -30) ---
    negative_matches = _NEGATIVE_PATTERNS.findall(text[:3000])
    if negative_matches:
        penalty = min(len(negative_matches) * 10, 30)
        score -= penalty
        reasons.append(f"negative_signals={len(negative_matches)} (-{penalty})")

    # Clamp score
    score = max(0, min(100, score))

    # Decision
    reason = "; ".join(reasons)
    if score >= 40:
        return score, "sufficient", reason
    elif score >= 15:
        return score, "insufficient", reason
    else:
        return score, "unprocessable", reason


# --- Layer 4: Main Pipeline ---


def extract_content_from_html(html: str) -> ExtractedContent:
    """Main pipeline entry point: extract structured content from raw HTML.

    Runs all 4 layers sequentially:
        1. Semantic HTML extraction
        2. Embedded data extraction (Next.js, Nuxt, JSON-LD)
        3. Quality scoring
        4. Result assembly

    Args:
        html: Raw HTML string from HTTP fetch

    Returns:
        ExtractedContent with text, metadata, quality score, and decision
    """
    result = ExtractedContent()
    soup = BeautifulSoup(html, "html.parser")

    # Layer 1: Metadata extraction (always run)
    result.metadata = _extract_metadata(soup)
    result.title = result.metadata.og_title or result.metadata.title or ""

    # Layer 2: Embedded data extraction (highest priority)
    best_text = ""
    best_source = ""

    # Try embedded data sources first (they're usually cleaner)
    for extractor in (_extract_next_data, _extract_nuxt_data, _extract_json_ld):
        text, source = extractor(soup)
        if text and len(text) > len(best_text):
            best_text = text
            best_source = source

    if best_text:
        result.text = best_text
        result.sources.append(best_source)
        logger.info(f"Content extracted from embedded data: {best_source} ({len(best_text)} chars)")

    # Layer 1: Semantic HTML extraction (complement or fallback)
    semantic_text, semantic_source = _extract_semantic_content(soup)
    if semantic_text:
        if not result.text or len(semantic_text) > len(result.text):
            result.text = semantic_text
            result.sources.insert(0, semantic_source)
            logger.info(f"Content extracted from semantic HTML: {semantic_source} ({len(semantic_text)} chars)")
        elif semantic_source not in result.sources:
            result.sources.append(semantic_source)

    # Layer 3: Quality assessment
    score, decision, reason = _assess_quality(result.text, result.sources, result.metadata)
    result.quality_score = score
    result.decision = decision
    result.decision_reason = reason

    logger.info(
        f"Content extraction complete: score={score}, decision={decision}, "
        f"sources={result.sources}, reason={reason}"
    )

    return result
