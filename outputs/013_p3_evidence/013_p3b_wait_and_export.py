"""One-off: wait for the editor's focus to return to 毕设FOC驱动板, then export.

Why a poll instead of a plain command: `doc.open` only reaches documents of the
*focused* project (measured 2026-09-21 — a uuid from another project answers
`CONNECTOR_ERROR: returned no tab id`), and the connector hot-update reloads the
editor page, which moved the focus to test2. So the batch② verification waits for
the human to put the 毕设板 back in front, re-checks R1 immediately before the
call, and only then exports.

**One connection per poll**, deliberately: the first version of this script held
one client open for fifteen minutes and its `doc.list` stopped being answered
while other CLI calls ran against the same daemon — a long-lived client is not
worth debugging for a probe. Short-lived connections are what the CLI itself
does.

Read-only: one `doc.list` per poll, at most one `doc.open` (focus) plus one
`export.fab` (risk=read) at the end. Nothing is written inside the project.

Usage: python outputs/013_p3_evidence/013_p3b_wait_and_export.py [seconds]
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from boardwise.cli import _bridge_uri, _open_cli, _write_fab_bundle  # noqa: E402

PCB1 = "ab812fb712e14a62920977ed67aaf8f1"
PROJECT = "毕设FOC驱动板"
OUT = Path("outputs/013_fab_bishe3")
LOG = Path("outputs/013_p3_evidence/013_p3b_wait_log.txt")


def log(line: str) -> None:
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%H:%M:%S')} {line}\n")


class Session:
    """One short-lived CLI connection, opened and closed per poll."""

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


async def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 900
    deadline = time.monotonic() + limit
    opened = False
    while time.monotonic() < deadline:
        async with Session() as session:
            listing = await session.client.call("doc.list", {})
            project = listing["projects"][0]["friendlyName"]
            active = (listing.get("active") or {}).get("uuid")
            log(f"poll project={project!r} active={active!r}")
            if project == PROJECT and active != PCB1 and not opened:
                opened = True
                log("focus is the right project — opening PCB1 (focus-class prerequisite)")
                try:
                    await session.client.call("doc.open", {"uuid": PCB1})
                except Exception as exc:  # noqa: BLE001 - recorded, never guessed at
                    log(f"doc.open(PCB1) failed: {exc}")
            elif project == PROJECT and active == PCB1:
                # R1 re-checked on the same read that authorises the call.
                data = await session.client.call(
                    "export.fab", {"outDir": str(OUT).replace("\\", "/"), "pcbUuid": PCB1}
                )
                written = _write_fab_bundle(data, OUT)
                (OUT / "_r1.json").write_text(
                    json.dumps({"project": project, "active": active}, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                log(f"export ok: {json.dumps(written['written'], ensure_ascii=False)}")
                log(f"failed={data['failed']} overrides={data['manifest']['preset']['overrides']}")
                print(json.dumps(written["written"], ensure_ascii=False))
                return 0
        await asyncio.sleep(10)
    log("gave up: the focus never came back to 毕设FOC驱动板")
    print("TIMEOUT: focus never returned to the 毕设板")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
