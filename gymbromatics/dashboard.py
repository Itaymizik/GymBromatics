"""Generate a portable offline HTML dashboard from an existing analysis JSON."""

import argparse
from dataclasses import asdict
import hashlib
import base64
import json
import math
from pathlib import Path
import subprocess
import tempfile
from typing import Any

import imageio_ffmpeg
import numpy as np

from .filter import smooth_vertical_motion
from .state import Landmark
from .repetitions import detect_repetitions
from .technique import build_technique_trajectories
from .comparisons import compare_repetitions


def build_dashboard_data(analysis: dict[str, Any], confidence: float = 0.5) -> dict[str, Any]:
    """Shoulder midpoint is a chest proxy, not a sternum or barbell landmark."""
    if not 0 <= confidence <= 1:
        raise ValueError("Confidence must be between 0 and 1")
    metadata = analysis["video"]
    if metadata.get("schema_version") != 3:
        raise ValueError("Dashboard requires schema v3 interior joint angles; reprocess the video")
    frames = analysis["frames"]
    if not frames:
        raise ValueError("Cannot build a dashboard from an empty analysis")
    fps = float(metadata["fps"])
    height = int(metadata["height"])
    if height < 2 or not math.isfinite(fps) or fps <= 0:
        raise ValueError("Invalid video dimensions or FPS")
    raw_y = np.full(len(frames), np.nan)
    for index, frame in enumerate(frames):
        if frame["frame_index"] != index:
            raise ValueError("Dashboard requires consecutive frame indices beginning at zero")
        shoulders = []
        for side in ("left", "right"):
            value = frame["landmarks"].get(f"{side}_shoulder")
            if value is not None:
                point = Landmark(**value)
                if point.is_reliable(confidence) and 0 <= point.x <= 1 and 0 <= point.y <= 1:
                    shoulders.append(point.y)
        if len(shoulders) == 2:
            raw_y[index] = sum(shoulders) / 2 * (height - 1)
    motion = smooth_vertical_motion(raw_y, fps)
    hip_y = np.full(len(frames), np.nan)
    knees = np.full(len(frames), np.nan)
    for index, frame in enumerate(frames):
        side = frame["angles"]["display_side"]
        point_data = frame["landmarks"].get(f"{side}_hip")
        if point_data is not None:
            point = Landmark(**point_data)
            if point.is_reliable(confidence) and 0 <= point.x <= 1 and 0 <= point.y <= 1:
                hip_y[index] = point.y * (height - 1)
        value = frame["angles"].get(side, {}).get("knee_angle_deg")
        if value is not None:
            knees[index] = value
    repetitions = detect_repetitions(hip_y, knees, fps, height)
    hip_motion = smooth_vertical_motion(hip_y, fps)

    def finite(value: float) -> float | None:
        return float(value) if np.isfinite(value) else None

    samples = []
    for index, frame in enumerate(frames):
        side = frame["angles"]["display_side"]
        sample_angles = frame["angles"].get(side, {})
        samples.append({
            "frame": index, "time": index / fps,
            "velocity": finite(motion.velocity_up[index]),
            "hip_y_smoothed_px": finite(hip_motion.y_smoothed[index]),
            "hip_velocity": finite(hip_motion.velocity_up[index]),
            "chest_y_px": finite(raw_y[index]),
            "chest_y_smoothed_px": finite(motion.y_smoothed[index]),
            "interpolated": bool(motion.interpolated[index]),
            "side": side,
            "knee": sample_angles.get("knee_angle_deg"),
            "hip": sample_angles.get("hip_angle_deg"),
            "ankle": sample_angles.get("ankle_angle_deg"),
        })
    # Tie saved edits to the actual analysis, not just a reusable filename.
    identity = hashlib.sha256(json.dumps(analysis, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "analysis_id": identity,
        "technique": build_technique_trajectories(frames, int(metadata.get("width", 0)), height, fps),
        "repetitions": [asdict(rep) for rep in repetitions],
        "repetition_comparisons": compare_repetitions(samples, [asdict(rep) for rep in repetitions], fps),
        "repetition_method": "Smoothed selected-side hip Y peaks; upright return and knee-angle checks. Complete cycles only; review suggested boundaries.",
        "name": Path(metadata["input_video"]).name,
        "fps": fps, "duration": len(frames) / fps, "samples": samples,
        "measurement": {
            "point": "midpoint of left and right shoulders (chest proxy)",
            "axis": "vertical image axis", "unit": "px/s", "positive": "upward",
            "filter": "Savitzky-Golay, polynomial order 2; differentiate after smoothing",
            "window_frames": motion.window_frames, "max_gap_seconds": 0.15,
            "confidence_threshold": confidence,
            "calibration": "uncalibrated 2D image; no conversion to metres",
            "time": "frame_index / fps, constant frame rate",
        },
    }


def export_dashboard(
    analysis_path: Path, video_path: Path, output_path: Path, confidence: float = 0.5,
) -> Path:
    if output_path.suffix.lower() != ".html":
        raise ValueError("Dashboard output must have an .html extension")
    profile_path = output_path.with_suffix(".json")
    paths = [p.resolve() for p in (analysis_path, video_path, output_path, profile_path)]
    if len(set(paths)) != len(paths):
        raise ValueError("Dashboard outputs must not overwrite their inputs")
    data = build_dashboard_data(json.loads(analysis_path.read_text(encoding="utf-8")), confidence)
    if not video_path.is_file():
        raise FileNotFoundError(f"Annotated video not found: {video_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # OpenCV's mp4v is not consistently browser-decodable. Embed an H.264 copy
    # so the dashboard works offline with no server, external CDN or file fetch.
    with tempfile.TemporaryDirectory(prefix="dashboard-", dir=output_path.parent) as temp:
        compatible = Path(temp) / "video.mp4"
        command = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
            "-i", str(video_path.resolve()), "-map", "0:v:0", "-an",
            "-c:v", "libx264", "-crf", "20", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(compatible.resolve()),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=300)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f"Video conversion failed: {error.stderr.decode(errors='replace')}") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Video conversion exceeded the 5-minute timeout") from error
        encoded_video = base64.b64encode(compatible.read_bytes()).decode("ascii")
    template = Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")
    # Escape '<' so filenames cannot terminate the JSON script element.
    payload = json.dumps(data, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c")
    script = "\n".join(Path(__file__).with_name(name).read_text(encoding="utf-8")
                       for name in ("dashboard_stats.js", "comparisons.js", "technique.js", "calibration.js", "technique_ui.js", "chat_ui.js", "dashboard.js"))
    html = template.replace("__DASHBOARD_DATA__", payload).replace("__VIDEO_BASE64__", encoded_video).replace("__DASHBOARD_SCRIPT__", script)
    output_path.write_text(html, encoding="utf-8")
    profile_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an offline velocity/angle dashboard without repeating pose extraction")
    parser.add_argument("analysis", type=Path)
    parser.add_argument("--video", type=Path, required=True, help="Annotated video matching the analysis")
    parser.add_argument("--output", type=Path, default=Path("outputs/squatsample_dashboard.html"))
    parser.add_argument("--confidence", type=float, default=0.5)
    feedback = parser.add_mutually_exclusive_group()
    feedback.add_argument("--feedback", action="store_true", help="Also generate Hebrew feedback using Gemini Free Tier")
    feedback.add_argument("--feedback-prepare-only", action="store_true", help="Save feedback evidence without a cloud call")
    args = parser.parse_args()
    try:
        feedback_path = args.output.with_name(args.output.stem.removesuffix('_dashboard')+'_feedback.json')
        if args.feedback or args.feedback_prepare_only:
            reserved = {p.resolve() for p in (args.analysis, args.video, args.output, args.output.with_suffix('.json'), Path('.env.local'))}
            if any(p.resolve() in reserved for p in (feedback_path, feedback_path.with_name(feedback_path.stem+'_input.json'))):
                raise ValueError('Feedback outputs must not overwrite other inputs/outputs')
        result = export_dashboard(args.analysis, args.video, args.output, args.confidence)
        if args.feedback or args.feedback_prepare_only:
            from .feedback import generate_session_feedback
            session = json.loads(args.output.with_suffix('.json').read_text(encoding='utf-8'))
            feedback_result = generate_session_feedback(session, feedback_path, prepare_only=args.feedback_prepare_only)
            print(json.dumps({'feedback':str(feedback_path), 'status':feedback_result['status'],
                              'error_code':feedback_result.get('error_code')}))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Error: {error}\n")
    print(result)


if __name__ == "__main__":
    main()
