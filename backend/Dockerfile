# Homelab Dashboard — Backend Dockerfile
# Multi-stage build: Python 3.12 slim

FROM docker:28-cli AS docker_cli
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HOMELAB_DATA_MOUNT=/app/data

WORKDIR /app

COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker_cli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/

# Install system dependencies for Docker SDK
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make entrypoint executable
RUN chmod +x entrypoint.sh && mkdir -p /app/data && \
    ln -s data/homelab.db /app/homelab.db && \
    ln -s data/apps /app/apps && ln -s data/backups /app/backups

# Expose FastAPI port
EXPOSE 8000

# Run migrations and then start the server
ENTRYPOINT ["./entrypoint.sh"]
