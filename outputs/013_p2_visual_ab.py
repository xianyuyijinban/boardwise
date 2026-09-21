"""013 batch-2 §八: is the marker overlay actually visible?

Screen grabs are the only capture path on this host (the bridge's own
export.screenshot and PrintWindow both return cached frames). But `--zoom` moves
the view, so a before/after red-pixel count is confounded by different content on
screen. This does a clean A/B in ONE view: grab -> mark (no zoom) -> grab ->
verified clear -> grab. If the marks render, the middle grab differs from its
neighbours at the same scroll/zoom.

usage: python outputs/013_p2_visual_ab.py [--idle-min 5]
"""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "src")

from boardwise.bridge import client as bridge_client  # noqa: E402
from boardwise.bridge import daemon as bridge_daemon  # noqa: E402

WANT = "毕设FOC驱动板"
P1 = "5f0f4e169f1745e789501f939bb10851"
WIN = "143528512"          # the window titled 毕设FOC驱动板 (the one showing the canvas)
OUT = Path("outputs")
LOG = OUT / "013_p2_visual_ab.txt"


def log(line: str) -> None:
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def grab(prefix: str) -> str:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", "outputs/013_p2_screengrab.ps1", "-Prefix", prefix],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return ((proc.stdout or "") + (proc.stderr or "")).strip()


def redscan(path: str) -> str:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", "outputs/013_p2_redscan.ps1", "-Files", path],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (proc.stdout or proc.stderr or "").strip().splitlines()[-1]


def marks_from(path: Path) -> list[dict]:
    out = []
    for f in json.loads(path.read_text(encoding="utf-8"))["findings"]:
        for ref in f.get("refs") or []:
            out.append({"ref": ref, "ruleId": f.get("rule_id", ""),
                        "severity": f.get("severity", ""), "text": f.get("message", "")})
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle-min", type=float, default=5.0)
    ap.add_argument("--tries", type=int, default=6)
    args = ap.parse_args()

    token = bridge_daemon.ensure_token()
    client = await bridge_client.BridgeClient.open(
        bridge_client.uri_for(port=61190), token, "cli", client="boardwise-cli")
    try:
        deadline = __import__("time").time() + args.idle_min * 60
        while True:
            data = await client.call("doc.list", {})
            name = next((p.get("friendlyName", "") for p in data.get("projects") or []
                         if p.get("focused")), "")
            if name == WANT:
                break
            if __import__("time").time() > deadline:
                log(f"TIMEOUT last={name!r}")
                return 2
            await asyncio.sleep(4)
        op = await client.call("doc.open", {"uuid": P1})
        log(f"R1 OK focused={name!r} doc.open matches="
            f"{(op.get('document') or {}).get('matchesRequest')}")

        marks = marks_from(OUT / "013_bishe_findings.json")
        log("--- stage A: baseline grab (no markers) ---")
        log(grab("outputs/013_ab_pre_"))
        log(redscan(f"outputs/013_ab_pre_{WIN}.png"))

        res = await client.call("review.mark", {
            "clear": False, "markers": True, "color": "#FF0000",
            "zoom": False, "marks": marks, "pageUuid": P1})
        (OUT / "013_ab_mark.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"--- stage B: marked {len(res.get('marked', []))} "
            f"{json.dumps(res.get('markers'), ensure_ascii=False)} ---")
        log(grab("outputs/013_ab_on_"))
        log(redscan(f"outputs/013_ab_on_{WIN}.png"))

        cleared = None
        for i in range(1, args.tries + 1):
            await client.call("doc.open", {"uuid": P1})
            r = await client.call("review.mark", {"clear": True, "markers": True})
            cleared = r.get("cleared")
            log(f"clear try#{i}: cleared={cleared}")
            if cleared is True:
                break
            await asyncio.sleep(2)
        log("--- stage C: after a verified clear ---")
        log(grab("outputs/013_ab_off_"))
        log(redscan(f"outputs/013_ab_off_{WIN}.png"))
        return 0 if cleared is True else 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
