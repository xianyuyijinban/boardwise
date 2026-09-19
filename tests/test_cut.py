"""The cutting tool: board -> block template (task 008a, work item 2).

The round-trip test is the load-bearing one. A template claims to be "a faithful
extract of board X, region Y" — a claim in a comment is worth nothing, so
everything the cut needs is recorded *inside* the template (designators, the
boundary, each parameter's constraint) and re-cutting from the board it names
must reproduce the committed file byte for byte.

The refusals get tested too, because they are the tool's actual design: a
boundary that cuts a wire or leaves a part outside is an error rather than a
silent include-or-drop, and a port is never invented.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.blocks import load_block_template
from boardwise.core.overrides import load_overrides
from boardwise.engines.cut import CutError, extract_block, infer_constraint, recut, write_block

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = "tests/fixtures/ch340_golden.epro2"
SIDECAR = ROOT / "tests" / "fixtures" / "ch340_golden.overrides.json"
BLOCKS = ROOT / "blocklib" / "blocks"

#: The cut each committed template came from. Kept here as well as inside the
#: templates so the test can state the *intent* independently of the artifact.
CUTS = {
    # Canvas space (task 010c): each bbox is the stored one with its y range
    # swapped, `[x0,y0,x1,y1] -> [x0,-y1,x1,-y0]`, because the harvest now reads
    # through a parser that negates the stored y once at its own boundary.
    "ch340_usb_input": (["USB1", "R24", "R27", "C4"], (40.0, 40.0, 230.0, 240.0)),
    "ch340_power_3v3": (
        ["U5", "C5", "C6", "C7", "C9", "LED1", "U3"],
        (130.0, 330.0, 430.0, 475.0),
    ),
    "ch340_core": (["U1", "C1", "X1", "C25", "C3"], (60.0, 530.0, 310.0, 690.0)),
    "ch340_uart_header": (["H1"], (390.0, 600.0, 460.0, 660.0)),
}

#: The only provenance kind with a source board to re-derive from. Everything
#: below keys off this rather than off a hand-maintained list of names, because
#: a list is a thing somebody has to remember to extend — and the failure mode of
#: forgetting is a *silent* one (a new block simply is never checked).
RECUTTABLE_KIND = "board-extract"


def _committed_templates() -> dict[str, object]:
    """Every committed block, by name — inspected, not enumerated."""
    return {
        path.stem: load_block_template(path)
        for path in sorted(BLOCKS.glob("*.json"))
    }


def test_the_recut_guard_covers_every_board_extract_and_nothing_else():
    """Which blocks the re-cut guard owns, decided by reading them.

    A `datasheet-extract` or `textbook` block has no source board, so asking it
    to reproduce a cut is a category error, not a failing check. This pins that
    boundary in **both** directions: every board-extract on disk is in `CUTS`
    (so a new board-extract cannot slip in unguarded), and nothing else is.
    """
    committed = _committed_templates()
    by_kind: dict[str, set[str]] = {}
    for name, template in committed.items():
        by_kind.setdefault(template.provenance_kind, set()).add(name)

    assert set(CUTS) == by_kind.get(RECUTTABLE_KIND, set()), (
        "the CUTS table and the board-extract blocks on disk disagree; the "
        "table must cover exactly the blocks that have a source board"
    )

    # The other kinds are real and present — otherwise this test would pass
    # vacuously on a repo that had never authored one.
    authored = set(by_kind) - {RECUTTABLE_KIND}
    assert authored, (
        "no authored (datasheet-extract/textbook) block is committed yet, so "
        "the exclusion below is not being exercised"
    )
    for kind in authored:
        for name in by_kind[kind]:
            assert name not in CUTS, (
                f"{name} is a {kind} block and must not be in the re-cut table"
            )


@pytest.mark.parametrize("name", sorted(CUTS))
def test_a_board_extract_refuses_nothing_but_an_authored_block_does(name):
    """Re-cut is for board-extracts; an authored block is refused, with prose."""
    template = _committed_templates()[name]
    assert template.provenance_kind == RECUTTABLE_KIND


def test_an_authored_block_cannot_be_recut_and_says_so():
    """The refusal is explicit and explains itself, rather than failing obscurely."""
    authored = [
        t for t in _committed_templates().values()
        if t.provenance_kind != RECUTTABLE_KIND
    ]
    assert authored, "no authored block to check the refusal against"
    for template in authored:
        with pytest.raises(CutError) as caught:
            recut("tests/fixtures/ch340_golden.epro2", template)
        message = str(caught.value)
        assert template.name in message
        assert template.provenance_kind in message
        assert "only a board-extract can be re-cut" in message


def test_every_committed_block_vs_regenerates_from_the_board_it_names():
    """Re-cutting must reproduce the committed JSON exactly."""
    sidecar = load_overrides(SIDECAR)
    for name, (designators, bbox) in sorted(CUTS.items()):
        path = BLOCKS / f"{name}.json"
        committed = json.loads(path.read_text(encoding="utf-8"))
        template = load_block_template(path)
        assert [c.ref for c in template.components] == designators, name
        assert template.bbox_file == bbox, name
        fresh = recut(GOLDEN, template, overrides=sidecar)
        assert fresh.to_json() == committed, (
            f"{name}: the committed template is not what the board produces — "
            "re-run tools/extract_block.py --recut"
        )


def test_the_cut_partitions_the_page_without_losing_copper():
    """The four boundaries together own every wire run, and share none."""
    from boardwise.parsers.schematic import collect_page_layout

    page = collect_page_layout(GOLDEN)
    owned: dict[tuple, str] = {}
    for name, (_designators, bbox) in CUTS.items():
        def inside(point) -> bool:
            return bbox[0] <= point[0] <= bbox[2] and bbox[1] <= point[1] <= bbox[3]

        for run in page.wires:
            if all(inside(p) for p in run.points):
                key = tuple(run.points)
                assert key not in owned, f"run {key} claimed by {owned.get(key)} and {name}"
                owned[key] = name
    assert len(owned) == len(page.wires), (
        f"{len(page.wires) - len(owned)} wire run(s) lie outside every block"
    )


def test_ports_come_from_the_boundary_and_only_where_a_name_exists():
    template = load_block_template(BLOCKS / "ch340_usb_input.json")
    ports = {port.role: port for port in template.interface}
    assert set(ports) == {"GND", "+5V", "D+", "D-"}
    assert ports["GND"].net_class == "gnd"
    assert ports["+5V"].net_class == "power"
    assert ports["D+"].net_class == "signal"
    # NET5/NET6 (the CC pull-downs) never leave the block, so they are internal
    # nets and must not appear as an interface.
    assert "NET5" not in ports and "NET6" not in ports
    # A port is anchored on the label or flag the board actually has there.
    labels = {(label.net, label.x, label.y) for label in template.labels}
    assert ("D+", ports["D+"].position[0], ports["D+"].position[1]) in labels


def test_the_core_block_offers_the_six_interfaces_it_should():
    template = load_block_template(BLOCKS / "ch340_core.json")
    assert {port.role for port in template.interface} == {
        "GND", "VCC", "RX", "TX", "D+", "D-",
    }
    assert {port.role for port in template.interface if port.is_signal} == {
        "RX", "TX", "D+", "D-",
    }


def test_the_boundary_must_contain_the_parts_it_is_given():
    with pytest.raises(CutError, match="does not contain"):
        extract_block(
            GOLDEN,
            name="bad",
            designators=["USB1", "C4"],
            # Canvas space (task 010c). USB1 sits at y=131, below this box's
            # y span [150, 240]; C4 (y=200) is inside it.
            bbox=(40.0, 150.0, 230.0, 240.0),
        )


def test_the_boundary_may_not_cut_a_wire():
    """Half a run cannot be assigned to a block without dragging or losing it."""
    with pytest.raises(CutError, match="cuts through"):
        extract_block(
            GOLDEN,
            name="bad",
            designators=["USB1"],
            # Canvas space (task 010c): the same region as before the convention
            # change, with the y ends swapped. USB1 (89, 131) is inside; the VBUS
            # run continues to x = 198, past this right-hand boundary.
            bbox=(40.0, 40.0, 170.0, 240.0),
        )


def test_a_designator_that_is_not_on_the_page_is_refused():
    with pytest.raises(CutError, match="no such part"):
        extract_block(
            GOLDEN,
            name="bad",
            designators=["USB1", "R99"],
            bbox=(40.0, -240.0, 230.0, -40.0),
        )


def test_the_corrections_sidecar_is_folded_in_with_its_provenance():
    """The fixture is evidence and never edited (§G.3); the template carries it."""
    sidecar = load_overrides(SIDECAR)
    outcome = extract_block(
        GOLDEN,
        name="usb",
        designators=["USB1", "R24", "R27", "C4"],
        bbox=CUTS["ch340_usb_input"][1],
        overrides=sidecar,
    )
    r24 = next(c for c in outcome.template.components if c.ref == "R24")
    assert r24.device.lcsc == "C25905"
    assert r24.device.device_uuid == "ef1f93374e0c4079b48a2d1a3cec8f6b"
    assert r24.device.library_uuid == "0819f05c4eef4c71ace90d822a990e87"
    assert r24.device.expect_footprint == "R0402"
    assert "0402WGF5101TCE" in r24.device.provenance
    # U3's *value* correction lands on the parameter, not the device binding
    power = extract_block(
        GOLDEN,
        name="power",
        designators=CUTS["ch340_power_3v3"][0],
        bbox=CUTS["ch340_power_3v3"][1],
        overrides=sidecar,
    )
    u3 = power.template.param("u3_value")
    assert u3 is not None and u3.default == "2.2kΩ"
    assert "人为错误" in u3.provenance
    # and a part with no sidecar entry carries no invented provenance
    c6 = power.template.param("c6_value")
    assert c6 is not None and c6.provenance == ""


def test_a_part_with_no_value_gets_no_parameter():
    """"Every number is a parameter" — a part with no number has nothing to say."""
    template = load_block_template(BLOCKS / "ch340_uart_header.json")
    assert template.params == []
    assert all(component.params == {} for component in template.components)


@pytest.mark.parametrize(
    "value,footprint,device_name,expected",
    [
        ("100nF", "0603", "CC0603KRX7R9BB104", "capacitor_value"),
        ("30pF", "0402", "CC0402JRNPO9BN300", "capacitor_value"),
        ("10nF", "0603", "CC0603KRX7R9BB103", "capacitor_value"),
        ("5.1K", "0402", "Res_0402", "resistor_value"),
        ("2.2kΩ", "0805", "FRC0805J471 TS", "resistor_value"),
        ("5.1K", "R0402", "", "resistor_value"),
        ("12MHz", "SMD3225-4P", "X322512MSB4SI", "free_text"),
        ("", "0603", "CC0603", "free_text"),
        # `104` is a resistor's marking and a capacitor's marking at once; with
        # no package evidence the tool refuses to guess, which is the point.
        ("104", "", "", "free_text"),
    ],
)
def test_the_constraint_inference_states_its_evidence(value, footprint, device_name, expected):
    constraint, reason = infer_constraint(value, footprint, device_name)
    assert constraint == expected
    assert reason


def test_write_block_round_trips_through_disk(tmp_path):
    outcome = extract_block(
        GOLDEN,
        name="uart",
        designators=["H1"],
        bbox=CUTS["ch340_uart_header"][1],
    )
    path = write_block(outcome, tmp_path / "uart.json")
    assert load_block_template(path).name == "uart"
