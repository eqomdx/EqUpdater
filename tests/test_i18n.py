"""EqUpdater's own text, in every language it speaks.

The English text in the code is the key. Every literal handed to ``tr`` or
``N_`` is collected here, and each translation must cover all of them, with
the same placeholders -- a missing ``{name}`` would raise KeyError in front
of the player, and a missing message would show up as English in the middle
of German.
"""

import ast
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from equpdater import i18n  # noqa: E402

PACKAGE = os.path.join(ROOT, "equpdater")
PLACEHOLDER = re.compile(r"\{(\w*)\}")


def messages() -> set:
    """Every literal passed to tr() or N_() anywhere in the package."""
    found = set()
    for name in os.listdir(PACKAGE):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(PACKAGE, name), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) in ("tr", "N_")
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                found.add(node.args[0].value)
    return found


class TestTranslations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.messages = messages()

    def tearDown(self):
        i18n.set_language("enUS")

    def test_the_code_has_messages(self):
        self.assertGreater(len(self.messages), 250)

    def test_every_language_covers_every_message(self):
        for code, table in i18n.TRANSLATIONS.items():
            missing = sorted(self.messages - set(table))
            self.assertEqual(missing, [], f"{code} is missing translations")

    def test_no_stale_translations(self):
        """A key the code no longer uses is a translation of something that
        changed: the new English goes untranslated while this one rots."""
        for code, table in i18n.TRANSLATIONS.items():
            stale = sorted(set(table) - self.messages)
            self.assertEqual(stale, [], f"{code} has translations for text "
                                        f"the code no longer uses")

    def test_placeholders_match(self):
        for code, table in i18n.TRANSLATIONS.items():
            for english, translated in table.items():
                self.assertEqual(
                    sorted(PLACEHOLDER.findall(translated)),
                    sorted(PLACEHOLDER.findall(english)),
                    f"{code}: {english!r}")

    def test_nothing_left_blank(self):
        for code, table in i18n.TRANSLATIONS.items():
            for english, translated in table.items():
                self.assertTrue(translated.strip(), f"{code}: {english!r}")

    def test_game_language_picks_the_ui_language(self):
        self.assertEqual(i18n.ui_language("deDE"), "deDE")
        self.assertEqual(i18n.ui_language("ptBR"), "ptBR")
        self.assertEqual(i18n.ui_language("zhCN"), "zhCN")
        # No translation: English, never a half-translated window.
        self.assertEqual(i18n.ui_language("koKR"), "enUS")
        self.assertEqual(i18n.ui_language("nonsense"), "enUS")

    def test_font_choice_greyed_only_where_no_font_has_the_letters(self):
        for code in ("enUS", "deDE", "ruRU", "esES", "ptBR"):
            i18n.set_language(code)
            self.assertTrue(i18n.font_choice_matters(), code)
        i18n.set_language("zhCN")
        self.assertFalse(i18n.font_choice_matters())

    def test_tr_translates_and_fills_in(self):
        i18n.set_language("deDE")
        self.assertNotEqual(i18n.tr("Update available!"), "Update available!")
        out = i18n.tr("Delete {folder} and all of its files?", folder="pfUI")
        self.assertIn("pfUI", out)
        i18n.set_language("koKR")
        self.assertEqual(i18n.tr("Update available!"), "Update available!")

    def test_unknown_text_passes_through(self):
        """Text from elsewhere -- a server's error, an addon's notes -- has
        no translation and must come through untouched."""
        i18n.set_language("ruRU")
        self.assertEqual(i18n.tr("HTTP 503 from github.com"),
                         "HTTP 503 from github.com")


if __name__ == "__main__":
    unittest.main()
