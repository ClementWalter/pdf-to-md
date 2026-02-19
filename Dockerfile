FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output for logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Cache-busting arg: changes each commit so COPY + install always re-run
ARG CACHE_BUST=unknown

# Copy full project (pyproject.toml + source) to build the package
COPY pyproject.toml ./
COPY src/ src/

# Install production dependencies (pymupdf4llm is lightweight, no ML models needed)
RUN uv pip install --system --no-cache "."

# Create cache directory
RUN mkdir -p /app/cache

EXPOSE 8000

CMD ["uvicorn", "pdf2md.main:app", "--host", "0.0.0.0", "--port", "8000"]
