IMAGE_NAME := muldoon/those-who-run
PLATFORM   := linux/amd64
VERSION    ?= dev
VOICE      := en_GB-alba-medium
VOICE_URL  := https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alba/medium
PY         ?= .venv/bin/python

.PHONY: help venv lock voice lint fmt typecheck test openapi brand-css wordmark check build build-pitwall replay web-build web-dev web-check web-preview archive-push archive-pull clean

help:
	@echo "help     - this list"
	@echo "venv     - create .venv from uv.lock with the dev and engineer extras (needs uv)"
	@echo "lock     - re-resolve uv.lock after changing dependencies in pyproject.toml"
	@echo "voice    - download the Piper voice into ./voices"
	@echo "lint     - ruff check + format check"
	@echo "fmt      - ruff format"
	@echo "typecheck - mypy on src/"
	@echo "test     - pytest"
	@echo "openapi  - write web/openapi.json, the pit wall API's schema, from its models"
	@echo "brand-css - write web/src/styles/brand.css, the web app's brand colours, from brand.py"
	@echo "wordmark - redraw the wordmark and icons as outlines: make wordmark NOTO=<NotoSansCJK-VF.ttc>"
	@echo "check    - everything a PR must pass: lint, typecheck, tests with coverage floor, web-check (CI runs this)"
	@echo "build    - podman build $(IMAGE_NAME):$(VERSION) for $(PLATFORM)"
	@echo "build-pitwall - podman build the slim pit wall image, $(IMAGE_NAME):$(VERSION)-pitwall"
	@echo "replay   - replay FILE=recording.jsonl"
	@echo "web-build - build the React pit wall into web/dist (needs Node, web/.node-version)"
	@echo "web-dev  - Vite's dev server on http://localhost:5173, /api proxied to a local pitwall"
	@echo "web-check - ESLint, tsc, Vitest, the client and brand.css freshness checks, the bundle budget, Playwright"
	@echo "web-preview - web/dist over a read-only copy of a deployed store, on http://<laptop>:9852 (PREVIEW_CONTEXT=<kube context>)"
	@echo "archive-push - upload GT7_ARCHIVE_DIR to the outings release of $(ARCHIVE_REPO) (ADR 0002)"
	@echo "archive-pull - download the outings release of $(ARCHIVE_REPO) into GT7_ARCHIVE_DIR"
	@echo "clean    - remove .venv, caches, coverage and build output"

# Python version from .python-version, packages from uv.lock: the same set CI and
# the image install.
venv:
	uv sync --frozen --extra dev --extra engineer

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

brand-css:
	$(PY) scripts/brand_css.py

# The wordmark and icons (scripts/wordmark.py): outlines of Noto Sans CJK JP and
# Barlow Semi Condensed (SIL OFL 1.1), then the PNG icons from them. fontTools is
# not a project dependency: uvx brings a pinned one. The PNGs need ImageMagick.
NOTO      ?=
FONTTOOLS := fonttools==4.66.1
BARLOW_SC := web/node_modules/@fontsource/barlow-semi-condensed/files/barlow-semi-condensed-latin-700-normal.woff2

wordmark: $(WEB_DEPS)
	@test -n "$(NOTO)" && test -f "$(NOTO)" || { echo "NOTO must name Noto Sans CJK's NotoSansCJK-VF.ttc (Fedora: google-noto-sans-cjk-vf-fonts; or https://github.com/notofonts/noto-cjk), e.g. make wordmark NOTO=/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc" >&2; exit 1; }
	@command -v magick >/dev/null 2>&1 || { echo "ImageMagick (magick) is missing: it renders the PNG icons" >&2; exit 1; }
	uvx --with $(FONTTOOLS) --with brotli==1.2.0 python scripts/wordmark.py "$(NOTO)" $(BARLOW_SC)
	magick -background none web/src/assets/icon.svg -resize 192x192 -strip web/public/icon-192.png
	magick -background none web/src/assets/icon.svg -strip web/public/icon-512.png
	magick -background none web/src/assets/icon-maskable.svg -strip web/public/icon-maskable-512.png
	magick -background none web/src/assets/icon.svg -resize 180x180 -strip web/public/apple-touch-icon.png

# The definition of green: CI runs exactly this. The coverage floor lives in
# pyproject.toml ([tool.coverage.report] fail_under); a skipped test fails the run;
# uv.lock must match pyproject.toml; web/openapi.json must match the API's models;
# and the web app passes web-check (brand.css matching brand.py among it), which
# fails when Node or the browser is missing.
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
	$(PY) scripts/brand_css.py --check
	cd web && npm run lint
	cd web && npm run typecheck
	cd web && npm run api:check
	cd web && npm test
	cd web && npx vite build
	cd web && npm run budget
	cd web && TWR=$(TWR) npx playwright test

# The pit wall on the phone and iPad from a laptop: web/dist over a copy of a
# deployed store, taken read-only from the pit wall pod in a Kubernetes cluster
# (tar out of /data; nothing is written there). Open http://<this laptop>:9852 on
# the same network. PREVIEW_CONTEXT, the kube context, has no default:
# `make web-preview PREVIEW_CONTEXT=<context>`. /api/engine/* goes to the
# engineer's read-only port on the node it runs on (its hostPort, ADR 0001
# point 3), so the live status is live; set PREVIEW_ENGINEER to point it elsewhere.
PREVIEW_CONTEXT ?=
PREVIEW_POD     ?= deploy/those-who-run-pitwall
PREVIEW_ENGINEER_SELECTOR ?= app.kubernetes.io/name=those-who-run

web-preview: web-build
	@test -n "$(PREVIEW_CONTEXT)" || { echo "web-preview: set PREVIEW_CONTEXT to the kube context the pit wall runs in, e.g. make web-preview PREVIEW_CONTEXT=my-cluster" >&2; exit 2; }
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
# the directory, these mirror it to and from the `outings` release of
# those-who-run/outings.
ARCHIVE ?= $(or $(GT7_ARCHIVE_DIR),$(HOME)/.cache/those-who-run/outings)
ARCHIVE_REPO ?= those-who-run/outings

archive-push:
	gh release view outings -R $(ARCHIVE_REPO) >/dev/null 2>&1 || gh release create outings -R $(ARCHIVE_REPO) --prerelease \
		--title "Outing archive" \
		--notes "Outings specs and tests rely on: <id>.jsonl.gz and its <id>.json sidecar. See docs/adr/0002-outing-archive.md in those-who-run/those-who-run."
	gh release upload outings -R $(ARCHIVE_REPO) $(ARCHIVE)/*.jsonl.gz $(ARCHIVE)/*.json --clobber

archive-pull:
	mkdir -p $(ARCHIVE)
	gh release download outings -R $(ARCHIVE_REPO) -D $(ARCHIVE) --skip-existing

clean:
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build \
		web/node_modules web/dist web/test-results .preview
	find . -name __pycache__ -type d -not -path './.git/*' -prune -exec rm -rf {} +
