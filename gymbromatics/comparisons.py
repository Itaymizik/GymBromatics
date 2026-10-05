"""Descriptive within-session comparisons; independent of pose extraction/UI."""

import math
from statistics import median
from typing import Any



METRICS = {
    "duration": "s", "descent_duration": "s", "ascent_duration": "s",
    "min_knee_angle": "deg", "min_hip_angle": "deg", "min_ankle_angle": "deg",
    "bottom_pause": "s", "peak_ascent_velocity": "px/s", "mean_ascent_velocity": "px/s",
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _measurement(value: float | None, coverage: float = 1.0, reason: str | None = None) -> dict[str, Any]:
    return {"value": value, "coverage": coverage, "reason": reason}


def _metrics(samples: list[dict[str, Any]], rep: dict[str, Any], fps: float) -> dict[str, Any]:
    start, bottom, end = (rep[key] for key in ("start", "bottom", "end"))
    segment, ascent = samples[start:end + 1], samples[bottom:end + 1]
    result = {name: _measurement(value / fps) for name, value in (
        ("duration", end - start), ("descent_duration", bottom - start), ("ascent_duration", end - bottom))}
    # Extrema need complete coverage: a missing bottom/peak cannot be inferred.
    for name in ("knee", "hip", "ankle"):
        values = [row[name] for row in segment if _finite(row.get(name))]
        complete = len(values) == len(segment)
        result[f"min_{name}_angle"] = _measurement(
            min(values) if complete else None, len(values) / len(segment), None if complete else "missing_samples")
    speeds = [row["velocity"] for row in ascent if _finite(row.get("velocity"))]
    complete = len(speeds) == len(ascent)
    result["peak_ascent_velocity"] = _measurement(
        max(0.0, max(speeds)) if complete else None, len(speeds) / len(ascent), None if complete else "missing_samples")
    intervals = [(a["velocity"] + b["velocity"]) / 2 for a, b in zip(ascent, ascent[1:])
                 if _finite(a.get("velocity")) and _finite(b.get("velocity"))]
    coverage = len(intervals) / (end - bottom)
    result["mean_ascent_velocity"] = _measurement(
        sum(intervals) / len(intervals) if coverage >= .8 else None, coverage,
        None if coverage >= .8 else "insufficient_coverage")
    valid = sum(_finite(row.get("hip_y_smoothed_px")) and _finite(row.get("hip_velocity")) for row in segment)
    pause, reason = None, "missing_samples"
    if valid == len(segment):
        positions = [row["hip_y_smoothed_px"] for row in segment]
        deepest, excursion = max(positions), max(positions) - min(positions)
        peak = max(abs(row["hip_velocity"]) for row in segment)
        reason = "no_motion"
        if excursion > 0 and peak > 0:
            def slow(index: int) -> bool:
                return (samples[index]["hip_y_smoothed_px"] >= deepest - .05 * excursion
                        and abs(samples[index]["hip_velocity"]) <= .1 * peak)
            first = last = bottom
            if slow(bottom):
                while first > start and slow(first - 1):
                    first -= 1
                while last < end and slow(last + 1):
                    last += 1
            duration = (last - first) / fps
            pause, reason = duration if duration >= .2 else 0.0, None
    result["bottom_pause"] = _measurement(pause, valid / len(segment), reason)
    return result


def _delta(value: float | None, reference: float | None, unit: str, reason: str | None = None) -> dict[str, Any]:
    if reason or value is None or reference is None:
        return {"delta": None, "percent": None, "reason": reason or "unavailable_metric", "percent_reason": reason or "unavailable_metric"}
    difference = value - reference
    percent_reason = "angular_metric" if unit == "deg" else "near_zero_reference" if abs(reference) <= (.01 if unit == "s" else .1) else None
    return {"delta": difference, "percent": None if percent_reason else difference / abs(reference) * 100,
            "reason": None, "percent_reason": percent_reason}


def compare_repetitions(samples: list[dict[str, Any]], repetitions: list[dict[str, Any]], fps: float) -> dict[str, Any]:
    """Ordered complete repetitions; all deltas are current minus reference."""
    if not _finite(fps) or fps <= 0:
        raise ValueError("FPS must be finite and positive")
    previous_end, ids = -1, set()
    for rep in repetitions:
        bounds = [rep.get(key) for key in ("start", "bottom", "end")]
        if (not all(type(value) is int for value in bounds)
                or not 0 <= bounds[0] < bounds[1] < bounds[2] < len(samples)
                or bounds[0] < previous_end or not isinstance(rep.get("id"), str)
                or not rep["id"] or rep["id"] in ids):
            raise ValueError("Invalid or unordered repetition boundaries/IDs")
        previous_end = bounds[2]
        ids.add(rep["id"])
    rows = [{"id": rep["id"], "ordinal": i + 1,
             "boundaries": {key: rep[key] for key in ("start", "bottom", "end")},
             "source": rep.get("source", "auto"), "needs_review": bool(rep.get("needs_review", False)),
             "interpolated_ascent_fraction": sum(bool(s.get("interpolated")) for s in samples[rep["bottom"]:rep["end"] + 1]) / (rep["end"] - rep["bottom"] + 1),
             "metrics": _metrics(samples, rep, fps)} for i, rep in enumerate(repetitions)]
    references, trends = {}, {}
    for name, unit in METRICS.items():
        points = [(row["ordinal"], row["metrics"][name]["value"], row["id"]) for row in rows if row["metrics"][name]["value"] is not None]
        values = [point[1] for point in points]
        references[name] = {"value": median(values) if values else None, "valid_repetitions": len(values)}
        trend = {"valid_repetitions": len(values), "slope_per_rep": None,
                 "first_rep_id": points[0][2] if points else None, "last_rep_id": points[-1][2] if points else None,
                 "first_to_last": _delta(values[-1] if values else None, values[0] if values else None, unit,
                                         "insufficient_repetitions" if len(values) < 2 else None),
                 "reason": "insufficient_repetitions" if len(values) < 3 else None}
        if len(values) >= 3:
            mean_x, mean_y = sum(p[0] for p in points) / len(points), sum(values) / len(values)
            trend["slope_per_rep"] = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / sum((p[0] - mean_x) ** 2 for p in points)
        trends[name] = trend
    for i, row in enumerate(rows):
        row["previous_rep_id"] = rows[i - 1]["id"] if i else None
        row["versus_previous"] = {name: _delta(row["metrics"][name]["value"], rows[i - 1]["metrics"][name]["value"] if i else None, unit, "no_previous_rep" if not i else None) for name, unit in METRICS.items()}
        row["versus_session_median"] = {name: _delta(row["metrics"][name]["value"], references[name]["value"], unit, "insufficient_repetitions" if references[name]["valid_repetitions"] < 2 else None) for name, unit in METRICS.items()}
    return {"schema_version": 1, "units": METRICS.copy(), "method": {
        "delta": "current minus reference; percent uses absolute reference",
        "reference": "median of available values, including current rep; not a technique target",
        "extrema": "complete finite sample coverage required",
        "mean_velocity": "signed trapezoidal mean over valid adjacent ascent intervals; minimum 80% interval coverage",
        "velocity": "smoothed shoulder midpoint, positive upward, uncalibrated px/s; interpolated samples included",
        "pause": "contiguous bottom region: deepest 5% of hip excursion and <=10% peak absolute hip speed; minimum 0.2s",
        "trend": "OLS over original rep ordinals; minimum 3 available reps; descriptive, no fatigue or significance inference",
        "percent_reference_minimum": {"s": .01, "px/s": .1},
    }, "session_median": references, "repetitions": rows, "trends": trends}
