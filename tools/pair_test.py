"""Revoke -> wait for a connector pairing. Verify the context separately
via the reference CLI's read-only `project info` (active project == /test).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = Path.home() / ".boardwise" / "audit"
PY = HERE / ".venv" / "Scripts" / "python.exe"


def wait_hello_ok(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        files = sorted(AUDIT.glob("*.jsonl"))
        if files:
            for line in files[-1].read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if (
                    entry.get("action") == "hello"
                    and entry.get("role") == "connector"
                    and entry.get("ok")
                    and time.time() - entry.get("ts", 0) < 30
                ):
                    return True
        time.sleep(2)
    return False


def main() -> int:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    for round_no in range(1, rounds + 1):
        subprocess.run(
            [str(PY), "-m", "boardwise.cli", "bridge", "revoke"],
            cwd=str(HERE), capture_output=True,
        )
        print(f"round {round_no}: revoked, waiting for a connector…", flush=True)
        if wait_hello_ok(60):
            print(f"round {round_no}: PAIRED")
            return 0
        print(f"round {round_no}: no pairing in 60s")
    print("FAILED: no pairing")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
