"""013 batch-2 §八 + §六 on the real host, done in one identity window.

The focused project flaps between /test, test2 and 毕设FOC驱动板 while 岳 works
(012 recorded the same drift). R1 is a per-action check, so this driver polls
`doc.list` until the focused project is 毕设FOC驱动板 **and** then runs the whole
acceptance inside that window:

  §八  doc.open(P1) -> review.mark -> capture -> clear -> capture
       -> review.mark with a nonexistent pageUuid (expect PAGE_MISMATCH, canvas untouched)
       -> doc.open(PCB1) -> review.mark with no pageUuid (expect CONNECTOR_ERROR)
  §六  measure PCB1 vs PCB2 -> export-fab --pcb <the bigger board> -> inspect the bundle

Every raw payload lands in outputs/013_p8_*.json / 013_p6_*.json. The only host
change is the marker overlay the acceptance is about (removed by `clear`) plus
which document is in front (doc.open is risk=read: "Changes the editor's active
document, never the project's content").

usage: python outputs/013_p2_full_hunt.py [--idle-min 30]
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
P1 = "5f0f4e169f1745e789501f939bb10851"          # schematic1 / P1
P2 = "b0342c521c674ddab8dcc8aaf269ca59"          # schematic1 / P2
P1B = "0876ea4e415ed158"                          # schematic2 / P1
PCB1 = "ab812fb712e14a62920977ed67aaf8f1"
PCB2 = "308cffdb9f930ec1"
OUT = Path("outputs")
FINDINGS = OUT / "013_bishe_findings.json"
LOG = OUT / "013_p2_full_hunt_trace.txt"


def log(line: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    print(f"{stamp} {line}", flush=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {line}\n")


def save(name: str, payload) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def marks_from(path: Path) -> list[dict]:
    out = []
    for f in json.loads(path.read_text(encoding="utf-8"))["findings"]:
        for ref in f.get("refs") or []:
            out.append({"ref": ref, "ruleId": f.get("rule_id", ""),
                        "severity": f.get("severity", ""), "text": f.get("message", "")})
    return out


def capture(prefix: str) -> None:
    proc = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", "outputs/013_p2_capture_all.ps1", "-Prefix", prefix],
        capture_output=True, text=True)
    log(f"capture {prefix}: {(proc.stdout or '').strip().replace(chr(10), ' | ')}")


def shell(args: list[str], out_name: str) -> int:
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (OUT / out_name).write_text(
        f"$ {' '.join(args)}\nexit={proc.returncode}\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}\n", encoding="utf-8")
    log(f"{' '.join(args[1:])} -> exit {proc.returncode}")
    return proc.returncode


async def call(client, action: str, params: dict, name: str):
    try:
        data = await client.call(action, params)
        save(name, data)
        return data, None
    except bridge_client.BridgeError as exc:  # type: ignore[attr-defined]
        err = {"error": {"code": exc.code, "message": exc.message, "detail": exc.detail}}
        save(name, err)
        return None, err


def brief(label: str, data, err) -> None:
    if err:
        log(f"{label}: [{err['error']['code']}] {err['error']['message'][:130]}")
    else:
        log(f"{label}: {json.dumps(data, ensure_ascii=False)[:200]}")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle-min", type=float, default=30.0)
    args = ap.parse_args()

    token = bridge_daemon.ensure_token()
    client = await bridge_client.BridgeClient.open(
        bridge_client.uri_for(port=61190), token, "cli", client="boardwise-cli")
    log("=== full hunt started (looking for focused project 毕设FOC驱动板) ===")
    try:
        deadline = time.time() + args.idle_min * 60
        last = None
        while True:
            name, data = await _focused(client)
            if name != last:
                log(f"focused={name!r}")
                last = name
            if name == WANT:
                break
            if time.time() > deadline:
                log(f"TIMEOUT after {args.idle_min} min; last focused={last!r}")
                return 2
            await asyncio.sleep(4)

        save("013_p8_r1_doclist.json", data)
        log(f"R1 OK: focused={name!r} active={json.dumps(data.get('active'), ensure_ascii=False)}")

        # ---------- §八 ----------
        opened, err = await call(client, "doc.open", {"uuid": P1}, "013_p8_docopen_p1.json")
        brief("doc.open(P1)", opened, err)
        if err or not (opened.get("document") or {}).get("matchesRequest"):
            log("ABORT: P1 is not the current document — refusing to mark")
            return 3

        marks = marks_from(FINDINGS)
        data, err = await call(client, "review.mark",
                               {"clear": False, "markers": True, "color": "#FF0000",
                                "zoom": True, "marks": marks, "pageUuid": P1},
                               "013_p8_mark.json")
        brief("review.mark(zoom)", data, err)
        capture("outputs/013_p8_on_")
        shell([".venv/Scripts/python.exe", "-m", "boardwise.cli", "bridge", "screenshot",
               "outputs/013_mark_P1.png"], "013_p8_screenshot.txt")

        data, err = await call(client, "review.mark", {"clear": True, "markers": True},
                               "013_p8_clear.json")
        brief("review.mark(clear)", data, err)
        capture("outputs/013_p8_off_")
        shell([".venv/Scripts/python.exe", "-m", "boardwise.cli", "bridge", "screenshot",
               "outputs/013_mark_cleared.png"], "013_p8_screenshot_cleared.txt")

        data, err = await call(client, "review.mark",
                               {"clear": False, "markers": True, "marks": marks,
                                "pageUuid": "0000000000000000"},
                               "013_p8_mismatch.json")
        brief("review.mark(bogus pageUuid -> expect PAGE_MISMATCH)", data, err)
        capture("outputs/013_p8_mismatch_")

        # ---------- PCB in front: review.mark must refuse ----------
        opened, err = await call(client, "doc.open", {"uuid": PCB1}, "013_p8_docopen_pcb1.json")
        brief("doc.open(PCB1)", opened, err)
        data, err = await call(client, "review.mark",
                               {"clear": False, "markers": True, "marks": marks},
                               "013_p8_pcb_focus.json")
        brief("review.mark(PCB focused -> expect CONNECTOR_ERROR)", data, err)
        capture("outputs/013_p8_pcbfocus_")

        # ---------- §六 ----------
        # pcb.readback reads the *focused* board (no uuid param), so measure each
        # board by putting it in front first — that is also the state export.fab needs.
        counts = {}
        for tag, uuid in (("pcb1", PCB1), ("pcb2", PCB2)):
            op, operr = await call(client, "doc.open", {"uuid": uuid}, f"013_p6_docopen_{tag}.json")
            if operr or not (op.get("document") or {}).get("matchesRequest"):
                log(f"doc.open({tag}) failed: {json.dumps(operr or op, ensure_ascii=False)[:200]}")
                counts[tag] = None
                continue
            rb, rberr = await call(client, "pcb.readback", {"includePrimitives": False},
                                   f"013_p6_readback_{tag}.json")
            n = (rb or {}).get("componentCount")
            counts[tag] = n
            log(f"pcb.readback {tag} ({uuid}) -> componentCount={n} "
                f"err={(rberr or {}).get('error', {}).get('code')}")

        target, target_tag = (PCB1, "pcb1")
        if (counts.get("pcb2") or 0) > (counts.get("pcb1") or 0):
            target, target_tag = PCB2, "pcb2"
        log(f"export target = {target_tag} ({target}) by component count {counts}")

        op, operr = await call(client, "doc.open", {"uuid": target}, "013_p6_docopen_target.json")
        brief(f"doc.open({target_tag}) for the export", op, operr)
        if operr or not (op.get("document") or {}).get("matchesRequest"):
            log("ABORT: the export target is not in front")
            return 4

        name, data = await _focused(client)
        save("013_p6_r1_doclist.json", data)
        log(f"R1 (fab): focused={name!r} active={json.dumps(data.get('active'), ensure_ascii=False)}")

        shell([".venv/Scripts/python.exe", "-m", "boardwise.cli", "bridge", "export-fab",
               "--out", "outputs/013_fab_bishe", "--pcb", target], "013_p6_export.txt")
        _inspect_bundle()

        # leave the schematic page in front again
        await call(client, "doc.open", {"uuid": P1}, "013_p8_docopen_restore.json")
        log("restored P1 in front")
        return 0
    finally:
        await client.close()


async def _focused(client):
    data = await client.call("doc.list", {})
    projects = data.get("projects") or []
    return next((p.get("friendlyName", "") for p in projects if p.get("focused")), ""), data


def _inspect_bundle() -> None:
    d = OUT / "013_fab_bishe"
    if not d.is_dir():
        log("fab bundle dir missing")
        return
    for p in sorted(d.iterdir()):
        head = ""
        if p.suffix == ".csv":
            head = p.read_text(encoding="utf-8", errors="replace").splitlines()[0][:400]
        log(f"fab file {p.name} {p.stat().st_size} B {head}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
