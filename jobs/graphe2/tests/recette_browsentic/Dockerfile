FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /usr/local/bin/uv
WORKDIR /worker/graphe2
COPY graphe1/pyproject.toml graphe1/README.md ../graphe1/
COPY graphe1/src ../graphe1/src
COPY graphe2/pyproject.toml graphe2/uv.lock ./
COPY graphe2/src ./src
RUN uv sync --locked --no-dev --no-editable \
    && useradd --create-home --uid 1000 worker
COPY graphe2/tests/recette_browsentic/*.py graphe2/tests/recette_browsentic/recette.pdf /recette/
ENV PATH="/worker/graphe2/.venv/bin:${PATH}"
USER worker
