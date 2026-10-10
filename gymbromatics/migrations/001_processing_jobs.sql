CREATE TABLE IF NOT EXISTS processing_jobs (
    session_id UUID PRIMARY KEY,
    status TEXT NOT NULL CHECK (
        status IN ('created', 'uploaded', 'queued', 'processing', 'complete', 'failed')
    ),
    original_filename TEXT NOT NULL,
    content_type TEXT NOT NULL,
    expected_size_bytes BIGINT NOT NULL CHECK (expected_size_bytes > 0),
    input_object_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    declared_checksum_sha256 TEXT,
    checksum_sha256 TEXT,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    error_code TEXT,
    processing_started_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    result_objects JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    CHECK (declared_checksum_sha256 IS NULL OR declared_checksum_sha256 ~ '^[0-9a-f]{64}$'),
    CHECK (checksum_sha256 IS NULL OR checksum_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS processing_jobs_queue_idx
    ON processing_jobs (next_attempt_at, created_at, session_id)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS processing_jobs_lease_idx
    ON processing_jobs (lease_expires_at)
    WHERE status = 'processing';
