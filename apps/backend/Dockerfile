FROM ghcr.io/astral-sh/uv:0.12.13 AS uv
FROM python:3.12-slim-bookworm AS base
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app/apps/backend:/app/python"
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY apps/backend apps/backend
COPY python python
COPY contracts contracts
RUN DJANGO_SETTINGS_MODULE=config.settings.dev python apps/backend/manage.py collectstatic --noinput

FROM base AS development
RUN uv sync --frozen
COPY tests tests
COPY scripts scripts
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "apps/backend", "--reload-dir", "python"]

FROM base AS production
USER 10001:10001
ENV DJANGO_SETTINGS_MODULE=config.settings.prod
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-graceful-shutdown", "20"]
