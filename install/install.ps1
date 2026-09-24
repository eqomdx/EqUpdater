<#
.SYNOPSIS
    One-click installer for EqUpdater.

.DESCRIPTION
    Bootstraps a real Python (the Microsoft Store stub does not count),
    installs PyInstaller and certifi, then builds EqUpdater.exe from this
    repository.

    That is the whole job. EqUpdater does not touch your game folder during
    installation and does not need to know where it is: the app finds it, and
    imports your Octo Updater settings itself the first time it runs.

    No administrator rights required - everything installs per-user.
    Safe to re-run: every step is idempotent.

    EqUpdater is derived from Octo Updater by rebasedkon:
    https://github.com/rebasedkon/octo-updater

.PARAMETER NoBuild
    Set up Python and the dependencies but do not build the executable.

.PARAMETER NoShortcut
    Do not offer to put a shortcut on the desktop.

.EXAMPLE
    .\install.ps1
#>
[CmdletBinding()]
param(
    [switch]$NoBuild,
    [switch]$NoShortcut,
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

Write-Head "1/4  Python"
$py = Find-RealPython
if (-not $py) { $py = Install-Python }
Write-Ok "$($py.Path)  (Python $($py.Version))"

Write-Head "2/4  Dependencies"
Write-Step "pip install --user --upgrade pyinstaller certifi"
& $py.Path -m pip install --user --upgrade --disable-pip-version-check `
    pyinstaller certifi
if ($LASTEXITCODE -ne 0) {
    throw "Installing PyInstaller failed. See the messages above."
}
Write-Ok "PyInstaller and certifi ready"

Write-Head "3/4  Tests"
# The safety rules are the product. Building without checking them would be
# shipping an updater that might overwrite somebody's files on the strength
# of an edit nobody ran.
& $py.Path -m unittest discover -s (Join-Path $projectDir "tests") `
    -t $projectDir 2>&1 | Select-Object -Last 5
if ($LASTEXITCODE -ne 0) {
    throw "The test suite failed. Not building."
}
Write-Ok "tests passed"

if ($NoBuild) {
    Write-Head "Done (build skipped)"
    exit 0
}

Write-Head "4/4  Build"
& $py.Path (Join-Path $projectDir "build.py")
if ($LASTEXITCODE -ne 0) {
    throw "The build failed. See the messages above."
}
$exe = Join-Path $projectDir "EqUpdater.exe"
if (-not (Test-Path $exe)) {
    $exe = Join-Path $projectDir "dist\EqUpdater.exe"
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
Write-Host "  Run EqUpdater.exe." -ForegroundColor Green
Write-Host ""
Write-Host "  The first time it starts it will look for an Octo Updater" -ForegroundColor DarkGray
Write-Host "  configuration and import your settings. The old one is copied" -ForegroundColor DarkGray
Write-Host "  aside and left exactly where it is." -ForegroundColor DarkGray
Write-Host ""
