"""One quantity, one implementation — compare, blocks, and the power tree (083).

Three modules had each grown their **own** answer to "what does this value
mean", and each of the three carried bugs the repository had already fixed
somewhere else. The same defect, three times, in the same direction: 071 §2
("one verdict has one implementation") is a rule about the *authoritative*
parser existing once, and it does not stop a second copy from being written
next to it.

* **#51** — ``core/compare.py`` carried a private grammar that read neither
  the trade's mid-letter spelling nor floating-point equality, so ``4K7`` vs
  ``4700`` (one 4.7 kΩ resistor) and ``0.1uF`` vs ``100nF`` (one 100 nF
  capacitor) were both reported as value differences. The false direction is
  the expensive one: ``compare`` is the referee for "are these two netlists the
  same board", and ``engines/draw.py`` runs it as an acceptance check on a
  candidate that was just drawn.
* **#52** — ``core/blocks.py`` carried a third value grammar for its parameter
  constraints, so a block template whose default was written ``4K7`` — the
  spelling every rule in this repository reads — failed to load. Note the
  refusal was fail-closed, so the cost was a mis-rejection, not a false pass.
* **#53** — ``engines/validate_spec.py``'s power-tree gate compared two volt
  spellings *as strings*, so a ``3V3`` source and a ``3.3V`` sink on one rail
  produced a VIOLATION. The repository writes both: the committed sidecar
  (``blocklib/blocks.portmeta.json``) declares the CH340's VCC rail as
  ``3V3``, and ``3.3V`` is what most people type.

All three now read :mod:`boardwise.core.values`, which is where those parsers
live since 083 moved them down out of ``rules/``. The move is what made #51 and
#52 possible at all: ``core`` may not import ``rules`` (006c's executable
layering, ``tests/test_layer_rules.py``), so a parser that ``core`` has to use
has to sit below it. ``boardwise.rules.values`` is still importable and still
answers — it is a forwarding shim, and
:func:`test_the_shim_answers_for_every_name_the_repository_imports` is what
keeps that true.

What each file pins:

* the delegations themselves, at the level the defect was reported at —
  ``values_equal``, ``check_constraint``, the power-tree gate;
* the **refusals**, which are the half a fix like this usually loses: a
  multi-token value, a lowercase ``m``, a unit-less capacitor, ``5.1K`` as a
  capacitance, an empty parameter, a voltage neither parser reads;
* the #52 divergence matrix as a regression net — the spellings the old
  constraint accepted must still load, because delegating to a parser that is
  narrower on one axis (``1G``, ``1meg``, a bare ``1F``) would turn a repair
  into a regression.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.blocks import (
    BLOCK_TEMPLATE_KIND,
    SCHEMA_VERSION,
    BlockError,
    check_constraint,
    load_board_spec,
    template_from_json,
)
from boardwise.core.compare import compare_models, values_equal
from boardwise.core.portmeta import port_meta_from_json
from boardwise.core.values import parse_voltage_volts
from boardwise.engines.validate_spec import FAIL, PASS, _gate_power_tree, validate_spec
from boardwise.parsers.schematic import build_schematic_model

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = Path(__file__).parent / "fixtures" / "ch340_golden.epro2"
CH340_SPEC = ROOT / "blocklib" / "specs" / "ch340g_usb_uart.json"
PORT_META = ROOT / "blocklib" / "blocks.portmeta.json"

# --------------------------------------------------------------------------
# #51 — compare delegates its value grammar
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("golden", "candidate"),
    [
        ("4K7", "4700"),  # the issue's first row: one resistor, two spellings
        ("4K7", "4.7k"),
        ("4k7", "4.7kΩ"),
        ("4u7", "4.7uF"),  # the capacitance half of the same notation
        ("2M2", "2.2M"),
        ("1M0", "1M"),
        ("0.1uF", "100nF"),  # issue #39's float tail, now inherited
        ("1kΩ", "1000"),
        ("4R7", "4.7"),
        ("10k", "10K"),  # compare's own case-insensitive step (bom has none)
    ],
)
def test_two_spellings_of_one_value_are_equal(golden, candidate):
    assert values_equal(golden, candidate) is True


@pytest.mark.parametrize(
    ("golden", "candidate"),
    [
        ("4K7", "4.8k"),  # genuinely two resistors
        ("100nF", "220nF"),
        ("100Ω", "100nF"),  # same number, two kinds: the kind travels with it
        ("10Ω", "10uF"),
        # Same number, different kind — the only shape that can catch a
        # comparison that checks the number and forgets what it is a number
        # *of*. 1 mΩ and 1 mF are both 0.001, and they are not one part.
        ("1m", "1mF"),
        ("0.001", "1mF"),
        ("472M", "472M 1KV"),  # multi-token degrades to string comparison
        ("22u", "22uF"),  # a capacitor with no unit is not a capacitance
        ("10H", "10"),  # a henry is not a quantity this repository reads
        ("abc", "10k"),
        ("4K7", ""),
    ],
)
def test_two_values_that_are_not_one_value_are_not_equal(golden, candidate):
    assert values_equal(golden, candidate) is False


def test_a_lowercase_m_is_read_as_milliohms_and_still_never_matches_10k():
    """The old grammar blacklisted ``m`` because it means milli on a resistor
    and micro on an old capacitor marking. The kind now settles it
    structurally: the capacitance grammar requires its farad unit, so ``10m``
    is 10 milliohms and only that. What must not come back is a *false
    equality* — 0.01 Ω is not 10 kΩ, and that was 005's own pinned answer."""
    assert values_equal("10m", "10000") is False
    assert values_equal("10m", "0.01") is True
    assert values_equal("10m", "10uF") is False  # 0.01 Ω is not 10 µF


def test_a_candidate_that_only_respells_a_value_is_not_a_design_difference():
    """The issue's own reproduction, one level up: a candidate that writes its
    values in the trade's notation (``5.1K`` -> ``5K1``, ``1kΩ`` -> ``1K0``,
    ``100nF`` -> ``0.1uF``) is the same board, and ``compare_models`` is what
    ``boardwise compare`` and ``engines/draw.py`` ask."""
    golden = build_schematic_model(GOLDEN)
    candidate = build_schematic_model(GOLDEN)
    respelled = {}
    for designator, component in candidate.components.items():
        value = component.value
        for old, new in (("100nF", "0.1uF"), ("5.1K", "5K1"), ("1kΩ", "1K0")):
            if value == old:
                component.value = new
                respelled[designator] = (old, new)
    assert len(respelled) >= 3, respelled
    report = compare_models(golden, candidate)
    assert not report.component_differences, report.render()
    assert report.is_empty


def test_a_candidate_with_a_different_value_is_still_reported():
    """The other half: delegation must not turn the referee mute. ``220nF``
    and a respelled ``5.2K`` are different parts, and a real difference
    outranks a spelling."""
    golden = build_schematic_model(GOLDEN)
    candidate = build_schematic_model(GOLDEN)
    for component in candidate.components.values():
        if component.value == "100nF":
            component.value = "220nF"
        elif component.value == "5.1K":
            component.value = "5.2K"  # one notch up: 5.2 k, not 5.1 k
    report = compare_models(golden, candidate)
    subjects = {d.subject for d in report.component_differences}
    assert {"C1", "R24", "R27"} <= subjects, subjects


def test_a_resistor_respelled_in_mid_letter_is_not_a_design_difference():
    """``5K1`` is 5.1 kΩ and ``1K0`` is 1 kΩ: the same parts, written the way
    the trade writes them. Before #51 each of these was a reported difference —
    a false difference, on a board that is the same board."""
    golden = build_schematic_model(GOLDEN)
    candidate = build_schematic_model(GOLDEN)
    respelled = 0
    for component in candidate.components.values():
        whole, dot, tail = component.value.partition(".")
        if dot and tail == "1K":
            component.value = f"{whole}K1"
            respelled += 1
    assert respelled, "the fixture must contain a 5.1K resistor to respell"
    report = compare_models(golden, candidate)
    assert not report.component_differences, report.render()


# --------------------------------------------------------------------------
# #52 — the block parameter constraints delegate
# --------------------------------------------------------------------------


def _template_with_param(constraint: str, default: str) -> None:
    """Load a template whose one parameter defaults to ``default``."""
    body = {
        "kind": BLOCK_TEMPLATE_KIND,
        "version": SCHEMA_VERSION,
        "name": "t",
        "description": "",
        "provenance": {
            "kind": "textbook",
            "source": "hand",
            "designators": ["R1"],
            "note": "",
        },
        "origin_file": [0.0, 0.0],
        "bbox_file": [0.0, 0.0, 10.0, 10.0],
        "notes": [],
        "interface": [],
        "params": [
            {
                "name": "r1_value",
                "role": "R1 value",
                "default": default,
                "constraint": constraint,
            }
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
            "labels": [],
        },
    }
    template_from_json(body, where="t")


@pytest.mark.parametrize(
    ("constraint", "value"),
    [
        # the issue's acceptance row
        ("resistor_value", "4K7"),
        ("resistor_value", "1M0"),
        ("resistor_value", "2M2"),
        ("resistor_value", "4R7"),
        ("capacitor_value", "4u7"),
        ("capacitor_value", "2n2"),
        ("capacitor_value", "5p1"),
        ("capacitor_value", "10uF"),
        # and the spellings the old grammar already had
        ("resistor_value", "10k"),
        ("resistor_value", "2.2kΩ"),
        ("resistor_value", "470"),
        ("resistor_value", "0.1"),
        ("resistor_value", "10kohm"),
        ("resistor_value", "0R01"),
        ("capacitor_value", "100nF"),
        ("capacitor_value", "1mF"),
        ("capacitor_value", "22pF"),
    ],
)
def test_a_mid_letter_default_loads(constraint, value):
    """The defect, as it was reported: ``BlockError: t.params[2].default is not
    a resistor value: '4K7'`` on a value every rule in the repository reads."""
    assert check_constraint(constraint, value) is None
    _template_with_param(constraint, value)


@pytest.mark.parametrize(
    ("constraint", "value", "expected"),
    [
        ("resistor_value", "abc", "is not a resistor value: 'abc'"),
        ("resistor_value", "", "is empty; a resistor value is required"),
        ("resistor_value", "   ", "is empty; a resistor value is required"),
        ("resistor_value", "banana", "is not a resistor value: 'banana'"),
        ("resistor_value", "100nF", "is not a resistor value: '100nF'"),
        ("capacitor_value", "abc", "is not a capacitor value: 'abc'"),
        ("capacitor_value", "", "is empty; a capacitor value is required"),
        # the constraint that gave the capacitance grammar its rationale: the
        # farad unit is what tells 5.1 k from 100 n, and it stays required
        ("capacitor_value", "5.1K", "is not a capacitor value: '5.1K'"),
        ("capacitor_value", "100", "is not a capacitor value: '100'"),
        ("capacitor_value", "4u7", None),  # the mid-letter form IS the unit
    ],
)
def test_a_constraint_still_refuses_what_it_always_refused(constraint, value, expected):
    assert check_constraint(constraint, value) == expected


def test_a_mistyped_default_is_still_a_load_error():
    """The constraint is a load-time check, not only a registry call: the
    error has to reach whoever wrote the JSON."""
    with pytest.raises(BlockError, match="not a resistor"):
        _template_with_param("resistor_value", "banana")


# --------------------------------------------------------------------------
# #52 — the divergence matrix, as a regression net
# --------------------------------------------------------------------------
#
# Measured before the fix (evidence/083/divergence_matrix_before.txt): the old
# grammar and the authoritative parser disagreed in both directions, and each
# direction costs something. Rejecting what the old grammar accepted (below)
# would turn #52 into a regression — a spelling a template was allowed to say
# would become a load error because the parser happens to be narrower. So the
# delegation is paired with a named supplementary pattern for exactly these,
# and this block is what keeps that pairing honest.


@pytest.mark.parametrize(
    "value",
    [
        "1G",  # a gigaohm: SI, and the old grammar's prefix table held G
        "1meg",  # the same prefix spelled out, also held before
        "10 kΩ",  # a space before the unit
        "2.2 kOhm",
        "4.7K",
        "100R",  # mid-letter R, which the old grammar did *not* have
        "R010",  # the leading-R spelling
        "4K7Ω",  # notation plus unit
    ],
)
def test_a_resistor_spelling_the_parser_does_not_read_still_loads(value):
    assert check_constraint("resistor_value", value) is None


@pytest.mark.parametrize("value", ["1F", "1f", "2.7F", "5.1KF", "1 kF"])
def test_a_capacitor_spelling_the_parser_does_not_read_still_loads(value):
    """A bare farad is a supercapacitor's own unit, and the old grammar's
    ``k`` before ``F`` was accepted too. Both are outside the pinned parser
    grammar (078/079 closed that on purpose), and refusing them would be a
    regression of the same shape as #52 itself."""
    assert check_constraint("capacitor_value", value) is None


@pytest.mark.parametrize("value", ["1G2", "0K1", "1.2.3", "1e3", "4K7 2"])
def test_a_resistor_neither_side_reads_is_still_refused(value):
    assert check_constraint("resistor_value", value) is not None


@pytest.mark.parametrize("value", ["1F2", "0F1", "5.1K", "1F 1", "1e-9"])
def test_a_capacitor_neither_side_reads_is_still_refused(value):
    assert check_constraint("capacitor_value", value) is not None


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


# --------------------------------------------------------------------------
# the move itself: boardwise.rules.values is a shim, and it answers
# --------------------------------------------------------------------------
#
# 083 moved the implementation to boardwise.core/values.py and left a forwarding
# shim at boardwise/rules/values.py, because #51 and #52 need the parsers from
# inside core and 006c's layering forbids core importing rules. The shim is
# only worth having if it is *total*: a name that resolves today and stops
# resolving is an ImportError in somebody's test at 3am, not a warning. These
# are the names the repository actually imports (the census is
# evidence/083/import_surface.txt, walked by evidence/083/probe_import_surface.py).


def test_the_shim_answers_for_every_name_the_repository_imports():
    from boardwise.rules import values as shim

    for name in (
        "ANCHOR_E96_LETTER",
        "ANCHOR_MID_LETTER",
        "ANCHOR_PACKAGE_CONTEXT",
        "decode_eia_3digit",
        "mpn_resistance_candidates",
        "mpn_resistance_readings",
        "mpn_value_code",
        "mpn_value_code_anchor",
        "parse_capacitance_farads",
        "parse_resistance_ohms",
        "parse_voltage_volts",
    ):
        assert getattr(shim, name) is not None, name
        assert name in shim.__all__, f"{name} is imported but not promised"


def test_the_shim_re_exports_the_implementation_not_a_copy_of_it():
    """Two objects would be two implementations wearing one name: a value
    parsed through the shim and the same value parsed through core would be
    parsed by different code, and the next fix would land on one of them."""
    from boardwise.core import values as implementation
    from boardwise.rules import values as shim

    for name in shim.__all__:
        assert getattr(shim, name) is getattr(implementation, name), name
    assert shim.parse_capacitance_farads("100nF") == implementation.parse_capacitance_farads(
        "100nF"
    )


def test_a_private_name_still_reaches_through_the_shim():
    """``tests/test_011d_rules.py`` stubs ``_too_long`` and widens
    ``_MAX_DECODED_CHARS`` on this module, and 078/079's reasoning is written
    about ``_without_leading_size``. A star import does not bind any of them,
    which is what the module ``__getattr__`` is for (PEP 562)."""
    from boardwise.core import values as implementation
    from boardwise.rules import values as shim

    assert shim._too_long is implementation._too_long
    assert shim._MAX_DECODED_CHARS == implementation._MAX_DECODED_CHARS == 64
    assert shim._without_leading_size is implementation._without_leading_size
    assert shim._too_long("x" * 100) is True


def test_a_set_on_the_shim_wins_over_the_implementation():
    """The other half of PEP 562: ``__getattr__`` runs only when normal lookup
    fails, so a monkeypatch on the shim still shadows the real name. That is
    what the rules' own tests do, and a shim that made patching impossible
    would have failed them rather than this."""
    from boardwise.rules import values as shim

    original = shim._too_long
    shim._too_long = lambda text: False
    try:
        assert shim._too_long("x" * 100) is False
    finally:
        shim._too_long = original
    assert shim._too_long is original


def test_a_name_nobody_defines_is_an_attribute_error_from_the_shim():
    """The shim does not invent names. It forwards, and a forwarding failure
    is the implementation's own error, which is the honest one."""
    from boardwise.rules import values as shim

    with pytest.raises(AttributeError):
        shim.parse_resistance_volts


def test_the_implementation_records_where_it_came_from():
    """The migration note is the only thing 083 changed inside the moved file,
    and it is the first thing a reader needs. If it ever rots away, the move
    becomes invisible — which is how a second copy grows back."""
    source = (ROOT / "src" / "boardwise" / "core" / "values.py").read_text(
        encoding="utf-8"
    )
    for marker in ("moved here in 083", "#51", "#52", "071 §2", "006c", "shim"):
        assert marker in source, marker
    shim_source = (ROOT / "src" / "boardwise" / "rules" / "values.py").read_text(
        encoding="utf-8"
    )
    assert "boardwise.core.values" in shim_source
    # A shim that still carried a parser would be a second implementation.
    assert "def parse_resistance_ohms" not in shim_source
    assert "def parse_capacitance_farads" not in shim_source
    assert "def parse_voltage_volts" not in shim_source
