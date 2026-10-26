# syntax=docker/dockerfile:1
# Base images are pinned by digest for reproducible rebuilds; Dependabot bumps them.
#
# Two images from one file (ADR 0001 point 5, amended by ADR 0003 point 7):
#   (default)         the engineer, `run`
#   --target pitwall  the pit wall: the data API and the built web app, nothing else
# BuildKit builds only the stages the target needs, so the engineer's build never
# runs Node or reads web/.
FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

# The web app (web/), built to static files. Node lives only in this stage.
FROM node:26-slim@sha256:0d1e33586362bb9e608c4e751e7a9e7edb55c9ac11461ed5666af696cc461dd4 AS web
WORKDIR /web
COPY web/package.json web/package-lock.json web/.npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# The pit wall: `those-who-run pitwall` serving /api/v1 over GT7_DATA_DIR and the
# web app from /app/web. The core install only (aiohttp, DuckDB, PyYAML): no
# engineer extra (Discord, Piper, gt-telem, prometheus-client), no audio
# libraries, no voice and no Node.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS pitwall

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

# The licence, the third-party notices, the fonts' OFL text and the voice's model card.
COPY README.md LICENSE THIRD_PARTY_NOTICES.md rules.example.yaml ./
COPY licenses ./licenses
COPY src ./src
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable \
    && useradd --uid 1000 --user-group --home-dir /app --no-create-home engineer \
    && mkdir -p /data \
    && chown -R engineer:engineer /data

COPY --from=web /web/dist /app/web

ENV PATH=/app/.venv/bin:$PATH \
    GT7_DATA_DIR=/data \
    GT7_PITWALL_STATIC=/app/web \
    GT7_PITWALL_PORT=9852 \
    PYTHONUNBUFFERED=1

USER 1000:1000
EXPOSE 9852/tcp
VOLUME ["/data"]

# /healthz on GT7_PITWALL_PORT: up while /data is readable, engineer or not.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["those-who-run", "healthcheck", "--mode", "pitwall"]

ENTRYPOINT ["those-who-run"]
CMD ["pitwall"]

# The engineer, the default target: it stays the last stage.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS engineer

ARG VOICE=en_GB-alba-medium
ARG VOICE_URL=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The voice, checked against voices/SHA256SUMS (the same file `make voice` checks).
COPY voices/SHA256SUMS /app/voices/SHA256SUMS
RUN cd /app/voices \
    && python -c "import sys, urllib.request as u; [u.urlretrieve(f'{sys.argv[1]}/{n}', n) for n in sys.argv[2:]]" \
        "${VOICE_URL}" "${VOICE}.onnx" "${VOICE}.onnx.json" \
    && grep -E " ${VOICE}\.onnx(\.json)?$" SHA256SUMS | sha256sum -c --strict -

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependencies from the lockfile first, in their own layer: a change under src/
# does not reinstall them. The engineer extra is Discord, Piper, gt-telem and
# metrics. The pit wall is its own image (--target pitwall).
COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra engineer

# The licence, the third-party notices, the fonts' OFL text and the voice's model card.
COPY README.md LICENSE THIRD_PARTY_NOTICES.md rules.example.yaml ./
COPY licenses ./licenses
COPY src ./src
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --extra engineer \
    && useradd --uid 1000 --user-group --home-dir /app --no-create-home engineer \
    && mkdir -p /data \
    && chown -R engineer:engineer /data

# The speech cache goes to $XDG_CACHE_HOME/those-who-run, outside the /data volume
# the pit wall can write to (ADR 0001); /tmp is the same place HOME=/tmp gives.
ENV PATH=/app/.venv/bin:$PATH \
    GT7_VOICE_MODEL=/app/voices/en_GB-alba-medium.onnx \
    GT7_DATA_DIR=/data \
    XDG_CACHE_HOME=/tmp/.cache \
    GT7_METRICS_PORT=9850 \
    PYTHONUNBUFFERED=1

USER 1000:1000
EXPOSE 33740/udp 9850/tcp
VOLUME ["/data"]

# Probes the engineer's /healthz on GT7_METRICS_PORT.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["those-who-run", "healthcheck"]

ENTRYPOINT ["those-who-run"]
CMD ["run"]
