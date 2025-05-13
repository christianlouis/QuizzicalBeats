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
COPY run_migration.py run.py docker-entrypoint.sh LICENSE favicon.ico ./

# Make the entrypoint script executable
RUN chmod +x docker-entrypoint.sh

# Create necessary directories and ensure proper permissions
RUN mkdir -p /data && chmod 777 /data

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_APP=run.py

# Use the entrypoint script
ENTRYPOINT ["./docker-entrypoint.sh"]