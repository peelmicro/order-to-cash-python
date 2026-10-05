"""Entry point of the one-shot seed job (a CLI, not an HTTP service): `python -m otc_seed`."""

import sys

from otc_seed.presentation.cli import main

if __name__ == "__main__":
    sys.exit(main())
