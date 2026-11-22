"""Tests for Studio app lifecycle: tab heartbeats, active-work warnings, safe Quit & Restart."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from webapp import model_status, server

HEADERS = {"X-RAIW-Request": "1"}


def _reset_lifecycle(monkeypatch) -> list[int]:
    exits: list[int] = []
    done = threading.Event()

    def fake_exit(code: int) -> None:
        exits.append(code)
        done.set()

    with server._lifecycle_lock:
        server._lifecycle_clients.clear()
        server._lifecycle_ever_connected = False
        server._lifecycle_zero_since = None
        server._lifecycle_shutting_down = False
    monkeypatch.setattr(server, "_exit_process", fake_exit)
    monkeypatch.setattr(server, "_release_gpu_and_cleanup", lambda: None)
    return exits


def test_ping_and_bye_track_active_tabs(monkeypatch) -> None:
    _reset_lifecycle(monkeypatch)
    client = TestClient(server.app)

    r1 = client.post("/lifecycle/ping", data={"client_id": "tab-a"}, headers=HEADERS)
    assert r1.status_code == 200
    assert r1.json()["active_tabs"] == 1

    r2 = client.post("/lifecycle/ping", data={"client_id": "tab-b"}, headers=HEADERS)
    assert r2.status_code == 200
    assert r2.json()["active_tabs"] == 2

    b1 = client.post("/lifecycle/bye", data={"client_id": "tab-a"}, headers=HEADERS)
    assert b1.status_code == 200
    assert b1.json()["active_tabs"] == 1

    b2 = client.post("/lifecycle/bye", data={"client_id": "tab-b"}, headers=HEADERS)
    assert b2.status_code == 200
    assert b2.json()["active_tabs"] == 0


def test_shutdown_blocks_with_409_when_busy_and_allows_force(monkeypatch) -> None:
    exits = _reset_lifecycle(monkeypatch)
    monkeypatch.setattr(
        server,
        "_active_work_summary",
        lambda: {
            "busy": True,
            "active_jobs": 2,
            "downloading": True,
            "updating": False,
            "reasons": ["2 active clean/video job(s)", "model download in progress (sdxl-zimage)"],
        },
    )
    monkeypatch.setattr(server, "_schedule_process_exit", lambda code, delay_sec=0.35: exits.append(code))

    client = TestClient(server.app)

    blocked = client.post("/lifecycle/shutdown", data={"force": "false"}, headers=HEADERS)
    assert blocked.status_code == 409
    body = blocked.json()
    assert body["busy"] is True
    assert body["active_jobs"] == 2
    assert body["downloading"] is True
    assert exits == []

    forced = client.post("/lifecycle/shutdown", data={"force": "true"}, headers=HEADERS)
    assert forced.status_code == 200
    fbody = forced.json()
    assert fbody["ok"] is True
    assert fbody["forced"] is True
    assert exits == [0]


def test_shutdown_idle_exits_cleanly_with_code_0(monkeypatch) -> None:
    exits = _reset_lifecycle(monkeypatch)
    monkeypatch.setattr(
        server,
        "_active_work_summary",
        lambda: {"busy": False, "active_jobs": 0, "downloading": False, "updating": False, "reasons": []},
    )
    monkeypatch.setattr(server, "_schedule_process_exit", lambda code, delay_sec=0.35: exits.append(code))

    client = TestClient(server.app)
    resp = client.post("/lifecycle/shutdown", data={"force": "false"}, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json()["shutting_down"] is True
    assert exits == [0]


def test_restart_uses_exit_code_75_and_guards_busy(monkeypatch) -> None:
    exits = _reset_lifecycle(monkeypatch)
    monkeypatch.setenv("RAIW_ALLOW_RESTART", "1")
    monkeypatch.setattr(server, "_schedule_process_exit", lambda code, delay_sec=0.35: exits.append(code))

    busy_flag = {"busy": True}
    monkeypatch.setattr(
        server,
        "_active_work_summary",
        lambda: {
            "busy": busy_flag["busy"],
            "active_jobs": 1 if busy_flag["busy"] else 0,
            "downloading": False,
            "updating": False,
            "reasons": ["1 active clean/video job(s)"] if busy_flag["busy"] else [],
        },
    )

    client = TestClient(server.app)
    r409 = client.post("/lifecycle/restart", data={"force": "false"}, headers=HEADERS)
    assert r409.status_code == 409
    assert exits == []

    busy_flag["busy"] = False
    ok = client.post("/lifecycle/restart", data={"force": "false"}, headers=HEADERS)
    assert ok.status_code == 200
    assert ok.json()["restarting"] is True
    assert exits == [75]


def test_lifecycle_config_toggle(monkeypatch) -> None:
    _reset_lifecycle(monkeypatch)
    saved: dict[str, object] = {}
    monkeypatch.setenv("RAIW_AUTO_SHUTDOWN", "1")
    monkeypatch.setattr(model_status, "load_settings", lambda: dict(saved))
    monkeypatch.setattr(model_status, "save_settings", lambda d: (saved.update(d) or dict(saved)))

    client = TestClient(server.app)
    r_off = client.post("/lifecycle/config", data={"auto_shutdown_on_close": "false"}, headers=HEADERS)
    assert r_off.status_code == 200
    assert r_off.json()["auto_shutdown_enabled"] is False

    r_on = client.post("/lifecycle/config", data={"auto_shutdown_on_close": "true"}, headers=HEADERS)
    assert r_on.status_code == 200
    assert r_on.json()["auto_shutdown_enabled"] is True
