"""Process lifecycle tests never start the real application or stop unrelated PIDs."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from app import local_service
from app.local_config import atomic_write, sha
from app.local_service import ManagedService


def test_managed_helper_process_identity_and_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(local_service, "ROOT", tmp_path)
    command = [sys.executable, "-c", "import time; time.sleep(30)"]
    process = psutil.Popen(command, cwd=tmp_path, env={**os.environ, "WALIAPI_MANAGED_NONCE": "test-nonce"},
                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    service = ManagedService(tmp_path / "state")
    state = {"pid": process.pid, "created_at": process.create_time(), "command": command, "nonce_hash": sha(b"test-nonce")}
    try:
        atomic_write(service.path, json.dumps(state).encode())
        assert service.status() == {"process_running": True, "pid": process.pid}
        atomic_write(service.path, json.dumps({**state, "nonce_hash": "wrong"}).encode())
        with pytest.raises(ValueError, match="ownership"): service.stop()
        assert process.is_running()
        atomic_write(service.path, json.dumps({**state, "created_at": state["created_at"] - 10}).encode())
        with pytest.raises(ValueError, match="identity"): service.stop()
        assert process.is_running()
        atomic_write(service.path, json.dumps(state).encode())
        assert service.stop()["stopped"]
        process.wait(timeout=5)
        assert not service.status()["process_running"]
        assert service.stop()["stopped"]
    finally:
        if process.is_running(): process.kill(); process.wait(timeout=5)


def test_process_start_is_fixed_loopback_detached_and_secret_free(tmp_path, monkeypatch):
    calls = []
    process = SimpleNamespace(pid=123, create_time=lambda: 123.25, terminate=lambda: calls.append("terminate"), wait=lambda **kwargs: None)
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return process
    monkeypatch.setattr(local_service.psutil, "Popen", spawn)
    service = ManagedService(tmp_path)
    monkeypatch.setattr(service, "_verified", lambda: None)
    result = service.start(9911)
    assert result["pid"] == 123
    command, options = calls[0]
    assert command[-3:] == ["127.0.0.1", "--port", "9911"]
    assert "WALIAPI_MANAGED_NONCE" in options["env"]
    assert options["env"]["WALIAPI_MANAGED_NONCE"] not in service.path.read_text()
    assert options["cwd"] == local_service.ROOT and options["stdin"] == subprocess.DEVNULL
    if os.name == "nt": assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
    monkeypatch.setattr(service, "_verified", lambda: process)
    with pytest.raises(ValueError, match="already running"): service.start()
    with pytest.raises(ValueError, match="Port"): service.start(1)


def test_failed_state_write_terminates_only_new_child(tmp_path, monkeypatch):
    calls = []
    process = SimpleNamespace(pid=123, create_time=lambda: 123.25, terminate=lambda: calls.append("terminate"), wait=lambda **kwargs: calls.append("wait"))
    monkeypatch.setattr(local_service.psutil, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(local_service, "atomic_write", lambda *args: (_ for _ in ()).throw(OSError("disk error")))
    service = ManagedService(tmp_path); monkeypatch.setattr(service, "_verified", lambda: None)
    with pytest.raises(OSError): service.start()
    assert calls == ["terminate", "wait"]


def test_stale_pid_denied_access_and_wrong_command_are_never_killed(tmp_path, monkeypatch):
    service = ManagedService(tmp_path)
    atomic_write(service.path, json.dumps({"pid": 999, "created_at": 1, "command": ["wrong"], "nonce_hash": "hash"}).encode())
    monkeypatch.setattr(local_service.psutil, "Process", lambda _: (_ for _ in ()).throw(psutil.NoSuchProcess(999)))
    assert not service.status()["process_running"]
    monkeypatch.setattr(local_service.psutil, "Process", lambda _: (_ for _ in ()).throw(psutil.AccessDenied(999)))
    with pytest.raises(ValueError, match="cannot be verified"): service.stop()
    process = SimpleNamespace(is_running=lambda: True, create_time=lambda: 1, cmdline=lambda: ["foreign"])
    monkeypatch.setattr(local_service.psutil, "Process", lambda _: process)
    with pytest.raises(ValueError, match="command"): service.stop()


def test_symlink_and_junction_guard_without_os_privileges(tmp_path, monkeypatch):
    from app.local_config import safe_path
    monkeypatch.setattr(Path, "is_junction", lambda _: True)
    with pytest.raises(ValueError, match="junctions"): safe_path(tmp_path)
