"""Local device runtime: hardware inventory, thermal governor and keep-awake.

The platform is local-first: this module discovers the machine it runs on
(CPU, RAM, GPU/VRAM, disk, battery), samples temperatures, and decides whether
heavy agent work is safe right now. It can also hold the operating system awake
for long runs, then release that hold automatically at critical temperature or
when its time budget expires.

Every probe is local. There is no telemetry, no remote call, and inference
servers are only contacted on loopback. Sensor access is best-effort: desktops
and virtual machines often expose no temperatures, in which case the governor
stays in monitor-only mode instead of blocking work.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import re
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from .security import audit, authorize

router = APIRouter(prefix="/api/device", tags=["device"])

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SYSTEM = platform.system()
MACHINE = platform.machine()


# ---------------------------------------------------------------------------
# Hardware inventory
# ---------------------------------------------------------------------------

def _cmd(args: list[str], timeout: float = 3.0) -> str | None:
    """Run a read-only diagnostic command if it is installed."""
    if not args or not shutil.which(args[0]):
        return None
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _parse_meminfo(text: str) -> dict:
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, rest = line.partition(":")
        if not separator:
            continue
        token = rest.strip().split(" ")[0] if rest.strip() else ""
        try:
            values[key] = int(token) * 1024
        except ValueError:
            continue
    return {
        "total_bytes": values.get("MemTotal"),
        "available_bytes": values.get("MemAvailable", values.get("MemFree")),
    }


def memory_info() -> dict:
    total = available = None
    source = SYSTEM
    if SYSTEM == "Linux":
        try:
            parsed = _parse_meminfo(Path("/proc/meminfo").read_text(encoding="utf-8"))
        except OSError:
            parsed = {}
        total = parsed.get("total_bytes")
        available = parsed.get("available_bytes")
    elif SYSTEM == "Darwin":
        raw = _cmd(["sysctl", "-n", "hw.memsize"])
        if raw and raw.isdigit():
            total = int(raw)
    elif SYSTEM == "Windows":
        try:
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                total = int(status.ullTotalPhys)
                available = int(status.ullAvailPhys)
        except (AttributeError, OSError, ValueError):
            total = available = None
    total_mb = round(total / 1048576) if total else None
    available_mb = round(available / 1048576) if available else None
    used_percent = None
    if total_mb and available_mb is not None:
        used_percent = round(100 * (1 - available_mb / total_mb))
    return {
        "total_mb": total_mb,
        "available_mb": available_mb,
        "used_percent": used_percent,
        "source": source,
    }


def cpu_info() -> dict:
    model = ""
    if SYSTEM == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.lower().startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
        except OSError:
            model = ""
    elif SYSTEM == "Darwin":
        model = _cmd(["sysctl", "-n", "machdep.cpu.brand_string"]) or ""
    if not model:
        model = platform.processor() or MACHINE

    physical = None
    frequency = None
    if SYSTEM == "Linux":
        physical_ids: set[tuple[str, str]] = set()
        try:
            physical_id = core_id = None
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("physical id"):
                    physical_id = line.split(":", 1)[1].strip()
                elif line.startswith("core id"):
                    core_id = line.split(":", 1)[1].strip()
                elif line.startswith("cpu MHz"):
                    try:
                        value = float(line.split(":", 1)[1].strip())
                        frequency = max(frequency or 0.0, value)
                    except ValueError:
                        pass
                elif not line.strip() and physical_id is not None:
                    physical_ids.add((physical_id, core_id or ""))
                    physical_id = core_id = None
        except OSError:
            physical_ids = set()
        physical = len(physical_ids) or None
    elif SYSTEM == "Darwin":
        raw = _cmd(["sysctl", "-n", "hw.physicalcpu"])
        physical = int(raw) if raw and raw.isdigit() else None
        raw_freq = _cmd(["sysctl", "-n", "hw.cpufrequency_max"])
        if raw_freq and raw_freq.isdigit():
            frequency = round(int(raw_freq) / 1_000_000, 1)

    return {
        "model": model[:160],
        "logical_cores": os.cpu_count(),
        "physical_cores": physical,
        "max_frequency_mhz": round(frequency, 1) if frequency else None,
        "architecture": MACHINE,
    }


def _parse_nvidia_csv(text: str) -> list[dict]:
    gpus = []
    for row in text.splitlines():
        parts = [part.strip() for part in row.split(",")]
        if len(parts) < 4:
            continue

        def number(value: str, cast: Callable[[str], float] = float):
            try:
                return cast(value)
            except (TypeError, ValueError):
                return None

        gpus.append({
            "vendor": "nvidia",
            "name": parts[0][:120],
            "vram_mb": number(parts[1]),
            "used_mb": number(parts[2]),
            "temp_c": number(parts[3]),
            "utilization_pct": number(parts[4]) if len(parts) > 4 else None,
            "driver": parts[5] if len(parts) > 5 else None,
            "unified_memory": False,
        })
    return gpus


def _numeric(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def gpu_info() -> list[dict]:
    gpus = _parse_nvidia_csv(_cmd([
        "nvidia-smi",
        "--query-gpu=name,memory.total,memory.used,temperature.gpu,utilization.gpu,driver_version",
        "--format=csv,noheader,nounits",
    ], timeout=2.5) or "")
    if gpus:
        return gpus

    if SYSTEM == "Darwin" and MACHINE == "arm64":
        return [{
            "vendor": "apple",
            "name": "Apple Silicon GPU (Metal, unified memory)",
            "vram_mb": None,
            "used_mb": None,
            "temp_c": None,
            "utilization_pct": None,
            "driver": None,
            "unified_memory": True,
        }]

    raw = _cmd([
        "rocm-smi", "--showtemp", "--showmeminfo", "vram", "--json"
    ], timeout=2.5)
    if raw:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        cards = []
        for key, card in data.items():
            if not isinstance(card, dict):
                continue
            temperature = next(
                (_numeric(value) for name, value in card.items()
                 if "Temperature" in name and "(C)" in name and _numeric(value) is not None),
                None,
            )
            total = next(
                (_numeric(value) for name, value in card.items()
                 if "VRAM Total Memory" in name and _numeric(value) is not None),
                None,
            )
            used = next(
                (_numeric(value) for name, value in card.items()
                 if "VRAM Total Used" in name and _numeric(value) is not None),
                None,
            )
            name = card.get("Card series") or card.get("Card SKU") or f"AMD GPU {key}"
            cards.append({
                "vendor": "amd",
                "name": str(name)[:120],
                "vram_mb": round(total / 1048576) if total else None,
                "used_mb": round(used / 1048576) if used else None,
                "temp_c": temperature,
                "utilization_pct": None,
                "driver": "ROCm",
                "unified_memory": False,
            })
        return cards
    return []


def battery_info() -> dict | None:
    if SYSTEM == "Linux":
        for path in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            try:
                percent = int((path / "capacity").read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                continue
            try:
                status = (path / "status").read_text(encoding="utf-8").strip()
            except OSError:
                status = "unknown"
            return {
                "present": True,
                "percent": max(0, min(100, percent)),
                "plugged": status.lower() in {"charging", "full"},
                "status": status,
            }
    elif SYSTEM == "Darwin":
        raw = _cmd(["pmset", "-g", "batt"])
        if raw:
            match = re.search(r"(\d+)%", raw)
            if match:
                return {
                    "present": True,
                    "percent": int(match.group(1)),
                    "plugged": "AC Power" in raw,
                    "status": "charging" if "charging" in raw else "discharging",
                }
    return None


def platform_info() -> dict:
    return {
        "system": SYSTEM,
        "release": platform.release(),
        "machine": MACHINE,
        "python": platform.python_version(),
        "hostname": socket.gethostname()[:64],
        "apple_silicon": SYSTEM == "Darwin" and MACHINE == "arm64",
        "container": Path("/.dockerenv").exists(),
    }


def disk_info() -> dict | None:
    try:
        usage = shutil.disk_usage(Path.cwd())
    except OSError:
        return None
    return {
        "total_gb": round(usage.total / 1073741824, 1),
        "free_gb": round(usage.free / 1073741824, 1),
        "used_percent": round(100 * usage.used / usage.total) if usage.total else 0,
    }


_HW_LOCK = threading.Lock()
_HW_CACHE: dict = {"at": 0.0, "data": None}


def hardware_report(force: bool = False) -> dict:
    with _HW_LOCK:
        cached = _HW_CACHE["data"]
        fresh = cached is not None and time.time() - _HW_CACHE["at"] < 5
        if fresh and not force:
            return cached
    data = {
        "platform": platform_info(),
        "cpu": cpu_info(),
        "memory": memory_info(),
        "disk": disk_info(),
        "gpus": gpu_info(),
        "battery": battery_info(),
    }
    with _HW_LOCK:
        _HW_CACHE.update(at=time.time(), data=data)
    return data


def recommend_model(memory: dict, gpus: list[dict]) -> dict:
    ram_mb = memory.get("total_mb") or 0
    vram_mb = max((gpu.get("vram_mb") or 0 for gpu in gpus), default=0)
    unified = any(gpu.get("unified_memory") for gpu in gpus)
    budget_mb = vram_mb or (int(ram_mb * 0.6) if unified else 0)

    if budget_mb >= 24000:
        name, context, layers, vram = "qwen2.5-coder:32b", 16384, 99, 20.0
    elif budget_mb >= 14000:
        name, context, layers, vram = "qwen2.5-coder:14b", 8192, 99, 9.0
    elif budget_mb >= 9000:
        name, context, layers, vram = "qwen2.5-coder:14b", 8192, 99, 9.0
    elif budget_mb >= 5500:
        name, context, layers, vram = "qwen2.5-coder:7b", 8192, 99, 4.7
    elif budget_mb >= 3500:
        name, context, layers, vram = "qwen2.5-coder:3b", 4096, 99, 2.0
    elif ram_mb >= 16000:
        name, context, layers, vram = "qwen2.5-coder:7b", 4096, 0, None
    elif ram_mb >= 8000:
        name, context, layers, vram = "qwen2.5-coder:3b", 4096, 0, None
    else:
        name, context, layers, vram = "qwen2.5-coder:1.5b", 2048, 0, None

    if budget_mb >= 24000:
        reason = "Large GPU memory: strongest local coding model with a wide context."
    elif budget_mb >= 9000:
        reason = "Enough GPU memory for a 14B quantized coding model."
    elif budget_mb >= 5500:
        reason = "A 7B quantized model fits comfortably in this GPU."
    elif budget_mb >= 3500:
        reason = "Small GPU memory: a 3B model keeps latency and heat low."
    elif ram_mb:
        reason = "No usable GPU memory detected: CPU inference with a small model."
    else:
        reason = "Memory could not be detected: start with the smallest model."
    base = os.getenv("LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1")
    return {
        "name": name,
        "runtime": "ollama",
        "context_tokens": context,
        "gpu_layers": layers,
        "estimated_vram_gb": vram,
        "reason": reason,
        "pull_command": f"ollama pull {name}",
        "env": {
            "LOCAL_MODEL_ONLY": "1",
            "LOCAL_MODEL_BASE_URL": base,
            "LOCAL_MODEL_NAME": name,
            "LOCAL_CONTEXT_CHAR_BUDGET": str(min(context * 3, 12000)),
        },
    }


def _models(payload) -> list[str]:
    if not isinstance(payload, dict):
        return []
    names = []
    if isinstance(payload.get("models"), list):
        for item in payload["models"]:
            if isinstance(item, dict):
                value = item.get("name") or item.get("model")
                if value:
                    names.append(str(value)[:120])
    if isinstance(payload.get("data"), list):
        for item in payload["data"]:
            if isinstance(item, dict) and item.get("id"):
                names.append(str(item["id"])[:120])
    return names[:12]


def _check_backend(spec: tuple[str, str, str]) -> dict:
    name, base, path = spec
    try:
        request = Request(base.rstrip("/") + path, headers={"Accept": "application/json"})
        with urlopen(request, timeout=0.6) as response:
            if response.status != 200:
                return {"name": name, "url": base, "status": "offline", "models": []}
            payload = json.loads(response.read(65536).decode("utf-8", "replace"))
        return {"name": name, "url": base, "status": "ready", "models": _models(payload)}
    except (URLError, OSError, ValueError, TimeoutError):
        return {"name": name, "url": base, "status": "offline", "models": []}


def probe_backends() -> list[dict]:
    specs = [
        ("ollama", "http://127.0.0.1:11434", "/api/tags"),
        ("llama.cpp", "http://127.0.0.1:9931", "/v1/models"),
        ("llama.cpp", "http://127.0.0.1:8080", "/v1/models"),
        ("lm-studio", "http://127.0.0.1:1234", "/v1/models"),
    ]
    configured = os.getenv("LOCAL_MODEL_BASE_URL", "").strip().rstrip("/")
    if configured:
        parsed = urlsplit(configured)
        if (parsed.scheme == "http" and parsed.hostname in LOOPBACK
                and not parsed.username and not parsed.password):
            specs = [("configured", configured, "/models")] + [
                spec for spec in specs if spec[1] != configured
            ]
    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        return list(pool.map(_check_backend, specs))


# ---------------------------------------------------------------------------
# Thermal sensors and governor
# ---------------------------------------------------------------------------

def read_thermal_sensors() -> list[dict]:
    sensors: dict[str, float] = {}

    def add(label: str, celsius: float) -> None:
        if -20 <= celsius <= 150:
            sensors[label[:80]] = max(sensors.get(label[:80], -999.0), round(celsius, 1))

    thermal = Path("/sys/class/thermal")
    if thermal.is_dir():
        for zone in thermal.glob("thermal_zone*"):
            try:
                raw = (zone / "temp").read_text(encoding="utf-8").strip()
                label = (zone / "type").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            try:
                value = float(raw)
            except ValueError:
                continue
            add(label or zone.name, value / 1000 if abs(value) > 1000 else value)

    hwmon = Path("/sys/class/hwmon")
    if hwmon.is_dir():
        for chip in hwmon.glob("hwmon*"):
            try:
                chip_name = (chip / "name").read_text(encoding="utf-8").strip()
            except OSError:
                chip_name = chip.name
            for entry in chip.glob("temp*_input"):
                try:
                    value = float(entry.read_text(encoding="utf-8").strip()) / 1000
                except (OSError, ValueError):
                    continue
                add(f"{chip_name}/{entry.stem}", value)

    gpu_temps = _cmd([
        "nvidia-smi", "--query-gpu=name,temperature.gpu",
        "--format=csv,noheader,nounits",
    ], timeout=2)
    if gpu_temps:
        for row in gpu_temps.splitlines():
            parts = [part.strip() for part in row.split(",")]
            if len(parts) >= 2:
                try:
                    add(parts[0] or "gpu", float(parts[1]))
                except ValueError:
                    continue

    return [
        {"label": label, "celsius": value}
        for label, value in sorted(sensors.items(), key=lambda item: item[1], reverse=True)
    ]


def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


def thermal_limits() -> dict:
    return {
        "warn_c": _env_float("DEVICE_TEMP_WARN_C", 78, 40, 100),
        "hot_c": _env_float("DEVICE_TEMP_HOT_C", 86, 45, 105),
        "critical_c": _env_float("DEVICE_TEMP_CRITICAL_C", 92, 50, 110),
        "resume_c": _env_float("DEVICE_TEMP_RESUME_C", 70, 30, 95),
        "cooldown_seconds": _env_int("DEVICE_COOLDOWN_SECONDS", 30, 5, 600),
        "sample_seconds": _env_int("DEVICE_SAMPLE_SECONDS", 5, 1, 300),
        "min_battery_percent": _env_int("DEVICE_MIN_BATTERY_PERCENT", 15, 0, 100),
        "max_hours": _env_float("DEVICE_SESSION_MAX_HOURS", 8, 0.5, 72),
        "predict_minutes": _env_float("DEVICE_PREDICT_MINUTES", 1.5, 0, 10),
    }


class ThermalGovernor:
    """Samples temperatures and decides whether heavy work may proceed.

    The controller uses an exponentially weighted temperature, a short-horizon
    slope and a predicted temperature to pause before the critical limit, then
    applies hysteresis plus a cooldown before resuming. With no sensors it
    stays permissive and reports monitor-only mode rather than inventing data.
    """

    def __init__(self, reader: Callable[[], list[dict]] | None = None,
                 clock: Callable[[], float] | None = None,
                 thresholds: dict | None = None,
                 db_path: str | Path | None = None) -> None:
        self._reader = reader or read_thermal_sensors
        self._clock = clock or time.time
        limits = thermal_limits()
        limits.update(thresholds or {})
        self.warn = float(limits["warn_c"])
        self.hot = float(limits["hot_c"])
        self.critical = float(limits["critical_c"])
        self.resume = float(limits["resume_c"])
        self.cooldown = float(limits["cooldown_seconds"])
        self.sample_seconds = float(limits["sample_seconds"])
        self.predict_minutes = float(limits["predict_minutes"])
        self.min_battery = float(limits["min_battery_percent"])
        self.max_hours = float(limits["max_hours"])
        self._db = Path(db_path or os.getenv("DEVICE_DB_PATH", "./database/device.sqlite3"))
        self._lock = threading.RLock()
        self._sensors: list[dict] = []
        self._samples: deque = deque(maxlen=240)
        self._events: deque = deque(maxlen=40)
        self._state = "unknown"
        self._max_c: float | None = None
        self._ewma: float | None = None
        self._slope = 0.0
        self._predicted: float | None = None
        self._cooldown_until = 0.0
        self._last_sample = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.session_started = self._clock()

    def _record(self, kind: str, detail: str) -> None:
        try:
            self._db.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._db, timeout=5)) as con, con:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute(
                    "CREATE TABLE IF NOT EXISTS device_events("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER NOT NULL,"
                    "kind TEXT NOT NULL, detail TEXT NOT NULL)"
                )
                con.execute(
                    "INSERT INTO device_events(created_at,kind,detail) VALUES(?,?,?)",
                    (int(time.time()), kind[:48], detail[:300]),
                )
                con.execute(
                    "DELETE FROM device_events WHERE id NOT IN "
                    "(SELECT id FROM device_events ORDER BY id DESC LIMIT 500)"
                )
        except (sqlite3.Error, OSError):
            return

    def sample_once(self, force: bool = False) -> dict:
        with self._lock:
            now = self._clock()
            if not force and self._last_sample and now - self._last_sample < 1.0:
                return self._snapshot(now)
            self._last_sample = now
            try:
                sensors = self._reader() or []
            except Exception:
                sensors = []
            cleaned = []
            for sensor in sensors[:32]:
                if not isinstance(sensor, dict):
                    continue
                value = _numeric(sensor.get("celsius"))
                if value is None:
                    continue
                cleaned.append({
                    "label": str(sensor.get("label") or "sensor")[:80],
                    "celsius": round(max(-20.0, min(150.0, value)), 1),
                })
            self._sensors = cleaned
            values = [sensor["celsius"] for sensor in cleaned]
            previous_ewma = self._ewma

            if values:
                self._max_c = max(values)
                self._ewma = (
                    self._max_c if previous_ewma is None
                    else round(0.3 * self._max_c + 0.7 * previous_ewma, 2)
                )
                self._samples.append((now, self._ewma))
                while len(self._samples) > 2 and now - self._samples[0][0] > 180:
                    self._samples.popleft()
                if len(self._samples) >= 2:
                    first_at, first_value = self._samples[0]
                    minutes = (now - first_at) / 60
                    self._slope = (
                        (self._ewma - first_value) / minutes if minutes > 0.01 else 0.0
                    )
                else:
                    self._slope = 0.0
                self._predicted = round(self._ewma + self._slope * self.predict_minutes, 2)
            else:
                self._max_c = None
                self._ewma = None
                self._predicted = None
                self._slope = 0.0

            previous_state = self._state
            if self._max_c is None:
                state = "unknown"
            elif (self._max_c >= self.critical
                  or (self._predicted is not None and self._predicted >= self.critical
                      and self._max_c >= self.warn - 5)):
                state = "critical"
                self._cooldown_until = max(self._cooldown_until, now + self.cooldown)
            elif (self._max_c >= self.hot
                  or (self._predicted is not None and self._predicted >= self.hot + 2
                      and self._max_c >= self.warn - 5)):
                state = "hot"
                self._cooldown_until = max(self._cooldown_until, now + self.cooldown)
            elif now < self._cooldown_until:
                state = "cooldown"
            elif previous_state in ("hot", "critical", "cooldown") and self._max_c > self.resume:
                state = "warm"
            elif self._max_c >= self.warn:
                state = "warm"
            else:
                state = "normal"
                self._cooldown_until = 0.0

            self._state = state
            if state != previous_state:
                self._events.append({
                    "at": int(now),
                    "from": previous_state,
                    "to": state,
                    "celsius": self._max_c,
                })
                self._record(
                    "thermal." + state,
                    f"{previous_state}->{state} max={self._max_c}",
                )
                if state == "critical":
                    keeper = globals().get("KEEP_AWAKE")
                    if keeper is not None:
                        keeper.stop(reason="thermal")
            return self._snapshot(now)

    def _admission_locked(self, now: float) -> dict:
        if self._max_c is None:
            return {
                "allowed": True,
                "reason": "No temperature sensors detected; thermal guard is in monitor-only mode.",
                "retry_after": 0,
                "mode": "monitor",
            }
        if self._state == "critical":
            return {
                "allowed": False,
                "reason": f"Device at {self._max_c:.0f}°C is above the critical limit; work paused.",
                "retry_after": max(5, int(self._cooldown_until - now) + 5),
                "mode": "paused",
            }
        if self._state == "hot":
            return {
                "allowed": False,
                "reason": f"Device at {self._max_c:.0f}°C is too hot for another model call.",
                "retry_after": max(5, int(self._cooldown_until - now) + 5),
                "mode": "paused",
            }
        if now < self._cooldown_until:
            return {
                "allowed": False,
                "reason": "Cooling down after a hot period; work resumes automatically.",
                "retry_after": max(1, int(self._cooldown_until - now) + 1),
                "mode": "cooling",
            }
        battery = battery_info()
        if battery and battery.get("percent") is not None and not battery.get("plugged"):
            if battery["percent"] < self.min_battery:
                return {
                    "allowed": False,
                    "reason": (
                        f"Battery at {battery['percent']}% is below the "
                        f"{self.min_battery:.0f}% safety floor."
                    ),
                    "retry_after": 60,
                    "mode": "battery",
                }
        if self._state == "warm":
            return {
                "allowed": True,
                "reason": f"Running warm at {self._max_c:.0f}°C; keep sessions short and vents clear.",
                "retry_after": 0,
                "mode": "warm",
            }
        return {
            "allowed": True,
            "reason": f"Within thermal budget at {self._max_c:.0f}°C.",
            "retry_after": 0,
            "mode": "active",
        }

    def _duty_cycle(self) -> float:
        return {"normal": 1.0, "warm": 0.6, "hot": 0.0,
                "critical": 0.0, "cooldown": 0.0}.get(self._state, 1.0)

    def _snapshot(self, now: float) -> dict:
        return {
            "state": self._state,
            "max_c": round(self._max_c, 1) if self._max_c is not None else None,
            "ewma_c": round(self._ewma, 1) if self._ewma is not None else None,
            "slope_c_per_min": round(self._slope, 2),
            "predicted_c": self._predicted,
            "sensors": list(self._sensors),
            "thresholds": {
                "warn": self.warn,
                "hot": self.hot,
                "critical": self.critical,
                "resume": self.resume,
            },
            "cooldown_remaining": max(0, int(round(self._cooldown_until - now))),
            "duty_cycle": self._duty_cycle(),
            "sensors_available": bool(self._sensors),
            "note": (
                "No temperature sensors exposed by this system. The guard cannot "
                "throttle; keep-awake and session limits still apply."
                if self._max_c is None else
                "Heavy work is paused until the device cools."
                if self._state in ("hot", "critical", "cooldown") else
                "Running warm; reduce sustained load."
                if self._state == "warm" else
                "Temperature is within the configured budget."
            ),
            "history": [
                {"t": round(at, 1), "c": round(value, 1)}
                for at, value in list(self._samples)[-60:]
            ],
            "events": list(self._events)[-8:],
            "sample_seconds": self.sample_seconds,
            "admission": self._admission_locked(now),
        }

    def admission(self) -> dict:
        self.sample_once()
        with self._lock:
            return self._admission_locked(self._clock())

    def status(self) -> dict:
        self.sample_once()
        with self._lock:
            return self._snapshot(self._clock())

    def ensure_monitor(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()

            def loop() -> None:
                while not self._stop.wait(self.sample_seconds):
                    try:
                        self.sample_once(force=True)
                    except Exception:
                        continue

            self._thread = threading.Thread(
                target=loop, name="thermal-monitor", daemon=True
            )
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=1.5)


# ---------------------------------------------------------------------------
# Keep-awake
# ---------------------------------------------------------------------------

class KeepAwake:
    """Hold the operating system awake with the platform's native mechanism."""

    def __init__(self, system: str | None = None,
                 clock: Callable[[], float] | None = None,
                 starter: Callable[[], dict | None] | None = None) -> None:
        self._system = system or SYSTEM
        self._clock = clock or time.time
        self._starter = starter
        self._lock = threading.RLock()
        self._active = False
        self._backend: str | None = None
        self._pid: int | None = None
        self._note = ""
        self._started_at: float | None = None
        self._expires_at: float | None = None
        self._stop_backend: Callable[[], None] | None = None

    def _spawn(self, command: list[str], backend: str) -> dict | None:
        try:
            process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except (OSError, ValueError):
            return None
        time.sleep(0.2)
        if process.poll() is not None:
            return None

        def stop() -> None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()

        return {"backend": backend, "pid": process.pid, "note": "", "stop": stop}

    def _windows(self) -> dict | None:
        try:
            kernel = ctypes.windll.kernel32
        except AttributeError:
            return None
        continuous = 0x80000000
        system_required = 0x00000001
        display_required = 0x00000002
        stop_event = threading.Event()

        def hold() -> None:
            kernel.SetThreadExecutionState(
                continuous | system_required | display_required
            )
            while not stop_event.wait(20):
                kernel.SetThreadExecutionState(
                    continuous | system_required | display_required
                )
            kernel.SetThreadExecutionState(continuous)

        thread = threading.Thread(target=hold, name="keep-awake", daemon=True)
        thread.start()

        def stop() -> None:
            stop_event.set()
            thread.join(timeout=2)

        return {
            "backend": "SetThreadExecutionState",
            "pid": None,
            "note": "Windows system and display hold",
            "stop": stop,
        }

    def _start_backend(self) -> dict | None:
        if self._starter is not None:
            return self._starter()
        if self._system == "Darwin":
            return self._spawn(["caffeinate", "-dimsu"], "caffeinate")
        if self._system == "Linux":
            if shutil.which("systemd-inhibit"):
                return self._spawn([
                    "systemd-inhibit",
                    "--what=idle:sleep",
                    "--who=Aetherion OmniForge",
                    "--why=Local agent session",
                    "--mode=block",
                    "sleep", "infinity",
                ], "systemd-inhibit")
            return None
        if self._system == "Windows":
            return self._windows()
        return None

    def _supported(self) -> bool:
        if self._starter is not None:
            return True
        if self._system == "Darwin":
            return shutil.which("caffeinate") is not None
        if self._system == "Linux":
            return shutil.which("systemd-inhibit") is not None
        return self._system == "Windows"

    def _status_locked(self) -> dict:
        now = self._clock()
        remaining = (
            max(0, int(self._expires_at - now))
            if self._active and self._expires_at else None
        )
        return {
            "active": self._active,
            "backend": self._backend,
            "pid": self._pid,
            "started_at": int(self._started_at) if self._started_at else None,
            "expires_at": int(self._expires_at) if self._expires_at else None,
            "ttl_remaining_seconds": remaining,
            "note": self._note,
            "supported": self._supported(),
        }

    def start(self, reason: str = "local session",
              ttl_seconds: int | None = None) -> dict:
        with self._lock:
            if self._active:
                if ttl_seconds:
                    self._expires_at = self._clock() + ttl_seconds
                return self._status_locked()
            result = self._start_backend()
            if not result:
                self._backend = None
                self._pid = None
                self._note = (
                    "The operating system did not provide a sleep inhibitor. "
                    "Work continues, but the machine may sleep."
                )
                audit("device.keepawake.unavailable", self._note)
                return self._status_locked()
            self._active = True
            self._backend = result.get("backend")
            self._pid = result.get("pid")
            self._note = result.get("note", "")
            self._stop_backend = result.get("stop")
            self._started_at = self._clock()
            self._expires_at = (
                self._clock() + ttl_seconds if ttl_seconds else None
            )
            audit("device.keepawake.start", f"{reason} via {self._backend}")
            return self._status_locked()

    def touch(self, ttl_seconds: int = 7200) -> dict:
        with self._lock:
            if self._active:
                self._expires_at = self._clock() + max(60, int(ttl_seconds))
            return self._status_locked()

    def stop(self, reason: str = "manual") -> dict:
        with self._lock:
            if not self._active:
                return self._status_locked()
            backend = self._backend
            stop_backend = self._stop_backend
            self._active = False
            self._backend = None
            self._pid = None
            self._started_at = None
            self._expires_at = None
            self._stop_backend = None
            self._note = ""
            audit("device.keepawake.stop", f"{reason} via {backend}")
        if stop_backend is not None:
            try:
                stop_backend()
            except Exception:
                pass
        return self.status()

    def status(self) -> dict:
        with self._lock:
            expired = (
                self._active
                and self._expires_at is not None
                and self._clock() >= self._expires_at
            )
        if expired:
            return self.stop(reason="ttl")
        with self._lock:
            return self._status_locked()


KEEP_AWAKE = KeepAwake()
_GOVERNOR = ThermalGovernor()


def admission() -> dict:
    return _GOVERNOR.admission()


def ensure_monitor() -> None:
    _GOVERNOR.ensure_monitor()


def touch_keep_awake(seconds: int = 7200) -> None:
    KEEP_AWAKE.touch(seconds)


def shutdown() -> None:
    _GOVERNOR.shutdown()
    KEEP_AWAKE.stop(reason="shutdown")


def session_status() -> dict:
    now = time.time()
    keep = KEEP_AWAKE.status()
    started = _GOVERNOR.session_started
    return {
        "started_at": int(started),
        "uptime_seconds": max(0, int(now - started)),
        "keep_awake_seconds": (
            max(0, int(now - keep["started_at"]))
            if keep["active"] and keep["started_at"] else 0
        ),
        "max_hours": _GOVERNOR.max_hours,
    }


def status_report() -> dict:
    hardware = hardware_report()
    thermal = _GOVERNOR.status()
    return {
        **hardware,
        "thermal": thermal,
        "keep_awake": KEEP_AWAKE.status(),
        "session": session_status(),
        "recommendation": recommend_model(hardware["memory"], hardware["gpus"]),
        "backends": probe_backends(),
        "limits": thermal_limits(),
        "privacy": (
            "All device probes run locally. No telemetry, model prompts or "
            "hardware data leave this machine."
        ),
    }


class KeepAwakeRequest(BaseModel):
    enabled: bool
    ttl_minutes: int | None = Field(default=480, ge=1, le=1440)


@router.get("")
def device_status(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return status_report()


@router.get("/thermal")
def thermal_status(authorization: str | None = Header(default=None)):
    authorize(authorization)
    return _GOVERNOR.status()


@router.post("/keep-awake")
def set_keep_awake(body: KeepAwakeRequest,
                   authorization: str | None = Header(default=None)):
    authorize(authorization)
    if body.enabled:
        KEEP_AWAKE.start("dashboard", ttl_seconds=(body.ttl_minutes or 480) * 60)
    else:
        KEEP_AWAKE.stop(reason="dashboard")
    return status_report()
