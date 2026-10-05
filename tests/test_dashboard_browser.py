"""Opt-in browser acceptance test against the generated portable dashboard."""

import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("RUN_DASHBOARD_BROWSER_TEST") != "1", reason="Opt-in local Chromium dashboard test")
def test_graph_video_angles_keyboard_and_mobile() -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    artifact = Path(os.environ.get("DASHBOARD_HTML", "demo_artifacts/squatsample_dashboard.html")).resolve()
    data = json.loads(artifact.with_suffix(".json").read_text(encoding="utf-8"))
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page(viewport={"width": 1360, "height": 1050}, device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri())
        page.wait_for_function("document.getElementById('video').readyState >= 2")
        assert page.locator("#video-error").is_hidden()
        assert page.locator("#time").inner_text() == "0.00"
        page.locator("#chart").scroll_into_view_if_needed()
        bounds = page.locator("#chart").bounding_box()
        selected = 80
        # Click a point on the time axis and verify the actual displayed measurements.
        click_x = bounds["x"] + 58 + selected / (len(data["samples"]) - 1) * (bounds["width"] - 78)
        page.mouse.click(click_x, bounds["y"] + bounds["height"] / 2)
        target = data["samples"][selected]
        assert page.locator("#scrubber").input_value() == str(selected)
        assert float(page.locator("#time").inner_text()) == pytest.approx(target["time"], abs=.005)
        for name in ("knee", "hip", "ankle"):
            assert page.locator(f"#{name}").inner_text() == f"{target[name]:.1f}°"
        assert page.locator("#video").evaluate("v => v.paused")
        assert page.locator("#video").evaluate("v => v.currentTime") == pytest.approx(target["time"], abs=1 / data["fps"])
        page.wait_for_function("!document.getElementById('video').seeking")
        page.screenshot(path=str(artifact.with_name(artifact.stem + '_preview.png')), full_page=True)
        page.locator("#next").click()
        assert page.locator("#scrubber").input_value() == "81"
        page.locator("#scrubber").focus()
        page.keyboard.press("ArrowLeft")
        assert page.locator("#scrubber").input_value() == "80"
        page.locator("#play").click()
        page.wait_for_function("Number(document.getElementById('scrubber').value) > 82")
        page.locator("#play").click()
        assert page.locator("#video").evaluate("v => v.paused")
        assert page.locator("#download").get_attribute("href").startswith("blob:")
        page.set_viewport_size({"width": 375, "height": 900})
        page.wait_for_function("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(artifact.with_name(artifact.stem + '_mobile_preview.png')), full_page=True)
        assert not errors, errors
        browser.close()


@pytest.mark.skipif(os.environ.get("RUN_DASHBOARD_BROWSER_TEST") != "1", reason="Opt-in local Chromium dashboard test")
def test_repetition_editing_persistence_import_export_and_loop(tmp_path: Path) -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    artifact = Path("demo_artifacts/squatsample_dashboard.html").resolve()
    data = json.loads(artifact.with_suffix('.json').read_text(encoding='utf-8'))
    first = data['repetitions'][0]
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel='chromium')
        page = browser.new_page(viewport={'width':1360,'height':1100})
        errors=[]
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(artifact.as_uri())
        page.wait_for_function("document.getElementById('video').readyState >= 2")
        buttons = page.locator('#rep-list button[data-rep-id]')
        assert buttons.count() == 3
        buttons.first.click()
        assert int(page.locator('#scrubber').input_value()) == first['start']
        assert int(page.locator('#scrubber').get_attribute('max')) < len(data['samples'])-1
        page.locator('#rep-editor summary').click()
        page.locator('#mark-bottom').focus()
        page.keyboard.press('ArrowRight')
        assert int(page.locator('#mark-bottom').input_value()) == first['bottom']+1
        page.locator('#undo-rep').click()
        assert int(page.locator('#mark-bottom').input_value()) == first['bottom']
        # Drag the actual chart handle, then verify undo restores the proposal.
        handle = page.locator('#handle-bottom')
        handle.scroll_into_view_if_needed()
        box = handle.bounding_box()
        page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2)
        page.mouse.down()
        page.mouse.move(box['x']+box['width']/2+40,box['y']+box['height']/2,steps=5)
        page.mouse.up()
        assert int(page.locator('#mark-bottom').input_value()) > first['bottom']
        page.locator('#undo-rep').click()
        assert int(page.locator('#mark-bottom').input_value()) == first['bottom']
        page.locator('#mark-bottom').focus()
        page.keyboard.press('ArrowRight')
        page.reload()
        page.wait_for_function("document.getElementById('video').readyState >= 2")
        buttons.first.click()
        assert int(page.locator('#mark-bottom').input_value()) == first['bottom']+1
        page.locator('#rep-editor summary').click()
        page.locator('#delete-rep').click()
        assert buttons.count() == 2
        page.locator('#undo-rep').click()
        assert buttons.count() == 3
        page.locator('#delete-rep').click()

        def click_frame(index: int) -> None:
            page.locator('#chart').scroll_into_view_if_needed()
            chart=page.locator('#chart').bounding_box()
            x=chart['x']+58+index/(len(data['samples'])-1)*(chart['width']-78)
            page.mouse.click(x,chart['y']+chart['height']/2)
            assert int(page.locator('#scrubber').input_value()) == index

        page.locator('#add-rep').click()
        for index in (first['start'],first['bottom'],first['end']):
            click_frame(index)
            page.locator('#record-marker').click()
        assert buttons.count() == 3
        assert 'manual-' in buttons.first.get_attribute('data-rep-id')
        page.locator('#zoom-rep').uncheck()
        click_frame(0)
        if page.locator('#rep-editor').get_attribute('open') is None:
            page.locator('#rep-editor summary').click()
        page.locator('#set-bottom').click()
        assert page.locator('#rep-status').get_attribute('data-error') == 'true'
        assert int(page.locator('#mark-bottom').input_value()) == first['bottom']
        with page.expect_download() as download_info:
            page.locator('#export-reps').click()
        exported=tmp_path/'reps.json'
        download_info.value.save_as(exported)
        saved=json.loads(exported.read_text(encoding='utf-8'))
        assert saved['analysis_id']==data['analysis_id']
        assert saved['repetitions'][0]['start']==first['start']
        import_input=page.locator('#import-reps')
        import_input.locator('xpath=ancestor::details').locator('summary').click()
        invalid={**saved,'analysis_id':'different-video'}
        import_input.set_input_files({'name':'invalid.json','mimeType':'application/json','buffer':json.dumps(invalid).encode()})
        page.wait_for_function("document.getElementById('rep-status').dataset.error==='true'")
        assert buttons.count()==3
        page.locator('#reset-reps').click()
        assert buttons.first.get_attribute('data-rep-id').startswith('auto-')
        import_input.set_input_files(str(exported))
        page.wait_for_function("document.querySelector('#rep-list button[data-rep-id]').dataset.repId.startsWith('manual-')")
        buttons.first.click()
        page.locator('#loop-rep').check()
        click_frame(first['end']-1)
        page.locator('#play').click()
        page.wait_for_function(f"!document.getElementById('video').paused && Number(document.getElementById('scrubber').value)<{first['bottom']}")
        page.locator('#play').click()
        page.locator('#loop-rep').uncheck()
        click_frame(first['end']-1)
        page.locator('#play').click()
        page.wait_for_function(f"document.getElementById('video').paused && Number(document.getElementById('scrubber').value)==={first['end']}")
        page.locator('#zoom-rep').check()
        page.locator('#rep-editor').evaluate("el => el.open = false")
        page.screenshot(path='outputs/repetitions_dashboard_preview.png',full_page=True)
        page.set_viewport_size({'width':375,'height':900})
        page.wait_for_function('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path='outputs/repetitions_mobile_preview.png',full_page=True)
        assert not errors,errors
        browser.close()
