
import hashlib
import json
from datetime import datetime, timezone

import fitz

from backend.app.config import (
    MANIFEST_PATH,
    PDF_PATH,
    PAGES_PATH,
    PROCESSED_DIR,
)


def sha256_bytes(data: bytes) -> str:
    """Return a SHA-256 checksum for bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Return a SHA-256 checksum for text."""
    return sha256_bytes(text.encode("utf-8"))


def extract_pdf() -> dict:
    """Extract text page by page and write a manifest."""

    if not PDF_PATH.exists():
        raise FileNotFoundError(
            f"Source PDF not found: {PDF_PATH}"
        )

    if PDF_PATH.stat().st_size == 0:
        raise ValueError("The source PDF is empty.")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    pdf_bytes = PDF_PATH.read_bytes()
    document_checksum = sha256_bytes(pdf_bytes)

    page_records = []
    empty_text_pages = []
    total_characters = 0

    with fitz.open(PDF_PATH) as document:
        if document.needs_pass:
            raise ValueError(
                "The PDF is password-protected."
            )

        metadata = document.metadata or {}
        page_count = len(document)

        for index, page in enumerate(document):
            # Page numbers in the project are one-based.
            page_number = index + 1

            extracted = page.get_text("text", sort=True)
            page_text = extracted.replace("\x00", "").strip()

            character_count = len(page_text)
            total_characters += character_count

            if not page_text:
                empty_text_pages.append(page_number)

            page_records.append({
                "document_filename": PDF_PATH.name,
                "document_checksum": document_checksum,
                "page_number": page_number,
                "page_checksum": sha256_text(page_text),
                "character_count": character_count,
                "text": page_text,
            })

        manifest = {
            "source_name": "CBS News HealthWatch",
            "filename": PDF_PATH.name,
            "source_path": str(PDF_PATH),
            "document_checksum": document_checksum,
            "file_size_bytes": len(pdf_bytes),
            "page_count": page_count,
            "total_extracted_characters": total_characters,
            "empty_text_pages": empty_text_pages,
            "metadata": {
                "title": metadata.get("title"),
                "author": metadata.get("author"),
                "subject": metadata.get("subject"),
                "creator": metadata.get("creator"),
                "producer": metadata.get("producer"),
                "creation_date": metadata.get("creationDate"),
            },
            "extraction_method": "PyMuPDF page.get_text",
            "extracted_at_utc": datetime.now(
                timezone.utc
            ).isoformat(),
        }

    # Write one JSON object per page.
    with PAGES_PATH.open("w", encoding="utf-8") as output:
        for record in page_records:
            output.write(
                json.dumps(record, ensure_ascii=False) + "\n"
            )

    # Write document-level extraction metadata.
    with MANIFEST_PATH.open("w", encoding="utf-8") as output:
        json.dump(
            manifest,
            output,
            ensure_ascii=False,
            indent=2,
        )

    print("PDF:", PDF_PATH.name)
    print("SHA-256:", document_checksum)
    print("Page count:", manifest["page_count"])
    print("Extracted characters:", total_characters)
    print("Pages with no text:", empty_text_pages)
    print("Pages file:", PAGES_PATH)
    print("Manifest file:", MANIFEST_PATH)

    return manifest


if __name__ == "__main__":
    extract_pdf()
