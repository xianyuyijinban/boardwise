"""A block port's ``role`` is not a ball, and the pin check must not treat it as
one (issue #48, task 081).

Batch 4 turned gate 3 into a pin-level difference on the strength of one premise
that only holds for the test blocks: *"a port's `role` and a pin table's
`number` are both the ball's name"*. Every MCU block cut out of a real board
breaks it — those roles are net names and function names (`SPI_SCK`, `GND`,
`D+`) — so the difference was a functional name minus a set of balls, which is
never empty, and a **perfect** board came out DEFECT. Direction 2 had the mirror
fault: a function name looked up in a ball→net table never hits, so a ball the
firmware *does* use was reported as a pin the firmware has not grown into.

The rules this file pins, a+b1 as ruled:

* **a (the floor)** — a port with no ball evidence is *withheld* from the
  pin-level comparison and named in a note. Never a defect, and never an open
  question claiming the firmware has not grown into a ball nobody named.
* **b1 (the evidence)** — ``BlockPort.ball`` is the field a block author fills
  in to say "this port, on the package this template draws, is that ball". The
  loader refuses a value that is not spelled like a ball, because a function name
  in the one field that must not hold one is the same bug wearing a hat.

Both directions of gate 3 are covered from both ends: the withheld form (#48's
own reproduction) and the ball-named form (issue #35, which must not regress).
"""

from __future__ import annotations

import json

import pytest

from boardwise.core.blocks import (
    BLOCK_TEMPLATE_KIND,
    SCHEMA_VERSION,
    BlockConnection,
    BlockError,
    BlockInstance,
    BoardSpec,
    template_from_json,
    template_to_json,
)
from boardwise.core.pintable import pin_table_from_json
from boardwise.engines.pintable_check import (
    DEFECT,
    NOTE,
    OPEN_QUESTION,
    check_pin_table,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def mcu_block(*ports: tuple[str, str], symbol_pins: tuple[str, ...] = ("PA5", "PB6")):
    """An MCU block whose interface is exactly ``(role, ball)`` pairs.

    ``ball`` of ``""`` means the key is not written at all, which is the shape
    every block in the library has. The block goes through the loader, so these
    tests are also the round-trip test's starting point.
    """
    interface = []
    for role, ball in ports:
        port = {"role": role, "net": role, "net_class": "signal"}
        if ball:
            port["ball"] = ball
        interface.append(port)
    return template_from_json(
        {
            "kind": BLOCK_TEMPLATE_KIND,
            "version": SCHEMA_VERSION,
            "name": "mcu",
            "description": "",
            "provenance": {
                "kind": "textbook", "source": "hand", "designators": ["U1"], "note": "",
            },
            "origin_file": [0.0, 0.0],
            "bbox_file": [0.0, 0.0, 10.0, 10.0],
            "notes": [],
            "interface": interface,
            "params": [],
            "symbols": {
                "u": {
                    "offsets": {number: [0.0, 0.0] for number in symbol_pins},
                    "body": [0.0, 0.0, 5.0, 5.0],
                    "pin_names": {number: number for number in symbol_pins},
                }
            },
            "components": [
                {
                    "ref": "U1", "symbol": "u",
                    "placement": {"x": 0.0, "y": 0.0, "rotation": 0.0, "mirror": False},
                    "device": {"lcsc": "C431633"}, "footprint": "LQFP-64",
                    "params": {}, "pins": [],
                }
            ],
            "geometry": {"wires": [], "flags": [], "labels": []},
        },
        where="mcu-block",
    )


def table(*pins: tuple[str, str, str]):
    """A pin table from ``(number, function, net)`` triples."""
    return pin_table_from_json(
        {
            "kind": "boardwise-firmware-pintable",
            "version": 1,
            "mcu": "ic.stm32g431rbt6",
            "pins": [
                {"number": number, "name": number, "function": function, "net": net}
                for number, function, net in pins
            ],
        },
        where="synthetic",
    )


def spec_for(template, *pairs: tuple[str, str], block_id: str = "mcu") -> BoardSpec:
    """A spec wiring ``(net, port role)`` pairs onto the MCU block."""
    return BoardSpec(
        name="synthetic", description="", provenance_kind="textbook",
        provenance_source="hand", provenance_note="",
        blocks=[
            BlockInstance(
                id=block_id, template_path="/t/mcu.json", template=template,
                at=(0.0, 0.0),
            )
        ],
        connections=[
            BlockConnection(net=net, ports=[(block_id, role), ("other", role)])
            for net, role in pairs
        ],
        params={}, sheet_attrs={}, sheet_origin=(0.0, 0.0),
    )


def withheld_notes(report):
    return [
        f for f in report.notes
        if f.rule == "spec-difference" and "no ball-name evidence" in f.message
    ]


# --------------------------------------------------------------------------
# contract 1 — the issue's own shape: a functional role must not be differenced
# --------------------------------------------------------------------------

#: The block the issue reported: an MCU whose ports are named after what they
#: *do* (`SPI_SCK`, `GND`) — which is what ``blocklib/blocks/*.json`` looks like
#: for every block cut out of a golden board.
FUNCTIONAL = mcu_block(("SPI_SCK", ""), ("GND", ""))


def test_a_functional_role_makes_a_correct_board_a_defect_today():
    """The shape, stated as a claim about the report, not about the code.

    Everything on both sides is right: the spec wires the MCU's `SPI_SCK` port to
    `SPI1_SCK`, the firmware puts PA5 on `SPI1_SCK` as `SPI_SCK`. What used to
    happen is the difference ``{PA5} - {"SPI_SCK"}``, which is never empty.
    """
    spec = spec_for(FUNCTIONAL, ("SPI1_SCK", "SPI_SCK"))
    report = check_pin_table(
        table(("PA5", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert report.ok, [f.render() for f in report.defects]
    assert not report.open_questions, [f.render() for f in report.open_questions]
    assert report.matched_nets == 0, "an uncomparable net is not a matched net"


def test_a_withheld_port_is_named_in_a_note():
    spec = spec_for(FUNCTIONAL, ("SPI1_SCK", "SPI_SCK"))
    report = check_pin_table(
        table(("PA5", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    notes = withheld_notes(report)
    assert len(notes) == 1
    assert notes[0].kind == NOTE
    assert "SPI_SCK" in notes[0].message, "the note must name the port it skipped"
    assert "withheld" in notes[0].message
    assert "*not* a pass" in notes[0].message
    assert "not a defect" in notes[0].message


def test_a_withheld_port_never_claims_the_firmware_never_used_the_ball():
    """Direction 2's open question is the mirror of the defect, and is worse.

    A functional role looked up in the firmware's pin→net table can never hit, so
    the old code printed "the firmware has not grown into that pin yet" about
    `SPI_SCK` — a pin the firmware may be sitting on under another name. The
    board below is correct on both counts: the firmware's own net is wired by a
    ball-named port, and the functional port's net it simply does not use.
    Withheld, so there is no finding to misread.
    """
    tmpl = mcu_block(("SPI_SCK", ""), ("PA5", ""))
    spec = spec_for(tmpl, ("SPI1_MOSI", "SPI_SCK"), ("SPI1_SCK", "PA5"))
    report = check_pin_table(
        table(("PA5", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert report.ok, [f.render() for f in report.findings]
    assert not report.open_questions, [f.render() for f in report.open_questions]
    assert not any(
        "has not grown into" in f.message for f in report.findings
    ), [f.render() for f in report.findings]
    assert report.matched_nets == 1
    notes = withheld_notes(report)
    assert len(notes) == 1, "exactly one port has no ball evidence"
    assert "'SPI_SCK'" in notes[0].message
    assert "PA5" not in notes[0].message, "the ball-named port is not withheld"


def test_a_withheld_port_cannot_produce_a_defect_even_on_the_wrong_ball():
    """Not even a *disagreement* produces one.

    PB6 on `SPI1_SCK` really is a wrong ball, and the report has no way to know
    it: the spec never said which ball `SPI_SCK` is. Claiming a defect there
    would be the #48 bug with the sign flipped. Fill in `ball` to get the check
    back (below).
    """
    spec = spec_for(FUNCTIONAL, ("SPI1_SCK", "SPI_SCK"))
    report = check_pin_table(
        table(("PB6", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert report.ok, [f.render() for f in report.defects]
    assert not report.open_questions
    assert report.matched_nets == 0


def test_a_net_the_spec_never_connects_is_still_a_defect():
    """The floor is only about *balls*. A missing net needs no ball to refute.

    Withholding must not turn gate 3 off: this is the one direction that needs
    no pin-level evidence at all, and it is the shape that catches a firmware
    table invented from nothing.
    """
    spec = spec_for(FUNCTIONAL, ("SPI1_SCK", "SPI_SCK"))
    report = check_pin_table(
        table(("PA5", "SPI_SCK", "SPI1_SCK"), ("PB6", "UART_TX", "USART1_TX")),
        spec=spec, mcu_block_id="mcu",
    )
    assert not report.ok
    orphan = [f for f in report.defects if f.rule == "spec-difference"]
    assert len(orphan) == 1
    assert "USART1_TX" in orphan[0].message
    assert "spec never connects" in orphan[0].message
    assert orphan[0].kind == DEFECT


def test_a_net_the_spec_connects_to_no_mcu_port_is_still_a_defect():
    """The other no-evidence-needed case, and the one `(none)` exists for.

    The net is in the spec but the MCU block is not on it at all, so no ball
    exists to withhold — there is nothing on the other side of the comparison
    and the firmware's pin cannot be agreed with.
    """
    spec = spec_for(FUNCTIONAL)
    spec.connections.append(
        BlockConnection(net="LED1", ports=[("other", "LED1")])
    )
    report = check_pin_table(
        table(("PA5", "GPIO", "LED1")), spec=spec, mcu_block_id="mcu"
    )
    assert not report.ok
    unwired = [f for f in report.defects if "(none)" in f.message]
    assert len(unwired) == 1
    assert "schematic does not wire" in unwired[0].message
    assert unwired[0].evidence[1] == "spec: (no port)"


# --------------------------------------------------------------------------
# contract 2 — issue #35 must not regress: a ball-named role still compares
# --------------------------------------------------------------------------


def test_a_ball_shaped_role_still_compares_at_pin_level():
    tmpl = mcu_block(("PA3", ""), ("PB6", ""))
    spec = spec_for(tmpl, ("SPI1_SCK", "PA3"))
    report = check_pin_table(
        table(("PA3", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert report.ok
    assert report.matched_nets == 1
    assert not withheld_notes(report), "a ball-named role needs no `ball` field"


def test_a_ball_shaped_role_still_reports_the_wrong_ball_verbatim():
    """The finding text is pinned, not just its kind.

    Batch 4's wording is what a reader of a #35 report has been reading; the
    fix had to add ball evidence without re-wording the case that already
    worked. `role on ball` is spelled only when the two differ, so for the
    ball-named blocks the sentence is character-for-character what it was.
    """
    tmpl = mcu_block(("PA3", ""), ("PB6", ""))
    spec = spec_for(tmpl, ("SPI1_SCK", "PA3"))
    report = check_pin_table(
        table(("PB6", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert not report.ok
    defects = [f for f in report.defects if f.rule == "spec-difference"]
    assert len(defects) == 1
    assert defects[0].message == (
        "firmware puts PB6 on net 'SPI1_SCK', which the spec connects to the MCU "
        "block's port(s) PA3 — the firmware uses a pin the schematic does not wire"
    )
    assert defects[0].evidence == [
        "net SPI1_SCK", "spec: PA3", "firmware: PB6",
    ]
    assert report.matched_nets == 0


def test_a_ball_shaped_role_still_catches_one_ball_on_two_nets():
    tmpl = mcu_block(("PA3", ""), ("PB6", ""))
    spec = spec_for(tmpl, ("SPI1_SCK", "PA3"), ("SPI1_MISO", "PB6"))
    report = check_pin_table(
        table(("PA3", "SPI_SCK", "SPI1_MISO")), spec=spec, mcu_block_id="mcu"
    )
    doubled = [
        f for f in report.defects if "one ball cannot be on two nets" in f.message
    ]
    assert len(doubled) == 1
    assert doubled[0].evidence == ["net SPI1_SCK", "PA3 on 'SPI1_MISO'"]


def test_a_ball_shaped_role_still_asks_the_open_question():
    tmpl = mcu_block(("PA3", ""), ("PB6", ""))
    spec = spec_for(tmpl, ("LED1", "PA3"), ("SPI1_SCK", "PB6"))
    report = check_pin_table(
        table(("PA3", "GPIO", "LED1")), spec=spec, mcu_block_id="mcu"
    )
    assert report.ok
    questions = [f for f in report.open_questions if f.rule == "spec-difference"]
    assert len(questions) == 1
    assert "PB6" in questions[0].message
    assert "has not grown into that pin yet" in questions[0].message


# --------------------------------------------------------------------------
# contract 3 — the `ball` field, all three ways
# --------------------------------------------------------------------------

#: A functional role *with* the evidence the block author supplies.
BALLED = mcu_block(("SPI_SCK", "PA5"), ("GND", ""))


def test_the_ball_field_restores_the_pin_level_comparison():
    spec = spec_for(BALLED, ("SPI1_SCK", "SPI_SCK"))
    report = check_pin_table(
        table(("PA5", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert report.ok, [f.render() for f in report.findings]
    assert report.matched_nets == 1
    assert not withheld_notes(report), "the `ball` field is the evidence asked for"


def test_the_ball_field_catches_the_wrong_ball():
    spec = spec_for(BALLED, ("SPI1_SCK", "SPI_SCK"))
    report = check_pin_table(
        table(("PB6", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert not report.ok
    defects = [f for f in report.defects if f.rule == "spec-difference"]
    assert len(defects) == 1
    assert "PB6" in defects[0].message
    # The evidence has to show *which* ball the spec meant, or the reader is
    # back to guessing from the role.
    assert "SPI_SCK on PA5" in defects[0].evidence[1]
    assert report.matched_nets == 0


def test_the_ball_field_catches_one_ball_on_two_nets():
    """The #48 mirror: the spec's `SPI_SCK` is PA5, the firmware has PA5 on `Y`."""
    spec = spec_for(BALLED, ("SPI1_SCK", "SPI_SCK"))
    report = check_pin_table(
        table(("PA5", "SPI_SCK", "NET_Y")), spec=spec, mcu_block_id="mcu"
    )
    assert not report.ok
    doubled = [
        f for f in report.defects if "one ball cannot be on two nets" in f.message
    ]
    assert len(doubled) == 1
    assert "SPI1_SCK" in doubled[0].message
    # The finding names the *ball*, not the role: "puts the same pin on
    # SPI_SCK on 'NET_Y'" would put two "on"s and answer nothing.
    assert "PA5 on 'NET_Y'" in doubled[0].message
    assert doubled[0].evidence == ["net SPI1_SCK", "PA5 on 'NET_Y'"]
    assert not report.open_questions


def test_the_ball_wins_over_a_ball_shaped_role():
    """Two pieces of evidence that disagree: `ball` is the one that was written
    down on purpose, so it is the one believed."""
    tmpl = mcu_block(("PA3", "PB6"))
    spec = spec_for(tmpl, ("SPI1_SCK", "PA3"))
    report = check_pin_table(
        table(("PB6", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    assert report.ok and report.matched_nets == 1
    assert not withheld_notes(report)


def test_a_port_with_a_ball_evidence_is_not_withheld_even_when_nothing_uses_it():
    """The open question is a real finding again once the ball is known.

    The board has an `SPI_MISO` net the firmware has not grown into, and the port
    on it says which ball — so "which pin has it not used" is answerable, and the
    checker answers it.
    """
    tmpl = mcu_block(("SPI_SCK", "PA5"), ("PA6", ""), symbol_pins=("PA5", "PA6"))
    spec = spec_for(tmpl, ("SPI1_MISO", "SPI_SCK"), ("SPI1_SCK", "PA6"))
    report = check_pin_table(
        table(("PA6", "SPI_SCK", "SPI1_SCK")), spec=spec, mcu_block_id="mcu"
    )
    questions = [f for f in report.open_questions if f.rule == "spec-difference"]
    assert len(questions) == 1
    assert questions[0].kind == OPEN_QUESTION
    assert "SPI1_MISO" in questions[0].message
    assert "SPI_SCK" in questions[0].message
    assert "has not grown into that pin yet" in questions[0].message
    assert report.ok
    assert not withheld_notes(report)


# --------------------------------------------------------------------------
# contract 5 — the mixed block: all three port shapes on one template
# --------------------------------------------------------------------------


def test_the_three_port_shapes_behave_as_three_separate_questions():
    """One block, one spec, one table — and each port answered on its own terms.

    `SPI_SCK`/PA5 is answered by the field, `PA3` by its own name, and `GND` is
    not answered at all. The point is that the two answerable ports are *really*
    compared: a wrong ball on either of them is still a defect, in a block whose
    third port is being withheld.
    """
    tmpl = mcu_block(("SPI_SCK", "PA5"), ("PA3", ""), ("GND", ""))
    spec = spec_for(
        tmpl, ("SPI1_SCK", "SPI_SCK"), ("LED1", "PA3"), ("GND", "GND"),
    )
    report = check_pin_table(
        table(("PA5", "SPI_SCK", "SPI1_SCK"), ("PA3", "GPIO", "LED1")),
        spec=spec, mcu_block_id="mcu",
    )
    assert report.ok, [f.render() for f in report.defects]
    assert report.matched_nets == 2, "the two evidenced nets are matched"
    notes = withheld_notes(report)
    assert len(notes) == 1 and "GND" in notes[0].message
    assert "SPI_SCK" not in notes[0].message and "PA3" not in notes[0].message


def test_the_mixed_block_still_defects_on_the_evidenced_ports():
    tmpl = mcu_block(("SPI_SCK", "PA5"), ("PA3", ""), ("GND", ""))
    spec = spec_for(
        tmpl, ("SPI1_SCK", "SPI_SCK"), ("LED1", "PA3"), ("GND", "GND"),
    )
    report = check_pin_table(
        table(("PB6", "SPI_SCK", "SPI1_SCK"), ("PA3", "GPIO", "LED1")),
        spec=spec, mcu_block_id="mcu",
    )
    assert not report.ok
    defects = [f for f in report.defects if f.rule == "spec-difference"]
    assert len(defects) == 1
    assert "PB6" in defects[0].message
    assert report.matched_nets == 1, "LED1 still matched; SPI1_SCK did not"
    assert withheld_notes(report), "GND is still withheld"


# --------------------------------------------------------------------------
# contract 4 — the loader: shape-checked, optional, round-tripped
# --------------------------------------------------------------------------


def _tiny_template_with_interface(interface):
    body = {
        "kind": BLOCK_TEMPLATE_KIND,
        "version": SCHEMA_VERSION,
        "name": "tiny",
        "description": "",
        "provenance": {
            "kind": "textbook", "source": "hand", "designators": ["R1"], "note": "",
        },
        "origin_file": [0.0, 0.0],
        "bbox_file": [0.0, 0.0, 100.0, 100.0],
        "notes": [],
        "interface": interface,
        "params": [],
        "symbols": {"sym1": {"offsets": {"1": [0.0, 0.0]}}},
        "components": [
            {
                "ref": "R1", "symbol": "sym1",
                "placement": {"x": 0.0, "y": 0.0, "rotation": 0.0, "mirror": False},
                "device": {"lcsc": "C1"}, "footprint": "0402", "params": {},
                "pins": [],
            }
        ],
        "geometry": {"wires": [], "flags": [], "labels": []},
    }
    return template_from_json(body, where="tiny")


def test_a_functional_name_in_ball_is_refused_by_name():
    with pytest.raises(BlockError) as caught:
        _tiny_template_with_interface(
            [{"role": "SPI_SCK", "net": "SPI1_SCK", "net_class": "signal",
              "ball": "SPI_SCK"}]
        )
    message = str(caught.value)
    assert "interface[0].ball" in message, message
    assert "'SPI_SCK' is not a ball name" in message
    assert "PA5" in message, "the error must show what a ball looks like"


@pytest.mark.parametrize(
    "value",
    ["PA", "P5", "PA5.WRONG", "spi_sck", "", "SPI1_SCK", "PB6-ALT"],
    ids=["no-port", "no-digit", "dotted", "lowercase", "empty", "net-name",
         "hyphenated"],
)
def test_only_a_ball_shaped_value_is_accepted(value):
    if value == "":
        # An empty `ball` is a port that names no ball, not a bad one.
        port = {"role": "SPI_SCK", "net": "N", "net_class": "signal", "ball": value}
        assert _tiny_template_with_interface([port]).interface[0].ball is None
        return
    with pytest.raises(BlockError, match=r"interface\[0\]\.ball"):
        _tiny_template_with_interface(
            [{"role": "SPI_SCK", "net": "N", "net_class": "signal", "ball": value}]
        )


@pytest.mark.parametrize("value", ["PA5", "PC12", "PA55"])
def test_everything_the_repository_calls_a_ball_is_one(value):
    """`\\d{1,2}` is two digits, so `PA55` is a ball here and must stay one.

    The rule is "whatever `core/pintable.py` says a ball is" — one predicate,
    one implementation (071). This test exists so that anyone who later tightens
    the regex has to come here and answer for it.
    """
    template = _tiny_template_with_interface(
        [{"role": "R", "net": "N", "net_class": "signal", "ball": value}]
    )
    assert template.interface[0].ball == value


@pytest.mark.parametrize(
    "value", [5, ["PA5"], {"ball": "PA5"}, True],
    ids=["int", "list", "object", "bool"],
)
def test_a_ball_of_the_wrong_type_names_itself(value):
    with pytest.raises(BlockError) as caught:
        _tiny_template_with_interface(
            [{"role": "SPI_SCK", "net": "N", "net_class": "signal", "ball": value}]
        )
    assert "interface[0].ball" in str(caught.value)


def test_ball_is_optional_and_absent_reads_as_none():
    template = _tiny_template_with_interface(
        [{"role": "SPI_SCK", "net": "N", "net_class": "signal"}]
    )
    assert template.interface[0].ball is None
    assert "ball" not in template_to_json(template)["interface"][0], (
        "an absent ball must not be written out — that is what keeps every "
        "committed block byte-identical"
    )


def test_ball_survives_a_round_trip():
    template = mcu_block(("SPI_SCK", "PA5"), ("GND", ""))
    once = template_to_json(template)
    assert once["interface"][0]["ball"] == "PA5"
    assert "ball" not in once["interface"][1]
    twice = template_to_json(template_from_json(once))
    assert once == twice, "a field that cannot be re-read is not a field"
    assert json.dumps(once)
    reread = template_from_json(once)
    assert [p.ball for p in reread.interface] == ["PA5", None]


def test_the_five_committed_blocks_carry_no_ball():
    """The library is unchanged on purpose, and says so in its own files.

    None of the five is an MCU block, so none of them has a ball to declare —
    adding one would be inventing evidence nobody measured.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path in sorted((root / "blocklib" / "blocks").glob("*.json")):
        body = json.loads(path.read_text(encoding="utf-8"))
        assert "ball" not in body, path
        for port in body["interface"]:
            assert "ball" not in port, path
        assert all(
            p.ball is None
            for p in template_from_json(body, where=str(path)).interface
        ), path
