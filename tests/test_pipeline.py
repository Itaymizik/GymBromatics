import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from gymbromatics.pipeline import process_video
from gymbromatics.state import FrameState, Landmark
from gymbromatics.visualizer import SkeletonVisualizer


def test_renderer_skips_missing_and_unreliable_points() -> None:
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    renderer = SkeletonVisualizer()
    assert np.array_equal(frame, renderer.draw(frame, FrameState(0, 0, {})))
    for point in (
        Landmark(.5, .5, 0, .1, 1),
        Landmark(.5, .5, 0, 1, .1),
        Landmark(float("nan"), .5, 0, 1, 1),
        Landmark(2, .5, 0, 1, 1),
    ):
        assert np.array_equal(frame, renderer.draw(frame, FrameState(0, 0, {"left_hip": point})))
    state = FrameState(0, 0, {
        "left_hip": Landmark(.5, .3, 0, 1, 1),
        "left_knee": Landmark(.5, .7, 0, 1, 1),
    })
    rendered = renderer.draw(frame, state)
    assert rendered[50, 50].any()  # The connecting limb, not just endpoint dots.
    assert not frame.any()  # Input pixels remain available for other consumers.


class FakeExtractor:
    def extract(self, frame: np.ndarray, frame_index: int, timestamp_ms: int) -> FrameState:
        # Deliberately lose the pose on alternating frames.
        points = {"left_hip": Landmark(.5, .5, 0, 1, 1)} if frame_index % 2 == 0 else {}
        return FrameState(frame_index, timestamp_ms, points)


def test_video_round_trip_preserves_frames_and_missing_pose(tmp_path: Path) -> None:
    source, target, data = (tmp_path / name for name in ("input.mp4", "result.mp4", "result.json"))
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 25, (100, 80))
    assert writer.isOpened()
    for _ in range(6):
        writer.write(np.zeros((80, 100, 3), dtype=np.uint8))
    writer.release()
    summary = process_video(source, target, data, FakeExtractor(), SkeletonVisualizer())
    assert summary.frames_processed == 6
    assert summary.frames_with_pose == 3
    records = json.loads(data.read_text(encoding="utf-8"))["frames"]
    assert [record["timestamp_ms"] for record in records] == [0, 40, 80, 120, 160, 200]
    assert records[1]["landmarks"] == {}
    assert records[1]["pose_detected"] is False
    assert records[1]["angles"]["left"]["knee_angle_deg"] is None
    capture = cv2.VideoCapture(str(target))
    try:
        assert capture.get(cv2.CAP_PROP_FPS) == 25
        frames = []
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
        assert len(frames) == 6
        assert frames[0].shape == (80, 100, 3)
        assert frames[0].any()
        # Lossy inter-frame encoding leaves small residuals on a blank frame.
        assert frames[1].max() < 15
        assert frames[1].mean() < 0.1
    finally:
        capture.release()


def test_rejects_overwriting_source_and_missing_input(tmp_path: Path) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(b"original")
    with pytest.raises(ValueError, match="distinct paths"):
        process_video(source, source, tmp_path / "data.json", FakeExtractor())
    assert source.read_bytes() == b"original"
    with pytest.raises(FileNotFoundError):
        process_video(tmp_path / "missing.mp4", tmp_path / "out.mp4", tmp_path / "data.json", FakeExtractor())
    with pytest.raises(ValueError, match="no decodable frames|Cannot open"):
        process_video(source, tmp_path / "out.mp4", tmp_path / "data.json", FakeExtractor())


def test_real_sample(tmp_path: Path) -> None:
    """Opt-in acceptance test: RUN_MEDIAPIPE_TEST=1; requires the local model."""
    import os
    if os.environ.get("RUN_MEDIAPIPE_TEST") != "1":
        pytest.skip("Set RUN_MEDIAPIPE_TEST=1 to process the real squat sample")
    from gymbromatics.extractor import MediaPipePoseExtractor
    from gymbromatics.model import DEFAULT_MODEL

    with MediaPipePoseExtractor(DEFAULT_MODEL) as extractor:
        summary = process_video(
            Path("data/squatsample.mp4"), tmp_path / "skeleton.mp4",
            tmp_path / "landmarks.json", extractor,
        )
    records = json.loads((tmp_path / "landmarks.json").read_text())["frames"]
    assert summary.frames_processed > 0
    assert summary.frames_with_pose / summary.frames_processed > .8
    assert len(records) == summary.frames_processed
    assert all(a["timestamp_ms"] < b["timestamp_ms"] for a, b in zip(records, records[1:]))
    assert all(len(r["landmarks"]) == 33 for r in records if r["pose_detected"])
    assert all(r["angles"]["display_side"] == records[0]["angles"]["display_side"] for r in records)
    side = records[0]["angles"]["display_side"]
    standing = records[0]["angles"][side]
    bottom = min((r["angles"][side] for r in records), key=lambda a: a["knee_angle_deg"])
    assert standing["knee_angle_deg"] > 160
    assert standing["hip_angle_deg"] > 160
    assert 75 < standing["ankle_angle_deg"] < 105
    assert bottom["knee_angle_deg"] < 100
    assert bottom["hip_angle_deg"] < standing["hip_angle_deg"]
    assert bottom["ankle_angle_deg"] < standing["ankle_angle_deg"]
