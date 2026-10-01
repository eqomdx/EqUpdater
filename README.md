<p align="center">
  <img src="icon.png" alt="EqUpdater" width="96">
</p>

<h1 align="center">EqUpdater</h1>

<p align="center">
  A desktop updater and mod manager for <b>OctoWoW</b>.<br>
  Game client, DLL mods, addons, texture packs, client tweaks and server news, in one place.
</p>

<p align="center">
  <img src="docs/screenshot.png" alt="EqUpdater's MODS tab" width="720">
</p>

> EqUpdater is derived from **[Octo Updater](https://github.com/rebasedkon/octo-updater)**
> by **rebasedkon**. Support the original author on
> [Ko-fi](https://ko-fi.com/rebased) or
> [Buy Me a Coffee](https://buymeacoffee.com/rebased).
> See [Credits](#credits).

---

## Install

**Close World of Warcraft first.**

1. Download this repository (**Code → Download ZIP**) and extract it.
2. Double-click **`install/INSTALL.cmd`**.
3. Launch EqUpdater from the desktop shortcut it offers.

The installer sets up Python if you need it, builds
`dist\EqUpdater\EqUpdater.exe`, and never touches your game folder. No
administrator rights are needed, and it is safe to run again to upgrade.

Keep `EqUpdater.exe` next to the `_internal` folder beside it: it is a folder
build, so it starts fast and never unpacks itself into `%TEMP%`.

---

## Safe by design

**EqUpdater only automatically updates what it manages.** It will never
silently overwrite:

- addons or mods you installed yourself
- a newer version than the one being offered
- files you have edited
- a different fork or source than the one you chose
- anything it cannot verify

When it holds something back, it says why. When you deliberately replace or
downgrade something, it asks first and keeps a backup.

### Managed and unmanaged

- **Managed** — installed by EqUpdater, or handed over with **Manage**.
  Checked for updates and included in **Update All**.
- **Unmanaged** — installed by hand. Shown and left exactly as it is, until
  you choose to manage it.

**Update All** updates everything managed where a newer version can be
confirmed, and skips the rest.

---

## Features

### Game client
- Downloads and verifies the OctoWoW client, repairing only what is wrong.
- Will not update or patch while the game is running.
- Optional: keep a custom `speech.mpq` (MPQ tab → **Ignore speech.mpq**).

### DLL mods
- VanillaFixes, ClassicAPI, Nampower, SuperWoW, UnitXP_SP3, DXVK and more,
  each with its description and latest version.
- **Essential mods are opt-in** — you are asked once, on first run.
- DLLs already in your client are never replaced just because EqUpdater
  recognises them.
- `dlls.txt` is kept in step, so an enabled mod always actually loads.

### Addons
- ★ **Recommended** addons, a wider list of maintained community versions,
  and search.
- Add any addon from **GitHub, GitLab, Gitea or Codeberg**.
- Knows the difference between newer, older and modified — a different
  commit is not assumed to be an update.
- Switch an addon to another fork, ignore updates for one, or stop managing it.

### Texture packs (MPQ)
- Install packs such as **Octo Raid Visuals** by Rook.
- **Link a source** for a pack you installed yourself, so it can be checked
  for updates. Linking changes no files.
- **Replace** keeps your old file beside the new one.

### Tweaks
- Client tweaks patched into `WoW.exe`.
- **Reset** asks before putting everything back to defaults.

### News
- Announcements and the Changelog, read straight from the OctoWoW forum:
  once at launch, and again when you press refresh.
- If the forum cannot be read, the News tab says why and keeps the last news
  it received.

### Look and feel
- Animated underwater background (Settings → **Animated background**; off
  uses a still image and almost no CPU).
- Fonts: **Arial** (default), **Friz Quadrata** or **OpenDyslexic**, switched
  live in Settings. All three come with EqUpdater; nothing to install.
- Dark title bar to match.
- In your language: EqUpdater follows **Tweaks → Game Language** —
  English, Deutsch, Русский, 中文 (简体), Español or Português (BR).
  Changing the language offers a restart.

---

## Coming from Octo Updater

On first launch, EqUpdater finds your Octo Updater settings, backs them up and
imports your game folder, locale, tweaks, mods and addons. Your old
configuration is **copied, never moved**, so going back costs nothing.

---

## Running from source

```sh
python -m pip install pillow pyinstaller certifi
python -m equpdater          # run it
python build.py              # build dist/EqUpdater/EqUpdater.exe
```

Python 3.10 or newer. On Linux, run it from source the same way.

### Tests

```sh
python tools/check.py           # the whole suite; prints only what failed
python build.py --release       # builds only if the suite passes
```

The suite guards EqUpdater's safety rules. It runs in CI on every change and
before every release build; it is not part of installing.

---

## Credits

EqUpdater is a derivative work of **Octo Updater**.

> **Octo Updater** — Copyright (c) 2026 **rebasedkon**
> https://github.com/rebasedkon/octo-updater
>
> Support the author:
> [Ko-fi](https://ko-fi.com/rebased) ·
> [Buy Me a Coffee](https://buymeacoffee.com/rebased)
>
> Contact: inskon@proton.me ·
> [Discord (rebazed)](https://discord.com/users/287467238573867018)

Much of what EqUpdater does — the client sync, the MPQ engine and the addon
installer — is the original author's work. Full attribution is in
[NOTICE](NOTICE); licence terms are in [LICENSE](LICENSE).

The bundled fonts keep their own licences; see
[fonts/README.txt](fonts/README.txt).

Octo Raid Visuals is made by
[Rook](https://octowow.st/git/Rook/RaidVisuals-OctoWoW).
