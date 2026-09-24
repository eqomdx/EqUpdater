# EqUpdater development handoff

**Version:** 2.0.1  
**Date:** 2026-09-24  
**Project:** EqUpdater, derived from rebasedkon/octo-updater  
**Repository:** https://github.com/eqomdx/EqUpdater

## Current product direction

EqUpdater is no longer just an Octo Updater skin. The current branch has the safer updater model plus the blue underwater visual overhaul. Preserve these principles when making further changes:

- never automatically downgrade a known local version;
- only Update All components that EqUpdater manages and can safely prove are newer;
- unmanaged/manual addons stay unmanaged until explicitly adopted;
- locally modified, divergent, local-newer, ignored, unknown, or source-changed components are held back;
- `dlls.txt` registration repair is allowed without replacing the DLL itself.

## Current UI

- Full-window `bubbles.jpg` background.
- Dark navy panels over the background.
- Reusable Canvas gradient buttons for PLAY / UPDATE / UPDATE ALL.
- The one-pixel/right-edge gap in the gradient button fill is fixed.
- Settings support heading is now **SUPPORT ME**.
- The old bottom attribution/support strip has been removed from Settings.
- Buy Me a Coffee opens `https://ko-fi.com/equadis`.

## Icon / Windows taskbar

The canonical source is `icon.png` and must remain the supplied pink octopus + wrench image.

Current SHA-256 of `icon.png`:

`605efe13b379d9c722e0ce0b630b40988e9f4e285b2d3d36c8ee20d3676c839c`

`icon.ico` is regenerated from that image and contains:

`16, 20, 24, 32, 40, 48, 64, 96, 128, 256 px`

`build.py` uses `icon.ico` for the PyInstaller executable and adds both `icon.ico` and `icon.png` as runtime data.

The runtime uses `iconphoto()` with `icon.png` first, then `iconbitmap()`/ICO as fallback.

Windows also receives this explicit AppUserModelID before Tk creates the window:

`eqomdx.EqUpdater.2`

This was added specifically to stop Windows reusing the old Octo/EqUpdater taskbar group/icon cache.

If a user has an old *pinned* shortcut, Windows may still show that pinned shortcut's cached icon until it is unpinned/re-pinned, but the running process now has its own taskbar identity and current icon.

## Fonts

Font choices in Settings:

1. Friz Quadrata — default
2. Arial
3. OpenDyslexic

OpenDyslexic currently uses a `0.92` size multiplier because 1.00 overflowed fixed-height UI and 0.82 was too small.

EqUpdater privately registers `.ttf` / `.otf` files on Windows using `AddFontResourceExW(..., FR_PRIVATE, ...)`; it does not need an administrator/system-wide font install.

The user supplied these original font archives during development:

- `friz-quadrata.zip`
  - SHA-256 `54f39851b404db8eba76c80036c0e05517b18937c5e8edbebd71bf253cea3de8`
- `arial.zip`
  - SHA-256 `7fc73d5da7bedf99fa53f02f55a46eebd0c6332de90235683c7c568e721fc20f`
- `opendyslexic-0.92.zip`
  - SHA-256 `fdca7495b639878ab0489ff7ecf4e8e3f350e5f9c2de63f8ee9d6214ead75a15`

The returned source package does not redistribute font binaries. Instead:

- `install/install.ps1` automatically searches the project directory, Downloads, Desktop and Documents for those archive patterns and extracts their `.ttf/.otf` files to `%LOCALAPPDATA%\EqUpdater\fonts` before building.
- `equpdater/ui.py` repeats archive discovery at runtime in the project/app directory, EqUpdater app-data directory, Downloads and Desktop.
- `FontManager` detects the actual installed/privately registered family name before enabling a font choice.

Embedded family names verified during this work:

- Friz: `Friz Quadrata`
- Arial: `Arial`
- OpenDyslexic: `OpenDyslexic`

Do not silently present OpenDyslexic while rendering a fallback family.

## News / changelog

`equpdater/news.py` owns News fetching/parsing.

Primary source is OctoWoW's public `octonews.php` JSON endpoint, matching the upstream launcher's mechanism:

- Announcements: forum 2, full/latest post
- Patch Notes & Changelog: forum 4, recent list

HTML/phpBB scraping remains as a fallback and is intentionally more tolerant than the earlier `topictitle`-only parser.

The app keeps the last successful News data in config and renders cache immediately, refreshing in a worker thread.

Important: the hosted endpoint could not be directly fetched from the development web sandbox, so final live verification still needs to be done by running EqUpdater on the user's machine. If News still fails, use the session log and inspect the exact HTTP/JSON error before changing the parser again.

## Important files

- `equpdater/app.py` — Tk app, panels, settings, mods/addons UI, footer/update flows
- `equpdater/ui.py` — FontManager, private font loading, background/gradient UI helpers
- `equpdater/news.py` — announcements/changelog fetching and parsing
- `equpdater/planner.py` — central safe update planning
- `equpdater/versions.py` — version comparison
- `equpdater/gitcompare.py` — source/commit ancestry checks
- `equpdater/hashing.py` — content fingerprints
- `equpdater/config.py` — schema/provenance/migration
- `equpdater/branding.py` — product identity, paths, icon candidates, Windows App ID
- `build.py` — canonical PyInstaller build
- `install/install.ps1` — Windows one-click install/build/test/font import
- `tests/` — safety, migration, news and GUI smoke tests

## Current tests

Latest validation:

`Ran 157 tests ... OK` (Windows, 2026-09-24, after the consent and texture-pack pass)

Command used in a virtual display:

`xvfb-run -a python -m unittest discover -s tests -t .`

The Windows installer also runs the suite before building. It intentionally decides success from Python's exit code rather than treating unittest's stderr output as a PowerShell error.

## Consent and texture-pack sources (2026-09-24, second pass)

Closes the two remaining points of the "manage only what you were given"
feedback.

**DLLs are opt-in.** `auto_install_mods` defaults to `False` everywhere. The
first time a client is usable, `_ask_essential_mods` asks once (VanillaFixes
included, no exemption), stores `essential_mods_asked` and the answer; the
Settings toggle also counts as an answer. `config._CARRY_KEYS` no longer
carries Octo Updater's `auto_install_mods`.

**Fixed on the way: discovered DLLs were overwritten.** Discovery recorded
existing mods as unmanaged, enabled, no version; `_apply_mods_worker` read
that as "wanted, not installed" and installed over them on any Apply,
including the first-run one. The worker now refuses to install over files on
disk it does not own (unless `force`, or the record carries a failed-install
error), and `_install_missing_essential_mods` skips them. Fresh installs now
write a full `new_mod_record` with a fingerprint.

**Texture packs can be linked to a source.** `equpdater/mpq.py` is the pure
logic (parse, pick release asset, judge, settle), tested in
`tests/test_mpq.py`. Sources: catalogue entry, GitHub/Codeberg latest release
(optionally a named asset), or a `dl.octowow.st` URL with a `.sha256`
sidecar. Only linked packs are checked. A link whose bytes match the source
is tracked like an install; one that differs is `sourceDiffers` and never
updated; a release with no digest is `unconfirmed`. **Replace…** renames the
old file to `<file>.<stamp>.bak` in Data. Old `mpq` records (managed + sha +
url) read as catalogue installs.

## Historical bugs already fixed

Do not reintroduce these:

- Tk `_poll()` callback surviving destruction and emitting `invalid command name ..._poll`.
- PowerShell installer aborting because unittest writes normal progress to stderr.
- DLL update logic treating `remote != installed` as an update and downgrading local-newer versions.
- Catalog-matched manual addons being automatically taken over.
- different Git SHA being assumed to mean remote-newer.
- recommended repository changes being treated as normal updates.
- old `OctoUpdater.ico` / `EqUpdater.ico` resource naming.
- PLAY gradient leaving a narrow unpainted strip at its right edge.
- OpenDyslexic at 0.82 scale being too small.
- Settings bottom attribution/support strip taking space and becoming unreadably small.
- Essential mods (and VanillaFixes unconditionally) installed without asking.
- Apply installing over a discovered, unmanaged DLL.
- Unlinked texture packs compared with the catalogue by file name.

## Next recommended checks

1. Build on Windows with `install\INSTALL.cmd`.
2. Confirm the new octopus/wrench icon in:
   - Explorer executable icon
   - title bar
   - running taskbar button
   - newly-created desktop shortcut
3. Open Settings and confirm `SUPPORT ME`.
4. Confirm Friz, Arial and OpenDyslexic all switch live and persist after restart.
5. Confirm OpenDyslexic fits the fixed 1000×700 design at Windows 100%, 125% and 150% scaling.
6. Verify Announcements and Changelog against the live OctoWoW service and capture the session log if either still fails.
7. Only after those checks, push the packaged changes to `eqomdx/EqUpdater`.
