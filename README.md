# EqUpdater

A desktop updater and mod manager for **OctoWoW**.

EqUpdater manages your game client, DLL mods, addons, texture packs, client tweaks, and server news from one place.

## Install

1. Download the repository
2. Extract it
3. Run **`install/INSTALL.cmd`**
4. Launch EqUpdater

No administrator rights are required.

## Features

* **Game client updates** with integrity checking
* **DLL mod management**
* **Addon installation and updates**
* **Texture pack management**
* **Custom addon repositories**
* **Client tweaks**
* **OctoWoW news and changelogs**
* **Windows and Linux support**

## Safe Updates

EqUpdater only automatically updates files that it manages.

It will not silently overwrite:

* Manually installed addons or mods
* Newer local versions
* Locally modified files
* Custom forks or different sources
* Files it cannot safely verify

## Managed vs Unmanaged

**Managed** components are installed by EqUpdater or explicitly added using **Manage**. These can be checked and updated automatically.

**Unmanaged** components were installed manually. EqUpdater can detect them, but leaves them untouched unless you choose to manage them.

## Update All

**Update All** updates everything EqUpdater manages where a newer version can be confirmed.

Anything unsafe or uncertain is skipped instead of being overwritten.

## Addons

EqUpdater supports:

* Automatic update checking
* Custom repositories
* GitHub, Codeberg, GitLab and Gitea sources
* Local modification detection
* Switching sources or forks
* Individual install, update and removal
* Ignoring updates for specific components

## DLL Mods

DLL mods can be installed and managed individually.

Essential mods are **opt-in**, and existing DLLs are not automatically replaced just because EqUpdater detects them.

## Texture Packs

Texture packs can be installed through EqUpdater or linked to an external source.

EqUpdater can track supported packs for updates while leaving custom or unlinked MPQs alone.

## Backups

When you deliberately replace or downgrade something, EqUpdater creates a backup first.


