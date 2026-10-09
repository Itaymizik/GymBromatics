"""FastAPI application for the session dashboard and grounded chat."""

from __future__ import annotations

import copy
from datetime import timedelta
import html
import json
from pathlib import Path
import secrets
from tempfile import SpooledTemporaryFile
import threading
from typing import Any, Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .chat import reply
from .feedback_provider import FeedbackError, FeedbackProvider, GeminiFreeTier
from .job_repository import JobNotFound, JobRepository, LocalJobRepository
from .jobs import JobStatus, ProcessingJob, new_processing_job
from .storage import (
    ChecksumMismatch,
    ChecksumRequired,
    LocalUploadStorage,
    StorageObjectNotFound,
    UploadTooLarge,
    VideoStorage,
    video_storage_from_env,
)
from .upload_contract import (
    ConfirmUploadRequest,
    ConfirmUploadResponse,
    CreateVideoSessionRequest,
    CreateVideoSessionResponse,
    JobStatusResponse,
    MAX_VIDEO_BYTES,
    UploadInstruction,
    UploadReceiptResponse,
)


DEFAULT_DASHBOARDS = (
    Path("demo_artifacts/squatsample_dashboard.html"),
    Path("demo_artifacts/squat_test2_dashboard.html"),
)
MAX_REQUEST_BYTES = 32 * 1024
LOCAL_RUNTIME_ROOT = Path(".gymbromatics-local")


class RepetitionInput(BaseModel):
    """Only user-editable repetition fields accepted by the chat API."""

    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(min_length=1, max_length=200)
    start: int = Field(ge=0)
    bottom: int = Field(ge=0)
    end: int = Field(ge=0)
    source: Literal["auto", "manual", "edited"]
    needs_review: bool = False


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis_id: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    repetitions: list[RepetitionInput] = Field(max_length=30)
    message: str = Field(min_length=1, max_length=1500)
    selected_rep_id: str | None = Field(default=None, max_length=200)
    foot_side: Literal["left", "right"] | None = None
    conversation_id: str | None = Field(default=None, min_length=16, max_length=100)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    revision: str | None = None


class ApplicationState:
    """Mutable process state kept behind locks until persistence is introduced."""

    def __init__(
        self,
        dashboard_paths: list[Path],
        provider: FeedbackProvider | None = None,
        video_storage: VideoStorage | None = None,
        job_repository: JobRepository | None = None,
    ) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        for path in dashboard_paths:
            html_path = path.resolve()
            json_path = html_path.with_suffix(".json")
            if not html_path.is_file() or not json_path.is_file():
                raise FileNotFoundError(f"Dashboard pair is missing: {html_path}")
            data = json.loads(json_path.read_text(encoding="utf-8"))
            analysis_id = data.get("analysis_id")
            if not isinstance(analysis_id, str) or len(analysis_id) != 64:
                raise ValueError(f"Dashboard has an invalid analysis_id: {json_path}")
            if analysis_id in self.sessions:
                raise ValueError(f"Duplicate analysis_id: {analysis_id}")
            self.sessions[analysis_id] = {"data": data, "path": html_path}
        self.provider = provider or GeminiFreeTier.from_env()
        self.video_storage = video_storage or video_storage_from_env(
            LOCAL_RUNTIME_ROOT / "objects"
        )
        self.job_repository = job_repository or LocalJobRepository(LOCAL_RUNTIME_ROOT / "jobs")
        self.page_token = secrets.token_urlsafe(32)
        self.conversations: dict[str, ConversationState] = {}
        self.state_lock = threading.Lock()
        self.generation_lock = threading.Lock()

    def readiness(self) -> tuple[bool, dict[str, bool]]:
        provider_configured = not isinstance(self.provider, GeminiFreeTier) or (
            bool(self.provider.api_key) and self.provider.free_tier_confirmed
        )
        checks = {"sessions_loaded": bool(self.sessions), "llm_configured": provider_configured}
        return all(checks.values()), checks


def _same_origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.headers.get('host', '')}"


def create_app(
    dashboard_paths: list[Path] | None = None,
    provider: FeedbackProvider | None = None,
    video_storage: VideoStorage | None = None,
    job_repository: JobRepository | None = None,
) -> FastAPI:
    """Application factory keeps configuration explicit and tests isolated."""

    runtime = ApplicationState(
        list(dashboard_paths or DEFAULT_DASHBOARDS),
        provider,
        video_storage,
        job_repository,
    )
    app = FastAPI(
        title="GymBromatics API",
        version="1.0.0",
        description="Side-view squat session dashboards and evidence-grounded chat.",
    )
    app.state.runtime = runtime

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content={"error": str(error.detail)})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"error": "invalid_request"},
        )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        content_length = request.headers.get("content-length")
        request_limit = (
            MAX_VIDEO_BYTES
            if request.method == "PUT" and request.url.path.endswith("/upload")
            else MAX_REQUEST_BYTES
        )
        if request.method in {"POST", "PUT", "PATCH"} and content_length:
            try:
                too_large = int(content_length) > request_limit
            except ValueError:
                too_large = True
            if too_large:
                response = JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"error": "request_too_large"},
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        return response

    def require_chat_request(
        request: Request,
        x_chat_token: str | None = Header(default=None),
    ) -> None:
        if (
            request.headers.get("origin") != _same_origin(request)
            or x_chat_token is None
            or not secrets.compare_digest(x_chat_token, runtime.page_token)
        ):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    @app.get("/health/live", tags=["health"])
    async def health_live() -> dict[str, str]:
        return {"status": "live"}

    @app.get("/health/ready", tags=["health"])
    async def health_ready(response: Response) -> dict[str, Any]:
        ready, checks = runtime.readiness()
        if not ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "ready" if ready else "not_ready", "checks": checks}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index() -> str:
        links = '<li><a href="/upload">ניתוח סרטון חדש</a></li>' + "".join(
            f'<li><a href="/sessions/{analysis_id}">{html.escape(record["data"]["name"])}</a></li>'
            for analysis_id, record in runtime.sessions.items()
        )
        return (
            '<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8">'
            "<title>GymBromatics</title><h1>בחירת סשן</h1><ul>" + links + "</ul></html>"
        )

    @app.get("/upload", response_class=HTMLResponse, include_in_schema=False)
    async def upload_page() -> str:
        return Path(__file__).with_name("upload.html").read_text(encoding="utf-8")

    @app.get("/assets/upload.js", response_class=PlainTextResponse, include_in_schema=False)
    async def upload_script() -> PlainTextResponse:
        return PlainTextResponse(
            Path(__file__).with_name("upload.js").read_text(encoding="utf-8"),
            media_type="application/javascript",
        )

    @app.get("/sessions/{analysis_id}", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(analysis_id: str) -> str:
        record = runtime.sessions.get(analysis_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
        page = record["path"].read_text(encoding="utf-8")
        bootstrap = "<script>window.GYM_CHAT_TOKEN=" + json.dumps(runtime.page_token) + ";</script>"
        return page.replace("</head>", bootstrap + "</head>")

    @app.get("/api/sessions/{analysis_id}", tags=["sessions"])
    async def session_metadata(analysis_id: str) -> dict[str, Any]:
        record = runtime.sessions.get(analysis_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
        data = record["data"]
        return {
            "analysis_id": analysis_id,
            "name": data["name"],
            "fps": data["fps"],
            "duration": data["duration"],
            "repetitions": data["repetitions"],
        }

    def get_video_job(session_id: str) -> ProcessingJob:
        try:
            return runtime.job_repository.get(session_id)
        except (JobNotFound, ValueError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="video_session_not_found"
            ) from None

    @app.post(
        "/api/video-sessions",
        response_model=CreateVideoSessionResponse,
        status_code=status.HTTP_201_CREATED,
        tags=["video-processing"],
    )
    async def create_video_session(
        body: CreateVideoSessionRequest, request: Request
    ) -> CreateVideoSessionResponse:
        session_id = str(uuid4())
        try:
            target = runtime.video_storage.create_upload_target(
                session_id,
                filename=body.filename,
                content_type=body.content_type,
                expires_in=timedelta(minutes=15),
                checksum_sha256=body.checksum_sha256,
            )
        except ChecksumRequired:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="checksum_required",
            ) from None
        job = new_processing_job(
            session_id=session_id,
            original_filename=body.filename,
            content_type=body.content_type,
            expected_size_bytes=body.size_bytes,
            input_object_key=target.object_key,
            declared_checksum_sha256=body.checksum_sha256,
        )
        runtime.job_repository.create(job)
        upload_url = target.url
        if isinstance(runtime.video_storage, LocalUploadStorage):
            upload_url = str(
                request.url_for("upload_local_video", session_id=session_id)
            )
        return CreateVideoSessionResponse(
            session_id=session_id,
            status=JobStatus.CREATED,
            upload=UploadInstruction(
                url=upload_url,
                method=target.method,
                headers=target.headers,
                expires_at=target.expires_at,
            ),
        )

    @app.put(
        "/api/video-sessions/{session_id}/upload",
        response_model=UploadReceiptResponse,
        tags=["video-processing"],
    )
    async def upload_local_video(
        session_id: str, request: Request
    ) -> UploadReceiptResponse:
        if not isinstance(runtime.video_storage, LocalUploadStorage):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="local_upload_unavailable",
            )
        job = get_video_job(session_id)
        if job.status != JobStatus.CREATED:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="upload_closed")
        if request.headers.get("content-type", "").split(";", 1)[0] != job.content_type:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="content_type_mismatch",
            )

        size = 0
        with SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b") as upload:
            async for chunk in request.stream():
                size += len(chunk)
                if size > job.expected_size_bytes or size > MAX_VIDEO_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="upload_size_mismatch",
                    )
                upload.write(chunk)
            if size != job.expected_size_bytes:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="upload_size_mismatch",
                )
            upload.seek(0)
            try:
                stored = await run_in_threadpool(
                    runtime.video_storage.accept_upload,
                    session_id,
                    filename=job.original_filename,
                    source=upload,
                    content_type=job.content_type,
                    max_bytes=job.expected_size_bytes,
                    expected_checksum_sha256=job.declared_checksum_sha256,
                )
            except UploadTooLarge:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="upload_size_mismatch",
                ) from None
            except ChecksumMismatch:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="checksum_mismatch",
                ) from None
        return UploadReceiptResponse(
            session_id=session_id,
            status=JobStatus.CREATED,
            size_bytes=stored.size_bytes,
            checksum_sha256=stored.checksum_sha256,
        )

    @app.post(
        "/api/video-sessions/{session_id}/upload-complete",
        response_model=ConfirmUploadResponse,
        tags=["video-processing"],
    )
    async def confirm_video_upload(
        session_id: str, body: ConfirmUploadRequest
    ) -> ConfirmUploadResponse:
        job = get_video_job(session_id)
        if job.status == JobStatus.CREATED:
            try:
                stored = runtime.video_storage.inspect(job.input_object_key)
            except StorageObjectNotFound:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="upload_not_found"
                ) from None
            except ChecksumMismatch:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="upload_metadata_mismatch",
                ) from None
            if (
                stored.size_bytes != body.size_bytes
                or stored.size_bytes != job.expected_size_bytes
                or stored.checksum_sha256 != body.checksum_sha256.lower()
                or (
                    job.declared_checksum_sha256 is not None
                    and stored.checksum_sha256 != job.declared_checksum_sha256
                )
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="upload_metadata_mismatch",
                )
            job = runtime.job_repository.transition(
                session_id,
                JobStatus.UPLOADED,
                expected_version=job.version,
                checksum_sha256=stored.checksum_sha256,
            )
        if job.status == JobStatus.UPLOADED:
            job = runtime.job_repository.transition(
                session_id, JobStatus.QUEUED, expected_version=job.version
            )
        if job.status != JobStatus.QUEUED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="upload_already_processed"
            )
        return ConfirmUploadResponse(session_id=session_id, status=JobStatus.QUEUED)

    @app.get(
        "/api/video-sessions/{session_id}",
        response_model=JobStatusResponse,
        tags=["video-processing"],
    )
    async def video_session_status(session_id: str, request: Request) -> JobStatusResponse:
        job = get_video_job(session_id)
        result_urls = {
            name: str(
                request.url_for(
                    "download_video_result", session_id=session_id, result_name=name
                )
            )
            for name in job.result_objects
        }
        return JobStatusResponse(
            session_id=job.session_id,
            status=job.status,
            attempt=job.attempt,
            error_code=job.error_code,
            result_urls=result_urls,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    @app.get(
        "/api/video-sessions/{session_id}/results/{result_name}",
        tags=["video-processing"],
        name="download_video_result",
    )
    async def download_video_result(
        session_id: str, result_name: str
    ) -> StreamingResponse:
        job = get_video_job(session_id)
        object_key = job.result_objects.get(result_name)
        if job.status != JobStatus.COMPLETE or object_key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="result_not_found"
            )
        stored = runtime.video_storage.inspect(object_key)
        media_types = {
            "annotated_video": "video/mp4",
            "analysis_json": "application/json",
            "dashboard_html": "text/html; charset=utf-8",
            "dashboard_json": "application/json",
        }

        def chunks():
            with runtime.video_storage.open_reader(object_key) as source:
                while chunk := source.read(1024 * 1024):
                    yield chunk

        return StreamingResponse(
            chunks(),
            media_type=media_types.get(result_name, stored.content_type),
            headers={"Content-Length": str(stored.size_bytes)},
        )

    @app.post("/api/chat", tags=["chat"], dependencies=[Depends(require_chat_request)], deprecated=True)
    @app.post("/sessions/{session_id}/chat", tags=["chat"], dependencies=[Depends(require_chat_request)])
    async def chat(body: ChatRequest, session_id: str | None = None) -> dict[str, Any]:
        if session_id is not None and session_id != body.analysis_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="session_mismatch")
        record = runtime.sessions.get(body.analysis_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session_not_found")
        with runtime.state_lock:
            if body.conversation_id:
                conversation = runtime.conversations.get(body.conversation_id)
                if conversation is None or conversation.session != body.analysis_id:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_conversation")
                conversation_id = body.conversation_id
            else:
                if len(runtime.conversations) >= 200:
                    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="conversation_limit")
                conversation_id = secrets.token_urlsafe(24)
                conversation = ConversationState(session=body.analysis_id)
        if not runtime.generation_lock.acquire(blocking=False):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="busy")
        try:
            session = copy.copy(record["data"])
            session["repetitions"] = [item.model_dump() for item in body.repetitions]
            result = await run_in_threadpool(
                reply,
                session,
                body.message,
                body.selected_rep_id,
                body.foot_side,
                conversation.history,
                conversation.revision,
                runtime.provider,
            )
            updated_history = result.pop("history")
            with runtime.state_lock:
                runtime.conversations[conversation_id] = ConversationState(
                    session=body.analysis_id,
                    history=updated_history,
                    revision=result["revision"],
                )
            result["conversation_id"] = conversation_id
            return result
        except FeedbackError as error:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from None
        finally:
            runtime.generation_lock.release()

    return app


app = create_app()
