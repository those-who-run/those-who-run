#!/usr/bin/env bash
# The Streamlit pit wall is gone (#238 AC4): no image can import it.
#   scripts/smoke-no-web-extra.sh IMAGE...   (DOCKER=podman to use podman)
# Each image's size goes to the step summary too, so #26 can follow the engineer's.
set -euo pipefail

[ $# -gt 0 ] || { echo "usage: smoke-no-web-extra.sh IMAGE..." >&2; exit 2; }
docker=${DOCKER:-docker}

for image in "$@"; do
  echo "$image: $("$docker" image inspect "$image" --format '{{.Size}}' | awk '{printf "%.0f MB", $1 / 1e6}')" \
    | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  if "$docker" run --rm --entrypoint /app/.venv/bin/python "$image" -c "import streamlit" 2> /dev/null; then
    echo "$image still has Streamlit" >&2
    exit 1
  fi
done
echo "no Streamlit: OK"
