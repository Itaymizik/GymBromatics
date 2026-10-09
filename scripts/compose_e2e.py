"""Exercise the Compose API and worker with a real local squat video."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 30,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if isinstance(body, dict) else body
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": content_type} if data is not None else {},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload.decode("utf-8")) if payload else {}
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} returned {error.code}: {detail}") from error


def wait_until_ready(base_url: str, deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{base_url}/health/live", timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise TimeoutError("API did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, nargs="?", default=Path("data/squatsample.mp4"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--timeout-seconds", type=float, default=180)
    args = parser.parse_args()
    if not args.video.is_file():
        parser.error(f"video not found: {args.video}")
    deadline = time.monotonic() + args.timeout_seconds
    wait_until_ready(args.base_url, deadline)

    video_bytes = args.video.read_bytes()
    checksum_sha256 = hashlib.sha256(video_bytes).hexdigest()
    created = request_json(
        f"{args.base_url}/api/video-sessions",
        method="POST",
        body={
            "filename": args.video.name,
            "content_type": "video/mp4",
            "size_bytes": len(video_bytes),
            "checksum_sha256": checksum_sha256,
        },
    )
    request_json(
        created["upload"]["url"],
        method="PUT",
        body=video_bytes,
        content_type="video/mp4",
        timeout=60,
    )
    request_json(
        f"{args.base_url}/api/video-sessions/{created['session_id']}/upload-complete",
        method="POST",
        body={
            "size_bytes": len(video_bytes),
            "checksum_sha256": checksum_sha256,
        },
    )

    while time.monotonic() < deadline:
        job = request_json(
            f"{args.base_url}/api/video-sessions/{created['session_id']}"
        )
        print(f"status={job['status']} attempt={job['attempt']}")
        if job["status"] == "failed":
            raise RuntimeError(f"processing failed: {job.get('error_code')}")
        if job["status"] == "complete":
            expected = {
                "annotated_video",
                "analysis_json",
                "dashboard_html",
                "dashboard_json",
            }
            if set(job["result_urls"]) != expected:
                raise RuntimeError("completed job did not expose all result URLs")
            for name, url in job["result_urls"].items():
                with urlopen(url, timeout=30) as response:
                    if not response.read(32):
                        raise RuntimeError(f"empty result: {name}")
            print(f"compose_e2e=passed session_id={created['session_id']}")
            return
        time.sleep(2)
    raise TimeoutError("video processing did not finish before the deadline")


if __name__ == "__main__":
    main()
