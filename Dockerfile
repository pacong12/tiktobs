# TikTObs — TikTok LIVE OBS Integration
#
# Build:  docker build -t tiktobs .
# Run:    docker run -d --name tiktobs -p 8000:8000 -v tiktobs-data:/app/data tiktobs
#
# The app listens on 0.0.0.0 inside the container; map the port however you
# like. Persistent state (SQLite DB, ticker/sound configs, logs, uploaded
# sounds) lives in /app/data — keep it on a volume.

FROM python:3.12-slim

# Don't buffer logs so `docker logs -f` streams in real time, and don't
# create .pyc files in the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first (layer caching) before copying the code.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code. `data/` is intentionally NOT copied — it is a volume.
COPY app ./app
COPY static ./static
COPY run_app.py .

# Non-root user; data volume owned by it.
RUN useradd --create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

VOLUME ["/app/data"]
EXPOSE 8000

# run_app.py binds 127.0.0.1 and opens a browser, which makes no sense in a
# container, so start uvicorn directly. Host/port are overridable.
ENV TIKTOBS_HOST=0.0.0.0 \
    TIKTOBS_PORT=8000
CMD ["sh", "-c", "uvicorn app.main:app --host ${TIKTOBS_HOST} --port ${TIKTOBS_PORT}"]
