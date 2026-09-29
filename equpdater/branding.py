"""Who this product is, in one place.

Every name the application answers to lives here so a rebrand is an edit to
one file rather than a hunt through six thousand lines. The previous rename
was exactly that hunt, and it left the product's own name in the user agent,
the window icon, the log heading and the config directory at four different
stages of the change.

**What is deliberately not here**: OctoWoW, octowow.st, the news feed, the
torrent, the `.octobak` shield suffix. Those name the *server and its client*,
not this updater, and renaming them would break the thing this updater
updates. `LEGACY_*` below names the product this one grew out of, and exists
only so its settings can be found and carried forward.
"""

from __future__ import annotations

import os
import sys

#: The product.
APP_NAME = "EqUpdater"
APP_TITLE = "EqUpdater"
APP_VERSION = "2.0.4"

#: Upstream, for the About box and the attribution the licence requires.
#: EqUpdater is a substantially reworked derivative of Octo Updater; see
#: NOTICE.
UPSTREAM_NAME = "Octo Updater"
PROJECT_REPO = "eqomdx/EqUpdater"
PROJECT_URL = f"https://github.com/{PROJECT_REPO}"

USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
WINDOWS_APP_ID = "eqomdx.EqUpdater.2"

#: The products whose settings this one inherits, newest first. Each is a
#: directory name under the platform's application-data root.
LEGACY_APP_DIRS = ("OctoUpdater",)

#: Pre-1.3 Octo Updater kept its config beside the executable under this name.
LEGACY_LOOSE_CONFIG = "octo_updater_config.json"

#: Marker blocks this updater writes into pfUI's saved profile. The old
#: spelling is still recognised when stripping, so a profile written by Octo
#: Updater is cleaned up correctly instead of accumulating both.
PFUI_MARK_PREFIX = "EQUPDATER"
PFUI_LEGACY_MARK_PREFIXES = ("OCTO_UPDATER",)


def app_data_dir(app_name: str = APP_NAME) -> str:
    """Where this product keeps its settings, per platform.

    Windows: %LOCALAPPDATA%\\EqUpdater. Linux/macOS: the XDG data directory,
    falling back to ~/.local/share. Never beside the executable: that breaks
    the moment the app lives somewhere read-only, which is most places an
    installer puts it."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = (os.environ.get("XDG_DATA_HOME")
                or os.path.join(os.path.expanduser("~"), ".local", "share"))
    return os.path.join(base, app_name)


def legacy_app_data_dirs() -> list:
    """Every previous product's data directory, in inheritance order."""
    return [app_data_dir(name) for name in LEGACY_APP_DIRS]


def app_dir() -> str:
    """The folder the running application sits in -- the executable's when
    frozen, the package's parent when running from source."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def icon_candidates() -> list:
    """Where the runtime window icon assets might be, best first.

    ``icon.png`` is the canonical cross-platform source used by Tk's
    ``iconphoto``. ``icon.ico`` is retained for Windows ``iconbitmap`` and
    PyInstaller's executable resource. Bundled copies are preferred over the
    source tree; a frozen executable itself is the final Windows fallback.
    """
    names = ["icon.png", "icon.ico"]
    out = []
    base = getattr(sys, "_MEIPASS", None)
    for name in names:
        if base:
            out.append(os.path.join(base, name))
        out.append(os.path.join(app_dir(), name))
    if getattr(sys, "frozen", False):
        out.append(sys.executable)
    return out


#: The window background: a still image, and the looping animation shown
#: over it when "Animated background" is on.
BACKGROUND_STATIC = "pubbles.png"
BACKGROUND_ANIMATED = "bubbles.gif"


def _asset_candidates(name: str) -> list:
    """Where a bundled (frozen) or source-tree asset may live."""
    out = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        out.append(os.path.join(base, name))
    out.append(os.path.join(app_dir(), name))
    return out


def background_candidates() -> list:
    """Where the static bubble background may live."""
    return _asset_candidates(BACKGROUND_STATIC)


def animated_background_candidates() -> list:
    """Where the looping bubble animation may live."""
    return _asset_candidates(BACKGROUND_ANIMATED)
