"""scripts/home_lab_bump.py: the release's bump of home-lab's kustomization (#238 R3)."""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "home_lab_bump", ROOT / "scripts" / "home_lab_bump.py"
)
assert _spec and _spec.loader
home_lab_bump = importlib.util.module_from_spec(_spec)
sys.modules["home_lab_bump"] = home_lab_bump  # a dataclass looks its module up
_spec.loader.exec_module(home_lab_bump)
plan = home_lab_bump.plan

# home-lab's file before the switch: one image for both pods.
ONE = """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
images:
  - name: muldoon/those-who-run
    newTag: 0.7.3
"""

# After it: the pit wall's placeholder name gets its own entry (#238 R3).
TWO = """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
images:
  - name: muldoon/those-who-run
    newTag: 0.7.3
  - name: those-who-run-pitwall
    newName: muldoon/those-who-run
    newTag: 0.7.3-pitwall
"""


def test_one_tag_is_bumped():
    out = plan(ONE, "0.7.4")
    assert (out.bump, out.old, out.pitwall) == (True, "0.7.3", False)
    assert out.text == ONE.replace("newTag: 0.7.3", "newTag: 0.7.4")
    assert out.changed == "`newTag: 0.7.3` to `newTag: 0.7.4`"


def test_two_tags_are_bumped_together():
    out = plan(TWO, "0.8.0")
    assert (out.bump, out.old, out.pitwall) == (True, "0.7.3", True)
    assert out.text == TWO.replace("0.7.3", "0.8.0")
    assert out.changed == (
        "`newTag: 0.7.3` to `newTag: 0.8.0` and `newTag: 0.7.3-pitwall` to `newTag: 0.8.0-pitwall`"
    )


def test_two_tags_in_either_order():
    swapped = TWO.replace("newTag: 0.7.3\n", "newTag: X\n").replace(
        "newTag: 0.7.3-pitwall", "newTag: 0.7.3"
    )
    swapped = swapped.replace("newTag: X", "newTag: 0.7.3-pitwall")
    out = plan(swapped, "0.7.4")
    assert out.bump and out.pitwall
    assert out.text == swapped.replace("0.7.3", "0.7.4")


@pytest.mark.parametrize("text", [ONE, TWO])
@pytest.mark.parametrize("version", ["0.7.3", "0.7.2", "0.6.10"])
def test_not_older_is_left_alone(text, version):
    out = plan(text, version)
    assert (out.bump, out.old, out.text, out.changed) == (False, "0.7.3", text, "")


def test_versions_compare_as_numbers_not_strings():
    assert plan(ONE.replace("0.7.3", "0.9.0"), "0.10.0").bump


@pytest.mark.parametrize(
    "text",
    [
        "images:\n  - name: muldoon/those-who-run\n",  # none
        ONE + "    newTag: 0.7.3\n",  # two the same
        TWO + "    newTag: 0.7.3\n",  # three
        TWO.replace("0.7.3-pitwall", "0.7.2-pitwall"),  # the bases differ
        TWO.replace("0.7.3-pitwall", "0.7.3-web"),  # not -pitwall
        ONE.replace("newTag: 0.7.3", "newTag: 0.7.3-pitwall"),  # only the pit wall
        ONE.replace("newTag: 0.7.3", "newTag: latest"),  # not x.y.z
        ONE.replace("newTag: 0.7.3", 'newTag: "0.7.3"'),  # quoted
        ONE.replace("newTag: 0.7.3", "newTag: 0.7.3 # pinned"),  # a trailing comment
        ONE.replace("    newTag: 0.7.3", "  - newTag: 0.7.3"),  # a key the bump can't read
    ],
)
def test_any_other_shape_fails(text):
    with pytest.raises(ValueError, match="newTag"):
        plan(text, "0.7.4")


def test_a_comment_about_newtag_does_not_count():
    text = "# the release bumps newTag: see release.yml\n" + ONE
    assert plan(text, "0.7.4").text == text.replace("newTag: 0.7.3", "newTag: 0.7.4")


def test_version_must_be_x_y_z():
    with pytest.raises(ValueError, match="x.y.z"):
        plan(ONE, "0.7.4-rc1")


def test_crlf_line_endings_are_kept():
    text = ONE.replace("\n", "\r\n")
    assert plan(text, "0.7.4").text == text.replace("0.7.3", "0.7.4")


def test_main_rewrites_the_file_and_prints_the_plan(tmp_path, capsys):
    path = tmp_path / "kustomization.yaml"
    path.write_text(TWO)
    assert home_lab_bump.main(["0.7.4", str(path)]) == 0
    assert path.read_text() == TWO.replace("0.7.3", "0.7.4")
    lines = capsys.readouterr().out.splitlines()
    assert lines[:3] == ["bump=true", "old=0.7.3", "pitwall=true"]
    assert lines[3].startswith("changed=`newTag: 0.7.3` to `newTag: 0.7.4` and ")


def test_main_leaves_a_newer_file_alone(tmp_path, capsys):
    path = tmp_path / "kustomization.yaml"
    path.write_text(ONE)
    assert home_lab_bump.main(["0.7.3", str(path)]) == 0
    assert path.read_text() == ONE
    assert capsys.readouterr().out.splitlines() == [
        "bump=false",
        "old=0.7.3",
        "pitwall=false",
        "changed=",
    ]


def test_main_fails_with_an_annotation(tmp_path, capsys):
    path = tmp_path / "kustomization.yaml"
    path.write_text(ONE + "    newTag: 0.7.3\n")
    assert home_lab_bump.main(["0.7.4", str(path)]) == 1
    assert path.read_text() == ONE + "    newTag: 0.7.3\n"
    assert capsys.readouterr().out.startswith(f"::error::{path}: expected one newTag")
    assert home_lab_bump.main([]) == 2


def test_main_names_the_file_as_asked(tmp_path, capsys):
    path = tmp_path / "kustomization.yaml"
    path.write_text("images: []\n")
    assert home_lab_bump.main(["0.7.4", str(path), "home-lab/kustomization.yaml"]) == 1
    assert capsys.readouterr().out.startswith("::error::home-lab/kustomization.yaml: expected")
