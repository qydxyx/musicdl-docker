# ── Stage 1: Builder ──────────────────────────────
FROM python:3.11-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────
FROM python:3.11-slim-bookworm

# ffmpeg for audio processing, ca-certificates for HTTPS, curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Copy pre-compiled Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app
COPY backend/ backend/
COPY static/ static/

# Persistent volumes for downloads and configuration
VOLUME ["/app/downloads", "/app/data"]

# Bind to 0.0.0.0 inside container so host port forwarding works
ENV HOST=0.0.0.0 \
    PORT=8080 \
    PYTHONUNBUFFERED=1 \
    MUSICDL_DATA_DIR=/app/data \
    MUSICDL_DOWNLOAD_DIR=/app/downloads

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8080/api/system_info || exit 1

CMD ["python", "-m", "backend.app"]
