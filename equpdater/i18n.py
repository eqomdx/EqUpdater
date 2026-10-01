"""EqUpdater's own words in the player's language.

EqUpdater speaks the language the game is set to (Tweaks -> Game Language).
A game language with no translation here -- Chinese -- leaves EqUpdater in
English. The language is fixed for the life of the window; changing it
restarts EqUpdater (see ``EqUpdaterApp._offer_language_restart``).

Every message is looked up by its English text, so the English in the code
stays readable and a missing translation shows English, never a blank.
Placeholders are named, ``tr("Delete {folder}?", folder=name)``, so a
translation can put them in whatever order its grammar needs.

What is *not* translated, on purpose:

- the session log. It is what gets pasted when someone asks for help, and
  the people helping read English;
- what other people wrote: news posts, addon descriptions from the
  catalogue, error text from servers and the operating system;
- names: mods, addons, files, OctoWoW, EqUpdater.

``tests/test_i18n.py`` fails when a message has no translation in any
language, or a translation's placeholders differ from the English.
"""

from __future__ import annotations

from .locales import de, es, pt_br, ru

#: Game locale code -> that language's translations. A code not listed here
#: shows English.
TRANSLATIONS = {
    "deDE": de.STRINGS,
    "esES": es.STRINGS,
    "ptBR": pt_br.STRINGS,
    "ruRU": ru.STRINGS,
}

_language = "enUS"
_strings: dict = {}


def ui_language(game_locale: str) -> str:
    """The language EqUpdater shows for a game locale: the same one, or
    English when there is no translation for it."""
    return game_locale if game_locale in TRANSLATIONS else "enUS"


def set_language(game_locale: str) -> None:
    global _language, _strings
    _language = ui_language(game_locale)
    _strings = TRANSLATIONS.get(_language, {})


def language() -> str:
    return _language


def tr(text: str, **values) -> str:
    """``text`` in the current language, with ``values`` filled in."""
    out = _strings.get(text) or text
    return out.format(**values) if values else out


def N_(text: str) -> str:
    """Marks a string for translation where it is defined (a table read at
    import time) without translating it there; it is passed through
    ``tr`` where it is shown."""
    return text
