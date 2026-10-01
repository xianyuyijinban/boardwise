"""Value decoding and unit parsing helpers for the PARAM rules (task 011d).

.. note::

   **This module moved here in 083.** The implementation used to live at
   ``boardwise/rules/values.py``; that path is now a forwarding shim, so every
   existing ``from boardwise.rules.values import ...`` keeps working and new
   code should import ``boardwise.core.values`` directly.

   It moved because two consumers were below the layer it was in. Issue #51
   (``core/compare.py``) and issue #52 (``core/blocks.py``) each carried their
   own private copy of the value grammar, and delegating them to *this* module
   would have meant ``core`` importing ``rules`` — which 006c's executable
   constitution (``tests/test_layer_rules.py``) forbids at every depth, a
   function-local import included. 071 §2 says one verdict has one
   implementation; the arrow diagram says which way that implementation has to
   face for ``core`` to be able to use it. Both hold here: the parsers are
   unchanged and unique, and they now sit in the layer their lowest consumer
   can reach.

   Nothing about the module's behaviour changed in the move. The arrow
   ``rules -> core`` was already legal and is the direction the shim uses.


Five parsers live here, all *whitelist* parsers: they either recognise the
string or return None — "unparseable" must never become "zero" or "whatever
the digits look like".

- :func:`parse_resistance_ohms` — board resistor values (``10kΩ``, ``4R7``,
  ``0R01``, and the trade's mid-letter ``4K7``). Moved here from
  ``rules/connectivity.py`` by 071 §2: the board's Value field and an MPN are
  read by one module, because the rule that compares the two had one grammar
  for each side and the mid-letter spelling fell between them (issue #23).
- :func:`parse_capacitance_farads` — board capacitor values (``100nF``,
  ``0.1uF``, ``22pF``, and the trade's mid-letter ``4u7``/``2n2``/``5p1``). A
  bare number without a unit is None: for capacitors the convention-less
  number is ambiguous by two orders of magnitude and the 011 family exists
  because a guess got recorded as a fact.
- :func:`decode_eia_3digit` — the EIA three-digit value code (``471`` ->
  47x10^1). The *base unit depends on the part kind*: ohms for resistors,
  picofarads for capacitors, so the caller supplies the multiplier.
- :func:`parse_voltage_volts` — a rail voltage (``5V``, ``3.3 V``, and the
  mid-letter ``3V3`` the port sidecar itself uses; issue #53). Added here
  because the power-tree gate was comparing two volt spellings as strings,
  which is the same "one quantity, one implementation" gap as #51 and #52 —
  in a third module.
- :func:`mpn_value_code` — extract the EIA code from an MPN, whitelisted to
  the shapes the big manufacturers actually print: the code at the end of the
  string, optionally followed by a single tolerance letter (``...225K``), or
  embedded before a dielectric/tolerance tail (``...BB104``). Package codes
  are guarded: a trailing group that completes ``0402/0603/0805/1206/1210``
  is a *size*, not a value. Anything else -- two candidate codes, no code at
  all, or a token written in a notation that only *looks* like an EIA code
  (see :func:`_non_eia_notation`) -- is None, and the rule reports UNKNOWN
  instead of guessing.

Two bounds hold at every entry point above, because these parsers are handed
whatever a board or a BOM line happens to contain (issues #27/#31): a first
whitespace-separated token longer than :data:`_MAX_DECODED_CHARS` is not
decompiled at all, and a quantity that ``float`` overflowed to a non-finite
number is None like any other unreadable value. Neither is a new verdict — both
answer what this module already answers for a string it does not recognise.
"""

from __future__ import annotations

import math
import re

#: How much of an outside string the decoders will look at (issue #27).
#:
#: The regexes below are grammatical, not bounded, and two of them scan a digit
#: run from every start position: ``_MID_LETTER_RE``'s ``\d*`` and
#: ``_ELECTROLYTIC_RE``'s ``\d+[Vv]\d{3}``. A value field or an MPN that is one
#: long run of digits therefore costs O(n²). The issue reports 28 s for an MPN of
#: 32000 digits and this machine measures 8.3 s for the same call; both scale x4
#: per doubling.
#:
#: **The shape of the repair is the point.** The obvious alternative -- bounding
#: the regex (``\d{0,3}``) -- would undo 071's infix repair: the mid-letter reader
#: has to see the *whole* run ``060310`` before it can strip the size code
#: ``0603`` that heads it, and handed only the last three digits it spells the
#: pseudo-reading ``310K0`` again, the reading a board declaring 310 kΩ passed on
#: (issue #24). So the *length* is checked, not the digits: past the cap the
#: string is one this decoder cannot read -- the same answer it gives a notation
#: it does not recognise -- and the regexes only ever run on a bounded string, so
#: the quadratic term is O(64²), which is nothing. The cap is measured on the
#: first whitespace-separated token, the piece the decoders read.
_MAX_DECODED_CHARS = 64


def _too_long(text: str | None) -> bool:
    """True when ``text``'s first whitespace-separated token exceeds the cap.

    The token, not the whole string: that is the piece the decoders read (an
    MPN's ``" TS"`` tail is a packaging note, not code), and it is how every entry
    point below slices it anyway. Only the length is asked -- what makes a long
    string unreadable here is the cost of the question, not its digits.
    """
    if not text:
        return False
    stripped = text.strip()
    return bool(stripped) and len(stripped.split(maxsplit=1)[0]) > _MAX_DECODED_CHARS


def _finite(quantity: float | None) -> float | None:
    """``quantity`` when it is a finite number, else None (issue #31).

    ``float`` overflows in silence: ``"1" * 400`` parses to ``inf`` and reports no
    error, and an infinite board value reached ``params._closest_reading``'s
    ``math.log(decoded / declared)`` as ``log(0.0)`` -- a ``ValueError`` out of
    ``run_review``, one unreadable value field taking the whole report down. This
    module answers "cannot be read" for every string it does not recognise, and an
    overflow is one of those.
    """
    if quantity is None:
        return None
    return quantity if math.isfinite(quantity) else None


_CAP_UNITS = {
    "pf": 1e-12,
    "nf": 1e-9,
    "uf": 1e-6,
    "µf": 1e-6,
    "mf": 1e-3,
}
_CAP_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(pF|nF|uF|µF|MF)$", re.IGNORECASE)

#: Package sizes that legitimately end in three digits -- a trailing group
#: completing one of these is the part's *size*, never its value.
_PACKAGE_TAILS = ("0402", "0603", "0805", "1206", "1210")

#: The same sizes written the **metric** way: three figures, the two dimensions
#: in tenths of a millimetre -- ``105`` = 1.0x0.5 mm (= 0402), ``160``/``188`` =
#: 1.6x0.8 mm (= 0603, TDK's and Murata's spellings of it), ``201`` = 0805,
#: ``321``/``322`` = 1206/1210, ``451``/``453`` = 1812.
#:
#: This is the industry's finite size list, not a manufacturer's private shape
#: (071 §3), and it is a *grammar* fact: a part number states its size once, at
#: the front (``GRM188``R71C104KA01D, ``C1608``X5R1A105KT). The guard built on
#: it fires only on a token's **first** digit run, which is what keeps it off the
#: value codes sharing a spelling: ``105`` is also 1 uF, and ``CL10A105KA8NNNC``'s
#: ``105`` sits behind ``CL10`` and stays a value.
_METRIC_SIZE_CODES = ("105", "160", "188", "201", "321", "322", "451", "453")

#: The imperial (four-figure) sizes, longest first, for the prefix strip below.
_IMPERIAL_SIZE_CODES = (
    "01005", "0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010",
    "2512",
)

#: Every size code, longest first: which one a digit run starts with is decided
#: here, and ``2010`` must win over ``201`` before it can be stripped.
_SIZE_CODE_PREFIXES = _IMPERIAL_SIZE_CODES + _METRIC_SIZE_CODES

#: The **components** of a size code as whole digit runs, for asking "does this
#: token state a package size of its own?" (the anchor below).
_SIZE_CODE_RUNS = frozenset(_IMPERIAL_SIZE_CODES + _METRIC_SIZE_CODES)

#: The three syntactic **anchors** a decoded reading can carry (071 §1, oracle
#: ruling 2026-09-29, option C -- "锚点闸"). A reading with an anchor may support
#: a WARN; a reading without one is a string that merely *contains* three digits,
#: and such a reading may contradict a board only in silence (UNKNOWN).
#:
#: The anchor is not a shape whitelist -- that is the enumeration that failed
#: (issues #18, #22-#26). It is the weaker question "is this value stated in a
#: *code field*", and the three answers are the three ways a token can say so:
#:
#: * :data:`ANCHOR_E96_LETTER` -- the four figures sit in a field whose grammar
#:   names a letter right at them: the E-96 code followed by a tolerance letter
#:   (``RK73H1JTTD1002F``'s ``1002F``), 厚声's ordering field with its
#:   ``T``-taping tail (``0603WAF1002T5E``, ``0805W8J0103T5E`` -- the letter's
#:   exact meaning differs by house, tolerance here and taping there; what the
#:   anchor states is that the four figures are a code field, not a bare run of
#:   digits), and the shunt field between a tolerance letter and its ``R``;
#: * :data:`ANCHOR_MID_LETTER` -- the trade's mid-letter notation read in its
#:   canonical form (the whole digit run after the package size comes off:
#:   ``CRCW060310K0FKEA`` -> ``10K0``). The *shorter* readings of the same run are
#:   the vendor-prefix guesses (``074K7`` also reading as ``4K7``) and carry no
#:   anchor, because by construction one of them is wrong;
#: * :data:`ANCHOR_PACKAGE_CONTEXT` -- the EIA three-digit code in a token that
#:   also states a package size (``CC0603``KRX7R9BB104, ``GRM188``R71C104KA01D).
#:   The size field is what makes the three digits a code field rather than
#:   whatever digits happen to be in the string -- which is exactly what the
#:   five electrolytics of issue #25 lacked (``UVR1H101MPD``, ``50YXF100MEFC``).
ANCHOR_E96_LETTER = "值码带相邻容差字母"
ANCHOR_MID_LETTER = "中缀正规形"
ANCHOR_PACKAGE_CONTEXT = "值码带封装语境"

_CODE_RE = re.compile(r"(\d{3})")

#: Notations that *look* like an EIA code and are not one (task 015, the M2
#: defect: they were being hard-read, and ``PA50V330M10x15`` came back as
#: 3.3e-11 F). A token carrying any of them is refused *as a whole*, not
#: mined for the one group that parses: dropping a candidate can promote
#: another, and the ``...225KT000E`` tail would then lose ``225`` to ``000``.
#:
#: * ``_R_NOTATION_RE`` -- ``R`` as the decimal point: ``RE2512F3R001`` is a
#:   0.001 ohm shunt, not "00 x 10^1". The fraction is at most three digits
#:   (``R001``, ``1R0``, ``4R7``) *and* the number ends there, which is what
#:   keeps this guard off the dielectric codes: in ``CC0603KRX7R9BB104`` the
#:   digits after ``R`` are ``X7R9``'s, and the value ``104`` follows.
#: * ``_VOLTAGE_TAIL_RE`` -- value, tolerance letter, voltage rating:
#:   ``HGC1206R5106K500NSPJ``'s ``106K500`` reads 10 uF, +/-10%, 50 V, so its
#:   second group is a rating and neither group is a value on its own.
#: * ``_ELECTROLYTIC_RE`` -- the electrolytic layouts: a case size
#:   (``PA50V330M10x15``'s ``10x15``); a voltage printed before the value
#:   (``50V330``); or the trade's voltage code, tolerance letter and
#:   capacitance (``1VM101`` = 35 V, +/-20 %, 100 uF -- issue 18). The figures
#:   in the last two shapes are microfarads, never the EIA code their shape
#:   mimics. The voltage-code marker also fires on TDK's voltage code
#:   (``C1608X5R1V225KT000E``'s ``1V225``): that part refuses either way, and
#:   refusing a token whose digits are already unreadable costs nothing. Its
#:   tolerance letter is pinned to the trade's ``[MKGJT]`` on purpose: a
#:   letter-blind class also swallows the ceramics whose EIA code follows a
#:   dielectric run -- ``CC0603KRX7R9BB104`` reads as ``9BB104``, and that part
#:   is decoded correctly today (measured over 5452 candidate tokens harvested
#:   from this repo's tests, fixtures, docs and reviewsets: 8 ceramics lost
#:   without the pin, none with it).
#:
#: The guards must stay independent: each one owns witnesses the others leave
#: alone, because a witness refused by two guards cannot detect the loss of
#: either (a mutation that disabled one stayed green while every voltage-tail
#: witness was also matched by the R pattern -- measured 2026-09-21, task 015
#: sec.4.2).
_R_NOTATION_RE = re.compile(r"\d[Rr]\d{1,3}")
_VOLTAGE_TAIL_RE = re.compile(r"\d{3}[A-Z]\d{3}")
_ELECTROLYTIC_RE = re.compile(r"\d[xX]\d|\d+[Vv]\d{3}|\d[A-Z][MKGJT]\d{3}")

#: The shunt convention with the coding *in front of* the ``R`` (task 046):
#: ``FRL1210FR400TS`` states 400 mΩ as ``FR400``. The letter has to be one of
#: the tolerance letters and has to sit immediately before the ``R``, which is
#: what keeps this off ``AR03BTCX5001`` (``A`` is not a tolerance letter),
#: ``RC0603FR-074K7L`` (that ``R`` is followed by a dash) and
#: ``JER2512F3R005`` (a digit in front of the ``R`` -- 043's refusal, unchanged).
_SHUNT_FIELD_RE = re.compile(r"[FJKD]R(\d{2,3})")

#: Polymer-electrolytic series whose digits are a capacitance in
#: **microfarads** (task 046): ``SPZ1HM100E07O00RAXXX`` is a 10 µF Aishi part,
#: and this decoder's capacitor base unit is the picofarad -- reading its
#: ``100`` as an EIA code is what produced "10 pF" for a 10 µF part.
_POLYMER_SERIES_HEADS = ("SPZ", "SPA")


def _digit_run(token: str, index: int) -> str:
    """The whole run of digits the character at ``index`` belongs to."""
    start = index
    while start > 0 and token[start - 1].isdigit():
        start -= 1
    end = index
    while end < len(token) and token[end].isdigit():
        end += 1
    return token[start:end]


def _r_as_decimal_point(token: str) -> bool:
    """True when ``R`` is the decimal point of a number that ends there."""
    for m in _R_NOTATION_RE.finditer(token):
        if not any(ch.isdigit() for ch in token[m.end():]):
            return True
    return False


def _voltage_rating_tail(token: str) -> str | None:
    """The ``<value><tolerance><voltage>`` tail, package sizes exempted.

    Every start position is tried, not ``finditer``'s non-overlapping scan:
    in ``HGC1206R5106K500NSPJ`` the scan finds ``206R510`` first (the size
    1206 plus the right-hand digits) and skipping it would end the scan
    before the real tail, ``106K500``.
    """
    for start in range(len(token)):
        m = _VOLTAGE_TAIL_RE.match(token, start)
        if m is None:
            continue
        if _digit_run(token, start) in _PACKAGE_TAILS:
            continue
        return m.group(0)
    return None


def _non_eia_notation(token: str) -> bool:
    """True when the token is written in a notation this decoder does not read."""
    return bool(
        _ELECTROLYTIC_RE.search(token)
        or _r_as_decimal_point(token)
        or _voltage_rating_tail(token)
        or _SHUNT_FIELD_RE.search(token)
    )


def _foreign_unit_code(token: str) -> bool:
    """True when the token's digits are a value in a unit this decoder does not read.

    Only the polymer-electrolytic series so far (task 046): ``SPZ``/``SPA`` part
    numbers print their capacitance in microfarads, so a three-digit group in
    one of them would have to be decoded against a µF base -- which the EIA
    path cannot do (the caller's base is picofarads) and must therefore not
    touch. Reading ``SPZ1HM100E07O00RAXXX``'s ``100`` against that base is what
    reported 10 pF for a 10 µF part; refusing the token reports UNKNOWN instead,
    which is the honest answer for a string whose digits this decoder does not
    know how to scale.
    """
    return token.startswith(_POLYMER_SERIES_HEADS)


def parse_capacitance_farads(value: str) -> float | None:
    """Board capacitor value -> farads, with an explicit unit required.

    Two grammars, tried in this order:

    * the **unit suffix** an editor accepts: ``100nF``, ``0.1uF``, ``22pF``,
      ``1mF`` (and the Greek-mu spellings, normalised below);
    * the trade's **mid-letter** notation, the capacitor half of the one the
      resistance side has read since 071: ``4u7`` = 4.7 µF, ``2n2`` = 2.2 nF,
      ``5p1`` = 5.1 pF (issue #23). The defect it closes was not a wrong
      number but a *silent* one -- a rule handed a value it cannot read skips
      the part entirely, so a board writing ``4u7`` lost its ``param-rc-cutoff``
      pair, while the same part spelled ``4.7uF`` was measured. Read by
      :func:`_mid_letter_farads`, which requires the notation to span the field.

    Every string the suffix grammar reads keeps its exact value: the two grammars
    cannot overlap at all -- the suffix form names its unit and ends there
    (``100nF``), while a mid-letter reading has to span the whole field, and a
    trailing ``F`` is a character it does not cover (``4u7F`` is not this
    notation).

    Two refusals come before the grammar: a first token longer than the cap is not
    read at all (issue #27), and a quantity that overflowed to a non-finite float
    is not a capacitance this can state (issue #31).
    """
    if not value or _too_long(value):
        return None
    text = value.strip()
    m = _CAP_RE.match(text)
    if m is None:
        return _mid_letter_farads(text)
    # GREEK SMALL LETTER MU (U+03BC) and MICRO SIGN (U+00B5) are one unit to a
    # reader and two code points to Python: ``_CAP_RE``'s ``re.IGNORECASE``
    # folds them together (both casefold to U+03BC), so ``22μF`` *matches* and
    # then arrives here as ``"μf"`` — a key :data:`_CAP_UNITS` never held, and
    # the lookup raised ``KeyError`` out of the rule (task 055's defect: a
    # Greek-mu value, an everyday IME spelling, crashed the decap rule where
    # the contract is "unreadable -> None -> UNKNOWN"). The key is normalised
    # to the micro sign and read with ``.get``: the map is now total, so an
    # unrecognised unit is None like any other unreadable value.
    factor = _CAP_UNITS.get(m.group(2).lower().replace("\u03bc", "\u00b5"))
    if factor is None:
        return None
    return _finite(float(m.group(1)) * factor)


def _cap_spelling(text: str) -> str:
    """``text`` with every micro spelling read as one letter (task 055's lesson).

    MICRO SIGN (U+00B5), GREEK SMALL LETTER MU (U+03BC) and the GREEK CAPITAL
    LETTER MU (U+039C) the two of them upper-case to are one unit to a reader and
    three code points to Python, so :data:`_CAP_MID_LETTER_RE`'s
    ``re.IGNORECASE`` matches all three. The reading they produce is spelled
    ``U``; comparing it to the field as written would refuse ``4µ7`` -- a value
    the scan has just read.
    """
    return (
        text.replace("\u00b5", "u")
        .replace("\u03bc", "u")
        .replace("\u039c", "u")
        .upper()
    )


#: The capacitance notation **as a whole field**: the digits of the mantissa, one
#: unit letter, and the digits after it that carry the fraction if there are any
#: (``4u7`` = 4.7 µF, ``2n2`` = 2.2 nF, ``5p1`` = 5.1 pF, ``4u70`` = 4.70 µF,
#: ``100n`` = 100 nF, ``22u`` = 22 µF -- the fraction-free spelling the trade
#: prints whenever the value is a whole number of its unit, and the one
#: ``core/parts.quantity_slug`` calls "the schematic spelling").
#:
#: It is written out here rather than left to the scan below because this is the
#: shape question -- *is the field the notation* -- and the scan answers the
#: different one, *what is it worth*. The two are not each other's spare tyre:
#: every witness below is refused by the guard named, and by that one only.
#:
#: * this pattern owns the **anchoring** (``C4u7``: a designator in front of the
#:   notation is not a value field) and the **presence of a mantissa** -- digits
#:   in front of the unit letter, which the resistance side requires too (``u7``
#:   states nothing, ``0u1`` says 0.1 in a spelling this reader does not own);
#: * the scan owns the fraction's **presence and length** (``100n`` and ``22u``
#:   state the value outright; ``2N2222``'s four digits after the letter are the
#:   cap the resistance notation puts on ``4K700``), the size-code strip and the
#:   leading zero (``12345u7``, ``0603u1``).
#:
#: The fraction is **optional** as of 087. 077 read the shape with the fraction
#: required and recorded the gap rather than opening it, and the gap was this
#: repository's own: ``core/parts.quantity_slug`` calls ``100n`` "the schematic
#: spelling" and addresses shelf parts by it (``cap.100n_0402``), so the shelf and
#: the board were two spellings of one value (071 §2, same family, same reason).
#: What opening it cost was measured before it was decided: the four tokens this
#: repository's own corpus gains are ``100n``/``330u``/``540n``/``540N``, no board
#: changes state, no eval case moves -- and one scenario does, on purpose
#: (``tests/test_036_subcircuit.py``'s RC insert declares ``1n``; reading it turns
#: a previously invisible RC pair into a finding, which ``edit apply``'s own "a
#: change may not add findings" gate then refuses to save). That gate's 口径 is a
#: separate decision and was not touched here; the scenario's own expectation is
#: what was re-pinned, with the measurement written down in its comment.
_CAP_NOTATION_FIELD_RE = re.compile(r"\d+[unp\u00b5\u03bc]\d*", re.IGNORECASE)


def _mid_letter_farads(text: str) -> float | None:
    """The mid-letter reading of a field written exactly that way, or None.

    Anchoring, one quantity along from the resistance side's
    (:func:`parse_resistance_ohms`): the notation has to span the field, so a
    reading that covers only part of a longer string is not a reading of it. The
    witnesses say why that is not pedantry -- a Value field and a part number are
    read by the same module (:func:`_mid_letter_readings`), and a merchant part
    number is full of mid-letter-shaped groups that are not values: ``2N2222`` is
    a transistor whose ``2N2`` would read as 2.2 nF, ``1N4148`` a diode whose
    ``1N4`` would read as 1.4 nF. What refuses those two is the scan's own cap on
    the fraction -- four digits after the letter is the tail the resistance
    notation refuses in ``4K700`` -- while the whole-field match below refuses
    ``C4u7``, which is not the notation at all. ``540N`` *is* the notation (540 nF,
    087 on), and the part number that contains it, ``IRF540N``, is refused by the
    anchoring rather than by its shape. ``2n2`` is the capacitance and ``2N2222``
    is not a capacitor.

    Two questions, in this order, and neither answers the other:

    * **is the field the notation** (:data:`_CAP_NOTATION_FIELD_RE`, a whole-field
      match) -- what is read has to *be* the field, not sit inside it, and the
      field has to carry digits in front of the unit letter;
    * **what is it worth** -- the scan the resistance side uses
      (:func:`_mid_letter_readings`), which owns the fraction's presence and
      length, the size-code strip, the mantissa's three figures and the meaning of
      the fraction.

    Its own refusal is ``vendor_prefix=False``: a Value field states the value and
    nothing else, so the digit run in front of the unit letter is the mantissa
    rather than a manufacturer's code. That is the resistance side's own rule,
    ``47R`` reading as 47 Ω -- and it is why ``0u1`` states nothing here, as
    ``0K1`` states nothing there.
    """
    if _CAP_NOTATION_FIELD_RE.fullmatch(text) is None:
        return None  # not this notation as a whole field
    readings = _mid_letter_readings(text, kind="capacitance", vendor_prefix=False)
    if len(readings) != 1:
        return None  # absent or ambiguous -- both are "cannot read"
    farads, (text_read, _anchor) = next(iter(readings.items()))
    if _cap_spelling(text_read) != _cap_spelling(text):
        return None  # the reading does not cover the field's own figures
    return _finite(farads)


def decode_eia_3digit(code: str, base: float) -> float | None:
    """``"471"`` with base 1.0 (ohms) -> 470.0; base 1e-12 (farads) -> 100 nF.

    The EIA code is mantissa x 10^exponent, expressed in ``base`` units:
    ``10**exponent`` is the decade, ``base`` only switches the unit."""
    if not re.fullmatch(r"\d{3}", code):
        return None
    mantissa = int(code[:2])
    exponent = int(code[2])
    if base <= 0:
        return None
    return mantissa * (10.0 ** exponent) * base


#: The trade's **mid-letter** notations: the multiplier takes the place of the
#: decimal point. One notation per quantity, one scan over both
#: (:func:`_mid_letter_readings`) -- "one verdict has one implementation" is the
#: repository's rule (071 §2).
#:
#: * resistance — ``4K7`` = 4.7 kΩ, ``4R7`` = 4.7 Ω, ``10K2`` = 10.2 kΩ,
#:   ``1M0`` = 1 MΩ. Uppercase ``M`` only: lowercase ``m`` is milli in some
#:   houses and mega in others, so it is refused;
#: * capacitance (issue #23) — ``4u7`` = 4.7 µF, ``2n2`` = 2.2 nF, ``5p1`` =
#:   5.1 pF: ``u``/``n``/``p`` are the units the trade prints. The fraction is the
#:   digits after the decimal point when there are any, and a whole number of the
#:   unit needs none: ``100n`` = 100 nF and ``22u`` = 22 µF are the trade's own
#:   spelling for those values (087, and the resistance side has always read the
#:   same way round). ``m``/``M`` (``4m7`` = 4.7 mF) is refused, for a blunter
#:   reason than the resistance letter: a millifarad part is far enough outside
#:   the vocabulary that the tokens spelling it are pseudo-readings rather than
#:   values. The unit spelled out in full is still read — ``1mF`` is the suffix
#:   grammar's, above.
#:
#: The micro letter has three code points (MICRO SIGN, GREEK SMALL LETTER MU,
#: and the GREEK CAPITAL LETTER MU both upper-case to) and they are one unit
#: (task 055); the scan matches all three, and :func:`_cap_spelling` is what a
#: caller compares a field against.
_MID_LETTER_BASE = {"R": 1.0, "K": 1e3, "M": 1e6}
_CAP_MID_LETTER_BASE = {"U": 1e-6, "N": 1e-9, "P": 1e-12}

#: ``<mantissa><letter><fraction>``, the mantissa being the digit run directly
#: before the letter (a run longer than three digits contributes its last three).
_MID_LETTER_RE = re.compile(r"(\d*)([RKM])(\d*)", re.IGNORECASE)
_CAP_MID_LETTER_RE = re.compile(r"(\d*)([unp\u00b5\u03bc])(\d*)", re.IGNORECASE)

#: The two notations in the one shape :func:`_mid_letter_readings` dispatches on:
#: ``kind`` -> (scan, letters-and-multipliers). The scan spells its letters and
#: the table says what they are worth, so the reading looks the letter up in the
#: table of the notation it was scanned by.
_MID_LETTER_KINDS = {
    "resistance": (_MID_LETTER_RE, _MID_LETTER_BASE),
    "capacitance": (_CAP_MID_LETTER_RE, _CAP_MID_LETTER_BASE),
}


def _without_leading_size(run: str) -> str:
    """``run`` with a leading package size code removed (071 §3②).

    ``CRCW0603``10K0FKEA states 10.0 kΩ in its own field, but the digit run in
    front of the ``K`` is ``060310``: read whole it also spells ``310K0`` =
    310 kΩ, a reading that crosses the size field into the value field -- and a
    board declaring 310K **passed** on it (issue #24). The size is grammar, not
    mantissa, so it comes off first. A run that was nothing but the size leaves
    no mantissa at all (:func:`_mid_letter_readings` then produces no reading),
    which is the same rule from the other side: ``CC0603KRX7R9BB104``'s
    ``603K`` was read off its size field.
    """
    for size in _SIZE_CODE_PREFIXES:
        if run.startswith(size):
            return run[len(size):]
    return run


def _mid_letter_readings(
    token: str, *, vendor_prefix: bool = True, kind: str = "resistance"
) -> dict[float, tuple[str, str]]:
    """The trade's mid-letter readings inside ``token``: value -> (text, anchor).

    The one implementation of the notations (071 §2), one scan per quantity
    (:data:`_MID_LETTER_KINDS`): the board's Value field
    (:func:`parse_resistance_ohms`, :func:`_mid_letter_farads`) and a part number
    (:func:`mpn_resistance_readings`) are read by the same scan, because a
    ``4K7`` typed into an editor and a ``4K7`` printed inside an MPN are one
    grammar and "one verdict has one implementation" is the repository's rule --
    and a ``4u7`` is that notation read in the capacitor's unit (issue #23).
    One flag separates the callers, and only one: ``vendor_prefix``. Inside
    an MPN the digits in front of the letter can be a manufacturer's code
    (``074K7``), so every suffix is a candidate; a Value field states the value
    and nothing else, so ``47R`` is 47 Ω and not 47 Ω or 7 Ω.

    ``kind`` picks the notation: ``"resistance"`` (``R``/``K``/``M``) or
    ``"capacitance"`` (``u``/``n``/``p`` and the micro spellings). Which letters
    a notation holds and what each is worth is the whole of the difference
    between them; every structural refusal below is one rule for both.

    The **located** candidate carries :data:`ANCHOR_MID_LETTER` (071 §1 C): the
    one read off a run the size code was stripped off, so that run *is* the
    value field (``CRCW0603``10``K0``). A run that came through the strip
    untouched was never located -- ``RL0805FR-070R1L``'s ``07`` is a date code,
    not a size -- so every reading off it is a vendor-prefix guess and carries
    none (078 A1, issue #32). All of them are still returned: 046's "both
    readings are legitimate" and the amplitude waiver do not need an anchor, and
    dropping the right reading is what turns a correct board into a violation.
    The anchor only decides who is allowed to *accuse*.

    Two refusals are grammar, not vendor shapes (071 §3②/§4):

    * the digit run may carry the package size in front of the mantissa
      (``0603``10``K0``), which comes off before anything is read;
    * a letter with **no** digit run in front of it states no value:
      ``WR06X1002FTL``'s ``R06`` was read as 0.06 Ω and ``GRM188R71C104KA01D``'s
      ``R71`` as 0.71 Ω, both of them the series-name letter followed by the
      series' own numbering (issues #25/#26). A letter right after a letter is
      the same case -- the digit run before it is empty by construction, since
      the scan's first group is the *whole* run of digits the letter follows.

    What this returns is a **reading**, not a verdict: it scans for the notation
    wherever it sits in the token, and it is the caller that asks whether the
    reading spans the field it was handed (:func:`parse_resistance_ohms`,
    :func:`_mid_letter_farads`). That question is 071 §1 C's anchor in the
    Value-field form, and it is what keeps a part number out of the capacitor
    notation -- ``2N2222`` contains ``2N2``.
    """
    scan, bases = _MID_LETTER_KINDS[kind]
    readings: dict[float, tuple[str, str]] = {}
    for match in scan.finditer(token):
        run, raw_letter, fraction = match.group(1), match.group(2), match.group(3)
        if raw_letter == "m":
            continue  # lowercase m: milli in some houses, mega in others
        letter = raw_letter.upper()
        if letter == "\u039c":
            letter = "U"  # both micro spellings upper-case to the Greek capital
        if letter not in bases:
            continue  # the scan and its table are one whitelist, spelled twice
        if len(fraction) > 2:
            continue  # the shunt form (`R005`) and any longer tail
        located_run = _without_leading_size(run)
        if not located_run:
            continue  # no mantissa: a series name, or the size code alone
        # 078 A1: did the strip *locate* the value segment? Only a run the size
        # code came off is one -- see the anchor line below.
        located = len(located_run) < len(run)
        run = located_run
        base = bases[letter]
        trimmed = run[-3:]
        # Mantissa candidates: inside a part number every suffix of the digit
        # run that does not start with a zero ("074" -> "74", "4"), because a
        # vendor's own prefix in front of the value is indistinguishable from a
        # longer mantissa; in a Value field the run itself, because there is no
        # vendor prefix to guess at.
        if vendor_prefix:
            candidates = [
                trimmed[index:]
                for index in range(len(trimmed))
                if not trimmed[index:].startswith("0")
            ]
            # 078 A2: a tail that is exactly one ``0`` is no mantissa in either
            # reading, but in front of the resistance notation's own ``R`` it is
            # the board's spelling of a sub-ohm value. Yageo's date code is what
            # puts a value's zero head inside the run (``RL0805FR-070R1L``'s
            # ``07``), so refusing the ``0`` refused the part's real value --
            # 0.1 Ω was absent from the readings while its date code's 70.1 Ω
            # sat there alone and took the blame for a correctly written board
            # (issue #32). One letter, one shape: ``0K1``/``0u1`` and the
            # capacitor side stay refused (the value grammar owns those
            # spellings, as the comment below says), and ``R`` with three
            # digits is refused above, before this line.
            if letter == "R":
                candidates.extend(
                    trimmed[index:]
                    for index in range(len(trimmed))
                    if trimmed[index:] == "0"
                )
        else:
            # No vendor prefix to guess at, so the run itself is the mantissa --
            # unless it starts with a zero, which is not a significant figure in
            # either reading (`0K1` states nothing; the spellings that do start
            # that way, `0R5`/`0R01`, are the board grammar's and are read above
            # it). In the capacitor notation the same refusal leaves `0u1`
            # unread, and there the suffix grammar holds the spellings that do
            # state the value (`0.1uF`, `100nF`).
            candidates = [] if trimmed.startswith("0") else [trimmed]
        for position, mantissa in enumerate(candidates):
            digits = mantissa + fraction
            if not digits:
                continue
            value = int(digits) / (10 ** len(fraction)) * base
            if value <= 0:
                continue
            anchor = (
                ANCHOR_MID_LETTER
                if located and position == 0
                else ""  # 078 A1: see the note at the strip
            )
            readings.setdefault(value, (f"{mantissa}{letter}{fraction}", anchor))
    return readings


#: The ohm suffix a board value may carry (``10kΩ``, ``10 ohm``), and the three
#: spellings of the *board* grammar: ``R`` as the decimal point (``0R01``),
#: ``R`` in front (``R010``), and a bare number with an optional ``k``/``m``/``M``.
_OHM_SUFFIX_RE = re.compile(r"(?i)\s*(?:ohms?|\u03a9)\s*$")
_R_DECIMAL_RE = re.compile(r"(\d+)[Rr](\d+)")
_LEADING_R_RE = re.compile(r"[Rr](\d+)")
_PLAIN_OHMS_RE = re.compile(r"(\d+(?:\.\d+)?)([kKmM]?)")
_PLAIN_OHMS_MULTIPLIERS = {"": 1.0, "k": 1e3, "K": 1e3, "m": 1e-3, "M": 1e6}


def parse_resistance_ohms(value: str) -> float | None:
    """A board resistor value -> ohms, or None when it is not one this reads.

    Moved here from ``rules/connectivity.py`` (071 §2) so that the rule comparing
    a Value field with an MPN reads both sides in one module. The defect that
    moved it: the trade's mid-letter spelling (``4K7`` = 4.7 kΩ) is read by
    :func:`_mid_letter_readings` for **MPNs**, while the board side answered None
    -- and a rule handed a value it cannot parse skips the part entirely, which
    is worse than a miss (issue #23).

    Two grammars, tried in this order:

    * the **board grammar** an editor accepts: a unit suffix, ``R`` as the
      decimal point (``0R01``, ``4R7``), a leading ``R`` (``R010``), milliohms
      (``10m``), or a bare number with a ``k``/``m``/``M`` multiplier;
    * the trade's **mid-letter** notation (``4K7``, ``1K0``, ``2M2``, ``100R``),
      which must span the whole value: a Value field states one value, so
      ``10MF`` is a millifarad capacitor and not ``10M``.

    The order is load-bearing, not stylistic: ``4.7kΩ`` is the board grammar's
    4700 Ω, while the mid-letter scan would take the ``7K`` after the dot for
    7000 Ω. Every string the board grammar already reads keeps its exact value,
    so this is additive -- what it refuses today it goes on refusing.

    Two refusals come before the grammar (issues #27/#31): a first token longer
    than the cap is not read at all, and a quantity that overflowed to a
    non-finite float is not a resistance this can state -- ``"1" * 400`` used to
    come back as ``inf`` and took the whole review down when the rule divided a
    decoded reading by it.
    """
    text = (value or "").strip()
    if not text or _too_long(text):
        return None
    body = _OHM_SUFFIX_RE.sub("", text).strip()
    if not body:
        return None
    match = _R_DECIMAL_RE.fullmatch(body)
    if match is not None:
        return _finite(float(f"{match.group(1)}.{match.group(2)}"))
    match = _LEADING_R_RE.fullmatch(body)
    if match is not None:
        return _finite(float(f"0.{match.group(1)}"))
    match = _PLAIN_OHMS_RE.fullmatch(body)
    if match is not None:
        return _finite(
            float(match.group(1)) * _PLAIN_OHMS_MULTIPLIERS[match.group(2)]
        )
    readings = _mid_letter_readings(body, vendor_prefix=False)
    if len(readings) != 1:
        return None  # absent or ambiguous -- both are "cannot read"
    value_ohms, (text_read, _anchor) = next(iter(readings.items()))
    if text_read.upper() != body.upper():
        return None  # the notation does not span the value field
    return _finite(value_ohms)


def mpn_resistance_readings(mpn: str) -> list[tuple[float, str]]:
    """Every legitimate reading of the MPN's resistance notation.

    Why a *list* and not one number: a vendor prefixes its own coding to the
    value, and by shape that prefix is indistinguishable from a longer mantissa.
    Yageo's ``RC0603FR-074K7L`` is a 4.7 kΩ part whose value text is ``4K7``
    ("07" is the vendor's code), but ``074K7`` reads just as grammatically as
    ``74K7`` = 74.7 kΩ. Deciding between them from the string alone is guessing,
    so this returns the **set** of readings, deduplicated by value; the caller
    matches the board's own declared value against them, and an MPN whose readings
    *all* disagree is still a contradiction.

    Five shapes are read, each one's whitelist written out at its own helper --
    the mid-letter notation (:func:`_mid_letter_readings`), 厚声's
    three-figures-plus-exponent field in both its alphabets
    (:func:`_letter_exponent_reading`, :func:`_numeric_exponent_reading`), the
    E-96 four-figure code (:func:`_e96_reading`) and the shunt field between a
    tolerance letter and its ``R`` (:func:`_shunt_reading`). They are additive
    on purpose (task 046): an MPN where two conventions are by shape
    indistinguishable keeps *both* readings, because the caller -- the board's
    own declared value -- is the only thing that can choose, and dropping the
    right reading is what turns a correct board into a violation.

    Returns ``[(ohms, notation_text), …]`` — empty when the MPN states its value
    in EIA three-digit form instead (``FRC0805J471``) or in no readable form at
    all. This is the shape every existing caller wants; a verdict that has to say
    *how far it may trust* a reading asks
    :func:`mpn_resistance_candidates`, which carries the anchor alongside. What
    it refuses, deliberately:

    * lowercase ``m`` (milli vs mega);
    * ``R`` followed by **three** digits — ``R005``, ``R100``, ``3R005``: the
      shunt convention, where the digits before the ``R`` are part of the part's
      coding rather than a mantissa (measured: ``JER2512F3R005`` is a 5 mΩ
      shunt, and reading it as 3.005 Ω would turn a correct board into a
      violation). Those MPNs still answer UNKNOWN, exactly as before 043;
    * a letter with no digit run in front of it (``WR06X1002FTL``, ``AR03BTCX5001``)
      and a package size code in front of one (``CRCW060310K0FKEA``): see
      :func:`_mid_letter_readings` -- 071 §3②/§4 turned both of those
      pseudo-readings off.

    **This is the resistor decoder.** Capacitor MPNs contain mid-letter-looking
    groups incidentally (``CC0603KRX7R9BB104`` reads as 7R9), so only a caller
    that already knows the part is a resistor may consult it.

    It delegates, so the length cap of :func:`mpn_resistance_candidates` (issue
    #27) covers this entry point too: a first token over the cap answers ``[]``.
    """
    return [
        (value, text) for value, text, _anchor in mpn_resistance_candidates(mpn)
    ]


def mpn_resistance_candidates(mpn: str) -> list[tuple[float, str, str]]:
    """Every reading with the syntactic anchor it carries: ``(ohms, text, anchor)``.

    ``anchor`` is one of :data:`ANCHOR_E96_LETTER`, :data:`ANCHOR_MID_LETTER`,
    :data:`ANCHOR_PACKAGE_CONTEXT` or ``""`` for a reading that carries none
    (071 §1 C). The rule that compares a board value with an MPN asks this one:
    a reading with an anchor may support a WARN, an unanchored one may not --
    a string that merely contains digits is not evidence enough to accuse a BOM
    line of being wrong. :func:`mpn_resistance_readings` is this minus the anchor,
    for callers that only want the numbers.

    A first token over the length cap is not decompiled at all (issue #27) -- the
    whole scan below (``_mid_letter_readings``' backtracks among it) is quadratic
    in the token's length, and an MPN that long is not a part number.
    """
    if not mpn or _too_long(mpn):
        return []
    token = mpn.strip().split()[0] if mpn.strip() else ""
    readings = dict(_mid_letter_readings(token))
    for reading in (
        _letter_exponent_reading(token),
        _numeric_exponent_reading(token),
        _e96_reading(token),
        _shunt_reading(token),
    ):
        if reading is not None:
            value, text, anchor = reading
            readings.setdefault(value, (text, anchor))
    return sorted(
        (value, text, anchor) for value, (text, anchor) in readings.items()
    )


#: The size codes that head a part number (task 046). Requiring one is what
#: keeps :func:`_letter_exponent_reading` -- whose field is three digits and a
#: letter, exactly the shape the mid-letter reader also mangles -- off every
#: token that is not a 厚声 (Uni-Royal) part number.
_SIZE_HEADS = (
    "01005", "0201", "0402", "0603", "0805", "1206", "1210", "1812", "2010",
    "2512",
)

#: 厚声's ordering rule for a ≤±1% part's resistance: three significant figures
#: followed by an exponent character, and the small exponents are written as
#: letters — ``J`` = 10^-1, ``K`` = 10^-2, ``L`` = 10^-3. So ``0603WAF220KT5E``
#: is a 2.2 Ω part (220 x 10^-2) and ``0603WAF330JT5E`` is 33 Ω (330 x 10^-1).
#: The whole field is anchored on the size head, the power/tolerance letters and
#: the taping suffix; a numeric exponent (``0603WAF1002T5E`` = 100 x 10^2) is
#: read by its own sibling below, not here.
_LETTER_EXPONENT_FIELD_RE = re.compile(
    r"^(?:01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)"
    r"[A-Z0-9]{2,4}(\d{3})([JKL])T[A-Z0-9]+$"
)
_LETTER_EXPONENT = {"J": -1, "K": -2, "L": -3}

#: The same 厚声 field with a **numeric** exponent (task 048) — the same three
#: significant figures, a digit instead of a letter, and the same size head /
#: power-tolerance letters / taping suffix anchors: ``0603WAF1002T5E`` =
#: 100 x 10^2 = 10 kΩ, ``0805W8F1003T5E`` = 100 x 10^3 = 100 kΩ. The 5% (E-24)
#: members of the family lead the field with a ``0`` — ``0805W8J0103T5E`` =
#: 010 x 10^3 = 10 kΩ, the worked example in the ordering rule — which the same
#: reading handles, a leading zero leaving the significand unchanged.
_NUMERIC_EXPONENT_FIELD_RE = re.compile(
    r"^(?:01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)"
    r"[A-Z0-9]{2,4}(\d{3})(\d)T[A-Z0-9]+$"
)


def _letter_exponent_reading(token: str) -> tuple[float, str, str] | None:
    """厚声's three-figures-plus-letter-exponent field, or None.

    ``0603WAF220KT5E`` is the witness this exists for (task 046): its ``220K``
    is 2.2 Ω, while the mid-letter reader takes the same characters for
    ``220K`` = 220 kΩ and, dropping the leading ``2``, for 20 kΩ as well — the
    reading the rule quoted as "decodes to 2e+04 Ω" for a part the board
    correctly declares as 2.2 Ω.

    The field's own grammar (size head, letters, exponent letter, ``T`` tail) is
    what makes it a code field, so this reading carries
    :data:`ANCHOR_E96_LETTER` -- ``0603WAF1002T5E``'s family is the witness the
    anchor was ruled for (071 §1 C, oracle ruling 2026-09-29: the board's 19
    signed MPN defects stay WARNs, and they are all read by that field).
    """
    m = _LETTER_EXPONENT_FIELD_RE.match(token)
    if m is None:
        return None
    figures, letter = m.group(1), m.group(2)
    value = int(figures) * (10.0 ** _LETTER_EXPONENT[letter])
    if value <= 0:
        return None
    return value, f"{figures}{letter} (letter-exponent field)", ANCHOR_E96_LETTER


def _numeric_exponent_reading(token: str) -> tuple[float, str, str] | None:
    """厚声's three-figures-plus-digit-exponent field, or None.

    Five of the six shapes this module reads state the value *inside* an MPN
    whose other fields are letters; this one is the reason a plate of 厚声
    part numbers came back UNKNOWN: ``0603WAF1002T5E`` and ``0805W8F1003T5E``
    state 10 kΩ and 100 kΩ in the same ordering grammar as 046's ``220K``, only
    with a digit exponent, and no other reader owns the ``...T5E`` tail (the
    E-96 reader needs the token to *end* in four figures, and the mid-letter
    reader finds no ``R``/``K``/``M`` in ``WAF1002T5E``).

    Same anchor as its sibling: the field is pinned by the size head and the
    ``T`` tail, so the four figures sit in a code field rather than in a run of
    digits that happens to be three long.
    """
    m = _NUMERIC_EXPONENT_FIELD_RE.match(token)
    if m is None:
        return None
    figures, exponent = m.group(1), m.group(2)
    value = int(figures) * (10.0 ** int(exponent))
    if value <= 0:
        return None
    return value, f"{figures}{exponent} (numeric-exponent field)", ANCHOR_E96_LETTER


#: The four-figure package sizes (task 046). This is :data:`_PACKAGE_TAILS` plus
#: 2512: the three-figure guard above never needed 2512, and a four-figure field
#: ending in one of these is a size, not a value.
_E96_PACKAGE_TAILS = ("0402", "0603", "0805", "1206", "1210", "2512")

#: The E-96 four-figure code at the very end of the token — three significant
#: figures and a power of ten (``5001`` = 500 x 10^1 = 5.00 kΩ), optionally
#: followed by a single tolerance letter (``5001F``). The lookbehind keeps it
#: off the tail of a longer digit run (``...05001``).
_E96_FIELD_RE = re.compile(r"(?<!\d)(\d{4})([A-Za-z])?$")


def _e96_reading(token: str) -> tuple[float, str, str] | None:
    """The E-96 four-figure code, or None (absent, guarded or ambiguous).

    The witness is Viking's ``AR03BTCX5001`` (task 046): a 5.00 kΩ part, whose
    ``5001`` this reader turns into 500 x 10^1 Ω -- while the mid-letter reader
    used to read the same token as 0.03 Ω (``R03``) and the rule quoted that
    figure. Since 071 §4 the ``R03`` pseudo-reading is gone (a series-name
    letter followed by the series' numbering is not a value), so the surviving
    reading is this one; the ambiguity guard below stays for the tokens where
    two *real* four-figure candidates still disagree.

    The anchor is the **trailing tolerance letter** (071 §1 C): ``RK73H1JTTD1002F``
    states ``1002F``, and the letter is what pins the four figures as a value
    code. A bare four-figure run at the end of a token (``AR03BTCX5001``) carries
    none -- it may still *match* the board's value, but it may not, by itself,
    accuse the board of being wrong.
    """
    candidates: dict[float, tuple[str, bool]] = {}
    for m in _E96_FIELD_RE.finditer(token):
        figures = m.group(1)
        if figures in _E96_PACKAGE_TAILS or figures.startswith("0"):
            continue
        value = int(figures[:3]) * (10.0 ** int(figures[3]))
        if value <= 0:
            continue
        candidates.setdefault(value, (figures, m.group(2) is not None))
    if len(candidates) != 1:
        return None
    value, (figures, lettered) = next(iter(candidates.items()))
    return value, f"{figures} (E-96)", ANCHOR_E96_LETTER if lettered else ""


def _shunt_reading(token: str) -> tuple[float, str, str] | None:
    """The ``FR400`` shunt field, or None.

    ``FRL1210FR400TS`` states 400 mΩ as ``FR400`` (task 046): a tolerance
    letter, the ``R`` decimal point, then the fraction's digits, with the
    hundredths written out rather than dropped. ``R`` alone (``AR03BTCX5001``)
    and ``R`` after a digit (``JER2512F3R005``, 043) are not this shape.

    The tolerance letter the shape starts with is an anchor in the same sense as
    the E-96 one (071 §1 C): a coded field, not a run of digits. Declared rather
    than assumed: the ruling's three anchors do not name this shape, and the
    reading it produces is the one the FPC board's ``R1`` is declared against
    (400 mΩ), so anchoring it keeps THIS MESSAGE SET honest — a shunt whose
    board value is wrong is a BOM contradiction a reader has to see.
    """
    m = _SHUNT_FIELD_RE.search(token)
    if m is None:
        return None
    digits = m.group(1)
    value = int(digits) / (10.0 ** len(digits))
    if value <= 0:
        return None
    return value, f"{m.group(0)} (shunt field)", ANCHOR_E96_LETTER


def mpn_value_code(mpn: str) -> str | None:
    """The EIA value code inside an MPN, or None when absent/ambiguous/refused.

    Whitelist (measured shapes), analysed on the MPN's first token (suffixes
    like ``" TS"`` are packaging notes, not part of the code): the value code
    sits at the token's end (``FRC0805J471``) or directly before a single
    tolerance/dielectric letter (``CL10A225KA8NNNC`` -> ``225K``;
    ``CC0603KRX7R9BB104`` -> ``BB104``). A candidate that completes a package
    size is rejected; differing candidates are ambiguity, and ambiguity is
    None -- the rule downstream reports "cannot decode" rather than picking
    one.

    A token written in one of the *other* notations the trade prints
    (:func:`_non_eia_notation`) is None as well: the digits in it are a
    resistance, a voltage rating or an electrolytic capacitance, and reading
    them as an EIA code is what produced 3.3e-11 F for a 330 uF part
    (task 015). A shunt's ``R`` field counts here (``FRL1210FR400TS``'s ``400``
    is 400 mΩ, task 046), and so does a token whose digits are a value in a unit
    this decoder does not read at all (:func:`_foreign_unit_code`): a polymer
    electrolytic prints microfarads, so reading ``SPZ1HM100E07O00RAXXX``'s
    ``100`` against the picofarad base is what reported 10 pF for a 10 µF part.

    A token's **leading** metric size code is a size too, on the same footing as
    the trailing imperial one (:data:`_METRIC_SIZE_CODES`, 071 §3①): reading
    ``GRM188R71C104KA01D``'s ``188`` as a value put two candidates in the list
    (``188`` and ``104``), ambiguity turned the whole token into None, and a
    100 nF part the board declares correctly reported "contains no decodable
    value code" -- a silent miss, which is what issue #22 measured.

    A first token over the length cap answers None without being scanned (issue
    #27): the guards below are quadratic in the token's length -- each one walks
    or backtracks over the whole digit run -- and a string that long is not a part
    number.
    """
    if not mpn or _too_long(mpn):
        return None
    token = mpn.strip().split()[0] if mpn.strip() else ""
    if not token or _non_eia_notation(token) or _foreign_unit_code(token):
        return None
    candidates: list[str] = []
    for m in _CODE_RE.finditer(token):
        code = m.group(1)
        before = token[: m.start()]
        after = token[m.end():]
        # Package guard: the group completes a size code -> it is a size.
        if len(before) >= 1 and (before[-1] + code) in _PACKAGE_TAILS:
            continue
        # Leading metric size guard: a whole three-figure run at the front of
        # the token, spelled as one of the metric sizes, is the size field.
        if (
            code in _METRIC_SIZE_CODES
            and _digit_run(token, m.start()) == code
            and not any(ch.isdigit() for ch in before)
        ):
            continue
        if after == "":
            candidates.append(code)
            continue
        # A single letter right after the code is a tolerance/dielectric
        # marker (``225K``, ``BB104``); anything starting with a digit is a
        # second number this whitelist does not try to read.
        if re.fullmatch(r"[A-Z][A-Za-z0-9]*", after):
            candidates.append(code)
    distinct = sorted(set(candidates))
    if len(distinct) != 1:
        return None  # absent or ambiguous -- both are "cannot decode"
    return distinct[0]


def has_package_context(mpn: str) -> bool:
    """True when the MPN's first token states a package size of its own.

    The predicate behind :data:`ANCHOR_PACKAGE_CONTEXT` (071 §1 C): a whole
    digit run that IS a size code, imperial or metric (``CC0603``KRX7R9BB104,
    ``GRM188``R71C104KA01D). It is the difference between a three-digit value
    code and three digits that happen to sit in a string -- the electrolitics of
    issue #25 (``UVR1H101MPD``, ``50YXF100MEFC``, ``NRWA221M35V``,
    ``16ZLH470MEFC``, ``EEU-FC1H101``) carry no size at all.
    """
    if not mpn:
        return False
    token = mpn.strip().split()[0] if mpn.strip() else ""
    return any(
        match.group(0) in _SIZE_CODE_RUNS for match in re.finditer(r"\d+", token)
    )


def mpn_value_code_anchor(mpn: str) -> tuple[str | None, str]:
    """``(code, anchor)`` -- :func:`mpn_value_code` with the anchor it carries.

    A capacitor's value code is a *string reading* like any other, so 071 §1 C
    asks it the same question: is the reading anchored? Here the anchor is the
    package context (:func:`has_package_context`) -- the one thing that turns
    three digits into a code field. ``None`` code keeps ``""``.

    The length cap (issue #27) is stated here as well as inside
    :func:`mpn_value_code`, because this is an entry point of its own: a first
    token over the cap answers ``(None, "")`` -- no code and no anchor to ask
    :func:`has_package_context` about.
    """
    if _too_long(mpn):
        return None, ""
    code = mpn_value_code(mpn)
    if code is None:
        return None, ""
    return code, (ANCHOR_PACKAGE_CONTEXT if has_package_context(mpn) else "")


# --------------------------------------------------------------------------
# voltage — the third quantity of this family (issue #53)
# --------------------------------------------------------------------------

#: A rail voltage as one field. An optional sign, then one of two grammars:
#:
#: * the trade's **mid-letter** notation read in volts (``3V3`` = 3.3 V, ``1V8``
#:   = 1.8 V). This is the R/K/M notation with the unit letter in the middle
#:   instead of a prefix, and it is not a hypothetical spelling: the repository
#:   writes it. ``blocklib/blocks.portmeta.json`` declares the CH340's VCC rail
#:   as ``"voltage": "3V3"``, so a parser that does not read it reads half the
#:   repository's own rails wrong.
#: * a number with an optional ``V`` that may stand off it by a space (``3.3``,
#:   ``3.30V``, ``3.3 V``, ``5V``) — the editor grammar, the same shape
#:   :func:`parse_capacitance_farads`'s ``100nF`` branch has.
#:
#: The two cannot overlap, and that is the whole point of writing them as two
#: branches rather than one alternation: the mid-letter one *requires* a
#: fraction after the ``V``, so ``3V`` is the suffix grammar's alone and no
#: string is read by both. The same split :func:`parse_capacitance_farads`
#: states for the same reason — every string one grammar reads keeps the exact
#: value, so a new grammar is additive.
_VOLTAGE_RE = re.compile(
    r"(?P<sign>[+-]?)"
    r"(?:"
    r"(?P<int>\d*)[Vv](?P<frac>\d{1,2})"
    r"|"
    r"(?P<num>\d+(?:\.\d+)?|\.\d+)\s*[Vv]?"
    r")"
)


def parse_voltage_volts(value: str) -> float | None:
    """A rail voltage -> volts, or None when it is not one this reads.

    Added by issue #53. The defect it closes is not a wrong number but a
    *comparison that had no number to make*: ``validate_spec``'s power-tree
    gate asked ``port.voltage != source.voltage`` on the raw strings, so a
    source declaring ``3V3`` and a sink declaring ``3.3V`` — the same rail,
    written the two ways this repository itself writes it — was reported as a
    VIOLATION. The gate is fail-closed by design, so the cost of a missing
    parser was a correctly wired board stopped at gate four.

    A sign is part of the field, not decoration: ``+24V`` and ``-12V`` name a
    real supply and a real rail, and a grammar that refused the sign would make
    the one spelling that carries polarity the one spelling that cannot be
    compared. The number is the reading either way.

    What is refused is everything this cannot state, and it is refused the way
    the other two parsers refuse: empty, a first token over the cap
    (:func:`_too_long`, issue #27), a string with no number in it (``abc``),
    more than one token (``5V 1A``), a doubled unit (``3V3V``), and a
    mid-letter mantissa that is empty or starts with a zero. That last pair
    follows the mid-letter grammar's own rule rather than inventing one —
    ``V3`` and ``0V5`` are the shape ``0K1`` is refused by, and
    :func:`_mid_letter_readings` is where the reasoning is written down.

    Deliberately **not** here: prefixes. A rail is stated in volts; ``5V``/``12V``
    /``3V3`` cover the vocabulary of ``blocks.portmeta.json``. ``5V5`` and
    ``3300mV`` are a different question (and would want the same
    package-size-free treatment this parser has, which
    :func:`_mid_letter_readings` cannot give it: it strips *package size codes*
    off a mantissa, so it would read the ``1206`` in a 1206 V rail as a size
    and refuse the field).

    :func:`_finite` closes it (issue #31), like every other parser here.
    """
    if not value or _too_long(value):
        return None
    text = value.strip()
    if not text:
        return None
    match = _VOLTAGE_RE.fullmatch(text)
    if match is None:
        return None
    fraction = match.group("frac")
    if fraction is not None:
        whole = match.group("int")
        if not whole or whole.startswith("0"):
            return None  # ``V3`` states no value; ``0V5`` is not significant
        magnitude = int(whole + fraction) / (10 ** len(fraction))
    else:
        magnitude = float(match.group("num"))
    if match.group("sign") == "-":
        magnitude = -magnitude
    return _finite(magnitude)
