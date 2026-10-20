@AGENTS.md

## Claude Code

The rules are in `AGENTS.md` above; these notes are only for Claude Code.

- Run `make web-check` from the repository root, not `npm` scripts one by one,
  before saying the work is done; `make check` before opening the PR.
- When a Playwright test fails, read its screenshot and trace in
  `test-results/` before changing the test.
- Python rules are in the root `CLAUDE.md`; keep them out of web work.
