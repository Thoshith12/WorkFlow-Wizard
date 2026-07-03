#!/bin/sh
set -e

if [ $# -gt 0 ]; then
    echo "========================================================="
    echo "Starting custom command: $@"
    echo "========================================================="
    exec "$@"
fi

echo "========================================================="
echo "Running Alembic database migrations for RAG service..."
echo "========================================================="
alembic upgrade head

echo "========================================================="
echo "Starting FastAPI server..."
echo "========================================================="
exec uvicorn app.main:app --host 0.0.0.0 --port 8001
