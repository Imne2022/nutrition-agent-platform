CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    document_id BIGSERIAL PRIMARY KEY,
    filename TEXT NOT NULL,
    checksum TEXT NOT NULL UNIQUE,
    page_count INTEGER NOT NULL DEFAULT 0,
    source_name TEXT NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS articles (
    article_id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    canonical_url TEXT,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'candidate'
        CHECK (
            review_status IN ('candidate', 'reviewed', 'rejected')
        ),
    topic TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (start_page >= 1),
    CHECK (end_page >= start_page)
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL
        REFERENCES documents(document_id) ON DELETE CASCADE,
    article_id BIGINT
        REFERENCES articles(article_id) ON DELETE SET NULL,
    page_number INTEGER NOT NULL CHECK (page_number >= 1),
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    chunk_text TEXT NOT NULL,
    text_hash TEXT NOT NULL UNIQUE,
    embedding VECTOR(384) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS claims (
    claim_id BIGSERIAL PRIMARY KEY,
    article_id BIGINT
        REFERENCES articles(article_id) ON DELETE CASCADE,
    claim_text TEXT NOT NULL,
    claim_type TEXT,
    source_page INTEGER,
    assessment_status TEXT NOT NULL DEFAULT 'unassessed',
    assessment_notes TEXT
);

CREATE TABLE IF NOT EXISTS nutrition_facts (
    fact_id BIGSERIAL PRIMARY KEY,
    article_id BIGINT
        REFERENCES articles(article_id) ON DELETE CASCADE,
    nutrient_or_topic TEXT NOT NULL,
    value_text TEXT,
    unit TEXT,
    source_page INTEGER,
    verification_status TEXT NOT NULL DEFAULT 'unverified'
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id BIGSERIAL PRIMARY KEY,
    question TEXT,
    status TEXT NOT NULL DEFAULT 'started',
    provider TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_articles_document
    ON articles(document_id);

CREATE INDEX IF NOT EXISTS idx_chunks_article
    ON chunks(article_id);

CREATE INDEX IF NOT EXISTS idx_chunks_page
    ON chunks(page_number);