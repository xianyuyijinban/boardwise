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
#: The three guards must stay independent: each one owns witnesses the other
#: two leave alone, because a witness refused by two guards cannot detect the
#: loss of either (a mutation that disabled one stayed green while every
#: voltage-tail witness was also matched by the R pattern -- measured
#: 2026-09-21, task 015 sec.4.2).
_R_NOTATION_RE = re.compile(r"\d[Rr]\d{1,3}")
_VOLTAGE_TAIL_RE = re.compile(r"\d{3}[A-Z]\d{3}")
_ELECTROLYTIC_RE = re.compile(r"\d[xX]\d|\d+[Vv]\d{3}")


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
    )


def parse_capacitance_farads(value: str) -> float | None:
    """Board capacitor value -> farads, with an explicit unit required."""
    if not value:
        return None
    m = _CAP_RE.match(value.strip())
    if m is None:
        return None
    return float(m.group(1)) * _CAP_UNITS[m.group(2).lower()]


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
    (task 015).
    """
    if not mpn:
        return None
    token = mpn.strip().split()[0] if mpn.strip() else ""
    if not token or _non_eia_notation(token):
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
