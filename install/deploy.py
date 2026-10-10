"""Command-line entry for install.ps1; the code is equpdater/deploy.py."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater.deploy import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
