"""One-off: run the export.fab BOM filter-rule probe matrix on the real editor.

Read-only w.r.t. the project: one `export.fab` per candidate, `pcbUuid` pinned to
PCB1 (R1 checked before each call), files written by the production writer
`boardwise.cli._write_fab_bundle` into `outputs/013_p3_probe_<name>/`. Prints one
line per candidate: BOM rows, the three file names and their sizes.

Usage: .venv/Scripts/python.exe outputs/013_p3_evidence/013_p3_probe_matrix.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from boardwise.cli import _bridge_uri, _open_cli, _write_fab_bundle  # noqa: E402

PCB1 = "ab812fb712e14a62920977ed67aaf8f1"
PROJECT = "毕设FOC驱动板"
ROOT = Path("outputs")

OLD_PRESET = [
    {"property": "Add into BOM", "includeValue": "yes"},
    {"property": "Convert to PCB", "includeValue": "yes"},
]

CANDIDATES = [
    ("p0_control_old_preset", {"bom": {"filterOptions": OLD_PRESET}}),
    ("p1_preset_default", {}),
    (
        "p2_addbom_no_plus_convert_no",
        {"bom": {"filterOptions": [
            {"property": "Add into BOM", "includeValue": "no"},
            {"property": "Convert to PCB", "includeValue": "no"},
        ]}},
    ),
    ("p3_host_default_none", {"bom": {"filterOptions": None}}),
]


def bom_rows(path: Path) -> tuple[int, str]:
    """(data rows, encoding) for one CSV — the row count is the whole point."""
    raw = path.read_bytes()
    for encoding in ("utf-16", "utf-8-sig", "utf-8", "gbk"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        lines = [line for line in text.splitlines() if line.strip()]
        return max(len(lines) - 1, 0), encoding
    return 0, "undecodable"


async def r1_and_run(client, name: str, extra: dict) -> dict:
    listing = await client.call("doc.list", {})
    project = listing["projects"][0]["friendlyName"]
    actual = (listing.get("active") or {}).get("uuid")
    if project != PROJECT or actual != PCB1:
        raise SystemExit(f"R1 refused: project={project!r} active={actual!r}")

    params = {"outDir": f"outputs/013_p3_probe_{name}", "pcbUuid": PCB1, **extra}
    data = await client.call("export.fab", params)
    out = ROOT / f"013_p3_probe_{name}"
    written = _write_fab_bundle(data, out)
    (out / "_probe.json").write_text(
        json.dumps(
            {
                "candidate": name,
                "bomOverride": extra.get("bom", None),
                "effectiveFilters": data["manifest"]["preset"]["bom"].get("filterOptions"),
                "files": [{"role": f["role"], "name": f["name"], "bytes": f["bytes"]} for f in data["files"]],
                "overrides": data["manifest"]["preset"]["overrides"],
                "written": written["written"],
                "failed": data["failed"],
                "partial": data["partial"],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return data, written


async def main() -> int:
    BridgeClient, _, port, token = _open_cli(type("A", (), {"port": None})())
    client = await BridgeClient.open(_bridge_uri(port), token, "cli", client="boardwise-cli")
    try:
        for name, extra in CANDIDATES:
            data, written = await r1_and_run(client, name, extra)
            bom = next((f for f in data["files"] if f["role"] == "bom"), None)
            if bom is None:
                print(f"{name}: NO BOM -> {data['failed']}")
                continue
            path = ROOT / f"013_p3_probe_{name}" / bom["name"]
            rows, encoding = bom_rows(path)
            names = ", ".join(f"{f['role']}={f['name']}({f['bytes']}B)" for f in data["files"])
            print(f"{name}: bom rows={rows} [{encoding}] | {names} | overrides={data['manifest']['preset']['overrides']}")
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
