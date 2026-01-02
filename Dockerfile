# REdI Email Processing API - Dockerfile
# 
# Multi-stage build for production deployment
# Author: Sean Wing
# Date: 2026-01-02

FROM python:3.11-slim as base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY templates/ ./templates/

# Create non-root user for security
RUN useradd -m -u 1000 redi && \
    chown -R redi:redi /app && \
    mkdir -p /var/log/redi && \
    chown -R redi:redi /var/log/redi

# Switch to non-root user
USER redi

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:5000/health')" || exit 1

# Run the application with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "src.app:app"]
