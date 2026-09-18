"""The gates a board spec must pass (task 008c, item 4; 009-M0 P0).

The gates split into two families: the **product gates** (sources, pin budget,
levels, power tree) always run, and the **closed book** is benchmark discipline
that runs only under ``benchmark=True`` — a user drawing a new board owes sound
electricity, not a bibliography, and has no target board to name.

The negative cases are the point of this file — each gate is asked the one
question it exists to answer, and then asked it in the shape that must be
refused:

* sources — a declared input that is not there is refused, and a part citation
  with no shelf to check against is undecidable rather than absent;
* closed book (benchmark mode) — a template cut out of the target board is
  refused, and so is a field that cites nothing (or cites something never
  declared);
* pin budget — a pin the MCU symbol does not have is refused, and so is asking
  for more pins than the symbol exposes;
* levels — two domains on one net are refused unless a block on it declares
  itself the shifter, and a *silent* port is undecidable rather than agreeing;
* power tree — zero sources or two sources are refused, and so is a sink asking
  for a voltage the source does not provide.

Two behaviours are pinned because they are the easy ways to get this wrong:

* **undecidable blocks.** "I could not tell" must never read as "this is fine";
* **skipped says so.** A gate whose inputs were never supplied prints that it
  checked nothing, and does not block — because a board with no MCU is a real
  thing, not a failure.

The committed CH340 board is the known-good fixture for the product gates: it
is a real page whose metadata has been filled in, so if it fails, the gate is
wrong. Under ``benchmark=True`` the closed book refuses it *on purpose* — its
blocks were cut out of the very page it would be graded against, which is
exactly what closed book forbids.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.blocks import (
    BlockError,
    load_block_template,
    load_board_spec,
    template_from_json,
    template_to_json,
)
from boardwise.core.parts import load_parts
from boardwise.core.pintable import pin_table_from_json
from boardwise.core.portmeta import (
    PortMetaError,
    load_port_meta,
    port_meta_from_json,
)
from boardwise.engines.validate_spec import (
    FAIL,
    GATE_ORDER,
    PASS,
    SKIPPED,
    UNDECIDABLE_GATE,
    _gate_levels,
    validate_spec,
)

ROOT = Path(__file__).resolve().parents[1]
CH340_SPEC = ROOT / "blocklib" / "specs" / "ch340g_usb_uart.json"
CH340_GOLDEN = ROOT / "tests" / "fixtures" / "ch340_golden.epro2"
LIBRARY = ROOT / "blocklib" / "parts.json"
BLOCKS = ROOT / "blocklib" / "blocks"
PORT_META = ROOT / "blocklib" / "blocks.portmeta.json"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def port(role: str, net_class: str = "signal", **fields) -> dict:
    """One interface entry. Anything in ``fields`` is the metadata under test."""
    body = {"role": role, "net": role, "net_class": net_class, "position": [0.0, 0.0]}
    body.update(fields)
    return body


def template_body(
    name: str,
    ports: list[dict],
    *,
    source: str = "hand",
    provenance_kind: str = "textbook",
    pins: tuple[str, ...] = ("1", "2", "3"),
    params: list[dict] | None = None,
) -> dict:
    """The smallest template that loads, with the shape the tests need to vary."""
    body = {
        "kind": "boardwise-block-template",
        "version": 1,
        "name": name,
        "description": "",
        "provenance": {
            "kind": provenance_kind,
            "source": source,
            "designators": ["U1"],
            "note": "",
        },
        "origin_file": [0.0, 0.0],
        "bbox_file": [0.0, 0.0, 100.0, 100.0],
        "notes": [],
        "interface": list(ports),
        "params": list(params or []),
        "symbols": {
            "sym1": {
                "offsets": {number: [10.0 * index, 0.0] for index, number in enumerate(pins)},
                "body": None,
                "pin_names": {number: number for number in pins},
            }
        },
        "components": [
            {
                "ref": "U1",
                "symbol": "sym1",
                "placement": {"x": 0.0, "y": 0.0, "rotation": 0.0, "mirror": False},
                "device": {"lcsc": "C1", "name": "Part"},
                "footprint": "0402",
                "params": {},
                "pins": [],
            }
        ],
        "geometry": {
            "wires": [{"net": "", "points": [[0.0, 0.0], [10.0, 0.0]]}],
            "flags": [],
            "labels": [],
        },
    }
    return body


def spec_json(
    *,
    blocks: list[dict],
    connections: list[dict],
    params: dict | None = None,
    references: list[dict] | None = None,
    param_evidence: dict | None = None,
    provenance_source: str = "hand",
    notes: list[str] | None = None,
) -> dict:
    body = {
        "kind": "boardwise-board-spec",
        "version": 1,
        "name": "t",
        "description": "",
        "provenance": {"kind": "textbook", "source": provenance_source, "note": ""},
        "sheet": {"attrs": {}, "origin": [0.0, 0.0]},
        "blocks": blocks,
        "connections": connections,
        "params": params or {},
    }
    if references is not None:
        body["references"] = references
    if param_evidence is not None:
        body["param_evidence"] = param_evidence
    if notes is not None:
        body["notes"] = notes
    return body


def write_spec(tmp_path: Path, raw: dict) -> Path:
    """Write ``raw`` out. Template references are bare names here, so the
    extension is added once, in the one place that writes the spec."""
    for block in raw.get("blocks", []):
        if not str(block.get("template", "")).endswith(".json"):
            block["template"] = f"{block['template']}.json"
    path = Path(tmp_path) / "spec.json"
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_templates(tmp_path: Path, templates: dict[str, dict]) -> None:
    for index, (name, body) in enumerate(templates.items()):
        (Path(tmp_path) / f"{name}.json").write_text(
            json.dumps(body, indent=2), encoding="utf-8"
        )
        assert index >= 0  # the loop is here for the write, not for counting


def build(tmp_path: Path, raw: dict, templates: dict[str, dict]):
    write_templates(tmp_path, templates)
    return load_board_spec(write_spec(tmp_path, raw))


def pin_table(*pins, mcu: str = "ic.testmcu"):
    return pin_table_from_json(
        {
            "kind": "boardwise-firmware-pintable",
            "version": 1,
            "mcu": mcu,
            "pins": [
                {"number": number, "name": number, "function": function, "net": net}
                for number, function, net in pins
            ],
        },
        where="synthetic",
    )


def reference(ref_id: str, kind: str = "intent", **fields) -> dict:
    body = {"id": ref_id, "kind": kind}
    body.update(fields)
    return body


def rules_of(report, gate: str) -> set[str]:
    result = report.gate(gate)
    assert result is not None
    return {finding.rule for finding in result.findings}


def plain(message: str) -> str:
    """A message without the emphasis asterisks, so phrases can be asserted."""
    return message.replace("*", "")


# --------------------------------------------------------------------------
# the port metadata itself
# --------------------------------------------------------------------------


def test_a_port_carries_its_direction_voltage_and_level():
    template = template_from_json(
        template_body(
            "t",
            [
                port("VDD", "power", direction="source", voltage="3V3"),
                port("GND", "gnd", direction="sink"),
                port("IO", "signal", level="3V3"),
            ],
        )
    )
    assert template.port("VDD").is_source
    assert template.port("VDD").voltage == "3V3"
    assert template.port("GND").is_sink
    assert template.port("IO").level == "3V3"


def test_a_direction_outside_the_two_words_is_refused():
    with pytest.raises(BlockError, match="expected one of source, sink"):
        template_from_json(template_body("t", [port("VDD", "power", direction="upstream")]))


@pytest.mark.parametrize(
    "role, cls, field, value",
    [
        ("IO", "signal", "direction", "source"),
        ("IO", "signal", "voltage", "3V3"),
        ("VDD", "power", "level", "3V3"),
        ("GND", "gnd", "voltage", "0V"),
        ("GND", "gnd", "level", "3V3"),
    ],
)
def test_one_knob_per_job(role, cls, field, value):
    """A field on the wrong class would let two gates disagree about one port."""
    with pytest.raises(BlockError):
        template_from_json(template_body("t", [port(role, cls, **{field: value})]))


def test_the_new_fields_survive_a_round_trip():
    body = template_body(
        "t",
        [
            port("VDD", "power", direction="source", voltage="5V"),
            port("IO", "signal", level="USB"),
        ],
    )
    template = template_from_json(body)
    again = template_to_json(template)
    assert again["interface"][0]["direction"] == "source"
    assert again["interface"][0]["voltage"] == "5V"
    assert again["interface"][1]["level"] == "USB"
    assert template_from_json(again).port("IO").level == "USB"


def test_a_template_without_the_fields_does_not_grow_them():
    """A block written before 008c item 4 must not change shape on a re-write."""
    body = template_body("t", [port("IO"), port("VDD", "power")])
    again = template_to_json(template_from_json(body))
    for entry in again["interface"]:
        assert set(entry) == {"role", "net", "net_class", "position"}


def test_the_port_metadata_sidecar_says_what_every_ch340_port_is(tmp_path):
    """The known-good board is the fixture: every port of it is declared."""
    for path in sorted(BLOCKS.glob("ch340_*.json")):
        template = load_block_template(path, port_meta=load_port_meta(PORT_META))
        assert template.port
        for entry in template.interface:
            if entry.net_class == "signal":
                assert entry.level, f"{path.name}: {entry.role} declares no level"
            elif entry.net_class == "power":
                assert entry.direction, f"{path.name}: {entry.role} declares no direction"
                assert entry.voltage, f"{path.name}: {entry.role} declares no voltage"
            else:
                assert entry.direction, f"{path.name}: {entry.role} declares no direction"


def test_where_port_metadata_lives_follows_from_whether_the_block_can_be_recut():
    """The sidecar exists for one reason, and it is not "all metadata".

    A board-extract block is guarded by `tests/test_cut.py`: re-cutting from the
    golden must reproduce the committed bytes. Port metadata is a *declaration*
    about a port, not a geometric fact the cut produces, so writing it into a
    board-extract file would break that guard — which is why it lives in
    `blocks.portmeta.json` instead.

    A `datasheet-extract` or `textbook` block has no source board (the engine
    refuses to re-cut it), so nothing would break, and the metadata is better
    held where it cannot drift away from the block it describes. So the rule is
    not "metadata always goes in the sidecar" — it is **"the sidecar exists
    exactly for the blocks that have a re-cut guard to satisfy"**. This test
    states that rule so a future block cannot quietly land on the wrong side of
    it in either direction.
    """
    import json

    from boardwise.core.portmeta import PORT_META_FIELDS, load_port_meta

    sidecar = load_port_meta(PORT_META)

    for path in sorted(BLOCKS.glob("*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        inline = {
            field
            for entry in raw.get("interface", [])
            for field in PORT_META_FIELDS
            if entry.get(field)
        }
        template = load_block_template(path)
        in_sidecar = template.name in sidecar.blocks
        can_recut = template.provenance_kind == "board-extract"

        assert can_recut != bool(inline), (
            f"{path.name} ({template.provenance_kind}): metadata is written "
            f"{'inline' if inline else 'in the sidecar'} but a block that "
            f"{'' if can_recut else 'cannot '}be re-cut must use the other home "
            "— 'inline' fields would be wiped by `--recut` for a board-extract, "
            "and a datasheet/textbook block has no re-cut to protect it from "
            "being read without the sidecar"
        )
        if can_recut:
            assert in_sidecar, f"{path.name} is re-cuttable but the sidecar skips it"
        else:
            assert not in_sidecar, (
                f"{path.name} carries its metadata inline, so the sidecar entry "
                "is unreachable (it would be merged into a field that is "
                "already set, which the sidecar refuses)"
            )


def test_read_without_the_sidecar_every_port_is_silent(tmp_path):
    """The complement: no metadata means 'cannot tell', never 'agree'."""
    for path in sorted(BLOCKS.glob("ch340_*.json")):
        for entry in load_block_template(path).interface:
            assert (entry.direction, entry.voltage, entry.level) == ("", "", "")


# --------------------------------------------------------------------------
# spec evidence — the loader half
# --------------------------------------------------------------------------


def test_an_undeclared_reference_kind_is_refused(tmp_path):
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}],
        connections=[],
        references=[reference("r", "vibes")],
    )
    with pytest.raises(BlockError, match="kind: expected one of"):
        build(tmp_path, raw, {"ta": template_body("ta", [port("A")])})


def test_a_part_reference_names_the_shelf_key_it_cites(tmp_path):
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}],
        connections=[],
        references=[reference("p", "part", path="x/parts.json")],
    )
    with pytest.raises(BlockError, match="names the shelf key"):
        build(tmp_path, raw, {"ta": template_body("ta", [port("A")])})


def test_a_textbook_reference_names_the_topology_it_follows(tmp_path):
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}],
        connections=[],
        references=[reference("b", "textbook")],
    )
    with pytest.raises(BlockError, match="names the topology"):
        build(tmp_path, raw, {"ta": template_body("ta", [port("A")])})


def test_the_same_reference_id_twice_is_refused(tmp_path):
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}],
        connections=[],
        references=[reference("r", "intent", path="intent.md"), reference("r", "datasheet", path="d.pdf")],
    )
    with pytest.raises(BlockError, match="duplicate reference id"):
        build(tmp_path, raw, {"ta": template_body("ta", [port("A")])})


def test_citing_one_authority_twice_is_refused(tmp_path):
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["r", "r"]}],
        connections=[],
        references=[reference("r", "intent", path="intent.md")],
    )
    with pytest.raises(BlockError, match="cited twice"):
        build(tmp_path, raw, {"ta": template_body("ta", [port("A")])})


def test_evidence_for_a_value_nobody_assigned_is_refused(tmp_path):
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}],
        connections=[],
        references=[reference("r", "intent", path="intent.md")],
        param_evidence={"a.nothing": ["r"]},
    )
    with pytest.raises(BlockError, match="no such parameter value"):
        build(tmp_path, raw, {"ta": template_body("ta", [port("A")])})


# --------------------------------------------------------------------------
# the port-metadata sidecar
# --------------------------------------------------------------------------


def sidecar(name: str = "ta", role: str = "A", fields: dict | None = None, **extra) -> dict:
    return {
        "kind": "boardwise-block-port-metadata",
        "version": 1,
        "blocks": {name: {"ports": {role: fields or {"level": "3V3"}}, **extra}},
    }


def test_the_committed_sidecar_loads_and_names_real_blocks():
    """A sidecar entry for a template nobody has is a typo, not a no-op."""
    meta = load_port_meta(PORT_META)
    assert meta.for_template("ch340_core") is not None
    for name, entry in meta.blocks.items():
        matches = [p.name for p in BLOCKS.glob("*.json") if p.stem == name]
        assert matches, f"{name} is annotated but no block file is called that"


def test_a_field_the_schema_does_not_have_is_refused():
    with pytest.raises(PortMetaError, match="expected one of direction, voltage, level"):
        port_meta_from_json(sidecar(fields={"impedance": "50R"}))


def test_an_empty_value_is_refused():
    with pytest.raises(PortMetaError, match="non-empty string"):
        port_meta_from_json(sidecar(fields={"level": "  "}))


def test_annotating_a_port_the_block_does_not_have_is_refused(tmp_path):
    meta = port_meta_from_json(sidecar(role="NOPE"), where="sidecar")
    raw = template_body("ta", [port("A")])
    with pytest.raises(PortMetaError, match="has no port 'NOPE'"):
        meta.merge(raw)


def test_a_second_answer_to_one_question_is_refused(tmp_path):
    """The file already said it: the sidecar may not quietly win."""
    meta = port_meta_from_json(sidecar(fields={"level": "5V"}), where="sidecar")
    raw = template_body("ta", [port("A", level="3V3")])
    with pytest.raises(PortMetaError, match="already '3V3' in the template"):
        meta.merge(raw)


def test_the_class_rules_are_enforced_in_the_one_place_they_live(tmp_path):
    """`direction` on a signal port is still refused — same rule, either file."""
    meta = port_meta_from_json(sidecar(fields={"direction": "source"}), where="sidecar")
    (Path(tmp_path) / "ta.json").write_text(
        json.dumps(template_body("ta", [port("A")])), encoding="utf-8"
    )
    with pytest.raises(BlockError) as caught:
        load_block_template(Path(tmp_path) / "ta.json", port_meta=meta)
    assert "sidecar" in str(caught.value), "the message must name the sidecar, not the file"
    assert "a claim about power" in str(caught.value)


def test_the_provenance_is_carried_into_the_template_notes(tmp_path):
    meta = port_meta_from_json(
        sidecar(provenance="datasheet p.4", notes=["WHY: because U5 says so."]),
        where="sidecar",
    )
    raw = template_body("ta", [port("A")])
    assert meta.merge(raw)
    assert raw["notes"] == ["WHY: because U5 says so. [datasheet p.4]"]


def test_a_missing_sidecar_file_is_an_error_not_silence():
    with pytest.raises(PortMetaError, match="cannot read"):
        load_port_meta("nowhere/portmeta.json")


# --------------------------------------------------------------------------
# gate 1 — the closed book (benchmark discipline)
# --------------------------------------------------------------------------


def fully_cited(tmp_path: Path, **overrides):
    """A spec that cites a declared input for every one of its fields."""
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]}],
        connections=[],
        references=[reference("intent", "intent", path="intent.md")],
    )
    raw.update(overrides)
    return build(
        tmp_path, raw, {"ta": template_body("ta", [port("A")], source="textbook")}
    )


def test_product_validation_needs_no_target(tmp_path):
    """A new board has no golden to be graded against, and the product gates
    must not ask for one (009-M0 P0, acceptance scenario 4)."""
    spec = fully_cited(tmp_path)
    report = validate_spec(spec)
    gate = report.gate("closed-book")
    assert gate.status == SKIPPED
    assert "benchmark" in gate.skipped, "a skipped gate must say what would run it"
    assert report.ok


def test_a_benchmark_run_with_no_target_cannot_be_called_clean(tmp_path):
    spec = fully_cited(tmp_path)
    report = validate_spec(spec, benchmark=True)
    gate = report.gate("closed-book")
    assert gate.status == UNDECIDABLE_GATE
    assert not report.ok, "an untested claim is not a pass"
    assert "not a pass" in plain(gate.undecidables[0].message)


def test_a_template_cut_from_the_target_board_is_refused(tmp_path):
    raw = spec_json(
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]}],
        connections=[],
        references=[reference("intent", "intent", path="intent.md")],
    )
    spec = build(
        tmp_path,
        raw,
        {"ta": template_body("ta", [port("A")], source="tests/fixtures/target_board.epro2")},
    )
    report = validate_spec(spec, target="tests/fixtures/target_board.epro2", benchmark=True)
    assert report.gate("closed-book").status == FAIL
    assert "self-reference" in rules_of(report, "closed-book")


def test_an_export_date_is_not_a_loophole(tmp_path):
    """The same board exported tomorrow is the same board."""
    spec = build(
        tmp_path,
        spec_json(
            blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]}],
            connections=[],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {"ta": template_body("ta", [port("A")], source="tests/fixtures/ProPrj_box.epro2")},
    )
    report = validate_spec(spec, target="tests/fixtures/ProPrj_box_2026-09-17.epro2", benchmark=True)
    assert "self-reference" in rules_of(report, "closed-book")


def test_every_alias_of_the_target_can_be_named(tmp_path):
    """A local project and its export are one board under two names."""
    spec = build(
        tmp_path,
        spec_json(
            blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]}],
            connections=[],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {"ta": template_body("ta", [port("A")], source="blocklib/sources/pillbox.eprj2")},
    )
    alone = validate_spec(spec, target="exports/ProPrj_box_2026-09-17.epro2", benchmark=True)
    assert "self-reference" not in rules_of(alone, "closed-book")
    both = validate_spec(
        spec, target=["exports/ProPrj_box_2026-09-17.epro2", "pillbox"], benchmark=True
    )
    assert "self-reference" in rules_of(both, "closed-book")


def test_a_near_miss_is_not_a_false_accusation(tmp_path):
    """`ch340x` may not be condemned for being named like `ch340`."""
    spec = build(
        tmp_path,
        spec_json(
            blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]}],
            connections=[],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {"ta": template_body("ta", [port("A")], source="blocklib/blocks/ch340x_board.json")},
    )
    report = validate_spec(spec, target="ch340.epro2", benchmark=True)
    assert "self-reference" not in rules_of(report, "closed-book")


def test_naming_the_answer_in_the_spec_text_is_a_leak(tmp_path):
    spec = fully_cited(tmp_path, notes=["compared against target_board to check our work"])
    report = validate_spec(spec, target="target_board.epro2", benchmark=True)
    assert "answer-leak" in rules_of(report, "closed-book")


def test_declaring_the_answer_as_an_input_is_refused(tmp_path):
    spec = fully_cited(
        tmp_path,
        references=[
            reference("intent", "intent", path="intent.md"),
            reference("answer", "datasheet", path="target_board.epro2"),
        ],
    )
    report = validate_spec(spec, target="target_board.epro2", benchmark=True)
    assert "self-reference" in rules_of(report, "closed-book")


# --------------------------------------------------------------------------
# gate 2 — the sources (product discipline: declared inputs are real)
# --------------------------------------------------------------------------


def test_a_declared_input_that_is_not_there_is_refused(tmp_path):
    spec = fully_cited(tmp_path)
    report = validate_spec(spec, root=tmp_path)
    assert "declared-input-exists" in rules_of(report, "sources")
    assert not report.ok


def test_a_part_reference_the_shelf_does_not_have_is_refused(tmp_path):
    (Path(tmp_path) / "intent.md").write_text("intent", encoding="utf-8")
    spec = fully_cited(
        tmp_path,
        references=[
            reference("intent", "intent", path="intent.md"),
            reference("missing", "part", ref="ic.not-on-the-shelf"),
        ],
        blocks=[
            {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent", "missing"]}
        ],
    )
    report = validate_spec(spec, root=tmp_path, library=load_parts(LIBRARY))
    assert "declared-input-exists" in rules_of(report, "sources")


def test_without_the_shelf_a_part_citation_is_undecidable(tmp_path):
    (Path(tmp_path) / "intent.md").write_text("intent", encoding="utf-8")
    spec = fully_cited(
        tmp_path,
        references=[
            reference("intent", "intent", path="intent.md"),
            reference("answer-part", "part", ref="ic.rt9013_33gb"),
        ],
        blocks=[
            {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent", "answer-part"]}
        ],
    )
    report = validate_spec(spec, root=tmp_path)
    gate = report.gate("sources")
    assert gate.undecidables, "no library was supplied, so the citation cannot be checked"
    assert not report.ok


# --------------------------------------------------------------------------
# the evidence ledger (part of the closed book — benchmark mode only)
# --------------------------------------------------------------------------


def test_a_field_that_cites_nothing_is_refused(tmp_path):
    """Blocks, values and connections are each asked where they came from."""
    spec = build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "b", "template": "tb", "at": [0.0, 0.0], "evidence": ["intent"]},
            ],
            connections=[
                {
                    "net": "N",
                    "ports": [["a", "A"], ["b", "B"]],
                }
            ],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {
            "ta": template_body("ta", [port("A")]),
            "tb": template_body("tb", [port("B")]),
        },
    )
    report = validate_spec(spec, target="some_board.epro2", benchmark=True)
    gate = report.gate("closed-book")
    messages = " ".join(f.message for f in gate.violations)
    assert "connection 'N'" in messages
    assert "no inputs at all" not in messages


def test_a_missing_block_and_value_citation_are_each_reported(tmp_path):
    spec = build(
        tmp_path,
        spec_json(
            blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}],
            connections=[],
            params={"a.r_value": "10k"},
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {
            "ta": template_body(
                "ta",
                [port("A")],
                params=[
                    {
                        "name": "r_value",
                        "role": "R value",
                        "default": "1k",
                        "constraint": "resistor_value",
                    }
                ],
            )
        },
    )
    report = validate_spec(spec, target="some_board.epro2", benchmark=True)
    gate = report.gate("closed-book")
    messages = " ".join(f.message for f in gate.violations)
    assert "block 'a'" in messages
    assert "'a.r_value'" in messages


def test_a_citation_to_something_never_declared_is_refused(tmp_path):
    spec = fully_cited(
        tmp_path,
        blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["nowhere"]}],
    )
    report = validate_spec(spec, target="some_board.epro2", benchmark=True)
    gate = report.gate("closed-book")
    assert any("never declares" in f.message for f in gate.violations)


def test_a_spec_that_declares_nothing_is_refused(tmp_path):
    spec = build(
        tmp_path,
        spec_json(blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}], connections=[]),
        {"ta": template_body("ta", [port("A")])},
    )
    report = validate_spec(spec, target="some_board.epro2", benchmark=True)
    assert any("declares no inputs" in f.message for f in report.violations)


def test_an_uncited_input_is_noted_and_does_not_block(tmp_path):
    (Path(tmp_path) / "intent.md").write_text("intent", encoding="utf-8")
    (Path(tmp_path) / "notes.md").write_text("notes nobody cited", encoding="utf-8")
    spec = fully_cited(
        tmp_path,
        references=[
            reference("intent", "intent", path="intent.md"),
            reference("spare", "intent", path="notes.md"),
        ],
    )
    report = validate_spec(spec, target="some_board.epro2", root=tmp_path, benchmark=True)
    gate = report.gate("closed-book")
    assert not gate.violations and not gate.undecidables
    assert any(
        "declared but never cited" in f.message and "spare" in f.message
        for f in gate.findings
        if f.rule == "evidence-present"
    )


def test_a_fully_cited_spec_passes_the_closed_book(tmp_path):
    (Path(tmp_path) / "intent.md").write_text("intent", encoding="utf-8")
    spec = fully_cited(tmp_path)
    report = validate_spec(spec, target="some_board.epro2", root=tmp_path, benchmark=True)
    assert report.gate("closed-book").status == PASS


def test_a_spec_without_a_ledger_is_still_a_product_spec(tmp_path):
    """A user drawing a new board owes sound electricity, not a bibliography:
    the ledger-less spec the benchmark refuses passes product validation
    (009-M0 P0 — the committed CH340 spec is exactly this shape)."""
    spec = build(
        tmp_path,
        spec_json(blocks=[{"id": "a", "template": "ta", "at": [0.0, 0.0]}], connections=[]),
        {"ta": template_body("ta", [port("A")])},
    )
    report = validate_spec(spec)
    assert report.ok
    assert report.gate("closed-book").status == SKIPPED
    # ...and the same spec still fails the closed book when it *is* graded
    graded = validate_spec(spec, target="some_board.epro2", benchmark=True)
    assert not graded.ok
    assert "evidence-present" in rules_of(graded, "closed-book")


# --------------------------------------------------------------------------
# gate 3 — the pin budget
# --------------------------------------------------------------------------


def mcu_spec(tmp_path: Path, *, mcu_pins=("PA1", "PA2"), connections=None, blocks=("mcu",)):
    templates = {"ic.testmcu": template_body("ic.testmcu", [port("A"), port("B")], pins=mcu_pins)}
    return build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "mcu", "template": "ic.testmcu", "at": [0.0, 0.0], "evidence": ["intent"]}
            ],
            connections=connections or [],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        templates,
    )


def test_no_pin_table_means_skipped_not_passed(tmp_path):
    spec = mcu_spec(tmp_path)
    report = validate_spec(spec, target="some_board.epro2")
    gate = report.gate("pin-budget")
    assert gate.status == SKIPPED, "a skipped gate must never claim to agree"
    assert "nothing was checked" in gate.skipped
    assert report.ok, "a page whose MCU carries no firmware is not a failing page"


def test_a_pin_table_with_no_matching_block_is_undecidable(tmp_path):
    spec = fully_cited(tmp_path)
    report = validate_spec(
        spec, target="some_board.epro2", table=pin_table(("PA1", "GPIO", "LED1"))
    )
    gate = report.gate("pin-budget")
    assert gate.status == UNDECIDABLE_GATE
    assert not report.ok


def test_a_pin_the_symbol_does_not_have_is_refused(tmp_path):
    spec = mcu_spec(tmp_path, mcu_pins=("PA1",))
    report = validate_spec(
        spec, target="some_board.epro2", table=pin_table(("PA9", "GPIO", "NET1"))
    )
    gate = report.gate("pin-budget")
    assert gate.status == FAIL
    assert "pin-numbers-exist" in rules_of(report, "pin-budget")


def test_asking_for_more_pins_than_the_symbol_has_is_refused(tmp_path):
    spec = mcu_spec(
        tmp_path,
        mcu_pins=("PA1",),
        connections=[
            {"net": "N1", "ports": [["mcu", "A"], ["mcu", "B"]], "evidence": ["intent"]}
        ],
    )
    report = validate_spec(spec, target="some_board.epro2", table=pin_table(("PA1", "GPIO", "N1")))
    gate = report.gate("pin-budget")
    assert gate.status == FAIL
    assert any("more pins than the part has" in f.message for f in gate.violations)


def test_two_instances_of_the_mcu_template_are_ambiguous(tmp_path):
    raw = spec_json(
        blocks=[
            {"id": "mcu1", "template": "ic.testmcu", "at": [0.0, 0.0], "evidence": ["intent"]},
            {"id": "mcu2", "template": "ic.testmcu", "at": [0.0, 0.0], "evidence": ["intent"]},
        ],
        connections=[
            {"net": "N1", "ports": [["mcu1", "A"], ["mcu2", "B"]], "evidence": ["intent"]},
        ],
        references=[reference("intent", "intent", path="intent.md")],
    )
    spec = build(
        tmp_path,
        raw,
        {"ic.testmcu": template_body("ic.testmcu", [port("A"), port("B")], pins=("PA1",))},
    )
    report = validate_spec(spec, target="some_board.epro2", table=pin_table(("PA1", "GPIO", "N1")))
    assert report.gate("pin-budget").status == UNDECIDABLE_GATE
    # ...and naming one settles it
    named = validate_spec(
        spec, target="some_board.epro2", table=pin_table(("PA1", "GPIO", "N1")), mcu_block_id="mcu1"
    )
    assert named.gate("pin-budget").status == PASS


def test_an_mcu_pin_the_firmware_never_names_is_a_defect(tmp_path):
    spec = mcu_spec(tmp_path, connections=[])
    table = pin_table(("PA1", "GPIO", "LED1"))
    report = validate_spec(spec, target="some_board.epro2", table=table)
    assert report.gate("pin-budget").status == FAIL


def test_a_pin_table_that_agrees_with_the_spec_passes(tmp_path):
    spec = mcu_spec(
        tmp_path,
        connections=[
            {"net": "LED1", "ports": [["mcu", "A"], ["mcu", "B"]], "evidence": ["intent"]}
        ],
    )
    table = pin_table(("PA1", "GPIO", "LED1"))
    report = validate_spec(spec, target="some_board.epro2", table=table)
    assert report.gate("pin-budget").status == PASS


# --------------------------------------------------------------------------
# gate 4 — levels
# --------------------------------------------------------------------------


def level_spec(tmp_path: Path, second, *, third=None, connections=None):
    templates = {
        "ta": template_body("ta", [port("A", level="3V3")]),
        "tb": template_body("tb", [port("B", **second)]),
    }
    entries = [{"net": "N", "ports": [["a", "A"], ["b", "B"]], "evidence": ["intent"]}]
    if third is not None:
        templates["tc"] = template_body("tc", [port("C", **third)])
        entries.append({"net": "M", "ports": [["b", "B"], ["c", "C"]], "evidence": ["intent"]})
    return build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "b", "template": "tb", "at": [0.0, 0.0], "evidence": ["intent"]},
            ]
            + ([{"id": "c", "template": "tc", "at": [0.0, 0.0], "evidence": ["intent"]}] if third else []),
            connections=connections or entries,
            references=[reference("intent", "intent", path="intent.md")],
        ),
        templates,
    )


def test_two_domains_on_one_net_is_a_violation(tmp_path):
    spec = level_spec(tmp_path, {"level": "5V"})
    report = validate_spec(spec, target="some_board.epro2")
    gate = report.gate("levels")
    assert gate.status == FAIL
    assert "level-domain" in rules_of(report, "levels")


def test_no_declaration_makes_two_domains_on_one_net_legal(tmp_path):
    """A block saying it is a level shifter does not licence its own net.

    Replaces the old ``level_shifter: true`` exemption (M0-P0c). That exemption
    let a block put two domains on one net just by declaring itself allowed to,
    which is the one thing a real shifter never does: its low side and its high
    side are two *different* nets. Here the block states the level it actually
    speaks, and the net still fails because the other end disagrees.
    """
    spec = build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "b", "template": "tb", "at": [0.0, 0.0], "evidence": ["intent"]},
            ],
            connections=[
                {"net": "N", "ports": [["a", "A"], ["b", "B"]], "evidence": ["intent"]}
            ],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {
            "ta": template_body("ta", [port("A", level="3V3")]),
            "tb": template_body("tb", [port("B", level="5V")]),
        },
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("levels")
    assert gate.status == FAIL
    assert [f.message for f in gate.violations if "two IO domains" in f.message]


def test_a_silent_port_is_undecidable_not_agreeing(tmp_path):
    spec = level_spec(tmp_path, {})
    report = validate_spec(spec, target="some_board.epro2")
    gate = report.gate("levels")
    assert gate.status == UNDECIDABLE_GATE
    assert not report.ok
    assert any("cannot be decided" in f.message for f in gate.undecidables)


def test_a_net_with_no_levels_at_all_is_undecidable(tmp_path):
    spec = build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "b", "template": "tb", "at": [0.0, 0.0], "evidence": ["intent"]},
            ],
            connections=[
                {"net": "N", "ports": [["a", "A"], ["b", "B"]], "evidence": ["intent"]}
            ],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {
            "ta": template_body("ta", [port("A")]),
            "tb": template_body("tb", [port("B")]),
        },
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("levels")
    assert gate.status == UNDECIDABLE_GATE
    assert "not a pass" in plain(gate.undecidables[0].message)


def test_a_two_sided_shifter_joins_two_nets_each_in_one_domain(tmp_path):
    """The legitimate conversion: two nets, one domain each (M0-P0c).

    Replaces ``test_two_domains_without_a_shifter_between_them``, whose premise
    — "a shifter not on the offending net licences nothing" — was part of the
    exemption's vocabulary and no longer means anything. What a real shifter
    looks like is this: its low side joins the 3V3 net, its high side joins the
    5V net, and *neither net mixes domains*. That is why the exemption was
    wrong — the legal case never triggered it.
    """
    templates = {
        "tlv": template_body("tlv", [port("A", level="3V3")]),
        "ttx": template_body(
            "ttx", [port("L", level="3V3"), port("H", level="5V")], pins=("1", "2")
        ),
        "thv": template_body("thv", [port("B", level="5V")]),
    }
    spec = build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "lv", "template": "tlv", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "tx", "template": "ttx", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "hv", "template": "thv", "at": [0.0, 0.0], "evidence": ["intent"]},
            ],
            connections=[
                {"net": "N3V3", "ports": [["lv", "A"], ["tx", "L"]], "evidence": ["intent"]},
                {"net": "N5V", "ports": [["tx", "H"], ["hv", "B"]], "evidence": ["intent"]},
            ],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        templates,
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("levels")
    assert gate.status == PASS, [f.message for f in gate.findings]
    assert not gate.violations
    assert not gate.undecidables, [f.message for f in gate.undecidables]


def test_one_domain_on_every_port_passes(tmp_path):
    spec = level_spec(tmp_path, {"level": "3V3"})
    gate = validate_spec(spec, target="some_board.epro2").gate("levels")
    assert gate.status == PASS


def test_a_rail_on_the_same_page_does_not_switch_off_the_level_check(tmp_path):
    """A non-signal port skips *its own* net, not the gate (M0-P0c).

    The gate walks the spec's connections, and a rail is not its business — a
    rail's business is the power tree. But the skip has to be per-net: with a
    power net and a mixed-domain signal net on one page, only the signal net may
    be judged, and it must still be judged.
    """
    spec = build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "b", "template": "tb", "at": [0.0, 0.0], "evidence": ["intent"]},
            ],
            connections=[
                {"net": "N", "ports": [["a", "A"], ["b", "B"]], "evidence": ["intent"]},
                {"net": "VCC", "ports": [["a", "P"], ["b", "P"]], "evidence": ["intent"]},
            ],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {
            "ta": template_body(
                "ta", [port("A", level="3V3"), port("P", "power", direction="source", voltage="3V3")]
            ),
            "tb": template_body(
                "tb", [port("B", level="5V"), port("P", "power", direction="sink", voltage="3V3")]
            ),
        },
    )
    gate = _gate_levels(spec)
    # The rail is skipped...
    assert not [f for f in gate.findings if "VCC" in f.message]
    # ...and the signal net on the same page is still judged.
    assert [f for f in gate.violations if "net 'N'" in f.message]


def test_a_connection_that_names_no_real_block_is_skipped(tmp_path):
    """The gate's first guard: a net with no resolvable port is not a finding.

    ``_ports_of`` returns nothing when a connection names a block that is not on
    the page. Reached here by pulling the block out from under an already-loaded
    spec, because the loader refuses such a connection in the first place — so
    this pins the guard's own behaviour (nothing to judge, nothing reported)
    rather than a state a valid spec can be written in.
    """
    spec = level_spec(tmp_path, {"level": "3V3"})
    for connection in spec.connections:
        connection.ports = [("ghost", "A")]
    gate = _gate_levels(spec)
    assert gate.findings == []


# --------------------------------------------------------------------------
# gate 5 — the power tree
# --------------------------------------------------------------------------


def power_spec(tmp_path: Path, first: dict, second: dict):
    return build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "b", "template": "tb", "at": [0.0, 0.0], "evidence": ["intent"]},
            ],
            connections=[
                {"net": "VCC", "ports": [["a", "A"], ["b", "A"]], "evidence": ["intent"]}
            ],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {
            "ta": template_body("ta", [port("A", "power", **first)]),
            "tb": template_body("tb", [port("A", "power", **second)]),
        },
    )


def test_a_rail_with_no_source_is_refused(tmp_path):
    spec = power_spec(
        tmp_path, {"direction": "sink", "voltage": "3V3"}, {"direction": "sink", "voltage": "3V3"}
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == FAIL
    assert "one-source" in {f.rule for f in gate.findings}
    assert "no source" in gate.violations[0].message


def test_two_sources_on_one_rail_is_refused(tmp_path):
    spec = power_spec(
        tmp_path,
        {"direction": "source", "voltage": "3V3"},
        {"direction": "source", "voltage": "3V3"},
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == FAIL
    assert "2 sources" in gate.violations[0].message


def test_a_sink_that_asks_for_another_voltage_is_refused(tmp_path):
    spec = power_spec(
        tmp_path,
        {"direction": "source", "voltage": "3V3"},
        {"direction": "sink", "voltage": "5V"},
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == FAIL
    assert "voltage-match" in {f.rule for f in gate.findings}


def test_a_source_that_says_no_voltage_is_undecidable(tmp_path):
    spec = power_spec(
        tmp_path, {"direction": "source"}, {"direction": "sink", "voltage": "3V3"}
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == UNDECIDABLE_GATE
    assert "cannot be checked" in gate.undecidables[0].message


def test_a_sink_that_says_no_voltage_is_undecidable(tmp_path):
    spec = power_spec(
        tmp_path, {"direction": "source", "voltage": "3V3"}, {"direction": "sink"}
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == UNDECIDABLE_GATE


def test_a_port_with_no_direction_cannot_be_counted(tmp_path):
    spec = power_spec(tmp_path, {"voltage": "3V3"}, {"voltage": "3V3"})
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == UNDECIDABLE_GATE


def test_ground_needs_no_source(tmp_path):
    """Ground is the sink: four sinks and no driver is a circuit, not a fault."""
    spec = build(
        tmp_path,
        spec_json(
            blocks=[
                {"id": "a", "template": "ta", "at": [0.0, 0.0], "evidence": ["intent"]},
                {"id": "b", "template": "tb", "at": [0.0, 0.0], "evidence": ["intent"]},
            ],
            connections=[
                {
                    "net": "GND",
                    "ports": [["a", "G"], ["b", "G"]],
                    "evidence": ["intent"],
                }
            ],
            references=[reference("intent", "intent", path="intent.md")],
        ),
        {
            "ta": template_body("ta", [port("G", "gnd", direction="sink")]),
            "tb": template_body("tb", [port("G", "gnd", direction="sink")]),
        },
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == PASS


def test_one_source_feeding_a_matching_sink_passes(tmp_path):
    spec = power_spec(
        tmp_path,
        {"direction": "source", "voltage": "3V3"},
        {"direction": "sink", "voltage": "3V3"},
    )
    gate = validate_spec(spec, target="some_board.epro2").gate("power-tree")
    assert gate.status == PASS


# --------------------------------------------------------------------------
# the known-good board, and the report itself
# --------------------------------------------------------------------------


def test_the_ch340_board_passes_product_validation():
    """The committed spec is a *product* spec: no golden, no evidence ledger,
    and it still comes back clean (009-M0 P0). It is a real page with its
    metadata filled in — if it fails, the gate is wrong."""
    spec = load_board_spec(CH340_SPEC, port_meta=load_port_meta(PORT_META))
    report = validate_spec(spec)
    assert report.gate("sources").status == PASS
    assert report.gate("levels").status == PASS
    assert report.gate("power-tree").status == PASS
    assert report.gate("pin-budget").status == SKIPPED
    assert report.gate("closed-book").status == SKIPPED
    assert report.ok


def test_the_same_board_without_the_metadata_cannot_be_called_clean():
    """Reading the files alone gives no metadata, and 'cannot tell' blocks."""
    spec = load_board_spec(CH340_SPEC)
    report = validate_spec(spec)
    assert report.gate("levels").status == UNDECIDABLE_GATE
    assert report.gate("power-tree").status == UNDECIDABLE_GATE
    assert not report.ok


def test_the_ch340_board_is_refused_by_the_closed_book():
    """Every one of its blocks was cut out of the page it would be graded against."""
    spec = load_board_spec(CH340_SPEC)
    report = validate_spec(spec, target=str(CH340_GOLDEN), benchmark=True)
    gate = report.gate("closed-book")
    assert gate.status == FAIL
    assert sum(1 for f in gate.violations if f.rule == "self-reference") == 5, [
        f.message for f in gate.violations
    ]


def test_the_gates_are_reported_in_the_order_they_are_told_to_run():
    spec = load_board_spec(CH340_SPEC)
    report = validate_spec(spec)
    assert [gate.name for gate in report.gates] == list(GATE_ORDER)


def test_the_report_can_be_read_by_a_machine(tmp_path):
    spec = fully_cited(tmp_path)
    report = validate_spec(spec)
    body = report.as_json()
    assert body["ok"] is True
    assert body["spec_hash"] == report.spec_hash
    assert {gate["name"] for gate in body["gates"]} == set(GATE_ORDER)
    assert body["rendered"], "the rendered form is part of the report"


def test_the_report_is_bound_to_the_spec_revision_it_ran_on(tmp_path):
    """"It passed" must name the bytes that passed — nothing is cached (009-M0)."""
    import hashlib

    spec = fully_cited(tmp_path)
    report = validate_spec(spec)
    digest = hashlib.sha256(Path(spec.path).read_bytes()).hexdigest()[:12]
    assert report.spec_hash == digest
    assert f"spec sha256:{digest}" in report.render()[0]


def test_a_blocking_report_says_so_in_its_last_line(tmp_path):
    spec = fully_cited(tmp_path)
    report = validate_spec(spec, benchmark=True)  # no target ⇒ undecidable
    assert report.render()[-1].startswith("verdict: STOPPED")
