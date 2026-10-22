
from fastapi import FastAPI

from backend.app.api.search import router as search_router
from backend.app.api.answer import router as answer_router

app = FastAPI(
    title="Nutrition Evidence API",
    version="0.1.0",
    description="Semantic search over the indexed nutrition evidence.",
)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(search_router, prefix="/api", tags=["Search"])
app.include_router(answer_router, prefix="/api", tags=["Answer"])