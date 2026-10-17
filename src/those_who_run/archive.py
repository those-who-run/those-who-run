"""The outing archive: the recordings specs and tests rely on, kept off the NUC.

The NUC keeps only the newest ``GT7_RECORD_KEEP`` outings. ``recordings archive``
copies one into the archive directory (``GT7_ARCHIVE_DIR``) with a sidecar
``<id>.json`` that says what it is: track, car, session kinds, the sessions in
it, a note and the issues that cite it. The directory is mirrored to the
``outings`` release of this repository (ADR 0002): ``make archive-push`` uploads
it and ``fetch`` (or ``make archive-pull``) brings outings back.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RELEASE_TAG = "outings"
OUTING_ID = re.compile(r"^\d{8}-\d{6}$")


def archive_dir(env: Mapping[str, str] | None = None) -> Path:
    e = os.environ if env is None else env
    if e.get("GT7_ARCHIVE_DIR"):
        return Path(e["GT7_ARCHIVE_DIR"])
    return Path.home() / ".cache" / "those-who-run" / "outings"


@dataclass
class ArchivedOuting:
    id: str
    sha256: str
    bytes: int
    frames: int
    date: str  # YYYY-MM-DD, UTC, from the id
    tracks: list[str]
    cars: list[str]
    kinds: list[str]  # "lap_race (rolling)", one per distinct kind
    sessions: list[str]  # the ``recordings`` line for each session
    note: str
    issues: list[int] = field(default_factory=list)
    archived_at: str = ""

    @property
    def file(self) -> str:
        return f"{self.id}.jsonl.gz"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ArchivedOuting:
        names = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in names})

    def line(self) -> str:
        what = " · ".join(
            p for p in ("/".join(self.tracks), "/".join(self.cars), ", ".join(self.kinds)) if p
        )
        cites = " ".join(f"#{n}" for n in self.issues)
        size = f"{self.bytes / 1e6:.1f} MB"
        return "  ".join(p for p in (self.id, what, f"{self.frames} frames", size, cites) if p)


def sidecar(directory: Path, outing_id: str) -> Path:
    return Path(directory) / f"{outing_id}.json"


def outing_id(path: Path) -> str:
    """The outing id from a recorder file name (``20261017-162118.jsonl.gz``)."""
    stem = Path(path).name.split(".", 1)[0]
    if not OUTING_ID.match(stem):
        raise ValueError(f"{path}: not an outing recording (expected YYYYMMDD-HHMMSS.jsonl.gz)")
    return stem


def find_outing(ref: str | Path, record_dir: Path | None) -> Path:
    """A recording path, or an outing id looked up in ``record_dir``."""
    path = Path(ref)
    if path.exists():
        return path
    if record_dir is not None and OUTING_ID.match(str(ref)):
        for name in (f"{ref}.jsonl.gz", f"{ref}.jsonl"):
            if (Path(record_dir) / name).exists():
                return Path(record_dir) / name
    raise FileNotFoundError(f"{ref}: no such recording (in GT7_RECORD_DIR or as a path)")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _frames(path: Path) -> int:
    opener: Any = gzip.open if path.name.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _unique(values: Iterable[str | None]) -> list[str]:
    return list(dict.fromkeys(v for v in values if v))


def describe(path: Path) -> dict[str, Any]:
    """Track, car, session kinds and one line per session, as ``recordings`` sees them."""
    from those_who_run.recordtools import summarise_recording

    sessions, _ = summarise_recording(path)
    summaries = [s.summary for s in sessions]

    def kind(s: Mapping[str, Any]) -> str | None:
        k = s.get("session_kind") or {}
        return f"{k['kind']} ({k.get('start', 'unknown')})" if k.get("kind") else None

    return {
        "tracks": _unique((s.get("track") or {}).get("name") for s in summaries),
        "cars": _unique(s.get("car_name") for s in summaries),
        "kinds": _unique(kind(s) for s in summaries),
        "sessions": [s.line() for s in sessions],
    }


def archive_outing(
    source: Path,
    directory: Path,
    note: str = "",
    issues: Iterable[int] = (),
    clock: Any = time.time,
) -> ArchivedOuting:
    """Copy an outing into ``directory`` and write its sidecar. Archiving the same
    outing again keeps the file, adds the issues and replaces the note if one is
    given."""
    oid = outing_id(source)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / f"{oid}.jsonl.gz"
    if source.name.endswith(".gz"):
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(source, tmp)
    else:  # a plain recording: archive it gzipped like the recorder writes it
        tmp = dest.with_name(dest.name + ".part")
        with open(source, "rb") as src, gzip.GzipFile(tmp, "wb", mtime=0) as out:
            shutil.copyfileobj(src, out)
    os.replace(tmp, dest)

    old = list_archive(directory, only=oid)
    previous = old[0] if old else None
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))
    entry = ArchivedOuting(
        id=oid,
        sha256=_sha256(dest),
        bytes=dest.stat().st_size,
        frames=_frames(dest),
        date=f"{oid[:4]}-{oid[4:6]}-{oid[6:8]}",
        note=note or (previous.note if previous else ""),
        issues=sorted(set(issues) | set(previous.issues if previous else ())),
        archived_at=previous.archived_at if previous else stamp,
        **describe(dest),
    )
    path = sidecar(directory, oid)
    path.write_text(json.dumps(asdict(entry), indent=2, ensure_ascii=False) + "\n", "utf-8")
    return entry


def list_archive(directory: Path, only: str | None = None) -> list[ArchivedOuting]:
    directory = Path(directory)
    if not directory.is_dir():
        return []
    names = [sidecar(directory, only)] if only else sorted(directory.glob("*.json"))
    return [ArchivedOuting.from_dict(json.loads(p.read_text("utf-8"))) for p in names if p.exists()]


def fetch(oid: str, directory: Path, repo: str | None = None) -> tuple[Path | None, str]:
    """The archived outing ``oid`` as a local file, downloading it from the
    ``outings`` release with ``gh`` if it is not in ``directory`` yet. Returns the
    path, or None and the reason it is not available."""
    if not OUTING_ID.match(oid):
        return None, f"{oid!r} is not an outing id"
    directory = Path(directory)
    path = directory / f"{oid}.jsonl.gz"
    if not path.exists():
        gh = shutil.which("gh")
        if gh is None:
            return None, f"not in {directory}, and no gh to download it from the archive"
        directory.mkdir(parents=True, exist_ok=True)
        cmd = [gh, "release", "download", RELEASE_TAG, "-D", str(directory), "--clobber"]
        cmd += ["-p", path.name, "-p", f"{oid}.json"] + (["-R", repo] if repo else [])
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"gh release download failed: {exc}"
        if done.returncode != 0 or not path.exists():
            return None, f"gh release download failed: {done.stderr.strip() or done.returncode}"
    known = list_archive(directory, only=oid)
    if known and known[0].sha256 != _sha256(path):
        return None, f"{path} does not match the sha256 in its sidecar"
    return path, ""
