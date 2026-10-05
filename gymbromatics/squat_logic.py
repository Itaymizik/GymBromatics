"""2D squat joint-angle estimates, independent of pose provider and rendering."""

from dataclasses import dataclass
from typing import Literal

import numpy as np

from .state import FrameState

Side = Literal["left", "right"]
JOINTS = ("knee", "hip", "ankle")


@dataclass(frozen=True)
class JointAngles:
    """Interior segment angles: straight knee/hip 180 degrees, neutral ankle 90."""

    knee_angle_deg: float | None
    hip_angle_deg: float | None
    ankle_angle_deg: float | None

    def values(self) -> tuple[float | None, float | None, float | None]:
        return self.knee_angle_deg, self.hip_angle_deg, self.ankle_angle_deg


@dataclass(frozen=True)
class FrameAngles:
    left: JointAngles
    right: JointAngles
    display_side: Side | None

    @property
    def selected(self) -> JointAngles:
        return getattr(self, self.display_side) if self.display_side else JointAngles(None, None, None)


def angle_between(first: np.ndarray, second: np.ndarray) -> float | None:
    """Unsigned angle in degrees; degenerate/nonfinite vectors are unmeasurable."""
    lengths = float(np.linalg.norm(first) * np.linalg.norm(second))
    if not np.isfinite(lengths) or lengths < 1e-8:
        return None
    return float(np.degrees(np.arccos(np.clip(np.dot(first, second) / lengths, -1.0, 1.0))))


def joint_vectors(
    state: FrameState, side: Side, joint: str, width: int, height: int, confidence: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Pixel-space center and segment vectors, shared with the angle arcs."""
    required = {
        "knee": ("knee", "hip", "ankle"),
        "hip": ("hip", "shoulder", "knee"),
        "ankle": ("ankle", "knee", "heel", "foot_index"),
    }[joint]
    points = []
    for name in required:
        point = state.landmarks.get(f"{side}_{name}")
        if point is None or not point.is_reliable(confidence):
            return None
        if not (0 <= point.x <= 1 and 0 <= point.y <= 1):
            return None
        # Correct the aspect ratio before any dot product (not normalized x/y).
        points.append(np.array([point.x * (width - 1), point.y * (height - 1)]))
    center = points[0]
    first = points[1] - center
    second = points[3] - points[2] if joint == "ankle" else points[2] - center
    if angle_between(first, second) is None:
        return None
    return center, first, second


class SquatKinematics:
    """One instance per video. Lock the best visible side once it is measurable."""

    def __init__(self, confidence: float = 0.5, side: Side | None = None) -> None:
        if not 0 <= confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        if side not in (None, "left", "right"):
            raise ValueError("Side must be left, right, or None")
        self.confidence = confidence
        self.side = side

    def calculate(self, state: FrameState, width: int, height: int) -> FrameAngles:
        if width < 2 or height < 2:
            raise ValueError("Frame dimensions must be at least 2 pixels")
        results: dict[str, JointAngles] = {}
        for side in ("left", "right"):
            values: list[float | None] = []
            for joint in JOINTS:
                vectors = joint_vectors(state, side, joint, width, height, self.confidence)
                value = None
                if vectors is not None:
                    value = angle_between(vectors[1], vectors[2])
                values.append(value)
            results[side] = JointAngles(*values)
        if self.side is None:
            candidates = [s for s in ("left", "right") if any(v is not None for v in results[s].values())]
            if candidates:
                def score(side: str) -> tuple[int, float]:
                    points = [state.landmarks.get(f"{side}_{name}") for name in
                              ("shoulder", "hip", "knee", "ankle", "heel", "foot_index")]
                    reliability = sum(min(p.visibility, p.presence) for p in points
                                      if p is not None and p.is_reliable(self.confidence))
                    return sum(v is not None for v in results[side].values()), reliability
                self.side = max(candidates, key=score)
        return FrameAngles(results["left"], results["right"], self.side)
