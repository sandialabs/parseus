#!/usr/bin/env python3
"""Compatibility wrapper for the standalone Parseus deployment manager.

This deployment tooling is standard-library only and runs on the host with
Python 3.8 or later. That is separate from the Parseus application source under
``src/``, which requires Python 3.11 - 3.13 (see ``pyproject.toml``).
"""

import sys

# Keep this check (and everything above it) free of syntax newer than Python 3.x
# basics, so an interpreter that is too old reports a clear message instead of
# a SyntaxError/ImportError from the package below.
if sys.version_info < (3, 8):
    sys.stderr.write(
        "manage_parseus requires Python 3.8 or later "
        "(found {}.{}.{}).\n".format(*sys.version_info[:3])
    )
    raise SystemExit(1)

from manage_parseus_lib.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
