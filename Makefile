IMAGE_NAME := muldoon/those-who-run
PLATFORM   := linux/amd64
VERSION    ?= dev
VOICE      := en_GB-alba-medium
VOICE_URL  := https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium
PY         ?= .venv/bin/python

.PHONY: help venv lock voice lint fmt typecheck test check build replay web archive-push archive-pull clean

help:
	@echo "help     - this list"
	@echo "venv     - create .venv from uv.lock with the dev and web extras (needs uv)"
	@echo "lock     - re-resolve uv.lock after changing dependencies in pyproject.toml"
	@echo "voice    - download the Piper voice into ./voices"
	@echo "lint     - ruff check + format check"
	@echo "fmt      - ruff format"
	@echo "typecheck - mypy on src/"
	@echo "test     - pytest"
	@echo "check    - everything a PR must pass: lint, typecheck, tests with coverage floor (CI runs this)"
	@echo "build    - podman build $(IMAGE_NAME):$(VERSION) for $(PLATFORM)"
	@echo "replay   - replay FILE=recording.jsonl"
	@echo "web      - the pit wall on http://localhost:8501"
	@echo "archive-push - upload GT7_ARCHIVE_DIR to the outings release (ADR 0002)"
	@echo "archive-pull - download the outings release into GT7_ARCHIVE_DIR"
	@echo "clean    - remove .venv, caches, coverage and build output"

# Python version from .python-version, packages from uv.lock: the same set CI and
# the image install.
venv:
	uv sync --frozen --extra dev --extra web

lock:
	uv lock

# Checked against voices/SHA256SUMS, the file the Dockerfile checks too.
voice:
	mkdir -p voices
	cd voices && for f in $(VOICE).onnx $(VOICE).onnx.json; do \
		test -f $$f || curl -fsSL -o $$f $(VOICE_URL)/$$f || exit 1; \
	done
	cd voices && grep -E ' $(VOICE)\.onnx(\.json)?$$' SHA256SUMS | sha256sum -c --strict - \
		|| { rm -f $(VOICE).onnx $(VOICE).onnx.json; exit 1; }

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

fmt:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

typecheck:
	$(PY) -m mypy

test:
	$(PY) -m pytest -q

# The definition of green: CI runs exactly this. The coverage floor lives in
# pyproject.toml ([tool.coverage.report] fail_under); a skipped test fails the run;
# uv.lock must match pyproject.toml.
check: lint typecheck
	uv lock --check
	TWR_FAIL_ON_SKIP=1 $(PY) -m pytest -q -rs --cov --cov-report=term

build:
	podman build --format docker --platform $(PLATFORM) -t $(IMAGE_NAME):$(VERSION) .

# No release target: images are published only by .github/workflows/release.yml,
# from a v* tag, after make check passes (see README, Releasing).

replay:
	$(PY) -m those_who_run replay $(FILE)

web:
	$(PY) -m those_who_run web

# The outing archive (docs/adr/0002-outing-archive.md): `recordings archive` fills
# the directory, these mirror it to and from the repository's `outings` release.
ARCHIVE ?= $(or $(GT7_ARCHIVE_DIR),$(HOME)/.cache/those-who-run/outings)

archive-push:
	gh release view outings >/dev/null 2>&1 || gh release create outings --prerelease \
		--title "Outing archive" \
		--notes "Outings specs and tests rely on: <id>.jsonl.gz and its <id>.json sidecar. See docs/adr/0002-outing-archive.md."
	gh release upload outings $(ARCHIVE)/*.jsonl.gz $(ARCHIVE)/*.json --clobber

archive-pull:
	mkdir -p $(ARCHIVE)
	gh release download outings -D $(ARCHIVE) --skip-existing

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
