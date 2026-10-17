import importlib.util
import tomllib
from pathlib import Path

import pytest

from those_who_run import __version__

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "release_version", ROOT / "scripts" / "release_version.py"
)
assert _spec and _spec.loader
release_version = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release_version)
release_outputs = release_version.release_outputs


def test_final_release_moves_latest():
    assert release_outputs("v0.5.0", "0.5.0") == {
        "version": "0.5.0",
        "latest": "true",
        "package": "0.5.0",
    }


@pytest.mark.parametrize("tag", ["v0.5.0-rc1", "v0.5.0rc1", "v0.5.0a1", "v0.5.0.dev3"])
def test_prerelease_never_moves_latest(tag):
    package = tag[1:].replace("-", "")
    out = release_outputs(tag, package)
    assert (out["version"], out["latest"], out["package"]) == (tag[1:], "false", package)


def test_rc_tag_matches_normalised_package_version():
    assert release_outputs("v0.5.0-rc1", "0.5.0rc1")["version"] == "0.5.0-rc1"


@pytest.mark.parametrize(
    "tag", ["v0.4.1", "0.5.0", "v0.5.0-rc1", "vnext", "release-0.5.0", "v0.5.0+x"]
)
def test_tag_not_matching_the_version_fails(tag):
    with pytest.raises(ValueError):
        release_outputs(tag, "0.5.0")


def test_main_writes_github_output(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert release_version.main([f"v{__version__}"]) == 0
    assert f"version={__version__}" in out.read_text()
    assert release_version.main(["v999.0.0"]) == 1
    assert "does not match" in capsys.readouterr().err


def test_version_lives_in_one_place():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert "version" not in project and "version" in project["dynamic"]
