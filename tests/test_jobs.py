from datetime import datetime, timezone

import pytest

from gymbromatics.jobs import (
    InvalidJobTransition,
    JobStatus,
    ProcessingJob,
    new_processing_job,
    transition_job,
)


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_job() -> ProcessingJob:
    return new_processing_job(
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=123,
        input_object_key="sessions/input.mp4",
        now=NOW,
    )


def test_happy_path_preserves_upload_metadata_and_counts_attempts() -> None:
    job = make_job()
    job = transition_job(job, JobStatus.UPLOADED, checksum_sha256="a" * 64)
    job = transition_job(job, JobStatus.QUEUED)
    job = transition_job(job, JobStatus.PROCESSING)
    job = transition_job(
        job,
        JobStatus.COMPLETE,
        result_objects={"dashboard": "sessions/result.html"},
    )

    assert job.status == JobStatus.COMPLETE
    assert job.attempt == 1
    assert job.checksum_sha256 == "a" * 64
    assert job.result_objects["dashboard"].endswith("result.html")
    assert job.version == 5


def test_processing_job_can_return_to_queue_for_retry() -> None:
    job = transition_job(make_job(), JobStatus.UPLOADED, checksum_sha256="b" * 64)
    job = transition_job(job, JobStatus.QUEUED)
    job = transition_job(job, JobStatus.PROCESSING)
    job = transition_job(job, JobStatus.QUEUED)
    job = transition_job(job, JobStatus.PROCESSING)

    assert job.attempt == 2


def test_same_state_is_idempotent() -> None:
    job = make_job()
    assert transition_job(job, JobStatus.CREATED) is job


@pytest.mark.parametrize(
    ("target", "kwargs"),
    [
        (JobStatus.COMPLETE, {"result_objects": {"dashboard": "result.html"}}),
        (JobStatus.UPLOADED, {}),
        (JobStatus.FAILED, {}),
    ],
)
def test_invalid_or_incomplete_transition_is_rejected(
    target: JobStatus, kwargs: dict[str, object]
) -> None:
    with pytest.raises(InvalidJobTransition):
        transition_job(make_job(), target, **kwargs)


def test_serialization_round_trip() -> None:
    job = make_job()
    assert ProcessingJob.from_dict(job.to_dict()) == job
