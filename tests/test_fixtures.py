"""The fixtures folder: gzipped, reproducible, and every file in the index (#167)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from those_who_run.__main__ import main
from those_who_run.replay import read_recording, write_recording

FIXTURES = Path(__file__).parent / "fixtures"
INDEX = FIXTURES / "FIXTURES.yaml"
REPO = Path(__file__).parent.parent
FIELDS = ("file", "date", "track", "car", "kind", "outing", "source", "pins", "tests")
CASE_FIELDS = ("file", "source", "pins", "tests", "web_tests")
OUTING = re.compile(r"^\d{8}-\d{6}$")


def index_problems(folder: Path, repo: Path = REPO) -> list[str]:
    """What is wrong with the fixtures in ``folder`` against its FIXTURES.yaml."""
    index = yaml.safe_load((folder / "FIXTURES.yaml").read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = index["fixtures"]
    cases: list[dict[str, Any]] = index.get("cases") or []
    drives = [e.get("file") for e in entries]
    listed = drives + [c.get("file") for c in cases]
    present = sorted(p.name for p in folder.iterdir() if p.name != "FIXTURES.yaml")
    problems = [f"{name}: not in FIXTURES.yaml" for name in present if name not in listed]
    problems += [f"{name}: listed but missing" for name in listed if name not in present]
    problems += [f"{name}: listed twice" for name in set(listed) if listed.count(name) > 1]
    problems += [
        f"{name}: not a .jsonl.gz (thin writes gzip by default)"
        for name in present
        if not name.endswith(".jsonl.gz") and (name in drives or name not in listed)
    ]
    tests = Path(__file__).parent
    for c in cases:
        name = c.get("file")
        problems += [f"{name}: no {f}" for f in CASE_FIELDS if f not in c or c[f] in ("", [])]
        if not str(name).endswith(".json"):
            problems.append(f"{name}: a case file is .json")
        problems += [
            f"{name}: no test module {t}"
            for t in c.get("tests") or []
            if not (tests / f"{t}.py").exists()
        ]
        problems += [
            f"{name}: no web test {t}" for t in c.get("web_tests") or [] if not (repo / t).is_file()
        ]
    for e in entries:
        name = e.get("file")
        problems += [f"{name}: no {f}" for f in FIELDS if f not in e or e[f] in ("", [])]
        outing = e.get("outing")
        if outing is not None and not OUTING.match(str(outing)):
            problems.append(f"{name}: outing {outing!r} is not a YYYYMMDD-HHMMSS id")
        problems += [
            f"{name}: no test module {t}"
            for t in e.get("tests") or []
            if not (tests / f"{t}.py").exists()
        ]
    return problems


def test_every_fixture_is_indexed():
    assert index_problems(FIXTURES) == []


def test_an_unlisted_fixture_fails_the_index(tmp_path):
    (tmp_path / "FIXTURES.yaml").write_text(INDEX.read_text(encoding="utf-8"), encoding="utf-8")
    index = yaml.safe_load(INDEX.read_text(encoding="utf-8"))
    for e in index["fixtures"] + index["cases"]:
        (tmp_path / e["file"]).write_bytes(b"")
    assert index_problems(tmp_path) == []
    (tmp_path / "real-new-drive-2026-10-18.jsonl.gz").write_bytes(b"")
    (tmp_path / "real-plain-2026-10-18.jsonl").write_bytes(b"")
    (tmp_path / "more-cases.json").write_bytes(b"")
    assert index_problems(tmp_path) == [
        "more-cases.json: not in FIXTURES.yaml",
        "real-new-drive-2026-10-18.jsonl.gz: not in FIXTURES.yaml",
        "real-plain-2026-10-18.jsonl: not in FIXTURES.yaml",
        "more-cases.json: not a .jsonl.gz (thin writes gzip by default)",
        "real-plain-2026-10-18.jsonl: not a .jsonl.gz (thin writes gzip by default)",
    ]


def test_a_case_file_needs_its_tests(tmp_path):
    """Case files (#294) are JSON with no drive fields, and their tests must exist."""
    index = yaml.safe_load(INDEX.read_text(encoding="utf-8"))
    index["cases"] = [
        {"file": "a.json", "source": "s", "pins": ["p"], "tests": ["test_nope"], "web_tests": []},
        {"file": "b.yaml", "source": "s", "pins": ["p"], "tests": ["test_format_cases"]},
        {
            "file": "c.json",
            "source": "s",
            "pins": ["p"],
            "tests": ["test_format_cases"],
            "web_tests": ["web/src/lib/nope.test.ts"],
        },
    ]
    (tmp_path / "FIXTURES.yaml").write_text(yaml.safe_dump(index), encoding="utf-8")
    for e in index["fixtures"] + index["cases"]:
        (tmp_path / e["file"]).write_bytes(b"")
    assert index_problems(tmp_path) == [
        "a.json: no web_tests",
        "a.json: no test module test_nope",
        "b.yaml: no web_tests",
        "b.yaml: a case file is .json",
        "c.json: no web test web/src/lib/nope.test.ts",
    ]


def test_fixtures_are_gzip_without_a_timestamp():
    """No mtime in the gzip header: re-cutting a fixture from the same frames is no diff."""
    for p in sorted(FIXTURES.glob("*.jsonl.gz")):
        head = p.read_bytes()[:8]
        assert head[:2] == b"\x1f\x8b" and head[4:8] == b"\0\0\0\0", p.name


def test_thin_writes_gzip_by_default_and_the_same_bytes_each_time(tmp_path, capsys):
    src = FIXTURES / "real-nuc-suzuka-east-2026-10-15.jsonl.gz"
    assert main(["thin", str(src), str(tmp_path / "a.jsonl"), "--every", "2"]) == 0
    assert str(tmp_path / "a.jsonl.gz") in capsys.readouterr().out
    first = (tmp_path / "a.jsonl.gz").read_bytes()
    assert main(["thin", str(src), str(tmp_path / "a.jsonl.gz"), "--every", "2"]) == 0
    assert (tmp_path / "a.jsonl.gz").read_bytes() == first
    assert main(["thin", str(src), str(tmp_path / "b.jsonl"), "--every", "2", "--plain"]) == 0
    assert list(read_recording(tmp_path / "b.jsonl")) == list(
        read_recording(tmp_path / "a.jsonl.gz")
    )


def test_write_recording_plain_and_gzip_hold_the_same_frames(tmp_path):
    frames = list(read_recording(FIXTURES / "real-nuc-suzuka-east-2026-10-15.jsonl.gz"))
    assert write_recording(tmp_path / "x.jsonl", frames) == len(frames)
    assert write_recording(tmp_path / "x.jsonl.gz", frames) == len(frames)
    assert list(read_recording(tmp_path / "x.jsonl")) == list(
        read_recording(tmp_path / "x.jsonl.gz")
    )


def test_tracks_detect_reads_a_gzipped_recording(capsys):
    src = FIXTURES / "real-nuc-suzuka-east-2026-10-15.jsonl.gz"
    assert main(["tracks", "detect", str(src)]) == 0
    assert "result: confirmed Suzuka Circuit East Course" in capsys.readouterr().out


OUTING_FIELDS = ("id", "date", "track", "car", "kind", "frames", "sha256", "note", "cited_by")


def outing_problems(index: dict[str, Any]) -> list[str]:
    """The archive part of the index (#197): each archived outing described, every
    fixture's outing archived, and no id both archived and lost."""
    outings = index.get("outings") or []
    ids = [str(o.get("id")) for o in outings]
    lost = {str(o.get("id")) for o in index.get("lost") or []}
    problems = [f"outing {i}: listed twice" for i in set(ids) if ids.count(i) > 1]
    for o in outings:
        oid = str(o.get("id"))
        if not OUTING.match(oid):
            problems.append(f"outing {oid!r}: not a YYYYMMDD-HHMMSS id")
        problems += [f"outing {oid}: no {f}" for f in OUTING_FIELDS if f not in o]
        if not o.get("note"):
            problems.append(f"outing {oid}: no note")
    problems += [f"outing {i}: both archived and lost" for i in sorted(lost & set(ids))]
    problems += [
        f"{e['file']}: outing {e['outing']} is not archived"
        for e in index["fixtures"]
        if e.get("outing") is not None and str(e["outing"]) not in ids
    ]
    return problems


def test_archived_outings_are_indexed():
    index = yaml.safe_load(INDEX.read_text(encoding="utf-8"))
    assert outing_problems(index) == []
    # The outings #197 names as cited by the open specs: archived, or noted as lost.
    cited = {"20261016-180243", "20261017-140635", "20261017-141530", "20261017-103458"}
    cited |= {"20261017-143142", "20261017-162118"}
    known = {str(o["id"]) for o in index["outings"]} | {str(o["id"]) for o in index["lost"]}
    assert cited <= known


def test_a_fixture_outing_that_is_not_archived_fails():
    index = yaml.safe_load(INDEX.read_text(encoding="utf-8"))
    index["outings"] = [o for o in index["outings"] if o["id"] != "20261017-141530"]
    assert outing_problems(index) == [
        "real-nuc-willow-springs-pit-stop-2026-10-17.jsonl.gz: outing 20261017-141530 "
        "is not archived"
    ]
