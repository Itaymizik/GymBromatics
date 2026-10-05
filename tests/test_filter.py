import numpy as np
import pytest

from gymbromatics.filter import smooth_vertical_motion


def test_vertical_velocity_sign_units_and_smoothing() -> None:
    fps = 30
    time = np.arange(120) / fps
    motion = smooth_vertical_motion(200 - 25 * time, fps)
    assert motion.velocity_up == pytest.approx(np.full(120, 25), abs=1e-8)
    assert smooth_vertical_motion(100 + 12 * time, fps).velocity_up == pytest.approx(np.full(120, -12), abs=1e-8)
    rng = np.random.default_rng(42)
    noisy = 200 - 25 * time + rng.normal(0, 1.5, len(time))
    filtered = smooth_vertical_motion(noisy, fps)
    raw_error = np.mean((-np.gradient(noisy, 1 / fps)[6:-6] - 25) ** 2)
    smooth_error = np.mean((filtered.velocity_up[6:-6] - 25) ** 2)
    assert smooth_error < raw_error * .2


def test_quadratic_motion_has_expected_changing_velocity() -> None:
    fps = 30
    time = np.arange(90) / fps
    motion = smooth_vertical_motion(100 + 5 * time ** 2, fps)
    assert motion.velocity_up == pytest.approx(-10 * time, abs=1e-8)


def test_short_gaps_interpolate_but_long_gaps_do_not_create_velocity_spikes() -> None:
    y = np.arange(90, dtype=float)
    y[:2] = np.nan
    y[20:23] = np.nan
    y[40:50] = np.nan
    y[50:] += 1000  # There must be no derivative across this disconnected segment.
    motion = smooth_vertical_motion(y, 30)
    assert motion.interpolated[20:23].all()
    assert not motion.interpolated[40:50].any()
    assert np.isnan(motion.velocity_up[:2]).all()
    assert np.isnan(motion.velocity_up[40:50]).all()
    assert motion.velocity_up[2:40] == pytest.approx(np.full(38, -30), abs=1e-8)
    assert motion.velocity_up[50:] == pytest.approx(np.full(40, -30), abs=1e-8)


def test_missing_short_and_invalid_inputs() -> None:
    assert np.isnan(smooth_vertical_motion(np.full(12, np.nan), 30).velocity_up).all()
    assert np.isnan(smooth_vertical_motion(np.arange(4), 30).velocity_up).all()
    assert len(smooth_vertical_motion(np.array([]), 30).velocity_up) == 0
    for fps in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            smooth_vertical_motion(np.arange(10), fps)
