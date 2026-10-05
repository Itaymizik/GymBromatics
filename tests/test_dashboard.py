import copy

import pytest

from gymbromatics.dashboard import build_dashboard_data


def analysis_fixture() -> dict:
    frames = []
    for index in range(60):
        point = {"x": .5, "y": .8 - index / 300, "z": 0, "visibility": 1, "presence": 1}
        frames.append({
            "frame_index": index,
            "landmarks": {"left_shoulder": dict(point), "right_shoulder": dict(point)},
            "angles": {"display_side": "left", "left": {
                "knee_angle_deg": 180 - index, "hip_angle_deg": 170 - index,
                "ankle_angle_deg": 90 - index / 10,
            }},
        })
    return {"video": {"schema_version": 3, "fps": 30, "height": 301, "input_video": "sample.mp4"}, "frames": frames}


def test_profile_keeps_frame_time_angles_and_speed_aligned() -> None:
    result = build_dashboard_data(analysis_fixture())
    assert result["duration"] == 2
    assert len(result["samples"]) == 60
    sample = result["samples"][30]
    assert sample["time"] == 1
    assert sample["velocity"] == pytest.approx(30)
    assert (sample["knee"], sample["hip"], sample["ankle"]) == (150, 140, 87)
    assert result["measurement"]["unit"] == "px/s"


def test_both_shoulders_required_and_angles_not_fabricated() -> None:
    analysis = analysis_fixture()
    for index in range(20, 35):
        analysis["frames"][index]["landmarks"]["right_shoulder"]["visibility"] = .1
    analysis["frames"][25]["angles"]["left"]["ankle_angle_deg"] = None
    result = build_dashboard_data(analysis)
    assert result["samples"][25]["velocity"] is None
    assert result["samples"][25]["ankle"] is None
    assert result["samples"][25]["knee"] == 155
    short_gap = copy.deepcopy(analysis_fixture())
    short_gap["frames"][20]["landmarks"] = {}
    sample = build_dashboard_data(short_gap)["samples"][20]
    assert sample["chest_y_px"] is None
    assert sample["interpolated"] is True
    assert sample["velocity"] == pytest.approx(30)


def test_empty_old_schema_and_nonconsecutive_frames_rejected() -> None:
    source = analysis_fixture()
    source["video"]["schema_version"] = 2
    with pytest.raises(ValueError, match="schema v3"):
        build_dashboard_data(source)
    source = analysis_fixture()
    source["frames"][3]["frame_index"] = 5
    with pytest.raises(ValueError, match="consecutive"):
        build_dashboard_data(source)
    source["frames"] = []
    with pytest.raises(ValueError, match="empty"):
        build_dashboard_data(source)
