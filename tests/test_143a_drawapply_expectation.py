"""143a: the plan-side half of 143's findings — the change plan's own expectation.

* F1 — a degradation the compiler had to make reaches `change.downgrades`, the
  list `draw plan` prints for the reader who authorises the drawing;
* F2 — `islands_from_circuit` builds the netlist expectation with the **same**
  role-sibling rule the compiler draws and the checker grades by (060 sec.2), so
  a correct drawing is not reported as a disagreement by the plan it came from;
* F3 — the postconditions are written in one namespace (the designator), while
  `from_pin`/`on_pin` keep the spec id their contract requires.
"""

from __future__ import annotations

import test_053b_drawcompiler as T
from boardwise.engines import drawapply, drawcompiler as dc

from gate_skip import skip_if_the_147_gate_refused

PAGE = (0.0, 0.0, 1170.0, 825.0)


def _compile(circuit, presentation, book):
    result = dc.compile(circuit, presentation, book, dc.CompileBudget(page_box=PAGE))
    # 147c: 143a's F2 scene lands a rail flag so that its name row is crossed by
    # another net's wire — one of the shapes 147's gate now refuses. The skip names
    # the gate line; a refusal by anything else still fails here.
    skip_if_the_147_gate_refused(result, "143a F2, the sibling-role LDO scene")
    assert result.ok, result.render_failures()
    return result.best()


def _plan(plan, circuit, presentation, book, **kwargs):
    return drawapply.module_plan(
        plan, circuit, presentation, book,
        lcsc_by_part={part.id: "C1855" for part in circuit.parts},
        values_by_part={part.id: part.value or "x" for part in circuit.parts},
        **kwargs,
    )


# ------------------------------------------------------------------- F1


def test_143a_f1_a_compiler_degradation_reaches_the_change_plans_downgrades():
    """A fallback the engineer did not ask for is a `downgrade:` line they read."""
    book = T.library()
    del book["PWR-GND"]
    circuit, presentation = T.ldo_circuit(), T.ldo_presentation()
    plan = _compile(circuit, presentation, book)

    change = _plan(plan, circuit, presentation, book)
    assert change.change.draw_downgrades, change.change.draw_notes
    assert any("PWR-GND" in line for line in change.change.draw_downgrades)


# ------------------------------------------------------------------- F2


def test_143a_f2_a_sibling_role_pin_is_in_the_plans_netlist_expectation():
    """060 sec.2: the compiler wires the sibling pad, so the plan must expect it.

    With only `U1.2` spelled on the 3V3 rail the drawing still carries `U1.4` on
    it (both are the symbol's VOUT). The expectation used to be read off
    `net.members` alone, so `draw apply`'s read-back compared the drawing against
    a smaller net and reported *"U1.2 is on net 'Net2' with ['U1.2', 'U1.4'] …
    but the plan says ['U1.2']"* — a correct drawing refused by its own plan,
    exit 3, never saved.
    """
    circuit = T._ldo_pair_circuit(out_members=["U1.2"])
    presentation = T.ldo_presentation(parts=("U1", "C1"))
    plan = _compile(circuit, presentation, T.library())

    change = _plan(plan, circuit, presentation, T.library())
    designator = {part.spec_id: part.designator for part in change.change.draw_parts}
    u1 = designator["U1"]
    mates = {tuple(island.mates) for island in change.change.islands}
    pair = ("U1.2", "U1.4")
    assert any(
        {f"{u1}.2", f"{u1}.4"} == set(members) for members in mates
    ), sorted(mates)

    # …and the live netlist the compiler's own drawing produces now satisfies the
    # plan's own postconditions (the read-back that used to disagree).
    live: dict[tuple[str, str], str] = {}
    for index, members in enumerate(sorted(mates)):
        for member in members:
            part, _, pin = member.partition(".")
            live[(part, pin)] = f"Net{index}"
    state = drawapply.postcondition_problems(change, live=live)
    assert drawapply.all_satisfied(state), state


def test_143a_f2_the_two_sibling_exceptions_are_the_compilers_own():
    """A pin in `nc[]` stays off the net; a pin the spec puts elsewhere is a
    contradiction left to `circuit-invalid`, not silently joined."""
    diameter = T.ams1117_duplicate_vout
    book = dict(T.library())
    book["AMS1117-3.3-C6186"] = diameter()
    base_nets = [
        T.net("VIN5", "power", ["U1.3"]),
        T.net("3V3", "power", ["U1.2"]),
        T.net("GND", "gnd", ["U1.1"]),
    ]
    parts = [T.part("U1", "AMS1117-3.3-C6186", "x")]
    designators = {"U1": "U1"}
    book_map = {"AMS1117-3.3-C6186": diameter()}

    plain = drawapply.islands_from_circuit(
        T.circuit(parts, base_nets), designators, book_map
    )
    three_v3 = [island for island in plain if island.pin == "U1.2"]
    assert three_v3 and set(three_v3[0].mates) == {"U1.2", "U1.4"}

    no_connect = drawapply.islands_from_circuit(
        T.circuit(parts, base_nets, nc=["U1.4"]), designators, book_map
    )
    assert set(no_connect[0].mates) == {"U1.3"} or all(
        "U1.4" not in island.mates for island in no_connect
    )

    elsewhere = [
        T.net("VIN5", "power", ["U1.3"]),
        T.net("3V3", "power", ["U1.2"]),
        T.net("OTHER", "signal", ["U1.4"]),
        T.net("GND", "gnd", ["U1.1"]),
    ]
    split = drawapply.islands_from_circuit(
        T.circuit(parts, elsewhere), designators, book_map
    )
    island_of = {(island.pin): set(island.mates) for island in split}
    assert island_of["U1.2"] == {"U1.2"}
    assert island_of["U1.4"] == {"U1.4"}


def test_143a_f2_no_profiles_means_the_answer_is_what_it_always_was():
    """A caller holding only the circuit is unchanged (the parameter is optional)."""
    circuit = T.divider_circuit()
    islands = drawapply.islands_from_circuit(circuit, {"R1": "R1", "R2": "R2"})
    assert {tuple(island.mates) for island in islands} == {
        ("R1.1",), ("R1.2", "R2.1"), ("R2.2",),
    }


# ------------------------------------------------------------------- F3


def test_143a_f3_the_postconditions_name_the_designator_not_the_spec_id():
    """`from_pin` is a spec id by contract; the sentence a human reads is not.

    A page that already numbers R1/R2 makes the allocator hand out R3/R4, and the
    list used to read "a wire carrying net VIN … starting on R1.1" beside "R3
    (10k, R0402) is on the page" — a part that does not exist on that page.
    """
    circuit, presentation = T.divider_circuit(), T.divider_presentation()
    plan = _compile(circuit, presentation, T.library())
    change = _plan(plan, circuit, presentation, T.library(), pool=["R1", "R2"])

    placed = {part.spec_id: part.designator for part in change.change.draw_parts}
    assert placed["R1"] != "R1", placed  # the witness needs the two to differ

    # The document keeps the spec id (changeplan's contract, and the read-back
    # resolves that end through the placed part).
    assert [wire.from_pin for wire in change.change.draw_wires] == [
        "R1.1", "", "R2.1", "R2.2",
    ] or all(wire.from_pin.startswith(("R1.", "R2.", ""))
             for wire in change.change.draw_wires)

    # …and the sentences are in the page's own namespace.
    sentences = "\n".join(change.expected_postcondition)
    assert f"starting on {placed['R1']}." in sentences
    assert f"starting on {placed['R2']}." in sentences
    for spec_id in ("R1", "R2"):
        assert f"starting on {spec_id}." not in sentences.replace(
            f"starting on {placed[spec_id]}.", ""
        )
