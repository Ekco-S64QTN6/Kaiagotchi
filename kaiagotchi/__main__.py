"""Module entry point for Kaiagotchi.

Allows launching the full agent via ``python -m kaiagotchi``. This simply
delegates to :func:`kaiagotchi.cli.run`, the canonical launcher also used by
the ``kaiagotchi`` console script and ``python -m kaiagotchi.cli``.
"""

import sys

from kaiagotchi.cli import run

if __name__ == "__main__":
    sys.exit(run())
