
import hashlib
import json
import re

from backend.app.config import PAGES_PATH


SKIP_PATTERNS = [
    r"^https?://",
    r"^www\.",
    r"^page\s+\d+$",
    r"^copyright\b",
    r"^all rights reserved\b",
    r"^advertisement$",
    r"^read more$",
]


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def looks_like_heading(line: str) -> bool:
    line = re.sub(r"\s+", " ", line).strip()
    words = line.split()

    if len(line) < 15 or len(line) > 160:
        return False

    if len(words) < 3 or len(words) > 22:
        return False

    if line.endswith((".", ",", ";", ":")):
        return False

    if re.fullmatch(r"[\W\d_]+", line):
        return False

    for pattern in SKIP_PATTERNS:
        if re.search(pattern, line, re.IGNORECASE):
            return False

    letters = [char for char in line if char.isalpha()]
    if not letters:
        return False

    uppercase_ratio = (
        sum(char.isupper() for char in letters) / len(letters)
    )

    title_case_count = sum(
        word[0].isupper()
        for word in words
        if word[0].isalpha()
    )
    title_case_ratio = title_case_count / len(words)

    return (
        uppercase_ratio >= 0.75
        or title_case_ratio >= 0.60
    )


def find_article_candidates() -> list[dict]:
    if not PAGES_PATH.exists():
        raise FileNotFoundError(
            f"Run extraction first: {PAGES_PATH}"
        )

    candidates = []
    seen = set()

    with PAGES_PATH.open(encoding="utf-8") as source:
        for raw_record in source:
            if not raw_record.strip():
                continue

            record = json.loads(raw_record)
            page_number = record["page_number"]

            lines = [
                re.sub(r"\s+", " ", line).strip()
                for line in record["text"].splitlines()
                if line.strip()
            ]

            # Inspect only the first 18 non-empty lines per page.
            for line_index, line in enumerate(
                lines[:18], start=1
            ):
                if not looks_like_heading(line):
                    continue

                normalized = normalize_title(line)
                key = (normalized, page_number)

                if key in seen:
                    continue

                seen.add(key)

                short_hash = hashlib.sha256(
                    f"{page_number}:{normalized}".encode("utf-8")
                ).hexdigest()[:10]

                candidates.append({
                    "candidate_id": f"candidate-{short_hash}",
                    "title": line,
                    "canonical_url": None,
                    "detected_on_page": page_number,
                    "detected_line_number": line_index,
                    "start_page": None,
                    "end_page": None,
                    "review_status": "candidate",
                    "topic": None,
                    "needs_manual_review": True,
                })

    return candidates
