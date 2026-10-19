"""scripts/release_digest.py lists what a release changes in the watched places (#357 AC1).

Each test builds a small history: a tagged release, then squash-merge-style
commits whose subjects end in `(#N)`. Skip markers are spelt in pieces, so this
file adds none the test guard would see.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "release_digest", ROOT / "scripts" / "release_digest.py"
)
assert _spec and _spec.loader
release_digest = importlib.util.module_from_spec(_spec)
sys.modules["release_digest"] = release_digest  # dataclasses look their module up
_spec.loader.exec_module(release_digest)

XFAIL = "pytest.mark." + "xfail"
PYPROJECT = """\
[project]
name = "x"
dependencies = ["pyyaml>=6"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.coverage.report]
fail_under = 90
"""
PACKAGE_JSON = {"dependencies": {"react": "19.3.0"}, "devDependencies": {"vite": "8.3.2"}}


# A developer's signing config must not reach these throwaway repositories.
NO_SIGNING = ("-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *NO_SIGNING, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def commit(repo: Path, subject: str, files: dict[str, str | None]) -> None:
    for path, text in files.items():
        target = repo / path
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", subject)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    commit(
        tmp_path,
        "chore(release): 0.1.0 (#1)",
        {
            "pyproject.toml": PYPROJECT,
            "web/package.json": json.dumps(PACKAGE_JSON),
            ".github/workflows/ci.yml": "on: push\n",
            "tests/test_a.py": "def test_a():\n    assert 1\n",
            "tests/test_b.py": "def test_b():\n    assert 1\n",
            "src/app.py": "x = 1\n",
        },
    )
    _git(tmp_path, "tag", "v0.1.0")
    return tmp_path


def run(repo: Path) -> str:
    return release_digest.markdown(release_digest.digest("v0.1.0..main", cwd=str(repo)))


def test_the_four_kinds_and_not_a_version_bump(repo):
    commit(
        repo,
        "feat: fetch things (#10)",
        {"pyproject.toml": PYPROJECT.replace('"pyyaml>=6"', '"pyyaml>=6", "requests>=2"')},
    )
    commit(repo, "ci: a new step (#11)", {".github/workflows/ci.yml": "on: [push, pull_request]\n"})
    commit(repo, "test: drop b (#12)", {"tests/test_b.py": None})
    commit(
        repo,
        "test: a known failure (#13)",
        {"tests/test_a.py": f"import pytest\n\n\n@{XFAIL}\ndef test_a():\n    assert 1\n"},
    )
    bumped = {**PACKAGE_JSON, "dependencies": {"react": "19.4.0"}}
    commit(repo, "deps: bump react (#14)", {"web/package.json": json.dumps(bumped)})

    text = run(repo)
    assert text.startswith(release_digest.MARKER)
    assert "- `requests` (pyproject.toml, dependencies) (#10)" in text
    assert "- M `.github/workflows/ci.yml` (#11)" in text
    assert "- `tests/test_b.py`: test file deleted (#12)" in text
    assert f"- `tests/test_a.py`: skip or expected failure added: @{XFAIL} (#13)" in text
    assert "react" not in text
    assert "#14" not in text


def test_a_new_npm_dev_dependency(repo):
    more = {**PACKAGE_JSON, "devDependencies": {"vite": "8.3.2", "left-pad": "1.3.0"}}
    commit(repo, "chore: pad (#20)", {"web/package.json": json.dumps(more)})
    assert "- `left-pad` (web/package.json, devDependencies) (#20)" in run(repo)


def test_the_coverage_floor_and_the_budget(repo):
    commit(repo, "budget (#30)", {"web/bundle-budget.json": json.dumps({"entry": 100})})
    _git(repo, "tag", "-f", "v0.1.0")
    commit(repo, "test: lower floor (#31)", {"pyproject.toml": PYPROJECT.replace("90", "85")})
    commit(repo, "perf: bigger (#32)", {"web/bundle-budget.json": json.dumps({"entry": 120})})
    text = run(repo)
    assert "- coverage floor `fail_under`: 90 -> 85 (#31)" in text
    assert "- bundle budget: entry 100 -> 120 (#32)" in text
    assert "coverage floor lowered: fail_under 90 -> 85 (#31)" in text


def test_a_direct_push_is_named_by_its_subject(repo):
    commit(repo, "fix the Makefile by hand", {"Makefile": "check:\n"})
    assert "- A `Makefile` (`fix the Makefile by hand`)" in run(repo)


def test_nothing_watched(repo):
    commit(repo, "fix: the app (#40)", {"src/app.py": "x = 2\n"})
    text = run(repo)
    assert "Nothing in the watched places changed." in text
    assert "#40" not in text


def test_main_defaults_to_the_last_tag(repo, monkeypatch, capsys):
    commit(repo, "ci: tweak (#50)", {".github/workflows/ci.yml": "on: pull_request\n"})
    monkeypatch.chdir(repo)
    assert release_digest.main([]) == 0
    out = capsys.readouterr().out
    assert "from `v0.1.0` to `HEAD`" in out
    assert "(#50)" in out


def test_main_rejects_a_three_dot_range(repo, monkeypatch):
    monkeypatch.chdir(repo)
    with pytest.raises(SystemExit):
        release_digest.main(["v0.1.0...main"])
