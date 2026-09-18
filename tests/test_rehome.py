"""`--rehome`: identity re-anchoring, and the sidecar it writes (008b tail).

Measured on the machine 2026-09-16: two entries harvested from a **personal**
library carry the library's *name* (`"FOC"`) where the library uuid belongs, so
`lib.device.get` answers `found:false` for both, and no amount of `--verify`
helps — the chain starts from a pair the library will not accept.

The correction is therefore an identity, and it is resolved the only
deterministic way available: by **C-number**, through `lib.device.search`, which
accepts an item only on an exact, unique match. It is written to a sidecar
rather than into the library, so `blocklib/parts.json` stays a function of
sources + corrections and an offline `--check` keeps meaning something.

The stub bridge here is the point: the whole command is exercised without an
editor, and the *questions* it asks are asserted, not just the answers.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from boardwise.core.parts import (
    CORRECTIONS_KIND,
    LibraryCorrections,
    PartError,
    PartLibrary,
    corrections_from_json,
    load_corrections,
    load_parts,
    save_corrections,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "blocklib" / "sources"
PILLBOX = SOURCES / "smart_pillbox.eprj2"
#: The two entries the library cannot key, and the C-numbers they carry.
PERSONAL = {"C2861195": "ic.drv8350srtvr", "C49423996": "ic.hb04n090s"}


def _load_tool():
    """`tools/` is not a package, so the module is loaded by path."""
    name = "harvest_parts_rehome_tool"
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "harvest_parts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool()


class StubBridge:
    """A `BridgeClient` that answers `lib.device.search` from a table."""

    def __init__(self, items: dict[str, list[dict]] | None = None, *, error: str = ""):
        self.items = items or {}
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def call(self, action: str, params: dict):
        self.calls.append((action, params))
        if self.error:
            raise RuntimeError(self.error)
        keyword = str(params.get("keyword") or "")
        return {"keyword": keyword, "items": self.items.get(keyword, [])}

    async def close(self) -> None:
        return None

    def actions(self) -> list[str]:
        return [action for action, _params in self.calls]


def synthetic_library() -> PartLibrary:
    """A shelf with one resolvable entry and two personal-library ones."""
    from tests.test_parts_library import entry  # noqa: PLC0415 - shares the helper

    return PartLibrary(
        parts=[
            entry(key="res.5k1_0402", lcsc="C2906948",
                  libraryUuid="b" * 32, deviceUuid="a" * 32),
            entry(key="ic.drv8350srtvr", lcsc="C2861195",
                  libraryUuid="FOC", deviceUuid="c" * 32),
            entry(key="ic.hb04n090s", lcsc="C49423996",
                  libraryUuid="FOC", deviceUuid="d" * 32),
        ]
    )


def run(coro):
    import asyncio

    return asyncio.run(coro)


# --------------------------------------------------------------------------
# Which entries are candidates
# --------------------------------------------------------------------------


def test_the_candidates_are_the_ones_whose_identity_cannot_be_a_key():
    """A shape test, so the set is reproducible without the bridge."""
    candidates = TOOL.identity_candidates(synthetic_library())
    assert [p.lcsc for p in candidates] == ["C2861195", "C49423996"]
    # An entry that is merely *unverified* is not a candidate.
    assert all(p.libraryUuid == "FOC" for p in candidates)


def test_the_committed_library_has_been_re_anchored_and_needs_no_more():
    """The real artifact, *after* `--rehome` ran for real (2026-09-17).

    The two personal-library entries are no longer candidates: their uuids are
    the ones the bridge returned for their C-number, and the shelf is now
    reproducible from sources + sidecar. The test that used to assert they were
    still candidates documented the *pre*-rehome state; keeping it would have
    meant pinning the bug as the expectation.

    The measurement is still here, in the form that cannot go stale: a candidate
    is an entry whose identity cannot be keyed, and the committed shelf has none.
    """
    library = load_parts(ROOT / "blocklib" / "parts.json")
    assert TOOL.identity_candidates(library) == []
    for lcsc in PERSONAL:
        part = library.by_lcsc()[lcsc]
        assert part.libraryUuid != "FOC", f"{lcsc} still carries a library *name*"
        assert part.deviceUuid and len(part.deviceUuid) == 32


def test_the_candidate_scan_still_recognises_a_personal_library_entry():
    """Positive control: the scan must not go quiet now that the shelf is clean."""
    library = load_parts(ROOT / "blocklib" / "parts.json")
    lcsc = next(iter(PERSONAL))
    part = library.by_lcsc()[lcsc]
    saved = part.libraryUuid
    try:
        part.libraryUuid = "FOC"
        assert {p.lcsc for p in TOOL.identity_candidates(library)} == {lcsc}
    finally:
        part.libraryUuid = saved


# --------------------------------------------------------------------------
# Resolving them (stubbed bridge)
# --------------------------------------------------------------------------


def _hit(lcsc: str, *, device: str = "d" * 32, library: str = "1" * 32) -> dict:
    # Hex-only placeholders: a library uuid is 32 hex characters, and the whole
    # point of `looks_like_library_uuid` is that anything else is refused.
    return {"uuid": device, "supplierId": lcsc, "libraryUuid": library,
            "footprintName": "WQFN-32"}


def test_a_unique_exact_hit_re_anchors_the_identity():
    client = StubBridge({lcsc: [_hit(lcsc)] for lcsc in PERSONAL})
    library = synthetic_library()
    outcome = run(TOOL.plan_rehoming(client, library, entries=TOOL.identity_candidates(library)))
    assert outcome.ok
    assert set(outcome.records) == set(PERSONAL)
    record = outcome.records["C2861195"]
    assert record.deviceUuid == "d" * 32 and record.libraryUuid == "1" * 32
    # The note names both halves of the change: that is what makes the artifact
    # explain itself without the sidecar being read.
    assert "FOC" in record.note and "supplierId" in record.note


def test_two_hits_are_a_refusal_not_a_guess():
    client = StubBridge({"C2861195": [_hit("C2861195"), _hit("C2861195", device="e" * 32)]})
    outcome = run(TOOL.plan_rehoming(client, synthetic_library(), entries=[]))
    assert outcome.ok  # nothing asked
    outcome = run(
        TOOL.plan_rehoming(
            client, synthetic_library(), entries=TOOL.identity_candidates(synthetic_library())
        )
    )
    assert "C2861195" not in outcome.records
    assert any("exact key must be unique" in line for line in outcome.problems)
    assert any("C49423996" not in line for line in outcome.problems)


def test_an_answer_that_is_not_a_uuid_is_refused():
    """A name is not a uuid, whichever side of the exchange it arrives from."""
    client = StubBridge({"C2861195": [_hit("C2861195", library="FOC")]})
    library = synthetic_library()
    outcome = run(TOOL.plan_rehoming(client, library, entries=TOOL.identity_candidates(library)))
    assert outcome.records == {}
    assert any("not a uuid either" in line for line in outcome.problems)


def test_a_bridge_failure_is_reported_per_entry():
    client = StubBridge(error="no editor")
    library = synthetic_library()
    outcome = run(TOOL.plan_rehoming(client, library, entries=TOOL.identity_candidates(library)))
    assert outcome.records == {}
    assert len(outcome.problems) == 2
    assert all("lib.device.search failed" in line for line in outcome.problems)


def test_an_entry_without_a_c_number_is_not_asked_about():
    from tests.test_parts_library import entry

    library = PartLibrary(parts=[entry(key="part.x", lcsc="", libraryUuid="FOC")])
    client = StubBridge({})
    outcome = run(TOOL.plan_rehoming(client, library, entries=library.parts))
    assert client.calls == []
    assert any("no C-number" in line for line in outcome.problems)


# --------------------------------------------------------------------------
# The sidecar
# --------------------------------------------------------------------------


def test_the_sidecar_round_trips_and_keeps_both_sections(tmp_path):
    path = tmp_path / "corrections.json"
    from boardwise.core.parts import DatasheetOverride, IdentityOverride

    corrections = LibraryCorrections(
        identity={
            "C2861195": IdentityOverride("C2861195", "a" * 32, "b" * 32, "re-anchored"),
        },
        datasheets={
            "C2977777": DatasheetOverride("C2977777", "https://example.invalid/x.pdf", "read"),
        },
    )
    save_corrections(corrections, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["kind"] == CORRECTIONS_KIND
    # Sorted by C-number, so the file is stable whatever order it was built in.
    assert [item["lcsc"] for item in raw["identity"]] == ["C2861195"]
    reloaded = load_corrections(path)
    assert reloaded.identity_for("c2861195") is not None  # lookup is case-insensitive
    assert reloaded.datasheet_for("C2977777").pdfUrl.startswith("https://")


def test_a_missing_sidecar_means_no_corrections(tmp_path):
    corrections = load_corrections(tmp_path / "absent.json")
    assert corrections.is_empty
    assert corrections.identity_for("C1") is None


def test_the_sidecar_schema_fails_closed():
    good = {"kind": CORRECTIONS_KIND, "identity": [], "datasheets": []}
    assert corrections_from_json(good).is_empty
    with pytest.raises(PartError, match="kind"):
        corrections_from_json({**good, "kind": "something-else"})
    with pytest.raises(PartError, match="unknown key"):
        corrections_from_json({**good, "extra": 1})
    # Half an identity corrects nothing, and a non-uuid replacement is the same
    # mistake the file exists to fix.
    for record in (
        {"lcsc": "C1", "deviceUuid": "a" * 32},
        {"lcsc": "C1", "deviceUuid": "a" * 32, "libraryUuid": "FOC"},
    ):
        with pytest.raises(PartError):
            corrections_from_json({**good, "identity": [record]})
    with pytest.raises(PartError, match="required"):
        corrections_from_json({**good, "datasheets": [{"lcsc": "C1"}]})
    with pytest.raises(PartError, match="appears twice"):
        corrections_from_json(
            {**good, "identity": [
                {"lcsc": "C1", "deviceUuid": "a" * 32, "libraryUuid": "b" * 32},
                {"lcsc": "c1", "deviceUuid": "a" * 32, "libraryUuid": "b" * 32},
            ]}
        )


# --------------------------------------------------------------------------
# The harvest applies them
# --------------------------------------------------------------------------


def _pillbox_ch340_lcsc() -> str:
    from boardwise.engines.harvest import placed_devices
    from boardwise.parsers.board_source import load_board_source

    project = load_board_source(PILLBOX)
    for device in placed_devices(project).devices.values():
        if (device.attributes.get("Supplier Part") or "").strip() == "C2977777":
            return "C2977777"
    raise AssertionError("the pillbox no longer places a CH340N")


def test_the_harvest_applies_an_identity_correction_and_says_so():
    from boardwise.core.parts import IdentityOverride
    from boardwise.engines.harvest import harvest_board

    corrections = LibraryCorrections(
        identity={
            "C2977777": IdentityOverride("C2977777", "f" * 32, "0" * 32, "re-anchored by test"),
        }
    )
    entries, _ = harvest_board(PILLBOX, corrections=corrections)
    ch340 = next(e for e in entries if e.lcsc == _pillbox_ch340_lcsc())
    assert (ch340.deviceUuid, ch340.libraryUuid) == ("f" * 32, "0" * 32)
    assert "re-anchored by test" in ch340.notes


def test_the_verifier_is_asked_about_the_corrected_pair():
    """The whole point: the bridge must be asked about the identity the entry
    will carry, not the one the board wrote."""
    from boardwise.core.parts import IdentityOverride
    from boardwise.engines.harvest import devices_to_verify, harvest_board

    corrections = LibraryCorrections(
        identity={
            "C2977777": IdentityOverride("C2977777", "f" * 32, "0" * 32, "re-anchored"),
        }
    )
    asked: list[tuple[str, str]] = []

    def verifier(device_uuid: str, library_uuid: str) -> str:
        asked.append((device_uuid, library_uuid))
        return ""

    harvest_board(PILLBOX, verifier=verifier, corrections=corrections)
    assert ("f" * 32, "0" * 32) in asked
    # The board's own pair is never offered: that is the identity the library
    # rejects, and asking about it answers `found:false` for the one entry the
    # correction exists for.
    from boardwise.engines.harvest import devices_to_verify

    original = devices_to_verify([PILLBOX])
    corrected_pair = {"f" * 32, "0" * 32}
    for pair in original:
        assert not (set(pair) & corrected_pair), pair

    wanted = devices_to_verify([PILLBOX], corrections=corrections)
    assert ("f" * 32, "0" * 32) in wanted
    assert ("f" * 32, "0" * 32) not in original


def test_the_harvest_applies_a_datasheet_link_from_the_sidecar():
    """An offline harvest can reproduce a link that only the network could fetch.

    The URL is applied; the sidecar's prose is not copied onto the entry, because
    the tool that fills links edits the library in place while the harvest
    rebuilds it — two writers, and a wording one of them adds is a difference the
    other cannot reproduce.
    """
    from boardwise.core.parts import DatasheetOverride
    from boardwise.engines.harvest import harvest_board

    corrections = LibraryCorrections(
        datasheets={
            "C2977777": DatasheetOverride(
                "C2977777", "https://example.invalid/ch340.pdf", "read from the product page"
            )
        }
    )
    entries, _ = harvest_board(PILLBOX, corrections=corrections)
    ch340 = next(e for e in entries if e.lcsc == "C2977777")
    assert ch340.datasheetPdfUrl == "https://example.invalid/ch340.pdf"
    assert "read from the product page" not in ch340.notes


def test_a_library_uuid_that_is_not_a_uuid_never_becomes_verified():
    """The schema refuses the claim, so `--rehome` is the only way forward."""
    from boardwise.core.parts import PartEntry, PartError
    from boardwise.core.parts import entry_from_json

    offender = {
        "key": "ic.example", "lcsc": "C1", "mpn": "X", "deviceUuid": "d" * 32,
        "libraryUuid": "FOC", "footprint_name_verified": True,
    }
    with pytest.raises(PartError) as caught:
        entry_from_json(offender, where="example")
    assert "footprint_name_verified is true" in str(caught.value)
    assert "not a library uuid" in str(caught.value)


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def _stub_open(monkeypatch, client: StubBridge) -> None:
    async def open_client():
        return client

    monkeypatch.setattr(TOOL, "_open_client", open_client)


def test_the_command_writes_only_the_sidecar(monkeypatch, tmp_path, capsys):
    library_path = tmp_path / "parts.json"
    save_library_like_committed(library_path)
    sidecar = tmp_path / "corrections.json"
    _stub_open(monkeypatch, StubBridge({lcsc: [_hit(lcsc)] for lcsc in PERSONAL}))

    code = TOOL._cli([
        "--rehome", "--out", str(library_path), "--corrections-file", str(sidecar)
    ])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "re-anchored C2861195" in out and "re-anchored C49423996" in out
    written = load_corrections(sidecar)
    assert set(written.identity) == set(PERSONAL)
    # The library itself is untouched: refreshing it is the next command's job.
    assert load_parts(library_path).by_lcsc()["C2861195"].libraryUuid == "FOC"


def test_the_command_reports_a_partial_result_and_says_which(monkeypatch, tmp_path, capsys):
    library_path = tmp_path / "parts.json"
    save_library_like_committed(library_path)
    sidecar = tmp_path / "corrections.json"
    _stub_open(monkeypatch, StubBridge({"C2861195": [_hit("C2861195")]}))

    code = TOOL._cli([
        "--rehome", "--out", str(library_path), "--corrections-file", str(sidecar)
    ])
    captured = capsys.readouterr()
    assert code == 1
    assert "could not be re-anchored" in captured.err
    # What did resolve is still recorded — a partial answer is progress, and it
    # is recorded as exactly that.
    written = load_corrections(sidecar)
    assert set(written.identity) == {"C2861195"}


def test_the_command_preserves_the_other_section_of_the_sidecar(
    monkeypatch, tmp_path, capsys
):
    library_path = tmp_path / "parts.json"
    save_library_like_committed(library_path)
    sidecar = tmp_path / "corrections.json"
    from boardwise.core.parts import DatasheetOverride

    save_corrections(
        LibraryCorrections(
            datasheets={
                "C2977777": DatasheetOverride(
                    "C2977777", "https://example.invalid/a.pdf", "read"
                )
            }
        ),
        sidecar,
    )
    _stub_open(monkeypatch, StubBridge({lcsc: [_hit(lcsc)] for lcsc in PERSONAL}))

    assert TOOL._cli([
        "--rehome", "--out", str(library_path), "--corrections-file", str(sidecar)
    ]) == 0
    written = load_corrections(sidecar)
    assert set(written.identity) == set(PERSONAL)
    assert written.datasheet_for("C2977777") is not None, "re-homing dropped the links"


def test_the_command_says_so_when_there_is_nothing_to_do(monkeypatch, tmp_path, capsys):
    library_path = tmp_path / "parts.json"
    save_library_like_committed(library_path, healthy=True)
    _stub_open(monkeypatch, StubBridge({}))
    code = TOOL._cli([
        "--rehome", "--out", str(library_path), "--corrections-file", str(tmp_path / "c.json")
    ])
    assert code == 0
    assert "nothing to re-anchor" in capsys.readouterr().out


def test_the_command_refuses_to_do_two_jobs_at_once(tmp_path, capsys):
    """`--rehome` writes the sidecar; refreshing the library is a separate run,
    which is what keeps a two-entry correction from re-curating all 85."""
    with pytest.raises(SystemExit) as info:
        TOOL._cli(["--rehome", "--verify", "--out", str(tmp_path / "parts.json")])
    assert info.value.code == 2
    assert "run it alone" in capsys.readouterr().err


def test_sources_are_still_required_without_rehome(capsys):
    with pytest.raises(SystemExit) as info:
        TOOL._cli([])
    assert info.value.code == 2
    assert "--sources is required" in capsys.readouterr().err


def save_library_like_committed(path: Path, *, healthy: bool = False) -> None:
    """A library file with the two measured candidates (or none)."""
    from boardwise.core.parts import save_parts

    library = synthetic_library() if not healthy else synthetic_library()
    if healthy:
        for part in library.parts:
            part.libraryUuid = "b" * 32
    save_parts(library, path)
