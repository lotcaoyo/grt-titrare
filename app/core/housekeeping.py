"""Removal of leftovers from earlier versions.

Updating replaces files but cannot delete ones that no longer exist in the new
release, so every rename leaves a copy behind. Over a few versions that turns
the folder into a place where it is unclear what is current — and on a machine
handed to an editor, unclear means broken.

The list is explicit on purpose. No wildcards, no heuristics: only names this
project is known to have created and stopped using. Anything the user put there
is never touched.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import env

# Renamed in 1.1.1 — the Cyrillic name displayed as mojibake in Git.
OBSOLETE_FILES = ("ЧИТАТЬ.txt",)

# Matching by name is not enough: Git on Windows can check the file out with
# mangled bytes, so the name on disk is no longer the name that was committed.
# The first line of the old file is stable whatever happened to its name.
OBSOLETE_MARKER = "GRT TITRARE"

# Left behind by the silent Python installer when the target placeholder was
# not substituted.
OBSOLETE_DIRS = ("{app}", "{app")

# Working folders from the versions before the interface handled everything.
# Removed only when empty, because a file inside means unfinished work.
LEGACY_WORK = ("work/in", "work/out", "work/translate/.sessions",
               "work/translate", "work/done", "work/error", "work/.temp",
               "work")


def _is_empty(path: Path) -> bool:
    try:
        return not any(path.iterdir())
    except OSError:
        return False


def run() -> list[str]:
    """Returns what was removed, for the log."""
    removed: list[str] = []

    for name in OBSOLETE_FILES:
        target = env.ROOT / name
        if target.is_file():
            try:
                target.unlink()
                removed.append(name)
            except OSError:
                pass

    # Same file, unreadable name. Identified by what is inside it, and only
    # inside the package root — never in folders that hold the user's work.
    for candidate in env.ROOT.glob("*.txt"):
        try:
            if candidate.stat().st_size > 64_000:
                continue
            head = candidate.read_text(encoding="utf-8", errors="replace")
            if head.lstrip().upper().startswith(OBSOLETE_MARKER):
                candidate.unlink()
                removed.append(candidate.name)
        except OSError:
            continue

    for name in OBSOLETE_DIRS:
        target = env.ROOT / name
        if target.is_dir():
            try:
                shutil.rmtree(target)
                removed.append(f"{name}/")
            except OSError:
                pass

    for relative in LEGACY_WORK:
        target = env.ROOT / relative
        if target.is_dir() and _is_empty(target):
            try:
                target.rmdir()
                removed.append(f"{relative}/")
            except OSError:
                pass

    # Previous icon files: each release ships a new name to defeat the icon
    # cache, and the old ones are dead weight.
    assets = env.ROOT / "assets"
    if assets.is_dir():
        for old in assets.glob("icon*.ico"):
            if old.name != env.ICON_NAME:
                try:
                    old.unlink()
                    removed.append(f"assets/{old.name}")
                except OSError:
                    pass

    # Executables retired by an icon rebuild: they were still running when the
    # replacement arrived, so they could only be renamed, not removed.
    for stray in (env.RUNTIME / "python" / "Scripts").glob("*.old-*.exe"):
        try:
            stray.unlink()
            removed.append(f"runtime/.../{stray.name}")
        except OSError:
            pass

    # Half-built launcher left behind by an interrupted rebuild.
    for stray in (env.RUNTIME / "python" / "Scripts").glob("*.new"):
        try:
            stray.unlink()
            removed.append(f"runtime/.../{stray.name}")
        except OSError:
            pass

    # A backup is kept only until the next update proves the new code runs.
    backup = env.DATA / "app_backup"
    if backup.is_dir():
        try:
            shutil.rmtree(backup)
            removed.append("data/app_backup/")
        except OSError:
            pass

    if removed:
        try:
            env.LOGS.mkdir(parents=True, exist_ok=True)
            (env.LOGS / "cleanup.log").write_text(
                "Убрано при запуске:\n" + "\n".join(f"  {n}" for n in removed),
                encoding="utf-8")
        except OSError:
            pass
    return removed
