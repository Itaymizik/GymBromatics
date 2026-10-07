"""Domain model and state machine for asynchronous video processing jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping
from uuid import UUID, uuid4


class JobStatus(str, Enum):
    CREATED = "created"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


ALLOWED_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = {
    JobStatus.CREATED: frozenset({JobStatus.UPLOADED, JobStatus.FAILED}),
    JobStatus.UPLOADED: frozenset({JobStatus.QUEUED, JobStatus.FAILED}),
    JobStatus.QUEUED: frozenset({JobStatus.PROCESSING, JobStatus.FAILED}),
    # Returning to queued represents a retry after a transient worker failure.
    JobStatus.PROCESSING: frozenset(
        {JobStatus.QUEUED, JobStatus.COMPLETE, JobStatus.FAILED}
    ),
    JobStatus.COMPLETE: frozenset(),
    JobStatus.FAILED: frozenset(),
}


class InvalidJobTransition(ValueError):
    """Raised when a job is moved through an unsupported state transition."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ProcessingJob:
    """Provider-independent record for one uploaded squat video."""

    session_id: str
    status: JobStatus
    original_filename: str
    content_type: str
    expected_size_bytes: int
    input_object_key: str
    created_at: datetime
    updated_at: datetime
    checksum_sha256: str | None = None
    attempt: int = 0
    error_code: str | None = None
    result_objects: Mapping[str, str] = field(default_factory=dict)
    version: int = 1

    def __post_init__(self) -> None:
        UUID(self.session_id)
        if self.expected_size_bytes <= 0:
            raise ValueError("expected_size_bytes must be positive")
        if self.attempt < 0 or self.version < 1:
            raise ValueError("attempt and version must not be negative")
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("job timestamps must be timezone-aware")
        object.__setattr__(self, "result_objects", dict(self.result_objects))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["created_at"] = self.created_at.isoformat()
        payload["updated_at"] = self.updated_at.isoformat()
        payload["schema_version"] = 1
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProcessingJob":
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported job schema version")
        values = dict(payload)
        values.pop("schema_version")
        values["status"] = JobStatus(values["status"])
        values["created_at"] = datetime.fromisoformat(values["created_at"])
        values["updated_at"] = datetime.fromisoformat(values["updated_at"])
        return cls(**values)


def new_processing_job(
    *,
    original_filename: str,
    content_type: str,
    expected_size_bytes: int,
    input_object_key: str,
    session_id: str | None = None,
    now: datetime | None = None,
) -> ProcessingJob:
    timestamp = now or utc_now()
    return ProcessingJob(
        session_id=session_id or str(uuid4()),
        status=JobStatus.CREATED,
        original_filename=original_filename,
        content_type=content_type,
        expected_size_bytes=expected_size_bytes,
        input_object_key=input_object_key,
        created_at=timestamp,
        updated_at=timestamp,
    )


def transition_job(
    job: ProcessingJob,
    target: JobStatus,
    *,
    now: datetime | None = None,
    checksum_sha256: str | None = None,
    error_code: str | None = None,
    result_objects: Mapping[str, str] | None = None,
) -> ProcessingJob:
    """Return the next immutable job state; repeated transitions are idempotent."""

    if target == job.status:
        return job
    if target not in ALLOWED_TRANSITIONS[job.status]:
        raise InvalidJobTransition(f"cannot transition {job.status.value} -> {target.value}")
    if target == JobStatus.UPLOADED and not checksum_sha256:
        raise InvalidJobTransition("uploaded jobs require a checksum")
    if target == JobStatus.FAILED and not error_code:
        raise InvalidJobTransition("failed jobs require an error_code")
    if target == JobStatus.COMPLETE and not result_objects:
        raise InvalidJobTransition("complete jobs require result objects")

    return replace(
        job,
        status=target,
        updated_at=now or utc_now(),
        checksum_sha256=checksum_sha256 or job.checksum_sha256,
        attempt=job.attempt + (1 if target == JobStatus.PROCESSING else 0),
        error_code=error_code if target == JobStatus.FAILED else None,
        result_objects=dict(result_objects or job.result_objects),
        version=job.version + 1,
    )
