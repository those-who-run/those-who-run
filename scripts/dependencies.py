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
    `[project.optional-dependencies]` group, every `[dependency-groups]` group and
    `[build-system] requires` (what builds the wheel runs at install time too)."""
    data = tomllib.loads(pyproject)
    project = data.get("project", {})
    found: dict[str, str] = {}
    for requirement in data.get("build-system", {}).get("requires", []):
        found.setdefault(normalise(_requirement_name(requirement)), "build-system")
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


# npm's sections that name a package to install: each adds a name to the tree.
NPM_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")


def _override_name(key: str) -> str:
    """An `overrides` key is a name, optionally with a version range after an `@`
    that is not the scope's: `foo`, `foo@1`, `@scope/foo@^2`."""
    at = key.find("@", 1)
    return key if at == -1 else key[:at]


def _override_names(overrides: dict[str, object]) -> list[str]:
    """Every package an `overrides` tree names, nested ones included; `.` is the
    parent's own version, not a name."""
    names = []
    for key, value in overrides.items():
        if key == ".":
            continue
        names.append(_override_name(key))
        if isinstance(value, dict):
            names.extend(_override_names(value))
    return names


def npm_dependencies(package_json: str) -> dict[str, str]:
    """{name: section} for `dependencies`, `devDependencies`,
    `optionalDependencies`, `peerDependencies` and every name in `overrides`
    (an override can pull in a package by name with an `npm:` alias or a URL)."""
    data = json.loads(package_json)
    found: dict[str, str] = {}
    for section in NPM_SECTIONS:
        for name in data.get(section, {}):
            found.setdefault(name, section)
    for name in _override_names(data.get("overrides", {})):
        found.setdefault(name, "overrides")
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
