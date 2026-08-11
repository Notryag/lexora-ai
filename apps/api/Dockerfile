# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS build

ARG UV_VERSION=0.11.28

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace/lexora-ai

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock README.md ./
COPY packages/rag-core ./packages/rag-core

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim

ENV HOME=/home/lexora \
    PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system lexora \
    && useradd --system --create-home --home-dir /home/lexora --gid lexora --shell /usr/sbin/nologin lexora

COPY --from=build --chown=lexora:lexora /app/.venv ./.venv
COPY --chown=lexora:lexora alembic ./alembic
COPY --chown=lexora:lexora alembic.ini ./alembic.ini

RUN /app/.venv/bin/alembic --help >/dev/null \
    && /app/.venv/bin/python -c "import lexora_ai"

USER lexora

EXPOSE 8011

CMD ["lexora-api"]
