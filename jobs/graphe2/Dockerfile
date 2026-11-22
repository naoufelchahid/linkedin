FROM python:3.12-slim AS worker
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /usr/local/bin/uv
WORKDIR /worker/graphe2
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable \
    && useradd --create-home --uid 1000 worker
ENV PATH="/worker/graphe2/.venv/bin:${PATH}"
USER worker
ENTRYPOINT ["linkedin-applications"]
