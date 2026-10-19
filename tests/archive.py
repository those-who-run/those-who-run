"""Archived outings for tests (#197, ADR 0002).

``archived_outing("20261017-162118")`` gives the outing's ``.jsonl.gz`` from
``GT7_ARCHIVE_DIR`` (default ``~/.cache/those-who-run/outings``), downloading it
from the ``outings`` release of ``those-who-run/outings`` with ``gh`` the first time. When it
can't (no ``gh``, not logged in, offline) the test is skipped with the reason,
and ``make check`` fails on the skip: a test that needs an outing needs ``gh``
logged in, locally and in CI (``GH_TOKEN``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from those_who_run.archive import archive_dir, fetch


def archived_outing(outing_id: str) -> Path:
    path, reason = fetch(outing_id, archive_dir())
    if path is None:
        pytest.skip(f"archived outing {outing_id}: {reason}")
    return path
