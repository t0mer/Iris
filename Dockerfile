# Stage 1: SPA, built once on the native build platform (output is arch-independent).
FROM --platform=$BUILDPLATFORM mirror.gcr.io/library/node:22-alpine AS frontend
WORKDIR /src/web
COPY web/package*.json ./
RUN npm ci
COPY web/ ./
# Vite outDir is ../app/static
RUN npm run build

# Stage 2: runtime (Debian-based so ffmpeg and manylinux wheels work on amd64 and arm64).
FROM mirror.gcr.io/library/python:3.12-slim
ARG VERSION=2026.10.0-beta.44
ARG REVISION=unknown
LABEL org.opencontainers.image.title="iris" \
      org.opencontainers.image.description="Self-hosted WhatsApp safety monitor for kids" \
      org.opencontainers.image.source="https://github.com/t0mer/Iris" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${REVISION}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    UV_COMPILE_BYTECODE=0 \
    UV_LINK_MODE=copy \
    IRIS_VERSION=${VERSION} \
    IRIS_DATA_DIR=/data \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY LICENSE /app/LICENSE
COPY app/ ./app/
COPY --from=frontend /src/app/static ./app/static
COPY scripts/entrypoint.sh /entrypoint.sh

RUN useradd --create-home --uid 10001 iris \
    && mkdir -p /data && chown -R iris:iris /data \
    && chmod +x /entrypoint.sh
USER iris

VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${IRIS_PORT:-8080}/api/health" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
