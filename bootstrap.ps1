# GRT Titrare - first run bootstrap
#
# Builds a private environment under runtime\. Two routes, in order:
#
#   1. A Python already registered on this computer.
#   2. The official installer, unpacked into runtime\python-base.
#
# Heavy packages are deliberately NOT placed inside the interpreter. They go to
# runtime\packages, so rebuilding the environment on another machine does not
# throw away four gigabytes of model and CUDA libraries.
#
# ASCII only on purpose - PowerShell 5.1 misreads Cyrillic in files without BOM.
#
# Note on error handling: native tools such as py.exe report perfectly normal
# conditions on the error stream. Under 'Stop' that aborts the whole script, so
# the preference stays on 'Continue' and every step is checked explicitly.

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root     = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime  = Join-Path $Root 'runtime'
$VenvDir  = Join-Path $Runtime 'python'
$VenvPy   = Join-Path $VenvDir 'Scripts\python.exe'
$Packages = Join-Path $Runtime 'packages'
$BaseDir  = Join-Path $Runtime 'python-base'

$Probe = 'import sys,tkinter,venv; assert (3,9)<=sys.version_info<(3,14); print(sys.version.split()[0])'

function Say($t)  { Write-Host "  $t" -ForegroundColor Gray }
function Good($t) { Write-Host "  $t" -ForegroundColor Green }
function Bad($t)  { Write-Host "  $t" -ForegroundColor Red }

function Quiet-Run($exe, $arguments) {
    # Returns stdout text when the command succeeded, otherwise $null.
    try {
        $output = & $exe @arguments 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) { return ($output | Out-String).Trim() }
    } catch { }
    return $null
}

Write-Host ''
Write-Host '  GRT Titrare - preparing the environment' -ForegroundColor Cyan
Write-Host '  This runs once. Later starts are instant.'
Write-Host ''

# --- already built and working? -------------------------------------------- #

if (Test-Path $VenvPy) {
    if (Quiet-Run $VenvPy @('-c', 'import tkinter, yaml; print(1)')) {
        Good 'Environment already present.'
        exit 0
    }
    Say 'Existing environment is broken, rebuilding.'
    Remove-Item -Recurse -Force $VenvDir -ErrorAction SilentlyContinue
}

# --- route 1: a Python that is already here -------------------------------- #

function Test-Python($exe) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    $version = Quiet-Run $exe @('-c', $Probe)
    if ($version) { $script:FoundVersion = $version; return $true }
    return $false
}

function Find-Python {
    $seen = New-Object System.Collections.Generic.List[string]

    foreach ($tag in '-3.12', '-3.11', '-3.10', '-3.13', '-3') {
        $path = Quiet-Run 'py' @($tag, '-c', 'import sys; print(sys.executable)')
        if ($path) { $seen.Add($path) }
    }
    foreach ($name in 'python.exe', 'python3.exe') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source) { $seen.Add($cmd.Source) }
    }
    foreach ($base in @($BaseDir,
                        "$env:LOCALAPPDATA\Programs\Python",
                        "$env:ProgramFiles\Python312",
                        "$env:ProgramFiles\Python311",
                        'C:\Python312', 'C:\Python311')) {
        if (Test-Path $base) {
            Get-ChildItem -Path $base -Filter 'python.exe' -Recurse -Depth 2 `
                -ErrorAction SilentlyContinue |
                ForEach-Object { $seen.Add($_.FullName) }
        }
    }
    foreach ($candidate in ($seen | Select-Object -Unique)) {
        if (Test-Python $candidate) { return $candidate }
    }
    return $null
}

Say 'Looking for Python on this computer...'
$python = Find-Python

# --- route 2: a portable build that ships Tkinter ---------------------------- #
#
# The MSI bundle can report success and install nothing, and the plain NuGet
# package has no Tkinter, so neither can be the primary route. These builds are
# a complete CPython in a tar archive - unpack and it runs. No registry, no
# elevation, and Tkinter is inside, which is what the interface needs.

if (-not $python) {
    $archive = Join-Path $env:TEMP 'grt-python.tar.gz'
    $unpack  = Join-Path $env:TEMP 'grt-python-unpack'
    $pinned  = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260728/cpython-3.12.13%2B20260728-x86_64-pc-windows-msvc-install_only.tar.gz'

    # Full path first: a short name depends on PATH, which cannot be trusted.
    $tar = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not (Test-Path $tar)) {
        $cmd = Get-Command tar -ErrorAction SilentlyContinue
        $tar = if ($cmd) { $cmd.Source } else { $null }
    }
    if (-not $tar) {
        Say 'tar is unavailable on this Windows build, skipping.'
    } else {
        # Ask for the newest build, fall back to a known one if GitHub is
        # unreachable or the answer is not what we expect.
        $url = $pinned
        try {
            $api = Invoke-RestMethod -TimeoutSec 20 -Headers @{ 'User-Agent' = 'GRT-Titrare' } `
                'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest'
            $asset = $api.assets | Where-Object {
                $_.name -like 'cpython-3.12.*-x86_64-pc-windows-msvc-install_only.tar.gz'
            } | Select-Object -First 1
            if ($asset) { $url = $asset.browser_download_url }
        } catch {
            Say 'Could not ask for the newest build, using the known one.'
        }

        Say 'Downloading a portable Python (about 45 MB)...'
        try {
            Remove-Item -Recurse -Force $unpack -ErrorAction SilentlyContinue
            Remove-Item -Force $archive -ErrorAction SilentlyContinue
            (New-Object Net.WebClient).DownloadFile($url, $archive)

            Say 'Unpacking...'
            New-Item -ItemType Directory -Force -Path $unpack | Out-Null
            & $tar -xzf $archive -C $unpack
            if ($LASTEXITCODE -ne 0) { throw "tar returned $LASTEXITCODE" }

            $inner = Join-Path $unpack 'python'
            if (Test-Path (Join-Path $inner 'python.exe')) {
                Remove-Item -Recurse -Force $BaseDir -ErrorAction SilentlyContinue
                Move-Item $inner $BaseDir
                if (Test-Python (Join-Path $BaseDir 'python.exe')) {
                    $python = Join-Path $BaseDir 'python.exe'
                    Good 'Portable build ready.'
                } else {
                    Say 'The portable build did not pass the check.'
                }
            } else {
                Say 'The archive did not contain what was expected.'
            }
        } catch {
            Say "Portable build failed: $($_.Exception.Message)"
        } finally {
            Remove-Item -Force $archive -ErrorAction SilentlyContinue
            Remove-Item -Recurse -Force $unpack -ErrorAction SilentlyContinue
        }
    }
}

# --- route 3: the official installer ----------------------------------------- #

if (-not $python) {
    $version   = '3.12.10'
    $installer = Join-Path $env:TEMP 'grt-python-setup.exe'
    $logFile   = Join-Path $env:TEMP 'grt-python-setup.log'

    Say "No Python found. Downloading $version (about 25 MB)..."
    try {
        (New-Object Net.WebClient).DownloadFile(
            "https://www.python.org/ftp/python/$version/python-$version-amd64.exe",
            $installer)
    } catch {
        Bad "Download failed: $($_.Exception.Message)"
    }

    if (Test-Path $installer) {
        Say 'Installing into the application folder...'
        Remove-Item -Recurse -Force $BaseDir -ErrorAction SilentlyContinue

        # InstallLauncherAllUsers=0 matters: the launcher otherwise installs
        # machine-wide, which needs elevation and makes the whole silent run
        # fail without saying so.
        $flags = @(
            '/quiet',
            'InstallAllUsers=0',
            'InstallLauncherAllUsers=0',
            'Include_launcher=0',
            "TargetDir=$BaseDir",
            'AssociateFiles=0',
            'PrependPath=0',
            'Shortcuts=0',
            'Include_test=0',
            'Include_doc=0',
            'Include_pip=1',
            'Include_tcltk=1',
            "/log `"$logFile`""
        )
        $proc = Start-Process -FilePath $installer -ArgumentList $flags -Wait -PassThru
        Remove-Item $installer -Force -ErrorAction SilentlyContinue

        if (Test-Python (Join-Path $BaseDir 'python.exe')) {
            $python = Join-Path $BaseDir 'python.exe'
        } else {
            Say "Installer exit code: $($proc.ExitCode)"
            $python = Find-Python
            if (-not $python -and (Test-Path $logFile)) {
                Say 'Last lines of the installer log:'
                Get-Content $logFile -Tail 12 | ForEach-Object { Write-Host "    $_" }
            }
        }
    }
}

if (-not $python) {
    Write-Host ''
    Bad 'Could not find or install Python.'
    Write-Host ''
    Write-Host '  Checked these locations:'
    foreach ($place in @($BaseDir,
                         "$env:LOCALAPPDATA\Programs\Python",
                         "$env:ProgramFiles\Python312",
                         'C:\Python312')) {
        $found = Test-Path (Join-Path $place 'python.exe')
        Write-Host ("    {0,-5} {1}" -f $(if ($found) {'yes'} else {'no'}), $place)
    }

    # Say why a Python that IS there was rejected: almost always Tkinter.
    $any = Get-ChildItem -Path $BaseDir, "$env:LOCALAPPDATA\Programs\Python" `
        -Filter 'python.exe' -Recurse -Depth 2 -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($any) {
        Write-Host ''
        Write-Host "  Found $($any.FullName) but it did not pass the check:"
        & $any.FullName -c $Probe 2>&1 | ForEach-Object { Write-Host "    $_" }
    }

    Write-Host ''
    Write-Host '  Install Python 3.12 manually, ticking "Add python.exe to PATH",'
    Write-Host '  then run this file again:'
    Write-Host '  https://www.python.org/downloads/release/python-31210/'
    Write-Host ''
    exit 1
}

Good "Using Python $script:FoundVersion"
Say $python

# --- build the environment --------------------------------------------------- #

Say 'Creating an isolated environment...'
& $python -m venv $VenvDir 2>&1 | Out-Null
if (-not (Test-Path $VenvPy)) {
    Write-Host ''
    Bad 'Could not create the environment.'
    Write-Host "  Tried with: $python"
    Write-Host ''
    exit 1
}

New-Item -ItemType Directory -Force -Path $Packages | Out-Null

Say 'Installing base packages...'
& $VenvPy -m pip install --disable-pip-version-check --no-warn-script-location `
    --upgrade pip 2>&1 | Out-Null
& $VenvPy -m pip install --disable-pip-version-check --no-warn-script-location `
    pyyaml tkinterdnd2 2>&1 | Out-Null

if (-not (Quiet-Run $VenvPy @('-c', 'import tkinter, yaml; print(1)'))) {
    Write-Host ''
    Bad 'The interface cannot start: tkinter or yaml is missing.'
    Write-Host '  Send this text to Oleg.'
    Write-Host ''
    exit 1
}

Write-Host ''
Good 'Ready. Starting GRT Titrare.'
Start-Sleep -Milliseconds 500
exit 0
