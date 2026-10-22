
from backend.app.rag.retriever import retrieve


TEST_CASES = [
    {
        "question": "What are the potential benefits of green tea for weight loss?",
        "expected_url": "green-tea-and-weight-loss",
    },
    {
        "question": "What are the risks of restricting sodium too much?",
        "expected_url": "6-dangers-of-sodium-restriction",
    },
    {
        "question": "What are the health benefits of oats?",
        "expected_url": "/nutrition/foods/oats",
    },
    {
        "question": "How can meditation benefit mental and physical health?",
        "expected_url": "12-benefits-of-meditation",
    },
]


def main() -> None:
    passed = 0

    for test in TEST_CASES:
        question = test["question"]
        expected_url = test["expected_url"]

        print(f"\nQuestion: {question}")

        try:
            results = retrieve(question, top_k=5)
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")
            continue

        if not results:
            print("FAIL: No results returned.")
            continue

        top = results[0]
        citation = top.get("citation") or ""
        score = top.get("similarity", 0.0)

        print(f"Top result: {citation}")
        print(f"Similarity: {score:.4f}")

        if expected_url in citation:
            print("PASS: Expected article retrieved first.")
            passed += 1
        else:
            print("FAIL: Expected article was not retrieved first.")

    print(f"\nResult: {passed}/{len(TEST_CASES)} tests passed.")


if __name__ == "__main__":
    main()
