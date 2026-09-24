"""Frozen-build entry point.

PyInstaller runs its entry script as `__main__` with no parent package, so
`equpdater/__main__.py`'s relative imports fail inside a built executable --
the app starts, raises ImportError before the window exists, and exits with
nothing on screen. (A --windowed build has no console to print it to, which
is why it looked like the exe simply did not run.)

So the frozen build starts here instead, with an absolute import.
`python -m equpdater` still goes through `equpdater/__main__.py`.
"""

from equpdater.app import EqUpdaterApp, _enable_dpi_awareness


def main() -> None:
    _enable_dpi_awareness()
    EqUpdaterApp().mainloop()


if __name__ == "__main__":
    main()
