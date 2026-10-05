import copy
import pytest

from gymbromatics.technique import build_technique_trajectories


def source_frames():
    return [{"angles": {"display_side": "left"}, "landmarks": {
        f"left_{name}": {"x": .4, "y": .6, "z": 0, "visibility": .9, "presence": .9}
        for name in ("hip", "shoulder", "knee", "heel", "foot_index")}} for _ in range(30)]


def test_pixel_aspect_ratio_and_no_occlusion_interpolation():
    frames = source_frames()
    frames[15]["landmarks"]["left_heel"]["visibility"] = .1
    frames[16]["landmarks"]["left_heel"]["presence"] = .1
    frames[17]["landmarks"]["left_heel"]["x"] = 1.1
    result = build_technique_trajectories(frames, 1001, 501, 30)
    assert result["frames"][10]["hip"][0] == pytest.approx(400)
    assert result["frames"][10]["hip"][1] == pytest.approx(300)
    assert all(result["frames"][i]["heel"] is None for i in (15, 16, 17))
    assert result["frames"][15]["hip"] is not None


def test_unknown_dimensions_or_short_pose_is_unavailable():
    assert build_technique_trajectories(source_frames(), 0, 501, 30)["frames"][10]["hip"] is None
    assert build_technique_trajectories(source_frames()[:4], 1001, 501, 30)["frames"][0]["hip"] is None


def test_does_not_modify_input_or_switch_to_hidden_side():
    frames = source_frames()
    original = copy.deepcopy(frames)
    result = build_technique_trajectories(frames, 1001, 501, 30)
    assert frames == original
    assert result["side"] == "left"


def test_foot_side_is_selected_independently_and_angles_are_confidence_gated():
    frames = source_frames()
    for frame in frames:
        frame['angles']['left'] = {'knee_angle_deg': 90.0}
        frame['landmarks']['left_ankle'] = dict(frame['landmarks']['left_knee'])
        for suffix in ('heel', 'foot_index'):
            frame['landmarks'][f'right_{suffix}'] = dict(frame['landmarks'][f'left_{suffix}'])
            frame['landmarks'][f'left_{suffix}']['visibility'] = .1
    frames[15]['landmarks']['left_ankle']['visibility'] = .1
    result = build_technique_trajectories(frames, 1001, 501, 30)
    assert result['side'] == 'left'
    assert result['foot_side'] == 'right'
    assert result['frames'][10]['heel'] is not None
    assert result['frames'][10]['feet']['left']['heel'] is None
    assert result['frames'][10]['knee_angle_deg'] == 90
    assert result['frames'][15]['knee_angle_deg'] is None
