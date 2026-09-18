"""Block template / board spec schema and parameter constraints (task 008a, item 1).

The template format only earns its keep if it is *strict*: a field the reader
ignores is a field the writer thinks is doing something. These tests pin the
three rules that make that true — unknown keys are an error, an unknown
constraint is an error, and a parameter's value is checked against its
constraint at every place it can enter (the template's default and the spec's
assignment).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.blocks import (
    BLOCK_TEMPLATE_KIND,
    BOARD_SPEC_KIND,
    CONSTRAINTS,
    BlockError,
    SCHEMA_VERSION,
    check_constraint,
    load_block_template,
    load_board_spec,
    net_class_of,
    template_from_json,
    template_to_json,
)

ROOT = Path(__file__).resolve().parents[1]
BLOCKS = ROOT / "blocklib" / "blocks"
SPEC = ROOT / "blocklib" / "specs" / "ch340g_usb_uart.json"

COMMITTED_BLOCKS = sorted(BLOCKS.glob("*.json"))


def minimal_template(**overrides) -> dict:
    """The smallest valid template: one symbol, one part, one wire, one port."""
    body = {
        "kind": BLOCK_TEMPLATE_KIND,
        "version": SCHEMA_VERSION,
        "name": "tiny",
        "description": "",
        "provenance": {"kind": "textbook", "source": "hand", "designators": ["R1"], "note": ""},
        "origin_file": [0.0, 0.0],
        "bbox_file": [0.0, 0.0, 100.0, 100.0],
        "notes": [],
        "interface": [
            {"role": "IN", "net": "IN", "net_class": "signal", "position": [0.0, 0.0]}
        ],
        "params": [
            {"name": "r1_value", "role": "R1 value", "default": "10k", "constraint": "resistor_value"}
        ],
        "symbols": {
            "sym1": {
                "offsets": {"1": [0.0, 0.0], "2": [20.0, 0.0]},
                "body": [0.0, -5.0, 20.0, 5.0],
                "pin_names": {"1": "a", "2": "b"},
            }
        },
        "components": [
            {
                "ref": "R1",
                "symbol": "sym1",
                "placement": {"x": 10.0, "y": 10.0, "rotation": 0.0, "mirror": False},
                "device": {"lcsc": "C1", "name": "Res_0402"},
                "footprint": "0402",
                "params": {"value": "r1_value"},
                "pins": [
                    {"number": "1", "name": "a", "net": "IN"},
                    {"number": "2", "name": "b", "net": "OUT"},
                ],
            }
        ],
        "geometry": {
            "wires": [{"net": "IN", "points": [[0.0, 0.0], [20.0, 0.0]]}],
            "flags": [],
            "labels": [{"net": "IN", "x": 0.0, "y": 0.0, "rotation": 0.0}],
        },
    }
    body.update(overrides)
    return body


def test_the_committed_block_library_is_readable():
    assert len(COMMITTED_BLOCKS) >= 4, sorted(p.name for p in COMMITTED_BLOCKS)
    for path in COMMITTED_BLOCKS:
        template = load_block_template(path)
        assert template.components, path
        assert template.symbols, path
        # A block that cannot be re-read is not a template.
        assert template_from_json(template_to_json(template)).name == template.name


def test_json_round_trip_is_lossless():
    """Serialise -> read -> serialise must be a fixed point, field for field."""
    for path in COMMITTED_BLOCKS:
        original = json.loads(path.read_text(encoding="utf-8"))
        once = template_to_json(load_block_template(path))
        twice = template_to_json(template_from_json(once))
        assert once == twice, path


def test_unknown_keys_are_rejected():
    """A silently ignored field is a field the author believes is working."""
    with pytest.raises(BlockError, match="unknown key"):
        template_from_json(minimal_template(extra=1))
    body = minimal_template()
    body["components"][0]["oops"] = True
    with pytest.raises(BlockError, match="unknown key"):
        template_from_json(body)


def test_the_retired_level_shifter_flag_is_an_unknown_key():
    """``level_shifter`` was deleted, and its key must not quietly come back.

    The flag let a block declare itself licensed to bridge two IO domains on one
    net, which only ever let real mix-ups through (M0-P0c, 2026-09-18). Leaving
    the key accepted would let an author write it, believe it still does
    something, and get no signal — so it is an unknown key on purpose.
    """
    with pytest.raises(BlockError, match="unknown key"):
        template_from_json(minimal_template(level_shifter=True))


def test_the_kind_and_version_are_checked():
    with pytest.raises(BlockError, match="kind"):
        template_from_json(minimal_template(kind="something-else"))
    with pytest.raises(BlockError, match="version"):
        template_from_json(minimal_template(version=SCHEMA_VERSION + 1))


def test_an_unknown_constraint_is_an_error_not_a_no_op():
    body = minimal_template()
    body["params"][0]["constraint"] = "resistor_val"  # a typo
    with pytest.raises(BlockError, match="unknown constraint"):
        template_from_json(body)
    # and the registry refuses to answer for a name it does not own, because
    # "no constraint" and "constraint that checks nothing" must not be the
    # same answer
    with pytest.raises(BlockError):
        check_constraint("not_a_constraint", "anything")


def test_a_parameter_default_must_pass_its_own_constraint():
    body = minimal_template()
    body["params"][0]["default"] = "banana"
    with pytest.raises(BlockError, match="not a resistor"):
        template_from_json(body)


@pytest.mark.parametrize(
    "constraint,value,ok",
    [
        ("resistor_value", "10k", True),
        ("resistor_value", "4R7", True),
        ("resistor_value", "2.2kΩ", True),
        ("resistor_value", "100nF", False),
        ("resistor_value", "", False),
        ("capacitor_value", "100nF", True),
        ("capacitor_value", "30pF", True),
        ("capacitor_value", "1uF", True),
        ("capacitor_value", "5.1K", False),
        ("capacitor_value", "100", False),
        ("frequency", "12MHz", True),
        ("frequency", "", False),
        ("free_text", "", True),
        ("free_text", "anything at all", True),
    ],
)
def test_the_constraint_registry_checks_what_it_claims(constraint, value, ok):
    assert (check_constraint(constraint, value) is None) is ok
    assert constraint in CONSTRAINTS


def test_a_component_binding_must_name_a_parameter_of_its_block():
    body = minimal_template()
    body["components"][0]["params"] = {"value": "nope"}
    with pytest.raises(BlockError, match="not a parameter of this block"):
        template_from_json(body)


def test_a_pin_must_belong_to_its_symbol():
    body = minimal_template()
    body["components"][0]["pins"].append({"number": "9", "name": "x", "net": "IN"})
    with pytest.raises(BlockError, match="has no offset"):
        template_from_json(body)


def test_net_class_is_derived_from_the_board_not_from_the_name():
    assert net_class_of("GND", {}) == "gnd"
    assert net_class_of("AGND", {}) == "gnd"
    assert net_class_of("+5V", {"+5V": "Power"}) == "power"
    assert net_class_of("VCC", {"VCC": "Power"}) == "power"
    # a rail nobody flagged is a signal by this rule, which is the honest answer
    assert net_class_of("+5V", {}) == "signal"
    assert net_class_of("RX", {}) == "signal"


def test_the_board_spec_loads_and_resolves_its_templates():
    spec = load_board_spec(SPEC)
    assert spec.name and spec.blocks
    assert {b.id for b in spec.blocks} == {"usb", "power", "core", "uart"}
    for block in spec.blocks:
        assert Path(block.template_path).is_file()
        assert block.template.name.startswith("ch340")
    # every connection names a real port of a real block, both directions
    for connection in spec.connections:
        for block_id, role in connection.ports:
            block = spec.instance(block_id)
            assert block is not None
            assert block.template.port(role) is not None


def test_the_spec_states_every_number_it_uses():
    """The CH340 spec sets every parameter its blocks declare.

    Not a general rule (a spec may rely on defaults) but a property of this
    spec: it exists to demonstrate the parameter layer, and a design that
    silently depends on a template default is not fully stated.
    """
    spec = load_board_spec(SPEC)
    declared = {
        f"{block.id}.{param.name}"
        for block in spec.blocks
        for param in block.template.params
    }
    assert set(spec.params) == declared, sorted(declared ^ set(spec.params))


def test_a_spec_parameter_must_name_a_real_block_and_parameter():
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    raw["params"]["nosuchblock.x"] = "1"
    path = SPEC.parent / "_bad_param.json"
    try:
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(BlockError, match="no block"):
            load_board_spec(path)
    finally:
        path.unlink(missing_ok=True)


def test_a_spec_parameter_value_is_checked_against_its_constraint():
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    raw["params"]["usb.r24_value"] = "not a resistor"
    path = SPEC.parent / "_bad_value.json"
    try:
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(BlockError, match="not a resistor"):
            load_board_spec(path)
    finally:
        path.unlink(missing_ok=True)


def test_a_connection_needs_two_ports():
    """One port is not a connection — that is an unconnected interface."""
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    raw["connections"][0]["ports"] = [["usb", "GND"]]
    path = SPEC.parent / "_bad_conn.json"
    try:
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(BlockError, match="at least two ports"):
            load_board_spec(path)
    finally:
        path.unlink(missing_ok=True)


def test_a_connection_to_an_unknown_port_is_refused():
    raw = json.loads(SPEC.read_text(encoding="utf-8"))
    raw["connections"][0]["ports"][1] = ["usb", "NOPE"]
    path = SPEC.parent / "_bad_port.json"
    try:
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(BlockError, match="has no port"):
            load_board_spec(path)
    finally:
        path.unlink(missing_ok=True)


def test_the_spec_kind_is_checked_so_a_template_cannot_be_passed_as_a_spec():
    path = COMMITTED_BLOCKS[0]
    with pytest.raises(BlockError, match=BOARD_SPEC_KIND):
        load_board_spec(path)
