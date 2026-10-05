"""Download the pretrained Google model once, then run entirely locally."""

from pathlib import Path
from urllib.request import urlopen
import shutil
import zipfile

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/1/pose_landmarker_full.task"
)
DEFAULT_MODEL = Path("models/pose_landmarker_full.task")


def download_model(path: Path = DEFAULT_MODEL) -> Path:
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".download")
    try:
        with urlopen(MODEL_URL, timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if not zipfile.is_zipfile(temporary):
            raise ValueError("Downloaded model is not a valid MediaPipe task bundle")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path
