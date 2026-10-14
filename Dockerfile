# Ridgeline HR Agent: runtime image (SPEC slice 1). One uvicorn worker on $PORT.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    FASTEMBED_CACHE_PATH=/opt/fastembed \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /srv

# Dependencies first, for the layer cache.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the embedding model into the image so a cold start never downloads it.
RUN uv run --no-sync python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed')"

# Runtime code and data only: ingest/, evaluation/ and tests/ stay out.
COPY app/ app/
COPY mcp_servers/ mcp_servers/
COPY index/ index/
COPY corpus/ corpus/
COPY mock_data/ mock_data/

EXPOSE 8000
CMD ["sh", "-c", "exec /srv/.venv/bin/uvicorn --factory app.main:create_app --host 0.0.0.0 --port ${PORT} --workers 1"]
