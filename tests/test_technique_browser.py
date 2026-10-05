"""Opt-in end-to-end tests for both portable dashboards and calibration."""
import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("RUN_DASHBOARD_BROWSER_TEST") != "1", reason="Opt-in Chromium")
@pytest.mark.parametrize("name,count", [("squatsample", 3), ("squat_test2", 5)])
def test_technique_notes_calibration_editing_and_mobile(name, count, tmp_path):
    from playwright.sync_api import sync_playwright
    artifact = Path(f"demo_artifacts/{name}_dashboard.html").resolve()
    data = json.loads(artifact.with_suffix(".json").read_text(encoding="utf-8"))
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page(viewport={"width": 1360, "height": 1050})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri())
        page.wait_for_function("document.getElementById('video').readyState >= 2")
        assert page.locator(".technique-rep").count() == count
        assert page.locator("#user-height").input_value() == ""
        assert "ללא כיול" in page.locator("#cal-status").inner_text()
        page.locator("#rep-list button[data-rep-id]").first.click()
        assert page.locator(".technique-rep").count() == 1
        assert page.locator(".technique-note").count() == 3
        note_before = page.locator(".technique-note").first.inner_text()
        page.locator("#rep-editor summary").click()
        page.locator("#mark-bottom").evaluate("e=>{e.value=Number(e.value)-8;e.dispatchEvent(new Event('input'));e.dispatchEvent(new Event('change'));}")
        # Depth uses the whole repetition, not the manually selected bottom window.
        assert page.locator(".technique-note").first.inner_text() == note_before
        page.locator("#undo-rep").click()
        assert page.locator(".technique-note").first.inner_text() == note_before
        page.locator(".technique-note button").first.click()
        assert int(page.locator("#scrubber").input_value()) > data["repetitions"][0]["start"]
        page.locator("#all-reps").click()
        page.locator(".calibration-panel summary").click()
        page.locator("#cal-capture").click()
        page.wait_for_function("!document.getElementById('cal-preview').hidden")
        # Synthetic height tests automatic scale, not a measured demo-person height.
        page.locator("#user-height").fill("180")
        assert "אוטומטי משוער פעיל" in page.locator("#cal-status").inner_text()
        initial_shank=float(page.locator('#cal-shank').input_value())
        page.locator('#cal-shank').fill(str(initial_shank+10))
        page.locator('#cal-shank').press('Tab')
        assert 'בתיקון ידני' in page.locator('#cal-status').inner_text()
        with page.expect_download() as download:
            page.locator("#export-technique").click()
        output = tmp_path / "technique.json"
        download.value.save_as(output)
        report = json.loads(output.read_text(encoding="utf-8"))
        assert report["calibration"]["cmPerPixel"] == pytest.approx(180 / (sum(report['calibration']['segments'].values())*1.06))
        assert report['calibration']['mode']=='manual-segments'
        assert report['calibration']['segments']['shank']==pytest.approx(initial_shank+10)
        assert len(report["repetitions"]) == count
        assert report["calibration"]["referenceFrame"] == data["repetitions"][0]["start"]
        page.reload()
        assert "פעיל" in page.locator("#cal-status").inner_text()
        assert page.locator("#user-height").input_value() == "180"
        assert 'בתיקון ידני' in page.locator('#cal-status').inner_text()
        page.locator('.calibration-panel summary').click()
        page.locator('#cal-clear').click()
        assert 'אוטומטי משוער פעיל' in page.locator('#cal-status').inner_text()
        assert float(page.locator('#cal-shank').input_value())==pytest.approx(initial_shank)
        page.locator('#cal-head').fill('25')
        page.locator('#cal-head').press('Tab')
        assert 'פעיל' not in page.locator('#cal-status').inner_text()
        page.locator('#cal-clear').click()
        # A new first-rep boundary must discard the old manual correction.
        page.locator('#cal-shank').fill(str(initial_shank+10))
        page.locator('#cal-shank').press('Tab')
        page.locator('#rep-list button[data-rep-id]').first.click()
        page.locator('#rep-editor summary').click()
        page.locator('#mark-start').evaluate("e=>{e.value=Number(e.value)+1;e.dispatchEvent(new Event('input'));e.dispatchEvent(new Event('change'));}")
        assert 'בתיקון ידני' not in page.locator('#cal-status').inner_text()
        page.locator('#undo-rep').click()
        page.locator("#user-height").fill("0")
        assert "משוער פעיל" not in page.locator("#cal-status").inner_text()
        page.locator("#user-height").fill("")
        page.select_option("#near-foot", "right")
        assert 'ימין' in page.locator('#foot-side-info').inner_text()
        page.reload()
        assert page.locator('#near-foot').input_value() == 'right'
        page.select_option("#near-foot", "auto")
        page.locator("#rep-list button[data-rep-id]").first.click()
        section=page.locator('section[aria-labelledby="technique-title"]')
        section.screenshot(path=f"outputs/{name}_technique_preview.png")
        page.set_viewport_size({"width": 375, "height": 850})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        section.screenshot(path=f"outputs/{name}_technique_mobile.png")
        assert not errors
        browser.close()
