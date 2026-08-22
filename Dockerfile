# Build context is the repo root, not web/ — the Django app imports
# src/claims_engine (judicial_deposits/core_cache.py: `from claims_engine.load
# import core_key`), so both trees have to be in the image.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Dependency layer first so code-only changes don't reinstall everything.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY web ./web
RUN uv sync --frozen --no-dev

WORKDIR /app/web
RUN uv run --no-sync python manage.py collectstatic --noinput

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
