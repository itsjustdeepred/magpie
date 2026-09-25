FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/data \
    HEARTBEAT_FILE=/tmp/magpie.heartbeat \
    PUID=1000 \
    PGID=1000

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY magpie/ magpie/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

VOLUME /data

# The bot touches the heartbeat file every 30s while its event loop is alive.
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, sys, time; sys.exit(time.time() - os.path.getmtime(os.environ['HEARTBEAT_FILE']) > 120)"

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "magpie"]
