"""Warehouse schema for Kompass (DuckDB, single file). Path override: KOMPASS_DB."""
import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    return Path(os.environ.get("KOMPASS_DB", ROOT / "data" / "kompass.duckdb"))


SCHEMA = """
-- ---------- Module 1: context layer ----------
CREATE TABLE IF NOT EXISTS accounts (
    account_id      VARCHAR PRIMARY KEY,   -- normalised domain
    name            VARCHAR,
    legal_name_norm VARCHAR,
    domain          VARCHAR UNIQUE,
    country         VARCHAR,
    employees       INTEGER,
    founded         INTEGER,
    ats_provider    VARCHAR,               -- personio | greenhouse | lever | ashby
    ats_slug        VARCHAR,
    segment         VARCHAR,
    segment_confidence VARCHAR,            -- high | medium | low
    segment_evidence_url VARCHAR,          -- page the label was based on
    sells_b2b_industrial BOOLEAN,
    segment_reason  VARCHAR,
    sources         VARCHAR[],
    updated_at      TIMESTAMP DEFAULT now()
);
CREATE TABLE IF NOT EXISTS signals (
    signal_id    VARCHAR PRIMARY KEY,
    account_id   VARCHAR,
    signal_type  VARCHAR,
    title        VARCHAR,
    evidence_url VARCHAR NOT NULL,         -- every signal must cite a source
    evidence_text VARCHAR,
    observed_at  TIMESTAMP,
    confidence   DOUBLE,
    source       VARCHAR,                  -- ats | aeo | manual
    closed_at    TIMESTAMP                 -- set when the posting disappears (role likely filled)
);
CREATE TABLE IF NOT EXISTS account_scores (
    account_id VARCHAR PRIMARY KEY,
    fit_score  INTEGER,
    tier       VARCHAR,
    breakdown  JSON,
    scored_at  TIMESTAMP DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ingest_log (
    run_at TIMESTAMP DEFAULT now(), rows_in INTEGER, rows_merged INTEGER, rows_new INTEGER
);
CREATE TABLE IF NOT EXISTS llm_calls (
    called_at TIMESTAMP DEFAULT now(), purpose VARCHAR, model VARCHAR, mode VARCHAR,
    input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER, ok BOOLEAN
);

-- ---------- Module 2: signal agent ----------
CREATE TABLE IF NOT EXISTS postings (
    posting_id  VARCHAR PRIMARY KEY,       -- provider:slug:id
    account_id  VARCHAR,
    title       VARCHAR,
    location    VARCHAR,
    url         VARCHAR,
    description VARCHAR,
    first_seen  TIMESTAMP DEFAULT now(),
    last_seen   TIMESTAMP DEFAULT now(),
    closed_at   TIMESTAMP,
    classified  BOOLEAN DEFAULT false
);
CREATE TABLE IF NOT EXISTS drafts (
    draft_id       VARCHAR PRIMARY KEY,
    account_id     VARCHAR,
    prompt_name    VARCHAR,
    prompt_version VARCHAR,
    variant        VARCHAR,                -- production | experiment
    model          VARCHAR,
    why_now        JSON,                   -- [{claim, source_id}]
    body           VARCHAR,
    sources        JSON,                   -- {S1: url, ...}
    guard_ok       BOOLEAN,
    guard_issues   JSON,
    play           JSON,                   -- {persona, channel, channel_note}
    status         VARCHAR DEFAULT 'pending',   -- pending | blocked | approved | edited | rejected
    created_at     TIMESTAMP DEFAULT now()
);
CREATE TABLE IF NOT EXISTS reviews (
    draft_id     VARCHAR,
    reviewer     VARCHAR,
    decision     VARCHAR,                  -- approve | edit | reject
    final_body   VARCHAR,
    reason       VARCHAR,
    edit_distance DOUBLE,                  -- 0 = unchanged, 1 = fully rewritten
    reviewed_at  TIMESTAMP DEFAULT now()
);

-- ---------- Module 4: AEO radar ----------
CREATE TABLE IF NOT EXISTS aeo_answers (
    answer_id  VARCHAR PRIMARY KEY,
    run_id     VARCHAR,
    question_id VARCHAR,
    lang       VARCHAR,
    provider   VARCHAR,
    model      VARCHAR,
    repeat_idx INTEGER,
    answer     VARCHAR,
    asked_at   TIMESTAMP DEFAULT now(),
    citations  JSON,                       -- URLs the assistant cited (API field + URLs in text)
    excluded_vendors JSON                  -- vendors named in the question itself (not counted)
);
CREATE TABLE IF NOT EXISTS aeo_mentions (
    answer_id  VARCHAR,
    vendor     VARCHAR,                    -- account_id or competitor id
    position   INTEGER,                    -- 1 = first vendor named
    sentence   VARCHAR
);

-- ---------- Module 5: inbound agent ----------
CREATE TABLE IF NOT EXISTS leads (
    lead_id     VARCHAR PRIMARY KEY,
    received_at TIMESTAMP DEFAULT now(),
    name VARCHAR, email VARCHAR, company VARCHAR, message VARCHAR,
    consent     BOOLEAN,
    is_test     BOOLEAN DEFAULT false,
    converted   BOOLEAN DEFAULT false
);
CREATE TABLE IF NOT EXISTS lead_decisions (
    lead_id    VARCHAR,
    step       VARCHAR,
    detail     JSON,
    decided_at TIMESTAMP DEFAULT now()
);
"""


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if read_only and not path.exists():
        connect().close()
    con = duckdb.connect(str(path), read_only=read_only)
    if not read_only:
        con.execute(SCHEMA)
    return con
