
from sqlalchemy import create_engine, text

from backend.app.config import DATABASE_URL, TOP_K
from backend.app.ml.embeddings import embed_query


def retrieve(question: str, top_k: int | None = None) -> list[dict]:
    """Retrieve relevant chunks from all indexed sources."""
    if not question or not question.strip():
        raise ValueError("Question must not be empty.")

    limit = TOP_K if top_k is None else top_k
    if not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("top_k must be an integer between 1 and 100.")

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is missing from .env")

    vector = embed_query(question.strip())
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

    sql = text("""
        SELECT
            c.chunk_id,
            c.page_number,
            c.chunk_index,
            c.chunk_text,
            a.title AS article_title,
            a.canonical_url,
            d.filename,
            1 - (c.embedding <=> CAST(:q AS vector)) AS similarity
        FROM chunks c
        JOIN documents d ON d.document_id = c.document_id
        LEFT JOIN articles a ON a.article_id = c.article_id
        ORDER BY c.embedding <=> CAST(:q AS vector)
        LIMIT :k
    """)

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sql,
                {"q": str(vector), "k": limit},
            ).mappings().all()
    finally:
        engine.dispose()

    results = []

    for row in rows:
        url = row["canonical_url"]

        # Web articles have no verified PDF page numbers.
        citation = (
            url
            if url
            else f"{row['filename']} p.{row['page_number']}"
        )

        results.append({
            "chunk_id": row["chunk_id"],
            "page_number": row["page_number"] if not url else None,
            "chunk_index": row["chunk_index"],
            "chunk_text": row["chunk_text"],
            "article_title": row["article_title"],
            "citation": citation,
            "canonical_url": url,
            "similarity": float(row["similarity"]),
        })

    return results
