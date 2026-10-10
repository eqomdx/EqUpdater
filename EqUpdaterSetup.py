"""Entry point of the Windows release installer (EqUpdater-vX.Y.Z-Windows.exe).

Built by ``python build.py --setup``; see equpdater/installer.py.
"""

import sys

from equpdater.installer import main

if __name__ == "__main__":
    sys.exit(main())
