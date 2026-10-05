import numpy as np
import pytest

from gymbromatics.squat_logic import SquatKinematics, angle_between
from gymbromatics.state import FrameState, Landmark
from gymbromatics.visualizer import AngleVisualizer


def pose(points: dict[str, tuple[float, float]], width: int = 641, height: int = 361) -> FrameState:
    return FrameState(0, 0, {f"left_{name}": Landmark(x / (width - 1), y / (height - 1), 0, 1, 1)
                              for name, (x, y) in points.items()})


STANDING = {"shoulder": (200, 40), "hip": (200, 120), "knee": (200, 200),
            "ankle": (200, 280), "heel": (180, 300), "foot_index": (240, 300)}


def test_neutral_angles_and_known_flexion() -> None:
    result = SquatKinematics().calculate(pose(STANDING), 641, 361)
    assert result.selected.values() == pytest.approx((180, 180, 90))
    # Horizontal thigh / vertical trunk and shin = 90-degree interior angles.
    bent = dict(STANDING, hip=(120, 200), shoulder=(120, 120))
    assert SquatKinematics().calculate(pose(bent), 641, 361).selected.values() == pytest.approx((90, 90, 90))
    bent["knee"] = (240, 240)
    assert SquatKinematics().calculate(pose(bent), 641, 361).selected.ankle_angle_deg == pytest.approx(45)
    bent["knee"] = (160, 240)
    assert SquatKinematics().calculate(pose(bent), 641, 361).selected.ankle_angle_deg == pytest.approx(135)


@pytest.mark.parametrize("degrees", [30, 60, 120, 150])
@pytest.mark.parametrize("joint", ["knee", "hip", "ankle"])
def test_interior_angles_not_complement_or_supplement(joint: str, degrees: float) -> None:
    points = dict(STANDING)
    radians = np.radians(degrees)
    if joint == "ankle":
        center = np.array(points["ankle"])
        points["knee"] = tuple(center + 60 * np.array([np.cos(radians), -np.sin(radians)]))
    else:
        center = np.array(points[joint])
        moving_point = "ankle" if joint == "knee" else "knee"
        points[moving_point] = tuple(center + 60 * np.array([np.sin(radians), -np.cos(radians)]))
    angles = SquatKinematics().calculate(pose(points), 641, 361).selected
    assert getattr(angles, f"{joint}_angle_deg") == pytest.approx(degrees)


def test_aspect_ratio_mirror_and_resize_invariance() -> None:
    bent = dict(STANDING, hip=(120, 200), shoulder=(80, 120), knee=(240, 240))
    expected = SquatKinematics().calculate(pose(bent), 641, 361).selected.values()
    mirrored = {name: (640 - x, y) for name, (x, y) in bent.items()}
    assert SquatKinematics().calculate(pose(mirrored), 641, 361).selected.values() == pytest.approx(expected)
    resized = {name: (x * 2, y * 2) for name, (x, y) in bent.items()}
    assert SquatKinematics().calculate(pose(resized, 1281, 721), 1281, 721).selected.values() == pytest.approx(expected)
    # For this geometry the shin/foot angle is 45 degrees in pixels,
    # whereas computing directly from normalized 16:9 coordinates is incorrect.
    assert expected[2] == pytest.approx(45)


def test_missing_confidence_degenerate_and_no_stale_values() -> None:
    calculator = SquatKinematics()
    state = pose(STANDING)
    assert calculator.calculate(state, 641, 361).display_side == "left"
    points = dict(state.landmarks)
    points["left_knee"] = Landmark(.5, .5, 0, .1, 1)
    lost = calculator.calculate(FrameState(1, 33, points), 641, 361)
    assert lost.selected.values() == (None, None, None)
    assert lost.display_side == "left"
    assert calculator.calculate(FrameState(2, 66, {}), 641, 361).selected.values() == (None, None, None)
    assert angle_between(np.zeros(2), np.ones(2)) is None
    assert angle_between(np.array([float("nan"), 1]), np.ones(2)) is None
    points = dict(state.landmarks)
    points["left_knee"] = points["left_hip"]
    assert calculator.calculate(FrameState(3, 99, points), 641, 361).selected.knee_angle_deg is None


def test_selected_side_remains_stable_and_can_be_overridden() -> None:
    state = pose(STANDING)
    calculator = SquatKinematics()
    calculator.calculate(state, 641, 361)
    right_only = FrameState(1, 33, {name.replace("left", "right"): p for name, p in state.landmarks.items()})
    result = calculator.calculate(right_only, 641, 361)
    assert result.display_side == "left"
    assert result.selected.values() == (None, None, None)
    assert result.right.values() == pytest.approx((180, 180, 90))
    assert SquatKinematics(side="right").calculate(right_only, 641, 361).selected.values() == pytest.approx((180, 180, 90))


@pytest.mark.parametrize("width,height", [(640, 360), (360, 640), (100, 80)])
def test_angle_overlay_handles_missing_tracking_and_sizes(width: int, height: int) -> None:
    blank = np.zeros((height, width, 3), dtype=np.uint8)
    state = FrameState(0, 0, {})
    result = AngleVisualizer().draw(blank, state, SquatKinematics().calculate(state, width, height))
    assert result.shape == blank.shape
    assert result.any()  # Dashboard remains with '--' for missing measurements.
    assert not blank.any()
