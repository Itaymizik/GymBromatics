FROM python:3.11-slim AS system

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN groupadd --system gymbromatics \
    && useradd --system --gid gymbromatics --home-dir /app gymbromatics

COPY requirements-api.txt ./
RUN pip install --no-cache-dir --requirement requirements-api.txt

COPY gymbromatics ./gymbromatics
COPY demo_artifacts ./demo_artifacts

RUN mkdir -p /app/.gymbromatics-local \
    && chown -R gymbromatics:gymbromatics /app/.gymbromatics-local

FROM system AS api

USER gymbromatics
EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health/live',timeout=2)"

CMD ["sh", "-c", "exec python -m uvicorn gymbromatics.api:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]

FROM system AS worker

RUN apt-get update \
    && apt-get install --no-install-recommends -y libegl1 libgl1 libgles2 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt \
    && mkdir -p /app/models \
    && python -c "from gymbromatics.model import download_model; download_model()" \
    && echo "5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1  /app/models/pose_landmarker_full.task" | sha256sum --check --strict \
    && chown -R gymbromatics:gymbromatics /app/models

USER gymbromatics

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "from pathlib import Path; assert Path('/app/models/pose_landmarker_full.task').is_file(); assert b'gymbromatics.worker' in Path('/proc/1/cmdline').read_bytes()"

CMD ["python", "-m", "gymbromatics.worker", "--watch"]

# Keep plain docker build backward-compatible with the API image.
FROM api AS runtime
