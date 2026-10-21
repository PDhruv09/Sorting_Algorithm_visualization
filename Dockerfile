FROM eclipse-temurin:21-jdk-noble

# ------------------------------------------------------------
# System configuration
# ------------------------------------------------------------

ENV DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ENV PORT=8000


# ------------------------------------------------------------
# Install Python
#
# Keep the normal system /tmp directory during package
# installation. We switch to the dedicated Sort Visualizer
# temporary directory later, after it has been created.
# ------------------------------------------------------------

RUN apt-get update \
    && apt-get install -y \
        --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*


# ------------------------------------------------------------
# Non-root application user
# ------------------------------------------------------------

RUN groupadd \
        --system \
        sortviz \
    && useradd \
        --system \
        --gid sortviz \
        --create-home \
        --home-dir /home/sortviz \
        sortviz


# ------------------------------------------------------------
# Application directory
# ------------------------------------------------------------

WORKDIR /app


# Copy dependency file first so Docker can cache installation.
COPY requirements.txt /app/requirements.txt


# ------------------------------------------------------------
# Python dependencies
# ------------------------------------------------------------

RUN python3 -m pip install \
        --no-cache-dir \
        --break-system-packages \
        -r /app/requirements.txt


# ------------------------------------------------------------
# Application source
# ------------------------------------------------------------

COPY server.py /app/server.py
COPY runner.py /app/runner.py
COPY static /app/static


# Optional files used by local/testing workflows can be copied
# separately later if needed. They are not required by the
# production web service.


# ------------------------------------------------------------
# Writable temporary directory
#
# Student Java source and compiled files are created in
# temporary directories underneath this location.
# ------------------------------------------------------------

RUN mkdir -p /tmp/sortviz \
    && chown -R sortviz:sortviz /tmp/sortviz \
    && chown -R sortviz:sortviz /app \
    && chmod 700 /tmp/sortviz


# From this point onward, Python/Java temporary files should
# use our dedicated writable directory.
ENV TMPDIR=/tmp/sortviz


# ------------------------------------------------------------
# Drop root privileges
# ------------------------------------------------------------

USER sortviz


# ------------------------------------------------------------
# Networking
# ------------------------------------------------------------

EXPOSE 8000


# ------------------------------------------------------------
# Container health check
# ------------------------------------------------------------

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=15s \
    --retries=3 \
    CMD python3 -c \
        "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.getenv('PORT', '8000') + '/health', timeout=3).read()" \
        || exit 1


# ------------------------------------------------------------
# Production server
#
# Azure Container Apps can provide PORT through the environment.
# One worker is intentional for now because our simple in-memory
# rate limiter is process-local.
# ------------------------------------------------------------

CMD ["sh", "-c", "exec python3 -m uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]