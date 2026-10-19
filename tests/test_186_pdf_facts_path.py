"""186: the PDF → facts → gate path, the name fallback, and the hygiene word gate.

Four pieces, one flow (岳 2026-10-15 的 AI 使用者体验反馈 P1–P4 + 清洗批暴露的防线缺口):

* **A (P4)** — `parts add --facts/--fact/--verified`: the first-class entry for
  a human's facts. The gate that refuses to be closed by feeding a PDF is 039's
  design and stays; what was missing was a **route to close it**;
* **B (P2)** — the identity chain gains the **device name** as its last step
  (MPN → C-number → name, each exact), for the shelf entry *and* for the local
  PDF in the datasheet folder. A board carries parts whose only identity is the
  name (measured: 26 of 98 on `.tmp_bug98b/<现场板>.epro2` have no MPN and no
  supplier), and a datasheet read for exactly such a part could not be attached
  to it;
* **C (P1 + 2.3)** — the report says which action clears the gate, splits 未审
  器件 into 「工具读不懂」 / 「真缺资料」, and `parts fetch` tells the reader what to
  do when the extractor proposes nothing;
* **D** — `tools/check_repo_hygiene.py` gains a second gate reading a **local,
  gitignored** word list; three states (hit / clean / no list). 187B added the
  baseline, the encoding sniff and the single pass, and moved every case here
  onto a **temporary** list: the real one is a fact about a machine, so the
  repository-side assertion is the container gate only.

The fixtures are synthetic and use **neutral codes** (R4b): no real project name
or part number is typed into this file. The one fixture board it reads is a
tracked synthetic/DIY fixture, and the end-to-end test takes the part's name
from that board's own record rather than spelling it here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import (
    FACTS_KEYS,
    IDENTITY_LCSC,
    IDENTITY_MPN,
    IDENTITY_NAME,
    PartLibrary,
    load_parts,
    resolve_facts,
    save_parts,
)
from boardwise.engines.checkup import (
    REASON_CLASS_MISSING_MATERIAL,
    REASON_CLASS_UNDECODABLE,
    UNKNOWN_REASON_UNDECODABLE,
    UNREVIEWED_CLEARING_NOTE,
    render_report_markdown,
    render_review_summary,
    unreviewed_classes,
    unreviewed_counts_by_class,
    unreviewed_counts_by_reason,
    unreviewed_parts,
)

ROOT = Path(__file__).resolve().parents[1]
#: A tracked fixture with a part whose only identity is its device name — a
#: U-prefix IC with an empty MPN and an empty supplier. Read, never written.
NAME_ONLY_BOARD = ROOT / "tests" / "fixtures" / "llc_board.epro2"
SHELF = ROOT / "blocklib" / "parts.json"

#: The neutral stand-in the commands are exercised with. The end-to-end test
#: takes its name from the board's own record; this one is for the unit cases.
NEUTRAL_NAME = "ACME-PWR-1000"
NEUTRAL_PROV = "file:acme-pwr-1000.pdf p.3"


def _facts(*, provenance: str = NEUTRAL_PROV) -> dict:
    return {
        "nc_pins": {"pins": ["2"], "provenance": provenance},
        "supply_pins": [
            {"pins": ["1"], "name": "VIN", "v_operating": [2.2, 5.5], "provenance": provenance}
        ],
    }


def _facts_file(tmp_path: Path, facts: dict | None = None) -> Path:
    path = tmp_path / "facts.json"
    path.write_text(
        json.dumps(facts if facts is not None else _facts(), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _shelf(tmp_path: Path, *entries) -> Path:
    path = tmp_path / "parts.json"
    save_parts(PartLibrary(parts=list(entries)), path)
    return path


def _entry(key: str, *, mpn: str = "", lcsc: str = "C1", category: str = ""):
    """A shelf entry a **live** shelf accepts: the schema's uuid pair included.

    039's rule, met here rather than worked around: an entry a rule acts on must
    be placeable, so it carries `deviceUuid`+`libraryUuid`. A candidate
    (the `candidate` tier) is the one shape allowed to omit them.
    """
    from boardwise.core.parts import PartEntry

    return PartEntry(
        key=key,
        mpn=mpn,
        lcsc=lcsc,
        category=category,
        deviceUuid="0123456789abcdef0123456789abcdef",
        libraryUuid="fedcba9876543210fedcba9876543210",
    )


def _verified_flags(extra: list[str] | None = None) -> list[str]:
    """`--verified` plus the uuid pair the **schema** demands of a live entry.

    Not this batch's rule (039's): an entry a rule acts on must be placeable, so
    it carries `deviceUuid`+`libraryUuid`. The flags are the offline spelling of
    what `parts select --resolve` gets from the bridge.
    """
    return [
        "--verified",
        "--device-uuid", "0123456789abcdef0123456789abcdef",
        "--library-uuid", "fedcba9876543210fedcba9876543210",
        *(extra or []),
    ]


# --------------------------------------------------------------------------
# A — `parts add --facts/--fact/--verified`
# --------------------------------------------------------------------------


def test_a_new_entry_can_be_written_with_verified_facts(capsys, tmp_path):
    """The P4 entry: identity + facts + the explicit declaration, in one write."""
    shelf = _shelf(tmp_path)
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(_facts_file(tmp_path)), "--category", "ic.ldo",
        "--library", str(shelf), *_verified_flags(),
    ])
    out = capsys.readouterr().out
    assert code == 0
    entry = load_parts(shelf).get("candidate.acme_pwr_1000")
    assert entry is not None
    assert entry.facts_verified is True
    assert entry.facts == _facts()
    assert entry.category == "ic.ldo"
    # A verified entry does **not** write the key: `true` is the schema's default
    # and a claim nobody typed would rewrite every line of the shelf (039).
    raw = json.loads(shelf.read_text(encoding="utf-8"))
    written = raw["parts"][0]
    # 522: neither key is written for `verified` — the tier is the schema's
    # default and a claim nobody typed would rewrite every line of the shelf
    # (039's ruling, carried to the three-value field).
    assert "facts_verified" not in written
    assert "facts_trust" not in written
    assert written["facts"] == _facts()
    assert "gate: facts_trust = verified" in out


def test_verified_without_facts_is_refused(capsys, tmp_path):
    """`--verified` means "these facts are checked" — with no facts it is a lie."""
    shelf = _shelf(tmp_path)
    before = shelf.read_bytes()
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--library", str(shelf), *_verified_flags(),
    ])
    err = capsys.readouterr().err
    assert code == 2
    assert "--verified 要配 facts" in err
    assert shelf.read_bytes() == before


def test_verified_without_the_uuid_pair_says_where_the_ids_come_from(capsys, tmp_path):
    """039's schema rule, surfaced with the route to satisfy it."""
    shelf = _shelf(tmp_path)
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(_facts_file(tmp_path)), "--library", str(shelf), "--verified",
    ])
    err = capsys.readouterr().err
    assert code == 2
    assert "deviceUuid + libraryUuid" in err
    assert "parts select" in err and "--device-uuid" in err


def test_facts_without_verified_stay_a_candidate(capsys, tmp_path):
    """No `--verified` ⇒ the facts are written, reviewable, and drive nothing."""
    shelf = _shelf(tmp_path)
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(_facts_file(tmp_path)), "--library", str(shelf),
    ])
    out = capsys.readouterr().out
    assert code == 0
    entry = load_parts(shelf).get("candidate.acme_pwr_1000")
    assert entry.facts_verified is False
    assert entry.facts is None, "a candidate's claim is held back from the rules"
    assert entry.candidate_facts == _facts()
    raw = json.loads(shelf.read_text(encoding="utf-8"))["parts"][0]
    assert raw["facts_trust"] == "candidate" and raw["facts"] == _facts()
    assert "gate: facts_trust = candidate" in out


@pytest.mark.parametrize(
    "payload",
    [
        # A fact whose provenance cites no page: the 011b gate, unchanged.
        {"nc_pins": {"pins": ["2"], "provenance": "the datasheet says so"}},
        # A key the vocabulary does not have.
        {"not_a_fact": {"pins": ["2"], "provenance": NEUTRAL_PROV}},
        # A shape the loader refuses for a known key.
        {"nc_pins": {"pins": [], "provenance": NEUTRAL_PROV}},
    ],
    ids=["no-page", "unknown-kind", "empty-pins"],
)
def test_facts_that_the_validator_refuses_never_land(capsys, tmp_path, payload):
    """The existing validate pipeline is the gate — `add` does not soften it."""
    shelf = _shelf(tmp_path)
    before = shelf.read_bytes()
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(_facts_file(tmp_path, payload)), "--library", str(shelf),
        *_verified_flags(),
    ])
    err = capsys.readouterr().err
    assert code == 2
    assert shelf.read_bytes() == before, "a refused entry leaves no bytes behind"
    assert "boardwise parts add" in err


def test_the_fetch_sidecar_shape_is_accepted_as_it_stands(capsys, tmp_path):
    """`parts fetch`'s `<stem>.candidate.json` is `{"label","url","facts"}` — one
    handoff, so what a fetch proposed can be handed straight back in."""
    shelf = _shelf(tmp_path)
    sidecar = tmp_path / "candidate.json"
    sidecar.write_text(
        json.dumps({"label": NEUTRAL_NAME, "url": "file:x.pdf", "facts": _facts()}),
        encoding="utf-8",
    )
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(sidecar), "--library", str(shelf), *_verified_flags(),
    ])
    capsys.readouterr()
    assert code == 0
    assert load_parts(shelf).get("candidate.acme_pwr_1000").facts == _facts()


def test_repeated_fact_flags_compose_and_a_duplicate_key_is_refused(capsys, tmp_path):
    """`--fact KEY=JSON`, repeatable; JSON because every fact kind is a record."""
    shelf = _shelf(tmp_path)
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--fact", f'nc_pins={json.dumps({"pins": ["2"], "provenance": NEUTRAL_PROV})}',
        "--fact", f'led={json.dumps({"vf_v": [1.8, 2.2], "if_max_ma": 20, "provenance": NEUTRAL_PROV})}',
        "--library", str(shelf), *_verified_flags(),
    ])
    capsys.readouterr()
    assert code == 0
    entry = load_parts(shelf).get("candidate.acme_pwr_1000")
    assert sorted(entry.facts) == ["led", "nc_pins"]

    dup = cli.main([
        "parts", "add", "OTHER-1", "--lcsc", "C9900000002",
        "--fact", f'nc_pins={json.dumps({"pins": ["2"], "provenance": NEUTRAL_PROV})}',
        "--fact", f'nc_pins={json.dumps({"pins": ["3"], "provenance": NEUTRAL_PROV})}',
        "--library", str(shelf),
    ])
    assert dup == 2
    assert "给了两次" in capsys.readouterr().err


def test_a_fact_key_outside_the_vocabulary_lists_the_vocabulary(capsys, tmp_path):
    shelf = _shelf(tmp_path)
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--fact", '{"not": "a key=1"}', "--library", str(shelf),
    ])
    err = capsys.readouterr().err
    assert code == 2
    for key in FACTS_KEYS:
        assert key in err


def test_a_fact_value_that_is_not_json_is_refused(capsys, tmp_path):
    shelf = _shelf(tmp_path)
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--fact", "nc_pins=2,3", "--library", str(shelf),
    ])
    assert code == 2
    assert "必须是 JSON" in capsys.readouterr().err


def test_facts_fill_the_candidate_that_is_already_on_the_shelf(capsys, tmp_path):
    """The step that was missing: the candidate `parts fetch` left behind gets
    its facts, and no earlier byte of the file moves."""
    shelf = _shelf(tmp_path)
    assert cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--library", str(shelf), "--key", "ic.acme_pwr_1000",
        "--device-uuid", "0123456789abcdef0123456789abcdef",
        "--library-uuid", "fedcba9876543210fedcba9876543210",
    ]) == 0
    capsys.readouterr()
    before = shelf.read_bytes()

    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(_facts_file(tmp_path)), "--category", "ic.ldo",
        "--library", str(shelf), *_verified_flags(),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "entry updated: ic.acme_pwr_1000" in out
    entry = load_parts(shelf).get("ic.acme_pwr_1000")
    assert entry.facts_verified is True and entry.facts == _facts()
    assert entry.category == "ic.ldo"
    # One entry, not two: the update rewrote the record in place.
    raw = json.loads(shelf.read_text(encoding="utf-8"))
    assert [item["key"] for item in raw["parts"]] == ["ic.acme_pwr_1000"]
    assert len(raw["parts"]) == 1
    assert before != shelf.read_bytes()


def test_a_verified_entry_is_never_overwritten_without_force(capsys, tmp_path):
    """An unreviewed claim does not replace something a human vouched for —
    the same guard `parts fetch` applies, for the same reason."""
    shelf = _shelf(tmp_path)
    assert cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(_facts_file(tmp_path)), "--library", str(shelf),
        *_verified_flags(),
    ]) == 0
    capsys.readouterr()
    before = shelf.read_bytes()
    other = _facts_file(tmp_path, {"nc_pins": {"pins": ["9"], "provenance": NEUTRAL_PROV}})
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(other), "--library", str(shelf), *_verified_flags(),
    ])
    err = capsys.readouterr().err
    assert code == 2 and "已经有核验过的 facts" in err and "--force" in err
    assert shelf.read_bytes() == before

    forced = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001",
        "--facts", str(other), "--library", str(shelf), "--force", *_verified_flags(),
    ])
    capsys.readouterr()
    assert forced == 0
    assert load_parts(shelf).get("candidate.acme_pwr_1000").facts == {
        "nc_pins": {"pins": ["9"], "provenance": NEUTRAL_PROV}
    }


def test_filling_facts_does_not_rewrite_identity(capsys, tmp_path):
    """Writing facts is not an identity edit: a C-number that differs from the
    entry's is refused rather than silently applied."""
    shelf = _shelf(tmp_path)
    assert cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001", "--library", str(shelf),
    ]) == 0
    capsys.readouterr()
    code = cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000002",
        "--facts", str(_facts_file(tmp_path)), "--library", str(shelf),
    ])
    err = capsys.readouterr().err
    assert code == 2
    assert "改身份不是写 facts 的事" in err
    assert load_parts(shelf).get("candidate.acme_pwr_1000").lcsc == "C9900000001"


def test_add_without_facts_still_refuses_a_duplicate_identity(capsys, tmp_path):
    """039's guard, unchanged: no facts ⇒ the old refusal and the old hint."""
    shelf = _shelf(tmp_path)
    assert cli.main([
        "parts", "add", NEUTRAL_NAME, "--lcsc", "C9900000001", "--library", str(shelf),
    ]) == 0
    capsys.readouterr()
    before = shelf.read_bytes()
    code = cli.main([
        "parts", "add", NEUTRAL_NAME.lower(), "--lcsc", "C9900000009",
        "--library", str(shelf),
    ])
    err = capsys.readouterr().err
    assert code == 2
    assert "already on the shelf" in err and "parts show" in err
    assert shelf.read_bytes() == before


# ---------------------------------------------------------------- the chain


def test_the_identity_chain_answers_in_evidence_order(tmp_path):
    """MPN → C-number → device name, and the answer says which one matched."""
    from boardwise.core.parts import PartEntry

    library = PartLibrary(parts=[
        PartEntry(key="ic.by_mpn", mpn="MPN-1", lcsc="C1"),
        PartEntry(key="ic.by_lcsc", mpn="OTHER", lcsc="C2"),
        PartEntry(key="ic.by_name", mpn=NEUTRAL_NAME, lcsc="C3"),
    ])
    assert resolve_facts(library, mpn="MPN-1") == (library.parts[0], IDENTITY_MPN)
    assert resolve_facts(library, lcsc="C2") == (library.parts[1], IDENTITY_LCSC)
    assert resolve_facts(library, name=NEUTRAL_NAME) == (library.parts[2], IDENTITY_NAME)
    # The MPN step wins when both could answer, and an empty identity is no
    # identity at all.
    assert resolve_facts(library, mpn="MPN-1", name="OTHER")[1] == IDENTITY_MPN
    assert resolve_facts(library, mpn="", lcsc="", name="") == (None, "")


def test_the_name_step_is_exact_and_never_fuzzy(tmp_path):
    """#202's lesson, one level up: "close enough" identity is how a rule cites
    the wrong datasheet. A name differing in case is a miss."""
    from boardwise.core.parts import PartEntry

    library = PartLibrary(parts=[PartEntry(key="ic.by_name", mpn=NEUTRAL_NAME, lcsc="C3")])
    assert resolve_facts(library, name=NEUTRAL_NAME.lower()) == (None, "")
    assert resolve_facts(library, name=NEUTRAL_NAME)[0] is not None


def test_resolve_component_facts_reads_the_boards_own_fields(tmp_path):
    """One place spells the field names, so no reader can forget the name step."""
    from boardwise.core.parts import PartEntry, resolve_component_facts

    library = PartLibrary(parts=[PartEntry(key="ic.by_name", mpn=NEUTRAL_NAME, lcsc="C3")])
    comp = Component(
        uid="u1", designator="U1", props={"device_name": NEUTRAL_NAME},
        pins=[Pin("1", "VIN", "+5V")],
    )
    entry, matched = resolve_component_facts(library, comp)
    assert entry is not None and matched == IDENTITY_NAME


def test_the_rules_lookup_walks_the_same_chain_as_the_gate():
    """The gate and the rules must not disagree about the same shelf.

    Both sides resolve a board part through `resolve_facts`, so a part whose
    entry was found by name is judged *and* judged from those facts — the
    report cannot say "this part is fine" while a rule says "no facts for it".

    187B (task 186-H1) widened this from `FactsRule` alone to the **four PCB
    rules that still read the shelf by MPN/C-number only**: they were the
    counter-example to the paragraph above, skipping exactly the name-only parts
    the gate had already called reviewable. Same ruler, four more readers — a
    name-only part must be visible to each of them.
    """
    from boardwise.core.parts import PartEntry
    from boardwise.rules.facts import FactsRule

    library = PartLibrary(parts=[
        PartEntry(key="ic.by_name", mpn=NEUTRAL_NAME, lcsc="C3"),
    ])
    rule = FactsRule(library)
    named = Component(
        uid="u1", designator="U1", props={"device_name": NEUTRAL_NAME},
        pins=[Pin("1", "VIN", "+5V")],
    )
    assert rule.entry_for(named).key == "ic.by_name"
    near_miss = Component(
        uid="u2", designator="U2", props={"device_name": NEUTRAL_NAME.lower()},
        pins=[Pin("1", "VIN", "+5V")],
    )
    assert rule.entry_for(near_miss) is None

    # The four rules 187B migrated, each asked the question its own gate asks.
    # Three entries, three names, three categories: the parts carry no MPN and no
    # C-number, so only the device-name step can find any of them — and one
    # name-only part is visible to the rule that cares about *its* category.
    from boardwise.rules.pcb.focground import _looks_like_resistor
    from boardwise.rules.pcb.mcureset import _read_mcus as _reset_readings
    from boardwise.rules.pcb.mcusupply import _read_mcus as _supply_readings
    from boardwise.rules.pcb.regulator import _regulator_readings

    shelf = PartLibrary(parts=[
        _category_entry("ic.mcu.by_name", "ACME-MCU-1", "ic.mcu"),
        _category_entry("ic.ldo.by_name", "ACME-LDO-1", "ic.ldo"),
        _category_entry("res.by_name", "ACME-RES-1", "resistor"),
    ])

    def _board(designator: str, device_name: str) -> DesignModel:
        component = Component(
            uid=designator.lower(), designator=designator, lcsc_part="", mpn="",
            props={"device_name": device_name},
            pins=[Pin("1", "VDD", "+3V3"), Pin("2", "NRST", "NRST")],
        )
        return DesignModel(components={designator: component}, nets={})

    mcu = _board("U3", "ACME-MCU-1")
    assert len(_supply_readings(mcu, shelf)[0]) == 1, "pcb-mcu-supply-groups 没看见它"
    assert len(_reset_readings(mcu, shelf)[0]) == 1, "pcb-mcu-reset-boot 没看见它"
    ldo = _board("U5", "ACME-LDO-1")
    assert len(_regulator_readings(ldo, shelf)[0]) == 1, "pcb-regulator-cap-distance 没看见它"
    resistor = _board("U7", "ACME-RES-1")
    assert _looks_like_resistor("U7", "", resistor, shelf)[0] is True, "R1b 没看见它"

    # …and the same four say nothing about a near miss, exactly as the gate does:
    # the widened chain is still an **exact** chain, not a looser one.
    fuzzy = _board("U9", "acme-mcu-1")
    assert _supply_readings(fuzzy, shelf)[0] == []
    assert _reset_readings(fuzzy, shelf)[0] == []
    assert _regulator_readings(fuzzy, shelf)[0] == []
    assert _looks_like_resistor("U9", "", fuzzy, shelf)[0] is False


def _category_entry(key: str, mpn: str, category: str):
    """A shelf entry with a category, for the four migrated rules."""
    from boardwise.core.parts import PartEntry

    return PartEntry(key=key, mpn=mpn, lcsc="", category=category)


# --------------------------------------------------------------------------
# B — the local datasheet channel finds a PDF filed under the device name
# --------------------------------------------------------------------------


def _name_only_model(model_name: str = NEUTRAL_NAME) -> DesignModel:
    model = DesignModel()
    model.components["U1"] = Component(
        uid="u1", designator="U1", props={"device_name": model_name},
        pins=[Pin("1", "VIN", "+5V")],
    )
    model.nets = {"+5V": Net("+5V", [("U1", "1")])}
    return model


def test_the_engineer_channel_matches_a_pdf_filed_under_the_device_name(tmp_path):
    """P2: `Name=…` and a PDF of the same name did not meet. Two spellings are
    normalised (hyphens/underscores/case), and the hit is labelled as the weaker
    evidence it is."""
    folder = tmp_path / "ds"
    folder.mkdir()
    (folder / "ACME-PWR-1000_v1.2.pdf").write_bytes(b"%PDF-1.4 fake")
    rows = {
        row["designator"]: row
        for row in unreviewed_parts(
            _name_only_model(), library=PartLibrary(parts=[]), datasheet_dir=folder
        )
    }
    engineer = rows["U1"]["channels"]["engineer"]
    assert engineer["ok"] is True
    assert engineer["matchedBy"] == IDENTITY_NAME
    assert "按器件名匹配" in engineer["detail"]
    assert engineer["path"].endswith(".pdf")


def test_the_engineer_channel_prefers_the_mpn_when_both_would_match(tmp_path):
    """Evidence order is the report's claim: matching under the MPN is not
    reported as matching under the name."""
    from boardwise.core.parts import PartEntry

    folder = tmp_path / "ds"
    folder.mkdir()
    (folder / "MPN-1.pdf").write_bytes(b"%PDF-1.4 fake")
    model = _name_only_model()
    model.components["U1"].mpn = "MPN-1"
    library = PartLibrary(parts=[PartEntry(key="ic.by_mpn", mpn="MPN-1", lcsc="C1")])
    rows = {
        row["designator"]: row
        for row in unreviewed_parts(model, library=library, datasheet_dir=folder)
    }
    assert rows["U1"]["channels"]["engineer"]["matchedBy"] == IDENTITY_MPN
    assert "按器件名匹配" not in rows["U1"]["channels"]["engineer"]["detail"]


# --------------------------------------------------------------------------
# A + B + C end to end: a Name-only part on a real fixture board, offline
# --------------------------------------------------------------------------


def _name_only_fixture() -> tuple[Path, str, str]:
    """``(board, designator, device name)`` from the tracked fixture, not typed here.

    R4b: the test knows *which* part it is by asking the board, so no real
    project or part name enters this file.
    """
    from boardwise.core.parts import is_ic_designator

    model, _board = cli._load_model(NAME_ONLY_BOARD, view="schematic")
    for designator, component in sorted(model.components.items()):
        if not is_ic_designator(designator):
            continue
        name = str(component.props.get("device_name") or "").strip()
        if name and not (component.mpn or "").strip() and not (component.lcsc_part or "").strip():
            return NAME_ONLY_BOARD, designator, name
    pytest.skip("the fixture board no longer holds a name-only IC")


def _checkup(board: Path, shelf: Path, out: Path) -> dict:
    code = cli.main([
        "checkup", "--file", str(board), "--out", str(out), "--library", str(shelf),
    ])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert code in (0, 1, 3), f"checkup exited {code}"
    return report


def test_end_to_end_a_name_only_part_leaves_the_gate_once_its_facts_are_verified(
    capsys, tmp_path, monkeypatch
):
    """The scenario the batch exists for, run through the real CLI:

    board with a Name-only IC → the part is on the 未审 list (真缺资料) → facts
    written onto the shelf for that name with `--verified` → checkup again → the
    part is gone from `needs_datasheet`, and it was the *declaration* that did
    it (the candidate run just before it changes nothing).
    """
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, designator, name = _name_only_fixture()
    shelf = _shelf(tmp_path)

    before = _checkup(board, shelf, tmp_path / "out-before")
    seeds = {row["part"] for row in before["needs_datasheet"]}
    listed = {row["designator"] for row in before["unreviewed_parts"]}
    assert designator in listed and designator in seeds
    assert before["summary"]["mayClaimPassed"] is False
    row = next(r for r in before["unreviewed_parts"] if r["designator"] == designator)
    assert REASON_CLASS_MISSING_MATERIAL in unreviewed_classes(row)

    # ① facts, but no declaration: the gate stays shut (feeding a PDF).
    assert cli.main([
        "parts", "add", name, "--lcsc", "C9900000186", "--facts", str(_facts_file(tmp_path)),
        "--category", "ic.ldo", "--library", str(shelf),
    ]) == 0
    capsys.readouterr()
    middle = _checkup(board, shelf, tmp_path / "out-middle")
    assert designator in {r["designator"] for r in middle["unreviewed_parts"]}

    # ② the same facts, declared verified: the gate opens for that part.
    assert cli.main([
        "parts", "add", name, "--lcsc", "C9900000186", "--facts", str(_facts_file(tmp_path)),
        "--category", "ic.ldo", "--library", str(shelf), *_verified_flags(),
    ]) == 0
    capsys.readouterr()
    after = _checkup(board, shelf, tmp_path / "out-after")
    assert designator not in {r["designator"] for r in after["unreviewed_parts"]}
    assert designator not in {row["part"] for row in after["needs_datasheet"]}
    # The rest of the list is untouched: this closed one part, not the list.
    assert {r["designator"] for r in after["unreviewed_parts"]} == listed - {designator}
    assert after["summary"]["unreviewedParts"] == before["summary"]["unreviewedParts"] - 1


def test_end_to_end_the_entry_is_found_by_name_and_the_report_says_so(capsys, tmp_path, monkeypatch):
    """Why the part left the gate: the review resolved the entry by the device
    name — the weaker claim — and `parts missing` reports the same resolution."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, designator, name = _name_only_fixture()
    shelf = _shelf(tmp_path)
    assert cli.main([
        "parts", "add", name, "--lcsc", "C9900000186",
        "--facts", str(_facts_file(tmp_path)), "--library", str(shelf),
        *_verified_flags(),
    ]) == 0
    capsys.readouterr()

    json_out = tmp_path / "missing.json"
    assert cli.main([
        "parts", "missing", "--file", str(board), "--library", str(shelf),
        "--json", str(json_out),
    ]) == 0
    out = capsys.readouterr().out
    report = json.loads(json_out.read_text(encoding="utf-8"))
    row = next(r for r in report["parts"] if r["designator"] == designator)
    assert row["matchedBy"] == IDENTITY_NAME
    assert row["onShelf"] is True and row["unverified"] is False
    assert row["missing"] == [key for key in FACTS_KEYS if key not in _facts()]
    assert "matched by device name" in out


# --------------------------------------------------------------------------
# C — the report says which action clears the gate, and splits the list
# --------------------------------------------------------------------------


def _report_with(unreviewed: list[dict]) -> dict:
    return {
        "schema": "boardwise.checkup/7",
        "summary": {"unreviewedParts": len(unreviewed)},
        "unreviewed_parts": unreviewed,
        "needs_datasheet": [],
        "completion": {"unreviewedByClass": unreviewed_counts_by_class(unreviewed)},
    }


def _would_be_row(designator: str, *reasons: str) -> dict:
    return {
        "designator": designator,
        "name": "",
        "value": "",
        "footprint": "",
        "mpn": "",
        "supplier": "",
        "reasons": list(reasons),
        "isIc": True,
        "onShelf": False,
        "shelfKey": "",
        "shelfMatchedBy": "",
        "factsVerified": None,
        "factsPresent": [],
        "missingFacts": ["supply_pins"],
        "channels": {},
    }


def test_the_unreviewed_section_names_the_action_that_clears_the_gate():
    """P1: 给 PDF ≠ 清闸. The line names the CLI's own commands — including the
    one that does **not** work — and the review-summary skeleton carries it too."""
    report = _report_with([_would_be_row("U1", "无 MPN")])
    markdown = render_report_markdown(report)
    assert UNREVIEWED_CLEARING_NOTE in markdown
    assert "parts add" in UNREVIEWED_CLEARING_NOTE and "--verified" in UNREVIEWED_CLEARING_NOTE
    assert "need-datasheet" in UNREVIEWED_CLEARING_NOTE
    assert UNREVIEWED_CLEARING_NOTE in render_review_summary(report, [])


def test_the_unreviewed_list_is_split_into_two_kinds_of_work():
    """2.3: 「工具读不懂」 and 「真缺资料」 need opposite next steps, so the report
    names both — from the rows, so the table cannot disagree with the list."""
    unreviewed = [
        _would_be_row("R1", UNKNOWN_REASON_UNDECODABLE, "供应商字段为空"),
        _would_be_row("U2", "无 MPN", "供应商字段为空"),
        _would_be_row("U3"),  # no reasons at all: an IC the shelf has nothing for
    ]
    assert unreviewed_counts_by_reason(unreviewed) == {
        UNKNOWN_REASON_UNDECODABLE: 1,
        "无 MPN": 1,
        "供应商字段为空": 2,
    }
    assert unreviewed_counts_by_class(unreviewed) == {
        REASON_CLASS_UNDECODABLE: 1,
        REASON_CLASS_MISSING_MATERIAL: 3,
    }
    assert unreviewed_classes(unreviewed[0]) == [
        REASON_CLASS_UNDECODABLE,
        REASON_CLASS_MISSING_MATERIAL,
    ]

    markdown = render_report_markdown(_report_with(unreviewed))
    assert f"**{REASON_CLASS_UNDECODABLE}**（1）：`R1`" in markdown
    # R1 carries both reasons, so it is named in both lists: the classes answer
    # "what work is this" per reason, and the heading's number stays the count
    # of parts.
    assert f"**{REASON_CLASS_MISSING_MATERIAL}**（3）：`R1`、`U2`、`U3`" in markdown
    assert "再喂 PDF 也没用" in markdown


def test_checkup_writes_the_class_split_beside_the_reason_split(capsys, tmp_path, monkeypatch):
    """The two tables in a real report are counted from the section's own rows."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    board, _designator, _name = _name_only_fixture()
    report = _checkup(board, SHELF, tmp_path / "out")
    rows = report["unreviewed_parts"]
    assert report["summary"]["unreviewedByClass"] == unreviewed_counts_by_class(rows)
    assert report["completion"]["unreviewedByClass"] == report["summary"]["unreviewedByClass"]
    assert sum(report["summary"]["unreviewedByClass"].values()) >= len(rows)
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    for name in (REASON_CLASS_UNDECODABLE, REASON_CLASS_MISSING_MATERIAL):
        assert f"**{name}**（" in markdown


def test_fetch_with_nothing_extracted_points_at_the_manual_path(monkeypatch, tmp_path, capsys):
    """P3 止血: an empty extraction is a statement about the document, not a
    failure of the tool — and the manual path is one command away."""
    shelf = _shelf(tmp_path, _entry("ic.acme", mpn=NEUTRAL_NAME, lcsc="C9900000001"))
    pdf = tmp_path / "acme.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(cli, "_pdf_text", lambda path: ("<<<page 1>>>\nnothing here\n", "stub"))
    code = cli.main([
        "parts", "fetch", NEUTRAL_NAME, "--file", str(pdf), "--library", str(shelf),
        "--out", str(tmp_path / "ds"),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "facts 提取为空" in out
    assert "parts add" in out and "--verified" in out


# --------------------------------------------------------------------------
# D — the hygiene word gate (three states)
# --------------------------------------------------------------------------


def _guard():
    spec = importlib.util.spec_from_file_location(
        "check_repo_hygiene_186", ROOT / "tools" / "check_repo_hygiene.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_no_list_means_the_gate_is_off(tmp_path):
    """Every clone and every CI run: no `.sensitive-words` ⇒ nothing to scan,
    by construction rather than by a flag someone may set wrong."""
    guard = _guard()
    (tmp_path / "a.md").write_text("anything at all", encoding="utf-8")
    assert guard.sensitive_words(tmp_path / ".sensitive-words") == []
    assert guard.sensitive_violations(tmp_path, guard.sensitive_words(tmp_path / ".sensitive-words"), ["a.md"]) == []


def test_a_listed_word_in_a_tracked_file_is_a_violation_with_file_and_line(tmp_path):
    guard = _guard()
    (tmp_path / ".sensitive-words").write_text("# a note\nAcmeCorp\n", encoding="utf-8")
    (tmp_path / "clean.md").write_text("nothing to see", encoding="utf-8")
    (tmp_path / "dirty.md").write_text("line one\nsee AcmeCorp here\n", encoding="utf-8")
    words = guard.sensitive_words(tmp_path / ".sensitive-words")
    assert words == ["AcmeCorp"], "the comment line is not a word"
    hits = guard.sensitive_violations(tmp_path, words, ["clean.md", "dirty.md"])
    assert hits == ["dirty.md:2 (word #1)"]
    # The word itself is never echoed: the list is the one place it lives.
    assert all("AcmeCorp" not in hit for hit in hits)


def test_the_word_matches_as_a_token_not_as_a_substring(tmp_path):
    """A three-letter name must not fire inside a longer word (`docs`), while a
    real occurrence — punctuation, a space, a case difference — does."""
    guard = _guard()
    words = guard.sensitive_words(
        _write(tmp_path / ".sensitive-words", "ocs\n")
    )
    (tmp_path / "words.md").write_text("docs and rocks\n", encoding="utf-8")
    (tmp_path / "real.md").write_text("the ocs-project board\n", encoding="utf-8")
    assert guard.sensitive_violations(tmp_path, words, ["words.md"]) == []
    assert guard.sensitive_violations(tmp_path, words, ["real.md"]) == [
        "real.md:1 (word #1)"
    ]


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_the_list_file_itself_is_never_scanned(tmp_path):
    """Otherwise every line of the list would match itself and say nothing."""
    guard = _guard()
    (tmp_path / ".sensitive-words").write_text("AcmeCorp\n", encoding="utf-8")
    words = guard.sensitive_words(tmp_path / ".sensitive-words")
    assert guard.sensitive_violations(tmp_path, words, [".sensitive-words"]) == []


def test_the_real_repository_passes_the_container_gate_as_it_stands():
    """The red line this repository always checks: no unapproved container.

    **187B narrowed this to the container gate.** It used to run the whole guard
    and expect exit 0, which stopped being a statement about the repository the
    moment the owner wrote their own (gitignored) word list: the number of hits
    in an old clone depends on *their* list, not on this batch. The word gate's
    own semantics are pinned against temporary lists (here and in
    `tests/test_187b_gate_holes.py`), which is the machine-independent half.
    """
    import subprocess

    out = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, cwd=ROOT
    )
    tracked = [p for p in out.stdout.decode("utf-8").split("\0") if p]
    guard = _guard()
    assert guard.violations(tracked) == []
