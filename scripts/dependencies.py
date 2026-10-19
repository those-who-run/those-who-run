"""The project's direct dependencies, read from its manifests (#355, #357).

Standard library only: the release digest runs it on a bare runner.

    python scripts/dependencies.py    print every direct dependency, one per line
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A requirement's name: what comes before extras, a version or a marker (PEP 508).
_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def normalise(name: str) -> str:
    """PEP 503: case and runs of `-`, `_` and `.` don't matter."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirement_name(requirement: str) -> str:
    match = _NAME.match(requirement)
    if not match:
        raise ValueError(f"not a requirement: {requirement!r}")
    return match.group(1)


def python_dependencies(pyproject: str) -> dict[str, str]:
    """{normalised name: where it is declared} for `[project.dependencies]`, every
    `[project.optional-dependencies]` group and every `[dependency-groups]` group."""
    data = tomllib.loads(pyproject)
    project = data.get("project", {})
    found: dict[str, str] = {}
    for requirement in project.get("dependencies", []):
        found.setdefault(normalise(_requirement_name(requirement)), "dependencies")
    for extra, requirements in project.get("optional-dependencies", {}).items():
        for requirement in requirements:
            found.setdefault(normalise(_requirement_name(requirement)), f"extra {extra}")
    for group, requirements in data.get("dependency-groups", {}).items():
        for requirement in requirements:
            if isinstance(requirement, str):  # {include-group = ...} adds no name
                found.setdefault(normalise(_requirement_name(requirement)), f"group {group}")
    return found


def npm_dependencies(package_json: str) -> dict[str, str]:
    """{name: section} for `dependencies` and `devDependencies`."""
    data = json.loads(package_json)
    found: dict[str, str] = {}
    for section in ("dependencies", "devDependencies"):
        for name in data.get(section, {}):
            found.setdefault(name, section)
    return found


def direct_dependencies(pyproject: str, package_json: str) -> dict[str, dict[str, str]]:
    """Both manifests: {"python": {...}, "npm": {...}}."""
    return {"python": python_dependencies(pyproject), "npm": npm_dependencies(package_json)}


def main() -> int:
    deps = direct_dependencies(
        (ROOT / "pyproject.toml").read_text(), (ROOT / "web" / "package.json").read_text()
    )
    for ecosystem, names in deps.items():
        for name, where in sorted(names.items()):
            print(f"{ecosystem}\t{name}\t{where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
