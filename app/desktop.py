"""Native desktop host for the transplanted WaLiAPI UI (no Rust gateway)."""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, TextIO
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from webview.window import Window

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 32 * 1024 * 1024


def probe_backend(port: int) -> bool:
    try:
        response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1, trust_env=False)
        response.raise_for_status()
        if response.json().get("service") != "WaLiAPI-Python":
            raise RuntimeError(f"端口 {port} 被其他服务占用，请修改 SERVER_PORT。")
        return True
    except httpx.RequestError:
        return False


class BackendProcess:
    """Reuse an existing backend; terminate only the process we started."""

    def __init__(self, port: int):
        if not 1 <= port <= 65535:
            raise ValueError("Invalid backend port")
        self.port = port
        self.process: subprocess.Popen | None = None
        self.log: TextIO | None = None

    def start(self, timeout: float = 60) -> None:
        if probe_backend(self.port):
            return
        log_dir = ROOT / "logs"
        log_dir.mkdir(exist_ok=True)
        self.log = (log_dir / "desktop-backend.log").open("a", encoding="utf-8")
        env = dict(os.environ)
        env['SERVER_PORT'] = str(self.port)
        origin = f"http://localhost:{self.port}"
        origins = env.get("CORS_ALLOWED_ORIGINS", "http://localhost:9900").split(",")
        env["CORS_ALLOWED_ORIGINS"] = ",".join(dict.fromkeys([*origins, origin]))
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=ROOT, env=env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Python 后端启动失败，请查看 logs/desktop-backend.log（需要现有 MySQL 配置）。")
            if probe_backend(self.port):
                return
            time.sleep(0.2)
        raise RuntimeError("后端启动超时，请查看 logs/desktop-backend.log。")

    def close(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        if self.log is not None:
            self.log.close()


class NativeBridge:
    """Expose user-confirmed file dialogs, not unrestricted filesystem access."""

    def __init__(self, origin: str):
        self._origin = origin
        self._window: Window | None = None
        self._selected: set[Path] = set()

    def _check_origin(self) -> Window:
        if self._window is None:
            raise PermissionError("Native desktop window is not ready")
        current = urlsplit(self._window.get_current_url() or "")
        if f"{current.scheme}://{current.netloc}" != self._origin or not current.path.startswith("/desktop/"):
            raise PermissionError("Native bridge is restricted to the desktop UI")
        return self._window

    def select_files(self, directory: bool = False, multiple: bool = False):
        window = self._check_origin()
        import webview
        paths = window.create_file_dialog(webview.FileDialog.FOLDER if directory else webview.FileDialog.OPEN, allow_multiple=multiple)
        if not paths:
            return None
        resolved = [Path(path).resolve() for path in paths]
        self._selected.update(resolved)
        return [str(path) for path in resolved] if multiple else str(resolved[0])

    def read_file(self, path: str):
        self._check_origin()
        selected = Path(path).resolve()
        if selected not in self._selected or not selected.is_file():
            raise PermissionError("请先通过系统文件选择器选择文件")
        if selected.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("文件不能超过 32 MB")
        content = selected.read_bytes()
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("文件不能超过 32 MB")
        return {"name": selected.name, "base64": base64.b64encode(content).decode("ascii")}

    def save_file(self, content: str, default_name: str = "export.json") -> bool:
        window = self._check_origin()
        import webview
        if len(content.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("导出内容不能超过 32 MB")
        target = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=Path(default_name).name)
        if not target:
            return False
        path = target if isinstance(target, str) else target[0]
        Path(path).write_text(content, encoding="utf-8")
        return True

    def open_external(self, url: str) -> None:
        self._check_origin()
        if urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("Only HTTP(S) links are supported")
        webbrowser.open(url)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="WaLiAPI Python 桌面版")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument('--port', type=int, default=int(os.environ.get('DESKTOP_PORT', '9910')))
    parser.add_argument("--check", action="store_true", help="检查桌面资源和后端，不创建窗口")
    args = parser.parse_args(argv)
    os.chdir(ROOT)
    if not (ROOT / "app/static/desktop/index.html").is_file():
        raise SystemExit("桌面资源未构建，请先执行 cd desktop && npm ci && npm run build")
    backend = BackendProcess(args.port)
    try:
        backend.start()
        origin = f"http://localhost:{args.port}"
        # Existing servers must actually serve this project's desktop resources.
        page = httpx.get(origin + "/desktop/", timeout=5, trust_env=False)
        if page.status_code != 200 or "WaLiAPI Desktop" not in page.text:
            raise RuntimeError("此端口未提供桌面资源，请检查是否启动了当前项目的后端。")
        if args.check:
            print(json.dumps({"desktop_assets": "ok", "backend": "ok", "port": args.port, "reused_backend": backend.process is None}))
            return
        import webview
        bridge = NativeBridge(origin)
        window = webview.create_window("WaLiAPI Desktop · Python", origin + "/desktop/", js_api=bridge,
                                       width=1440, height=900, min_size=(1000, 680), background_color="#f5f7fa")
        if window is None:
            raise RuntimeError("无法创建桌面窗口")
        bridge._window = window
        webview.start(debug=args.debug, private_mode=True)
    finally:
        backend.close()


if __name__ == "__main__":
    main()
