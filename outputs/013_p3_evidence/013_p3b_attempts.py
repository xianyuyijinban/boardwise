"""One-off: get the new bundle into the window that has the 毕设板 open, then export.

**The environment this has to survive.** This machine has several editor windows
and the daemon keeps ONE connector socket, so "which build answers" and "which
project is in front" alternate independently — the audit log
(`~/.boardwise/audit/2026-09-21.jsonl`) shows hellos reporting 0.4.9, 0.4.10 and
0.4.10 inside one minute, and the focused project flipping with them (test,
test2, 毕设FOC驱动板). That, not a human hand, is the "focus drift" the earlier
batch recorded. An export that passes R1 can therefore still be answered by a
stale bundle — which is exactly what happened first: R1 clean, BOM header 17
columns (the old preset).

**The protocol**, per attempt, on one connection:

  1. read the answering connector's version (`sys.probe`) and R1 (`doc.list`);
  2. if that window is the 毕设板 with PCB1 in front, export and measure the BOM
     header — 15 columns means the new build answered, and that bundle is written
     to the delivery directory `outputs/013_fab_bishe3/`;
  3. if the header is 17, that window still runs the older build: push the
     freshly built bundle into *that* window (`sys.self_update`, the payload
     `bridge update-connector` sends), wait for the page to come back, and try
     again. A stale build's export goes to `outputs/013_p3b_stale/` and is
     recorded, never delivered.

Both versions in play are called 0.4.10, so the **header is the only marker that
says which build answered** — hence step 3 keyed on the header, not on the
version string. If a self-update lands (the log records `old`/`new`/`bytes`) and
the very next export from the same window still shows 17 columns, that means the
same-version rewrite did not take effect in the editor, and the exit code is 2
so the caller can decide (a version bump is the remaining lever).

Every attempt is appended to `013_p3b_attempts.jsonl`.

Usage: python outputs/013_p3_evidence/013_p3b_attempts.py [attempts]
"""

import asyncio
import csv
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from boardwise.cli import (  # noqa: E402
    _bridge_uri,
    _connector_artifacts,
    _open_cli,
    _update_connector_payload,
    _write_fab_bundle,
)

PCB1 = "ab812fb712e14a62920977ed67aaf8f1"
PROJECT = "毕设FOC驱动板"
GOOD = Path("outputs/013_fab_bishe3")
SCRATCH = Path("outputs/013_p3b_stale")
LOG = Path("outputs/013_p3_evidence/013_p3b_attempts.jsonl")


class Session:
    def __init__(self) -> None:
        self.BridgeClient, _, self.port, self.token = _open_cli(type("A", (), {"port": None})())

    async def __aenter__(self):
        self.client = await self.BridgeClient.open(
            _bridge_uri(self.port), self.token, "cli", client="boardwise-cli"
        )
        return self

    async def __aexit__(self, *_exc):
        await self.client.close()
        return False


def bom_shape(path: Path) -> tuple[int, int, str]:
    rows = list(csv.reader(io.StringIO(path.read_bytes().decode("utf-16")), delimiter="\t"))
    return len(rows[0]), len(rows) - 1, "\t".join(rows[0])


def note(entry: dict) -> None:
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False))


async def main() -> int:
    attempts = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    bundle, extension_json = _connector_artifacts()
    params, byte_count = _update_connector_payload(bundle, extension_json, None)
    updated_once = False
    for attempt in range(1, attempts + 1):
        async with Session() as session:
            probe = await session.client.call("sys.probe", {})
            connector = probe.get("connector")
            listing = await session.client.call("doc.list", {})
            project = listing["projects"][0]["friendlyName"]
            active = (listing.get("active") or {}).get("uuid")
            entry = {
                "attempt": attempt,
                "at": time.strftime("%H:%M:%S"),
                "connector": connector,
                "project": project,
                "active": active,
                "bundleBytes": byte_count,
            }
            if project == PROJECT and active == PCB1:
                data = await session.client.call(
                    "export.fab", {"outDir": str(GOOD).replace("\\", "/"), "pcbUuid": PCB1}
                )
                _write_fab_bundle(data, SCRATCH)
                columns, rows, header = bom_shape(SCRATCH / "fab_bom.csv")
                entry.update({"columns": columns, "rows": rows, "header": header})
                if columns == 15:
                    _write_fab_bundle(data, GOOD)
                    (GOOD / "_r1.json").write_text(
                        json.dumps(
                            {"connector": connector, "project": project, "active": active},
                            ensure_ascii=False,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    entry["delivered"] = True
                    note(entry)
                    return 0
                # 17 columns: this window is still the older build. Hand it the
                # new one and come back after its page reloads.
                result = await session.client.call("sys.self_update", params)
                entry["selfUpdate"] = {
                    "old": result.get("oldVersion"),
                    "new": result.get("newVersion"),
                    "bytes": result.get("bytes"),
                }
                if updated_once:
                    note(entry)
                    print("the same-version rewrite did not take effect — see the log", file=sys.stderr)
                    return 2
                updated_once = True
                note(entry)
                await asyncio.sleep(15)
                continue
            note(entry)
        await asyncio.sleep(15)
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
