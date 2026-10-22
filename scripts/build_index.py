import hashlib
import json
from pathlib import Path

from sqlalchemy import create_engine, text

from backend.app.config import (
    ARTICLES_REVIEW_PATH,
    DATABASE_URL,
    MANIFEST_PATH,
    PAGES_PATH,
    PDF_PATH,
)
from backend.app.ingestion.chunker import chunk_page
from backend.app.ml.embeddings import embed_texts


BATCH_SIZE = 32


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def read_jsonl(path: Path) -> list[dict]:
    records = []

    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in {path}, line {line_number}"
                ) from exc

            if not isinstance(record, dict):
                raise ValueError(
                    f"Expected a JSON object in {path}, "
                    f"line {line_number}"
                )

            records.append(record)

    return records


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def get_page_number(record: dict) -> int:
    value = record.get("page_number", record.get("page"))

    try:
        page_number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid or missing page number: {record}"
        ) from exc

    if page_number < 1:
        raise ValueError(
            f"Page number must be positive: {record}"
        )

    return page_number


def get_page_text(record: dict) -> str:
    value = record.get("text")

    if value is None:
        value = record.get("page_text", "")

    return str(value or "").strip()


def get_reviewed_articles(data) -> list[dict]:
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = data.get(
            "candidates",
            data.get("articles", []),
        )
    else:
        raise ValueError(
            "articles_review.json must contain a list or an object"
        )

    if not isinstance(candidates, list):
        raise ValueError(
            "The candidates/articles field must contain a list"
        )

    reviewed = []
    seen_keys = set()

    for article in candidates:
        if not isinstance(article, dict):
            continue

        if article.get("review_status") != "reviewed":
            continue

        if article.get("needs_manual_review") is True:
            continue

        if not str(article.get("title", "")).strip():
            raise ValueError(
                f"Reviewed article has no title: {article}"
            )

        try:
            start_page = int(article["start_page"])
            end_page = int(article["end_page"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                f"Reviewed article has an invalid page range: {article}"
            ) from exc

        if start_page < 1 or end_page < start_page:
            raise ValueError(
                f"Invalid article page range: {article}"
            )

        article_key = (
            str(article["title"]).strip(),
            start_page,
            end_page,
        )

        if article_key in seen_keys:
            raise ValueError(
                f"Duplicate reviewed article detected: {article_key}"
            )

        seen_keys.add(article_key)

        reviewed.append({
            **article,
            "title": str(article["title"]).strip(),
            "start_page": start_page,
            "end_page": end_page,
        })

    return reviewed


def get_article_key(article: dict) -> tuple[str, int, int]:
    return (
        article["title"],
        article["start_page"],
        article["end_page"],
    )


def find_matching_article(
    page_number: int,
    articles: list[dict],
) -> dict:
    matching_articles = [
        article
        for article in articles
        if article["start_page"]
        <= page_number
        <= article["end_page"]
    ]

    if len(matching_articles) != 1:
        raise ValueError(
            f"Page {page_number} matches "
            f"{len(matching_articles)} reviewed articles. "
            "Each chunk must map to exactly one article. "
            "Review article page ranges or implement "
            "text-level segmentation for multiple articles "
            "on the same page."
        )

    return matching_articles[0]


def assert_no_duplicate_articles(
    conn,
    document_id: int,
) -> None:
    duplicates = conn.execute(
        text("""
            SELECT
                title,
                start_page,
                end_page,
                COUNT(*) AS duplicate_count
            FROM articles
            WHERE document_id = :document_id
            GROUP BY
                title,
                start_page,
                end_page
            HAVING COUNT(*) > 1
        """),
        {"document_id": document_id},
    ).all()

    if duplicates:
        details = "; ".join(
            f"{title!r} pages {start_page}-{end_page} "
            f"(x{count})"
            for title, start_page, end_page, count in duplicates
        )
        raise RuntimeError(
            f"Duplicate article rows already exist for "
            f"document_id={document_id}: {details}. "
            "Resolve duplicates and add a unique constraint "
            "on (document_id, title, start_page, end_page) "
            "before re-running."
        )


def main():
    required_files = [
        PDF_PATH,
        PAGES_PATH,
        MANIFEST_PATH,
        ARTICLES_REVIEW_PATH,
    ]

    for path in required_files:
        if not path.is_file():
            raise FileNotFoundError(
                f"Required file not found: {path}"
            )

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is missing. Check the root .env file."
        )

    checksum = sha256_file(PDF_PATH)
    manifest = read_json(MANIFEST_PATH)

    if not isinstance(manifest, dict):
        raise ValueError(
            "manifest.json must contain a JSON object"
                )
    
    pages = read_jsonl(PAGES_PATH)
    articles = get_reviewed_articles(
        read_json(ARTICLES_REVIEW_PATH)
    )

    if not articles:
        raise ValueError(
            "No reviewed articles found. "
            "Review data/processed/articles_review.json "
            "before building the index."
        )

    if not pages:
        raise ValueError("pages.jsonl contains no records")

    normalized_pages = []

    for record in pages:
        page_number = get_page_number(record)

        normalized_pages.append({
            "page_number": page_number,
            "text": get_page_text(record),
        })

    normalized_pages.sort(
        key=lambda page: page["page_number"]
    )

    page_numbers = [
        page["page_number"] for page in normalized_pages
    ]

    expected_numbers = list(range(1, len(normalized_pages) + 1))

    if page_numbers != expected_numbers:
        raise ValueError(
            "Page numbers must be unique and sequential from 1. "
            "Inspect pages.jsonl before continuing."
        )

    declared_count = manifest.get("page_count")

    if (
        declared_count is not None
        and int(declared_count) != len(normalized_pages)
    ):
        raise ValueError(
            f"Manifest says {declared_count} pages, but "
            f"pages.jsonl contains {len(normalized_pages)}."
        )

    declared_checksum = next(
        (
            manifest[key]
            for key in (
                "document_checksum",
                "checksum",
                "sha256",
                "file_sha256",
            )
            if manifest.get(key)
        ),
        None,
    )

    if (
        declared_checksum
        and declared_checksum.lower() != checksum.lower()
    ):
        raise ValueError(
            "Manifest checksum differs from the PDF checksum. "
            "Check the manifest or rerun Day 2 extraction."
        )

    chunks = []

    for page in normalized_pages:
        if not page["text"]:
            continue

        for chunk in chunk_page(
            page["page_number"],
            page["text"],
        ):
            page_number = chunk["page_number"]

            chunk_text = str(chunk.get("chunk_text") or "").strip()

            if not chunk_text:
                raise ValueError(
                    f"Empty chunk text on page {page_number}"
                )

            if "chunk_index" not in chunk:
                raise ValueError(
                    f"chunk_index missing on page {page_number}"
                )

            if "text_hash" not in chunk:
                raise ValueError(
                    f"text_hash missing on page {page_number}"
                )

            matching_article = find_matching_article(
                page_number,
                articles,
            )

            chunks.append({
                **chunk,
                "chunk_text": chunk_text,
                "article_key": get_article_key(matching_article),
            })

    if not chunks:
        raise ValueError(
            "No chunks generated. Check the extracted page text."
        )

    print(f"Source PDF: {PDF_PATH.name}")
    print(f"PDF pages: {len(normalized_pages)}")
    print(f"Reviewed articles: {len(articles)}")
    print(f"Chunks to index: {len(chunks)}")
    print("Generating embeddings...")

    vectors = []

    for start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[start:start + BATCH_SIZE]
        batch_vectors = embed_texts([
            item["chunk_text"] for item in batch
        ])

        if len(batch_vectors) != len(batch):
            raise RuntimeError(
                f"Embedding batch starting at {start} returned "
                f"{len(batch_vectors)} vectors for "
                f"{len(batch)} chunks."
            )

        vectors.extend(batch_vectors)

    if len(vectors) != len(chunks):
        raise RuntimeError(
            "The number of embeddings does not match the chunks."
        )

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
    )

    try:
        # All database modifications commit together or roll back.
        with engine.begin() as conn:
            document_id = conn.execute(
                text("""
                    INSERT INTO documents (
                        filename,
                        checksum,
                        page_count,
                        source_name
                    )
                    VALUES (
                        :filename,
                        :checksum,
                        :page_count,
                        :source_name
                    )
                    ON CONFLICT (checksum)
                    DO UPDATE SET
                        filename = EXCLUDED.filename,
                        page_count = EXCLUDED.page_count,
                        source_name = EXCLUDED.source_name
                    RETURNING document_id
                """),
                {
                    "filename": PDF_PATH.name,
                    "checksum": checksum,
                    "page_count": len(normalized_pages),
                    "source_name": "HealthWatch",
                },
            ).scalar_one()

            assert_no_duplicate_articles(conn, document_id)

            article_ids = {}

            for article in articles:
                key = (
                    article["title"],
                    article["start_page"],
                    article["end_page"],
                )

                article_id = conn.execute(
                    text("""
                        SELECT article_id
                        FROM articles
                        WHERE document_id = :document_id
                          AND title = :title
                          AND start_page = :start_page
                          AND end_page = :end_page
                        ORDER BY article_id
                        LIMIT 1
                    """),
                    {
                        "document_id": document_id,
                        "title": article["title"],
                        "start_page": article["start_page"],
                        "end_page": article["end_page"],
                    },
                ).scalar_one_or_none()

                values = {
                    "document_id": document_id,
                    "title": article["title"],
                    "canonical_url": article.get("canonical_url"),
                    "start_page": article["start_page"],
                    "end_page": article["end_page"],
                    "review_status": "reviewed",
                    "topic": article.get("topic"),
                }

                if article_id is None:
                    article_id = conn.execute(
                        text("""
                            INSERT INTO articles (
                                document_id,
                                title,
                                canonical_url,
                                start_page,
                                end_page,
                                review_status,
                                topic
                            )
                            VALUES (
                                :document_id,
                                :title,
                                :canonical_url,
                                :start_page,
                                :end_page,
                                :review_status,
                                :topic
                            )
                            RETURNING article_id
                        """),
                        values,
                    ).scalar_one()
                else:
                    conn.execute(
                        text("""
                            UPDATE articles
                            SET canonical_url = :canonical_url,
                                review_status = :review_status,
                                topic = :topic
                            WHERE article_id = :article_id
                        """),
                        {
                            **values,
                            "article_id": article_id,
                        },
                    )

                article_ids[key] = article_id

            for chunk in chunks:
                key = chunk["article_key"]

                if key not in article_ids:
                    raise ValueError(
                        f"No database article ID found for chunk: {key}"
                    )

                chunk["article_id"] = article_ids[key]

            # Replace indexed chunks for this document only.
            conn.execute(
                text("""
                    DELETE FROM chunks
                    WHERE document_id = :document_id
                """),
                {"document_id": document_id},
            )

            insert_sql = text("""
                INSERT INTO chunks (
                    document_id,
                    article_id,
                    page_number,
                    chunk_index,
                    chunk_text,
                    text_hash,
                    embedding
                )
                VALUES (
                    :document_id,
                    :article_id,
                    :page_number,
                    :chunk_index,
                    :chunk_text,
                    :text_hash,
                    CAST(:embedding AS vector)
                )
            """)

            for chunk, vector in zip(chunks, vectors, strict=True):
                conn.execute(
                    insert_sql,
                    {
                        "document_id": document_id,
                        "article_id": chunk["article_id"],
                        "page_number": chunk["page_number"],
                        "chunk_index": chunk["chunk_index"],
                        "chunk_text": chunk["chunk_text"],
                        "text_hash": chunk["text_hash"],
                        "embedding": json.dumps(vector),
                    },
                )

        print("\nINDEXING SUCCESSFUL")
        print(f"Document ID: {document_id}")
        print(f"Reviewed articles indexed: {len(articles)}")
        print(f"Chunks indexed: {len(chunks)}")
        print(f"Embeddings generated: {len(vectors)}")

    finally:
        engine.dispose()


if __name__ == "__main__":
    main()