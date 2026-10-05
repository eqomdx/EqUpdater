"""`python -m equpdater` - the entry point.

The window class lives in app.py; this exists so the package is runnable in
place, which is how the tests, a source checkout and PyInstaller all start
it. Keeping it separate means app.py has no `if __name__` block competing
with the frozen entry script."""

from .app import run


def main() -> None:
    run()


if __name__ == "__main__":
    main()
