# syntax=docker/dockerfile:1
FROM python:3.12.11-slim AS base

# ── System dependencies (consolidated single layer) ──
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        git \
        procps \
        tar \
    && rm -rf /var/lib/apt/lists/*

# ── Install agy CLI ──
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"

# ── Python environment configuration ──
# Running as root is a deliberate design decision to allow the agy CLI agent
# full flexibility in managing workspace packages, CLI tools, and system operations.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ── Install uv (fast Python package manager) ──
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /usr/local/bin/

WORKDIR /app

# ── Install Python deps (cache-optimized) ──
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ── Copy application source ──
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ── Create default directories ──
RUN mkdir -p /root/.gemini/antigravity-cli/brain /root/workspace

# ── Entrypoint ──
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# ── Healthcheck: verify bot process is alive ──
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD pgrep -f "main.py" > /dev/null || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["uv", "run", "python", "main.py"]
