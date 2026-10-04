# Read-only public API: serves the committed outputs/ (no LLM calls, ingest disabled).
# Build: docker build -t navigator-api .     Run: docker run -p 8000:8000 navigator-api
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NAVIGATOR_DISABLE_INGEST=1 \
    PORT=8000

WORKDIR /app
# Editable install: settings.REPO_ROOT is the package's parent, so outputs/, config/ and
# data/ must sit next to navigator/ in /app.
COPY pyproject.toml README.md ./
COPY navigator ./navigator
COPY config ./config
COPY data/starter ./data/starter
COPY data/supplement ./data/supplement
COPY outputs ./outputs
COPY scores ./scores
RUN pip install --no-cache-dir -e . \
    && useradd --create-home app && chown -R app /app
USER app

EXPOSE 8000
# Hosts such as Railway, Render, Fly and Hugging Face set $PORT.
CMD ["sh", "-c", "uvicorn navigator.api.main:app --host 0.0.0.0 --port ${PORT}"]
