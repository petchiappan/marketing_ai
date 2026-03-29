# ═══════════════════════════════════════════════════════════════════════
# Marketing AI – Production Dockerfile (Railway-Ready)
# Multi-stage build  ·  Gunicorn + Uvicorn workers  ·  Non-root user
# ═══════════════════════════════════════════════════════════════════════

# ── Stage 1: Builder ──────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY pyproject.toml ./
COPY app/ ./app/
COPY alembic.ini ./
COPY alembic/ ./alembic/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .


# ── Stage 2: Runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Install runtime system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libpq5 \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Copy application code
WORKDIR /app
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/

# Set ownership to non-root user
RUN chown -R appuser:appuser /app

USER appuser

# Railway sets PORT dynamically; default to 8000 for local testing
ENV PORT=8000
EXPOSE ${PORT}

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

# Production server: Gunicorn with Uvicorn workers
# - Workers: 2 (Railway Hobby plan has 8 GB RAM / shared vCPU; 2 workers is safe)
# - Graceful timeout: 120s for long-running LLM agent calls
# - Access log to stdout for Railway's log viewer
CMD gunicorn app.main:app \
    --bind 0.0.0.0:${PORT} \
    --workers ${GUNICORN_WORKERS:-2} \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout ${GUNICORN_TIMEOUT:-120} \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    --forwarded-allow-ips "*" \
    --proxy-protocol
