"""Desktop shortcut.

Created through the Windows shell rather than by writing a .lnk by hand: the
format is undocumented, and the shell already knows where the Desktop actually
is — which on a machine with OneDrive is not where the obvious path points.

The shortcut targets pythonw.exe directly, not the .bat, so starting the app
never flashes a console window.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import env

ICON = env.ASSETS / env.ICON_NAME
NAME = "GRT Titrare"

_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop '{name}.lnk'
if (Test-Path $link) {{ Remove-Item $link -Force }}
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath       = '{target}'
$s.Arguments        = '{arguments}'
$s.WorkingDirectory = '{workdir}'
$s.IconLocation     = '{icon}'
$s.Description      = 'Титры на румынском из русского видео'
$s.Save()
Write-Output $link
"""

_FIND = r"""
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop '{name}.lnk'
if (Test-Path $link) {{ Write-Output $link }}
"""


def _powershell(script: str) -> str | None:
    if sys.platform != "win32":
        return None
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", script],
            capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace",
            creationflags=env.hide_console_flags())
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip()
    return output or None


def _target() -> tuple[Path, str]:
    """pythonw when the environment is built, the launcher otherwise."""
    if env.PYTHONW.exists():
        return env.PYTHONW, str(env.ROOT / "app" / "main.py")
    return env.ROOT / "GRT Titrare.bat", ""


def existing() -> Path | None:
    found = _powershell(_FIND.format(name=NAME))
    return Path(found) if found else None


def create() -> Path | None:
    if sys.platform != "win32":
        return None
    target, arguments = _target()
    icon = ICON if ICON.exists() else target

    script = _SCRIPT.format(
        name=NAME,
        target=str(target).replace("'", "''"),
        arguments=(f'"{arguments}"' if arguments else "").replace("'", "''"),
        workdir=str(env.ROOT).replace("'", "''"),
        icon=str(icon).replace("'", "''"),
    )
    result = _powershell(script)
    return Path(result) if result else None


ICON_STAMP = "icon-v11"       # bump when the icon changes


def ensure_once() -> Path | None:
    """Create the shortcut on first run, and refresh it when the icon changes.

    Only once otherwise: a shortcut the user deliberately deleted should stay
    deleted, and an application that keeps putting itself back on the desktop
    is one people learn to resent. A new icon is the exception — an existing
    shortcut would keep showing the old picture forever.
    """
    marker = env.DATA / "shortcut.done"
    if marker.exists():
        try:
            if ICON_STAMP in marker.read_text(encoding="utf-8"):
                return None
        except OSError:
            return None
        if existing() is None:
            return None            # deleted on purpose, leave it that way
    link = create()
    try:
        env.DATA.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{ICON_STAMP}\n{link or 'не создан'}",
                          encoding="utf-8")
    except OSError:
        pass
    return link
