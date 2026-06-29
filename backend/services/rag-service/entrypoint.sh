#!/bin/sh
set -e

echo "========================================================="
echo "Running Alembic database migrations for RAG service..."
echo "========================================================="
alembic upgrade head

echo "========================================================="
echo "Database migrations complete. Starting FastAPI server..."
echo "========================================================="
exec uvicorn app.main:app --host 0.0.0.0 --port 8001
