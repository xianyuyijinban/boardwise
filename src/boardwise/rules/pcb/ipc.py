"""PCB rules that quote a **standard** rather than a house number (task 126c,
通用层 4 + 8): how much current a track may carry, and how far apart two nets of
different voltage must sit.

This is the sibling of :mod:`boardwise.rules.pcb.distance` and deliberately not
the same thing. Both files read :mod:`boardwise.core.measure` and nothing else, and
both let a **number** decide rather than a taste — but 126b's thresholds are
house rules the oracle has not ruled on and say so in their ``source``, while
every constant below traces to **IPC-2221**, the standard 126b's docstring
refers to when it says 「IPC-2221 states *clearance*, not a placement distance —
that is 126c's job」. The two are kept in separate files so a guess can never be
read as a standard and a standard can never be read as a guess.

:func:`required_track_width` (the ampacity half) and :func:`required_spacing`
(the clearance half) are **pure functions of a number and a constant**, so a
reviewer can re-derive every row in a report with a pocket calculator; the rules
only decide *which net to ask about* and *what to say when the answer is
missing*.

What the two rules share is the discipline, not the arithmetic:

* **UNKNOWN is a work order with an address** (钉 6). A net whose current nobody
  declared, or whose voltage no source names, is an **INFO finding whose message
  names the missing fact and where it may be written** — not a silence and never
  a guess. See :class:`TrackAmpacity` and :class:`VoltageSpacing` for the exact
  per-state contract, and ``tests/test_126c_pcb_ipc_rules.py`` for the pins.
* **The subject set is the contract's**, not the board's net list.
  :class:`TrackAmpacity` examines the nets the design-intent contract names in
  a **current slot**; :class:`VoltageSpacing` examines the nets either source
  calls a **rail** plus every ground net. A board with no contract therefore has
  **no subject at all** for the ampacity rule, and it is silent — 92 INFO rows
  on 毕设FOC's PCB1 saying "nobody declared a current for ``NET37``" would be a
  wash that buries the rows that mean something, and it is the same reading 126b
  took for nets the voltage inference could not call supply nets. What makes
  this 「缺席而非空」 rather than 「装作知道」 is that it is stated in the module
  docstring, in each rule's docstring, and pinned by a test that counts the empty
  answer; a reader who wants the missing facts enumerated can ask for them by
  *writing the contract*, which is the address the UNKNOWN rows give. The
  spacing rule is the exception that proves the point: it does **not** need a
  contract, because the drawing's own rail enumeration and the ground reference
  are facts the board carries, which is why it has rows on that same fixture
  (127b: four of them, all of them UNKNOWN work orders — the three WARNs 126b
  reported there were cross-layer projections and a same-potential ground join).

**Ampacity** (:class:`TrackAmpacity`) is the classic IPC-2221 conductor-current
relation, ``I = k·ΔT^0.44·A^0.725`` with the area ``A`` in square mils and the
current in amperes; ``k`` is 0.048 on an external conductor and 0.024 on an
internal one, the 10 °C rise and the 1 oz (1.378 mil) copper thickness are the
constants the standard's own table is quoted at. The rule inverts it — the
contract states the current, the board carries a width, and the comparison that
matters is 「does this width carry this current」 — and then takes the **minimum**
width per copper layer
(:func:`~boardwise.core.measure.conductor_copper`), because the narrowest segment
of a net is the one that heats up, not the average.
516 A2 widens the unit of judgement from the net **name** to the **conductor**:
one piece of copper can be exported under two names (``IRbus``/``IRBUS`` on 实板
A), so each declared net is expanded to its overlapping-copper component and the
component is judged at its narrowest point.

**Issue #84 narrows what that minimum is allowed to conclude.** The contract
states **one current per net**, and a net is not obliged to be one conductor all
the way along it: 实板 A's ``IRbus`` carries its main current on a 30 mil trunk
plus two layers of pour and reaches its four 100 Ω shunt resistors' sense taps
along 27 segments of 10 mil, and ``ACN`` the same with a pour whose cross-section
is ~125 mil and five 10 mil zero-crossing sense lines. Reading the net's current
against the layer's narrowest track judged those sense lines as overloads — four
false ERRORs on one board, and the model that is missing is **branch**. So when a
conductor also carries copper **at least three times as wide as its narrowest
segment and wide enough for the declared current on its own** (a trunk, or a pour
read as a track, :data:`BRANCH_WIDTH_RATIO`), the narrow segments are reported as
an **UNKNOWN that names them** — width, count, total length, coordinate span and
each segment's own endpoints — instead of as an overload. What the rule still
does not do is decide *which* segment carries the current: only the designer
knows where the load is, so the row is a work order that says so and names the
copper it would otherwise have judged.

Insufficient is an **ERROR**: an overloaded conductor is a safety defect (it
runs hot, it anneals the copper, it is the failure mode that ends in a smoke),
and it is the one judgement in the PCB side that is not a matter of taste.
Margin is silence — a track wider than it needs to be is not a finding, and
inventing one would train readers to ignore the ERRORs.

**Spacing** (:class:`VoltageSpacing`) uses :data:`VOLTAGE_SPACING_MIL`, a **data**
table rather than arithmetic, because the standard states it as a table and the
shape of the table *is* the finding: the clearance is flat across each voltage
band and jumps at the band's edge. It pairs nets whose voltage difference falls
in a band with :func:`~boardwise.core.measure.net_clearance` and warns when the
measured gap is under the band's number. Ground nets are voltage 0 — not 0 V
*because of their name* but because a ground net **is** the reference node of the
board, the same thing :mod:`boardwise.core.power_domains` reads and the same
thing 126b's supply-net inference rests on. 516 A1 narrowed the exemption: only
two **grounds**, or copper that geometrically coincides, are one node — two nets
merely *declared* at the same voltage are judged by the swing bound
``max(|a|, |b|)`` (:class:`VoltageSpacing` says why).

**The pour blind spot is documented, not papered over.** A pair whose only
relationship is that one shape sits inside a pour's outer outline is
*unmeasurable* — the real pour has clearance voids around foreign pads and those
voids are not in the geometry model — so :func:`~boardwise.core.measure.
net_clearance` returns ``None``. This rule drops such a pair: not counted as a
violation, not counted as a pass, and **not** reported as "clearance unknown"
either, because the unknown is in the *measurement library*, not in the design's
facts, and dressing it as a missing design fact would send an engineer to write
a contract entry that already exists. :meth:`VoltageSpacing.check` says so where
it happens, and the test module pins the count of pairs it skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..base import Finding, FindingTarget
from ...core.architecture import generate_architecture
from ...core.measure import (
    ClearanceResult,
    ConductorCopper,
    LayerCopper,
    conductor_copper,
    net_clearance,
)
from ...core.model import is_ground_net
from ...core.values import parse_current_amps, parse_voltage_volts
from .base import PcbReviewContext, PcbRule

#: The IPC-2221 conductor-current constant ``k`` for an **external** conductor.
#: From the standard's own table of ``I = k·ΔT^0.44·A^0.725`` (area in square
#: mils, current in amperes) — the pair most often quoted as IPC-2221 §6.4 /
#: Table 6-1's companion conductor-capacity figures. 0.048 assumes the heat of
#: both sides of the board has somewhere to go; 0.024 (:data:`INNER_K`) assumes
#: it does not, which is why an inner conductor of the same width carries half
#: as much. Both are the standard's numbers, not a derating this build invented.
OUTER_K = 0.048

#: The same constant for an **internal** conductor (IPC-2221, as above).
INNER_K = 0.024

#: The temperature rise the current formula is quoted at, in °C. IPC-2221's
#: conductor table is stated for a **10 °C** rise above ambient; a design that
#: wants a different rise has to re-derive the relation, and this build does not
#: guess one (the same refusal 126b's ``DECAP_DISTANCE_MIL`` docstring makes).
TEMP_RISE_C = 10.0

#: 1 oz copper thickness in mils: 1 oz/ft² of copper is 1.37 mil thick, the
#: conversion the IPC conductor tables use (34.8 µm / 1000 mil → 1.378).
COPPER_THICKNESS_MIL = 1.378

#: How much wider than a conductor's **narrowest** segment a different piece of
#: its own copper must be before the narrow segments stop being read as its
#: current path (issue #84, 岳 2026-10-22).
#:
#: **Why a ratio at all, and why three.** The question is 「is this narrow copper
#: the conductor, or a branch off the conductor」, and the only fact the rule has
#: is width — a sense line off a power trunk is narrower than the trunk by the
#: *design rule of the two functions*, while two segments of the same path differ
#: by routing, not by role. The threshold is the pair 岳's issue states: wide
#: copper must be at least this many times the narrowest segment **and** at least
#: the width the declared current needs (:meth:`TrackAmpacity._load_bearing`), so
#: a conductor whose widest copper is itself too narrow for the current keeps
#: every row it had.
#:
#: Three is a house number and is stated as one: it is the smallest ratio at
#: which a 10 mil sense line (the one 实板 A actually routes) can sit beside a
#: trunk, and it is deliberately not tunable per board — a rule that asked the
#: designer how much wider the trunk is would be asking the party under review to
#: set the threshold. What the ratio decides is only whether a row is an ERROR or
#: an UNKNOWN: the segments are **named either way**, so a wrong three costs a
#: reader one confirmation, not a missed defect.
BRANCH_WIDTH_RATIO = 3.0

#: The copper weight the thickness above belongs to, in ounces per square foot.
COPPER_OZ_PER_FT2 = 1.0

#: ``I = k·ΔT^0.44·A^0.725`` — the IPC-2221 conductor-current relation, written
#: as data with its provenance rather than folded into a comment, because a
#: reviewer re-deriving a row needs the exponents themselves. Solved for the
#: area: ``A = (I / (k·ΔT^0.44))^(1/0.725)``.
CURRENT_EXPONENT_AREA = 0.725
CURRENT_EXPONENT_DELTA_T = 0.44

#: IPC-2221 Table 6-1, simplified, as **data**: ``(vmin, vmax, spacing_mil)``.
#:
#: **What this table is.** Column B2 of the standard's Table 6-1 — *external
#: conductors, uncoated, sea level to 3050 m* — with the voltage ranges merged
#: where the standard gives one number for several adjacent rows, because the
#: merged rows are the ones a review actually asks about:
#:
#:     0–15 V → 4 mil · 16–30 V → 4 mil · 31–150 V → 24 mil · 151–300 V →
#:     50 mil · 301–500 V → 100 mil
#:
#: (uncoated, B2: 0–15 → 0.1 mm, 16–30 → 0.1 mm, 31–50 → 0.6 mm, 51–100 →
#: 0.6 mm, 101–150 → 0.6 mm, 151–170 → 1.25 mm, 171–250 → 1.25 mm, 251–300 →
#: 1.25 mm, 301–500 → 2.5 mm; 4 / 24 / 50 / 100 mil are the mil roundings of
#: 0.1 / 0.6 / 1.25 / 2.5 mm.)
#:
#: **Why B2, the uncoated external column, and not a smaller one.** Three
#: reasons, all in the conservative direction — a rule that under-spaces calls a
#: legal board defective, and a false ERROR/WARN costs a reviewer more than a
#: missed one costs copper:
#:
#: 1. **the tool cannot see the coating.** Whether the assembled product is
#:    conformally coated is a fact about the *product*, and nothing in an
#:    ``.epro2`` document states it. B2 is the column that holds without it;
#: 2. **it is the largest of the bare-board columns** (B1 internal is 2 mil
#:    where B2 is 4 mil at the bottom band, and 0.05 mm vs 0.1 mm through the
#:    middle), so reading B2 costs nothing when the coating exists and is right
#:    when it does not;
#: 3. **the measurement is a plan-view projection.** The clearance primitive
#:    (:func:`~boardwise.core.measure.net_clearance`) measures the XY-plane gap
#:    between two shapes and conservatively returns 0 for cross-layer pairs, so
#:    the reading it produces is already the pessimistic one; pairing a
#:    pessimistic number with an optimistic threshold would cancel out.
#:
#: **岳 2026-10-06 裁**: this simplified table is the IPC-2221 side of the
#: question; **IEC 60950 / IEC 60664-1** is left as the upgrade path for the
#: bands above 30 V, where creepage (surface distance along the insulation) and
#: clearance (through the air) stop being the same number and a safety-oriented
#: review needs both. This build states clearance only, says so, and does not
#: pretend creepage is covered.
VOLTAGE_SPACING_MIL: tuple[tuple[float, float, float], ...] = (
    (0.0, 15.0, 4.0),
    (15.0, 30.0, 4.0),
    (30.0, 150.0, 24.0),
    (150.0, 300.0, 50.0),
    (300.0, 500.0, 100.0),
)

#: Above :data:`VOLTAGE_SPACING_MIL`'s last band the standard continues
#: arithmetically rather than in bands: **+0.005 mm per volt above 500 V**
#: (IPC-2221 Table 6-1's continuation of the B2 column). In mils that is
#: 0.005 mm = 0.1969 mil per volt; the constant is written in mm-per-volt and
#: converted here so the number in the comment and the number in the code are
#: the same statement.
SPACING_ABOVE_MAX_BAND_MM_PER_V = 0.005
MM_PER_MIL = 0.0254

#: The voltage at which the simplified table above stops being one: past this
#: the arithmetic continuation is a stretch, creepage and clearance part company,
#: and the answer belongs to IEC 60950 (see :data:`VOLTAGE_SPACING_MIL`). A pair
#: this far apart is reported UNKNOWN with that fact named, never extrapolated.
SPACING_TABLE_MAX_V = 1000.0

#: A net's ground reference: a ground net is 0 V **because it is the board's
#: reference node**, the same reading :mod:`boardwise.core.power_domains` gives
#: and the same one 126b's supply-net inference rests on. It is not "the name
#: says so": ``is_ground_net`` is the shared predicate both sides call, so the
#: two modules cannot disagree about which nets are ground.
GROUND_VOLTS = 0.0


# ---------------------------------------------------------------------------
# the arithmetic, as pure functions
# ---------------------------------------------------------------------------


def required_width_mil(
    amps: float, *, inner: bool = False, thickness_mil: float = COPPER_THICKNESS_MIL
) -> float:
    """Track width (mil) that carries ``amps`` at a 10 °C rise, IPC-2221.

    The IPC-2221 conductor-current relation is
    ``I = k·ΔT^0.44·A^0.725`` with ``A`` in square mils; this is the same
    relation solved for width, ``A = (I / (k·ΔT^0.44))^(1/0.725)`` followed by
    ``width = A / thickness``.

    Worked example, the ROBOT contract's ``range: "±3A"`` on the ``U+`` net
    (verified against the test module, which pins both directions):

    * external, 1 oz: ``A = (3 / (0.048 · 10^0.44))^1/0.725`` = 74.1616 mil²,
      ``width = 74.1616 / 1.378`` = **53.8 mil**;
    * internal, 1 oz: ``A = (3 / (0.024 · 10^0.44))^1/0.725`` = 192.927 mil²,
      ``width = 192.927 / 1.378`` = **140.0 mil**.

    A non-positive current has no required width to speak of (there is nothing
    to carry); the caller asks the question only for a current it parsed out of
    a declaration, and a negative declaration is read as its magnitude there, so
    this function returns 0.0 rather than raising — the "no current, no width"
    answer is the honest one and no fixture has one.
    """
    if amps <= 0.0:
        return 0.0
    k = INNER_K if inner else OUTER_K
    area = (amps / (k * TEMP_RISE_C ** CURRENT_EXPONENT_DELTA_T)) ** (
        1.0 / CURRENT_EXPONENT_AREA
    )
    return area / thickness_mil


def required_spacing_mil(differential_volts: float) -> float | None:
    """Minimum conductor spacing (mil) at a voltage difference, or ``None``.

    ``None`` means **the simplified table does not answer this**: the pair is
    above :data:`SPACING_TABLE_MAX_V`, where the standard's arithmetic
    continuation is a stretch and IEC 60950 is the authority. The caller
    reports that as UNKNOWN naming the fact — it does not fall back to the last
    band's number, because extrapolating a safety threshold downward is exactly
    the kind of quiet invention this repository refuses.

    Hand-checkable on the bands this rule actually fires on:

    * ``|24 − 0| = 24 V`` → the ``15–30 V`` band → **4 mil**;
    * ``|24 − 5| = 19 V`` → the same band → **4 mil**;
    * ``|12 − 0| = 12 V`` → the ``0–15 V`` band → **4 mil**;
    * ``|3.3 − 0| = 3.3 V`` → the ``0–15 V`` band → **4 mil**;
    * ``500 V`` → the last band's own 100 mil; ``501 V`` → 100 mil +
      (1 V × 0.005 mm) = 100.197 mil.
    """
    if differential_volts < 0.0:
        differential_volts = -differential_volts
    for low, high, spacing in VOLTAGE_SPACING_MIL:
        if differential_volts <= high:
            return spacing
    if differential_volts > SPACING_TABLE_MAX_V:
        return None
    last_high = VOLTAGE_SPACING_MIL[-1][1]
    extra_mm = (differential_volts - last_high) * SPACING_ABOVE_MAX_BAND_MM_PER_V
    return VOLTAGE_SPACING_MIL[-1][2] + extra_mm / MM_PER_MIL


# ---------------------------------------------------------------------------
# the two facts the rules read
# ---------------------------------------------------------------------------


def _intent_rails(ctx: PcbReviewContext) -> list:
    """The contract's ``rails[]``, or an empty list (no contract, no rails)."""
    intent = getattr(ctx, "intent", None)
    return list(getattr(intent, "rails", None) or [])


def declared_currents(ctx: PcbReviewContext) -> dict[str, tuple[float, str]]:
    """``net -> (amps, where it was declared)`` from the contract.

    **Three places, and the order they are read in.**

    1. ``requirements.signals[net=…].range`` — the first source, and the one the
       task book names. The ROBOT ctrl-FOC contract writes the phase-current
       nets this way: ``{"net": "U+", "range": "±3A", "kind": "current-sense",
       "polarity": "bidirectional", …}``. The reading is a **magnitude**:
       ``±3A`` is a bidirectional chain measured at three amps, and a conductor
       carries amps in either direction, so the ``±`` is stripped and 3.0 is
       what goes into the formula. What is *not* done is reading the ``±`` as a
       doubling (6 A) or as a sign — a signed current would make the comparison
       meaningless and 011's lesson is that a shape this build does not
       understand must not become a guess.
    2. ``requirements.rails[net=…].peakCurrent`` and ``…continuousCurrent`` —
       the same slot pair 092's ``pwr-ldo-dissipation`` already reads through
       :func:`~boardwise.core.values.parse_current_amps` (its UNKNOWN rows point
       an engineer at exactly this address), so a supply current written into
       the contract is usable here without a second current grammar. Peak wins
       over continuous: a conductor that survives the peak survives both, and
       judging the continuous current only would under-state the load.
    3. Nothing else. **A net's shape never becomes a current** — a track that
       happens to be 40 mil wide does not say how much current the design
       intends, and 011 exists because guessing that reading produced ERRORs
       dressed as facts.

    Both parsers are the ones in :mod:`boardwise.core.values`
    (「一个量纲一个实现」, 092): a bare ``3`` with no unit, or ``3V``, is not a
    current and yields no entry, so the net falls through to UNKNOWN and the
    report says where to write the fact.
    """
    declared: dict[str, tuple[float, str]] = {}
    intent = getattr(ctx, "intent", None)
    for signal in getattr(intent, "signals", None) or []:
        net = str(getattr(signal, "net", "") or "").strip()
        if not net:
            continue
        raw = str(getattr(signal, "slots", {}).get("range", "") or "").strip()
        amps = _magnitude_amps(raw)
        if amps is None:
            continue
        declared[net] = (
            amps,
            f"contract requirements.signals[net={net}].range = {raw!r}"
            f"（±/~ 前缀按幅值读，双向链也是这个数）",
        )
    for rail in _intent_rails(ctx):
        net = str(getattr(rail, "net", "") or "").strip()
        if not net:
            continue
        for slot in ("peakCurrent", "continuousCurrent"):
            raw = str(getattr(rail, "slots", {}).get(slot, "") or "").strip()
            amps = parse_current_amps(raw)
            if amps is None:
                continue
            declared[net] = (
                abs(amps),
                f"contract requirements.rails[net={net}].{slot} = {raw!r}",
            )
            break
    return declared


def _magnitude_amps(raw: str) -> float | None:
    """``"±3A"`` → 3.0; anything this build does not read → ``None``.

    The polarity prefix (U+00B1, ``~``, ``+``) is stripped and what remains goes
    through the shared current grammar, so ``±3A``, ``~500mA`` and ``3A`` are one
    shape. A negative declaration is read as its magnitude for the same reason
    the ``±`` is: what a conductor must carry is a magnitude. Anything else —
    a bare ``3``, ``3V``, a prose sentence — is ``None``, which is the UNKNOWN
    row, not a zero and not a guess.
    """
    if not raw:
        return None
    text = raw.strip()
    for prefix in ("±", "+", "~", "-"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    amps = parse_current_amps(text)
    return None if amps is None else abs(amps)


def _declared_net_names(ctx: PcbReviewContext) -> set[str]:
    """Every net the contract names in a slot this rule reads a current from.

    This is the rule's **subject set**, and it is deliberately wider than the
    set of nets whose declaration could be read
    (:func:`declared_currents`). The two together are what make the UNKNOWN row
    say something:

    * a net the contract names **with** a readable current is judged
      (:class:`TrackAmpacity`'s per-layer comparison);
    * a net the contract names **with an unreadable** one — ``"5"`` with no
      unit, ``"5V"``, a prose sentence — is an UNKNOWN, because 「you declared
      something here and it is not a current」 is an actionable work order;
    * a net the contract does not name at all is **silence**, which is the
      module docstring's 「no subject」 discipline.

    The distinction is the whole reason this function exists separately from
    :func:`declared_currents`: folding the two together would make an
    unreadable declaration indistinguishable from no declaration, and the second
    has nothing to say.
    """
    names: set[str] = set()
    intent = getattr(ctx, "intent", None)
    for signal in getattr(intent, "signals", None) or []:
        net = str(getattr(signal, "net", "") or "").strip()
        if net and "range" in (getattr(signal, "slots", {}) or {}):
            names.add(net)
    for rail in _intent_rails(ctx):
        net = str(getattr(rail, "net", "") or "").strip()
        if not net:
            continue
        slots = getattr(rail, "slots", {}) or {}
        if "peakCurrent" in slots or "continuousCurrent" in slots:
            names.add(net)
    return names


def _unreadable_current_reason(ctx: PcbReviewContext, net: str) -> str:
    """Why the contract's declaration for ``net`` is not a current.

    The row quotes the offending text when there is one, because 「you wrote
    ``"5"`` there and a current needs a unit」 is the whole message; a slot the
    contract leaves merely empty is reported as the absence it is, which is a
    different work order from a wrong unit.
    """
    intent = getattr(ctx, "intent", None)
    for signal in getattr(intent, "signals", None) or []:
        if str(getattr(signal, "net", "") or "").strip() == net:
            raw = str((getattr(signal, "slots", {}) or {}).get("range", "")).strip()
            if raw:
                return (
                    f"the contract declares requirements.signals[net={net}].range "
                    f"= {raw!r}, which is not a current this build can read (a "
                    "number, an SI prefix and an A, in that order)"
                )
    for rail in _intent_rails(ctx):
        if str(getattr(rail, "net", "") or "").strip() == net:
            slots = getattr(rail, "slots", {}) or {}
            for key in ("peakCurrent", "continuousCurrent"):
                raw = str(slots.get(key, "")).strip()
                if raw:
                    return (
                        f"the contract declares requirements.rails[net={net}]."
                        f"{key} = {raw!r}, which is not a current this build can "
                        "read (a number, an SI prefix and an A, in that order)"
                    )
    return f"the contract names net {net!r} in a current slot but states no current"


def declared_voltages(
    ctx: PcbReviewContext, model: object
) -> tuple[dict[str, tuple[float, str]], list[str]]:
    """``net -> (volts, where it came from)`` plus a list of conflict notes.

    **Two sources, and the contract wins.**

    * ``requirements.rails[net=…].voltage`` then ``…targetVoltage`` — the
      requirement an engineer wrote. This is the *requirement*, so it outranks
      the drawing's own reading: if the two disagree, the contract is the
      statement of intent and the architecture is the reading of the drawing, and
      which of them is wrong is the architecture self-consistency question A3
      owns — not this rule's to decide.
    * ``architecture.chains.rails[].voltage`` — 044's enumeration of the rails
      the drawing itself supports (a net name that states its voltage, a shelf
      regulator's declared or MPN-decoded output). Read through the **public**
      :func:`~boardwise.core.architecture.generate_architecture`, the same call
      ``cli.checkup`` already makes for the report's own ``architecture`` section,
      so the voltages here are literally the ones the report prints — not a
      second, drifting implementation of "which rails does this board have".

    **A conflict is stated, not resolved.** Where both sources name the same net
    with different voltages, the contract's number is the one used and the
    divergence comes back in ``notes``, which every WARN's evidence quotes — a
    disagreement between a requirement and a drawing is a finding of its own and
    this rule refuses to swallow it silently.

    **A net two boards disagree about is also a conflict, and it is not
    resolved either.** :func:`generate_architecture` walks a project board by
    board, and two boards may each have a rail of the same name at a different
    voltage; picking one would let a board's spacing verdict depend on which
    board was enumerated first. Such a net is **dropped from the map entirely** (no entry, no verdict),
    which leaves it in the UNKNOWN population like any other unpriced net — the
    honest state, and the reason the enumeration's conflict set is returned
    rather than silently keeping the first board's number.
    """
    volts: dict[str, tuple[float, str]] = {}
    notes: list[str] = []

    for rail in _intent_rails(ctx):
        net = str(getattr(rail, "net", "") or "").strip()
        if not net:
            continue
        for slot in ("voltage", "targetVoltage"):
            raw = str(getattr(rail, "slots", {}).get(slot, "") or "").strip()
            if not raw:
                continue
            value = parse_voltage_volts(raw)
            if value is None:
                # 164c (F5): a statement this build cannot read is **dropped with
                # a reason**, not dropped in silence — the UNKNOWN row for the net
                # then quotes this note instead of saying 「nobody priced it」,
                # which would send the engineer to write a number that is already
                # there.
                notes.append(
                    f"net {net!r}: the contract's {slot} = {raw!r} is not a "
                    "voltage this build can read (a number, an optional sign and a "
                    "V, in that order), so no voltage is stored for it"
                )
                continue
            if value == 0.0:
                # A 0 V rail is the board's reference level and both callers
                # already price grounds by convention (`is_ground_net`), so a
                # contract statement of 0 V is not a rail voltage here — dropped,
                # and named.
                notes.append(
                    f"net {net!r}: the contract's {slot} = {raw!r} states 0 V — the "
                    "board's reference level, which the ground convention already "
                    "carries — so no rail voltage is stored for it"
                )
                continue
            if net in volts and volts[net][0] != value:
                notes.append(
                    f"net {net!r}: contract says {volts[net][0]:g} V "
                    f"({volts[net][1]}) but {slot} = {raw!r} says {value:g} V; "
                    "the first is kept and the second is ignored — the sources disagree"
                )
                break
            volts[net] = (value, f"contract requirements.rails[net={net}].{slot} = {raw!r}")
            break

    architecture_rails, architecture_notes = _architecture_rails(model)
    notes.extend(architecture_notes)
    for net, value, where in architecture_rails:
        if net in volts:
            if volts[net][0] != value:
                notes.append(
                    f"net {net!r}: the contract says {volts[net][0]:g} V and the "
                    f"architecture enumeration says {value:g} V ({where}); the "
                    "contract is the requirement and wins, and the divergence is "
                    "reported rather than averaged — the sources disagree"
                )
            continue
        volts[net] = (value, f"architecture.chains.rails[net={net}].voltage ({where})")

    return volts, notes


#: The phrase every **conflicted** note carries. It is what lets
#: :func:`_notes_about`'s reader tell 「two sources disagree」 apart from 「the one
#: statement could not be read」 — see :meth:`VoltageSpacing._unknown_voltage`,
#: which says which of the two an UNKNOWN row is.
SOURCES_DISAGREE = "the sources disagree"


def _notes_about(notes: list[str], net: str) -> list[str]:
    """The notes **addressed to** ``net``.

    Every note :func:`declared_voltages` writes starts with ``net 'X':`` (that has
    been the convention since 126c), so a caller holding the flat list can still
    ask 「what was said about *this* net」 without a second return channel.
    """
    prefix = f"net {net!r}:"
    return [note for note in notes if note.startswith(prefix)]


def _architecture_rails(
    model: object,
) -> tuple[list[tuple[str, float, str]], list[str]]:
    """``(net, volts, where)`` per rail the drawing supports, from 044, plus notes.

    Read through the public enumeration, with the shelf — the same shelf
    :func:`boardwise.rules.decap.cap_candidates_on` and 126b's supply-net
    inference read, through
    :func:`boardwise.rules.facts.read_default_library`, because the regulator
    half of the voltage inference is a shelf fact and a rule that read a
    different shelf would give a different answer.

    Every failure mode here degrades to **fewer known voltages**, never to an
    exception and never to a guess: a model of ``None`` enumerates nothing, an
    unreadable shelf reaches :func:`boardwise.core.parts.load_parts` as a path
    that does not resolve (which that function already reads as an empty shelf),
    and a rail whose voltage the enumeration could not establish comes back
    without one and is simply not in this list — its net then falls to UNKNOWN
    with a message saying no source names its voltage.

    **The second half of the return value is 164c's F4.** The enumeration walks a
    project board by board, and two boards may each carry a rail of the same name
    at a different voltage; such a net is dropped from the map (no entry, no
    verdict — picking one would make a board's spacing verdict depend on the
    board that happened to be enumerated first). Dropping the net was right;
    dropping the **reason** was not, and this function's caller's docstring
    promised the conflict came back in its ``notes``. It does now: one note per
    conflicted net, naming both voltages and both boards, which is also what lets
    :class:`VoltageSpacing`'s UNKNOWN row say 「two sources contradict each other」
    instead of 「no source names this voltage」.
    """
    if model is None:
        return [], []
    from ..facts import read_default_library  # noqa: PLC0415 — read at call time

    try:
        library = read_default_library()
    except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
        library = None
    try:
        enumeration = generate_architecture(model, library=library)
    except Exception:  # noqa: BLE001 — see above: never a crash on the report
        return [], []
    seen: dict[str, tuple[float, str]] = {}
    conflicting: dict[str, list[tuple[float, str]]] = {}
    for rail in (enumeration.section.get("chains") or {}).get("rails") or []:
        net = str(rail.get("net") or "")
        value = rail.get("voltage")
        if not net or value is None:
            continue
        board = str(rail.get("board") or "")
        where = board or "this project"
        if net in seen:
            if seen[net][0] != float(value):
                conflicting.setdefault(net, [seen[net]]).append((float(value), where))
            continue
        seen[net] = (float(value), where)
    notes = [
        f"net {net!r}: the architecture enumeration prices this net at "
        + " and ".join(f"{volts:g} V on {where}" for volts, where in sides)
        + " — the sources disagree, so no voltage is asserted for it and it falls "
        "to UNKNOWN; keeping one would make this board's spacing verdict depend on "
        "which board was enumerated first"
        for net, sides in sorted(conflicting.items())
    ]
    return (
        [
            (net, value, where) for net, (value, where) in seen.items()
            if net not in conflicting
        ],
        notes,
    )


# ---------------------------------------------------------------------------
# shared readings
# ---------------------------------------------------------------------------


def _is_outer(board: object, layer_id: int | None) -> bool | None:
    """Is ``layer_id`` an external copper layer? ``None`` when unclassifiable.

    The distinction is the ``k`` in the ampacity relation (:data:`OUTER_K` vs
    :data:`INNER_K`), and it is read from the document's own ``LAYER`` table —
    ``layer_type in {"TOP", "BOTTOM"}`` through
    :attr:`boardwise.core.geometry.LayerInfo.is_copper`'s own vocabulary. A track
    whose layer has no definition at all is **not** guessed to be outer (a wrong
    guess would halve or double a safety threshold): the caller turns ``None``
    into an UNKNOWN naming the layer id.
    """
    if layer_id is None:
        return None
    info = getattr(board, "layers", {}).get(layer_id)
    if info is None:
        return None
    return info.layer_type in ("TOP", "BOTTOM")


def _measurement(kind: str, value: float, layer_ids: list[int] | None = None) -> dict:
    """The structured reading a PCB finding carries (钉 3).

    ``unit`` is always ``"mil"`` — every PCB-side reader keeps mils throughout
    (:mod:`boardwise.core.measure` never converts). ``layer_ids`` is filled by
    the rules whose number belongs to a named copper layer (a per-layer minimum
    width does; a plan-view clearance between two nets does not, it belongs to
    whichever layers the closest pair happened to share).
    """
    payload: dict = {"kind": kind, "value": round(value, 1), "unit": "mil"}
    if layer_ids:
        payload["layer_ids"] = sorted(layer_ids)
    return payload


def _clearance_measurement(
    measured: ClearanceResult, *, external: ClearanceResult | None = None
) -> dict:
    """The clearance reading **with the closest pair identified as fields** (#85).

    :func:`_measurement` carries the number; this adds the pair the number was
    read from, because the number alone cannot be acted on. ``element_a`` /
    ``element_b`` are the two labels the message already quotes, and
    ``component_a`` / ``component_b`` are the same claim in a field a consumer
    can compare — ``""`` for an element that belongs to no placement (a track, a
    via, a pour), the documented spelling of 「not resolvable」 that
    :class:`~boardwise.rules.base.FindingTarget` already uses.

    ``within_one_footprint`` is the question those two fields answer, **written
    out rather than left for the reader to derive**: the pair is one
    footprint's own pad pitch, which no routing change can move (issue #85).
    Leaving it absent when false would make 「no」 and 「nobody said」 read the
    same, which is the one thing a structured claim may not do.

    ``external_*`` appear only when the reading was taken twice — when the
    closest pair *is* a footprint pitch, the gap that a layout change can move
    is the nearest pair outside it, and both numbers belong in the evidence (岳's
    second reading of #85).
    """
    payload = _measurement("clearance", measured.distance)
    payload["element_a"] = measured.element_a
    payload["element_b"] = measured.element_b
    payload["component_a"] = measured.component_a
    payload["component_b"] = measured.component_b
    payload["within_one_footprint"] = measured.within_one_footprint
    if external is not None:
        payload["external_value"] = round(external.distance, 1)
        payload["external_element_a"] = external.element_a
        payload["external_element_b"] = external.element_b
        payload["external_component_a"] = external.component_a
        payload["external_component_b"] = external.component_b
    # #87④: additive identities for the exact pair(s) measured above. Older
    # ClearanceResult callers without details stay valid and mean "not recorded".
    for prefix, result in (("", measured), ("external_", external)):
        if result is None:
            continue
        detail_a = result.element_a_detail
        detail_b = result.element_b_detail
        if not detail_a or not detail_b:
            continue
        payload[f"{prefix}element_a_detail"] = detail_a
        payload[f"{prefix}element_b_detail"] = detail_b
        payload[f"{prefix}shared_layer_ids"] = sorted(
            set(detail_a["layers"]) & set(detail_b["layers"])
        )
    return payload


# ---------------------------------------------------------------------------
# pcb-track-ampacity
# ---------------------------------------------------------------------------


class TrackAmpacity(PcbRule):
    """Does a track carry the current the contract says its net carries?

    **The subject is the contract's net, and there is no subject without one.**
    The subject set is :func:`_declared_net_names` — every net the contract
    names in a **current slot** (``signals[].range``, ``rails[].peakCurrent`` /
    ``…continuousCurrent``) that actually carries copper on **this** PCB
    document. A net the contract says nothing about is not a subject and not a
    row: that is what keeps 毕设FOC (92 drawn nets, no contract) silent.

    **The judgement's unit is the conductor, not the name** (516 A2). A board
    routinely exports one piece of copper under two net names — 实板 A carries
    ``IRbus`` (the schematic name) and ``IRBUS`` (the PCB name) on one conductor,
    ``Gear``/``GEAR`` the same. Each declared net is expanded to its **connected
    component** under 「copper that overlaps on a shared layer」
    (:func:`_conductor_component`) and the component is judged **once, at its
    narrowest point** — because the narrower alias is the bottleneck. A declared
    net that turns out to be one conductor with a net nobody declared gets an
    **INFO** saying so even when the component passes, so the extra copper the
    rule measured is never silent.

    * a **readable** current (see :func:`declared_currents`) → one row per copper
      layer that carries the conductor's tracks: the required width
      (:func:`required_width_mil`) against the **minimum** measured width over
      all the component's nets on that layer
      (:func:`~boardwise.core.measure.conductor_copper`), and **ERROR** when the
      measured one is narrower;
    * a layer whose narrowest segments sit beside **load-bearing copper** — a
      trunk or a pour at least :data:`BRANCH_WIDTH_RATIO` times as wide as they
      are and wide enough for the declared current on its own — → **UNKNOWN**,
      one row per width class of those segments, naming them all (width, count,
      total length, coordinate span, each segment's own endpoints) and stating
      which copper the current is more likely to be on. This is issue #84's
      finding and the fifth state: the contract states **one current per net**,
      the board says the net's copper comes in two widths, and which segment
      carries the load is a fact about the *load*, not about the copper. The row
      is the work order that says so; the segments are named either way, so the
      reader confirms a location rather than hunts for one. See
      :meth:`_load_bearing` for the threshold's two halves and why a ratio is a
      ratio, and :meth:`_branch_rows` for what one row claims;
    * an **unreadable** declaration — ``"5"`` with no unit, ``"5V"``, prose — →
      **UNKNOWN**, an INFO finding naming the net, quoting the offending text
      and both addresses a current may be written at. This is the one UNKNOWN
      that means 「you declared something here and it is not a current」; the
      alternative (a net the contract never mentions) has nothing to say and is
      silence, which the subject-set paragraph above is about;
    * a current but **no tracks on this document** (a net carried entirely by
      pads and pours) → **UNKNOWN** naming the net, because there is no width to
      measure: pad and pour area is a different conductor model, and pretending
      a pour's area were a track width would be a number this rule cannot defend;
    * a track on a copper layer the document does not define → **UNKNOWN**
      naming the layer id, since choosing outer or inner there would halve or
      double a safety threshold.

    **The pour boundary, said on both sides.** 「Pad and pour area is a different
    conductor model」 is why a conductor whose copper is all pads and pours has no
    width to judge; issue #84 makes the same boundary work in the other
    direction: a pour (or a trunk) far wider than the narrowest track is copper
    the current *can* be flowing in, so the narrow track is not read as the
    conductor on width alone. What is read off a pour here is a **coarse** mean
    width (:attr:`~boardwise.core.measure.LayerCopper.pour_mean_width`), which is
    all the rule needs to ask 「is there much wider copper on this conductor」 and
    explicitly not a capacity claim — the finding it produces is an UNKNOWN, never
    a pass.

    **Margin is silence.** A track wider than it needs is not a finding. A
    design is entitled to over-provision copper and a rule that called that a
    defect would be reporting taste as ERROR.

    **Only tracks are judged; vias are not (留 D).** A via's ampacity is a
    separate calculation — the barrel's current path, its plating thickness and
    its hole-to-hole spacing are not the conductor relation this file quotes, and
    :meth:`boardwise.core.geometry.ViaGeometry.annular_ring` is a diameter, not a
    width. Getting that right needs facts (plating thickness per fab) that no
    fixture states, so a via-aware reading is left to a later stick rather than
    approximated here; pads are not judged for the same reason.

    **Severity rationale.** ERROR, not WARN, and the reason is stated in
    ``source``: an overloaded conductor is the one judgement on this side that
    is a safety matter rather than a preference. The number is the standard's,
    the current is the contract's and the width is the board's, so all three are
    printed in the message and a reviewer can disagree with any of them. The one
    row that is **not** an ERROR is #84's branch row, and it says so in its own
    words: it is an **UNKNOWN** — the rule declining to convict on a fact about
    the load it cannot read — and 钉 6's convention is that an UNKNOWN travels as
    INFO, with the work order written out.

    **Measured on the ROBOT ctrl-FOC fixture** (``ProPrj_ROBOT ctrl FOC``, the
    contract's own ``range: "±3A"``): ``U+`` and ``W+`` both carry their phase
    current on 10 mil copper on all three of their layers (layers 1 / 2 / 16),
    so each yields three ERRORs — external needs 53.8 mil, internal layers need
    140.0 mil, and 10.0 is nowhere near either. That is the rule's true-positive
    case and it is exactly why the finding is an ERROR: three amps down a 10 mil
    trace on the outer layer is a conductor this standard says will run far past
    a 10 °C rise. It is also the case that pins #84's gate shut rather than
    opening it: measured through
    :func:`~boardwise.core.measure.conductor_copper`, ``U+``'s widest track is
    15.0 mil and ``W+``'s 14.0 mil, neither net carries a pour at all, and the
    bar on either is 53.8 mil (outer) / 140.0 mil (inner) — so these six rows
    stayed six ERRORs when the branch reading landed, which is the negative half
    of the issue's evidence.
    """

    id = "pcb-track-ampacity"
    title = "A track is wide enough to carry its net's declared current"
    level = "L1-pcb-geometry"
    source = (
        "IPC-2221 conductor-current relation I = k·ΔT^0.44·A^0.725 "
        "(k = 0.048 external / 0.024 internal, ΔT = 10 °C, 1 oz = 1.378 mil), "
        "against the current declared in the design-intent contract and the "
        "per-layer minimum track width read off the board, against the widest "
        "copper the same conductor carries (issue #84: a branch beside a trunk "
        "or a pour is named as UNKNOWN, not judged by the net's whole current)"
    )

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        currents = declared_currents(ctx)
        declared = _declared_net_names(ctx)
        if not currents and not declared:
            # No contract, or a contract that names no net with a current slot at
            # all: **no subject**. 92 nets on 毕设FOC's PCB1 all lack one, and 92
            # UNKNOWN rows saying so would be a wash (the module docstring's
            # argument).
            return []
        findings: list[Finding] = []
        drawn = [net for net in board.net_names() if board.net(net).element_count]
        covered: set[str] = set()
        # 516 A2: the subject of one judgement is the **conductor**, not the net
        # name. A board exports `IRbus` in the schematic and `IRBUS` on the PCB
        # for one piece of copper; judging only the declared half leaves the
        # other half's 10 mil copper unread. Each declared net is expanded to its
        # connected component under 「copper that overlaps on a shared layer」,
        # and the component is judged once, at its narrowest point.
        for net in sorted(declared & set(drawn)):
            if net in covered:
                continue
            members = _conductor_component(board, net, drawn)
            covered |= members
            findings.extend(
                self._one_component(ctx, sorted(members), currents, declared)
            )
        return findings

    def _one_component(
        self,
        ctx: PcbReviewContext,
        members: list[str],
        currents: dict[str, tuple[float, str]],
        declared: set[str],
    ) -> list[Finding]:
        """Every row for one conductor (516 A2), one per copper layer with tracks.

        ``members`` is the connected component of net names that are physically
        one piece of copper: a declared net plus every net whose copper overlaps
        it on a shared layer (and, transitively, theirs). The judgement is at the
        **narrowest** width over all members on each layer — the bottleneck is
        what carries the current, and a rule that judged each name alone would
        miss the narrower alias.

        Since issue #84 the per-layer reading is taken at segment resolution
        (:func:`~boardwise.core.measure.conductor_copper`) and the narrowest
        width is not the whole answer: when the conductor also carries copper
        wide enough to be the current path on its own (:func:`_load_bearing`), the
        layer's undersized segments are reported by :meth:`_branch_rows` as
        UNKNOWN and named, instead of as an overload. Layers where that gate does
        not open keep the ERROR the rule always produced.

        The names that are *declared* but carry no readable current still get
        their UNKNOWN (that is the 「you declared something here and it is not a
        current」 work order, unchanged). A component that also contains a net the
        contract never named gets one **INFO** saying so — even when the
        component passes, because 「the rule measured the copper of net X, which
        nobody declared」 must not be silent.
        """
        declared_members = [net for net in members if net in declared]
        priced_members = [net for net in declared_members if net in currents]
        unnamed = [net for net in members if net not in declared]
        extra: list[Finding] = []
        if unnamed:
            extra.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"the declared net {declared_members[0]!r} is one "
                        f"conductor with unnamed net(s) "
                        + ", ".join(repr(net) for net in unnamed)
                        + " (their copper overlaps on a shared layer), so this "
                        "rule measured their copper too — declare a current for "
                        "them if they are separate statements, or accept them as "
                        "this conductor's other names"
                    ),
                    evidence=[
                        f"component: {' ≡ '.join(repr(net) for net in members)}",
                    ],
                    target=FindingTarget(net_refs=list(members)),
                )
            )
        if not priced_members:
            return [
                self._unknown(
                    ctx, net, 0.0, "", missing=_unreadable_current_reason(ctx, net)
                )
                for net in declared_members
            ] + extra
        # The conductor's current is the largest declared on any of its names —
        # conservative, and the names are one conductor so they should agree.
        amps, where = max(
            (currents[net] for net in priced_members), key=lambda item: item[0]
        )
        primary = priced_members[0]
        # Issue #84: the layer reading is kept at **segment** resolution, because
        # the rule now has to name the segments it declines to judge and has to
        # ask what else the layer carries. `track_count` is the conductor's whole
        # track population, layer or no layer, exactly as `track_width_stats`
        # counts it — it is what the "no width to compare" row below reports.
        #
        # The layer the rule *iterates* is still 「a layer with tracks」: a pour on
        # a layer that carries no track is copper the conductor has (so it can
        # load-bear, see `_load_bearing`) but it is not a width, and a net whose
        # copper is all pads and pours keeps the UNKNOWN it always had instead of
        # falling silent.
        copper = conductor_copper(ctx.board, members)
        judged_layers = {
            layer_id: layer
            for layer_id, layer in copper.layers.items()
            if layer.tracks
        }
        if not judged_layers:
            return [
                self._unknown(
                    ctx,
                    primary,
                    amps,
                    where,
                    missing=(
                        f"the per-layer track widths of net {primary!r} — it "
                        f"carries {copper.track_count} tracks but none of them "
                        "names a copper layer, so there is no width to compare"
                        if copper.track_count
                        else f"a track on net {primary!r} — this PCB document "
                        "carries it as pads and pours only"
                    ),
                )
            ] + extra
        if len(members) > 1:
            others = " ≡ ".join(repr(net) for net in members if net != primary)
            subject = (
                f"net {primary!r} ≡ {others} (one conductor, {len(members)} names)"
            )
        else:
            subject = f"net {primary!r}"
        findings: list[Finding] = []
        for layer_id in sorted(judged_layers):
            layer = judged_layers[layer_id]
            outer = _is_outer(ctx.board, layer_id)
            if outer is None:
                findings.append(
                    self._unknown(
                        ctx,
                        primary,
                        amps,
                        where,
                        missing=(
                            f"whether copper layer {layer_id} is external or "
                            f"internal (the document defines no LAYER record for "
                            f"it), which is what picks the IPC-2221 constant for "
                            f"net {primary!r}"
                        ),
                    )
                )
                continue
            needed = required_width_mil(amps, inner=not outer)
            if layer.min_width + 1e-9 >= needed:
                continue  # margin is silence, not a finding
            name = ctx.board.layer_name(layer_id)
            # Issue #84: before the narrowest segment becomes an overload, ask
            # whether it is the conductor at all — see `_load_bearing`.
            load = _load_bearing(copper, layer=layer, needed=needed)
            if load is not None:
                findings.extend(
                    self._branch_rows(
                        ctx,
                        members=members,
                        subject=subject,
                        primary=primary,
                        layer=layer,
                        layer_name=name,
                        outer=outer,
                        needed=needed,
                        amps=amps,
                        where=where,
                        load=load,
                    )
                )
                continue
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="ERROR",
                    level=self.level,
                    message=(
                        f"{subject} carries {amps:g} A ({where}) but its "
                        f"{'external' if outer else 'internal'} copper on layer "
                        f"{layer_id} ({name}) is {layer.min_width:.1f} mil wide "
                        f"at its narrowest, and IPC-2221 at ΔT={TEMP_RISE_C:g} °C "
                        f"/ {COPPER_OZ_PER_FT2:g} oz needs {needed:.1f} mil — "
                        f"{needed / layer.min_width:.1f}x over the copper that "
                        "is there"
                    ),
                    evidence=[
                        f"net {primary!r}: {where}",
                        f"layer {layer_id} ({name}), {layer.track_count} "
                        f"track(s), min width {layer.min_width:.4f} mil, "
                        f"total length {layer.total_length:.2f} mil",
                        f"IPC-2221: k={OUTER_K if outer else INNER_K}, "
                        f"ΔT={TEMP_RISE_C:g} °C, thickness {COPPER_THICKNESS_MIL} mil "
                        f"→ required width {needed:.4f} mil",
                    ]
                    + (
                        [f"one conductor: {' ≡ '.join(repr(n) for n in members)}"]
                        if len(members) > 1
                        else []
                    ),
                    target=FindingTarget(
                        net_refs=list(members),
                        measurement=_measurement("width", layer.min_width, [layer_id]),
                    ),
                )
            )
        return findings + extra

    def _branch_rows(
        self,
        ctx: PcbReviewContext,
        *,
        members: list[str],
        subject: str,
        primary: str,
        layer: LayerCopper,
        layer_name: str,
        outer: bool,
        needed: float,
        amps: float,
        where: str,
        load: "_LoadBearing",
    ) -> list[Finding]:
        """One UNKNOWN per width class of the layer's undersized segments (#84).

        **What a row claims, and what it refuses to claim.** The conductor carries
        ``amps`` and the layer carries ``load`` — copper at least
        :data:`BRANCH_WIDTH_RATIO` times as wide as its narrowest segments and
        wide enough for that current on its own — so the narrow segments are
        **named** (width class, count, total length, coordinate span, and every
        segment's own id, length and endpoints) and **not** judged by the net's
        whole current. The row says the current 「can be flowing in the wider
        copper instead」, which is why 「this segment is undersized」 is not a
        conclusion this rule may draw from a track width and a net-level
        declaration.

        **Which width classes, and why by width.** The document states each
        segment's width, and a branch is routed at a design rule: 实板 A's 27
        sense taps are all 10 mil and ACN's five are all 10 mil. Grouping by the
        stated width therefore produces one row per branch design rule rather
        than one per segment (27 rows for one shape would be a wash, which is the
        same argument the module's 「no subject」 paragraph makes), while still
        naming every segment — in the evidence, with its own coordinates.

        **The rows are named, so a wrong gate is visible.** This is the state the
        rule is least sure of, and the severity says so: INFO, because it is an
        UNKNOWN and not a violation. A reader who disagrees with the gate has the
        width, the coordinates and the required width in front of them.
        """
        findings: list[Finding] = []
        for width, segments in _width_classes(layer.tracks, needed):
            total = sum(segment.length for segment in segments)
            box = _span(segments)
            longest = max(segments, key=lambda t: (t.length, t.id))
            # A malformed record can state a zero width; the ratio would divide
            # by it, and 「no copper at all」 is the honest reading of one.
            shortfall = (
                f"the copper there is {needed / width:.1f}x under the standard"
                if width > 0.0
                else "the segment states a 0.0 mil width, so there is no copper "
                "there to carry anything"
            )
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="INFO",
                    level=self.level,
                    message=(
                        f"{subject} carries {amps:g} A ({where}) and its "
                        f"{'external' if outer else 'internal'} copper on layer "
                        f"{layer.layer_id} ({layer_name}) has {len(segments)} "
                        f"segment(s) at {width:.1f} mil — {total:.1f} mil of "
                        f"copper from ({box[0]:.1f}, {box[1]:.1f}) to "
                        f"({box[2]:.1f}, "
                        f"{box[3]:.1f}), the longest being {longest.id!r} of "
                        f"{longest.length:.1f} mil from ({longest.start.x:.1f}, "
                        f"{longest.start.y:.1f}) to ({longest.end.x:.1f}, "
                        f"{longest.end.y:.1f}) — narrower than the {needed:.1f} mil "
                        f"IPC-2221 needs at ΔT={TEMP_RISE_C:g} °C / "
                        f"{COPPER_OZ_PER_FT2:g} oz, while the same conductor also "
                        f"carries {load.describe()}. Which of these segments is the "
                        "net's current path is not a fact this rule can read: a "
                        "signal or sense branch off load-bearing copper is not "
                        "judged by the net's whole current, so this row reports the "
                        "segments instead of calling them an overload (issue #84). "
                        "Confirm which segments are in the current path — if one of "
                        f"them is, {shortfall}, and a contract that states one "
                        "current for the whole net cannot say which segment it means"
                    ),
                    evidence=[
                        f"net {primary!r}: {where}",
                        f"layer {layer.layer_id} ({layer_name}): "
                        f"{len(segments)} segment(s) at {width:.4f} mil, "
                        f"{total:.2f} mil total, spanning ({box[0]:.1f}, "
                        f"{box[1]:.1f}) to ({box[2]:.1f}, {box[3]:.1f})",
                        f"IPC-2221: k={OUTER_K if outer else INNER_K}, "
                        f"ΔT={TEMP_RISE_C:g} °C, thickness {COPPER_THICKNESS_MIL} mil "
                        f"→ required width {needed:.4f} mil for {amps:g} A",
                        load.evidence(),
                    ]
                    + [
                        f"segment {segment.id!r}: {segment.width:.4f} mil, "
                        f"{segment.length:.2f} mil, ({segment.start.x:.1f}, "
                        f"{segment.start.y:.1f}) to ({segment.end.x:.1f}, "
                        f"{segment.end.y:.1f})"
                        for segment in segments
                    ]
                    + (
                        [f"one conductor: {' ≡ '.join(repr(n) for n in members)}"]
                        if len(members) > 1
                        else []
                    ),
                    target=FindingTarget(
                        net_refs=list(members),
                        measurement=_measurement("width", width, [layer.layer_id]),
                    ),
                )
            )
        return findings

    def _unknown(
        self,
        ctx: PcbReviewContext,
        net: str,
        amps: float,
        where: str,
        *,
        missing: str,
    ) -> Finding:
        """One UNKNOWN row, as an INFO finding (钉 6 — see the module docstring).

        **Why INFO rather than a four-state :class:`~boardwise.rules.base.Outcome`.**
        The schematic side can return ``Outcome`` objects because its harness
        aggregates them; the PCB runner's contract is ``check(ctx) -> list[Finding]``
        (:class:`~boardwise.rules.pcb.base.PcbRule`), and the finding array is
        what ``review-mark``, ``warning_triage`` and the module attribution all
        read. An UNKNOWN therefore travels as an **INFO** finding whose message
        **names the missing fact and the address it may be written at** — the
        same convention ``rules.railratings`` uses on the schematic side for the
        same reason ("a row that names where to supply it"), which is what keeps
        "this is not a defect" (the severity) distinct from "nobody said"
        (the message). ``rules.base.Outcome`` itself enforces that an UNKNOWN
        names its ``missing_fact``, and the message here is that fact verbatim.
        """
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"net {net!r} cannot be checked for ampacity: {missing}. "
                f"Write the current at requirements.signals[net={net}].range "
                f"(e.g. \"±3A\") or requirements.rails[net={net}].peakCurrent / "
                f".continuousCurrent — this rule never guesses a current out of "
                f"a track's shape"
                + (f" (the contract does declare {amps:g} A, {where})" if where else "")
            ),
            evidence=[f"net {net!r} on {ctx.board_title or 'this PCB document'}"],
            target=FindingTarget(net_refs=[net]),
        )


def _conductor_component(
    board: object, seed: str, drawn: list[str]
) -> set[str]:
    """Every net name that is physically one conductor with ``seed`` (516 A2).

    Successive hops, not one: two names can overlap the seed while a third
    overlaps only the second, so the closure is a BFS over 「copper that
    overlaps on a shared layer」 (:func:`net_clearance` → ``overlapping`` and
    ``distance <= 0``). A single-hop reading would judge a three-name conductor
    by the two names it reached from the declared one and leave the third's
    narrow copper unread — measured on 实板 A, where ``IRbus`` (schematic name)
    and ``IRBUS`` (PCB name) are one piece of copper and the closure is what
    makes the rule measure both.

    The walk only ever starts from a declared net and expands from copper that
    overlaps, so a board's isolated nets are never visited: ``net_clearance`` is
    asked once per (component member × drawn net) in the worst case, and a
    declared net with no same-layer overlap costs one pass over the drawn nets.
    """
    component = {seed}
    frontier = [seed]
    while frontier:
        current = frontier.pop()
        for other in drawn:
            if other in component:
                continue
            measured = net_clearance(board, current, other)
            if (
                measured is None
                or not measured.overlapping
                or measured.distance > 0.0
            ):
                continue
            component.add(other)
            frontier.append(other)
    return component


@dataclass
class _LoadBearing:
    """Copper of one conductor that could carry its current **instead of** a
    narrow segment (issue #84).

    ``kind`` is ``"track"`` (a trunk) or ``"pour"``; ``value`` is the width that
    answers the question, in mils — the track's own width, or the pour's mean
    width (:attr:`~boardwise.core.measure.LayerCopper.pour_mean_width`); and
    ``threshold`` is what it had to reach, kept because the message and the
    evidence both have to state the bar the reading cleared.
    """

    kind: str
    value: float
    layer_id: int
    threshold: float
    count: int = 0
    area: float = 0.0
    span: float = 0.0

    def describe(self) -> str:
        """The clause a branch row puts after 「also carries」."""
        if self.kind == "pour":
            return (
                f"{self.count} pour polygon(s) on layer {self.layer_id} whose "
                f"copper is {self.area:.0f} sq mil over a {self.span:.1f} mil "
                f"extent ({self.value:.1f} mil mean width)"
            )
        return (
            f"{self.count} track(s) of {self.value:.1f} mil on layer "
            f"{self.layer_id}"
        )

    def evidence(self) -> str:
        """The same reading as a row a reviewer can check against the bar."""
        bar = (
            f"the bar is max({BRANCH_WIDTH_RATIO:g} × narrowest, required) = "
            f"{self.threshold:.4f} mil"
        )
        if self.kind == "pour":
            return (
                f"load-bearing copper: {self.count} pour polygon(s) on layer "
                f"{self.layer_id}, {self.area:.0f} sq mil over a {self.span:.1f} "
                f"mil extent = {self.value:.4f} mil mean width — {bar}"
            )
        return (
            f"load-bearing copper: {self.count} track(s) at "
            f"{self.value:.4f} mil on layer {self.layer_id} — {bar}"
        )


def _load_bearing(
    copper: ConductorCopper, *, layer: LayerCopper, needed: float
) -> _LoadBearing | None:
    """The conductor's widest copper, when it is wide enough to be the current path.

    The bar (§ issue #84) is 岳's pair: copper qualifies when it is at least
    :data:`BRANCH_WIDTH_RATIO` times the **judged layer's** narrowest segment
    (:attr:`~boardwise.core.measure.LayerCopper.min_width`) *and* at least the
    width the declared current needs on that layer
    (:func:`required_width_mil`, which is why an inner layer asks for a different
    number than an outer one). Making the *narrowest* segment part of the bar is
    what keeps the gate about 「the conductor's copper comes in two widths」 rather
    than about 「some copper somewhere is wide」: on a net that is uniformly
    thin there is nothing for the bar to compare against and the row stays an
    ERROR.

    **The question is asked of the conductor, not of the layer.** Copper on
    another layer counts — a plane under a thin top-side tap is copper the same
    net's current can flow in, and the assumption issue #84 removes is
    「one net's current is the same all along it」, which is a statement about the
    net, not about a face. **Which layer the winning copper is on is then
    reported, and the judged layer wins whenever it can**: a reader checking
    「is the trunk really there」 should be sent to the layer in front of them when
    that layer's own copper qualifies, so the search takes two passes — the
    judged layer first, then the remaining layers lowest id first — and the layer
    id is in the row either way (实板 A's ``ACN`` pours both faces at ~122–123 mil,
    and the layer-2 row quotes the layer-2 pour rather than the marginally wider
    one on layer 1).

    Ties and ordering: within one layer the widest candidate wins, equal values
    keep the *track* over the pour, and the two passes are as above — so the
    answer is deterministic. Pads and vias are not candidates — they are not
    judged by this rule at all (留 D) and their numbers are not widths.
    """
    threshold = max(BRANCH_WIDTH_RATIO * layer.min_width, needed)
    # Two passes: the judged layer first (see the docstring), then the rest.
    order = [layer.layer_id] + [
        layer_id for layer_id in sorted(copper.layers) if layer_id != layer.layer_id
    ]
    seen: set[int] = set()
    best: _LoadBearing | None = None
    for layer_id in order:
        if layer_id in seen:
            continue
        seen.add(layer_id)
        other = copper.layers.get(layer_id)
        if other is None:
            continue
        if other.max_width >= threshold and (
            best is None or other.max_width > best.value
        ):
            best = _LoadBearing(
                kind="track",
                value=other.max_width,
                layer_id=layer_id,
                threshold=threshold,
                count=sum(1 for t in other.tracks if t.width >= threshold),
            )
        mean = other.pour_mean_width
        if mean >= threshold and (best is None or mean > best.value):
            best = _LoadBearing(
                kind="pour",
                value=mean,
                layer_id=layer_id,
                threshold=threshold,
                count=other.pour_count,
                area=other.pour_area,
                span=other.pour_span,
            )
        if best is not None:
            return best
    return best


def _width_classes(tracks: list, needed: float) -> list[tuple[float, list]]:
    """The segments narrower than ``needed``, grouped by stated width (#84).

    Grouped by the width the document states (exact float equality, the same
    reading :attr:`~boardwise.core.measure.LayerCopper.min_width` takes): a
    branch is routed at a design rule, so one rule width is one group and 27
    sense taps at 10 mil are one row rather than 27. Groups come out narrowest
    first and segments keep the board's own order, so the rows are deterministic.
    A segment exactly at ``needed`` is not undersized — the same ``>=`` epsilon
    the layer comparison uses.
    """
    groups: dict[float, list] = {}
    for track in tracks:
        if track.width + 1e-9 >= needed:
            continue
        groups.setdefault(track.width, []).append(track)
    return sorted(groups.items())


def _span(tracks: list) -> tuple[float, float, float, float]:
    """``(min_x, min_y, max_x, max_y)`` over a group of segments' endpoints."""
    xs: list[float] = []
    ys: list[float] = []
    for track in tracks:
        xs.extend((track.start.x, track.end.x))
        ys.extend((track.start.y, track.end.y))
    return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# pcb-voltage-spacing
# ---------------------------------------------------------------------------


def _gap(
    board,
    first: str,
    second: str,
    *,
    ignore_within_component: bool = False,
) -> ClearanceResult | None:
    """The closest measurable pair between two nets, read **where they can arc**.

    ``same_layer_only`` (517, the 516-A1 follow-up) is the primary reading:
    without it the plan-view 0.0 of two nets that cross somewhere buried 516-A1's
    real-board miss (``HV``↔``GND`` silently at 66.94 mil against a 100 mil
    band). When there is no
    same-layer pair at all the reading falls back to the plan-view projection —
    **only when that projection shares a layer**, which preserves 127b's meaning
    (a pair whose closest copper is at least a prepreg apart is not judged).

    ``ignore_within_component`` (issue #85) is threaded through to
    :func:`~boardwise.core.measure.net_clearance`: with it set, a pair of pads
    belonging to one placement — a gap the part's own selection fixed — is kept
    out of the reading, so the caller gets the nearest pair a **routing change**
    could move.
    """
    measured = net_clearance(
        board,
        first,
        second,
        same_layer_only=True,
        ignore_within_component=ignore_within_component,
    )
    if measured is None:
        projected = net_clearance(
            board, first, second, ignore_within_component=ignore_within_component
        )
        if projected is not None and projected.shares_a_layer:
            measured = projected
    return measured


class VoltageSpacing(PcbRule):
    """Are two nets of different voltage far enough apart?

    **The subject is every net this board draws whose voltage is knowable**, and
    knowable means one of three things: the contract states it
    (:func:`declared_voltages` reads ``requirements.rails[].voltage`` /
    ``targetVoltage``), the architecture enumeration establishes it
    (``architecture.chains.rails[].voltage``), or the net **is** ground — 0 V
    because it is the board's reference node, which is what makes the rule fire
    on a board with no contract at all (毕设FOC's PCB1 has three known rails and
    three ground islands and no contract whatsoever).

    For every unordered pair of those nets, once each:

    * the difference is looked up in :data:`VOLTAGE_SPACING_MIL`
      (:func:`required_spacing_mil`);
    * the pair is measured with :func:`~boardwise.core.measure.net_clearance`
      and **WARN** when the measured gap is under the band's number — unless the
      closest pair is one footprint's own pad pitch, which the rule reports
      **INFO** (issue #85, in full lower down).

    **Four states, and none of them is a guess.**

    * **voltage unknown** → **UNKNOWN** (INFO), naming the net and the sources
      that would establish it (the contract's ``rails[].voltage``, or a name /
      regulator fact the architecture enumeration could find). A net the
      enumeration listed as a rail but could not price is exactly this case, and
      毕设FOC's ``VCC`` / ``VCCA`` / ``VREF`` are three real instances of it.
    * **difference above :data:`SPACING_TABLE_MAX_V`** → **UNKNOWN** (INFO)
      naming IEC 60950, because that is where the simplified table stops being
      an authority. No fixture reaches it; the path is here so that the day one
      does, the answer is a named gap and not an extrapolated number.
    * **unmeasurable pair** (:func:`~boardwise.core.measure.net_clearance`
      returns ``None`` — the pair's only relationship is a shape inside a pour
      outline, and the pour's real clearance voids are not in the geometry model)
      → **dropped**. Not counted as a violation, not counted as a pass, and not
      reported as an UNKNOWN either: the missing thing there is in the
      *measurement library*, not in the design's facts, and telling an engineer
      to write a contract entry that already exists sends them nowhere. The one
      place the shape is pinned is the synthetic test below that builds two
      contained pours and asserts both halves — the library says ``None`` and
      the rule says nothing.
    * **two boards disagree about a rail of the same name** → dropped from the
      voltage map entirely, so the net reads UNKNOWN like any other unpriced
      net; picking one board's number would make a verdict depend on enumeration
      order.
    * **one node, or a cross-layer pair** → dropped, and **not** reported
      as an UNKNOWN either, for the reason the pour case above gives: the
      missing thing is in the *measurement* or in the *design's own wiring*,
      neither of which an engineer can fix by writing a contract entry. 127b.

    **A footprint's own pad pitch is reported, but never as a WARN** (issue #85,
    岳 2026-10-2x). The closest pair between two nets can be **one component's
    two pads** — an SOIC pin 1 on ``V`` against pin 2 on ``GND`` — and that
    distance is the footprint's pad pitch: the part's *selection* fixed it and
    no routing change can move it, so a WARN there is a work order for something
    the engineer cannot do. The row keeps the reading and states the reason
    (「footprint pitch, not a routing item」), and its severity is decided by the
    gap a layout change *could* close: the nearest pair **outside** that
    footprint (:func:`~boardwise.core.measure.net_clearance` with
    ``ignore_within_component`` set). Both numbers go in the message, the
    evidence and ``target.measurement`` (岳 asked for the same in #85's second
    reading: 实板 A's ``GND``↔``V`` is 94.5 mil at the footprint's own pads and
    114.7 mil outside, and the 114.7 already satisfies the 100 mil band).

    * **outside pair measurable and passing** → **INFO**: nothing here for a
      layout change to fix, and the message says so.
    * **outside pair measurable and failing** → **WARN**, about that number: the
      routing item is real even though the closest pair is not.
    * **no outside pair measurable** (their other copper shares no layer — the
      127b drop) → **INFO**, saying the external spacing is not asserted. The
      alternative would let a pair that 127b deliberately drops become a WARN
      the moment it also happens to be one footprint's own two pads.
    * **the two pads overlap** (``distance <= 0`` on a shared layer) → still the
      **WARN** it was: two different-voltage nets whose copper touches are a
      short, and a short is a defect whatever footprint it is inside.

    A **track against a footprint's pad** is *not* this case — a track belongs to
    no placement, so no component test can call the pair internal — and it stays
    the routing item it is. On 实板 A that is 6 of the 10 WARNs: four are same-
    component pad pairs (downgraded here) and two are a track against a pad of
    one component (unchanged).

    **Why B2 (uncoated external) is the column, and why a 0.0 mil reading is a
    WARN rather than an ERROR**, is written at :data:`VOLTAGE_SPACING_MIL`: the
    tool cannot see the coating, B2 is the largest bare-board column, and the
    measurement is already a pessimistic plan-view projection. The severity
    stays WARN because a spacing shortfall is a **compliance finding against the
    standard**, and the standard's own remedy (increase the gap, or state the
    product's coating class) is a design decision — while an overloaded
    conductor (:class:`TrackAmpacity`) is the safety one.

    **Two pairs are dropped before the table is consulted** (127b; the first
    clause narrowed by 516 A1):

    * **one node** (:func:`_same_potential`, 岳 2026-10-17) — a pair is one node,
      so spacing is not the question, in exactly two cases: **both are grounds**
      (the board's reference node, met in one place on purpose — 岳裁定 4's
      ``GND``/``PGND``), or **the two names are the same node the design tied
      together** — the contract prices them at one potential **and** their copper
      geometrically coincides (``overlapping`` and ``distance <= 0`` on a shared
      layer). The old 「the contract wrote the same voltage twice」 clause is
      **gone on its own**: ``HV`` = 311 V and ``U`` = 311 V are two pieces of
      copper at a nominal average of 311, and one can sit at 0 while the other is
      at 311, so their swing is 311 V. Such a pair is now judged by the **swing
      bound** ``max(|a|, |b|)`` — which is why the old
      ``required_spacing_mil(0.0) = 4 mil`` reading silently excused a 62.99 mil
      ``HV``↔``U`` gap on the real board that this band wants at 100. The
      coincidence half keeps its same-potential qualifier deliberately: two
      **different**-voltage nets whose copper overlaps are not a single-point
      join, they are a **short**, and 126c pins that they must still be reported
      (``+5V`` against ``GND`` at 0.0 mil is a WARN, not an exemption).
    * **cross-layer** — a pair whose closest copper shares no layer
      (:attr:`~boardwise.core.measure.ClearanceResult.shares_a_layer`). Its
      distance is a plan-view projection of shapes separated vertically by at
      least the prepreg, and judging that against a 4 mil band measures the
      board's thickness. This is the same misattribution 127a named: ``U6`` is a
      **bottom** placement whose footprint pads all carry ``layerId == 1``, so a
      layer-blind reading reported its ``+24V`` pad 10 as touching a layer-1 GND
      track.

    **The quantity judged is the swing bound for a nominally-equal pair, and the
    difference otherwise** (516 A1). A pair the contract prices at one potential
    (``HV``/``U``, both 311 V) is looked up at ``max(|a|, |b|)`` — what separates
    two conductors is the largest instantaneous difference their own signals can
    present, and for two nominally-equal magnitudes that bound is the magnitude
    itself (one at its extreme while the other is at zero). A genuinely
    different pair (24 V against 5 V) keeps its **difference** — 19 V — because
    that is the number the standard's own table is indexed by, and 126c pins the
    message to say ``19 V``. Both readings agree wherever the old code was right;
    the only rows whose verdict moves are the nominally-equal ones whose old
    ``4 mil`` reading silenced a real shortfall.

    **Measured on 毕设FOC after 127b** (``ProPrj_毕设FOC驱动板``, read-only, no
    contract): PCB1 prices five nets (``+24V`` 24 V, ``+5V`` 5 V, and the three
    ground islands at 0 V) and every one of their ten pairs is either dropped by
    one of the two clauses above or comfortably inside its band — **zero WARNs**,
    and three UNKNOWNs still naming the unpriced rails ``VCC`` / ``VCCA`` /
    ``VREF``. 126b's three WARNs on that board were all projections, on a board
    whose host DRC is clean. PCB3 examines two nets (``+24V`` and ``PGND``, 21.26
    mil apart) and passes; PCB2's whole output is a single UNKNOWN for ``VCC``.
    The numbers are pinned, with their derivation, in
    ``tests/test_126c_pcb_ipc_rules.py`` and ``tests/test_127b_blind_review_fixes.py``.
    """

    id = "pcb-voltage-spacing"
    title = "Nets at different voltages keep their IPC-2221 conductor spacing"
    level = "L1-pcb-geometry"
    source = (
        "IPC-2221 Table 6-1, column B2 (external conductors, uncoated), "
        "simplified — 4 / 24 / 50 / 100 mil by voltage band (岳 2026-10-06 裁："
        "IEC 60950 / IEC 60664-1 留作升级路径，本规则只管 clearance 不管 creepage）"
    )

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        volts, conflicts = declared_voltages(ctx, ctx.model)
        if ctx.model is None and not volts:
            return []  # nothing prices any net: nothing to say about any pair

        drawn = [net for net in board.net_names() if board.net(net).element_count]
        priced = {net: volts[net] for net in drawn if net in volts}
        grounds = sorted(net for net in drawn if is_ground_net(net))
        for net in grounds:
            priced.setdefault(net, (GROUND_VOLTS, "ground net — the board's 0 V reference"))

        rails = _rail_names(ctx, ctx.model)
        unknown = sorted(
            net for net in drawn
            if net not in priced and net in rails
        )
        findings = [
            self._unknown_voltage(ctx, net, conflicts) for net in unknown
        ]
        names = sorted(priced)
        for index, first in enumerate(names):
            for second in names[index + 1:]:
                row = self._one_pair(ctx, first, second, priced, conflicts)
                if row is not None:
                    findings.append(row)
        return findings

    def _one_pair(
        self,
        ctx: PcbReviewContext,
        first: str,
        second: str,
        priced: dict[str, tuple[float, str]],
        conflicts: list[str],
    ) -> Finding | None:
        """One WARN, one INFO, one silence, one drop — never anything else."""
        board = ctx.board
        volts_a, where_a = priced[first]
        volts_b, where_b = priced[second]
        differential = abs(volts_a - volts_b)
        same_nominal = differential <= 1e-9
        # 517 (the 516-A1 follow-up): judge the gap **where the two nets share a
        # layer**, not the plan-view minimum. A two-layer board always has some
        # crossing where two nets project onto each other at 0.0, and the
        # cross-layer early return below then dropped the whole pair — so the
        # same-layer gap was never looked at. On the real board that was four
        # silent 311 V high-side pairs (``HV``↔``GND`` 66.94 mil, ``HV``↔``U``
        # 62.99, ``HV``↔``V`` 62.99, ``HV``↔``W`` 37.89, all against 100).
        # ``_gap`` owns the reading and its two fallbacks; see its docstring.
        measured = _gap(board, first, second)
        if _same_potential(first, second, volts_a, volts_b, measured):
            # 516 A1 (岳 2026-10-17): 「同电位豁免只保留双地或几何重合」. Two nets
            # are **one node** — and spacing is not the question — in exactly two
            # cases, and 「the contract wrote the same number twice」 is not one:
            #
            # * **two grounds** (`is_ground_net` on both): the board's reference
            #   node, met in one place on purpose (岳裁定 4, 2026-10-07 — 毕设FOC's
            #   ``GND``/``PGND`` read 0.0 mil / ``overlapping=True``, a join the
            #   designer drew);
            # * **the same node the design tied together**: the contract prices
            #   the two names at one potential *and* their copper geometrically
            #   coincides (``overlapping`` and ``distance <= 0`` on a shared
            #   layer). The same-potential qualifier is load-bearing: two
            #   **different**-voltage nets whose copper overlaps are a **short**,
            #   not a single-point join, and 126c pins that they are still
            #   reported (``+5V``/``GND`` at 0.0 mil is a WARN).
            #
            # A pair that is merely *nominally* at one potential (``HV`` and ``U``
            # both declared 311 V) is **not** exempt: two switching-phase lines
            # whose averages are both 311 V swing 311 V apart instantaneously
            # (one at 0 while the other is at 311), and 516 measured ``HV``↔``U``
            # at 62.99 mil on the real board where IPC-2221 wants 100 — a true
            # WARN that the old equality test swallowed. It is judged below.
            return None
        if measured is None:
            # Two drops arrive here and both are 127b's:
            #
            # * the documented **pour blind spot** — see the class docstring's
            #   third paragraph for why this is not an UNKNOWN;
            # * a **cross-layer pair**: no shape pair of the two nets shares a
            #   layer, so any distance between them is a plan-view projection of
            #   shapes at least a prepreg apart — measured at 0.0 mil on 毕设FOC
            #   PCB1 for ``U6.10`` (``+24V``, bottom face) against a ``GND`` track
            #   on layer 1, on a board whose host DRC is clean. Judging that
            #   against a 4 mil IPC-2221 band measures the board's thickness, not
            #   its layout.
            #
            # 517 made the second case arrive here rather than at a
            # ``shares_a_layer`` test below: the measurement is taken with
            # ``same_layer_only``, so "no same-layer pair" is `None` and the
            # fallback below only adopts a projection that *does* share a layer.
            # The old post-hoc check is gone with it — it could never fire, and a
            # condition that cannot fire is a reader's trap.
            return None
        # 516 A1: for a pair the contract prices at **one** potential the quantity
        # judged is the **swing bound**, not the nominal difference. What
        # separates two conductors is the largest instantaneous difference their
        # own signals can present, and for two equal magnitudes that bound is the
        # magnitude itself — the case where one sits at its extreme while the
        # other sits at zero. Judging the *difference of averages* put two 311 V
        # phase lines into the 0–15 V band (``required_spacing_mil(0.0) = 4 mil``),
        # which is the bug this fixes: it is not a stricter reading of the
        # difference, it is the wrong quantity. A genuinely different pair keeps
        # its difference — that is the number the standard's table is indexed by.
        judged = max(abs(volts_a), abs(volts_b)) if same_nominal else differential
        needed = required_spacing_mil(judged)
        if needed is None:
            return self._unknown_band(
                ctx, first, second, volts_a, volts_b, where_a, where_b, judged
            )
        if measured.distance + 1e-9 >= needed:
            return None  # margin is silence
        touching = measured.overlapping and measured.distance <= 0.0
        # issue #85 (岳 2026-10-2x): 「最近对可能是同一颗器件自己的两个焊盘」.
        # When both elements of the closest pair are pads of **one** placement,
        # the number is that footprint's own pad pitch — fixed by the part's
        # selection, moveable by no routing change — so it is not the thing this
        # rule is for. The pair is still reported (a reader needs the number and
        # the reason), but the severity is decided by the gap a **layout** change
        # could close: the nearest pair outside that footprint.
        #
        # The `touching` guard is load-bearing, not decoration: two different-
        # voltage nets whose copper *overlaps* are a short (126c's ``+5V``/
        # ``GND`` at 0.0 mil is a WARN), and a short is a defect whatever
        # footprint it is inside.
        pitch = measured.within_one_footprint and not touching
        external = (
            _gap(board, first, second, ignore_within_component=True) if pitch else None
        )
        # INFO when the footprint is the whole story: either the external pair
        # is far enough (`external` passes the band) or there is no external
        # pair to judge at all (the two nets' other copper shares no layer — the
        # 127b drop, which must not turn into a WARN just because a pitch pair
        # exists). WARN whenever a routing item was measured and fails.
        external_passes = external is not None and external.distance + 1e-9 >= needed
        severity = "INFO" if pitch and (external_passes or external is None) else "WARN"
        statement = (
            f"share a nominal potential but are not one node, so the swing "
            f"bound max(|{volts_a:g}|,|{volts_b:g}|) = {judged:g} V is judged"
            if same_nominal
            else f"are {judged:g} V apart"
        )
        if pitch:
            # 岳's two readings of #85, in one row: the pair is named as a
            # footprint pitch **and** the nearest external pair is given, so a
            # reader can see which of the two numbers they are being asked about
            # — and whether there is anything left to ask.
            pitch_clause = (
                f" — but that pair is {measured.component_a}'s own two pads "
                f"(footprint pitch), which the part's selection fixed and no "
                f"routing change can move"
            )
            if external_passes:
                pitch_clause += (
                    f"; the nearest pair **outside that footprint** is "
                    f"{external.distance:.1f} mil ({external.element_a} / "
                    f"{external.element_b}), which satisfies the {needed:.1f} mil "
                    f"band this pair is judged by, so there is nothing here for a "
                    f"layout change to fix"
                )
            elif external is None:
                pitch_clause += (
                    "; no pair of these two nets outside that footprint is "
                    "measurable (their other copper shares no layer), so no "
                    "external spacing is asserted here"
                )
            else:
                pitch_clause += (
                    f"; the nearest pair **outside that footprint** is "
                    f"{external.distance:.1f} mil ({external.element_a} / "
                    f"{external.element_b}), which is under the {needed:.1f} mil "
                    f"band — that one is a routing item"
                )
        else:
            pitch_clause = (
                " — those two nets' copper touch on a shared layer, so this "
                "is a short, not merely a tight gap"
                if touching
                else ""
            )
        return Finding(
            rule_id=self.id,
            severity=severity,
            level=self.level,
            message=(
                f"net {first!r} ({volts_a:g} V) and net {second!r} ({volts_b:g} V) "
                f"{statement}: IPC-2221 (B2, uncoated) gives {needed:.1f} mil, "
                f"and the measured gap is {measured.distance:.1f} mil between "
                f"{measured.element_a} and {measured.element_b}"
                + pitch_clause
            ),
            evidence=[
                f"{first}: {volts_a:g} V — {where_a}",
                f"{second}: {volts_b:g} V — {where_b}",
                f"measured {measured.distance:.4f} mil "
                f"({measured.element_a} / {measured.element_b}), "
                f"overlapping={measured.overlapping}"
                + (
                    f"; both elements belong to {measured.component_a} "
                    "(within_one_footprint=True)"
                    if measured.within_one_footprint
                    else ""
                ),
                f"band {judged:g} V → required {needed:.4f} mil "
                "(IPC-2221 Table 6-1 column B2)"
                + (
                    f"; nominal difference {differential:g} V is not the "
                    "quantity judged (swing bound)"
                    if same_nominal
                    else ""
                ),
            ]
            + (
                [
                    f"the nearest pair **outside {measured.component_a}** "
                    f"(ignore_within_component=True): "
                    + (
                        f"{external.distance:.4f} mil ({external.element_a} / "
                        f"{external.element_b})"
                        if external is not None
                        else "unmeasurable — no same-layer pair and no plan-view "
                        "projection that shares a layer"
                    )
                ]
                if pitch
                else []
            )
            + conflicts,
            target=FindingTarget(
                net_refs=[first, second],
                measurement=_clearance_measurement(measured, external=external),
            ),
        )

    def _unknown_voltage(
        self, ctx: PcbReviewContext, net: str, conflicts: list[str]
    ) -> Finding:
        """The net with no **usable** voltage — an INFO, saying which kind of unknown.

        164c (F4/F5): the row is the reader's whole answer for an unpriced rail, so
        it must distinguish the two ways a net ends up here. 「no source names this
        voltage」 sends the engineer to the contract; 「two sources named two
        different voltages」 sends them to *reconcile* two statements — and a row
        that said the first while the second was true would send them to write a
        number that is already there. A note addressed to this net
        (:func:`_notes_about`) is what tells them apart, and the note's own text —
        both numbers, both boards — is quoted so the row is actionable on its own.
        """
        own = _notes_about(conflicts, net)
        if own and any(SOURCES_DISAGREE in note for note in own):
            message = (
                f"net {net!r} has conflicting voltage sources — "
                + "；".join(own)
                + ", so no voltage is asserted for it and its spacing against every "
                "other net cannot be judged: this row is UNKNOWN rather than a "
                "guess, and it takes two agreeing statements to close it"
            )
            evidence = [f"net {net!r} on {ctx.board_title or 'this PCB document'}"] + own
        elif own:
            message = (
                f"net {net!r} has no usable stated voltage — "
                + "；".join(own)
                + ", so its spacing against every other net cannot be judged and "
                "this row is UNKNOWN rather than a guess"
            )
            evidence = [f"net {net!r} on {ctx.board_title or 'this PCB document'}"] + own
        else:
            message = (
                f"net {net!r} has no established voltage, so its spacing against "
                "every other net cannot be judged — establish it at "
                f"requirements.rails[net={net}].voltage (or .targetVoltage) in the "
                "design-intent contract, or let the architecture enumeration find "
                "it (a net name that states its voltage, or a shelf regulator's "
                "output). This rule never reads a voltage out of a net's name"
                + ("; contract/architecture conflict on another net is noted in "
                   "this report's other rows" if conflicts else "")
            )
            evidence = [f"net {net!r} on {ctx.board_title or 'this PCB document'}"]
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=message,
            evidence=evidence,
            target=FindingTarget(net_refs=[net]),
        )

    def _unknown_band(
        self,
        ctx: PcbReviewContext,
        first: str,
        second: str,
        volts_a: float,
        volts_b: float,
        where_a: str,
        where_b: str,
        judged: float,
    ) -> Finding:
        """Beyond :data:`SPACING_TABLE_MAX_V` the simplified table has no answer.

        ``judged`` is the quantity the table refused (516 A1) — the swing bound
        for a nominally-equal pair, the difference otherwise — so a message about
        a pair the table cannot price names the number that was actually asked
        about.
        """
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"net {first!r} and net {second!r} are {judged:g} V apart, "
                f"above the {SPACING_TABLE_MAX_V:g} V the simplified IPC-2221 "
                "Table 6-1 column reaches, so no spacing is asserted here — that "
                "band is where clearance and creepage part company and IEC 60950 "
                "/ IEC 60664-1 is the authority (岳 2026-10-06 裁)"
            ),
            evidence=[
                f"{first}: {volts_a:g} V — {where_a}",
                f"{second}: {volts_b:g} V — {where_b}",
            ],
            target=FindingTarget(net_refs=[first, second]),
        )


def _same_potential(
    first: str,
    second: str,
    volts_a: float,
    volts_b: float,
    measured: ClearanceResult | None,
) -> bool:
    """Are these two nets **one node**, so spacing is not the question? (516 A1)

    岳 2026-10-17 裁定: 「同电位豁免只保留双地或几何重合」. Exactly two clauses,
    and the old 「same declared voltage」 test is gone — it is *not* one of them:

    * **both are ground nets** (:func:`is_ground_net`): a ground net is the
      board's reference node, so two of them are at one potential by definition
      of what a ground net *is*. This is 岳裁定 4's ``GND``/``PGND`` case, and it
      needs no measurement: the pair is one node whatever the copper does;
    * **the same node the design tied together**: the contract prices the two
      names at one potential **and** their copper geometrically coincides
      (``measured.overlapping`` and ``measured.distance <= 0.0``). The two names
      are then one conductor the designer joined on purpose, which is what 127b's
      ``GND``/``PGND`` story was about — generalised off grounds. (``net_clearance``
      only reports ``overlapping`` for a same-layer pair, so a plan-view crossing
      of two different layers never reaches this clause.)

    The same-potential qualifier on the second clause is **load-bearing**: two
    **different**-voltage nets whose copper overlaps are not a single-point join,
    they are a **short**, and the caller must still report them (126c pins that
    ``+5V`` against ``GND`` at 0.0 mil is a WARN, not an exemption). Reading the
    clause as bare geometry would swallow that short — the same class of silence
    this fix exists to remove.

    Anything else is **not** exempt. Two nets the contract prices at the *same
    number* — ``HV`` = 311 V and ``U`` = 311 V — are two different pieces of
    copper, and the number is a nominal average: one can sit at 0 while the other
    is at 311, so the swing between them is 311 V. 516 measured that pair at
    62.99 mil on the real board where the band wants 100. Treating the equal
    number as one node is what made that WARN vanish; the caller now judges such
    a pair by :func:`max` of the two magnitudes instead.
    """
    if is_ground_net(first) and is_ground_net(second):
        return True
    return bool(
        abs(volts_a - volts_b) <= 1e-9
        and measured is not None
        and measured.overlapping
        and measured.distance <= 0.0
    )


def _rail_names(ctx: PcbReviewContext, model: object) -> set[str]:
    """Every net either source calls a **rail**, priced or not.

    This is the filter that decides who gets an UNKNOWN row: without it, every
    one of PCB1's 92 drawn nets would be reported — ``CAN_RX`` is not a rail
    whose voltage is missing, it is a signal net and the rule has nothing to say
    about it. The test is deliberately the question both sources answer (「is
    this a rail?」), so a net the enumeration listed as a rail but could not
    price **is** reported, and a net neither source calls a rail is silence.

    The contract's half is a dict lookup. The enumeration's half costs a netlist
    walk, so it is computed **once per board** and passed in rather than asked
    per net — the enumeration is the same call `cli.checkup` makes, and calling
    it 92 times to answer one question would be the kind of accidental quadratic
    that turns a review into a coffee break. Failure is the narrower direction:
    an enumeration that raises contributes no names.
    """
    names = {
        str(getattr(rail, "net", "") or "").strip() for rail in _intent_rails(ctx)
    }
    names.discard("")
    if model is None:
        return names
    try:
        enumeration = generate_architecture(model, library=None)
    except Exception:  # noqa: BLE001 — a narrower reading, never a crash
        return names
    for rail in (enumeration.section.get("chains") or {}).get("rails") or []:
        net = str(rail.get("net") or "").strip()
        if net:
            names.add(net)
    return names


__all__ = [
    "COPPER_OZ_PER_FT2",
    "COPPER_THICKNESS_MIL",
    "GROUND_VOLTS",
    "INNER_K",
    "OUTER_K",
    "SOURCES_DISAGREE",
    "SPACING_ABOVE_MAX_BAND_MM_PER_V",
    "SPACING_TABLE_MAX_V",
    "TEMP_RISE_C",
    "VOLTAGE_SPACING_MIL",
    "TrackAmpacity",
    "VoltageSpacing",
    "declared_currents",
    "declared_voltages",
    "required_spacing_mil",
    "required_width_mil",
]