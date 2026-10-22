
import json

from backend.app.config import (
    ARTICLES_REVIEW_PATH,
    PROCESSED_DIR,
)
from backend.app.ingestion.article_parser import (
    find_article_candidates,
)


def main() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    candidates = find_article_candidates()

    output = {
        "review_instructions": (
            "Candidates are heuristic suggestions. Verify the "
            "title and page range against the original PDF. "
            "Only reviewed articles may be indexed."
        ),
        "candidates": candidates,
    }

    with ARTICLES_REVIEW_PATH.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            output,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print("Candidate headings:", len(candidates))
    print("Review file:", ARTICLES_REVIEW_PATH)
    print("Verify each candidate manually.")


if __name__ == "__main__":
    main()
