from backend.app.rag.retriever import retrieve


def main() -> None:
    print("Nutrition PDF semantic retrieval test")
    print("Enter a question, or type 'exit' to stop.")
    while True:
        question = input("\nQuestion: ").strip()
        if question.lower() in {"exit", "quit"}:
            print("Retrieval test finished.")
            break
        if not question:
            print("Please enter a question.")
            continue
        try:
            results = retrieve(question, top_k=5)
        except Exception as exc:
            print(f"Retrieval failed: {type(exc).__name__}: {exc}")
            continue
        if not results:
            print("No matching chunks found. Check the index.")
            continue
        for rank, r in enumerate(results, start=1):
            print(f"\n[{rank}] {r['citation']}")
            print(f"Similarity score: {r['similarity']:.4f}")
            print(f"Article: {r.get('article_title') or 'Unassigned'}")
            print(r["chunk_text"])


if __name__ == "__main__":
    main()