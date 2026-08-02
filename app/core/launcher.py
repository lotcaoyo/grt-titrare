"""A real executable of our own, with the icon inside it.

Windows takes the icon for a taskbar button — and for anything pinned — from
the resources of the running .exe, not from the window. While the process is
pythonw.exe, the Python logo is what the system will show, no matter what the
window carries. Pinning makes this permanent.

So the interpreter is copied under our own name and the icon is written into
its resource table. From then on the process is "GRT Titrare.exe" and Windows
has our picture to work with.
"""

from __future__ import annotations

import ctypes
import shutil
import struct
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from . import env

EXE_NAME = "GRT Titrare.exe"
RT_ICON = 3
RT_GROUP_ICON = 14


# --------------------------------------------------------------------------- #
#  icon resources
# --------------------------------------------------------------------------- #

def _read_ico(path: Path) -> tuple[list[bytes], list[tuple]]:
    """Split an .ico into its images and their directory entries."""
    blob = path.read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", blob, 0)
    if reserved or kind != 1 or not count:
        raise ValueError("это не файл иконки")

    images, entries = [], []
    for index in range(count):
        (width, height, colours, pad, planes, bits,
         size, offset) = struct.unpack_from("<BBBBHHII", blob, 6 + index * 16)
        images.append(blob[offset:offset + size])
        entries.append((width, height, colours, pad, planes, bits, size))
    return images, entries


def _group_icon(entries: list[tuple]) -> bytes:
    """The directory Windows reads to pick the right size.

    Same layout as the file header, except each entry ends with the resource id
    of its image instead of a file offset."""
    out = struct.pack("<HHH", 0, 1, len(entries))
    for index, (width, height, colours, pad, planes, bits, size) in enumerate(entries, 1):
        out += struct.pack("<BBBBHHIH", width, height, colours, pad,
                           planes, bits, size, index)
    return out


def _embed_icon(exe: Path, ico: Path) -> None:
    images, entries = _read_ico(ico)

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    # Типы ресурса и его номер передаются как MAKEINTRESOURCE: целое число,
    # подставленное на место указателя. Через LPCWSTR это не выразить, поэтому
    # оба параметра объявлены как указатели общего вида.
    kernel32.UpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                         wintypes.LPVOID, wintypes.WORD,
                                         wintypes.LPVOID, wintypes.DWORD]
    kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]

    handle = kernel32.BeginUpdateResourceW(str(exe), False)
    if not handle:
        raise OSError(f"BeginUpdateResource: {ctypes.get_last_error()}")

    try:
        for index, data in enumerate(images, 1):
            if not kernel32.UpdateResourceW(
                    handle, ctypes.c_void_p(RT_ICON), ctypes.c_void_p(index),
                    0, data, len(data)):
                raise OSError(f"UpdateResource RT_ICON {index}")

        group = _group_icon(entries)
        if not kernel32.UpdateResourceW(
                handle, ctypes.c_void_p(RT_GROUP_ICON), ctypes.c_void_p(1),
                0, group, len(group)):
            raise OSError("UpdateResource RT_GROUP_ICON")
    except Exception:
        kernel32.EndUpdateResourceW(handle, True)     # discard
        raise

    if not kernel32.EndUpdateResourceW(handle, False):
        raise OSError(f"EndUpdateResource: {ctypes.get_last_error()}")


# --------------------------------------------------------------------------- #
#  building it
# --------------------------------------------------------------------------- #

def path() -> Path:
    return env.PYTHONW.with_name(EXE_NAME)


def _works(exe: Path) -> bool:
    """A renamed interpreter must still interpret. Verify before trusting it."""
    try:
        result = subprocess.run([str(exe), "-c", "import sys; print(sys.version)"],
                                capture_output=True, text=True, timeout=30,
                                creationflags=env.hide_console_flags())
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure() -> Path | None:
    """Build the executable if missing or if the icon has changed."""
    if sys.platform != "win32" or not env.PYTHONW.exists():
        return None

    target = path()
    stamp = env.DATA / "launcher.stamp"
    if target.exists() and stamp.exists():
        try:
            if stamp.read_text(encoding="utf-8").strip() == env.ICON_NAME:
                return target
        except OSError:
            pass

    ico = env.ASSETS / env.ICON_NAME
    if not ico.exists():
        return None

    try:
        # A running copy cannot be replaced, so build beside it and swap.
        staging = target.with_suffix(".new")
        staging.unlink(missing_ok=True)
        shutil.copy2(env.PYTHONW, staging)
        _embed_icon(staging, ico)
        if not _works(staging):
            staging.unlink(missing_ok=True)
            return None
        target.unlink(missing_ok=True)
        staging.replace(target)
    except Exception:
        return target if target.exists() else None

    try:
        env.DATA.mkdir(parents=True, exist_ok=True)
        stamp.write_text(env.ICON_NAME, encoding="utf-8")
    except OSError:
        pass
    return target
