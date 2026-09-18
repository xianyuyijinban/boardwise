"""Aim the pairing at the context whose focused page is the blank test page.

Two connector instances race for one pairing slot (per-project extension
contexts, measured 2026-09-13). Loop: revoke -> wait for a pairing -> ask the
paired instance what page it sees -> accept when it is the blank test page.
"""
import json
import os
import pathlib
import subprocess
import sys
import time

AUDIT = pathlib.Path.home() / ".boardwise/audit/2026-09-13.jsonl"
REVOKE = [r"E:\boardwise\.venv\Scripts\python.exe", "-m", "boardwise.cli", "bridge", "revoke"]
GEOM = [r"E:\boardwise\.venv\Scripts\python.exe", "-m", "boardwise.cli", "bridge", "call",
        "--action", "sch.geometry"]
CWD = r"E:\boardwise"
ENV = dict(os.environ)
ENV["PYTHONPATH"] = r"E:\boardwise\src"


def fresh_hello_ok() -> bool:
    lines = [json.loads(l) for l in AUDIT.read_text(encoding="utf-8").splitlines() if l.strip()]
    for entry in lines:
        if not isinstance(entry, dict) or "ts" not in entry:
            continue
        if time.time() - entry["ts"] > 20:
            continue
        if entry.get("action") == "hello" and entry.get("role") == "connector" and entry.get("ok"):
            return True
    return False


def wait_pair(seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if fresh_hello_ok():
            return True
        time.sleep(2)
    return False


def focused_components() -> int:
    out = subprocess.run(GEOM, capture_output=True, text=True, cwd=CWD, env=ENV, timeout=60)
    try:
        data = json.loads(out.stdout)
        return len(data.get("components") or [])
    except json.JSONDecodeError:
        return -1


for attempt in range(1, 7):
    subprocess.run(REVOKE, capture_output=True, text=True, cwd=CWD, env=ENV, timeout=30)
    if not wait_pair(45):
        print(f"attempt {attempt}: no pairing within 45s")
        continue
    count = focused_components()
    print(f"attempt {attempt}: paired, focused components = {count}")
    if count == 1:
        print("TARGET ACQUIRED: pairing belongs to the blank test page context")
        sys.exit(0)
print("could not aim the pairing at the blank test page within 6 attempts")
sys.exit(1)
