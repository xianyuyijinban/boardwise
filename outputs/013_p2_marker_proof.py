"""013 batch-2 §八: decisive marker-visibility test, then clear the canvas.

Red is not a safe probe on a schematic (component bodies and page frames are red
too), so this marks with #FF00FF — a colour that does not occur in the drawing —
and counts magenta pixels in the same view before, during, and after. The same
run finishes by clearing the overlay (and verifying the clear), because the
canvas belongs to 岳's real project.

usage: python outputs/013_p2_marker_proof.py [--idle-min 6]
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
LOG = OUT / "013_p2_marker_proof.txt"


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


def scan(path: str, r: int, g: int, b: int) -> str:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", "outputs/013_p2_redscan.ps1", "-Files", path,
         "-R", str(r), "-G", str(g), "-B", str(b)],
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
    ap.add_argument("--idle-min", type=float, default=6.0)
    ap.add_argument("--tries", type=int, default=10)
    args = ap.parse_args()

    token = bridge_daemon.ensure_token()
    client = await bridge_client.BridgeClient.open(
        bridge_client.uri_for(port=61190), token, "cli", client="boardwise-cli")
    marks = marks_from(OUT / "013_bishe_findings.json")
    try:
        deadline = time.time() + args.idle_min * 60

        async def clear_until_done(tag: str, tries: int) -> object:
            cleared = None
            for i in range(1, tries + 1):
                try:
                    r = await client.call("review.mark", {"clear": True, "markers": True})
                    cleared = r.get("cleared")
                except bridge_client.BridgeError as exc:  # type: ignore[attr-defined]
                    cleared = f"error {exc.code}"
                log(f"{tag} clear try#{i}: cleared={cleared}")
                if cleared is True:
                    break
                await asyncio.sleep(2)
            return cleared

        # 0. hygiene first: an earlier ab run marked and its clear loop died on a
        # drifted focus, so remove anything left before measuring anything.
        log("stage 0 (sweep any leftover markers)")
        await clear_until_done("sweep", args.tries)

        while True:
            data = await client.call("doc.list", {})
            name = next((p.get("friendlyName", "") for p in data.get("projects") or []
                         if p.get("focused")), "")
            if name == WANT:
                break
            if time.time() > deadline:
                log(f"TIMEOUT last={name!r}")
                return 2
            await asyncio.sleep(4)
        op = await client.call("doc.open", {"uuid": P1})
        log(f"R1 OK focused={name!r} doc.open matches="
            f"{(op.get('document') or {}).get('matchesRequest')}")

        log("stage 1 (baseline)")
        log(grab("outputs/013_proof_before_"))
        log(scan("outputs/013_proof_before_2.png", 200, 70, 200))   # magenta
        log(scan("outputs/013_proof_before_2.png", 200, 70, 70))    # red

        # the focus flaps between projects, so the guard can refuse a mark that
        # was fine a second ago: re-open the page and retry instead of giving up.
        res = None
        for attempt in range(1, args.tries + 1):
            try:
                await client.call("doc.open", {"uuid": P1})
                res = await client.call("review.mark", {
                    "clear": False, "markers": True, "color": "#FF00FF",
                    "zoom": False, "marks": marks, "pageUuid": P1})
                break
            except bridge_client.BridgeError as exc:  # type: ignore[attr-defined]
                log(f"mark attempt #{attempt} refused [{exc.code}]: {exc.message[:90]}")
                res = None
                await asyncio.sleep(2)
        if res is None:
            log("mark never landed")
            return 3
        (OUT / "013_proof_mark.json").write_text(
            json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"stage 2 (markers drawn: {len(res.get('marked', []))} marked, "
            f"{json.dumps(res.get('markers'), ensure_ascii=False)})")
        log(grab("outputs/013_proof_marked_"))
        log(scan("outputs/013_proof_marked_2.png", 200, 70, 200))

        cleared = await clear_until_done("final", args.tries)
        log("stage 3 (after clear)")
        log(grab("outputs/013_proof_after_"))
        log(scan("outputs/013_proof_after_2.png", 200, 70, 200))
        return 0 if cleared is True else 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
