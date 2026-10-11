# Multi-stage production container for AI Tool Discovery
# Runs FFmpeg, Faster-Whisper STT, Tesseract OCR, and Flask on Free-Tier Linux hosts
FROM python:3.11-slim

# Set environment flags
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    DATA_DIR=/app/data \
    FLASK_ENV=production

# Install essential system dependencies: FFmpeg, Tesseract OCR, and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . /app/

# Create persistent storage directories
RUN mkdir -p /app/data/uploads /app/data/transcripts /app/data/frames /app/data/audio

# Add non-root user for security (required by Hugging Face Spaces & security best practices)
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Production WSGI startup
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:create_app()"]
