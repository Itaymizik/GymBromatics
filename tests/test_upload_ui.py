from pathlib import Path

from fastapi.testclient import TestClient

from gymbromatics.api import create_app
from gymbromatics.job_repository import LocalJobRepository
from gymbromatics.storage import LocalVideoStorage


class Provider:
    model = "test-only"

    def generate(self, system, payload, schema):  # pragma: no cover
        raise AssertionError("upload UI must not invoke the LLM")


def test_upload_page_and_script_are_served_from_the_application(tmp_path) -> None:
    app = create_app(
        [Path("demo_artifacts/squatsample_dashboard.html")],
        Provider(),
        video_storage=LocalVideoStorage(tmp_path / "objects"),
        job_repository=LocalJobRepository(tmp_path / "jobs"),
    )
    with TestClient(app, base_url="http://testserver") as client:
        index = client.get("/")
        page = client.get("/upload")
        script = client.get("/assets/upload.js")

    assert index.status_code == 200
    assert 'href="/upload"' in index.text
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert 'lang="he" dir="rtl"' in page.text
    assert 'id="video-file"' in page.text
    assert 'id="start-upload"' in page.text
    assert 'id="result-list"' in page.text
    assert 'src="/assets/upload.js"' in page.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("application/javascript")


def test_upload_ui_calls_each_async_processing_endpoint() -> None:
    source = Path("gymbromatics/upload.js").read_text(encoding="utf-8")

    assert "'/api/video-sessions'" in source
    assert "/upload-complete" in source
    assert "XMLHttpRequest" in source
    assert "sessionStorage" in source
    assert "result_urls" in source
    assert "setTimeout(resolve,2000)" in source
    assert "250*1024*1024" in source
