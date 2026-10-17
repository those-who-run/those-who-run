"""Check a release tag against the package version and say which image tags to push.

    python scripts/release_version.py v0.5.0-rc1

Fails (exit 1) when the tag is not ``v`` plus the version in
``src/those_who_run/__init__.py``, compared as PEP 440 versions, so ``v0.5.0-rc1``
matches ``0.5.0rc1``. Otherwise prints ``version=`` (the tag without its ``v``,
the image tag), ``latest=`` (true only for a final release, never for a
pre-release or dev tag) and ``package=`` (the version as the code has it, which
``those-who-run --version`` prints), appending them to ``$GITHUB_OUTPUT`` when it is set.
"""

from __future__ import annotations

import os
import sys

from packaging.version import InvalidVersion, Version


def release_outputs(tag: str, package_version: str) -> dict[str, str]:
    """``version``, ``latest`` and ``package`` for a tag, or ValueError when it does not match."""
    if not tag.startswith("v"):
        raise ValueError(f"tag {tag!r} does not start with 'v'")
    name = tag[1:]
    try:
        tagged = Version(name)
    except InvalidVersion as exc:
        raise ValueError(f"tag {tag!r} is not a version") from exc
    if tagged.local:
        raise ValueError(f"tag {tag!r} has a local version, which is not an image tag")
    if tagged != Version(package_version):
        raise ValueError(f"tag {tag!r} does not match the package version {package_version!r}")
    latest = not (tagged.is_prerelease or tagged.is_devrelease)
    return {"version": name, "latest": "true" if latest else "false", "package": package_version}


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    from those_who_run import __version__

    try:
        outputs = release_outputs(argv[0], __version__)
    except ValueError as exc:
        print(f"release_version: {exc}", file=sys.stderr)
        return 1
    lines = [f"{k}={v}" for k, v in outputs.items()]
    print("\n".join(lines))
    if path := os.environ.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
