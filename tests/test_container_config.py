from pathlib import Path


def test_compose_runs_api_and_worker_with_shared_runtime_volume() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "  api:\n" in compose
    assert "  worker:\n" in compose
    assert "target: api" in compose
    assert "target: worker" in compose
    assert compose.count("gymbromatics-runtime:/app/.gymbromatics-local") == 1
    assert "condition: service_healthy" in compose
    assert "gymbromatics.worker" in compose
    assert '"8765:8080"' in compose


def test_worker_image_contains_dependencies_and_verified_pose_model() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "FROM system AS api" in dockerfile
    assert "FROM system AS worker" in dockerfile
    assert "COPY requirements.txt ./" in dockerfile
    assert "download_model()" in dockerfile
    assert "sha256sum --check --strict" in dockerfile
    assert "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1" in dockerfile
    assert dockerfile.count("USER gymbromatics") == 2


def test_ci_runs_real_compose_flow_on_main_and_always_cleans_up() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "  compose-e2e:\n" in workflow
    assert "github.event_name == 'push'" in workflow
    assert "docker compose up --detach --build --wait" in workflow
    assert "python scripts/compose_e2e.py tests/fixtures/squat_e2e.mp4" in workflow
    assert "docker compose logs --no-color" in workflow
    assert "docker compose down --volumes --remove-orphans" in workflow
    assert Path("tests/fixtures/squat_e2e.mp4").is_file()
