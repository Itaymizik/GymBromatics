"""Video storage boundary and a filesystem implementation for local use."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO, Mapping, Protocol, runtime_checkable
from urllib.parse import quote
from uuid import UUID


class StorageObjectNotFound(FileNotFoundError):
    pass


class UploadTooLarge(ValueError):
    pass


class ChecksumMismatch(ValueError):
    pass


class ChecksumRequired(ValueError):
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
        checksum_sha256: str | None = None,
    ) -> UploadTarget: ...

    def inspect(self, object_key: str) -> StoredObject: ...

    def open_reader(self, object_key: str) -> BinaryIO: ...

    def download(self, object_key: str, destination: Path) -> StoredObject: ...

    def store_result(
        self, session_id: str, *, name: str, source: BinaryIO, content_type: str
    ) -> StoredObject: ...

    def delete_session(self, session_id: str) -> None: ...


@runtime_checkable
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
        checksum_sha256: str | None = None,
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

    def open_reader(self, object_key: str) -> BinaryIO:
        self.inspect(object_key)
        return self._path(object_key).open("rb")

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


class GCSVideoStorage:
    """Google Cloud Storage adapter with direct, signed browser uploads."""

    def __init__(
        self,
        bucket_name: str,
        *,
        prefix: str = "",
        client: Any | None = None,
        signing_credentials: Any | None = None,
        signing_service_account: str | None = None,
    ) -> None:
        if not bucket_name or "/" in bucket_name:
            raise ValueError("bucket_name must be a plain GCS bucket name")
        normalized_prefix = prefix.strip("/")
        if ".." in normalized_prefix.split("/"):
            raise ValueError("prefix must not contain parent path segments")
        if client is None:
            try:
                import google.auth
                from google.cloud import storage as google_storage
            except ImportError as error:  # pragma: no cover - deployment guard
                raise RuntimeError(
                    "google-cloud-storage is required for GCSVideoStorage"
                ) from error
            credentials, project = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            client = google_storage.Client(project=project, credentials=credentials)
            if signing_service_account and signing_credentials is None:
                from google.auth import impersonated_credentials

                signing_credentials = impersonated_credentials.Credentials(
                    source_credentials=credentials,
                    target_principal=signing_service_account,
                    target_scopes=[
                        "https://www.googleapis.com/auth/devstorage.read_write"
                    ],
                    lifetime=900,
                )
        elif signing_service_account:
            raise ValueError(
                "signing_service_account requires default credentials; "
                "inject signing_credentials with a custom client"
            )
        self.client = client
        self.bucket_name = bucket_name
        self.bucket = client.bucket(bucket_name)
        self.prefix = normalized_prefix
        self.signing_credentials = signing_credentials

    @staticmethod
    def _session_id(value: str) -> str:
        return str(UUID(value))

    @staticmethod
    def _input_key(session_id: str, filename: str) -> str:
        suffix = Path(filename).suffix.lower()
        if suffix not in {".mp4", ".mov", ".webm"}:
            suffix = ".video"
        return f"sessions/{session_id}/input/video{suffix}"

    def _blob_name(self, object_key: str) -> str:
        if (
            not object_key
            or object_key.startswith("/")
            or ".." in object_key.split("/")
        ):
            raise ValueError("invalid object key")
        return f"{self.prefix}/{object_key}" if self.prefix else object_key

    def _blob(self, object_key: str) -> Any:
        return self.bucket.blob(self._blob_name(object_key))

    @staticmethod
    def _is_not_found(error: Exception) -> bool:
        try:
            from google.api_core.exceptions import NotFound
        except ImportError:  # pragma: no cover - only possible without GCS dependency
            return False
        return isinstance(error, NotFound)

    def create_upload_target(
        self,
        session_id: str,
        *,
        filename: str,
        content_type: str,
        expires_in: timedelta,
        checksum_sha256: str | None = None,
    ) -> UploadTarget:
        normalized = self._session_id(session_id)
        if checksum_sha256 is None:
            raise ChecksumRequired("GCS uploads require a SHA-256 checksum")
        checksum = checksum_sha256.lower()
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise ValueError("invalid SHA-256 checksum")
        object_key = self._input_key(normalized, filename)
        signed_headers = {
            "x-goog-meta-sha256": checksum,
            "x-goog-if-generation-match": "0",
        }
        signed_url_options: dict[str, Any] = {
            "version": "v4",
            "expiration": expires_in,
            "method": "PUT",
            "content_type": content_type,
            "headers": signed_headers,
        }
        if self.signing_credentials is not None:
            signed_url_options["credentials"] = self.signing_credentials
        url = self._blob(object_key).generate_signed_url(**signed_url_options)
        return UploadTarget(
            object_key=object_key,
            url=url,
            method="PUT",
            headers={"Content-Type": content_type, **signed_headers},
            expires_at=datetime.now(timezone.utc) + expires_in,
        )

    def inspect(self, object_key: str) -> StoredObject:
        blob = self._blob(object_key)
        try:
            blob.reload()
        except Exception as error:
            if self._is_not_found(error):
                raise StorageObjectNotFound(object_key) from error
            raise
        metadata: Mapping[str, str] = blob.metadata or {}
        checksum = metadata.get("sha256", "").lower()
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            raise ChecksumMismatch("GCS object is missing valid sha256 metadata")
        return StoredObject(
            object_key=object_key,
            size_bytes=int(blob.size),
            checksum_sha256=checksum,
            content_type=blob.content_type or "application/octet-stream",
        )

    def open_reader(self, object_key: str) -> BinaryIO:
        self.inspect(object_key)
        return self._blob(object_key).open("rb")

    def download(self, object_key: str, destination: Path) -> StoredObject:
        stored = self.inspect(object_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._blob(object_key).download_to_filename(str(destination), checksum="auto")
        return stored

    def store_result(
        self, session_id: str, *, name: str, source: BinaryIO, content_type: str
    ) -> StoredObject:
        normalized = self._session_id(session_id)
        if not name or Path(name).name != name:
            raise ValueError("result name must be a plain filename")
        object_key = f"sessions/{normalized}/results/{name}"
        blob = self._blob(object_key)
        digest = hashlib.sha256()
        size = 0
        with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as upload:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                upload.write(chunk)
            upload.seek(0)
            checksum = digest.hexdigest()
            blob.metadata = {"sha256": checksum}
            blob.upload_from_file(
                upload,
                rewind=True,
                size=size,
                content_type=content_type,
                if_generation_match=0,
                checksum="auto",
            )
        return StoredObject(object_key, size, checksum, content_type)

    def delete_session(self, session_id: str) -> None:
        normalized = self._session_id(session_id)
        logical_prefix = f"sessions/{normalized}/"
        for blob in self.client.list_blobs(
            self.bucket_name, prefix=self._blob_name(logical_prefix)
        ):
            blob.delete(if_generation_match=blob.generation)


def video_storage_from_env(local_root: Path) -> VideoStorage:
    """Select local files by default and GCS when a bucket is configured."""

    bucket = os.getenv("GYMBROMATICS_GCS_BUCKET", "").strip()
    if not bucket:
        return LocalVideoStorage(local_root)
    return GCSVideoStorage(
        bucket,
        prefix=os.getenv("GYMBROMATICS_GCS_PREFIX", "").strip(),
        signing_service_account=os.getenv(
            "GYMBROMATICS_GCS_SIGNING_SERVICE_ACCOUNT", ""
        ).strip()
        or None,
    )
