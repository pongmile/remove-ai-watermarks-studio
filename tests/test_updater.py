"""Tests for GitHub update checks, flaky-network retry logic, and model download retries."""

from __future__ import annotations

import subprocess
import threading
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from webapp import model_status, server

HEADERS = {"X-RAIW-Request": "1"}


def _proc(rc: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["git"], rc, stdout=stdout, stderr=stderr)


def test_git_retry_recovers_after_transient_network_errors(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []
    sleeps: list[float] = []

    def fake_run_git(*args: str, timeout: float = 5.0):
        calls.append(args)
        if len(calls) == 1:
            return None  # simulated timeout
        if len(calls) == 2:
            return _proc(128, stderr="fatal: unable to access repo: Could not resolve host: github.com")
        return _proc(0, stdout="ok")

    monkeypatch.setattr(server, "_run_git", fake_run_git)
    monkeypatch.setattr(server.time, "sleep", sleeps.append)

    proc, attempts = server._run_git_with_retry("fetch", "--tags", "origin", retries=3, base_delay=1.5)
    assert proc is not None
    assert proc.returncode == 0
    assert attempts == 3
    assert sleeps == [1.5, 3.0]


def test_git_retry_does_not_retry_auth_or_not_found(monkeypatch) -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_run_git(*args: str, timeout: float = 5.0):
        calls.append(1)
        return _proc(128, stderr="remote: Repository not found.")

    monkeypatch.setattr(server, "_run_git", fake_run_git)
    monkeypatch.setattr(server.time, "sleep", sleeps.append)

    proc, attempts = server._run_git_with_retry("fetch", "--tags", "origin", retries=3, base_delay=1.5)
    assert proc is not None
    assert proc.returncode == 128
    assert attempts == 1
    assert sleeps == []


def test_update_check_reports_offline_and_attempts_on_total_failure(monkeypatch) -> None:
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)

    base_status = {
        "git_available": True,
        "current_version": "0.66.0",
        "branch": "main",
        "commit": "8f25dfe",
        "commit_date": "2026-11-23T00:00:00+07:00",
        "dirty": False,
        "remotes": {
            "origin": "https://github.com/pongmile/remove-ai-watermarks-studio.git",
            "upstream": None,
        },
        "checked_at": None,
        "behind_origin": 0,
        "behind_upstream": None,
        "latest_upstream_tag": "v0.66.0",
        "recent_commits": ["8f25dfe feat: fork"],
        "offline": False,
        "attempts": None,
        "error": None,
    }

    def fake_collect(*, checked_at=None, error=None, attempts=None):
        snap = dict(base_status)
        snap["checked_at"] = checked_at
        snap["error"] = error
        snap["offline"] = server._is_offline_git_error(error)
        snap["attempts"] = attempts
        return snap

    monkeypatch.setattr(server, "_collect_update_status", fake_collect)
    monkeypatch.setattr(
        server,
        "_run_git",
        lambda *args, timeout=5.0: _proc(
            128,
            stderr="fatal: unable to access origin: Could not resolve host: github.com",
        ),
    )

    client = TestClient(server.app)
    resp = client.post("/update/check", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["offline"] is True
    assert data["attempts"] == 3
    assert "Could not resolve host" in (data["error"] or "")


def test_update_apply_rejects_dirty_worktree(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_collect_update_status",
        lambda **kw: {
            "git_available": True,
            "current_version": "0.66.0",
            "branch": "main",
            "commit": "8f25dfe",
            "commit_date": None,
            "dirty": True,
            "remotes": {"origin": "https://github.com/pongmile/remove-ai-watermarks-studio.git", "upstream": None},
            "checked_at": None,
            "behind_origin": 1,
            "behind_upstream": 0,
            "latest_upstream_tag": "v0.66.0",
            "recent_commits": [],
            "offline": False,
            "attempts": None,
            "error": None,
        },
    )

    client = TestClient(server.app)
    resp = client.post("/update/apply", data={"source": "origin"}, headers=HEADERS)
    assert resp.status_code == 409
    assert "uncommitted changes" in resp.text.lower()


def test_update_apply_ff_only_and_protects_torch(monkeypatch) -> None:
    monkeypatch.setattr(server.time, "sleep", lambda _s: None)
    state = {"head": "aaaa111", "fetched": False}

    def fake_collect(*, checked_at=None, error=None, attempts=None):
        return {
            "git_available": True,
            "current_version": "0.66.0",
            "branch": "main",
            "commit": state["head"],
            "commit_date": None,
            "dirty": False,
            "remotes": {"origin": "https://github.com/pongmile/remove-ai-watermarks-studio.git", "upstream": None},
            "checked_at": checked_at,
            "behind_origin": 0 if state["head"] == "bbbb222" else 1,
            "behind_upstream": None,
            "latest_upstream_tag": "v0.66.0",
            "recent_commits": [],
            "offline": False,
            "attempts": attempts,
            "error": error,
        }

    def fake_run_git(*args: str, timeout: float = 5.0):
        if "fetch" in args:
            state["fetched"] = True
            return _proc(0)
        if args[:2] == ("rev-parse", "--verify"):
            return _proc(0, stdout="bbbb222")
        if args[:2] == ("merge", "--ff-only"):
            state["head"] = "bbbb222"
            return _proc(0, stdout="Fast-forward")
        if args[:2] == ("rev-parse", "--short"):
            return _proc(0, stdout=state["head"])
        if args[:2] == ("diff", "--name-only"):
            return _proc(0, stdout="webapp/server.py\n")
        return _proc(0)

    reinstall_calls: list[bool] = []

    def fake_reinstall(*, sync_pyproject: bool = False):
        reinstall_calls.append(sync_pyproject)
        return True, "", True

    monkeypatch.setattr(server, "_collect_update_status", fake_collect)
    monkeypatch.setattr(server, "_run_git", fake_run_git)
    monkeypatch.setattr(server, "_reinstall_editable_no_deps", fake_reinstall)

    client = TestClient(server.app)
    resp = client.post("/update/apply", data={"source": "origin"}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["updated"] is True
    assert data["old_commit"] == "aaaa111"
    assert data["new_commit"] == "bbbb222"
    assert data["restart_required"] is True
    assert data["torch_protected"] is True
    assert reinstall_calls == [False]


def test_model_download_retry_recovers_on_transient_failure() -> None:
    calls = {"n": 0}
    stop = threading.Event()
    spec = SimpleNamespace(repo_id="org/repo", revision=None, store="hf")

    def flaky_download(repo_id: str, name: str, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionResetError("connection reset by peer")
        return "/tmp/ok"

    with mock.patch.object(stop, "wait", return_value=False) as wait_mock:
        model_status._download_file_with_retry(flaky_download, spec, "weights.onnx", stop, retries=3, base_delay=0.01)

    assert calls["n"] == 3
    assert wait_mock.call_count == 2
