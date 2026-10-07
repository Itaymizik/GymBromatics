from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from gymbromatics.jobs import JobStatus
from gymbromatics.upload_contract import (
    CreateVideoSessionRequest,
    CreateVideoSessionResponse,
    MAX_VIDEO_BYTES,
    UploadInstruction,
)


def test_create_session_contract_accepts_supported_video() -> None:
    request = CreateVideoSessionRequest(
        filename="squat.mp4",
        content_type="video/mp4",
        size_bytes=123,
        checksum_sha256="a" * 64,
    )
    response = CreateVideoSessionResponse(
        session_id="00000000-0000-0000-0000-000000000001",
        status=JobStatus.CREATED,
        upload=UploadInstruction(
            url="https://storage.example/upload",
            headers={"Content-Type": "video/mp4"},
            expires_at=datetime.now(timezone.utc),
        ),
    )

    assert request.size_bytes == 123
    assert response.status == JobStatus.CREATED


@pytest.mark.parametrize(
    "payload",
    [
        {"filename": "../squat.mp4", "content_type": "video/mp4", "size_bytes": 1},
        {"filename": "squat.avi", "content_type": "video/avi", "size_bytes": 1},
        {"filename": "squat.mp4", "content_type": "video/mp4", "size_bytes": 0},
        {
            "filename": "squat.mp4",
            "content_type": "video/mp4",
            "size_bytes": MAX_VIDEO_BYTES + 1,
        },
    ],
)
def test_create_session_contract_rejects_unsafe_input(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CreateVideoSessionRequest(**payload)
