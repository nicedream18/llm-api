import base64
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import desktop


def test_backend_reuses_service_without_starting_or_stopping_it(monkeypatch):
    monkeypatch.setattr(desktop, 'probe_backend', lambda port: port == 9910)
    spawn = Mock()
    monkeypatch.setattr(desktop.subprocess, 'Popen', spawn)
    backend = desktop.BackendProcess(9910)
    backend.start()
    backend.close()
    spawn.assert_not_called()
    assert backend.process is None


def test_backend_start_and_close_only_own_process(monkeypatch, tmp_path):
    probes = iter([False, True])
    monkeypatch.setattr(desktop, 'probe_backend', lambda _: next(probes))
    monkeypatch.setattr(desktop, 'ROOT', tmp_path)
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    monkeypatch.setattr(desktop.subprocess, 'Popen', spawn)
    backend = desktop.BackendProcess(9910)
    backend.start()
    assert spawn.call_args.kwargs['env']['SERVER_PORT'] == '9910'
    assert 'http://localhost:9910' in spawn.call_args.kwargs['env']['CORS_ALLOWED_ORIGINS']
    backend.close()
    process.terminate.assert_called_once()
    assert backend.log.closed


def test_backend_timeout_and_failed_launch_are_cleaned_up(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, 'probe_backend', lambda _: False)
    monkeypatch.setattr(desktop, 'ROOT', tmp_path)
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(desktop.subprocess, 'Popen', Mock(return_value=process))
    backend = desktop.BackendProcess(9910)
    try:
        with pytest.raises(RuntimeError, match='超时'):
            backend.start(timeout=0)
    finally:
        backend.close()
    process.terminate.assert_called_once()


@pytest.mark.parametrize('port', [0, -1, 65536])
def test_backend_rejects_invalid_port(port):
    with pytest.raises(ValueError):
        desktop.BackendProcess(port)


def bridge_at(url):
    bridge = desktop.NativeBridge('http://localhost:9910')
    bridge._window = SimpleNamespace(get_current_url=lambda: url)
    return bridge


@pytest.mark.parametrize('url', ['https://evil.test/desktop/', 'http://localhost:9910/other', 'http://localhost:99100/desktop/'])
def test_bridge_rejects_foreign_origin_and_path(url):
    with pytest.raises(PermissionError):
        bridge_at(url).read_file('/tmp/never-selected')


def test_bridge_only_reads_explicitly_selected_files(tmp_path):
    selected = tmp_path / 'example.txt'
    selected.write_text('桌面文件')
    bridge = bridge_at('http://localhost:9910/desktop/#/channels')
    with pytest.raises(PermissionError):
        bridge.read_file(str(selected))
    bridge._selected.add(selected.resolve())
    result = bridge.read_file(str(selected))
    assert result['name'] == 'example.txt'
    assert base64.b64decode(result['base64']).decode() == '桌面文件'


def test_bridge_rejects_oversized_files(monkeypatch, tmp_path):
    selected = tmp_path / 'large.txt'
    selected.write_text('12345')
    monkeypatch.setattr(desktop, 'MAX_FILE_BYTES', 4)
    bridge = bridge_at('http://localhost:9910/desktop/')
    bridge._selected.add(selected.resolve())
    with pytest.raises(ValueError, match='32 MB'):
        bridge.read_file(str(selected))


def test_external_links_allow_only_http(monkeypatch):
    open_url = Mock()
    monkeypatch.setattr(desktop.webbrowser, 'open', open_url)
    bridge = bridge_at('http://localhost:9910/desktop/')
    with pytest.raises(ValueError):
        bridge.open_external('file:///etc/passwd')
    bridge.open_external('https://example.test')
    open_url.assert_called_once_with('https://example.test')
