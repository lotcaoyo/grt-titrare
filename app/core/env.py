"""Filesystem layout and configuration.

Everything the application needs lives under the package root. No component is
installed into the operating system, which is what makes the folder portable
and removable without traces.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

# Progress bars have nowhere to go in a windowed process, and the application
# draws its own anyway. Set before the libraries are imported.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TQDM_DISABLE", "1")

ROOT = Path(__file__).resolve().parents[2]

RUNTIME = ROOT / "runtime"
_VENV = RUNTIME / "python"

# A virtual environment keeps its executables in Scripts\; a plain install puts
# them next to the folder root. Both layouts are accepted so the bootstrap is
# free to pick whichever route worked on this particular machine.
PYTHON = (_VENV / "Scripts" / "python.exe" if (_VENV / "Scripts").is_dir()
          else _VENV / "python.exe")
PYTHONW = PYTHON.with_name("pythonw.exe")

# Heavy packages live outside the interpreter on purpose: rebuilding the
# environment then costs seconds instead of re-downloading four gigabytes.
PACKAGES = RUNTIME / "packages"
BIN = RUNTIME / "bin"
FFMPEG = BIN / "ffmpeg.exe"
FFPROBE = BIN / "ffprobe.exe"

ASSETS = ROOT / "assets"

# The icon file carries a version in its name on purpose. Windows caches icons
# by path, so replacing the contents of a file it has already seen changes
# nothing on screen — a new path is the only reliable way to refresh it.
ICON_NAME = "icon-v10.ico"

MODELS = ROOT / "models"
LOGS = ROOT / "logs"

# Internal state. The user never opens any of this: films are added by drag and
# drop, translation happens inside the window, and the finished .srt is written
# next to the source video where the editor already is.
DATA = ROOT / "data"
SESSIONS = DATA / "sessions"
TEMP = DATA / "temp"

CONFIG_FILE = ROOT / "config.yaml"
MANIFEST_FILE = ROOT / "manifest.json"
TERMBASE_FILE = ROOT / "termbase.yaml"

VIDEO_SUFFIXES = {
    ".mp4", ".mov", ".mkv", ".avi", ".mxf", ".m4v",
    ".wmv", ".flv", ".webm", ".mpg", ".mpeg", ".ts",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg",
}

DEFAULT_CONFIG: dict = {
    "recognition": {
        "language": "ru",
        "model": "auto",            # auto | large-v3 | medium
        "beam_size": 1,
        "word_timestamps": True,
        "vad": True,
        "batch_size": "auto",
    },
    "subtitles": {
        "max_chars_per_line": 42,
        "max_lines": 2,
        "max_cps": 17,
        "min_duration": 1.0,
        "max_duration": 7.0,
        "min_gap": 0.08,
        "offset": 0.0,
    },
    "sentences": {
        "pause_split": 0.7,
        "min_chars": 30,
        "max_chars": 250,
    },
    "translation": {
        "chunk_size": 150,
        "genre": "",
    },
    "update": {
        "enabled": True,
        "repo": "",              # "owner/repository" on GitHub
        "branch": "main",
        "check_on_start": True,
    },
    "termbase": {
        "shared_path": "",
    },
}


def read_version() -> str:
    """Single source of truth. Bumping manifest.json is what ships an update,
    so keeping the running version in the same file removes the chance of
    updating one and forgetting the other."""
    try:
        import json
        return str(json.loads(
            MANIFEST_FILE.read_text(encoding="utf-8")).get("version", "0.0.0"))
    except Exception:
        return "0.0.0"


VERSION = read_version()


def ensure_dirs() -> None:
    for path in (RUNTIME, BIN, PACKAGES, MODELS, LOGS, DATA, SESSIONS, TEMP):
        path.mkdir(parents=True, exist_ok=True)


def _merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return dict(DEFAULT_CONFIG)
    try:
        raw = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8")) or {}
    except Exception:
        return dict(DEFAULT_CONFIG)
    return _merge(DEFAULT_CONFIG, raw)


def enable_local_packages() -> None:
    """Make CUDA libraries shipped as pip wheels visible to ctranslate2.

    The wheels drop their DLLs into site-packages\\nvidia\\...\\bin. Since
    Python 3.8, Windows no longer searches PATH for dependent DLLs, so the
    directories have to be registered explicitly or the GPU path fails with an
    unhelpful import error.
    """
    package_root = str(PACKAGES)
    if package_root not in sys.path:
        sys.path.insert(0, package_root)

    if sys.platform != "win32":
        return
    nvidia_root = PACKAGES / "nvidia"
    if not nvidia_root.is_dir():
        return
    for bin_dir in sorted(nvidia_root.glob("*/bin")):
        try:
            os.add_dll_directory(str(bin_dir))
        except (OSError, AttributeError):
            pass
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def hide_console_flags() -> int:
    """Subprocess flag that keeps ffmpeg from flashing a black window."""
    if sys.platform == "win32":
        return 0x08000000  # CREATE_NO_WINDOW
    return 0
