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

# Dev-only: the Claude Code CLI. When LLM_BACKEND=claude_code (the dev/local backend) the app routes
# every completion through this CLI using CLAUDE_CODE_OAUTH_TOKEN, so calls bill to a Max/Pro
# SUBSCRIPTION instead of API credits. Gated by a build arg so PROD images (LLM_BACKEND=api) stay
# lean and never ship the CLI. The local docker-compose sets INSTALL_CLAUDE_CLI=1.
ARG INSTALL_CLAUDE_CLI=0
RUN if [ "$INSTALL_CLAUDE_CLI" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && \
        curl -fsSL https://claude.ai/install.sh | bash && \
        rm -rf /var/lib/apt/lists/*; \
    fi
ENV PATH="/root/.local/bin:${PATH}"

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
