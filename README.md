# GymBromatics — squat video skeleton POC

[![CI](https://github.com/Itaymizik/GymBromatics/actions/workflows/ci.yml/badge.svg)](https://github.com/Itaymizik/GymBromatics/actions/workflows/ci.yml)

Local video processing with MediaPipe Pose Landmarker (BlazePose) and OpenCV.
Extracts 33 named body landmarks per frame and produces an MP4 skeleton overlay
plus a JSON time series. No training or cloud inference is involved.

The repository includes four versioned files under `demo_artifacts/`: HTML and
JSON session exports for the two sample squats. Generated videos, previews and
intermediate analysis remain under the ignored `outputs/` directory. This keeps
CI reproducible without committing every generated artifact.

## Setup and run (PowerShell, from the project root)

Tested with Python 3.11.5 on Windows. Use Python 3.11+ for these pinned dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m gymbromatics data/squatsample.mp4 --download-model
```

For the deployable API only, install the smaller runtime dependency set:

```powershell
python -m pip install -r requirements-api.txt
```

### Docker and CI

Run the same API container used by CI:

```powershell
docker compose up --build --detach
```

Then open <http://127.0.0.1:8765>. The container reads `.env.local` at runtime;
the file is excluded from both Git and the Docker build context.

`.github/workflows/ci.yml` runs the Python test suite and, independently, builds
the API image and smoke-tests readiness, the index, API documentation and the
non-root runtime user. Dependabot checks Python and GitHub Actions dependencies
weekly.

The first run downloads Google's pretrained **full** pose model into `models/`.
Subsequent runs use the cached model; `--download-model` can be omitted.
For offline use, supply an existing task bundle with `--model path/to/model.task`.

Outputs:

- `outputs/squatsample_skeleton.mp4`: skeleton, colored joint-angle arcs and a live angle dashboard.
- `outputs/squatsample_landmarks.json`: metadata, one record per decoded frame,
  and processing totals.

Optional arguments: `--output output.mp4`, `--json landmarks.json`,
`--confidence 0.5`, `--model models/pose_landmarker_full.task`, `--side auto|left|right`.
Existing output files are replaced on rerun. Input and output paths must differ.

## Architecture and data contract

- `state.py`: provider-independent `Landmark` and `FrameState` dataclasses.
- `extractor.py`: `PoseExtractor` interface and the MediaPipe video adapter.
- `visualizer.py`: OpenCV drawing from named landmarks, without MediaPipe types.
- `squat_logic.py`: bilateral 2D joint angles, confidence gating and stable display-side selection.
- `pipeline.py`: video I/O, timestamps, JSON streaming and resource cleanup.
- `model.py`: optional model download and local cache.
- `filter.py`: gap-aware trajectory smoothing and vertical velocity calculation.
- `dashboard.py` / `dashboard.html` / `dashboard.js`: portable interactive video/velocity/angle report.
- `repetitions.py`: automatic squat-cycle proposals from the hip trajectory.

Coordinates are normalized image `x`, `y` and relative-depth `z`, with confidence
values `visibility` and `presence`. Y increases downwards; z is **not** a calibrated
distance in metres. Left/right names refer to the subject's anatomy. Hip, knee,
ankle and wrist landmarks are available by name for later squat analysis.

Missing detections produce `pose_detected: false` and `landmarks: {}`. The frame
is still written. Low-confidence landmarks remain in JSON, but points and limbs
are drawn only when both visibility and presence meet the threshold. Downstream
analysis must use the same reliability check or interpolate gaps before analysis.

This milestone covers extraction, skeleton rendering, joint-angle estimates and
a smoothed chest-proxy vertical velocity profile, and automatic repetition
proposals with manual editing. Depth and sticking-point heuristics remain future modules.

The output preserves decoded frame dimensions and nominal FPS. It is a silent
MP4 (`mp4v`); audio is not copied. Timestamps are computed from frame index / FPS,
so the pipeline assumes constant frame rate. Use a side-profile video of one
lifter with the body visible. Occluded joints may be omitted from the overlay.

## Joint-angle overlay

The right-hand translucent dashboard matches cyan knee, violet hip and amber
ankle arcs on the selected leg. Arcs span the interior angle between the two
segment directions. At the ankle, the heel-to-toe foot axis is translated to
the ankle center for drawing.
Values update every frame; unavailable measurements show `--`. By default the
most visible measurable side is selected on the first suitable frame and locked
for the video. Use `--side left` or `--side right` to override. JSON schema v3
stores both sides under each frame's `angles`, in degrees, with unavailable
angles represented by `null` (never stale values).

- **Knee angle:** `angle(hip-knee, ankle-knee)`; a straight knee is 180°.
- **Hip angle:** `angle(shoulder-hip, knee-hip)`; a straight trunk/thigh
  is 180°. This is a trunk-thigh proxy, not an isolated measurement of pelvic tilt
  or the anatomical pelvis-femur angle.
- **Ankle angle:** `angle(knee-ankle, toe-heel)`; a shin perpendicular
  to the heel-to-toe foot axis is 90°. The angle decreases as the shin leans
  toward the toes during descent. The foot axis avoids the ankle-to-toe
  downward slope in neutral stance.

All three angles are interior angles in [0°, 180°] and decrease with squat
flexion. Schema v3 uses `knee_angle_deg`, `hip_angle_deg`, `ankle_angle_deg`;
these replace the v2 flexion/dorsiflexion fields, which used a different convention.

All vectors use pixel-scaled x/y to correct for image aspect ratio. These are
2D side-view estimates; camera perspective and landmark errors affect accuracy.
No clinical calibration or initial-pose zeroing is performed. Hip/knee magnitudes
do not distinguish hyperextension. Displayed integers round the full-precision
values stored in JSON. The dashboard sits in the right margin; frame subjects
to its left to keep the overlay clear.

## Interactive chest-velocity dashboard

Open `outputs/squatsample_dashboard.html` directly in a browser. It is a portable
offline report: the chart data and an H.264 copy of the annotated video are
embedded, so no server, CDN, upload or internet connection is needed.

- Click the velocity chart to pause and seek to the nearest frame. The panel
  displays its knee, hip and ankle **interior angles**, selected anatomical side,
  timestamp and vertical velocity.
- Use the time slider (including keyboard arrows), frame-step buttons or video
  playback; the selection marker and measurements stay synchronized.
- Hover/touch the graph for time/velocity and download the profile as JSON.
- Missing velocity or angles are shown as unavailable, never as zero.

Generate it from the existing analysis without running MediaPipe again:

```powershell
.\.venv\Scripts\python.exe -m gymbromatics.dashboard outputs/squatsample_landmarks.json --video outputs/squatsample_skeleton.mp4 --output outputs/squatsample_dashboard.html
```

Or include it with a new video processing run:

```powershell
.\.venv\Scripts\python.exe -m gymbromatics data/squatsample.mp4 --dashboard
```

The chest location is approximated by the **midpoint of both shoulders**.
The profile measures **vertical velocity in pixels/second**: positive upward,
negative downward. It is not total 2D speed, bar speed or calibrated metres/second.
Frame times use `frame_index / fps`. A quadratic Savitzky–Golay filter smooths
the Y trajectory with an odd window of approximately 0.35 seconds; only then is
the smoothed trajectory differentiated. The actual window is recorded in JSON.
Both shoulders must pass confidence checks. Bounded gaps up to 0.15 seconds are
interpolated and flagged, longer gaps remain gaps. Contiguous segments shorter
than five frames have no velocity. Segment edges have less smoothing support.
The camera should remain stationary; perspective and camera motion affect the
measurement. Joint angles stay attached to their original frame and are not
interpolated with the chest trajectory.

`outputs/squatsample_dashboard.json` contains the profile, processing parameters,
raw/smoothed chest Y, interpolation flags, frame indices and linked angles.
The original analysis JSON and annotated MP4 remain unchanged by report export.

## Repetition selection and editing

The dashboard proposes complete squat cycles automatically. Select a repetition
chip to seek to its start and focus the chart. Turn off chart focus to retain
the full timeline. Playback stops at the selected end, or repeats that interval
when the loop checkbox is enabled. Choosing "all video" removes this restriction.

Open the boundary editor to adjust start, bottom and end with labeled sliders,
keyboard arrows, or the "use displayed frame" buttons. The three markers above
the chart are also draggable and keyboard accessible. Start must precede bottom,
bottom must precede end, and repetitions cannot overlap (a shared endpoint is OK).
Use "add repetition" to mark three frames in sequence; delete erroneous proposals
or undo changes with the corresponding buttons. Automatic, edited and manual
repetitions are labeled separately.

Edits are saved in local browser storage under a SHA-256 identity of the exact
analysis. Local-file storage support varies by browser: if saving fails, the
dashboard reports it. Export the repetition JSON for durable backup or transfer;
import validates the analysis identity, integer frame bounds, order and overlaps.
Reopening the same file in the same browser restores saved edits. Moving the
HTML or using a different browser may require importing the exported file.
Exported timestamps use frame index / FPS; frame indices are zero-based. Displayed
frame labels are one-based. The original Python analysis files are not modified
by browser edits. Undo supports the current session; restoring automatic proposals
can itself be undone.

Automatic detection uses the confidence-gated hip on the already-selected body
side, smoothed with the same gap-aware filter. Local maxima in image Y locate
the bottom. Minimum prominence is the larger of 3.5% of image height and 25% of
the segment's robust excursion. Bounds return within 8% of excursion (minimum
2 pixels) of each adjacent standing valley, avoiding merged reps when standing
height drifts during the set. Available knee angles validate
near-upright endpoints (at least 170 degrees) and at least 20 degrees of flexion.
Hip speed at endpoints must be below 15% of the segment's 95th-percentile speed
(with a 5 px/s floor), so the interval includes deceleration into standing.
Cycles must last at least 0.6 seconds. Long gaps and incomplete cycles at the
video edges are excluded, and interpolated or missing knee data flag a proposal
for review. These thresholds are POC heuristics, not a depth or lift-validity
assessment; manually adjust unusual tempos, camera movement and partial reps.

An optional browser acceptance test verifies graph clicking, video decoding,
time/angle synchronization, keyboard navigation, playback and mobile layout:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.venv/pw-browsers'
.\.venv\Scripts\python.exe -m playwright install chromium
$env:RUN_DASHBOARD_BROWSER_TEST = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_dashboard_browser.py -q
```

## Tests

### Geometry-based side-view technique notes

Both portable dashboards include per-session counts and expandable per-repetition
notes for a minimum knee angle of 90 degrees or less, hip/shoulder coordination during early
ascent, and estimated heel lift. Selecting or editing a repetition recomputes the
notes immediately; evidence buttons seek the relevant video frame. The technique
JSON download includes current boundaries, thresholds, results and calibration.

`technique.py` prepares fixed-side, confidence-gated image-pixel trajectories.
Visibility and presence must both be at least 0.65. Coordinates are smoothed with
a 0.2-second Savitzky–Golay window without interpolating occlusions. `technique.js`
contains pure geometric rules independent of MediaPipe and the browser UI.
`technique_ui.js` handles presentation and optional calibration. No learned
exercise-quality classifier is used; the previous external-model experiment,
weights and isolated experiment environment have been removed. MediaPipe remains
the landmark extractor.

Depth uses the minimum reliable interior knee angle across the entire repetition:
90 degrees or less meets the project target; greater than 90 does not. It uses
the original aspect-corrected angle measurements with an additional 0.65
visibility/presence gate on hip, knee and ankle. At least 80% coverage is required
both across the repetition and around the marked bottom. This is a project
criterion, not a competition-depth decision. Coordination flags simultaneous hip-first rise
over 8% of bottom torso length and trunk-inclination increase of at least 12°,
maintained for 0.15 seconds in the first half of ascent. Heel lift requires a
relative heel/toe vertical change over 6% of projected foot length and a foot
angle increase of at least 8°, maintained for 0.15 seconds. The reference is the
start of that repetition, assuming an initially planted heel. At least 80% valid
coverage is needed per assessment window; insufficient resolution, missing
landmarks or substantial toe motion yield `unavailable`, never a clean result.
The heel rule uses only the selected near foot, never both feet or a fallback
to the far foot. The default foot is selected once per video using heel/toe
visibility; the user can explicitly select anatomical left/right because
visibility alone does not prove which foot is nearer. This choice is independent
of the fixed torso/knee measurement side. Thresholds are experimental heuristics,
not validated clinical limits.

User height is entered in centimetres. `calibration.js` automatically estimates
pixel stature using the selected near side within ±0.1 seconds of the first rep's
start: vertical floor-to-ankle height + ankle-to-knee + knee-to-hip + hip-to-shoulder
+ shoulder-to-ear Euclidean lengths. Floor Y is approximated by the lower heel/toe
landmark. Calibration uses raw confidence-gated pixel landmarks, with median
segment lengths over at least three valid upright frames (knee >=160°, hip >=150°).
All points must be visible and in the expected vertical order; a total-length
range exceeding 12% of its median makes the automatic estimate unavailable.
An editable **experimental 6% allowance** of the measured sum approximates the
missing ear-to-crown segment. This coefficient is not an anthropometric guarantee.
Height / estimated total pixels gives cm/pixel, automatically when a valid height
is entered. It does not correct perspective, camera tilt or out-of-plane motion.
The user can view the reference image with segment overlays and edit the five
lengths and head allowance (0–20%). Manual lengths are tied to start frame and
side, and reset when either changes. Invalid/insufficient data disables automatic
scale rather than keeping a stale one; complete manual lengths can supply an
explicit fallback. Reset restores automatic lengths and the 6% head allowance.
Old crown/floor calibration is not silently reused; valid saved user height and
foot selection are retained. The export identifies automatic/manual mode, window,
segments, coefficient, reference frame and scale.
The scale adds approximate centimetres to technique-note distances; existing
velocity plots retain their explicitly labeled px/s units. No height or physical
scale is invented for the demo videos. Rules use dimensionless ratios and angles
and therefore remain available without physical calibration. Calibration and
near-foot selection persist per analysis in local browser storage and can be exported.

To check the new rules and UI:

```powershell
node tests/test_technique_math.cjs
node tests/test_calibration_math.cjs
.\.venv\Scripts\python.exe -m pytest tests/test_technique.py -q
$env:RUN_DASHBOARD_BROWSER_TEST = '1'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.venv/pw-browsers'
.\.venv\Scripts\python.exe -m pytest tests/test_technique_browser.py -q
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:RUN_MEDIAPIPE_TEST = '1'
.\.venv\Scripts\python.exe -m pytest -q
```

The opt-in integration test processes `data/squatsample.mp4` using the local
model. Other tests cover missing landmarks, confidence gating, video/JSON
alignment, invalid input and protection against overwriting the source.

### Stored repetition comparisons

Each generated `*_dashboard.json` session and embedded HTML payload now includes
`repetition_comparisons` (schema version 1), without adding dashboard UI.
The same field is recomputed for the current boundaries in full-session downloads,
repetition exports and browser storage when repetitions are edited. Imported
comparisons are ignored and recomputed from the session samples. Browser edits
do not overwrite the original JSON file on disk; download to persist those edits.

Metrics: total/descent/ascent durations, minimum knee/hip/ankle interior angles,
bottom pause, and peak/mean upward chest-proxy velocity. Phase durations include
any stationary portion assigned by the bottom marker. Velocities remain px/s,
independent of optional height calibration, and are only compared within a session.
Mean velocity is a signed trapezoidal mean over valid adjacent ascent intervals.
Pause uses the existing summary-table definition (deepest 5% of hip excursion,
at most 10% of peak absolute hip speed, continuous for at least 0.2 seconds).

For each rep, comparisons use the immediately preceding rep and the session
median of available values (including the current rep). Deltas mean current minus
reference. Angles use degree differences only; time/velocity also have percentage
changes, unless the absolute reference is at most 0.01 s / 0.1 px/s. Null results
have reasons. Extrema and pause require complete finite coverage; mean velocity
requires at least 80% valid adjacent intervals. Coverage and the fraction of
interpolated ascent samples are retained; coverage is not a confidence score.
Original boundary provenance and `needs_review` are retained, not interpreted as
confirmation that the repetition boundaries are correct.

Session trends include first-to-last available differences and a least-squares
slope against original repetition ordinals, with at least three available reps
required for a slope. Missing reps are not renumbered. A single rep has no usable
comparison. These are descriptive measurements, without automatic claims of
fatigue, technique quality, or statistically significant change; a session median
is not a technique target.

Validation: `python -m pytest tests/test_comparisons.py -q` checks known arithmetic,
missing data, edge cases and Python/JavaScript parity (Node required). With
`RUN_DASHBOARD_BROWSER_TEST=1`, it also verifies edited/reloaded/downloaded data
in both example dashboards.

### Optional Hebrew LLM feedback (Gemini Free Tier)

The feedback stage is separate from extraction and deterministic kinematics.
It uses `gemini-3.1-flash-lite` via Google's REST API, with no added Python
dependency. The model has a free tier; **the API key's project must actually be
Free Tier with billing disabled**. A model name or API key alone cannot verify
the billing tier. This application requires explicit local confirmation, does
not enable billing, never switches to another provider/model, and makes one
request per uncached session. On quota exhaustion it stops without retries.
Check current [pricing](https://ai.google.dev/gemini-api/docs/pricing) and
[billing](https://ai.google.dev/gemini-api/docs/billing) in Google AI Studio.
Free-tier inputs/outputs may be used by Google to improve its products.

Create a key for a Free Tier project at <https://aistudio.google.com/api-keys>.
Create the ignored `.env.local` file in the project root using `.env.example`:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_FREE_TIER_CONFIRMED=true
```

Set the second value only after verifying the project has no billing enabled.
Never paste a real key into chat, a command line, HTML, exported session data
or source control. Existing environment variables take precedence over the
file. The file parser only reads these two names and does not execute contents.

Run on the existing sessions without reprocessing their videos:

```powershell
.\.venv\Scripts\python.exe -m gymbromatics.feedback outputs/squatsample_dashboard.json
.\.venv\Scripts\python.exe -m gymbromatics.feedback outputs/squat_test2_dashboard.json
```

For a new video, append `--feedback` to the existing pipeline command:

```powershell
.\.venv\Scripts\python.exe -m gymbromatics data/squatsample.mp4 --dashboard --feedback
```

The standalone dashboard export command also supports `--feedback`.
Use `--feedback-prepare-only` on either pipeline command, or `--prepare-only`
with `gymbromatics.feedback`, to build the input without credentials/network.
The standalone command accepts either dashboard/session JSON or schema-v3
landmark JSON, an optional `--env-file`, and `--foot-side left|right` to override
automatic near-foot selection. To use browser-edited repetitions, download the
full session JSON and run feedback on that file. Browser-only calibration/foot
preferences are not read automatically; velocities remain px/s.

Outputs are `<session>_feedback_input.json` (the numeric evidence sent to the
model) and `<session>_feedback.json` (status, provenance, evidence, Hebrew session
summary, per-repetition observations, and next steps). These are sidecar files;
the dashboard display and original analysis are unchanged. Status `prepared`
means no LLM call was made and `feedback` is null. `unavailable` includes a safe
error code such as `missing_api_key`, `free_tier_not_confirmed`, `quota_exceeded`,
or `invalid_feedback`; it never pretends that a fallback is model feedback.
The standalone CLI returns exit code 2 for unavailable feedback. The video and
dashboard pipelines retain their artifacts and report the feedback status.

The cloud receives anonymous rep IDs and computed scalar metrics/comparisons,
geometry-rule results, coverage, and limitations. No video, frames, coordinate
trajectories, filenames, user height, credentials, or original IDs are sent.
`technique_report.cjs` reuses the existing dashboard geometry rules through
Node.js; without Node or geometry, those rules are explicitly unavailable while
the other measurements remain usable. Comparisons are always recomputed from
current boundaries. Local output maps anonymous IDs back to original rep IDs.

Structured responses cite evidence IDs for each statement. Validation checks
evidence membership locally instead of embedding long repeated enum lists in
the API schema (which can cause Gemini to reject a request). Validation checks
structure, actual references, rep association, Hebrew text, and absence of
numeric digits in prose; exact values remain in the attached evidence. It does
**not** prove semantic correctness. Prompts prohibit inferring fatigue, injury,
knee valgus, barbell speed, or medical conclusions. Technique `clear` only means
the configured heuristic did not trigger, and `review` remains a flag to inspect.
The rule of knee angle <=90 degrees is not represented as a validated parallel
test. Feedback is limited to 30 reps / 100 KB of evidence per request.

Successful feedback is reused only when the analysis identity, current input,
boundaries, foot choice, prompt/schema and model match. Manually edited session
data therefore invalidate the cache. No cloud calls occur during normal tests.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_feedback.py -q
```

### Session chat in the dashboard

Start the local server from the project root (using the same `.env.local`):

```powershell
.\.venv\Scripts\python.exe -m gymbromatics.chat_server
```

Open <http://127.0.0.1:8765> and choose a session. The chat panel is above the
session statistics. Select a repetition in either the dashboard or the chat
selector, enter a question in Hebrew, and send. Evidence cards show computed
values and buttons seek the video to a repetition or measured event. Suggested
questions fill the text box without sending a request. Opening standalone HTML
still supports all offline analysis; chat requires the local server.

The development command now starts a FastAPI application through Uvicorn. Its
interactive API documentation is available at <http://127.0.0.1:8765/docs>.
`GET /health/live` checks that the process can answer requests, while
`GET /health/ready` also checks that demo sessions and Gemini configuration are
available. Dashboards are served at `GET /sessions/{analysis_id}` and chat uses
`POST /sessions/{analysis_id}/chat` with Pydantic-validated input.

`--port 8766` selects a different port; `--dashboards <file.html> ...` registers
other exported dashboards with their matching session JSON. The server binds
only to loopback and serves only the registered pages, never a project directory.
The API requires the local Origin/Host and a page token; the Gemini key remains
in Python. A page token is not the API key. This is a local single-user tool,
not an authenticated multi-user production deployment.

Each message makes at most one Gemini call; the client never automatically
retries. The server allows one generation at a time. The server sends the
question, anonymous selected-repetition ID, last four exchanges, and current
evidence/definitions. It does not send the video or coordinate trajectories.
Chat content is sent to Google's free tier, under that tier's data-use terms.
No paid fallback is used. Quota, key, validation and network failures appear in
the panel without fabricated answers.

History is kept only in server memory, scoped to a conversation and analysis.
Reloading the page or choosing New conversation starts a fresh conversation;
stopping the server clears history. Edited boundaries or near-foot selection
recompute evidence and invalidate old links/history, including edits made while
a request is in flight. Per-turn selection is preserved in conversational context.
The server resolves all timestamps and links; the model cannot invent video URLs.
Schema/reference validation is not a proof of semantic correctness.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_chat.py -q
$env:RUN_DASHBOARD_BROWSER_TEST='1'
$env:PLAYWRIGHT_BROWSERS_PATH=Join-Path (Get-Location) '.venv/pw-browsers'
.\.venv\Scripts\python.exe -m pytest tests/test_chat.py -q
```

References: [MediaPipe Python video guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python)
and [pretrained models](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker#models).
