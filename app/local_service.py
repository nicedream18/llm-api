"""Manage only a single process started here and verified by identity and nonce."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import psutil

from app.local_config import atomic_write, file_lock, read_bytes, safe_path, sha

ROOT = Path(__file__).resolve().parents[1]


class ManagedService:
    def __init__(self, state_dir=None):
        self.directory = safe_path(state_dir or Path.home() / ".waliapi")
        self.path = self.directory / "service.json"

    def _verified(self):
        state = json.loads(read_bytes(self.path) or b"{}")
        if not state: return None
        try:
            process = psutil.Process(state["pid"])
            if not process.is_running(): return None
            if abs(process.create_time() - state["created_at"]) > .001: raise ValueError("Process identity changed")
            if process.cmdline() != state["command"] or Path(process.exe()).resolve() != Path(sys.executable).resolve() or Path(process.cwd()).resolve() != ROOT:
                raise ValueError("Process command identity mismatch")
            if sha(process.environ().get("WALIAPI_MANAGED_NONCE", "").encode()) != state["nonce_hash"]:
                raise ValueError("Process ownership marker mismatch")
            return process
        except psutil.NoSuchProcess:
            return None
        except psutil.AccessDenied:
            raise ValueError("Process identity cannot be verified") from None

    def status(self):
        process = self._verified()
        return {"process_running": process is not None, "pid": process.pid if process else None}

    def start(self, port=9900):
        if not 1024 <= port <= 65535: raise ValueError("Port must be between 1024 and 65535")
        with file_lock(self.directory / "service.lock"):
            if self._verified(): raise ValueError("Managed process is already running")
            nonce = secrets.token_urlsafe(32)
            command = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)]
            log_path = safe_path(self.directory / "service.log")
            fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            with os.fdopen(fd, "ab") as stream:
                process = psutil.Popen(command, cwd=ROOT, env={**os.environ, "WALIAPI_MANAGED_NONCE": nonce},
                                       stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                       start_new_session=os.name != "nt")
            try:
                atomic_write(self.path, json.dumps({"pid": process.pid, "created_at": process.create_time(), "command": command, "nonce_hash": sha(nonce.encode()), "port": port}).encode())
            except Exception:
                process.terminate()
                process.wait(timeout=5)
                raise
            return {"started": True, "pid": process.pid, "port": port, "status": "starting; inspect diagnostics for readiness"}

    def stop(self):
        with file_lock(self.directory / "service.lock"):
            process = self._verified()
            if process:
                process.terminate()
                try: process.wait(timeout=5)
                except psutil.TimeoutExpired:
                    if self._verified(): process.kill(); process.wait(timeout=5)
            if self.path.exists(): self.path.unlink()
            return {"stopped": True}
