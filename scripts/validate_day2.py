
import json

from backend.app.config import (
    ARTICLES_REVIEW_PATH,
    MANIFEST_PATH,
    PAGES_PATH,
)


def load_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def main():
    errors = []

    for path in (
        MANIFEST_PATH,
        PAGES_PATH,
        ARTICLES_REVIEW_PATH,
    ):
        if not path.exists():
            errors.append(f"Required file is missing: {path}")

    if errors:
        print("VALIDATION FAILED")
        for error in errors:
            print("-", error)
        raise SystemExit(1)

    manifest = load_json(MANIFEST_PATH)

    with PAGES_PATH.open(encoding="utf-8") as file:
        pages = [
            json.loads(line)
            for line in file
            if line.strip()
        ]

    expected_count = manifest["page_count"]

    if len(pages) != expected_count:
        errors.append(
            f"Expected {expected_count} pages; "
            f"found {len(pages)} records."
        )

    actual_numbers = [
        record.get("page_number") for record in pages
    ]
    expected_numbers = list(range(1, len(pages) + 1))

    if actual_numbers != expected_numbers:
        errors.append(
            "Page numbers are missing, duplicated, or unordered."
        )

    for record in pages:
        page_number = record.get("page_number")

        for field in (
            "document_checksum",
            "page_checksum",
            "character_count",
            "text",
        ):
            if field not in record:
                errors.append(
                    f"Page {page_number}: missing {field}."
                )

        text = record.get("text", "")
        if record.get("character_count") != len(text):
            errors.append(
                f"Page {page_number}: character count mismatch."
            )

    review = load_json(ARTICLES_REVIEW_PATH)
    candidates = review.get("candidates", [])

    ids = [item.get("candidate_id") for item in candidates]

    if len(ids) != len(set(ids)):
        errors.append("Duplicate candidate IDs found.")

    for item in candidates:
        if item.get("review_status") != "reviewed":
            continue

        start = item.get("start_page")
        end = item.get("end_page")

        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 1
            or end < start
            or end > expected_count
        ):
            errors.append(
                f"{item.get('candidate_id')}: "
                "invalid reviewed page range."
            )

        if not item.get("title", "").strip():
            errors.append(
                f"{item.get('candidate_id')}: "
                "reviewed candidate has no title."
            )

        if item.get("needs_manual_review") is not False:
            errors.append(
                f"{item.get('candidate_id')}: "
                "reviewed candidate still requires manual review."
            )

    print("PDF pages:", expected_count)
    print("Extracted page records:", len(pages))
    print("Candidate headings:", len(candidates))
    print(
        "Reviewed candidates:",
        sum(
            item.get("review_status") == "reviewed"
            for item in candidates
        ),
    )
    print("Empty-text pages:", manifest.get("empty_text_pages", []))

    if errors:
        print("\nVALIDATION FAILED")
        for error in errors:
            print("-", error)
        raise SystemExit(1)

    print("\nSTRUCTURAL VALIDATION PASSED")
    print("Manual source verification is still required.")


if __name__ == "__main__":
    main()
