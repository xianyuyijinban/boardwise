"""175/B-2: two flags of one family may not be drawn as a pair.

**The defect 173 measured.** On the flyback page two *different* ground nets had
their flags hung off the same row: `SEC_GND`'s lead ran up at `x=725`, `PGND`'s
down at `x=730` — 5 units apart, so the two leads read as one pair and the two
isolated ground domains read as one net. 074 refuses a lead that runs *through*
another net's wire; nothing asked the milder question of a lead that runs
*alongside* one.

**What this batch adds.** :data:`boardwise.engines.drawcompiler.SIBLING_LEAD_CLEARANCE`
(a borrowed value — see the constant, and :func:`test_the_spacing_value_is_a_borrowed_one`)
and :func:`boardwise.engines.drawcompiler._lead_too_close`, asked from the flag
ladder as a **preference**: the ladder keeps looking for a rung that keeps the
gap, and the first crowded rung is what it falls back on when there is none, so
no page can lose a flag to this rule.

The end-to-end pin is the same delivered page as 175/B-1's: the two ground leads
that were 5 units apart, and every ground flag still drawn.
"""

from __future__ import annotations

import functools
import pathlib

from boardwise.core.circuitspec import CircuitSpec
from boardwise.core.presentationspec import PresentationSpec
from boardwise.engines import drawapply, drawcompiler as dc, router

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
PAGE_150 = ROOT / "outputs" / "150" / "presentation_150_r5rot.json"


# ------------------------------------------------------------------ 取值与出处


def test_the_spacing_value_is_a_borrowed_one():
    """12 units, from the reference harness's own schematic planner.

    ``easyeda-agent_RE/source/internal/app/cmd_sch_autoconnect.go``,
    ``defaultAutoconnectRules().MinLabelGap = 12`` — the gap at which that
    planner calls a stub "running close to another channel". Same unit (1 unit =
    1 mil), same kind of decision. It is deliberately above this file's own
    `FLAG_CLEARANCE` (5, how close a flag may graze a *wire*) and it is a **house
    value pending 岳's look** — 岳 2026-10-12: 「借鉴上游参数慢慢调」.
    """
    assert dc.SIBLING_LEAD_CLEARANCE == 12.0
    assert dc.SIBLING_LEAD_CLEARANCE > dc.FLAG_CLEARANCE, (
        "two named runs need more room than a flag needs from a wire"
    )
    source = (ROOT / "src" / "boardwise" / "engines" / "drawcompiler.py").read_text(
        encoding="utf-8"
    )
    assert "MinLabelGap = 12" in source, "the constant carries its provenance"
    assert "cmd_sch_autoconnect.go" in source


# -------------------------------------------------------- 判定：谁算「兄弟」


def _router(**overrides) -> dc._Router:
    router_ = dc.lattice_router(
        grid=5.0, residue=(0.0, 0.0), boxes=(), bounds=(0.0, 0.0, 400.0, 400.0),
    )
    for name, value in overrides.items():
        setattr(router_, name, value)
    return router_


#: 173's measured pair: `PGND`'s lead — a run out of its pad at (760,665) to
#: (730,665) and then up to (730,640).
PGND_LEAD = [(760.0, 665.0), (730.0, 665.0), (730.0, 640.0)]
SEC_GND_PIN = (695.0, 665.0)


def _with_pgnd_lead(owner: str = "PGND", kind: str = "gnd") -> dc._Router:
    router_ = _router()
    dc._remember_lead(router_, owner, kind, PGND_LEAD)
    return router_


def _gap(lead, node):
    return min(
        dc._run_to_point(start, end, node) for start, end in zip(lead, lead[1:])
    )


def test_a_lead_running_beside_a_sibling_is_reported():
    """173's 5 units is what makes the pair, and the reason names the net and the point."""
    router_ = _with_pgnd_lead()
    run = [(695.0, 665.0), (725.0, 665.0), (725.0, 690.0)]
    reason = dc._lead_too_close(router_, "SEC_GND", "gnd", run)
    assert reason is not None and "PGND" in reason
    nodes = set()
    for start, end in zip(PGND_LEAD, PGND_LEAD[1:]):
        nodes |= dc._lattice_nodes(_router(), start, end)
    gap = min(
        dc._run_to_point(start, end, node)
        for start, end in zip(run, run[1:])
        for node in nodes
    )
    assert gap == 5.0, f"173 measured 5 units between these two legs, got {gap:g}"


def test_a_run_far_enough_away_is_left_alone():
    router_ = _with_pgnd_lead()
    clear = [(695.0, 665.0), (705.0, 665.0), (705.0, 690.0)]
    assert dc._lead_too_close(router_, "SEC_GND", "gnd", clear) is None


def test_a_nets_own_other_flag_is_not_a_sibling():
    """Two pads of one net named by two of its own flags are one name twice.

    069 sec.1 depends on that being allowed: a net with several pads hangs a flag
    on each of them, and those leads are routinely side by side.
    """
    router_ = _with_pgnd_lead(owner="GND")
    assert dc._lead_too_close(
        router_, "GND", "gnd", [(695.0, 665.0), (725.0, 665.0), (725.0, 690.0)],
    ) is None


def test_a_flag_of_another_family_is_not_a_sibling():
    """A ground glyph beside a rail glyph is two pictures, not one pair.

    Measured, not assumed: asking this question across families took 053b's own
    sideways LDO scene — where a rail flag's lead sits 10 units under another
    rail's — into a `layout-unsat` it never had, because the moved lead pushed
    `VIN5`'s run into the only rung `3V3` had left.
    """
    router_ = _with_pgnd_lead(kind="rail")
    assert dc._lead_too_close(
        router_, "SEC_GND", "gnd", [(695.0, 665.0), (725.0, 665.0), (725.0, 690.0)],
    ) is None


# ------------------------------------------------------- 梯子：偏好而非拒绝


def _crowded(lead) -> str:
    return "crowded"


def test_the_ladder_moves_to_a_rung_that_keeps_the_gap():
    """岳's 「退下一档/换挂向」: the first rung gives way, the answer keeps 12 units.

    The same call without the rule returns 173's rung — the one that ends up 5
    units from `PGND`'s lead.
    """
    router_ = _with_pgnd_lead()
    plain, plain_lead, _hang = dc._flag_anchor(
        router_, SEC_GND_PIN, (1.0, 0.0), set(),
    )
    assert dc._lead_too_close(router_, "SEC_GND", "gnd", plain_lead) is not None, (
        "premise: the rung the ladder would take is the crowded one"
    )
    anchor, lead, _hang = dc._flag_anchor(
        router_, SEC_GND_PIN, (1.0, 0.0), set(),
        near=lambda run: dc._lead_too_close(router_, "SEC_GND", "gnd", run),
    )
    assert (anchor, lead) != (plain, plain_lead)
    assert dc._lead_too_close(router_, "SEC_GND", "gnd", lead) is None
    assert _gap(lead, (730.0, 665.0)) >= dc.SIBLING_LEAD_CLEARANCE


def test_the_preference_is_never_a_refusal():
    """A page with no roomier rung keeps the drawing it had.

    The ladder is asked for a rung that is *always* crowded, which is what a pad
    packed against its neighbour looks like: the answer is the plain one, not
    "no lead" — 148 measured what a stricter ladder costs, and 175's rule is a
    spacing decision, not another way to refuse a page.
    """
    router_ = _with_pgnd_lead()
    plain = dc._flag_anchor(router_, SEC_GND_PIN, (1.0, 0.0), set())
    squeezed = dc._flag_anchor(
        router_, SEC_GND_PIN, (1.0, 0.0), set(), near=_crowded,
    )
    assert squeezed == plain
    assert squeezed[1] is not None


# ------------------------------------------------------------- 真页：150 落地页


@functools.cache
def _landing_page():
    result = dc.compile(
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"),
        PresentationSpec.load(PAGE_150),
        drawapply.load_library(SPECS / "flyback_uc3845.library.json"),
        dc.CompileBudget(),
    )
    assert result.ok, [item.detail for item in result.failures]
    return result.candidates[0]


def _flag_leads(plan, net: str):
    """Each of this net's flag leads: a run whose far end is one of its anchors."""
    anchors = {
        (symbol.x, symbol.y) for symbol in plan.power_symbols if symbol.net == net
    }
    out = []
    for segment in plan.segments:
        if segment.net != net:
            continue
        if router._key(segment.points[-1]) in {router._key(a) for a in anchors}:
            out.append(list(segment.points))
    return out


def test_the_landing_pages_two_ground_leads_stop_reading_as_one_pair():
    """173's measurement, reversed: `SEC_GND`'s lead and `PGND`'s are now 25 apart.

    Old (`outputs/173/evidence.md` section B-2): `SEC_GND`'s lead
    ``[(695,665),(725,665),(725,690)]`` beside `PGND`'s
    ``[(760,665),(730,665),(730,640)]`` — legs at x=725 and x=730, 5 units.
    New: `SEC_GND`'s flag comes out 10 units instead of 30, so its leg stands at
    x=705. Both sides are **the leads that end on a flag anchor**, so this is the
    gap between two flags' own runs and not a net against itself.
    """
    plan = _landing_page()
    sec_gnd = _flag_leads(plan, "SEC_GND")
    pgnd = _flag_leads(plan, "PGND")
    assert sec_gnd and pgnd, "premise: both grounds hang flags"
    gap = min(
        dc._run_to_point(a, b, (node[0], node[1]))
        for lead in pgnd
        for a, b in zip(lead, lead[1:])
        for other in sec_gnd
        for node in other
    )
    assert gap >= dc.SIBLING_LEAD_CLEARANCE, (
        f"SEC_GND's lead comes {gap:g} units from PGND's flag lead"
    )
