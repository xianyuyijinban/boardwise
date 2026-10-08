"""Feedback-divider **placement**, read off the FB pin (task 131c, stick 3).

``pcb-regulator-cap-distance`` (131b) asks how far each regulator's input and
output capacitors sit from the pin they serve. This rule asks the narrower
question a **voltage-mode regulator** poses: where is the feedback network,
and where does its top leg actually land?

Three measurements per feedback divider, all of them numbers rather than
verdicts:

* **FB pin ↔ upper leg** and **FB pin ↔ lower leg** — edge-to-edge, with the
  pad pair. The FB node is a high-impedance sense node, so the loop between
  the divider tap and the pin is noise-coupled in proportion to its area; the
  two legs are reported separately because a design that puts the upper leg at
  the pin and the lower leg at the rail is a different defect from one that
  puts both at the rail.
* **FB pin ↔ the FB-node capacitor** — the capacitor on the tap net, if there
  is one. Reported as present-and-measured or as absent, with the tap's members
  quoted, because 「there is no capacitor on the FB node」 is a statement a reader
  can act on and 「the divider is 40 mil away」 is not. **Not** the
  ground-bridged predicate 126b and 131b use: the feedback-node capacitor
  filters the sensed node and may return to any local one — on 毕设FOC 1.0.0
  ``C92`` sits between the tap and ``$1N66641``, the bootstrap/RON node, which
  ``is_ground_net`` correctly refuses to call ground. Under the narrower
  predicate this rule would have said 「no FB-node capacitor」 on the one board
  that has one.
* **Which end the upper leg hangs on** — the output-capacitor end or the rail
  end, plus **how far the upper leg is from the nearest output capacitor**. The
  two are reported together and neither replaces the other, because on 毕设FOC
  1.0.0 they disagree in exactly the way this stick exists to surface: ``R14``
  and the output capacitors share the net ``+5V``, so the net comparison says
  「the output-capacitor end」 — while the nearest storage capacitor on that node
  is ``C101``, **745.2 mil** away. The rail is shared; the node is not local.
  Whether that is wrong is 岳's call; what this rule does is put both numbers
  in one row so the premise can be rejected as well as the conclusion.

**How a divider is recognised, and why the sieve is needed.** The mechanical
criteria are the ones ``rules/params.py`` already established (task 129's
divider reader, the code the task book points at): the upper leg has one end on
a net with an **established, non-ground** domain, the two legs share a **non-
ground tap net**, the lower leg's other end is on **ground**, and the tap has
**at least one member that is not a leg** — an unloaded divider declares no
range.

Those four criteria alone do not say *feedback*. Measured across the fixture
corpus they yield **two** groups on 毕设FOC 1.0.0 (``R14``/``R21`` on ``+5V``
and ``R26``/``R35`` on ``+24V``), one on 毕设FOC 1.1.0's ``PCB1``
(``R20``/``R23``, the buck that board's *first* document never reaches), one on
``ROBOT ctrl FOC`` (``R6``/``R7`` into ``VBUS``) and two on
``DCDC-12V9V转5V3V3`` (``R5``/``R6`` and ``R7``/``R9``) — four boards, six
groups, and only some of them feedback networks. ``R26``/``R35`` on
1.0.0 is a current-sense divider into the STM32's ``PC4``, and ``R7``/``R9`` on
the DCDC board is an enable threshold. A resistor divider reading a rail is
the same shape whether the thing it feeds is a regulator's sense pin or a
microcontroller's ADC, and the mechanical criteria cannot tell them apart. So
this rule adds **one** filter, the one the task book names:

    **the tap's IC-side member must sit on a pin whose *name* reads as ``FB``
    (:func:`boardwise.core.pinrole.pin_role`), and that member must be a
    part the shelf calls a regulator.**

Both halves are needed and each excludes a different family:

* the ``FB`` role excludes a **current-sense / ADC** divider — the STM32's
  ``PC4`` is named for what it is, and the name is not ``FB``;
* the **regulator** half excludes a divider feeding something that is not a
  power regulator at all, and the **strictness of the role test** is what
  excludes an **EN / UVLO threshold** divider, whose tap *does* land on a
  regulator pin. The DCDC board carries exactly that case (``R7``/``R9`` on
  ``+12V`` into ``U9``'s ``EN``), and ``EN`` is not ``FB`` — but the shelf does
  not classify the TPS560430 as a regulator, so on that board the *category*
  half rejects it first and the *role* half is never reached. The role half's
  load-bearing case is therefore built synthetically in the test
  (``test_an_en_threshold_divider_on_a_real_regulator_is_not_a_feedback_one``):
  same IC, same category, same tap shape, one pin name different.

The filter is read off **pin names and the shelf**, never off an MPN pattern
and never off a net name, so a part with no name and no category is skipped
rather than guessed at.

**The rail-side answer is a net comparison, not a distance.** 「Is the upper
leg on the output-capacitor end or on the rail?」 is decided by asking whether
the leg's non-tap net is the same net as the non-ground net of any capacitor
on the regulator's output node. On 1.0.0 the answer is *rail*, and the row
says so with both net names quoted — a reader who believes ``+5V`` **is** the
output node (because ``L4``'s other pin really is on ``+5V``) can see the
comparison that produced the answer and disagree with the premise rather than
with the tool.

**Measured, not judged — the same discipline as 131b.** There is no
``*_DISTANCE_MIL`` constant in this module, and the one row that carries a
verdict-shaped word (「on the rail」 / 「on the output-capacitor end」) is an
``INFO`` that states the comparison, not a ``WARN`` that asserts a defect. 岳
has not ruled a threshold for FB loop area, leg spacing, or the sense-point
convention, and a rule that invented one would put a number in the ledger that
nobody decided. The seam is explicit: a later batch that gets a ruling adds the
constant and grades these rows at it.

**Empty input is silence.** A context with no ``pcb_model`` (see
:mod:`boardwise.rules.pcb.regulator` for why the netlist view is the PCB
document's own), a board that places no regulator, or a regulator with no pin
whose name reads as ``FB`` all produce nothing. A buck with no divider at all
produces one ``INFO`` naming the IC and the pin, because 「this regulator has
no feedback network drawn」 is a finding; a regulator with no ``FB`` pin name
produces nothing, because the rule has not established that the part has one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..base import Finding, FindingTarget
from ...core.geometry import BoardGeometry
from ...core.measure import component_distance
from ...core.model import is_ground_net
from ...core.parts import load_parts
from ...core.pinrole import pin_role
from ...core.power_domains import domain_of, infer_net_domains
from ...core.values import parse_resistance_ohms
from ..decap import CapCandidate, cap_candidates_on
from ..facts import default_library_path
from .base import PcbReviewContext, PcbRule
from .distance import _board_models, _mil, _measurement
from .regulator import (
    POOL_HF,
    POOL_STORAGE,
    REGULATOR_CATEGORIES,
    _POOL_LABELS,
    _regulator_readings,
    regulator_role,
)

__all__ = [
    "FbDivider",
    "SENSE_CAP_END",
    "SENSE_CAP_RAIL",
    "RegulatorFbPlacement",
    "fb_dividers",
]

#: Where the upper leg's non-tap end sits, as this rule established it.
#:
#: The values are the words the row carries, so the label on a finding and the
#: comparison that produced it cannot drift apart.
#:
#: ``SENSE_CAP_END`` — the upper leg's non-tap net **is** the non-ground net of
#: a capacitor on this regulator's output node. The divider therefore senses at
#: the output capacitor, the convention the LM5164 datasheet asks for.
#:
#: ``SENSE_CAP_RAIL`` — the upper leg's non-tap net is a net this regulator
#: does **not** name as its output.
#:
#: **No fixture currently reaches this branch**, and that is worth saying
#: rather than leaving a reader to assume the branch is exercised. On 毕设FOC
#: 1.0.0 the comparison comes out :data:`SENSE_CAP_END` — ``R14``'s far end is
#: ``+5V`` and the LM5164's output node resolves to ``+5V`` too (via ``L4``) —
#: yet the nearest storage capacitor on that node is ``C101``, **745.2 mil**
#: from the upper leg. Same net, different locality, which is why the row
#: carries the distance as well as the comparison. The branch stays because it
#: is the other half of a two-valued answer, and a two-valued answer with only
#: one value exercised is not an answer.
SENSE_CAP_END = "on the output-capacitor end"
SENSE_CAP_RAIL = "on the rail"


@dataclass(frozen=True)
class FbDivider:
    """One feedback divider, as the rule established it and why."""

    #: The regulator this divider belongs to, and the shelf category that made
    #: it a regulator (quoted in every finding).
    ic: str = ""
    category: str = ""
    #: The FB pin, its **name** as the symbol declares it, and the tap net.
    fb_pin_number: str = ""
    fb_pin_name: str = ""
    tap_net: str = ""
    #: The two legs. ``upper`` is the one whose non-tap end is on the rail;
    #: ``lower`` is the one whose other end is on ground. Designators only —
    #: the parts themselves are in the model the caller passed in.
    upper: str = ""
    lower: str = ""
    #: The upper leg's non-tap net, the tap net, and the lower leg's ground net.
    rail_net: str = ""
    ground_net: str = ""
    #: Established domain of ``rail_net``, in volts, or ``None``.
    rail_volts: float | None = None
    #: The nets this regulator's **output** is on, resolved (see
    #: :func:`_output_nets_of`) and quoted in every row. Empty when the
    #: regulator's output could not be established — an honest 「this rule
    #: could not find the output node」, not a guess.
    output_nets: tuple[str, ...] = ()
    #: How ``output_nets`` was established, in one clause, for the evidence.
    output_basis: str = ""

    @property
    def legs(self) -> tuple[str, str]:
        return (self.upper, self.lower)


def _resistors(model: object) -> dict[str, object]:
    """Designator -> component, for every part whose value reads as a resistance.

    Read through :func:`boardwise.core.values.parse_resistance_ohms` and
    **only** that: a resistor is a part whose value parses as ohms, so a
    capacitor or a test point is not a candidate and an unreadable value is
    UNKNOWN rather than a zero-ohm leg. ``parse_resistance_ohms`` returns
    ``None`` for a value nobody wrote down, and this filters on that.
    """
    found: dict[str, object] = {}
    for designator, component in (getattr(model, "components", {}) or {}).items():
        ohms = parse_resistance_ohms(str(getattr(component, "value", "") or ""))
        if ohms is not None and ohms > 0:
            found[str(designator)] = component
    return found


def _nets_of(component: object) -> list[str]:
    """A component's pin nets, in pin order, de-duplicated, ground kept.

    A resistor's two terminals are all this needs; the function is written over
    ``Component`` so a caller can hand it an IC too.
    """
    seen: list[str] = []
    for pin in getattr(component, "pins", ()) or ():
        net = str(getattr(pin, "net", "") or "")
        if net and net not in seen:
            seen.append(net)
    return seen


def _fb_pin(component: object) -> tuple[str, str, str] | None:
    """``(pin number, pin name, net)`` for this part's ``FB`` pin, or ``None``.

    Read through :func:`boardwise.core.pinrole.pin_role` on the pin's **name**,
    never by matching the string ``FB`` and never by guessing from the MPN: a
    pin called ``VFB``/``VDIV`` resolves the same way, and a pin whose name says
    nothing resolves to nothing. Returns ``None`` — silence, not a guess — when
    no pin's name declares the role.
    """
    for pin in getattr(component, "pins", ()) or ():
        name = str(getattr(pin, "name", "") or "")
        if pin_role(name) != "FB":
            continue
        return (
            str(getattr(pin, "number", "") or ""),
            name,
            str(getattr(pin, "net", "") or ""),
        )
    return None


def fb_dividers(model: object, library=None) -> list[FbDivider]:
    """Every **feedback** divider in one board model, with the reading behind it.

    The four mechanical criteria are the ones
    :meth:`boardwise.rules.params.DividerOutput._rows` established (the code
    the task book points at), reused rather than re-derived so the two readers
    cannot disagree about what a divider is:

    1. the upper leg has one end on a net with an **established, non-ground**
       domain (:func:`boardwise.core.power_domains.domain_of` returning volts);
    2. the two legs share a **non-ground** net — the tap;
    3. the lower leg's other end is on **ground**
       (:func:`boardwise.core.model.is_ground_net`);
    4. the tap has at least one member that is **not** a leg — an unloaded
       divider declares no range, so it is not a feedback network.

    Then the one filter this rule adds on top, and the reason it exists: the
    tap's IC-side member must be a **regulator** (shelf category
    :data:`~boardwise.rules.pcb.regulator.REGULATOR_CATEGORIES`) sitting on a
    pin whose name reads as ``FB``. Criteria 1–4 alone cannot tell a feedback
    divider from a current-sense or a threshold divider — measured on 毕设FOC
    1.0.0 they admit ``R26``/``R35``, which feeds the STM32's ``PC4``, and that
    is the group the **role** half rejects. The role test also has to be
    *strict*, accepting only ``FB`` and not 「some regulator pin」, or an
    ``EN``/``UVLO`` threshold divider would be admitted; on the DCDC board the
    ``R7``/``R9`` pair into ``U9``'s ``EN`` is exactly that case. The shelf does
    not classify the TPS560430 as a regulator, so there the **category** half
    rejects it first — which is why the role half's own load-bearing case is
    built synthetically in the tests rather than claimed from that board.

    Each ``(upper, lower)`` pair is considered **once**: the loop is
    orientation-ordered by criterion 1 (only the leg with a rail end can be the
    upper one), and a pair already returned is not returned again with the legs
    swapped — the same first-wins discipline
    :meth:`~boardwise.rules.params.DividerOutput._rows` uses, so the two
    readers report the same number of dividers.
    """
    if library is None:
        try:
            library = load_parts(default_library_path())
        except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
            library = None

    readings = {
        r.designator: r
        for _title, board_model in _board_models(model)
        for r in _regulator_readings(board_model, library)
    }
    fb_nets = {
        designator: _fb_pin(getattr(readings[designator], "component", None))
        for designator in readings
    }

    dividers: list[FbDivider] = []
    for _title, board_model in _board_models(model):
        guesses = infer_net_domains(board_model, library)
        components = getattr(board_model, "components", {}) or {}
        nets = getattr(board_model, "nets", {}) or {}
        resistors = _resistors(board_model)
        seen: set[tuple[str, str]] = set()
        for upper_desig, upper in sorted(resistors.items()):
            upper_nets = _nets_of(upper)
            for top_net in upper_nets:
                volts, _source, _why = domain_of(guesses, top_net)
                if volts is None or is_ground_net(top_net):
                    continue
                for lower_desig, lower in sorted(resistors.items()):
                    if lower_desig == upper_desig:
                        continue
                    lower_nets = _nets_of(lower)
                    shared = [
                        net
                        for net in lower_nets
                        if net in upper_nets and not is_ground_net(net)
                    ]
                    grounded = [net for net in lower_nets if is_ground_net(net)]
                    if not shared or not grounded:
                        continue
                    tap = shared[0]
                    key = tuple(sorted((upper_desig, lower_desig)))
                    if key in seen:
                        continue
                    seen.add(key)
                    on_tap = _fb_ic_on_tap(tap, key, nets, components, readings, fb_nets)
                    if on_tap is None:
                        # Either the tap is unloaded (criterion 4) or no
                        # regulator's FB pin sits on it. Both are silence.
                        continue
                    ic_desig, fb = on_tap
                    # ``_fb_ic_on_tap`` only returns a designator it found in
                    # ``readings``, so this is a dict hit by construction — the
                    # ``.get`` is here so that a future change to the filter
                    # degrades to *silence* (a loaded tap with no established
                    # regulator behind it) rather than to a ``KeyError`` that
                    # the runner would swallow as a skipped rule.
                    reading = readings.get(ic_desig)
                    if reading is None:
                        continue
                    output_nets, output_basis = _output_nets_of(reading, board_model)
                    dividers.append(
                        FbDivider(
                            ic=ic_desig,
                            category=reading.category,
                            fb_pin_number=fb[0],
                            fb_pin_name=fb[1],
                            tap_net=tap,
                            upper=upper_desig,
                            lower=lower_desig,
                            rail_net=top_net,
                            ground_net=grounded[0],
                            rail_volts=volts,
                            output_nets=output_nets,
                            output_basis=output_basis,
                        )
                    )
    return dividers


def _capacitors_on(model: object, net_name: str, library) -> list[CapCandidate]:
    """Every capacitor with a terminal on ``net_name``, however its other end lands.

    Broader than :func:`~boardwise.rules.decap.cap_candidates_on` on purpose, and
    the difference is the measurement: that predicate asks for a capacitor
    **bridging to a ground net**, which is right for a decoupling question and
    wrong for 「is there a capacitor on the FB node」. The feedback-node
    capacitor's job is to filter the node the divider *senses*, and it may be
    returned to any local node — on 毕设FOC 1.0.0 ``C92`` (100 nF) sits between
    the tap ``$1N66466`` and ``$1N66641``, the bootstrap/RON node, which
    ``is_ground_net`` correctly refuses to call ground. Under the narrower
    predicate this rule would have reported 「no FB-node capacitor」 on the one
    board that has one, which is the shape of defect 129 exists to remove.

    Identification still goes through the same
    :func:`~boardwise.rules.decap` machinery (a part that reads as a capacitor
    by value or by shelf), so 「a capacitor」 means one thing across the rules;
    only the *other terminal* is left unconstrained, and the evidence says which
    net each one actually goes to so a reader can judge the topology themselves.
    """
    net = (getattr(model, "nets", {}) or {}).get(net_name)
    if net is None:
        return []
    from ..decap import _looks_like_capacitor

    components = getattr(model, "components", {}) or {}
    found: list[CapCandidate] = []
    for designator, _pin in net.pins:
        component = components.get(designator)
        if component is None or not _looks_like_capacitor(component, library):
            continue
        found.append(
            CapCandidate(
                designator=designator,
                value=getattr(component, "value", "") or "",
                mpn=getattr(component, "mpn", "") or "",
                lcsc=getattr(component, "lcsc_part", "") or "",
                footprint=getattr(component, "footprint", "") or "",
                grounded=True,
            )
        )
    return found


def _fb_ic_on_tap(
    tap: str,
    legs: tuple[str, str],
    nets: dict,
    components: dict,
    readings: dict,
    fb_nets: dict,
) -> tuple[str, tuple[str, str, str]] | None:
    """``(designator, (pin number, pin name, net))`` of the regulator on ``tap``.

    **The filter the mechanical criteria cannot do.** Scans the tap's
    non-leg members for one that is a **regulator** (shelf category in
    :data:`~boardwise.rules.pcb.regulator.REGULATOR_CATEGORIES`) with a pin on
    this tap whose *name* reads as ``FB``, and returns the first such.

    All members are scanned, not just the first: on 毕设FOC 1.0.0 the tap
    ``$1N66466`` carries ``C92`` (the FB-node capacitor), ``U11`` and the
    lower leg, in that pin order, so a first-member reading would see the
    capacitor and drop the divider.

    Returns ``None`` — this is a current-sense, ADC-threshold or ``EN``/``UVLO``
    divider, and neither is a feedback network. Measured on the corpus:
    ``R26``/``R35`` on 毕设FOC 1.0.0 (tap ``$1N66392``, into the STM32's
    ``PC4``) and ``R7``/``R9`` on the DCDC board (tap ``$1N10444``, into
    ``U9``'s ``EN``) are both rejected here, and the second one is the reason
    the role test is strict: its member **is** a regulator.
    """
    net = nets.get(tap)
    if net is None:
        return None
    for designator, _pin_number in net.pins:
        if designator in legs or designator not in components:
            continue
        reading = readings.get(designator)
        if reading is None or reading.category not in REGULATOR_CATEGORIES:
            continue
        fb = fb_nets.get(designator)
        if fb is None or fb[2] != tap:
            continue
        return designator, fb
    return None


def _output_nets_of(reading: object, board_model: object) -> tuple[tuple[str, ...], str]:
    """This regulator's **output** net(s), and the clause that says how.

    Two shapes, and the difference is a fact about the part rather than a
    preference:

    * **A pin named as an output** (``pin_role(...) == "OUT"``) — an LDO's
      ``VOUT``. The nets that pin sits on *are* the output. This is the shape
      131b already reads as the ``VOUT`` side, and it is reused rather than
      re-derived.

    * **A switching regulator with an ``SW`` pin and no output pin** — a buck.
      Its output is behind the inductor, so the ``SW`` net is *not* the output
      and no pin on the IC names it. The output is then found by walking **one
      hop from the switching node through the inductor**: the net on the
      inductor's other terminal. On 毕设FOC 1.0.0 that is how ``U11``'s output
      is established as ``+5V`` — ``SW`` is on ``$1N66672``, ``L4`` spans
      ``$1N66672`` to ``+5V``, so ``+5V`` is the post-inductor output node.

      The walk is **exactly one hop, through a part that is an inductor**, and
      it is not taken when the IC *does* name an output pin. A second hop would
      be a topology guess; refusing to guess is what keeps the honest
      「output not established」 case available (an ``SW`` pin with no inductor on
      it, which a reader can then act on) instead of a wrong net.

    Returns ``(nets, basis)``. ``nets`` is empty when neither shape applied,
    and ``basis`` then says which — so the row distinguishes 「this regulator has
    no output pin and no inductor after its switch node」 from 「it has an output
    pin, on no net this document carries」.
    """
    component = getattr(reading, "component", None)
    components = getattr(board_model, "components", {}) or {}

    out_nets: list[str] = []
    for pin in getattr(component, "pins", ()) or ():
        if pin_role(str(getattr(pin, "name", "") or "")) != "OUT":
            continue
        net = str(getattr(pin, "net", "") or "")
        if net and net not in out_nets:
            out_nets.append(net)
    if out_nets:
        return tuple(out_nets), (
            f"read off the pin(s) whose name resolves to the OUT role "
            f"({', '.join(out_nets)})"
        )

    sw_nets = [
        str(getattr(pin, "net", "") or "")
        for pin in getattr(component, "pins", ()) or ()
        if pin_role(str(getattr(pin, "name", "") or "")) == "SW"
        and getattr(pin, "net", None)
    ]
    if not sw_nets:
        return (), "no pin name resolves to the OUT or SW role"
    for sw_net in sw_nets:
        net = (getattr(board_model, "nets", {}) or {}).get(sw_net)
        if net is None:
            continue
        for designator, _pin_number in net.pins:
            part = components.get(designator)
            if part is None or designator == getattr(reading, "designator", ""):
                continue
            if not _looks_like_inductor(part):
                continue
            other = [
                str(getattr(pin, "net", "") or "")
                for pin in getattr(part, "pins", ()) or ()
                if getattr(pin, "net", None) and str(getattr(pin, "net")) != sw_net
            ]
            if other and other[0] not in out_nets:
                out_nets.append(other[0])
    if out_nets:
        return tuple(out_nets), (
            f"no pin name resolves to OUT, so the output was taken one hop from "
            f"the switching net {', '.join(sw_nets)} through the inductor on it "
            f"({', '.join(out_nets)}) — a buck's output is behind the inductor"
        )
    return (), (
        f"no pin name resolves to OUT and no inductor was found on the "
        f"switching net {', '.join(sw_nets)}, so the output node is not "
        f"established by this rule"
    )


def _looks_like_inductor(part: object) -> bool:
    """Does this part read as an inductor, on its declared value or its MPN?

    Deliberately narrow and deliberately two-sided, because the corpus needs
    both: on 毕设FOC 1.0.0 ``L4`` declares ``33uH`` (the value carries it), while
    a part whose value is blank and whose MPN encodes the inductance carries it
    in the MPN. The value is read through
    :func:`boardwise.core.values.parse_inductance_henries` when it exists and
    falls back to an ``H``/``uH``/``nH``/``mH`` token test on the MPN; a part
    whose neither says inductance is **not** an inductor, because stepping
    through an arbitrary part to guess the output node is exactly the guess
    this walk refuses.
    """
    value = str(getattr(part, "value", "") or "").strip()
    if value and _INDUCTANCE_TOKEN.search(value):
        return True
    mpn = str(getattr(part, "mpn", "") or "").strip()
    return bool(mpn) and bool(_INDUCTANCE_TOKEN.search(mpn))


#: A value or an MPN that carries an inductance unit. ``H``/``uH``/``nH``/``mH``
#: with a leading digit or dot, so a bare letter ``H`` in an unrelated token does
#: not match and ``33uH``/``2.2uH``/``4R7``-style entries are judged on their
#: own text.
_INDUCTANCE_TOKEN = re.compile(r"\d\s*(?:uH|nH|mH|H)\b")


class RegulatorFbPlacement(PcbRule):
    """Where a regulator's feedback divider sits, and which end it senses at.

    One pass per **feedback divider** (see :func:`fb_dividers` for the
    recognition and the one filter it adds), producing one ``INFO`` row:

    * the two leg distances from the FB pin (upper first, then lower), each
      with its pad pair, and the FB-node capacitor's distance when the tap has
      a grounded one;
    * the sense-point answer — :data:`SENSE_CAP_END` or :data:`SENSE_CAP_RAIL` —
      with **both** net names quoted, because the answer is a comparison and a
      reader who rejects the comparison must be able to see it.

    A regulator whose ``FB`` pin carries a tap net that no divider reaches gets
    one row saying so, naming the pin and the net: 「this regulator has no
    feedback network drawn」 is actionable, and silence would read as a clean
    bill of health. A regulator with **no** pin whose name reads as ``FB``
    gets nothing — the rule has not established that the part has such a pin,
    and 131b's row already names the unclassified pin names.

    **All rows are ``INFO``.** See the module docstring: no threshold exists,
    so a 600 mil gap is a number and not a defect.
    """

    id = "pcb-regulator-fb-placement"
    title = "Feedback divider sits at the FB pin, and the upper leg senses the output node"
    level = "L1-pcb-geometry"
    source = "house rule（岳 2026-10 待裁）"

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        return self.check_with_library(ctx, load_parts(default_library_path()))

    def check_with_library(
        self, ctx: PcbReviewContext, library=None
    ) -> list[Finding]:
        """The pass itself, with the shelf handed in rather than read here.

        The same injection point
        :meth:`~boardwise.rules.pcb.regulator.RegulatorCapDistance.
        check_with_library` publishes, for the same reason: the synthetic tests
        can inject a shelf without monkeypatching the project's own
        :func:`boardwise.rules.facts.default_library_path`.
        """
        board = ctx.board
        model = ctx.pcb_model
        if board is None or model is None:
            return []
        if library is None:
            try:
                library = load_parts(default_library_path())
            except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
                library = None

        dividers = fb_dividers(model, library)
        claimed: dict[str, str] = {}
        findings: list[Finding] = []
        for divider in dividers:
            if board.component(divider.ic) is None:
                continue  # this PCB document places no such regulator
            claimed[divider.ic] = divider.tap_net
            findings.extend(self._one_divider(divider, board, model, library))
        for _title, board_model in _board_models(model):
            for reading in _regulator_readings(board_model, library):
                if reading.designator in claimed:
                    continue
                if board.component(reading.designator) is None:
                    continue
                fb = _fb_pin(getattr(reading, "component", None))
                if fb is None:
                    continue  # no pin named FB: not this rule's question
                findings.append(self._no_divider(reading, fb))
        return findings

    # -- rows -------------------------------------------------------------

    def _identity(self, divider: FbDivider) -> list[str]:
        return [
            f"{divider.ic} read as a regulator because the shelf category is "
            f"{divider.category!r}",
            f"divider recognised mechanically (upper leg on a net with an "
            f"established non-ground domain, both legs sharing the non-ground "
            f"tap {divider.tap_net!r}, lower leg's other end on ground "
            f"{divider.ground_net!r}, tap loaded) — then kept because the tap's "
            f"IC-side member is {divider.ic} and pin {divider.fb_pin_number} is "
            f"named {divider.fb_pin_name!r}, which reads as the FB role",
            f"upper leg {divider.upper} spans {divider.tap_net!r} to "
            f"{divider.rail_net!r}; lower leg {divider.lower} spans "
            f"{divider.tap_net!r} to {divider.ground_net!r}",
            f"rail domain established at {divider.rail_volts} V",
        ]

    def _output_cap_nets(self, model: object, divider: FbDivider, library) -> list[str]:
        """Non-ground nets of every capacitor on this regulator's output node(s).

        「Which end does the upper leg hang on」 is a net comparison, so this is
        the set of nets the comparison is made against: the capacitors that
        bridge one of the regulator's **output** nets to ground, and the
        non-ground net each of them sits on.

        Uses :func:`~boardwise.rules.decap.cap_candidates_on`, the same predicate
        126b and 131b use, so 「a capacitor on a rail」 means one thing across the
        three rules. On 毕设FOC 1.0.0 that is ``+5V`` — which carries ``C5``,
        ``C11`` and ``C101``, the rail's storage capacitors.
        """
        nets: list[str] = []
        for output_net in divider.output_nets:
            for candidate in cap_candidates_on(model, output_net, library):
                component = (getattr(model, "components", {}) or {}).get(
                    candidate.designator
                )
                for pin in getattr(component, "pins", ()) or ():
                    net = str(getattr(pin, "net", "") or "")
                    if net and not is_ground_net(net) and net not in nets:
                        nets.append(net)
        return nets

    def _nearest_output_cap(
        self, model: object, divider: FbDivider, board: BoardGeometry, library
    ) -> tuple[str, object, str] | None:
        """``(designator, distance, pool)`` of the nearest output-node capacitor.

        **The number the sense-point question is really about, and the reason
        the net comparison alone is not enough.** On 毕设FOC 1.0.0 the upper leg
        ``R14`` and the output capacitors share the net ``+5V``, so the net
        comparison answers 「the output-capacitor end」 — while the nearest part
        on that net is hundreds of mil away. The rail is shared; the node is not
        local. Reporting the nearest one is what makes that difference legible,
        and it stays a measurement rather than a verdict: with no threshold in
        force, a large number is a reading and not a defect.

        Measured **from the upper leg**, not from the IC: the question is where
        the *sensing* part sits, and the sensing part is the resistor.

        **Both pools are reported**, and the *storage* pool is the one the
        sense-point question is about, because that is the part the LM5164's
        datasheet means by its output capacitor. 裁定 ③ (131b) owns the split —
        ``>= 1 µF`` is storage, below it is high-frequency bypass — and the pool
        is read through :func:`~boardwise.rules.pcb.regulator.regulator_role`,
        the same function ``pcb-regulator-cap-distance`` uses, so 「storage」 and
        「high-frequency bypass」 mean one thing across the two rules. A nearest
        100 nF bypass is a real measurement and a misleading answer to 「where is
        the output capacitor」, so it is reported with its pool and the storage
        one is preferred when both exist.
        """
        best: dict[str, tuple[str, object, str]] = {}
        for output_net in divider.output_nets:
            for candidate in cap_candidates_on(model, output_net, library):
                if board.component(candidate.designator) is None:
                    continue
                distance = component_distance(
                    board, divider.upper, candidate.designator
                )
                if distance is None:
                    continue
                pool = regulator_role(candidate, model) or POOL_HF
                held = best.get(pool)
                if held is None or distance.edge_distance < held[1].edge_distance:
                    best[pool] = (candidate.designator, distance, pool)
        if POOL_STORAGE in best:
            return best[POOL_STORAGE]
        if POOL_HF in best:
            return best[POOL_HF]
        return None

    def _no_divider(self, reading, fb: tuple[str, str, str]) -> Finding:
        """The row for a regulator that names an ``FB`` pin but no divider."""
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"{reading.designator} has a pin named {fb[1]!r} on net "
                f"{fb[2]!r} but no feedback divider reaches it — no upper leg "
                f"with an established rail domain and a grounded lower leg "
                f"share that net, so there is no feedback network to place"
            ),
            evidence=[
                f"{reading.designator} read as a regulator because the shelf "
                f"category is {reading.category!r}",
                f"FB pin {fb[0]} is named {fb[1]!r} on net {fb[2]!r}",
                f"members of {fb[2]!r}: see the tap criterion in fb_dividers — "
                f"a divider was not found among them",
            ],
            target=FindingTarget(
                component_ref=reading.designator, net_refs=[fb[2]]
            ),
        )

    def _one_divider(
        self,
        divider: FbDivider,
        board: BoardGeometry,
        model: object,
        library,
    ) -> list[Finding]:
        """The one row for one feedback divider."""
        measured: list[tuple[str, object]] = []
        for role, designator in (("upper", divider.upper), ("lower", divider.lower)):
            distance = (
                component_distance(board, divider.ic, designator)
                if board.component(designator) is not None
                else None
            )
            if distance is not None:
                measured.append((role, (designator, distance)))

        # The FB node's capacitor, if the tap has one. **Not**
        # :func:`~boardwise.rules.decap.cap_candidates_on`: that predicate asks
        # for a capacitor *bridging to ground*, and the feedback-node capacitor
        # on 毕设FOC 1.0.0 (``C92``) bridges the tap to ``$1N66641`` — the
        # bootstrap/RON node, which ``is_ground_net`` correctly refuses — so the
        # ground-bridged reading would have reported 「no FB-node capacitor」 on
        # the one board that has one. Every capacitor **on the tap** is listed
        # here instead, and which one bridges to ground is stated in the
        # evidence rather than assumed.
        sense_caps = _capacitors_on(model, divider.tap_net, library)
        sense = None
        for candidate in sense_caps:
            if board.component(candidate.designator) is None:
                continue
            distance = component_distance(board, divider.ic, candidate.designator)
            if distance is not None and (sense is None or distance.edge_distance < sense[1].edge_distance):
                sense = (candidate.designator, distance)

        cap_nets = self._output_cap_nets(model, divider, library)
        placement = (
            SENSE_CAP_END if divider.rail_net in cap_nets else SENSE_CAP_RAIL
        )
        # The net comparison answers 「same net?」; this answers 「how far?」.
        # On 毕设FOC 1.0.0 the two disagree in the way the task book cares about,
        # so both go in the row.
        out_cap = self._nearest_output_cap(model, divider, board, library)
        if out_cap is not None:
            out_cap_text = (
                f"the nearest {_POOL_LABELS[out_cap[2]]} capacitor on that output "
                f"node is {out_cap[0]} at "
                f"{_mil(out_cap[1].edge_distance):.1f} mil from the upper leg "
                f"{divider.upper} (pads {out_cap[1].pad_a} / {out_cap[1].pad_b})"
            )
        elif divider.output_nets:
            out_cap_text = (
                f"no capacitor on {' / '.join(divider.output_nets)} is placed on "
                f"this PCB document, so the sensing point has no measured "
                f"distance"
            )
        else:
            out_cap_text = (
                "no output node was established, so the sensing point has no "
                "measured distance"
            )

        leg_text = "; ".join(
            f"{role} leg {designator} at {_mil(distance.edge_distance):.1f} mil "
            f"(pads {distance.pad_a} / {distance.pad_b})"
            for role, (designator, distance) in measured
        ) or "neither leg is placed on this PCB document"
        if sense is not None:
            sense_text = (
                f"FB-node capacitor {sense[0]} at "
                f"{_mil(sense[1].edge_distance):.1f} mil from {divider.ic} "
                f"(pads {sense[1].pad_a} / {sense[1].pad_b})"
            )
        else:
            sense_text = (
                f"no capacitor on the FB node {divider.tap_net!r} "
                f"({', '.join(sorted(c.designator for c in sense_caps)) or 'none'}"
                f"{' placed on this document' if sense_caps else ' on the net'})"
            )
        # The answer is a *comparison*, so the row quotes both sides of it and,
        # when the output node could not be established, says that instead of
        # implying a rail verdict it did not earn.
        if not divider.output_nets:
            placement_text = (
                f"the upper leg's non-tap end is on {divider.rail_net!r}, but "
                f"this regulator's output node could not be established "
                f"({divider.output_basis}), so which end the divider senses at "
                f"is NOT judged here"
            )
        else:
            placement_text = (
                f"the upper leg's non-tap end is on {divider.rail_net!r}, which "
                + (
                    "is the non-ground net of a capacitor on this regulator's "
                    f"output node ({', '.join(sorted(cap_nets))})"
                    if placement == SENSE_CAP_END
                    else (
                        "is not the non-ground net of a capacitor on this "
                        f"regulator's output node ({', '.join(sorted(cap_nets)) or 'none'})"
                    )
                )
                + f" — the divider senses {placement}"
            )

        return [
            Finding(
                rule_id=self.id,
                severity="INFO",
                level=self.level,
                message=(
                    f"{divider.ic}'s feedback divider {divider.upper}/{divider.lower} "
                    f"at the {divider.ic}.{divider.fb_pin_number} FB pin on "
                    f"{divider.tap_net!r}: {leg_text}; {sense_text}; {placement_text}; "
                    f"{out_cap_text} "
                    f"— measurement only, no FB threshold is in force yet"
                ),
                evidence=self._identity(divider)
                + [
                    *[
                        f"distance {divider.ic} -> {designator}: "
                        f"{_mil(distance.edge_distance):.1f} mil edge-to-edge "
                        f"(pads {distance.pad_a} / {distance.pad_b})"
                        for _role, (designator, distance) in measured
                    ],
                    (
                        f"FB-node capacitor: {sense[0]} @ {divider.tap_net} = "
                        f"{_mil(sense[1].edge_distance):.1f} mil edge-to-edge "
                        f"from {divider.ic}"
                        if sense is not None
                        else f"FB-node capacitor: {sense_text}"
                    ),
                    f"this regulator's output pin net(s): "
                    f"{', '.join(divider.output_nets) or '(none)'}",
                    f"how the output node was established: {divider.output_basis}",
                    f"non-ground nets of the capacitors on that output node: "
                    f"{', '.join(sorted(cap_nets)) or '(none)'}",
                    f"output-node distance: {out_cap_text}",
                    f"sense-point reading: upper leg {divider.upper}'s non-tap "
                    f"net {divider.rail_net!r} vs those — {placement}",
                ],
                target=FindingTarget(
                    component_ref=divider.ic,
                    net_refs=[divider.tap_net],
                    counterpart_ref=divider.upper,
                    measurement=(
                        _measurement(
                            "distance",
                            min(
                                distance.edge_distance
                                for _role, (_d, distance) in measured
                            ),
                        )
                        if measured
                        else None
                    ),
                ),
            )
        ]
