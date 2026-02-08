# T-21: Dockerfile for Agent Zero Telegram Bot
# Multi-stage build for optimized production image

FROM python:3.11-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.11-slim

# Create non-root user for security
RUN groupadd --gid 1000 botuser && \
    useradd --uid 1000 --gid botuser --shell /bin/bash --create-home botuser

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set working directory
WORKDIR /app

# Copy bot code
COPY bot/ ./bot/

# Create data directory and set permissions
RUN mkdir -p /data && chown -R botuser:botuser /data /app

# Switch to non-root user
USER botuser

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default state file location (overridden by config.json)
ENV STATE_FILE=/data/state.json

# Run the bot
CMD ["python", "-m", "bot"]
