#!/bin/zsh
set -eu
cd -- "$(dirname -- "$0")"
export PATH="$PWD/.venv/bin:$PATH"
if [[ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null || true)" == 1 ]]; then
  exec /usr/bin/arch -arm64 .venv/bin/python -m app.desktop "$@"
fi
exec /usr/bin/arch -x86_64 .venv/bin/python -m app.desktop "$@"
