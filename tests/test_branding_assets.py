"""Regression checks for user-visible EqUpdater branding assets."""

import hashlib
import os
import unittest

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECTED_ICON_SHA256 = "605efe13b379d9c722e0ce0b630b40988e9f4e285b2d3d36c8ee20d3676c839c"
EXPECTED_ICO_SIZES = {
    (16, 16), (20, 20), (24, 24), (32, 32), (40, 40),
    (48, 48), (64, 64), (96, 96), (128, 128), (256, 256),
}


class TestBrandingAssets(unittest.TestCase):
    def test_canonical_icon_is_the_supplied_octopus_wrench_asset(self):
        path = os.path.join(ROOT, "icon.png")
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(digest, EXPECTED_ICON_SHA256)

    def test_windows_icon_has_all_required_sizes(self):
        path = os.path.join(ROOT, "icon.ico")
        with Image.open(path) as im:
            self.assertEqual(set(im.ico.sizes()), EXPECTED_ICO_SIZES)

    def test_old_support_heading_does_not_return(self):
        path = os.path.join(ROOT, "equpdater", "app.py")
        with open(path, encoding="utf-8") as f:
            source = f.read()
        self.assertIn('text="SUPPORT ME"', source)
        self.assertNotIn('text="SUPPORT EQUPDATER"', source)

    def test_opendyslexic_scale_stays_readable(self):
        from equpdater.ui import FONT_SIZE_SCALE
        self.assertGreaterEqual(FONT_SIZE_SCALE["opendyslexic"], 0.90)
        self.assertLessEqual(FONT_SIZE_SCALE["opendyslexic"], 0.95)

    def test_font_registration_never_broadcasts(self):
        """A WM_FONTCHANGE broadcast waits on every window on the desktop;
        one busy game window hung EqUpdater before its window appeared."""
        import ctypes
        import tempfile
        from unittest import mock
        from equpdater import ui
        calls = []

        class FakeDLL:
            def __init__(self, name, **kw):
                self.name = name

            def __getattr__(self, fn):
                def call(*args):
                    calls.append((self.name, fn))
                    return 1
                return call

        with tempfile.NamedTemporaryFile(suffix=".ttf", delete=False) as f:
            font = f.name
        try:
            with mock.patch.object(ui.os, "name", "nt"), \
                 mock.patch.object(ctypes, "WinDLL", FakeDLL, create=True), \
                 mock.patch.object(ui, "_bundled_font_paths", lambda: [font]), \
                 mock.patch.object(ui, "_REGISTERED_PRIVATE_FONTS", set()):
                ui._register_private_fonts()
        finally:
            os.remove(font)
        self.assertIn(("gdi32", "AddFontResourceExW"), calls)
        self.assertFalse([c for c in calls if c[1].startswith(("SendMessage",
                                                                "PostMessage"))])

    def test_fonts_ship_with_the_app(self):
        """Every choice works on a fresh PC: the faces are in the source tree,
        build.py packs that folder, and the app registers what is in it."""
        fonts = os.path.join(ROOT, "fonts")
        for name in ("FrizQuadrata-Regular.ttf", "OpenDyslexic-Regular.otf",
                     "OpenDyslexic-Bold.otf", "OpenDyslexic-OFL.txt"):
            self.assertTrue(os.path.isfile(os.path.join(fonts, name)), name)
        with open(os.path.join(ROOT, "build.py"), encoding="utf-8") as f:
            self.assertIn('"--add-data", FONTS_DIR', f.read())
        from equpdater import ui
        shipped = {os.path.basename(p) for p in ui._bundled_font_paths()}
        self.assertIn("FrizQuadrata-Regular.ttf", shipped)
        self.assertIn("OpenDyslexic-Regular.otf", shipped)

    def test_no_hunting_through_the_users_folders(self):
        """Fonts used to be fished out of zips in Downloads, Desktop and
        Documents. They ship now; nothing should go looking."""
        from equpdater import ui
        self.assertFalse(hasattr(ui, "_extract_local_font_archives"))
        with open(os.path.join(ROOT, "install", "install.ps1"),
                  encoding="utf-8") as f:
            self.assertNotIn("font archive", f.read().lower())


if __name__ == "__main__":
    unittest.main()
