"""``python -m those_who_run`` and the ``those-who-run`` script.

The commands live in :mod:`those_who_run.cli`, one module each.
"""

import sys

from those_who_run.cli import build_parser, main

__all__ = ["build_parser", "main"]

if __name__ == "__main__":
    sys.exit(main())
