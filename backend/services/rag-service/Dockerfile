FROM python:3.11-slim

WORKDIR /workspace

# Build tools needed to compile fasttext-wheel from source on Python 3.11
# (fasttext-wheel has no pre-built wheel for cp311, so pip compiles it)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    make \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Install shared package (build context is backend/)
COPY shared/ ./shared/
RUN pip install --no-cache-dir -e ./shared

# Install rag-service dependencies (fasttext-wheel compiles here — cached after first build)
COPY services/rag-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download FastText language-identification model (~126 MB, cached after first build)
# Path must match FASTTEXT_MODEL_PATH env var default in steps.py
RUN curl -fSL -o /workspace/lid.176.ftz \
    https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz

# Copy rag-service application, alembic migrations, and entrypoint script
COPY services/rag-service/app/ ./app/
COPY services/rag-service/alembic/ ./alembic/
COPY services/rag-service/alembic.ini .
COPY services/rag-service/entrypoint.sh .

RUN chmod +x ./entrypoint.sh \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /workspace

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
