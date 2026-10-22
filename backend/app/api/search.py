
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.rag.retriever import retrieve
from backend.app.config import RAG_MIN_SIMILARITY

router = APIRouter()


class SearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    text: str
    source: str
    page_number: int | None
    chunk_index: int
    article_title: str | None
    similarity: float


class SearchResponse(BaseModel):
    question: str
    results: list[SearchResult]


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    try:
        matches = retrieve(request.question, top_k=request.top_k)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Search failed. Check the application logs.",
        ) from exc

    
    # Keep only results that meet the configured relevance threshold.
    matches = [
        item
        for item in matches
        if item["similarity"] >= RAG_MIN_SIMILARITY
    ]

    results = [
        SearchResult(
            text=item["chunk_text"],
            source=item["citation"],
            page_number=item["page_number"],
            chunk_index=item["chunk_index"],
            article_title=item["article_title"],
            similarity=item["similarity"],
        )
        for item in matches
    ]

    return SearchResponse(
        question=request.question,
        results=results,
    )
