from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os

import pytest

from gymbromatics.job_repository import (
    ConcurrentJobUpdate,
    JobAlreadyExists,
    JobNotFound,
)
from gymbromatics.jobs import JobStatus, new_processing_job, utc_now
from gymbromatics.postgres_repository import PostgresJobRepository


@pytest.fixture
def postgres_repository():
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    repository = PostgresJobRepository(database_url, min_size=1, max_size=4)
    with repository.pool.connection() as connection:
        connection.execute("TRUNCATE processing_jobs")
    try:
        yield repository
    finally:
        with repository.pool.connection() as connection:
            connection.execute("TRUNCATE processing_jobs")
        repository.close()


def make_job(*, now=None):
    return new_processing_job(
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=5,
        input_object_key="sessions/input/video.mp4",
        declared_checksum_sha256="a" * 64,
        now=now,
    )


def queue(repository: PostgresJobRepository, job):
    repository.create(job)
    uploaded = repository.transition(
        job.session_id,
        JobStatus.UPLOADED,
        expected_version=job.version,
        checksum_sha256="a" * 64,
    )
    return repository.transition(
        job.session_id, JobStatus.QUEUED, expected_version=uploaded.version
    )


def test_postgres_migration_and_job_lifecycle(postgres_repository) -> None:
    repository = postgres_repository
    job = make_job()
    repository.create(job)

    assert repository.healthcheck()
    assert repository.get(job.session_id) == job
    assert repository.list_by_status(JobStatus.CREATED) == [job]
    with pytest.raises(JobAlreadyExists):
        repository.create(job)
    with pytest.raises(JobNotFound):
        repository.get("00000000-0000-0000-0000-000000000099")

    uploaded = repository.transition(
        job.session_id,
        JobStatus.UPLOADED,
        expected_version=job.version,
        checksum_sha256="b" * 64,
    )
    with pytest.raises(ConcurrentJobUpdate):
        repository.transition(
            job.session_id, JobStatus.QUEUED, expected_version=job.version
        )
    queued = repository.transition(
        job.session_id, JobStatus.QUEUED, expected_version=uploaded.version
    )
    now = utc_now()
    claimed = repository.claim_next_queued(
        now=now, lease_expires_at=now + timedelta(minutes=5)
    )
    assert claimed is not None
    assert claimed.session_id == queued.session_id
    assert claimed.status == JobStatus.PROCESSING
    assert claimed.attempt == 1
    assert claimed.version == queued.version + 1

    complete = repository.transition(
        job.session_id,
        JobStatus.COMPLETE,
        expected_version=claimed.version,
        result_objects={"dashboard_html": "sessions/result/dashboard.html"},
    )
    assert repository.get(job.session_id) == complete


def test_postgres_claim_is_atomic_across_repository_instances(
    postgres_repository,
) -> None:
    first = postgres_repository
    second = PostgresJobRepository(
        os.environ["TEST_DATABASE_URL"], min_size=1, max_size=2
    )
    queued = queue(first, make_job())
    now = utc_now()

    def claim(repository: PostgresJobRepository):
        return repository.claim_next_queued(
            now=now, lease_expires_at=now + timedelta(minutes=5)
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(claim, (first, second)))
    finally:
        second.close()

    successful = [claim for claim in claims if claim is not None]
    assert len(successful) == 1
    assert successful[0].session_id == queued.session_id
    assert first.get(queued.session_id).attempt == 1


def test_postgres_skips_jobs_until_retry_time(postgres_repository) -> None:
    repository = postgres_repository
    now = utc_now()
    queued = queue(repository, make_job(now=now))
    claimed = repository.claim_next_queued(
        now=now, lease_expires_at=now + timedelta(minutes=5)
    )
    retry_at = now + timedelta(minutes=1)
    repository.transition(
        queued.session_id,
        JobStatus.QUEUED,
        expected_version=claimed.version,
        error_code="processing_timeout",
        next_attempt_at=retry_at,
    )

    assert repository.claim_next_queued(
        now=now + timedelta(seconds=30),
        lease_expires_at=now + timedelta(minutes=6),
    ) is None
    assert repository.claim_next_queued(
        now=retry_at,
        lease_expires_at=retry_at + timedelta(minutes=5),
    ) is not None
