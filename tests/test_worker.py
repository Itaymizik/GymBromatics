from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from gymbromatics.api import create_app
from gymbromatics.job_repository import LocalJobRepository
from gymbromatics.jobs import JobStatus, new_processing_job
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
        repository, storage, processor, workspace=tmp_path / "work"
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
        repository, storage, FakeProcessor(fail=True), workspace=tmp_path / "work"
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
        repository, storage, FakeProcessor(), workspace=tmp_path / "work"
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
