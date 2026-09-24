"""Settings: where they live, how they are written, and how they are carried
forward from Octo Updater.

Two things here are load-bearing and both were inherited rather than invented.
Writes go through a temp file and an atomic rename, so a crash mid-write
cannot leave a truncated config; and every change goes through `update_config`
under a lock, so a worker thread and the UI thread cannot each save a stale
snapshot over the other's keys.

The new part is the schema. The old one recorded what was installed:

    {"installed_version": "1.4", "enabled": true}

which cannot answer the question this product is built around -- *whose file
is this*. The v2 schema records provenance instead: who installed it, from
where, at which revision, and what the files looked like when they arrived.
Everything the planner protects follows from being able to answer that.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time

from . import branding
from .hashing import files_hash, folder_hash

#: 1 = Octo Updater's records. 2 = ownership and provenance.
SCHEMA_VERSION = 2

_LOCK = threading.RLock()

APP_DATA_DIR = branding.app_data_dir()
CONFIG_FILE = os.path.join(APP_DATA_DIR, "config.json")
BACKUP_DIR = os.path.join(APP_DATA_DIR, "backups")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_config(path: str = None) -> dict:
    try:
        with open(path or CONFIG_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        # A corrupt config reads as an empty one rather than crashing the
        # app on launch. The file itself is left alone for inspection.
        return {}


def _atomic_write(path: str, text: str) -> None:
    """Temp file plus rename, so an interrupted write leaves the previous
    config intact rather than half of the new one."""
    ensure_dir(os.path.dirname(path) or ".")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def save_config(data: dict, path: str = None) -> None:
    with _LOCK:
        try:
            _atomic_write(path or CONFIG_FILE, json.dumps(data, indent=2))
        except Exception:
            pass


def update_config(mutator, path: str = None) -> dict:
    """Read, mutate and save under one lock. Every write goes through here."""
    with _LOCK:
        cfg = load_config(path)
        mutator(cfg)
        save_config(cfg, path)
        return cfg


# ──────────────────────────────────────────────────────────────────────────────
#  Records
# ──────────────────────────────────────────────────────────────────────────────

def new_mod_record(*, managed: bool, installed_version=None,
                   installed_files=None, content_hash=None,
                   source_url=None, custom_source: bool = False,
                   enabled: bool = True, adopted: bool = False) -> dict:
    """One DLL mod's provenance.

    `managed` is the field the whole product turns on: false means EqUpdater
    found this file rather than putting it there, and every automatic flow
    leaves it alone. `adopted` records that the user handed over something
    EqUpdater found, which is worth keeping distinct from something EqUpdater
    installed itself -- the files predate us either way, so their fingerprint
    baseline is weaker evidence."""
    return {
        "managed": bool(managed),
        "installed_by": branding.APP_NAME if managed and not adopted else None,
        "adopted": bool(adopted),
        "enabled": bool(enabled),
        "ignore_updates": False,
        "installed_version": installed_version,
        "installed_files": list(installed_files or []),
        "content_hash": content_hash,
        "hash_baseline": "install" if content_hash and not adopted else
                         ("adoption" if content_hash else None),
        "source_url": source_url,
        "custom_source": bool(custom_source),
        "error": None,
    }


def new_addon_record(*, managed: bool, git=None, branch=None, ref=None,
                     sha=None, content_hash=None, custom_source: bool = False,
                     adopted: bool = False, installed_version=None) -> dict:
    """One addon's provenance. `git` is the source it was *installed from*,
    which is not necessarily the source the catalogue currently recommends --
    keeping those apart is what makes a fork switch a decision rather than an
    update."""
    return {
        "managed": bool(managed),
        "installed_by": branding.APP_NAME if managed and not adopted else None,
        "adopted": bool(adopted),
        "ignore_updates": False,
        "git": git,
        "branch": branch,
        "ref": ref,
        "sha": sha,
        "installed_version": installed_version,
        "content_hash": content_hash,
        "hash_baseline": "install" if content_hash and not adopted else
                         ("adoption" if content_hash else None),
        "custom_source": bool(custom_source),
        "error": None,
    }


# ──────────────────────────────────────────────────────────────────────────────
#  Migration from Octo Updater
# ──────────────────────────────────────────────────────────────────────────────

def find_legacy_config() -> str | None:
    """The newest previous-product config on this machine, or None.

    Checked in inheritance order and only as far as the first hit: settings
    are carried forward once, from the most recent product, not merged across
    every version that ever ran."""
    for base in branding.legacy_app_data_dirs():
        candidate = os.path.join(base, "config.json")
        if os.path.isfile(candidate):
            return candidate
    # Pre-1.3 Octo Updater kept it beside the executable.
    loose = os.path.join(branding.app_dir(), branding.LEGACY_LOOSE_CONFIG)
    if os.path.isfile(loose):
        return loose
    return None


def backup_file(path: str, label: str = "migration") -> str | None:
    """Copy a file into the backups folder under a timestamp. Returns the
    copy's path, or None if it could not be made.

    Copied, never moved: the old product's config stays exactly where it was.
    Somebody who does not like what EqUpdater did must be able to go back to
    the previous updater and find their settings intact."""
    if not path or not os.path.isfile(path):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest_dir = os.path.join(BACKUP_DIR, label, stamp)
    try:
        ensure_dir(dest_dir)
        dest = os.path.join(dest_dir, os.path.basename(path))
        shutil.copy2(path, dest)
        return dest
    except OSError:
        return None


#: Keys carried across verbatim. Anything not listed is either regenerated
#: (caches, timestamps) or belongs to a product that no longer exists.
_CARRY_KEYS = (
    "out_dir", "locale", "tweaks", "minimize_on_play", "auto_install_mods",
    "ignore_speech", "pending_reconcile", "dxvk_notice_pending",
    "addons_catalog_cache", "chat_commands_seeded", "recommended_addons_seeded",
)


def migrate_records(old_cfg: dict, *, client_dir: str = "",
                    mod_files_for=None, addon_dir_for=None,
                    hash_files=files_hash, hash_folder=folder_hash) -> dict:
    """Turn Octo Updater's records into v2 provenance records.

    The rule, and it is the careful one: **an old record is evidence that the
    old updater installed something, not evidence that the files on disk are
    still what it installed.** So a record that clearly came from an install
    (it carries a version, or a commit sha) is carried across as managed, and
    a fingerprint is taken *now* and marked as a migration baseline rather
    than an install baseline. Modifications made before this moment cannot be
    detected by anything -- that information was never recorded -- and the UI
    says so rather than implying a clean bill of health.

    A record with no version and no sha proves nothing about who installed
    what, so it migrates as unmanaged: visible, preserved, and never swept.

    `mod_files_for(mod_id, record)` and `addon_dir_for(folder)` are injected
    so this is testable without a client, and so the app can supply the real
    registry and paths."""
    out_mods, out_addons = {}, {}

    for mod_id, old in (old_cfg.get("mods") or {}).items():
        if not isinstance(old, dict):
            continue
        version = old.get("installed_version")
        files = old.get("installed_files") or (
            mod_files_for(mod_id, old) if mod_files_for else [])
        managed = bool(version)
        content = None
        if managed and client_dir and files:
            content = hash_files(client_dir, files)
        rec = new_mod_record(
            managed=managed,
            installed_version=version,
            installed_files=files,
            content_hash=content,
            enabled=bool(old.get("enabled", False)),
            adopted=managed,          # the files predate this product
        )
        rec["ignore_updates"] = bool(old.get("ignore_updates", False))
        rec["error"] = old.get("error")
        if managed:
            rec["hash_baseline"] = "migration" if content else None
            rec["installed_by"] = branding.UPSTREAM_NAME
        out_mods[mod_id] = rec

    for folder, old in (old_cfg.get("addons") or {}).items():
        if not isinstance(old, dict):
            continue
        sha = old.get("sha")
        git = old.get("git")
        managed = bool(sha and git)
        content = None
        if managed and addon_dir_for:
            content = hash_folder(addon_dir_for(folder))
        rec = new_addon_record(
            managed=managed,
            git=git,
            branch=old.get("branch"),
            ref=old.get("ref"),
            sha=sha,
            content_hash=content,
            custom_source=bool(old.get("custom", False)),
            adopted=managed,
        )
        if managed:
            rec["hash_baseline"] = "migration" if content else None
            rec["installed_by"] = branding.UPSTREAM_NAME
        out_addons[folder] = rec

    return {"mods": out_mods, "addons": out_addons}


def migrate_config(old_cfg: dict, **kw) -> dict:
    """A whole v1 config as a v2 one. Pure: no disk, no network."""
    new = {k: old_cfg[k] for k in _CARRY_KEYS if k in old_cfg}
    new.update(migrate_records(old_cfg, **kw))
    new["schema"] = SCHEMA_VERSION
    new["migrated_from"] = {
        "product": branding.UPSTREAM_NAME,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "version": old_cfg.get("octo_updater_version"),
    }
    return new


def bootstrap_config(**kw) -> dict:
    """The first-launch sequence, run once and only once.

    1. An EqUpdater config already here wins; nothing else happens.
    2. Otherwise look for the previous product's config.
    3. Back it up, migrate compatible settings, write the result here.
    4. Stamp the schema so this never runs again.

    Idempotent by construction: step 1 short-circuits every later launch, and
    a failed migration leaves no stamp, so it is retried rather than half
    applied. The old config is copied, never moved."""
    existing = load_config()
    if existing.get("schema") == SCHEMA_VERSION:
        return existing

    if existing:
        # An EqUpdater config written before this schema: upgrade in place.
        upgraded = dict(existing)
        if "mods" in existing or "addons" in existing:
            upgraded.update(migrate_records(existing, **kw))
        upgraded["schema"] = SCHEMA_VERSION
        save_config(upgraded)
        return upgraded

    legacy_path = find_legacy_config()
    if not legacy_path:
        fresh = {"schema": SCHEMA_VERSION}
        save_config(fresh)
        return fresh

    legacy = load_config(legacy_path)
    backup = backup_file(legacy_path, "octoupdater-config")
    migrated = migrate_config(legacy, **kw)
    migrated["migrated_from"]["path"] = legacy_path
    migrated["migrated_from"]["backup"] = backup
    save_config(migrated)
    return migrated
