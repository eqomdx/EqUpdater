# Installing EqUpdater

> **Players and testers: you do not need this folder.** Download
> `EqUpdater-vX.Y.Z-Windows.exe` (Windows installer) or
> `EqUpdater-vX.Y.Z-Linux-x86_64.AppImage` from the
> [Releases page](https://github.com/eqomdx/EqUpdater/releases/latest) -
> or, to test a pull request, from its **Release** workflow run's
> artifacts on GitHub Actions - and run it. Those are built and
> self-tested by CI and are what users get. Everything below builds
> EqUpdater from source on your own PC, which is for developers; a
> hand-made build (a `dist/EqUpdater` folder with `EqUpdater.exe` and
> `_internal`) is not the release and should not be used to test one.

**Windows — from source.** Download this repository (green *Code* button →
*Download ZIP*), unpack it, open the `install` folder and double-click
**`INSTALL.cmd`**.

It installs Python for you if you do not have it, checks the source, builds
EqUpdater, installs it to `%LOCALAPPDATA%\Programs\EqUpdater\EqUpdater.exe`
and offers a desktop shortcut. No administrator rights; safe to run again.

**Updating is the same thing.** Run the new version's `INSTALL.cmd`: it
replaces the app in `%LOCALAPPDATA%\Programs\EqUpdater` and points every
EqUpdater shortcut there - desktop, Start menu, pinned to the taskbar,
including the ones older versions made into their own download folders.
Your settings and everything EqUpdater keeps track of stay in
`%LOCALAPPDATA%\EqUpdater`, untouched. The replacement is staged
(`EqUpdater.new` is built beside the old copy, which is only moved aside to
`EqUpdater.old` once the new one is complete, and moved back if the swap
fails), so a failed update leaves the version you had. Close EqUpdater
first; if it is open the installer says so and changes nothing. Old download
folders are left alone and can be deleted - see `install/deploy.py`.

Every run keeps a log from its very first line: `<date>-installer.log` in
`%LOCALAPPDATA%\EqUpdater\install-logs` (or `%TEMP%\EqUpdater\install-logs`
if that folder cannot be written). If anything fails, the installer says what
went wrong and prints the log's path - send that file when asking for help.

**If your antivirus removes EqUpdater.exe during the build**, the installer
says so ("The build was interrupted by antivirus software"), shows Windows
Defender's record of it if Defender was responsible, and stops. PyInstaller-
built programs are a common false positive. Allow or restore `EqUpdater.exe`
in Windows Security -> Virus & threat protection -> Protection history (or
your antivirus's quarantine), or exclude the EqUpdater folder, then run the
installer again.

**The test suite is not part of installing.** It guards EqUpdater's safety
rules, and it runs in CI on every change and before every release build
(`python build.py --release`). It is not run on your PC during install, where
a GUI or timing test behaving differently on one machine could stop you
installing the program. Developers can still run it here with `-RunTests`.

**It installs a folder, not a loose .exe.** `EqUpdater.exe` needs the
`_internal` directory beside it, so start it from the shortcut. That is on purpose: a one-file build unpacks ~30 MB into `%TEMP%`
on every launch and will not start at all when the system drive is full —
which is a real state for anyone who keeps games on C:. `python build.py
--onefile` still makes the portable single file if you want it.

**Windows — from PowerShell**

```powershell
.\install\install.ps1
```

`-NoBuild` sets up the dependencies only. `-NoShortcut` does not offer a new
desktop shortcut (existing EqUpdater shortcuts are still corrected). `-Yes` answers every prompt. `-RunTests` runs the full test suite
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
