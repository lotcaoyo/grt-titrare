"""Component detection and installation.

Each component knows how to check itself and how to install itself. The user
interface only renders that state, so adding a component never touches the UI.

Nothing here writes outside the package folder: Python packages land in the
private interpreter, binaries in runtime\\bin, weights in models\\.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import env, gpu

Progress = Callable[[float, str], None]   # 0..1 (negative = indeterminate), caption
Log = Callable[[str], None]

READY, MISSING, BLOCKED = "ready", "missing", "blocked"

FFMPEG_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
              "ffmpeg-master-latest-win64-gpl.zip")

MODEL_REPOS = {
    "large-v3": ("Systran/faster-whisper-large-v3", 3_090),   # MB, for the bar
    "medium": ("Systran/faster-whisper-medium", 1_530),
}


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #

def _pip(packages: list[str], log: Log) -> None:
    """Install into the private interpreter, streaming pip's own output."""
    command = [str(env.PYTHON), "-m", "pip", "install",
               "--disable-pip-version-check", "--no-warn-script-location",
               "--no-input", "--upgrade",
               "--target", str(env.PACKAGES), *packages]
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
        creationflags=env.hide_console_flags(),
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if line:
            log(line)
    if process.wait() != 0:
        raise RuntimeError("pip завершился с ошибкой — подробности в журнале ниже")
    importlib.invalidate_caches()


def _download(url: str, target: Path, progress: Progress, caption: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "GRT-Titrare"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        with open(target, "wb") as handle:
            while True:
                chunk = response.read(1 << 18)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if total:
                    progress(done / total,
                             f"{caption} — {done / 1e6:.0f} из {total / 1e6:.0f} МБ")
                else:
                    progress(-1, f"{caption} — {done / 1e6:.0f} МБ")


def _folder_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1e6


def _importable(module: str) -> bool:
    env.enable_local_packages()
    try:
        importlib.invalidate_caches()
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# --------------------------------------------------------------------------- #
#  component definitions
# --------------------------------------------------------------------------- #

@dataclass
class Component:
    key: str
    title: str
    note: str
    size: str
    installable: bool = True
    log: list[str] = field(default_factory=list)

    def check(self) -> tuple[str, str]:
        raise NotImplementedError

    def install(self, progress: Progress, log: Log) -> None:
        raise NotImplementedError


class DriverComponent(Component):
    def __init__(self) -> None:
        super().__init__(
            key="driver",
            title="Видеокарта и драйвер",
            note="Единственное, что приложение не может установить само",
            size="",
            installable=False,
        )

    def check(self) -> tuple[str, str]:
        info = gpu.detect(refresh=True)
        if info.present:
            return READY, f"{info.summary}. {info.speed_hint()}"
        return BLOCKED, (f"{info.reason} Титры делать можно, "
                         f"но расчёт пойдёт на процессоре и будет медленным.")


class FfmpegComponent(Component):
    def __init__(self) -> None:
        super().__init__(
            key="ffmpeg",
            title="ffmpeg",
            note="Вытягивает звуковую дорожку из видеофайла",
            size="80 МБ",
        )

    def check(self) -> tuple[str, str]:
        if env.FFMPEG.exists():
            return READY, "Установлен в папке приложения"
        found = shutil.which("ffmpeg")
        if found:
            return READY, f"Найден в системе: {found}"
        return MISSING, "Не установлен"

    def install(self, progress: Progress, log: Log) -> None:
        archive = env.TEMP / "ffmpeg.zip"
        env.TEMP.mkdir(parents=True, exist_ok=True)
        log("Загрузка сборки ffmpeg с GitHub")
        _download(FFMPEG_URL, archive, progress, "Загрузка ffmpeg")

        progress(-1, "Распаковка")
        log("Распаковка исполняемых файлов")
        env.BIN.mkdir(parents=True, exist_ok=True)
        wanted = {"ffmpeg.exe", "ffprobe.exe"}
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.namelist():
                name = Path(member).name
                if name in wanted:
                    with bundle.open(member) as source, \
                         open(env.BIN / name, "wb") as destination:
                        shutil.copyfileobj(source, destination)
                        log(f"Извлечён {name}")
        archive.unlink(missing_ok=True)
        if not env.FFMPEG.exists():
            raise RuntimeError("В архиве не оказалось ffmpeg.exe")


class EngineComponent(Component):
    def __init__(self) -> None:
        super().__init__(
            key="engine",
            title="Движок распознавания",
            note="faster-whisper — распознаёт русскую речь и ставит тайм-коды",
            size="120 МБ",
        )

    def check(self) -> tuple[str, str]:
        if _importable("faster_whisper"):
            try:
                import faster_whisper  # noqa: F401
                version = getattr(faster_whisper, "__version__", "")
            except Exception:
                version = ""
            return READY, f"Установлен{f' · версия {version}' if version else ''}"
        return MISSING, "Не установлен"

    def install(self, progress: Progress, log: Log) -> None:
        progress(-1, "Установка пакетов")
        _pip(["faster-whisper==1.2.1"], log)
        if not _importable("faster_whisper"):
            raise RuntimeError("Пакет поставился, но не импортируется")


class CudaComponent(Component):
    def __init__(self) -> None:
        super().__init__(
            key="cuda",
            title="Библиотеки CUDA",
            note="cuBLAS и cuDNN — без них расчёт молча уходит на процессор",
            size="900 МБ",
        )

    def check(self) -> tuple[str, str]:
        root = env.PACKAGES / "nvidia"
        has_cublas = (root / "cublas" / "bin").is_dir()
        has_cudnn = (root / "cudnn" / "bin").is_dir()
        if has_cublas and has_cudnn:
            return READY, f"Установлены · {_folder_mb(root):.0f} МБ"
        if not gpu.detect().present:
            return BLOCKED, "Не нужны: дискретная видеокарта не обнаружена"
        return MISSING, "Не установлены — видеокарта простаивает"

    def install(self, progress: Progress, log: Log) -> None:
        progress(-1, "Установка библиотек CUDA — это самый долгий шаг")
        log("Загрузка cuBLAS и cuDNN для CUDA 12")
        _pip(["nvidia-cublas-cu12", "nvidia-cudnn-cu12>=9.1,<10"], log)
        env.enable_local_packages()


class ModelComponent(Component):
    def __init__(self) -> None:
        super().__init__(
            key="model",
            title="Модель распознавания",
            note="Веса Whisper. Подбираются по объёму памяти видеокарты",
            size="3,1 ГБ",
        )

    @staticmethod
    def _target(name: str) -> Path:
        return env.MODELS / f"faster-whisper-{name}"

    @staticmethod
    def resolve_name() -> str:
        config = env.load_config()
        choice = str(config["recognition"].get("model", "auto"))
        if choice in MODEL_REPOS:
            return choice
        return gpu.detect().recommended_model()

    def check(self) -> tuple[str, str]:
        for name in ("large-v3", "medium"):
            path = self._target(name)
            if (path / "model.bin").exists():
                return READY, f"{name} · {_folder_mb(path) / 1000:.1f} ГБ"
        wanted = self.resolve_name()
        self.size = "3,1 ГБ" if wanted == "large-v3" else "1,5 ГБ"
        return MISSING, f"Не загружена. Для этой машины подходит {wanted}"

    def install(self, progress: Progress, log: Log) -> None:
        if not _importable("huggingface_hub"):
            progress(-1, "Подготовка загрузчика")
            _pip(["huggingface_hub"], log)

        from huggingface_hub import snapshot_download

        name = self.resolve_name()
        repo, expected_mb = MODEL_REPOS[name]
        target = self._target(name)
        log(f"Модель {name} из репозитория {repo}")

        failure: list[BaseException] = []

        def worker() -> None:
            try:
                snapshot_download(
                    repo_id=repo,
                    local_dir=str(target),
                    allow_patterns=["*.bin", "*.json", "*.txt", "*.model"],
                    max_workers=4,
                )
            except BaseException as exc:      # reported on the main thread
                failure.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while thread.is_alive():
            done = _folder_mb(target)
            progress(min(done / expected_mb, 0.99),
                     f"Загрузка модели {name} — {done:.0f} из {expected_mb} МБ")
            time.sleep(0.5)
        thread.join()
        if failure:
            raise failure[0]
        if not (target / "model.bin").exists():
            raise RuntimeError("Загрузка завершилась, но файл модели отсутствует")
        progress(1.0, "Модель готова")


class SelfTestComponent(Component):
    """Answers the only question that matters before a shift starts:
    is this machine actually going to use the graphics card?"""

    def __init__(self) -> None:
        super().__init__(
            key="selftest",
            title="Проверка готовности",
            note="Прогоняет короткий тест и показывает реальную скорость",
            size="30 сек",
        )

    @property
    def _marker(self):
        return env.LOGS / "selftest.json"

    def check(self) -> tuple[str, str]:
        import json
        if not self._marker.exists():
            return MISSING, "Не проводилась. Займёт полминуты."
        try:
            data = json.loads(self._marker.read_text(encoding="utf-8"))
        except Exception:
            return MISSING, "Не проводилась"
        if data.get("gpu"):
            return READY, (f"{data['mode']} · {data['speed']:.0f}× реального времени. "
                           f"{data['forecast']}")
        return BLOCKED, (f"{data['mode']} · {data['speed']:.1f}× реального времени. "
                         f"{data['forecast']}")

    def install(self, progress: Progress, log: Log) -> None:
        import json
        import time as _time
        from .asr import Recogniser, extract_audio

        for name, component in (("ffmpeg", FfmpegComponent()),
                                ("движок", EngineComponent()),
                                ("модель", ModelComponent())):
            if component.check()[0] != READY:
                raise RuntimeError(f"Сначала установите: {name}")

        env.TEMP.mkdir(parents=True, exist_ok=True)
        env.LOGS.mkdir(parents=True, exist_ok=True)
        clip = env.TEMP / "selftest.wav"

        progress(-1, "Готовлю тестовый отрезок")
        log("Генерация 30-секундного отрезка")
        subprocess.run(
            [str(env.FFMPEG), "-y", "-f", "lavfi",
             "-i", "sine=frequency=180:duration=30",
             "-ac", "1", "-ar", "16000", "-loglevel", "error", str(clip)],
            check=True, creationflags=env.hide_console_flags())

        progress(-1, "Загружаю модель — первый запуск всегда дольше")
        recogniser = Recogniser(log)
        recogniser.load()

        progress(-1, "Считаю")
        started = _time.perf_counter()
        recogniser.transcribe(clip, _EmptyTermbase(), lambda v: progress(v, "Считаю"))
        elapsed = max(_time.perf_counter() - started, 0.01)

        speed = 30.0 / elapsed
        gpu_used = "видеокарта" in recogniser.mode
        minutes = 25 * 60 / speed / 60
        forecast = f"Фильм на 25 минут — примерно {minutes:.0f} мин."
        if not gpu_used:
            forecast += " Расчёт идёт на процессоре."

        self._marker.write_text(json.dumps(
            {"mode": recogniser.mode, "speed": speed, "gpu": gpu_used,
             "forecast": forecast}, ensure_ascii=False), encoding="utf-8")
        clip.unlink(missing_ok=True)
        log(f"Итог: {recogniser.mode}, {speed:.1f}x, {forecast}")
        progress(1.0, forecast)


class _EmptyTermbase:
    @staticmethod
    def asr_prompt() -> str:
        return ""

    @staticmethod
    def apply(text: str) -> str:
        return text


def all_components() -> list[Component]:
    return [DriverComponent(), FfmpegComponent(), EngineComponent(),
            CudaComponent(), ModelComponent(), SelfTestComponent()]


def ready_to_work(components: list[Component]) -> bool:
    """Blocked components are warnings, not stoppers — the CPU path still works."""
    required = {"ffmpeg", "engine", "model"}
    return all(component.check()[0] == READY
               for component in components if component.key in required)
