# 0002: Where the outing archive lives

**Status:** Accepted, 2026-10-17. Asked for by #197 (its Open question, and the
roadmap's open decision).

## Context

The NUC keeps the newest 20 outings (`GT7_RECORD_KEEP`), yet the open specs
cite outings by id as evidence. On 2026-10-17 the open issues cited 14 outing
ids, plus two session ids. Four of the outings were already gone. The other
ten were 79 MB of `.jsonl.gz` between them. The biggest was `20261017-162118`, a 12-lap race at 21 MB. A
60 Hz outing grows at about 20 MB an hour. Specs that need full-rate data
(#15, #65, #97, #98, #131) will keep adding them.

The archive has to:

- keep outings off the NUC, so a pruned recording or a lost disk does not take
  the evidence with it;
- be reachable from a laptop and from CI, so a test can fetch the outing it
  needs;
- stay private, like the repository;
- keep large files out of every clone and build context (#167's concern).

The four options in #197:

| Option | Off the NUC | Laptop and CI | Private | Clones stay small | Cost |
|---|---|---|---|---|---|
| Git LFS in this repo | yes | yes | yes | yes, if LFS objects are fetched lazily | a small free quota for storage and downloads; CI runs that fetched outings would use it up |
| Release assets on this repo | yes | yes (`gh release download`) | yes, with the repo | yes | none: assets up to 2 GB each, no bandwidth quota |
| The NAS | yes, but in the same house | laptop only: CI can't reach the home lab (ADR 0001, point 3) | yes | yes | a share, credentials on every machine |
| An S3-compatible bucket in the home lab | same as the NAS | same as the NAS | yes | yes | another service to run and back up |

## Decision

### 1. The archive is the `outings` release of this repository

- A pre-release with the tag `outings`. It never matches `v*`, so the release
  workflow does not run for it (releases are tagged `vX.Y.Z`).
- Each outing is two assets: `<id>.jsonl.gz`, the outing exactly as the NUC
  recorded it (the same bytes; the sidecar has its sha256), and `<id>.json`,
  the sidecar. The sidecar gives the track, car and session kinds, one
  `recordings` line per session, the frame count, the size, a note on what the
  outing shows, and the issues that cite it.
- An outing is never removed from the archive. Archiving it again replaces the
  sidecar, adds issues and keeps the note unless a new one is given.

### 2. A directory is the working copy

- `those-who-run recordings archive <outing> --note "…" --issue N` copies an
  outing (an id in `GT7_RECORD_DIR`, or a path) into `GT7_ARCHIVE_DIR`
  (default `~/.cache/those-who-run/outings`) and writes the sidecar. With no
  outing it lists the archive. It only needs a directory, as #197 asks.
- `make archive-push` uploads the directory to the release (creating it the
  first time); `make archive-pull` downloads what is missing. Both use `gh`,
  logged in as someone who can read the repository.
- On the NUC, copy outings out with `kubectl cp` and archive them from a
  laptop. Nothing in the cluster talks to GitHub.

### 3. Tests fetch by id

- `tests/archive.py`'s `archived_outing(id)` returns the local copy, fetching it
  from the release with `gh` the first time and checking it against the
  sidecar's sha256. When it can't, it skips the test with the reason.
- `make check` fails on any skip (#161). So the first test that needs an
  archived outing also gives the CI job `GH_TOKEN` (`contents: read`) and
  caches `GT7_ARCHIVE_DIR`. Until then, nothing in the suite fetches.
- Fixtures stay in `tests/fixtures`, thinned, gzipped and indexed (#167). An
  archived outing is the raw source a fixture is cut from (`thin --window` for
  full-rate cuts); the index's `outings` section lists every archived outing,
  and a fixture's `outing` must be one of them.

### 4. Specs cite the archive id

An outing id in an issue is the archive id: the same `YYYYMMDD-HHMMSS`. A spec
that relies on an outing archives it first, and its Evidence or Fixtures say
"archived" next to the id (`docs/ISSUE_FORMAT.md`).

Why: release assets are the one option that CI and a laptop can both reach,
that stays private with the repository, and that costs nothing to download.
LFS would do the same job, but its free download allowance would run out
quickly once CI fetched outings. The NAS and a bucket keep the data
in the same house as the NUC, and CI can't reach them.

Settles: #197's Open question, the roadmap's open decision.

## Consequences

- The archive holds 10 outings (79 MB) from 2026-10-16 and 2026-10-17, listed
  in `tests/fixtures/FIXTURES.yaml` under `outings`. Four ids the specs cite
  were already pruned. They are listed under `lost`, with what survives of
  them in `/data/sessions`.
- Raising `GT7_RECORD_KEEP` on the NUC is still worth doing (#197's second
  question). The recordings directory held 88 MB for 20 outings. The
  `local-path` volume does not enforce its 1 GiB request, and the node had
  132 GB free.
- If the repository goes public, the archive goes public with it, the same as
  the fixtures. The recordings hold telemetry only: car, track, speeds and
  positions on the track, no account or network details.
- Moving the archive later means one new ADR, a `make archive-pull` and an
  upload to the new place. The ids, sidecars and index stay the same.

## References

- GitHub, "About releases": release assets up to 2 GiB each, no bandwidth limit.
  https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases
- GitHub, "About billing for Git Large File Storage".
  https://docs.github.com/en/billing/managing-billing-for-git-large-file-storage/about-billing-for-git-large-file-storage
