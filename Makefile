IMAGE_NAME := muldoon/those-who-run
PLATFORM   := linux/amd64
VERSION    ?= dev
VOICE      := en_GB-alba-medium
VOICE_URL  := https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium
PYTHON     ?= python3
PY         ?= .venv/bin/python

.PHONY: help venv voice lint fmt typecheck test check build release replay web clean

help:
	@echo "help     - this list"
	@echo "venv     - create .venv and install with dev and web extras"
	@echo "voice    - download the Piper voice into ./voices"
	@echo "lint     - ruff check + format check"
	@echo "fmt      - ruff format"
	@echo "typecheck - mypy on src/"
	@echo "test     - pytest"
	@echo "check    - everything a PR must pass: lint, typecheck, tests with coverage floor (CI runs this)"
	@echo "build    - podman build $(IMAGE_NAME):$(VERSION) for $(PLATFORM)"
	@echo "release  - build and push with VERSION=x.y.z"
	@echo "replay   - replay FILE=recording.jsonl"
	@echo "web      - the pit wall on http://localhost:8501"
	@echo "clean    - remove .venv, caches, coverage and build output"

venv:
	$(PYTHON) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,web]"

voice: voices/$(VOICE).onnx voices/$(VOICE).onnx.json

voices/%:
	mkdir -p voices
	curl -fsSL -o $@ $(VOICE_URL)/$(notdir $@)

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
# pyproject.toml ([tool.coverage.report] fail_under); a skipped test fails the run.
check: lint typecheck
	TWR_FAIL_ON_SKIP=1 $(PY) -m pytest -q -rs --cov --cov-report=term

build:
	podman build --platform $(PLATFORM) -t $(IMAGE_NAME):$(VERSION) .

release:
	@test "$(VERSION)" != "dev" || (echo "set VERSION=x.y.z" && exit 1)
	podman build --platform $(PLATFORM) -t $(IMAGE_NAME):$(VERSION) .
	podman push $(IMAGE_NAME):$(VERSION)
	@echo "Released $(IMAGE_NAME):$(VERSION)"

replay:
	$(PY) -m those_who_run replay $(FILE)

web:
	$(PY) -m those_who_run web

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
