FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.5.4

COPY pyproject.toml README.md ./
COPY jutra/ ./jutra/

RUN uv pip install --system --no-cache .

ENV PORT=8080 \
    GOOGLE_GENAI_USE_VERTEXAI=true \
    LLM_LOCATION=global \
    EMBED_LOCATION=europe-west4

EXPOSE 8080

# Single-process: FastAPI serves REST + mounts MCP SSE at /mcp
CMD exec uvicorn jutra.api.main:app --host 0.0.0.0 --port ${PORT} --workers 1
