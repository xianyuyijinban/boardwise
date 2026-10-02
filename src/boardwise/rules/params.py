"""PARAM rules (task 011d sec.3.2-3.4): LED current, divider output, RC
cutoff, and the value-vs-MPN cross-check.

All four are four-state rules over the netlist model, the shelf, and (where
voltages matter) the domain inference. Division of labour worth stating in
code, because two rules look at the same resistor:

- ``param-led-current`` judges the LED's series resistance using the
  **board's value field** (what the schematic declares), against the oracle's
  window for the 3V3 domain (revision of 2026-09-19, replacing the earlier
  current computation);
- ``param-value-mpn-match`` judges whether that declaration agrees with the
  part's MPN. A board can pass one and fail the other: a 1k board value
  gives a legal current while contradicting a 470-ohm MPN -- exactly the
  golden board's U3.

That last rule reports a contradiction and **not** a repair (052 §2.1): its
finding names both candidate fixes and carries no suggested value, because
which field is the wrong one is a design decision (048's ruling). **Since 071 §1
it only accuses where the reading has a syntactic anchor** (oracle ruling
2026-09-29, option C): both sides of the comparison are strings, so the reading
has to be a *code field* -- an E-96/厚声 code with its tolerance letter, the
trade's mid-letter notation in its canonical form, or an EIA three-digit code in
a token that states a package size -- and a reading without one contradicts the
board in silence (UNKNOWN, "字符串解码无锚点，低置信"). Matching a declared value
never requires an anchor: this gate withholds verdicts, it does not tighten
them.

**Since 091 A2a the direction comes from the design intent where the intent states
one.** A contract may carry `decisions[].value` for a designator — the quantity the
design *chose* — and then the finding says **改料号/重选件** (the design value is
what the board is meant to be) instead of naming both repairs and choosing
neither; the sentence quotes the answer's provenance, because who said so decides
whether it is a statement or a question (052 §4). No such value, and both repairs
are named again with an `intent-missing` line pointing at the key to write (that
token comes from `core.designintent`, its one home: the report prints it too, and
`rules` may not import `engines`). All of it goes through :func:`repair_directions`,
one function for this rule's one production path, and **none of it moves the
verdict**: severity, the four states and the finding's target are what they were —
an intent states a direction, and grading by intent is A3's.
"""

from __future__ import annotations

import math

from ..core.circuitspec import PROVENANCE_USER_STATED, PROVENANCE_VERIFIED
from ..core.designintent import (
    INTENT_MISSING,
    SECTION_DECISIONS,
    IntentSource,
    write_path,
)
from ..core.model import Component, DesignModel, is_ground_net
from ..core.power_domains import domain_of, infer_net_domains
from .base import Finding, FindingTarget, Outcome
from .facts import FactsRule
from .unproven import unproven_nets, unproven_outcome
from .values import (
    decode_eia_3digit,
    mpn_resistance_candidates,
    mpn_value_code_anchor,
    parse_capacitance_farads,
)

LEVEL = "L2-facts"

#: The oracle's window for an indicator LED's series resistance, in ohms,
#: **inclusive**. Ruling of 2026-09-19: in the 3V3 domain the series resistance
#: must sit in [470, 2200] ohm, judged by the resistance value (4.7k is the
#: counter-example and violates); every other domain is UNKNOWN.
#:
#: Judging the *resistance* replaced the earlier current computation (floor
#: 0.5 mA, ceiling 50% of the datasheet If max). Three reasons, in the order
#: they matter: the window is the design intent a reviewer can read straight
#: off the BOM; it needs no LED facts, so an LED with no shelf entry is still
#: gradeable; and the old rule's verdict on the golden board's own 1k part was
#: UNKNOWN (Vf 2.7-3.2 V straddled the floor) for a part the oracle had just
#: ruled *correct* -- a rule that cannot say "fine" about the reference design
#: is measuring the wrong number.
LED_SERIES_BOUNDS_3V3 = (470.0, 2200.0)

#: The domain the window is stated for, and how far a KNOWN net voltage may
#: sit from it and still count as that domain.
LED_WINDOW_DOMAIN_V = 3.3
LED_DOMAIN_TOLERANCE_V = 0.05

#: How far a board's value field may sit from its MPN's decoded value before
#: the disagreement is called a contradiction, by part kind (task 015 batch 2;
#: oracle ruling of 2026-09-21, decision A with category thresholds -- his
#: words for the complaint: "不要定的太死"). The judged quantity is
#: ``max(declared, decoded) / min(declared, decoded)``, so both directions
#: read the same; a ratio strictly below the threshold is OK, at or above it
#: is the violation it always was.
#:
#: Three measured facts produced exactly these two numbers:
#:
#: * **The families do not share a scale.** The parts the oracle ruled *not*
#:   wrong are U10/U14 (1k ohm declared against a 470-ohm MPN, 2.13x) and
#:   C28/C29/C36/C42/C44 (100 nF against 2.2 uF and 10 nF, 10x-22x). One
#:   global 3x threshold only rescues the resistors: the capacitors still
#:   report, and the graduation measurement stayed broken. Splitting by kind
#:   is what the evidence supports.
#: * **2.13x sits on both sides of a ruling.** U10/U14 pass here, while the
#:   golden board's U3 -- also 1k against 470 -- is a defect the oracle signed
#:   in 011c. A threshold in the middle of that pair cannot exist, so the
#:   golden board's U3 turning OK is a **cost taken knowingly**: it moves from
#:   detected to missed in the dev measurement, and its 011c record is left
#:   alone rather than rewritten to fit.
#: * **25x is interpolated, not measured.** No capacitor witness above 22x
#:   exists anywhere in the repository, so the ceiling is the project lead's
#:   interpolation over the evidence above, confirmed by the oracle. If a
#:   real board ever produces a larger disagreement, this is the number to
#:   re-ask about.
MPN_AMPLITUDE_TOLERANCE_R = 3.0
MPN_AMPLITUDE_TOLERANCE_C = 25.0

#: 052 §2.1: a contradiction names **both** repairs and the rule chooses
#: neither. Fixing the board value to the MPN's decoded value is one option
#: (the part number is the true one); swapping in a part that matches the board
#: value is the other (the design value is the true one) -- and 048 ruled on 17
#: thesis-sampling parts where the *MPN column* was the wrong field, so writing
#: the decoded value back is not a safe default. A fixed template, so both
#: directions are always named in the same words whatever the amplitude or the
#: part; the amplitude tolerances above are a noise policy, not evidence that
#: the part number is the accurate side.
#:
#: **Anchored only, since 071 §1 C**: a row quotes this template only when the
#: reading that contradicts the board carries a syntactic anchor (a code field --
#: see :data:`boardwise.rules.values.ANCHOR_E96_LETTER` and its siblings). The
#: unanchored case is UNKNOWN instead, because a string that merely contains
#: digits may not, by itself, tell a designer their BOM line is wrong.
MPN_REPAIR_DIRECTIONS = (
    " -- two repairs fit this contradiction and this rule picks neither "
    "(052 §2.1, 修复方向由设计意图决定): fix Value to {mpn_value} "
    "(若料号属实), or fix the MPN/LCSC to a part matching {board_value} "
    "(若设计值属实)"
)

#: The direction the design stands behind, in the words a reader acts on (091
#: A2a). `user_stated` is the engineer's own decision, so the sentence states;
#: `verified_recipe` is a recipe somebody checked, so it names its basis;
#: everything weaker is a draft and the sentence **asks** instead — 052 §4's rule
#: (an `ai_asserted` fact may ride along as a hint, never as a ruler). The three
#: tokens come from the contract's own vocabulary (`core.circuitspec`), and a
#: rank missing from this table is read as the draft, which is the safe default.
_DIRECTION_WORDS: dict[str, str] = {
    PROVENANCE_USER_STATED: "按设计决策应改料号",
    PROVENANCE_VERIFIED: "按已验证配方（verified_recipe）应改料号",
}
_DIRECTION_DRAFT = "AI 草稿认为应改料号，请确认"


def _stated_quantity(text: str, kind: str) -> float | None:
    """A contract's machine value, read by the parser that reads the board's.

    Two notations, one quantity: the shipped ctrl FOC contract writes the design's
    value as ``0.1Ω`` while that board's own field says ``100mΩ``. Comparing the
    two *strings* would call the decision a disagreement with the board, so the
    comparison goes through the value parsers — the same reading the rule already
    makes of the two fields it is comparing (048's lesson, one field over).
    """
    if kind == "capacitor":
        return parse_capacitance_farads(text)
    return parse_resistance_ohms(text)


def repair_directions(
    designator: str,
    *,
    mpn_value: str,
    board_value: str,
    board_quantity: float | None,
    kind: str,
    intent: IntentSource | None,
) -> str:
    """What to do about a Value-vs-MPN contradiction — the one place that says it.

    The rule used to know the contradiction and not the repair (052 §2.1: both
    directions, the choice left to the reader). Since 091 A2a the design intent
    can answer the direction, and this function is the **single** production path
    of that answer, so the states cannot drift into two wordings (#55's
    ``_grade_new_findings`` shape, and 052 §2.1's own lesson that one rule with
    two candidate repairs must not format them twice).

    Three states:

    * **no contract** (``intent is None``) — byte-for-byte the sentence this rule
      has ended with since 052: both repairs, in the same words, no direction. A
      reading that carries no intent document must not change at all;
    * **the contract states a machine-readable value for this designator**
      (``decisions[subject=…].value``) — the direction is the *design's*, and it is
      **改料号/重选件**: the design value is what the board is meant to be, so the
      MPN/LCSC column is the field to re-pick. The wording names the answer's
      provenance — who said so decides whether this is a statement (``user_stated``)
      or a question (``ai_asserted``, 052 §4). If the decision's value does not
      agree with the board's own field, the sentence says so rather than pretending
      the board side is fine;
    * **no such value** — no decision for this designator, or one whose prose states
      no machine-readable number: both repairs again, plus an `intent-missing` line
      naming the file and the key to write. That is the honest answer, because
      "which side is wrong" is exactly what is still undecided.
    """
    both = MPN_REPAIR_DIRECTIONS.format(
        mpn_value=mpn_value, board_value=board_value
    )
    if intent is None:
        return both
    decision = intent.decision(designator)
    where = write_path(SECTION_DECISIONS, designator, "value")
    file_note = (
        f"，出处 {intent.path}" if intent.path
        else "，出处见 checkup 的 intent.contract.file"
    )
    stated = (decision.stated_value if decision is not None else "") or ""
    if stated:
        draft = decision.provenance not in _DIRECTION_WORDS
        words = _DIRECTION_WORDS.get(decision.provenance, _DIRECTION_DRAFT)
        text = (
            f" -- 修复方向由设计意图决定（052 §2.1）：设计决策 {where} = {stated}"
            f"（provenance {decision.provenance}{file_note}）—— {words}"
            f"：把 MPN/LCSC 换成与 {stated} 相符的件（重选件）"
        )
        if draft:
            text += "；ai_asserted 是草稿（052 §4），确认前不要照改"
        else:
            text += f"；把 Value 改成 MPN 解码值 {mpn_value} 会把电路改错"
        stated_quantity = _stated_quantity(stated, kind)
        if stated_quantity is None:
            text += (
                f"。注意：决策的值 {stated} 不是本规则能读的量"
                "——两个字段都要按决策正文人工核实"
            )
        elif board_quantity is None or not math.isclose(
            stated_quantity, board_quantity, rel_tol=1e-3
        ):
            text += (
                f"。注意：决策的值 {stated} 与板上的值 {board_value} 也不一致"
                "——Value 字段同样要按设计决策核实"
            )
        return text
    return (
        both
        + f"；{INTENT_MISSING}: 位号 {designator} 的 `decisions[].value` 没声明 —— "
        + f"写进 `{intent.path or '（合同路径见 checkup 的 intent.contract.file）'}`"
        + f" 的 `{where}`"
        + (
            f"（已有决策正文，缺的是机读值；provenance {decision.provenance}）"
            if decision is not None else
            "（decisions[] 里还没有这个位号）"
        )
        + "；方向由设计决策定，未定之前两边都列 —— 工具只提问，不改写"
    )


def parse_resistance_ohms(value: str) -> float | None:
    """Re-exported helper: ``rules/values.py`` holds the one ohm parser (071 §2).

    The re-export used to point at the L1 copy in ``rules/connectivity.py``,
    which is why this module read board values with a *different* grammar from
    the one it read MPNs with. Both now come from ``values.py``.
    """
    from .values import parse_resistance_ohms as _parse

    return _parse(value)


def _kind_of(comp: Component, entry) -> str | None:
    """``"resistor"`` / ``"capacitor"`` / None -- shelf category first, then
    the value's unit. The unit inference is what lets the golden board's U3
    (a v1-era shelf entry with no category) be judged at all: its value
    ``1kΩ`` names a resistance."""
    category = (entry.category if entry is not None else "") or ""
    if category in ("resistor", "capacitor"):
        return category
    value = comp.value or ""
    if parse_resistance_ohms(value) is not None:
        return "resistor"
    if parse_capacitance_farads(value) is not None:
        return "capacitor"
    return None


#: Engineering prefixes for :func:`_human_value`, largest scale first. The two
#: spans differ because the value parsers do: a resistor value may be a bare
#: number (``470``) while a capacitor value *must* name its unit, so a
#: capacitor candidate always ends in ``pF``/``nF``/``uF``/``mF``.
_RESISTOR_PREFIXES = ((1e6, "M"), (1e3, "k"), (1.0, ""))
_CAPACITOR_PREFIXES = ((1e-3, "mF"), (1e-6, "uF"), (1e-9, "nF"), (1e-12, "pF"))


def _human_value(quantity: float, kind: str) -> str:
    """A decoded SI quantity written the way a person writes the value.

    ``1000.0`` ohms becomes ``"1k"`` and ``1e-7`` farads becomes ``"100nF"``,
    so the quantity a message quotes can be typed back into the editor
    unchanged: it is the text of the "fix Value" candidate in
    :data:`MPN_REPAIR_DIRECTIONS` (the anchored contradiction), and it is what
    the UNKNOWN row's ``missing_fact`` quantifies the disagreement with. The
    round trip still matters either way, because it is the value an operator
    would paste into ``--after`` (``tests/test_016_*`` pins the round trip
    across the whole EIA code space).

    Six significant digits is deliberate: the quantities this formatter sees
    are EIA codes (a two-digit mantissa times a power of ten), so six digits
    render every one of them exactly and strip the float noise that dividing
    by 1e-6 or 1e3 would otherwise print.
    """
    prefixes = _RESISTOR_PREFIXES if kind == "resistor" else _CAPACITOR_PREFIXES
    for scale, suffix in prefixes:
        if quantity >= scale:
            return f"{quantity / scale:.6g}{suffix}"
    # Unreachable for decoded EIA codes (the smallest resistor is 10 ohm and
    # the smallest capacitor is 10 pF, both above their last prefix); kept so
    # the function is total rather than raising inside a rule.
    return f"{quantity:.6g}"


def _closest_reading(
    readings: list[tuple[float, str, str]], declared: float | None
) -> tuple[float, str, str]:
    """The candidate the comparison is made against: the one nearest the board's own.

    A mid-letter MPN can have several legitimate readings (task 043), and the
    comparison — and therefore the amplitude a violation quotes — has to be made
    against a specific one. The board's own declared value is the only evidence
    that distinguishes them, so the nearest reading (by amplitude, i.e. by
    ``|log|`` distance) is the one: a part whose readings are ``{4.7k, 74.7k}``
    on a board that says ``4.7k`` is being compared against 4.7 kΩ, and the row
    carries the other readings as evidence so the choice is visible.

    The anchor travels with the chosen candidate (071 §1 C): which reading a
    contradiction rests on decides whether the rule may accuse at all. Since 078
    A1 that anchor belongs to a **located** value segment -- one the package-size
    strip actually took content off (``CRCW0603``10``K0``FKEA``) -- and to
    nothing else, so ``074K7``'s two readings now carry none between them: a
    Yageo date code in front of ``4K7`` is not a size, the run was never
    located, and ``74K7`` may no longer accuse on its own (issue #32). Which
    reading is *closest* is a separate question and this is still how it is
    answered.

    A value the parser could not read (``None``), a non-positive one, or a
    non-finite one has no distance to anything: the smallest reading is used, and
    that path's message says the value field is unparsable anyway. The non-finite
    case is issue #31: ``item[0] / inf`` is ``0.0`` and ``math.log`` of it raises
    ``ValueError``, so an infinite declared value -- which ``float`` produces in
    silence from a long enough run of digits -- took the whole review down here
    before the parsers refused it and before this guard existed (both gates stay:
    this function is called with values from callers that are not the parsers).
    """
    if declared is None or not math.isfinite(declared) or declared <= 0:
        return readings[0]
    return min(readings, key=lambda item: abs(math.log(item[0] / declared)))


class ValueMpnMatch(FactsRule):
    """PARAM-4: the board's value field agrees with the MPN's decoded value.

    The decoder is a whitelist (EIA three-digit codes, package sizes guarded,
    the trade's mid-letter and exponent notations); an MPN that decodes to
    nothing is UNKNOWN ("contains no decodable value"), never a guessed match.
    R24/R27 have no MPN at all and stay UNKNOWN for exactly that reason.
    **UNKNOWN is the verdict for a refused notation too** (``R`` as the decimal
    point, a voltage rating after the value, an electrolytic part number --
    task 015): those strings do carry a value, but not one this decoder reads,
    and hard-reading them turned a 330 uF part into a 3.3e-11 F contradiction.

    A *readable* MPN that disagrees with the board's value is judged by
    amplitude, not by equality (ruling of 2026-09-21, see
    :data:`MPN_AMPLITUDE_TOLERANCE_R`): a small ratio is OK **with its
    amplitude quoted in the message**, so the row says what was seen instead
    of passing in silence, and it enters no precision denominator.

    **Since 071 §1 a bigger ratio is UNKNOWN, not a violation** -- the
    bleed-stop of oracle ruling 2026-09-29. The whole verdict rests on two
    strings (the Value field, and an MPN read by an enumeration of vendor
    notations), and an enumeration of private shapes never ends: with one
    **Since 071 §1 C an accusation also needs the reading to be anchored** --
    oracle ruling 2026-09-29, taken after the full stop ("every decoded string
    reading is UNKNOWN") turned out to silence nineteen signed defects on the
    oracle's own sampling board (rulings A2/A4, `reviewsets/毕设滤波采样_*.json`).
    The enumeration of vendor shapes is abandoned either way -- with one shape
    patched (#18), an external harness produced five more within hours, across
    four manufacturers and three voltage-code positions (#25) -- but the *line*
    is no longer "is it a string" (everything is) and not "which shape is it"
    (which never ends). It is: **is the value stated in a code field?** Three
    ways a token can say so, and a reading that carries none contradicts the
    board in silence:

    * :data:`~boardwise.rules.values.ANCHOR_E96_LETTER` -- four figures in a
      field whose grammar names a letter at them (``RK73H1JTTD1002F``'s
      ``1002F``, ``0603WAF1002T5E``'s field with its ``T`` tail, the shunt
      field between a tolerance letter and its ``R``);
    * :data:`~boardwise.rules.values.ANCHOR_MID_LETTER` -- the mid-letter
      notation in its canonical form (``CRCW060310K0FKEA`` -> ``10K0``);
    * :data:`~boardwise.rules.values.ANCHOR_PACKAGE_CONTEXT` -- an EIA
      three-digit code in a token that also states a package size
      (``CC0603``KRX7R9BB104, ``GRM188``R71C104KA01D).

    A **match** never needs an anchor, and neither does the amplitude waiver
    below: this gate withholds verdicts, it does not tighten them.

    **A violation reports a contradiction, and since 091 A2a a direction when the
    design intent states one** (052 §2.1, after 048): the finding's target carries
    the board's own value as ``expected_before`` and an **empty**
    ``suggested_after`` — the repair that would fill that field is a *value* write,
    and the direction the message may now state is 改料号/重选件, which is a
    different change kind (052 §2.1's closed `--direction mpn`). The message goes
    through :func:`repair_directions`, the one production path of that wording, so
    three states — no contract, a decision with a machine value, a decision without
    one — cannot drift apart. Severity, verdict and the target are untouched by it:
    an intent states a *direction*, and A3 is where intent reaches grading.
    ``edit plan`` still refuses to build a plan without a direction being stated —
    see ``cli._cmd_edit_plan_value``."""

    id = "param-value-mpn-match"
    title = "The board's value field matches the MPN's decoded value"
    level = LEVEL
    source = (
        "house rule (EIA three-digit code cross-check); the contradiction is "
        "a BOM/schematic mismatch, not a hazard. Since 071 §1 C (oracle ruling "
        "2026-09-29) a disagreement is a WARN only when the MPN reading carries "
        "a syntactic anchor (a code field: E-96/厚声 letter, canonical "
        "mid-letter form, EIA code with package context); an unanchored "
        "reading is UNKNOWN"
    )

    def __init__(
        self,
        library=None,
        intent: IntentSource | None = None,
    ) -> None:
        super().__init__(library)
        #: The design intent this reading was handed (091 A2a), or ``None`` for a
        #: reading that carries none — which is every path that does not name one,
        #: and it keeps this rule byte-for-byte what it was. Handed in at
        #: construction rather than read off the disk: a rule judges a netlist, and
        #: where a contract lives (and which one) is the caller's question, not the
        #: rule's (`engines.review` builds the per-run instance).
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _rows(self, model: DesignModel) -> list[tuple]:
        rows: list[tuple] = []
        for comp in model.components.values():
            entry = self.entry_for(comp)
            kind = _kind_of(comp, entry)
            if kind is None:
                continue  # neither resistor nor capacitor by any evidence
            # 043: a resistor MPN may state its value in the trade's **mid-letter**
            # notation (`4K7` = 4.7 kΩ), which is not an EIA code at all — and the
            # EIA reader used to mine a wrong code out of it (`RC0603FR-074K7L`
            # came back as "074" = 70 kΩ, task 043's reported WARN). The
            # mid-letter readings are tried first, for resistors only — and they
            # are asked for *with their anchors* (071 §1 C), because the reading a
            # contradiction rests on is what decides whether the rule may accuse.
            candidates: list[tuple[float, str, str]] = (
                mpn_resistance_candidates(comp.mpn or "") if kind == "resistor" else []
            )
            readings: list[tuple[float, str]] = [
                (value, text) for value, text, _anchor in candidates
            ]
            code, code_anchor = mpn_value_code_anchor(comp.mpn or "")
            if not readings and code is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: its MPN "
                            f"{comp.mpn!r} contains no decodable EIA value "
                            "code (or two conflicting ones, or is written in "
                            "a notation that is not EIA)"
                        ),
                        missing_fact=(
                            f"a decodable EIA value code in the MPN of "
                            f"{comp.designator}"
                        ),
                    ),
                    None,
                ))
                continue
            if kind == "resistor":
                declared = parse_resistance_ohms(comp.value or "")
                if candidates:
                    decoded, notation, anchor = _closest_reading(candidates, declared)
                    label = f"value {notation!r}"
                else:
                    decoded = decode_eia_3digit(code, 1.0)
                    anchor = code_anchor
                    label = f"code {code}"
                unit = "Ω"
            else:
                declared = parse_capacitance_farads(comp.value or "")
                decoded = decode_eia_3digit(code, 1e-12)
                anchor = code_anchor
                label = f"code {code}"
                unit = "F"
            # An MPN whose notation has several legitimate readings says so: the
            # comparison below is made against the one nearest the board's own
            # value, and a reader has to be able to see the others.
            notation_evidence = (
                [
                    "MPN notation readings: "
                    + " / ".join(f"{value:g} ({text})" for value, text in readings)
                ]
                if len(readings) > 1
                else []
            )
            if declared is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: the MPN decodes to "
                            f"{decoded:.4g} {unit} but the board's value "
                            f"field {comp.value!r} is empty or unparsable"
                        ),
                        missing_fact=(
                            f"a parseable value field on {comp.designator}"
                        ),
                    ),
                    None,
                ))
                continue
            # Nominal equality with a relative tolerance first: both numbers
            # are nominal declarations of the same part, so 470 vs 470.0 is a
            # match. Everything else is judged by amplitude (2026-09-21).
            if math.isclose(declared, decoded, rel_tol=1e-3):
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: board value "
                            f"{declared:.4g} {unit} matches MPN "
                            f"{label} ({decoded:.4g} {unit})"
                        ),
                        evidence=list(notation_evidence),
                    ),
                    None,
                ))
            else:
                tolerance = (
                    MPN_AMPLITUDE_TOLERANCE_R if kind == "resistor"
                    else MPN_AMPLITUDE_TOLERANCE_C
                )
                # ``min <= 0`` has no ratio: 0/0 is undefined and anything/0 is
                # infinite, and neither is an amplitude a reader can judge. It
                # stays a contradiction, as it always was.
                low_side, high_side = sorted((declared, decoded))
                ratio = high_side / low_side if low_side > 0 else None
                if ratio is not None and ratio < tolerance:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="OK",
                            subject=comp.designator,
                            message=(
                                f"{comp.designator}: board value "
                                f"{declared:.4g} {unit} vs MPN "
                                f"{decoded:.4g} {unit} differ {ratio:.2f}x, "
                                f"below the {tolerance:g}x tolerance (oracle "
                                'ruling 015 batch-2: "\u4e0d\u8981\u5b9a\u7684'
                                '\u592a\u6b7b")'
                            ),
                            evidence=[
                                f"{comp.designator} value {comp.value!r}",
                                f"{comp.designator} mpn {comp.mpn!r}",
                                *notation_evidence,
                            ],
                        ),
                        None,
                    ))
                    continue
                amplitude = (
                    f"{ratio:.2f}x apart, at or above the {tolerance:g}x "
                    "tolerance"
                    if ratio is not None else
                    f"a zero side ({declared:.4g} vs {decoded:.4g} {unit}) "
                    "leaves the ratio undefined, so no tolerance applies"
                )
                # 071 §1 C, the anchor gate (oracle ruling 2026-09-29). The
                # reading may accuse the board only if the token states the value
                # in a *code field* -- an E-96/厚声 code with its letter, the
                # canonical mid-letter form, or an EIA code with a package size
                # in the same token. The enumeration of vendor shapes is not what
                # this decides (it never ends: after #18, five more shapes in
                # hours, four manufacturers, three voltage-code positions -- #25);
                # it decides whether the digits are a value at all. An unanchored
                # reading still *matches* (that is the board's own value agreeing
                # with it) and still waives an amplitude below the tolerance, but
                # it may not be the only witness against a BOM line.
                if not anchor:
                    rows.append((
                        Outcome(
                            rule_id=self.id,
                            state="UNKNOWN",
                            subject=comp.designator,
                            message=(
                                f"{comp.designator}: board value "
                                f"{declared:.4g} {unit} contradicts its MPN "
                                f"({comp.mpn!r} decodes to {decoded:.4g} {unit}) "
                                f"-- BOM and schematic disagree ({amplitude}), "
                                "but the reading carries no syntactic anchor: "
                                "字符串解码无锚点，低置信 "
                                "(071 §1 C -- three digits found in a string are "
                                "not evidence that a BOM line is wrong, so the "
                                "contradiction is withheld)"
                            ),
                            evidence=[
                                f"{comp.designator} value {comp.value!r}",
                                f"{comp.designator} mpn {comp.mpn!r}",
                                *notation_evidence,
                            ],
                            missing_fact=(
                                f"a syntactic anchor for the reading that "
                                f"disagrees on {comp.designator} (board value "
                                f"{comp.value!r} vs MPN {comp.mpn!r} decoding to "
                                f"{_human_value(decoded, kind)}) -- a code field "
                                "around the digits, or a fact that corroborates "
                                "one side"
                            ),
                        ),
                        None,
                    ))
                    continue
                # Task 016: the one row in the codebase that carries a
                # structured target, which is what makes this the first
                # repairable rule. Since 052 §2.1 the target names the
                # contradiction and **no** repair: `suggested_after` is empty
                # because the rule has two candidates and evidence for neither,
                # and `edit plan` refuses to pick one for the operator. The
                # message names both, with the MPN's decoded quantity written
                # back in a human notation the value parsers read
                # (`_human_value`) so the "fix Value" candidate can be typed
                # straight into `--after` -- and names the anchor, so a reader can
                # see what let this row speak (071 §1 C).
                #
                # Where the design intent states a machine value for this
                # designator, the *direction* is no longer left open: the design
                # value is what the board is meant to be, so the message says
                # 改料号/重选件 and names the answer's provenance (091 A2a). The
                # wording is built by `repair_directions` -- one function for this
                # one production path, and `suggested_after` still stays empty
                # (a re-picked MPN is a change kind this build does not have).
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=comp.designator,
                        message=(
                            f"{comp.designator}: board value "
                            f"{declared:.4g} {unit} contradicts its MPN "
                            f"({comp.mpn!r} decodes to {decoded:.4g} {unit}) "
                            f"-- BOM and schematic disagree ({amplitude}；"
                            f"锚点：{anchor})"
                            + repair_directions(
                                comp.designator,
                                mpn_value=_human_value(decoded, kind),
                                board_value=comp.value,
                                board_quantity=declared,
                                kind=kind,
                                intent=self.intent,
                            )
                        ),
                        evidence=[
                            f"{comp.designator} value {comp.value!r}",
                            f"{comp.designator} mpn {comp.mpn!r}",
                            *notation_evidence,
                        ],
                    ),
                    "WARN",
                    FindingTarget(
                        component_ref=comp.designator,
                        expected_before=comp.value,
                        suggested_after="",
                    ),
                ))
        return rows


class LedCurrent(FactsRule):
    """PARAM-1: an indicator LED's series resistance sits in the oracle's window.

    The judged quantity is the **board's value field** of the series
    resistor(s) -- the value-vs-MPN contradiction is
    ``param-value-mpn-match``'s business, not this rule's. In the 3V3 domain
    the oracle's window is :data:`LED_SERIES_BOUNDS_3V3` (inclusive); a supply
    rail at any other, or at no nameable, voltage is UNKNOWN with the reason
    attached, because the oracle has stated a window for the 3V3 domain only.

    Two properties are deliberate and were measured, not assumed:

    * **the LED's own facts are not required.** The verdict is the resistor's
      value, so an indicator LED with no shelf entry is still gradeable; the
      previous version was UNKNOWN for every LED without ``vf_v``/``if_max_ma``.
    * **the rule speaks only where the domain is known.** On the golden board
      the series resistor's far side is ``VCC`` -- a name that by itself is
      never guessed, and is 3.3 V here only because the RT9013-33GB's facts
      say so. Where nobody speaks for the rail, the verdict is UNKNOWN rather
      than a window applied to an invented voltage.

    Nothing in the rule is a *hazard* check: an out-of-window resistance is
    WARN (a BOM/design contradiction, the LED works or does not), while a LED
    with **no** series resistance at all is ERROR -- 0 ohm is a short across
    the rail, which is destructive rather than marginal.

    **Issue #19 follow-up (076): both reads are net-shaped.** The series
    resistance is found by *sharing a net with the LED*, and the window's
    voltage is read off that resistor's far net -- which, like every domain in
    this harness, may be named by an LDO's output pin wherever it sits. The
    per-page merge welds net names across pages, so on a welded name the
    resistor may be the other board's and the rail the other board's
    regulator; neither the OK nor the missing-resistor ERROR is then
    established, and the row is UNKNOWN naming the net and the pages
    (:meth:`_watched` lists exactly the nets that are read). A reading with no
    unproven names -- single page, project file, netlist, ``--file`` -- is
    byte-for-byte what it was.
    """

    id = "param-led-current"
    title = "An indicator LED's series resistance sits in the oracle's window"
    level = LEVEL
    source = (
        "oracle ruling (xianyuyijinban, 2026-09-19): in the 3V3 domain an indicator "
        "LED's series resistance must sit in [470, 2200] ohm, judged by the "
        "resistance value (4.7k is the counter-example and violates); every "
        "other domain is UNKNOWN"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _leds(self, model: DesignModel) -> list[Component]:
        leds = []
        for comp in model.components.values():
            entry = self.entry_for(comp)
            if entry is not None and entry.category == "led":
                leds.append(comp)
                continue
            if "LED" in (comp.footprint or "").upper():
                leds.append(comp)
        return leds

    def _series_resistance(
        self, model: DesignModel, led: Component
    ) -> list[tuple[Component, float, str, tuple[str, ...]]]:
        """Resistors sharing a net with the LED, with their other-end nets.

        Resistors are identified by their value parsing as a resistance --
        **not** by the R designator prefix (the U3 lesson: an 0805 resistor
        lived under a U prefix).

        The fourth element is the net(s) the resistor and the LED **share** --
        the pairing evidence this rule reads. Returned rather than recomputed,
        because issue #19's follow-up (076) has to test those names *before* the
        pair is judged: welded by the per-page merge, the resistor this rule
        adopts may be the other board's part."""
        found: list[tuple[Component, float, str, tuple[str, ...]]] = []
        led_nets = {pin.net for pin in led.pins if pin.net}
        for comp in model.components.values():
            if comp.designator == led.designator:
                continue
            ohms = parse_resistance_ohms(comp.value or "")
            if ohms is None or ohms <= 0:
                continue
            nets = [pin.net for pin in comp.pins if pin.net]
            shared = tuple(dict.fromkeys(net for net in nets if net in led_nets))
            if not shared:
                continue
            other = [net for net in nets if net not in led_nets]
            for net in other or nets:
                found.append((comp, ohms, net, shared))
        return found

    def _watched(
        self,
        resistors: list[tuple[Component, float, str, tuple[str, ...]]],
        supply_net: str,
    ) -> list[str]:
        """Every net this LED's verdict reads, in the order it reads them (076).

        Two reads, which is why there are two sources here:

        * the nets the rule **pairs** on -- each candidate series resistance is
          found by sharing one of them with the LED, so a welded name can hand
          this board another board's resistor (and, with it, a total that sums
          parts from two boards);
        * ``supply_net`` -- the net whose voltage the window is judged in. For
          the LED rule that voltage may come from an LDO's output pin wherever
          it sits (the golden board's own path), which on a welded name may be
          the other page's regulator.

        Ground is not filtered out of the pairing set: where the LED and the
        resistor happen to meet on a ground net, that net *is* the pairing and
        this rule reads its pins like any other. What it never reads is who else
        sits on the LED's own ground side -- it asks whether that net is ground
        **by name** -- so a ground name only the LED touches is not evidence
        here.

        One net per entry however it was reached: a resistor whose both nets are
        the LED's own (a part across the LED) puts its supply net in the pairing
        set as well, and a name listed twice would make the refusal read
        "``'VCC'`` and ``'VCC'`` were each seen on more than one page".
        """
        watched = dict.fromkeys(
            net for _c, _o, _n, shared in resistors for net in shared
        )
        if supply_net:
            watched.setdefault(supply_net, None)
        return list(watched)

    def _supply_side(
        self,
        led: Component,
        resistors: list[tuple[Component, float, str, tuple[str, ...]]],
        guesses: dict,
    ) -> tuple[list[tuple[Component, float, str, tuple[str, ...]]], float | None, str]:
        """The series resistors on the supply side, and the rail behind them.

        A resistor counts when it shares a net with the LED **and** its far
        side sits on a net whose voltage somebody can name; that voltage is
        the domain the rule judges in. With no resistor at all the LED's own
        non-ground net is the supply side -- there is nothing in between, so
        "no series resistor" stays domain-gated instead of being assumed from
        the presence of two nets.

        Two silences that must not merge: *no resistor* (the LED sits straight
        across two nets) and *a resistor whose far side nobody names*. The
        first is graded as 0 ohm once the domain is known; the second is
        UNKNOWN, because summing an empty path would read as 0 ohm and report
        a missing resistor that is on the board.
        """
        path: list[tuple[Component, float, str, tuple[str, ...]]] = []
        volts: float | None = None
        net_name = ""
        for comp, ohms, net, shared in resistors:
            value, _source, _why = domain_of(guesses, net)
            if value is None:
                continue
            path.append((comp, ohms, net, shared))
            if volts is None:
                volts, net_name = value, net
        if path:
            return path, volts, net_name
        if resistors:
            return [], None, ""
        for pin in led.pins:
            if not pin.net or is_ground_net(pin.net):
                continue
            value, _source, _why = domain_of(guesses, pin.net)
            if value is not None:
                return [], value, pin.net
        return [], None, ""

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        low, high = LED_SERIES_BOUNDS_3V3
        window = f"[{low:g}, {high:g}] \u03a9"
        for led in self._leds(model):
            resistors = self._series_resistance(model, led)
            path, supply_volts, supply_net = self._supply_side(
                led, resistors, guesses
            )
            total = sum(ohms for _c, ohms, _n, _s in path)
            evidence = [
                f"{led.designator} pins "
                + ", ".join(
                    f"{p.number}@{p.net or '(no net)'}" for p in led.pins
                ),
            ]
            if path:
                evidence.append(
                    "series resistance "
                    + "+".join(
                        f"{comp.designator}({ohms:.4g}\u03a9)"
                        for comp, ohms, _n, _s in path
                    )
                    + f" = {total:.4g} \u03a9"
                )
            # Issue #19 follow-up (076). This rule's two reads are the pairing
            # (which resistor shares a net with the LED) and the rail's voltage,
            # and the per-page merge welds net names blind: board 2's resistor
            # becomes board 1's series resistance, and board 2's regulator names
            # board 1's rail. Neither the pass (a legal 1k in the window) nor the
            # failure (no resistor at all, 0 ohm across the rail) is established
            # on such a name, so the row is UNKNOWN -- and it is filed *before*
            # the branches below, because "nothing names the rail" is also a
            # conclusion about nets this reading cannot attribute to a board.
            welded = unproven_nets(model, self._watched(resistors, supply_net))
            if welded:
                rows.append((
                    unproven_outcome(
                        self.id,
                        led.designator,
                        welded,
                        what=(
                            "whether any resistor at all is in series with it, "
                            "and what the rail behind that path is at (both are "
                            "read from these nets' pins)"
                        ),
                        evidence=evidence,
                    ),
                    None,
                ))
                continue
            if supply_volts is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: the oracle's window needs a "
                            "named supply voltage, and nothing names the rail "
                            "behind its series resistance"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"a known voltage on the far side of "
                            f"{led.designator}'s series resistor"
                            if resistors else
                            f"a known voltage on {led.designator}'s own nets"
                        ),
                    ),
                    None,
                ))
                continue
            if abs(supply_volts - LED_WINDOW_DOMAIN_V) > LED_DOMAIN_TOLERANCE_V:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: its series resistance sits on "
                            f"{supply_net!r} at {supply_volts:g} V, and the "
                            "oracle's window is stated for the 3.3 V domain "
                            "only"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"an oracle-approved series-resistance window for "
                            f"the {supply_volts:g} V domain"
                        ),
                    ),
                    None,
                ))
                continue
            if not path:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: no series resistor on its nets "
                            f"({supply_net!r} at {supply_volts:g} V) -- 0 \u03a9 is "
                            f"outside the oracle's window {window} for the "
                            "3.3 V domain, and nothing bounds the current"
                        ),
                        evidence=evidence,
                    ),
                    "ERROR",
                ))
                continue
            resistors_text = "+".join(
                f"{comp.designator}({ohms:.4g}\u03a9)"
                for comp, ohms, _n, _s in path
            )
            # Quote the evidence that named the rail: the whole 011 family is
            # built on "who says so", and on the golden board the answer is an
            # LDO's facts rather than the net's own name.
            _volts, supply_source, _why_not = domain_of(guesses, supply_net)
            evidence.append(
                f"supply side {supply_net} = {supply_volts:g} V"
                + (f" per {supply_source}" if supply_source else "")
            )
            if low <= total <= high:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: series resistance "
                            f"{resistors_text} from {supply_net} "
                            f"({supply_volts:g} V) sits inside the oracle's "
                            f"window {window}"
                        ),
                        evidence=evidence,
                    ),
                    None,
                ))
            else:
                side = "below" if total < low else "above"
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=led.designator,
                        message=(
                            f"{led.designator}: series resistance "
                            f"{resistors_text} from {supply_net} "
                            f"({supply_volts:g} V) is {side} the oracle's "
                            f"window {window} for the 3.3 V domain"
                        ),
                        evidence=evidence,
                    ),
                    "WARN",
                ))
        return rows



class DividerOutput(FactsRule):
    """PARAM-2: a resistor divider's tap voltage (with tolerance) fits the
    load pin's declared input range.

    The declared range comes from the load's shelf facts: its supply_pins
    record for that pin, whose ``v_operating`` is the datasheet's declared
    window for the pin. A load pin with no such record is UNKNOWN ("the load
    pin's range is undeclared") -- the rule never invents a window. Tolerance
    comes from the shelf's ``Tolerance`` parameter when it parses; without it
    the message says the spread is nominal-only."""

    id = "param-divider-output"
    title = "A divider's tap voltage fits the load pin's declared range"
    level = LEVEL
    source = (
        "the load part's own supply_pins v_operating facts; resistor "
        "tolerance from the shelf's Tolerance parameter"
    )

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return self.findings_from(self._rows(model))

    def _tolerance(self, comp: Component) -> float:
        """The part's fractional tolerance from its shelf params, or 0."""
        entry = self.entry_for(comp)
        if entry is None:
            return 0.0
        text = entry.params.get("Tolerance", "")
        digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        try:
            return float(digits) / 100.0 if digits else 0.0
        except ValueError:
            return 0.0

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        resistors: dict[str, tuple[Component, float]] = {}
        for comp in model.components.values():
            ohms = parse_resistance_ohms(comp.value or "")
            if ohms is not None and ohms > 0:
                resistors[comp.designator] = (comp, ohms)

        rows: list[tuple[Outcome, str | None]] = []
        seen_dividers: set[tuple[str, str]] = set()
        for upper_desig, (upper, r_up) in resistors.items():
            upper_nets = [p.net for p in upper.pins if p.net]
            for top_net in upper_nets:
                volts, source, _why = domain_of(guesses, top_net)
                if volts is None or is_ground_net(top_net):
                    continue
                for bottom_desig, (bottom, r_down) in resistors.items():
                    if bottom_desig == upper_desig:
                        continue
                    bottom_nets = [p.net for p in bottom.pins if p.net]
                    shared = [
                        net for net in bottom_nets
                        if net in upper_nets and not is_ground_net(net)
                    ]
                    grounded = [net for net in bottom_nets if is_ground_net(net)]
                    if not shared or not grounded:
                        continue
                    tap = shared[0]
                    key = tuple(sorted((upper_desig, bottom_desig)))
                    if key in seen_dividers:
                        continue
                    seen_dividers.add(key)
                    loads = [
                        (designator, pin)
                        for designator, pin in model.nets[tap].pins
                        if designator not in (upper_desig, bottom_desig)
                    ]
                    if not loads:
                        continue  # an unloaded divider has no declared range
                    # Issue #19: both halves of this rule are net-shaped — the
                    # loads are whoever shares the tap, and the rail voltage is
                    # inferred from a net that may hold another page's regulator.
                    # On a welded name neither is established, so the tap is not
                    # judged (the WARN that leaves a load's declared range and the
                    # OK that fits it are the same unproven claim).
                    welded = unproven_nets(model, (tap, top_net))
                    if welded:
                        rows.append((
                            unproven_outcome(
                                self.id,
                                f"{upper_desig}/{bottom_desig}",
                                welded,
                                what=(
                                    "what its tap feeds and what its rail is "
                                    "(both are read from these nets' members)"
                                ),
                                evidence=[
                                    f"divider {upper_desig}/{bottom_desig}: "
                                    f"tap {tap}, rail {top_net}"
                                ],
                            ),
                            None,
                        ))
                        continue
                    self._check_tap(
                        rows, model, guesses, upper_desig, bottom_desig,
                        r_up, r_down, volts, source, tap, loads,
                    )
        if not seen_dividers:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject="divider survey",
                    message=(
                        "no resistor divider between a known domain and "
                        "ground was found on this board"
                    ),
                ),
                None,
            ))
        return rows

    def _check_tap(
        self, rows, model, guesses, upper_desig, bottom_desig,
        r_up, r_down, volts, source, tap, loads,
    ) -> None:
        v_tap = volts * r_down / (r_up + r_down)
        # Tolerance: both resistors' spreads act on the ratio; the honest
        # cheap bound is the sum of their fractional tolerances.
        tol_upper = self._tolerance(model.components[upper_desig])
        tol_bottom = self._tolerance(model.components[bottom_desig])
        spread = (tol_upper + tol_bottom) * volts * r_down * r_up / (
            (r_up + r_down) ** 2
        )
        v_lo, v_hi = v_tap - spread, v_tap + spread
        for load_desig, load_pin in loads:
            load = model.components.get(load_desig)
            if load is None:
                continue
            entry = self.entry_for(load)
            records = (entry.facts or {}).get("supply_pins", []) if entry else []
            declared = next(
                (
                    record.get("v_operating")
                    for record in records
                    if load_pin in [str(p) for p in record.get("pins", [])]
                    and record.get("v_operating")
                ),
                None,
            )
            evidence = [
                f"divider {upper_desig}/{bottom_desig}: tap {tap} = "
                f"{v_tap:.3g} V (spread ±{spread:.3g} V) from "
                f"{volts:.3g} V per {source}",
                f"load {load_desig} pin{load_pin}",
            ]
            if declared is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"{load_desig} pin{load_pin} is fed by the "
                            f"{upper_desig}/{bottom_desig} divider but "
                            "declares no input range in its facts"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"an input-range fact for {load_desig} "
                            f"pin{load_pin}"
                        ),
                    ),
                    None,
                ))
                continue
            lo, hi = declared
            if lo is None or hi is None:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="UNKNOWN",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"{load_desig} pin{load_pin}'s declared range "
                            f"[{lo}, {hi}] is one-sided, so the tap cannot "
                            "be judged against it"
                        ),
                        evidence=evidence,
                        missing_fact=(
                            f"a two-sided input range for {load_desig} "
                            f"pin{load_pin}"
                        ),
                    ),
                    None,
                ))
                continue
            if v_lo < lo or v_hi > hi:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="VIOLATION",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"the {upper_desig}/{bottom_desig} divider's tap "
                            f"{v_tap:.3g} V (spread ±{spread:.3g} V) leaves "
                            f"{load_desig} pin{load_pin}'s declared range "
                            f"[{lo}, {hi}]"
                        ),
                        evidence=evidence,
                    ),
                    "WARN",
                ))
            else:
                rows.append((
                    Outcome(
                        rule_id=self.id,
                        state="OK",
                        subject=f"{load_desig} pin{load_pin}",
                        message=(
                            f"the {upper_desig}/{bottom_desig} divider's tap "
                            f"{v_tap:.3g} V fits {load_desig} "
                            f"pin{load_pin}'s declared range [{lo}, {hi}]"
                        ),
                        evidence=evidence,
                    ),
                    None,
                ))


class RcCutoff(FactsRule):
    """PARAM-3: report an RC network's -3 dB cutoff as a number (INFO).

    No requirement channel exists for "what the design needed", so the rule
    reports and refuses to grade -- an INFO that invents a pass/fail would be
    worse than silence. Topology recognised: a resistor and a capacitor in
    series between a net and ground (a low-pass to ground).

    **The number rides in the OK state, not in VIOLATION.** Until 011e the rows
    were emitted as ``VIOLATION`` and ``check()`` downgraded them to INFO, which
    made the four-state table lie: VIOLATION is the column the oracle reads as
    "the rules found something wrong", and a report-only measurement is not
    that. Measured on the graduation board: 11 of its VIOLATION cells were
    these numbers, and on an unannotated board every one of them landed in the
    harness's unexplained column and inflated the precision denominator. The
    state now says what is true -- a measurement was taken and nothing was
    violated -- and the finding channel stays exactly as it was (INFO), which
    is why ``check()`` keys off the row's severity hint rather than its state.

    **Issue #19 follow-up (076): the pair is a membership claim too.** The
    report-only shape made this rule look like it read one part's own values,
    which is why #19's first pass left it out -- but "these two parts are one
    network" is read from a *net's* members (the pair is whatever shares a
    non-ground net, plus that capacitor being grounded), and the per-page merge
    welds net names blind. Welded, board 2's capacitor became board 1's
    partner and the board got a cutoff it does not have; the row is UNKNOWN on
    such a net now, naming the net and the pages, with ``check()`` filing
    nothing either way. A single-page reading (and every project-file, netlist
    and ``--file`` reading) carries no unproven names and is byte-for-byte what
    it was.
    """

    id = "param-rc-cutoff"
    title = "RC networks' -3 dB cutoff, reported as a number"
    level = LEVEL
    source = "house rule (report-only): fc = 1 / (2*pi*R*C)"

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [outcome for outcome, _s in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        findings: list[Finding] = []
        for outcome, severity in self._rows(model):
            # The severity hint is the "this row is a report" marker: the
            # survey row (no pair found) carries None and stays silent.
            if severity is None:
                continue
            findings.append(self.finding_from_row(outcome, severity))
        return findings

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        pairs: list[tuple[Component, float, Component, float, str]] = []
        resistors: dict[str, float] = {}
        capacitors: dict[str, float] = {}
        for comp in model.components.values():
            ohms = parse_resistance_ohms(comp.value or "")
            if ohms is not None and ohms > 0:
                resistors[comp.designator] = ohms
            farads = parse_capacitance_farads(comp.value or "")
            if farads is not None:
                capacitors[comp.designator] = farads
        #: The pairs this rule looked at, refused ones included, so the survey row
        #: below states "no pair exists here" only when that is true.
        seen: set[tuple[str, str]] = set()
        for r_desig, ohms in resistors.items():
            r_nets = [
                p.net for p in model.components[r_desig].pins if p.net
            ]
            for c_desig, farads in capacitors.items():
                if c_desig == r_desig:
                    continue
                key = tuple(sorted((r_desig, c_desig)))
                if key in seen:
                    continue
                c_nets = [
                    p.net for p in model.components[c_desig].pins if p.net
                ]
                shared = [
                    net for net in c_nets
                    if net in r_nets and not is_ground_net(net)
                ]
                capped = [net for net in c_nets if is_ground_net(net)]
                if not shared or not capped:
                    continue
                # Issue #19 follow-up (076). A resistor and a capacitor are "one
                # network" here because they **share a non-ground net**, and the
                # per-page merge welds those names across pages. On a welded name
                # the partner may be the other board's part, so the cutoff is not
                # this board's number — filing it measures a network no page
                # draws (岳's reproduction: fc = 159 Hz welded, nothing at all
                # when the pair is real). Both directions are withheld, so the
                # row is UNKNOWN.
                #
                # This is the pair's own net, and the only net the verdict reads:
                # the resistor's far terminal is never looked at by this rule,
                # and the capacitor's ground side is read **by name**
                # (`is_ground_net`), not by membership. It is also *not* checked
                # on purpose: a ground name sits on every page of a multi-sheet
                # board by construction, so refusing on it would refuse every RC
                # pair there — a false alarm, not a closed hole.
                #
                # The pair is marked seen either way: a refusal must not sit
                # beside a survey row claiming no pair was found (the same call
                # `param-divider-output` makes for a welded divider).
                welded = unproven_nets(model, shared)
                if welded:
                    seen.add(key)
                    rows.append((
                        unproven_outcome(
                            self.id,
                            f"{r_desig}/{c_desig}",
                            welded,
                            what=(
                                f"whether {r_desig} and {c_desig} are one network "
                                "at all (this rule's pair is read from these "
                                "nets' pins)"
                            ),
                            evidence=[
                                f"{r_desig} + {c_desig} share {shared[0]!r}",
                                f"{r_desig} value "
                                f"{model.components[r_desig].value!r}",
                                f"{c_desig} value "
                                f"{model.components[c_desig].value!r}",
                            ],
                        ),
                        None,
                    ))
                    continue
                # A pair sharing a *known supply rail* is decoupling, not a
                # signal low-pass (the golden board's U3+C6 on VCC): the RC
                # rule would otherwise file every decoupling cap as a
                # "filter" and drown the report.
                if any(domain_of(guesses, net)[0] is not None for net in shared):
                    continue
                seen.add(key)
                pairs.append((
                    model.components[r_desig], ohms,
                    model.components[c_desig], farads, shared[0],
                ))
        if not seen:
            rows.append((
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject="RC survey",
                    message=(
                        "no resistor-to-ground capacitor pair (RC low-pass "
                        "topology) was found on this board"
                    ),
                ),
                None,
            ))
        for r_comp, ohms, c_comp, farads, net in pairs:
            fc = 1.0 / (2.0 * math.pi * ohms * farads)
            text = f"{fc:,.0f} Hz" if fc >= 1 else f"{fc:.3g} Hz"
            rows.append((
                Outcome(
                    rule_id=self.id,
                    # OK, not VIOLATION: a measurement is not a fault (011e
                    # sec.1.1). The finding this row still produces is INFO.
                    state="OK",
                    subject=f"{r_comp.designator}/{c_comp.designator}",
                    message=(
                        f"RC {r_comp.designator}({ohms:.4g}Ω) + "
                        f"{c_comp.designator}({c_comp.value}) on {net!r}: "
                        f"fc = {text} (-3 dB cutoff; reported, not graded -- "
                        "no requirement channel exists)"
                    ),
                    evidence=[
                        f"{r_comp.designator} value {r_comp.value!r}",
                        f"{c_comp.designator} value {c_comp.value!r}",
                    ],
                ),
                "INFO",
            ))
        return rows
