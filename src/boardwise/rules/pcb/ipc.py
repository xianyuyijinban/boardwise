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
  are facts the board carries, which is why it has 7 rows on that same fixture.

**Ampacity** (:class:`TrackAmpacity`) is the classic IPC-2221 conductor-current
relation, ``I = k·ΔT^0.44·A^0.725`` with the area ``A`` in square mils and the
current in amperes; ``k`` is 0.048 on an external conductor and 0.024 on an
internal one, the 10 °C rise and the 1 oz (1.378 mil) copper thickness are the
constants the standard's own table is quoted at. The rule inverts it — the
contract states the current, the board carries a width, and the comparison that
matters is 「does this width carry this current」 — and then takes the **minimum**
width per copper layer from :func:`~boardwise.core.measure.track_width_stats`,
because the narrowest segment of a net is the one that heats up, not the average.
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
thing 126b's supply-net inference rests on.

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

from ..base import Finding, FindingTarget
from ...core.architecture import generate_architecture
from ...core.measure import net_clearance, track_width_stats
from ...core.model import is_ground_net
from ...core.parts import load_parts
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
            value = parse_voltage_volts(raw)
            if value is None or value <= 0.0:
                continue
            if net in volts and volts[net][0] != value:
                notes.append(
                    f"net {net!r}: contract says {volts[net][0]:g} V "
                    f"({volts[net][1]}) but {slot} = {raw!r} says {value:g} V; "
                    "the first is kept and the second is ignored"
                )
                break
            volts[net] = (value, f"contract requirements.rails[net={net}].{slot} = {raw!r}")
            break

    for net, value, where in _architecture_rails(model):
        if net in volts:
            if volts[net][0] != value:
                notes.append(
                    f"net {net!r}: the contract says {volts[net][0]:g} V and the "
                    f"architecture enumeration says {value:g} V ({where}); the "
                    "contract is the requirement and wins, and the divergence is "
                    "reported rather than averaged"
                )
            continue
        volts[net] = (value, f"architecture.chains.rails[net={net}].voltage ({where})")

    return volts, notes


def _architecture_rails(model: object) -> list[tuple[str, float, str]]:
    """``(net, volts, where)`` per rail the drawing supports, from 044.

    Read through the public enumeration, with the shelf — the same shelf
    :func:`boardwise.rules.decap.cap_candidates_on` and 126b's supply-net
    inference read, through
    :func:`boardwise.rules.facts.default_library_path`, because the regulator
    half of the voltage inference is a shelf fact and a rule that read a
    different shelf would give a different answer.

    Every failure mode here degrades to **fewer known voltages**, never to an
    exception and never to a guess: a model of ``None`` enumerates nothing, an
    unreadable shelf reaches :func:`boardwise.core.parts.load_parts` as a path
    that does not resolve (which that function already reads as an empty shelf),
    and a rail whose voltage the enumeration could not establish comes back
    without one and is simply not in this list — its net then falls to UNKNOWN
    with a message saying no source names its voltage.
    """
    if model is None:
        return []
    from ..facts import default_library_path  # noqa: PLC0415 — read at call time

    try:
        library = load_parts(default_library_path())
    except Exception:  # noqa: BLE001 — a shelfless reading is a narrower one
        library = None
    try:
        enumeration = generate_architecture(model, library=library)
    except Exception:  # noqa: BLE001 — see above: never a crash on the report
        return []
    seen: dict[str, tuple[float, str]] = {}
    conflicting: set[str] = set()
    for rail in (enumeration.section.get("chains") or {}).get("rails") or []:
        net = str(rail.get("net") or "")
        value = rail.get("voltage")
        if not net or value is None:
            continue
        board = str(rail.get("board") or "")
        if net in seen:
            if seen[net][0] != float(value):
                conflicting.add(net)
            continue
        seen[net] = (float(value), board or "this project")
    return [
        (net, value, where) for net, (value, where) in seen.items()
        if net not in conflicting
    ]


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

    * a **readable** current (see :func:`declared_currents`) → one row per copper
      layer that carries the net's tracks: the required width
      (:func:`required_width_mil`) against the **minimum** measured width on
      that layer (:func:`~boardwise.core.measure.track_width_stats`), and
      **ERROR** when the measured one is narrower;
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
    printed in the message and a reviewer can disagree with any of them.

    **Measured on the ROBOT ctrl-FOC fixture** (``ProPrj_ROBOT ctrl FOC``, the
    contract's own ``range: "±3A"``): ``U+`` and ``W+`` both carry their phase
    current on 10 mil copper on all three of their layers (layers 1 / 2 / 16),
    so each yields three ERRORs — external needs 53.8 mil, internal layers need
    140.0 mil, and 10.0 is nowhere near either. That is the rule's true-positive
    case and it is exactly why the finding is an ERROR: three amps down a 10 mil
    trace on the outer layer is a conductor this standard says will run far past
    a 10 °C rise.
    """

    id = "pcb-track-ampacity"
    title = "A track is wide enough to carry its net's declared current"
    level = "L1-pcb-geometry"
    source = (
        "IPC-2221 conductor-current relation I = k·ΔT^0.44·A^0.725 "
        "(k = 0.048 external / 0.024 internal, ΔT = 10 °C, 1 oz = 1.378 mil), "
        "against the current declared in the design-intent contract and the "
        "per-layer minimum track width read off the board"
    )

    def check(self, ctx: PcbReviewContext) -> list[Finding]:
        board = ctx.board
        if board is None:
            return []
        currents = declared_currents(ctx)
        if not currents and not _declared_net_names(ctx):
            # No contract, or a contract that names no net with a current slot at
            # all: **no subject**. 92 nets on 毕设FOC's PCB1 all lack one, and 92
            # UNKNOWN rows saying so would be a wash (the module docstring's
            # argument).
            return []
        findings: list[Finding] = []
        drawn = [net for net in board.net_names() if board.net(net).element_count]
        for net in sorted(_declared_net_names(ctx) & set(drawn)):
            if net in currents:
                findings.extend(self._one_net(ctx, net, *currents[net]))
            else:
                findings.append(self._unknown(
                    ctx, net, 0.0, "", missing=_unreadable_current_reason(ctx, net)
                ))
        return findings

    def _one_net(
        self, ctx: PcbReviewContext, net: str, amps: float, where: str
    ) -> list[Finding]:
        """Every row for ``net``: one per copper layer with tracks, or one row."""
        board = ctx.board
        stats = track_width_stats(board, net)
        if not stats.per_layer:
            return [
                self._unknown(
                    ctx,
                    net,
                    amps,
                    where,
                    missing=(
                        f"the per-layer track widths of net {net!r} — it carries "
                        f"{stats.track_count} tracks but none of them names a "
                        "copper layer, so there is no width to compare"
                        if stats.track_count
                        else f"a track on net {net!r} — this PCB document carries "
                        "it as pads and pours only"
                    ),
                )
            ]
        findings: list[Finding] = []
        for layer_id in sorted(stats.per_layer):
            layer = stats.per_layer[layer_id]
            outer = _is_outer(board, layer_id)
            if outer is None:
                findings.append(
                    self._unknown(
                        ctx,
                        net,
                        amps,
                        where,
                        missing=(
                            f"whether copper layer {layer_id} is external or "
                            f"internal (the document defines no LAYER record for "
                            f"it), which is what picks the IPC-2221 constant for "
                            f"net {net!r}"
                        ),
                    )
                )
                continue
            needed = required_width_mil(amps, inner=not outer)
            if layer.min_width + 1e-9 >= needed:
                continue  # margin is silence, not a finding
            name = board.layer_name(layer_id)
            findings.append(
                Finding(
                    rule_id=self.id,
                    severity="ERROR",
                    level=self.level,
                    message=(
                        f"net {net!r} carries {amps:g} A ({where}) but its "
                        f"{'external' if outer else 'internal'} copper on layer "
                        f"{layer_id} ({name}) is {layer.min_width:.1f} mil wide at "
                        f"its narrowest, and IPC-2221 at ΔT={TEMP_RISE_C:g} °C / "
                        f"{COPPER_OZ_PER_FT2:g} oz needs {needed:.1f} mil — "
                        f"{needed / layer.min_width:.1f}x over the copper that "
                        "is there"
                    ),
                    evidence=[
                        f"net {net!r}: {where}",
                        f"layer {layer_id} ({name}), {layer.track_count} track(s), "
                        f"min width {layer.min_width:.4f} mil, "
                        f"total length {layer.total_length:.2f} mil",
                        f"IPC-2221: k={OUTER_K if outer else INNER_K}, "
                        f"ΔT={TEMP_RISE_C:g} °C, thickness {COPPER_THICKNESS_MIL} mil "
                        f"→ required width {needed:.4f} mil",
                    ],
                    target=FindingTarget(
                        net_refs=[net],
                        measurement=_measurement("width", layer.min_width, [layer_id]),
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


# ---------------------------------------------------------------------------
# pcb-voltage-spacing
# ---------------------------------------------------------------------------


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
      and **WARN** when the measured gap is under the band's number.

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

    **Why B2 (uncoated external) is the column, and why a 0.0 mil reading is a
    WARN rather than an ERROR**, is written at :data:`VOLTAGE_SPACING_MIL`: the
    tool cannot see the coating, B2 is the largest bare-board column, and the
    measurement is already a pessimistic plan-view projection. The severity
    stays WARN because a spacing shortfall is a **compliance finding against the
    standard**, and the standard's own remedy (increase the gap, or state the
    product's coating class) is a design decision — while an overloaded
    conductor (:class:`TrackAmpacity`) is the safety one. A measured gap of
    exactly 0.0 on a shared copper layer says so in the message, because "these
    two nets' copper touches" is a different fact from "these two are too close"
    and a reader needs to know which one they are looking at.

    **Measured on 毕设FOC** (``ProPrj_毕设FOC驱动板``, read-only, no contract):
    PCB1 examines five priced nets (``+24V`` 24 V, ``+5V`` 5 V, and the three
    ground islands ``GND`` / ``AGND`` / ``PGND`` at 0 V) in ten pairs: three come
    out WARN, seven pass, and three UNKNOWNs name the unpriced rails ``VCC`` /
    ``VCCA`` / ``VREF``. PCB3 examines two nets (``+24V`` and ``PGND``, 21.26 mil
    apart) and reports one pass and nothing else. PCB2 has only ``GND`` priced
    and one unpriced rail, so its whole output is a single UNKNOWN for ``VCC``.
    The numbers are pinned, with their derivation, in
    ``tests/test_126c_pcb_ipc_rules.py``.
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
        """One WARN, one silence, one drop — never anything else."""
        board = ctx.board
        volts_a, where_a = priced[first]
        volts_b, where_b = priced[second]
        differential = abs(volts_a - volts_b)
        needed = required_spacing_mil(differential)
        if needed is None:
            return self._unknown_band(
                ctx, first, second, volts_a, volts_b, where_a, where_b
            )
        measured = net_clearance(board, first, second)
        if measured is None:
            # The documented pour blind spot: dropped, not reported. See the
            # class docstring's third paragraph for why this is not an UNKNOWN.
            return None
        if measured.distance + 1e-9 >= needed:
            return None  # margin is silence
        touching = measured.overlapping and measured.distance <= 0.0
        return Finding(
            rule_id=self.id,
            severity="WARN",
            level=self.level,
            message=(
                f"net {first!r} ({volts_a:g} V) and net {second!r} ({volts_b:g} V) "
                f"are {differential:g} V apart, which IPC-2221 (B2, uncoated) "
                f"gives {needed:.1f} mil, and the measured gap is "
                f"{measured.distance:.1f} mil between {measured.element_a} and "
                f"{measured.element_b}"
                + (
                    " — those two nets' copper touch on a shared layer, so this "
                    "is a short, not merely a tight gap"
                    if touching
                    else ""
                )
            ),
            evidence=[
                f"{first}: {volts_a:g} V — {where_a}",
                f"{second}: {volts_b:g} V — {where_b}",
                f"measured {measured.distance:.4f} mil "
                f"({measured.element_a} / {measured.element_b}), "
                f"overlapping={measured.overlapping}",
                f"band {differential:g} V → required {needed:.4f} mil "
                "(IPC-2221 Table 6-1 column B2)",
            ]
            + conflicts,
            target=FindingTarget(
                net_refs=[first, second],
                measurement=_measurement("clearance", measured.distance),
            ),
        )

    def _unknown_voltage(
        self, ctx: PcbReviewContext, net: str, conflicts: list[str]
    ) -> Finding:
        """The net whose voltage no source names — an INFO, naming the address."""
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"net {net!r} has no established voltage, so its spacing against "
                "every other net cannot be judged — establish it at "
                f"requirements.rails[net={net}].voltage (or .targetVoltage) in the "
                "design-intent contract, or let the architecture enumeration find "
                "it (a net name that states its voltage, or a shelf regulator's "
                "output). This rule never reads a voltage out of a net's name"
                + ("; contract/architecture conflict on another net is noted in "
                   "this report's other rows" if conflicts else "")
            ),
            evidence=[f"net {net!r} on {ctx.board_title or 'this PCB document'}"],
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
    ) -> Finding:
        """Beyond :data:`SPACING_TABLE_MAX_V` the simplified table has no answer."""
        differential = abs(volts_a - volts_b)
        return Finding(
            rule_id=self.id,
            severity="INFO",
            level=self.level,
            message=(
                f"net {first!r} and net {second!r} are {differential:g} V apart, "
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