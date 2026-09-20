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
  all -- is None, and the rule reports UNKNOWN instead of guessing.
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
    """The EIA value code inside an MPN, or None when absent/ambiguous.

    Whitelist (measured shapes), analysed on the MPN's first token (suffixes
    like ``" TS"`` are packaging notes, not part of the code): the value code
    sits at the token's end (``FRC0805J471``) or directly before a single
    tolerance/dielectric letter (``CL10A225KA8NNNC`` -> ``225K``;
    ``CC0603KRX7R9BB104`` -> ``BB104``). A candidate that completes a package
    size is rejected; differing candidates are ambiguity, and ambiguity is
    None -- the rule downstream reports "cannot decode" rather than picking
    one.
    """
    if not mpn:
        return None
    token = mpn.strip().split()[0] if mpn.strip() else ""
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
