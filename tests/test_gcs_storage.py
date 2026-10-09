from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
from datetime import timedelta

import pytest

from gymbromatics.storage import (
    ChecksumMismatch,
    ChecksumRequired,
    GCSVideoStorage,
)


class FakeBlob:
    def __init__(self, name: str) -> None:
        self.name = name
        self.data = b""
        self.size = 0
        self.content_type = "application/octet-stream"
        self.metadata: dict[str, str] = {}
        self.generation = 7
        self.signed_options: dict | None = None
        self.upload_options: dict | None = None
        self.deleted_generation: int | None = None

    def generate_signed_url(self, **options) -> str:
        self.signed_options = options
        return f"https://storage.googleapis.test/signed/{self.name}"

    def reload(self) -> None:
        return None

    def open(self, mode: str):
        assert mode == "rb"
        return BytesIO(self.data)

    def download_to_filename(self, filename: str, **options) -> None:
        assert options == {"checksum": "auto"}
        Path(filename).write_bytes(self.data)

    def upload_from_file(self, source, **options) -> None:
        self.upload_options = options
        self.data = source.read()
        self.size = len(self.data)
        self.content_type = options["content_type"]

    def delete(self, *, if_generation_match: int) -> None:
        self.deleted_generation = if_generation_match


class FakeBucket:
    def __init__(self) -> None:
        self.blobs: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        return self.blobs.setdefault(name, FakeBlob(name))


class FakeClient:
    def __init__(self) -> None:
        self.fake_bucket = FakeBucket()
        self.list_prefix: str | None = None

    def bucket(self, name: str) -> FakeBucket:
        assert name == "videos"
        return self.fake_bucket

    def list_blobs(self, bucket_name: str, *, prefix: str):
        assert bucket_name == "videos"
        self.list_prefix = prefix
        return [blob for name, blob in self.fake_bucket.blobs.items() if name.startswith(prefix)]


def test_gcs_creates_v4_put_url_with_signed_checksum_metadata() -> None:
    client = FakeClient()
    credentials = object()
    storage = GCSVideoStorage(
        "videos", prefix="staging", client=client, signing_credentials=credentials
    )
    session_id = "00000000-0000-0000-0000-000000000001"
    checksum = "a" * 64

    target = storage.create_upload_target(
        session_id,
        filename="squat.mp4",
        content_type="video/mp4",
        expires_in=timedelta(minutes=15),
        checksum_sha256=checksum,
    )

    assert target.object_key == f"sessions/{session_id}/input/video.mp4"
    assert target.url.startswith("https://storage.googleapis.test/signed/staging/")
    assert target.headers == {
        "Content-Type": "video/mp4",
        "x-goog-meta-sha256": checksum,
        "x-goog-if-generation-match": "0",
    }
    blob = client.fake_bucket.blob(f"staging/{target.object_key}")
    assert blob.signed_options == {
        "version": "v4",
        "expiration": timedelta(minutes=15),
        "method": "PUT",
        "content_type": "video/mp4",
        "headers": {
            "x-goog-meta-sha256": checksum,
            "x-goog-if-generation-match": "0",
        },
        "credentials": credentials,
    }

    with pytest.raises(ChecksumRequired):
        storage.create_upload_target(
            session_id,
            filename="squat.mp4",
            content_type="video/mp4",
            expires_in=timedelta(minutes=15),
        )


def test_gcs_inspects_downloads_stores_and_deletes_session(tmp_path: Path) -> None:
    client = FakeClient()
    storage = GCSVideoStorage("videos", prefix="staging", client=client)
    session_id = "00000000-0000-0000-0000-000000000002"
    input_key = f"sessions/{session_id}/input/video.mp4"
    input_blob = client.fake_bucket.blob(f"staging/{input_key}")
    input_blob.data = b"video"
    input_blob.size = 5
    input_blob.content_type = "video/mp4"
    input_blob.metadata = {"sha256": hashlib.sha256(b"video").hexdigest()}

    assert storage.inspect(input_key).size_bytes == 5
    assert storage.open_reader(input_key).read() == b"video"
    destination = tmp_path / "input.mp4"
    storage.download(input_key, destination)
    assert destination.read_bytes() == b"video"

    result = storage.store_result(
        session_id,
        name="dashboard.json",
        source=BytesIO(b"{}"),
        content_type="application/json",
    )
    result_blob = client.fake_bucket.blob(f"staging/{result.object_key}")
    assert result.checksum_sha256 == hashlib.sha256(b"{}").hexdigest()
    assert result_blob.metadata == {"sha256": result.checksum_sha256}
    assert result_blob.upload_options["if_generation_match"] == 0
    assert result_blob.upload_options["checksum"] == "auto"

    storage.delete_session(session_id)
    assert client.list_prefix == f"staging/sessions/{session_id}/"
    assert input_blob.deleted_generation == 7
    assert result_blob.deleted_generation == 7


def test_gcs_rejects_object_without_sha256_metadata() -> None:
    client = FakeClient()
    storage = GCSVideoStorage("videos", client=client)
    key = "sessions/00000000-0000-0000-0000-000000000003/input/video.mp4"
    blob = client.fake_bucket.blob(key)
    blob.size = 5

    with pytest.raises(ChecksumMismatch):
        storage.inspect(key)
