"""MediaPipe adapter. No drawing or squat heuristics belong here."""

from pathlib import Path
from types import TracebackType
from typing import Protocol

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import PoseLandmarker, PoseLandmarkerOptions, RunningMode

from .state import FrameState, LANDMARK_NAMES, Landmark


class PoseExtractor(Protocol):
    def extract(self, frame: np.ndarray, frame_index: int, timestamp_ms: int) -> FrameState:
        """Return named landmarks in normalized image coordinates."""
        ...


class MediaPipePoseExtractor:
    """One instance per video; video timestamps must strictly increase."""

    def __init__(self, model_path: Path, confidence: float = 0.5) -> None:
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("Confidence must be between 0 and 1")
        # Bytes avoid native Windows model-path problems with Hebrew/Unicode paths.
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=confidence,
            min_pose_presence_confidence=confidence,
            min_tracking_confidence=confidence,
        )
        self._landmarker = PoseLandmarker.create_from_options(options)

    def extract(self, frame: np.ndarray, frame_index: int, timestamp_ms: int) -> FrameState:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._landmarker.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp_ms
        )
        landmarks: dict[str, Landmark] = {}
        if result.pose_landmarks:
            for name, point in zip(LANDMARK_NAMES, result.pose_landmarks[0], strict=True):
                landmarks[name] = Landmark(
                    x=float(point.x), y=float(point.y), z=float(point.z),
                    visibility=float(point.visibility or 0.0),
                    presence=float(point.presence or 0.0),
                )
        return FrameState(frame_index, timestamp_ms, landmarks)

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> "MediaPipePoseExtractor":
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None,
        exc_value: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        self.close()
