# Lynceus single-container image: FastAPI backend + statically exported Next.js UI.
#
#   docker build -t lynceus .
#   docker run -d --name lynceus -p 8020:8020 --env-file .env -v lynceus-runs:/data/runs lynceus
#
# The AMD Token Factory key is supplied at run time (--env-file / -e) and is never
# copied into the image (.dockerignore excludes every .env).

# ---------- Stage 1: build the static web export ----------
FROM node:20-alpine AS web

WORKDIR /app/web

# Install deps from the lockfile only, so this layer caches on lockfile changes.
COPY web/package.json web/package-lock.json ./
RUN npm ci

# Build the Next.js static export (output: "export" -> web/out).
COPY web/ ./
RUN npm run build

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Backend sources, sample-shift seeder and the committed benchmark manifest/results
# (the benchmark images are excluded by .dockerignore).
COPY backend/ ./backend/

# Regular (non-editable) install; knowledge/*.md ships as package data.
RUN pip install --no-cache-dir ./backend

# Static web export from stage 1.
COPY --from=web /app/web/out ./web/out

COPY deploy/entrypoint.sh /usr/local/bin/lynceus-entrypoint
RUN chmod +x /usr/local/bin/lynceus-entrypoint

# A site-packages install cannot find web/out or benchmark/ relative to the
# source tree, so point the app at where they were staged.
# Audit records live on a volume so they survive container replacement.
ENV LYNCEUS_WEB_DIR=/app/web/out \
    LYNCEUS_BENCHMARK_DIR=/app/backend/benchmark \
    LYNCEUS_STORAGE_DIR=/data/runs \
    PORT=8020

# Unprivileged runtime user; the volume mount point is created owned by it so a
# fresh named volume inherits that ownership.
RUN useradd --uid 10001 --no-create-home --home-dir /app lynceus \
    && mkdir -p /data/runs \
    && chown -R lynceus:lynceus /data
USER lynceus

VOLUME /data/runs

EXPOSE 8020

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8020'), timeout=4)"

ENTRYPOINT ["lynceus-entrypoint"]
