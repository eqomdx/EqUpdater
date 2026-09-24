# Installing EqUpdater

**Windows — the easy way.** Download this repository (green *Code* button →
*Download ZIP*), unpack it, open the `install` folder and double-click
**`INSTALL.cmd`**.

It installs Python for you if you do not have it, runs the test suite, builds
`EqUpdater.exe` in the project folder, and offers a desktop shortcut. No
administrator rights; safe to run again.

**Windows — from PowerShell**

```powershell
.\install\install.ps1
```

`-NoBuild` sets up the dependencies only. `-NoShortcut` skips the desktop
shortcut. `-Yes` answers every prompt.

**Linux / macOS, or if you would rather do it by hand**

```sh
python3 -m pip install --user pyinstaller certifi
python3 -m unittest discover -s tests
python3 build.py
```

Or skip the executable entirely and run it from source:

```sh
python3 -m equpdater
```

## What the installer does not do

It does not go near your game folder. The previous updater's installer found
your client, backed it up, rewrote its config and patched its own source
before building — EqUpdater does none of that at install time. It finds the
client itself, and imports your Octo Updater settings on first launch, where
you can see it happen and undo it.
