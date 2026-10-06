# Architecture and data contract

[← Back to README](../README.md)

## Modules

- `state.py`: provider-independent `Landmark` and `FrameState` dataclasses.
- `extractor.py`: `PoseExtractor` interface and the MediaPipe video adapter.
- `visualizer.py`: OpenCV drawing from named landmarks, without MediaPipe types.
- `squat_logic.py`: bilateral 2D joint angles, confidence gating and stable display-side selection.
- `pipeline.py`: video I/O, timestamps, JSON streaming and resource cleanup.
- `model.py`: optional model download and local cache.
- `filter.py`: gap-aware trajectory smoothing and vertical velocity calculation.
- `dashboard.py` / `dashboard.html` / `dashboard.js`: portable interactive video/velocity/angle report.
- `repetitions.py`: automatic squat-cycle proposals from the hip trajectory.
- `technique.py` / `technique.js` / `technique_ui.js` / `calibration.js`: geometry-based technique notes and height calibration.
- `comparisons.py` / `comparisons.js`: per-repetition comparisons (Python/JavaScript parity).
- `feedback.py` / `feedback_provider.py`: optional Gemini feedback sidecar.
- `api.py` / `chat.py` / `chat_server.py` / `chat_ui.js`: FastAPI server and session chat.

The pose layer is isolated behind `PoseExtractor`, so MediaPipe can be replaced
(e.g. by YOLO-Pose) without changing the kinematics modules.

## Landmark data contract

Coordinates are normalized image `x`, `y` and relative-depth `z`, with confidence
values `visibility` and `presence`. Y increases downwards; z is **not** a calibrated
distance in metres. Left/right names refer to the subject's anatomy. Hip, knee,
ankle and wrist landmarks are available by name for squat analysis.

Missing detections produce `pose_detected: false` and `landmarks: {}`. The frame
is still written. Low-confidence landmarks remain in JSON, but points and limbs
are drawn only when both visibility and presence meet the threshold. Downstream
analysis must use the same reliability check or interpolate gaps before analysis.
