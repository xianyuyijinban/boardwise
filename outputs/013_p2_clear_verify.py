"""013 batch-2: clear the indicator markers until the host says it did, then grab.

`review.mark {clear:true}` returned cleared:false once (note: "the canvas refused
the removal — an unsupported canvas or an unknown tab") right after a successful
mark — the host is flaky here, so retry and report each attempt instead of
believing one call. Marker hygiene on 岳's real project matters more than the
retry count.

usage: python outputs/013_p2_clear_verify.py [--tries 8]
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

OUT = Path("outputs")
P1 = "5f0f4e169f1745e789501f939bb10851"
LOG = OUT / "013_p2_clear_verify.txt"


def log(line: str) -> None:
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tries", type=int, default=8)
    args = ap.parse_args()

    token = bridge_daemon.ensure_token()
    client = await bridge_client.BridgeClient.open(
        bridge_client.uri_for(port=61190), token, "cli", client="boardwise-cli")
    attempts = []
    try:
        for i in range(1, args.tries + 1):
            data = await client.call("doc.list", {})
            focus = next((p.get("friendlyName", "") for p in data.get("projects") or []
                          if p.get("focused")), "")
            active = (data.get("active") or {}).get("uuid")
            # put the marked page back in front, then ask the host to clear
            try:
                opened = await client.call("doc.open", {"uuid": P1})
                matches = bool((opened.get("document") or {}).get("matchesRequest"))
            except bridge_client.BridgeError as exc:  # type: ignore[attr-defined]
                matches = f"error {exc.code}"
            try:
                res = await client.call("review.mark", {"clear": True, "markers": True})
                cleared = res.get("cleared")
                note = res.get("note", "")
            except bridge_client.BridgeError as exc:  # type: ignore[attr-defined]
                cleared, note = f"error {exc.code}", exc.message
            attempts.append({"try": i, "focus": focus, "active": active,
                             "docOpenMatches": matches, "cleared": cleared, "note": note})
            log(f"try#{i} focus={focus!r} active={active} docOpenMatches={matches} "
                f"cleared={cleared}")
            if cleared is True:
                break
            await asyncio.sleep(3)
    finally:
        await client.close()
    (OUT / "013_p2_clear_verify.json").write_text(
        json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = attempts and attempts[-1].get("cleared") is True
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", "outputs/013_p2_screengrab.ps1", "-Prefix", "outputs/013_vis_cleared_"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    log((proc.stdout or "").strip())
    log(f"final cleared={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
