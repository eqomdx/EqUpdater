# EqUpdater

A desktop updater and mod manager for the **OctoWoW** client — game files,
DLL mods, addons, texture packs, client tweaks and server news.

> **EqUpdater keeps your OctoWoW client and the components you choose to
> manage up to date, without overwriting newer, custom or manually managed
> installs.**

That sentence is the product. It is not marketing: an updater that
enthusiastically synchronises everything to whatever its catalogue happens to
contain will, sooner or later, replace something you wanted. EqUpdater is
built so that cannot happen by accident.

---

> ### Derived from Octo Updater
>
> EqUpdater is a derivative work of
> **[Octo Updater](https://github.com/rebasedkon/octo-updater)** by
> **rebasedkon**, and most of what it *does* — the client sync, the MPQ
> engine, the addon installer, the window you are looking at — is their work.
> Please support them:
> **[Ko-fi](https://ko-fi.com/rebased)** ·
> **[Buy Me a Coffee](https://buymeacoffee.com/rebased)**
>
> Full attribution in [NOTICE](NOTICE); licence terms in [LICENSE](LICENSE).

---

## Install

**Close World of Warcraft first.**

Click the green **Code** button above → **Download ZIP**, extract it, and
double-click **`install/INSTALL.cmd`**.

It installs Python if you need it, runs the test suite, builds
`EqUpdater.exe`, and offers a desktop shortcut. No administrator rights, and
it is safe to run more than once. It does **not** touch your game folder.

On Linux, or by hand:

```sh
python3 -m pip install --user pyinstaller certifi
python3 build.py          # or just: python3 -m equpdater
```

More in [`install/README.md`](install/README.md).

### Coming from Octo Updater

Run EqUpdater. On its first launch it finds your Octo Updater configuration,
copies it aside as a backup, and imports your settings — game folder, locale,
tweaks, which mods you had, which addons, and anything you had set to ignore
updates.

Your old configuration is **copied, never moved**. Octo Updater still works
and still has its settings, so going back costs nothing.

---

## The idea

> EqUpdater manages what EqUpdater installed, or what you asked it to manage.
> It may inspect everything else, but it will not silently replace it.

Two consequences follow, and they are the whole design:

**Different does not mean outdated.** A file that differs from the
updater's preferred copy might be newer, might be a fork you chose, might be
one you edited, might be from another branch. Four different situations, four
different right answers, and exactly one of them is "replace it".

**Not knowing is a reason to stop.** If EqUpdater cannot establish that a
remote version is genuinely newer — the lookup failed, the versions are not
comparable, the commit histories diverge — it leaves your files alone and
says why.

---

## Managed and unmanaged

Every mod, addon and texture pack is in one of two camps.

**Managed** — EqUpdater installed it, or you pressed *Manage*. It is checked
for updates, included in Update All, and can be removed from the UI.

**Unmanaged** — it is on disk and EqUpdater did not put it there. It shows up
on its page as *Installed manually*, with its name and version read from its
own `.toc`, and a link to a likely repository if one is known. EqUpdater will
**not** replace, delete, downgrade, re-point or update it, and Update All
skips it entirely.

A folder name matching an entry in the catalogue does not make an addon
yours-and-therefore-ours. Questie installed by hand stays exactly as you
installed it until you say otherwise.

Two buttons move things between the camps:

- **Manage** — records that EqUpdater may update this from a given source,
  and fingerprints the files as they are. **It installs nothing.** Your copy
  is untouched.
- **Stop managing** (↩) — gives up ownership. The files stay exactly where
  they are; EqUpdater simply stops offering updates for them.

---

## How EqUpdater decides

### Versions

Real ordering, not string comparison:

```
remote > local   →  Update available
remote == local  →  Up to date
remote < local   →  Local version newer       (never touched automatically)
unknown          →  Unable to verify          (never touched automatically)
```

It reads `v90`, `V90`, `90`, `1.2`, `1.2.3`, `v1.2.3`, `release-1.2`, `1.10`,
`2026.09.01` and pre-release tails like `1.2.3-beta1`. `1.10` is correctly
newer than `1.9`. Two versions from different numbering schemes — `V90` and
`1.2.3` — are reported as not comparable rather than guessed at.

**The case this was built for.** You have UnitXP **V90**. The configured
repository publishes **V89**. EqUpdater shows:

```
UnitXP_SP3
Installed: V90        Repository: V89
LOCAL VERSION NEWER
```

Update All skips it and says so in the log. There is no *Update* button,
because there is no update. If you genuinely want V89, right-click the
status: you are told it is a downgrade, a backup is taken, and then it
happens.

### Commits

Addons are tracked by commit, and a different commit sha is an observation,
not a direction. EqUpdater asks the host (GitHub, Codeberg, Gitea, GitLab)
which commit contains which:

```
installed is an ancestor of remote  →  Update available
remote is an ancestor of installed  →  Local version newer
same commit                         →  Up to date
neither contains the other          →  Different revision   (rebase, fork, branch)
cannot be established               →  Unable to verify
```

### Local modifications

When EqUpdater installs something it fingerprints what it wrote. If those
files no longer match, the component reads **Modified locally** and automatic
updates are held back — so a config you edited, or a patched `.lua`, is not
quietly replaced. *Replace…* overwrites it deliberately, after telling you
what will be lost and taking a backup.

### Sources

The source an addon was **installed from** and the source the catalogue
currently **recommends** are two different things. When they disagree you get
**Different source** and a *switch* (⇄) button — never an update. Switching
forks is a decision about which project you want, not a version bump.

A source you chose yourself is marked custom and is never argued with again.

---

## Update All

> Update everything EqUpdater manages and can prove is behind.

It updates managed mods and addons with a proven newer version. It skips, and
tells you it skipped:

| Skipped | Because |
|---|---|
| Unmanaged / installed manually | Not EqUpdater's to replace |
| Local version newer | Updating would be a downgrade |
| Modified locally | Your changes would be lost |
| Different source | A different fork is a choice |
| Different revision | Neither history contains the other |
| Unable to verify | Lookup failed, or versions are not comparable |
| Ignored | You said not to |
| Disabled | Not in use |

When anything is being held back you get a preview first:

```
5 updates available

    ClassicAPI      1.4 → 1.5
    SuperWoW        2.2 → 2.3
    aux-addon       abc1234 → def5678

Not being changed:

    UnitXP_SP3
        local version is newer
    pfUI
        local files have been modified
    Questie
        not managed by EqUpdater
```

When nothing unusual is happening there is no dialog — one click, as before.
A confirmation nobody ever needs is one everybody learns to dismiss.

---

## Doing it anyway

Every protection has a deliberate way past it, because otherwise people go
back to deleting folders by hand:

| Action | Where | What it does |
|---|---|---|
| **Manage** | MODS, ADDONS | Take ownership. Changes no files. |
| **Stop managing** | ADDONS (↩) | Give up ownership. Changes no files. |
| **Switch source** | ADDONS (⇄) | Track a different repository from now on. |
| **Replace…** | ADDONS | Overwrite with the source's version. Backs up first. |
| **Force replace** | MODS (right-click) | Install the source's version over this one, downgrade included. Backs up first. |
| **Reinstall** | MODS | Put back files that have gone missing. |
| **Ignore updates** | MODS | Exclude from every automatic flow. |

Backups go to `%LOCALAPPDATA%\EqUpdater\backups\`. They are taken for
deliberate destructive actions only — an updater that copied everything on
every update would bury the one backup that mattered.

---

## Everything else

**Game client** — torrent-based sync with integrity verification, locale
selection, and client tweaks patched into `WoW.exe`. Unchanged from Octo
Updater, which did it well.

**Texture packs (MPQ)** — same ownership rules. A patch MPQ has no version,
so a pack EqUpdater did not install reads *Installed · version not tracked*
rather than pretending to know whether it is current. Your custom textures
are not "out of date".

**DLL mods** — `dlls.txt` is written in a defined load order, its cache is
invalidated on every rewrite, and every enabled mod is re-registered at the
end of an apply and again on PLAY. The official launcher keeps its own mod
list and can drop entries it does not know about; this repairs that, which is
configuration repair and not replacement of anybody's DLL.

**First run against an existing client** — EqUpdater looks before it touches.
Mods already installed are recorded as found, shown on the MODS page and left
alone; only genuinely missing essentials are installed.

**Windows and Linux.** **Custom repositories** for any addon. **Per-component
install and remove.** **Update badges** that count only what can actually be
updated.

---

## Running from source

```sh
python3 -m equpdater
```

Requires Python 3.10+. `certifi` is optional and recommended.

## Tests

```sh
python3 -m unittest discover -s tests
```

The safety rules have tests of their own, written as the promises they are —
never downgrade, never touch unmanaged, never overwrite modified, a sha
mismatch is not proof, ignore means ignore, a failed lookup never replaces
anything. They run against `equpdater.planner`, which every list, badge,
worker and sweep in the app consults, so proving the decision proves all of
them at once.

## Layout

```
equpdater/
    versions.py     version parsing and ordering
    gitcompare.py   commit ancestry via the host APIs
    hashing.py      content fingerprints, for local-modification detection
    states.py       the status and action vocabulary
    planner.py      plan(component) -> what may be done, and why
    config.py       settings, the v2 schema, migration from Octo Updater
    branding.py     product identity and platform paths
    app.py          the window, the workers, and the engines inherited
                    from Octo Updater
tests/
build.py            builds EqUpdater.exe
install/            one-click Windows installer
```

## Known limitations

- **Modifications made before you switched to EqUpdater cannot be detected.**
  Fingerprints start at install or at migration; nothing recorded what your
  files looked like before that. Migrated components are marked as such.
- **Ancestry needs the host's API.** A private repository, a rate limit, or a
  force-push that removed the commit you hold all produce *Unable to verify* —
  which is honest, and means nothing is replaced, but it is not an update
  either.
- **Adopting an addon does not learn its commit.** EqUpdater cannot tell which
  commit a folder came from, so an adopted addon reads *Unable to verify*
  until you install from its source once. Inventing a sha would be worse.
- **A pinned direct-download mod has no version feed**, so it can only ever
  read as current. It says so.

## Licence

[Octo Updater License](LICENSE). Attribution terms are met in
[NOTICE](NOTICE), above, and in the application under Settings.
