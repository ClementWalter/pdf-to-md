FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output for logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps required by Marker (OCR, image processing)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy full project (pyproject.toml + source) to build the package
COPY pyproject.toml ./
COPY src/ src/

# Install production dependencies including the ML extras (marker-pdf + torch)
RUN uv pip install --system --no-cache ".[ml]"

# Create cache directory
RUN mkdir -p /app/cache

EXPOSE 8000

CMD ["uvicorn", "pdf2md.main:app", "--host", "0.0.0.0", "--port", "8000"]
