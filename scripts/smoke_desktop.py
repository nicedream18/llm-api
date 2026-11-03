"""Exercise the actual macOS WKWebView window against the local Python backend."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime

import webview

from app.config import config
from app.desktop import ROOT, BackendProcess, NativeBridge


class SmokeBridge(NativeBridge):
    def smoke_credentials(self):
        self._check_origin()
        return {'username': config.auth.admin_username, 'password': config.auth.bootstrap_password, 'token': config.auth.admin_token}


def main():
    parser = argparse.ArgumentParser(description='Verify the native desktop without interrupting an existing window')
    parser.add_argument('--port', type=int, default=9911)
    args = parser.parse_args()
    backend = BackendProcess(args.port)
    backend.start()
    origin = 'http://localhost:' + str(args.port)
    bridge = SmokeBridge(origin)
    window = webview.create_window('WaLiAPI Desktop · Python · Smoke', origin + '/desktop/', js_api=bridge, width=1440, height=900, min_size=(1000, 680))
    if window is None:
        raise RuntimeError('Native window was not created')
    bridge._window = window
    output = ROOT / 'logs' / ('desktop-smoke-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True, exist_ok=True)
    result = {'renderer': 'WKWebView', 'pages': [], 'screenshots': []}

    def wait_for(expression, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if window.evaluate_js(expression):
                return
            time.sleep(0.2)
        raise RuntimeError('Desktop page condition timed out: ' + expression)

    def screenshot(name):
        import Quartz
        window.restore()
        window.show()
        wait_for("document.visibilityState === 'visible'")
        window.evaluate_js("window.__smoke_painted = false; requestAnimationFrame(() => requestAnimationFrame(() => { window.__smoke_painted = true; }));")
        wait_for('window.__smoke_painted')
        time.sleep(0.5)
        for info in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID):
            if info.get('kCGWindowOwnerPID') == os.getpid() and info.get('kCGWindowLayer') == 0 and str(info.get('kCGWindowName', '')).startswith('WaLiAPI Desktop'):
                path = output / (name + '.png')
                subprocess.run(['/usr/sbin/screencapture', '-x', '-l', str(info['kCGWindowNumber']), str(path)], check=True, capture_output=True)
                result['screenshots'].append(str(path))
                return
        raise RuntimeError('Native test window was not found')

    def check():
        try:
            window.events.loaded.wait(20)
            wait_for("Boolean(document.querySelector('input[type=password]'))")
            screenshot('login')
            wait_for('Boolean(window.pywebview?.api?.smoke_credentials)')
            # Credentials stay inside this process and the test-only native bridge.
            window.evaluate_js("""(async () => {
              const value = await window.pywebview.api.smoke_credentials();
              const response = await fetch('/api/v1/auth/login', { method: 'POST', credentials: 'include', headers: { 'content-type': 'application/json' }, body: JSON.stringify({username:value.username,password:value.password}) });
              if (response.ok) window.__smoke_auth = 'cookie';
              else if (value.token) { sessionStorage.setItem('waliapi.desktop.admin-token', value.token); window.__smoke_auth = 'token'; }
              else window.__smoke_auth = 'failed';
            })()""")
            wait_for('Boolean(window.__smoke_auth)')
            result['authentication'] = window.evaluate_js('window.__smoke_auth')
            if result['authentication'] == 'failed':
                raise RuntimeError('No usable local administrator credentials')
            window.evaluate_js('location.reload()')
            wait_for("document.body.innerText.includes('欢迎使用 WaLiAPI')")
            wait_for("!document.body.innerText.includes('加载中...')")
            screenshot('dashboard')
            window.evaluate_js("""window.__smoke_http_failures = [];
              const originalFetch = window.fetch.bind(window);
              window.fetch = async (...args) => {
                const response = await originalFetch(...args);
                if (!response.ok) window.__smoke_http_failures.push({path: String(args[0]), status: response.status});
                return response;
              };""")
            for route, title in [('/channels','渠道'), ('/channels/auth','Codex'), ('/api-keys','密钥'), ('/logs','日志'), ('/settings','安全'), ('/services/knowledge-base','知识库'), ('/services/wiki','新建 Wiki 项目'), ('/services/mcp','MCP')]:
                window.evaluate_js('location.hash = ' + json.dumps('#' + route))
                wait_for("!document.body.innerText.includes('加载中...') && document.body.innerText.includes(" + json.dumps(title) + ')')
                time.sleep(0.5)
                text = window.evaluate_js('document.body.innerText')
                if '出了点问题' in text or '数据加载失败' in text or '设置加载失败' in text:
                    raise RuntimeError('Desktop page failed: ' + route)
                result['pages'].append(route)
                if route == '/services/wiki':
                    screenshot('wiki')
            result['http_failures'] = window.evaluate_js('window.__smoke_http_failures')
            if result['http_failures']:
                raise RuntimeError('A desktop page API request failed')
            result['native_file_bridge'] = window.evaluate_js("Boolean(window.pywebview?.api?.read_file)")
            result['status'] = 'passed'
        except Exception as exc:  # noqa: BLE001 - capture evidence and close the native window on any test failure
            result['status'] = 'failed'
            result['error'] = str(exc)
        finally:
            print(json.dumps(result, ensure_ascii=False), flush=True)
            window.destroy()

    try:
        webview.start(check, private_mode=True)
    finally:
        backend.close()
    if result.get('status') != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
