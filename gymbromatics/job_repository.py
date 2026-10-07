"""Job persistence boundary and JSON-file implementation for local use."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import threading
from typing import Mapping, Protocol
from uuid import UUID

from .jobs import JobStatus, ProcessingJob, transition_job


class JobNotFound(KeyError):
    pass


class JobAlreadyExists(ValueError):
    pass


class ConcurrentJobUpdate(RuntimeError):
    pass


class JobRepository(Protocol):
    """Persistence contract with optimistic concurrency for worker safety."""

    def create(self, job: ProcessingJob) -> ProcessingJob: ...

    def get(self, session_id: str) -> ProcessingJob: ...

    def list_by_status(
        self, status: JobStatus, *, limit: int | None = None
    ) -> list[ProcessingJob]: ...

    def claim_next_queued(
        self, *, now: datetime, lease_expires_at: datetime
    ) -> ProcessingJob | None: ...

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
    ) -> ProcessingJob: ...


class LocalJobRepository:
    """Atomic JSON repository intended for one local application process."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._lock_path = self.root / ".repository.lock"

    @contextmanager
    def _exclusive(self):
        """Serialize read-modify-write operations across threads and processes."""
        with self._lock:
            with self._lock_path.open("a+b") as handle:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0, os.SEEK_END)
                    if handle.tell() == 0:
                        handle.write(b"0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                    try:
                        yield
                    finally:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                    try:
                        yield
                    finally:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _path(self, session_id: str) -> Path:
        normalized = str(UUID(session_id))
        return self.root / f"{normalized}.json"

    @staticmethod
    def _write(path: Path, job: ProcessingJob) -> None:
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    def create(self, job: ProcessingJob) -> ProcessingJob:
        path = self._path(job.session_id)
        with self._exclusive():
            if path.exists():
                raise JobAlreadyExists(job.session_id)
            self._write(path, job)
        return job

    def _get_unlocked(self, session_id: str) -> ProcessingJob:
        path = self._path(session_id)
        if not path.is_file():
            raise JobNotFound(session_id)
        return ProcessingJob.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def get(self, session_id: str) -> ProcessingJob:
        with self._exclusive():
            return self._get_unlocked(session_id)

    def list_by_status(
        self, status: JobStatus, *, limit: int | None = None
    ) -> list[ProcessingJob]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        with self._exclusive():
            jobs = self._list_unlocked()
        matches = sorted(
            (job for job in jobs if job.status == status),
            key=lambda job: (job.created_at, job.session_id),
        )
        return matches[:limit] if limit is not None else matches

    def _list_unlocked(self) -> list[ProcessingJob]:
        return [
            ProcessingJob.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in self.root.glob("*.json")
        ]

    def claim_next_queued(
        self, *, now: datetime, lease_expires_at: datetime
    ) -> ProcessingJob | None:
        if now.tzinfo is None or lease_expires_at.tzinfo is None:
            raise ValueError("claim timestamps must be timezone-aware")
        if lease_expires_at <= now:
            raise ValueError("lease must expire after claim time")
        with self._exclusive():
            candidates = sorted(
                (
                    job
                    for job in self._list_unlocked()
                    if job.status == JobStatus.QUEUED
                    and (job.next_attempt_at is None or job.next_attempt_at <= now)
                ),
                key=lambda job: (job.created_at, job.session_id),
            )
            if not candidates:
                return None
            current = candidates[0]
            claimed = transition_job(
                current,
                JobStatus.PROCESSING,
                now=now,
                lease_expires_at=lease_expires_at,
            )
            self._write(self._path(claimed.session_id), claimed)
            return claimed

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
        path = self._path(session_id)
        with self._exclusive():
            current = self._get_unlocked(session_id)
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
            if updated is not current:
                self._write(path, updated)
            return updated
