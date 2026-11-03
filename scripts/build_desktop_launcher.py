"""Build a timestamped, local macOS app launcher for this Python checkout."""
from __future__ import annotations

import platform
import plistlib
import shlex
import shutil
from datetime import datetime

from app.desktop import ROOT


def main():
    if not (ROOT / '.venv/bin/python').is_file() or not (ROOT / 'app/static/desktop/index.html').is_file():
        raise SystemExit('请先安装桌面依赖并构建 desktop 前端。')
    name = 'WaLiAPI-Python-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.app'
    target = ROOT / 'dist' / name
    executable = target / 'Contents/MacOS/waliapi-python'
    resources = target / 'Contents/Resources'
    executable.parent.mkdir(parents=True, exist_ok=False)
    resources.mkdir()
    architecture = platform.machine()
    executable.write_text('#!/bin/zsh\nset -eu\ncd -- ' + shlex.quote(str(ROOT)) + '\nexport PATH="$PWD/.venv/bin:$PATH"\nmkdir -p logs\nexec /usr/bin/arch -' + architecture + ' .venv/bin/python -m app.desktop "$@" >> logs/desktop-launcher.log 2>&1\n', encoding='utf-8')
    executable.chmod(0o755)
    info = {'CFBundleName': 'WaLiAPI Python', 'CFBundleDisplayName': 'WaLiAPI Python',
            'CFBundleIdentifier': 'local.waliapi.python.desktop', 'CFBundleExecutable': 'waliapi-python',
            'CFBundlePackageType': 'APPL', 'CFBundleVersion': '1', 'CFBundleShortVersionString': '0.4.4',
            'NSHighResolutionCapable': True, 'LSMinimumSystemVersion': '11.0', 'LSArchitecturePriority': [architecture]}
    source_icon = ROOT / 'desktop/assets/icon.icns'
    if source_icon.is_file():
        shutil.copy2(source_icon, resources / 'icon.icns')
        info['CFBundleIconFile'] = 'icon.icns'
    with (target / 'Contents/Info.plist').open('wb') as handle:
        plistlib.dump(info, handle)
    print(target)


if __name__ == '__main__':
    main()
