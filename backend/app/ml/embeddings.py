
from functools import lru_cache

import numpy as np
from sentence_transformers import SentenceTransformer

from backend.app.config import EMBEDDING_MODEL


EXPECTED_DIMENSIONS = 384


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    model = SentenceTransformer(EMBEDDING_MODEL)
    #dimensions = model.get_sentence_embedding_dimension()
    dimensions = model.get_embedding_dimension()

    if dimensions != EXPECTED_DIMENSIONS:
        raise ValueError(
            f"Expected 384 dimensions, received {dimensions}"
        )

    return model


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    if any(not isinstance(t, str) or not t.strip() for t in texts):
        raise ValueError("All texts must be non-empty strings")

    vectors = get_model().encode(
        texts,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    vectors = np.asarray(vectors, dtype=np.float32)

    if vectors.ndim != 2 or vectors.shape[1] != 384:
        raise ValueError(f"Unexpected embedding shape: {vectors.shape}")

    return vectors.tolist()


def embed_query(question: str) -> list[float]:
    if not question or not question.strip():
        raise ValueError("Question must not be empty")

    return embed_texts([question.strip()])[0]
