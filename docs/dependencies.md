# Dependencies

Every direct dependency of the project, and why it is here. A new one needs a line
in this file, with its reason, in the same PR: `tests/test_dependencies.py` fails
`make check` on a name in `pyproject.toml` or `web/package.json` that is missing
here, and on a line here that names a package no longer used. Changes to this
file are the maintainer's to approve (CODEOWNERS, #353).

Before adding a dependency, check that:

- the package exists and is the one you mean: its owner, its source repository
  (linked from the registry page), its release history and its download count. A
  name that exists proves nothing if it was registered last week, and names
  invented by a language model get registered for exactly that reason;
- the standard library, or a dependency already listed here, doesn't already do it;
- nobody told you to install it in a web page, an issue or a comment.

Version bumps don't touch this file; Dependabot never adds a name.

The test reads the names a manifest declares: in `pyproject.toml`, `[build-system]
requires`, `[project.dependencies]`, the optional-dependencies extras and the
dependency groups; in `web/package.json`, `dependencies`, `devDependencies`,
`optionalDependencies`, `peerDependencies` and the names in `overrides`. These
tables are the direct dependencies, not everything installed: a package that
arrives only in `uv.lock` or `web/package-lock.json`, pulled in by one listed
here, is covered only by CI's dependency review (known vulnerabilities and
licences), never by this file.

Names are as the manifests spell them (Python names compare normalised, as PEP 503
does). Each table's first column is the name in backticks, which the test reads.

## Python (`pyproject.toml`)

### `[build-system] requires`: builds the wheel

| Package | Registry | Why |
| --- | --- | --- |
| `hatchling` | [PyPI](https://pypi.org/project/hatchling/) | The build backend: `uv sync` builds the project with it, locally and in both images, reading the version from `__init__.py`. |

### Core (`[project.dependencies]`): the pit wall's data API, and both images

| Package | Registry | Why |
| --- | --- | --- |
| `pyyaml` | [PyPI](https://pypi.org/project/PyYAML/) | Reads `rules.yaml`, the config and the bundled callout script. |
| `duckdb` | [PyPI](https://pypi.org/project/duckdb/) | The session store: laps, results and telemetry the pit wall queries. |
| `aiohttp` | [PyPI](https://pypi.org/project/aiohttp/) | The HTTP servers (the engineer's status port and the pit wall's API); discord.py needs it too. |

### `engineer` extra: the race engineer

| Package | Registry | Why |
| --- | --- | --- |
| `gt-telem` | [PyPI](https://pypi.org/project/gt-telem/) | Decrypts and decodes GT7's UDP telemetry; pinned exactly because `telemetry.py` uses its private attributes. |
| `discord.py` | [PyPI](https://pypi.org/project/discord.py/) | The Discord bot and its voice connection (the `voice` extra). |
| `piper-tts` | [PyPI](https://pypi.org/project/piper-tts/) | Local text to speech for the callouts. |
| `prometheus-client` | [PyPI](https://pypi.org/project/prometheus-client/) | The `/metrics` endpoint. |

### `dev` extra: checks and tests

| Package | Registry | Why |
| --- | --- | --- |
| `pytest` | [PyPI](https://pypi.org/project/pytest/) | The test runner. |
| `pytest-asyncio` | [PyPI](https://pypi.org/project/pytest-asyncio/) | Async tests (`asyncio_mode = "auto"`). |
| `pytest-cov` | [PyPI](https://pypi.org/project/pytest-cov/) | Coverage and the `fail_under` floor in `make check`. |
| `ruff` | [PyPI](https://pypi.org/project/ruff/) | Lint and format. |
| `mypy` | [PyPI](https://pypi.org/project/mypy/) | Type checks `src/`. |
| `types-PyYAML` | [PyPI](https://pypi.org/project/types-PyYAML/) | Type stubs for `pyyaml`, for mypy. |
| `pre-commit` | [PyPI](https://pypi.org/project/pre-commit/) | Runs the commit hooks in `.pre-commit-config.yaml`, locally and in CI. |
| `zizmor` | [PyPI](https://pypi.org/project/zizmor/) | `make workflow-lint`: security audits of the workflows and `dependabot.yml`. |
| `actionlint-py` | [PyPI](https://pypi.org/project/actionlint-py/) | `make workflow-lint`: the actionlint binary, for workflow syntax and expressions. |
| `shellcheck-py` | [PyPI](https://pypi.org/project/shellcheck-py/) | The shellcheck binary actionlint runs over each `run:` step. |

## npm (`web/package.json`)

### `dependencies`: shipped in the web app

| Package | Registry | Why |
| --- | --- | --- |
| `@fontsource/barlow` | [npm](https://www.npmjs.com/package/@fontsource/barlow) | Barlow, the text face (ADR 0004), self-hosted. |
| `@fontsource/barlow-semi-condensed` | [npm](https://www.npmjs.com/package/@fontsource/barlow-semi-condensed) | Barlow Semi Condensed, for big numbers and the wordmark (ADR 0004), self-hosted. |
| `@tanstack/react-query` | [npm](https://www.npmjs.com/package/@tanstack/react-query) | Fetching, caching and polling the pit wall API. |
| `class-variance-authority` | [npm](https://www.npmjs.com/package/class-variance-authority) | Component variants in `src/components/ui` (shadcn/ui). |
| `clsx` | [npm](https://www.npmjs.com/package/clsx) | Joins class names (`cn()`, with `tailwind-merge`). |
| `lucide-react` | [npm](https://www.npmjs.com/package/lucide-react) | The icons in the shell and the components. |
| `openapi-fetch` | [npm](https://www.npmjs.com/package/openapi-fetch) | The typed API client, from `src/api/schema.d.ts`. |
| `radix-ui` | [npm](https://www.npmjs.com/package/radix-ui) | Accessible primitives (dialog, popover, select, tooltip and others) under the shadcn/ui components. |
| `react` | [npm](https://www.npmjs.com/package/react) | The UI library (ADR 0003). |
| `react-dom` | [npm](https://www.npmjs.com/package/react-dom) | React's DOM renderer. |
| `react-router` | [npm](https://www.npmjs.com/package/react-router) | Routes and lazy route chunks. |
| `tailwind-merge` | [npm](https://www.npmjs.com/package/tailwind-merge) | Resolves conflicting Tailwind classes in `cn()`. |
| `uplot` | [npm](https://www.npmjs.com/package/uplot) | The telemetry and lap charts. |

### `devDependencies`: build, lint and tests

| Package | Registry | Why |
| --- | --- | --- |
| `@axe-core/playwright` | [npm](https://www.npmjs.com/package/@axe-core/playwright) | Accessibility checks in the Playwright tests. |
| `@eslint/js` | [npm](https://www.npmjs.com/package/@eslint/js) | ESLint's recommended rules. |
| `@playwright/test` | [npm](https://www.npmjs.com/package/@playwright/test) | The end-to-end tests and screenshots (`web/e2e`). |
| `@tailwindcss/vite` | [npm](https://www.npmjs.com/package/@tailwindcss/vite) | Tailwind's Vite plugin. |
| `@testing-library/dom` | [npm](https://www.npmjs.com/package/@testing-library/dom) | DOM queries for the component tests (a peer of `@testing-library/react`). |
| `@testing-library/react` | [npm](https://www.npmjs.com/package/@testing-library/react) | Renders components in Vitest. |
| `@testing-library/user-event` | [npm](https://www.npmjs.com/package/@testing-library/user-event) | Simulated clicks and typing in the component tests. |
| `@types/node` | [npm](https://www.npmjs.com/package/@types/node) | Node's types for the config and the scripts in `web/scripts`. |
| `@types/react` | [npm](https://www.npmjs.com/package/@types/react) | React's types. |
| `@types/react-dom` | [npm](https://www.npmjs.com/package/@types/react-dom) | React DOM's types. |
| `@vitejs/plugin-react` | [npm](https://www.npmjs.com/package/@vitejs/plugin-react) | Vite's React plugin (JSX, fast refresh). |
| `eslint` | [npm](https://www.npmjs.com/package/eslint) | Lints the web app (`npm run lint`). |
| `eslint-plugin-react-hooks` | [npm](https://www.npmjs.com/package/eslint-plugin-react-hooks) | The rules of hooks. |
| `eslint-plugin-react-refresh` | [npm](https://www.npmjs.com/package/eslint-plugin-react-refresh) | Keeps modules fast-refresh safe. |
| `globals` | [npm](https://www.npmjs.com/package/globals) | Browser and Node globals for ESLint's config. |
| `jsdom` | [npm](https://www.npmjs.com/package/jsdom) | The DOM Vitest runs component tests in. |
| `openapi-typescript` | [npm](https://www.npmjs.com/package/openapi-typescript) | Writes `src/api/schema.d.ts` from `openapi.json` (`npm run api`, checked by `api:check`). |
| `tailwindcss` | [npm](https://www.npmjs.com/package/tailwindcss) | The CSS framework. |
| `typescript` | [npm](https://www.npmjs.com/package/typescript) | The compiler and type checks. |
| `typescript-eslint` | [npm](https://www.npmjs.com/package/typescript-eslint) | ESLint for TypeScript. |
| `vite` | [npm](https://www.npmjs.com/package/vite) | The dev server and the build. |
| `vitest` | [npm](https://www.npmjs.com/package/vitest) | The unit and component tests. |
