"""Provider-independent, confidence-gated 2D trajectories for technique rules.

Rule evaluation lives in technique.js so edited rep boundaries can be evaluated
offline in the dashboard. Coordinates use original image pixels, Y downward.
"""
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from .filter import smooth_vertical_motion
from .state import Landmark


@dataclass(frozen=True)
class TechniqueFrame:
    shoulder: list[float] | None
    hip: list[float] | None
    knee: list[float] | None
    heel: list[float] | None
    toe: list[float] | None
    knee_angle_deg: float | None
    feet: dict[str, dict[str, list[float] | None]]
    calibration_points: dict[str, dict[str, list[float] | None]]


def build_technique_trajectories(
    frames: list[dict[str, Any]], width: int, height: int, fps: float,
    confidence: float = 0.65,
) -> dict[str, Any]:
    """Use a fixed anatomical side; never interpolate occluded landmarks."""
    side = next((f["angles"].get("display_side") for f in frames
                 if f["angles"].get("display_side") in ("left", "right")), "left")
    def reliable(frame: dict[str, Any], name: str) -> Landmark | None:
        value = frame["landmarks"].get(name)
        if value is None or width < 2 or height < 2:
            return None
        point = Landmark(**value)
        return point if point.is_reliable(confidence) and 0 <= point.x <= 1 and 0 <= point.y <= 1 else None

    # Foot selection is independent of the side used for torso/knee measurements.
    # Visibility is a proxy for the near foot; the dashboard allows correction.
    scores = {s: sum(min(p.visibility, p.presence, q.visibility, q.presence)
                    if (p := reliable(f, f"{s}_heel")) is not None
                    and (q := reliable(f, f"{s}_foot_index")) is not None else 0
                    for f in frames) / max(1, len(frames)) for s in ("left", "right")}
    foot_side = max((side, "right" if side == "left" else "left"), key=scores.get)
    points: dict[str, list[list[float] | None]] = {}
    names = {key: f"{side}_{key}" for key in ("shoulder", "hip", "knee")}
    names.update({f"{s}_{key}": f"{s}_{suffix}" for s in ("left", "right")
                  for key, suffix in (("heel", "heel"), ("toe", "foot_index"))})
    for key, name in names.items():
        raw = np.full((len(frames), 2), np.nan)
        for i, frame in enumerate(frames):
            point = reliable(frame, name)
            if point is not None:
                raw[i] = [point.x * (width - 1), point.y * (height - 1)]
        smoothed = np.column_stack([
            smooth_vertical_motion(raw[:, axis], fps, window_seconds=.2,
                                   max_gap_seconds=0).y_smoothed for axis in (0, 1)
        ])
        points[key] = [p.tolist() if np.all(np.isfinite(p)) else None for p in smoothed]
    output = []
    for i, frame in enumerate(frames):
        angle = frame["angles"].get(side, {}).get("knee_angle_deg")
        if not (isinstance(angle, (float, int)) and np.isfinite(angle) and 0 <= angle <= 180
                and all(reliable(frame, f"{side}_{key}") is not None for key in ("hip", "knee", "ankle"))):
            angle = None
        feet = {s: {key: points[f"{s}_{key}"][i] for key in ("heel", "toe")} for s in ("left", "right")}
        output.append(asdict(TechniqueFrame(
            **{key: points[key][i] for key in ("shoulder", "hip", "knee")},
            **feet[foot_side], knee_angle_deg=angle, feet=feet,
            calibration_points={s: {key: [p.x * (width - 1), p.y * (height - 1)]
                                      if (p := reliable(frame, f"{s}_{suffix}")) is not None else None
                                   for key, suffix in (("ear", "ear"), ("shoulder", "shoulder"),
                                                       ("hip", "hip"), ("knee", "knee"),
                                                       ("ankle", "ankle"), ("heel", "heel"), ("toe", "foot_index"))}
                                for s in ("left", "right")})))
    return {
        "version": 2, "side": side, "foot_side": foot_side, "foot_visibility_scores": scores,
        "confidence_threshold": confidence,
        "width": width, "height": height,
        "coordinate_space": "original image pixels, y downward",
        "smoothing": "Savitzky-Golay 0.2 s; no gap interpolation; >=5 consecutive valid frames",
        "frames": output,
    }
