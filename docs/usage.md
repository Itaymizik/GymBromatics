# Usage

[← Back to README](../README.md)

## Setup (PowerShell, from the project root)

Tested with Python 3.11.5 on Windows. Use Python 3.11+ for these pinned dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m gymbromatics data/squatsample.mp4 --download-model
```

`data/` is not versioned; use your own side-profile squat video.

For the deployable API only, install the smaller runtime dependency set:

```powershell
python -m pip install -r requirements-api.txt
```

The first run downloads Google's pretrained **full** pose model into `models/`.
Subsequent runs use the cached model; `--download-model` can be omitted.
For offline use, supply an existing task bundle with `--model path/to/model.task`.

## Outputs

- `outputs/squatsample_skeleton.mp4`: skeleton, colored joint-angle arcs and a live angle dashboard.
- `outputs/squatsample_landmarks.json`: metadata, one record per decoded frame,
  and processing totals.
- `outputs/squatsample_dashboard.html` / `.json` (with `--dashboard`): see
  [dashboard.md](dashboard.md).

The repository includes four versioned files under `demo_artifacts/`: HTML and
JSON session exports for the two sample squats. Generated videos, previews and
intermediate analysis remain under the ignored `outputs/` directory. This keeps
CI reproducible without committing every generated artifact.

## CLI options

Optional arguments: `--output output.mp4`, `--json landmarks.json`,
`--confidence 0.5`, `--model models/pose_landmarker_full.task`, `--side auto|left|right`,
`--dashboard`, `--feedback`, `--feedback-prepare-only`.
Existing output files are replaced on rerun. Input and output paths must differ.

The output preserves decoded frame dimensions and nominal FPS. It is a silent
MP4 (`mp4v`); audio is not copied. Timestamps are computed from frame index / FPS,
so the pipeline assumes constant frame rate. Use a side-profile video of one
lifter with the body visible. Occluded joints may be omitted from the overlay.

## Docker and CI

Build and run the API and MediaPipe worker together:

```powershell
docker compose up --build --detach
```

Then open <http://127.0.0.1:8765/upload>. Compose starts two non-root containers:
the API receives uploads and exposes status/results, while the worker claims queued
jobs and runs MediaPipe. A named volume, `gymbromatics-runtime`, is mounted at
`/app/.gymbromatics-local` in both containers so job records and artifacts are
visible to both services and survive container recreation.

The worker image includes the pinned MediaPipe dependencies and the versioned pose
model. The build verifies the model SHA-256 checksum. The API image retains the
smaller dependency set. `.env.local` is optional for video processing; when present,
it is read only by the API at runtime and remains excluded from Git and the build
context.

To stop the services without deleting processed sessions:

```powershell
docker compose down
```

To delete the containers and the local Compose data volume:

```powershell
docker compose down --volumes
```

The second command permanently removes uploaded videos and generated results from
the Compose volume.

With the services running, exercise the complete upload-to-results path using a
local sample video:

```powershell
.\.venv\Scripts\python.exe scripts\compose_e2e.py data\squatsample.mp4
```

`.github/workflows/ci.yml` runs the Python test suite, validates the Compose file,
builds both image targets, and smoke-tests the API and worker images. On pushes to
`main`, a separate job also processes `tests/fixtures/squat_e2e.mp4` through the
real upload, job claiming, MediaPipe, storage, and result-download path. It prints
container logs on failure and always removes its containers and temporary volume.
Dependabot checks Python and GitHub Actions dependencies weekly.

Staging deployment (Cloud Run) is described in [infra/README.md](../infra/README.md).

References: [MediaPipe Python video guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python)
and [pretrained models](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker#models).
