# Hugging Face Space (Docker SDK): builds the read-only API from the public GitHub repo.
# REF pins the commit the judges see; deploy/deploy_hf.sh sets it.
FROM python:3.13-slim

ARG REPO=https://github.com/syedwajiulhassan715-rgb/Hack-Nation.git
ARG REF=main

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Spaces run as uid 1000
RUN useradd -m -u 1000 user
WORKDIR /app
RUN git clone --filter=blob:none --no-checkout "$REPO" /app \
    && git -C /app checkout "$REF" \
    && rm -rf /app/web /app/cache /app/.git /app/*.zip /app/*.pdf \
    && chown -R user /app
RUN pip install --no-cache-dir -e /app

USER user
ENV PYTHONUNBUFFERED=1 \
    NAVIGATOR_DISABLE_INGEST=1 \
    PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn navigator.api.main:app --host 0.0.0.0 --port ${PORT}"]
