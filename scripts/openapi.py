"""Write ``web/openapi.json``, the pit wall API's schema, from the response models.

``--check`` writes nothing and exits 1 when the committed file differs from the
models (``make check`` runs it). The schema itself is built by
:func:`those_who_run.openapi.spec`; add a module's routes there.

    .venv/bin/python scripts/openapi.py          # or: make openapi
    .venv/bin/python scripts/openapi.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from those_who_run.openapi import dump, spec

OUT = Path(__file__).resolve().parent.parent / "web" / "openapi.json"


def main(argv: list[str] | None = None, out: Path = OUT) -> int:
    p = argparse.ArgumentParser(description="Write web/openapi.json from the response models.")
    p.add_argument("--check", action="store_true", help="fail if the committed file is stale")
    args = p.parse_args(argv)
    text = dump(spec())
    if args.check:
        if not out.is_file() or out.read_text(encoding="utf-8") != text:
            print(f"{out} is stale: run `make openapi` and commit it", file=sys.stderr)
            return 1
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
