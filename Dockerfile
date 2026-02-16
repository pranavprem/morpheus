FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies including Bitwarden CLI
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Download and install Bitwarden CLI
RUN curl -L "https://github.com/bitwarden/clients/releases/download/cli-v2024.2.0/bw-linux-2024.2.0.zip" -o bw.zip \
    && unzip bw.zip \
    && chmod +x bw \
    && mv bw /usr/local/bin/ \
    && rm bw.zip

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create non-root user
RUN useradd --create-home --shell /bin/bash morpheus
USER morpheus

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]