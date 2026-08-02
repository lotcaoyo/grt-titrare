"""Updates straight from GitHub.

Only the app\\ folder is replaced. The Python runtime, CUDA libraries and the
three gigabytes of model weights stay where they are, so an update is a fifty
kilobyte download and takes a second — which is what makes it realistic to fix
something in the evening and have every editor running the fix next morning.

The user's own config.yaml and termbase.yaml are never overwritten.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import env, launcher

MANIFEST_URL = "https://raw.githubusercontent.com/{repo}/{branch}/manifest.json"
ARCHIVE_URL = "https://codeload.github.com/{repo}/zip/refs/heads/{branch}"

PRESERVED = {"config.yaml", "termbase.yaml"}


@dataclass
class Release:
    version: str
    notes: str = ""

    def newer_than(self, current: str) -> bool:
        return _as_tuple(self.version) > _as_tuple(current)


def _as_tuple(version: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(version).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _settings() -> tuple[bool, str, str]:
    config = env.load_config().get("update", {})
    return (bool(config.get("enabled", True)),
            str(config.get("repo", "") or "").strip().strip("/"),
            str(config.get("branch", "main") or "main"))


def check() -> Release | None:
    """None means nothing to do: disabled, unconfigured, offline or current."""
    enabled, repo, branch = _settings()
    if not enabled or "/" not in repo:
        return None
    url = MANIFEST_URL.format(repo=repo, branch=branch)
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "GRT-Titrare",
                          "Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None

    release = Release(version=str(data.get("version", "0")),
                      notes=str(data.get("notes", "")))
    return release if release.newer_than(env.read_version()) else None


def install(progress: Callable[[float, str], None],
            log: Callable[[str], None]) -> str:
    """Downloads, swaps app\\ and returns the version now on disk."""
    enabled, repo, branch = _settings()
    if not enabled or "/" not in repo:
        raise RuntimeError("Обновления не настроены: укажите репозиторий "
                           "в config.yaml → update → repo")

    staging = Path(tempfile.mkdtemp(prefix="grt-update-"))
    archive = staging / "source.zip"
    try:
        progress(-1, "Загрузка обновления")
        log(f"Репозиторий {repo}, ветка {branch}")
        url = ARCHIVE_URL.format(repo=repo, branch=branch)
        request = urllib.request.Request(url, headers={"User-Agent": "GRT-Titrare"})
        with urllib.request.urlopen(request, timeout=90) as response, \
                open(archive, "wb") as handle:
            shutil.copyfileobj(response, handle)
        log(f"Загружено {archive.stat().st_size / 1e6:.1f} МБ")

        progress(-1, "Распаковка")
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)

        roots = [p for p in staging.iterdir() if p.is_dir()]
        if not roots:
            raise RuntimeError("Архив пуст")
        source_root = roots[0]

        new_app = source_root / "app"
        if not (new_app / "main.py").exists():
            raise RuntimeError("В обновлении нет папки app — проверьте структуру "
                               "репозитория")

        progress(-1, "Замена файлов")
        backup = env.DATA / "app_backup"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if (env.ROOT / "app").exists():
            shutil.move(str(env.ROOT / "app"), str(backup))
        try:
            shutil.move(str(new_app), str(env.ROOT / "app"))
        except Exception:
            if backup.exists():
                shutil.move(str(backup), str(env.ROOT / "app"))
            raise

        # Files the user owns are only created when absent, never replaced.
        for name in PRESERVED:
            incoming = source_root / name
            if incoming.exists() and not (env.ROOT / name).exists():
                shutil.copy2(incoming, env.ROOT / name)
                log(f"Добавлен {name}")

        # manifest.json carries the version, so it must travel with the code:
        # without it the app would keep believing it is still on the old build.
        # File names stay ASCII: Git on Windows escapes anything else, and the
        # repository then shows unreadable rubbish instead of the file name.
        for extra in ("manifest.json", "GRT Titrare.bat",
                      "bootstrap.ps1", "README.md"):
            incoming = source_root / extra
            if incoming.exists():
                shutil.copy2(incoming, env.ROOT / extra)

        version = _installed_version()
        log(f"Установлена версия {version}")
        progress(1.0, f"Версия {version} установлена")
        return version
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _installed_version() -> str:
    return env.read_version()


def restart() -> None:
    """Start the freshly installed code and let this process go."""
    own = launcher.ensure()
    executable = (own if own and own.exists()
                  else env.PYTHONW if env.PYTHONW.exists() else Path(sys.executable))
    entry = env.ROOT / "app" / "main.py"
    try:
        subprocess.Popen([str(executable), str(entry)],
                         cwd=str(env.ROOT), close_fds=True,
                         creationflags=env.hide_console_flags())
    except OSError:
        return
    os._exit(0)
