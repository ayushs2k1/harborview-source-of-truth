"""Allow ``python -m sot``."""

import sys

from sot.cli import main

if __name__ == "__main__":
    sys.exit(main())
