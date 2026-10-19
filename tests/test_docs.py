"""The docs and the code agree (#338): every environment variable the code reads has
a row in the config table, every command and make target is documented, every
metric is named, and the internal links resolve. Each failure names what is
missing and the file to edit."""

import argparse
import importlib.util
import re
import subprocess
from pathlib import Path

import pytest

from those_who_run.cli import build_parser

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "those_who_run"
SETUP = ROOT / "docs" / "setup.md"
DEVELOPMENT = ROOT / "docs" / "development.md"
OPERATIONS = ROOT / "docs" / "operations.md"

_spec = importlib.util.spec_from_file_location("docs_links", ROOT / "scripts" / "docs_links.py")
assert _spec is not None and _spec.loader is not None
docs_links = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(docs_links)

# The variables that are ours: GT7_* and DISCORD_*, and two without a prefix.
OURS = re.compile(r"""["'](GT7_[A-Z0-9_]+|DISCORD_[A-Z0-9_]+|PITWALL_URL|LOG_LEVEL)["']""")


def section(path: Path, heading: str) -> str:
    """The text under ``## heading`` up to the next heading of that level."""
    text = path.read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    assert m, f"{path.relative_to(ROOT)} has no '## {heading}' section"
    return m.group(1)


def first_column(path: Path, heading: str) -> list[str]:
    """The backticked names in the first column of the table under ``heading``."""
    rows = re.findall(r"^\|\s*`([^`]+)`\s*\|", section(path, heading), re.M)
    assert rows, f"no table with backticked names under '## {heading}' in {path.name}"
    return rows


def read_by_code() -> dict[str, set[str]]:
    """Every variable a quoted string under src/ names, and the files that name it."""
    found: dict[str, set[str]] = {}
    for py in sorted(SRC.rglob("*.py")):
        for name in OURS.findall(py.read_text(encoding="utf-8")):
            found.setdefault(name, set()).add(py.relative_to(SRC).as_posix())
    return found


def test_every_variable_the_code_reads_has_a_row_in_the_config_table():
    """R1, R7: named by the code, missing from docs/setup.md's config table."""
    documented = set(first_column(SETUP, "Configuration"))
    code = read_by_code()
    missing = [
        f"`{name}` is read by {', '.join(sorted(files))}"
        " but has no row in docs/setup.md's config table"
        for name, files in sorted(code.items())
        if name not in documented
    ]
    assert not missing, "\n".join(missing)


def test_every_row_of_the_config_table_is_read_by_the_code():
    """R1, R7: a row for a variable nothing reads."""
    code = read_by_code()
    stale = [
        f"`{name}` has a row in docs/setup.md's config table but nothing under src/ reads it"
        for name in first_column(SETUP, "Configuration")
        if name not in code
    ]
    assert not stale, "\n".join(stale)


def test_the_variables_found_include_the_ones_outside_config_py():
    """The scan is not a hand list: it finds archive.py's GT7_ARCHIVE_DIR (#338's
    evidence) and the unprefixed two."""
    code = read_by_code()
    assert "archive.py" in code["GT7_ARCHIVE_DIR"]
    assert {"PITWALL_URL", "LOG_LEVEL", "DISCORD_BOT_TOKEN", "GT7_DATA_DIR"} <= set(code)


def commands() -> set[str]:
    """Every command, and each subcommand of one that has them, from the parser:
    ``run``, ``tracks list`` …"""

    def subparsers(p: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
        for action in p._actions:
            if isinstance(action, argparse._SubParsersAction):
                return dict(action.choices)
        return {}

    found = set()
    for name, parser in subparsers(build_parser()).items():
        subs = subparsers(parser)
        # A command that needs a subcommand (`tracks`) is documented by its subcommands.
        found.update({f"{name} {sub}" for sub in subs} or {name})
    return found


def test_every_command_is_in_the_commands_table():
    """R2, R7: a command or subcommand missing from docs/setup.md's commands table."""
    documented = set(first_column(SETUP, "Commands"))
    missing = [
        f"`{c}` is a command (build_parser) but has no row in docs/setup.md's commands table"
        for c in sorted(commands() - documented)
    ]
    assert not missing, "\n".join(missing)


def test_the_commands_table_names_only_commands():
    """R2, R7: a row for a command that doesn't exist."""
    stale = [
        f"`{c}` has a row in docs/setup.md's commands table but is not a command"
        for c in sorted(set(first_column(SETUP, "Commands")) - commands())
    ]
    assert not stale, "\n".join(stale)


def test_the_commands_found_include_subcommands():
    assert {"run", "rebuild-best", "tracks learn", "cars find"} <= commands()


def phony() -> set[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8").replace("\\\n", " ")
    lines = re.findall(r"^\.PHONY:(.*)$", text, re.M)
    assert lines, "the Makefile has no .PHONY line"
    return {target for line in lines for target in line.split()}


@pytest.fixture(scope="module")
def make_help() -> set[str]:
    out = subprocess.run(
        ["make", "-s", "--no-print-directory", "help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return set(re.findall(r"^(\S+)\s+- ", out, re.M))


def test_every_phony_target_is_in_make_help(make_help):
    """R3, R7: a .PHONY target `make help` doesn't list."""
    missing = [
        f"make target `{t}` is in .PHONY but not in `make help`:"
        " add an @echo line to the Makefile's help"
        for t in sorted(phony() - make_help)
    ]
    assert not missing, "\n".join(missing)


def test_every_make_help_target_is_in_the_make_table(make_help):
    """R3, R7: a `make help` target missing from docs/development.md's make table."""
    table = set(first_column(DEVELOPMENT, "Make targets"))
    missing = [
        f"make target `{t}` is in `make help` but has no row in docs/development.md's make table"
        for t in sorted(make_help - table)
    ]
    assert not missing, "\n".join(missing)


def test_the_make_table_names_only_targets(make_help):
    """R3, R7: a row for a target that doesn't exist."""
    stale = [
        f"`{t}` has a row in docs/development.md's make table but is not a make target"
        for t in sorted(set(first_column(DEVELOPMENT, "Make targets")) - (make_help | phony()))
    ]
    assert not stale, "\n".join(stale)


def registered_metrics() -> set[str]:
    source = (SRC / "metrics.py").read_text(encoding="utf-8")
    return set(
        re.findall(r"""(?:Counter|Gauge|Histogram|Summary|Info|Enum)\(\s*["'](\w+)["']""", source)
    )


def test_every_metric_is_named_in_the_operations_guide():
    """R8, R7: a metric registered in metrics.py that docs/operations.md doesn't name."""
    documented = set(re.findall(r"`(gt7_\w+)", section(OPERATIONS, "Metrics")))
    metrics = registered_metrics()
    assert len(metrics) >= 19, "the scan of metrics.py found too few metrics"
    missing = [
        f"metric `{m}` is registered in metrics.py but not named in docs/operations.md, Metrics"
        for m in sorted(metrics - documented)
    ]
    stale = [
        f"docs/operations.md, Metrics names `{m}`, which metrics.py does not register"
        for m in sorted(documented - metrics)
    ]
    assert not missing + stale, "\n".join(missing + stale)


# The link checker (scripts/docs_links.py, `make docs-check`, R4).


def test_the_repositorys_links_resolve(capsys):
    """R4, R5: what `make docs-check` runs, offline."""
    assert docs_links.main([]) == 0, capsys.readouterr().err


def test_the_link_check_reads_the_files_r4_names():
    names = {p.relative_to(ROOT).as_posix() for p in docs_links.markdown_files()}
    assert {"README.md", "ROADMAP.md", "docs/setup.md", "docs/adr/README.md"} <= names
    assert ".github/ISSUE_TEMPLATE/spec.md" in names
    assert "CHANGELOG.md" not in names


@pytest.fixture
def site(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "operations.md").write_text(
        "# Operations\n\n## Releasing\n\nText.\n\n## Releasing\n\n## `make check` and `pit_lane`\n"
    )
    (tmp_path / "docs" / "img.png").write_bytes(b"")
    return tmp_path


def broken(root: Path, text: str) -> list[str]:
    page = root / "docs" / "page.md"
    page.write_text(text)
    docs_links.anchors.cache_clear()
    return docs_links.check_file(page, root)


def test_links_that_resolve_pass(site):
    assert (
        broken(
            site,
            "[a](operations.md#releasing) [b](operations.md#releasing-1)"
            " [c](operations.md#make-check-and-pit_lane) [d](#here) ![e](img.png)\n"
            '<img src="img.png"> [f](https://example.com/x#y) [g]: operations.md\n\n## Here\n',
        )
        == []
    )


def test_a_renamed_heading_fails_naming_the_file_and_the_link(site):
    """AC4: a link to a heading that is gone."""
    assert broken(site, "See [Releasing](operations.md#shipping).\n") == [
        "docs/page.md:1: operations.md#shipping: no heading #shipping in docs/operations.md"
    ]


def test_a_missing_file_fails(site):
    assert broken(site, "\n![x](missing.png) [y](../nowhere.md)\n") == [
        "docs/page.md:2: missing.png: no such file missing.png",
        "docs/page.md:2: ../nowhere.md: no such file ../nowhere.md",
    ]


def test_an_anchor_in_the_same_file_is_checked(site):
    assert broken(site, "[x](#nope)\n\n## Yes\n") == [
        "docs/page.md:1: #nope: no heading #nope in docs/page.md"
    ]


def test_links_in_code_are_not_links(site):
    assert broken(site, "```\n[x](nope.md)\n```\n\n`[y](nope.md)`\n") == []


def test_the_check_fails_with_a_message(site, capsys):
    (site / "docs" / "page.md").write_text("[x](gone.md)\n")
    docs_links.anchors.cache_clear()
    assert docs_links.main([str(site / "docs" / "page.md")], root=site) == 1
    assert "1 broken link(s)" in capsys.readouterr().err


def test_the_pull_request_template_asks_for_the_docs_line():
    """R6 and the 2026-10-19 addendum: what every PR is asked for."""
    template = (ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
    for asked in (
        "Closes #",
        "Part of #N (ACn stays open)",
        "## What changed and why",
        "## How it was tested",
        "**Docs:** Updated:",
        "None needed because",
        "**Screenshots:**",
        "`make check` is green",
        "**AI assistance:**",
        "Tests weakened:",
    ):
        assert asked in template, f".github/pull_request_template.md does not ask for {asked!r}"
