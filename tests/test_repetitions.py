import json
from pathlib import Path

import numpy as np

from gymbromatics.dashboard import build_dashboard_data
from gymbromatics.repetitions import detect_repetitions


def series() -> tuple[np.ndarray, np.ndarray]:
    # Three deliberate cycles with standing intervals and a pause at the bottom.
    cycle = np.r_[np.zeros(15), np.linspace(0, 1, 30), np.ones(15), np.linspace(1, 0, 30), np.zeros(15)]
    movement = np.tile(cycle, 3)
    return 100 + 80 * movement, 178 - 100 * movement


def test_three_full_cycles_include_pauses_without_double_counting() -> None:
    hip, knee = series()
    reps = detect_repetitions(hip, knee, 30, 360)
    assert len(reps) == 3
    for index, rep in enumerate(reps):
        assert index * 105 < rep.start < rep.bottom < rep.end < (index + 1) * 105
        assert 140 < knee[rep.start] <= 180
        assert knee[rep.bottom] < 90
        assert not rep.needs_review
    assert all(a.end <= b.start for a, b in zip(reps, reps[1:]))


def test_noise_and_straight_knee_translation_are_not_repetitions() -> None:
    rng = np.random.default_rng(7)
    assert not detect_repetitions(100 + rng.normal(0, .5, 200), np.full(200, 178), 30, 360)
    hip, _ = series()
    assert not detect_repetitions(hip, np.full(len(hip), 178), 30, 360)


def test_changing_standing_height_does_not_merge_adjacent_repetitions() -> None:
    hip, knee = series()
    hip = hip + np.arange(len(hip)) * .2
    reps = detect_repetitions(hip, knee, 30, 360)
    assert len(reps) == 3
    for index, rep in enumerate(reps):
        assert index * 105 <= rep.start < rep.bottom < rep.end < (index + 1) * 105


def test_incomplete_edges_and_long_occlusion_are_not_joined() -> None:
    hip, knee = series()
    # First cycle starts in the hole; last cycle never returns to standing.
    reps = detect_repetitions(hip[50:-50], knee[50:-50], 30, 360)
    assert len(reps) == 1
    hip[42:63] = np.nan
    reps = detect_repetitions(hip, knee, 30, 360)
    assert len(reps) == 2
    assert reps[0].start > 100


def test_short_gaps_and_missing_knee_are_marked_for_review() -> None:
    hip, knee = series()
    hip[30:32] = np.nan
    knee[145] = np.nan
    reps = detect_repetitions(hip, knee, 30, 360)
    assert len(reps) == 3
    assert [r.needs_review for r in reps] == [True, True, False]


def test_real_sample_has_three_reproducible_proposals_and_identity() -> None:
    path = Path('outputs/squatsample_landmarks.json')
    if not path.is_file():
        import pytest
        pytest.skip('Requires previously processed squat sample')
    source = json.loads(path.read_text())
    result = build_dashboard_data(source)
    assert len(result['repetitions']) == 3
    assert [r['bottom'] for r in result['repetitions']] == sorted(r['bottom'] for r in result['repetitions'])
    assert result['analysis_id'] == build_dashboard_data(source)['analysis_id']
    source['frames'][0]['landmarks']['left_hip']['y'] += .001
    assert build_dashboard_data(source)['analysis_id'] != result['analysis_id']
