
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.config import RAG_MIN_SIMILARITY
from backend.app.rag.extractive_answer import build_extractive_answer
from backend.app.rag.retriever import retrieve

router = APIRouter()


class AnswerRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class AnswerSource(BaseModel):
    text: str
    source: str
    article_title: str | None
    similarity: float


class AnswerResponse(BaseModel):
    question: str
    answer: str | None
    insufficient_evidence: bool
    sources: list[AnswerSource]


@router.post("/answer", response_model=AnswerResponse)
def answer(request: AnswerRequest) -> AnswerResponse:
    try:
        matches = retrieve(
            request.question,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Answer retrieval failed. Check the application logs.",
        ) from exc

    result = build_extractive_answer(
        question=request.question,
        matches=matches,
        min_similarity=RAG_MIN_SIMILARITY,
    )

    return AnswerResponse(
        question=request.question,
        answer=result["answer"],
        insufficient_evidence=result["insufficient_evidence"],
        sources=[
            AnswerSource(**source)
            for source in result["sources"]
        ],
    )
