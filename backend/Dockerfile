FROM python:3.12-slim

WORKDIR /app

# System deps: curl for healthcheck, libpq for psycopg2 fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download spacy model (avoids runtime download delay)
RUN python -m spacy download en_core_web_sm 2>/dev/null || true

COPY . .

# Create required directories
RUN mkdir -p /app/models /app/data/raw /app/data/processed /app/data/temporal /app/data/output /app/logs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
