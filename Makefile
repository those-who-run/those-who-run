IMAGE_NAME := muldoon/those-who-run
PLATFORM   := linux/amd64
VERSION    ?= dev
VOICE      := en_GB-alba-medium
VOICE_URL  := https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium
PY         ?= .venv/bin/python

.PHONY: help venv lock voice lint fmt typecheck test openapi check build build-pitwall replay web web-build web-dev web-check web-preview archive-push archive-pull clean

help:
	@echo "help     - this list"
	@echo "venv     - create .venv from uv.lock with the dev, engineer and web extras (needs uv)"
	@echo "lock     - re-resolve uv.lock after changing dependencies in pyproject.toml"
	@echo "voice    - download the Piper voice into ./voices"
	@echo "lint     - ruff check + format check"
	@echo "fmt      - ruff format"
	@echo "typecheck - mypy on src/"
	@echo "test     - pytest"
	@echo "openapi  - write web/openapi.json, the pit wall API's schema, from its models"
	@echo "check    - everything a PR must pass: lint, typecheck, tests with coverage floor, web-check (CI runs this)"
	@echo "build    - podman build $(IMAGE_NAME):$(VERSION) for $(PLATFORM)"
	@echo "build-pitwall - podman build the slim pit wall image, $(IMAGE_NAME):$(VERSION)-pitwall"
	@echo "replay   - replay FILE=recording.jsonl"
	@echo "web      - the Streamlit pit wall on http://localhost:8501 (until #238)"
	@echo "web-build - build the React pit wall into web/dist (needs Node, web/.node-version)"
	@echo "web-dev  - Vite's dev server on http://localhost:5173, /api proxied to a local pitwall"
	@echo "web-check - ESLint, tsc, Vitest, the client freshness check, the bundle budget, Playwright"
	@echo "web-preview - web/dist over a read-only copy of the NUC's store, on http://<laptop>:9852"
	@echo "archive-push - upload GT7_ARCHIVE_DIR to the outings release (ADR 0002)"
	@echo "archive-pull - download the outings release into GT7_ARCHIVE_DIR"
	@echo "clean    - remove .venv, caches, coverage and build output"

# Python version from .python-version, packages from uv.lock: the same set CI and
# the image install.
venv:
	uv sync --frozen --extra dev --extra engineer --extra web

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

openapi:
	$(PY) scripts/openapi.py

# The definition of green: CI runs exactly this. The coverage floor lives in
# pyproject.toml ([tool.coverage.report] fail_under); a skipped test fails the run;
# uv.lock must match pyproject.toml; web/openapi.json must match the API's models;
# and the web app passes web-check, which fails when Node or the browser is missing.
check: lint typecheck
	uv lock --check
	$(PY) scripts/openapi.py --check
	TWR_FAIL_ON_SKIP=1 $(PY) -m pytest -q -rs --cov --cov-report=term
	$(MAKE) web-check

build:
	podman build --format docker --platform $(PLATFORM) -t $(IMAGE_NAME):$(VERSION) .

build-pitwall:
	podman build --format docker --platform $(PLATFORM) --target pitwall -t $(IMAGE_NAME):$(VERSION)-pitwall .
	podman image inspect $(IMAGE_NAME):$(VERSION)-pitwall --format 'pitwall image: {{.Size}} bytes'

# No release target: images are published only by .github/workflows/release.yml,
# from a v* tag, after make check passes (see README, Releasing).

replay:
	$(PY) -m those_who_run replay $(FILE)

web:
	$(PY) -m those_who_run web

# The React pit wall (web/, ADR 0003). Node is a development requirement only: the
# version in web/.node-version, packages from web/package-lock.json with npm ci.
# A missing Node or Playwright browser fails, as a skipped test does (#161).
WEB_DEPS := web/node_modules/.package-lock.json
TWR      := $(abspath .venv/bin/those-who-run)

$(WEB_DEPS): web/package.json web/package-lock.json
	@command -v node >/dev/null 2>&1 || { echo "Node is missing: install Node $$(cat web/.node-version) (web/.node-version) to build and check web/" >&2; exit 1; }
	cd web && npm ci --no-audit --no-fund
	@touch $@

web-build: $(WEB_DEPS)
	cd web && npm run build

web-dev: $(WEB_DEPS)
	$(PY) -m those_who_run pitwall --address 127.0.0.1 & pid=$$!; \
		trap 'kill $$pid' EXIT INT TERM; cd web && npm run dev

web-check: $(WEB_DEPS)
	@cd web && node scripts/browser-check.ts
	cd web && npm run lint
	cd web && npm run typecheck
	cd web && npm run api:check
	cd web && npm test
	cd web && npx vite build
	cd web && npm run budget
	cd web && TWR=$(TWR) npx playwright test

# The new pit wall on the phone and iPad before #238 deploys it: web/dist over a
# copy of the NUC's store, taken read-only from the pit wall pod (tar out of /data;
# nothing is written there). Open http://<this laptop>:9852 on the home Wi-Fi.
# /api/engine/* goes to the engineer's read-only port on the node it runs on (its
# hostPort, ADR 0001 point 3), so the live status is live; set PREVIEW_ENGINEER to
# point it elsewhere.
PREVIEW_CONTEXT ?= my-cluster
PREVIEW_POD     ?= deploy/those-who-run-pitwall
PREVIEW_ENGINEER_SELECTOR ?= app.kubernetes.io/name=those-who-run

web-preview: web-build
	rm -rf .preview && mkdir -p .preview/data
	kubectl --context=$(PREVIEW_CONTEXT) -n those-who-run exec $(PREVIEW_POD) -- \
		tar -C /data -cf - --exclude=./engineer.lock . | tar -C .preview/data -xf -
	@echo "pit wall preview: http://$$(hostname -I 2>/dev/null | cut -d' ' -f1):9852"
	engineer=$${PREVIEW_ENGINEER:-http://$$(kubectl --context=$(PREVIEW_CONTEXT) -n those-who-run get pod \
		-l $(PREVIEW_ENGINEER_SELECTOR) -o jsonpath='{.items[0].status.hostIP}'):9850}; \
	echo "engineer: $$engineer"; \
	GT7_DATA_DIR=.preview/data GT7_ENGINEER_URL=$$engineer \
		$(PY) -m those_who_run pitwall --address 0.0.0.0 --static web/dist

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
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build \
		web/node_modules web/dist web/test-results .preview
	find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
