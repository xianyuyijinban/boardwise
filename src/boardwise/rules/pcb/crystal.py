"""An MCU's crystal network: where the reference and the load caps sit (task 131d).

131a landed the pin names, 131b read them as ``IN`` / ``OUT`` on a **regulator**,
and 131c read them as ``FB`` on the same. 131d reads a **microcontroller's**
oscillator pins, which is a third object and the last pin-name consumer in the
MCU pack: the pins are not a supply, the net carries a frequency reference
rather than a rail, and the parts that matter are a **crystal** and its two
**load capacitors** rather than a bypass and a divider.

**The pin names, and the fix that made them usable (131d, 零).**
:func:`boardwise.core.pinrole.pin_role` read ``PF0-OSC_IN`` as ``IN`` before
this batch — the token scan split it into ``PF0-OSC`` + ``IN`` and the ``IN``
half is a power-table hit. Any rule asking ``role == "IN"`` would have had a
crystal oscillator input in its regulator-input pool. The pinrole side is
fixed there; what this rule needs is the *name* rather than the role, and it
reads the name with a substring test (:func:`oscillator_pins_of`) precisely so
it never depends on the role vocabulary at all. The two are kept apart on
purpose: ``pin_role`` answers 「does this name declare a supply role」, which is
``False`` for every oscillator pin, and this rule asks 「which pins name an
oscillator」, which is a different question with a different answer.

**Which pins, and which nets.** Every pin whose **name** carries ``OSC``, on
any part the shelf calls :data:`MCU_CATEGORIES` (``ic.mcu``). The measured
spellings are ``PH0-OSC_IN`` / ``PH1-OSC_OUT`` (毕设FOC 1.0.0 and 1.1.0, 高速板),
``PF0-OSC_IN`` / ``PF1-OSC_OUT`` (ROBOT ctrl FOC, 药箱), ``PC14-OSC32_IN`` /
``PC15-OSC32_OUT`` (every STM32 on the corpus) and ``PD0-OSC_IN`` /
``PD1-OSC_OUT`` (超声波) — and the crystal's own end pins read ``OSC1`` /
``OSC2``. A pin with **no net** is an unpopulated branch (the 32.768 kHz option
every STM32 declares and neither acceptance board uses) and is **skipped**,
one row naming it, because 「nobody fitted the low-frequency crystal」 is not a
defect and never inventing a crystal for it is the honest answer.

**How a crystal is recognised — the acknowledged fragile step.** The shelf has
no crystal category: ``blocklib/parts.json`` carries 14 and neither crystal on
the acceptance boards is one of them (both have an **empty** ``category``,
while :func:`boardwise.rules.pcb.distance.classify_device` counts 87 of the
shelf's 109 curated entries as category-less). So unlike 131b and 131c there
is no shelf answer to consult, and this rule falls back to a two-signal sieve
over the part's own text — the ``value`` spelling a frequency (``25MHz``) or the
footprint naming the crystal package (``3225``). **This is deliberately the
fragile part of the rule and it is declared as such** in
:data:`CRYSTAL_NAME_HINT` and :func:`is_crystal_member`: it pattern-matches a
part's spelling where 131a's whole argument is that identity must come from a
stated field. The two signals are the narrowest available — a frequency with
its unit is not a part number and a ``3225`` package is not a chip-size
footprint — and the alternative (requiring a category that does not exist)
would have made the rule silent on every board in the corpus, which is worse
than narrow. A part that matches neither is simply not a crystal and the rule
says so.

**Load capacitors: the bridging predicate, and why the same-net form is out.**
A load capacitor is a capacitor **from an oscillator net to a ground net** —
one terminal on ``OSC-IN`` or ``OSC-OUT``, the other on a *different* ground
net. That is :func:`boardwise.rules.decap.cap_candidates_on`'s predicate
verbatim, the one 126b and 131b already use, so the three rules cannot
disagree about what a grounded capacitor is. Its complement matters just as
much: ROBOT's ``C3`` has **both** terminals on ``OSC-OUT``, so it bridges
nothing and is excluded structurally — there is no second net to bridge to.
That part is reported, once, in the exclusion list and never as a measured
load capacitor: a capacitor drawn across a single node is a drawing or
netlist question, not a placement measurement, and the task pins the exclusion.

**The three columns, and who judges them.** Every load-capacitor row carries,
side by side:

* **规格 CL** — the crystal's *spec* load capacitance, from the shelf's
  ``Load Capacitance`` param (measured: ``20pF`` on ``X322525MSB4SI``, ``12pF``
  on ``X32258MOB4SI``). Absent where the shelf has no entry, and the row then
  says so rather than substituting the as-declared value for the spec.
* **实测容值** — what the board actually fitted, read through
  :func:`boardwise.core.values.parse_capacitance_farads` on the part's own
  ``value``. 1.0.0's ``C25`` / ``C26`` read ``30pF``; ROBOT's ``C2`` reads
  ``100nF``.
* **串联等效 CL** — the two load capacitors in series, ``C/2``, plus
  :data:`PARASITIC_CAP_FARADS` (5 pF, the 「典型 3-7pF 取 5」 allowance, and a
  **default, not a measurement** — stated as such in the row).

**No verdict.** 1.0.0's 30 pF pair gives ``30/2 + 5 = 20 pF`` against a
``20pF`` spec, which matches, and ROBOT's ``100nF`` against ``12pF`` is three
orders of magnitude out. **Both are the same severity, and neither is graded**:
岳 has ruled on no tolerance, and a rule that invented one would put a number
in the ledger that nobody decided. What the task asks for is that the gap be
*visible*, and three columns side by side is what makes it visible — the
equivalent lands on the same row as the spec, so neither number can be read
without the other.

**Measured, not judged — the same discipline as 131b and 131c.** There is no
``*_DISTANCE_MIL`` constant in this module and every row is ``INFO``. The seam
is the same one those two left open: a later batch that gets a ruling adds the
constant and grades at it.

**Empty input is silence.** No ``ic.mcu`` part, no ``pcb_model`` (the PCB
document's own netlist view — see :mod:`boardwise.rules.pcb.regulator` for why
the schematic view is not a substitute), an oscillator net with no member that
is a crystal, and a crystal or a load capacitor the PCB document in hand does
not place, are each either silence or a single row that names what is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..base import Finding, FindingTarget
from ...core.geometry import BoardGeometry
from ...core.measure import pad_edge_distance
from ...core.parts import find_facts, load_parts
from ...core.values import parse_capacitance_farads
from ..decap import cap_candidates_on, same_net_capacitors_on
from ..facts import default_library_path
from .base import PcbReviewContext, PcbRule
from .distance import _mil, _measurement

__all__ = [
    "CRYSTAL_NAME_HINT",
    "MCU_CATEGORIES",
    "OSC_NAME_MARKER",
    "PARASITIC_CAP_FARADS",
    "McuCrystalPlacement",
    "McuOscillator",
    "is_crystal_member",
    "oscillator_pins_of",
    "series_equivalent_load",
]


#: The shelf categories this rule examines. Only ``ic.mcu``.
#:
#: The same discipline 131b states, for the same reason: a ``ic.reference``
#: (毕设FOC's ``U20`` = REF2033) has an oscillator of its own and is not a
#: microcontroller, and a part the shelf classifies nothing at all is UNKNOWN
#: rather than something to guess — 87 of 109 curated entries carry no
#: category, so guessing here would mean pattern-matching an MPN, which is the
#: failure mode 131a's ``pin_role`` was written to avoid.
MCU_CATEGORIES: frozenset[str] = frozenset({"ic.mcu"})

#: The marker an MCU pin's **name** must carry to be an oscillator pin.
#:
#: Read as a substring, case-insensitively after
#: :func:`boardwise.core.pinrole._normalise`, and deliberately *not* through
#: :func:`boardwise.core.pinrole.pin_role`: this rule asks which pins name an
#: oscillator, not whether they declare a supply role, and 131d's fix makes the
#: answer to the second question ``False`` for every one of them. Reading the
#: name directly is what lets the rule say *which pin* it means — a net-name
#: test could not name ``U1.5`` from ``OSC-IN``.
OSC_NAME_MARKER = "OSC"

#: Words that, in a part's own value or footprint, name a **frequency
#: reference**: the unit-suffixed frequency an editor accepts (``25MHz``,
#: ``8MHz``, ``32.768KHz``).
#:
#: **This is the fragile step and it is declared, not hidden.** The shelf has
#: no crystal category — ``blocklib/parts.json`` carries 14 and neither
#: crystal on the acceptance boards is one of them (both have an empty
#: ``category``) — so there is no stated field to read and this rule falls back
#: to the part's spelling. :func:`is_crystal_member` is exported and this tuple
#: is named so a reader can see the sieve rather than infer it.
CRYSTAL_NAME_HINT: tuple[str, ...] = ("MHZ", "KHZ")

#: Words that, in a part's **footprint**, name the crystal package family.
#: The 3225 SMD crystal is what both acceptance boards use
#: (``CRYSTAL-SMD_4P-L3.2-W2.5-BL``, and 1.0.0's ``OSC-SMD_4P-L3.2-W2.5-BL``).
CRYSTAL_FOOTPRINT_HINT: tuple[str, ...] = ("XTAL", "3225", "CRYSTAL")

#: The parasitic capacitance added to the series-equivalent load figure, in
#: farads.
#:
#: **A default, not a measurement.** 「典型 3-7pF 取 5」 — the trace and pad
#: capacitance a crystal sees in addition to its two fitted capacitors, taken
#: at the middle of the usual range. Nothing in the corpus states a figure for
#: any board, so the row says 「default」 next to it and a reader who has the
#: board's real stackup can replace it. It is a named constant rather than a
#: literal buried in the arithmetic for exactly that reason: it is the one
#: number in the load-capacitance row that this tool did not measure.
PARASITIC_CAP_FARADS = 5e-12

#: The label a load-capacitor row carries for each of its three columns. The
#: labels are the values, so a row and the comparison that produced it cannot
#: drift apart.
COL_SPEC = "规格 CL（晶振标称负载电容）"
COL_DECLARED = "实测容值（板上装的）"
COL_EQUIV = "串联等效 CL"


def _upper(text: object) -> str:
    return str(text or "").strip().upper()


def _pf(farads: float) -> str:
    """Farads in picofarads, spelled the way the board spells it (``5pF``).

    The load-capacitance columns are read against the drawings' own notation —
    ``20pF``, ``30pF``, ``100nF`` — so the derived number is spelled the same
    way rather than in the ``5 pF`` the ``{:g}`` of a float would give. A
    reader comparing the row to the parts list is comparing like with like.
    """
    return f"{farads * 1e12:g}pF"


def oscillator_pins_of(component: object) -> list[object]:
    """This part's pins whose **name** names an oscillator, in pin order.

    The test is a substring match on the uppercased name against
    :data:`OSC_NAME_MARKER`, and it is the name that is read — never the net,
    never the MPN, never a designator prefix. ``PF0-OSC_IN`` and ``PC14-OSC32_IN``
    both match; a pin named ``IN`` on a net called ``OSC-IN`` does not, because
    the rule has to be able to say *which pin* it means.
    """
    return [
        pin
        for pin in (getattr(component, "pins", ()) or ())
        if OSC_NAME_MARKER in _upper(getattr(pin, "name", ""))
    ]


def is_crystal_member(model: object, designator: str) -> bool:
    """Does the board's part at ``designator`` read as a **crystal**?

    The fragile step, in one function, and the docstring at the module head is
    its defence: the shelf carries no crystal category, so the two surviving
    signals are the part's own ``value`` spelling a frequency
    (:data:`CRYSTAL_NAME_HINT`) and its ``footprint`` naming the crystal
    package (:data:`CRYSTAL_FOOTPRINT_HINT`). Either alone is enough — a
    design that lost its value string still gets its crystal examined through
    the footprint — and a part matching neither is simply not a crystal, which
    the caller reports as such rather than guessing.

    Read off the **board model** the caller passed in, the same view
    :func:`boardwise.rules.pcb.regulator.regulator_role` reads, because the
    geometry and the netlist have to agree on which part is which.
    """
    component = (getattr(model, "components", {}) or {}).get(str(designator))
    if component is None:
        return False
    if any(hint in _upper(getattr(component, "value", "")) for hint in CRYSTAL_NAME_HINT):
        return True
    footprint = _upper(getattr(component, "footprint", ""))
    return any(hint in footprint for hint in CRYSTAL_FOOTPRINT_HINT)


def series_equivalent_load(farads: float) -> float:
    """``C/2 + parasitic`` — the equivalent load a pair of equal caps presents.

    The arithmetic is the textbook one: two equal capacitors from the
    oscillator pins to ground appear to the crystal as their parallel sum's
    reciprocal, i.e. ``C/2``, and the board's own stray capacitance is added
    on top. :data:`PARASITIC_CAP_FARADS` is a **default**, not a measurement
    (see the module head); this function adds it and does not decide whether
    the result is right — 岳 does.
    """
    return farads / 2.0 + PARASITIC_CAP_FARADS


def _load_capacitance_spec(component: object, library) -> tuple[str, str]:
    """``(spec text, basis)`` for the crystal's declared load capacitance.

    Read from the shelf's ``Load Capacitance`` **param** of the exact-matched
    entry (:func:`boardwise.core.parts.find_facts`, exact MPN then LCSC — #202's
    lesson), never from the MPN's size code and never from the board's fitted
    capacitors. The two are different quantities and confusing them is the
    mistake the three-column row exists to prevent.

    Returns ``("", reason)`` when the shelf has no entry or the entry states no
    such param — an honest 「no spec on the shelf」, not a substituted value.
    """
    entry = find_facts(
        library,
        mpn=str(getattr(component, "mpn", "") or ""),
        lcsc=str(getattr(component, "lcsc_part", "") or ""),
    )
    if entry is None:
        return "", (
            "no shelf entry for this crystal (exact MPN then LCSC both "
            "unmatched), so no 规格 CL is stated"
        )
    params = getattr(entry, "params", None) or {}
    for key in ("Load Capacitance", "External load capacitor", "负载电容"):
        text = str(params.get(key) or "").strip()
        if text:
            return text, f"shelf entry {entry.key!r}, param {key!r} = {text!r}"
    return "", (
        f"shelf entry {entry.key!r} states no load-capacitance param, so no "
        "规格 CL is available"
    )


@dataclass(frozen=True)
class McuOscillator:
    """One MCU's oscillator network, as this rule established it and why."""

    #: The MCU designator and the shelf category that made it an MCU.
    designator: str = ""
    category: str = ""
    #: The board's own model (a multi-board project has one per board), which
    #: is also the model the capacitor candidates must be asked about.
    board_model: object = None
    #: ``{net: [(pin number, pin name), ...]}`` — the oscillator pins that
    #: carry a net. An unpopulated branch is in
    #: :attr:`unused_pin_names`, never here.
    pins_by_net: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    #: ``[pin name]`` for the oscillator pins with no net at all. Evidence for
    #: the 「skipped」 row, never a network.
    unused_pin_names: tuple[str, ...] = ()

    @property
    def nets(self) -> list[str]:
        return list(self.pins_by_net)


def _mcu_oscillators(model: object, library) -> list[McuOscillator]:
    """Every ``ic.mcu`` part, per board, with its oscillator pins read.

    The shelf is read once through :func:`boardwise.core.parts.load_parts` /
    :func:`~boardwise.core.parts.find_facts` — the same exact-match lookup
    131b and 131c use, asked directly so the category this rule's evidence
    quotes is the one the shelf states.
    """
    readings: list[McuOscillator] = []
    components = getattr(model, "components", {}) or {}
    for designator in sorted(components):
        component = components[designator]
        entry = find_facts(
            library,
            mpn=str(getattr(component, "mpn", "") or ""),
            lcsc=str(getattr(component, "lcsc_part", "") or ""),
        )
        category = (entry.category or "") if entry is not None else ""
        if category not in MCU_CATEGORIES:
            continue
        pins_by_net: dict[str, list[tuple[str, str]]] = {}
        unused: list[str] = []
        for pin in oscillator_pins_of(component):
            net = str(getattr(pin, "net", "") or "")
            name = str(getattr(pin, "name", "") or "") or f"pin {getattr(pin, 'number', '?')!r}"
            if not net:
                unused.append(name)
                continue
            pins_by_net.setdefault(net, []).append(
                (str(getattr(pin, "number", "") or ""), name)
            )
        readings.append(
            McuOscillator(
                designator=str(designator),
                category=category,
                board_model=model,
                pins_by_net=pins_by_net,
                unused_pin_names=tuple(unused),
            )
        )
    return readings


class McuCrystalPlacement(PcbRule):
    """Is a microcontroller's crystal and its load capacitors **next to it**?

    One pass per MCU, per **oscillator net**:

    1. the net is named by an oscillator pin of a part the shelf calls
       :data:`MCU_CATEGORIES`;
    2. the crystal on it is established (:func:`is_crystal_member`) and named;
    3. the load capacitors are the **ground-bridging** capacitors on that net
       (:func:`~boardwise.rules.decap.cap_candidates_on`) — a capacitor with
       **both** ends on the net is excluded, and named in the exclusion list,
       which is ROBOT's ``C3``;
    4. four numbers per crystal, all of them measurements:
       **crystal pad ↔ every oscillator pin of the MCU** (the full pad × pin
       matrix, each row saying whether it is the **same net** — the loop's own
       leg — or a cross-net reading, because
       :func:`component_distance` refuses same-net pairs and would answer with
       some other net's gap), **load capacitor ↔ the MCU's oscillator pin on
       the same net**, **load capacitor ↔ the crystal's pad on the same net**,
       and the **three-column load-capacitance figure**.

    **Measured, not judged.** See the module docstring: no threshold, every row
    ``INFO``, and the load-capacitance row is a comparison the rule makes and
    not a verdict it delivers. A board that places no MCU, a context with no
    ``pcb_model``, and a PCB document that carries no crystal produce nothing
    or one row that says which — and ``llc_board.epro2`` produces nothing at
    all, because it places no part the shelf calls an MCU.
    """

    id = "pcb-mcu-crystal-placement"
    title = "An MCU's crystal and its load capacitors sit next to the oscillator pins they serve"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        ``library=None`` degrades to an empty shelf — the same "shelfless
        reading is a narrower one" contract 131b and 131c honour, so the
        synthetic tests can inject a two-entry library without monkeypatching
        the project's own :func:`boardwise.rules.facts.default_library_path`.
        A shelfless crystal is still recognised
        (:func:`is_crystal_member` reads the part's own words), and a shelfless
        crystal has no 规格 CL, which the row then says.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        findings: list[Finding] = []
        for osc in _mcu_oscillators(model, library):
            if board.component(osc.designator) is None:
                continue  # no geometry on this PCB document: nothing to measure
            if osc.unused_pin_names:
                findings.append(self._unused_branch(osc))
            # Crystal-level rows first — the crystal-to-MCU matrix is a property
            # of the crystal, so it is emitted once per crystal here rather than
            # once per net below.
            for crystal in self._crystals_of(osc, board):
                findings.extend(self._crystal_to_mcu(osc, board, crystal))
            for net in sorted(osc.pins_by_net):
                findings.extend(self._one_net(osc, board, net, library))
        return findings

    # -- rows -------------------------------------------------------------

    def _identity(self, osc: McuOscillator) -> list[str]:
        """The evidence every row of one MCU's oscillator carries."""
        facts = [
            f"{osc.designator} read as an MCU because the shelf category is "
            f"{osc.category!r}",
            "oscillator pins were read off the pin **name** "
            f"(a substring test on {OSC_NAME_MARKER!r}), never off the net name "
            "and never off the MPN: "
            + ", ".join(
                f"pin {number} {name!r} @ {net!r}"
                for net, pins in sorted(osc.pins_by_net.items())
                for number, name in pins
            ),
            "131d's pinrole fix is what makes this rule's object reachable: "
            "before it, pin_role('PF0-OSC_IN') answered 'IN' and a rule "
            "asking for a supply IN role would have taken a crystal "
            "oscillator input for a regulator input pin",
        ]
        if osc.unused_pin_names:
            facts.append(
                "oscillator pins with no net at all (an unpopulated branch, "
                "skipped and never given a crystal): "
                + ", ".join(osc.unused_pin_names)
            )
        return facts

    def _unused_branch(self, osc: McuOscillator) -> Finding:
        """The row for an oscillator branch nobody populated.

        Every STM32 declares a 32.768 kHz option; neither acceptance board
        fits it. 「No crystal on this branch」 is an unpopulated option, not a
        defect, so the row says so rather than reporting a missing part.
        """
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{osc.designator} declares oscillator pin(s) "
                f"{', '.join(osc.unused_pin_names)} with **no net at all** — "
                "an unpopulated low-frequency branch, so no crystal, no load "
                "capacitor and no distance is claimed for it"
            ),
            evidence=self._identity(osc),
            target=FindingTarget(component_ref=osc.designator),
        )

    def _one_net(
        self,
        osc: McuOscillator,
        board: BoardGeometry,
        net: str,
        library,
    ) -> list[Finding]:
        """Every row for one oscillator net of one MCU."""
        model = osc.board_model
        evidence = self._identity(osc)
        members = sorted(
            {
                owner
                for owner, _pin in (getattr(model, "nets", {}).get(net).pins
                                    if model.nets.get(net) is not None else [])
            }
        )
        evidence.append(
            f"net {net!r} members as the board declares them: "
            f"{', '.join(members) or '(none)'}"
        )
        crystals = [
            designator
            for designator in members
            if is_crystal_member(model, designator)
        ]
        if not crystals:
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{osc.designator}'s oscillator net {net!r} carries no "
                        "member this rule reads as a crystal — no crystal is "
                        "placed, so no crystal-to-pin distance and no "
                        "load-capacitance figure is claimed (the members are "
                        f"{', '.join(members) or 'none'}; crystal recognition "
                        "is the documented two-signal sieve, so a crystal "
                        "spelled outside it would land here)"
                    ),
                    evidence=evidence,
                    target=FindingTarget(
                        component_ref=osc.designator, net_refs=[net]
                    ),
                )
            ]

        findings: list[Finding] = []
        for crystal in crystals:
            if board.component(crystal) is None:
                continue  # named by the netlist, not carried by this PCB document
            findings.extend(
                self._load_caps(osc, board, net, crystal, library, evidence)
            )
        return findings

    def _crystals_of(
        self, osc: McuOscillator, board: BoardGeometry
    ) -> list[str]:
        """Every crystal on any of this MCU's oscillator nets, placed on this board.

        De-duplicated across nets, because a crystal is a **part**: its two
        oscillator pads sit on ``OSC-IN`` and ``OSC-OUT``, so a per-net scan
        would find it twice. The crystal-to-MCU matrix is a property of the
        part, not of a net, and is emitted once per crystal from here.
        """
        found: list[str] = []
        for net in sorted(osc.pins_by_net):
            net_obj = (getattr(osc.board_model, "nets", {}) or {}).get(net)
            for owner, _pin in (getattr(net_obj, "pins", None) or []):
                designator = str(owner)
                if designator in found:
                    continue
                if not is_crystal_member(osc.board_model, designator):
                    continue
                if board.component(designator) is None:
                    continue  # named by the netlist, not carried by this document
                found.append(designator)
        return found

    def _crystal_identity(self, model: object, crystal: str) -> str:
        """One evidence line naming the crystal, its value and its MPN.

        The three-column row is a comparison about *this* reference, and a
        reader who only sees the numbers cannot tell which part they are
        about — 25 MHz / ``X322525MSB4SI`` on 毕设FOC, 8 MHz /
        ``X32258MOB4SI`` on ROBOT and 药箱. The frequency is also the signal
        the sieve matched on, so quoting it shows the reader the working.
        """
        component = (getattr(model, "components", {}) or {}).get(crystal)
        return (
            f"crystal {crystal}: value "
            f"{str(getattr(component, 'value', '') or '')!r}, MPN "
            f"{str(getattr(component, 'mpn', '') or '')!r}, footprint "
            f"{str(getattr(component, 'footprint', '') or '')!r}"
        )

    def _pad(self, board: BoardGeometry, designator: str, pin: str):
        for pad in board.pads_for_component(designator):
            if (pad.pin_number or pad.id) == pin:
                return pad
        return None

    def _crystal_to_mcu(
        self,
        osc: McuOscillator,
        board: BoardGeometry,
        crystal: str,
    ) -> list[Finding]:
        """The per-pin measurement: every crystal OSC pad against every MCU OSC pin.

        **The full matrix, not the same-net pair.** A crystal's oscillator pads
        are on two nets (``OSC-IN`` and ``OSC-OUT``) and the MCU's oscillator
        pins are on the two nets of the same names, so a same-net reading
        gives two rows and a component-level reading gives one wrong number
        (:func:`component_distance` refuses same-net pairs outright, so its
        answer on a crystal and its MCU is some *other* net's gap — 1.0.0's
        ``X1`` ↔ ``U1`` reads 93.2 mil at pads ``3``/``16``, which are
        ``OSC-OUT`` and a ``VCC`` pad).

        The four numbers are the two loop legs seen from both ends: on 毕设FOC
        1.0.0 ``X1.1`` (OSC-IN) reads **162.1 mil** against ``U1.12``
        (``PH0-OSC_IN``) and **162.8 mil** against ``U1.13`` (``PH1-OSC_OUT``),
        while ``X1.3`` (OSC-OUT) reads 96.4 and **93.3**; on ROBOT
        ``X2.1`` reads **160.2** against ``U1.5`` and **166.2** against
        ``U1.6``, and ``X2.3`` reads 88.0 against both. The same-net row is
        the leg the placement question is about, and the row says which of the
        two it is, so a reader can take either.

        Read pad to pad with :func:`~boardwise.core.measure.pad_edge_distance`,
        which is layer-blind by design (the caller decides what a
        cross-face pair means); the evidence quotes both pads' layers so that
        decision is available rather than implied.
        """
        xtal_pads = [
            pad
            for pad in board.pads_for_component(crystal)
            if pad.net and pad.net in osc.pins_by_net
        ]
        if not xtal_pads:
            return []
        mcu_pins = [
            (number, name, net_name)
            for net_name, pins in osc.pins_by_net.items()
            for number, name in pins
        ]
        findings: list[Finding] = []
        identity = [*self._identity(osc), self._crystal_identity(osc.board_model, crystal)]
        for pin_number, pin_name, pin_net in sorted(mcu_pins):
            mcu_pad = self._pad(board, osc.designator, pin_number)
            if mcu_pad is None:
                continue
            for pad in sorted(xtal_pads, key=lambda p: p.pin_number or p.id):
                distance = pad_edge_distance(pad, mcu_pad)
                same_net = pad.net == pin_net
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity="INFO",
                        level=self.level,
                        message=(
                            f"{crystal}.{pad.pin_number or pad.id} @ {pad.net!r} "
                            f"sits {_mil(distance):.1f} mil edge-to-edge from "
                            f"{osc.designator}.{pin_number} "
                            f"({pin_name!r} @ {pin_net!r})"
                            + (
                                " — the **same net**, so this is the "
                                "oscillator loop's own leg"
                                if same_net
                                else " — a **cross-net** reading (the crystal's "
                                "other oscillator pad against this pin), reported "
                                "because the loop is closed by both and a reader "
                                "comparing the two numbers needs both"
                            )
                            + " — measurement only, no crystal-loop threshold is "
                            "in force yet"
                        ),
                        evidence=[
                            *identity,
                            f"read pad to pad, not component to component: "
                            f"core.measure.component_distance refuses same-net "
                            f"pairs by design, so the component-level number on "
                            f"{crystal} ↔ {osc.designator} would be some other "
                            "net's gap",
                            f"{crystal}.{pad.pin_number or pad.id} @ {pad.net} "
                            f"(layers {sorted(pad.effective_layers()) or 'unstated'}) "
                            f"-> {osc.designator}.{pin_number} @ {mcu_pad.net or '(no net)'} "
                            f"(layers {sorted(mcu_pad.effective_layers()) or 'unstated'}) "
                            f"= {_mil(distance):.1f} mil edge-to-edge"
                            + ("" if same_net else "  [cross-net]"),
                            f"crystal pads carrying an oscillator net: "
                            + ", ".join(
                                f"{p.pin_number or p.id} @ {p.net}"
                                for p in xtal_pads
                            ),
                        ],
                        target=FindingTarget(
                            component_ref=crystal,
                            net_refs=[pad.net],
                            counterpart_ref=osc.designator,
                            measurement=_measurement("distance", distance),
                        ),
                    )
                )
        return findings

    def _load_caps(
        self,
        osc: McuOscillator,
        board: BoardGeometry,
        net: str,
        crystal: str,
        library,
        identity: list[str],
    ) -> list[Finding]:
        """The load-capacitor rows: the three columns, and the two distances.

        The candidate pool is :func:`~boardwise.rules.decap.cap_candidates_on`
        — a capacitor **bridging** this net to a ground net. ROBOT's ``C3`` has
        both terminals on ``OSC-OUT``, so it bridges nothing and is excluded
        structurally; it is named in the evidence as an exclusion, which is the
        difference between 「a load capacitor was measured」 and 「a capacitor
        is drawn across one node and is a different question」.
        """
        model = osc.board_model
        candidates = list(cap_candidates_on(model, net, library))
        excluded = [
            other.designator
            for other in same_net_capacitors_on(model, net)
        ]
        crystal_component = (model.components or {}).get(crystal)
        spec_text, spec_basis = _load_capacitance_spec(crystal_component, library)
        evidence = [
            *identity,
            self._crystal_identity(model, crystal),
            f"crystal {crystal} recognised as a frequency reference by the "
            "documented two-signal sieve (value naming a frequency, or a "
            "footprint naming the crystal package) — the shelf states no "
            "crystal category, so this step is the acknowledged fragile one",
            f"规格 CL source: {spec_basis}",
            f"load-capacitor candidates bridging {net!r} to a ground net: "
            + (", ".join(sorted(c.designator for c in candidates)) or "(none)"),
            *(
                [
                    f"excluded — {other} has **both** terminals on {net!r}, so "
                    "it bridges nothing and is not a load capacitor across the "
                    "oscillator loop (a capacitor drawn across a single node is "
                    "a drawing or netlist question, not a placement "
                    "measurement)"
                    for other in excluded
                ]
                or [f"no capacitor on {net!r} is excluded for sharing both ends"]
            ),
        ]
        if not candidates:
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"the load-capacitance network of {crystal} on {net!r} "
                        "is empty — no capacitor on this net bridges it to a "
                        "ground net, so no 实测容值 and no 串联等效 CL can be "
                        "stated for this leg"
                    ),
                    evidence=evidence,
                    target=FindingTarget(
                        component_ref=crystal, net_refs=[net]
                    ),
                )
            ]

        findings: list[Finding] = []
        mcu_pads = [
            (number, self._pad(board, osc.designator, number))
            for number, _name in (osc.pins_by_net.get(net) or [])
        ]
        xtal_pads = [
            pad for pad in board.pads_for_component(crystal) if pad.net == net
        ]
        for candidate in sorted(candidates, key=lambda c: c.designator):
            comp = (model.components or {}).get(candidate.designator)
            declared = str(getattr(comp, "value", "") or "")
            farads = parse_capacitance_farads(declared) if declared else None
            pads = board.pads_for_component(candidate.designator)
            on_net = [pad for pad in pads if pad.net == net]
            to_mcu = min(
                (
                    pad_edge_distance(pad, mcu_pad)
                    for pad in on_net
                    for _number, mcu_pad in mcu_pads
                    if mcu_pad is not None
                ),
                default=None,
            )
            to_xtal = min(
                (
                    pad_edge_distance(pad, xtal_pad)
                    for pad in on_net
                    for xtal_pad in xtal_pads
                ),
                default=None,
            )
            if farads is None:
                columns = (
                    f"{COL_SPEC}: {spec_text or '(no spec on the shelf)'}",
                    f"{COL_DECLARED}: {declared or '(nobody wrote one down)'} — "
                    "unreadable, so no 串联等效 CL is computed (an unreadable "
                    "value is UNKNOWN, never a zero)",
                )
                summary = (
                    f"{candidate.designator} on {net!r} states no readable "
                    f"capacitance (value {declared!r}) — the 规格 CL is "
                    f"{spec_text or 'not on the shelf'} and no 串联等效 CL is "
                    "computed, because this rule does not substitute a number "
                    "it cannot read"
                )
            else:
                equivalent = series_equivalent_load(farads)
                columns = (
                    f"{COL_SPEC}: {spec_text or '(no spec on the shelf — the shelf carries no 规格 CL for this part)'}",
                    f"{COL_DECLARED}: {declared} = {_pf(farads)}",
                    f"{COL_EQUIV}: {_pf(farads / 2)} (C/2) + "
                    f"{_pf(PARASITIC_CAP_FARADS)} parasitic "
                    f"(DEFAULT, 「典型 3-7pF 取 5」, not a measurement) = "
                    f"{_pf(equivalent)}",
                )
                summary = (
                    f"{candidate.designator} on {net!r}: 实测容值 {declared} "
                    f"({_pf(farads)}), 串联等效 CL {_pf(equivalent)}, against "
                    f"规格 CL {spec_text or 'not on the shelf'} — three columns "
                    "side by side and **no verdict**: 岳 has ruled on no "
                    "tolerance, so whether the two agree is a human reading, "
                    "and the numbers are placed together so it cannot be skipped"
                )
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=summary,
                    evidence=evidence
                    + [
                        *columns,
                        f"load capacitor {candidate.designator} -> MCU "
                        + (
                            "unmeasurable on this PCB document"
                            if to_mcu is None
                            else f"{_mil(to_mcu):.1f} mil edge-to-edge "
                            "(same-net pad pair, read directly)"
                        ),
                        f"load capacitor {candidate.designator} -> crystal "
                        + (
                            "unmeasurable on this PCB document"
                            if to_xtal is None
                            else f"{_mil(to_xtal):.1f} mil edge-to-edge "
                            "(same-net pad pair, read directly)"
                        ),
                    ],
                    target=FindingTarget(
                        component_ref=candidate.designator,
                        net_refs=[net],
                        counterpart_ref=crystal,
                    ),
                )
            )
        return findings
