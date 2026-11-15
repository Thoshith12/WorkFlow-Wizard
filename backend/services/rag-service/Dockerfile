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

# ── Torch (own layer — cached independently of requirements.txt) ──────────────
# CPU build — smaller (~195 MB) and reliable on unstable networks.
# Switch back to torch==2.3.1+cu121 with --index-url https://download.pytorch.org/whl/cu121
# once the network is stable and you want GPU inference.
RUN pip install --no-cache-dir --timeout 300 --retries 5 \
        torch==2.3.1 \
        --index-url https://download.pytorch.org/whl/cpu

# Install remaining rag-service dependencies (torch excluded — already above)
COPY services/rag-service/requirements.txt .
RUN pip install --no-cache-dir --timeout 300 -r requirements.txt

# Download FastText language-identification model (~126 MB, cached after first build)
# Path must match FASTTEXT_MODEL_PATH env var default in steps.py
RUN curl -fSL -o /workspace/lid.176.ftz \
    https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz

# Create HuggingFace model cache directory
# Models are downloaded on first use and persisted via Docker volume mount.
RUN mkdir -p /workspace/.cache/huggingface
ENV HF_HOME=/workspace/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/workspace/.cache/huggingface/sentence-transformers

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
