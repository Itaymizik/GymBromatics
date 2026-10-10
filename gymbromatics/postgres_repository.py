"""PostgreSQL implementation of the processing-job repository."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping
from uuid import UUID

from .job_repository import (
    ConcurrentJobUpdate,
    JobAlreadyExists,
    JobNotFound,
)
from .jobs import JobStatus, ProcessingJob, transition_job


MIGRATIONS = ((1, Path(__file__).with_name("migrations") / "001_processing_jobs.sql"),)
MIGRATION_LOCK_ID = 1_948_263_117


class PostgresJobRepository:
    """Shared repository with transactions, optimistic versions and atomic claims."""

    def __init__(
        self,
        database_url: str,
        *,
        min_size: int = 1,
        max_size: int = 5,
        migrate: bool = True,
    ) -> None:
        if not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection URL")
        if min_size < 0 or max_size < 1 or min_size > max_size:
            raise ValueError("invalid PostgreSQL pool size")
        try:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
        except ImportError as error:  # pragma: no cover - deployment guard
            raise RuntimeError("psycopg[binary,pool] is required for PostgreSQL") from error
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row},
            open=True,
        )
        self.pool.wait(timeout=15)
        if migrate:
            self.migrate()

    def migrate(self) -> None:
        with self.pool.connection() as connection:
            with connection.transaction():
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (MIGRATION_LOCK_ID,))
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                applied = {
                    row["version"]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations"
                    ).fetchall()
                }
                for version, path in MIGRATIONS:
                    if version in applied:
                        continue
                    connection.execute(path.read_text(encoding="utf-8"))
                    connection.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)",
                        (version,),
                    )

    @staticmethod
    def _job(row: Mapping[str, Any]) -> ProcessingJob:
        values = dict(row)
        values["session_id"] = str(values["session_id"])
        values["status"] = JobStatus(values["status"])
        values["result_objects"] = dict(values["result_objects"] or {})
        return ProcessingJob(**values)

    @staticmethod
    def _parameters(job: ProcessingJob) -> dict[str, Any]:
        return {
            "session_id": UUID(job.session_id),
            "status": job.status.value,
            "original_filename": job.original_filename,
            "content_type": job.content_type,
            "expected_size_bytes": job.expected_size_bytes,
            "input_object_key": job.input_object_key,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "declared_checksum_sha256": job.declared_checksum_sha256,
            "checksum_sha256": job.checksum_sha256,
            "attempt": job.attempt,
            "error_code": job.error_code,
            "processing_started_at": job.processing_started_at,
            "lease_expires_at": job.lease_expires_at,
            "next_attempt_at": job.next_attempt_at,
            "result_objects": json.dumps(dict(job.result_objects)),
            "version": job.version,
        }

    def create(self, job: ProcessingJob) -> ProcessingJob:
        parameters = self._parameters(job)
        try:
            with self.pool.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO processing_jobs (
                        session_id, status, original_filename, content_type,
                        expected_size_bytes, input_object_key, created_at, updated_at,
                        declared_checksum_sha256, checksum_sha256, attempt, error_code,
                        processing_started_at, lease_expires_at, next_attempt_at,
                        result_objects, version
                    ) VALUES (
                        %(session_id)s, %(status)s, %(original_filename)s, %(content_type)s,
                        %(expected_size_bytes)s, %(input_object_key)s, %(created_at)s,
                        %(updated_at)s, %(declared_checksum_sha256)s, %(checksum_sha256)s,
                        %(attempt)s, %(error_code)s, %(processing_started_at)s,
                        %(lease_expires_at)s, %(next_attempt_at)s,
                        %(result_objects)s::jsonb, %(version)s
                    )
                    """,
                    parameters,
                )
        except Exception as error:
            if getattr(error, "sqlstate", None) == "23505":
                raise JobAlreadyExists(job.session_id) from error
            raise
        return job

    def get(self, session_id: str) -> ProcessingJob:
        normalized = UUID(session_id)
        with self.pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM processing_jobs WHERE session_id = %s", (normalized,)
            ).fetchone()
        if row is None:
            raise JobNotFound(session_id)
        return self._job(row)

    def list_by_status(
        self, status: JobStatus, *, limit: int | None = None
    ) -> list[ProcessingJob]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        query = (
            "SELECT * FROM processing_jobs WHERE status = %s "
            "ORDER BY created_at, session_id"
        )
        parameters: tuple[Any, ...] = (status.value,)
        if limit is not None:
            query += " LIMIT %s"
            parameters += (limit,)
        with self.pool.connection() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._job(row) for row in rows]

    def claim_next_queued(
        self, *, now: datetime, lease_expires_at: datetime
    ) -> ProcessingJob | None:
        if now.tzinfo is None or lease_expires_at.tzinfo is None:
            raise ValueError("claim timestamps must be timezone-aware")
        if lease_expires_at <= now:
            raise ValueError("lease must expire after claim time")
        with self.pool.connection() as connection:
            with connection.transaction():
                row = connection.execute(
                    """
                    WITH candidate AS (
                        SELECT session_id
                        FROM processing_jobs
                        WHERE status = 'queued'
                          AND (next_attempt_at IS NULL OR next_attempt_at <= %(now)s)
                        ORDER BY created_at, session_id
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE processing_jobs AS job
                    SET status = 'processing',
                        updated_at = %(now)s,
                        processing_started_at = %(now)s,
                        lease_expires_at = %(lease_expires_at)s,
                        next_attempt_at = NULL,
                        error_code = NULL,
                        attempt = job.attempt + 1,
                        version = job.version + 1
                    FROM candidate
                    WHERE job.session_id = candidate.session_id
                    RETURNING job.*
                    """,
                    {"now": now, "lease_expires_at": lease_expires_at},
                ).fetchone()
        return self._job(row) if row is not None else None

    def transition(
        self,
        session_id: str,
        target: JobStatus,
        *,
        expected_version: int,
        now: datetime | None = None,
        checksum_sha256: str | None = None,
        error_code: str | None = None,
        result_objects: Mapping[str, str] | None = None,
        lease_expires_at: datetime | None = None,
        next_attempt_at: datetime | None = None,
    ) -> ProcessingJob:
        normalized = UUID(session_id)
        with self.pool.connection() as connection:
            with connection.transaction():
                row = connection.execute(
                    "SELECT * FROM processing_jobs WHERE session_id = %s FOR UPDATE",
                    (normalized,),
                ).fetchone()
                if row is None:
                    raise JobNotFound(session_id)
                current = self._job(row)
                if current.version != expected_version:
                    raise ConcurrentJobUpdate(
                        f"expected version {expected_version}, found {current.version}"
                    )
                updated = transition_job(
                    current,
                    target,
                    now=now,
                    checksum_sha256=checksum_sha256,
                    error_code=error_code,
                    result_objects=result_objects,
                    lease_expires_at=lease_expires_at,
                    next_attempt_at=next_attempt_at,
                )
                if updated is current:
                    return current
                parameters = self._parameters(updated)
                result = connection.execute(
                    """
                    UPDATE processing_jobs SET
                        status = %(status)s,
                        updated_at = %(updated_at)s,
                        checksum_sha256 = %(checksum_sha256)s,
                        attempt = %(attempt)s,
                        error_code = %(error_code)s,
                        processing_started_at = %(processing_started_at)s,
                        lease_expires_at = %(lease_expires_at)s,
                        next_attempt_at = %(next_attempt_at)s,
                        result_objects = %(result_objects)s::jsonb,
                        version = %(version)s
                    WHERE session_id = %(session_id)s AND version = %(expected_version)s
                    RETURNING *
                    """,
                    {**parameters, "expected_version": expected_version},
                ).fetchone()
                if result is None:
                    raise ConcurrentJobUpdate(session_id)
                return self._job(result)

    def healthcheck(self) -> bool:
        try:
            with self.pool.connection(timeout=2) as connection:
                return connection.execute("SELECT 1").fetchone() is not None
        except Exception:
            return False

    def close(self) -> None:
        self.pool.close()
