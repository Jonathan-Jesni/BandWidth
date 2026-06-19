# Single image shared by every BandWidth process. Each docker-compose service
# (server + the 5 agent daemons) runs this image with its own `command`.
FROM python:3.11-slim

# Faster, cleaner Python in containers.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install deps first so the layer caches across source changes.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy the application source (see .dockerignore for exclusions).
COPY . .

# Webhook server port (agents need no inbound ports — they dial out to Band).
EXPOSE 5000

# No default CMD: docker-compose sets the per-service command. Running the
# image directly starts the webhook server, bound for container networking.
ENV HOST=0.0.0.0
CMD ["python", "server.py"]
