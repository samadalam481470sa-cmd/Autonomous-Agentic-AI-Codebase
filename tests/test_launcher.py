"""The local launcher keeps `./run.sh` usable when its default port is busy."""

import aetherion


def test_default_port_is_optional_so_the_launcher_can_fall_back():
    assert aetherion.parse_args([]).port is None
    assert aetherion.parse_args(["--port", "8123"]).port == 8123


def test_next_free_port_skips_busy_ports(monkeypatch):
    monkeypatch.setattr(
        aetherion, "_busy", lambda host, port: port in {8001, 8002}
    )

    assert aetherion._next_free_port("127.0.0.1", 8001) == 8003


def test_next_free_port_reports_when_the_scan_is_exhausted(monkeypatch):
    monkeypatch.setattr(aetherion, "_busy", lambda host, port: True)

    assert aetherion._next_free_port("127.0.0.1", 8001, attempts=2) is None
