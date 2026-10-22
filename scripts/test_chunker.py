
from backend.app.ingestion.chunker import (
    chunk_page,
    split_text,
    text_hash,
)


def main():
    assert split_text("") == []
    assert split_text("   ") == []

    sample = "Dietary fiber occurs in plant foods."
    assert split_text(sample, 100, 10) == [sample]

    long_text = " ".join(
        f"Nutrition sentence {i}." for i in range(200)
    )
    chunks = split_text(long_text, 300, 50)

    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)

    records = chunk_page(7, long_text, 300, 50)
    assert all(record["page_number"] == 7 for record in records)
    assert [r["chunk_index"] for r in records] == list(
        range(len(records))
    )
    assert len(text_hash("test")) == 64

    print(f"PASS: chunker created {len(chunks)} test chunks.")


if __name__ == "__main__":
    main()
