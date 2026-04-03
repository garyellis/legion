# syntax=docker/dockerfile:1

# --- Builder ---
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first (cache-friendly layer ordering)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --group dev --extra postgres --extra agents

# Install the project itself
COPY . .
RUN uv sync --frozen --group dev --extra postgres --extra agents

# --- Runtime ---
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH"

CMD ["legion-api"]
