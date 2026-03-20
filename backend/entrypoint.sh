#!/bin/bash
set -e

# Homelab Dashboard — Backend Entrypoint Script
# This script runs migrations before starting the application server.

# Ensure the app package is in the PYTHONPATH
export PYTHONPATH=$PYTHONPATH:.

echo "Running database migrations..."
alembic upgrade head

echo "Starting Homelab Dashboard backend..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
