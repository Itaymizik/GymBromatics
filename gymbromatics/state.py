"""Provider-independent pose data. Image Y increases downwards."""

from dataclasses import dataclass
from math import isfinite


LANDMARK_NAMES = (
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer", "left_ear", "right_ear",
    "mouth_left", "mouth_right", "left_shoulder", "right_shoulder",
    "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_pinky",
    "right_pinky", "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle",
    "right_ankle", "left_heel", "right_heel", "left_foot_index", "right_foot_index",
)


@dataclass(frozen=True)
class Landmark:
    """Normalized image x/y; z is relative depth, not calibrated metres."""

    x: float
    y: float
    z: float
    visibility: float
    presence: float

    def is_reliable(self, threshold: float) -> bool:
        return (
            all(isfinite(v) for v in (self.x, self.y, self.z, self.visibility, self.presence))
            and self.visibility >= threshold
            and self.presence >= threshold
        )


@dataclass(frozen=True)
class FrameState:
    frame_index: int
    timestamp_ms: int
    landmarks: dict[str, Landmark]

    @property
    def pose_detected(self) -> bool:
        return bool(self.landmarks)
