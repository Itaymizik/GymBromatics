"""Job persistence boundary and JSON-file implementation for local use."""

from __future__ import annotations

import json
import os
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
    ) -> ProcessingJob: ...


class LocalJobRepository:
    """Atomic JSON repository intended for one local application process."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

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
        with self._lock:
            if path.exists():
                raise JobAlreadyExists(job.session_id)
            self._write(path, job)
        return job

    def get(self, session_id: str) -> ProcessingJob:
        path = self._path(session_id)
        with self._lock:
            if not path.is_file():
                raise JobNotFound(session_id)
            return ProcessingJob.from_dict(json.loads(path.read_text(encoding="utf-8")))

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
    ) -> ProcessingJob:
        path = self._path(session_id)
        with self._lock:
            current = self.get(session_id)
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
            )
            if updated is not current:
                self._write(path, updated)
            return updated
