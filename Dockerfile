# Two stages: Node builds the frontend, Python runs the API and serves the
# built assets. One image, one Render service — the same shape render.yaml
# describes for the native Python runtime.

# --- Stage 1: build the frontend -------------------------------------------
# Node 22: Vite 7 requires ^20.19.0 || >=22.12.0, and 22 LTS clears it without
# depending on which 20.x minor the tag happens to point at.
FROM node:22-slim AS frontend

WORKDIR /app/frontend

# Manifests first, so npm ci stays cached until dependencies actually change.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- Stage 2: the app ------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Same ordering trick: requirements before source, so editing code doesn't
# reinstall the world. psycopg and bcrypt both ship wheels, so no compiler.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ backend/

# config.py resolves static_dir as <repo root>/frontend/dist, and this image's
# repo root is /app — so the built assets have to land exactly here or
# main.py silently skips mounting them and serves a bare API.
COPY --from=frontend /app/frontend/dist frontend/dist

# Non-root. It owns /app because backend/ is where the SQLite fallback file
# gets written when DATABASE_URL is unset.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

# Render injects PORT; the default keeps `docker run` working locally.
ENV PORT=10000
EXPOSE 10000

# Migrations run at startup rather than at build time — the database isn't
# reachable while building. render.yaml puts this in preDeployCommand, which
# the free plan doesn't offer, so it moves here.
CMD ["sh", "-c", "cd backend && alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
