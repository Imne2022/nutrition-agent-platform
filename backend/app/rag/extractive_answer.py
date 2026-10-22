
import re


STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being",
    "by", "do", "does", "did", "for", "from", "had", "has", "have",
    "how", "i", "in", "into", "is", "it", "its", "of", "on", "or",
    "that", "the", "their", "this", "to", "was", "were", "what",
    "when", "where", "which", "who", "why", "will", "with", "would",
    "you", "your", "can", "could", "should", "may", "might",
}


def _tokens(text: str) -> set[str]:
    """Return meaningful lowercase words from text."""
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    return {
        word for word in words
        if len(word) > 1 and word not in STOP_WORDS
    }


def build_extractive_answer(
    question: str,
    matches: list[dict],
    min_similarity: float,
    max_sentences: int = 3,
) -> dict:
    """
    Select relevant sentences verbatim from retrieved evidence.
    No generative model or newly composed factual claims are used.
    """
    question_tokens = _tokens(question)

    if not question_tokens:
        return {
            "answer": None,
            "insufficient_evidence": True,
            "sources": [],
        }

    candidates = []

    for match in matches:
        similarity = float(match["similarity"])

        if similarity < min_similarity:
            continue

        chunk = match["chunk_text"].strip()
        sentences = re.split(r"(?<=[.!?])\s+", chunk)

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            sentence_tokens = _tokens(sentence)
            overlap = question_tokens.intersection(sentence_tokens)

            if not overlap:
                continue

            relevance = len(overlap) / len(question_tokens)

            candidates.append({
                "text": sentence,
                "source": match["citation"],
                "article_title": match["article_title"],
                "similarity": similarity,
                "relevance": relevance,
            })

    # Prefer sentences that match the question, then stronger retrieval matches.
    candidates.sort(
        key=lambda item: (
            item["relevance"],
            item["similarity"],
        ),
        reverse=True,
    )

    selected = []
    seen_sentences = set()

    for candidate in candidates:
        normalized = candidate["text"].casefold()

        if normalized in seen_sentences:
            continue

        seen_sentences.add(normalized)
        selected.append(candidate)

        if len(selected) >= max_sentences:
            break

    if not selected:
        return {
            "answer": None,
            "insufficient_evidence": True,
            "sources": [],
        }

    sources = [
        {
            "text": item["text"],
            "source": item["source"],
            "article_title": item["article_title"],
            "similarity": round(item["similarity"], 4),
        }
        for item in selected
    ]

    return {
        "answer": " ".join(item["text"] for item in selected),
        "insufficient_evidence": False,
        "sources": sources,
    }
