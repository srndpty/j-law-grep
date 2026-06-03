from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ]
    python = next((path for path in candidates if path.exists()), Path(sys.executable))
    return subprocess.call([str(python), *sys.argv[1:]], cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
