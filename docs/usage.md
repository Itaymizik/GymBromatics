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

Staging deployment (Cloud Run) is described in [infra/README.md](../infra/README.md).

References: [MediaPipe Python video guide](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python)
and [pretrained models](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker#models).
