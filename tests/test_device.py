"""Local device runtime: hardware probe, thermal governor, keep-awake and API."""

import pytest
from fastapi.testclient import TestClient

from services.api import device, security
from services.api.main import app

TOKEN = "device-test-token-1234567890"


def test_meminfo_and_nvidia_parsing():
    parsed = device._parse_meminfo(
        "MemTotal:       32768000 kB\n"
        "MemAvailable:   16384000 kB\n"
    )
    assert parsed["total_bytes"] == 32768000 * 1024
    assert parsed["available_bytes"] == 16384000 * 1024

    gpus = device._parse_nvidia_csv(
        "NVIDIA GeForce RTX 4090, 24564, 1200, 55, 12, 555.42\n"
    )
    assert gpus[0]["vendor"] == "nvidia"
    assert gpus[0]["vram_mb"] == 24564
    assert gpus[0]["temp_c"] == 55
    assert gpus[0]["used_mb"] == 1200


def test_model_recommendation_tiers():
    small = device.recommend_model({"total_mb": 8192}, [])
    assert small["name"].endswith("3b")
    assert small["gpu_layers"] == 0

    big = device.recommend_model(
        {"total_mb": 65536}, [{"vram_mb": 24564, "unified_memory": False}]
    )
    assert big["name"].endswith("32b")
    assert big["gpu_layers"] == 99

    unified = device.recommend_model(
        {"total_mb": 32768}, [{"vram_mb": None, "unified_memory": True}]
    )
    assert unified["name"].endswith("14b")


def make_governor(tmp_path, first_temp, predict_minutes=0.0):
    class Reader:
        value = first_temp

        def __call__(self):
            return [{"label": "cpu", "celsius": self.value}]

    reader = Reader()
    clock = {"now": 1000.0}
    governor = device.ThermalGovernor(
        reader=reader,
        clock=lambda: clock["now"],
        thresholds={
            "warn": 78,
            "hot": 86,
            "critical": 92,
            "resume": 70,
            "cooldown": 30,
            "sample_seconds": 1,
            "predict_minutes": predict_minutes,
            "min_battery_percent": 0,
        },
        db_path=tmp_path / "device.sqlite3",
    )
    return governor, reader, clock


def test_governor_pauses_when_hot_then_cools_down(tmp_path):
    governor, reader, clock = make_governor(tmp_path, 60)
    status = governor.status()
    assert status["state"] == "normal"
    assert status["admission"]["allowed"] is True

    reader.value = 89
    clock["now"] += 10
    assert governor.status()["state"] == "hot"
    denied = governor.admission()
    assert denied["allowed"] is False
    assert denied["retry_after"] > 0

    reader.value = 68
    clock["now"] += 5
    assert governor.status()["state"] == "cooldown"

    clock["now"] += 40
    assert governor.status()["state"] == "normal"
    assert governor.admission()["allowed"] is True


def test_predictive_guard_trips_before_critical(tmp_path):
    governor, reader, clock = make_governor(tmp_path, 80, predict_minutes=1.5)
    for temperature in (80, 83, 86):
        reader.value = temperature
        governor.sample_once(force=True)
        clock["now"] += 15
    status = governor.status()
    assert status["state"] in ("hot", "critical")
    assert status["admission"]["allowed"] is False


def test_governor_without_sensors_is_monitor_only(tmp_path):
    governor = device.ThermalGovernor(
        reader=lambda: [], clock=lambda: 2000.0,
        thresholds={"min_battery_percent": 0}, db_path=tmp_path / "device.sqlite3",
    )
    status = governor.status()
    assert status["state"] == "unknown"
    assert status["sensors_available"] is False
    assert status["admission"]["mode"] == "monitor"
    assert status["admission"]["allowed"] is True


def test_keep_awake_expires_and_releases_backend():
    stopped = []
    clock = {"now": 5000.0}
    keeper = device.KeepAwake(
        system="Linux",
        clock=lambda: clock["now"],
        starter=lambda: {
            "backend": "fake",
            "pid": 42,
            "note": "test backend",
            "stop": lambda: stopped.append(1),
        },
    )
    started = keeper.start("test", ttl_seconds=60)
    assert started["active"] is True
    assert started["backend"] == "fake"
    assert started["ttl_remaining_seconds"] == 60

    clock["now"] += 61
    expired = keeper.status()
    assert expired["active"] is False
    assert stopped == [1]


@pytest.fixture
def device_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_ADMIN_TOKEN", TOKEN)
    monkeypatch.setenv("SECURITY_DB_PATH", str(tmp_path / "security.sqlite3"))
    monkeypatch.setenv("DEVICE_DB_PATH", str(tmp_path / "device.sqlite3"))
    monkeypatch.delenv("AGENT_TOTP_SECRET", raising=False)
    security.reset()
    monkeypatch.setattr(device._GOVERNOR, "_reader",
                        lambda: [{"label": "cpu", "celsius": 55.0}])
    monkeypatch.setattr(device._GOVERNOR, "_db", tmp_path / "device.sqlite3")
    monkeypatch.setattr(device._GOVERNOR, "_last_sample", 0.0)
    return TestClient(app)


def test_device_api_requires_token_and_controls_keep_awake(device_client, monkeypatch):
    stopped = []
    monkeypatch.setattr(device.KEEP_AWAKE, "_starter", lambda: {
        "backend": "fake",
        "pid": 7,
        "note": "test backend",
        "stop": lambda: stopped.append(1),
    })
    device.KEEP_AWAKE.stop(reason="test reset")
    headers = {"Authorization": "Bearer " + TOKEN}

    assert device_client.get("/api/device").status_code == 403

    status = device_client.get("/api/device", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["platform"]["python"]
    assert body["recommendation"]["name"]
    assert body["thermal"]["sensors_available"] is True
    assert body["privacy"].startswith("All device probes run locally")

    enabled = device_client.post(
        "/api/device/keep-awake",
        json={"enabled": True, "ttl_minutes": 30},
        headers=headers,
    )
    assert enabled.status_code == 200
    assert enabled.json()["keep_awake"]["active"] is True

    disabled = device_client.post(
        "/api/device/keep-awake", json={"enabled": False}, headers=headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["keep_awake"]["active"] is False
    assert stopped == [1]

    thermal = device_client.get("/api/device/thermal", headers=headers)
    assert thermal.status_code == 200
    assert thermal.json()["state"] in {"normal", "warm"}
