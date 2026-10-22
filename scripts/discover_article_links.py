"""
Archive-only article-link discovery.

No network access. All processing is derived from PDF-extracted
records whose provenance has been validated against the archived
PDFs in archive/pdf/.

The pipeline:

  1. Loads pdf_extracted.json and rejects records without a
     source_pdf / source_page pointer.
  2. Confirms the cited source_pdf exists in archive/pdf/.
  3. Derives allowed hosts and article path prefixes from the
     surviving records only.
  4. Matches reviewed titles to extracted URLs offline.
  5. Writes data/processed/article_links.json and a manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any


# ---------------------------------------------------------
# Paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ARCHIVE_DIR = PROJECT_ROOT / "archive" / "pdf"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

PDF_EXTRACTED_PATH = PROCESSED_DIR / "pdf_extracted.json"
REVIEW_PATH = PROCESSED_DIR / "articles_review.json"
OUTPUT_PATH = PROCESSED_DIR / "article_links.json"
MANIFEST_PATH = PROCESSED_DIR / "processing_manifest.json"


def processed_path(filename: str) -> Path:
    """Restrict every generated file to data/processed/."""
    path = (PROCESSED_DIR / filename).resolve()
    if not path.is_relative_to(PROCESSED_DIR.resolve()):
        raise ValueError("Output must remain inside data/processed/")
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------
# Provenance rules
# ---------------------------------------------------------

PROVENANCE_ACCEPTED = {"verified_from_archive"}

# Fields that must be present on every accepted record.
REQUIRED_PROVENANCE_FIELDS = ("source_pdf", "source_page")

# Documented, reproducible title-exclusion rules. Each rule states
# WHY it is excluded so an auditor can trace it back to the source.
TITLE_EXCLUSION_RULES = (
    {
        "reason": "document-level directory page, not an article",
        "match": "candidate_id",
        "value": "document-level-nutrition-directory",
    },
    {
        "reason": "site navigation heading, not an article",
        "match": "title_startswith",
        "value": "healthline nutrition",
    },
    {
        "reason": "non-article fragment captured by PDF text flow",
        "match": "title_exact",
        "value": "backed by science?",
    },
    {
        "reason": (
            "image placeholder text, not an article title; "
            "see review notes for the corresponding page"
        ),
        "match": "title_contains",
        "value": "no image",
    },
    {
        "reason": (
            "truncated fragment; the full title is recovered on the "
            "same PDF page and should be used instead. Kept as an "
            "explicit rule until the positional-recovery step lands."
        ),
        "match": "title_startswith",
        "value": "vitex agnus-castus: which benefits of chasteberry are",
    },
)

DATE_TITLE_RE = re.compile(
    r"^(?:"
    r"\d{1,2}\s+\w+\s+\d{4}"
    r"|\w+\s+\d{1,2},\s*\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r")$"
)

NON_ARTICLE_PATH_PATTERNS = (
    re.compile(r"^/$"),
    re.compile(r"^/search/?$"),
    re.compile(r"^/tag/"),
    re.compile(r"^/author/"),
    re.compile(r"^/about/"),
    re.compile(r"^/contact/"),
    re.compile(r"^/newsletter/"),
    re.compile(r"^/privacy"),
    re.compile(r"^/terms"),
)


# ---------------------------------------------------------
# Text helpers
# ---------------------------------------------------------

def normalize(text: str) -> str:
    text = urllib.parse.unquote(text or "")
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", text).strip().casefold()


def title_key(text: str) -> str:
    return normalize(text).rstrip(" .!?:")


# ---------------------------------------------------------
# Provenance validation
# ---------------------------------------------------------

def _archive_pdf_names() -> set[str]:
    """Return the set of PDF filenames actually present in the archive."""
    if not ARCHIVE_DIR.exists():
        return set()
    return {p.name for p in ARCHIVE_DIR.glob("*.pdf") if p.is_file()}


def _record_has_provenance(record: dict[str, Any]) -> bool:
    if record.get("provenance_status") not in PROVENANCE_ACCEPTED:
        return False
    for field in REQUIRED_PROVENANCE_FIELDS:
        value = record.get(field)
        if value in (None, ""):
            return False
    page = record.get("source_page")
    if not isinstance(page, int) or page <= 0:
        return False
    return True


def load_validated_records() -> list[dict[str, Any]]:
    """
    Load pdf_extracted.json and keep only records whose provenance
    can be traced to a PDF that actually exists in archive/pdf/.

    Rejected records are not silently dropped — they are returned
    in a separate list so the manifest can record why they failed.
    """
    if not PDF_EXTRACTED_PATH.exists():
        raise FileNotFoundError(
            f"PDF extraction not found: {PDF_EXTRACTED_PATH}. "
            "Run pdf_extract.py first."
        )

    with PDF_EXTRACTED_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)

    raw_records = (
        data.get("articles", []) if isinstance(data, dict) else data
    )
    if not isinstance(raw_records, list):
        raise ValueError("pdf_extracted.json must contain a list of records")

    archive_names = _archive_pdf_names()
    accepted: list[dict[str, Any]] = []

    for record in raw_records:
        if not isinstance(record, dict):
            continue
        if not _record_has_provenance(record):
            continue
        if record["source_pdf"] not in archive_names:
            continue
        accepted.append(record)

    return accepted


# ---------------------------------------------------------
# Offline URL validation
# ---------------------------------------------------------

def _is_valid_http_url(url: str) -> bool:
    """Syntax-only URL check. No network."""
    if not isinstance(url, str) or not url.strip():
        return False
    parsed = urllib.parse.urlparse(url.strip())
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
    )


def _canonical_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path = path.rstrip("/") + "/"
    return f"{parsed.scheme}://{host}{path}"


# ---------------------------------------------------------
# Runtime configuration derived from archive evidence
# ---------------------------------------------------------

class ArchiveConfig:
    def __init__(self, records: list[dict[str, Any]]) -> None:
        self.hosts: set[str] = set()
        self.prefixes: set[str] = set()
        self.directory_urls: set[str] = set()
        self.url_to_record: dict[str, dict[str, Any]] = {}

        for record in records:
            url = record.get("url") or ""
            parsed = urllib.parse.urlparse(url)
            if not parsed.hostname:
                continue

            canonical = _canonical_url(url)
            self.url_to_record[canonical] = record

            cid = str(record.get("candidate_id", "")).strip()
            if cid == "document-level-nutrition-directory":
                self.directory_urls.add(canonical)
                continue

            self.hosts.add(parsed.hostname.lower())
            path = parsed.path or "/"
            first = path.split("/")[1] if path.count("/") >= 2 else ""
            if first:
                self.prefixes.add(f"/{first}/")

    def is_allowed_host(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        return (
            parsed.scheme in {"http", "https"}
            and (parsed.hostname or "").lower() in self.hosts
        )

    def is_article_url(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        if parsed.query or parsed.fragment:
            return False
        canonical = _canonical_url(url)
        if canonical in self.directory_urls:
            return False
        path = parsed.path or "/"
        if path in self.prefixes:
            return False
        for pattern in NON_ARTICLE_PATH_PATTERNS:
            if pattern.match(path):
                return False
        return any(path.startswith(p) for p in self.prefixes)

    def record_for_url(self, url: str) -> dict[str, Any] | None:
        return self.url_to_record.get(_canonical_url(url))


# ---------------------------------------------------------
# Title eligibility (documented rules, no hardcoded exclusions
# beyond TITLE_EXCLUSION_RULES)
# ---------------------------------------------------------

def _title_is_excluded(record: dict[str, Any]) -> str | None:
    """Return the exclusion reason, or None if the title is eligible."""
    title = str(record.get("title", "")).strip()
    if not title:
        return "empty title"
    key = title_key(title)
    cid = str(record.get("candidate_id", "")).strip()

    for rule in TITLE_EXCLUSION_RULES:
        match = rule["match"]
        value = rule["value"]
        if match == "candidate_id" and cid == value:
            return rule["reason"]
        if match == "title_exact" and key == title_key(value):
            return rule["reason"]
        if match == "title_startswith" and key.startswith(title_key(value)):
            return rule["reason"]
        if match == "title_contains" and title_key(value) in key:
            return rule["reason"]

    if DATE_TITLE_RE.match(title):
        return "date-shaped text, not an article title"

    return None


def load_article_titles(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Return eligible article records (dicts), preserving their
    provenance. Deduplication is deterministic: first occurrence
    of a title_key wins, ordered by (source_pdf, source_page).
    """
    eligible: list[dict[str, Any]] = []
    seen: set[str] = set()

    ordered = sorted(
        records,
        key=lambda r: (
            str(r.get("source_pdf", "")),
            int(r.get("source_page", 0) or 0),
        ),
    )

    for record in ordered:
        reason = _title_is_excluded(record)
        if reason is not None:
            continue
        key = title_key(str(record.get("title", "")))
        if key in seen:
            continue
        seen.add(key)
        eligible.append(record)

    return eligible


# ---------------------------------------------------------
# Load existing outputs (provenance-gated)
# ---------------------------------------------------------

def load_existing_links() -> dict[str, dict[str, Any]]:
    if not OUTPUT_PATH.exists():
        return {}
    with OUTPUT_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    records = data.get("links", [])
    if not isinstance(records, list):
        return {}
    existing: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        if not _record_has_provenance(record):
            continue  # reject unprovenanced previous outputs
        title = str(record.get("title", "")).strip()
        if title:
            existing[title_key(title)] = record
    return existing


# ---------------------------------------------------------
# Offline discovery: match title -> extracted URL
# ---------------------------------------------------------

def discover_url_for_title(
    record: dict[str, Any],
    config: ArchiveConfig,
) -> dict[str, Any]:
    """
    Resolve the URL for a record WITHOUT network access.

    The URL must:
      - be present on the record (extracted from the PDF),
      - pass syntax validation,
      - be on a host cited in the archive,
      - be article-shaped, and
      - not be the directory URL.

    No live page is fetched. The record's provenance_status
    determines whether the URL is accepted as verified.
    """
    title = str(record.get("title", "")).strip()
    url = str(record.get("url", "")).strip()

    result: dict[str, Any] = {
        "title": title,
        "url": None,
        "status": "not_found",
        "source_pdf": record.get("source_pdf"),
        "source_page": record.get("source_page"),
        "provenance_status": record.get("provenance_status"),
    }

    if not url:
        result["error"] = "No URL present in the PDF-extracted record"
        return result

    if not _is_valid_http_url(url):
        result["error"] = "URL failed syntax validation"
        return result

    if not config.is_allowed_host(url):
        result["error"] = "URL host is not cited in the archive"
        return result

    if not config.is_article_url(url):
        result["error"] = "URL is not an article-shaped path"
        return result

    # Trust only if the extraction marked this record as archived.
    if record.get("provenance_status") in PROVENANCE_ACCEPTED:
        result["url"] = _canonical_url(url)
        result["status"] = "verified_from_archive"
        return result

    result["error"] = (
        "Record has a URL but was not marked verified_from_archive"
    )
    return result


# ---------------------------------------------------------
# Run pipeline (offline)
# ---------------------------------------------------------

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def run_discovery() -> None:
    records = load_validated_records()
    config = ArchiveConfig(records)
    eligible = load_article_titles(records)
    existing = load_existing_links()

    results: list[dict[str, Any]] = []

    print(f"Archive PDFs: {sorted(_archive_pdf_names())}")
    print(f"Validated records: {len(records)}")
    print(f"Eligible titles: {len(eligible)}")
    print(f"Archive hosts: {sorted(config.hosts)}")
    print(f"Article prefixes: {sorted(config.prefixes)}")

    for index, record in enumerate(eligible, start=1):
        title = str(record.get("title", "")).strip()
        key = title_key(title)
        prior = existing.get(key)
        print(f"[{index}/{len(eligible)}] {title}")

        if prior and prior.get("status") == "verified_from_archive":
            result = {**prior, "title": title}
            print(f"  -> preserved archive-verified: {result['url']}")
        else:
            result = discover_url_for_title(record, config)
            print(
                f"  -> {result.get('status')}: {result.get('url')} "
                f"(pdf={result.get('source_pdf')} "
                f"p.{result.get('source_page')})"
            )
            if result.get("error"):
                print(f"     Note: {result['error']}")

        results.append(result)

    OUTPUT_PATH = processed_path("article_links.json")
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        json.dump({"links": results}, file, indent=2, ensure_ascii=False)
        file.write("\n")

    manifest = {
        "archive_dir": str(ARCHIVE_DIR),
        "archive_pdfs": [
            {"name": n, "sha256": _sha256_file(ARCHIVE_DIR / n)}
            for n in sorted(_archive_pdf_names())
        ],
        "input_files": {
            "pdf_extracted.json": _sha256_file(PDF_EXTRACTED_PATH),
            "articles_review.json": (
                _sha256_file(REVIEW_PATH) if REVIEW_PATH.exists() else None
            ),
        },
        "counts": {
            "validated_records": len(records),
            "eligible_titles": len(eligible),
            "verified_from_archive": sum(
                r.get("status") == "verified_from_archive" for r in results
            ),
            "needs_review": sum(
                r.get("status") == "needs_review" for r in results
            ),
            "not_found": sum(
                r.get("status") == "not_found" for r in results
            ),
        },
        "rules": {
            "title_exclusions": TITLE_EXCLUSION_RULES,
            "provenance_accepted": sorted(PROVENANCE_ACCEPTED),
            "network_access": "disabled",
        },
    }
    with MANIFEST_PATH.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2, ensure_ascii=False)
        file.write("\n")

    print()
    print(f"Saved {len(results)} records to {OUTPUT_PATH}")
    print(f"Manifest: {MANIFEST_PATH}")
    print(f"Verified from archive: {manifest['counts']['verified_from_archive']}")


if __name__ == "__main__":
    run_discovery()