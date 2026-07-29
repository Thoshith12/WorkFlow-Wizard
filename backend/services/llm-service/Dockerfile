FROM python:3.11-slim

WORKDIR /workspace

# Install shared package (build context is backend/)
COPY shared/ ./shared/
RUN pip install --no-cache-dir -e ./shared

# Install llm-service dependencies
COPY services/llm-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy llm-service application source
COPY services/llm-service/app/ ./app/

ENV PYTHONPATH=/workspace

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
