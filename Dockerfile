# syntax=docker/dockerfile:1
# Base images are pinned by digest for reproducible rebuilds; Dependabot bumps them.
FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

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
# does not reinstall them. The web extra is the pit wall (`those-who-run web`), so
# one image runs both; it adds Streamlit, pandas and pyarrow, roughly 300 MB (#26).
COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --extra web

COPY README.md LICENSE rules.example.yaml ./
COPY src ./src
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable --extra web \
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
    GT7_WEB_PORT=8501 \
    PYTHONUNBUFFERED=1

USER 1000:1000
EXPOSE 33740/udp 9850/tcp 8501/tcp
VOLUME ["/data"]

# Probes /healthz for `run` or Streamlit's health for `web`, on the configured port.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["those-who-run", "healthcheck"]

ENTRYPOINT ["those-who-run"]
CMD ["run"]
