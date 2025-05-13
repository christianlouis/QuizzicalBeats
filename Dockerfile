# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory to /app
WORKDIR /app

# Install system dependencies and Node.js
RUN apt-get update && apt-get install -y \
    libavcodec-extra \
    ffmpeg \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make the entrypoint script executable
RUN chmod +x docker-entrypoint.sh

# Create necessary directories and ensure proper permissions
RUN mkdir -p /data && chmod 777 /data

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_APP=run.py

# Use the entrypoint script
ENTRYPOINT ["./docker-entrypoint.sh"]