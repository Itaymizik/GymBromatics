from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gymbromatics.api import create_app
from gymbromatics.job_repository import LocalJobRepository
from gymbromatics.storage import LocalVideoStorage, StoredObject, UploadTarget


class Provider:
    model = "test-only"

    def generate(self, system, payload, schema):  # pragma: no cover - not used here
        raise AssertionError("the upload flow must not call the LLM")


@pytest.fixture
def upload_api(tmp_path):
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = LocalVideoStorage(tmp_path / "objects")
    app = create_app(
        [Path("demo_artifacts/squatsample_dashboard.html")],
        Provider(),
        video_storage=storage,
        job_repository=repository,
    )
    with TestClient(app, base_url="http://testserver") as client:
        yield client, repository, storage


def create_session(client: TestClient, content: bytes, **changes):
    body = {
        "filename": "squat.mp4",
        "content_type": "video/mp4",
        "size_bytes": len(content),
        "checksum_sha256": hashlib.sha256(content).hexdigest(),
        **changes,
    }
    response = client.post("/api/video-sessions", json=body)
    assert response.status_code == 201
    return response.json()


def test_complete_local_upload_flow(upload_api) -> None:
    client, repository, storage = upload_api
    content = b"fake mp4 bytes"
    created = create_session(client, content)
    session_id = created["session_id"]

    assert created["status"] == "created"
    assert created["upload"]["method"] == "PUT"
    assert created["upload"]["url"].endswith(f"/{session_id}/upload")

    uploaded = client.put(
        created["upload"]["url"],
        content=content,
        headers=created["upload"]["headers"],
    )
    assert uploaded.status_code == 200
    receipt = uploaded.json()
    assert receipt["checksum_sha256"] == hashlib.sha256(content).hexdigest()

    confirmed = client.post(
        f"/api/video-sessions/{session_id}/upload-complete",
        json={
            "size_bytes": receipt["size_bytes"],
            "checksum_sha256": receipt["checksum_sha256"],
        },
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "queued"

    status = client.get(f"/api/video-sessions/{session_id}")
    assert status.status_code == 200
    assert status.json()["status"] == "queued"
    assert repository.get(session_id).checksum_sha256 == receipt["checksum_sha256"]
    assert storage.inspect(repository.get(session_id).input_object_key).size_bytes == len(content)

    # Confirmation is safe to retry after a lost HTTP response.
    repeated = client.post(
        f"/api/video-sessions/{session_id}/upload-complete",
        json={
            "size_bytes": receipt["size_bytes"],
            "checksum_sha256": receipt["checksum_sha256"],
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "queued"


def test_upload_rejects_wrong_type_size_and_checksum(upload_api) -> None:
    client, _, _ = upload_api
    content = b"video"

    wrong_type = create_session(client, content)
    response = client.put(
        wrong_type["upload"]["url"], content=content, headers={"Content-Type": "text/plain"}
    )
    assert response.status_code == 415
    assert response.json() == {"error": "content_type_mismatch"}

    wrong_size = create_session(client, content, size_bytes=len(content) + 1)
    response = client.put(
        wrong_size["upload"]["url"], content=content, headers={"Content-Type": "video/mp4"}
    )
    assert response.status_code == 409
    assert response.json() == {"error": "upload_size_mismatch"}

    wrong_checksum = create_session(client, content, checksum_sha256="0" * 64)
    response = client.put(
        wrong_checksum["upload"]["url"], content=content, headers={"Content-Type": "video/mp4"}
    )
    assert response.status_code == 409
    assert response.json() == {"error": "checksum_mismatch"}


def test_confirmation_requires_uploaded_object_and_matching_metadata(upload_api) -> None:
    client, _, _ = upload_api
    content = b"video"
    created = create_session(client, content)
    session_id = created["session_id"]
    checksum = hashlib.sha256(content).hexdigest()

    missing = client.post(
        f"/api/video-sessions/{session_id}/upload-complete",
        json={"size_bytes": len(content), "checksum_sha256": checksum},
    )
    assert missing.status_code == 409
    assert missing.json() == {"error": "upload_not_found"}

    client.put(
        created["upload"]["url"],
        content=content,
        headers={"Content-Type": "video/mp4"},
    )
    mismatch = client.post(
        f"/api/video-sessions/{session_id}/upload-complete",
        json={"size_bytes": len(content), "checksum_sha256": "f" * 64},
    )
    assert mismatch.status_code == 409
    assert mismatch.json() == {"error": "upload_metadata_mismatch"}


def test_unknown_video_session_is_404(upload_api) -> None:
    client, _, _ = upload_api
    response = client.get("/api/video-sessions/00000000-0000-0000-0000-000000000099")
    assert response.status_code == 404
    assert response.json() == {"error": "video_session_not_found"}


class SignedUploadStorage:
    def __init__(self) -> None:
        self.checksum: str | None = None
        self.object_key = "sessions/signed/input/video.mp4"

    def create_upload_target(self, session_id, **options):
        self.checksum = options["checksum_sha256"]
        self.object_key = f"sessions/{session_id}/input/video.mp4"
        return UploadTarget(
            object_key=self.object_key,
            url="https://storage.googleapis.test/signed-upload",
            method="PUT",
            headers={
                "Content-Type": options["content_type"],
                "x-goog-meta-sha256": self.checksum,
            },
            expires_at=datetime.now(timezone.utc),
        )

    def inspect(self, object_key):
        assert object_key == self.object_key
        return StoredObject(object_key, 5, self.checksum, "video/mp4")

    def open_reader(self, object_key):  # pragma: no cover - unused
        raise AssertionError

    def download(self, object_key, destination):  # pragma: no cover - unused
        raise AssertionError

    def store_result(self, session_id, *, name, source, content_type):  # pragma: no cover
        raise AssertionError

    def delete_session(self, session_id):  # pragma: no cover - unused
        return None


def test_api_returns_provider_signed_upload_url(tmp_path) -> None:
    repository = LocalJobRepository(tmp_path / "jobs")
    storage = SignedUploadStorage()
    app = create_app(
        [Path("demo_artifacts/squatsample_dashboard.html")],
        Provider(),
        video_storage=storage,
        job_repository=repository,
    )
    checksum = hashlib.sha256(b"video").hexdigest()
    with TestClient(app, base_url="https://api.test") as client:
        created = create_session(client, b"video")
        assert created["upload"]["url"] == "https://storage.googleapis.test/signed-upload"
        assert created["upload"]["headers"]["x-goog-meta-sha256"] == checksum
        local_upload = client.put(
            f"/api/video-sessions/{created['session_id']}/upload",
            content=b"video",
            headers={"Content-Type": "video/mp4"},
        )
        assert local_upload.status_code == 404
        confirmed = client.post(
            f"/api/video-sessions/{created['session_id']}/upload-complete",
            json={"size_bytes": 5, "checksum_sha256": checksum},
        )
    assert confirmed.status_code == 200
    assert repository.get(created["session_id"]).status.value == "queued"
