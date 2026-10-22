import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

RAW_DIR = ROOT_DIR / "data" / "raw"
PROCESSED_DIR = ROOT_DIR / "data" / "processed"

PDF_PATH = (
    RAW_DIR
    / "nutrition_directory.pdf"
)

PAGES_PATH = PROCESSED_DIR / "pages.jsonl"
MANIFEST_PATH = PROCESSED_DIR / "manifest.json"
ARTICLES_REVIEW_PATH = PROCESSED_DIR / "articles_review.json"

# Web article ingestion
ARTICLE_LINKS_PATH = PROCESSED_DIR / "article_links.json"
ARTICLES_RAW_PATH = PROCESSED_DIR / "articles_raw.jsonl"

DATABASE_URL = os.getenv("DATABASE_URL", "")

EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/all-MiniLM-L6-v2",
)

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "hosted").lower()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
TOP_K = int(os.getenv("TOP_K", "5"))
RAG_MIN_SIMILARITY = float(
    os.getenv("RAG_MIN_SIMILARITY", "0.35")
)