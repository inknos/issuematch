FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /usr/local/bin/uv

WORKDIR /opt/issuematch

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

COPY app/ app/
COPY alembic/ alembic/
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --no-cache

# -----------------------------------------------------------
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/issuematch/.venv/bin:$PATH"

WORKDIR /opt/issuematch

COPY --from=builder /opt/issuematch/.venv .venv
COPY --from=builder /opt/issuematch/app app
COPY --from=builder /opt/issuematch/alembic alembic
COPY --from=builder /opt/issuematch/alembic.ini .

EXPOSE 9473

CMD ["sh", "-c", "alembic upgrade head && python -m app.seed_admin && uvicorn app.main:app --host 0.0.0.0 --port 9473"]
