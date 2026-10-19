"""Every direct dependency has a line, with its reason, in docs/dependencies.md (#355).

A new name in pyproject.toml or web/package.json fails here until the PR adds it to
the doc, which the maintainer reviews; a version bump changes no name and passes.
"""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "dependencies.md"

_spec = importlib.util.spec_from_file_location("dependencies", ROOT / "scripts" / "dependencies.py")
assert _spec and _spec.loader
dependencies = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dependencies)

# A table row whose first cell is a name in backticks, and its last cell.
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|.*\|\s*([^|]*?)\s*\|\s*$")


def documented(doc: str) -> dict[str, dict[str, str]]:
    """{"python": {name: reason}, "npm": {name: reason}} from the doc's tables, by
    the `## Python` and `## npm` sections they sit under."""
    found: dict[str, dict[str, str]] = {"python": {}, "npm": {}}
    section = None
    for line in doc.splitlines():
        if line.startswith("## "):
            heading = line[3:].lower()
            section = next((k for k in found if heading.startswith(k)), None)
            continue
        match = _ROW.match(line)
        if match and section:
            name = match.group(1)
            if section == "python":
                name = dependencies.normalise(name)
            found[section][name] = match.group(2)
    return found


def problems(declared: dict[str, dict[str, str]], doc: str) -> list[str]:
    """What is wrong between the manifests and the doc, as messages to act on."""
    listed = documented(doc)
    heading = {"python": "Python", "npm": "npm"}
    out = []
    for ecosystem, manifest in (("python", "pyproject.toml"), ("npm", "web/package.json")):
        for name, where in sorted(declared[ecosystem].items()):
            if name not in listed[ecosystem]:
                out.append(
                    f"{name} ({manifest}, {where}) is a new direct dependency: add a row "
                    f"for it to docs/dependencies.md, under `## {heading[ecosystem]}`, with "
                    "its registry link and why the project needs it. Check first that it "
                    "is the package you mean and that nothing already listed does the job."
                )
        for name, reason in sorted(listed[ecosystem].items()):
            if name not in declared[ecosystem]:
                out.append(
                    f"{name} is in docs/dependencies.md but not in {manifest}: remove its row."
                )
            elif len(reason) < 10:
                out.append(f"{name}: its row in docs/dependencies.md needs a reason.")
    return out


def _manifests() -> dict[str, dict[str, str]]:
    return dependencies.direct_dependencies(
        (ROOT / "pyproject.toml").read_text(), (ROOT / "web" / "package.json").read_text()
    )


def test_every_direct_dependency_is_documented():
    found = problems(_manifests(), DOC.read_text())
    assert not found, "\n".join(found)


PYPROJECT = """
[project]
dependencies = ["PyYAML>=6", "aiohttp>=3.9,<4"]
[project.optional-dependencies]
engineer = ["discord.py[voice]>=2.4,<3", "gt-telem==1.2.1 ; python_version >= '3.14'"]
[dependency-groups]
lint = ["ruff", {include-group = "engineer"}]
"""
PACKAGE_JSON = '{"dependencies": {"react": "19.3.0"}, "devDependencies": {"@types/react": "1"}}'
DOC_TEXT = """
## Python

| Package | Registry | Why |
| --- | --- | --- |
| `pyyaml` | [PyPI](https://pypi.org/project/PyYAML/) | Reads the rules. |
| `aiohttp` | [PyPI](https://pypi.org/project/aiohttp/) | The HTTP servers. |
| `discord_py` | [PyPI](https://pypi.org/project/discord.py/) | The Discord bot. |
| `gt-telem` | [PyPI](https://pypi.org/project/gt-telem/) | GT7 telemetry. |
| `ruff` | [PyPI](https://pypi.org/project/ruff/) | Lint and format. |

## npm

| Package | Registry | Why |
| --- | --- | --- |
| `react` | [npm](https://www.npmjs.com/package/react) | The UI library. |
| `@types/react` | [npm](https://www.npmjs.com/package/@types/react) | React's types. |
"""


def test_names_are_read_from_every_section_and_normalised():
    deps = dependencies.direct_dependencies(PYPROJECT, PACKAGE_JSON)
    assert deps["python"] == {
        "pyyaml": "dependencies",
        "aiohttp": "dependencies",
        "discord-py": "extra engineer",
        "gt-telem": "extra engineer",
        "ruff": "group lint",
    }
    assert deps["npm"] == {"react": "dependencies", "@types/react": "devDependencies"}
    assert problems(deps, DOC_TEXT) == []


def test_a_version_bump_passes():
    bumped = PYPROJECT.replace("aiohttp>=3.9,<4", "aiohttp>=3.13,<4")
    deps = dependencies.direct_dependencies(bumped, PACKAGE_JSON.replace('"1"', '"2"'))
    assert problems(deps, DOC_TEXT) == []


@pytest.mark.parametrize(
    ("pyproject", "package_json", "name"),
    [
        (PYPROJECT.replace('"PyYAML>=6"', '"PyYAML>=6", "requests>=2"'), PACKAGE_JSON, "requests"),
        (PYPROJECT, PACKAGE_JSON.replace('"1"}', '"1", "left-pad": "1.3.0"}'), "left-pad"),
    ],
)
def test_a_new_dependency_fails_naming_it(pyproject, package_json, name):
    found = problems(dependencies.direct_dependencies(pyproject, package_json), DOC_TEXT)
    assert len(found) == 1
    assert found[0].startswith(f"{name} (")
    assert "new direct dependency" in found[0]


def test_a_row_for_a_removed_dependency_fails():
    deps = dependencies.direct_dependencies(
        PYPROJECT.replace(', "aiohttp>=3.9,<4"', ""), PACKAGE_JSON
    )
    assert problems(deps, DOC_TEXT) == [
        "aiohttp is in docs/dependencies.md but not in pyproject.toml: remove its row."
    ]


def test_a_row_needs_a_reason():
    doc = DOC_TEXT.replace("| GT7 telemetry. |", "| |")
    found = problems(dependencies.direct_dependencies(PYPROJECT, PACKAGE_JSON), doc)
    assert found == ["gt-telem: its row in docs/dependencies.md needs a reason."]


def test_a_python_name_under_npm_does_not_count():
    doc = DOC_TEXT.replace("| `ruff` |", "| `rufff` |") + (
        "| `ruff` | [npm](https://www.npmjs.com/package/ruff) | Wrong section. |\n"
    )
    found = problems(dependencies.direct_dependencies(PYPROJECT, PACKAGE_JSON), doc)
    assert any(f.startswith("ruff (pyproject.toml") for f in found)
