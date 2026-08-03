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

# --- route 2: a standalone build, no installer at all ------------------------ #
#
# The MSI bundle reports success and then leaves nothing at the requested path
# often enough that it cannot be the primary route. This package is a plain
# zip of a complete CPython: unpack and it works. No registry, no elevation,
# no chance of it deciding to install somewhere else.

if (-not $python) {
    $version = '3.12.10'
    $pkg = Join-Path $env:TEMP 'grt-python-pkg.zip'
    $unpack = Join-Path $env:TEMP 'grt-python-pkg'

    Say "Downloading a standalone Python $version (about 30 MB)..."
    try {
        Remove-Item -Recurse -Force $unpack -ErrorAction SilentlyContinue
        Remove-Item -Force $pkg -ErrorAction SilentlyContinue
        (New-Object Net.WebClient).DownloadFile(
            "https://www.nuget.org/api/v2/package/python/$version", $pkg)

        Say 'Unpacking...'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($pkg, $unpack)

        $tools = Join-Path $unpack 'tools'
        if (Test-Path (Join-Path $tools 'python.exe')) {
            Remove-Item -Recurse -Force $BaseDir -ErrorAction SilentlyContinue
            Move-Item $tools $BaseDir
            if (Test-Python (Join-Path $BaseDir 'python.exe')) {
                $python = Join-Path $BaseDir 'python.exe'
                Good 'Standalone build ready.'
            } else {
                Say 'The standalone build is missing Tkinter, trying the installer.'
            }
        } else {
            Say 'The package did not contain what was expected.'
        }
    } catch {
        Say "Standalone build failed: $($_.Exception.Message)"
    } finally {
        Remove-Item -Force $pkg -ErrorAction SilentlyContinue
        Remove-Item -Recurse -Force $unpack -ErrorAction SilentlyContinue
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
