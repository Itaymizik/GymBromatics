"""Local queued-job worker for the complete squat analysis pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import logging
from pathlib import Path
import tempfile
import time
from typing import Mapping, Protocol

from .dashboard import export_dashboard
from .extractor import MediaPipePoseExtractor
from .job_repository import ConcurrentJobUpdate, JobRepository, LocalJobRepository
from .jobs import JobStatus, ProcessingJob
from .model import DEFAULT_MODEL
from .pipeline import process_video
from .squat_logic import SquatKinematics
from .storage import LocalVideoStorage, VideoStorage
from .visualizer import AngleVisualizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Artifact:
    path: Path
    content_type: str


class VideoJobProcessor(Protocol):
    def process(self, input_path: Path, output_dir: Path) -> Mapping[str, Artifact]: ...


class MediaPipeVideoJobProcessor:
    """Adapter from one local file to all GymBromatics output artifacts."""

    def __init__(self, model_path: Path = DEFAULT_MODEL, confidence: float = 0.5) -> None:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        self.model_path = model_path
        self.confidence = confidence

    def process(self, input_path: Path, output_dir: Path) -> Mapping[str, Artifact]:
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"MediaPipe model missing: {self.model_path}. Run the model download command first."
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        video = output_dir / "annotated_video.mp4"
        analysis = output_dir / "analysis.json"
        dashboard = output_dir / "dashboard.html"
        with MediaPipePoseExtractor(self.model_path, self.confidence) as extractor:
            process_video(
                input_path,
                video,
                analysis,
                extractor,
                AngleVisualizer(self.confidence),
                SquatKinematics(self.confidence),
            )
        export_dashboard(analysis, video, dashboard, self.confidence)
        return {
            "annotated_video": Artifact(video, "video/mp4"),
            "analysis_json": Artifact(analysis, "application/json"),
            "dashboard_html": Artifact(dashboard, "text/html; charset=utf-8"),
            "dashboard_json": Artifact(dashboard.with_suffix(".json"), "application/json"),
        }


class LocalJobWorker:
    """Claims queued jobs and persists their artifacts through storage interfaces."""

    def __init__(
        self,
        repository: JobRepository,
        storage: VideoStorage,
        processor: VideoJobProcessor,
        *,
        workspace: Path,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.processor = processor
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def run_once(self) -> ProcessingJob | None:
        queued = self.repository.list_by_status(JobStatus.QUEUED, limit=1)
        if not queued:
            return None
        candidate = queued[0]
        try:
            job = self.repository.transition(
                candidate.session_id,
                JobStatus.PROCESSING,
                expected_version=candidate.version,
            )
        except ConcurrentJobUpdate:
            return None

        logger.info("Processing video session %s", job.session_id)
        try:
            with tempfile.TemporaryDirectory(
                prefix=f"{job.session_id}-", dir=self.workspace
            ) as temporary:
                workdir = Path(temporary)
                input_path = workdir / f"input{Path(job.original_filename).suffix.lower()}"
                self.storage.download(job.input_object_key, input_path)
                artifacts = self.processor.process(input_path, workdir / "outputs")
                result_objects: dict[str, str] = {}
                for result_name, artifact in artifacts.items():
                    if not artifact.path.is_file():
                        raise FileNotFoundError(f"processor did not create {artifact.path}")
                    with artifact.path.open("rb") as source:
                        stored = self.storage.store_result(
                            job.session_id,
                            name=artifact.path.name,
                            source=source,
                            content_type=artifact.content_type,
                        )
                    result_objects[result_name] = stored.object_key
            completed = self.repository.transition(
                job.session_id,
                JobStatus.COMPLETE,
                expected_version=job.version,
                result_objects=result_objects,
            )
            logger.info("Completed video session %s", job.session_id)
            return completed
        except Exception as error:
            logger.exception("Video session %s failed", job.session_id)
            current = self.repository.get(job.session_id)
            if current.status == JobStatus.PROCESSING:
                return self.repository.transition(
                    job.session_id,
                    JobStatus.FAILED,
                    expected_version=current.version,
                    error_code=self._error_code(error),
                )
            raise

    def run_pending(self, *, limit: int | None = None) -> list[ProcessingJob]:
        if limit is not None and limit < 1:
            raise ValueError("limit must be positive")
        processed: list[ProcessingJob] = []
        while limit is None or len(processed) < limit:
            result = self.run_once()
            if result is None:
                break
            processed.append(result)
        return processed

    @staticmethod
    def _error_code(error: Exception) -> str:
        if isinstance(error, FileNotFoundError):
            return "required_file_missing"
        if isinstance(error, (ValueError, RuntimeError)):
            return "video_processing_error"
        return "internal_processing_error"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=Path(".gymbromatics-local"))
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--watch", action="store_true", help="Keep polling for new jobs")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    worker = LocalJobWorker(
        LocalJobRepository(args.runtime_root / "jobs"),
        LocalVideoStorage(args.runtime_root / "objects"),
        MediaPipeVideoJobProcessor(args.model, args.confidence),
        workspace=args.runtime_root / "work",
    )
    while True:
        results = worker.run_pending()
        if not args.watch:
            print(f"Processed {len(results)} queued job(s).")
            return
        if not results:
            time.sleep(args.poll_seconds)


if __name__ == "__main__":
    main()
