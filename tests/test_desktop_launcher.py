import plistlib

import pytest

from scripts import build_desktop_launcher


def test_launcher_keeps_native_architecture_and_existing_builds(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(build_desktop_launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(build_desktop_launcher.platform, 'machine', lambda: 'arm64')
    for name in ['.venv/bin/python', 'app/static/desktop/index.html', 'desktop/assets/icon.icns']:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    previous = tmp_path / 'dist/previous.app'
    previous.mkdir(parents=True)
    build_desktop_launcher.main()
    output = capsys.readouterr().out.strip()
    assert 'WaLiAPI-Python-' in output
    bundle = next((tmp_path / 'dist').glob('WaLiAPI-Python-*.app'))
    script = bundle / 'Contents/MacOS/waliapi-python'
    assert 'exec /usr/bin/arch -arm64 .venv/bin/python -m app.desktop' in script.read_text()
    assert script.stat().st_mode & 0o111
    with (bundle / 'Contents/Info.plist').open('rb') as handle:
        info = plistlib.load(handle)
        assert info['LSArchitecturePriority'] == ['arm64']
        assert info['CFBundleIconFile'] == 'icon.icns'
    assert (bundle / 'Contents/Resources/icon.icns').is_file()
    assert previous.exists()


def test_launcher_rejects_missing_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(build_desktop_launcher, 'ROOT', tmp_path)
    with pytest.raises(SystemExit, match='先安装桌面依赖'):
        build_desktop_launcher.main()
