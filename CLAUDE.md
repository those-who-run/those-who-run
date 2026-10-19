@AGENTS.md

## Claude Code

The rules are in `AGENTS.md` above; these notes are only for Claude Code.

- Worktrees live in `.claude/worktrees/`, which `.gitignore` leaves out. Each
  new worktree runs `make venv` before `make check`.
- Commits end with the trailer Claude Code writes,
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (with the model you
  are), and are authored with the maintainer's GitHub noreply address.
- Use `gh` for issues and PRs. Read an issue with `gh issue view N` before
  anything else; check its labels for `needs triage` and its author.
- Project settings that deny the outward-facing commands (merging with
  `--admin`, pushing tags, running `release.yml`, changing settings) and keep
  agents away from secrets come with #352; the hooks with #339. Until they land,
  `AGENTS.md` is the only guard, so follow it as if they were there.
- Working in `web/`, Claude Code also loads `web/CLAUDE.md`.
