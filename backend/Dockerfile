FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ENV PATH="/application/.venv/bin:$PATH"
WORKDIR /application
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-build

FROM python:3.13-slim-bookworm
RUN useradd --create-home --uid 10001 application
WORKDIR /application
ENV PATH="/application/.venv/bin:$PATH"
COPY --from=build --chown=application:application /application/.venv/ ./.venv/
COPY --chown=application:application app/ ./app/
COPY --chown=application:application scripts/ ./scripts/
COPY --chown=application:application alembic/ ./alembic/
COPY --chown=application:application alembic.ini ./
COPY --chown=application:application tests/fixtures/recorded/flights/ ./tests/fixtures/recorded/flights/
RUN chown application:application /application
USER application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
