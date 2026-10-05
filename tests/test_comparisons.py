"""Known arithmetic, quality failures, Python/browser parity and saved exports."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from gymbromatics.comparisons import compare_repetitions


def fixture():
    samples, reps = [], []
    for i, half in enumerate((2, 3, 4)):
        start = len(samples)
        reps.append(dict(id=f"r{i}", start=start, bottom=start+half, end=start+2*half, source="auto"))
        samples.extend(dict(knee=100-10*i, hip=110-10*i, ankle=80-5*i,
                            velocity=10*(i+1), hip_y_smoothed_px=half-abs(j-half),
                            hip_velocity=-2 if j<half else 0 if j==half else 2,
                            interpolated=False) for j in range(2*half+1))
    return samples, reps


def assert_tree(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            assert_tree(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected)
        for a, e in zip(actual, expected):
            assert_tree(a, e)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert actual == pytest.approx(expected, abs=1e-10)
    else:
        assert actual == expected


def test_known_comparisons():
    samples, reps = fixture()
    before = copy.deepcopy((samples, reps))
    result = compare_repetitions(samples, reps, 2)
    assert (samples, reps) == before
    middle = result["repetitions"][1]
    assert middle["metrics"]["duration"]["value"] == 3
    assert middle["versus_previous"]["duration"]["delta"] == 1
    assert middle["versus_previous"]["duration"]["percent"] == 50
    assert middle["versus_previous"]["min_knee_angle"]["delta"] == -10
    assert middle["versus_previous"]["min_knee_angle"]["percent"] is None
    assert middle["versus_previous"]["bottom_pause"]["percent_reason"] == "near_zero_reference"
    assert middle["versus_session_median"]["duration"]["delta"] == 0
    assert result["trends"]["duration"]["slope_per_rep"] == 1
    assert result["trends"]["mean_ascent_velocity"]["slope_per_rep"] == 10
    assert result["trends"]["mean_ascent_velocity"]["first_to_last"]["percent"] == 200


def test_missing_single_empty_and_invalid():
    samples, reps = fixture()
    samples[reps[1]["bottom"]]["knee"] = None
    samples[reps[1]["bottom"]]["velocity"] = None
    samples[reps[1]["bottom"]]["hip_velocity"] = None
    result = compare_repetitions(samples, reps, 2)
    metrics = result["repetitions"][1]["metrics"]
    for key in ("min_knee_angle", "peak_ascent_velocity", "mean_ascent_velocity", "bottom_pause"):
        assert metrics[key]["value"] is None
        assert metrics[key]["coverage"] < 1
    assert result["repetitions"][2]["versus_previous"]["min_knee_angle"]["reason"] == "unavailable_metric"
    assert result["session_median"]["min_knee_angle"]["value"] == 90
    assert result["trends"]["min_knee_angle"]["slope_per_rep"] is None
    single = compare_repetitions(samples, reps[:1], 2)
    assert single["repetitions"][0]["versus_session_median"]["duration"]["reason"] == "insufficient_repetitions"
    assert compare_repetitions([], [], 2)["repetitions"] == []
    with pytest.raises(ValueError):
        compare_repetitions(samples, reps[::-1], 2)
    with pytest.raises(ValueError):
        compare_repetitions(samples, reps, 0)
    json.dumps(result, allow_nan=False)


@pytest.mark.skipif(not shutil.which("node"), reason="Node required for browser math parity")
def test_browser_math_parity():
    samples, reps = fixture()
    cases = [dict(samples=samples, repetitions=reps, fps=2),
             dict(samples=samples, repetitions=reps[:1], fps=2),
             dict(samples=[], repetitions=[], fps=2)]
    missing = copy.deepcopy(cases[0])
    for key in ("knee", "hip_velocity", "velocity"):
        missing["samples"][8][key] = None
    missing["samples"][16]["interpolated"] = True
    cases.append(missing)
    # Nonzero plateau and static/unmeasurable pause.
    plateau = copy.deepcopy(cases[0])
    for row in plateau["samples"]:
        row.update(hip_y_smoothed_px=10, hip_velocity=0)
    cases.append(copy.deepcopy(plateau))
    plateau["samples"][0].update(hip_y_smoothed_px=0, hip_velocity=-2)
    plateau["samples"][4].update(hip_y_smoothed_px=0, hip_velocity=2)
    cases.append(plateau)
    for name in ("squatsample", "squat_test2"):
        data = json.loads(Path(f"demo_artifacts/{name}_dashboard.json").read_text(encoding="utf-8"))
        cases.append(dict(samples=data["samples"], repetitions=data["repetitions"], fps=data["fps"]))
    script = """const fs=require('fs'),vm=require('vm');
    for(const f of ['dashboard_stats.js','comparisons.js']) vm.runInThisContext(fs.readFileSync('gymbromatics/'+f,'utf8'));
    const cases=JSON.parse(fs.readFileSync(0,'utf8'));
    process.stdout.write(JSON.stringify(cases.map(c=>compareRepetitions(c.samples,c.repetitions,c.fps))));"""
    actual = json.loads(subprocess.run([shutil.which("node"), "-e", script], input=json.dumps(cases), text=True,
                                      capture_output=True, check=True).stdout)
    for case, result in zip(cases, actual):
        assert_tree(result, compare_repetitions(**case))


@pytest.mark.skipif(os.environ.get("RUN_DASHBOARD_BROWSER_TEST") != "1", reason="Opt-in Chromium")
def test_updated_comparisons_saved_and_downloaded():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chromium")
        for name in ("squatsample", "squat_test2"):
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            path = Path(f"demo_artifacts/{name}_dashboard.html").resolve()
            original = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
            page.goto(path.as_uri())
            read_download = "async () => await (await fetch(document.getElementById('download').href)).json()"
            initial = page.evaluate(read_download)
            assert_tree(initial["repetition_comparisons"], original["repetition_comparisons"])
            page.locator('#session-stats-body button').first.click()
            page.locator('#mark-end').evaluate("e=>{e.dispatchEvent(new Event('pointerdown'));e.value=Number(e.value)-2;e.dispatchEvent(new Event('input'));e.dispatchEvent(new Event('change'));}")
            edited = page.evaluate(read_download)
            assert edited["repetitions"][0]["end"] == original["repetitions"][0]["end"]-2
            assert_tree(edited["repetition_comparisons"], compare_repetitions(edited["samples"], edited["repetitions"], edited["fps"]))
            stored = page.evaluate("id=>JSON.parse(localStorage.getItem('gymbromatics-reps-v1-'+id))", original['analysis_id'])
            assert_tree(stored['repetition_comparisons'], edited['repetition_comparisons'])
            # Loading older browser data must rebuild derived metrics while
            # preserving the user's repetition boundaries.
            page.evaluate("""id=>{
                const key='gymbromatics-reps-v1-'+id, saved=JSON.parse(localStorage.getItem(key));
                saved.repetition_comparisons.obsolete_metric=123;
                localStorage.setItem(key,JSON.stringify(saved));
            }""", original['analysis_id'])
            page.reload()
            assert_tree(page.evaluate(read_download)['repetition_comparisons'], edited['repetition_comparisons'])
            restored = page.evaluate("id=>JSON.parse(localStorage.getItem('gymbromatics-reps-v1-'+id))", original['analysis_id'])
            assert_tree(restored['repetition_comparisons'], edited['repetition_comparisons'])
            assert restored['repetitions'] == edited['repetitions']
            with page.expect_download() as download:
                page.locator('#export-reps').click()
            exported = json.loads(Path(download.value.path()).read_text(encoding='utf-8'))
            assert_tree(exported['repetition_comparisons'], edited['repetition_comparisons'])
            assert not errors
            page.close()
        browser.close()
