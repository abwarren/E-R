FROM python:3.12-slim

WORKDIR /app

# Install system deps (python3-dev needed for eval7 Cython build)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY source/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy engine source
COPY source/app.py .
COPY source/result_parser.py .
COPY source/ai_guard.py .
COPY source/dirk_tracker.py .
COPY source/cache_layer.py .
COPY source/engine_cache.py .
COPY source/scripts/ ./scripts/

# Create runtime directories
RUN mkdir -p uploads tracker_events validated_hands static cache

EXPOSE 5002

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
