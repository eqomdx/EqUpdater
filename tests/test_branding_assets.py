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


if __name__ == "__main__":
    unittest.main()
