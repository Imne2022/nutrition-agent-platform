
from backend.app.ml.embeddings import embed_query, embed_texts


def main():
    vectors = embed_texts([
        "Dietary fiber occurs in plant foods.",
        "Protein contributes to muscle maintenance.",
    ])
    assert len(vectors) == 2
    assert all(len(vector) == 384 for vector in vectors)

    query_vector = embed_query("Which foods contain dietary fiber?")
    assert len(query_vector) == 384

    print("PASS: embedding model works.")
    print(f"Vector dimensions: {len(query_vector)}")


if __name__ == "__main__":
    main()
