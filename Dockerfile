# syntax=docker/dockerfile:1

# --- Stage 1: build the SPA -------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: runtime -------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Chromium's system libraries. Acquisition is part of the product, so the
# worker path and the API path share one image rather than pretending the
# crawler is an optional add-on.
COPY pyproject.toml alembic.ini ./
COPY api ./api
COPY services ./services
COPY database ./database
COPY scripts ./scripts
COPY configs ./configs
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN pip install --upgrade pip && pip install . \
 && playwright install --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 polaris \
 && chmod +x /app/scripts/docker-entrypoint.sh \
 && chown -R polaris:polaris /app /ms-playwright
USER polaris

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3); sys.exit(0 if r.status==200 else 1)"

CMD ["/app/scripts/docker-entrypoint.sh"]
