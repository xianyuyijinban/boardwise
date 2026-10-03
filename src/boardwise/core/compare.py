"""Golden-vs-candidate design comparison — the referee for AI-drawn boards.

Compares two :class:`boardwise.core.model.DesignModel` instances at three
strictness levels (task 005):

1. **component level** — designator sets, then ``footprint`` / ``value`` /
   ``lcsc`` for common components;
2. **net level** — net-name sets, then per-net member sets;
3. **pin level** — the core: for common components, every pin's net mapping.

Normalisation rules are fixed here on purpose (they are the contract) — but the
*implementation* of the value rule is not this module's own, it is the one value
parser the repository has (071 §2, "one verdict has one implementation"):

- **value**: case-insensitive; engineering-notation equality when both sides
  parse to the same quantity (``10k`` == ``10K`` == ``10000``), read by
  :func:`boardwise.core.values.parse_resistance_ohms` /
  :func:`~boardwise.core.values.parse_capacitance_farads` and compared with
  :func:`math.isclose`, so the trade's mid-letter spelling is inherited
  (``4K7`` == ``4700``, ``4u7`` == ``4.7uF``; issue #51) and ``0.1uF`` no
  longer differs from ``100nF`` on a float's last bit (issue #39). The kind
  travels with the number — ``100Ω`` and ``100nF`` are two parts, not one — and
  a value neither parser reads (a multi-token ``472M 1KV``, ``22u``) degrades
  to string comparison, which is 005's contract: unreadable is not the same as
  equal, and a pass-by-silence here would clear a design that differs.
- **designator / net name / pin number**: exact strings, case-sensitive
  (``1`` and ``01`` are different pins).
- **footprint / lcsc**: exact strings after trimming.

The report is **strict**: every difference, in either direction, is a difference.
A *subset* reading ("the candidate must still contain the golden") is not a
property of this module — it belongs to the caller that needs it
(``boardwise persistence --baseline``), which splits the two directions with
:attr:`Difference.is_extra` rather than matching the detail prose itself.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from boardwise.core.model import DesignModel, Net

from .values import parse_capacitance_farads, parse_resistance_ohms

#: Difference levels, in report order.
COMPONENT_LEVEL = "component"
NET_LEVEL = "net"
PIN_LEVEL = "pin"

#: A part whose library symbol was redrawn and renumbered (see
#: :mod:`boardwise.core.verify`). Imported as a literal to keep this module
#: free of a compare -> verify import cycle; they are contractually equal.
DRIFTED_KIND = "drifted"


@dataclass
class Difference:
    """One difference, human-readable on every field."""

    level: str
    subject: str
    detail: str
    golden: str
    candidate: str

    def render(self) -> str:
        return (
            f"[{self.level}] {self.subject}: {self.detail}; "
            f"golden={self.golden!r} candidate={self.candidate!r}"
        )

    @property
    def is_extra(self) -> bool:
        """The candidate holds this and the golden does not — additive content.

        A **subset** comparison (``boardwise persistence --baseline``: "is what I
        snapshotted still there?") tolerates exactly this direction, because a
        project that grew after the snapshot is not a failed save. Every other
        detail — a component/net/pin/member missing on the candidate side, or a
        field that came back different — is a loss or a change, and no subset
        reading makes it a pass. Kept next to the details themselves so the
        direction is classified where the strings are written, never by a caller
        matching prose of its own.
        """
        return self.detail in EXTRA_DETAILS


#: The detail strings whose direction is "candidate only" — see
#: :attr:`Difference.is_extra`. Every ``Difference`` this module constructs uses
#: one of the strings in this file, so the set is exhaustive by construction;
#: ``tests/test_persistence.py`` pins that.
EXTRA_DETAILS = frozenset({
    "component extra in candidate",
    "net extra in candidate",
    "member extra in candidate",
    "pin extra in candidate",
})


@dataclass
class ComparisonReport:
    """Grouped differences; empty everywhere means the designs match."""

    component_differences: list[Difference] = field(default_factory=list)
    net_differences: list[Difference] = field(default_factory=list)
    pin_differences: list[Difference] = field(default_factory=list)

    @property
    def differences(self) -> list[Difference]:
        """All three levels as one list, in report order."""
        return [
            *self.component_differences,
            *self.net_differences,
            *self.pin_differences,
        ]

    @property
    def total(self) -> int:
        return (
            len(self.component_differences)
            + len(self.net_differences)
            + len(self.pin_differences)
        )

    @property
    def is_empty(self) -> bool:
        return self.total == 0

    def render(self) -> str:
        lines = [d.render() for d in self.component_differences]
        lines += [d.render() for d in self.net_differences]
        lines += [d.render() for d in self.pin_differences]
        lines.append(
            f"total: {self.total} difference(s) "
            f"(component {len(self.component_differences)}, "
            f"net {len(self.net_differences)}, "
            f"pin {len(self.pin_differences)})"
        )
        return "\n".join(lines)

    def to_jsonable(self) -> dict:
        def dump(diffs: list[Difference]) -> list[dict]:
            return [
                {
                    "level": d.level,
                    "subject": d.subject,
                    "detail": d.detail,
                    "golden": d.golden,
                    "candidate": d.candidate,
                }
                for d in diffs
            ]

        return {
            "component": dump(self.component_differences),
            "net": dump(self.net_differences),
            "pin": dump(self.pin_differences),
            "total": self.total,
        }


# --------------------------------------------------------------------------
# value normalisation
# --------------------------------------------------------------------------


def _quantity(text: str) -> tuple[str, float] | None:
    """``(kind, amount)`` when ``text`` is a value this repository reads.

    The parsing is delegated, not repeated: this module used to carry its own
    grammar (``_QUANTITY_RE`` and friends) and that copy is what let two bugs
    this repository had already fixed elsewhere reach the ``compare`` verdict —
    it did not read the trade's mid-letter spelling (``4K7``, ``4u7``), so two
    designs stating the *same* part were reported as different, and it decided
    equality with ``==``, so ``0.1uF`` (``1e-07``) differed from ``100nF``
    (``1.0000000000000001e-07``). Issues #23 and #39 fixed the authoritative
    parsers; compare was the copy that did not get the news (issue #51,
    071 §2 "one verdict has one implementation").

    The kind travels with the number, as it does in
    :func:`boardwise.engines.bom._quantity` — the two grammars do not share a
    unit, and ``100Ω`` next to ``100nF`` is two different parts, not one value
    spelled two ways.

    The parsers are imported at module level from the sibling
    :mod:`boardwise.core.values`, which is where they live since 083 moved them
    down out of ``rules/``. A sibling import cannot cycle, so there is nothing
    here to defer: the deferred-import shape 081 used in this package was for
    a *different* layer, and the layering test (``tests/test_layer_rules.py``)
    reads imports at any depth anyway.
    """
    ohms = parse_resistance_ohms(text)
    if ohms is not None:
        return "resistance", ohms
    farads = parse_capacitance_farads(text)
    if farads is not None:
        return "capacitance", farads
    return None


def values_equal(golden: str, candidate: str) -> bool:
    """Compare two component values under the task-005 normalisation rules.

    Three steps, in this order, and the order is the contract:

    1. the same string is the same value;
    2. the same string case-folded is the same value (``10k`` / ``10K``) — bom's
       comparison has no such step, but compare's does, so it stays;
    3. both sides read as the *same kind* of quantity → they are the same value
       when :func:`math.isclose` says so, with a relative tolerance because
       ``0.1uF`` and ``100nF`` are one part whose two spellings differ in the
       last bit of a float (issue #39).

    Anything else is not equal. A value the parsers cannot read — a multi-token
    ``472M 1KV``, a bare ``10H``, a ``5.1K`` in a capacitance slot — falls through
    to the string comparison that already said "not equal", which is 005's refusal
    to guess. (A unit-less ``22u`` used to be listed there, and 087 closed it: the
    fraction-free spelling is read, so ``22u`` and ``22uF`` meet at step 3 instead
    of being reported as a difference between two spellings of one part.) Note
    what step 3 does *not* have to do: it no longer needs a list of
    prefixes too ambiguous to trust. A lowercase ``m`` used to be blacklisted
    because the same string means milli on a resistor and micro on an old
    capacitor marking; the dispatch above settles it structurally, because
    ``parse_capacitance_farads`` refuses a value with no farad unit, so ``10m``
    is 10 milliohms and only that.
    """
    g = (golden or "").strip()
    c = (candidate or "").strip()
    if g == c:
        return True
    if g.lower() == c.lower():
        return True  # case-insensitive equality, e.g. ``10k`` vs ``10K``
    left, right = _quantity(g), _quantity(c)
    if left is not None and right is not None and left[0] == right[0]:
        return math.isclose(left[1], right[1], rel_tol=1e-9)
    return False  # degenerate: string comparison already said "not equal"


def compare_models(
    golden: DesignModel,
    candidate: DesignModel,
    pin_maps: "dict[str, Any] | None" = None,
) -> ComparisonReport:
    """Compare two design models at component, net and per-pin level.

    ``pin_maps`` (F4, 006b revision 4) is an optional
    ``designator -> PinMap`` from :mod:`boardwise.core.verify`. When a part's
    library symbol was redrawn and renumbered, its golden pin *numbers* no
    longer address its placed pins — the identity is the pin *name*. Passing
    the map makes the per-pin comparison follow that identity, so a
    renumbered part is compared pin-for-pin instead of producing one phantom
    "pin extra / pin net mapping differs" pair per pin.

    A part whose map is :data:`~boardwise.core.verify.MATCH_DRIFTED` and whose
    mapped pins still disagree is a genuine difference — only the *addressing*
    is translated, never the verdict. Parts without a map keep the old
    number-addresses-number behaviour, so this is exactly backwards
    compatible.
    """
    report = ComparisonReport()

    def _candidate_pin(designator: str, number: str) -> str:
        """The candidate pin number a golden pin number addresses for a part."""
        if pin_maps:
            pin_map = pin_maps.get(designator)
            if pin_map is not None and pin_map.kind == DRIFTED_KIND:
                return pin_map.remap(number)
        return number

    # --- component level -------------------------------------------------
    golden_ids = set(golden.components)
    candidate_ids = set(candidate.components)
    for designator in sorted(golden_ids - candidate_ids):
        report.component_differences.append(
            Difference(COMPONENT_LEVEL, designator, "component missing in candidate", "present", "absent")
        )
    for designator in sorted(candidate_ids - golden_ids):
        report.component_differences.append(
            Difference(COMPONENT_LEVEL, designator, "component extra in candidate", "absent", "present")
        )
    for designator in sorted(golden_ids & candidate_ids):
        g = golden.components[designator]
        c = candidate.components[designator]
        if (g.footprint or "").strip() != (c.footprint or "").strip():
            report.component_differences.append(
                Difference(COMPONENT_LEVEL, designator, "footprint differs", g.footprint, c.footprint)
            )
        if not values_equal(g.value, c.value):
            report.component_differences.append(
                Difference(COMPONENT_LEVEL, designator, "value differs", g.value, c.value)
            )
        if (g.lcsc_part or "").strip() != (c.lcsc_part or "").strip():
            report.component_differences.append(
                Difference(COMPONENT_LEVEL, designator, "lcsc differs", g.lcsc_part, c.lcsc_part)
            )

    # --- net level --------------------------------------------------------
    golden_nets = set(golden.nets)
    candidate_nets = set(candidate.nets)
    for name in sorted(golden_nets - candidate_nets):
        report.net_differences.append(
            Difference(NET_LEVEL, name, "net missing in candidate", "present", "absent")
        )
    for name in sorted(candidate_nets - golden_nets):
        report.net_differences.append(
            Difference(NET_LEVEL, name, "net extra in candidate", "absent", "present")
        )
    for name in sorted(golden_nets & candidate_nets):
        g_members = set(golden.nets[name].pins)
        c_members = set(candidate.nets[name].pins)
        # Translate golden members onto the candidate's addressing first: on a
        # renumbered part, ("USB1","1") and ("USB1","A1B12") are the same pin,
        # and reporting one as missing and the other as extra would be the
        # 28-phantom-difference trap F4 exists to close.
        g_translated = {
            (des, pin_maps[des].remap(num))
            if pin_maps and des in pin_maps and pin_maps[des].kind == DRIFTED_KIND
            else (des, num)
            for des, num in g_members
        }
        for member in sorted(g_translated - c_members):
            report.net_differences.append(
                Difference(NET_LEVEL, name, "member missing in candidate", f"{member[0]}.{member[1]}", "-")
            )
        for member in sorted(c_members - g_translated):
            report.net_differences.append(
                Difference(NET_LEVEL, name, "member extra in candidate", "-", f"{member[0]}.{member[1]}")
            )

    # --- pin level (the core) ---------------------------------------------
    for designator in sorted(golden_ids & candidate_ids):
        g_pins = {p.number: p for p in golden.components[designator].pins}
        c_pins = {p.number: p for p in candidate.components[designator].pins}
        # Which candidate pins the golden's pins address, per the identity map
        # (identity for every part whose symbol still matches).
        addressed = {
            number: _candidate_pin(designator, number) for number in g_pins
        }
        for number in sorted(g_pins):
            g_net = g_pins[number].net
            c_pin = c_pins.get(addressed[number])
            c_net = c_pin.net if c_pin is not None else "<<no such pin>>"
            if (g_net or "") != (c_net or ""):
                report.pin_differences.append(
                    Difference(
                        PIN_LEVEL,
                        f"{designator}.{number}",
                        "pin net mapping differs",
                        g_net or "unconnected",
                        c_net or "unconnected",
                    )
                )
        # A candidate pin is "extra" only when no golden pin addresses it.
        for number in sorted(set(c_pins) - set(addressed.values())):
            report.pin_differences.append(
                Difference(
                    PIN_LEVEL,
                    f"{designator}.{number}",
                    "pin extra in candidate",
                    "-",
                    c_pins[number].net or "unconnected",
                )
            )
    return report


def plan_membership_renames(
    golden_nets: Mapping[str, Net],
    candidate_nets: Mapping[str, Net],
    *,
    translate: Mapping[tuple[str, str], tuple[str, str]] | None = None,
    respect_golden_names: bool = False,
    skipped: list[str] | None = None,
) -> dict[str, str]:
    """Decide which candidate nets take a golden name, and refuse the rest.

    The one decision behind both membership-reconcile paths: a candidate net
    whose *member set* is identical to a golden net's is renamed to the golden
    name, and nothing else is. Returns ``{old candidate name: golden name}`` —
    the plan only; each caller applies it in its own way (immutably in
    :func:`reconcile_names`, in place in
    :func:`boardwise.engines.draw._reconcile_derived_names`).

    Two policy knobs, both explicit because the two callers genuinely differ
    and neither difference is settled here (086):

    * ``translate`` — rewrite a pin's addressing before comparing member sets,
      as ``(designator, placed number) -> (designator, golden number)``. A
      drifted part's placed pins carry pad-name numbers (``A5``), so without
      the translation the same two-member cluster reads different on each side.
      The draw path builds one from its ``pin_maps``; the calibration path
      passes ``None`` because both sides are already in the same addressing.
    * ``respect_golden_names`` — skip a candidate net that already carries a
      golden name. ``True`` for the draw path (a name that exists on the
      golden side is the right one already, and the drawn board carries our
      names explicitly); ``False`` for calibration, which asks "same
      connectivity?" and so lets a name that is *also* a golden name be
      permuted onto the cluster the golden gave that name — the CH340
      geometry has four such nets, cycled, and every rename has to happen.

    A rename whose target name is **already taken** is abandoned, never merged
    and never overwritten (issue #46): the first rename to a name keeps it, a
    second gives up and says so, and a rename onto a name another candidate
    net *keeps* is refused too. A net that is itself being renamed *away* does
    not block it — a cycle of renames is a permutation, and each member of it
    lands on the name the golden gave that cluster. This function is the
    **only** source of the ``skipped`` wording, so the two callers report the
    same input in the same words.
    """
    translate = translate or {}

    def members(pins) -> frozenset:
        return frozenset(translate.get(pin, pin) for pin in pins)

    golden_by_members: dict[frozenset, str] = {}
    for name, net in golden_nets.items():
        golden_by_members.setdefault(members(net.pins), name)

    renamed: dict[str, str] = {}
    taken: dict[str, str] = {}  # golden name -> the candidate net that took it
    for name, net in candidate_nets.items():
        if respect_golden_names and name in golden_nets:
            continue  # already the right name; leave it alone
        match = golden_by_members.get(members(net.pins))
        if match is None:
            continue
        if match in taken:
            if skipped is not None:
                skipped.append(
                    f"rename {name!r} -> {match!r} skipped: {taken[match]!r} was "
                    f"already renamed to {match!r}"
                )
            continue
        renamed[name] = match
        taken[match] = name

    # A rename onto a name another candidate net **keeps** would weld two
    # clusters into one (compare's `nets.setdefault` used to merge them; draw's
    # `candidate.nets[new] = net` dropped the incumbent, pins and all). The net
    # already called `NET1` and the one being renamed to `NET1` are different
    # circuits, and only one of them ever earned the name. A net that is itself
    # being renamed *away* does not block it — a cycle of renames is a
    # permutation, and each member of it lands on the name the golden gave that
    # cluster. (A net dropped here does not hand its name to somebody else — the
    # plan only ever shrinks.)
    #
    # Approving a rename is not a one-off decision (issue #57 finding 2). A
    # rename is approved *because* its target name is being vacated — and the
    # withdrawal below can withdraw the **vacating net's own** rename, which puts
    # that name back in use and strands every approval that rested on it. So the
    # withdrawal is repeated until it settles: each round can only remove
    # entries (``renamed`` never grows here), so it terminates, and afterwards
    # "no rename onto a name a candidate net keeps" is a property of the whole
    # plan rather than of one pass over it. Before this, the stranded approval
    # pointed at an occupied name and two circuits came out as one net.
    changed = True
    while changed:
        changed = False
        for name, match in list(renamed.items()):
            if (
                match != name
                and match in candidate_nets
                and renamed.get(match, match) == match
            ):
                del renamed[name]
                taken.pop(match, None)
                if skipped is not None:
                    skipped.append(
                        f"rename {name!r} -> {match!r} skipped: the candidate already "
                        f"carries a net called {match!r}"
                    )
                changed = True
    return renamed


def reconcile_names(
    candidate: DesignModel,
    golden: DesignModel,
    *,
    skipped: list[str] | None = None,
) -> DesignModel:
    """Rename the candidate's nets to the golden names, matched by membership.

    Calibration-mode preprocessing. The editor names nets *it* finds unnamed
    ``$1N5, $1N22, …`` while our golden-side parser names the same clusters
    deterministically (``NET1, NET22, …``); a calibration comparison must ask
    "same connectivity?" — i.e. compare by membership — without letting a
    naming convention masquerade as a drawing error. A candidate net whose
    membership exactly matches a golden net is renamed; anything else keeps
    its name and surfaces as a real difference. Deliberately *not* used by
    the draw verdict, where the drawn board carries our names explicitly and
    names must match verbatim.

    The decision is :func:`plan_membership_renames`, shared with
    :func:`boardwise.engines.draw._reconcile_derived_names` — one judgement, two
    applications. Calibration is the ``respect_golden_names=False`` side: a
    candidate net whose name is *also* a golden name may still be sitting on
    another golden cluster, and permuting those is the point of comparing by
    membership rather than by name. A rename whose target name is **already
    taken** is abandoned, never merged and never overwritten (issue #46), and
    the reason is appended to ``skipped`` when the caller passes a list.

    This path applies immutably: the candidate is left alone and a new
    :class:`DesignModel` comes back.
    """
    renamed = plan_membership_renames(
        golden.nets,
        candidate.nets,
        respect_golden_names=False,
        skipped=skipped,
    )

    import copy as _copy

    out = DesignModel(raw=dict(candidate.raw))
    # The safety metadata rides along **verbatim** (issue #57 finding 11). These
    # three fields exist so that a consumer can *refuse* to conclude — two parts
    # on one designator, a name placed on several pages, a net the per-page
    # merge welded blind — and a rebuild that leaves them at their empty
    # defaults turns every one of those refusals into a pass: an absent entry
    # reads as "proven". Copied, never rebuilt and never filtered, because an
    # empty tuple is itself an answer ("more than one page, page ids
    # unavailable") that a filter would drop one entry at a time.
    out.duplicate_designators = list(candidate.duplicate_designators)
    out.cross_page_designators = {
        name: list(pages)
        for name, pages in candidate.cross_page_designators.items()
    }
    out.unproven_nets = dict(candidate.unproven_nets)
    # …and with them why each name is unproven (107). A rebuilt reason falls back
    # to ``WELDED_BY_NAME``, which is the pre-107 wording: a truncation the
    # reconcile dropped would still refuse, but it would name the wrong gap.
    out.unproven_reasons = dict(candidate.unproven_reasons)
    for designator, component in candidate.components.items():
        clone = _copy.deepcopy(component)
        for pin in clone.pins:
            if pin.net in renamed:
                pin.net = renamed[pin.net]
        out.components[designator] = clone
    nets: dict[str, Net] = {}
    for name, net in candidate.nets.items():
        new_name = renamed.get(name, name)
        # One candidate net per output name, and the invariant is upstream's:
        # ``plan_membership_renames`` keeps two renames off one target
        # (``taken``) and withdraws every rename onto a name a candidate net
        # *keeps* — to a fixed point, because withdrawing one can strand
        # another (issue #57 finding 2). This line used to be documented as
        # unreachable and it was reachable: a rename approved because its
        # target was being vacated survived the withdrawal of that vacating
        # rename, and two clusters met under one name. It cannot merge now, and
        # a future edit that makes it reachable again would merge silently —
        # which is why the invariant is named here instead of assumed.
        entry = nets.setdefault(new_name, Net(name=new_name))
        for member in net.pins:
            if member not in entry.pins:
                entry.pins.append(member)
    out.nets = nets
    return out
