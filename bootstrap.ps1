# GRT Titrare - first run bootstrap
#
# Installs a private Python 3.12 into runtime\python. Nothing is written to the
# registry, PATH or Program Files, so no administrator rights are required and
# deleting the folder leaves no trace on the machine.
#
# Everything heavier than this (recognition engine, CUDA libraries, model) is
# installed later from inside the application, where progress is visible.
#
# ASCII only on purpose - PowerShell 5.1 misreads Cyrillic in files without BOM.

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root       = Split-Path -Parent $MyInvocation.MyCommand.Path
$Runtime    = Join-Path $Root 'runtime'
$PyDir      = Join-Path $Runtime 'python'
$PyExe      = Join-Path $PyDir 'python.exe'
$PyVersion  = '3.12.10'
$PyUrl      = "https://www.python.org/ftp/python/$PyVersion/python-$PyVersion-amd64.exe"

function Say($text) { Write-Host "  $text" -ForegroundColor Gray }

Write-Host ''
Write-Host '  GRT Titrare - preparing the environment' -ForegroundColor Cyan
Write-Host '  This runs once. Later starts are instant.'
Write-Host ''

if (Test-Path $PyExe) {
    Say 'Python already present.'
    exit 0
}

if (-not [Environment]::Is64BitOperatingSystem) {
    Write-Host '  This machine is 32-bit. Speech recognition needs 64-bit Windows.' -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null
$installer = Join-Path $env:TEMP 'grt-python-setup.exe'

try {
    Say "Downloading Python $PyVersion (about 25 MB)..."
    $wc = New-Object Net.WebClient
    $wc.DownloadFile($PyUrl, $installer)

    Say 'Installing into the application folder...'
    $flags = @(
        '/quiet',
        'InstallAllUsers=0',
        "TargetDir=`"$PyDir`"",
        'AssociateFiles=0',
        'PrependPath=0',
        'Shortcuts=0',
        'Include_launcher=0',
        'Include_test=0',
        'Include_doc=0',
        'Include_dev=0',
        'Include_pip=1',
        'Include_tcltk=1'
    )
    $proc = Start-Process -FilePath $installer -ArgumentList $flags -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "Python installer returned $($proc.ExitCode)" }
    if (-not (Test-Path $PyExe)) { throw 'Python installer finished but python.exe is missing' }

    Say 'Installing base packages...'
    & $PyExe -m pip install --disable-pip-version-check --no-warn-script-location `
        --upgrade pip 2>&1 | Out-Null
    & $PyExe -m pip install --disable-pip-version-check --no-warn-script-location `
        pyyaml tkinterdnd2 2>&1 | Out-Null

    # Tkinter is what draws the window. Fail loudly here rather than silently later.
    & $PyExe -c "import tkinter" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Python installed without Tkinter - the interface cannot start' }

    Write-Host ''
    Write-Host '  Ready. Starting GRT Titrare.' -ForegroundColor Green
    Start-Sleep -Milliseconds 600
    exit 0
}
catch {
    Write-Host ''
    Write-Host "  Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host '  Check the internet connection and run this file again.'
    Write-Host ''
    if (Test-Path $PyDir) { Remove-Item -Recurse -Force $PyDir -ErrorAction SilentlyContinue }
    exit 1
}
finally {
    Remove-Item $installer -Force -ErrorAction SilentlyContinue
}
