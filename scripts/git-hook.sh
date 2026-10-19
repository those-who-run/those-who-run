#!/bin/sh
# The git hooks (#339): `make hooks` copies this file to .git/hooks/pre-commit and
# .git/hooks/commit-msg, and it runs pre-commit with .pre-commit-config.yaml.
#
# Git keeps hooks in the common .git/hooks, shared by every worktree, and runs them
# from the root of the checkout that is committing. So this runs that checkout's own
# .venv/bin/pre-commit: removing the worktree that ran `make hooks` breaks nothing,
# and a branch from before the hooks (no .pre-commit-config.yaml) commits as it did.
hook=$(basename "$0")
if [ ! -f .pre-commit-config.yaml ]; then
	exit 0
fi
if [ ! -x .venv/bin/pre-commit ]; then
	echo "the $hook hook runs this checkout's .venv/bin/pre-commit: run \`make venv\` in $(pwd)" >&2
	exit 1
fi
here=$(cd "$(dirname "$0")" && pwd)
exec .venv/bin/pre-commit hook-impl --config=.pre-commit-config.yaml --hook-type="$hook" \
	--hook-dir "$here" -- "$@"
