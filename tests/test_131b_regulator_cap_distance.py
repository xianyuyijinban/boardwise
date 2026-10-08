"""Task 131 stick 2 (131b): ``pcb-regulator-cap-distance``.

The rule reads a regulator **pin-role-wise** — ``VIN`` and ``VOUT`` are two
sides, each searched on *its own* net — and splits the capacitors on that net
into two pools by 岳裁定 ③ (``< 1 µF`` = high-frequency bypass, ``>= 1 µF`` =
energy storage, no undecided middle band). Everything it emits is a
measurement; no threshold exists in this stick.

Evidence sources, in the order the task book names them:

* **Synthetic boards** — a hand-built :class:`~boardwise.core.geometry.BoardGeometry`
  and :class:`~boardwise.core.model.DesignModel` with an injected shelf
  (:meth:`~boardwise.rules.pcb.regulator.RegulatorCapDistance.check_with_library`,
  the injection point the rule publishes for exactly this), so the states are
  pinned without a fixture: a populated pool, an empty pool, a far
  capacitor, a part the shelf classifies as something else, a part it does not
  classify at all, and a buck with no output pin. Every expected distance is a
  subtraction of stated pad coordinates (pads are 40x40, so the edge gap
  between two on one axis is ``|x1 - x2| - 40``) with the derivation next to the
  assertion.
* **毕设FOC 1.0.0** (`ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2`, read-only)
  — the three regulators, every side and every pool, as a pinned table, with
  the two acceptance anchors called out: **U11's C89** (4.7 µF, 99.5 mil) must
  be the VIN storage nearest, and **U5's output pool** must hold only the parts
  on its own VOUT net — never the ``+5V`` input-side capacitors that share the
  input rail with U6.
* **ROBOT ctrl FOC** and **毕设FOC 1.1.0** (`ProPrj_毕设FOC驱动板_2026-09-17.epro2`,
  read-only) — U8 = ``AMS1117-3.3`` with two ``Output`` pins and two pools per
  side; and the three-document export, which must produce nothing rather than a
  row about a part that is not on the board.

**Which model is read, corrected by 131c.** 131b shipped this rule reading
``ctx.model``, and this docstring then argued the *schematic* view was the right
one, on the claim that the PCB view 「resolves every net to an auto-generated
``NETn``」. **That claim was backwards, and 131c measured it.** On the 1.0.0
export the two views name the same wires differently, and neither is ``NETn``'s
fault:

* the **schematic** view renumbers: U5's output is ``NET11``, U6's is ``NET3``;
* the **PCB** view carries the editor's own names: ``$1N66612`` and
  ``$1N66627``.

The nets are the same wires, so the rule measured the *right* parts and
attributed them to the *wrong* net. That is how U5's VOUT storage pool read
「empty」 in a real ``checkup`` while ``C3``/``C4`` sat on that very net 41.8 mil
from the pin, and how U6's VOUT storage nearest read *nothing* while ``C64``
was 91.4 mil away. The rule now reads ``ctx.pcb_model`` — the netlist view of
the PCB document it is measuring — and the real ``checkup`` is pinned both ways
in ``test_131c_regulator_fb_placement.py``. The synthetic helper below fills
``pcb_model=``, and ``_ctx`` fills **both** fields so a test that wants to prove
the schematic view is *not* read can say so.

The offline fixtures are read-only. Nothing here runs an editor or a daemon.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    PadGeometry,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartEntry, PartLibrary
from boardwise.core.pinrole import pin_role
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.pcb.base import PcbReviewContext, PcbRule
from boardwise.rules.pcb.distance import capacitor_role
from boardwise.rules.pcb.regulator import (
    SIDE_OUTPUT,
    HF_POOL_FARADS,
    POOL_HF,
    POOL_STORAGE,
    REGULATOR_CATEGORIES,
    RegulatorCapDistance,
    _regulator_readings,
    regulator_role,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"
FOC_110 = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
LLC = FIXTURES / "llc_board.epro2"


# ---------------------------------------------------------------------------
# synthetic helpers
# ---------------------------------------------------------------------------


def _pad(component: str, pin: str, *, x: float, y: float, net: str = "") -> PadGeometry:
    """One axis-aligned 40x40 pad, so every gap below is a subtraction."""
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        layer_id=1,
        x=x,
        y=y,
        width=40.0,
        height=40.0,
        shape="RECT",
        angle=0.0,
    )


def _comp(
    designator: str,
    *,
    value: str = "",
    mpn: str = "",
    lcsc: str = "",
    pins: list[Pin] = (),
) -> Component:
    return Component(
        uid=f"u-{designator}",
        designator=designator,
        value=value,
        mpn=mpn,
        lcsc_part=lcsc,
        pins=list(pins),
    )


def _model(components: list[Component]) -> DesignModel:
    """A ``DesignModel`` whose net index is built from its components' pins."""
    model = DesignModel(components={c.designator: c for c in components})
    nets: dict[str, Net] = {}
    for component in components:
        for pin in component.pins:
            if not pin.net:
                continue
            nets.setdefault(pin.net, Net(name=pin.net)).pins.append(
                (component.designator, pin.number)
            )
    model.nets = nets
    return model


def _board(parts: list[tuple[str, float, float]], pads: list[PadGeometry]) -> BoardGeometry:
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        components=[
            ComponentPlacement(id=f"c-{d}", designator=d, x=x, y=y, layer_id=1)
            for d, x, y in parts
        ],
        pads=list(pads),
    )


def _ctx(
    board: BoardGeometry | None,
    model: DesignModel | None = None,
    pcb_model: DesignModel | None = None,
) -> PcbReviewContext:
    """A synthetic context, with the netlist in **both** slots (131c).

    ``pcb_model`` is the field the rule reads; it defaults to ``model`` so the
    synthetic boards below (which have one view, named consistently) keep
    working unchanged. A test that wants to prove the schematic view is *not*
    what the rule consults passes two different models and asserts the row names
    a net that only exists in ``pcb_model``.
    """
    return PcbReviewContext(
        board=board,
        board_title="SYNTH",
        model=model,
        intent=None,
        module_of={},
        pcb_model=model if pcb_model is None else pcb_model,
    )


def _shelf(category: str = "ic.ldo") -> PartLibrary:
    """A real shelf holding one entry: ``SYNTHREG`` / ``C0``, with ``category``.

    A real :class:`~boardwise.core.parts.PartLibrary` with a real
    :class:`~boardwise.core.parts.PartEntry`, so the rule reads it through the
    same ``find_facts`` exact-match pair a curated shelf goes through. An empty
    ``category`` is 「the shelf has not classified it」, which is the case the
    no-guessing test needs.
    """
    return PartLibrary(parts=[
        PartEntry(key="test.synthreg.c0", mpn="SYNTHREG", lcsc="C0", category=category)
    ])


def _synthetic_regulator_board(
    *,
    storage_x: float | None = 60.0,
    hf_x: float | None = 150.0,
    category: str = "ic.ldo",
):
    """U1 (``VIN``/``VOUT``/``GND``) with at most one capacitor of each pool.

    Everything is on y=0, so every gap is horizontal: U1's pads span x in
    ``[-20, +20]`` and a capacitor's pad at ``x`` spans ``[x-20, x+20]``, so the
    edge gap to U1 is ``x - 40`` for a capacitor placed to the right.
    ``storage_x=60`` → **20.0 mil**, ``hf_x=150`` → **110.0 mil**.
    ``None`` deletes that capacitor, which is how the empty pool is built.
    """
    parts = [("U1", 0.0, 0.0)]
    pads = [
        _pad("U1", "1", x=0.0, y=0.0, net="VIN_NET"),
        _pad("U1", "2", x=0.0, y=0.0, net="OUT_NET"),
        _pad("U1", "3", x=0.0, y=0.0, net="GND"),
    ]
    caps: list[Component] = []
    if hf_x is not None:
        parts.append(("C_HF", hf_x, 0.0))
        pads += [
            _pad("C_HF", "1", x=hf_x, y=0.0, net="OUT_NET"),
            _pad("C_HF", "2", x=hf_x, y=0.0, net="AGND"),
        ]
        caps.append(_comp("C_HF", value="100nF", pins=[
            Pin("1", "1", "OUT_NET"), Pin("2", "2", "AGND"),
        ]))
    if storage_x is not None:
        parts.append(("C_ST", storage_x, 0.0))
        pads += [
            _pad("C_ST", "1", x=storage_x, y=0.0, net="OUT_NET"),
            _pad("C_ST", "2", x=storage_x, y=0.0, net="AGND"),
        ]
        caps.append(_comp("C_ST", value="4.7uF", pins=[
            Pin("1", "1", "OUT_NET"), Pin("2", "2", "AGND"),
        ]))
    model = _model([
        _comp("U1", mpn="SYNTHREG", lcsc="C0", pins=[
            Pin("1", "VIN", "VIN_NET"),
            Pin("2", "VOUT", "OUT_NET"),
            Pin("3", "GND", "GND"),
        ]),
        *caps,
    ])
    return model, _board(parts, pads), _shelf(category)


def _run(model, board, *, category: str = "ic.ldo"):
    """Run the rule against the injected shelf."""
    return RegulatorCapDistance().check_with_library(_ctx(board, model), _shelf(category))


# ---------------------------------------------------------------------------
# the contract: mounted, house-rule sourced, threshold-free
# ---------------------------------------------------------------------------


def test_the_rule_is_mounted_and_says_what_it_is():
    """The rule exists, is mounted exactly once, and carries 钉 7's label."""
    rule = RegulatorCapDistance()
    assert rule.id == "pcb-regulator-cap-distance"
    assert rule.level == "L1-pcb-geometry"
    assert rule.source == "house rule（岳 2026-10 待裁）"
    assert [r.id for r in BUILTIN_PCB_RULES].count(rule.id) == 1
    for mounted in BUILTIN_PCB_RULES:
        assert isinstance(mounted, PcbRule)
        assert mounted.id.startswith("pcb-")


def test_no_threshold_constant_exists_yet():
    """This stick measures; it must not carry a number waiting for 岳's ruling.

    Asserted over the module's own names: a ``*_DISTANCE_MIL`` constant here
    would be a rule that quietly invented the ruling the task book defers.
    """
    import boardwise.rules.pcb.regulator as module

    assert [n for n in dir(module) if "DISTANCE_MIL" in n and n != "_mil"] == []
    assert "REGULATOR_CAP_DISTANCE_MIL" not in vars(module)


def test_the_pool_boundary_is_the_rulings_own_one_and_not_126b_s():
    """裁定 ③'s 1 µF, not 127b's 10 µF, and the scope is two categories."""
    from boardwise.rules.pcb.distance import BULK_FARADS, HF_FARADS

    assert HF_POOL_FARADS == 1e-6
    assert HF_POOL_FARADS == HF_FARADS        # the two agree on the ceiling
    assert HF_POOL_FARADS != BULK_FARADS       # 126b's bulk floor is 10 µF
    assert REGULATOR_CATEGORIES == frozenset({"ic.ldo", "ic.buck"})


@pytest.mark.parametrize(
    "value, pool",
    [
        ("100nF", POOL_HF),        # 0.1 µF
        ("10nF", POOL_HF),         # 0.01 µF
        ("1uF", POOL_STORAGE),     # exactly at the floor
        ("4.7uF", POOL_STORAGE),   # the band 126b leaves undecided
        ("2.2uF", POOL_STORAGE),
        ("10uF", POOL_STORAGE),    # the float the epsilon exists for
        ("330uF", POOL_STORAGE),
    ],
)
def test_pool_assignment_reads_the_declared_value(value, pool):
    """The pool is a function of the value the drawing states."""
    model = _model([
        _comp("C1", value=value, pins=[Pin("1", "1", "N"), Pin("2", "2", "G")])
    ])
    candidate = type("Candidate", (), {"designator": "C1"})()
    assert regulator_role(candidate, model) == pool


def test_an_unreadable_capacitance_is_in_neither_pool():
    """UNKNOWN is not a pool and is not silently rounded into one."""
    for value in ("", "10", "some-value"):
        model = _model([
            _comp("C1", value=value, pins=[Pin("1", "1", "N"), Pin("2", "2", "G")])
        ])
        candidate = type("Candidate", (), {"designator": "C1"})()
        assert regulator_role(candidate, model) == "", value


def test_the_pool_boundary_disagrees_with_126b_exactly_where_the_ruling_says():
    """``4.7uF`` is UNKNOWN under 127b's split and **storage** here.

    That disagreement is 裁定 ③, not a bug in either reader — and it is why the
    U11/C89 anchor exists at all.
    """
    model = _model([
        _comp("C89", value="4.7uF", pins=[Pin("1", "1", "+24V"), Pin("2", "2", "PGND")])
    ])
    candidate = type("Candidate", (), {"designator": "C89"})()
    assert capacitor_role(candidate, model).role == "unknown"
    assert regulator_role(candidate, model) == POOL_STORAGE


# ---------------------------------------------------------------------------
# synthetic, the states
# ---------------------------------------------------------------------------


def test_a_populated_pool_reports_the_nearest_capacitor_with_its_pad_pair():
    """State 1: a measurement row carrying the number, the pads and the net.

    U1's pads span x in [-20, 20]; ``C_ST`` at x=60 spans [40, 80] → **20.0 mil**.
    ``C_HF`` at x=150 spans [130, 170] → **110.0 mil**.
    """
    model, board, _shelf = _synthetic_regulator_board(storage_x=60.0, hf_x=150.0)
    findings = _run(model, board)

    storage = [f for f in findings if f.target.counterpart_ref == "C_ST"]
    assert len(storage) == 1
    assert storage[0].severity == "INFO"
    assert storage[0].target.measurement == {
        "kind": "distance", "value": 20.0, "unit": "mil",
    }
    assert storage[0].target.net_refs == ["OUT_NET"]
    assert "energy storage" in storage[0].message and "C_ST" in storage[0].message

    hf = [f for f in findings if f.target.counterpart_ref == "C_HF"]
    assert len(hf) == 1
    assert hf[0].target.measurement["value"] == 110.0
    assert "high-frequency bypass" in hf[0].message


def test_an_empty_pool_says_which_side_and_which_pool():
    """State 2: the row names the designator, the side, the net and the pool.

    126b could not write this row: it pools by **net** and says 「this IC sits
    on supply net X and there is no capacitor on it」. Here the side and the pool
    are both named, because they are what a reader needs in order to act.
    """
    model, board, _shelf = _synthetic_regulator_board(storage_x=None, hf_x=150.0)
    findings = _run(model, board)

    empty = [
        f for f in findings
        if f.target.net_refs == ["OUT_NET"] and f.target.counterpart_ref == ""
    ]
    assert len(empty) == 1
    message = empty[0].message
    assert "U1" in message
    assert "VOUT" in message and "OUT_NET" in message
    assert "energy storage pool is empty" in message
    assert empty[0].target.measurement is None
    # The HF row on the same side is still a measurement — one side, two pools.
    assert len([f for f in findings if f.target.net_refs == ["OUT_NET"]]) == 2


def test_no_threshold_means_a_far_capacitor_is_still_only_info():
    """State 3: 10 000 mil is 50x 126b's 200 mil house rule and still INFO.

    岳 has not ruled on a threshold for this rule, so a WARN here would dress
    the task's 「纯测量输出」 as a verdict.
    """
    model, board, _shelf = _synthetic_regulator_board(storage_x=10040.0, hf_x=150.0)
    findings = _run(model, board)
    assert findings
    assert {f.severity for f in findings} == {"INFO"}
    far = [f for f in findings if f.target.counterpart_ref == "C_ST"]
    assert far[0].target.measurement["value"] == 10000.0


def test_a_part_the_shelf_classifies_as_something_else_is_not_examined():
    """``ic.opamp`` is not a regulator, even on a ``U`` designator."""
    model, board, _shelf = _synthetic_regulator_board(category="ic.opamp")
    assert _run(model, board, category="ic.opamp") == []


def test_a_part_the_shelf_does_not_classify_is_not_guessed_at():
    """No category means UNKNOWN, not 「probably a regulator」.

    The shelf is the only place a part's *function* is stated — 87 of the 109
    curated entries carry no category at all (127b's measurement) — so an
    unclassified MPN is left unexamined rather than pattern-matched.
    """
    model, board, _shelf = _synthetic_regulator_board(category="")
    assert _run(model, board, category="") == []


def test_an_unplaced_regulator_and_an_absent_board_are_silence():
    """Nothing to measure against produces nothing, and raises nothing."""
    model, _board_geometry, shelf = _synthetic_regulator_board()
    rule = RegulatorCapDistance()
    # A board that does not carry the regulator at all:
    assert rule.check_with_library(_ctx(_board([], []), model), shelf) == []
    # No board, no model:
    assert rule.check_with_library(_ctx(None, model), shelf) == []
    assert rule.check(_ctx(None, None)) == []
    assert rule.check(_ctx(BoardGeometry(source="s", name="e"))) == []

def test_a_regulator_with_no_vout_pin_says_so_rather_than_guessing_one():
    """A buck's ``SW`` is a switching node, not an output.

    Promoting ``SW`` to an output would put a capacitor-pool measurement on the
    inductor node. The row names what could not be classified instead.
    """
    model = _model([
        _comp("U1", mpn="SYNTHREG", lcsc="C0", pins=[
            Pin("1", "GND", "PGND"),
            Pin("2", "VIN", "VIN_NET"),
            Pin("3", "SW", "SW_NET"),
        ]),
        _comp("C1", value="100nF", pins=[Pin("1", "1", "VIN_NET"), Pin("2", "2", "PGND")]),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C1", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="PGND"),
            _pad("U1", "2", x=0.0, y=0.0, net="VIN_NET"),
            _pad("U1", "3", x=0.0, y=0.0, net="SW_NET"),
            _pad("C1", "1", x=60.0, y=0.0, net="VIN_NET"),
            _pad("C1", "2", x=60.0, y=0.0, net="PGND"),
        ],
    )
    findings = _run(model, board)
    side_rows = [
        f for f in findings if "declares no pin whose name reads as VOUT" in f.message
    ]
    assert len(side_rows) == 1
    evidence = " ".join(side_rows[0].evidence)
    assert "SW" in evidence and "GND" in evidence
    # The VIN side still produced its two rows against VIN_NET.
    assert len([f for f in findings if f.target.net_refs == ["VIN_NET"]]) == 2


def test_the_rule_reads_pin_roles_never_net_name_patterns():
    """An ``Input`` pin on ``VCC`` is the input side; a ``SW`` pin on ``+24V`` is neither.

    011's lesson applied here: a name that reads like a rail is not a
    declaration, and a direction word on a signal net is.
    """
    assert pin_role("Output") == "OUT"
    assert pin_role("Input") == "IN"
    assert pin_role("SW") == "SW"

    model = _model([
        _comp("U1", mpn="SYNTHREG", lcsc="C0", pins=[
            Pin("1", "Input", "VCC"),     # an IN pin on a rail-named net
            Pin("2", "Output", "SIG"),    # an OUT pin on a signal net
            Pin("3", "SW", "+24V"),       # a switching node on a rail net
        ]),
        _comp("C1", value="100nF", pins=[Pin("1", "1", "VCC"), Pin("2", "2", "PGND")]),
        _comp("C2", value="100nF", pins=[Pin("1", "1", "SIG"), Pin("2", "2", "PGND")]),
        _comp("C3", value="100nF", pins=[Pin("1", "1", "+24V"), Pin("2", "2", "PGND")]),
    ])
    board = _board(
        [("U1", 0.0, 0.0), ("C1", 60.0, 0.0), ("C2", 60.0, 0.0), ("C3", 60.0, 0.0)],
        [
            _pad("U1", "1", x=0.0, y=0.0, net="VCC"),
            _pad("U1", "2", x=0.0, y=0.0, net="SIG"),
            _pad("U1", "3", x=0.0, y=0.0, net="+24V"),
            _pad("C1", "1", x=60.0, y=0.0, net="VCC"),
            _pad("C1", "2", x=60.0, y=0.0, net="PGND"),
            _pad("C2", "1", x=60.0, y=0.0, net="SIG"),
            _pad("C2", "2", x=60.0, y=0.0, net="PGND"),
            _pad("C3", "1", x=60.0, y=0.0, net="+24V"),
            _pad("C3", "2", x=60.0, y=0.0, net="PGND"),
        ],
    )
    findings = _run(model, board)
    assert len([f for f in findings if f.target.net_refs == ["VCC"]]) == 2
    assert all("VIN" in f.message for f in findings if f.target.net_refs == ["VCC"])
    assert len([f for f in findings if f.target.net_refs == ["SIG"]]) == 2
    assert all("VOUT" in f.message for f in findings if f.target.net_refs == ["SIG"])
    # +24V belongs to no side, so it is measured only as evidence, never as a row.
    assert [f for f in findings if f.target.net_refs == ["+24V"]] == []


# ---------------------------------------------------------------------------
# 毕设FOC 1.0.0 — the three regulators, table-pinned
# ---------------------------------------------------------------------------


def _foc_100_rows(model=None) -> dict:
    """``{(designator, side, pool): finding}`` on 毕设FOC 1.0.0, PCB1.

    ``model`` defaults to the **PCB-side** view of the backup — see the module
    docstring for why, and why this is not a fixture accident.
    """
    if model is None:
        model, _geometry = cli._load_model(FOC_100, view="pcb")
    findings, _section = run_pcb_review(
        FOC_100, model=model, rules=[RegulatorCapDistance()]
    )
    rows: dict = {}
    for finding in findings:
        message = finding.message
        side = "VIN" if "VIN" in message else ("VOUT" if "VOUT" in message else "?")
        pool = (
            "HF" if "high-frequency bypass" in message
            else "STORAGE" if "energy storage" in message
            else "?"
        )
        rows[(finding.target.component_ref, side, pool)] = finding
    return rows


def test_the_three_regulators_of_bishe_foc_1_0_0_are_the_ones_examined():
    """U11 (buck), U5 and U6 (LDOs) — and ``U20`` / ``REF2033`` is not one.

    ``U20``'s shelf category is ``ic.reference``: a voltage reference has no
    input stage to place an input capacitor against, and asking it for one
    would file a finding against a part with no such pin.
    """
    model, _geometry = cli._load_model(FOC_100, view="pcb")
    readings = {r.designator: r for r in _regulator_readings(model)}
    assert set(readings) == {"U5", "U6", "U11"}
    assert readings["U11"].category == "ic.buck"
    assert readings["U5"].category == "ic.ldo"
    assert readings["U6"].category == "ic.ldo"
    # the side nets, read from the pin names
    assert readings["U11"].nets_by_side["IN"] == ["+24V"]
    assert readings["U5"].nets_by_side["IN"] == ["+5V"]
    assert readings["U5"].nets_by_side[SIDE_OUTPUT] == ["$1N66612"]
    assert readings["U6"].nets_by_side[SIDE_OUTPUT] == ["$1N66627"]


def test_the_acceptance_anchor_u11_c89_is_the_vin_storage_nearest():
    """**Anchor 1.** C89 (4.7 µF) is U11's VIN storage nearest, at 99.5 mil.

    This is the 冤案 the task book names. 126b measures the **HF** pool only and
    reports 「no high-frequency decoupling capacitor on ``+24V``」, because on
    that net C89 is a 4.7 µF part and 126b's split calls it neither pool. 裁定 ③
    calls it storage, so it is in a pool here, it is measured, and the row names
    it.
    """
    rows = _foc_100_rows()
    finding = rows[("U11", "VIN", "STORAGE")]
    assert finding.target.counterpart_ref == "C89"
    assert finding.target.measurement == {
        "kind": "distance", "value": 99.5, "unit": "mil",
    }
    assert finding.target.net_refs == ["+24V"]
    # The HF pool on the same net really is empty — that row is about the pool,
    # and it quotes C89 as the part that was excluded from it.
    hf = rows[("U11", "VIN", "HF")]
    assert hf.target.counterpart_ref == "" and "empty" in hf.message
    assert any(
        line.startswith("candidate C89") and "energy storage pool" in line
        for line in hf.evidence
    )


def test_the_acceptance_anchor_u5_output_pool_holds_only_its_own_net():
    """**Anchor 2.** U5's output pool is ``C3``/``C4`` and no ``+5V`` part.

    This is the 「按引脚角色分池不按网分池」 check. A net-pooled reading gives U5
    everything on ``+5V`` — ``C5``, ``C11``, ``C93``, ``C98``, ``C101`` — as its
    output decoupling, because ``+5V`` is U5's *input* rail and U6's as well.
    U5's real output net is ``$1N66612``, and U6's is ``$1N66627``; they share
    no part.
    """
    rows = _foc_100_rows()
    hf = rows[("U5", "VOUT", "HF")]
    assert hf.target.net_refs == ["$1N66612"]
    assert hf.target.counterpart_ref == "C3"
    assert hf.target.measurement["value"] == 41.8
    candidates_line = next(
        line for line in hf.evidence if line.startswith("candidates bridging")
    )
    assert candidates_line.endswith("C3, C4"), candidates_line
    for input_side_part in ("C5", "C11", "C93", "C98", "C101"):
        assert input_side_part not in candidates_line
        assert input_side_part not in hf.message

    storage = rows[("U5", "VOUT", "STORAGE")]
    assert storage.target.counterpart_ref == ""
    assert "energy storage pool is empty" in storage.message

    # U5's input side lives on the very net it shares with U6 and is a separate
    # row set whose nearest parts are different capacitors.
    assert rows[("U5", "VIN", "STORAGE")].target.counterpart_ref == "C5"
    assert rows[("U5", "VIN", "HF")].target.counterpart_ref == "C93"
    assert rows[("U6", "VIN", "STORAGE")].target.counterpart_ref == "C101"
    assert rows[("U6", "VOUT", "STORAGE")].target.counterpart_ref == "C64"


def test_u6_storage_nearest_on_its_output_net_is_c64():
    """U6's output net ``$1N66627`` — C64 (2.2 µF) is its storage nearest."""
    rows = _foc_100_rows()
    finding = rows[("U6", "VOUT", "STORAGE")]
    assert finding.target.counterpart_ref == "C64"
    assert finding.target.measurement["value"] == 91.4
    assert rows[("U6", "VOUT", "HF")].target.counterpart_ref == "C13"


def test_the_buck_has_no_vout_side_and_says_so():
    """The LM5164's output is behind ``SW``/``FB``, so the VOUT row is an UNKNOWN one.

    This is a **stated gap, not a pass**: the buck does have an output
    capacitor and this rule does not measure it, because its output side is the
    inductor node. The row names what could not be classified (``SW``, ``FB``,
    ``BST``, ``EN/UVLO``, ``RON``, ``PGOOD``, ``GND``, ``EP``) so a reader can
    see the rule's blind spot rather than infer a clean bill of health.
    """
    rows = _foc_100_rows()
    assert ("U11", "VOUT", "HF") not in rows and ("U11", "VOUT", "STORAGE") not in rows
    side_rows = [
        f for f in rows.values()
        if "declares no pin whose name reads as VOUT" in f.message
    ]
    assert len(side_rows) == 1
    evidence = " ".join(side_rows[0].evidence)
    for name in ("SW", "FB", "BST", "EN/UVLO", "PGOOD", "EP"):
        assert name in evidence


def test_the_whole_1_0_0_table_is_pinned():
    """Every (regulator, side, pool) row on 毕设FOC 1.0.0, with its numbers."""
    rows = _foc_100_rows()
    assert {
        key: (f.target.counterpart_ref, (f.target.measurement or {}).get("value"))
        for key, f in rows.items()
    } == {
        ("U11", "VIN", "HF"): ("", None),
        ("U11", "VIN", "STORAGE"): ("C89", 99.5),
        ("U11", "VOUT", "?"): ("", None),
        ("U5", "VIN", "HF"): ("C93", 521.2),
        ("U5", "VIN", "STORAGE"): ("C5", 95.9),
        ("U5", "VOUT", "HF"): ("C3", 41.8),
        ("U5", "VOUT", "STORAGE"): ("", None),
        ("U6", "VIN", "HF"): ("C98", 107.5),
        ("U6", "VIN", "STORAGE"): ("C101", 118.7),
        ("U6", "VOUT", "HF"): ("C13", 244.8),
        ("U6", "VOUT", "STORAGE"): ("C64", 91.4),
    }


def test_every_row_on_the_fixture_is_info_and_stamped_with_its_board():
    """No threshold means no WARN anywhere, and 钉 4 stamps the board title."""
    model, _geometry = cli._load_model(FOC_100, view="pcb")
    findings, section = run_pcb_review(
        FOC_100, model=model, rules=[RegulatorCapDistance()]
    )
    assert findings
    assert {f.severity for f in findings} == {"INFO"}
    assert {f.board for f in findings} == {"PCB1"}
    assert section is not None and section["boards"][0]["checksRun"] == [
        "pcb-regulator-cap-distance"
    ]


# ---------------------------------------------------------------------------
# ROBOT ctrl FOC — U8 = AMS1117-3.3
# ---------------------------------------------------------------------------


def test_the_robot_ldo_reports_both_pools_on_both_sides():
    """U8's VIN is ``+12V`` and its VOUT is ``VCC`` — two pools each.

    The AMS1117 is the case where two ``Output`` pins share one net, so the
    output side has one net and both pools are measured against it. The VIN row
    is the interesting one: ``+12V`` carries U8's own ``C10`` (10 µF), which is
    storage by 裁定 ③ and is that pool's nearest member at 35.0 mil.
    """
    model, _geometry = cli._load_model(ROBOT, view="pcb")
    findings, _section = run_pcb_review(
        ROBOT, model=model, rules=[RegulatorCapDistance()]
    )
    rows = {}
    for finding in findings:
        side = "VIN" if "VIN" in finding.message else "VOUT"
        pool = "HF" if "high-frequency bypass" in finding.message else "STORAGE"
        rows[(finding.target.component_ref, side, pool)] = finding
    assert {
        key: (f.target.counterpart_ref, (f.target.measurement or {}).get("value"))
        for key, f in rows.items()
    } == {
        ("U8", "VIN", "HF"): ("C6", 187.5),
        ("U8", "VIN", "STORAGE"): ("C10", 35.0),
        ("U8", "VOUT", "HF"): ("C15", 420.7),
        ("U8", "VOUT", "STORAGE"): ("C7", 62.8),
    }
    assert {f.target.component_ref for f in findings} == {"U8"}


# ---------------------------------------------------------------------------
# 毕设FOC 1.1.0 and llc — the boards with no placed regulator
# ---------------------------------------------------------------------------


def test_the_three_document_export_now_reaches_its_pcb1_regulators():
    """毕设FOC 2026-09-17 (the three-document 1.1.0 export): **131c changed this
    file's answer**, and the change is the point.

    131b recorded this board as the first-document blind spot:
    :func:`boardwise.parsers.epro2_model.build_design_model` read the backup's
    *first* PCB document only — ``PCB3``, 33 components — which places none of
    the three regulators, so the whole review produced nothing while ``PCB1``
    (105 components) carried all of them. The test below asserted that silence
    and called it 「a **model-scope limitation**, not a claim that the export has
    no power stage」.

    131c closed it. :func:`boardwise.engines.pcbreview.run_pcb_review` now builds
    one netlist view **per PCB document** and hands it over as
    ``ctx.pcb_model``, and this rule reads that field. So the same file now
    yields 11 rows on ``PCB1`` — the three regulators 131b's own test says the
    schematic names (``U7`` = ``LM5164DDAR``/``ic.buck``, ``U11`` =
    ``RT9013-33GB``/``ic.ldo``, ``U13`` = ``TPLP2981-30DBVR``/``ic.ldo``), now
    read off the board that actually places them.

    The designator numbering is 127a's measured fact, not a guess: this export
    renumbered against the 1.0.0 one, so the LM5164 is ``U7`` here and ``U11``
    there. ``PCB3`` and ``PCB2`` still produce nothing — neither places a part
    the shelf calls a regulator — and the rule still *ran* on every document,
    which is what ``checksRun`` records.
    """
    model, _geometry = cli._load_model(FOC_110, view="pcb")
    assert _regulator_readings(model) == [], (
        "the first-document model still places no regulator; the fix is that the "
        "runner no longer asks it for the whole review"
    )
    findings, section = run_pcb_review(
        FOC_110, model=model, rules=[RegulatorCapDistance()]
    )
    assert {f.target.component_ref for f in findings} == {"U7", "U11", "U13"}
    assert {f.board for f in findings} == {"PCB1"}
    assert all(f.severity == "INFO" for f in findings)
    # Per-document: the two small documents place no regulator part at all.
    assert [b["findings"] for b in section["boards"]] == [[], list(range(len(findings))), []]
    # And the schematic view of the same file names the same three — the two
    # views agree on *which parts*, which is why the earlier silence was a
    # scope gap and not a disagreement.
    schematic, _geometry = cli._load_model(FOC_110, view="schematic")
    assert {r.designator for r in _regulator_readings(schematic)} == {"U7", "U11", "U13"}


def test_llc_names_no_regulator_either():
    """llc's shelf has no ``ic.ldo`` / ``ic.buck`` entry, so the rule is silent.

    Pinned because 126b's llc silence test is the reason ``checksRun`` there
    names all five rules: a rule that never fires and a rule that fires
    correctly are only told apart by a test that demands nothing.
    """
    model, _geometry = cli._load_model(LLC, view="pcb")
    assert _regulator_readings(model) == []
    findings, _section = run_pcb_review(LLC, model=model, rules=[RegulatorCapDistance()])
    assert findings == []
