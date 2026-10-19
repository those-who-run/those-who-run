"""Reports the ways a change can weaken the tests (#358).

    python scripts/test_guard.py <base> <head>            what <base>...<head> weakens
                                                           (fails if anything)
    python scripts/test_guard.py <base> <head> --pr <N>   fails unless PR N's body
                                                           says why, in a line
                                                           `Tests weakened: <reason>`

It reads git history only: the diff from the merge base of <base> and <head> to
<head>, and the files at both ends. Reported, and failing without the line:

- a test file deleted, or renamed to something that isn't a test file;
- a test function removed (Python `def test_...`, a TypeScript `test(`/`it(` title)
  that doesn't come back elsewhere in the change;
- a skip, an expected failure or a focused test added (SKIP_PATTERNS);
- `fail_under` lowered, `xfail_strict` turned off, a bundle budget raised, the
  TWR_FAIL_ON_SKIP switch or Playwright's `forbidOnly` edited.

Removed assertions are counted for the summary but never fail: refactors move them.
The PR body is fetched with gh when the script runs, never taken from the event
payload, so a re-run after editing the body sees the edit. Standard library only;
release_digest.py (#357) shares SKIP_PATTERNS and is_test_file.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter
from dataclasses import dataclass

# Lines that skip a test, expect it to fail, or run one test alone. Matched on the
# lines a change adds to a test file; a line moved unchanged doesn't count.
SKIP_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        r"pytest\.mark\.(skip|skipif|xfail)\b",
        r"\bpytest\.(skip|xfail)\(",
        r"\bimportorskip\(",
        r"\b(test|it|describe)\.(skip|fixme|only|todo)\b",
        r"\.todo\(",
    )
)

_WEB_TEST = re.compile(r"^web/.*\.(test|spec)\.tsx?$")
_PY_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(")
_TS_TEST_TITLE = re.compile(r"""^\s*(?:test|it)\(\s*(["'`])(.+?)\1""")
_ASSERTION = re.compile(r"^\s*(assert\b|await expect\(|expect\()")
_WEAKENED_LINE = re.compile(r"^\s*Tests weakened:(.*)$", re.MULTILINE)
MIN_REASON = 10

BUDGET = "web/bundle-budget.json"
PYPROJECT = "pyproject.toml"
# Files where any edit to the named switch is reported.
SWITCHES = {
    "Makefile": "TWR_FAIL_ON_SKIP",
    "tests/conftest.py": "TWR_FAIL_ON_SKIP",
    "web/playwright.config.ts": "forbidOnly",
}


def is_test_file(path: str) -> bool:
    return path.startswith("tests/") or bool(_WEB_TEST.match(path))


def skips_in(line: str) -> bool:
    return any(p.search(line) for p in SKIP_PATTERNS)


@dataclass(frozen=True)
class Finding:
    path: str
    what: str


def _git(*args: str, cwd: str | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def _show(ref: str, path: str, cwd: str | None) -> str | None:
    try:
        return _git("show", f"{ref}:{path}", cwd=cwd)
    except subprocess.CalledProcessError:
        return None


@dataclass
class Diff:
    """The lines a change adds and removes, per file, and the files it deletes."""

    added: dict[str, list[str]]
    removed: dict[str, list[str]]
    deleted: list[str]
    renamed: list[tuple[str, str]]


def read_diff(base: str, head: str, cwd: str | None = None) -> Diff:
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []
    for row in _git("diff", "--name-status", "-M", f"{base}...{head}", cwd=cwd).splitlines():
        status, *paths = row.split("\t")
        if status == "D":
            deleted.append(paths[0])
        elif status.startswith("R"):
            renamed.append((paths[0], paths[1]))
    old = new = ""
    in_header = False
    patch = _git("diff", "--unified=0", "-M", "--no-color", f"{base}...{head}", cwd=cwd)
    for line in patch.splitlines():
        # `--- ` and `+++ ` are file names only between `diff --git` and the first
        # hunk; inside a hunk they are a removed `-- ...` or an added `++ ...` line.
        if line.startswith("diff --git "):
            in_header, old, new = True, "", ""
        elif line.startswith("@@"):
            in_header = False
        elif in_header and line.startswith("--- "):
            old = line[6:] if line.startswith("--- a/") else ""
        elif in_header and line.startswith("+++ "):
            new = line[6:] if line.startswith("+++ b/") else ""
        elif in_header:
            continue
        elif line.startswith("+") and new:
            added.setdefault(new, []).append(line[1:])
        elif line.startswith("-") and old:
            removed.setdefault(old, []).append(line[1:])
    return Diff(added, removed, deleted, renamed)


def _test_names(lines: list[str]) -> list[str]:
    names = []
    for line in lines:
        if m := _PY_TEST_DEF.match(line):
            names.append(m.group(1))
        elif m := _TS_TEST_TITLE.match(line):
            names.append(m.group(2))
    return names


def _numbers(text: str | None) -> dict[str, float]:
    """The budget's limits, flattened: entry, route and routes/<path>."""
    if not text:
        return {}
    data = json.loads(text)
    out: dict[str, float] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update({f"{key}/{k}": v for k, v in value.items()})
        else:
            out[key] = value
    return out


def _coverage(text: str | None) -> tuple[float | None, object]:
    if not text:
        return None, None
    data = tomllib.loads(text)
    tool = data.get("tool", {})
    floor = tool.get("coverage", {}).get("report", {}).get("fail_under")
    strict = tool.get("pytest", {}).get("ini_options", {}).get("xfail_strict")
    return floor, strict


def weakenings(base: str, head: str, cwd: str | None = None) -> tuple[list[Finding], int]:
    """What <base>...<head> weakens, and how many assertions it removes on balance."""
    diff = read_diff(base, head, cwd)
    found: list[Finding] = []
    merge_base = _git("merge-base", base, head, cwd=cwd).strip()

    for path in diff.deleted:
        if is_test_file(path):
            found.append(Finding(path, "test file deleted"))
    for old, new in diff.renamed:
        if is_test_file(old) and not is_test_file(new):
            found.append(Finding(old, f"test file renamed to {new}, which is not a test file"))

    # Test functions: removed in one place and not added in another is a removal.
    added_names = Counter(
        n for path, lines in diff.added.items() if is_test_file(path) for n in _test_names(lines)
    )
    for path, lines in sorted(diff.removed.items()):
        if not is_test_file(path) or path in diff.deleted:
            continue
        for name in _test_names(lines):
            if added_names[name]:
                added_names[name] -= 1
            else:
                found.append(Finding(path, f"test removed: {name}"))

    # Skips: added lines that skip, less the same lines removed elsewhere (a move).
    removed_skips = Counter(
        line.strip()
        for path, lines in diff.removed.items()
        if is_test_file(path)
        for line in lines
        if skips_in(line)
    )
    for path, lines in sorted(diff.added.items()):
        if not is_test_file(path):
            continue
        for line in lines:
            if not skips_in(line):
                continue
            if removed_skips[line.strip()]:
                removed_skips[line.strip()] -= 1
            else:
                found.append(Finding(path, f"skip or expected failure added: {line.strip()}"))

    old_floor, old_strict = _coverage(_show(merge_base, PYPROJECT, cwd))
    new_floor, new_strict = _coverage(_show(head, PYPROJECT, cwd))
    if old_floor is not None and (new_floor is None or new_floor < old_floor):
        found.append(
            Finding(PYPROJECT, f"coverage floor lowered: fail_under {old_floor} -> {new_floor}")
        )
    if old_strict is True and new_strict is not True:
        found.append(Finding(PYPROJECT, f"xfail_strict turned off: {old_strict} -> {new_strict}"))

    old_budget = _numbers(_show(merge_base, BUDGET, cwd))
    new_budget = _numbers(_show(head, BUDGET, cwd))
    for key, limit in sorted(new_budget.items()):
        if key in old_budget and limit > old_budget[key]:
            found.append(
                Finding(BUDGET, f"bundle budget raised: {key} {old_budget[key]} -> {limit}")
            )

    for path, switch in SWITCHES.items():
        lines = diff.added.get(path, []) + diff.removed.get(path, [])
        if any(switch in line for line in lines):
            found.append(Finding(path, f"{switch} edited"))

    def assertions(lines_by_path: dict[str, list[str]]) -> int:
        return sum(
            1
            for path, lines in lines_by_path.items()
            if is_test_file(path)
            for line in lines
            if _ASSERTION.match(line)
        )

    return found, max(0, assertions(diff.removed) - assertions(diff.added))


def reason(body: str) -> str | None:
    """The reason in a `Tests weakened:` line, if one is long enough."""
    for match in _WEAKENED_LINE.finditer(body or ""):
        text = match.group(1).strip()
        if len(text) >= MIN_REASON:
            return text
    return None


def pr_body(pr: str) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    cmd = ["gh", "pr", "view", pr, "--json", "body", "--jq", ".body"]
    if repo:
        cmd += ["--repo", repo]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def report(found: list[Finding], removed_assertions: int, why: str | None) -> str:
    if not found:
        lines = ["### Test guard", "", "Nothing in this change weakens the tests."]
    else:
        lines = ["### Test guard", "", "This change weakens the tests:", ""]
        lines += [f"- `{f.path}`: {f.what}" for f in found]
        lines += [""]
        if why:
            lines += [f"**Tests weakened:** {why}"]
        else:
            lines += [
                "The PR body has no `Tests weakened:` line saying why. If the change is "
                "right, add one (at least ten characters: what was wrong with the test) "
                "and re-run the failed job (`gh run rerun <run> --failed`). If it is not, "
                "fix the code, not the test."
            ]
    if removed_assertions:
        lines += ["", f"(Assertions removed on balance: {removed_assertions}; not a failure.)"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base")
    parser.add_argument("head")
    parser.add_argument("--pr", help="the PR whose body must explain a weakening")
    args = parser.parse_args(argv)

    found, removed_assertions = weakenings(args.base, args.head)
    why = reason(pr_body(args.pr)) if args.pr and found else None
    text = report(found, removed_assertions, why)
    print(text, end="")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    if found and not why:
        for f in found:
            print(f"::error file={f.path}::{f.what}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
