"""RAIL ratings (092 A2b): the intent's rail declarations against the board's parts.

091 A2a wired the **repair direction** out of the design intent; this batch
spends the same channel on two questions a board's own fields cannot answer,
because a rating is not on the board: *is this capacitor's rated voltage above
the rail it sits on* (``pwr-cap-voltage-rating``), and *how much does this LDO
dissipate* (``path-ldo-dissipation``). Both are read off two documents that
already exist — the contract (``requirements.rails[].targetVoltage`` and
``.continuousCurrent``) and the shelf (the catalog's ``Voltage Rating`` field,
the part's own ``ldo`` facts) — and neither rule reads a disk: the contract
arrives as :class:`~boardwise.core.designintent.IntentSource`, exactly as it
does for :func:`~boardwise.rules.params.repair_directions`.

**The discipline, and it is the whole batch** (092 §二):

* **a measurement is always reported, as INFO** — the ratio for a capacitor,
  the drop in volts for an LDO. Silence about a number nobody stated is what
  makes a report read as "rated", so the row is filed even when there is
  nothing to complain about. An INFO finding never blocks a write
  (#55 裁决 B) and never moves the verdict or the exit code;
* **only a limit this build can state is a WARN**: a capacitor whose rating is
  *below* its rail's voltage — a certain over-voltage, not a matter of taste —
  and an LDO whose computed dissipation exceeds a ``max_dissipation_mw`` the
  shelf actually declares, with the datasheet page it came from;
* **what cannot be read is UNKNOWN, and the row names where to supply it** —
  the same family as ``needs_datasheet`` ("C? 的耐压（所在轨 +12V=12V）") and as
  A2a's ``intent-missing`` ("write it into
  `requirements.rails[net=…].continuousCurrent`"). An UNKNOWN
  is not a pass and not a failure; it is a work order with an address. It is
  filed as an **INFO finding** so the report a reviewer opens carries it —
  the four-state row (``Outcome.state``) keeps saying UNKNOWN, and an INFO
  severity is what says "this is not a defect";
* **no derating standard is invented.** The comparison is ``rating >= rail``
  and ``P <= declared limit``, nothing else: no 80 %-of-rating rule, no
  "typical SOT-223 is good for 1 W" house number, no temperature or ripple
  correction. A margin this tool made up would be a verdict wearing a
  measurement's clothes, and the numbers that decide either row travel in the
  message from the two documents that state them.

Both rules take the intent at construction (``intent=``), so they are the
second and third entries of :data:`boardwise.engines.review.INTENT_RULES` and
ride A2a's ``_rules_for`` seam: a reading that names no contract gets the
module-level instances, whose ``intent`` is ``None``, and these two then have
**no subject at all** — the rail declarations *are* the subject — so they file
nothing and a reading without a contract is byte-for-byte what it was.

Where the numbers come from, in reading order, and why:

* **the rail's voltage** — the contract's ``rails[net=…].targetVoltage``
  first (it is the requirement), else the drawing's own verdict for that net
  (:func:`boardwise.core.power_domains.infer_net_domains`: a net name that
  states its voltage, an LDO's output fact or decoded suffix). That is the
  same reading every other voltage-aware rule makes; a rail the two documents
  price *differently* is not judged here — one of them is the requirement and
  the other is the drawing, and which of the two is wrong is the architecture
  self-consistency question A3 owns;
* **a capacitor's rating** — the shelf entry's own named field
  (``Voltage Rating`` and its spellings; the catalog stores it verbatim, the
  way :meth:`boardwise.core.parts.PartEntry.resistance` reads its own
  field), else a voltage token in the board's ``Value`` field
  (``100nF/50V``), else the MPN's own code field
  (:func:`boardwise.core.values.mpn_voltage_rating` — an **anchored** reading,
  071 §1 C: the token must say which figures are the rating);
* **an LDO's dissipation limit** — ``facts.ldo.max_dissipation_mw`` and
  nothing else: the limit is a datasheet claim, and a rule that reached for a
  bolted-on curve would be inventing the standard this batch refuses to
  invent. No such fact (every entry today) means the measurement is reported
  and nothing is judged.
"""

from __future__ import annotations

import re

from ..core.circuitspec import PROVENANCE_AI
from ..core.designintent import (
    INTENT_MISSING,
    SECTION_RAILS,
    IntentSource,
    write_path,
)
from ..core.model import Component, DesignModel
from ..core.parts import PartEntry
from ..core.power_domains import domain_of, infer_net_domains, ldo_output_pin
from ..core.values import mpn_voltage_rating, parse_current_amps, parse_voltage_volts
from .base import Finding, Outcome
from .decap import looks_like_capacitor
from .facts import FactsRule
from .unproven import unproven_nets, unproven_outcome

LEVEL = "L2-facts"

#: The shelf's own names for a part's rated voltage, in reading order. The
#: catalog is a **named-field** store — it writes ``"Voltage Rating": "50V"``
#: verbatim, in whichever spelling the listing used — so this reader asks for
#: the field rather than mining the description, and the same two-language list
#: :meth:`PartEntry.resistance` keeps for its own field. A key that is present
#: but unreadable falls through to the next reading; nothing here guesses.
_RATING_PARAM_KEYS: tuple[str, ...] = (
    "Voltage Rating",
    "Voltage Rated",
    "Rated Voltage",
    "Rated voltage",
    "额定电压",
    "耐压",
)

#: A ``Value`` field split into the tokens a voltage may be stated in:
#: ``100nF/50V``, ``10uF 25V``, ``1uF,16V``. The split is on anything that is
#: not part of a number or a unit letter, so a token is the smallest piece that
#: could carry a unit — and :func:`parse_voltage_volts` still has to accept it
#: whole (``10UF`` is refused: no ``V``, and ``U`` is a capacitance prefix).
_VALUE_TOKEN_RE = re.compile(r"[0-9A-Za-z.]+")


def _rail_entry(intent: IntentSource, net: str):
    """The contract's declaration for one rail, or ``None``."""
    return intent.document.entry(SECTION_RAILS, net)


def _contract_file_note(intent: IntentSource, lead: str = "，") -> str:
    """Where the contract lives — quoted by every row that asks for a slot.

    A document somebody built in memory has no path, and the carrier says so
    (``IntentSource.path`` is empty); the row then points at the one place the
    report always prints it rather than inventing a file name — A2a's own
    wording for the same case.
    """
    if intent.path:
        return f"{lead}写进 {intent.path}"
    return f"{lead}写进 checkup 的 intent.contract.file"


def rail_voltage(
    intent: IntentSource,
    guesses: dict,
    net: str | None,
) -> tuple[float | None, str, str]:
    """``(volts, source, why_not)`` for one rail — the contract, then the drawing.

    The contract's answer wins when it states one: it is the requirement, and a
    judgement that used the drawing's own inference instead would be comparing
    the board with itself. Without one, the net's own vote stands in
    (:func:`infer_net_domains`), and the source string that comes back quotes
    whichever rule of evidence answered — a net name that states its voltage,
    or an LDO's output fact. ``why_not`` is a ready-made missing fact naming
    **both** places an answer could come from, because "nobody states this
    rail's voltage" has two different fixes (a drawing that names it, or a
    contract that declares it) and the reader has to be told which one this
    reading is missing.
    """
    rail = _rail_entry(intent, net) if net else None
    stated = (rail.value("targetVoltage") if rail is not None else "").strip()
    slot = write_path(SECTION_RAILS, net or "?", "targetVoltage")
    if stated:
        volts = parse_voltage_volts(stated)
        if volts is not None and volts > 0:
            return volts, f"合同 {slot} = {stated!r}", ""
        return None, "", (
            f"{INTENT_MISSING}: 合同声明 {slot} = {stated!r}，不是本工具能读量的写法"
            f"（要 `24V`、`3.3V` 这样的拼法）{_contract_file_note(intent)}"
        )
    volts, source, why = domain_of(guesses, net)
    if volts is not None:
        return volts, source, ""
    return None, "", (
        f"{why}；{INTENT_MISSING}: 合同也没声明 {slot}{_contract_file_note(intent)}"
    )


def cap_voltage_rating(
    comp: Component, entry: PartEntry | None
) -> tuple[float | None, str]:
    """``(volts, where it came from)`` — a capacitor's rating, strongest first.

    Three readings, in the shelf-catalog-then-board order this repository uses
    for every quantity (``PartEntry.resistance``: the shelf's named field
    first, the board's own shorthand second, and never an MPN's bare digits):

    1. **the shelf entry's own field** (``Voltage Rating``, ``Voltage Rated``,
       …). The catalog states it verbatim with its unit; this is the strongest
       source and it is why the reader takes an entry at all;
    2. **a voltage token in the board's ``Value`` field** — ``100nF/50V``. An
       editor writes ratings there, and the token has to be a whole voltage to
       count (``10UF`` is not one);
    3. **the MPN's code field** (:func:`mpn_voltage_rating`) — anchored, per
       071 §1 C: the figures must sit in the ``value+tolerance+voltage``
       shape, which is the shape this codebase already refuses a *value*
       reading for. Reading bare digits in a part number as a rating is the
       enumeration that failed (issues #18, #22-#26) and this reader does not
       re-open it.

    Nothing readable is ``(None, "")``, and the caller then reports UNKNOWN
    naming the part and the rail — never a guessed rating, which would be a
    verdict built on nothing.
    """
    if entry is not None:
        for key in _RATING_PARAM_KEYS:
            raw = str(entry.params.get(key) or "").strip()
            if not raw:
                continue
            volts = parse_voltage_volts(raw)
            if volts is not None and volts > 0:
                return volts, f"货架条目 {entry.key} 的 {key} = {raw!r}"
    value = comp.value or ""
    for token in _VALUE_TOKEN_RE.findall(value):
        volts = parse_voltage_volts(token)
        if volts is not None and volts > 0:
            return volts, f"板上 Value 字段 {value!r} 里的 {token!r}"
    decoded = mpn_voltage_rating(comp.mpn or "")
    if decoded is not None:
        volts, field = decoded
        return volts, (
            f"料号 {comp.mpn!r} 的电压码 {field!r}"
            "（value+tolerance+voltage 字段，071 §1 C 的锚点写法）"
        )
    return None, ""


def _looks_like_capacitor(comp: Component, library) -> bool:
    """The shared predicate, with a parsed component's fields (as ``decap`` does)."""
    return looks_like_capacitor(
        comp.designator,
        comp.value or "",
        comp.mpn or "",
        comp.lcsc_part or "",
        library,
        footprint=comp.footprint or "",
    )


def _draft_note(entry) -> str:
    """052 §4: a requirement nobody confirmed is a hint, and the row says so.

    The *severity* is not moved by this: an intent states a requirement, and
    grading by provenance is A3's (091 A2a's own line). What travels is the
    caveat, in the words 052 §4 uses — the row may not read as a statement
    about a design nobody has signed.
    """
    if getattr(entry, "provenance", "") == PROVENANCE_AI:
        return "；注意：这条轨声明是 ai_asserted 草稿（052 §4），确认前不要照改"
    return ""


class CapVoltageRating(FactsRule):
    """RAIL-1: a capacitor on a declared rail is rated for that rail's voltage.

    The subject is the **contract's rails** — this rule has nothing to say
    without one — and for each rail it judges every capacitor whose pin sits on
    that net. Three states, one row each (092 §二):

    * ``rating >= rail`` — **INFO**, the ratio quoted (``50 V / 12 V = 4.17x``).
      A measurement, and the point of it is that a reader can disagree with the
      numbers; no derating coefficient is applied, because coining one is the
      invention this batch refuses;
    * ``rating < rail`` — **WARN**. An over-voltage is a fact about the two
      numbers, not a matter of taste: no margin policy is needed to state it;
    * the rating, or the rail's voltage, cannot be read — **UNKNOWN**, naming
      the part and the rail (``C? 的耐压（所在轨 +12V=12V）``) and the three
      places a rating can be written, or the two places a rail's voltage can.
    """

    id = "pwr-cap-voltage-rating"
    title = "A capacitor's voltage rating clears the rail it sits on"
    level = LEVEL
    source = (
        "the design intent's rail declaration (requirements.rails[].targetVoltage) "
        "against the capacitor's own rating, read from the shelf's Voltage Rating "
        "field, the board's Value field, or the MPN's code field; no derating "
        "standard is applied (092 A2b)"
    )

    def __init__(self, library=None, intent: IntentSource | None = None) -> None:
        super().__init__(library)
        #: The contract this reading was handed, or ``None`` — handed in at
        #: construction like 091 A2a's ``ValueMpnMatch.intent``, because
        #: ``BUILTIN_RULES`` outlives any single run and a rule may not read a
        #: disk.
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity)
            for outcome, severity in self._rows(model)
            if severity is not None
        ]

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        if self.intent is None:
            # The rail declarations *are* the subject. No contract, no subject,
            # no row — which is what keeps a reading that names no intent
            # byte-for-byte what it was (091 A2a's zero-movement reading).
            return []
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for rail in self.intent.document.rails:
            caps = sorted(
                (
                    comp
                    for comp in model.components.values()
                    if any(pin.net == rail.net for pin in comp.pins)
                    and _looks_like_capacitor(comp, self.library)
                ),
                key=lambda comp: comp.designator,
            )
            if not caps:
                continue
            volts, volts_source, volts_why = rail_voltage(self.intent, guesses, rail.net)
            for comp in caps:
                rows.append(self._row(model, rail, comp, volts, volts_source, volts_why))
        return rows

    def _row(
        self,
        model: DesignModel,
        rail,
        comp: Component,
        volts: float | None,
        volts_source: str,
        volts_why: str,
    ) -> tuple[Outcome, str | None]:
        ref = comp.designator
        nets = [rail.net, *(pin.net for pin in comp.pins)]
        # Issue #19: "this capacitor sits on that rail" is read from a net's
        # members, and the per-page merge welds net names blind — on such a
        # name the capacitor may be the other board's part, so the row refuses
        # rather than judging a rail this page may not draw.
        welded = unproven_nets(model, nets)
        if welded:
            return (
                unproven_outcome(
                    self.id,
                    ref,
                    welded,
                    what=(
                        f"whether {ref} sits on rail {rail.net!r} and what that "
                        "rail's voltage is"
                    ),
                    evidence=[f"{ref} pin{pin.number} @ {pin.net}" for pin in comp.pins],
                ),
                "INFO",
            )
        rating, where = cap_voltage_rating(comp, self.entry_for(comp))
        identity = f"value {comp.value!r}" + (f"，料号 {comp.mpn!r}" if comp.mpn else "")
        if volts is None:
            # The rail has no voltage anywhere, so no comparison exists — but a
            # rating that *is* readable is still stated, because "50 V against
            # an unknown rail" and "nothing is known at all" are two different
            # work orders.
            known = f"（耐压 {rating:g} V，来源 {where}）" if rating is not None else ""
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}（{identity}）{known}：所在轨 {rail.net} 的电压读不出，"
                        f"所以耐压无从比对 —— {volts_why}"
                    ),
                    evidence=[
                        f"{ref} pin{pin.number} @ {pin.net}" for pin in comp.pins
                    ],
                    missing_fact=volts_why,
                ),
                "INFO",
            )
        rail_label = f"所在轨 {rail.net} = {volts:g} V"
        if rating is None:
            missing = f"{ref} 的耐压（{rail_label}）"
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}（{identity}）的耐压读不出（{rail_label}）—— 三个取值口"
                        "都没读到：货架条目的 Voltage Rating 字段、板上 Value 字段里的"
                        "电压（如 `100nF/50V`）、料号的 value+tolerance+voltage 电压码。"
                        f"needs_datasheet 同族点名：{missing}"
                    ),
                    evidence=[
                        f"{ref} pin{pin.number} @ {pin.net}" for pin in comp.pins
                    ],
                    missing_fact=missing,
                ),
                "INFO",
            )
        ratio = rating / volts
        evidence = [
            f"{ref} 耐压 {rating:g} V —— 来源：{where}",
            f"{rail.net} 轨压 {volts:g} V —— 来源：{volts_source}",
        ]
        if rating >= volts:
            return (
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=ref,
                    message=(
                        f"{ref}: 耐压 {rating:g} V ≥ {rail_label}，比值 {ratio:.2f}x"
                        f"（测量行：{where}；轨压 {volts_source}）—— 不套降额系数，"
                        "本工具不发明降额标准"
                    ),
                    evidence=evidence,
                ),
                "INFO",
            )
        return (
            Outcome(
                rule_id=self.id,
                state="VIOLATION",
                subject=ref,
                message=(
                    f"{ref}: 耐压 {rating:g} V < {rail_label}，比值 {ratio:.2f}x —— "
                    f"确定的越限（不是降额口味：两个数都在这里——耐压来源 {where}；"
                    f"轨压来源 {volts_source}）。换一颗耐压不低于该轨的件，"
                    "或把该轨的声明改对"
                    + _draft_note(rail)
                ),
                evidence=evidence,
            ),
            "WARN",
        )


class LdoDissipation(FactsRule):
    """RAIL-2: an LDO's dissipation, from the declared rail voltages and current.

    ``P = (Vin - Vout) x I``: ``Vin``/``Vout`` are the two rails the part's own
    facts name pins on (the input pin from ``supply_pins``, the output pin from
    :func:`boardwise.core.power_domains.ldo_output_pin`), and ``I`` is the
    contract's ``continuousCurrent`` for the **output rail** — the load the
    design declares, not one this rule guessed from the board.

    * both voltages known, current declared — **INFO** with the numbers, or
      **WARN** when the shelf's ``ldo.max_dissipation_mw`` declares a limit and
      ``P`` exceeds it (the citation travels in the message);
    * both voltages known, no usable current — the drop is still a measurement
      and is reported (**INFO**), and the missing answer is its own **UNKNOWN**
      row naming ``requirements.rails[net=…].continuousCurrent`` — the
      ``intent-missing`` family 091 A2a established;
    * either voltage unknown — **UNKNOWN**, naming what is missing.

    What this rule does **not** do: it reports no limit the shelf has not
    declared, and it does not reach for a package-level rule of thumb — "不发明
    降额标准", the same discipline the capacitor rule keeps. Whether a part *is*
    an LDO at all is ``path-ldo-dropout``'s conclusion (from the same shelf
    facts), and a part whose category is not ``ic.ldo`` is skipped here rather
    than reported twice in two wordings.
    """

    id = "path-ldo-dissipation"
    title = "An LDO's dissipation estimate is within the declared limit"
    level = LEVEL
    source = (
        "P = (Vin - Vout) x I, with the rail voltages from the design intent or "
        "the drawing's own inference and I from the contract's continuousCurrent; "
        "the limit is the shelf's ldo.max_dissipation_mw fact and nothing else "
        "(092 A2b)"
    )

    def __init__(self, library=None, intent: IntentSource | None = None) -> None:
        super().__init__(library)
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity)
            for outcome, severity in self._rows(model)
            if severity is not None
        ]

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        if self.intent is None:
            return []
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for comp in self.ics(model):
            entry = self.entry_for(comp)
            if entry is None or entry.category != "ic.ldo" or not entry.facts:
                continue
            ldo = entry.facts.get("ldo") or {}
            in_pin = next(
                (
                    pin
                    for record in entry.facts.get("supply_pins", [])
                    for pin in record.get("pins", [])
                ),
                None,
            )
            out_pin = ldo_output_pin(entry)
            if in_pin is None or out_pin is None:
                # Which pins are the input and output is `path-ldo-dropout`'s
                # own UNKNOWN (from the same facts), and reporting the same gap
                # in a second wording is how two rules start disagreeing.
                continue
            in_net = _pin_net(comp, str(in_pin))
            out_net = _pin_net(comp, str(out_pin))
            welded = unproven_nets(model, (in_net, out_net))
            if welded:
                rows.append((
                    unproven_outcome(
                        self.id,
                        comp.designator,
                        welded,
                        what="the headroom between its input and output rails",
                        evidence=[
                            f"{comp.designator} pin{in_pin} @ {in_net}",
                            f"{comp.designator} pin{out_pin} @ {out_net}",
                        ],
                    ),
                    "INFO",
                ))
                continue
            vin, vin_source, vin_why = rail_voltage(self.intent, guesses, in_net)
            vout, vout_source, vout_why = rail_voltage(self.intent, guesses, out_net)
            if vin is None or vout is None:
                missing = "；".join(reason for reason in (vin_why, vout_why) if reason)
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: 耗散估算算不出 —— 输入/输出轨的电压"
                            f"有一个读不出：{missing}"
                        ),
                        evidence=[
                            f"{comp.designator} pin{in_pin} @ {in_net}",
                            f"{comp.designator} pin{out_pin} @ {out_net}",
                        ],
                        missing_fact=missing,
                    ),
                    "INFO",
                ))
                continue
            drop = vin - vout
            if drop <= 0:
                # A non-positive headroom is `path-ldo-dropout`'s subject (it
                # judges it against the part's dropout fact) and a dissipation
                # estimate of zero or less states nothing.
                continue
            drop_text = (
                f"压差 Vin − Vout = {drop:.4g} V（{in_net} {vin:g} V（{vin_source}）"
                f" − {out_net} {vout:g} V（{vout_source}））"
            )
            evidence = [
                f"{comp.designator} {entry.mpn or entry.lcsc} pin{in_pin} @ {in_net} = {vin:g} V",
                f"{comp.designator} {entry.mpn or entry.lcsc} pin{out_pin} @ {out_net} = {vout:g} V",
                f"{comp.designator}: {drop_text}",
            ]
            out_rail = _rail_entry(self.intent, out_net)
            declared = (
                str(out_rail.value("continuousCurrent")).strip()
                if out_rail is not None else ""
            )
            amps = parse_current_amps(declared) if declared else None
            if amps is None or amps <= 0:
                missing = _current_slot_note(self.intent, out_net, declared)
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: {drop_text} —— 耗散 P=(Vin−Vout)×I "
                            f"还差电流的声明；{missing}"
                        ),
                        evidence=evidence,
                    ),
                    "INFO",
                ))
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: 耗散估算算不出 —— {missing}"
                        ),
                        evidence=evidence,
                        missing_fact=missing,
                    ),
                    "INFO",
                ))
                continue
            p_mw = drop * amps * 1000.0
            limit = (ldo.get("max_dissipation_mw") or {})
            if not isinstance(limit, dict) or limit.get("mw") is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: {drop_text} × {amps:g} A = "
                            f"{p_mw / 1000.0:.4g} W（输出轨 {out_net} 的 "
                            f"continuousCurrent = {declared!r}）—— 货架条目没声明 "
                            "maxDissipation，只报测量值，不编封装限值"
                            "（本工具不发明降额标准）"
                        ),
                        evidence=evidence,
                    ),
                    "INFO",
                ))
                continue
            limit_mw = float(limit["mw"])
            provenance = str(limit.get("provenance") or "")
            text = (
                f"{comp.designator}: P = {drop_text} × {amps:g} A = "
                f"{p_mw / 1000.0:.4g} W vs 货架声明的限值 {limit_mw:g} mW"
                f"（{provenance}）"
            )
            if p_mw > limit_mw:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=comp.designator,
                        message=(
                            f"{text} —— 超出限值 {p_mw / limit_mw:.2f}x：这是拿得准的"
                            "越限（限值有出处），不是降额口味。降输出电流、分散耗散，"
                            "或换封装/换件"
                        ),
                        evidence=evidence,
                    ),
                    "WARN",
                ))
                continue
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=comp.designator,
                    message=f"{text} —— 测量行：在限值内（{p_mw / limit_mw:.2f}x）",
                    evidence=evidence,
                ),
                "INFO",
            ))
        return rows


def _pin_net(comp: Component, number: str) -> str | None:
    for pin in comp.pins:
        if pin.number == number:
            return pin.net
    return None


def _current_slot_note(intent: IntentSource, out_net: str, declared: str) -> str:
    """The missing current, in the ``intent-missing`` family (091 A2a's wording).

    One producer, two sentences: a slot nobody wrote, and a slot whose text is
    not a current this build reads — the second is *not* "no declaration", and
    a reader who is told the wrong one of those will edit the wrong thing.
    """
    slot = write_path(SECTION_RAILS, out_net, "continuousCurrent")
    if declared:
        return (
            f"{INTENT_MISSING}: 输出轨 {out_net} 的 {slot} = {declared!r} 不是本工具"
            f"能读的电流（要 `5A`、`500mA` 这样的拼法）{_contract_file_note(intent)}"
        )
    return (
        f"{INTENT_MISSING}: 输出轨 {out_net} 的 {slot} 没声明"
        f"{_contract_file_note(intent, lead=' —— ')}"
    )
