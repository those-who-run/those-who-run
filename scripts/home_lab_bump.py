"""Bump those-who-run's tags in home-lab's kustomization to a release (#238 R3).

    python3 scripts/home_lab_bump.py 0.7.4 kustomization.yaml [name in errors]

The release workflow's ``home-lab`` job runs this on the file it fetched from
home-lab. It accepts two shapes, so it works before and after home-lab's switch to
the React pit wall:

- one ``newTag`` line, ``x.y.z``: one image for the engineer and the pit wall;
- two, ``x.y.z`` and ``x.y.z-pitwall`` with the same ``x.y.z``: the engineer's
  image and the pit wall's.

Anything else fails (exit 1, with a ``::error::`` line). When home-lab is behind the
release it rewrites the file in place; when it is at the release or newer it leaves
the file alone. Either way it prints ``bump=`` (true or false), ``old=`` (the
``x.y.z`` home-lab is at), ``pitwall=`` (true when there is a ``-pitwall`` tag,
whose image the job must find on Docker Hub before it opens the PR) and
``changed=`` (the lines it changed, in Markdown, for the PR body). Standard
library only: the job runs it with the runner's python3, no venv.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass

SUFFIX = "-pitwall"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_NEWTAG = re.compile(r"^(?P<key>\s*newTag:\s*)(?P<tag>\S*)\s*$")
# Any newTag key, so one the line above can't read (`- newTag:`, a trailing comment)
# fails instead of being missed. Comments that mention newTag don't count.
_ANY_NEWTAG = re.compile(r"^\s*(-\s*)?newTag\s*:")


@dataclass(frozen=True)
class Bump:
    bump: bool
    old: str
    pitwall: bool
    changed: str
    text: str


def _semver(tag: str) -> tuple[int, int, int] | None:
    m = _SEMVER.match(tag)
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def plan(text: str, version: str) -> Bump:
    """The bump of ``text`` to ``version``, or ValueError when the shape is not one of the two."""
    new = _semver(version)
    if new is None:
        raise ValueError(f"{version} is not x.y.z")
    lines = text.splitlines(keepends=True)
    found = [(i, m) for i, line in enumerate(lines) if (m := _NEWTAG.match(line.rstrip("\r\n")))]
    if sum(bool(_ANY_NEWTAG.match(line)) for line in lines) != len(found):
        raise ValueError("a newTag line is not `newTag: <tag>`")
    tags = [m["tag"] for _, m in found]
    old = tags[0].removesuffix(SUFFIX) if tags else ""
    current = _semver(old)
    if current is None or sorted(tags) not in ([old], [old, old + SUFFIX]):
        raise ValueError(
            f"expected one newTag x.y.z, or two, x.y.z and x.y.z{SUFFIX}; found "
            + (", ".join(tags) if tags else "none")
        )
    suffixes = [tag.removeprefix(old) for tag in tags]
    pitwall = SUFFIX in suffixes
    if current >= new:
        return Bump(False, old, pitwall, "", text)
    changes = []
    for (i, m), suffix in zip(found, suffixes, strict=True):
        eol = lines[i][len(lines[i].rstrip("\r\n")) :]
        lines[i] = f"{m['key']}{version}{suffix}{eol}"
        changes.append(f"`newTag: {old}{suffix}` to `newTag: {version}{suffix}`")
    return Bump(True, old, pitwall, " and ".join(changes), "".join(lines))


def main(argv: list[str]) -> int:
    if len(argv) not in (2, 3):
        print(__doc__, file=sys.stderr)
        return 2
    version, path, *name = argv
    with open(path, encoding="utf-8", newline="") as fh:
        text = fh.read()
    try:
        result = plan(text, version)
    except ValueError as exc:
        print(f"::error::{name[0] if name else path}: {exc}")
        return 1
    if result.bump:
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(result.text)
    print(f"bump={str(result.bump).lower()}")
    print(f"old={result.old}")
    print(f"pitwall={str(result.pitwall).lower()}")
    print(f"changed={result.changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
