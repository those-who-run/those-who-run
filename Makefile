IMAGE_NAME := muldoon/gt7-race-engineer
PLATFORM   := linux/amd64
VERSION    ?= dev
VOICE      := en_GB-alba-medium
VOICE_URL  := https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium
PY         := .venv/bin/python

.PHONY: help venv voice lint fmt test build release run replay clean

help:
	@echo "venv     - create .venv and install with dev extras"
	@echo "voice    - download the Piper voice into ./voices"
	@echo "lint     - ruff check + format check"
	@echo "fmt      - ruff format"
	@echo "test     - pytest"
	@echo "build    - podman build $(IMAGE_NAME):$(VERSION) for $(PLATFORM)"
	@echo "release  - build and push with VERSION=x.y.z"
	@echo "replay   - replay FILE=recording.jsonl"

venv:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

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

test:
	$(PY) -m pytest -q

build:
	podman build --platform $(PLATFORM) -t $(IMAGE_NAME):$(VERSION) .

release:
	@test "$(VERSION)" != "dev" || (echo "set VERSION=x.y.z" && exit 1)
	podman build --platform $(PLATFORM) -t $(IMAGE_NAME):$(VERSION) .
	podman push $(IMAGE_NAME):$(VERSION)
	@echo "Released $(IMAGE_NAME):$(VERSION)"

replay:
	$(PY) -m gt7_race_engineer replay $(FILE)

clean:
	rm -rf .venv .pytest_cache .ruff_cache dist build src/*.egg-info
