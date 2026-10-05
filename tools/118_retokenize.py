#!/usr/bin/env python3
"""118: rewrite the flyback circuit spec in the **measured** pin tokens.

    .venv/Scripts/python.exe tools/118_retokenize.py [--check]

113 named every pin by role and shipped a profile to match; 118 measured the
host's symbols and found the two do not line up (``tools/118_token_map.py`` has
the crosswalk and where each row comes from).  This applies that crosswalk to
``blocklib/specs/flyback_uc3845.circuit.json`` so the spec writes what the
symbols are.

``--check`` reports the diff without writing, which is what the test calls.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _extra in (ROOT / "src", ROOT / "tests"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from importlib import import_module  # noqa: E402

TOKEN_MAP = import_module("118_token_map").TOKEN_MAP  # noqa: E402
NO_SUCH_PIN = import_module("118_token_map").NO_SUCH_PIN  # noqa: E402
SPEC = ROOT / "blocklib" / "specs" / "flyback_uc3845.circuit.json"


def retokenized(spec: dict) -> tuple[dict, list[str], list[str]]:
    """The spec with every part's pin tokens replaced, plus what it could not map."""
    table = {item["id"]: TOKEN_MAP.get(item["id"], {}) for item in spec["parts"]}
    dropped: list[str] = []
    for part_id, reasons in NO_SUCH_PIN.items():
        for token, why in reasons.items():
            dropped.append(f"{part_id}.{token}: {why}")
    out = json.loads(json.dumps(spec))
    removed: list[str] = []
    # **118's one real circuit edit.** 113 put `T1.A2` (the auxiliary cold end)
    # on PGND and `T1.S2` (the secondary return) on SEC_GND — two terminals on a
    # part that measures five pins and has one spare for both returns.  Measured
    # pin 4 is that one terminal, and the grammar says which net it must be on:
    # of the three assignments tried, only `pin 4 = SEC_GND` lets the chain
    # close (`_secondary` requires `sec_gnd in tx_nets`; on PGND the transformer
    # has no pin on the secondary ground and the flyback reading is refused).
    # So the **auxiliary cold end moves from PGND to SEC_GND**.  That is a change
    # to the circuit, not a rename, and it is why the refusal below is reported
    # by name rather than applied silently.
    COLD_END_MOVES = {"T1.A2": ("PGND", "SEC_GND")}
    for token, (was, now) in COLD_END_MOVES.items():
        part_id, _, pin = token.partition(".")
        moved = f"{part_id}.{pin}"
        for net in out["nets"]:
            if net["id"] == was and moved in net["members"]:
                net["members"] = [m for m in net["members"] if m != moved]
        for net in out["nets"]:
            if net["id"] == now and moved not in net["members"]:
                net["members"].append(moved)
            elif net["id"] == now:
                # the other return token already put this very pin here
                out.setdefault("_118_dedup", []).append(
                    f"{net['id']}: {moved} was already a member (both return "
                    f"tokens resolve to the one measured terminal)"
                )
        out.setdefault("_118_moved", []).append(
            f"{moved}: {was} -> {now} (the five-pin skeleton's one return "
            f"terminal; see tools/118_token_map.py)"
        )
    for net in out["nets"]:
        net["members"] = sorted(net["members"])
    for net in out["nets"]:
        members = []
        for member in net["members"]:
            part_id, _, token = member.partition(".")
            if part_id in NO_SUCH_PIN and token in NO_SUCH_PIN[part_id]:
                # 113 named a pin the measured symbol does not have.  Dropping
                # it is a real edit to the circuit, so it is done here and
                # reported by name — not left to fail as a dangling token.
                removed.append(f"{net['id']}: dropped {member}")
                continue
            replacement = table.get(part_id, {}).get(token)
            if replacement is None:
                members.append(member)
            else:
                members.append(f"{part_id}.{replacement}")
        net["members"] = sorted(members)
    for net in out["nets"]:
        # Two of 113's tokens can resolve to the same measured pin (the
        # transformer's two returns share one terminal), and a member list is a
        # set: listing it twice is a spec error, not a stronger statement.
        if len(set(net["members"])) != len(net["members"]):
            out.setdefault("_118_dedup", []).append(
                f"{net['id']}: collapsed "
                f"{sorted(m for m in net['members'] if net['members'].count(m) > 1)}"
            )
            net["members"] = sorted(set(net["members"]))
    moved = out.pop("_118_moved", [])
    dedup = out.pop("_118_dedup", [])
    return out, dropped, removed + moved + dedup, sorted(
        f"{p}.{t}" for p, mapping in table.items() for t in mapping
    )


def main(argv: list[str]) -> int:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    out, dropped, removed, mapped = retokenized(spec)
    if "--check" in argv:
        before = {n["id"]: sorted(n["members"]) for n in spec["nets"]}
        after = {n["id"]: sorted(n["members"]) for n in out["nets"]}
        for net in sorted(before):
            if before[net] != after[net]:
                print(f"  {net}:")
                print(f"     was {before[net]}")
                print(f"     now {after[net]}")
        return 0
    SPEC.write_text(
        json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"retokenized {SPEC.relative_to(ROOT).as_posix()}")
    print(f"  {len(mapped)} tokens mapped")
    for line in removed:
        print(f"  member removed -- {line}")
    print(f"  {len(dropped)} pin(s) with no counterpart:")
    for line in dropped:
        print(f"    - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
