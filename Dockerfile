# Match README badge (Python 3.12). Keep slim for smaller images.
FROM python:3.12-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    ntp \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code (flat layout: many sibling modules)
COPY *.py ./
COPY .env.example .env.example
COPY .env.lighter.example .env.lighter.example
# News fixtures may be needed for replay/tests; scripts for ops helpers.
# Do NOT COPY .env — mount secrets at runtime instead.
COPY news_fixtures/ ./news_fixtures/
COPY scripts/ ./scripts/

# Create data directory for SQLite
RUN mkdir -p /app/data

# Health check: import smoke-test (mini-app may listen on 8080 when enabled).
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import lighter_news_sniper" || exit 1

# Supervise the sniper and, when MM_ENABLED=1, the market maker.
CMD ["python", "watchdog_supervisor.py"]
