# Testing

[← Back to README](../README.md)

## Unit tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## MediaPipe integration test (opt-in)

```powershell
$env:RUN_MEDIAPIPE_TEST = '1'
.\.venv\Scripts\python.exe -m pytest -q
```

The opt-in integration test processes `data/squatsample.mp4` using the local
model. Other tests cover missing landmarks, confidence gating, video/JSON
alignment, invalid input and protection against overwriting the source.

## Browser acceptance tests (opt-in)

Verify graph clicking, video decoding, time/angle synchronization, keyboard
navigation, playback and mobile layout:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.venv/pw-browsers'
.\.venv\Scripts\python.exe -m playwright install chromium
$env:RUN_DASHBOARD_BROWSER_TEST = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_dashboard_browser.py -q
```

## Technique rules and calibration

```powershell
node tests/test_technique_math.cjs
node tests/test_calibration_math.cjs
.\.venv\Scripts\python.exe -m pytest tests/test_technique.py -q
$env:RUN_DASHBOARD_BROWSER_TEST = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.venv/pw-browsers'
.\.venv\Scripts\python.exe -m pytest tests/test_technique_browser.py -q
```

## Repetition comparisons

`python -m pytest tests/test_comparisons.py -q` checks known arithmetic,
missing data, edge cases and Python/JavaScript parity (Node required). With
`RUN_DASHBOARD_BROWSER_TEST=1`, it also verifies edited/reloaded/downloaded data
in both example dashboards.

## LLM feedback and chat

No cloud calls occur during normal tests.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_feedback.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_chat.py -q
$env:RUN_DASHBOARD_BROWSER_TEST='1'
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path (Get-Location) '.venv/pw-browsers'
.\.venv\Scripts\python.exe -m pytest tests/test_chat.py -q
```
