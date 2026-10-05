"""Stream video frames and JSON records without holding the video in memory."""

from dataclasses import asdict, dataclass
import json
import logging
import math
from pathlib import Path

import cv2

from .extractor import PoseExtractor
from .visualizer import AngleVisualizer, SkeletonVisualizer
from .squat_logic import SquatKinematics

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessingSummary:
    frames_processed: int
    frames_with_pose: int
    fps: float
    width: int
    height: int
    output_video: str
    output_json: str


def process_video(
    input_path: Path,
    output_path: Path,
    json_path: Path,
    extractor: PoseExtractor,
    visualizer: SkeletonVisualizer | None = None,
    kinematics: SquatKinematics | None = None,
) -> ProcessingSummary:
    paths = [path.resolve() for path in (input_path, output_path, json_path)]
    if len(set(paths)) != 3:
        raise ValueError("Input video, output video, and JSON must have distinct paths")
    if not input_path.is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}")
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("Output video must use the .mp4 extension")
    capture = cv2.VideoCapture(str(input_path))
    writer = None
    try:
        if not capture.isOpened():
            raise ValueError(f"Cannot open video: {input_path}")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0 or fps > 1000:
            raise ValueError(f"Unsupported video FPS: {fps}")
        ok, frame = capture.read()
        if not ok:
            raise ValueError("Input video contains no decodable frames")
        height, width = frame.shape[:2]
        if width % 2 or height % 2:
            raise ValueError("MP4 output requires even frame dimensions")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(
            str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
        )
        if not writer.isOpened():
            raise RuntimeError(f"Cannot create MP4 writer: {output_path}")
        renderer = visualizer or AngleVisualizer()
        analyzer = kinematics or SquatKinematics(renderer.confidence)
        count = detected = 0
        metadata = {
            "schema_version": 3, "input_video": str(input_path),
            "fps": fps, "width": width, "height": height,
            "coordinates": "normalized image x/y; y increases down; z is relative depth",
            "timestamp_source": "frame_index / fps (constant frame rate)",
            "landmark_names": "anatomical left/right; 33-point pose schema",
            "angles": {
                "units": "degrees", "space": "2D image pixels, aspect-ratio corrected",
                "convention": "interior segment angles in [0, 180]; angles decrease with squat flexion",
                "knee_angle_deg": "angle(hip-knee, ankle-knee); straight knee = 180",
                "hip_angle_deg": "angle(shoulder-hip, knee-hip); straight trunk-thigh = 180",
                "ankle_angle_deg": "angle(knee-ankle, toe-heel); perpendicular shin-foot = 90",
                "missing": "null; not carried forward", "display_side": "fixed after first measurable frame",
            },
        }
        with json_path.open("w", encoding="utf-8") as output:
            output.write('{"video": ' + json.dumps(metadata) + ', "frames": [\n')
            while ok:
                timestamp_ms = round(count * 1000.0 / fps)
                state = extractor.extract(frame, count, timestamp_ms)
                angles = analyzer.calculate(state, width, height)
                writer.write(renderer.draw(frame, state, angles))
                record = asdict(state)
                record["pose_detected"] = state.pose_detected
                record["angles"] = asdict(angles)
                if count:
                    output.write(',\n')
                output.write(json.dumps(record, allow_nan=False))
                count += 1
                detected += int(state.pose_detected)
                if count % 100 == 0:
                    logger.info("Processed %d frames (%d with pose)", count, detected)
                ok, frame = capture.read()
            summary = ProcessingSummary(count, detected, fps, width, height, str(output_path), str(json_path))
            output.write('\n], "summary": ' + json.dumps(asdict(summary)) + '}\n')
        return summary
    finally:
        capture.release()
        if writer is not None:
            writer.release()
