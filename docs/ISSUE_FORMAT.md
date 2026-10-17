# Issue format

Every issue is a spec: a person or an agent should be able to pick it up and
build it without asking around first. The template is
`.github/ISSUE_TEMPLATE/spec.md`; this page says what goes in each section.

## Rules

- **Evidence over assumption.** GT7 sends no mode, no wear, no flags; what it
  does send is learned from recordings. Every claim about telemetry names the
  recording it came from (outing file name or fixture, and date) and the
  numbers seen. Anything not checked against a recording says
  **Unverified:** in front of it.
- **Recordings are pruned.** The NUC keeps the newest 20 outings. Copy a
  recording the issue relies on into `tests/fixtures/` with `thin` (or note it
  is needed) before it goes.
- **Requirements are numbered** (R1, R2, …) and say MUST or SHOULD. Acceptance
  criteria are checkboxes, each one testable, and say which fixture pins it
  (README principle 5: a behaviour ships with a fixture from a real drive).
- **Approach is advice, not a contract.** It names the modules and signals to
  start from; the implementer may do better and says so in the PR.
- **One issue, one deliverable.** Split anything that needs two PRs.
- Keep **Dependencies** in both directions current, so the order of work can
  be read straight from the issues.
- **Shared decisions go in an ADR.** When more than one issue depends on the
  same decision, record it in `docs/adr/` (see its README) and link it from
  each issue, rather than deciding it in each.
- Size: **S** (an afternoon), **M** (a day or two), **L** (split it).

## Sections

| Section | What it holds |
|---|---|
| Summary | One or two sentences: what changes for the driver. |
| Why | The problem or the value, and where it sits in the roadmap. |
| Evidence | What the telemetry and recordings show, with numbers. Unknowns marked. |
| Requirements | R1… with MUST or SHOULD. Behaviour, not implementation. |
| Out of scope | What this issue deliberately leaves to other issues (linked). |
| Approach | Suggested design: modules, signals, thresholds, data flow. |
| Acceptance criteria | Checkboxes, each testable and tied to a fixture or a check. |
| Fixtures | Recordings the work has, and drives it still needs. |
| Dependencies | Blocked by and Blocks, as issue links. |
| Open questions | Decisions still to make, and who makes them. |
| References | Prior art, docs, related issues and PRs. |

Findings that arrive later (a new recording, a test that changed the
picture) go in a comment and are folded into the body, so the body is always
the current spec.
