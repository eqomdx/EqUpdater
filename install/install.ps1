<#
.SYNOPSIS
    One-click installer for EqUpdater.

.DESCRIPTION
    Bootstraps a real Python (the Microsoft Store stub does not count),
    installs PyInstaller, certifi and Pillow, then builds EqUpdater.exe from this
    repository.

    That is the whole job. EqUpdater does not touch your game folder during
    installation and does not need to know where it is: the app finds it, and
    imports your Octo Updater settings itself the first time it runs.

    No administrator rights required - everything installs per-user.
    Safe to re-run: every step is idempotent.

    EqUpdater is derived from Octo Updater by rebasedkon:
    https://github.com/rebasedkon/octo-updater

    The test suite is not part of an ordinary install. It gates releases
    (python build.py --release) and runs in CI; a GUI or timing test that
    behaves differently on one PC must not stop somebody installing the app.
    Developers who want it here can pass -RunTests.

    If a step fails, the installer prints what failed -- the failing test and
    its traceback, or the end of the build output -- and saves the complete
    output under %LOCALAPPDATA%\EqUpdater\install-logs.

.PARAMETER NoBuild
    Set up Python and the dependencies but do not build the executable.

.PARAMETER RunTests
    Developers: run the full test suite before building, and do not build if
    it fails.

.PARAMETER NoShortcut
    Do not offer to put a shortcut on the desktop.

.EXAMPLE
    .\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$NoBuild,
    [switch]$NoShortcut,
    [switch]$RunTests,
    [switch]$Yes
)

$ErrorActionPreference = "Stop"

function Write-Head($text) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor DarkCyan
    Write-Host " $text" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor DarkCyan
}
function Write-Step($text) { Write-Host "  -> $text" -ForegroundColor Gray }
function Write-Ok($text)   { Write-Host "  OK $text" -ForegroundColor Green }

# Complete output of each step goes to a log file; the console only shows the
# part that explains a failure.
$script:logDir = Join-Path $env:LOCALAPPDATA "EqUpdater\install-logs"
New-Item -ItemType Directory -Force -Path $script:logDir | Out-Null
$script:stamp = Get-Date -Format "yyyyMMdd-HHmmss"

function Invoke-Logged($name, [scriptblock]$command) {
    # Native programs write progress to stderr. Windows PowerShell turns that
    # into error records, which the installer's ErrorActionPreference=Stop
    # would treat as fatal even when the program succeeds - so allow it here,
    # capture everything, and decide from the exit code alone.
    $log = Join-Path $script:logDir "$($script:stamp)-$name.log"
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $lines = @(& $command 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
    $lines | Set-Content -Path $log -Encoding utf8
    return [pscustomobject]@{ Code = $code; Lines = $lines; Log = $log }
}

# ---------------------------------------------------------------------------
# Find a real Python.
#
# The entries under WindowsApps are the Microsoft Store stub: they sit on PATH
# and look like an interpreter, but running one just prints "Python was not
# found; run without arguments to install from the Microsoft Store". Skipping
# them is not optional - picking one up is the single most common way an
# installer like this appears to work and then does nothing.
# ---------------------------------------------------------------------------
function Find-RealPython {
    $candidates = @()

    $roots = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        "C:\Program Files\Python313", "C:\Program Files\Python312",
        "C:\Program Files\Python311", "C:\Program Files\Python310",
        "C:\Python313", "C:\Python312", "C:\Python311", "C:\Python310"
    )
    foreach ($r in $roots) {
        if (Test-Path $r) {
            $candidates += Get-ChildItem -Path $r -Filter python.exe -Recurse `
                -ErrorAction SilentlyContinue |
                Select-Object -ExpandProperty FullName
        }
    }
    foreach ($c in (Get-Command python.exe -All -ErrorAction SilentlyContinue)) {
        $candidates += $c.Source
    }

    $seen = @{}
    foreach ($p in $candidates) {
        if (-not $p) { continue }
        if ($p -like "*\WindowsApps\*") { continue }
        $key = $p.ToLower()
        if ($seen.ContainsKey($key)) { continue }
        $seen[$key] = $true
        if (-not (Test-Path $p)) { continue }
        try {
            $v = & $p -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        } catch { continue }
        if ($LASTEXITCODE -ne 0 -or -not $v) { continue }
        $parts = $v.Trim().Split(".")
        if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
            return [pscustomobject]@{ Path = $p; Version = $v.Trim() }
        }
    }
    return $null
}

function Install-Python {
    Write-Step "No suitable Python found. Installing Python 3.12 (per-user)..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw ("winget is not available on this machine, so Python cannot be " +
               "installed automatically.`n" +
               "Install Python 3.10 or newer from https://www.python.org/downloads/ " +
               "(tick 'Add python.exe to PATH') and run this installer again.")
    }
    & winget install --id Python.Python.3.12 --source winget --scope user `
        --silent --accept-package-agreements --accept-source-agreements `
        --disable-interactivity
    # winget exit codes vary between versions - verify by looking again.
    $py = Find-RealPython
    if (-not $py) {
        throw ("Python is still not detected after the install.`n" +
               "Install it manually from https://www.python.org/downloads/ " +
               "and run this installer again.")
    }
    return $py
}

# ---------------------------------------------------------------------------

Write-Head "EqUpdater - installer"
Write-Host "  Derived from Octo Updater by rebasedkon:" -ForegroundColor DarkGray
Write-Host "    https://github.com/rebasedkon/octo-updater" -ForegroundColor DarkGray

# Where this script lives, and therefore where the project is. Captured at
# script scope on purpose: inside a function $MyInvocation describes the
# function call, not the script file.
$script:selfPath = $MyInvocation.MyCommand.Path
if (-not $script:selfPath) {
    throw "Run this script from a file (install\install.ps1), not from a pipe."
}
$here = Split-Path -Parent $script:selfPath
if ((Split-Path -Leaf $here) -eq "install") {
    $projectDir = Split-Path -Parent $here
} else {
    $projectDir = $here
}

if (-not (Test-Path (Join-Path $projectDir "equpdater\app.py"))) {
    throw ("This installer builds EqUpdater, but the project is not next to " +
           "it.`nLooked in: $projectDir`n`n" +
           "Download the whole repository from " +
           "https://github.com/eqomdx/EqUpdater (Code -> Download ZIP), " +
           "unpack it, and run install\install.ps1 from inside it.")
}
Write-Ok "project: $projectDir"

Write-Head "1/3  Python"
$py = Find-RealPython
if (-not $py) { $py = Install-Python }
Write-Ok "$($py.Path)  (Python $($py.Version))"

Write-Head "2/3  Dependencies"
Write-Step "pip install --user --upgrade pyinstaller certifi pillow"
& $py.Path -m pip install --user --upgrade --disable-pip-version-check `
    pyinstaller certifi pillow
if ($LASTEXITCODE -ne 0) {
    throw "Installing PyInstaller failed. See the messages above."
}
Write-Ok "PyInstaller, certifi and Pillow ready"

# Import the user-supplied UI font archives into EqUpdater's private per-user
# font directory. No administrator rights and no system-wide font install.
# The app also repeats this discovery at runtime, but doing it here means the
# first packaged launch already has the fonts available.
Write-Step "Importing EqUpdater UI fonts (Friz Quadrata / Arial / OpenDyslexic)"
$fontDest = Join-Path $env:LOCALAPPDATA "EqUpdater\fonts"
New-Item -ItemType Directory -Force -Path $fontDest | Out-Null
$fontPatterns = @(
    "friz-quadrata*.zip", "friz*.zip",
    "arial*.zip",
    "opendyslexic*.zip"
)
$fontSearchRoots = @(
    $projectDir,
    (Join-Path $env:USERPROFILE "Downloads"),
    (Join-Path $env:USERPROFILE "Desktop"),
    (Join-Path $env:USERPROFILE "Documents")
)
$fontArchives = @()
foreach ($root in $fontSearchRoots) {
    if (-not (Test-Path $root)) { continue }
    foreach ($pattern in $fontPatterns) {
        $fontArchives += Get-ChildItem -Path $root -Filter $pattern -File `
            -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    }
}
$fontArchives = $fontArchives | Sort-Object -Unique
$fontImported = 0
foreach ($archive in $fontArchives) {
    $tmp = Join-Path $env:TEMP ("EqUpdaterFonts-" + [guid]::NewGuid().ToString("N"))
    try {
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        Expand-Archive -Path $archive -DestinationPath $tmp -Force
        Get-ChildItem -Path $tmp -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -match '^\.(ttf|otf)$' -and
                           -not $_.Name.StartsWith('._') -and
                           $_.FullName -notmatch '\\__MACOSX\\' } |
            ForEach-Object {
                Copy-Item $_.FullName (Join-Path $fontDest $_.Name) -Force
                $script:fontImported++
            }
    } catch {
        Write-Host "  Font archive skipped: $archive ($_)" -ForegroundColor Yellow
    } finally {
        Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    }
}
if ($fontImported -gt 0) {
    Write-Ok "imported $fontImported font files into $fontDest"
} else {
    Write-Host "  No font archives found. EqUpdater will also check Downloads/Desktop at launch." -ForegroundColor Yellow
}

if ($RunTests) {
    # Developers only. The same gate as `python build.py --release` and CI:
    # tools/check.py prints each failing test with its traceback (or, if the
    # test process crashed, which test was running and every thread's stack).
    Write-Head "Tests (developer)"
    $check = Invoke-Logged "tests" {
        & $py.Path (Join-Path $projectDir "tools\check.py") `
            --log (Join-Path $script:logDir "$($script:stamp)-tests-full.log")
    }
    $check.Lines | Write-Host
    if ($check.Code -ne 0) {
        throw "The test suite failed. Not building. Full log: $($check.Log)"
    }
    Write-Ok "tests passed"
}

if ($NoBuild) {
    Write-Head "Done (build skipped)"
    exit 0
}

Write-Head "3/3  Build"
# A quick check that the downloaded source is whole: it compiles and the
# package imports. Not the test suite - no windows, no threads, no network.
Write-Step "checking the source"
$source = Invoke-Logged "source-check" {
    & $py.Path -m compileall -q (Join-Path $projectDir "equpdater")
    if ($LASTEXITCODE -eq 0) {
        & $py.Path -c "import sys; sys.path.insert(0, r'$projectDir'); import equpdater, equpdater.news, equpdater.planner"
    }
}
if ($source.Code -ne 0) {
    $source.Lines | Select-Object -Last 30 | Write-Host
    throw ("The EqUpdater source is incomplete or damaged - download it " +
           "again. Details: $($source.Log)")
}
Write-Ok "source OK"

Write-Step "building EqUpdater (this takes a minute or two)"
$build = Invoke-Logged "build" {
    & $py.Path (Join-Path $projectDir "build.py")
}
if ($build.Code -ne 0) {
    Write-Host ""
    Write-Host "  The last lines of the build output:" -ForegroundColor Yellow
    $build.Lines | Select-Object -Last 40 | ForEach-Object { Write-Host "    $_" }
    throw "The build failed. Full output: $($build.Log)"
}

# A folder build: the executable needs the _internal directory beside it, so
# the shortcut points into dist\EqUpdater rather than at a loose .exe. This
# is not a single file on purpose - see the note at the top of build.py. A
# one-file build unpacks itself into %TEMP% on every launch and simply will
# not start when the system drive is full, which is a real state for anybody
# who keeps games on it.
$exe = Join-Path $projectDir "dist\EqUpdater\EqUpdater.exe"
if (-not (Test-Path $exe)) {
    throw "The build finished but $exe is missing."
}
Write-Ok $exe

if (-not $NoShortcut) {
    $answer = "y"
    if (-not $Yes) {
        $answer = Read-Host "  Put a shortcut on the desktop? [Y/n]"
        if (-not $answer) { $answer = "y" }
    }
    if ($answer -match "^[Yy]") {
        try {
            $desktop = [Environment]::GetFolderPath("Desktop")
            $lnk = Join-Path $desktop "EqUpdater.lnk"
            $shell = New-Object -ComObject WScript.Shell
            $sc = $shell.CreateShortcut($lnk)
            $sc.TargetPath = $exe
            $sc.WorkingDirectory = Split-Path -Parent $exe
            $sc.IconLocation = $exe
            $sc.Description = "EqUpdater - OctoWoW client, mods and addons"
            $sc.Save()
            Write-Ok "shortcut: $lnk"
        } catch {
            Write-Host "  Could not create the shortcut: $_" -ForegroundColor Yellow
        }
    }
}

Write-Head "Done"
Write-Host "  Run $exe" -ForegroundColor Green
Write-Host "  (keep that folder together - the .exe needs what is beside it)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  The first time it starts it will look for an Octo Updater" -ForegroundColor DarkGray
Write-Host "  configuration and import your settings. The old one is copied" -ForegroundColor DarkGray
Write-Host "  aside and left exactly where it is." -ForegroundColor DarkGray
Write-Host ""
