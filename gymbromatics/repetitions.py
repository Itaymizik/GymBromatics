"""Conservative squat segmentation from a smoothed hip trajectory, without ML."""

from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import find_peaks

from .filter import smooth_vertical_motion


@dataclass(frozen=True)
class Repetition:
    id: str
    start: int
    bottom: int
    end: int
    source: str = "auto"
    needs_review: bool = False


def detect_repetitions(
    hip_y: np.ndarray, knee_angles: np.ndarray, fps: float, image_height: int,
) -> list[Repetition]:
    """Propose complete stand/down/up/stand cycles; boundaries are editable.

    Y increases downward. Significant hip-Y peaks locate the hole. A return
    within 8% of the excursion from an upright baseline bounds each cycle.
    Available knee angles must corroborate standing (>=170) and flexion (>=20),
    with low hip speed at the endpoints to retain the entire ascent/descent.
    Never bridge a long tracking gap, or count a partial cycle at a video edge.
    """
    hips = np.asarray(hip_y, dtype=float)
    knees = np.asarray(knee_angles, dtype=float)
    if hips.ndim != 1 or knees.shape != hips.shape:
        raise ValueError("Hip and knee samples must be matching one-dimensional arrays")
    if image_height < 2 or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Invalid frame rate or image height")
    motion = smooth_vertical_motion(hips, fps)
    smoothed = motion.y_smoothed
    bounds = np.diff(np.r_[False, np.isfinite(smoothed), False].astype(int))
    result: list[Repetition] = []
    for begin, stop in zip(np.flatnonzero(bounds == 1), np.flatnonzero(bounds == -1)):
        y = smoothed[begin:stop]
        if len(y) < max(5, round(.6 * fps)):
            continue
        excursion = float(np.percentile(y, 95) - np.percentile(y, 10))
        prominence = max(image_height * .035, excursion * .25)
        peaks, _ = find_peaks(y, prominence=prominence, distance=max(1, round(.6 * fps)))
        speed = np.abs(motion.velocity_up[begin:stop])
        rest_speed = max(5.0, float(np.percentile(speed, 95)) * .15)
        segment_knees = knees[begin:stop]
        upright = (~np.isfinite(segment_knees) | (segment_knees >= 170)) & (speed <= rest_speed)
        for position, peak in enumerate(peaks):
            # Anchor each side at the adjacent standing valley. A global baseline
            # can join multiple reps when the lifter/camera shifts during a set.
            previous = int(peaks[position - 1]) if position else 0
            following = int(peaks[position + 1]) if position + 1 < len(peaks) else len(y) - 1
            left_bound = previous + int(np.argmin(y[previous:peak + 1]))
            right_bound = int(peak) + int(np.argmin(y[peak:following + 1]))
            left_threshold = y[left_bound] + max(2.0, (y[peak] - y[left_bound]) * .08)
            right_threshold = y[right_bound] + max(2.0, (y[peak] - y[right_bound]) * .08)
            # Knee lockout can occur a few frames after the hip's local minimum.
            # Search the whole inter-bottom interval, while retaining local heights.
            left = np.flatnonzero((y[previous:peak] <= left_threshold) & upright[previous:peak]) + previous
            right = np.flatnonzero((y[peak + 1:following + 1] <= right_threshold) & upright[peak + 1:following + 1])
            if not len(left) or not len(right):
                continue
            start, bottom, end = int(begin + left[-1]), int(begin + peak), int(begin + peak + 1 + right[0])
            if (end - start) / fps < .6 or min(bottom - start, end - bottom) < max(2, round(.15 * fps)):
                continue
            # Multiple shallow bumps during a pause belong to one cycle.
            if result and start < result[-1].end:
                continue
            top = knees[[start, end]]
            low = knees[bottom]
            if np.any(top[np.isfinite(top)] < 170):
                continue
            if np.isfinite(low) and np.isfinite(top).any() and np.nanmax(top) - low < 20:
                continue
            missing = not np.isfinite(knees[start:end + 1]).all() or not np.isfinite(hips[start:end + 1]).all()
            result.append(Repetition(f"auto-{bottom}", start, bottom, end, needs_review=missing))
    return result
