"""The Linux build uses the player's fontconfig, not a bundled one.

A fontconfig copied from the build machine (Ubuntu 22.04: 2.13) read a
Fedora tester's newer /etc/fonts and printed "invalid attribute 'xsi:nil'"
and "invalid constant used: system-ui" at every start. build.py now leaves
the font stack out; ``--self-test`` on the packaged build checks the loaded
fontconfig is the host's. These check the pieces without a build.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import build  # noqa: E402
from equpdater import platforms  # noqa: E402


class TestHostFontStack(unittest.TestCase):

    def test_the_whole_stack_is_listed(self):
        for lib in ("libfontconfig.so.1", "libfreetype.so.6", "libexpat.so.1"):
            self.assertIn(lib, platforms.HOST_FONT_STACK)

    def test_libraries_the_host_may_lack_stay_bundled(self):
        # Debian's bz2 soname is not Fedora's; zlib and the X11 libraries
        # are needed by Python and Tk themselves.
        for lib in ("libbz2.so.1.0", "libz.so.1", "libXft.so.2", "libX11.so.6"):
            self.assertNotIn(lib, platforms.HOST_FONT_STACK)

    def test_strip_removes_only_the_font_stack(self):
        internal = tempfile.mkdtemp()
        keep = ["libz.so.1", "libXft.so.2", "libtk8.6.so",
                "libfreetype-9fc94c80.so.6.20.1"]       # Pillow's own copy
        for name in list(platforms.HOST_FONT_STACK) + keep:
            open(os.path.join(internal, name), "wb").close()
        with mock.patch.object(build, "WINDOWS", False):
            removed = build.strip_host_font_stack(internal)
        self.assertEqual(sorted(removed), sorted(platforms.HOST_FONT_STACK))
        self.assertEqual(sorted(os.listdir(internal)), sorted(keep))

    def test_strip_does_nothing_on_windows(self):
        internal = tempfile.mkdtemp()
        open(os.path.join(internal, "libfontconfig.so.1"), "wb").close()
        with mock.patch.object(build, "WINDOWS", True):
            self.assertEqual(build.strip_host_font_stack(internal), [])
        self.assertEqual(os.listdir(internal), ["libfontconfig.so.1"])

    def test_loaded_library_reads_the_maps(self):
        maps = os.path.join(tempfile.mkdtemp(), "maps")
        with open(maps, "w") as f:
            f.write("7f00-7f01 r--p 00000000 08:01 123 "
                    "/tmp/.mount_EqU/usr/bin/_internal/libtk8.6.so\n"
                    "7f02-7f03 r--p 00000000 08:01 456 "
                    "/usr/lib64/libfontconfig.so.1.14.0\n"
                    "7f04-7f05 rw-p 00000000 00:00 0 \n")
        self.assertEqual(platforms.loaded_library("libfontconfig.so", maps),
                         "/usr/lib64/libfontconfig.so.1.14.0")
        self.assertIsNone(platforms.loaded_library("libnothing.so", maps))
        self.assertIsNone(platforms.loaded_library("libx", maps + ".missing"))


if __name__ == "__main__":
    unittest.main()
