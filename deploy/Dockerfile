# Dockerfile — openmsaify paper trade service
FROM python:3.12-slim

WORKDIR /app

# System deps
RUN apt-get update -qq && apt-get install -y --no-install-recommends \
    gcc git curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App
COPY trading/ ./trading/
COPY daemon.py .
COPY pyproject.toml .

# Runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Healthcheck — daemon creates PID file + log entries
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
  CMD test -f daemon.pid && grep -q "paper_trade_daemon.log" /dev/null || exit 1

ENTRYPOINT ["python", "daemon.py"]
