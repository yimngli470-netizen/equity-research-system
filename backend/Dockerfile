FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for psycopg and building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Headless Chromium for the IR scraper's rendered-fetch fallback — JS-rendered / WAF-stalling IR
# sites (ISRG/UBER/FIG) that a static httpx GET can't read. --with-deps pulls the required system libs.
RUN python -m playwright install --with-deps chromium

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
