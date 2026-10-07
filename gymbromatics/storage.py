"""Video storage boundary and a filesystem implementation for local use."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import BinaryIO, Protocol
from urllib.parse import quote
from uuid import UUID


class StorageObjectNotFound(FileNotFoundError):
    pass


class UploadTooLarge(ValueError):
    pass


class ChecksumMismatch(ValueError):
    pass


@dataclass(frozen=True)
class UploadTarget:
    object_key: str
    url: str
    method: str
    headers: dict[str, str]
    expires_at: datetime


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    size_bytes: int
    checksum_sha256: str
    content_type: str


class VideoStorage(Protocol):
    """Operations required by the API and worker, independent of cloud vendor."""

    def create_upload_target(
        self,
        session_id: str,
        *,
        filename: str,
        content_type: str,
        expires_in: timedelta,
    ) -> UploadTarget: ...

    def inspect(self, object_key: str) -> StoredObject: ...

    def download(self, object_key: str, destination: Path) -> StoredObject: ...

    def store_result(
        self, session_id: str, *, name: str, source: BinaryIO, content_type: str
    ) -> StoredObject: ...

    def delete_session(self, session_id: str) -> None: ...


class LocalUploadStorage(VideoStorage, Protocol):
    """Development adapter that receives bytes through the local API server."""

    def accept_upload(
        self,
        session_id: str,
        *,
        filename: str,
        source: BinaryIO,
        content_type: str,
        max_bytes: int,
        expected_checksum_sha256: str | None = None,
    ) -> StoredObject: ...


class LocalVideoStorage:
    """Filesystem adapter used for development and deterministic tests."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _session_id(value: str) -> str:
        return str(UUID(value))

    @staticmethod
    def _input_key(session_id: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".mp4", ".mov", ".webm"}:
            suffix = ".video"
        return f"sessions/{session_id}/input/video{suffix}"

    def _path(self, object_key: str) -> Path:
        candidate = (self.root / object_key).resolve()
        if self.root != candidate and self.root not in candidate.parents:
            raise ValueError("object key escapes storage root")
        return candidate

    def create_upload_target(
        self,
        session_id: str,
        *,
        filename: str,
        content_type: str,
        expires_in: timedelta,
    ) -> UploadTarget:
        normalized = self._session_id(session_id)
        key = self._input_key(normalized, filename)
        expires_at = datetime.now(timezone.utc) + expires_in
        return UploadTarget(
            object_key=key,
            url=f"local:///{quote(key)}",
            method="PUT",
            headers={"Content-Type": content_type},
            expires_at=expires_at,
        )

    def accept_upload(
        self,
        session_id: str,
        *,
        filename: str,
        source: BinaryIO,
        content_type: str,
        max_bytes: int,
        expected_checksum_sha256: str | None = None,
    ) -> StoredObject:
        """Local-only equivalent of a browser upload to a signed cloud URL."""

        normalized = self._session_id(session_id)
        key = self._input_key(normalized, filename)
        return self._write(
            key,
            source,
            content_type,
            max_bytes=max_bytes,
            expected_checksum=expected_checksum_sha256,
        )

    def _write(
        self,
        object_key: str,
        source: BinaryIO,
        content_type: str,
        *,
        max_bytes: int | None = None,
        expected_checksum: str | None = None,
    ) -> StoredObject:
        destination = self._path(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + ".uploading")
        digest = hashlib.sha256()
        size = 0
        try:
            with temporary.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    if max_bytes is not None and size > max_bytes:
                        raise UploadTooLarge(f"upload exceeds {max_bytes} bytes")
                    digest.update(chunk)
                    output.write(chunk)
            checksum = digest.hexdigest()
            if expected_checksum and checksum != expected_checksum.lower():
                raise ChecksumMismatch("uploaded file checksum does not match")
            os.replace(temporary, destination)
            stored = StoredObject(object_key, size, checksum, content_type)
            self._metadata_path(destination).write_text(
                json.dumps(asdict(stored), sort_keys=True), encoding="utf-8"
            )
            return stored
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _metadata_path(path: Path) -> Path:
        return path.with_name(path.name + ".metadata.json")

    def inspect(self, object_key: str) -> StoredObject:
        path = self._path(object_key)
        metadata = self._metadata_path(path)
        if not path.is_file() or not metadata.is_file():
            raise StorageObjectNotFound(object_key)
        return StoredObject(**json.loads(metadata.read_text(encoding="utf-8")))

    def download(self, object_key: str, destination: Path) -> StoredObject:
        stored = self.inspect(object_key)
        source = self._path(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as input_file, destination.open("wb") as output:
            while chunk := input_file.read(1024 * 1024):
                output.write(chunk)
        return stored

    def store_result(
        self, session_id: str, *, name: str, source: BinaryIO, content_type: str
    ) -> StoredObject:
        normalized = self._session_id(session_id)
        if not name or Path(name).name != name:
            raise ValueError("result name must be a plain filename")
        return self._write(f"sessions/{normalized}/results/{name}", source, content_type)

    def delete_session(self, session_id: str) -> None:
        normalized = self._session_id(session_id)
        directory = self._path(f"sessions/{normalized}")
        if not directory.exists():
            return
        for path in sorted(directory.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        directory.rmdir()
