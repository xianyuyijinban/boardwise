"""Value decoding and unit parsing helpers for the PARAM rules (task 011d).

Three parsers live here, all *whitelist* parsers: they either recognise the
string or return None — "unparseable" must never become "zero" or "whatever
the digits look like".

- :func:`parse_capacitance_farads` — board capacitor values (``100nF``,
  ``0.1uF``, ``22pF``). A bare number without a unit is None: for capacitors
  the convention-less number is ambiguous by two orders of magnitude and the
  011 family exists because a guess got recorded as a fact.
- :func:`decode_eia_3digit` — the EIA three-digit value code (``471`` ->
  47x10^1). The *base unit depends on the part kind*: ohms for resistors,
  picofarads for capacitors, so the caller supplies the multiplier.
- :func:`mpn_value_code` — extract the EIA code from an MPN, whitelisted to
  the shapes the big manufacturers actually print: the code at the end of the
  string, optionally followed by a single tolerance letter (``...225K``), or
  embedded before a dielectric/tolerance tail (``...BB104``). Package codes
  are guarded: a trailing group that completes ``0402/0603/0805/1206/1210``
  is a *size*, not a value. Anything else -- two candidate codes, no code at
  all, or a token written in a notation that only *looks* like an EIA code
  (see :func:`_non_eia_notation`) -- is None, and the rule reports UNKNOWN
  instead of guessing.
"""

from __future__ import annotations

import re

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
#: * ``_ELECTROLYTIC_RE`` -- the electrolytic layout, a case size
#:   (``PA50V330M10x15``'s ``10x15``) or a voltage printed before the value
#:   (``50V330``), where ``330M`` is 330 uF with a tolerance letter and not an
#:   EIA code at all. The second marker also fires on TDK's voltage code
#:   (``C1608X5R1V225KT000E``'s ``1V225``): that part refuses either way, and
#:   refusing a token whose digits are already unreadable costs nothing.
#:
#: The guards must stay independent: each one owns witnesses the others leave
#: alone, because a witness refused by two guards cannot detect the loss of
#: either (a mutation that disabled one stayed green while every voltage-tail
#: witness was also matched by the R pattern -- measured 2026-09-21, task 015
#: sec.4.2).
_R_NOTATION_RE = re.compile(r"\d[Rr]\d{1,3}")
_VOLTAGE_TAIL_RE = re.compile(r"\d{3}[A-Z]\d{3}")
_ELECTROLYTIC_RE = re.compile(r"\d[xX]\d|\d+[Vv]\d{3}")

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
    """Board capacitor value -> farads, with an explicit unit required."""
    if not value:
        return None
    m = _CAP_RE.match(value.strip())
    if m is None:
        return None
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
    return float(m.group(1)) * factor


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


#: The trade's **mid-letter** resistance notation: the multiplier takes the place
#: of the decimal point, ``4K7`` = 4.7 kΩ, ``4R7`` = 4.7 Ω, ``10K2`` = 10.2 kΩ,
#: ``1M0`` = 1 MΩ. The letters and what they multiply by (uppercase ``M`` only:
#: lowercase ``m`` is milli in some houses and mega in others, so it is refused).
_MID_LETTER_BASE = {"R": 1.0, "K": 1e3, "M": 1e6}

#: ``<mantissa><letter><fraction>``, the mantissa being the digit run directly
#: before the letter (a run longer than three digits contributes its last three).
_MID_LETTER_RE = re.compile(r"(\d*)([RKM])(\d*)", re.IGNORECASE)


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
    the mid-letter notation below, 厚声's three-figures-plus-exponent field in
    both its alphabets (:func:`_letter_exponent_reading`,
    :func:`_numeric_exponent_reading`), the E-96 four-figure code
    (:func:`_e96_reading`) and the shunt field between a tolerance letter and
    its ``R`` (:func:`_shunt_reading`). They are additive on purpose (task 046):
    an MPN where two conventions are by shape indistinguishable keeps *both*
    readings, because the caller -- the board's own declared value -- is the only
    thing that can choose, and dropping the right reading is what turns a correct
    board into a violation.

    Returns ``[(ohms, notation_text), …]`` — empty when the MPN states its value
    in EIA three-digit form instead (``FRC0805J471``) or in no readable form at
    all. What it refuses, deliberately:

    * lowercase ``m`` (milli vs mega);
    * ``R`` followed by **three** digits — ``R005``, ``R100``, ``3R005``: the
      shunt convention, where the digits before the ``R`` are part of the part's
      coding rather than a mantissa (measured: ``JER2512F3R005`` is a 5 mΩ
      shunt, and reading it as 3.005 Ω would turn a correct board into a
      violation). Those MPNs still answer UNKNOWN, exactly as before 043.

    **This is the resistor decoder.** Capacitor MPNs contain mid-letter-looking
    groups incidentally (``CC0603KRX7R9BB104`` reads as 7R9 / 3K / 603K), so only
    a caller that already knows the part is a resistor may consult it.
    """
    if not mpn:
        return []
    token = mpn.strip().split()[0] if mpn.strip() else ""
    readings: dict[float, str] = {}
    for match in _MID_LETTER_RE.finditer(token):
        run, raw_letter, fraction = match.group(1), match.group(2), match.group(3)
        if raw_letter == "m":
            continue  # lowercase m: milli in some houses, mega in others
        letter = raw_letter.upper()
        if len(fraction) > 2:
            continue  # the shunt form (`R005`) and any longer tail
        base = _MID_LETTER_BASE[letter]
        # Mantissa candidates: the suffixes of the digit run that do not start
        # with a zero ("074" -> "74", "4"), or nothing at all when the letter is
        # the only thing before the fraction ("R47" = 0.47 Ω).
        trimmed = run[-3:]
        candidates = (
            [trimmed[index:] for index in range(len(trimmed)) if not trimmed[index:].startswith("0")]
            if trimmed
            else [""]
        )
        for mantissa in candidates:
            digits = mantissa + fraction
            if not digits:
                continue
            value = int(digits) / (10 ** len(fraction)) * base
            if value <= 0:
                continue  # a zero-ohm reading is not evidence of anything
            readings.setdefault(value, f"{mantissa}{letter}{fraction}")
    for reading in (
        _letter_exponent_reading(token),
        _numeric_exponent_reading(token),
        _e96_reading(token),
        _shunt_reading(token),
    ):
        if reading is not None:
            value, text = reading
            readings.setdefault(value, text)
    return sorted(readings.items())


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


def _letter_exponent_reading(token: str) -> tuple[float, str] | None:
    """厚声's three-figures-plus-letter-exponent field, or None.

    ``0603WAF220KT5E`` is the witness this exists for (task 046): its ``220K``
    is 2.2 Ω, while the mid-letter reader takes the same characters for
    ``220K`` = 220 kΩ and, dropping the leading ``2``, for 20 kΩ as well — the
    reading the rule quoted as "decodes to 2e+04 Ω" for a part the board
    correctly declares as 2.2 Ω.
    """
    m = _LETTER_EXPONENT_FIELD_RE.match(token)
    if m is None:
        return None
    figures, letter = m.group(1), m.group(2)
    value = int(figures) * (10.0 ** _LETTER_EXPONENT[letter])
    if value <= 0:
        return None
    return value, f"{figures}{letter} (letter-exponent field)"


def _numeric_exponent_reading(token: str) -> tuple[float, str] | None:
    """厚声's three-figures-plus-digit-exponent field, or None.

    Five of the six shapes this module reads state the value *inside* an MPN
    whose other fields are letters; this one is the reason a plate of 厚声
    part numbers came back UNKNOWN: ``0603WAF1002T5E`` and ``0805W8F1003T5E``
    state 10 kΩ and 100 kΩ in the same ordering grammar as 046's ``220K``, only
    with a digit exponent, and no other reader owns the ``...T5E`` tail (the
    E-96 reader needs the token to *end* in four figures, and the mid-letter
    reader finds no ``R``/``K``/``M`` in ``WAF1002T5E``).
    """
    m = _NUMERIC_EXPONENT_FIELD_RE.match(token)
    if m is None:
        return None
    figures, exponent = m.group(1), m.group(2)
    value = int(figures) * (10.0 ** int(exponent))
    if value <= 0:
        return None
    return value, f"{figures}{exponent} (numeric-exponent field)"


#: The four-figure package sizes (task 046). This is :data:`_PACKAGE_TAILS` plus
#: 2512: the three-figure guard above never needed 2512, and a four-figure field
#: ending in one of these is a size, not a value.
_E96_PACKAGE_TAILS = ("0402", "0603", "0805", "1206", "1210", "2512")

#: The E-96 four-figure code at the very end of the token — three significant
#: figures and a power of ten (``5001`` = 500 x 10^1 = 5.00 kΩ), optionally
#: followed by a single tolerance letter (``5001F``). The lookbehind keeps it
#: off the tail of a longer digit run (``...05001``).
_E96_FIELD_RE = re.compile(r"(?<!\d)(\d{4})([A-Za-z])?$")


def _e96_reading(token: str) -> tuple[float, str] | None:
    """The E-96 four-figure code, or None (absent, guarded or ambiguous).

    The witness is Viking's ``AR03BTCX5001`` (task 046): a 5.00 kΩ part, whose
    ``5001`` this reader turns into 500 x 10^1 Ω, while the mid-letter reader
    reads the same token as 0.03 Ω (``R03``) — the reading the rule quoted as
    "decodes to 0.03 Ω". Two candidates with different values are ambiguity and
    add nothing at all.
    """
    candidates: dict[float, str] = {}
    for m in _E96_FIELD_RE.finditer(token):
        figures = m.group(1)
        if figures in _E96_PACKAGE_TAILS or figures.startswith("0"):
            continue
        value = int(figures[:3]) * (10.0 ** int(figures[3]))
        if value <= 0:
            continue
        candidates.setdefault(value, figures)
    if len(candidates) != 1:
        return None
    value, figures = next(iter(candidates.items()))
    return value, f"{figures} (E-96)"


def _shunt_reading(token: str) -> tuple[float, str] | None:
    """The ``FR400`` shunt field, or None.

    ``FRL1210FR400TS`` states 400 mΩ as ``FR400`` (task 046): a tolerance
    letter, the ``R`` decimal point, then the fraction's digits, with the
    hundredths written out rather than dropped. ``R`` alone (``AR03BTCX5001``)
    and ``R`` after a digit (``JER2512F3R005``, 043) are not this shape.
    """
    m = _SHUNT_FIELD_RE.search(token)
    if m is None:
        return None
    digits = m.group(1)
    value = int(digits) / (10.0 ** len(digits))
    if value <= 0:
        return None
    return value, f"{m.group(0)} (shunt field)"


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
    """
    if not mpn:
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
