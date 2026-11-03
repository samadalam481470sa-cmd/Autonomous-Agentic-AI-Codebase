"""Read-only local power and GPU telemetry for the always-on worker.

All probes are local executables or OS files. Nothing here installs drivers,
changes power settings, elevates privileges or contacts a network. Missing
telemetry is reported as unknown rather than assumed.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

NVIDIA_QUERY = [
    "nvidia-smi",
    "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
    "--format=csv,noheader,nounits",
]
ROCM_QUERY = ["rocm-smi", "--showuse", "--showtemp", "--json"]


def default_runner(argv, timeout=4):
    if not shutil.which(argv[0]):
        return None
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                                check=False, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_nvidia(text) -> list[dict]:
    devices = []
    for index, line in enumerate(str(text or "").splitlines()):
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        utilization, used, total, temperature = (_number(part) for part in parts[:4])
        if utilization is None and temperature is None:
            continue
        devices.append({
            "vendor": "nvidia", "index": index,
            "utilization_percent": utilization,
            "memory_used_mb": used, "memory_total_mb": total,
            "temperature_c": temperature,
        })
    return devices


def parse_rocm(text) -> list[dict]:
    try:
        payload = json.loads(str(text or "{}"))
    except ValueError:
        return []
    devices = []
    for index, (name, metrics) in enumerate(sorted(payload.items())):
        if not isinstance(metrics, dict):
            continue
        utilization = temperature = None
        for key, value in metrics.items():
            lowered = str(key).lower()
            if "use (%)" in lowered or "gpu use" in lowered:
                utilization = _number(str(value).replace("%", ""))
            elif "temperature" in lowered and "edge" in lowered:
                temperature = _number(str(value).replace("c", "").strip())
        if utilization is None and temperature is None:
            continue
        devices.append({
            "vendor": "amd", "index": index, "device": str(name)[:80],
            "utilization_percent": utilization, "memory_used_mb": None,
            "memory_total_mb": None, "temperature_c": temperature,
        })
    return devices


def gpu_status(*, runner=None, which=None, system=None) -> dict:
    runner = runner or default_runner
    which = which or shutil.which
    system = system or platform.system()
    source = "none"
    devices: list[dict] = []
    if which("nvidia-smi"):
        devices = parse_nvidia(runner(NVIDIA_QUERY))
        source = "nvidia-smi"
    if not devices and which("rocm-smi"):
        devices = parse_rocm(runner(ROCM_QUERY))
        if devices:
            source = "rocm-smi"
    apple = system == "Darwin" and platform.machine().lower() in ("arm64", "aarch64")
    utilizations = [item["utilization_percent"] for item in devices
                    if item.get("utilization_percent") is not None]
    temperatures = [item["temperature_c"] for item in devices
                    if item.get("temperature_c") is not None]
    return {
        "detected": bool(devices) or apple,
        "vendor": devices[0]["vendor"] if devices else ("apple" if apple else None),
        "devices": devices,
        "device_count": len(devices),
        "metrics_available": bool(devices),
        "max_utilization_percent": max(utilizations) if utilizations else None,
        "max_temperature_c": max(temperatures) if temperatures else None,
        "source": source,
        "note": (
            "Apple GPU telemetry needs privileged powermetrics; detection only."
            if apple and not devices else
            "Telemetry comes from vendor tools when installed; unknown is not zero usage."
        ),
    }


def parse_pmset(text):
    value = str(text or "")
    on_ac = None
    if "AC Power" in value:
        on_ac = True
    elif "Battery Power" in value:
        on_ac = False
    match = re.search(r"(\d{1,3})%", value)
    return {"on_ac": on_ac, "battery_percent": int(match.group(1)) if match else None}


def parse_windows_battery(text):
    """Parse ``BatteryStatus,EstimatedChargeRemaining`` output (2 = AC)."""
    value = str(text or "").strip()
    if not value:
        return {"on_ac": None, "battery_percent": None}
    parts = re.split(r"[,\s]+", value)
    status = None
    percent = None
    if parts:
        status = _number(parts[0])
    if len(parts) > 1:
        percent = _number(parts[1])
    on_ac = None if status is None else status == 2
    return {"on_ac": on_ac, "battery_percent": int(percent) if percent is not None else None}


def _linux_power(supply=Path("/sys/class/power_supply")) -> dict:
    on_ac = None
    percent = None
    try:
        entries = sorted(supply.glob("*"))
    except OSError:
        entries = []
    for entry in entries:
        try:
            kind = (entry / "type").read_text(encoding="utf-8").strip().lower()
        except (OSError, UnicodeError):
            continue
        if kind in ("mains", "ac", "ups") and on_ac is None:
            try:
                on_ac = (entry / "online").read_text(encoding="utf-8").strip() == "1"
            except (OSError, UnicodeError):
                on_ac = None
        if kind == "battery" and percent is None:
            try:
                percent = int((entry / "capacity").read_text(encoding="utf-8").strip())
            except (OSError, UnicodeError, ValueError):
                percent = None
    return {"on_ac": on_ac, "battery_percent": percent, "source": "sysfs"}


def power_state(*, runner=None, system=None, supply=Path("/sys/class/power_supply")) -> dict:
    runner = runner or default_runner
    system = system or platform.system()
    if system == "Linux":
        return _linux_power(supply)
    if system == "Darwin":
        result = parse_pmset(runner(["pmset", "-g", "batt"]))
        result["source"] = "pmset"
        return result
    if system == "Windows":
        result = parse_windows_battery(runner([
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Battery | Select-Object -First 1).BatteryStatus,"
            "(Get-CimInstance Win32_Battery | Select-Object -First 1).EstimatedChargeRemaining",
        ]))
        result["source"] = "win32_battery"
        return result
    return {"on_ac": None, "battery_percent": None, "source": "unsupported"}


def summary() -> dict:
    return {"gpu": gpu_status(), "power": power_state(), "platform": platform.platform()}
