from __future__ import annotations

from io import BytesIO
from pathlib import Path
import time
from datetime import timedelta

from fastapi.testclient import TestClient

from gymbromatics.api import create_app
from gymbromatics.job_repository import LocalJobRepository
from gymbromatics.jobs import JobStatus, new_processing_job, utc_now
from gymbromatics.storage import LocalVideoStorage
from gymbromatics.worker import Artifact, LocalJobWorker


class FakeProcessor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.inputs: list[bytes] = []

    def process(self, input_path: Path, output_dir: Path):
        self.inputs.append(input_path.read_bytes())
        if self.fail:
            raise ValueError("invalid test video")
        output_dir.mkdir(parents=True)
        values = {
            "annotated_video": ("annotated_video.mp4", b"annotated", "video/mp4"),
            "analysis_json": ("analysis.json", b'{"frames": []}', "application/json"),
            "dashboard_html": ("dashboard.html", b"<html></html>", "text/html"),
            "dashboard_json": ("dashboard.json", b'{"samples": []}', "application/json"),
        }
        artifacts = {}
        for name, (filename, content, content_type) in values.items():
            path = output_dir / filename
            path.write_bytes(content)
            artifacts[name] = Artifact(path, content_type)
        return artifacts


class SlowProcessor:
    def process(self, input_path: Path, output_dir: Path):
        time.sleep(5)
        return {}


class LeaseLosingProcessor(FakeProcessor):
    def __init__(self, repository) -> None:
        super().__init__()
        self.repository = repository

    def process(self, input_path: Path, output_dir: Path):
        current = self.repository.list_by_status(JobStatus.PROCESSING)[0]
        self.repository.transition(
            current.session_id,
            JobStatus.QUEUED,
            expected_version=current.version,
            error_code="processing_timeout",
            next_attempt_at=utc_now(),
        )
        return super().process(input_path, output_dir)


class Provider:
    model = "test-only"

    def generate(self, system, payload, schema):  # pragma: no cover
        raise AssertionError("worker result downloads must not call the LLM")


def queued_job(repository, storage, content=b"video"):
    provisional = new_processing_job(
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=len(content),
        input_object_key="placeholder",
    )
    stored = storage.accept_upload(
        provisional.session_id,
        filename="squat.mp4",
        source=BytesIO(content),
        content_type="video/mp4",
        max_bytes=len(content),
    )
    job = new_processing_job(
        session_id=provisional.session_id,
        original_filename="squat.mp4",
        content_type="video/mp4",
        expected_size_bytes=len(content),
        input_object_key=stored.object_key,
    )
    repository.create(job)
    job = repository.transition(
        job.session_id,
        JobStatus.UPLOADED,
        expected_version=job.version,
        checksum_sha256=stored.checksum_sha256,
    )
    return repository.transition(
        job.session_id, JobStatus.QUEUED, expected_version=job.version
    )


def test_worker_processes_oldest_job_and_stores_all_results(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    queued = queued_job(repository, storage)
    processor = FakeProcessor()
    worker = LocalJobWorker(
        repository,
        storage,
        processor,
        workspace=tmp_path / "work",
        use_subprocess=False,
    )

    completed = worker.run_once()

    assert completed is not None
    assert completed.status == JobStatus.COMPLETE
    assert completed.attempt == 1
    assert set(completed.result_objects) == {
        "annotated_video",
        "analysis_json",
        "dashboard_html",
        "dashboard_json",
    }
    assert processor.inputs == [b"video"]
    assert repository.list_by_status(JobStatus.QUEUED) == []
    for object_key in completed.result_objects.values():
        assert storage.inspect(object_key).size_bytes > 0
    assert list((tmp_path / "work").iterdir()) == []
    assert repository.get(queued.session_id) == completed


def test_worker_records_sanitized_failure_and_continues(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    queued = queued_job(repository, storage)
    worker = LocalJobWorker(
        repository,
        storage,
        FakeProcessor(fail=True),
        workspace=tmp_path / "work",
        max_attempts=1,
        use_subprocess=False,
    )

    failed = worker.run_once()

    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.error_code == "video_processing_error"
    assert repository.get(queued.session_id).status == JobStatus.FAILED
    assert worker.run_once() is None


def test_completed_results_are_downloadable_through_api(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    queued = queued_job(repository, storage)
    worker = LocalJobWorker(
        repository,
        storage,
        FakeProcessor(),
        workspace=tmp_path / "work",
        use_subprocess=False,
    )
    worker.run_once()
    app = create_app(
        [Path("demo_artifacts/squatsample_dashboard.html")],
        Provider(),
        video_storage=storage,
        job_repository=repository,
    )

    with TestClient(app, base_url="http://testserver") as client:
        response = client.get(f"/api/video-sessions/{queued.session_id}")
        assert response.status_code == 200
        result_urls = response.json()["result_urls"]
        assert set(result_urls) == {
            "annotated_video",
            "analysis_json",
            "dashboard_html",
            "dashboard_json",
        }
        dashboard = client.get(result_urls["dashboard_html"])
        assert dashboard.status_code == 200
        assert dashboard.text == "<html></html>"


def test_worker_retries_with_backoff_then_fails_at_attempt_limit(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    queued = queued_job(repository, storage)
    worker = LocalJobWorker(
        repository,
        storage,
        FakeProcessor(fail=True),
        workspace=tmp_path / "work",
        max_attempts=2,
        backoff_seconds=0,
        use_subprocess=False,
    )

    retry = worker.run_once()
    assert retry is not None
    assert retry.status == JobStatus.QUEUED
    assert retry.attempt == 1
    assert retry.error_code == "video_processing_error"

    failed = worker.run_once()
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.attempt == 2
    assert failed.error_code == "video_processing_error"
    assert repository.get(queued.session_id) == failed


def test_worker_terminates_timed_out_processor(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    queued = queued_job(repository, storage)
    worker = LocalJobWorker(
        repository,
        storage,
        SlowProcessor(),
        workspace=tmp_path / "work",
        timeout_seconds=0.1,
        lease_seconds=1,
        max_attempts=1,
    )

    started = time.monotonic()
    failed = worker.run_once()

    assert time.monotonic() - started < 3
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert failed.error_code == "processing_timeout"
    assert repository.get(queued.session_id).status == JobStatus.FAILED


def test_worker_recovers_expired_processing_lease(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    queued_job(repository, storage)
    past = utc_now() - timedelta(minutes=2)
    claimed = repository.claim_next_queued(
        now=past, lease_expires_at=past + timedelta(seconds=1)
    )
    assert claimed is not None and claimed.status == JobStatus.PROCESSING
    worker = LocalJobWorker(
        repository,
        storage,
        FakeProcessor(),
        workspace=tmp_path / "work",
        max_attempts=2,
        backoff_seconds=0,
        use_subprocess=False,
    )

    recovered = worker.recover_stale(now=utc_now())

    assert len(recovered) == 1
    assert recovered[0].status == JobStatus.QUEUED
    assert recovered[0].error_code == "processing_timeout"
    completed = worker.run_once()
    assert completed is not None
    assert completed.status == JobStatus.COMPLETE
    assert completed.attempt == 2


def test_worker_does_not_overwrite_job_after_losing_lease(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    queued = queued_job(repository, storage)
    worker = LocalJobWorker(
        repository,
        storage,
        LeaseLosingProcessor(repository),
        workspace=tmp_path / "work",
        use_subprocess=False,
    )

    current = worker.run_once()

    assert current is not None
    assert current.status == JobStatus.QUEUED
    assert current.error_code == "processing_timeout"
    assert repository.get(queued.session_id) == current
