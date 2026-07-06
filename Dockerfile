# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory to /app
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libavcodec-extra \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only necessary application files
# The .dockerignore file ensures we only include what's specified
COPY musicround/ ./musicround/
COPY migrations/ ./migrations/
COPY run_migration.py run.py wsgi.py docker-entrypoint.sh LICENSE favicon.ico .

# Make the entrypoint script executable
RUN chmod +x docker-entrypoint.sh

# Create necessary directories and ensure proper permissions
RUN mkdir -p /data/rounds /data/pdfs && chmod -R 777 /data

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_APP=run.py

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import json, urllib.request; response = urllib.request.urlopen('http://127.0.0.1:5000/healthz', timeout=3); payload = json.load(response); raise SystemExit(0 if payload.get('ok') else 1)"

# Use the entrypoint script
CMD ["./docker-entrypoint.sh"]
