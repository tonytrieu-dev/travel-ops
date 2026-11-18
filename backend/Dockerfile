FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
RUN case "$TARGETARCH" in \
      amd64) target=x86_64; checksum=a1f5ab12e2d60543945c985e372dca66aefe02221d8c235aa618e62720d8a215 ;; \
      arm64) target=aarch64; checksum=ebc92ff9c1ac8f8af0152b7a98f886feea6fc61de1dffd6bd8b52397c64d8fe6 ;; \
      *) exit 1 ;; \
    esac && \
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
      "https://github.com/BoundaryML/baml/releases/download/baml-language-0.23.0/baml-language-0.23.0-${target}-unknown-linux-gnu.tar.gz" \
      -o /tmp/baml.tar.gz && \
    echo "$checksum  /tmp/baml.tar.gz" | sha256sum --check --strict && \
    mkdir /opt/baml && tar -xzf /tmp/baml.tar.gz -C /opt/baml
ENV PATH="/application/.venv/bin:$PATH"
WORKDIR /application
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-build
COPY baml.toml ./
COPY baml_src/ ./baml_src/
RUN /opt/baml/bin/baml-cli generate

FROM python:3.13-slim-bookworm
RUN useradd --create-home --uid 10001 application
WORKDIR /application
ENV PATH="/application/.venv/bin:$PATH"
COPY --from=build --chown=application:application /application/.venv/ ./.venv/
COPY --from=build --chown=application:application /application/baml_sdk/ ./baml_sdk/
COPY --chown=application:application app/ ./app/
COPY --chown=application:application scripts/ ./scripts/
COPY --chown=application:application alembic/ ./alembic/
COPY --chown=application:application alembic.ini ./
COPY --chown=application:application baml_src/ ./baml_src/
COPY --chown=application:application tests/fixtures/recorded/flights/ ./tests/fixtures/recorded/flights/
RUN chown application:application /application
USER application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
