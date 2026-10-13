# NOTE: docker build not yet validated (no Docker on the authoring machine); validate on a Docker-capable host before deployment.
#
# Lynceus single-container image: FastAPI backend + statically exported Next.js UI.
# Layout note: backend/src/lynceus/api.py computes
#   _WEB_DIR = Path(__file__).resolve().parents[3] / "web" / "out"
# which from /app/backend/src/lynceus/api.py resolves to /app/web/out —
# the UI is staged at exactly that repo-relative location.

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

WORKDIR /app

# Backend package (src layout, includes the vendored lynceus_engine).
COPY backend/ ./backend/

# Install the backend and its dependencies from its own pyproject.toml.
RUN pip install --no-cache-dir ./backend

# Static web export built in stage 1, kept at the repo-relative location
# that _WEB_DIR resolves to (repo root web/out).
COPY --from=web /app/web/out ./web/out

# Persistent audit-record storage (LYNCEUS_STORAGE_DIR default in config.py is ./runs).
ENV LYNCEUS_STORAGE_DIR=/data
RUN mkdir -p /data
VOLUME /data

EXPOSE 8020

CMD ["python", "-m", "lynceus.main"]
