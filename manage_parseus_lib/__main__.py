import sys

# Same guard as manage_parseus.py, for ``python -m manage_parseus_lib``.
if sys.version_info < (3, 8):
    sys.stderr.write(
        "manage_parseus requires Python 3.8 or later "
        "(found {}.{}.{}).\n".format(*sys.version_info[:3])
    )
    raise SystemExit(1)

from manage_parseus_lib.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
