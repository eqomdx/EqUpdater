# Installing EqUpdater

**Windows — the easy way.** Download this repository (green *Code* button →
*Download ZIP*), unpack it, open the `install` folder and double-click
**`INSTALL.cmd`**.

It installs Python for you if you do not have it, checks the source, builds
`dist\EqUpdater\EqUpdater.exe`, and offers a desktop shortcut. No
administrator rights; safe to run again.

Every run keeps a log from its very first line: `<date>-installer.log` in
`%LOCALAPPDATA%\EqUpdater\install-logs` (or `%TEMP%\EqUpdater\install-logs`
if that folder cannot be written). If anything fails, the installer says what
went wrong and prints the log's path - send that file when asking for help.

**The test suite is not part of installing.** It guards EqUpdater's safety
rules, and it runs in CI on every change and before every release build
(`python build.py --release`). It is not run on your PC during install, where
a GUI or timing test behaving differently on one machine could stop you
installing the program. Developers can still run it here with `-RunTests`.

**It builds a folder, not a loose .exe.** `EqUpdater.exe` needs the
`_internal` directory beside it, so move the whole folder or use the
shortcut. That is on purpose: a one-file build unpacks ~30 MB into `%TEMP%`
on every launch and will not start at all when the system drive is full —
which is a real state for anyone who keeps games on C:. `python build.py
--onefile` still makes the portable single file if you want it.

**Windows — from PowerShell**

```powershell
.\install\install.ps1
```

`-NoBuild` sets up the dependencies only. `-NoShortcut` skips the desktop
shortcut. `-Yes` answers every prompt. `-RunTests` runs the full test suite
first and does not build if it fails.

**Linux / macOS, or if you would rather do it by hand**

```sh
python3 -m pip install --user pyinstaller certifi pillow
python3 build.py
```

## For developers

```sh
python tools/check.py             # the whole suite; prints only what failed
python build.py --release         # runs the suite first, builds only if it passes
```

`tools/check.py` runs the tests in a child process, so even a hard crash
(Tcl aborting on a Tk object freed on the wrong thread, say) is reported with
the test that was running and every thread's stack, instead of ending the run
silently.

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
