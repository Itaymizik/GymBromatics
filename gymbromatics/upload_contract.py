"""Pydantic models forming the public asynchronous upload API contract."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .jobs import JobStatus


MAX_VIDEO_BYTES = 250 * 1024 * 1024
VideoContentType = Literal["video/mp4", "video/quicktime", "video/webm"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateVideoSessionRequest(StrictModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: VideoContentType
    size_bytes: int = Field(gt=0, le=MAX_VIDEO_BYTES)
    checksum_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-fA-F]{64}$"
    )

    @field_validator("filename")
    @classmethod
    def plain_filename(cls, value: str) -> str:
        if value in {".", ".."} or "/" in value or "\\" in value or "\x00" in value:
            raise ValueError("filename must not contain a path")
        return value


class UploadInstruction(StrictModel):
    url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime


class CreateVideoSessionResponse(StrictModel):
    session_id: str
    status: Literal[JobStatus.CREATED]
    upload: UploadInstruction


class ConfirmUploadRequest(StrictModel):
    size_bytes: int = Field(gt=0, le=MAX_VIDEO_BYTES)
    checksum_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class JobStatusResponse(StrictModel):
    session_id: str
    status: JobStatus
    attempt: int = Field(ge=0)
    error_code: str | None = None
    result_urls: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

