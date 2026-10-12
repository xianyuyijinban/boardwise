"""PCB distance rules (task 126b, 通用层 1+9): how close things sit, and whether
anything hangs off the edge of the board.

Two rules, both reading :mod:`boardwise.core.measure` (task 125) and nothing
else — every number here comes out of a measurement primitive, never out of a
re-derivation:

* :class:`DecapDistance` (``pcb-decap-distance``) — **is the decoupling
  capacitor next to the chip that needs it?** For every IC and every supply net
  of that IC, find the capacitors that bridge that net to ground (the
  schematic model's own connectivity, through
  :func:`boardwise.rules.decap.cap_candidates_on` — the *same* predicate
  ``decap-required-caps`` uses) and measure the edge-to-edge gap to the nearest
  one. Too far is a WARN; a net with no grounded capacitor at all is an INFO
  that **names the net and the IC**, not a silence.
* :class:`ComponentSpacing` (``pcb-component-spacing``) — **do any two parts
  collide, and does anything hang off the edge?** Every pair of placed
  components in the same PCB document is measured once; a pair closer than the
  threshold is one WARN naming the *closest* pair's two designators, and a part
  whose pads reach past the board outline is an ERROR.

**The division of labour with the schematic side is the point of both rules.**
``decap-required-caps`` answers 「有没有」 — is a grounded capacitor of the
declared value on that net at all, from the datasheet's ``required_caps`` facts.
These two answer 「贴不贴」 — whether the one that is there sits next to the
chip. A board can pass the first and fail the second, and that is a real and
common defect (the cap was placed by the schematic's coordinates, the layout
never moved it), so neither rule duplicates the other's work: this module
**reuses** :func:`~boardwise.rules.decap.cap_candidates_on` and
:func:`~boardwise.rules.decap.same_net_capacitors_on` rather than re-deriving
"which capacitor counts", so the two halves cannot disagree about what a
decoupling candidate is.

**Supply nets come from the voltage inference, not from a name.** A net is a
*supply* net of an IC here when
:func:`~boardwise.core.power_domains.infer_net_domains` calls it ``KNOWN`` —
which is the net-name whitelist (``+5V``, ``3V3``, ...) plus a regulator's
declared or MPN-decoded output (011c). A net called ``VCC`` is **not** one: the
011 family exists because a name that reads like a rail is not a declaration,
and a rule that treated ``VCC`` as a supply net would put every signal net of a
connector named ``VCC`` into the report. On 毕设FOC's PCB1 that inference yields
exactly three supply nets (``+24V``, ``+5V``, and U11's LDO output ``NET10``),
which is why the measured run below reports four (IC, net) pairs rather than
the 100-odd the naive reading would produce — and four rather than 126b's five,
because ``U6`` is not an IC (127b). What the inference cannot say, it
does not say: a net it does not know is simply not examined, and the rule says
so in its own docstring rather than in a per-net UNKNOWN row (a rule that
emitted a row per unknown signal net would bury the five rows that matter under
a hundred that say nothing).

**Every threshold here is a house rule, not a standard.** Neither 200 mil nor
20 mil comes from IPC-2221 (that is 126c's job, and the two are deliberately
kept in separate files so the standards never launder a guess). Both constants
carry the provenance inline — and 岳's **2026-10-11** ruling has now fixed both
as graded lines (「以内 INFO、以外 WARN」, numbers kept), so these two rules are
the house-rule pair whose thresholds are no longer 待裁.

**Empty input never raises.** A board with no ICs, no capacitors, or no
outline produces no findings — except the one case where "no outline" is itself
worth saying (see :class:`ComponentSpacing`), and even that is silent rather
than an exception. :func:`boardwise.core.measure.component_distance` returns
``None`` for an unknown or padless designator, and every caller here treats
``None`` as "this pair cannot be measured, so it is not counted" rather than as
zero.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..base import Finding, FindingTarget
from ...core.geometry import BBox, BoardGeometry, Point
from ...core.measure import component_distance, pad_corners, pad_edge_distance
from ...core.model import is_ground_net
from ...core.parts import designator_category, find_facts, is_ic_designator, load_parts
from ...core.power_domains import infer_net_domains
from ...core.values import parse_capacitance_farads
from ..decap import cap_candidates_on
from .base import PcbReviewContext, PcbRule

#: How far a decoupling capacitor may sit from the IC it decouples, edge to
#: edge, in mils. Over this is a WARN — **the line is graded, and 岳 confirmed it
#: on 2026-10-11**: 「以内 INFO、以外 WARN」, with the number kept at the value this
#: constant already carried (200 mil). The same ruling upgraded the FOC pack's
#: driver-level reading of the same figure
#: (:data:`~boardwise.rules.pcb.foc.TI_DECAP_REFERENCE_MIL`), so the two rules now
#: grade the same distance consistently.
#:
#: **source: house rule（岳 2026-10 待裁 → 2026-10-11 裁：以内 INFO、以外 WARN）**
#: — not a standard. Nothing in
#: IPC-2221 states a placement distance (it states *clearance*, which is a
#: different question and 126c's), and the usual published figure for high-speed
#: decoupling is a fraction of a wavelength, which is a function of the edge
#: rate a design states and not a constant. 200 mil is the largest gap the 毕设FOC
#: measurement below still reads as plausible for a 0402/0603 bulk cap, and the
#: fixture's actual spread (26 / 32 / 47 / 56 mil) is far below it, so on this
#: board the threshold is not what decides anything — which is exactly the
#: evidence needed to say the number is a starting point, not a measurement.
DECAP_DISTANCE_MIL = 200.0

#: The smallest edge-to-edge gap two placed components may have, in mils.
#: Below this is a WARN — **岳 re-affirmed the line on 2026-10-11**: this is the
#: 「器件间距 20mil」 threshold of that ruling, and the number is kept as it was.
#: Note the direction: this one and :data:`DECAP_DISTANCE_MIL` are the same
#: shape of ruling (one side of the line is INFO, the other WARN) applied to two
#: opposite measurements — a *minimum* spacing against a *maximum* distance.
#:
#: **source: house rule（岳 2026-10 待裁 → 2026-10-11 裁：贴合/过近 WARN）** —
#: the placement-assembly and
#: solderability side of the same coin as the clearance rule, and again not an
#: IPC-2221 table value. The number is a *tightness* claim: below it two parts
#: cannot be reflowed or hand-soldered with ordinary clearance without the
#: solder mask bridging, and the jetted-assembly stencil wants roughly this much
#: room between adjacent apertures. 20 mil is where the two fixture populations
#: separate cleanly and where a real defect appears; 毕设FOC's PCB1 has 17 pairs
#: under it and 9 of those are touching (0 mil) — see the test module for the
#: measured distribution, which is the evidence behind asking 岳 to rule on it.
COMPONENT_SPACING_MIL = 20.0

#: A board outline with fewer corners than this is **not** a board outline, and
#: treating it as one manufactures ERRORs. The value is measured: 毕设FOC's PCB2
#: document carries a single-point ``BOARD_OUTLINE`` poly (17.4999, 27.5) — the
#: editor stored one vertex of a rectangle it never finished drawing — and 10 of
#: its 11 components sit outside that point. Reporting "all parts hang off the
#: board" for a board whose outline was never drawn is a false ERROR at board
#: scale, so a degenerate outline is treated as *absent*: the rule stays silent
#: about the board frame and says why in the module docstring rather than
#: blaming the parts.
MIN_OUTLINE_CORNERS = 3

#: The IC definition (127b): **the schematic's own device facts**, not a pin
#: count and not a designator prefix.
#:
#: 126b called anything with three or more pins an IC (:data:`MIN_IC_PINS`),
#: and the blind review found what that buys: on the 毕设FOC PCB3 the three
#: MOSFETs ``Q1`` / ``Q3`` / ``Q7`` (``MCAC53N06Y-TP``) each produced a
#: 「no decoupling capacitor near this IC」 WARN, and on PCB1 the **2x6 header
#: at ``U6``** produced one too — five false positives in all, every one of them
#: the rule asking a *transistor* or a *connector* for a bypass capacitor.
#:
#: The pin floor is kept (:data:`MIN_IC_PINS`) only as a **necessary**
#: condition — a two-pin part cannot have a decoupling requirement in any
#: meaningful sense — and the designator table
#: (:func:`~boardwise.core.parts.is_ic_designator`) is consulted **last**, as the
#: fallback for a part the device says nothing about. Both halves are pinned.
MIN_IC_PINS = 3

#: A designator prefix that is never an IC, whatever the shelf says. The pin
#: floor already excludes ``R`` / ``C`` / ``L`` (two pins), so this table is here
#: for the parts that are **many**-pin and still not an IC — a four-diode TVS
#: array, a multi-contact relay.
NON_IC_DESIGNATOR_PREFIXES: frozenset[str] = frozenset(
    {"D", "K", "T", "TVS", "RELAY", "XFMR"}
)

#: Footprint / value / MPN **words that name a header or a connector**, and are
#: therefore never an IC. This is the 127b discipline-5 case made mechanical: the
#: designator says ``U`` (so a designator table calls it an IC) and the part
#: says ``PZ2.54-2*6`` / ``PZ2.54-2x6P TP`` / ``PZ254V-11-04P`` — a **排针**, a
#: row of 2.54 mm holes. Measured on the fixture: U4 and U6 (PCB1) and U1 and
#: U2 (PCB3) are all ``PZ2.54``-family parts and all four carry
#: ``Designator: 'U?'``, which is precisely why the prefix cannot be trusted on
#: its own.
#:
#: Matched case-insensitively as a **substring** of the part's own text, because
#: these are the library's names and not ours: the same header family is spelled
#: ``PZ2.54-2*6``, ``HX PZ2.54-2x6P TP``, ``PZ254V-11-04P`` and
#: ``HDR-TH_4P-P2.54`` on four different parts.
CONNECTOR_WORDS: tuple[str, ...] = (
    "PZ2.54", "PZ254", "HDR", "HEADER", "CONN", "TYPE-C", "USB", "MX1.25", "XT60",
)

#: Words that name a **transistor** (MOSFET / BJT). A power MOSFET's drain sits
#: on a supply rail and its gate on a driver output, so a pin-count IC test reads
#: its ``+24V`` drain as 「an IC's supply net」 and asks for a bypass capacitor
#: beside it — exactly the false positive 岳 ruled on (裁定 1). Matched against
#: the same text, for the same reason.
TRANSISTOR_WORDS: tuple[str, ...] = (
    "MOS", "MOSFET", "N-CH", "P-CH", "2N7002", "MCAC", "DFN", "SOT-23", "SOT23",
)
#: ``TRANSISTOR_WORDS`` is scanned in order and the **first** hit is the reason
#: quoted in the evidence, so the order is a priority order and not a set: a
#: part named ``MCAC53N06Y-TP`` in an ``DFN(5x6)`` package must be reported as
#: 「transistor (``MCAC``)」 rather than as its package, because the MPN is the
#: part's identity and the package is a consequence of it.

#: Words that name a **passive** — a part with no supply rail of its own and
#: nothing to decouple. A two-pin passive never reaches the rule through the pin
#: floor; this is here for a passive **array** that arrives on a ``U``
#: designator.
PASSIVE_WORDS: tuple[str, ...] = ("RES-", "RES_", "CAP-", "CAP_", "XFMR", "TRANSFORMER")


@dataclass(frozen=True)
class DeviceFacts:
    """What the **schematic** says a part is — the 127b IC judgement's evidence.

    Three fields, all read off :class:`~boardwise.core.model.Component` (the
    parsed schematic placement, never the PCB footprint), plus the shelf entry
    that claims the part. Every one of them is optional, and the reason each one
    is here is measured:

    * ``shelf_category`` — ``blocklib/parts.json``'s own electrical
      classification, and the strongest signal when it is present: the
      fixture's ``ic.drv8350srtvr`` is ``ic.motor-driver`` and
      ``conn.type_c_16pin_2md_073`` is ``connector``. **Empty on most entries**
      — the fixture's headers and its MOSFET carry no ``category`` at all — which
      is exactly why this cannot be the only test.
    * ``text`` — the part's own ``footprint`` / ``value`` / ``mpn`` /
      ``device_name``, concatenated and lowercased. This is what catches the
      parts the shelf has not classified: a ``PZ2.54-2*6`` header says "2.54"
      and a ``MCAC53N06Y`` says "MCAC".
    * ``designator`` — the **fallback** and never more. U6 is a header whose
      designator says ``U``, which is why this is checked after everything else
      and why a ``U`` designator alone can no longer make a part an IC.
    """

    designator: str = ""
    shelf_category: str = ""
    text: str = ""


def device_facts(comp: object, library=None) -> DeviceFacts:
    """Read :class:`DeviceFacts` off one schematic :class:`Component`.

    The shelf is the **same** :func:`boardwise.rules.facts.default_library_path`
    every other facts-reading rule uses, resolved through
    :func:`~boardwise.core.parts.find_facts` (exact match on MPN then C-number,
    never a prefix match — #202's lesson). A missing shelf reaches
    :func:`boardwise.core.parts.load_parts` as a path that does not resolve,
    which that function already reads as an empty shelf, so this degrades to
    「the category half is absent」 rather than raising.

    ``library`` is an injection point for the tests and for a caller that has
    already read the shelf; the default reads the project's own.
    """
    from ..facts import default_library_path  # noqa: PLC0415 — read at call time

    if library is None:
        try:
            library = load_parts(default_library_path())
        except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
            library = None
    entry = find_facts(
        library,
        mpn=str(getattr(comp, "mpn", "") or ""),
        lcsc=str(getattr(comp, "lcsc_part", "") or ""),
    ) if library is not None else None
    props = getattr(comp, "props", {}) or {}
    text = " ".join(
        str(getattr(comp, name, "") or "")
        for name in ("footprint", "value", "mpn")
    )
    text = f"{text} {props.get('device_name', '') or ''}"
    return DeviceFacts(
        designator=str(getattr(comp, "designator", "") or ""),
        shelf_category=(entry.category or "") if entry is not None else "",
        text=text.lower(),
    )


def _hit(text: str, words: tuple[str, ...]) -> str:
    """The first word of ``words`` occurring in ``text``, or ``""``."""
    for word in words:
        if word.lower() in text:
            return word
    return ""


def classify_device(facts: DeviceFacts, *, pins: int) -> tuple[bool, str]:
    """Is this part an IC, and **why** — the ``(answer, evidence)`` pair.

    **The evidence string is not decoration.** The task book asks for the
    judgement's basis to be readable, and a rule that silently dropped four
    MOSFETs and four headers would be indistinguishable from one that got them
    right for the wrong reason.

    The order is the design, and each step is a place a part can stop:

    1. **fewer than three pins** — a two-pin part has no decoupling
       requirement. Necessary, never sufficient: this is what 126b stopped at.
    2. **the shelf's own category** — ``ic*`` is an IC; ``connector`` / ``fet`` /
       ``resistor`` / ``capacitor`` / ``crystal`` / ``inductor`` / ``diode`` /
       ``led`` are not. A part with **no** category does not stop here; it falls
       through to the words, because most of the fixture's parts carry none.
    3. **the part's own words** — a ``PZ2.54`` / ``HDR`` / ``TYPE-C`` footprint
       is a connector or header, ``MOS`` / ``MOSFET`` / ``2N7002`` is a
       transistor, a passive word is a passive. Each is a **stop**, not a guess:
       the part is not an IC and the reason names the word that decided it.
    4. **the designator** — the last resort, and the only step that can turn a
       part **into** an IC. It is reached only when the shelf and the words both
       said nothing. :func:`~boardwise.core.parts.is_ic_designator` is the
       project's own table.

    A part that stops at no step is **not** an IC by this rule's contract: the
    rule examines what it can establish and says so. That is the honest
    direction — it loses a real IC the shelf has never heard of, rather than
    filing a finding about a MOSFET.
    """
    if pins < MIN_IC_PINS:
        return False, f"{pins} pin(s) — below the {MIN_IC_PINS}-pin floor"
    if facts.shelf_category:
        category = facts.shelf_category
        if category.startswith("ic"):
            return True, f"shelf category {category!r} is an IC class"
        return False, f"shelf category {category!r} is not an IC class"
    text = facts.text
    hit = _hit(text, CONNECTOR_WORDS)
    if hit:
        return False, f"the part's own name or footprint says connector/header ({hit!r})"
    hit = _hit(text, TRANSISTOR_WORDS)
    if hit:
        return False, f"the part's own name or footprint says transistor ({hit!r})"
    hit = _hit(text, PASSIVE_WORDS)
    if hit:
        return False, f"the part's own name or footprint says passive ({hit!r})"
    prefix = re.match(r"^[A-Za-z]+", facts.designator or "")
    if prefix and prefix.group(0).upper() in NON_IC_DESIGNATOR_PREFIXES:
        return False, f"designator prefix {prefix.group(0)!r} never names an IC"
    if is_ic_designator(facts.designator):
        return True, (
            f"no device fact classifies it either way, so the designator "
            f"{facts.designator!r} is the fallback "
            f"({designator_category(facts.designator)!r})"
        )
    return False, (
        f"no device fact names it an IC and its designator "
        f"{facts.designator!r} does not either"
    )


#: A capacitor at or above this value is **bulk**: reservoir / inrush energy
#: storage, which belongs near the power entry or inside a big-current loop, not
#: against a chip pin. 岳裁定 5b asks for exactly this split. The number is a
#: **house rule** like 126b's two, and it is stated as such: the dividing line
#: between 「energy storage」 and 「bypass」 is where the capacitor's impedance
#: stops dominating the loop's own parasitics, which is a property of the *loop*
#: and not of the part. 10 µF is where it sits for every part on the 毕设FOC
#: fixtures, and the measured evidence agrees with the shape: every ``>= 10uF``
#: capacitor there is a ``330uF`` aluminium electrolytic (``PA50V330M10x15``, a
#: 10 mm can) — bulk by shape as well as by value.
BULK_FARADS = 10e-6

#: A capacitor at or below this value is a **high-frequency decoupling**
#: candidate. 1 µF is the classical ceramic-bypass ceiling: above it a
#: ceramic's impedance curve has already turned back up as its ESL dominates, so
#: a larger "decoupling" capacitor is not decoupling anything at high frequency.
#: House rule, same standing as :data:`BULK_FARADS`.
HF_FARADS = 1e-6

#: Slack for both boundary comparisons, in farads. See
#: :func:`capacitor_role` for why it is not optional.
_BOUNDARY_FARADS = 1e-12

CAP_ROLE_BULK = "bulk"
CAP_ROLE_HF = "hf"
CAP_ROLE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class CapRole:
    """Which role one candidate capacitor plays, and what said so.

    ``farads`` is read from the **schematic's own ``value`` field** through
    :func:`boardwise.core.values.parse_capacitance_farads` and never guessed —
    the task book forbids it, and 岳裁定 5b asks for the bulk/HF split to be a
    function of the value the drawing states. A candidate whose value nobody
    wrote down (:data:`CAP_ROLE_UNKNOWN`) is in **neither** pool: a capacitor
    whose value is unreadable is not evidence that it decouples anything, which
    is the same argument :func:`boardwise.rules.decap.decide_required_cap` makes.
    """

    designator: str
    role: str = CAP_ROLE_UNKNOWN
    farads: float | None = None
    #: Why — the declared value that decided it, or the fact that could not be
    #: read. Carried with the answer and quoted in the finding's evidence.
    reason: str = ""


def capacitor_role(candidate: object, model: object) -> CapRole:
    """The role of one :class:`~boardwise.rules.decap.CapCandidate`.

    The value comes from the **board model's own Component**, not from the
    candidate's echo of it, so the reading and the candidate cannot disagree
    about which field was consulted. ``>= BULK_FARADS`` is bulk, ``<= HF_FARADS``
    is a high-frequency candidate, and the band between them (1 µF < c < 10 µF,
    where this fixture's 2.2 µF and 4.7 µF parts sit) is **neither pool** —
    stated plainly rather than rounded into one, because that band is exactly
    where 「is it bulk or is it bypass」 is a question about the loop rather than
    about the part.
    """
    designator = str(getattr(candidate, "designator", "") or "")
    comp = (getattr(model, "components", {}) or {}).get(designator)
    declared = str(getattr(comp, "value", "") or "") if comp is not None else ""
    farads = parse_capacitance_farads(declared) if declared else None
    if farads is None:
        return CapRole(
            designator=designator,
            role=CAP_ROLE_UNKNOWN,
            farads=None,
            reason=(
                f"the schematic states no readable capacitance for it "
                f"(value {declared!r}) — an unreadable value is neither bulk "
                "nor a high-frequency candidate"
            ),
        )
    # A float tolerance at both boundaries, and it is not decoration:
    # ``parse_capacitance_farads("10uF")`` returns 9.999999999999999e-06, which
    # is *below* ``10e-06``. Without the epsilon a part whose value is exactly
    # the threshold would fall into the band between the pools and be silently
    # treated as neither — which is exactly the boundary case the pin exists to
    # settle. 1e-12 F is a picofarad, four orders below the smallest value any
    # real drawing states, and it is the same epsilon
    # :func:`boardwise.rules.decap.decide_required_cap` already uses for this
    # exact comparison.
    if farads + _BOUNDARY_FARADS >= BULK_FARADS:
        return CapRole(
            designator=designator,
            role=CAP_ROLE_BULK,
            farads=farads,
            reason=f"declared {declared!r} = {farads * 1e6:g} µF >= {BULK_FARADS * 1e6:g} µF — bulk",
        )
    if farads - _BOUNDARY_FARADS <= HF_FARADS:
        return CapRole(
            designator=designator,
            role=CAP_ROLE_HF,
            farads=farads,
            reason=f"declared {declared!r} = {farads * 1e6:g} µF <= {HF_FARADS * 1e6:g} µF — high-frequency decoupling",
        )
    return CapRole(
        designator=designator,
        role=CAP_ROLE_UNKNOWN,
        farads=farads,
        reason=(
            f"declared {declared!r} = {farads * 1e6:g} µF, between the "
            f"{HF_FARADS * 1e6:g} µF high-frequency ceiling and the "
            f"{BULK_FARADS * 1e6:g} µF bulk floor — neither pool"
        ),
    )


# ---------------------------------------------------------------------------
# shared readings
# ---------------------------------------------------------------------------


def _board_models(model: object) -> list[tuple[str, object]]:
    """``(board title, model)`` for every board in ``model``, in project order.

    The runner is handed the **project** model (040b: one model per project, one
    model per board inside it), and a PCB document is a *board's* board. So the
    supply-net question — which needs a netlist — is asked per board model
    rather than on a pooled project, and a multi-board project would otherwise
    raise :class:`~boardwise.core.model.MultiBoardProjectError` on
    ``.components`` or weld two boards' ``VCC`` into one (issue #19's shape).

    A plain :class:`~boardwise.core.model.DesignModel` (an ``.enet`` input, or
    one board's model on its own) is returned as a single entry with an empty
    title, so both callers read the same loop.
    """
    from ...core.model import ProjectModel

    if isinstance(model, ProjectModel):
        return [(board_model.board.title, board_model) for board_model in model.boards]
    if model is None:
        return []
    return [("", model)]


def _supply_nets(model: object) -> set[str]:
    """The nets this reading can call **supply nets**, across every board.

    A net is one when :func:`~boardwise.core.power_domains.infer_net_domains`
    returns a ``KNOWN`` domain for it. The shelf is read through
    ``blocklib/parts.json`` (the same default every facts rule uses, via
    :func:`boardwise.rules.facts.default_library_path`) because a regulator's
    output is one of the two things that makes a net's voltage knowable. The
    reader degrades on its own terms here and nothing is wrapped around it: an
    absent shelf reaches :func:`load_parts` as a path that does not resolve,
    which that function already reads as an empty shelf, and
    :func:`infer_net_domains` already handles a shelf-less reader (the net-name
    half keeps working, the regulator half is simply absent). Guarding the call
    here would have been a second, quieter version of the same handling — and
    the wrong direction to fail in, since an unreadable shelf would have cost
    the ``+5V``-style nets too.
    """
    from ..facts import default_library_path  # noqa: PLC0415 — read at call time

    library = load_parts(default_library_path())
    names: set[str] = set()
    for _title, board_model in _board_models(model):
        for name, guess in infer_net_domains(board_model, library).items():
            if guess.state == "KNOWN" and guess.volts is not None:
                names.add(name)
    return names


def _mil(value: float) -> float:
    """Round a mil reading for the report, keeping a measurable but stable value.

    The full float is kept in ``target.measurement`` (that is the evidence, and
    a reader may re-derive it); the message and the finding's own number are
    rounded to a tenth of a mil, which is finer than any placement tolerance
    anyone reads and coarser than the float noise a rotated-rectangle distance
    carries (measured: 31.74649999999997).
    """
    return round(value, 1)


def _measurement(kind: str, value: float) -> dict:
    """The structured reading a PCB finding carries (钉 3).

    ``unit`` is always ``"mil"`` and ``kind`` is one of the four the schema
    names. The two optional keys ``layer_ids`` and ``value_mm`` are **not**
    filled: a component-to-component edge distance is a plan-view gap that
    belongs to no single copper layer, and 125's own readers keep mil
    throughout (``core.measure`` never converts), so the one number here is in
    the one unit the rest of the PCB side speaks.
    """
    return {"kind": kind, "value": _mil(value), "unit": "mil"}


# ---------------------------------------------------------------------------
# pcb-decap-distance
# ---------------------------------------------------------------------------


class DecapDistance(PcbRule):
    """Are the decoupling capacitors **next to** the chips they decouple?

    One pass per IC, per supply net of that IC:

    1. the net is a supply net (the voltage inference says ``KNOWN`` — see the
       module docstring for why a net called ``VCC`` is not one);
    2. the grounded capacitors on it are read through
       :func:`boardwise.rules.decap.cap_candidates_on`, i.e. **the same**
       predicate ``decap-required-caps`` uses: a part that looks like a
       capacitor *and* bridges this net to a **different** ground net. A
       capacitor whose two terminals sit on one net bridges nothing and is not
       a candidate — that is 039 批①b's measurement, and it is inherited rather
       than re-argued;
    3. every candidate that has **geometry on this PCB document** is measured
       **on the net** against the IC — this capacitor's pad on ``net`` to this
       IC's pad on ``net``, edge to edge (:func:`~boardwise.core.measure.pad_edge_distance`) —
       and the **nearest** one is the row. A candidate with no geometry (a part
       the schematic names that this board does not carry — the multi-board
       case, and the 040/107 "a placement was dropped" case) is **skipped, not
       counted as zero**: an unmeasurable pair is the absence of information.
    4. edge distance over :data:`DECAP_DISTANCE_MIL` is a WARN; a net with **no
       candidate at all** is an INFO that names the IC and the net. That INFO is
       the one that overlaps the schematic side's territory, and it is
       deliberately *not* an ERROR: whether this net needs a capacitor is the
       datasheet's ``required_caps`` question (``decap-required-caps``, which
       runs on the same fixture and owns it), and a rule that invented the
       requirement here would be claiming a fact it does not have. What this
       rule can say without a datasheet is narrower and still useful: *this IC
       sits on a supply net and the design put no grounded capacitor anywhere
       on it*, which is a question about the layout worth asking.

    **Which distance, and why it changed (164c, D5).** The reading is the
    **same-net pad-to-pad** gap: the loop the capacitor actually decouples, and
    the number TI SLVA959B §5.3.1's 「within 0.2 in of the supply pin」 is about —
    the reading ``pcb-foc-decap-proximity`` (:mod:`boardwise.rules.pcb.foc`)
    already takes. Until 164c this rule measured
    :func:`~boardwise.core.measure.component_distance` instead, which refuses
    same-net pairs (the design *wants* a capacitor's pad on the supply net) and
    therefore answered with the closest pair across **other** nets — a placement
    distance that can be an order of magnitude smaller than the loop. Two rules
    with one threshold and two objects is exactly the 「两条规则可以互相矛盾」
    the audit filed; the object kept is the one the threshold belongs to. The
    placement distance is still quoted in every row's evidence, under its own
    name, so a reader who wants it does not have to go without it.

    **Severity and the third state.** Both severities are the two the schema
    has, and a board with nothing to say produces nothing: no ICs (silence), no
    supply nets (silence), no grounded capacitors on a net (one INFO), and no
    measurable candidate on a net (silence — the candidates exist, this PCB
    document does not carry them, and *that* is 126's per-board bookkeeping, not
    a layout claim).

    **What is an IC is now the schematic's own device facts**, not a pin
    count — see :func:`classify_device`, and 岳裁定 1 for the case that forced
    it. **The candidate pool is the high-frequency pool** — bulk capacitors are
    named and excluded, and an IC whose pool is entirely bulk gets an INFO
    saying so rather than a distance complaint; see :func:`capacitor_role` and
    岳裁定 5b.

    Measured on 毕设FOC's PCB1 (105 components) **after 127b**: 4 (IC, net)
    pairs, all INFO, **no WARN**. The 126b claim of 「one true positive, U6 on
    ``+24V`` at 556 mil」 is what the blind review rejected, and the schematic
    says why: U6 is a 2x6 排针 (``HX PZ2.54-2x6P TP``), and the single ``+24V``
    capacitor it was measured against is C17, a 4.7 µF part in the band between
    the HF ceiling and the bulk floor. On the 1.0.0 export — the board 岳
    actually uses — ``U6`` is the ``TPLP2981-30DBVR`` LDO and *is* judged an IC,
    which is the same rule reading two different boards correctly.
    """

    id = "pcb-decap-distance"
    title = "Decoupling capacitors sit next to the ICs they decouple"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None or ctx.model is None:
            return []
        supply = _supply_nets(ctx.model)
        # One PCB document carries one board's parts, and the module titles are
        # the schematic side's board names (`Board1` vs the PCB document's
        # `PCB1`), so the per-board supply sets are merged: an IC's pin is only
        # read through a net **some** board of the project calls a supply net.
        # Merging is the conservative direction — it can only add a net to
        # examine, never remove one — and it is what lets a rule that sees a
        # single PCB document still use the netlist the project read.
        findings: list[Finding] = []
        for designator, component, ic_model, why in _ic_pairs(ctx.model):
            if board.component(designator) is None:
                continue  # no geometry on this PCB document: nothing to measure
            nets = sorted(
                {
                    pin.net
                    for pin in component.pins
                    if pin.net and not is_ground_net(pin.net) and pin.net in supply
                }
            )
            for net in nets:
                findings.extend(
                    self._one_net(ic_model, board, designator, net, why)
                )
        return findings

    def _one_net(
        self,
        ic_model,
        board: BoardGeometry,
        designator: str,
        net: str,
        why_ic: str = "",
    ) -> list[Finding]:
        """The one row (or the one silence) for ``designator``'s supply ``net``.

        ``ic_model`` is the **board's own** model (see :func:`_ic_pairs`), which
        is the model :func:`~boardwise.rules.decap.cap_candidates_on` is asked
        about — asking the project pool instead would weld two boards'
        ``VCC`` into one net and count a capacitor from the other board as this
        one's decoupling (issue #19's shape).

        **The candidate pool is the high-frequency pool only** (127b, 岳裁定 5b).
        A ``330uF`` aluminium can sitting 508 mil from a MOSFET is not a
        mis-placed bypass capacitor — bulk energy storage belongs near the power
        entry, and asking for it to hug a chip pin was the second half of the
        blind review's complaint. Only a candidate the schematic declares at
        ``<= HF_FARADS`` is measured; a bulk one is named and excluded, and an
        IC whose whole candidate pool is bulk gets the INFO row below saying so
        rather than a WARN about a distance it should never have been asked for.
        """
        candidates = list(cap_candidates_on(ic_model, net))
        roles = {
            candidate.designator: capacitor_role(candidate, ic_model)
            for candidate in candidates
        }
        high_freq = [
            candidate.designator
            for candidate in candidates
            if roles[candidate.designator].role == CAP_ROLE_HF
        ]
        bulk = [
            candidate.designator
            for candidate in candidates
            if roles[candidate.designator].role == CAP_ROLE_BULK
        ]
        unreadable = [
            candidate.designator
            for candidate in candidates
            if roles[candidate.designator].role == CAP_ROLE_UNKNOWN
        ]
        role_evidence = [
            f"candidate {designator_} {role.role}: {role.reason}"
            for designator_, role in sorted(roles.items())
        ]
        if not high_freq:
            if bulk and not unreadable:
                return [
                    Finding(
                        rule_id=self.id,
                        severity="INFO",
                        level=self.level,
                        message=(
                            f"{designator} sits on the supply net {net!r}, and "
                            f"the only capacitors bridging it to ground are "
                            f"bulk ({', '.join(sorted(bulk))}) — bulk energy "
                            f"storage belongs near the power entry or inside the "
                            f"big-current loop, not against a chip pin, so there "
                            f"is no high-frequency decoupling candidate here to "
                            f"measure. Whether one is required at all is the "
                            f"datasheet's required_caps question "
                            f"(decap-required-caps)"
                        ),
                        evidence=[
                            f"{designator} @ {net} (no high-frequency candidate)",
                            f"{designator} judged an IC because {why_ic}",
                            *role_evidence,
                        ],
                        target=FindingTarget(component_ref=designator, net_refs=[net]),
                    )
                ]
            return [
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{designator} sits on the supply net {net!r}, and no "
                        f"high-frequency decoupling capacitor bridging it to "
                        f"ground was found on the net — whether one is required "
                        f"is the datasheet's required_caps question "
                        f"(decap-required-caps); this row says only that the "
                        f"layout has none to place"
                    ),
                    evidence=[
                        f"{designator} @ {net} (no high-frequency capacitor)",
                        f"{designator} judged an IC because {why_ic}",
                        *role_evidence,
                    ],
                    target=FindingTarget(component_ref=designator, net_refs=[net]),
                )
            ]
        candidates = high_freq
        # 164c (D5): the gap is read **on the net** — this capacitor's pad on
        # ``net`` to this IC's pad on ``net``, edge to edge. That is the loop the
        # capacitor actually decouples, and it is the reading TI SLVA959B §5.3.1
        # asks about (「within 200 mil of the supply pin」), which ``foc.py``'s
        # driver-level rule already measures. The measurement used to be
        # ``component_distance``, which refuses same-net pairs and therefore
        # answered with the closest pair across **other** nets — a placement
        # distance, and one the two rules could report differently for one
        # capacitor (the fixture below is measured at 210.0 vs 10.0 mil).
        ic_pads = [
            pad for pad in board.pads_for_component(designator) if pad.net == net
        ]
        measured: list[tuple[str, float]] = []
        for candidate in candidates:
            if board.component(candidate) is None:
                continue  # named by the netlist, not carried by this PCB document
            cap_pads = [
                pad for pad in board.pads_for_component(candidate) if pad.net == net
            ]
            if not cap_pads or not ic_pads:
                # No pad of this pair carries the net on this document, so there
                # is no loop leg to measure: unmeasurable, not zero (the same
                # "an unmeasurable pair is not counted" discipline as before).
                continue
            measured.append(
                (
                    candidate,
                    min(
                        pad_edge_distance(cap_pad, ic_pad)
                        for cap_pad in cap_pads
                        for ic_pad in ic_pads
                    ),
                )
            )
        if not measured:
            return []
        nearest, gap = min(measured, key=lambda pair: pair[1])
        evidence = [f"{designator} @ {net}", f"{nearest} @ {net}"]
        component_level = component_distance(board, designator, nearest)
        if component_level is not None:
            evidence.append(
                f"the reading is **pad-to-pad on {net!r}**: {nearest}'s pad on "
                f"{net!r} to {designator}'s pad on {net!r}, {_mil(gap):.1f} mil "
                "edge-to-edge — the loop this capacitor decouples, which is TI "
                "SLVA959B §5.3.1's own reference and the reading "
                "pcb-foc-decap-proximity takes. core.measure.component_distance "
                f"reads {_mil(component_level.edge_distance):.1f} mil (pads "
                f"{component_level.pad_a} / {component_level.pad_b}) — a "
                "**different** measurement, because it refuses same-net pairs and "
                "so answers with the closest pair across some other net; quoted "
                "so a reader who wants the placement distance has it"
            )
        target = FindingTarget(
            component_ref=designator,
            net_refs=[net],
            counterpart_ref=nearest,
            measurement=_measurement("distance", gap),
        )
        if gap <= DECAP_DISTANCE_MIL:
            return []
        return [
            Finding(
                rule_id=self.id,
                severity="WARN",
                level=self.level,
                message=(
                    f"{designator}'s nearest decoupling capacitor on {net!r} is "
                    f"{nearest} at {_mil(gap):.1f} mil edge-to-edge "
                    f"(pad on {net!r} to pad on {net!r}), over the "
                    f"{DECAP_DISTANCE_MIL:.0f} mil house rule — the loop it "
                    f"decouples is {_mil(gap) / DECAP_DISTANCE_MIL:.1f}x longer "
                    f"than the rule allows"
                ),
                evidence=evidence
                + [
                    f"candidates on {net}: {', '.join(sorted(candidates))}",
                    f"measured: {', '.join(f'{c}={_mil(d):.1f}' for c, d in sorted(measured, key=lambda p: p[1]))}",
                ],
                target=target,
            )
        ]


def _ic_pairs(model: object, library=None) -> list[tuple[str, object, object, str]]:
    """``(designator, component, board model, why)`` for every IC, in project order.

    **What changed in 127b, and why.** 126b's test was ``len(pins) >= 3`` and
    nothing else, which made every MOSFET and every 2.54 mm header an IC with a
    decoupling obligation. The blind review put a number on it: on 毕设FOC the
    three ``MCAC53N06Y-TP`` MOSFETs on PCB3 and the 2x6 headers at ``U4`` / ``U6``
    (PCB1) and ``U1`` / ``U2`` (PCB3) all carry a ``U``-prefixed or nine-pin
    designator and all four/five produced a WARN about a missing bypass
    capacitor. The judgement is now :func:`classify_device`, which reads the
    schematic's own facts; the pin floor survives only as a necessary condition
    inside it.

    **The board model, not the project pool.** A designator that is a 28-pin
    part on one board and a 2-pin header on another (040b's measured shape) must
    be judged per board. The board model travels with the designator because it
    is also the model the netlist half of the judgement (which capacitors bridge
    this net) must be asked of.

    The fourth element is the **evidence string** — which shelf category or
    which word in the part's own name decided it. It travels with the pair so
    the rule can quote it in a finding's evidence, which is the difference
    between 「we looked and it is not an IC」 and 「we did not look」.
    """
    pairs: list[tuple[str, object, object, str]] = []
    for _title, board_model in _board_models(model):
        components = getattr(board_model, "components", {}) or {}
        for designator in sorted(components):
            component = components[designator]
            pins = len(getattr(component, "pins", ()) or ())
            is_ic, why = classify_device(
                device_facts(component, library), pins=pins
            )
            if is_ic:
                pairs.append((str(designator), component, board_model, why))
    return pairs


# ---------------------------------------------------------------------------
# pcb-component-spacing
# ---------------------------------------------------------------------------


class ComponentSpacing(PcbRule):
    """Do any two parts collide, and does any part hang off the board?

    **Spacing.** Every unordered pair of placed components in this PCB document
    is measured once with :func:`~boardwise.core.measure.component_distance`
    (which is a bbox-rejected min over pad-pair edge distances, so 105
    components cost 5460 measurements in 0.66 s on the fixture — the whole
    O(n²) sweep is not the expensive part, the parse is). Each pair closer than
    :data:`COMPONENT_SPACING_MIL` is one WARN carrying the pair, the measured
    gap, and both designators' module names. **A designator that has no pads on
    this board is not in the sweep at all** (there is no shape to measure) and
    **two components whose pads overlap report 0.0**, which is what
    "touching" means and is a WARN like any other gap.

    **Two pairs are not measured at all** (task 127b, and both live inside
    :func:`~boardwise.core.measure.component_distance` rather than here, because
    they are facts about the copper and not about the threshold): a pad pair on
    **opposite faces** of the board, and a **same-net** pad pair. The first is
    127a's root cause — a bottom-side part's SMD pads carry the footprint's
    hardcoded ``layer_id == 1``, so a layer-blind reading compared copper across
    a 1.6 mm board; the second is 岳's, that two pads of one net meeting is the
    design's intent. Measured on 毕设FOC PCB1 this rule went from 17 WARNs
    (six of them 「touching」 on a DRC-clean board) to **4, none touching, all
    same-side and cross-net**.

    **Board frame.** A part whose pads' bounding box reaches past the outline is
    an ERROR, and each part gets at most one such row. The outline is read as an
    **axis-aligned bbox of its own points**, which is exact for the rectangle
    every real board outline in these fixtures is and conservative (never
    over-strict) for a cut-corner or round-corner outline: a part inside the
    polygon is inside its bbox, so no false ERROR can come from this. The part's
    own box is the bbox of every pad **corner**, not of the pad centres — a
    centre-only test would call a 40-mil pad sitting 30 mil inside the frame a
    part that is inside, and that is a real hole rather than a rounding detail.

    **A degenerate outline says nothing.** 毕设FOC's PCB2 document carries a
    *one-point* ``BOARD_OUTLINE`` poly (measured, see
    :data:`MIN_OUTLINE_CORNERS`) — an unfinished rectangle, not a board. A rule
    that measured against it would file 10 ERRORs saying every part on that
    document hangs off the board. Fewer than :data:`MIN_OUTLINE_CORNERS` corners
    is therefore read as **no outline at all**, and the board-frame half stays
    silent; the spacing half still runs, because a collision between two parts
    does not need a board frame to be true. That silence is a gap, not a pass:
    it is 126's job to report that a document's outline did not read, and this
    rule's job is to not invent parts hanging off a board that was never drawn.
    """

    id = "pcb-component-spacing"
    title = "Components keep their spacing and stay inside the board outline"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        designators = _measurable_designators(board)
        findings: list[Finding] = []
        for index, first in enumerate(designators):
            for second in designators[index + 1:]:
                distance = component_distance(board, first, second)
                if distance is None or distance.edge_distance >= COMPONENT_SPACING_MIL:
                    continue
                findings.append(
                    Finding(
                        rule_id=self.id,
                        severity="WARN",
                        level=self.level,
                        message=(
                            f"{first} and {second} are "
                            f"{_mil(distance.edge_distance):.1f} mil apart "
                            f"edge-to-edge (pads {distance.pad_a} / "
                            f"{distance.pad_b}), under the "
                            f"{COMPONENT_SPACING_MIL:.0f} mil house rule"
                            + (" — they touch" if distance.edge_distance <= 0.0 else "")
                        ),
                        evidence=[
                            f"{first}.{distance.pad_a} @ {distance.edge_distance:.4f} mil",
                            f"{second}.{distance.pad_b}",
                        ],
                        target=FindingTarget(
                            component_ref=first,
                            counterpart_ref=second,
                            measurement=_measurement("distance", distance.edge_distance),
                        ),
                    )
                )
        findings.extend(self._outside_outline(board, designators))
        return findings

    def _outside_outline(
        self, board: BoardGeometry, designators: list[str]
    ) -> list[Finding]:
        """One ERROR per part whose pads reach past a **real** board outline.

        The test is on each pad's **four corners**, not its centre. A centre is
        the weaker test and would be a real hole: a 40-mil pad centred 30 mil
        inside the frame reaches 10 mil past it, and a centre-only reading
        calls that part inside. The corners are read through
        :func:`boardwise.core.measure.pad_corners`, the same rotated-rectangle
        reading every other distance here uses, so a part that is off the board
        is caught at the same fidelity as a part that is too close to another.
        (126b promoted that helper from ``core.measure._pad_corners`` to the
        public ``pad_corners`` precisely because a rule in another layer is now
        its second caller and the repository's layer rule forbids crossing a
        layer boundary on a private name.)

        **The outline is a polygon, not its bounding box** (164c, the low-severity
        item of the audit). The comparison used to be ``pad_box`` vs
        ``BBox.from_points(outline.points)``, which is exact for the four-corner
        rectangles almost every board has and blind for anything else: a part
        sitting in an L-shaped board's **notch** is inside the box and outside the
        board, and the old reading said nothing about a part that is off the
        board. The number is now the same question asked properly — 「how far does
        the pad's deepest corner reach past the outline」 — and 「touching the edge
        is not over」 is kept exactly as it was (an on-edge point is inside, so its
        contribution is 0.0).
        """
        outline = board.outline
        if outline is None or len(outline.points) < MIN_OUTLINE_CORNERS:
            return []
        polygon = list(outline.points)
        findings: list[Finding] = []
        for designator in designators:
            pads = board.pads_for_component(designator)
            if not pads:
                continue
            over = 0.0
            worst = None
            for pad in pads:
                corners = pad_corners(pad)
                if not corners:
                    continue
                past = _outside_by(corners, polygon)
                if past > over:
                    over, worst = past, (pad, corners)
            if over <= 0.0 or worst is None:
                continue
            pad, corners = worst
            pad_box = BBox.from_points(corners)
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="ERROR",
                    level=self.level,
                    message=(
                        f"{designator}'s pads reach {over:.1f} mil past the board "
                        f"outline — the part is placed off the edge of the board"
                    ),
                    evidence=[
                        f"{designator}.{pad.pin_number or pad.id} corners "
                        + ", ".join(f"({c.x:.2f}, {c.y:.2f})" for c in corners)
                        + (
                            f"  (pad bbox {pad_box.min_x:.2f}, {pad_box.min_y:.2f})-"
                            f"({pad_box.max_x:.2f}, {pad_box.max_y:.2f})"
                            if pad_box is not None
                            else ""
                        ),
                        "board outline polygon ("
                        f"{len(polygon)} corners): "
                        + ", ".join(
                            f"({point.x:.2f}, {point.y:.2f})" for point in polygon[:8]
                        )
                        + (f", … (+{len(polygon) - 8} more)" if len(polygon) > 8 else ""),
                        "判据：焊盘的**四角**逐点对板框多边形做包含判定（在边上算在里面），"
                        "越界深度 = 最深那个越界角点到最近一条边的距离——"
                        "板框是 L 形/带缺口时，它的 AABB 会把缺口算进板内（164c）",
                    ],
                    target=FindingTarget(
                        component_ref=designator,
                        measurement=_measurement("distance", over),
                    ),
                )
            )
        return findings


def _point_in_outline(point: Point, polygon: list[Point]) -> bool:
    """Is ``point`` inside or **on** the board outline ``polygon``?

    Even-odd containment with an on-edge tolerance: a point on the boundary is on
    the board (「贴边不算越界」 — the board was routed to the outline), so the
    boundary counts as inside. The same 口径 as
    :func:`boardwise.core.measure.point_in_polygon` (public since 177), which this
    local copy still duplicates — 177 只收编了 focthermal 那份，这份留待后续。
    silk.py's ``_point_in_polygon`` is the deliberately different variant that does
    *not* count the boundary.
    """
    inside = False
    count = len(polygon)
    for index in range(count):
        a = polygon[index]
        b = polygon[(index + 1) % count]
        if _point_segment_mil(point, a, b) <= 1e-9:
            return True
        if (a.y > point.y) != (b.y > point.y):
            x_cross = a.x + (point.y - a.y) / (b.y - a.y) * (b.x - a.x)
            if point.x < x_cross:
                inside = not inside
    return inside


def _point_segment_mil(point: Point, a: Point, b: Point) -> float:
    """Distance from ``point`` to the segment ``ab``, in mils."""
    dx, dy = b.x - a.x, b.y - a.y
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.hypot(point.x - a.x, point.y - a.y)
    t = max(0.0, min(1.0, ((point.x - a.x) * dx + (point.y - a.y) * dy) / length_sq))
    return math.hypot(point.x - (a.x + t * dx), point.y - (a.y + t * dy))


def _outside_by(corners: list[Point], polygon: list[Point]) -> float:
    """How far a pad's rotated rectangle reaches past the outline, in mils.

    ``0.0`` when every corner is inside or on the outline — the口径 126b pinned
    and 164c keeps. Otherwise the **deepest** corner's distance to the nearest
    outline edge: the pad's furthest point past the boundary, which is the number
    「how far off the board is this part」 means. The corners are the pad's own
    rotated rectangle (:func:`boardwise.core.measure.pad_corners`), not its box.
    """
    outside = [
        corner for corner in corners if not _point_in_outline(corner, polygon)
    ]
    if not outside:
        return 0.0
    edges = [
        (polygon[index], polygon[(index + 1) % len(polygon)])
        for index in range(len(polygon))
    ]
    return max(
        min(_point_segment_mil(corner, a, b) for a, b in edges)
        for corner in outside
    )


def _measurable_designators(board: BoardGeometry) -> list[str]:
    """Placed designators, sorted, each with at least one pad on this board.

    Sorted so the pair sweep's order — and therefore which pair is "first" in
    the report — is a function of the board, not of the parser's record order.
    A designator placed twice on one document keeps one entry (the sweep is
    over designators, and :func:`~boardwise.core.measure.component_distance`
    reads the board's own pads for it, so a duplicate cannot produce a
    self-pair).
    """
    names = {
        str(comp.designator)
        for comp in board.components
        if comp.designator and board.pads_for_component(str(comp.designator))
    }
    return sorted(names)


__all__ = [
    "COMPONENT_SPACING_MIL",
    "DECAP_DISTANCE_MIL",
    "MIN_IC_PINS",
    "MIN_OUTLINE_CORNERS",
    "ComponentSpacing",
    "DecapDistance",
]
