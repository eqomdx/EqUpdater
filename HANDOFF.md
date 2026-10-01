# EqUpdater development handoff

**Version:** 2.0.5  
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

- Full-window background: `bubbles.gif` animated (default), `pubbles.png`
  static. Settings → **Animated background** (config `animated_background`,
  default true). `ui.AnimatedBackground` decodes/scales/darkens frames on a
  worker thread into a 4-frame queue; the Tk thread only pastes one
  PhotoImage per frame on an `after()` clock (the current GIF is 80-100 ms
  per frame, a 52 s loop; 0% CPU when off or minimised). Any failure logs and
  restores the PNG. `bubbles.jpg` retired.
- Edge fades (`ui.edge_fade_layers`) are baked into the still and every
  frame: the top eases to dark over 120 px, the bottom over the footer plus
  70 px. The header is drawn on the background canvas itself (it used to be
  a separate canvas with a still crop, which showed a hard line once the
  background moved), and the footer's status, version, progress bar and
  text are canvas items over the fade -- there is no solid footer block.
  `_layout_footer()` re-places them from the font's line height.
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

1. Arial — default (a saved choice still wins)
2. Friz Quadrata
3. OpenDyslexic

The FONT section sits under GENERAL in Settings' right column; the panel
grows to fit (`_fit_settings_panel`), which keeps all three reachable in
OpenDyslexic (650 of a possible 680 px at 100% scaling).

OpenDyslexic currently uses a `0.92` size multiplier because 1.00 overflowed fixed-height UI and 0.82 was too small.

EqUpdater privately registers `.ttf` / `.otf` files on Windows using `AddFontResourceExW(..., FR_PRIVATE, ...)`; it does not need an administrator/system-wide font install.

**The fonts ship with EqUpdater** (2026-10-01). `fonts/` holds Friz
Quadrata (Regular, BoldItalic) and OpenDyslexic 0.990 (four styles) with its
OFL licence; `build.py` packs the folder into `_internal/fonts`, and
`_bundled_font_paths()` registers it plus anything dropped into
`%LOCALAPPDATA%\EqUpdater\fonts`. Arial is not shipped: it comes with Windows.
Friz Quadrata is commercial (URW); Ollie has permission to ship it, and
`fonts/README.txt` says it is not covered by any EqUpdater licence.

The old route -- the installer and the app fishing `friz*.zip`,
`arial*.zip`, `opendyslexic*.zip` out of Downloads, Desktop and Documents --
is gone. It left users without fonts whenever the zips were not there.

Settings draws each font's name in that font (`FontManager.preview_font`);
`apply_tree` skips widgets marked `keeps_own_font`, so the list keeps its
faces whichever font is selected.

`FontManager` still detects each family's real name before enabling a choice.

Embedded family names verified during this work:

- Friz: `Friz Quadrata`
- Arial: `Arial`
- OpenDyslexic: `OpenDyslexic`

Do not silently present OpenDyslexic while rendering a fallback family.

## Languages (2026-10-01)

EqUpdater's own text follows the saved Game Language tweak: English,
German, Russian, Simplified Chinese, Spanish, Portuguese (BR). A game
language without a translation shows English. `equpdater/i18n.py` holds the
mechanism; `equpdater/locales/{de,ru,zh_cn,es,pt_br}.py` hold one dict each,
keyed by the English text.

- Wrap shown text in `tr("…")`, with named placeholders:
  `tr("Delete {folder}?", folder=name)`. Text defined in a table at import
  time is marked `N_("…")` and passed through `tr()` where it is shown.
- `tests/test_i18n.py` collects every `tr`/`N_` literal and fails if any
  language lacks it, keeps a stale one, or changes the placeholders. Adding
  or rewording English text therefore means adding the five translations.
- The language is set once, in `EqUpdaterApp.__init__`, before anything is
  drawn. Applying (or resetting) tweaks with a new language offers a
  restart, asked in the new language, and only after WoW.exe is written.
- **Not translated on purpose:** the session log (support reads it), news
  posts, addon descriptions from the catalogue, server/OS error text, and
  names. Stored errors stay English and are translated where shown.
- The translations were written by the assistant, not native speakers.
  Have a native speaker read each before relying on them.
- Friz Quadrata has no Cyrillic; Russian in Friz falls back to another face
  for those letters. Arial and OpenDyslexic cover the Latin and Cyrillic
  languages.
- None of the three fonts has Chinese; Windows draws it in its own Chinese
  font whatever is chosen. So in Chinese the FONT section in Settings is
  greyed out (`i18n.SYSTEM_FONT_LANGUAGES`); the saved choice is kept.
- Longer languages needed room: the Tweaks name column, the Mods name
  column and the footer buttons size themselves to their text.

## News / changelog

`equpdater/news.py` owns News fetching/parsing; `app.py` only renders.

The only source is the phpBB forum, read by the user's PC through
`secure_urlopen` with the app's User-Agent. No `octonews.php`, no `news.json`
(OctoBot's fallback, which is stale: two posts from April 2026).

- `fetch_forum_topics(forum_id)` reads the listing (`sk=tt&sd=d`), takes every
  `li.row`, and sorts by each topic's **start** date -- never row order, never
  the last-post column or its hidden mobile copy.
- `fetch_first_post(topic)` opens the canonical `viewtopic.php?t=<id>` and
  reads only the first `div.post#p<N>`, dropping quotes and signatures.
- Announcements = `fetch_latest_post(2)`: listing + one topic (2 requests).
- Changelog = `fetch_topic_list(4, 8)`: listing only (1 request); entries have
  title, start date, author and topic link, no body.

Adapted from OctoBot `octotracker/announcements.py` (selectors, verification
detection, first-post cleanup), except its listing parser, which takes the
first `<time>`/username in `.list-inner` -- on phpBB 3.3 that is the last
reply's.

**Cadence:** `_load_news()` once at launch (unconditionally), and each
refresh button calls `_load_featured()` / `_load_patch_notes()`. Switching to
the NEWS tab does not fetch; there is no TTL and no timer. A refresh while one
is in flight is ignored. Tested in `TestNewsCadence`.

**Why News was blank (diagnosed 2026-09-24):** octowow.st is behind
BlazingFast DDoS protection, which answers every non-browser client --
whatever the User-Agent -- with a JavaScript "Just a moment please..."
interstitial, HTTP 200, header `X-BF-Challenge: pending`. That hits both the
forum and `octonews.php`. The old code parsed it as JSON (error) and HTML
(zero topics, reported as "no topics"). It is now detected and reported as
`ForumBlockedError` naming the stage; the panel keeps cached content. EqUpdater
does **not** try to solve the challenge -- that is circumventing the site's
anti-bot protection.

**Why OctoBot gets through (diagnosed 2026-09-24):** BlazingFast has a
*named* User-Agent allowlist entry for OctoBot. Same client (urllib) from the
same PC: `User-Agent: OctoBot/1.0 (+OctoWoW Discord bot)` gets the forum;
`EqUpdater/2.0.1`, a Chrome UA, and honest variants such as
`EqUpdater/2.0.1 (+https://github.com/eqomdx/EqUpdater)` all get the
challenge. EqUpdater must not send OctoBot's UA: that is borrowing another
client's exemption. The fix is asking OctoWoW to add `EqUpdater/` to the
same allowlist; no code change is needed after that.

Every failure is logged to the session log as `<stage> failed: <why> [<url>]`.

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

`python tools/check.py` -- 199 tests, ~30 s on Windows. Runs the suite in a
child process with faulthandler, prints only failures (name, exception,
traceback) or, if the process crashed, the test that was running and every
thread's stack. CI: `.github/workflows/tests.yml` (windows-latest, Python
3.12). `python build.py --release` refuses to build if the suite fails.

**The installer does not run the suite** (since 2026-09-27). It checks the
source compiles and imports, then builds; `install.ps1 -RunTests` restores the
suite for developers. Output of every step is logged under
`%LOCALAPPDATA%\EqUpdater\install-logs`; the console shows only what explains
a failure.

**Why:** a user's install died at "3/4 Tests" with `Tcl_AsyncDelete: async
handler deleted by the wrong thread` (reported as "FTCI_AsyncDelete"). Cause:
`AnimatedBackground`'s worker thread target was a method of the Tk-facing
object, so the `bg-animation` thread held it -- and through it the Tk window
-- until the thread finished. The tests stopped the animation without waiting;
when teardown let go of the window while the worker was mid-frame, the
worker's exit dropped the last reference and Tk was deleted on the worker
thread. Fixed structurally: the worker is `ui._FrameProducer`, which holds no
Tk object; `AnimatedBackground.stop(wait)` joins it and releases the
PhotoImage on the Tk thread; `EqUpdaterApp.after` schedules nothing once
destroy has begun; tests close apps through `_close_app` (waits for the
worker, fails on a leak, keeps the app referenced so no worker can free it).
`TestTkTeardownRace` reproduces the crash in a child process.

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
- OpenDyslexic overflowing Settings and hiding the FONT choice (no way back).
  FONT is now one row under the game folder, and the panel grows to fit.
- `__MACOSX/._*.otf` stubs from the OpenDyslexic zip imported as fonts.

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
