FROM python:3.12-slim

WORKDIR /app

# System deps for eval7 Cython build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install Python deps (needs eval7 wheel)
COPY eval7-0.1.10-cp312-cp312-manylinux*.whl .
COPY source/requirements.txt .
RUN pip install --no-cache-dir eval7-0.1.10-cp312-cp312-manylinux*.whl \
    && pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY source/app.py .
COPY source/result_parser.py .
COPY source/ai_guard.py .
COPY source/dirk_tracker.py .
COPY source/cache_layer.py .
COPY source/engine_cache.py .
COPY source/scripts/ ./scripts/
COPY source/static/ ./static/

# Runtime dirs
RUN mkdir -p uploads tracker_events validated_hands cache

EXPOSE 5002

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
