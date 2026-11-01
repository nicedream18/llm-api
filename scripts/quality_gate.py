"""Run the repository acceptance gate with the active Python interpreter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path = ROOT) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    report = ROOT / "data" / "quality-coverage.json"
    report.parent.mkdir(exist_ok=True)
    python = sys.executable
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        raise SystemExit("npm is required")
    run([python, "-m", "pytest", "--cov=app", "--cov-fail-under=85",
         f"--cov-report=json:{report}", "-q"])
    baseline = json.loads((ROOT / "docs/quality-baseline.json").read_text(encoding="utf-8"))
    coverage = json.loads(report.read_text(encoding="utf-8"))
    if coverage["totals"]["percent_covered"] + 0.0001 < baseline["global"]:
        raise SystemExit("Global coverage decreased below baseline")
    current = {name.replace("\\", "/"): info for name, info in coverage["files"].items()}
    for name, minimum in baseline["critical"].items():
        if name not in current or current[name]["summary"]["percent_covered"] + 0.0001 < minimum:
            raise SystemExit(f"Critical module coverage decreased: {name}")
    run([python, "-m", "ruff", "check", "app", "tests", "scripts"])
    run([python, "-m", "mypy", "--follow-imports=silent", "app"])
    run([python, "-m", "compileall", "-q", "app", "tests", "scripts"])
    tests = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests/frontend").glob("*.test.cjs"))
    run(["node", "--test", *tests])
    for action in ("test", "typecheck", "build"):
        run([npm, "run", action], ROOT / "frontend")
    run(["git", "diff", "--check"])


if __name__ == "__main__":
    main()
