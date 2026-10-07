"""Tests for task 126 stick 3 (126c): the two IPC-2221 rules.

Three evidence sources, per the task book (§126c「测试」):

* **Synthetic boards** — a hand-built
  :class:`~boardwise.core.geometry.BoardGeometry` with axis-aligned pads and
  tracks at stated coordinates, plus a hand-built
  :class:`~boardwise.core.model.DesignModel` and a hand-built
  :class:`~boardwise.core.designintent.DesignIntent`. Every expected number is
  **derived by hand in the comment next to the assertion**: the ampacity
  inversion is written out longhand, the spacing band is a subtraction, and both
  are the same arithmetic :func:`required_width_mil` /
  :func:`required_spacing_mil` perform — so a reviewer can check the rule against
  the formula rather than against itself. This is where the three states are
  pinned: a violation, an OK (silence), and an UNKNOWN naming the missing fact.
* **ROBOT ctrl FOC** (``ProPrj_ROBOT ctrl FOC_2026-09-16.epro2`` plus the real
  ``blocklib/intents/robot-ctrl-foc.intent.json``, both read-only) — the **true
  contract anchor**, because it is the only fixture that declares a current at
  all: ``requirements.signals[net=U+].range = "±3A"``.
* **毕设FOC** (``ProPrj_毕设FOC驱动板_2026-09-17.epro2``, read-only, **no**
  contract) — the anchor for the half of the discipline that has no contract:
  what 「no current declared」 and 「no voltage established」 actually produce on a
  real board, and (with llc) what a board with neither produces.

Plus the three structural pins 126c owns: the two rules are in
``BUILTIN_PCB_RULES`` **in the declared order**, their ``source`` strings name
IPC-2221 rather than a house number (钉 7 — the contrast with 126b's two
「house rule（岳 2026-10 待裁）」 is the point), and UNKNOWN travels as an **INFO
finding whose message names the missing fact** rather than as a four-state
:class:`~boardwise.rules.base.Outcome`, with the reason pinned.

The offline fixtures are read-only. Nothing here runs an editor or a daemon.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.designintent import (
    DesignIntent,
    IntentRail,
    IntentSignal,
)
from boardwise.core.geometry import (
    BoardGeometry,
    ComponentPlacement,
    LayerInfo,
    PadGeometry,
    Point,
    TrackSegment,
    index_by_net,
)
from boardwise.core.measure import net_clearance
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.pcbreview import BUILTIN_PCB_RULES, run_pcb_review
from boardwise.rules.base import Outcome
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.distance import ComponentSpacing, DecapDistance
from boardwise.rules.pcb.ipc import (
    COPPER_THICKNESS_MIL,
    INNER_K,
    OUTER_K,
    SPACING_TABLE_MAX_V,
    TEMP_RISE_C,
    VOLTAGE_SPACING_MIL,
    TrackAmpacity,
    VoltageSpacing,
    declared_currents,
    required_spacing_mil,
    required_width_mil,
)

FIXTURES = Path(__file__).parent / "fixtures"
FOC = FIXTURES / "ProPrj_毕设FOC驱动板_2026-09-17.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
LLC = FIXTURES / "llc_board.epro2"
ROBOT_INTENT = Path(__file__).resolve().parents[1] / "blocklib" / "intents" / "robot-ctrl-foc.intent.json"
SHELF = Path(__file__).resolve().parents[1] / "blocklib" / "parts.json"

#: The PCB document title the runner stamps on this fixture's findings (钉 4).
ROBOT_BOARD = "PCB1"


# ---------------------------------------------------------------------------
# synthetic helpers — every geometry below is axis-aligned, so every distance
# is a subtraction anyone can redo
# ---------------------------------------------------------------------------


def _pad(
    component: str,
    pin: str,
    *,
    x: float,
    y: float,
    net: str,
    width: float = 40.0,
    height: float = 40.0,
) -> PadGeometry:
    """One **axis-aligned** 40x40 pad, so a gap is ``|x1 - x2| - 40``."""
    return PadGeometry(
        id=f"{component}.{pin}",
        component=component,
        pin_number=pin,
        net=net,
        layer_id=1,
        x=x,
        y=y,
        width=width,
        height=height,
        shape="RECT",
        angle=0.0,
    )


def _track(
    ident: str,
    *,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    net: str,
    width: float = 10.0,
    layer_id: int = 1,
) -> TrackSegment:
    """One axis-aligned (or vertical) track of stated width."""
    return TrackSegment(
        id=ident,
        net=net,
        layer_id=layer_id,
        start=Point(x1, y1),
        end=Point(x2, y2),
        width=width,
    )


def _layers(*definitions: tuple[int, str, str]) -> dict[int, LayerInfo]:
    return {
        layer_id: LayerInfo(layer_id=layer_id, name=name, layer_type=kind)
        for layer_id, name, kind in definitions
    }


#: The layer vocabulary the synthetic boards use. ``1``/``2`` are the external
#: faces (which pick ``OUTER_K``) and ``16`` is an inner signal layer (which
#: picks ``INNER_K``); ``99`` exists **only** in the one test that needs a track
#: on a layer the document never defines.
TOP_AND_INNER = _layers(
    (1, "Top Layer", "TOP"),
    (2, "Bottom Layer", "BOTTOM"),
    (16, "Inner2", "SIGNAL"),
)


def _board(
    pads: list[PadGeometry], tracks: list[TrackSegment], *, layers=None
) -> BoardGeometry:
    designators = sorted({pad.component for pad in pads})
    return BoardGeometry(
        source="synthetic",
        name="SYNTH",
        layers=dict(layers if layers is not None else TOP_AND_INNER),
        components=[
            ComponentPlacement(id=f"c-{d}", designator=d, x=0.0, y=0.0, layer_id=1)
            for d in designators
        ],
        pads=list(pads),
        tracks=list(tracks),
    )


def _model(components: list[Component]) -> DesignModel:
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


def _ctx(
    board: BoardGeometry,
    model: DesignModel | None = None,
    intent: DesignIntent | None = None,
) -> PcbReviewContext:
    return PcbReviewContext(
        board=board, board_title="SYNTH", model=model, intent=intent, module_of={}
    )


def _contract(
    *,
    signals: list[IntentSignal] = (),
    rails: list[IntentRail] = (),
) -> DesignIntent:
    return DesignIntent(signals=list(signals), rails=list(rails))


#: A two-net synthetic board: ``HV`` (pads at x=0, one track on layer 1) and
#: ``LV`` (pads at x=200). Both pads are 40x40, so a pad-to-pad gap is
#: ``|200 - 0| - 40 = 160.0`` mil, and the LV track's own width is 20 mil.
def _two_net_board(
    *,
    hv_track_width: float = 10.0,
    lv_track_width: float = 20.0,
    hv_layer: int = 1,
    lv_x: float = 200.0,
    lv_track_y: float = 0.0,
    lv_track_x: tuple[float, float] | None = None,
    pad_x: tuple[float, float] | None = None,
) -> BoardGeometry:
    """``HV``'s track on y=0 (x from -200 to -20); ``LV``'s track wherever asked.

    The LV track's x-range is a parameter because two of the clearance tests need
    the two tracks' x-ranges to **overlap** — a capsule pair whose bodies only ever
    approach end-on is measured between the end point and the far edge, which is a
    different number than the one those tests are about. Overlapping the x-ranges
    makes the closest approach a pure y-gap, which is a subtraction anyone can
    redo: two 10 mil capsules on y = 0 and y = h are ``(h - 5) - 5`` apart.
    """
    pads = pad_x or (0.0, lv_x)
    track_span = lv_track_x or (lv_x + 20.0, lv_x + 200.0)
    return _board(
        [
            _pad("J1", "1", x=pads[0], y=0.0, net="HV"),
            _pad("J2", "1", x=pads[1], y=0.0, net="LV"),
        ],
        [
            _track("hv-1", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0,
                   net="HV", width=hv_track_width, layer_id=hv_layer),
            _track("lv-1", x1=track_span[0], y1=lv_track_y,
                   x2=track_span[1], y2=lv_track_y,
                   net="LV", width=lv_track_width, layer_id=1),
        ],
    )


# ---------------------------------------------------------------------------
# the arithmetic, verified longhand against the constants
# ---------------------------------------------------------------------------


def test_the_ampacity_inversion_is_the_standard_equation_solved_longhand():
    """``I = k·ΔT^0.44·A^0.725`` inverted, checked against a hand evaluation.

    The task book's own numbers, done out:

    * ``ΔT^0.44`` with ``ΔT = 10`` is ``10^0.44`` = 2.754228703338166;
    * external, 3 A: ``A = (3 / (0.048 · 2.754228703338166))^1/0.725``
      = ``(3 / 0.13220297776023197)^1/0.725`` = ``22.693776^1.3879310...``
      = **74.16164155367699 mil²**, so the width at 1.378 mil copper is
      ``74.16164155367699 / 1.378`` = **53.81831752806748 mil**;
    * internal, 3 A: ``k`` is halved, so ``A`` goes up by exactly ``2^1/0.725``
      = 2.6018... and the width comes out at **140.0051153776043 mil**;
    * the back direction, so the function is pinned in *both* senses: a 10 mil
      external track of 1 oz copper carries
      ``0.048 · 10^0.44 · (10 · 1.378)^0.725`` = **0.8855170346618377 A**.

    The 3 A case is not an arbitrary number: it is the ROBOT contract's own
    ``range: "±3A"``, so this is the arithmetic behind the real anchor below.
    """
    assert TEMP_RISE_C == 10.0
    assert COPPER_THICKNESS_MIL == 1.378
    assert (OUTER_K, INNER_K) == (0.048, 0.024)

    outer = required_width_mil(3.0)
    assert outer == pytest.approx(53.81831752806748, abs=1e-9)
    inner = required_width_mil(3.0, inner=True)
    assert inner == pytest.approx(140.0051153776043, abs=1e-9)

    # Hand-evaluated the long way, from the constants rather than the function.
    delta = TEMP_RISE_C ** 0.44
    area = (3.0 / (OUTER_K * delta)) ** (1 / 0.725)
    assert area == pytest.approx(74.16164155367699, abs=1e-9)
    assert area / COPPER_THICKNESS_MIL == pytest.approx(outer, abs=1e-9)

    # Back direction: what a 10 mil external track may carry.
    assert OUTER_K * delta * (10.0 * COPPER_THICKNESS_MIL) ** 0.725 == pytest.approx(
        0.8855170346618377, abs=1e-12
    )
    assert required_width_mil(0.8855170346618377) == pytest.approx(10.0, abs=1e-6)
    # And the inner conductor of the same width carries half of it.
    assert INNER_K * delta * (10.0 * COPPER_THICKNESS_MIL) ** 0.725 == pytest.approx(
        0.44275851733091887, abs=1e-12
    )
    # "No current, no width" — and never an exception on a nonsense input.
    assert required_width_mil(0.0) == 0.0
    assert required_width_mil(-1.0) == 0.0


def test_the_spacing_bands_are_the_standard_table_read_as_data():
    """IPC-2221 Table 6-1 column B2, simplified — every band's own lookup.

    The band each difference lands in, and the value that comes out:

    * ``0`` and ``3.3`` and ``12`` and ``15`` V → the ``0–15`` band → **4 mil**;
    * ``24`` and ``30`` V → the ``15–30`` band → **4 mil** (the standard states
      the same 0.1 mm for 0–15 and 16–30, and the two bands are kept separate
      because that is how the standard's own rows are shaped);
    * ``31`` V is the first value that crosses into the ``30–150`` band →
      **24 mil** — this is the band edge the synthetic three-state test lands on,
      so it is the one that matters;
    * ``150`` → still 24 mil (the band is inclusive at its top); ``150.1`` →
      **50 mil**;
    * ``300`` → **50 mil**; ``300.1`` → **100 mil**;
    * ``500`` → **100 mil** (the last band), and ``501`` → the standard's
      arithmetic continuation, ``+0.005 mm`` per volt = 0.19685 mil, giving
      **100.19685… mil**;
    * above :data:`SPACING_TABLE_MAX_V` the function refuses (``None``) rather
      than extrapolating — that band belongs to IEC 60950 (岳 2026-10-06 裁).
    """
    assert VOLTAGE_SPACING_MIL == (
        (0.0, 15.0, 4.0),
        (15.0, 30.0, 4.0),
        (30.0, 150.0, 24.0),
        (150.0, 300.0, 50.0),
        (300.0, 500.0, 100.0),
    )
    assert [required_spacing_mil(v) for v in (0.0, 3.3, 12.0, 15.0)] == [4.0] * 4
    assert [required_spacing_mil(v) for v in (24.0, 30.0)] == [4.0, 4.0]
    assert required_spacing_mil(31.0) == 24.0
    assert required_spacing_mil(150.0) == 24.0
    assert required_spacing_mil(150.1) == 50.0
    assert required_spacing_mil(300.0) == 50.0
    assert required_spacing_mil(300.1) == 100.0
    assert required_spacing_mil(500.0) == 100.0
    assert required_spacing_mil(501.0) == pytest.approx(100.0 + 0.005 / 0.0254)
    # A difference is a difference: the sign of the argument cannot matter.
    assert required_spacing_mil(-24.0) == required_spacing_mil(24.0)
    # And past the authority's reach it says so instead of guessing.
    assert required_spacing_mil(SPACING_TABLE_MAX_V) is not None
    assert required_spacing_mil(SPACING_TABLE_MAX_V + 1.0) is None


# ---------------------------------------------------------------------------
# 钉 7 / the structure gate: the two rules are listed, and their source is a
# standard rather than a house number
# ---------------------------------------------------------------------------


def test_both_rules_are_in_the_builtin_list_in_the_declared_order():
    """「The list is the truth」 — the structure gate 126a put up, now four deep.

    126c **appends** its two to 126b's pair rather than interleaving them, so the
    executed order is 「house rules first, standards-derived readings second」.
    The order is pinned because the report's ``pcb_review.boards[].checksRun``
    prints it: a reader comparing two reports needs to know the difference
    between a rule that was added and a rule that was moved.
    """
    assert [rule.id for rule in BUILTIN_PCB_RULES] == [
        "pcb-decap-distance",
        "pcb-component-spacing",
        "pcb-track-ampacity",
        "pcb-voltage-spacing",
    ]


def test_both_thresholds_quote_ipc_2221_not_a_house_number():
    """钉 7: the contrast with 126b is the whole assertion.

    126b's two rules say 「house rule（岳 2026-10 待裁）」 because neither of their
    numbers comes from a standard. 126c's two are the batch the task book calls
    「阈值出处 IPC-2221」, so both ``source`` strings must name IPC-2221 and
    neither may claim the pending-ruling house-rule token — if either ever
    regresses into a house rule, this goes red, because that would mean a number
    with no standard behind it was being presented as one.
    """
    assert TrackAmpacity.source.startswith("IPC-2221")
    assert VoltageSpacing.source.startswith("IPC-2221")
    for rule in (TrackAmpacity(), VoltageSpacing()):
        assert "house rule" not in rule.source
        assert "待裁" not in rule.source, (
            "126c's numbers come from a standard, so they are not pending a ruling"
        )
    # The IPC-2221 batch also says which *column* and why — the ampacity half
    # names both constants, the spacing half names Table 6-1 and its upgrade.
    assert "0.048" in TrackAmpacity.source and "0.024" in TrackAmpacity.source
    assert "Table 6-1" in VoltageSpacing.source and "B2" in VoltageSpacing.source
    assert "IEC 60950" in VoltageSpacing.source
    # And the two 126b rules still say what they always said (this file did not
    # quietly re-standardise the house rules).
    assert DecapDistance.source == "house rule（岳 2026-10 待裁）"
    assert ComponentSpacing.source == "house rule（岳 2026-10 待裁）"


# ---------------------------------------------------------------------------
# pcb-track-ampacity — synthetic, three states
# ---------------------------------------------------------------------------


def test_an_over_narrow_track_for_the_declared_current_is_an_error():
    """State 1 (VIOLATION): 3 A on a 10 mil external track → ERROR.

    The board declares ``signals[net=HV].range = "±3A"``, which the rule reads
    as a magnitude of 3.0 A (the ``±`` marks a bidirectional chain, not a
    doubled load). The ``HV`` net's only track is 10 mil wide on layer 1, which
    the document calls ``TOP`` — external, so ``k = 0.048`` and
    :func:`required_width_mil` asks for **53.8 mil** (verified longhand in the
    test above). 10 < 53.8, so:

    * the severity is **ERROR**, and the reason is written into the rule's
      ``source``: an overloaded conductor is a safety matter, not a preference;
    * the target carries the net, the measured minimum width and the **layer it
      was read on** — a per-layer number belongs to a named layer, which is what
      ``measurement.layer_ids`` is for (钉 3's optional key), and a plan-view
      clearance has no such layer so it does not use one.
    """
    board = _two_net_board(hv_track_width=10.0)
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "GND")]),
            _component("J2", [Pin("1", "1", "LV"), Pin("2", "2", "GND")]),
        ]),
        _contract(signals=[IntentSignal(net="HV", slots={"range": "±3A"})]),
    )
    findings = TrackAmpacity().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "pcb-track-ampacity"
    assert finding.severity == "ERROR"
    assert finding.target.net_refs == ["HV"]
    assert finding.target.measurement == {
        "kind": "width", "value": 10.0, "unit": "mil", "layer_ids": [1],
    }
    assert "53.8" in finding.message, "the required width is in the prose too"
    assert "3 A" in finding.message
    # The evidence carries all three numbers separately, so a reviewer can
    # disagree with any one of them without re-running anything.
    joined = " | ".join(finding.evidence)
    assert "±3A" in joined and "min width 10.0000 mil" in joined
    assert "required width 53.8183 mil" in joined


def test_a_track_wider_than_it_needs_is_silence_not_a_finding():
    """State 2 (OK): margin is not a defect.

    Same board and same declaration, but the ``HV`` track is now 60 mil wide —
    above the 53.8 mil the standard asks for. The rule says **nothing**: a
    design is entitled to over-provision copper, and a rule that reported
    surplus copper as a finding would be reporting taste with a standard's
    vocabulary, which trains readers to ignore the ERRORs that do matter.
    """
    board = _two_net_board(hv_track_width=60.0)
    ctx = _ctx(
        board,
        _model([_component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "GND")])]),
        _contract(signals=[IntentSignal(net="HV", slots={"range": "±3A"})]),
    )
    assert TrackAmpacity().check(ctx) == []


def test_the_width_boundary_is_exactly_at_the_line_and_past_it():
    """The comparison is ``>=``: exactly the required width passes.

    53.8183... mil is the answer, so the two boards here are stated at
    ``required_width_mil(3.0)`` and one ten-thousandth of a mil under it. The
    check is written as ``min_width + 1e-9 >= needed``, which is what makes both
    boards fall on the side the assertion claims; without the epsilon the
    exactly-at-the-line board would flip on float noise, and a layout that lands
    a track on the limit would produce a report row that depends on rounding.
    """
    needed = required_width_mil(3.0)
    exactly = _ctx(
        _two_net_board(hv_track_width=needed),
        _model([_component("J1", [Pin("1", "1", "HV")])]),
        _contract(signals=[IntentSignal(net="HV", slots={"range": "±3A"})]),
    )
    assert TrackAmpacity().check(exactly) == []
    just_under = _ctx(
        _two_net_board(hv_track_width=needed - 0.001),
        _model([_component("J1", [Pin("1", "1", "HV")])]),
        _contract(signals=[IntentSignal(net="HV", slots={"range": "±3A"})]),
    )
    assert len(TrackAmpacity().check(just_under)) == 1


def test_the_same_width_on_an_inner_layer_needs_more_copper_than_on_an_outer():
    """The layer's position is in the answer, and it is the layer **id** that says so.

    **2 A**, chosen because it lands *between* the two required widths and so
    turns the layer question into the only thing deciding the verdict:

    * external: ``(2/(0.048·10^0.44))^1/0.725 / 1.378`` = **30.8 mil**, so a
      40 mil track passes;
    * internal: ``(2/(0.024·10^0.44))^1/0.725 / 1.378`` = **80.0 mil**, so the
      same 40 mil track fails by a factor of two.

    This is the one asymmetry in the rule, and it is pinned from both sides
    because a rule that used one constant everywhere would look right on a
    two-layer board and be wrong on the four-layer one (毕设FOC's PCB1 is four).
    """
    model = _model([_component("J1", [Pin("1", "1", "HV")])])
    contract = _contract(signals=[IntentSignal(net="HV", slots={"range": "2A"})])
    outer = _ctx(_two_net_board(hv_track_width=40.0, hv_layer=1), model, contract)
    inner = _ctx(_two_net_board(hv_track_width=40.0, hv_layer=16), model, contract)
    assert TrackAmpacity().check(outer) == [], (
        "40 mil external carries 2.63 A, and 2.0 A needs 30.8 mil"
    )
    inner_findings = TrackAmpacity().check(inner)
    assert len(inner_findings) == 1
    assert inner_findings[0].target.measurement["layer_ids"] == [16]
    assert "80.0" in inner_findings[0].message


def test_a_current_that_does_not_parse_is_unknown_naming_where_to_write_one():
    """State 3 (UNKNOWN): the contract *says* something, and it is not a current.

    Three shapes on one board, all of them the UNKNOWN case:

    * ``HV`` declares ``continuousCurrent = "5"`` — a bare number with no unit,
      which the shared current grammar refuses (011's lesson: an unparseable
      declaration must never become a guess);
    * ``PWR`` declares ``continuousCurrent = "5V"`` — the wrong dimension, and
      just as unreadable;
    * ``BUS`` declares ``signals[].range = "±3A or so"`` — prose, which the
      range reading refuses for the same reason.

    Note what makes these subjects at all: :func:`declared_currents` returns a
    map of *readable* currents, so a net whose declaration is unreadable is
    **not** in it — and the rule's subject is the contract's nets **that carry
    copper on this board**, compared against that map. A declaration is what
    puts a net on the list; a readable one is what answers the question. That is
    the only reading under which the UNKNOWN row has anything to say: 「you
    declared something here and it is not a current」 is actionable, whereas
    「you declared nothing here at all」 is only a restatement of the module's
    no-subject discipline, which is silence (pinned in the next test).

    The row is INFO and must name the net, **both** addresses a current may be
    written at (``requirements.signals[net=…].range`` and
    ``requirements.rails[net=…].peakCurrent`` / ``.continuousCurrent``, because
    the rule reads both and a message naming only one would send an engineer to
    a slot the rule does not read), and the negative — this rule never guesses a
    current out of a track's shape.
    """
    board = _board(
        [
            _pad("J1", "1", x=0.0, y=0.0, net="HV"),
            _pad("J2", "1", x=400.0, y=0.0, net="PWR"),
            _pad("J3", "1", x=800.0, y=0.0, net="BUS"),
        ],
        [
            _track("t-hv", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0, net="HV", width=10.0),
            _track("t-pwr", x1=420.0, y1=0.0, x2=780.0, y2=0.0, net="PWR", width=10.0),
            _track("t-bus", x1=820.0, y1=0.0, x2=1180.0, y2=0.0, net="BUS", width=10.0),
        ],
    )
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "HV")]),
            _component("J2", [Pin("1", "1", "PWR")]),
            _component("J3", [Pin("1", "1", "BUS")]),
        ]),
        _contract(
            rails=[
                IntentRail(net="HV", slots={"continuousCurrent": "5"}),
                IntentRail(net="PWR", slots={"continuousCurrent": "5V"}),
            ],
            signals=[IntentSignal(net="BUS", slots={"range": "±3A or so"})],
        ),
    )
    findings = TrackAmpacity().check(ctx)
    assert len(findings) == 3, sorted(f.message for f in findings)
    for finding in findings:
        assert finding.severity == "INFO", "UNKNOWN is not a defect"
        assert "cannot be checked for ampacity" in finding.message
        assert "requirements.signals[net=" in finding.message
        assert "requirements.rails[net=" in finding.message
        assert "peakCurrent" in finding.message and "continuousCurrent" in finding.message
        assert "never guesses a current" in finding.message
    assert sorted(f.target.net_refs[0] for f in findings) == ["BUS", "HV", "PWR"]


def test_a_contract_with_no_current_at_all_has_no_subject_and_says_nothing():
    """The 「no subject」 discipline, and it is a discipline rather than a shrug.

    A board with **no contract** (毕设FOC's own case, 92 drawn nets) produces
    ``[]``: the rule's subject is a current the design *declared*, and without a
    declaration there is no subject — not 92 UNKNOWN rows saying the same thing.
    The empty answer is asserted because "a rule that never fires" and "a rule
    that fires correctly" are only told apart by a test that expects nothing.
    """
    board = _two_net_board(hv_track_width=10.0)
    assert TrackAmpacity().check(_ctx(board)) == []
    assert TrackAmpacity().check(_ctx(board, _model([]), None)) == []
    assert TrackAmpacity().check(_ctx(board, None, _contract())) == []


def test_a_contract_net_this_pcb_document_does_not_draw_is_not_examined():
    """Named by the contract, absent from the board: absence of copper, not 0 mil.

    The contract declares 3 A on ``OTHER``, which no pad or track on this
    document carries. Reporting 「0 mil wide, insufficient」 would manufacture a
    defect out of a net that is simply on another PCB document of the project
    (040b's multi-board shape), so the net is dropped before the measurement.
    """
    board = _two_net_board(hv_track_width=10.0)
    ctx = _ctx(
        board,
        _model([_component("J1", [Pin("1", "1", "HV")])]),
        _contract(signals=[
            IntentSignal(net="HV", slots={"range": "±3A"}),
            IntentSignal(net="OTHER", slots={"range": "±3A"}),
        ]),
    )
    findings = TrackAmpacity().check(ctx)
    assert [f.target.net_refs for f in findings] == [["HV"]]


def test_a_net_with_a_current_but_no_track_on_this_board_is_unknown():
    """Pads and a pour are a different conductor model, so there is no width.

    The contract declares 3 A on ``HV`` and this document carries ``HV`` only as
    two pads. There is no per-layer track width to compare, and pretending a
    pad's size or a pour's area were a track width would put a number in the
    report this rule cannot defend. The row is UNKNOWN naming that exact gap.
    """
    board = _board(
        [
            _pad("J1", "1", x=0.0, y=0.0, net="HV"),
            _pad("J1", "2", x=100.0, y=0.0, net="HV"),
        ],
        [],
    )
    ctx = _ctx(
        board,
        _model([_component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "HV")])]),
        _contract(signals=[IntentSignal(net="HV", slots={"range": "±3A"})]),
    )
    findings = TrackAmpacity().check(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "INFO"
    assert "pads and pours only" in findings[0].message


def test_a_track_on_a_layer_the_document_does_not_define_is_unknown():
    """Choosing outer or inner there would halve or double a safety threshold.

    Layer 99 has no ``LAYER`` record, so the document says nothing about whether
    that copper is an outer face or an inner plane. Rather than default to
    external (the reading that would *pass* the check), the row is UNKNOWN naming
    the layer id — the absence of a definition is a missing fact, not a fact.
    """
    layers = _layers((1, "Top Layer", "TOP"))
    board = _two_net_board(hv_track_width=10.0, hv_layer=99)
    board.layers = layers
    ctx = _ctx(
        board,
        _model([_component("J1", [Pin("1", "1", "HV")])]),
        _contract(signals=[IntentSignal(net="HV", slots={"range": "±3A"})]),
    )
    findings = TrackAmpacity().check(ctx)
    assert len(findings) == 1
    assert findings[0].severity == "INFO"
    assert "99" in findings[0].message
    assert "external or internal" in findings[0].message


def test_the_rails_current_slots_are_read_and_peak_beats_continuous():
    """A current written into ``rails[]`` is usable, and peak wins over continuous.

    Two rows on one board:

    * ``+5V`` states ``continuousCurrent = 1A`` and ``peakCurrent = 3A``. The
      peak is the load the conductor has to survive, so the required width is
      the one for **3 A**: ``required_width_mil(3.0)`` = 53.8 mil, and a 50 mil
      track fails on it (50 < 53.8) — while 1 A would have needed only 11.8 mil
      and passed;
    * ``+3V3`` states only ``continuousCurrent = 0.2A``, which needs 1.3 mil, so
      a 10 mil track passes it silently.

    The grammar is the shared one
    (:func:`boardwise.core.values.parse_current_amps`, the same one 092's LDO
    dissipation rule reads), which is why ``"1A"``, ``"500mA"`` and ``"1.5 A"``
    all work and a bare ``"1"`` does not — 「一个量纲一个实现」.
    """
    board = _board(
        [
            _pad("J1", "1", x=0.0, y=0.0, net="+5V"),
            _pad("J2", "1", x=400.0, y=0.0, net="+3V3"),
        ],
        [
            _track("t-5v", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0, net="+5V", width=50.0),
            _track("t-3v3", x1=220.0, y1=0.0, x2=380.0, y2=0.0, net="+3V3", width=10.0),
        ],
    )
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "+5V")]),
            _component("J2", [Pin("1", "1", "+3V3")]),
        ]),
        _contract(rails=[
            IntentRail(net="+5V", slots={
                "continuousCurrent": "1A", "peakCurrent": "3A",
            }),
            IntentRail(net="+3V3", slots={"continuousCurrent": "0.2A"}),
        ]),
    )
    findings = TrackAmpacity().check(ctx)
    assert len(findings) == 1, [f.message for f in findings]
    finding = findings[0]
    assert finding.target.net_refs == ["+5V"]
    assert "3 A" in finding.message and "peakCurrent" in finding.message
    assert "53.8" in finding.message, (
        "3 A external is (3/(0.048·10^0.44))^(1/0.725)/1.378 = 53.8 mil"
    )


def test_an_empty_board_and_an_empty_model_never_raise():
    """空输入不炸: four empty shapes, four empty answers.

    A board with nothing, a board with no tracks, a context with no model and a
    context with no contract. A rule that raised here would take the whole
    ``checkup`` report down with it (the runner's per-rule try/except contains it
    but then the check is simply missing from ``checksRun``), so a test is the
    better guard.
    """
    assert TrackAmpacity().check(_ctx(BoardGeometry())) == []
    assert VoltageSpacing().check(_ctx(BoardGeometry())) == []
    assert VoltageSpacing().check(_ctx(BoardGeometry(), None)) == []
    empty = _board([], [])
    assert TrackAmpacity().check(_ctx(empty, _model([]), _contract())) == []
    assert VoltageSpacing().check(_ctx(empty, _model([]), _contract())) == []


def _component(designator: str, pins: list[Pin]) -> Component:
    return Component(uid=f"u-{designator}", designator=designator, pins=list(pins))


# ---------------------------------------------------------------------------
# pcb-voltage-spacing — synthetic, three states
# ---------------------------------------------------------------------------


def test_two_nets_closer_than_their_band_allowance_are_a_warn():
    """State 1 (VIOLATION): the band, the reading, and the number.

    ``HV`` is priced at 24 V by the contract and ``LV`` at 5 V, so the
    difference is ``|24 - 5| = 19 V``, which the ``15–30`` band gives **4 mil**.

    The reading that decides it is between the two **tracks**, whose x-ranges
    overlap so the closest approach is a pure y-gap — a subtraction anyone can
    redo:

    * ``HV``'s track is 10 mil wide on y = 0, so its capsule occupies
      y in ``[-5, 5]``;
    * ``LV``'s track is 10 mil wide on **y = 11**, so it occupies
      y in ``[6, 16]``;
    * the edge gap is therefore ``6 - 5`` = **1.0 mil** — under the 4 mil the
      band allows, so WARN, and unambiguously a *tight gap* rather than a
      touching one (``overlapping`` is False, so the message does not claim a
      short).

    The pads are parked 5000 mil apart in x so they cannot be the closest pair:
    :func:`~boardwise.core.measure.net_clearance` returns the minimum over every
    cross-net element pair, so a board where a pair happens to be close in y is
    only interesting if nothing else is closer.

    The message carries the difference, the required number **and** the measured
    one, so a reader never has to re-derive the verdict from the prose.
    """
    board = _two_net_board(
        lv_track_y=11.0, lv_track_width=10.0,
        lv_track_x=(-100.0, 400.0), pad_x=(-2000.0, 3000.0),
    )
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "GND")]),
            _component("J2", [Pin("1", "1", "LV"), Pin("2", "2", "GND")]),
        ]),
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "24V"}),
            IntentRail(net="LV", slots={"voltage": "5V"}),
        ]),
    )
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "pcb-voltage-spacing"
    assert finding.severity == "WARN"
    assert finding.target.net_refs == ["HV", "LV"]
    assert finding.target.measurement == {
        "kind": "clearance", "value": 1.0, "unit": "mil",
    }
    assert "19 V" in finding.message and "4.0 mil" in finding.message
    assert "1.0 mil" in finding.message
    assert "copper touch" not in finding.message, "1.0 mil apart is not a short"


def test_two_nets_at_or_above_their_band_allowance_are_silence():
    """State 2 (OK): the same pair with the gap on the other side of the line.

    The boundary is worth stating precisely, because 「exactly the allowance
    passes」 is a convention a reviewer will check:

    * two 10 mil capsules, the second on y = 15, give ``(15 - 5) - 5`` =
      **5.0 mil** — over the band's 4, so silence;
    * the second on y = 14 gives ``(14 - 5) - 5`` = **4.0 mil**, which is
      *exactly* the allowance and still passes, because the comparison is
      ``distance >= required``.

    Both are asserted, and both are asserted as an **empty list**: 「it clears
    the rule」 has to be a result a test demands rather than an absence a reader
    infers, because a rule that never fires and a rule that fires correctly are
    only told apart by a test that expects nothing.
    """
    model = _model([
        _component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "GND")]),
        _component("J2", [Pin("1", "1", "LV"), Pin("2", "2", "GND")]),
    ])
    contract = _contract(rails=[
        IntentRail(net="HV", slots={"voltage": "24V"}),
        IntentRail(net="LV", slots={"voltage": "5V"}),
    ])
    for height in (14.0, 15.0):
        board = _two_net_board(
            lv_track_y=height, lv_track_width=10.0,
            lv_track_x=(-100.0, 400.0), pad_x=(-2000.0, 3000.0),
        )
        assert VoltageSpacing().check(_ctx(board, model, contract)) == [], (
            f"y={height} is {(height - 5) - 5:.1f} mil apart, over the 4 mil band"
        )


def test_a_rail_nobody_priced_is_unknown_naming_the_address():
    """State 3 (UNKNOWN): the net the sources cannot price.

    ``HV`` is priced at 24 V by the contract. ``VCC`` is on the board, carries
    copper, and is named by a ``rails[]`` row that answers **no** voltage slot —
    so the rule cannot compare it against anything.

    The geometry has to make ``VCC`` a drawn net, because the rule's subject is a
    net **this PCB document carries**: a contract row naming a net that no pad or
    track here draws is a multi-board situation and is skipped before any
    measurement (pinned for the ampacity rule; here it would be the same skip).
    So ``VCC`` gets its own pad and track, parked far enough from everything else
    that the only thing wrong with it is its missing voltage.

    The row is INFO and must name

    * the net (the row is only actionable if it does),
    * both places a voltage may be written
      (``requirements.rails[net=…].voltage`` and ``.targetVoltage``),
    * the two *drawing-side* sources the enumeration itself would use — a net
      name that states its voltage, or a shelf regulator's output — because
      telling an engineer to write a contract entry when the answer was sitting
      in the net name would be the wrong instruction,
    * and the negative: this rule never reads a voltage out of a name.
    """
    board = _board(
        [
            _pad("J1", "1", x=0.0, y=0.0, net="HV"),
            _pad("J2", "1", x=500.0, y=0.0, net="LV"),
            _pad("J3", "1", x=1200.0, y=0.0, net="VCC"),
        ],
        [
            _track("hv", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0, net="HV"),
            _track("lv", x1=520.0, y1=0.0, x2=880.0, y2=0.0, net="LV"),
            _track("vcc", x1=1220.0, y1=0.0, x2=1580.0, y2=0.0, net="VCC"),
        ],
    )
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "GND")]),
            _component("J2", [Pin("1", "1", "LV"), Pin("2", "2", "GND")]),
            _component("J3", [Pin("1", "1", "VCC"), Pin("2", "2", "GND")]),
        ]),
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "24V"}),
            IntentRail(net="VCC", role="logic"),
            IntentRail(net="LV", slots={"voltage": "5V"}),
        ]),
    )
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "INFO"
    assert finding.target.net_refs == ["VCC"]
    assert "requirements.rails[net=VCC].voltage" in finding.message
    assert "targetVoltage" in finding.message
    assert "never reads a voltage out of a net's name" in finding.message


def test_a_signal_net_is_not_a_rail_and_is_not_reported():
    """The filter that keeps the UNKNOWN population honest.

    ``CAN_RX`` carries copper and no source calls it a rail. It is **silence**,
    not UNKNOWN: it is not a power net whose voltage is missing, it is a signal
    net, and reporting it would put 89 rows of 「we don't know this net's
    voltage」 next to the one rail row that means something. This is the same
    reading 126b's supply-net inference takes (a net called ``VCC`` is not a
    supply net because of its name), and it is what makes the UNKNOWN rows a work
    list rather than a wash.
    """
    board = _board(
        [
            _pad("J1", "1", x=0.0, y=0.0, net="HV"),
            _pad("J2", "1", x=500.0, y=0.0, net="LV"),
            _pad("U9", "1", x=900.0, y=0.0, net="CAN_RX"),
        ],
        [
            _track("hv", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0, net="HV"),
            _track("lv", x1=520.0, y1=0.0, x2=880.0, y2=0.0, net="LV"),
            _track("rx", x1=920.0, y1=0.0, x2=1100.0, y2=0.0, net="CAN_RX"),
        ],
    )
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "HV")]),
            _component("J2", [Pin("1", "1", "LV")]),
            _component("U9", [Pin("1", "1", "CAN_RX")]),
        ]),
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "24V"}),
            IntentRail(net="LV", slots={"voltage": "5V"}),
        ]),
    )
    assert VoltageSpacing().check(ctx) == [], (
        "CAN_RX is a signal net, not an unpriced rail: silence, not UNKNOWN"
    )


def test_a_pair_above_the_table_is_unknown_naming_iec_60950():
    """Beyond the simplified table the answer belongs to a different standard.

    ``HV`` at 400 V and ``LV`` at 100 V differ by 300 V, which the table's last
    band does cover (100 mil). Push ``HV`` to 1200 V and the difference is
    1100 V — above :data:`SPACING_TABLE_MAX_V` — and the rule asserts **no**
    spacing. It falls back neither to the last band's number nor to the standard's
    own ``+0.005 mm/V`` continuation: extrapolating a safety threshold is exactly
    the quiet invention this repository refuses, so the row is UNKNOWN and names
    the authority that does own the band.
    """
    board = _two_net_board(lv_x=500.0)
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "HV")]),
            _component("J2", [Pin("1", "1", "LV")]),
        ]),
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "1200V"}),
            IntentRail(net="LV", slots={"voltage": "100V"}),
        ]),
    )
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "INFO"
    assert "1100 V" in finding.message
    assert "IEC 60950" in finding.message and "IEC 60664-1" in finding.message
    assert "creepage" in finding.message
    assert finding.target.measurement is None, "no spacing is asserted, so none is claimed"


def test_the_contract_wins_over_the_architecture_and_the_divergence_is_reported():
    """Two sources, one number, and the disagreement stated rather than swallowed.

    The contract prices ``+24V`` at 5 V; the drawing's own enumeration prices the
    same net at 24 V — which is what a net named ``+24V`` states on its own. The
    **contract** is the requirement and is the number the comparison uses (5 V
    here), so the pair is judged at ``|5 - 0| = 5 V`` → the ``0–15`` band → 4 mil.

    The reading is between the two **tracks**, whose x-ranges overlap so the
    closest approach is a pure y-gap: both are 10 mil wide, one on y = 0
    (occupying ``[-5, 5]``) and one on **y = 11** (occupying ``[6, 16]``), so the
    edge gap is ``6 - 5`` = **1.0 mil** — under the 4 mil the ``0–15`` band
    allows. The pads sit 5000 mil apart in x so they cannot be the closest pair.

    The net names matter here: the board has to be ``+24V`` (which the drawing's
    own enumeration prices at 24.0 V from its name) against ``GND`` (0 V), because
    a net the enumeration can price is what makes the conflict real. A synthetic
    net called ``HV`` would have no enumeration price and the divergence this test
    exists for would never arise.

    The divergence is quoted in the finding's evidence, because 「the requirement
    and the drawing disagree」 is a finding of its own and this rule refuses to
    absorb it into a silent arithmetic.
    """
    board = _board(
        [
            _pad("J1", "1", x=-2000.0, y=0.0, net="+24V"),
            _pad("J2", "1", x=3000.0, y=0.0, net="GND"),
        ],
        [
            _track("rail", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0,
                   net="+24V", width=10.0),
            _track("gnd", x1=-100.0, y1=11.0, x2=400.0, y2=11.0,
                   net="GND", width=10.0),
        ],
    )
    ctx = _ctx(
        board,
        _model([
            _component("J1", [Pin("1", "1", "+24V"), Pin("2", "2", "GND")]),
        ]),
        _contract(rails=[IntentRail(net="+24V", slots={"voltage": "5V"})]),
    )
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN"
    # Two 10 mil capsules on y=0 and y=11: (11 - 5) - 5 = 1.0 mil, under the
    # 4.0 mil that |5 - 0| = 5 V asks for.
    assert finding.target.measurement["value"] == 1.0
    assert "5 V" in finding.message, "the contract's number is the one used"
    joined = " | ".join(finding.evidence)
    assert "contract requirements.rails[net=+24V].voltage" in joined
    assert "architecture enumeration says 24 V" in joined, (
        "the divergence is stated with both numbers, and says which source wins"
    )
    assert "the contract is the requirement and wins" in joined


def test_a_ground_net_is_zero_volt_without_its_name_saying_so():
    """Ground is the board's reference node, and the shared predicate says which.

    The board has a ``GND`` pad and a ``+5V`` pad 160 mil apart (a 160.0 mil gap,
    over the 4 mil the ``0–15`` band allows, so silence) and a ``GND`` pad
    2 mil from a ``+5V`` pad's track — that pair is the WARN. What matters for
    this test is that the rule reached a verdict **at all** on a board with no
    contract and no priced rail beyond the net name: ``+5V``'s voltage comes from
    the drawing's own enumeration (its name states it) and ``GND``'s is the
    reference. Both halves come from the same shared predicates the rest of the
    PCB side uses (:func:`boardwise.core.power_domains.voltage_from_net_name`
    inside the enumeration, :func:`boardwise.core.model.is_ground_net` here), so
    the two modules cannot disagree about which nets are ground.
    """
    board = _board(
        [
            _pad("C1", "1", x=0.0, y=0.0, net="+5V"),
            _pad("C1", "2", x=0.0, y=6.0, net="GND"),
        ],
        [
            _track("v5", x1=-200.0, y1=0.0, x2=-20.0, y2=0.0, net="+5V", width=20.0),
        ],
    )
    ctx = _ctx(board, _model([_component("C1", [Pin("1", "1", "+5V"), Pin("2", "2", "GND")])]))
    findings = VoltageSpacing().check(ctx)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "WARN"
    assert finding.target.net_refs == ["+5V", "GND"]
    # The pads: 40 wide at y=0 (spans [-20,20]) and y=6 (spans [-14,26]),
    # so the y gap is 6 - 40 -> clamped to 0.0, and x gap is 40 - 40 -> 0.0.
    # The tracks are 20 wide at y=0 ([-10,10]) against the GND pad ([-14,26]),
    # so the overlap on the x axis puts the minimum at 0.0 as well.
    assert finding.target.measurement["value"] == 0.0
    assert "0 V reference" in " | ".join(finding.evidence)


def test_a_pair_whose_only_relationship_is_a_pour_containment_is_dropped():
    """The documented pour blind spot: dropped, not a violation and not an UNKNOWN.

    :func:`boardwise.core.measure.net_clearance` returns ``None`` for a pair
    whose closest relationship is one shape sitting inside a pour's outer
    outline, because the pour's real clearance voids around foreign pads are not
    in the geometry model. This rule **drops** such a pair: reporting it would
    either manufacture a 0.0 mil short that may not exist, or — reporting it as
    UNKNOWN — send an engineer to write a contract entry that already exists,
    since the missing thing is in the *measurement library*, not in the design's
    facts.

    The board below has two such pours (``fill`` polygons) on the two nets and
    no other copper at all, so the pair is unmeasurable in both directions and
    the rule's whole output is the empty list.
    """
    from boardwise.core.geometry import PourShape

    board = _board(
        [],
        [],
    )
    board.pours = [
        PourShape(id="p-hv", net="HV", kind="fill", layer_id=1, points=[
            Point(0.0, 0.0), Point(100.0, 0.0), Point(100.0, 100.0), Point(0.0, 100.0),
        ]),
        PourShape(id="p-lv", net="LV", kind="fill", layer_id=1, points=[
            Point(10.0, 10.0), Point(50.0, 10.0), Point(50.0, 50.0), Point(10.0, 50.0),
        ]),
    ]
    # The net index is derived in __post_init__, which ran before the pours
    # were attached, so it is rebuilt the same way the parser builds it.
    board.nets = index_by_net(board.pads, board.tracks, board.vias, board.pours)
    ctx = _ctx(
        board,
        _model([_component("U1", [Pin("1", "1", "HV"), Pin("2", "2", "LV")])]),
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "24V"}),
            IntentRail(net="LV", slots={"voltage": "5V"}),
        ]),
    )
    # The measurement library says the pair is unmeasurable ...
    assert net_clearance(board, "HV", "LV") is None
    # ... and the rule says nothing about it at all.
    assert VoltageSpacing().check(ctx) == []


# ---------------------------------------------------------------------------
# UNKNOWN's shape on the PCB side (钉 6): an INFO finding, and why
# ---------------------------------------------------------------------------


def test_unknown_travels_as_an_info_finding_whose_message_is_the_missing_fact():
    """Why not an :class:`~boardwise.rules.base.Outcome` — pinned, not assumed.

    The schematic side can return ``Outcome`` objects because its harness
    aggregates them; the PCB runner's contract is
    ``check(ctx) -> list[Finding]``
    (:class:`~boardwise.rules.pcb.base.PcbRule`), and the findings array is what
    ``review-mark``, ``warning_triage`` and the module attribution read. So
    UNKNOWN travels as an **INFO** finding whose message states the missing fact
    — the same convention ``rules.railratings`` already uses for the same
    situation, and for the same reason (「a row that names where to supply it」).

    Three properties are asserted, because each could regress silently and each
    fails a different way:

    1. **the invariant itself still holds where it is enforced** —
       :class:`Outcome` raises on an UNKNOWN that names no missing fact. That is
       the sentence 126c's convention is borrowing, and if the schema ever
       relaxed it the convention would lose its anchor;
    2. **every UNKNOWN row both IPC rules emit is INFO** — an UNKNOWN is not a
       defect, and if it ever became a WARN or an ERROR the report's error count
       would start following a missing fact, which is exactly what 钉 6 forbids;
    3. **every such row names its net** and states the place the fact may be
       written, so the row is a work order with an address rather than a shrug.
    """
    # (1) the borrowed invariant, checked the way the dataclass checks it.
    with pytest.raises(ValueError, match="must name the fact it is missing"):
        Outcome(rule_id="pcb-track-ampacity", state="UNKNOWN", subject="U1")

    board = _two_net_board(hv_track_width=10.0)
    model = _model([
        _component("J1", [Pin("1", "1", "HV"), Pin("2", "2", "GND")]),
        _component("J2", [Pin("1", "1", "LV"), Pin("2", "2", "GND")]),
    ])
    rows: list = []
    rows += TrackAmpacity().check(_ctx(
        board, model, _contract(rails=[IntentRail(net="HV", slots={"continuousCurrent": "5"})]),
    ))
    rows += VoltageSpacing().check(_ctx(
        board, model,
        _contract(rails=[
            IntentRail(net="HV", slots={"voltage": "24V"}),
            IntentRail(net="LV"),
        ]),
    ))
    assert len(rows) == 2, [f.message for f in rows]
    for finding in rows:
        # (2) INFO, never WARN or ERROR.
        assert finding.severity == "INFO", (
            f"{finding.rule_id} reported an UNKNOWN as {finding.severity}"
        )
        # (3) the net, and the address.
        assert finding.target.net_refs, "an UNKNOWN row names its subject"
        net = finding.target.net_refs[0]
        assert net in finding.message
        assert "requirements." in finding.message, (
            "the row names where the fact may be written"
        )
        assert "never" in finding.message, (
            "the row states what the rule refuses to do"
        )


# ---------------------------------------------------------------------------
# ROBOT ctrl FOC — the true contract anchor
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def robot_findings():
    """The ROBOT ctrl-FOC board reviewed **with its real contract**.

    This is the only fixture pair where a current is actually declared, so it
    is the only place :class:`TrackAmpacity` has a subject at all.
    """
    intent = DesignIntent.load(ROBOT_INTENT)
    model, _geometry = cli._load_model(ROBOT, view="schematic")
    findings, section = run_pcb_review(ROBOT, model=model, intent=intent)
    return findings, section


def test_the_robot_contract_declares_exactly_two_sampled_phase_currents(robot_findings):
    """The contract shape is read as the task book describes it.

    ``robot-ctrl-foc.intent.json`` states two ``signals[]`` rows and nothing
    else: ``net: "U+"`` and ``net: "W+"``, each with ``range: "±3A"`` (the file
    is UTF-8 and the sign is U+00B1 — verified on the bytes, not on a console
    rendering), ``kind: "current-sense"``, ``polarity: "bidirectional"``,
    ``reference: "GND"``. So the rule has exactly **two** subjects on this board,
    and each of them is a magnitude of 3.0 A.

    The ``rails[]`` rows of that contract (``+12V`` / ``VCC`` / ``VCCA``) carry
    **no current slot**, so they are not ampacity subjects — which is why the
    six ERRORs below are six and not nine. A rule that read a current out of a
    rail's *absence* of one would be inventing the number the whole rule exists
    not to invent.
    """
    findings, _section = robot_findings
    intent = DesignIntent.load(ROBOT_INTENT)
    ranges = {
        signal.net: signal.slots.get("range", "") for signal in intent.signals
    }
    assert ranges == {"U+": "±3A", "W+": "±3A"}, (
        "the contract states the two sampled phase currents and no others"
    )
    # The declared-current reading is what the rule actually sees.
    ctx = PcbReviewContext(
        board=None, model=None, intent=intent, module_of={}
    )
    assert declared_currents(ctx) == {
        "U+": (3.0, declared_currents(ctx)["U+"][1]),
        "W+": (3.0, declared_currents(ctx)["W+"][1]),
    }, "both rows read as a 3.0 A magnitude"
    assert {f.target.net_refs[0] for f in findings if f.rule_id == "pcb-track-ampacity"} == {
        "U+", "W+",
    }


def test_robot_pcb1_the_phase_tracks_are_six_errors_against_the_measured_width(
    robot_findings,
):
    """The required width versus the measured minimum, net by net and layer by
    layer — the anchor the task book asks for.

    The measured facts on this board (``ProPrj_ROBOT ctrl FOC``'s PCB1 document,
    read through :func:`boardwise.core.measure.track_width_stats`):

    * ``U+`` has **14** tracks on three layers — layer 1 (Top, 5 tracks),
      layer 2 (Bottom, 7 tracks) and layer 16 (Inner2, 2 tracks) — and the
      **minimum width on every one of the three is 10.0 mil**;
    * ``W+`` has **15** tracks on the same three layers (4 / 8 / 3) and the same
      10.0 mil minimum.

    Against the contract's 3.0 A: the outer layers need
    ``(3/(0.048·10^0.44))^1/0.725 / 1.378`` = **53.8 mil**, the inner layer
    needs **140.0 mil** (both derived longhand above). So each net fires on each
    of its three layers — **six ERRORs**, all of them ``pcb-track-ampacity``, all
    of them ``ERROR`` rather than WARN, because an overloaded conductor is the one
    judgement on this side that is a safety matter.

    This is a **true positive in kind**: 3 A of phase current down a 10 mil
    1 oz trace on the outer layer is a conductor the standard says will run far
    past a 10 °C rise (a 10 mil external track of 1 oz copper carries 0.886 A),
    and on the inner layer the same trace is worth about 0.44 A. Whether the
    engineer's real answer is a wider trace, a parallel pair, or a different
    topology is not this rule's question; that the copper is under the standard
    is.
    """
    findings, _section = robot_findings
    amp = [f for f in findings if f.rule_id == "pcb-track-ampacity"]
    assert len(amp) == 6, [(f.rule_id, f.message) for f in findings]
    assert all(f.severity == "ERROR" for f in amp)
    assert all(f.board == ROBOT_BOARD for f in amp)

    rows = {
        (f.target.net_refs[0], f.target.measurement["layer_ids"][0]): (
            f.target.measurement["value"],
        )
        for f in amp
    }
    assert rows == {
        ("U+", 1): (10.0,),   # Top,     5 tracks, min 10.0 mil, needs 53.8
        ("U+", 2): (10.0,),   # Bottom,  7 tracks, min 10.0 mil, needs 53.8
        ("U+", 16): (10.0,),  # Inner2,  2 tracks, min 10.0 mil, needs 140.0
        ("W+", 1): (10.0,),
        ("W+", 2): (10.0,),
        ("W+", 16): (10.0,),
    }
    # The layer's position decides which number the message quotes.
    for finding in amp:
        layer = finding.target.measurement["layer_ids"][0]
        if layer in (1, 2):
            assert "external" in finding.message and "53.8" in finding.message
        else:
            assert "internal" in finding.message and "140.0" in finding.message


def test_robot_pcb1_the_rails_rule_prices_the_three_voltages_and_judges_no_cross_layer_pair(
    robot_findings,
):
    """The spacing half on the same board, where the contract names **no**
    voltages — so the drawing's own enumeration is the source.

    This contract's ``rails[]`` rows (``+12V`` / ``VCC`` / ``VCCA``) answer no
    ``voltage`` or ``targetVoltage`` slot, so all three voltages come from
    :mod:`boardwise.core.architecture`: ``+12V`` at 12.0 V (its name states it),
    ``VCC`` at 3.3 V (the STM32's ``VDD`` supply pin, and the enumeration's
    regulator half has nothing to say about it, so this is the name/supply-pin
    evidence), and ``GND`` at 0 V as the board's reference.

    **127b: both measured pairs are now dropped, and this test is the record of
    why.** 126b reported two WARNs at 0.0 mil, and its own docstring already
    said the number was a projection artifact:

    * ``+12V`` vs ``GND``: the closest pair was a ``+12V`` track on **layer 16**
      against ``R5``'s pad 1 on **layer 1**. Different layers. The 0.0 is two
      shapes projected onto each other in plan view, separated vertically by the
      prepreg — the test already asserted ``overlapping is False`` and that
      「touch」 must not appear in the message, which is the same rule stating in
      prose what the code now does structurally;
    * ``GND`` vs ``VCC``: a GND track against a pad on ``U1``, 0.0 by the same
      projection reading.

    127b gave :class:`boardwise.core.measure.ClearanceResult` a
    ``shared_layer_ids`` field, and this rule **drops a pair whose closest copper
    shares no layer** (:attr:`ClearanceResult.shares_a_layer`). Judging a
    cross-layer projection against IPC-2221's 4 mil band measures the board's
    thickness, not its layout. Both pairs are dropped — not counted as a pass,
    not counted as a violation, and not reported as an UNKNOWN, because the
    missing thing is in the *measurement* and not in the design's facts (the same
    argument the pour-containment blind spot makes).

    What survives is the UNKNOWN row: ``VCCA`` is named by the contract and no
    source prices it (neither its name nor a supply pin states a voltage), so
    one INFO names where a voltage may be written. **Three rails in, none judged,
    one work order** — the voltage half of the contract is still incomplete and
    this report says so.
    """
    findings, _section = robot_findings
    spacing = [f for f in findings if f.rule_id == "pcb-voltage-spacing"]
    warns = [f for f in spacing if f.severity == "WARN"]
    unknowns = [f for f in spacing if f.severity == "INFO"]
    assert warns == [], (
        "127b drops every cross-layer pair; both 126b rows were projections: "
        f"{[f.message for f in warns]}"
    )
    assert len(unknowns) == 1
    assert unknowns[0].target.net_refs == ["VCCA"], (
        "the one unpriced rail is still a work order — dropping the two "
        "cross-layer WARNs must not silence the row that can be acted on"
    )


# ---------------------------------------------------------------------------
# 毕设FOC — the no-contract anchor: what the discipline actually produces
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def foc_findings():
    """The full PCB review of 毕设FOC, run once for the whole module."""
    model, _geometry = cli._load_model(FOC, view="schematic")
    findings, section = run_pcb_review(FOC, model=model)
    return findings, section


def test_foc_ampacity_is_silent_because_no_contract_declares_a_current(foc_findings):
    """92 drawn nets, **zero** rows: the 「no subject」 half, on a real board.

    毕设FOC's PCB1 carries 92 nets with copper and the project has **no
    design-intent contract**, so no current is declared anywhere. The rule's
    subject is a declared current; with none, the whole output for this rule on
    this fixture is ``[]``.

    This is asserted as an empty list on purpose. The alternative — one INFO row
    per net saying 「nobody declared a current for ``NET37``」 — would be 92 rows
    that all say the same thing, and it would bury the six ERRORs the ROBOT
    anchor produces for a board that *did* declare one. 「No contract, no
    subject」 is the same discipline 126b took for nets the voltage inference
    could not call supply nets, and the reason is stated in the rule module's
    docstring rather than left as an absence a reader has to notice.
    """
    findings, _section = foc_findings
    assert not [f for f in findings if f.rule_id == "pcb-track-ampacity"], (
        "毕设FOC declares no current anywhere; the rule has no subject"
    )


def test_foc_pcb1_the_spacing_readings_are_four_unknowns_and_no_warn(foc_findings):
    """毕设FOC PCB1 anchor: five priced nets, **no WARN**, four UNKNOWNs.

    The priced nets, and where each voltage came from (there is no contract, so
    every one is the drawing's own enumeration, and only ``VCC``/``VCCA``/
    ``VREF`` come back without one):

    * ``+24V`` at **24.0 V** — its name states it;
    * ``+5V`` at **5.0 V** — its name states it;
    * ``GND`` / ``AGND`` / ``PGND`` at **0.0 V** — the board's reference.

    **127b: all three of 126b's WARNs are gone, each for its own stated
    reason**, and the board's host DRC being clean is what makes all three the
    same story rather than three coincidences.

    * ``+24V`` vs ``+5V``: 126b measured **0.0 mil** between a ``+24V`` track on
      **layer 16** and a ``+5V`` track on **layer 1**. Different layers — the
      0.0 is a plan-view projection of two shapes separated vertically by the
      prepreg. Dropped by the cross-layer clause; 126b's own test already
      asserted 「touch」 must not appear, which is the rule saying in prose what
      the code now does structurally.
    * ``+24V`` vs ``GND``: 126b measured **0.0 mil** between ``U6``'s pad 10 and
      a GND track and called it a *short* (``overlapping=True``). It is not.
      ``U6`` is a **bottom-side** placement (``COMPONENT.layerId == 2``) whose
      footprint pads all carry ``layerId == 1`` — the 127a root cause. With the
      effective-layer reading the pad is on **layer 2**, the track is on layer 1,
      the pair shares no layer, and the "short" is a projection across a 1.6 mm
      board. Dropped.
    * ``GND`` vs ``PGND``: 126b measured **0.0 mil** and ``overlapping=True``
      between ``U2``'s pad 33 (GND) and ``U6``'s pad 2 (PGND) — the same
      misattribution (``U6.2`` is on layer 2, ``U2.33`` on layer 1). Dropped on
      the same clause. Even had the layers agreed, 岳裁定 4 exempts two nets at
      the same potential, and two ground islands meeting in one place is the
      design's single-point join, not a defect.

    What is left is the four UNKNOWNs: ``VCC`` / ``VCCA`` / ``VREF`` on PCB1
    (three rails the enumeration listed but could not price) plus ``VCC`` on
    **PCB2**, which has eight drawn nets and no priced rail of its own. PCB3 is
    quiet as before: its two priced nets (``+24V`` and ``PGND``) measure 21.26
    mil apart, inside the 4 mil band? no — inside it comfortably, so it passes.

    **The honest reading of this anchor.** Nothing on this board violates its
    conductor spacing, and the rule now says so by saying nothing about the ten
    priced pairs while still naming the four rails whose voltage nobody has
    established. Before 127b it said the opposite — three 「the copper touches」
    rows on a board that is electrically clean — and a report that cries wolf
    three times is a report nobody reads the fourth time.
    """
    findings, _section = foc_findings
    spacing = [f for f in findings if f.rule_id == "pcb-voltage-spacing"]
    warns = [f for f in spacing if f.severity == "WARN"]
    unknowns = [f for f in spacing if f.severity == "INFO"]

    assert warns == [], (
        "127b: the +24V/+5V and +24V/GND rows are cross-layer projections and "
        "the GND/PGND row is a same-potential join — none is a spacing defect"
    )
    assert len(unknowns) == 4
    assert sorted((f.board, f.target.net_refs[0]) for f in unknowns) == [
        ("PCB1", "VCC"), ("PCB1", "VCCA"), ("PCB1", "VREF"), ("PCB2", "VCC"),
    ], (
        "the four unpriced rails are still work orders — silencing the three "
        "false WARNs must not silence the rows that can be acted on"
    )

    # Every INFO names its net and the address, and none of them is a defect.
    for finding in unknowns:
        assert finding.severity == "INFO"
        assert "requirements.rails[net=" in finding.message
        assert "targetVoltage" in finding.message


def test_llc_prices_no_rail_and_declares_no_current_so_both_rules_are_silent():
    """llc anchor: a board with neither a contract nor a priced rail.

    126b pinned llc as the clean board under the two distance rules; the IPC
    pair is silent on it for two *different* reasons, and keeping them apart is
    the point:

    * ``pcb-track-ampacity`` has **no subject** — llc has no contract, so no
      current is declared;
    * ``pcb-voltage-spacing`` has **no priced pair** — the architecture
      enumeration establishes no rail voltage on this board (it prices none, and
      llc carries no ground-named net either, so there is no difference to look
      up and not even an UNKNOWN to file).

    The whole IPC output is ``[]`` while ``checksRun`` still names both rules:
    silence is a result, not a skip, and it is pinned as an empty answer because
    "a rule that never fires" and "a rule that fires correctly" are only told
    apart by a test that demands nothing.
    """
    model, _geometry = cli._load_model(LLC, view="schematic")
    findings, section = run_pcb_review(LLC, model=model)
    assert findings == [], [(f.rule_id, f.message) for f in findings]
    assert section is not None
    assert section["boards"][0]["checksRun"][-2:] == [
        "pcb-track-ampacity", "pcb-voltage-spacing",
    ]