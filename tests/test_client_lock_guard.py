"""The updater refuses to patch a client whose files it cannot write.

`patch_exe` opens WoW.exe with `"wb"`, which truncates the moment it succeeds,
and the sync replaces files across the whole client directory. Both used to
begin work and find out about a running game partway through -- and a sync that
has replaced some of the client and left the rest is a worse state than one that
never started.

Windows locks a running executable against writing, so the question "is the game
open" and the question "can I write this file" have the same answer and only the
second one can be asked exactly. These tests use a read-only file to produce that
answer, which is the same refusal for the same reason.
"""

import os
import queue
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equpdater.app import CLOSE_THE_GAME, UpdateWorker, client_exe_locked


class ClientExeLockTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="equpd-lock-")
        self.exe = os.path.join(self.dir, "WoW.exe")

    def tearDown(self):
        if os.path.exists(self.exe):
            os.chmod(self.exe, stat.S_IWRITE | stat.S_IREAD)

    def write_exe(self):
        with open(self.exe, "wb") as f:
            f.write(b"MZ" + b"\0" * 64)

    def test_no_client_is_not_locked(self):
        """An empty folder is not a locked client.

        A directory with no WoW.exe is a first install, and refusing that would
        stop the one case where there is nothing to protect.
        """
        self.assertFalse(client_exe_locked(self.dir))

    def test_writable_exe_is_not_locked(self):
        self.write_exe()
        self.assertFalse(client_exe_locked(self.dir))

    def test_unwritable_exe_is_locked(self):
        self.write_exe()
        os.chmod(self.exe, stat.S_IREAD)

        if os.name != "nt" and os.geteuid() == 0:
            self.skipTest("root ignores the read-only bit")

        self.assertTrue(client_exe_locked(self.dir))

    def test_the_check_does_not_touch_the_file(self):
        """It opens for writing and writes nothing.

        The function exists to protect the bytes in this file, so a version of
        it that truncated on the way past would be the bug it is meant to stop.
        """
        self.write_exe()
        before = open(self.exe, "rb").read()

        client_exe_locked(self.dir)

        self.assertEqual(open(self.exe, "rb").read(), before)

    def test_sync_stops_before_it_fetches_anything(self):
        """The guard is the first thing the sync does.

        Asserted by running a worker against a locked client and requiring it to
        come back having said so. If this ever regresses, the sync reaches the
        network and the first sign of trouble is a half-replaced client.
        """
        self.write_exe()
        os.chmod(self.exe, stat.S_IREAD)

        if os.name != "nt" and os.geteuid() == 0:
            self.skipTest("root ignores the read-only bit")

        log_q, prog_q = queue.Queue(), queue.Queue()
        UpdateWorker(self.dir, log_q, prog_q).run()

        said = []
        while not log_q.empty():
            said.append(log_q.get()[0])

        self.assertTrue(any(CLOSE_THE_GAME in line for line in said),
                        f"the sync did not refuse; it said: {said}")
        # And it ends like any failed update, or the window never leaves its
        # "updating" state.
        self.assertEqual(said[-1], "__ERROR__")
        self.assertNotIn("__DONE__", said)

    def test_the_message_names_both_causes(self):
        """It cannot know which of the two it is, so it says both.

        The check answers "can I write this file". A running game is nearly
        always why, but a read-only file gives the same answer, and telling
        somebody to close a game they have already closed is a dead end.
        """
        self.assertIn("Close World of Warcraft", CLOSE_THE_GAME)
        self.assertIn("read-only", CLOSE_THE_GAME)


if __name__ == "__main__":
    unittest.main()
