"""013 batch-2 §八 visual evidence: mark the page, then SCREEN-grab the editor.

Neither `export.screenshot` (the bridge) nor `PrintWindow` can show the canvas on
this host — both hand back cached frames (measured: byte-identical across a
mark/clear cycle). A screen grab with the editor raised is the only path left, so
this driver raises each editor window for ~1 s, grabs, and restores the window
that had the foreground.

usage: python outputs/013_p2_visual_hunt.py [--idle-min 6] [--zoom]
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

from boardwise.bridge import client as bridge_client  # noqa: E402
from boardwise.bridge import daemon as bridge_daemon  # noqa: E402

WANT = "毕设FOC驱动板"
P1 = "5f0f4e169f1745e789501f939bb10851"
OUT = Path("outputs")


def marks_from(path: Path) -> list[dict]:
    out = []
    for f in json.loads(path.read_text(encoding="utf-8"))["findings"]:
        for ref in f.get("refs") or []:
            out.append({"ref": ref, "ruleId": f.get("rule_id", ""),
                        "severity": f.get("severity", ""), "text": f.get("message", "")})
    return out


def grab(prefix: str) -> str:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", "outputs/013_p2_screengrab.ps1", "-Prefix", prefix],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


async def focused(client):
    data = await client.call("doc.list", {})
    return next((p.get("friendlyName", "") for p in data.get("projects") or []
                 if p.get("focused")), ""), data


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle-min", type=float, default=6.0)
    ap.add_argument("--zoom", action="store_true")
    ap.add_argument("--tag", default="vis")
    args = ap.parse_args()

    token = bridge_daemon.ensure_token()
    client = await bridge_client.BridgeClient.open(
        bridge_client.uri_for(port=61190), token, "cli", client="boardwise-cli")
    try:
        deadline = time.time() + args.idle_min * 60
        while True:
            name, data = await focused(client)
            if name == WANT:
                break
            if time.time() > deadline:
                print(f"TIMEOUT: last focused={name!r}")
                return 2
            await asyncio.sleep(4)
        (OUT / f"013_{args.tag}_r1_doclist.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"R1 OK focused={name!r}")

        op = await client.call("doc.open", {"uuid": P1})
        print("doc.open:", json.dumps(op, ensure_ascii=False)[:160])
        if not (op.get("document") or {}).get("matchesRequest"):
            print("ABORT: P1 is not current")
            return 3

        marks = marks_from(OUT / "013_bishe_findings.json")
        marked = await client.call("review.mark", {
            "clear": False, "markers": True, "color": "#FF0000",
            "zoom": bool(args.zoom), "marks": marks, "pageUuid": P1})
        (OUT / f"013_{args.tag}_mark.json").write_text(
            json.dumps(marked, ensure_ascii=False, indent=2), encoding="utf-8")
        print("MARK:", len(marked.get("marked", [])), "marked,",
              len(marked.get("unresolved", [])), "unresolved,",
              json.dumps(marked.get("markers"), ensure_ascii=False))
        print(grab(f"outputs/013_{args.tag}_on_"))

        cleared = await client.call("review.mark", {"clear": True, "markers": True})
        (OUT / f"013_{args.tag}_clear.json").write_text(
            json.dumps(cleared, ensure_ascii=False, indent=2), encoding="utf-8")
        print("CLEAR:", json.dumps(cleared, ensure_ascii=False)[:120])
        print(grab(f"outputs/013_{args.tag}_off_"))
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
