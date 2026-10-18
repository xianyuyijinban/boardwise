"""The parameters an archived catalogue string states about a **passive** (517).

The product problem this module is the level-0 half of: the report's datasheet
gate used to list every passive whose board ``Value`` and MPN the decoders could
not read, and the real parameters were sitting in the 立创 archive all along —
in ``LCSC Part Name`` (``330kΩ ±5% 250mW 厚膜电阻``) and, for the MPN, in the
value/tolerance/rating fields the trade prints there (``0603B103K500NT`` = 10 nF
±10% 50 V). This batch squeezes the archive; **no network call** (the web-search
batch is the next one).

Three public readings:

* :func:`catalogue_params` — value / tolerance / power / voltage off a
  catalogue **string** (``LCSC Part Name``, ``Type``). Human prose, read
  token by token; a token this grammar does not recognise is skipped, never
  guessed at. A field that yields no value (or a value it cannot pin a unit
  on) yields **nothing**: an absent parameter is reported as absent, which is
  what "parse failure is not 'missing data'" needs.
* :func:`mpn_params` — the same four quantities off the **MPN**, through the
  readers :mod:`boardwise.core.values` already owns (the MPN decoders are
  unchanged — this module only asks them and scales the answers).
* :func:`crosscheck` — the three-way agreement over (archive, board ``Value``,
  MPN). **At least two agreeing readings** confirm a parameter; one or two
  clashing readings are a WARN with each reading written out. A single
  available reading is never enough — it confirms nothing and warns of
  nothing; it is just a reading.

The vocabulary deliberately stays narrow. Tolerance letters are the EIA/trade
set (``B/J/K/M/F/G`` …) read **only** where a catalogue token or an MPN field
states one; a letter floating in prose is not a tolerance. Power is
``<number><W>`` (``250mW``, ``1/4W``, ``0.25W``). Voltage is
``<number><V>`` or an MPN voltage tail the rating reader already recognises
(``103K500`` -> 50 V). Anything else returns ``None`` for that parameter —
the same whitelist discipline every parser in ``core.values`` holds.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field


def _finite(quantity: float) -> bool:
    """A quantity that overflowed to ±inf (or started as NaN) is unreadable."""
    return math.isfinite(quantity)


#: Significant figures a comparison keeps (the E-96 grid is three figures and
#: the catalogue prints the same three): ``104 * 10^3 * 1e-12`` and
#: ``100 * 1e-9`` are one 100 nF to four significant figures and two floats
#: in ``==``. Comparing rounded to :data:`_SIG_FIGURES` keeps the code-path
#: arithmetic and the unit-suffix arithmetic one value.
_SIG_FIGURES = 4


def _sig(value: float) -> float:
    """The comparison form of a quantity: rounded to :data:`_SIG_FIGURES`."""
    if value == 0 or not _finite(value):
        return value
    return round(value, -int(math.floor(math.log10(abs(value)))) + (_SIG_FIGURES - 1))

#: How a parsed quantity travels: the SI value plus the **token** it was read
#: from, so a report can quote its evidence rather than ask a reader to trust
#: a number. ``text`` is empty when the reading came from a code field whose
#: figures the token does not spell alone.
@dataclass(frozen=True)
class Quantity:
    value: float
    text: str = ""


@dataclass(frozen=True)
class MetaParams:
    """What one source states about a passive's four headline parameters.

    ``None`` means "this source does not state it" — never "it is zero" and
    never "we guessed". ``raw`` is the string the reading came from, for the
    report's evidence column.
    """

    value: Quantity | None = None
    tolerance: Quantity | None = None  # fraction: 0.05 = ±5%
    power: Quantity | None = None      # watts
    voltage: Quantity | None = None    # volts (rating)
    raw: str = ""

    def stated(self) -> dict[str, Quantity]:
        """The parameters this source actually states, dropping the absent ones."""
        return {
            name: quantity
            for name, quantity in (
                ("value", self.value),
                ("tolerance", self.tolerance),
                ("power", self.power),
                ("voltage", self.voltage),
            )
            if quantity is not None
        }


@dataclass
class CrosscheckRow:
    """One parameter's three-way verdict, with every reading written out.

    ``state`` is one of :data:`CONFIRMED` (≥2 sources agree),
    :data:`WARN_CONFLICT` (≥2 available and they disagree — **or** exactly two
    available and they disagree, which is the same WARN, never a silent pick),
    or :data:`SINGLE` (only one source states it: carried, but confirming
    nothing), or absent from the result entirely (no source states it).
    """

    param: str
    state: str
    readings: dict[str, float] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)
    agreeing: tuple[str, ...] = ()

    @property
    def confirmed(self) -> bool:
        return self.state == CONFIRMED


CONFIRMED = "confirmed"
WARN_CONFLICT = "warn-conflict"
SINGLE = "single"

#: Parameter order the report prints in.
PARAM_ORDER: tuple[str, ...] = ("value", "tolerance", "power", "voltage")


# ---------------------------------------------------------------------------
# catalogue-string grammar (LCSC Part Name / Type)
# ---------------------------------------------------------------------------

#: SI prefixes a catalogue quantity token may carry, with their scale. ``m``
#: is milli here (``250mW``); the catalogue does not write megawatts.
_SI_PREFIXES: dict[str, float] = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "m": 1e-3, "k": 1e3, "K": 1e3, "M": 1e6,
}

#: ``330kΩ`` / ``100nF`` / ``10uH`` — number, optional SI prefix, unit letter
#: with the optional ``Ω`` the catalogue appends. A bare ``330k`` (no unit) is
#: **not** read: the unit is what names the quantity.
_CAT_VALUE_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+)?)"
    r"(?P<prefix>[pnuµμmkKM])?"
    r"(?P<unit>[ΩFHV]|Ω|ohm|H)$"
)

#: ``±5%`` / ``5%`` / ``±0.5%`` — the tolerance token. Read only with the
#: percent sign: a bare ``5`` in prose is not a tolerance.
_CAT_TOLERANCE_RE = re.compile(r"^[±±]?\s*(?P<num>\d+(?:\.\d+)?)\s*%$")

#: ``250mW`` / ``1/4W`` / ``0.25W`` / ``2W`` — the power token. The fraction
#: spelling is how the trade writes a quarter/half/eighth watt.
_CAT_POWER_RE = re.compile(
    r"^(?:(?P<whole>\d+)\s*/\s*(?P<div>\d+)|(?P<num>\d+(?:\.\d+)?)(?P<prefix>[munµμ])?)"
    r"\s*[Ww]$"
)

#: ``50V`` / ``6.3V`` / ``25V`` — the voltage-rating token. A bare number
#: before ``V`` in prose is a rating; ``3V3`` (a rail name) is refused here
#: because the catalogue does not write ratings that way and a rail name is
#: not a rating.
_CAT_VOLTAGE_RE = re.compile(r"^(?P<num>\d+(?:\.\d+)?)\s*[Vv]$")


def _catalogue_value_token(token: str) -> Quantity | None:
    """A value token with its unit stated (``330kΩ``, ``100nF``, ``10uH``)."""
    match = _CAT_VALUE_RE.match(token)
    if match is None:
        return None
    number = float(match.group("num"))
    prefix = match.group("prefix")
    scale = _SI_PREFIXES[prefix] if prefix else 1.0
    value = number * scale
    # ``1mΩ`` is a real milliohm; ``1MF`` is refused (the trade prints
    # microfarads as u/µ, and ``mF``-in-prose is a pseudo-reading the
    # mid-letter readers refuse for the same reason).
    if match.group("unit").lower() in ("f", "h") and prefix in ("m", "M"):
        return None
    if not _finite(value) or value <= 0:
        return None
    return Quantity(value, token)


def _catalogue_tolerance_token(token: str) -> Quantity | None:
    """``±5%`` -> 0.05. Only the percent spelling is a tolerance."""
    match = _CAT_TOLERANCE_RE.match(token)
    if match is None:
        return None
    return Quantity(float(match.group("num")) / 100.0, token)


def _catalogue_power_token(token: str) -> Quantity | None:
    """``250mW`` / ``1/4W`` / ``0.25W`` -> watts."""
    match = _CAT_POWER_RE.match(token)
    if match is None:
        return None
    if match.group("whole") is not None:
        divisor = float(match.group("div"))
        if divisor <= 0:
            return None
        watts = float(match.group("whole")) / divisor
        return Quantity(watts, token) if _finite(watts) and watts > 0 else None
    number = float(match.group("num"))
    prefix = match.group("prefix") or ""
    watts = number * _SI_PREFIXES.get(prefix, 1.0)
    if not _finite(watts) or watts <= 0:
        return None
    return Quantity(watts, token)


def _catalogue_voltage_token(token: str) -> Quantity | None:
    """``50V`` -> 50 volts, a rating token in prose."""
    match = _CAT_VOLTAGE_RE.match(token)
    if match is None:
        return None
    volts = float(match.group("num"))
    if not _finite(volts) or volts <= 0:
        return None
    return Quantity(volts, token)


def catalogue_params(text: str) -> MetaParams:
    """Read the four parameters off a catalogue string, or state none of them.

    Token by token over whitespace; every token that parses as one of the four
    quantities is taken, the rest are skipped (they are the prose —
    ``厚膜电阻``, ``X7R``, ``0603`` — and skipping is the whitelist
    discipline: an unrecognised token is not a hint). ``X7R``/``0603`` are
    refused by construction: they carry no unit and no percent sign, so none
    of the four token grammars matches them.

    **One value token wins, the first one** — a catalogue line states one
    value. A second value-shaped token (rare; a stray number with a unit)
    does not overwrite it and does not become a conflict: the archive is one
    source and this reader is its single opinion. Ambiguity inside one source
    is the MPN decoders' question, not this reader's.
    """
    if not text or not text.strip():
        return MetaParams()
    value: Quantity | None = None
    tolerance: Quantity | None = None
    power: Quantity | None = None
    voltage: Quantity | None = None
    for token in text.replace("±", " ±").split():
        if value is None and token not in ("±", "+/-"):
            read = _catalogue_value_token(token)
            if read is not None:
                value = read
                continue
        read = _catalogue_tolerance_token(token)
        if read is not None:
            if tolerance is None:
                tolerance = read
            continue
        read = _catalogue_power_token(token)
        if read is not None:
            if power is None:
                power = read
            continue
        read = _catalogue_voltage_token(token)
        if read is not None:
            if voltage is None:
                voltage = read
            continue
    return MetaParams(
        value=value, tolerance=tolerance, power=power, voltage=voltage,
        raw=text,
    )


# ---------------------------------------------------------------------------
# MPN reading — the values.py decoders, asked and scaled
# ---------------------------------------------------------------------------

#: Tolerance-letter -> fraction, the EIA set the trade prints after a value
#: code (``0603B103K500NT``'s ``K``) and the precision set on E-96 fields
#: (``...1002F``'s ``F``). Read **only** in the MPN field positions named
#: below, never by scanning the token for a floating letter.
_TOLERANCE_LETTERS: dict[str, float] = {
    "B": 0.001, "C": 0.0025, "D": 0.005, "F": 0.01, "G": 0.02,
    "J": 0.05, "K": 0.10, "M": 0.20,
}


def mpn_params(mpn: str, *, kind: str = "") -> MetaParams:
    """Read the parameters an MPN states, through the existing decoders.

    ``kind`` narrows the base unit of the value code — ``"capacitor"`` reads
    picofarads, ``"inductor"`` refuses (there is no inductance parser in this
    repository to ask, and inventing one is a second decoder), anything else
    reads ohms. Refusing an unknown kind's value is deliberate: a code read
    against the wrong base is a wrong number, and a wrong number is worse
    than none.

    Tolerance is read from the one field that names it — the ceramic
    ``<value><tol><voltage>`` tail (``0603B103K500NT``) — and voltage from
    that tail's rating group (``500`` -> 50 V) or :func:`mpn_voltage_rating`'s
    ``<value><tol><rating>`` tail. The letter is read **only** there: a
    letter elsewhere in the token is packaging or dielectric, not a tolerance.

    A resistance reading is taken only when the decoder family returns **one**
    unambiguous candidate — several candidates is the decoders' own
    「ambiguous」, and the answer here is then None for the same reason it is
    None there. A reading whose figures overflowed to ±inf
    (:func:`_finite`) is None like any unreadable one.
    """
    from .values import (
        decode_eia_3digit,
        mpn_resistance_candidates,
        mpn_value_code,
        mpn_voltage_rating,
    )

    if not mpn or not mpn.strip():
        return MetaParams()
    token = mpn.strip().split()[0]
    value: Quantity | None = None
    voltage: Quantity | None = None
    if kind == "capacitor":
        code = mpn_value_code(mpn)
        if code is not None:
            farads = decode_eia_3digit(code, 1e-12)
            if farads is not None and _finite(farads) and farads > 0:
                value = Quantity(farads, code)
    elif kind != "inductor":
        candidates = mpn_resistance_candidates(mpn)
        # One unambiguous reading only: several candidates is the decoders'
        # own "ambiguous", and ambiguity is None here too.
        if len(candidates) == 1:
            ohms = candidates[0][0]
            if _finite(ohms) and ohms > 0:
                value = Quantity(ohms, candidates[0][1])
    # The rating readers: the voltage-tail field this module's tolerance read
    # sits in, then 092's ``<value><tol><voltage>`` reader.
    rating = mpn_voltage_rating(token)
    if rating is not None and _finite(rating[0]) and rating[0] > 0:
        voltage = Quantity(rating[0], rating[1])
    tolerance = _mpn_tail_tolerance(token, voltage is not None or value is not None)
    return MetaParams(
        value=value, tolerance=tolerance, voltage=voltage, raw=mpn,
    )


#: The ceramic field ``<value><tol letter><voltage code><packaging>``
#: (``103K500NT``): the tolerance letter sits **between** the value group and
#: the voltage group, which is the one position in an MPN that names a
#: tolerance. Pinned to the field shape — value figures, letter, rating
#: figures, packaging tail — exactly as ``_CAP_VOLTAGE_TAIL_RE`` pins it.
_MPN_TAIL_TOLERANCE_RE = re.compile(
    r"(?P<value>\d{3})(?P<tol>[BCDFGJKM])(?P<rating>\d{3}|\d[Rr]\d)(?:[A-Z]{2,4})?$"
)


def _mpn_tail_tolerance(token: str, require_field: bool) -> Quantity | None:
    """The tolerance letter of a ceramic ``<value><tol><voltage>`` tail.

    ``require_field`` keeps the letter read off a token that actually states
    the field (a value or a rating came out of it); a bare tail match on a
    token the other readers read nothing from is a letter-shaped fragment of
    packaging, not a tolerance.
    """
    if not require_field:
        return None
    for start in range(len(token)):
        match = _MPN_TAIL_TOLERANCE_RE.match(token, start)
        if match is not None:
            return Quantity(_TOLERANCE_LETTERS[match.group("tol")], match.group(0))
    return None


# ---------------------------------------------------------------------------
# the three-way crosscheck
# ---------------------------------------------------------------------------

#: The archive source's name in a crosscheck result (the report quotes it).
SOURCE_ARCHIVE = "archive"
SOURCE_BOARD = "board"
SOURCE_MPN = "mpn"


def _board_params(board_value: str, *, kind: str = "") -> MetaParams:
    """The board ``Value`` field read as a parameter source.

    The value half goes through the parsers the gate already trusts
    (``parse_resistance_ohms`` / ``parse_capacitance_farads``); tolerance,
    power and voltage are read by this module's catalogue grammars, because a
    board that writes ``100nF ±10% 50V`` in ``Value`` is writing prose in the
    same vocabulary the archive uses.
    """
    from .values import parse_capacitance_farads, parse_resistance_ohms

    text = (board_value or "").strip()
    if not text:
        return MetaParams()
    params = catalogue_params(text)
    if params.value is None:
        if kind == "capacitor":
            farads = parse_capacitance_farads(text)
            if farads is not None and farads > 0:
                params = MetaParams(
                    value=Quantity(farads, text),
                    tolerance=params.tolerance,
                    power=params.power,
                    voltage=params.voltage,
                    raw=text,
                )
        elif kind != "inductor":
            ohms = parse_resistance_ohms(text)
            if ohms is not None and ohms > 0:
                params = MetaParams(
                    value=Quantity(ohms, text),
                    tolerance=params.tolerance,
                    power=params.power,
                    voltage=params.voltage,
                    raw=text,
                )
    return params


def crosscheck(
    archive_text: str,
    board_value: str,
    mpn: str,
    *,
    kind: str = "",
) -> dict[str, CrosscheckRow]:
    """The three-way agreement, per parameter — the module docstring's rule.

    ``archive_text`` is the archive string (``LCSC Part Name``, falling back
    to ``Type``), ``board_value`` the placement's ``Value`` field, ``mpn`` the
    part number. Returns one row per parameter **any source states**:

    * ≥2 sources agree -> :data:`CONFIRMED`, with the agreeing sources named;
    * ≥2 available and they disagree -> :data:`WARN_CONFLICT`, every reading
      written out. **Two available and clashing is a WARN** — a silent pick
      is the one answer this module must never give;
    * exactly one available -> :data:`SINGLE` (carried, confirms nothing).

    A parameter no source states is absent from the result: absence is
    "missing metadata", the caller's own category.
    """
    sources: dict[str, MetaParams] = {}
    archive = catalogue_params(archive_text)
    if archive.stated():
        sources[SOURCE_ARCHIVE] = archive
    board = _board_params(board_value, kind=kind)
    if board.stated():
        sources[SOURCE_BOARD] = board
    mpn_read = mpn_params(mpn, kind=kind)
    if mpn_read.stated():
        sources[SOURCE_MPN] = mpn_read

    rows: dict[str, CrosscheckRow] = {}
    for param in PARAM_ORDER:
        readings = {
            name: read.stated()[param]
            for name, read in sources.items()
            if param in read.stated()
        }
        if not readings:
            continue
        names_by_value: dict[float, list[str]] = {}
        for name, quantity in readings.items():
            names_by_value.setdefault(_sig(quantity.value), []).append(name)
        best = max(names_by_value.items(), key=lambda item: len(item[1]))
        if len(best[1]) >= 2:
            state = CONFIRMED
        elif len(readings) >= 2:
            # Two or more sources, no value stated twice: every reading is
            # written out and the row is a WARN, whatever the count.
            state = WARN_CONFLICT
        else:
            state = SINGLE
        rows[param] = CrosscheckRow(
            param=param,
            state=state,
            readings={name: q.value for name, q in readings.items()},
            evidence={name: q.text for name, q in readings.items()},
            agreeing=tuple(best[1]) if state == CONFIRMED else (),
        )
    return rows


def confirmed_params(rows: dict[str, CrosscheckRow]) -> dict[str, CrosscheckRow]:
    """The subset of a crosscheck that **confirmed** — the gate-clearing read."""
    return {name: row for name, row in rows.items() if row.confirmed}


def warns_params(rows: dict[str, CrosscheckRow]) -> dict[str, CrosscheckRow]:
    """The subset that WARNs — the conflicts a report must write out."""
    return {name: row for name, row in rows.items() if row.state == WARN_CONFLICT}


__all__ = [
    "CONFIRMED",
    "PARAM_ORDER",
    "CrosscheckRow",
    "MetaParams",
    "Quantity",
    "SOURCE_ARCHIVE",
    "SOURCE_BOARD",
    "SOURCE_MPN",
    "SINGLE",
    "WARN_CONFLICT",
    "catalogue_params",
    "confirmed_params",
    "crosscheck",
    "mpn_params",
    "warns_params",
]
