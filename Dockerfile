FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    REPO_HEALTH_DB=/data/repo-health.sqlite3

RUN apt-get update \
    && apt-get install --no-install-recommends -y git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 repohealth \
    && mkdir -p /data /checkouts \
    && chown -R repohealth:repohealth /app /data /checkouts

USER repohealth
EXPOSE 8000
VOLUME ["/data", "/checkouts"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "repo_health.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
