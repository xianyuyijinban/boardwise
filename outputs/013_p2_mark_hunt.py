"""013 batch-2 §八 acceptance driver: act the instant the identity hits.

The editor's focused project flaps between /test, test2 and 毕设FOC驱动板 (岳 is
opening projects; 012 recorded the same drift). R1 says: verify the focused
project name is 毕设FOC驱动板 *at the moment of the write* — so this script
hunts for that state, and inside the same connection does:

  doc.list (R1)  ->  doc.open(page)  ->  review.mark  ->  capture the editor
  windows  ->  review.mark clear  ->  capture again

Every step's raw payload is written under outputs/. Read-only apart from the
marker overlay it is here to verify (which `clear` removes).

usage: python outputs/013_p2_mark_hunt.py [--color #FF0000] [--zoom] [--idle-min 8]
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

PAGE = "5f0f4e169f1745e789501f939bb10851"          # 毕设FOC驱动板 / schematic1 / P1
WANT = "毕设FOC驱动板"
OUT = Path("outputs")
FINDINGS = OUT / "013_bishe_findings.json"


def marks_from(path: Path) -> list[dict]:
    findings = json.loads(path.read_text(encoding="utf-8"))["findings"]
    out = []
    for f in findings:
        for ref in f.get("refs") or []:
            out.append({
                "ref": ref,
                "ruleId": f.get("rule_id", ""),
                "severity": f.get("severity", ""),
                "text": f.get("message", ""),
            })
    return out


def capture(prefix: str) -> str:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", "outputs/013_p2_capture_all.ps1", "-Prefix", prefix],
        capture_output=True, text=True,
    )
    return (proc.stdout or "") + (proc.stderr or "")


async def focused(client) -> tuple[str, dict]:
    data = await client.call("doc.list", {})
    projects = data.get("projects") or []
    name = next((p.get("friendlyName", "") for p in projects if p.get("focused")), "")
    return name, data


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--color", default="#FF0000")
    ap.add_argument("--zoom", action="store_true")
    ap.add_argument("--idle-min", type=float, default=8.0)
    ap.add_argument("--tag", default="markP1")
    args = ap.parse_args()

    token = bridge_daemon.ensure_token()
    client = await bridge_client.BridgeClient.open(
        bridge_client.uri_for(port=61190), token, "cli", client="boardwise-cli"
    )
    try:
        deadline = time.time() + args.idle_min * 60
        seen: list[str] = []
        tries = 0
        while True:
            tries += 1
            name, data = await focused(client)
            if name != seen[-1:] or tries == 1:
                seen.append(name)
                (OUT / "013_p2_hunt_trace.txt").open("a", encoding="utf-8").write(
                    f"{time.strftime('%H:%M:%S')} try#{tries} focused={name!r}\n"
                )
            if name == WANT:
                break
            if time.time() > deadline:
                print(f"TIMEOUT: {WANT!r} never focused in {args.idle_min} min; saw {seen}")
                return 2
            await asyncio.sleep(4)

        (OUT / f"013_p2_{args.tag}_doclist.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"R1 HIT at try#{tries}: focused={name!r}")

        opened = await client.call("doc.open", {"uuid": PAGE})
        print("doc.open:", json.dumps(opened, ensure_ascii=False))
        (OUT / f"013_p2_{args.tag}_docopen.json").write_text(
            json.dumps(opened, ensure_ascii=False, indent=2), encoding="utf-8")
        if not (opened.get("document") or {}).get("matchesRequest"):
            print("doc.open did not make the page current — stopping (no marker call)")

        marks = marks_from(FINDINGS)
        params = {"clear": False, "markers": True, "color": args.color,
                  "zoom": bool(args.zoom), "marks": marks, "pageUuid": PAGE}
        data = await client.call("review.mark", params)
        (OUT / f"013_p2_{args.tag}_mark.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        markers = data.get("markers") or {}
        print(f"MARK mode={data.get('mode')} marked={len(data.get('marked', []))} "
              f"unresolved={len(data.get('unresolved', []))} "
              f"attempted={markers.get('attempted')} accepted={markers.get('accepted')}")

        cap_prefix = f"outputs/013_cap_{args.tag}_on_"
        print(capture(cap_prefix))
        shot = subprocess.run(
            [".venv/Scripts/python.exe", "-m", "boardwise.cli", "bridge", "screenshot",
             f"outputs/013_{args.tag}_bridge.png"],
            capture_output=True, text=True)
        print("bridge screenshot:", (shot.stderr or shot.stdout).strip())

        cleared = await client.call("review.mark", {"clear": True, "markers": True})
        (OUT / f"013_p2_{args.tag}_clear.json").write_text(
            json.dumps(cleared, ensure_ascii=False, indent=2), encoding="utf-8")
        print("CLEAR:", json.dumps(cleared, ensure_ascii=False))
        print(capture(f"outputs/013_cap_{args.tag}_off_"))
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
