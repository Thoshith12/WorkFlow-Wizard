FROM python:3.11-slim

WORKDIR /workspace

# Build tools and gVisor runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    g++ \
    make \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Install gVisor (runsc) — direct binary download per https://gvisor.dev/docs/user_guide/install/
RUN set -e \
    && ARCH=$(uname -m) \
    && URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH} \
    && curl -fSL -o runsc ${URL}/runsc \
    && curl -fSL -o runsc.sha512 ${URL}/runsc.sha512 \
    && sha512sum -c runsc.sha512 \
    && rm -f runsc.sha512 \
    && chmod a+rx runsc \
    && mv runsc /usr/local/bin/runsc

# Install shared package (build context is backend/)
COPY shared/ ./shared/
RUN pip install --no-cache-dir -e ./shared

# Install tools-service dependencies
COPY services/tools-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install PyJWT for auth
RUN pip install --no-cache-dir PyJWT[crypto]

# Copy tools-service application, alembic migrations, and entrypoint script
COPY services/tools-service/app/ ./app/
COPY services/tools-service/alembic/ ./alembic/
COPY services/tools-service/alembic.ini .
COPY services/tools-service/entrypoint.sh .

# Create directories for sandbox artefacts
RUN mkdir -p /tmp/tool-venvs /tmp/tool-bundles

RUN chmod +x ./entrypoint.sh \
    && adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /workspace /tmp/tool-venvs /tmp/tool-bundles

# NOTE: gVisor + iptables require elevated privileges at runtime.
# The container must run with --cap-add=NET_ADMIN,SYS_ADMIN or --privileged.
# appuser ownership is set but the sandbox subprocess management may need root.
# In production, use a dedicated sandbox sidecar or rootless gVisor.

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8002/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
