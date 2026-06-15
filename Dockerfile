FROM python:3.12-slim

WORKDIR /app

# System deps + Node.js 20.x (for Express frontend)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Node.js deps
COPY scripts/package.json scripts/package-lock.json ./scripts/
RUN cd scripts && npm install --production

# Copy application code
COPY backend/ ./backend/
COPY scripts/ ./scripts/
COPY source/ ./source/

# Runtime dirs
RUN mkdir -p state logs backend/data backend/data/validated_hands backend/data/hand-collector/saved_hands

EXPOSE 1080 4000

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
ENV PORT=1080

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:1080/api/health || exit 1

CMD ["/entrypoint.sh"]
