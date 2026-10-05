"""Browser checks for summary calculations and editing, without video inference."""
import json
import os
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get("RUN_DASHBOARD_BROWSER_TEST") != "1", reason="Opt-in Chromium")
def test_session_stats():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chromium")
        page = browser.new_page(viewport={"width": 1360, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        for name, count in [("squatsample", 3), ("squat_test2", 5)]:
            artifact = Path(f"demo_artifacts/{name}_dashboard.html").resolve()
            data = json.loads(artifact.with_suffix(".json").read_text(encoding="utf-8"))
            page.goto(artifact.as_uri())
            table = page.locator("#session-stats-body")
            assert table.locator("tr").count() == count
            rep = data["repetitions"][0]
            cells = table.locator("tr").first.locator("td")
            assert float(cells.nth(0).inner_text()) == pytest.approx((rep["end"]-rep["start"])/data["fps"], abs=.005)
            assert float(cells.nth(1).inner_text()) == pytest.approx(min(s["knee"] for s in data["samples"][rep["start"]:rep["end"]+1]), abs=.05)
            assert float(cells.nth(3).inner_text()) == pytest.approx(max(s["velocity"] for s in data["samples"][rep["bottom"]:rep["end"]+1]), abs=.05)
            table.locator("button").first.click()
            assert table.locator('tr[data-selected="true"]').count() == 1
            page.locator("#mark-end").evaluate("e => {e.dispatchEvent(new Event('pointerdown')); e.value=Number(e.value)-2; e.dispatchEvent(new Event('input')); e.dispatchEvent(new Event('change'));}")
            assert float(cells.nth(0).inner_text()) == pytest.approx((rep["end"]-2-rep["start"])/data["fps"], abs=.005)
            page.locator(".session-stats").screenshot(path=f"outputs/{name}_stats_preview.png")
            page.set_viewport_size({"width": 375, "height": 850})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.set_viewport_size({"width": 1360, "height": 1000})
        # A known plateau has a one-second pause; an instantaneous reversal does not.
        result = page.evaluate("""() => {
          const rows=Array.from({length:31},(_,i)=>({knee:180-Math.min(i,30-i)*5,velocity:i>20?20:0,
            hip_y_smoothed_px:i<10?i:i<=20?10:30-i,hip_velocity:i<10?-10:i<=20?0:10}));
          const rep={start:0,bottom:15,end:30};
          const held=calculateRepStats(rows,rep,10);
          rows[15].hip_velocity=null;
          const missing=calculateRepStats(rows,rep,10);
          rows.forEach((r,i)=>{r.hip_y_smoothed_px=15-Math.abs(i-15);r.hip_velocity=i<15?-10:i===15?0:10;});
          return {held,missing,continuous:calculateRepStats(rows,rep,10)};
        }""")
        assert result["held"]["pause"] == 1
        assert result["missing"]["pause"] is None
        assert result["continuous"]["pause"] == 0
        assert not errors
        browser.close()
