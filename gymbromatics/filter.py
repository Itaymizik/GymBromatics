"""Smooth image trajectories before differentiating; never bridge long gaps."""

from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import savgol_filter


@dataclass(frozen=True)
class FilteredMotion:
    y_smoothed: np.ndarray
    velocity_up: np.ndarray
    interpolated: np.ndarray
    window_frames: int


def smooth_vertical_motion(
    y_pixels: np.ndarray, fps: float, window_seconds: float = 0.35,
    max_gap_seconds: float = 0.15,
) -> FilteredMotion:
    """Return px/s, positive upward. Missing/unusable samples remain NaN.

    Fill only bounded short gaps. Smooth each contiguous finite segment using
    a quadratic Savitzky-Golay filter, then derive velocity from that signal.
    At least five consecutive samples are needed for a usable segment.
    """
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError("FPS must be finite and positive")
    if not math.isfinite(window_seconds) or window_seconds <= 0:
        raise ValueError("Smoothing window must be finite and positive")
    if not math.isfinite(max_gap_seconds) or max_gap_seconds < 0:
        raise ValueError("Maximum gap must be finite and nonnegative")
    values = np.asarray(y_pixels, dtype=float).copy()
    if values.ndim != 1:
        raise ValueError("Y coordinates must be a one-dimensional array")
    values[~np.isfinite(values)] = np.nan
    interpolated = np.zeros(len(values), dtype=bool)
    max_gap = math.floor(fps * max_gap_seconds)
    good_indices = np.flatnonzero(np.isfinite(values))
    for first, last in zip(good_indices[:-1], good_indices[1:]):
        gap = last - first - 1
        if 0 < gap <= max_gap:
            values[first + 1:last] = np.linspace(values[first], values[last], gap + 2)[1:-1]
            interpolated[first + 1:last] = True
    window = max(5, round(fps * window_seconds))
    window += int(window % 2 == 0)
    smoothed = np.full(len(values), np.nan)
    velocity = np.full(len(values), np.nan)
    boundaries = np.diff(np.r_[False, np.isfinite(values), False].astype(int))
    for start, stop in zip(np.flatnonzero(boundaries == 1), np.flatnonzero(boundaries == -1)):
        length = stop - start
        if length < 5:
            continue
        segment_window = min(window, length if length % 2 else length - 1)
        smoothed[start:stop] = savgol_filter(values[start:stop], segment_window, 2, mode="interp")
        # OpenCV Y grows downward: negate the derivative to make ascent positive.
        velocity[start:stop] = -np.gradient(smoothed[start:stop], 1.0 / fps, edge_order=2)
    return FilteredMotion(smoothed, velocity, interpolated, window)
