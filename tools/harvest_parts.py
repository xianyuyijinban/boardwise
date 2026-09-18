"""Harvest a curated part library out of boards (task 008b, work item 2).

    python tools/harvest_parts.py --sources blocklib/sources/*.eprj2 \
        --out blocklib/parts.json

Offline by default: it reads the boards as files and writes JSON, touching
neither the network nor the editor.

    python tools/harvest_parts.py --sources ... --verify     # needs the bridge
    python tools/harvest_parts.py --sources ... --check      # re-run, compare

``--verify`` asks the **library** what each footprint is really called, through
``lib.footprint.get`` (the same action 006b used to confirm `R0402`/`R0805`).
The point of the check is that the *project's* footprint document title and the
*library's* name are two different claims; the entry keeps the project's name
and records whether the library agreed. It needs a running editor, so it is
opt-in — and when the bridge cannot be asked, entries stay ``unverified``
rather than being upgraded by assumption.

``--check`` re-harvests and compares against the file already on disk. It is the
idempotence claim made checkable: the same sources must produce byte-identical
entries, and a difference is printed as a diff of keys rather than a summary.

``--rehome`` re-anchors the entries whose stored identity cannot be a library key
(two parts harvested from a *personal* library carry the library's name where the
uuid belongs — measured 2026-09-16: `lib.device.get` answers `found:false` for
both). It resolves each one by C-number through `lib.device.search`, which accepts
an item only on an exact, unique match, and writes the result to a **sidecar**
(`blocklib/parts.corrections.json`) rather than editing the library: the harvest stays
a deterministic function of sources + corrections, which is what keeps `--check`
meaningful. Standalone mode — the library is refreshed by the next `--verify`
run, which applies the sidecar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from boardwise.core.parts import (  # noqa: E402
    IdentityOverride,
    LibraryCorrections,
    PartEntry,
    PartError,
    PartLibrary,
    library_to_json,
    load_corrections,
    load_parts,
    looks_like_library_uuid,
    save_corrections,
    save_parts,
)
from boardwise.engines.harvest import (  # noqa: E402
    FOOTPRINT_UUID_PATHS,
    footprint_uuid_of_device,
    BRIDGE_DECIDED_FIELDS,
    harvest,
    reconcile_counts,
    strip_bridge_decided,
    strip_bridge_decided_notes,
)


def _expand(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for pattern in patterns:
        if any(ch in pattern for ch in "*?["):
            out.extend(sorted(p for p in Path().glob(pattern) if p.is_file()))
        else:
            out.append(Path(pattern))
    return out


async def collect_footprint_names(
    sources: list[Path],
    *,
    client: object = None,
    corrections: LibraryCorrections | None = None,
) -> tuple[dict[tuple[str, str], str], list[str]]:
    """Ask the library what each device's footprint is called — by device.

    The chain is the one measured on the machine
    (2026-09-16)::

        lib.device.get(uuid=<library device uuid>, libraryUuid=<library uuid>)
          -> item.association.footprintUuid
        lib.footprint.get(uuid=<that>, libraryUuid=<library uuid>)
          -> name

    It starts from the **device** on purpose. The obvious-looking shortcut —
    asking ``lib.footprint.get`` with the footprint uuid the project holds —
    fails on the live library, exactly as 006b measured for project-local
    *symbol* uuids: a project-local document uuid is not a library key.

    One chain per distinct device uuid pair (not per entry, not per board), and
    a failure is per device: it is reported and that entry stays unverified.
    ``client`` is injectable so the whole path can be driven by a stub.
    """
    from boardwise.engines.harvest import devices_to_verify, footprint_uuid_of_device

    wanted = devices_to_verify(sources, corrections=corrections)
    problems: list[str] = []
    if not wanted:
        return ({}, problems)

    owns_client = client is None
    if owns_client:
        from boardwise.bridge.client import BridgeClient, uri_for
        from boardwise.bridge.daemon import ensure_token, resolve_port

        port = resolve_port()
        client = await BridgeClient.open(
            uri_for(port=port), ensure_token(), "cli", client="boardwise-cli"
        )
    answers: dict[tuple[str, str], str] = {}
    try:
        for pair, label in wanted.items():
            device_uuid, library_uuid = pair
            try:
                device = await client.call(
                    "lib.device.get", {"uuid": device_uuid, "libraryUuid": library_uuid}
                )
            except Exception as exc:  # noqa: BLE001 — one device failing is not fatal
                problems.append(
                    f"lib.device.get({label}, {device_uuid}) failed: {exc}"
                )
                continue
            item = device.get("item") if isinstance(device, dict) else None
            footprint_uuid, path = footprint_uuid_of_device(item)
            if not footprint_uuid:
                where = "the response carried no `item`" if item is None else (
                    "the item carries no footprint uuid under any known path "
                    f"({', '.join('.'.join(p) for p in FOOTPRINT_UUID_PATHS)})"
                )
                problems.append(f"lib.device.get({label}) answered nothing usable: {where}")
                continue
            try:
                footprint = await client.call(
                    "lib.footprint.get",
                    {"uuid": footprint_uuid, "libraryUuid": library_uuid},
                )
            except Exception as exc:  # noqa: BLE001
                problems.append(
                    f"lib.footprint.get({label}, {footprint_uuid} via {path}) failed: {exc}"
                )
                continue
            name = ""
            if isinstance(footprint, dict):
                name = str(footprint.get("name") or "").strip()
            if not name:
                problems.append(
                    f"lib.footprint.get({label}, {footprint_uuid} via {path}) "
                    "returned no name"
                )
                continue
            answers[pair] = name
    finally:
        if owns_client:
            await client.close()
    return (answers, problems)


# ---------------------------------------------------------------------------
# --rehome: identity re-anchoring (008b tail)
# ---------------------------------------------------------------------------

#: The sidecar a re-homing run writes, and every later harvest applies.
CORRECTIONS_FILE = "blocklib/parts.corrections.json"


def identity_candidates(library: PartLibrary) -> list[PartEntry]:
    """Entries whose stored identity cannot be resolved as it stands.

    The criterion is local and checkable — the library uuid is not uuid-shaped —
    so "which entries need re-anchoring" is reproducible without the bridge, and
    an entry that is merely *unverified* is not swept up in it.
    """
    return [
        part for part in library.parts if not looks_like_library_uuid(part.libraryUuid)
    ]


class Rehoming:
    """The outcome of asking the library to identify the broken entries.

    A plain class rather than a dataclass on purpose: this file is loaded by
    path from the tests, and Python 3.14's `dataclasses` looks the defining
    module up in `sys.modules` — which a path-loaded module is not in, so a
    dataclass here fails at import time with a `NoneType` error that says
    nothing about the cause.
    """

    def __init__(self) -> None:
        self.records: dict[str, IdentityOverride] = {}
        #: One line per entry that could **not** be re-anchored, with the reason.
        self.problems: list[str] = []

    @property
    def ok(self) -> bool:
        return not self.problems


async def plan_rehoming(
    client: object, library: PartLibrary, *, entries: list[PartEntry] | None = None
) -> Rehoming:
    """Resolve each broken identity by C-number, through the bridge.

    An identity is accepted only on an **exact, unique** C-number match — the
    same rule `parts select --resolve` uses, because "the search happened to
    return something" is not an identity. A part the library cannot answer for
    keeps its broken identity and is reported; nothing is written on its behalf.
    """
    from boardwise.engines.select import resolve_by_lcsc

    outcome = Rehoming()
    for entry in entries if entries is not None else identity_candidates(library):
        if not entry.lcsc:
            outcome.problems.append(f"{entry.key}: no C-number, so nothing to match on")
            continue
        resolution = await resolve_by_lcsc(client, entry.lcsc)
        if not resolution.resolved:
            outcome.problems.append(f"{entry.lcsc} ({entry.key}): {resolution.reason}")
            continue
        if not looks_like_library_uuid(resolution.libraryUuid):
            outcome.problems.append(
                f"{entry.lcsc} ({entry.key}): the search matched on "
                f"{resolution.matched_key!r} but answered library uuid "
                f"{resolution.libraryUuid!r}, which is not a uuid either"
            )
            continue
        outcome.records[entry.lcsc] = IdentityOverride(
            lcsc=entry.lcsc,
            deviceUuid=resolution.deviceUuid,
            libraryUuid=resolution.libraryUuid,
            note=(
                f"identity re-anchored by C-number through `lib.device.search` "
                f"(matched on {resolution.matched_key!r}); the stored library uuid "
                f"{entry.libraryUuid!r} is a library *name*, not a uuid, so "
                f"`lib.device.get` rejected the pair. device uuid "
                f"{entry.deviceUuid} -> {resolution.deviceUuid}."
            ),
        )
    return outcome


async def _open_client():
    """The bridge client a re-homing run talks through.

    A named function rather than an import inside `_run_rehome`, so a test can
    replace it and drive the whole command without an editor.
    """
    from boardwise.bridge.client import BridgeClient, uri_for
    from boardwise.bridge.daemon import ensure_token, resolve_port

    return await BridgeClient.open(
        uri_for(port=resolve_port()), ensure_token(), "cli", client="boardwise-cli"
    )


def _run_rehome(args: argparse.Namespace) -> int:
    """`--rehome`: resolve the broken identities and write the sidecar."""
    try:
        library = load_parts(args.out)
    except PartError as exc:
        print(f"harvest_parts: {exc}", file=sys.stderr)
        return 2
    candidates = identity_candidates(library)
    if not candidates:
        print(
            "rehome: nothing to re-anchor — every entry carries a uuid-shaped "
            "library uuid"
        )
        return 0

    print(f"rehome: {len(candidates)} entr(ies) cannot be resolved as they stand")
    for part in candidates:
        print(f"  {part.lcsc:10} {part.key:34} libraryUuid={part.libraryUuid!r}")

    async def run() -> Rehoming:
        client = await _open_client()
        try:
            return await plan_rehoming(client, library, entries=candidates)
        finally:
            await client.close()

    try:
        outcome = asyncio.run(run())
    except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
        print(f"harvest_parts: --rehome could not reach the bridge: {exc}",
              file=sys.stderr)
        return 2

    for line in outcome.problems:
        print(f"rehome: {line}", file=sys.stderr)
    for lcsc, record in sorted(outcome.records.items()):
        print(f"  re-anchored {lcsc}: device {record.deviceUuid} "
              f"library {record.libraryUuid}")

    merged = load_corrections(args.corrections_file)
    merged.identity.update(outcome.records)
    written = save_corrections(merged, args.corrections_file)
    print(f"rehome: wrote {written} ({len(outcome.records)} new identity, "
          f"{len(merged.datasheets)} datasheet URL(s) preserved)")

    if outcome.ok:
        print("rehome: next, refresh the library with the corrected identities:")
        print(f"  {Path(__file__).name} --sources ... --verify     # writes the library")
        print(f"  {Path(__file__).name} --sources ... --check --verify")
        return 0
    print(
        f"rehome: {len(outcome.problems)} entr(ies) could not be re-anchored; they "
        "keep their identity and stay unverified",
        file=sys.stderr,
    )
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harvest_parts",
        description="Harvest a curated part library from boards (task 008b).",
    )
    parser.add_argument(
        "--sources",
        nargs="+",
        metavar="PATH",
        help="Board files (.eprj2 local project or .epro2 export). Globs allowed.",
    )
    parser.add_argument(
        "--out",
        default="blocklib/parts.json",
        help="Where to write the library (default: blocklib/parts.json).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help=(
            "Also confirm each footprint name against the live library through "
            "the bridge (lib.footprint.get). Needs a running editor; without it "
            "entries stay 'unverified'."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Re-harvest and compare against the file on disk instead of writing.",
    )
    parser.add_argument(
        "--rehome",
        action="store_true",
        help=(
            "Re-anchor the entries whose stored library uuid cannot be a library "
            "key, by C-number through lib.device.search, and write the sidecar "
            f"({CORRECTIONS_FILE}). Standalone: the library itself is refreshed "
            "by the next --verify run."
        ),
    )
    parser.add_argument(
        "--corrections-file",
        default=CORRECTIONS_FILE,
        help=(
            "The sidecar every harvest applies — identity corrections and "
            f"datasheet PDF links (default: {CORRECTIONS_FILE}). `-` applies none."
        ),
    )
    parser.add_argument("--json", action="store_true", help="Print the library as JSON.")
    return parser


#: The fields a `--verify` run is the only thing that can settle — the rule
#: itself lives in the engine (`harvest.BRIDGE_DECIDED_FIELDS`) so that the
#: checker and the harvest cannot drift apart about which ones they are.
VERIFICATION_FIELDS = BRIDGE_DECIDED_FIELDS


def _diff_keys(expected: dict, actual: dict, *, ignore: tuple[str, ...] = ()) -> list[str]:
    """Where two libraries disagree — by entry, not by summary."""
    lines: list[str] = []
    expected_parts = {p["key"]: p for p in expected.get("parts", [])}
    actual_parts = {p["key"]: p for p in actual.get("parts", [])}
    if ignore:
        expected_parts = {k: strip_bridge_decided(v) for k, v in expected_parts.items()}
        actual_parts = {k: strip_bridge_decided(v) for k, v in actual_parts.items()}
    for key in sorted(set(expected_parts) - set(actual_parts)):
        lines.append(f"  only on disk: {key}")
    for key in sorted(set(actual_parts) - set(expected_parts)):
        lines.append(f"  only harvested: {key}")
    for key in sorted(set(expected_parts) & set(actual_parts)):
        if expected_parts[key] != actual_parts[key]:
            lines.append(f"  differs: {key}")
            for field_name in sorted(set(expected_parts[key]) | set(actual_parts[key])):
                before = expected_parts[key].get(field_name)
                after = actual_parts[key].get(field_name)
                if before != after:
                    lines.append(f"      {field_name}: {before!r} -> {after!r}")
    if ignore:
        # The library-level notes are not per-entry, so they need their own pass.
        # Same rule object as the per-entry fields: one definition, in the engine.
        before = strip_bridge_decided_notes(expected.get("notes", []))
        after = strip_bridge_decided_notes(actual.get("notes", []))
        for note in before:
            if note not in after:
                lines.append(f"  library note only on disk: {note[:80]}...")
        for note in after:
            if note not in before:
                lines.append(f"  library note only harvested: {note[:80]}...")
    return lines


def _cli(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.rehome:
        # One command, one job: re-homing writes the *sidecar* only. Refreshing
        # the library from it needs the bridge twice over (once to resolve, once
        # to verify), and folding that into this mode is how a run that only
        # meant to correct two identities would silently re-curate all 85.
        if args.check or args.verify:
            parser.error(
                "--rehome writes the sidecar and nothing else; run it alone, then "
                "re-run with --verify (and optionally --check) to refresh the library"
            )
        return _run_rehome(args)

    if not args.sources:
        parser.error("--sources is required (unless --rehome is given)")
    sources = _expand(args.sources)
    if not sources:
        print("harvest_parts: no source files matched", file=sys.stderr)
        return 2

    try:
        corrections = (
            LibraryCorrections()
            if args.corrections_file == "-"
            else load_corrections(args.corrections_file)
        )
    except PartError as exc:
        print(f"harvest_parts: {exc}", file=sys.stderr)
        return 2
    if not corrections.is_empty:
        print(
            f"corrections: {len(corrections.identity)} identity, "
            f"{len(corrections.datasheets)} datasheet link(s) from "
            f"{args.corrections_file}"
        )

    verifier = None
    if args.verify:
        try:
            answers, problems = asyncio.run(
                collect_footprint_names(sources, corrections=corrections)
            )
        except Exception as exc:  # noqa: BLE001 — the CLI must not traceback
            print(f"harvest_parts: --verify could not reach the bridge: {exc}",
                  file=sys.stderr)
            return 2
        print(f"verify: the library answered about {len(answers)} device(s)")
        for line in problems:
            print(f"verify: {line}", file=sys.stderr)
        verifier = lambda device_uuid, library_uuid: answers.get(  # noqa: E731
            (device_uuid, library_uuid)
        )

    try:
        result = harvest(sources, verifier=verifier, corrections=corrections)
    except PartError as exc:
        print(f"harvest_parts: {exc}", file=sys.stderr)
        return 2

    for line in result.report:
        print(line)
    counts = reconcile_counts(result)
    if counts:
        print("per board (distinct entries): " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    payload = library_to_json(result.library)
    if args.check:
        try:
            on_disk_library = load_parts(args.out)
        except PartError as exc:
            print(f"harvest_parts: {exc}", file=sys.stderr)
            return 2
        verified = [
            p for p in on_disk_library.parts if p.footprint_name_verified is not None
        ]
        if verified and not args.verify:
            # The names those entries carry came from the live library, so a
            # plain harvest cannot reproduce them — say so instead of reporting a
            # difference nobody can act on.
            print(
                f"note: {len(verified)} entr(ies) on disk carry library "
                "verification; a harvest without the bridge cannot reproduce "
                "those names. Comparing everything else exactly — re-run with "
                "`--check --verify` for a byte-for-byte comparison."
            )
        differences = _diff_keys(
            library_to_json(on_disk_library),
            payload,
            ignore=VERIFICATION_FIELDS if verified else (),
        )
        if differences:
            print(f"{args.out} DIFFERS from a fresh harvest:")
            for line in differences:
                print(line)
            return 1
        print(f"{args.out} matches a fresh harvest — the harvest is idempotent")
        return 0

    written = save_parts(result.library, args.out)
    print(f"written: {written} ({len(result.library.parts)} entries)")
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
