"""Voltage is a quantity too: the power-tree gate must read it (issue #53).

``engines/validate_spec.py``'s power-tree gate asked one sink port
``port.voltage != source.voltage`` — the two **strings**, with no
normalisation. So a source declaring ``3V3`` and a sink declaring ``3.3V``,
which is one rail written the two ways, came out as a VIOLATION, and a
VIOLATION stops the board at gate four. The pair is not hypothetical: this
repository writes both. ``blocklib/blocks.portmeta.json`` declares the CH340's
VCC rail as ``"voltage": "3V3"``, and ``3.3V`` is what a person types.

The direction is fail-closed (a mis-rejection, never a false pass), which is
why this went unnoticed: nothing was let through that should not have been. It
is the same defect as #51 and #52 — *one quantity, one implementation* (071 §2)
— in a third module, and the fix is the same one: the reading moves to
``rules/values.py`` as :func:`parse_voltage_volts` and the gate compares
numbers.

What this file pins:

* the parser itself, **both ways** — every spelling the sidecar and an editor
  produce, and every refusal, because a gate that is handed a string it cannot
  read must fall back rather than guess;
* the gate, on the five shapes the issue reported: one rail two ways is a pass,
  two rails is still a VIOLATION, and a spelling neither side can read keeps
  the *old* string verdict (fail-closed, unchanged behaviour);
* the message still quotes what the file says — normalising it to ``3.3`` would
  repair the evidence instead of the board;
* the committed CH340 board, re-declared in memory with the sink written
  ``3.3V`` against the sidecar's ``3V3``: the issue's acceptance form, on the
  repository's own page.

Sections for issues #51 and #52 live in ``evidence/083/pending_51_52/`` rather
than here. Both were written, both pass (127 tests green with the fix applied),
and neither can land yet: ``core/`` may not import ``rules/`` at *any* depth —
``tests/test_layer_rules.py`` walks every import node in the package, and a
function-local import is exactly the shape its docstring says it was written to
catch. That decision is not this batch's to make; see ``evidence/083/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.blocks import (
    BLOCK_TEMPLATE_KIND,
    SCHEMA_VERSION,
    load_board_spec,
)
from boardwise.core.portmeta import port_meta_from_json
from boardwise.engines.validate_spec import FAIL, PASS, _gate_power_tree, validate_spec
from boardwise.rules.values import parse_voltage_volts

ROOT = Path(__file__).resolve().parents[1]
CH340_SPEC = ROOT / "blocklib" / "specs" / "ch340g_usb_uart.json"
PORT_META = ROOT / "blocklib" / "blocks.portmeta.json"


# --------------------------------------------------------------------------
# the parser
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "volts"),
    [
        ("3.3V", 3.3),
        ("3.3", 3.3),
        ("3.30V", 3.3),  # trailing zeros are the same voltage
        ("3.3 V", 3.3),  # the unit may stand off the number
        ("3.3v", 3.3),
        ("5V", 5.0),
        ("12V", 12.0),
        ("3V3", 3.3),  # the mid-letter notation, in volts: the sidecar's own
        ("1V8", 1.8),
        ("3v3", 3.3),
        ("5V0", 5.0),
        ("+24V", 24.0),  # a sign is part of the field, not decoration
        ("-12V", -12.0),
        ("+3.3", 3.3),
        ("0.05", 0.05),
        (" 5V ", 5.0),
    ],
)
def test_a_voltage_is_read_in_volts(text, volts):
    assert parse_voltage_volts(text) == pytest.approx(volts)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "V",
        "5V3V",
        "3V3V",  # a doubled unit is not a voltage
        "5 V 1",
        "5V 1A",  # a current is not a voltage
        "12VDC",
        "3.3.3",
        "V3",  # no mantissa: the rule the mid-letter grammar already states
        "0V5",  # not a significant figure, the same rule as 0K1
        "3V123",  # a three-digit fraction is the shunt form, not a voltage
        "1" * 100 + "V",  # over the length cap (issue #27)
        None,
    ],
)
def test_a_voltage_this_cannot_state_is_refused(text):
    assert parse_voltage_volts(text) is None


def test_the_two_grammars_do_not_both_read_one_string():
    """The property the pattern's shape exists for: the mid-letter branch
    *requires* a fraction after the ``V``, so ``3V`` is the suffix grammar's
    alone and every string has exactly one reading. The capacitance parser
    states the same split for the same reason — a new grammar must be additive,
    never a second opinion on a string the first one already read."""
    for text, volts in (("3V", 3.0), ("3V3", 3.3), ("30V", 30.0), ("30V0", 30.0)):
        assert parse_voltage_volts(text) == pytest.approx(volts)


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------


def _power_spec(tmp_path, first: dict, second: dict):
    """Two blocks on one ``VCC`` net: the source's port metadata, then the
    sink's. The shape is the committed board's (one net, one source, one sink)
    with the two voltage strings as the only thing that varies."""

    def port(role: str, **fields) -> dict:
        body = {"role": role, "net": role, "net_class": "power", "position": [0.0, 0.0]}
        body.update(fields)
        return body

    def template_body(name: str, ports: list[dict]) -> dict:
        return {
            "kind": BLOCK_TEMPLATE_KIND,
            "version": SCHEMA_VERSION,
            "name": name,
            "description": "",
            "provenance": {
                "kind": "textbook",
                "source": "hand",
                "designators": ["R1"],
                "note": "",
            },
            "origin_file": [0.0, 0.0],
            "bbox_file": [0.0, 0.0, 100.0, 100.0],
            "notes": [],
            "interface": list(ports),
            "params": [],
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
                    "params": {},
                    "pins": [
                        {"number": "1", "name": "a", "net": "A"},
                        {"number": "2", "name": "b", "net": "A"},
                    ],
                }
            ],
            "geometry": {
                "wires": [{"net": "A", "points": [[0.0, 0.0], [20.0, 0.0]]}],
                "flags": [],
                "labels": [],
            },
        }

    root = Path(tmp_path)
    for name, ports in (("ta", [port("A", **first)]), ("tb", [port("A", **second)])):
        (root / f"{name}.json").write_text(
            json.dumps(template_body(name, ports)), encoding="utf-8"
        )
    spec_path = root / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "kind": "boardwise-board-spec",
                "version": 1,
                "name": "t",
                "description": "",
                "provenance": {"kind": "textbook", "source": "hand", "note": ""},
                "sheet": {"attrs": {}, "origin": [0.0, 0.0]},
                "blocks": [
                    {"id": "a", "template": "ta.json", "at": [0.0, 0.0]},
                    {"id": "b", "template": "tb.json", "at": [0.0, 0.0]},
                ],
                "connections": [{"net": "VCC", "ports": [["a", "A"], ["b", "A"]]}],
                "params": {},
            }
        ),
        encoding="utf-8",
    )
    return load_board_spec(spec_path)


@pytest.mark.parametrize(
    ("source", "sink"),
    [
        ("3V3", "3.3V"),  # the issue's first row, and the sidecar's own pair
        ("3.3V", "3V3"),
        ("5V", "5.0V"),
        ("3.3", "3.3V"),
        ("3.30V", "3.3"),
        ("+12V", "12V"),
        ("3.3 V", "3.3V"),
        ("3V3", "3V3"),  # the shipped spelling against itself still passes
    ],
)
def test_one_rail_written_two_ways_is_not_a_voltage_mismatch(tmp_path, source, sink):
    spec = _power_spec(
        tmp_path,
        {"direction": "source", "voltage": source},
        {"direction": "sink", "voltage": sink},
    )
    gate = _gate_power_tree(spec)
    assert not gate.violations, [f.message for f in gate.findings]
    assert gate.status == PASS


@pytest.mark.parametrize(
    ("source", "sink"),
    [
        ("3.3V", "5V"),  # genuinely two rails
        ("3V3", "3.6V"),
        ("5V", "5.1V"),
        ("+12V", "-12V"),  # a sign is not decoration
        ("12V", "12.1V"),
    ],
)
def test_two_rails_are_still_a_violation(tmp_path, source, sink):
    spec = _power_spec(
        tmp_path,
        {"direction": "source", "voltage": source},
        {"direction": "sink", "voltage": sink},
    )
    gate = _gate_power_tree(spec)
    assert gate.status == FAIL
    assert "voltage-match" in {f.rule for f in gate.findings}


@pytest.mark.parametrize(
    ("source", "sink"),
    [
        ("5V", "5VDC"),  # neither side readable -> the string is the whole of it
        ("5V", "5 V DC"),
        ("rail-a", "rail-b"),
        ("5V", "abc"),
        ("5V", "5V 1A"),
    ],
)
def test_a_voltage_neither_parser_reads_keeps_the_old_string_verdict(
    tmp_path, source, sink
):
    """The fail-closed direction, stated as a test. Delegating to a parser must
    not hand the gate a new way to call two unmatched strings equal, and must
    not make it declare itself *undecidable* over a spelling it has no better
    word for — undecidable would change which finding a reader sees, and the
    behaviour before the fix was a plain violation. Unreadable is compared as
    written, which is what it did before."""
    spec = _power_spec(
        tmp_path,
        {"direction": "source", "voltage": source},
        {"direction": "sink", "voltage": sink},
    )
    gate = _gate_power_tree(spec)
    assert gate.status == FAIL
    assert "voltage-match" in {f.rule for f in gate.findings}


def test_an_unreadable_voltage_against_itself_is_not_a_violation(tmp_path):
    spec = _power_spec(
        tmp_path,
        {"direction": "source", "voltage": "5VDC"},
        {"direction": "sink", "voltage": "5VDC"},
    )
    assert _gate_power_tree(spec).status == PASS


def test_the_violation_reports_the_strings_as_they_were_written(tmp_path):
    """The message is for a person reading a file: normalising it to ``3.3``
    would hide which of the two spellings is in it, and the fix would be
    repairing the evidence instead of the board."""
    spec = _power_spec(
        tmp_path,
        {"direction": "source", "voltage": "3V3"},
        {"direction": "sink", "voltage": "5.0"},
    )
    (finding,) = _gate_power_tree(spec).violations
    assert "'5.0'" in finding.message and "'3V3'" in finding.message
    assert finding.evidence == ["sink: 5.0", "source: 3V3"]


def test_the_other_power_tree_findings_are_untouched(tmp_path):
    """The gate has three questions and this fix touches one. A source that
    says no voltage, and a sink that says no voltage, are still *undecidable* —
    "this is not a pass" is the whole point of them, and a normalisation step
    is not an excuse to retire either."""
    no_source_voltage = _gate_power_tree(
        _power_spec(
            tmp_path, {"direction": "source"}, {"direction": "sink", "voltage": "3V3"}
        )
    )
    assert "cannot be checked" in no_source_voltage.undecidables[0].message
    no_sink_voltage = _gate_power_tree(
        _power_spec(
            tmp_path, {"direction": "source", "voltage": "3V3"}, {"direction": "sink"}
        )
    )
    assert no_sink_voltage.status != PASS
    assert no_sink_voltage.undecidables


# --------------------------------------------------------------------------
# the real board, with the sidecar's own spelling on one side
# --------------------------------------------------------------------------


def _ch340_with_sink_voltage(voltage: str):
    """The committed CH340 spec, with the CH340 core's VCC sink re-declared.

    The sidecar is read and copied, never edited on disk: the shipped file
    writes ``3V3`` on both ends, and the point of this test is the
    hand-maintained variant — the same rail, one endpoint typed the way a person
    types it.
    """
    raw = json.loads(PORT_META.read_text(encoding="utf-8"))
    raw["blocks"]["ch340_core"]["ports"]["VCC"]["voltage"] = voltage
    return load_board_spec(
        CH340_SPEC, port_meta=port_meta_from_json(raw, where="mutated-sidecar")
    )


def test_the_committed_sidecar_still_declares_the_rail_in_mid_letter():
    """Guard the premise: if this ever changes, the two tests below stop being
    about ``3V3`` vs ``3.3V`` and quietly become about nothing."""
    raw = json.loads(PORT_META.read_text(encoding="utf-8"))
    assert raw["blocks"]["ch340_power_3v3"]["ports"]["VCC"]["voltage"] == "3V3"
    assert raw["blocks"]["ch340_core"]["ports"]["VCC"]["voltage"] == "3V3"


def test_the_ch340_rail_passes_when_the_sink_is_written_3_3v():
    """The issue's acceptance form, on the repository's own board: the
    ``ch340_power_3v3`` source declares ``3V3`` and the CH340 core's sink is
    declared ``3.3V``. Before the fix that was a VIOLATION on a rail that is
    wired correctly, and ``validate --spec`` printed STOPPED."""
    report = validate_spec(_ch340_with_sink_voltage("3.3V"))
    gate = report.gate("power-tree")
    assert gate.status == PASS, [f.message for f in gate.findings]
    assert report.ok


def test_the_same_board_with_a_genuinely_wrong_sink_voltage_still_fails():
    gate = validate_spec(_ch340_with_sink_voltage("3.6V")).gate("power-tree")
    assert gate.status == FAIL
    assert "voltage-match" in {f.rule for f in gate.findings}
