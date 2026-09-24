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
                 mock.patch.object(ui, "_extract_local_font_archives", lambda: None), \
                 mock.patch.object(ui, "_bundled_font_paths", lambda: [font]), \
                 mock.patch.object(ui, "_REGISTERED_PRIVATE_FONTS", set()):
                ui._register_private_fonts()
        finally:
            os.remove(font)
        self.assertIn(("gdi32", "AddFontResourceExW"), calls)
        self.assertFalse([c for c in calls if c[1].startswith(("SendMessage",
                                                                "PostMessage"))])

    def test_mac_metadata_stubs_are_not_imported_as_fonts(self):
        """The supplied OpenDyslexic archive carries __MACOSX/._*.otf stubs."""
        import shutil
        import tempfile
        import zipfile
        from unittest import mock
        from equpdater import ui
        tmp = tempfile.mkdtemp(prefix="equ-fonts-")
        try:
            with zipfile.ZipFile(os.path.join(tmp, "opendyslexic-0.92.zip"), "w") as zf:
                zf.writestr("OpenDyslexic-Regular.otf", b"font")
                zf.writestr("__MACOSX/._OpenDyslexic-Regular.otf", b"stub")
            data = os.path.join(tmp, "data")
            with mock.patch.object(ui.branding, "app_dir", lambda: tmp), \
                 mock.patch.object(ui.branding, "app_data_dir", lambda *a: data), \
                 mock.patch.object(ui.os.path, "expanduser", lambda p: tmp):
                ui._extract_local_font_archives()
            self.assertEqual(os.listdir(os.path.join(data, "fonts")),
                             ["OpenDyslexic-Regular.otf"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
