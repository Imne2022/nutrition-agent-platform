
import hashlib
import json
import re
import sys

from sqlalchemy import text

from backend.app.config import ARTICLES_RAW_PATH
from backend.app.db import engine
from backend.app.ingestion.chunker import chunk_text
from backend.app.ml.embeddings import embed_texts


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_articles() -> list[dict]:
    if not ARTICLES_RAW_PATH.exists():
        raise FileNotFoundError(
            f"Article input file not found: {ARTICLES_RAW_PATH}"
        )

    records = []

    with ARTICLES_RAW_PATH.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number}"
                ) from exc

            title = record.get("title")
            url = record.get("url")
            article_text = record.get("text")

            if not all(
                isinstance(value, str) and value.strip()
                for value in (title, url, article_text)
            ):
                raise ValueError(
                    f"Line {line_number} needs non-empty "
                    "title, url, and text fields."
                )

            records.append(
                {
                    "title": title.strip(),
                    "url": url.strip(),
                    "text": article_text.strip(),
                }
            )

    return records


def build_index() -> None:
    records = load_articles()

    if not records:
        print("No article records found.")
        return

    inserted_articles = 0
    inserted_chunks = 0
    skipped_articles = 0

    with engine.begin() as connection:
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()

        print(f"Connected database: {database_name}")

        if database_name != "nutrition_rag":
            raise RuntimeError(
                "Wrong database. Expected nutrition_rag, "
                f"but connected to {database_name!r}. "
                "Check DATABASE_URL in .env."
            )

        for record in records:
            title = record["title"]
            url = record["url"]
            article_text = record["text"]

            # Make reruns safe: do not insert an existing URL again.
            existing = connection.execute(
                text(
                    """
                    SELECT article_id
                    FROM articles
                    WHERE canonical_url = :url
                    LIMIT 1
                    """
                ),
                {"url": url},
            ).first()

            if existing:
                print(f"SKIP existing article: {title}")
                skipped_articles += 1
                continue

            chunks = chunk_text(article_text)

            if not chunks:
                print(f"SKIP empty article after chunking: {title}")
                skipped_articles += 1
                continue

            embeddings = embed_texts(
                [chunk["chunk_text"] for chunk in chunks]
            )

            if len(embeddings) != len(chunks):
                raise RuntimeError(
                    f"Embedding count mismatch for {title}"
                )

            if any(len(vector) != 384 for vector in embeddings):
                raise RuntimeError(
                    f"Unexpected embedding dimensions for {title}"
                )

            checksum = sha256_text(url + "\n" + article_text)

            slug = re.sub(
                r"[^a-z0-9]+",
                "-",
                title.lower(),
            ).strip("-")[:70] or "article"

            document_result = connection.execute(
                text(
                    """
                    INSERT INTO documents (
                        filename,
                        checksum,
                        page_count,
                        source_name
                    )
                    VALUES (
                        :filename,
                        :checksum,
                        1,
                        :source_name
                    )
                    RETURNING document_id
                    """
                ),
                {
                    "filename": f"web-{slug}.txt",
                    "checksum": checksum,
                    "source_name": url,
                },
            )

            document_id = document_result.scalar_one()

            # Web pages do not have PDF page numbers.
            # The existing schema requires page values >= 1, so
            # 1 is a technical placeholder, NOT a real page number.
            article_result = connection.execute(
                text(
                    """
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
                        :url,
                        1,
                        1,
                        'candidate',
                        'nutrition'
                    )
                    RETURNING article_id
                    """
                ),
                {
                    "document_id": document_id,
                    "title": title,
                    "url": url,
                },
            )

            article_id = article_result.scalar_one()

            for chunk, embedding in zip(chunks, embeddings):
                # Scope the hash to this URL so identical text from
                # different sources does not collide globally.
                source_chunk_hash = sha256_text(
                    url + "\n" + chunk["chunk_text"]
                )

                connection.execute(
                    text(
                        """
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
                            1,
                            :chunk_index,
                            :chunk_text,
                            :text_hash,
                            CAST(:embedding AS vector)
                        )
                        """
                    ),
                    {
                        "document_id": document_id,
                        "article_id": article_id,
                        "chunk_index": chunk["chunk_index"],
                        "chunk_text": chunk["chunk_text"],
                        "text_hash": source_chunk_hash,
                        "embedding": json.dumps(embedding),
                    },
                )

                inserted_chunks += 1

            inserted_articles += 1
            print(
                f"INDEXED: {title} "
                f"({len(chunks)} chunks)"
            )

    print("\nIndexing complete.")
    print(f"New articles: {inserted_articles}")
    print(f"New chunks: {inserted_chunks}")
    print(f"Skipped articles: {skipped_articles}")


def main() -> int:
    try:
        build_index()
        return 0
    except Exception as exc:
        print(f"Indexing failed: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
