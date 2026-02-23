FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Silero VAD model during build so it's cached
RUN python -c "from livekit.plugins import silero; silero.VAD.load()"

# Copy application code
COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Railway sets PORT automatically
ENV PORT=8000

EXPOSE ${PORT}

# Run both the LiveKit agent and the FastAPI server
CMD ["./start.sh"]
