from datetime import timedelta
from io import BytesIO

import pytest

from gymbromatics.job_repository import (
    ConcurrentJobUpdate,
    JobAlreadyExists,
    LocalJobRepository,
)
from gymbromatics.jobs import JobStatus, new_processing_job
from gymbromatics.storage import (
    ChecksumMismatch,
    LocalVideoStorage,
    UploadTooLarge,
)


def make_job(session_id: str, input_key: str):
    return new_processing_job(
        session_id=session_id,
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=5,
        input_object_key=input_key,
    )


def test_local_storage_upload_inspect_download_and_result(tmp_path) -> None:
    job = new_processing_job(
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=5,
        input_object_key="placeholder",
    )
    storage = LocalVideoStorage(tmp_path / "objects")
    target = storage.create_upload_target(
        job.session_id,
        filename="../../squat.mp4",
        content_type="video/mp4",
        expires_in=timedelta(minutes=10),
    )
    stored = storage.accept_upload(
        job.session_id,
        filename="squat.mp4",
        source=BytesIO(b"video"),
        content_type="video/mp4",
        max_bytes=10,
    )

    assert target.object_key == stored.object_key
    assert storage.inspect(stored.object_key) == stored
    destination = tmp_path / "download.mp4"
    storage.download(stored.object_key, destination)
    assert destination.read_bytes() == b"video"

    result = storage.store_result(
        job.session_id,
        name="dashboard.json",
        source=BytesIO(b"{}"),
        content_type="application/json",
    )
    assert storage.inspect(result.object_key).size_bytes == 2


def test_failed_local_upload_leaves_no_partial_object(tmp_path) -> None:
    storage = LocalVideoStorage(tmp_path / "objects")
    job = new_processing_job(
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=5,
        input_object_key="placeholder",
    )
    with pytest.raises(UploadTooLarge):
        storage.accept_upload(
            job.session_id,
            filename="squat.mp4",
            source=BytesIO(b"too large"),
            content_type="video/mp4",
            max_bytes=3,
        )
    with pytest.raises(ChecksumMismatch):
        storage.accept_upload(
            job.session_id,
            filename="squat.mp4",
            source=BytesIO(b"video"),
            content_type="video/mp4",
            max_bytes=10,
            expected_checksum_sha256="0" * 64,
        )
    assert not list((tmp_path / "objects").rglob("*.uploading"))
    assert not list((tmp_path / "objects").rglob("video.mp4"))


def test_repository_persists_and_rejects_stale_updates(tmp_path) -> None:
    storage = LocalVideoStorage(tmp_path / "objects")
    provisional = new_processing_job(
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=5,
        input_object_key="placeholder",
    )
    target = storage.create_upload_target(
        provisional.session_id,
        filename="squat.mp4",
        content_type="video/mp4",
        expires_in=timedelta(minutes=10),
    )
    job = make_job(provisional.session_id, target.object_key)
    repository = LocalJobRepository(tmp_path / "jobs")
    repository.create(job)

    with pytest.raises(JobAlreadyExists):
        repository.create(job)

    uploaded = repository.transition(
        job.session_id,
        JobStatus.UPLOADED,
        expected_version=1,
        checksum_sha256="c" * 64,
    )
    reloaded = LocalJobRepository(tmp_path / "jobs").get(job.session_id)
    assert reloaded == uploaded

    with pytest.raises(ConcurrentJobUpdate):
        repository.transition(
            job.session_id,
            JobStatus.QUEUED,
            expected_version=1,
        )
