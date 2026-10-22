
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

import requests

from backend.app.config import ARTICLE_LINKS_PATH, ARTICLES_RAW_PATH


USER_AGENT = (
    "NutritionResearchIndexer/1.0 "
    "(educational research; contact information should be configured)"
)
TIMEOUT_SECONDS = 20


def read_links(path: Path = ARTICLE_LINKS_PATH) -> list[dict]:
    """Load only links whose recorded status is verified."""
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, dict) or not isinstance(data.get("links"), list):
        raise ValueError("Expected JSON object containing a links list.")

    verified = []

    for item in data["links"]:
        if not isinstance(item, dict):
            continue

        if item.get("status") != "verified":
            continue

        url = str(item.get("url", "")).strip()
        title = str(item.get("title", "")).strip()

        parsed = urlparse(url)

        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.healthline.com"
            or not parsed.path.startswith("/nutrition/")
            or not title
        ):
            print(f"SKIP invalid or unapproved source: {title!r}")
            continue

        verified.append({"title": title, "url": url})

    return verified


def clean_html(html: str) -> tuple[str, str]:
    """Extract the HTML title and readable text while skipping page chrome."""
    from html.parser import HTMLParser

    class TextExtractor(HTMLParser):
        SKIP_TAGS = {
            "script", "style", "noscript", "svg", "nav",
            "header", "footer", "aside", "button", "form",
        }

        BLOCK_TAGS = {
            "p", "h1", "h2", "h3", "h4", "h5", "h6",
            "li", "br", "div", "section", "article",
            "blockquote", "tr",
        }

        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_title = False
            self.skip_depth = 0
            self.skip_stack = []
            self.title_parts = []
            self.text_parts = []

        def handle_starttag(self, tag, attrs):
            if tag == "title":
                self.in_title = True

            if tag in self.BLOCK_TAGS and self.skip_depth == 0:
                self.text_parts.append("\n")

            if tag in self.SKIP_TAGS:
                self.skip_stack.append(tag)
                self.skip_depth += 1

        def handle_startendtag(self, tag, attrs):
            # Self-closing tags do not leave an open skip region.
            if tag in self.BLOCK_TAGS and self.skip_depth == 0:
                self.text_parts.append("\n")

        def handle_endtag(self, tag):
            if tag == "title":
                self.in_title = False

            if tag in self.SKIP_TAGS:
                # HTML may contain nested excluded elements.
                for index in range(len(self.skip_stack) - 1, -1, -1):
                    if self.skip_stack[index] == tag:
                        del self.skip_stack[index:]
                        break
                self.skip_depth = len(self.skip_stack)

            if tag in self.BLOCK_TAGS and self.skip_depth == 0:
                self.text_parts.append("\n")

        def handle_data(self, data):
            if self.in_title and data.strip():
                self.title_parts.append(data.strip())

            if self.skip_depth == 0 and data.strip():
                self.text_parts.append(data.strip())

    parser = TextExtractor()
    parser.feed(html)
    parser.close()

    title = re.sub(
        r"\s+", " ", " ".join(parser.title_parts)
    ).strip()

    body = unescape(" ".join(parser.text_parts))
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r" *\n *", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    # Remove common navigation phrases when they occur as standalone text.
    noise_patterns = [
        r"(?im)^\s*skip to main content\s*$",
        r"(?im)^\s*search healthline\s*$",
        r"(?im)^\s*subscribe\s*$",
    ]

    for pattern in noise_patterns:
        body = re.sub(pattern, "", body)

    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    return title, body


def fetch_article(item: dict) -> dict:
    """Fetch one article and record success or failure without hiding errors."""
    result = {
        "title": item["title"],
        "url": item["url"],
        "status": "failed",
        "page_title": None,
        "text": "",
        "error": None,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        response = requests.get(
            item["url"],
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        final_url = urlparse(response.url)
        if (
            final_url.scheme != "https"
            or final_url.hostname != "www.healthline.com"
            or not final_url.path.startswith("/nutrition/")
        ):
            raise ValueError("Unexpected final URL; refusing to ingest it.")

        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            raise ValueError(f"Expected HTML, got {content_type!r}.")

        page_title, body = clean_html(response.text)
        normalized_expected = re.sub(
            r"\s+", " ", item["title"]
        ).strip().casefold()

        normalized_actual = re.sub(
            r"\s+", " ", page_title
        ).strip().casefold()

        

        result["page_title"] = page_title
        result["final_url"] = response.url

        if normalized_expected not in normalized_actual:
            print(
                "  Warning: source title differs from configured title."
                f" Expected={item['title']!r}; actual={page_title!r}"
            )

        if len(body) < 1500:
            result["error"] = (
                "Extracted text is too short for safe ingestion; review manually."
            )
            return result

        result["text"] = body
        result["status"] = "fetched"

    except (requests.RequestException, ValueError) as exc:
        result["error"] = str(exc)

    return result


def main():
    links = read_links()
    if not links:
        raise RuntimeError("No eligible verified Healthline article URLs found.")

    ARTICLES_RAW_PATH.parent.mkdir(parents=True, exist_ok=True)

    results = []
    for item in links:
        print(f"Fetching: {item['title']}")
        result = fetch_article(item)
        results.append(result)
        print(f"  Status: {result['status']}")
        if result["error"]:
            print(f"  Detail: {result['error']}")

    with ARTICLES_RAW_PATH.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, ensure_ascii=False) + "\n")

    succeeded = sum(result["status"] == "fetched" for result in results)
    print(f"\nSaved {len(results)} results to {ARTICLES_RAW_PATH}")
    print(f"Fetched successfully: {succeeded}; needs review or failed: {len(results) - succeeded}")


if __name__ == "__main__":
    main()
