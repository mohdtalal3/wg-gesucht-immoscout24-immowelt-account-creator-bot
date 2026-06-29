-- ─────────────────────────────────────────────────────────────────────────────
-- Account Creator — Supabase Schema
-- Run this in: Supabase Dashboard → SQL Editor → New Query → Run
-- ─────────────────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── accounts ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS created_accounts (
    id          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    email       TEXT        NOT NULL UNIQUE,
    password    TEXT        NOT NULL,
    first_name  TEXT        NOT NULL DEFAULT '',
    last_name   TEXT        NOT NULL DEFAULT '',
    title       TEXT        NOT NULL DEFAULT '',
    platforms   JSONB       NOT NULL DEFAULT '[]'::jsonb,
    status      TEXT        NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_msg   TEXT        NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── bot_runs ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bot_runs (
    id          UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    status      TEXT        NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'completed', 'failed', 'stopped')),
    total       INTEGER     NOT NULL DEFAULT 0,
    completed   INTEGER     NOT NULL DEFAULT 0,
    failed      INTEGER     NOT NULL DEFAULT 0,
    log         TEXT        NOT NULL DEFAULT '',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

-- ── auto-update updated_at ────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION _set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_accounts_updated_at ON created_accounts;
CREATE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON created_accounts
    FOR EACH ROW EXECUTE FUNCTION _set_updated_at();
