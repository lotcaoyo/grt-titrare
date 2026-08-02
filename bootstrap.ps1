# GRT Titrare - first run bootstrap
#
# Builds a private environment under runtime\. Three routes are tried in order,
# because no single one works on every machine:
#
#   1. A Python already on this computer. Fastest, and the common case on a
#      workstation that has ever run a Python tool.
#   2. The official installer, but only when nothing usable was found. Note it
#      silently refuses to install into a custom folder when the same version
#      is already present, which is why route 1 comes first.
#   3. Clear instructions, rather than a silent failure.
#
# Heavy packages are deliberately NOT placed inside the interpreter. They go to
# runtime\packages, so rebuilding the environment on another machine does not
# throw away four gigabytes of model and CUDA libraries.
#
# ASCII only on purpose - PowerShell 5.1 misreads Cyrillic in files without BOM.

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime  = Join-Path $Root 'runtime'
$VenvDir  = Join-Path $Runtime 'python'
$VenvPy   = Join-Path $VenvDir 'Scripts\python.exe'
$Packages = Join-Path $Runtime 'packages'

function Say($text)  { Write-Host "  $text" -ForegroundColor Gray }
function Good($text) { Write-Host "  $text" -ForegroundColor Green }
function Bad($text)  { Write-Host "  $text" -ForegroundColor Red }

Write-Host ''
Write-Host '  GRT Titrare - preparing the environment' -ForegroundColor Cyan
Write-Host '  This runs once. Later starts are instant.'
Write-Host ''

# --- already built and working? ------------------------------------------- #

if (Test-Path $VenvPy) {
    & $VenvPy -c "import tkinter, yaml" 2>$null
    if ($LASTEXITCODE -eq 0) { Good 'Environment already present.'; exit 0 }
    Say 'Existing environment is broken, rebuilding.'
    Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue
}

# --- route 1: a Python that is already here -------------------------------- #

function Test-Python($exe) {
    if (-not $exe) { return $false }
    if (-not (Test-Path $exe)) { return $false }
    $check = '
import sys, tkinter, venv
assert (3, 9) <= sys.version_info < (3, 14)
print(sys.version.split()[0])
'
    $version = & $exe -c $check 2>$null
    if ($LASTEXITCODE -eq 0 -and $version) {
        $script:FoundVersion = $version.Trim()
        return $true
    }
    return $false
}

function Find-Python {
    $seen = @()
    foreach ($tag in '-3.12', '-3.11', '-3.10', '-3.13', '-3') {
        $path = (& py $tag -c "import sys; print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $path) { $seen += $path.Trim() }
    }
    foreach ($name in 'python.exe', 'python3.exe') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd) { $seen += $cmd.Source }
    }
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles\Python*", 'C:\Python*')) {
        Get-ChildItem -Path $base -Filter 'python.exe' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
            ForEach-Object { $seen += $_.FullName }
    }
    foreach ($candidate in ($seen | Select-Object -Unique)) {
        if (Test-Python $candidate) { return $candidate }
    }
    return $null
}

Say 'Looking for Python on this computer...'
$python = Find-Python

# --- route 2: install one, only if nothing was found ----------------------- #

if (-not $python) {
    Say 'None found. Downloading Python 3.12.10 (about 25 MB)...'
    $version   = '3.12.10'
    $installer = Join-Path $env:TEMP 'grt-python-setup.exe'
    $target    = Join-Path $Runtime 'python-base'
    try {
        (New-Object Net.WebClient).DownloadFile(
            "https://www.python.org/ftp/python/$version/python-$version-amd64.exe", $installer)
        Say 'Installing (no administrator rights needed)...'
        $flags = @('/quiet', 'InstallAllUsers=0', "TargetDir=`"$target`"",
                   'AssociateFiles=0', 'PrependPath=0', 'Shortcuts=0',
                   'Include_launcher=0', 'Include_test=0', 'Include_doc=0',
                   'Include_pip=1', 'Include_tcltk=1')
        Start-Process -FilePath $installer -ArgumentList $flags -Wait | Out-Null
        Remove-Item $installer -Force -ErrorAction SilentlyContinue

        if (Test-Python (Join-Path $target 'python.exe')) {
            $python = Join-Path $target 'python.exe'
        } else {
            $python = Find-Python      # it may have landed elsewhere
        }
    } catch {
        Say "Download failed: $($_.Exception.Message)"
    }
}

# --- route 3: say plainly what to do --------------------------------------- #

if (-not $python) {
    Write-Host ''
    Bad 'Could not find or install Python.'
    Write-Host '  Install Python 3.12 from python.org, tick "Add python.exe to PATH"'
    Write-Host '  during setup, then run this file again.'
    Write-Host '  https://www.python.org/downloads/release/python-31210/'
    Write-Host ''
    exit 1
}

Good "Using Python $script:FoundVersion"
Say $python

# --- build the environment -------------------------------------------------- #

try {
    Say 'Creating an isolated environment...'
    & $python -m venv $VenvDir
    if (-not (Test-Path $VenvPy)) { throw 'venv was not created' }

    New-Item -ItemType Directory -Force -Path $Packages | Out-Null

    Say 'Installing base packages...'
    & $VenvPy -m pip install --disable-pip-version-check --no-warn-script-location `
        --upgrade pip 2>&1 | Out-Null
    & $VenvPy -m pip install --disable-pip-version-check --no-warn-script-location `
        pyyaml tkinterdnd2 2>&1 | Out-Null

    & $VenvPy -c "import tkinter, yaml" 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'the interface cannot start: tkinter or yaml missing' }

    Write-Host ''
    Good 'Ready. Starting GRT Titrare.'
    Start-Sleep -Milliseconds 500
    exit 0
}
catch {
    Write-Host ''
    Bad "Setup failed: $($_.Exception.Message)"
    Write-Host '  Run this file again, or send the text above to Oleg.'
    Write-Host ''
    Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue
    exit 1
}
