"""Run with python -m gymbromatics data/squatsample.mp4."""

import argparse
from dataclasses import asdict
import json
import logging
from pathlib import Path

from .extractor import MediaPipePoseExtractor
from .model import DEFAULT_MODEL, download_model
from .pipeline import process_video
from .visualizer import AngleVisualizer
from .squat_logic import SquatKinematics


def confidence_value(value: str) -> float:
    number = float(value)
    if not 0 <= number <= 1:
        raise argparse.ArgumentTypeError("confidence must be between 0 and 1")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description="Overlay a MediaPipe skeleton on a squat video")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="Default: outputs/<input>_skeleton.mp4")
    parser.add_argument("--json", type=Path, help="Default: outputs/<input>_landmarks.json")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--download-model", action="store_true", help="Download Google's full model if missing")
    parser.add_argument("--confidence", type=confidence_value, default=0.5)
    parser.add_argument("--side", choices=("auto", "left", "right"), default="auto", help="Side shown in the angle overlay; auto locks the most visible side")
    parser.add_argument("--dashboard", action="store_true", help="Also export a portable interactive chest-velocity dashboard")
    feedback = parser.add_mutually_exclusive_group()
    feedback.add_argument("--feedback", action="store_true", help="Generate Hebrew feedback using a confirmed Gemini Free Tier key")
    feedback.add_argument("--feedback-prepare-only", action="store_true", help="Save feedback evidence without a cloud call")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    output_path = args.output or Path("outputs") / f"{args.input.stem}_skeleton.mp4"
    json_path = args.json or Path("outputs") / f"{args.input.stem}_landmarks.json"
    feedback_path = output_path.with_name(f"{args.input.stem}_feedback.json")
    try:
        if args.feedback or args.feedback_prepare_only:
            reserved = {p.resolve() for p in (args.input, output_path, json_path, Path('.env.local'))}
            if any(p.resolve() in reserved for p in (feedback_path, feedback_path.with_name(feedback_path.stem+'_input.json'))):
                raise ValueError('Feedback outputs must not overwrite other inputs/outputs')
        if not args.input.is_file():
            raise FileNotFoundError(f"Input video not found: {args.input}")
        if args.download_model:
            logging.info("Preparing model: %s", args.model)
            download_model(args.model)
        if not args.model.is_file():
            raise FileNotFoundError("Pose model missing. Pass --download-model or --model <path>.")
        with MediaPipePoseExtractor(args.model, args.confidence) as extractor:
            summary = process_video(
                args.input, output_path, json_path, extractor, AngleVisualizer(args.confidence),
                SquatKinematics(args.confidence, None if args.side == "auto" else args.side),
            )
        print(json.dumps(asdict(summary), indent=2))
        if args.dashboard:
            from .dashboard import export_dashboard

            dashboard_path = output_path.with_name(f"{args.input.stem}_dashboard.html")
            export_dashboard(json_path, output_path, dashboard_path, args.confidence)
            logging.info("Dashboard: %s", dashboard_path)
        if args.feedback or args.feedback_prepare_only:
            from .dashboard import build_dashboard_data
            from .feedback import generate_session_feedback

            session = build_dashboard_data(json.loads(json_path.read_text(encoding='utf-8')), args.confidence)
            feedback_result = generate_session_feedback(session, feedback_path, prepare_only=args.feedback_prepare_only)
            logging.info("Feedback: %s (%s%s)", feedback_path, feedback_result['status'],
                         ', '+feedback_result['error_code'] if feedback_result.get('error_code') else '')
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
