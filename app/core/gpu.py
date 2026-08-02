"""Graphics card detection.

The card is read through NVML, the library that ships with every NVIDIA driver.
Reading it directly is more honest than asking a deep learning framework,
because it separates two failures that look identical to the user: a missing
driver and a missing CUDA library.
"""

from __future__ import annotations

import ctypes
import subprocess
from dataclasses import dataclass

from . import env


@dataclass
class GpuInfo:
    present: bool
    name: str = ""
    vram_gb: float = 0.0
    driver: str = ""
    reason: str = ""

    @property
    def summary(self) -> str:
        if not self.present:
            return self.reason or "Дискретная видеокарта не найдена"
        return f"{self.name} · {self.vram_gb:.0f} ГБ · драйвер {self.driver}"

    def recommended_model(self) -> str:
        """Larger models need room for weights plus activations."""
        if not self.present:
            return "medium"
        if self.vram_gb >= 7.5:
            return "large-v3"
        if self.vram_gb >= 4.5:
            return "medium"
        return "medium"

    def compute_type(self) -> str:
        if not self.present:
            return "int8"
        if self.vram_gb >= 7.5:
            return "float16"
        return "int8_float16"

    def batch_size(self) -> int:
        if not self.present:
            return 1
        if self.vram_gb >= 11:
            return 16
        if self.vram_gb >= 7.5:
            return 8
        return 4

    def speed_hint(self) -> str:
        if not self.present:
            return "Расчёт на процессоре — примерно в 20 раз медленнее"
        if self.vram_gb >= 11:
            return "Фильм на 25 минут — ориентировочно 2 минуты"
        if self.vram_gb >= 7.5:
            return "Фильм на 25 минут — ориентировочно 3 минуты"
        return "Фильм на 25 минут — ориентировочно 6 минут"


def _via_nvml() -> GpuInfo | None:
    try:
        nvml = ctypes.CDLL("nvml.dll")
    except OSError:
        return None

    if nvml.nvmlInit_v2() != 0:
        return None
    try:
        handle = ctypes.c_void_p()
        if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
            return None

        name = ctypes.create_string_buffer(96)
        nvml.nvmlDeviceGetName(handle, name, 96)

        driver = ctypes.create_string_buffer(80)
        nvml.nvmlSystemGetDriverVersion(driver, 80)

        class Memory(ctypes.Structure):
            _fields_ = [("total", ctypes.c_ulonglong),
                        ("free", ctypes.c_ulonglong),
                        ("used", ctypes.c_ulonglong)]

        memory = Memory()
        if nvml.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) != 0:
            return None

        return GpuInfo(
            present=True,
            name=name.value.decode("utf-8", "replace").replace("NVIDIA ", ""),
            vram_gb=memory.total / (1024 ** 3),
            driver=driver.value.decode("utf-8", "replace"),
        )
    finally:
        nvml.nvmlShutdown()


def _via_smi() -> GpuInfo | None:
    try:
        output = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15,
            creationflags=env.hide_console_flags(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if output.returncode != 0 or not output.stdout.strip():
        return None

    parts = [p.strip() for p in output.stdout.strip().splitlines()[0].split(",")]
    if len(parts) < 3:
        return None
    try:
        vram = float(parts[1]) / 1024
    except ValueError:
        return None
    return GpuInfo(present=True,
                   name=parts[0].replace("NVIDIA ", ""),
                   vram_gb=vram,
                   driver=parts[2])


_cached: GpuInfo | None = None


def detect(refresh: bool = False) -> GpuInfo:
    global _cached
    if _cached is not None and not refresh:
        return _cached
    info = _via_nvml() or _via_smi()
    if info is None:
        info = GpuInfo(
            present=False,
            reason="Драйвер NVIDIA не отвечает. Либо карта не NVIDIA, "
                   "либо драйвер не установлен.",
        )
    _cached = info
    return info
