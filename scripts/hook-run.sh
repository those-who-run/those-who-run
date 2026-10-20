#!/bin/sh
# Runs one of .pre-commit-config.yaml's local hooks with this checkout's own tool (the
# version uv.lock or web/package-lock.json pins). A missing tool fails the hook with
# the make target that installs it, rather than letting the hook pass without it.
#
#   scripts/hook-run.sh <tool> <make target> [args...]
tool=$1
target=$2
shift 2
if ! command -v "$tool" >/dev/null 2>&1; then
	echo "$tool is missing in $(pwd): run \`make $target\` first" >&2
	exit 1
fi
exec "$tool" "$@"
