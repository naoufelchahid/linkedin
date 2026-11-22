FROM python:3.12-slim AS codex-cli
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) arch=x64; triple=x86_64; digest='l66NZkQgdk2C3pbcfULDz42yEUB581MVA6I+Y43Wp4OIqEy73HCdmZ0GTjeAHY2ycuH4N00d9VsLrwT1jxshTw==' ;; \
      arm64) arch=arm64; triple=aarch64; digest='9z17t4bbUJ9UCIb49O4PoA+ki+45q3rd8nZ8PeH6sYnlKkBld/Xpo/OS3h3Ti954+foshX4o7k5TCU8N7zzqQA==' ;; \
      *) exit 1 ;; \
    esac; \
    python -c 'import sys,urllib.request; urllib.request.urlretrieve(sys.argv[1],"/tmp/codex.tgz")' \
       "https://registry.npmjs.org/@openai/codex/-/codex-0.171.0-linux-${arch}.tgz"; \
    test "$(openssl dgst -sha512 -binary /tmp/codex.tgz | openssl base64 -A)" = "$digest"; \
    mkdir /opt/codex; \
    tar -xzf /tmp/codex.tgz -C /opt/codex --strip-components=3 \
       "package/vendor/${triple}-unknown-linux-musl"; \
    /opt/codex/bin/codex --version

FROM python:3.12-slim AS worker
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer poppler-utils fonts-liberation socat \
    && rm -rf /var/lib/apt/lists/*
COPY --from=codex-cli /opt/codex /opt/codex
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /usr/local/bin/uv
WORKDIR /worker/graphe2
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable \
    && useradd --create-home --uid 1000 worker
ENV PATH="/worker/graphe2/.venv/bin:/opt/codex/bin:/opt/codex/codex-path:${PATH}"
USER worker
ENTRYPOINT ["linkedin-applications"]
