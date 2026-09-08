# Build the same-origin React client without carrying Node into the runtime image.
FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Keep the public control plane separate from the future Linux ML inference image.
FROM python:3.10-slim AS api-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements-api.txt ./
RUN python -m pip install --upgrade pip && python -m pip install -r requirements-api.txt

COPY src ./src
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

RUN useradd --create-home --uid 10001 appuser
USER appuser

CMD ["sh", "-c", "uvicorn src.api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}"]
