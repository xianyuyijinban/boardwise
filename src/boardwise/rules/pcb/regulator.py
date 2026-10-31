"""Regulator input/output capacitor **placement**, read pin-role-wise (task 131b).

``pcb-decap-distance`` (126b) asks one question per **IC** and per **supply
net**: is a high-frequency capacitor near the chip? This module asks a
narrower and, for the power path, a more useful question — for every
**regulator** in the shelf's ``ic.ldo`` / ``ic.buck`` classes, for its
**VIN** pin and for its **VOUT** pin separately, how far is the nearest
capacitor of each pool on *that pin's own net*?

**Pins, not nets.** The two rules' object of study is different, and the
difference is the whole point. 126b pools by net, which is the right question
for 「this chip is fed by ``+5V``, is there a bypass cap anywhere on
``+5V``?」 — and the wrong question for a regulator, because on 毕设FOC 1.0.0 the
net ``+5V`` is simultaneously U5's **input** (U5.1 = ``VIN``), U6's **input**
(U6.1 = ``VIN``) and U11's **output** (U11 is the ``LM5164`` buck whose output
rail is ``+5V``). A net-pooled reading therefore hands U5 the capacitors that
belong to U6's input stage and calls the sum U5's decoupling. This rule reads
:func:`boardwise.core.pinrole.pin_role` on each pin's real name (131a landed
the names on the PCB-side model), keeps the ``IN`` pins as one side and the
``OUT`` pins as the other, and searches **each side's own net**. A pin whose
name declares neither role is recorded as UNKNOWN with the name that said so
— the rule does not promote an unrecognised pin to a side, because a wrong
side produces a finding about a pin the rule never meant.

**Pools are this package's own definition, not 126b's.** 岳裁定 ③ (2026-10-08):
a capacitor below :data:`HF_POOL_FARADS` (1 µF) is a **high-frequency bypass**;
a capacitor at or above it is **energy storage**. This is deliberately *not*
:data:`boardwise.rules.pcb.distance.BULK_FARADS` (10 µF) with the band between
them left unassigned — 裁定 ③ assigns that band to storage, so a ``2.2uF`` part
is storage here where 126b calls it neither pool. A capacitance nobody wrote
down is UNKNOWN and lands in **neither** pool: an unreadable value is not
evidence that a part bypasses anything, which is the same argument
:func:`boardwise.rules.decap.decide_required_cap` makes.

**This stick sets no threshold.** Every row it emits is an ``INFO``
measurement: the nearest capacitor of each pool and its edge-to-edge gap,
with the pad pair that produced the number. There is no ``*_DISTANCE_MIL``
constant here on purpose — the two numbers 126b uses are house rules awaiting
岳's ruling, and inventing a third one silently would make the ledger say a
threshold existed when none does. **The seam is left open**: a future batch
that gets a ruling adds a ``REGULATOR_CAP_DISTANCE_MIL`` constant and turns
the measured rows into WARNs at that line, which is why
:data:`HF_POOL_FARADS` and the pool helper live here rather than inside
:func:`_one_pool`.

**Empty input never raises.** A model with no ``ic.ldo`` / ``ic.buck`` part
produces no findings at all — measured on 毕设FOC's 2026-09-17 export (the
three-document 1.1.0 fixture) and on ``llc_board.epro2``. A pool with no
capacitor, and a side whose pin declares no role, are both single INFO rows
that name the designator, the side and the pool.

**Which model the rule reads: ``ctx.pcb_model``, and why (131c).** The rule is
handed :attr:`~boardwise.rules.pcb.base.PcbReviewContext.pcb_model` — the
netlist view of **the PCB document it is running on**, built per document by
:func:`boardwise.engines.pcbreview.run_pcb_review`. Two facts force that:

* **The two views name nets differently.** 131b's callers passed
  :func:`boardwise.cli._load_model`'s default, the *schematic* view, and that
  is a different set of names for the same wires: on 毕设FOC 1.0.0 U5's output
  is ``$1N66612`` in the PCB view and ``NET11`` in the schematic one, U6's is
  ``$1N66627`` / ``NET3``. A rule asking 「which capacitors sit on U5's output
  net」 has to ask it in the view it measures geometry in, or it measures the
  wrong net and calls the pool empty. The real ``checkup`` reproduced exactly
  that: U5's VOUT storage pool read *empty* (the parts are on ``$1N66612``) and
  its VIN storage nearest read *C93 @ 521.2 mil*, a part that belongs to
  neither reading once the names line up.
* **The PCB view is per document.** :func:`boardwise.parsers.epro2_model.
  build_design_model` with no document argument reads the backup's *first* PCB
  document only. On the 1.1.0 export that is ``PCB3`` (33 components), which
  places none of the three regulators the schematic names — so a first-document
  model is blind to ``PCB1`` (105 components), where all three sit. The
  runner now scopes the model to the document in hand, which is what the
  ``pcb_model`` field exists for; a caller that hands this rule a context with
  ``pcb_model=None`` gets silence, not a wrong answer.

``ctx.model`` — the schematic view — is read here for **one thing only**: the
**value** each part declares (164b). 131b deliberately did not read it, because
its net names are a different set for the same wires and this rule's questions
are 「which capacitors sit on *this pin's own net*」 — a geometry question the
PCB view must answer. But the *value* is a **declaration**, and 岳 ruled
(``tasks/158``) that 电气语义一律以原理图为准: the PCB document's own ``Value``
field is a **systematic placeholder**, measured on 毕设FOC 1.0.0's ``PCB1`` as 98
of 122 parts carrying a value the schematic contradicts (23 of them ``100nF``,
20 ``10K``). So the net and the geometry come from :attr:`~PcbReviewContext.
pcb_model` and the value comes from :func:`_declared`, which reads the schematic
page first and the PCB copy only as a fallback (153b's
:func:`~boardwise.rules.pcb.focground._value_ohms`). The defect this closes is
``C93``: the schematic's ``22µF`` filed as a ``< 1 µF`` high-frequency bypass
because the board copy says ``100nF``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..base import Finding, FindingTarget
from ...core.geometry import BoardGeometry, PadGeometry
from ...core.measure import pad_edge_distance
from ...core.partkind import (
    CATEGORY_ABSENT,
    CATEGORY_GATED,
    category_verdict,
)
from ...core.parts import (
    FACTS_TRUST_VERIFIED,
    resolve_component_facts,
)
from ...core.pinrole import pin_role
from ...core.values import parse_capacitance_farads
from ..decap import cap_candidates_on, recovered_farads, value_source_label
from ..facts import read_default_library
from .base import PcbReviewContext, PcbRule
from .distance import _board_models, _mil, _measurement
from .focground import DrawValue, _placed_on, _value_ohms, schematic_board_of

__all__ = [
    "HF_POOL_FARADS",
    "POOL_HF",
    "POOL_STORAGE",
    "REGULATOR_CATEGORIES",
    "SIDE_INPUT",
    "SIDE_OUTPUT",
    "RegulatorCapDistance",
    "RegulatorReading",
    "SameNetLoopDistance",
    "regulator_role",
    "same_net_loop_distance",
]


#: The shelf categories this rule examines. **Only** these two — a
#: ``ic.motor-driver``, a ``ic.reference`` (毕设FOC's ``U20`` = REF2033) and a
#: ``ic.opamp`` are not regulators, and asking a voltage reference for an input
#: capacitor would file a finding against a part that has no input stage.
#:
#: A part the shelf classifies nothing at all is **not** examined. The shelf is
#: the only place a part's *function* is stated (127b's
#: :func:`~boardwise.rules.pcb.distance.classify_device` measures this: 87 of the
#: 109 curated entries carry no category at all), so a category-less part is an
#: UNKNOWN rather than something to guess — guessing here would mean
#: pattern-matching ``LM``/``LDO``/``1117`` out of an MPN, which is the failure
#: mode 131a's ``pin_role`` was written to avoid.
REGULATOR_CATEGORIES: frozenset[str] = frozenset({"ic.ldo", "ic.buck"})

#: The **storage floor** in farads: a capacitor at or above this is energy
#: storage, one below it is a high-frequency bypass.
#:
#: **source: 岳裁定 ③ (2026-10-08)** — the power pack's own definition, not a
#: standard and not 126b's :data:`~boardwise.rules.pcb.distance.BULK_FARADS`.
#: 裁定 ③ is explicit that there is **no unassigned middle band**: ``1uF <= c``
#: is storage whatever its size, because 「储能与高频旁路的分界」 is a property
#: of the *loop* and 1 µF is where the board draws it. The fixture confirms the
#: band is real and populated — ``C89`` (4.7 µF), ``C5``/``C11``/``C101``/
#: ``C64`` (2.2 µF) — so a definition that left it out would silently drop four
#: real capacitors from every pool.
HF_POOL_FARADS = 1e-6

#: Slack for the single boundary comparison, in farads — one picofarad.
#:
#: Not decoration, and the **direction** matters:
#: :func:`boardwise.core.values.parse_capacitance_farads("10uF")` returns
#: ``9.999999999999999e-06``, which is *below* ``10e-06``, so a part declared
#: exactly at the floor can land a hair under it and be filed as HF bypass
#: instead of storage. The comparison is therefore ``farads + eps >= floor``
#: with **no** tolerance on the far side: a capacitor declared at 0.9999 µF is
#: genuinely below the floor and must not be rounded up into the storage pool.
#: 1e-12 F is a picofarad, four orders below the smallest value any real drawing
#: states, and it is the same trick and the same number
#: :func:`boardwise.rules.pcb.distance.capacitor_role` uses (127b).
_BOUNDARY_FARADS = 1e-12

POOL_HF = "hf"
POOL_STORAGE = "storage"

#: The two sides a regulator's pins are read into. The values are the
#: :func:`boardwise.core.pinrole.pin_role` roles, so the label on a finding and
#: the reading that produced it cannot drift apart.
SIDE_INPUT = "IN"
SIDE_OUTPUT = "out"  # the *label* on a report row; the pin role is ``OUT``

_SIDE_LABELS = {SIDE_INPUT: "VIN", SIDE_OUTPUT: "VOUT"}
_POOL_LABELS = {
    POOL_HF: "high-frequency bypass",
    POOL_STORAGE: "energy storage",
}


@dataclass(frozen=True)
class RegulatorReading:
    """One regulator as this rule established it, and why."""

    designator: str = ""
    component: object = None
    #: The board's own model (a multi-board project has one per board), which is
    #: also the model ``cap_candidates_on`` must be asked about.
    board_model: object = None
    #: The shelf category that made it a regulator — quoted in every finding.
    category: str = ""
    #: 527D3: which tier signed ``category``, carried so the 免责 row can quote
    #: the shelf's own tier in
    #: :func:`boardwise.rules.facts.category_absent_reason`'s wording.
    category_trust: str = FACTS_TRUST_VERIFIED
    #: ``{side: [nets]}`` — the pins whose name declared that side, grouped by
    #: the net each sits on.
    nets_by_side: dict[str, list[str]] = None
    #: ``[pin name]`` for the pins that declared no role. Evidence, never a side.
    unclassified_pin_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class SameNetLoopDistance:
    """The decoupling loop's gap on **one net**, and the pad pair that produced it.

    Issue #89: the same object :class:`~boardwise.core.measure.ComponentDistance`
    measures — a number in mils and the two pads — but read on the **net being
    decoupled** rather than across every pad pair of two components. The
    distinction is the whole defect: ``component_distance`` refuses same-net and
    cross-layer pad pairs by design (127b), and a decoupling capacitor's supply
    pad and its regulator's supply pad are *same-net* by construction, so that
    function answered ``None`` for exactly the pairs this rule asks about — and
    the caller then wrote ``None`` as 「none is placed」 while
    :meth:`~boardwise.core.geometry.BoardGeometry.component` had already proved
    the part is on the board.

    ``edge_distance`` is :func:`boardwise.core.measure.pad_edge_distance` — the
    **planar** edge-to-edge minimum, deliberately layer-blind — because the loop
    a capacitor decouples *is* a plan-view area: on 毕设FOC 1.0.0's U5/C3 pair the
    regulator is on the top face and the capacitor on the bottom, and the loop
    that matters is the projection through the vias. This is the reading
    :class:`~boardwise.rules.pcb.distance.DecapDistance` takes since 164c, which
    is why the same context yields the same number from both rules.
    """

    edge_distance: float = 0.0
    #: The **regulator's** pad on the net (``pin_number``, or its ``id``).
    pad_a: str = ""
    #: The **candidate capacitor's** pad on the net.
    pad_b: str = ""


def same_net_loop_distance(
    board: BoardGeometry, des_a: str, des_b: str, net: str
) -> SameNetLoopDistance | None:
    """The planar gap between two parts' pads **on ``net``** (issue #89).

    ``des_a`` is the regulator and ``des_b`` the candidate capacitor, both
    already known to be placed on this PCB document. Only pads whose
    ``pad.net == net`` take part — a capacitor's ground pad is not a leg of the
    supply loop — and the pair is measured with
    :func:`boardwise.core.measure.pad_edge_distance`, the layer-blind planar
    primitive. Same-net and cross-layer pairs are therefore **measured**, not
    refused: the loop projection is the object under study.

    ``None`` when either part has no pad on ``net`` on this document. That is
    「unmeasurable」, not 0.0 — the same discipline the shared geometry keeps,
    and the reason the caller's message distinguishes it from an unplaced part.
    Deterministic: pads are read in :meth:`BoardGeometry.pads_for_component`
    order and the first pair wins a tie, so the reported pad pair is stable.
    """
    pads_a = [pad for pad in board.pads_for_component(des_a) if pad.net == net]
    pads_b = [pad for pad in board.pads_for_component(des_b) if pad.net == net]
    if not pads_a or not pads_b:
        return None
    best: SameNetLoopDistance | None = None
    for pad_a in pads_a:
        for pad_b in pads_b:
            gap = pad_edge_distance(pad_a, pad_b)
            if best is None or gap < best.edge_distance:
                best = SameNetLoopDistance(
                    edge_distance=gap,
                    pad_a=str(pad_a.pin_number or pad_a.id),
                    pad_b=str(pad_b.pin_number or pad_b.id),
                )
    return best


def _declared(candidate: object, model: object, schematic: object | None = None) -> DrawValue:
    """The value this candidate declares, read through **both** views (164b).

    ``model`` is the board model the candidate came from (the PCB document's own
    netlist view) and ``schematic`` is **this document's schematic page**
    (:func:`~boardwise.rules.pcb.focground.schematic_board_of`), or ``None`` for
    「no schematic view for this document」.

    The reading itself is 153b's
    :func:`~boardwise.rules.pcb.focground._value_ohms`, reused rather than
    re-implemented: the schematic page's declaration wins, the PCB document's
    copy is the fallback, and a disagreement is carried in ``basis`` as
    「原理图 X / PCB 文档 Y」. ``None`` for ``schematic`` is honest rather than
    fatal — the copy is then the only value there is, and the basis says it is a
    fallback instead of claiming the schematic declared it.
    """
    designator = str(getattr(candidate, "designator", "") or "")
    component = (getattr(model, "components", {}) or {}).get(designator)
    return _value_ohms(component, _placed_on(schematic, designator))


def _pool_reading(
    candidate: object, model: object, schematic: object | None = None
) -> tuple[float | None, str]:
    """``(farads, basis)`` for one candidate's pool question (issue #86).

    Two questions, in the order 164b's discipline asks them: **what does the
    drawing declare** (:func:`_declared`, the schematic page's own field first
    and the PCB document's copy as its fallback), and — only when that yields
    nothing — **did the decoupling pool recover a value for this part from its
    identity** (:func:`~boardwise.rules.decap.recovered_farads`).

    The second question is #86. An old-library instance carries ``partId="1"``,
    an empty ``Value`` and a good MPN, so before this the part was in neither
    pool and a rail with a 100 nF capacitor 21 mil from its regulator was read as
    having none. ``basis`` is the sentence a row prints, and it is
    :func:`_declared`'s own («原理图 X / PCB 文档 Y») **plus** the recovery when
    one happened, because 「declared 100nF」 and 「recovered 100nF from the MPN」
    are two different claims about a board.
    """
    draw = _declared(candidate, model, schematic)
    declared = draw.value
    farads = parse_capacitance_farads(declared) if declared else None
    if farads is not None:
        return farads, draw.basis
    recovered = recovered_farads(candidate)
    if recovered is None:
        return None, draw.basis
    text = str(getattr(candidate, "value", "") or "")
    source = str(getattr(candidate, "value_source", "") or "")
    return recovered, (
        f"{draw.basis}; the schematic states no capacitance, and the decoupling "
        f"pool recovered {text!r} for it from the {value_source_label(source)} "
        "(issue #86)"
    )


def regulator_role(
    candidate: object, model: object, schematic: object | None = None
) -> str:
    """Which pool one :class:`~boardwise.rules.decap.CapCandidate` is in.

    Read off **both views** through :func:`_declared` — the schematic page's
    declaration first, the PCB document's copy as a fallback (164b) — and then
    through :func:`boardwise.core.values.parse_capacitance_farads`, never off a
    package name and never guessed: 裁定 ③ makes the pool a function of the value
    the drawing states. Returns :data:`POOL_HF` below the floor,
    :data:`POOL_STORAGE` at or above it, and ``""`` for a value nobody wrote
    down (the UNKNOWN case: in neither pool, and reported as such rather than
    silently assigned). ``schematic=None`` reads the board model alone, which is
    what a caller with no board link has.

    **A value the pool recovered counts** (issue #86, through
    :func:`_pool_reading`): the split stays a function of a capacitance, and the
    capacitance is the one the part's identity states when the drawing's own
    field is blank. ``""`` keeps its meaning — neither the drawing nor the
    identity could supply one.
    """
    farads, _basis = _pool_reading(candidate, model, schematic)
    if farads is None:
        return ""
    if farads + _BOUNDARY_FARADS >= HF_POOL_FARADS:
        return POOL_STORAGE
    return POOL_HF


def _pool_reason(
    candidate: object, model: object, schematic: object | None = None
) -> str:
    """The evidence string for one candidate's pool assignment.

    The **basis** is :func:`_declared`'s own sentence, printed verbatim: it names
    the view the value was judged on and, when the two views disagree, both
    declarations. That is 164b's whole point — an evidence line that says
    「declared '100nF'」 while reading a field the schematic contradicts is a lie,
    and the fix is for the row to quote the schematic *and* the copy.

    Issue #86 adds one clause to that sentence: when the drawing states nothing
    and the value came from the part's identity, the basis says so
    (:func:`_pool_reading`), so the row never presents a recovered number as a
    declared one.
    """
    designator = str(getattr(candidate, "designator", "") or "")
    farads, basis = _pool_reading(candidate, model, schematic)
    if farads is None:
        return (
            f"candidate {designator}: {basis} — not a readable "
            f"capacitance, so UNKNOWN and in neither pool"
        )
    if farads + _BOUNDARY_FARADS >= HF_POOL_FARADS:
        return (
            f"candidate {designator}: {basis} = "
            f"{farads * 1e6:g} µF >= {HF_POOL_FARADS * 1e6:g} µF — "
            f"{_POOL_LABELS[POOL_STORAGE]} pool (岳裁定 ③, the middle band is "
            f"assigned to storage, not left undecided)"
        )
    return (
        f"candidate {designator}: {basis} = "
        f"{farads * 1e6:g} µF < {HF_POOL_FARADS * 1e6:g} µF — "
        f"{_POOL_LABELS[POOL_HF]} pool"
    )



def _regulator_readings(
    model: object, library=None, *, allow_machine: bool = False
) -> tuple[list[RegulatorReading], list[RegulatorReading]]:
    """Every ``ic.ldo`` / ``ic.buck`` part, per board, with its pin roles read.

    The shelf is read once through :func:`boardwise.core.parts.load_parts` /
    :func:`boardwise.core.parts.resolve_component_facts` — the whole identity
    chain (exact MPN → C-number → **device name**, #202's exactness lesson at
    every step), the same call
    :func:`boardwise.rules.pcb.distance.device_facts` and `checkup`'s gate make,
    asked directly so the category read here is the one this rule's evidence
    quotes. 187B moved this site onto that shared call: with only MPN/C码 the
    rule skipped parts the gate had already judged reviewable (task 186-H1).

    Sides come from :func:`boardwise.core.pinrole.pin_role` on each pin's
    **name**. A ground pin, an enable pin and an unconnected ``NC`` all resolve
    to a role that is neither ``IN`` nor ``OUT``, which is the correct answer:
    only the two supply pins carry a capacitor-pool question.

    527D3 reads the class through
    :func:`boardwise.core.partkind.category_verdict` and hands back **two
    lists** — ``readings`` (the shelf calls it a regulator at a tier this rule
    may act on) and ``gated`` (it calls it a regulator at a tier this rule may
    not: a machine-granted class for a conclusion rule, or a draft). Three rules
    read this function (``pcb-regulator-cap-distance``, and 131c's
    ``pcb-regulator-fb-placement`` twice), and all three owe each gated part a
    免责 row rather than the silence a non-regulator gets — a real regulator
    whose class nobody signed must not drop out of the regulator rules.
    """
    if library is None:
        try:
            library = read_default_library()
        except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
            library = None
    readings: list[RegulatorReading] = []
    gated: list[RegulatorReading] = []
    for _title, board_model in _board_models(model):
        components = getattr(board_model, "components", {}) or {}
        for designator in sorted(components):
            component = components[designator]
            entry, _matched = resolve_component_facts(library, component)
            verdict = category_verdict(
                entry, REGULATOR_CATEGORIES, allow_machine=allow_machine
            )
            if verdict == CATEGORY_ABSENT:
                continue
            nets_by_side: dict[str, list[str]] = {
                SIDE_INPUT: [],
                SIDE_OUTPUT: [],
            }
            unclassified: list[str] = []
            for pin in getattr(component, "pins", ()) or ():
                name = str(getattr(pin, "name", "") or "")
                role = pin_role(name)
                if role == "IN":
                    side = SIDE_INPUT
                elif role == "OUT":
                    side = SIDE_OUTPUT
                else:
                    unclassified.append(name or f"pin {getattr(pin, 'number', '?')!r}")
                    continue
                net = str(getattr(pin, "net", "") or "")
                if net and net not in nets_by_side[side]:
                    nets_by_side[side].append(net)
            reading = RegulatorReading(
                designator=str(designator),
                component=component,
                board_model=board_model,
                category=str(getattr(entry, "category", "") or ""),
                category_trust=str(
                    getattr(entry, "category_trust", FACTS_TRUST_VERIFIED)
                ),
                nets_by_side=nets_by_side,
                unclassified_pin_names=tuple(unclassified),
            )
            (gated if verdict == CATEGORY_GATED else readings).append(reading)
    return readings, gated


class RegulatorCapDistance(PcbRule):
    """Are each regulator's input and output capacitors **next to it**?

    One pass per regulator, per **side** (``VIN`` / ``VOUT``), per **pool**
    (:data:`POOL_HF` / :data:`POOL_STORAGE`), producing one ``INFO`` row each:

    * a pool with a measurable capacitor — the **nearest** one, its edge-to-edge
      distance in mils and the pad pair the number came from;
    * a pool with none — a row that names the designator, the side and the
      pool, and lists every candidate on the net that was excluded and why.

    The pool of candidates is :func:`~boardwise.rules.decap.cap_candidates_on`
    on **that side's own net** — the 127b predicate (a capacitor, bridging this
    net to a *different* ground net), so the two rules cannot disagree about
    what a decoupling candidate is. Splitting them into pools is
    :func:`regulator_role`'s job, and 裁定 ③ owns the boundary.

    **Which gap: the loop on the net, not the placement (issue #89).** The
    number is :func:`same_net_loop_distance` — the regulator's pad on ``net`` to
    the capacitor's pad on ``net``, edge to edge, planar and layer-blind. It is
    the reading :class:`~boardwise.rules.pcb.distance.DecapDistance` takes since
    164c, so one context yields one number from both rules. Until this fix the
    rule asked :func:`~boardwise.core.measure.component_distance`, which by
    design refuses same-net *and* cross-layer pad pairs; a decoupling pair is
    same-net by construction, so every real candidate came back ``None`` and the
    row said 「candidates exist but none is placed」 about a part
    :meth:`~boardwise.core.geometry.BoardGeometry.component` had just proved is
    on the board.

    **Measured, not judged.** See the module docstring: no threshold, every row
    ``INFO``. A board with no regulator in :data:`REGULATOR_CATEGORIES` produces
    nothing at all — and so does a context with no ``pcb_model`` (the schematic
    view is not a substitute, see the module docstring), or one where this PCB
    document places no part the shelf calls a regulator (``PCB2``/``PCB3`` of
    毕设FOC 1.0.0 carry none, and neither does ``llc_board.epro2``).
    """

    id = "pcb-regulator-cap-distance"
    title = "Regulator input/output capacitors sit next to the regulator pin they serve"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, read_default_library())

    def check_with_library(
        self, ctx: PcbReviewContext, library=None, *, allow_machine: bool = False
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        ``library=None`` degrades to an empty shelf — the same "shelfless
        reading is a narrower one" contract
        :func:`_regulator_readings` already honours, so the synthetic tests can
        inject a two-entry library without monkeypatching the project's own
        :func:`boardwise.rules.facts.read_default_library` (which
        :func:`~boardwise.rules.pcb.distance._supply_nets` shares).

        ``allow_machine`` (527D3) is this rule's tier question, stated by the
        caller with the conservative default
        :func:`~boardwise.rules.pcb.mcureset.McuResetBoot.check_with_library`
        uses: the rows are measurements, but 「this part is a regulator」 is an
        identity. A class the tier refuses comes back in the reader's ``gated``
        list and gets a 免责 row here.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        # 164b: the **value** every pool decision is made on comes from this
        # document's own schematic page, resolved once through the container's
        # declared board link. ``None`` (no link, or a synthetic context) leaves
        # the PCB document's copy as the only value there is, and every row then
        # says it is reading a fallback.
        schematic = schematic_board_of(ctx)
        findings: list[Finding] = []
        readings, gated = _regulator_readings(
            model, library, allow_machine=allow_machine
        )
        for reading in readings:
            if board.component(reading.designator) is None:
                continue  # no geometry on this PCB document: nothing to measure
            for side in (SIDE_INPUT, SIDE_OUTPUT):
                nets = list(reading.nets_by_side.get(side) or [])
                if not nets:
                    findings.append(self._no_side(reading, side))
                    continue
                for net in nets:
                    for pool in (POOL_HF, POOL_STORAGE):
                        findings.extend(
                            self._one_pool(
                                reading, board, side, net, pool, library, schematic
                            )
                        )
        for reading in gated:
            findings.append(self._tier_gate_row(reading))
        return findings

    def _tier_gate_row(self, reading: RegulatorReading) -> Finding:
        """The 免责 row for a regulator the shelf names but this tier may not hear.

        One call into :func:`boardwise.rules.facts.category_gate_finding`, which
        owns the sentence — 131c and this rule read the same helper, so the two
        regulator rules keep saying one sentence about one unsigned class.
        """
        from ..facts import category_gate_finding

        return category_gate_finding(
            rule_id=self.id,
            level=self.level,
            designator=reading.designator,
            category=reading.category,
            category_trust=reading.category_trust,
            subject="它的输入/输出电容",
        )

    # -- rows -------------------------------------------------------------

    def _identity(self, reading: RegulatorReading) -> list[str]:
        """The evidence every row of one regulator carries."""
        facts = [
            f"{reading.designator} read as a regulator because the shelf "
            f"category is {reading.category!r}"
        ]
        if reading.unclassified_pin_names:
            facts.append(
                "pins whose names declare no supply role (UNKNOWN, and so not "
                f"on either side): {', '.join(reading.unclassified_pin_names)}"
            )
        return facts

    def _no_side(self, reading: RegulatorReading, side: str) -> Finding:
        """The row for a side no pin declared: 「which side, and there is none」."""
        label = _SIDE_LABELS[side]
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{reading.designator} declares no pin whose name reads as "
                f"{label}, so its {label} side has no net to measure and "
                f"neither {label} pool is examined — the pin names this rule "
                f"could not classify are in the evidence"
            ),
            evidence=self._identity(reading),
            target=FindingTarget(component_ref=reading.designator),
        )

    def _empty_reason(
        self,
        unplaced: list[str],
        padless: list[str],
        net: str,
        excluded: list[str] | None = None,
    ) -> str:
        """The parenthetical that says **why** a pool row has no measurement.

        Issue #89: the reasons are different claims and must not wear each
        other's clothes. 「no capacitor on the net at all」 is about the design;
        「none is placed on this PCB document」 is about the board's scope;
        「on the board but no same-net pad pair on this net」 is about this
        document's geometry — which is what the rule used to misreport as
        「none is placed」 whenever ``component_distance`` refused the pair.

        ``excluded`` is the **pool** side (#89 review): when the net carries
        candidates but every one of them belongs to the other pool (or states no
        readable capacitance), the net is not empty and this pool is. The old
        wording said 「no capacitor on the net at all」 directly under an evidence
        list naming that capacitor — two statements that cannot both be true.
        """
        if not unplaced and not padless:
            if excluded:
                return (
                    f" (the net is not empty: "
                    f"{', '.join(sorted(excluded))} on {net!r} is outside this "
                    f"pool — either the other pool or no readable "
                    f"capacitance — so this pool is empty, not the net)"
                )
            return " (no capacitor on the net at all)"
        if padless and not unplaced:
            return (
                f" (the candidates are on this PCB document, but no same-net "
                f"pad pair on {net!r} is measurable — unmeasurable, not 0 mil "
                f"and not unplaced)"
            )
        if unplaced and not padless:
            return (
                " (candidates exist but none is placed on this PCB document)"
            )
        return (
            " (some candidates are not placed on this PCB document, and the "
            f"rest are on it but have no measurable same-net pad pair on "
            f"{net!r})"
        )

    def _empty_evidence(
        self,
        unplaced: list[str],
        padless: list[str],
        net: str,
        excluded: list[str] | None = None,
    ) -> str:
        """The evidence line that names which candidates fell in which bucket."""
        parts: list[str] = []
        if unplaced:
            parts.append(
                "not placed on this PCB document: "
                + ", ".join(sorted(unplaced))
            )
        if padless:
            parts.append(
                f"on this PCB document with no pad on {net!r}: "
                + ", ".join(sorted(padless))
            )
        if not parts:
            if excluded:
                return (
                    f"candidates bridging {net!r} to a ground net are outside "
                    f"this pool: " + ", ".join(sorted(excluded))
                )
            return f"no candidate capacitor bridges {net!r} to a ground net"
        return "; ".join(parts)

    def _one_pool(
        self,
        reading: RegulatorReading,
        board: BoardGeometry,
        side: str,
        net: str,
        pool: str,
        library,
        schematic: object | None = None,
    ) -> list[Finding]:
        """The one row for ``(side, net, pool)`` of one regulator.

        The measurement is :func:`same_net_loop_distance` (issue #89), and the
        empty-pool row tells the cases apart instead of collapsing them:
        no capacitor on the net at all, a net whose every candidate is in the
        other pool (the pool is empty, not the net — #89 review), candidates
        this PCB document does not place, and candidates it does place but with
        no pad on ``net``. The last is 「unmeasurable」 — it must never read as
        0 mil or as unplaced.
        """
        label = _SIDE_LABELS[side]
        pool_label = _POOL_LABELS[pool]
        candidates = list(cap_candidates_on(reading.board_model, net, library))
        members = [
            c
            for c in candidates
            if regulator_role(c, reading.board_model, schematic) == pool
        ]
        excluded = [c for c in candidates if c not in members]
        excluded_names_list = sorted(c.designator for c in excluded)
        evidence = [
            *self._identity(reading),
            f"{label} net is {net!r} (read from the pin's name, not from a "
            f"netname pattern)",
            f"candidates bridging {net!r} to a ground net: "
            f"{', '.join(sorted(c.designator for c in candidates)) or '(none)'}",
            *[_pool_reason(c, reading.board_model, schematic) for c in sorted(
                candidates, key=lambda c: c.designator
            )],
        ]
        measured: list[tuple[str, SameNetLoopDistance]] = []
        unplaced: list[str] = []
        padless: list[str] = []
        for candidate in members:
            if board.component(candidate.designator) is None:
                # Named by the netlist, not carried by this PCB document — the
                # old path, kept: this is the 「not on the board」 case, not the
                # 「on the board but not measurable on this net」 one below.
                unplaced.append(candidate.designator)
                continue
            distance = same_net_loop_distance(
                board, reading.designator, candidate.designator, net
            )
            if distance is None:
                # On this board, but no pad of either part carries ``net``:
                # unmeasurable, **not** zero and **not** unplaced (issue #89).
                padless.append(candidate.designator)
                continue
            measured.append((candidate.designator, distance))
        if not measured:
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{reading.designator} has no {pool_label} capacitor "
                        f"measurable against its {label} net {net!r} — the "
                        f"{label} {pool_label} pool is empty on this net"
                        + self._empty_reason(
                            unplaced, padless, net, excluded_names_list
                        )
                    ),
                    evidence=evidence
                    + [
                        self._empty_evidence(
                            unplaced, padless, net, excluded_names_list
                        ),
                    ],
                    target=FindingTarget(
                        component_ref=reading.designator, net_refs=[net]
                    ),
                )
            ]
        nearest, distance = min(
            measured, key=lambda pair: pair[1].edge_distance
        )
        excluded_names = ", ".join(sorted(c.designator for c in excluded))
        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    f"{reading.designator}'s nearest {pool_label} capacitor on "
                    f"its {label} net {net!r} is {nearest} at "
                    f"{_mil(distance.edge_distance):.1f} mil edge-to-edge "
                    f"(pads {distance.pad_a} / {distance.pad_b}) — measurement "
                    f"only, no pool threshold is in force yet"
                ),
                evidence=evidence
                + [
                    f"nearest: {nearest} @ {net} = "
                    f"{_mil(distance.edge_distance):.1f} mil edge-to-edge",
                    f"measured {pool_label} members: "
                    + ", ".join(
                        f"{name}={_mil(distance_.edge_distance):.1f}"
                        for name, distance_ in sorted(
                            measured, key=lambda pair: pair[1].edge_distance
                        )
                    ),
                    (
                        f"excluded from this pool on {net}: {excluded_names}"
                        if excluded_names
                        else f"no capacitor on {net} is excluded from this pool"
                    ),
                ],
                target=FindingTarget(
                    component_ref=reading.designator,
                    net_refs=[net],
                    counterpart_ref=nearest,
                    measurement=_measurement("distance", distance.edge_distance),
                ),
            )
        ]
