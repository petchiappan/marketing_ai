# ═══════════════════════════════════════════════════════════════════════
# Marketing AI – Production Dockerfile (AWS Fargate-Ready)
# Multi-stage build  ·  Non-root user  ·  Health check
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
# Copy source first — setuptools needs the package to exist
COPY pyproject.toml ./
COPY app/ ./app/
COPY alembic.ini ./
COPY alembic/ ./alembic/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel --trusted-host pypi.org --trusted-host files.pythonhosted.org && \
    pip install --no-cache-dir . --trusted-host pypi.org --trusted-host files.pythonhosted.org


# ── Stage 2: Runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# Single RUN: certs + curl + libpq5 (avoids duplicate apt and extra layers)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl libpq5 && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Create non-root user (Fargate security best practice)
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy application code
WORKDIR /app
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY app/ ./app/

# Set ownership to non-root user
RUN chown -R appuser:appuser /app

USER appuser

# Expose the application port
EXPOSE 8000

# Health check for ECS / ALB
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Start uvicorn (workers tuned for Fargate vCPU allocation)
CMD ["uvicorn", "app.main:app", \
    "--host", "0.0.0.0", \
    "--port", "8000", \
    "--workers", "2", \
    "--proxy-headers", \
    "--forwarded-allow-ips", "*"]
