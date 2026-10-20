"""scripts/test_guard.py reports each way a change weakens the tests (#358 AC1).

Each test builds a small repository: a base commit, then a change on a branch.
The skip markers are spelt in pieces, so this file adds none the guard would see.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("test_guard", ROOT / "scripts" / "test_guard.py")
assert _spec and _spec.loader
guard = importlib.util.module_from_spec(_spec)
sys.modules["test_guard"] = guard  # dataclasses look their module up
_spec.loader.exec_module(guard)

SKIP = "pytest.mark." + "skip"
XFAIL = "pytest.mark." + "xfail"
TS_SKIP = "test." + "skip"

PYPROJECT = """\
[tool.pytest.ini_options]
xfail_strict = true

[tool.coverage.report]
fail_under = 90
"""
BUDGET = {"entry": 1000, "route": 600, "routes": {"src/routes/a.tsx": 500}}
PY_TESTS = """\
def test_one():
    assert 1


def test_two():
    assert 2
"""
TS_TESTS = """\
import { expect, test } from "vitest";

test("adds", () => {
  expect(1 + 1).toBe(2);
});
"""
BASE_FILES = {
    "pyproject.toml": PYPROJECT,
    "web/bundle-budget.json": json.dumps(BUDGET, indent=2) + "\n",
    "Makefile": "check:\n\tTWR_FAIL_ON_SKIP=1 pytest\n",
    "web/playwright.config.ts": "export default { forbidOnly: !!process.env.CI };\n",
    "tests/test_a.py": PY_TESTS,
    "web/src/a.test.ts": TS_TESTS,
    "src/app.py": "x = 1\n",
}


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


def _write(repo: Path, files: dict[str, str | None]) -> None:
    for path, text in files.items():
        target = repo / path
        if text is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _write(tmp_path, BASE_FILES)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "switch", "-q", "-c", "change")
    return tmp_path


def change(repo: Path, files: dict[str, str | None]) -> list[str]:
    """Commit the change; what the guard reports for main...change."""
    _write(repo, files)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change", "--allow-empty")
    found, _ = guard.weakenings("main", "change", cwd=str(repo))
    return [f"{f.path}: {f.what}" for f in found]


def test_an_honest_change_reports_nothing(repo):
    more = PY_TESTS + "\n\ndef test_three():\n    assert 3\n"
    assert change(repo, {"tests/test_a.py": more, "src/app.py": "x = 2\n"}) == []


def test_a_deleted_test_file(repo):
    found = change(repo, {"tests/test_a.py": None})
    assert found == ["tests/test_a.py: test file deleted"]


def test_a_deleted_web_test_file(repo):
    found = change(repo, {"web/src/a.test.ts": None})
    assert found == ["web/src/a.test.ts: test file deleted"]


def test_a_test_file_renamed_away(repo):
    _git(repo, "mv", "tests/test_a.py", "src/not_a_test.py")
    found = change(repo, {})
    assert found == [
        "tests/test_a.py: test file renamed to src/not_a_test.py, which is not a test file"
    ]


def test_a_removed_python_test(repo):
    found = change(repo, {"tests/test_a.py": "def test_one():\n    assert 1\n"})
    assert found == ["tests/test_a.py: test removed: test_two"]


def test_a_removed_typescript_test(repo):
    found = change(repo, {"web/src/a.test.ts": 'import { test } from "vitest";\n'})
    assert found == ["web/src/a.test.ts: test removed: adds"]


def test_moving_a_test_between_files_is_not_reported(repo):
    found = change(
        repo,
        {
            "tests/test_a.py": "def test_one():\n    assert 1\n",
            "tests/test_b.py": "def test_two():\n    assert 2\n",
        },
    )
    assert found == []


def test_moving_a_skipped_test_is_not_reported(repo):
    _write(repo, {"tests/test_a.py": f"import pytest\n\n\n@{SKIP}\n" + PY_TESTS})
    _git(repo, "commit", "-qam", "skip on main")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "change")
    _git(repo, "switch", "-q", "change")
    found = change(
        repo,
        {
            "tests/test_a.py": "def test_two():\n    assert 2\n",
            "tests/test_b.py": f"import pytest\n\n\n@{SKIP}\ndef test_one():\n    assert 1\n",
        },
    )
    assert found == []


@pytest.mark.parametrize(
    ("path", "line"),
    [
        ("tests/test_a.py", f"@{SKIP}"),
        ("tests/test_a.py", f'@{SKIP}if(True, reason="x")'),
        ("tests/test_a.py", f"@{XFAIL}"),
        ("tests/test_a.py", "dep = pytest.importor" + "skip('x')"),
        ("tests/test_a.py", "    pytest." + "skip('no')"),
        ("web/src/a.test.ts", TS_SKIP + '("later", () => {});'),
        ("web/src/a.test.ts", "it." + 'skip("later", () => {});'),
        ("web/src/a.test.ts", "describe." + 'skip("later", () => {});'),
        ("web/src/a.test.ts", "test." + 'fixme("later", () => {});'),
        ("web/src/a.test.ts", "test." + 'todo("later");'),
        ("web/src/a.test.ts", "test." + 'only("this", () => {});'),
        ("web/src/a.test.ts", "describe." + 'only("this", () => {});'),
    ],
)
def test_an_added_skip(repo, path, line):
    found = change(repo, {path: BASE_FILES[path] + "\n" + line + "\n"})
    assert found == [f"{path}: skip or expected failure added: {line.strip()}"]


def test_a_skip_outside_the_tests_is_not_reported(repo):
    assert change(repo, {"src/app.py": f"# {SKIP}\n"}) == []


def test_a_conditional_playwright_skip_in_a_body_is_not_reported(repo):
    body = (
        'test("drags", async ({ page }, testInfo) => {\n'
        f'  {TS_SKIP}(testInfo.project.name !== "phone", "touch: the phone project");\n'
        f"  {TS_SKIP}(!process.env.LIVE, 'needs the live source');\n"
        "});\n"
    )
    assert change(repo, {"web/src/a.test.ts": TS_TESTS + body}) == []


@pytest.mark.parametrize(
    "line",
    [
        f'  {TS_SKIP}(true, "always skipped");',  # a condition that is always true
        f'{TS_SKIP}(isPhone, "at the top level");',  # not inside a block
        f'  {TS_SKIP}("a title", async () => {{}});',  # a title: the test is skipped
        f"  {TS_SKIP}();",  # bare
    ],
)
def test_an_unconditional_playwright_skip_is_reported(repo, line):
    found = change(repo, {"web/src/a.test.ts": TS_TESTS + line + "\n"})
    assert found == [f"web/src/a.test.ts: skip or expected failure added: {line.strip()}"]


def test_a_removed_typescript_test_with_its_title_on_the_next_line(repo):
    wrapped = TS_TESTS + '\ntest(\n  "a long title prettier wrapped",\n  () => {},\n);\n'
    _write(repo, {"web/src/a.test.ts": wrapped})
    _git(repo, "commit", "-qam", "wrapped")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "change")
    _git(repo, "switch", "-q", "change")
    found = change(repo, {"web/src/a.test.ts": TS_TESTS})
    assert found == ["web/src/a.test.ts: test removed: a long title prettier wrapped"]


def test_a_no_cover_pragma_added_to_source(repo):
    line = "x = 2  # " + "pragma: no cover"
    found = change(repo, {"src/app.py": line + "\n"})
    assert found == [f"src/app.py: coverage exclusion added: {line}"]


def test_a_coverage_omit_added(repo):
    pyproject = PYPROJECT + '\n[tool.coverage.run]\nomit = ["src/hard.py"]\n'
    found = change(repo, {"pyproject.toml": pyproject})
    assert found == ["pyproject.toml: coverage omit added: src/hard.py"]


def test_a_coverage_exclude_pattern_added(repo):
    pyproject = PYPROJECT + 'exclude_also = ["if DEBUG:"]\n'
    found = change(repo, {"pyproject.toml": pyproject})
    assert found == ["pyproject.toml: coverage exclusion added: if DEBUG:"]


def test_a_lower_coverage_floor(repo):
    found = change(repo, {"pyproject.toml": PYPROJECT.replace("90", "85")})
    assert found == ["pyproject.toml: coverage floor lowered: fail_under 90 -> 85"]


def test_a_higher_coverage_floor_is_not_reported(repo):
    assert change(repo, {"pyproject.toml": PYPROJECT.replace("90", "95")}) == []


def test_xfail_strict_turned_off(repo):
    found = change(repo, {"pyproject.toml": PYPROJECT.replace("true", "false")})
    assert found == ["pyproject.toml: xfail_strict turned off: True -> False"]


def test_xfail_strict_turned_on_is_not_reported(repo):
    _write(repo, {"pyproject.toml": PYPROJECT.replace("xfail_strict = true\n", "")})
    _git(repo, "commit", "-qam", "not strict")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "change")
    _git(repo, "switch", "-q", "change")
    assert change(repo, {"pyproject.toml": PYPROJECT}) == []


def test_a_raised_bundle_budget(repo):
    budget = {**BUDGET, "routes": {"src/routes/a.tsx": 550, "src/routes/b.tsx": 400}}
    found = change(repo, {"web/bundle-budget.json": json.dumps(budget)})
    assert found == [
        "web/bundle-budget.json: bundle budget raised: routes/src/routes/a.tsx 500 -> 550"
    ]


def test_a_lower_bundle_budget_is_not_reported(repo):
    budget = {**BUDGET, "entry": 900}
    assert change(repo, {"web/bundle-budget.json": json.dumps(budget)}) == []


def test_the_skip_switch_edited(repo):
    found = change(repo, {"Makefile": "check:\n\tpytest\n"})
    assert found == ["Makefile: TWR_FAIL_ON_SKIP edited"]


def test_forbid_only_changed(repo):
    found = change(repo, {"web/playwright.config.ts": "export default { forbidOnly: false };\n"})
    assert found == ["web/playwright.config.ts: forbidOnly edited"]


def test_a_removed_line_starting_with_two_dashes_is_not_a_file_name(repo):
    _write(repo, {"tests/q.sql": "-- a comment\nselect 1;\n"})
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "sql")
    _git(repo, "switch", "-q", "main")
    _git(repo, "merge", "-q", "change")
    _git(repo, "switch", "-q", "change")
    found = change(
        repo, {"tests/q.sql": "select 1;\n", "tests/test_a.py": "def test_one():\n    assert 1\n"}
    )
    assert found == ["tests/test_a.py: test removed: test_two"]


def test_removed_assertions_are_counted_not_reported(repo):
    _write(repo, {"tests/test_a.py": PY_TESTS.replace("    assert 2\n", "    pass\n")})
    _git(repo, "commit", "-qam", "change")
    found, removed = guard.weakenings("main", "change", cwd=str(repo))
    assert found == []
    assert removed == 1


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Fixes a bug.\n\nTests weakened: the bounds were flaky on CI (#348)\n",
            "the bounds were flaky on CI (#348)",
        ),
        ("Tests weakened: demo", None),  # under ten characters
        ("Tests weakened:\n", None),
        ("No line at all", None),
        ("", None),
    ],
)
def test_the_reason_line(body, expected):
    assert guard.reason(body) == expected


def test_main_fails_without_a_reason_and_passes_with_one(repo, monkeypatch, capsys):
    change(repo, {"tests/test_a.py": None})
    monkeypatch.chdir(repo)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(guard, "pr_body", lambda pr: "No line here.")
    assert guard.main(["main", "change", "--pr", "1"]) == 1
    assert "has no `Tests weakened:` line" in capsys.readouterr().out
    monkeypatch.setattr(
        guard, "pr_body", lambda pr: "Tests weakened: the file tested a removed feature"
    )
    assert guard.main(["main", "change", "--pr", "1"]) == 0
    assert "the file tested a removed feature" in capsys.readouterr().out


def test_main_passes_when_nothing_is_weakened(repo, monkeypatch, tmp_path_factory):
    change(repo, {"src/app.py": "x = 3\n"})
    monkeypatch.chdir(repo)
    summary = tmp_path_factory.mktemp("summary") / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(guard, "pr_body", lambda pr: pytest.fail("no body needed"))
    assert guard.main(["main", "change", "--pr", "1"]) == 0
    assert "Nothing in this change weakens the tests." in summary.read_text()
