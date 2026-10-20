"""What a release changes in the places that need a human look (#357).

    python scripts/release_digest.py v0.7.4..main     the digest, as Markdown
    python scripts/release_digest.py                  from the last release tag
                                                      (not an -rc) to HEAD
    ... --github-output                               also `needs_look=true|false`
                                                      in $GITHUB_OUTPUT

Lists, from git history only, for the release PR's comment (release-please.yml):

- new direct dependencies (names, not versions) in pyproject.toml and
  web/package.json;
- changed files in the watched places: workflows, agent policy, the image's build,
  release config and scripts, the lockfiles and toolchain versions, CODEOWNERS and
  tests/conftest.py (WATCHED);
- weakened tests, as scripts/test_guard.py sees them (#358): test files deleted,
  tests removed, skips and expected failures added, the coverage floor lowered,
  the bundle budget raised;
- any change to the coverage floor or the bundle budget;

each with the PRs that made it, from the commit subjects' `(#N)`. It runs no code
from the history it reads; standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dependencies  # noqa: E402
import test_guard  # noqa: E402

MARKER = "<!-- release-digest -->"

# Paths whose every change is listed: a directory ends in `/`.
WATCHED = (
    ".github/",
    ".claude/",
    "CLAUDE.md",
    "web/CLAUDE.md",
    "AGENTS.md",
    "Dockerfile",
    ".dockerignore",
    "Makefile",
    "release-please-config.json",
    ".release-please-manifest.json",
    ".pre-commit-config.yaml",
    "scripts/",
    "web/.npmrc",
    # Dependencies and toolchains: new transitive packages appear only in the locks.
    "uv.lock",
    "web/package-lock.json",
    ".python-version",
    "web/.node-version",
    "docs/dependencies.md",
    # Who reviews what, and the test session's own switches.
    "CODEOWNERS",
    "docs/CODEOWNERS",
    "tests/conftest.py",
)
MANIFESTS = {"python": "pyproject.toml", "npm": "web/package.json"}
_PR = re.compile(r"\(#(\d+)\)\s*$")


def _git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _show(ref: str, path: str, cwd: str | None) -> str:
    try:
        return _git("show", f"{ref}:{path}", cwd=cwd)
    except subprocess.CalledProcessError:
        return ""


def _deps(ecosystem: str, text: str) -> dict[str, str]:
    if not text:
        return {}
    if ecosystem == "python":
        return dependencies.python_dependencies(text)
    return dependencies.npm_dependencies(text)


def code(text: str) -> str:
    """`text` as a Markdown code span that it cannot close: a backtick becomes `'`.
    Inside the span, `@name` pings nobody and `[x](url)` is no link."""
    return "`" + text.replace("`", "'") + "`"


def _prs(subjects: list[str]) -> list[str]:
    """`#N` for each subject that names its PR, in order, once each; the short
    subject itself, as code, for one that doesn't (a direct push)."""
    out: list[str] = []
    for subject in subjects:
        m = _PR.search(subject)
        ref = f"#{m.group(1)}" if m else code(subject[:60])
        if ref not in out:
            out.append(ref)
    return out


def _subjects(rev_range: str, path: str, cwd: str | None, *extra: str) -> list[str]:
    log = _git("log", "--reverse", "--format=%s", *extra, rev_range, "--", path, cwd=cwd)
    return log.splitlines()


@dataclass
class Digest:
    since: str
    until: str
    new_dependencies: list[tuple[str, list[str]]] = field(default_factory=list)
    watched: list[tuple[str, list[str]]] = field(default_factory=list)
    weakened: list[tuple[str, list[str]]] = field(default_factory=list)
    limits: list[tuple[str, list[str]]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.new_dependencies or self.watched or self.weakened or self.limits)


def _watched(path: str) -> bool:
    return any(path.startswith(w) if w.endswith("/") else path == w for w in WATCHED)


def digest(rev_range: str, cwd: str | None = None) -> Digest:
    since, until = rev_range.split("..", 1)
    until = until or "HEAD"
    out = Digest(since, until)

    # New names, each credited to the commit that added it.
    for ecosystem, manifest in MANIFESTS.items():
        before = _deps(ecosystem, _show(since, manifest, cwd))
        after = _deps(ecosystem, _show(until, manifest, cwd))
        new = sorted(set(after) - set(before))
        if not new:
            continue
        commits = _git("rev-list", "--reverse", rev_range, "--", manifest, cwd=cwd).split()
        credited: dict[str, list[str]] = {name: [] for name in new}
        for commit in commits:
            had = _deps(ecosystem, _show(f"{commit}^", manifest, cwd))
            has = _deps(ecosystem, _show(commit, manifest, cwd))
            subject = _git("log", "-1", "--format=%s", commit, cwd=cwd).strip()
            for name in set(has) - set(had):
                if name in credited:
                    credited[name].append(subject)
        for name in new:
            label = f"{code(name)} ({manifest}, {after[name]})"
            out.new_dependencies.append((label, _prs(credited[name])))

    for row in _git("diff", "--name-status", "-M", rev_range, cwd=cwd).splitlines():
        status, *paths = row.split("\t")
        path = paths[-1]
        if _watched(path) or (len(paths) > 1 and _watched(paths[0])):
            shown = " -> ".join(code(p) for p in paths)
            subjects = _subjects(rev_range, path, cwd)
            out.watched.append((f"{status[0]} {shown}", _prs(subjects)))

    found, _ = test_guard.weakenings(since, until, cwd=cwd)
    for finding in found:
        pickaxe = []
        if finding.what.startswith(("skip or expected failure added: ", "test removed: ")):
            pickaxe = ["-S", finding.what.split(": ", 1)[1]]
        elif finding.what == "test file deleted":
            pickaxe = ["--diff-filter=D"]
        subjects = _subjects(rev_range, finding.path, cwd, *pickaxe)
        out.weakened.append((f"{code(finding.path)}: {finding.what}", _prs(subjects)))

    old_floor = test_guard._coverage(_show(since, test_guard.PYPROJECT, cwd)).floor
    new_floor = test_guard._coverage(_show(until, test_guard.PYPROJECT, cwd)).floor
    if old_floor != new_floor:
        subjects = _subjects(rev_range, test_guard.PYPROJECT, cwd, "-G", "fail_under")
        out.limits.append(
            (f"coverage floor `fail_under`: {old_floor} -> {new_floor}", _prs(subjects))
        )
    old_budget = test_guard._numbers(_show(since, test_guard.BUDGET, cwd) or None)
    new_budget = test_guard._numbers(_show(until, test_guard.BUDGET, cwd) or None)
    if old_budget != new_budget:
        changes = [
            f"{k} {old_budget.get(k)} -> {new_budget.get(k)}"
            for k in sorted(set(old_budget) | set(new_budget))
            if old_budget.get(k) != new_budget.get(k)
        ]
        subjects = _subjects(rev_range, test_guard.BUDGET, cwd)
        out.limits.append((f"bundle budget: {', '.join(changes)}", _prs(subjects)))
    return out


def markdown(d: Digest) -> str:
    lines = [
        MARKER,
        "### Before you merge: what needs a look",
        "",
        f"Changes from {code(d.since)} to {code(d.until)} in the places a release should "
        "not ship unread (`scripts/release_digest.py`, #357). This comment is updated "
        "on every push to `main`.",
        "",
    ]
    if d.empty:
        return "\n".join(
            [
                *lines,
                "Nothing in the watched places changed. Approve and merge it once CI "
                "passes; merging by hand is what ships it (#394).",
                "",
            ]
        )
    lines += [
        "**Read the list below before you merge.** Merging by hand is what ships it (#394).",
        "",
    ]
    sections = (
        ("New direct dependencies", d.new_dependencies),
        ("Workflows, agent policy, build and release files", d.watched),
        ("Tests weakened", d.weakened),
        ("Coverage floor and bundle budget", d.limits),
    )
    for title, items in sections:
        if not items:
            continue
        lines += [f"**{title}**", ""]
        lines += [f"- {what} ({', '.join(prs) or 'no PR found'})" for what, prs in items]
        lines += [""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "range", nargs="?", help="<tag>..<ref>; default: the last release tag..HEAD"
    )
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="also write needs_look=true|false to the file $GITHUB_OUTPUT names",
    )
    args = parser.parse_args(argv)
    rev_range = args.range
    if not rev_range:
        # A release candidate (v0.8.0-rc1) is not a release: the digest covers
        # everything since the last real one.
        tag = _git(
            "describe", "--tags", "--abbrev=0", "--match", "v*", "--exclude", "*-rc*", "HEAD"
        ).strip()
        rev_range = f"{tag}..HEAD"
    if ".." not in rev_range or "..." in rev_range:
        parser.error("the range is <from>..<to>, e.g. v0.7.4..main")
    d = digest(rev_range)
    print(markdown(d), end="")
    if args.github_output:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"needs_look={'false' if d.empty else 'true'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
