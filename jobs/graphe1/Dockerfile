FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock README.md langgraph.json ./
COPY src ./src
RUN uv sync --locked --no-dev --group studio --no-editable \
    && useradd --create-home --uid 1000 discovery \
    && install -d -o discovery -g discovery -m 700 /app/.langgraph_api /home/discovery/.codex \
    && touch .env && chown discovery .env && chmod 600 .env
ENV PATH="/app/.venv/bin:${PATH}"
USER discovery
CMD ["langgraph", "dev", "--host", "0.0.0.0", "--port", "2024", "--no-browser", "--no-reload", "--allow-blocking"]
