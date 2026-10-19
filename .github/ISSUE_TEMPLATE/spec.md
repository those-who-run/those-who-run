---
name: Spec
about: A feature or change, written so a person or an agent can build it (see docs/ISSUE_FORMAT.md)
labels: ["needs triage"]
---

## Summary
<!-- One or two sentences: what changes for the driver. -->

## Why
<!-- The problem or the value. Set the milestone and one `stream:` label on the issue (see ROADMAP.md). -->

## Evidence
<!-- What recordings show, with outing/fixture names, dates and numbers. Prefix anything unchecked with **Unverified:** -->

## Requirements
- **R1 (MUST)**
- **R2 (SHOULD)**

## Out of scope
-

## Interfaces
<!-- What this adds or changes that other issues may also touch: events, tables and columns, config keys, CLI commands, /healthz or metric fields. Write "none" if none. -->
-

## Approach
<!-- Suggested design: modules, signals, thresholds, data flow. Advice, not a contract. -->

## Acceptance criteria
- [ ] AC1 … (pinned by `tests/fixtures/…`)

## Definition of done
- [ ] Tests for every acceptance criterion, in a named file: `tests/test_….py`
- [ ] Any new fixture is in `tests/fixtures/` and in the fixture index
- [ ] README tables updated (rules, config, metrics, `/healthz`) where they changed
- [ ] `make check` is green
- [ ] The issue has a `stream:` label and a milestone

## Fixtures
- **Have:**
- **Need:**

## Dependencies
- **Blocked by:**
- **Blocks:**

## Open questions
-

## References
-

**Size:** S | M | L
