FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system gymbromatics \
    && useradd --system --gid gymbromatics --home-dir /app gymbromatics

COPY requirements-api.txt ./
RUN pip install --no-cache-dir --requirement requirements-api.txt

COPY gymbromatics ./gymbromatics
COPY demo_artifacts ./demo_artifacts

RUN mkdir -p /app/.gymbromatics-local \
    && chown -R gymbromatics:gymbromatics /app/.gymbromatics-local

USER gymbromatics
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health/live',timeout=2)"

CMD ["sh", "-c", "exec python -m uvicorn gymbromatics.api:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips='*'"]
