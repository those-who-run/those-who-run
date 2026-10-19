#!/usr/bin/env bash
# Smoke test of the pitwall image (#237 AC7), as CI and the release run it:
#   scripts/smoke-pitwall.sh IMAGE        (DOCKER=podman to use podman)
# No engineer packages, no Streamlit and no Node in it; it serves /healthz, the
# session list API and the web app over an empty /data; and its size is printed.
set -euo pipefail

image=${1:?usage: smoke-pitwall.sh IMAGE}
docker=${DOCKER:-docker}

echo "pitwall image size: $("$docker" image inspect "$image" --format '{{.Size}}' | awk '{printf "%.0f MB", $1 / 1e6}')" \
  | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"

"$docker" run --rm --entrypoint /app/.venv/bin/python "$image" -c '
import importlib.util, shutil, sys
found = [m for m in ("discord", "piper", "onnxruntime", "gt_telem", "prometheus_client",
                     "streamlit", "pandas", "pyarrow", "numpy") if importlib.util.find_spec(m)]
node = shutil.which("node")
if found or node:
    sys.exit(f"the pitwall image should not have these: {found}, node at {node}")
for m in ("aiohttp", "duckdb", "yaml"):
    assert importlib.util.find_spec(m), m
'

name=twr-pitwall-smoke-$$
"$docker" run -d --rm --name "$name" -p 127.0.0.1::9852 "$image" > /dev/null
trap '"$docker" stop "$name" > /dev/null 2>&1 || true' EXIT
port=$("$docker" port "$name" 9852/tcp | head -n1 | sed 's/.*://')
url=http://127.0.0.1:$port

curl -fsS --retry 20 --retry-all-errors --retry-delay 1 "$url/healthz" | grep -F '"ok":true'
curl -fsS "$url/api/v1/sessions" | grep -F '"sessions"' > /dev/null
curl -fsS "$url/sessions/20261017-162118" | grep -F '<div id="root">' > /dev/null
"$docker" exec "$name" those-who-run healthcheck
echo "pitwall image: OK"
