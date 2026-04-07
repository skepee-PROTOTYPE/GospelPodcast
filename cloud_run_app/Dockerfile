# Cloud Run container for Gospel TTS publisher
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Rome

WORKDIR /app

# Install system deps: curl for health checks, ffmpeg for audio chunking/concat
RUN apt-get update -y && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy source
COPY cloud_run_app/requirements.txt /app/requirements.txt
COPY gospel_tts_app /app/gospel_tts_app
COPY gospel /app/gospel
COPY cloud_run_app/app.py /app/app.py

# Install Python deps
RUN pip install --no-cache-dir -r /app/requirements.txt

# Expose port
# Default to free Edge TTS — override with TTS_PROVIDER=google to use Neural2
ENV PORT=8080 \
    TTS_PROVIDER=edge

# Runtime env: set bucket via deploy time
# ENV FIREBASE_BUCKET=your-bucket-name

CMD ["python", "app.py"]
