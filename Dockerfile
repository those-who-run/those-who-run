FROM python:3.12-slim

ARG VOICE=en_GB-alba-medium
ARG VOICE_URL=https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium
ARG VOICE_SHA256=401369c4a81d09fdd86c32c5c864440811dbdcc66466cde2d64f7133a66ad03b
ARG VOICE_JSON_SHA256=aa965a2f02ecced632c2694e1fc72bbff6d65f265fab567ca945918c73dd89f4

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/voices \
    && curl -fsSL -o /app/voices/${VOICE}.onnx "${VOICE_URL}/${VOICE}.onnx" \
    && curl -fsSL -o /app/voices/${VOICE}.onnx.json "${VOICE_URL}/${VOICE}.onnx.json" \
    && echo "${VOICE_SHA256}  /app/voices/${VOICE}.onnx" | sha256sum -c - \
    && echo "${VOICE_JSON_SHA256}  /app/voices/${VOICE}.onnx.json" | sha256sum -c -

COPY pyproject.toml README.md LICENSE rules.example.yaml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --uid 1000 --user-group --home-dir /app --no-create-home engineer \
    && mkdir -p /data /tmp/those-who-run \
    && chown -R engineer:engineer /data /tmp/those-who-run

ENV GT7_VOICE_MODEL=/app/voices/en_GB-alba-medium.onnx \
    GT7_DATA_DIR=/data \
    GT7_METRICS_PORT=9850 \
    PYTHONUNBUFFERED=1

USER 1000:1000
EXPOSE 33740/udp 9850/tcp
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s \
    CMD curl -fsS http://127.0.0.1:9850/healthz || exit 1

ENTRYPOINT ["those-who-run"]
CMD ["run"]
