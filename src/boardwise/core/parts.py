"""The curated part library: the data contract, the value gate, the vocabulary.

008c will need a **deterministic shelf** to pick from, so this module is the
shelf's shape (`blocklib/parts.json`), the loader that validates it, and the
two pieces of policy that make a lookup trustworthy:

* **the value gate** — task 008b/#202's discipline, restated as code. An
  explicit ``Ω``/``ohm`` query is a *quantity*, not a substring: the value must
  come from a **named field**, the comparison is numerical, and the SI prefix is
  **case-sensitive** because ``mΩ`` and ``MΩ`` are nine decades apart. Nothing
  in a part number, a C-number or a prose sentence can supply a resistance.
  Failing to resolve is a failure, not a fuzzy match.
* **the footprint vocabulary table** — 006b's finding was that the library
  footprint name (``R0402``) and the human label (``0402``) are two different
  vocabularies, and that using the wrong one is how a 0402 part became a 0603
  placement. The only mapping allowed between them is the explicit table below
  (``0402`` -> ``{R0402, C0402, L0402, LED0402}``, disambiguated by a category
  word in the query). A word that is not in the table is **not mapped** —
  guessing a library name from a size is exactly the failure this table exists
  to prevent.

Nothing here touches the network or the editor: this is the offline half, and
`engines/select.py` is the picker that uses it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

#: Written into the library file so a stale one fails loudly rather than being
#: read with today's rules.
PART_LIBRARY_KIND = "boardwise-part-library"
#: v2 (task 011b): entries may carry an electrical ``category`` and a ``facts``
#: object. v1 files are rejected outright — the loader never guesses what a
#: pre-facts entry meant to claim.
SCHEMA_VERSION = 2

#: The electrical category of an entry (task 011b §2.2). Deliberately **not**
#: the shelf bucket that :func:`category_of`/``make_key`` compute from the
#: footprint: that one files the part on the shelf, this one says what the
#: part *is* — and the golden board's U3 (a resistor wearing a ``U`` prefix)
#: is the measured proof that the two must not be conflated. A value outside
#: this table is a loader error; extending the table is a decision, not a
#: silent fallback.
CATEGORY_VOCABULARY = frozenset({
    "resistor", "capacitor", "inductor", "led", "diode", "connector",
    "crystal", "ic.ldo", "ic.usb-uart", "ic.mcu", "ic.charger",
    "buzzer", "switch", "module",
})

#: Honest tri-state for facts we may or may not have evidence for. Used for
#: `basic` and for whether the bridge corroborated a footprint name: ``None``
#: means "not known", never "no".
TRUE, FALSE, UNKNOWN = True, False, None


class PartError(ValueError):
    """The part library is malformed, or a lookup cannot be answered."""


# --------------------------------------------------------------------------
# quantities: the value gate (#202)
# --------------------------------------------------------------------------

#: ``Ω`` is U+03A9 GREEK CAPITAL OMEGA and ``Ω`` is U+2126 OHM SIGN; both
#: appear in real catalog text, so both are accepted. The word forms are
#: matched case-insensitively *on the unit only* — the prefix must not be
#: folded, which is why this is an inline scoped flag and never a global one.
_OHM_UNIT = r"(?:Ω|Ω|(?i:ohms?))"

#: A resistance written in full: ``10kΩ``, ``0.33Ω``, ``330mΩ``, ``4.7 ohm``.
_RESISTANCE = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<number>\d+(?:\.\d+)?|\.\d+)\s*"
    r"(?P<prefix>[mMkK]?)\s*" + _OHM_UNIT + r"(?![A-Za-z0-9_]|[.,][0-9])"
)

#: The same value with the prefix doing duty as the decimal point — the way a
#: schematic writes it: ``4R7`` = 4.7, ``5k1`` = 5.1k, ``1M0`` = 1M. Applied
#: **only** to a curated field's own value (see :func:`parse_resistance_field`),
#: never to a catalog description or an MPN: ``1M`` in a part number is a
#: package code, not a megohm.
_RESISTANCE_SHORT = re.compile(
    r"(?P<number>\d+)\s*(?P<prefix>[mMkKrR])\s*(?P<frac>\d+)?"
)

#: Case is the whole point: ``m`` is milli, ``M`` is mega, and ``k``/``K`` are
#: the same decade (both spellings are common). ``R`` is the decimal marker.
_SCALE: dict[str, Decimal] = {
    "": Decimal(1),
    "R": Decimal(1),
    "r": Decimal(1),
    "m": Decimal("0.001"),
    "k": Decimal(1000),
    "K": Decimal(1000),
    "M": Decimal(1000000),
}

#: Characters that, immediately before a match, mean the "resistance" is really
#: an arithmetic expression or a range: ``1/2Ω``, ``1,000Ω``, ``<5Ω``. Those
#: must fail closed instead of being read as their numeric tail.
_OPERATOR_BEFORE = frozenset(".,/+-*^<>=~≤≥±×÷−")


def _ohm_tokens(text: str) -> list[re.Match[str]]:
    """Every ohm-unit token in ``text`` (the gate's trigger)."""
    return list(re.finditer(_OHM_UNIT, text))


def _resistance_occurrences(text: str) -> list[Decimal]:
    """Every parseable resistance in ``text``, rejecting operator-adjacent ones.

    Deliberately *not* a search-and-substring: the unit must be present, the
    number must be whole, and a value preceded by an operator is dropped rather
    than reinterpreted.
    """
    out: list[Decimal] = []
    for match in _RESISTANCE.finditer(text):
        before = text[: match.start()].rstrip()
        if before and before[-1] in _OPERATOR_BEFORE:
            continue
        out.append(Decimal(match.group("number")) * _SCALE[match.group("prefix")])
    return out


def parse_resistance_field(text: str, *, shorthand: bool = False) -> Decimal | None:
    """Read a resistance from a **whole declared field**, or ``None``.

    ``fullmatch`` on purpose: a field that merely *contains* a number is not a
    declaration. ``shorthand`` additionally accepts the schematic spelling
    (``4R7``, ``5k1``) and is passed only for a curated entry's own value —
    never for a catalog description, which is prose.
    """
    stripped = (text or "").strip()
    if not stripped:
        return None
    match = _RESISTANCE.fullmatch(stripped)
    if match is not None:
        return Decimal(match.group("number")) * _SCALE[match.group("prefix")]
    if not shorthand:
        return None
    match = _RESISTANCE_SHORT.fullmatch(stripped)
    if match is None:
        return None
    scale = _SCALE[match.group("prefix")]
    whole = Decimal(match.group("number"))
    fraction = match.group("frac")
    if fraction is None:
        return whole * scale
    # `5k1` is 5.1k: the prefix letter is the decimal point, so the fraction
    # scales with the same power, `len(fraction)` digits in.
    return (whole + Decimal(f"0.{fraction}")) * scale


@dataclass(frozen=True)
class ResistanceQuery:
    """The outcome of looking for a resistance in a query string.

    ``active`` means the query *carries* an ohm unit, and from then on the gate
    is on: ``ohms is None`` (an unparseable, ambiguous or repeated expression)
    must yield **no candidates at all**, not a fuzzy fallback.
    """

    active: bool
    ohms: Decimal | None
    remainder: str


def resistance_query(text: str) -> ResistanceQuery:
    """Split a query into "the resistance it asks for" and "everything else"."""
    units = _ohm_tokens(text)
    if not units:
        return ResistanceQuery(active=False, ohms=None, remainder=text)

    matches = _RESISTANCE.finditer(text)
    found: list[Decimal] = []
    count = 0
    for match in matches:
        count += 1
        before = text[: match.start()].rstrip()
        if before and before[-1] in _OPERATOR_BEFORE:
            continue
        found.append(Decimal(match.group("number")) * _SCALE[match.group("prefix")])

    # One unit token, one parseable number, and no second opinion anywhere in
    # the string. Anything else fails closed.
    distinct = set(found)
    if len(units) != 1 or count != 1 or len(distinct) != 1:
        return ResistanceQuery(active=True, ohms=None, remainder=text)
    remainder = _RESISTANCE.sub(" ", text, count=1)
    return ResistanceQuery(active=True, ohms=next(iter(distinct)), remainder=remainder)


def resistance_of_declared_field(text: str, *, shorthand: bool = False) -> Decimal | None:
    """A resistance a curated entry *declares*, or ``None`` if it declares none."""
    return parse_resistance_field(text, shorthand=shorthand)


def quantities_in_description(text: str) -> set[Decimal] | None:
    """Every explicit resistance in free text, or ``None`` when malformed.

    ``None`` (an ohm unit with no parseable number) is a *failure*, not an empty
    set: a description that says ``1/2Ω`` must not be treated as "no claim".
    """
    units = _ohm_tokens(text)
    if not units:
        return set()
    values = _resistance_occurrences(text)
    if len(values) != len(units):
        return None
    return set(values)


# --------------------------------------------------------------------------
# footprint vocabulary (the only allowed mapping)
# --------------------------------------------------------------------------

#: Size word -> the library footprint names it may mean. **This table is the
#: only vocabulary mapping boardwise performs.** It is written out rather than
#: derived because deriving it is precisely the bug 006b measured: a size is not
#: a library name, and the library's spelling is what the editor resolves.
FOOTPRINT_ALIASES: dict[str, tuple[str, ...]] = {
    "0402": ("R0402", "C0402", "L0402", "LED0402"),
    "0603": ("R0603", "C0603", "L0603", "LED0603"),
    "0805": ("R0805", "C0805", "L0805", "LED0805"),
    "1206": ("R1206", "C1206", "L1206", "LED1206"),
    "1210": ("C1210",),
    "2010": ("R2010",),
    "2512": ("R2512",),
    "1008": ("L1008",),
    # The imperial-to-metric pairs a human may type for the same chip size.
    "1608": ("R0603", "C0603"),
    "2012": ("R0805", "C0805"),
    "3216": ("R1206", "C1206"),
}

#: Category word -> the leading letter of the library name it selects. A query
#: that says ``cap 0402`` narrows ``{R0402, C0402, L0402, LED0402}`` to
#: ``C0402``; a query that says only ``0402`` keeps all four.
CATEGORY_TO_PREFIX: dict[str, str] = {
    "res": "R",
    "resistor": "R",
    "电阻": "R",
    "cap": "C",
    "capacitor": "C",
    "电容": "C",
    "ind": "L",
    "inductor": "L",
    "ferrite": "L",
    "电感": "L",
    "led": "LED",
    "发光二极管": "LED",
}


@dataclass(frozen=True)
class FootprintQuery:
    """The result of expanding footprint words found in a query."""

    #: Library footprint names the query accepts (empty means "no constraint").
    names: tuple[str, ...]
    #: Words that looked like a size but are not in the table.
    unmapped: tuple[str, ...] = ()
    #: Every word that looked like a size, mapped or not. A size word is a
    #: *filter*, not a search term: leaving `0402` in the text relevance would
    #: double-count it, and leaving an unmapped `9999` in would make a query
    #: that asked for a real resistance match nothing at all.
    size_words: tuple[str, ...] = ()


#: A bare size word: four digits, optionally prefixed by a package code the user
#: typed already (``R0402``), or the imperial size.
_SIZE_WORD = re.compile(r"^(?P<letter>[A-Za-z]{0,3})?(?P<digits>\d{4})$")


def expand_footprint_words(words: list[str], categories: list[str] | None = None) -> FootprintQuery:
    """Map query words to library footprint names, using the table only.

    ``words`` are the leftover query terms; ``categories`` are the category
    words the query used (``cap``, ``电阻``, …). A word that looks like a size
    but is not in :data:`FOOTPRINT_ALIASES` is returned in ``unmapped`` so the
    caller can report "this word matched nothing" instead of silently ignoring
    it — an unmapped word means the query cannot be answered by the table, not
    that every part is acceptable.
    """
    wanted_letters = {
        CATEGORY_TO_PREFIX[c.lower()] for c in (categories or []) if c.lower() in CATEGORY_TO_PREFIX
    }
    names: list[str] = []
    unmapped: list[str] = []
    sizes: list[str] = []
    for word in words:
        match = _SIZE_WORD.match(word)
        if match is None:
            continue
        sizes.append(word)
        letter = (match.group("letter") or "").upper()
        digits = match.group("digits")
        candidates: tuple[str, ...]
        if letter and f"{letter}{digits}" in {
            name for group in FOOTPRINT_ALIASES.values() for name in group
        }:
            # The user already spelled a library-shaped name (`R0402`).
            candidates = (f"{letter}{digits}",)
        elif digits in FOOTPRINT_ALIASES:
            candidates = FOOTPRINT_ALIASES[digits]
        else:
            unmapped.append(word)
            continue
        if wanted_letters:
            narrowed = tuple(n for n in candidates if _leading_letter(n) in wanted_letters)
            candidates = narrowed or candidates
        names.extend(candidates)
    return FootprintQuery(
        names=tuple(dict.fromkeys(names)),
        unmapped=tuple(unmapped),
        size_words=tuple(dict.fromkeys(sizes)),
    )


def _leading_letter(name: str) -> str:
    """``R0402`` -> ``R``; ``LED0805-R-RD`` -> ``LED``."""
    match = re.match(r"^([A-Za-z]+)", name)
    return (match.group(1) or "").upper() if match else ""


def footprint_matches(name: str, accepted: tuple[str, ...]) -> bool:
    """Does a library footprint name satisfy an expanded query word?

    Exact, or the library name **starts with** the accepted name — the library
    appends its own suffixes (``LED0805-R-RD``), and those are still the same
    package. Case-insensitive because the two vocabularies differ in case too
    (``led0805-r-rd`` in one file, ``LED0805-R-RD`` in another).
    """
    upper = (name or "").upper()
    return any(upper == want.upper() or upper.startswith(want.upper()) for want in accepted)


# --------------------------------------------------------------------------
# the shelf label (`key`)
# --------------------------------------------------------------------------

#: Footprint-family prefix -> shelf category. Checked **first** because the
#: footprint name is library vocabulary; the designator prefix is the schematic
#: author's intent and can disagree (measured: a 3-pin header in one of the
#: source boards carries ``Designator = U?``).
FOOTPRINT_CATEGORIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^R\d{4}", re.I), "res"),
    (re.compile(r"^C\d{4}", re.I), "cap"),
    (re.compile(r"^L\d{4}", re.I), "ind"),
    (re.compile(r"^LED", re.I), "led"),
    (re.compile(r"^(HDR|CONN|WAFER)[-_]", re.I), "conn"),
    (re.compile(r"^(USB|MICRO-USB|TYPE-C|XT60)", re.I), "conn"),
    (re.compile(r"^SW[-_]", re.I), "sw"),
    (re.compile(r"^(CRYSTAL|OSC)[-_]", re.I), "xtal"),
    (re.compile(r"^BUZ[-_]", re.I), "buzzer"),
    (re.compile(r"^CAP[-_]", re.I), "cap"),
    (re.compile(r"^IND[-_]", re.I), "ind"),
    (re.compile(r"^RES[-_]", re.I), "res"),
    (re.compile(r"^XFMR[-_]", re.I), "transformer"),
    (re.compile(r"^(SOD|SMC_)", re.I), "diode"),
    (re.compile(r"^(LQFP|QFN|WQFN|LGA|SOP|SO-|SOIC|SOT|TO-|DFN|BGA|TSSOP|MSOP)", re.I), "ic"),
)

#: Designator prefix -> shelf category. The fallback when the footprint does not
#: name a family.
DESIGNATOR_CATEGORIES: dict[str, str] = {
    "R": "res",
    "C": "cap",
    "L": "ind",
    "D": "diode",
    "LED": "led",
    "U": "ic",
    "IC": "ic",
    "Q": "fet",
    "X": "xtal",
    "Y": "xtal",
    "J": "conn",
    "P": "conn",
    "H": "conn",
    "CN": "conn",
    "USB": "conn",
    "SW": "sw",
    "BUZZER": "buzzer",
    "LS": "buzzer",
    "F": "fuse",
    "T": "transformer",
    "TP": "testpoint",
    "K": "relay",
}

#: The shelf a key falls back to when neither signal is conclusive. A truthful
#: label: it says the library could not tell, which is different from guessing.
DEFAULT_CATEGORY = "part"


def category_of(footprint_name: str, designator: str = "") -> str:
    """The shelf category of a part, or :data:`DEFAULT_CATEGORY`.

    Footprint family first, then the designator prefix, then nothing. The
    caller may report which signal was used; the category itself never claims
    more than its evidence.
    """
    name = (footprint_name or "").strip()
    for pattern, category in FOOTPRINT_CATEGORIES:
        if pattern.search(name):
            return category
    prefix = re.match(r"^([A-Za-z]+)", (designator or "").strip())
    if prefix:
        return DESIGNATOR_CATEGORIES.get(prefix.group(1).upper(), DEFAULT_CATEGORY)
    return DEFAULT_CATEGORY


#: SI prefix -> the letter a slug keeps. Case matters here too: ``m`` (milli)
#: and ``M`` (mega) must not collapse into one slug.
_SLUG_SCALE = (
    ("M", Decimal(1000000)),
    ("k", Decimal(1000)),
    ("m", Decimal("0.001")),
    ("u", Decimal("0.000001")),
    ("n", Decimal("0.000000001")),
    ("p", Decimal("0.000000000001")),
)

_QUANTITY_FOR_SLUG = re.compile(
    r"^(?P<number>\d+(?:\.\d+)?|\.\d+)\s*(?P<prefix>[Mkmunpµμ]?)\s*(?P<unit>[A-Za-zΩΩ]*)$"
)

_SIZE_IN_FOOTPRINT = re.compile(r"^(?:[A-Za-z]+)[-_]?(\d{4})$")


def quantity_slug(text: str) -> str:
    """``3kΩ`` -> ``3k``; ``5.1kΩ`` -> ``5k1``; ``100nF`` -> ``100n``.

    The schematic spelling, deliberately: a key like ``res.5k1_0402`` is what an
    engineer reads off the page. Unparseable text yields ``""`` so the caller
    falls back to another naming signal instead of inventing one.
    """
    match = _QUANTITY_FOR_SLUG.match((text or "").strip())
    if match is None:
        return ""
    prefix = match.group("prefix").replace("µ", "u").replace("μ", "u")
    number = match.group("number")
    unit = match.group("unit")
    # A bare number with no unit is a value, not a quantity (`10` on a resistor
    # is 10Ω by convention, but this slug rule refuses to assume).
    if not unit and not prefix:
        return ""
    if "." in number:
        whole, _, frac = number.partition(".")
        if prefix:
            # 5.1k -> 5k1: the prefix becomes the decimal marker.
            return f"{whole}{prefix}{frac}" if frac else f"{whole}{prefix}"
        return f"{whole}o{frac}" if frac else whole
    return f"{number}{prefix}"


def package_slug(footprint_name: str) -> str:
    """``R0402`` -> ``0402``; anything without a chip size -> ``""``."""
    match = _SIZE_IN_FOOTPRINT.match((footprint_name or "").strip())
    return match.group(1) if match else ""


def _slugify(text: str) -> str:
    slug = re.sub(r"[^0-9a-z]+", "_", (text or "").strip().lower())
    return slug.strip("_")


def make_key(
    *, category: str, value: str, mpn: str, footprint_name: str, title: str, lcsc: str
) -> str:
    """``<category>.<slug>`` — the shelf address of a part.

    Slug priority: **value + package** when both are readable (``5k1_0402``,
    the form 008b's task names), else the MPN, else the library device title.
    Never empty: the fallback is the C-number, and a part with nothing at all is
    rejected by the caller rather than given an invented name.
    """
    value_slug = quantity_slug(value)
    package = package_slug(footprint_name)
    if value_slug and package:
        slug = f"{value_slug}_{package}"
    elif mpn:
        slug = _slugify(mpn)
    elif title:
        slug = _slugify(title)
    else:
        slug = _slugify(lcsc)
    if not slug:
        raise PartError(
            f"cannot build a key for {lcsc or mpn or title or '(anonymous part)'}: "
            "no value, MPN, title or C-number to name it with"
        )
    return f"{category}.{slug}"


# --------------------------------------------------------------------------
# the library file
# --------------------------------------------------------------------------


@dataclass
class PartProvenance:
    """Where an entry came from, and where it has been used.

    ``designators`` accumulates across boards (``"U1@smart_pillbox"``,
    ``"U5@thesis_FOC_board"``) — that track record *is* the confidence signal,
    which is why merging is by identity and the history is kept rather than
    overwritten.
    """

    kind: str = ""  # 'board-extract' | 'catalog-select'
    source: str = ""
    designators: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class PartEntry:
    """One verified part on the shelf."""

    key: str
    value: str = ""
    mpn: str = ""
    lcsc: str = ""
    manufacturer: str = ""
    deviceUuid: str = ""
    libraryUuid: str = ""
    #: The **library** footprint name (`R0402`), never the human label (`0402`).
    footprint_name: str = ""
    #: `True` when the bridge's `lib.footprint.get` confirmed the name, `False`
    #: when it disagreed, `None` when it has not been consulted. Never "no"
    #: without a measurement.
    footprint_name_verified: bool | None = UNKNOWN
    #: Electrical parameters **verbatim, units kept** — `{"Resistance": "5.1kΩ ±1%"}`.
    #: No normalisation and no guessing: a consumer that needs a number applies
    #: the value gate to the original text.
    params: dict[str, str] = field(default_factory=dict)
    datasheetUrl: str = ""
    datasheetPdfUrl: str = ""
    #: JLC basic-part flag. `True`/`False` only with evidence (`JLCPCB Part
    #: Class`), `None` otherwise — "no evidence" is not "extended".
    basic: bool | None = UNKNOWN
    #: Electrical category from :data:`CATEGORY_VOCABULARY`, or "" when the
    #: entry has not been classified. Absent ≠ unknown-to-a-rule: rules see
    #: "" and report UNKNOWN rather than guessing from a designator prefix.
    category: str = ""
    #: Datasheet facts (task 011b §2.3), or None when nothing has been
    #: recorded. Every recorded fact carries its own page-cited provenance;
    #: the loader refuses a fact that cannot say where it came from.
    facts: dict[str, Any] | None = None
    provenance: PartProvenance = field(default_factory=PartProvenance)
    notes: list[str] = field(default_factory=list)

    def resistance(self) -> Decimal | None:
        """The declared resistance, from a **named field** only.

        Order is deliberate: the library's own `Resistance` attribute first
        (that is the catalog's declaration), then the entry's `value` under the
        schematic shorthand. An MPN or a C-number is never consulted — #202's
        regression was exactly a part number's `330` being read as 330Ω.

        A field may carry a qualifier alongside the quantity — a real catalog
        writes `5.1kΩ ±1%`, and refusing that would make the gate unusable on
        the very parts it exists for. The rule is therefore "**exactly one**
        resistance in the field", never "a number somewhere in the string":
        `1/2Ω` has a unit and no parseable quantity (rejected), `0.33Ω~1Ω` has
        two (ambiguous, rejected), `0805W8F330LT5E` has none (rejected).
        """
        for field_name in ("Resistance", "Resistance Tolerance", "阻值"):
            if field_name not in self.params:
                continue
            raw = self.params[field_name]
            found = parse_resistance_field(raw)
            if found is not None:
                return found
            values = quantities_in_description(raw)
            if values is not None and len(values) == 1:
                return next(iter(values))
        return parse_resistance_field(self.value, shorthand=True)


@dataclass
class PartLibrary:
    """The whole shelf."""

    parts: list[PartEntry] = field(default_factory=list)
    kind: str = PART_LIBRARY_KIND
    version: int = SCHEMA_VERSION
    sources: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def by_key(self) -> dict[str, PartEntry]:
        return {part.key: part for part in self.parts}

    def by_lcsc(self) -> dict[str, PartEntry]:
        return {part.lcsc: part for part in self.parts if part.lcsc}

    def get(self, key: str) -> PartEntry | None:
        return self.by_key().get(key)


_ENTRY_KEYS = (
    "key", "value", "mpn", "lcsc", "manufacturer", "deviceUuid", "libraryUuid",
    "footprint_name", "footprint_name_verified", "params", "datasheetUrl",
    "datasheetPdfUrl", "basic", "category", "facts", "provenance", "notes",
)
_PROVENANCE_KEYS = ("kind", "source", "designators", "note")


def _as_str(value: Any, where: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PartError(f"{where}: expected a string, got {type(value).__name__}")
    return value.strip()


def _as_opt_bool(value: Any, where: str) -> bool | None:
    if value is None:
        return UNKNOWN
    if not isinstance(value, bool):
        raise PartError(f"{where}: expected true/false/null, got {value!r}")
    return value


def _check_keys(body: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    if not isinstance(body, dict):
        raise PartError(f"{where}: expected an object, got {type(body).__name__}")
    unknown = sorted(set(body) - set(allowed))
    if unknown:
        raise PartError(
            f"{where}: unknown key(s) {', '.join(unknown)}; allowed: {', '.join(allowed)}"
        )


# --------------------------------------------------------------------------
# facts (task 011b §2.3) — datasheet claims, each with a page-cited source
# --------------------------------------------------------------------------

#: The whitelist of fact kinds. Anything else inside ``facts`` is a loader
#: error: a fact this project has not decided how to represent must not sneak
#: in under a typo-shaped key.
FACTS_KEYS = (
    "supply_pins", "required_caps", "nc_pins", "must_connect", "led", "ldo",
    "pull_required",
)

#: An optional mode tag on a per-pin fact (task 011d sec.2): multi-mode parts
#: (the CH340G's 5V/3.3V pair) tag each record with the mode it belongs to.
#: Absent means "applies unconditionally". A mode-only fact is checked only
#: when the board actually runs in that mode.
def _fact_mode(raw: dict[str, Any], where: str) -> str | None:
    if "mode" not in raw:
        return None
    mode = _as_str(raw.get("mode"), f"{where}.mode")
    if not mode.strip():
        raise PartError(f"{where}.mode: must be a non-empty string when present")
    return mode

#: A provenance string must cite WHERE in the source: a page, a section, a
#: table, or a figure. "The datasheet says so" is not a citation. This is the
#: hard gate task 011b was commissioned under — a fact that cannot name its
#: page does not enter the library.
_FACT_PAGE_RE = re.compile(
    r"(?i)\bp(?:age)?\.?\s*\d+"          # p4 / p.4 / page 4
    r"|\bsec(?:tion)?\.?\s*[\d.]+"       # sec.5.1 / section 7.2.3
    r"|\bfig(?:ure)?\.?\s*\d+"           # fig.1 / Figure 2
    r"|\btable\s*\d+"                    # Table 3
    r"|\b第\s*\d+\s*页"                   # 第 4 页
)


def _fact_provenance(value: Any, where: str) -> str:
    text = _as_str(value, where)
    if not text:
        raise PartError(f"{where}: a fact without provenance cannot be recorded")
    if "http" not in text:
        raise PartError(
            f"{where}: provenance must cite its source URL, got {text!r}"
        )
    if not _FACT_PAGE_RE.search(text):
        raise PartError(
            f"{where}: provenance must cite a page, section, table or figure "
            f"(e.g. 'p.4', 'sec.5.1', 'Table 3'), got {text!r}"
        )
    return text


def _fact_pin(value: Any, where: str) -> str:
    """A pin number as a **string** — named pins (BNC/ACK, 'V3') exist."""
    if not isinstance(value, str) or not value.strip():
        raise PartError(
            f"{where}: a pin number must be a non-empty string, got {value!r}"
        )
    return value.strip()


def _fact_range(value: Any, where: str) -> list[float | None]:
    """``[min, max]`` in the key's own unit. Either bound may be null when the
    source states only one side (measured: the RT9013 datasheet gives a 6V
    upper abs-max and no lower one) — a claim the loader refuses to invent
    must be expressible as its absence, not as a made-up 0."""
    if not isinstance(value, list) or len(value) != 2:
        raise PartError(f"{where}: a range must be [min, max], got {value!r}")
    lo, hi = value
    for bound in (lo, hi):
        if bound is None:
            continue
        if isinstance(bound, bool) or not isinstance(bound, (int, float)):
            raise PartError(
                f"{where}: range bounds must be numbers or null, got {bound!r}"
            )
    if lo is not None and hi is not None and lo > hi:
        raise PartError(f"{where}: range min {lo} > max {hi}")
    return [lo, hi]


def _fact_number(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PartError(f"{where}: expected a number, got {value!r}")
    return float(value)


def _facts_from_json(raw: Any, where: str) -> dict[str, Any]:
    """Validate one entry's ``facts`` object. Unknown kinds are rejected."""
    if not isinstance(raw, dict) or not raw:
        raise PartError(f"{where}: expected a non-empty object")
    _check_keys(raw, FACTS_KEYS, where)
    facts: dict[str, Any] = {}

    if "supply_pins" in raw:
        entries = raw["supply_pins"]
        if not isinstance(entries, list) or not entries:
            raise PartError(f"{where}.supply_pins: expected a non-empty list")
        checked = []
        for i, entry in enumerate(entries):
            spot = f"{where}.supply_pins[{i}]"
            _check_keys(entry, ("pins", "name", "v_operating", "v_abs_max", "provenance", "mode"), spot)
            pins_raw = entry.get("pins")
            if not isinstance(pins_raw, list) or not pins_raw:
                raise PartError(f"{spot}.pins: expected a non-empty list")
            record: dict[str, Any] = {
                "pins": [_fact_pin(pin, f"{spot}.pins[]") for pin in pins_raw],
                "name": _require_nonempty(entry.get("name"), f"{spot}.name"),
            }
            mode = _fact_mode(entry, spot)
            if mode is not None:
                record["mode"] = mode
            # Absent stays absent: a range the source never states must not
            # round-trip into an explicit null and then fail its own reload.
            if "v_operating" in entry:
                record["v_operating"] = _fact_range(entry["v_operating"], f"{spot}.v_operating")
            if "v_abs_max" in entry:
                record["v_abs_max"] = _fact_range(entry["v_abs_max"], f"{spot}.v_abs_max")
            record["provenance"] = _fact_provenance(entry.get("provenance"), f"{spot}.provenance")
            checked.append(record)
        facts["supply_pins"] = checked

    if "required_caps" in raw:
        entries = raw["required_caps"]
        if not isinstance(entries, list) or not entries:
            raise PartError(f"{where}.required_caps: expected a non-empty list")
        checked = []
        for i, entry in enumerate(entries):
            spot = f"{where}.required_caps[{i}]"
            _check_keys(entry, ("pin", "value", "provenance", "mode"), spot)
            checked.append({
                "pin": _fact_pin(entry.get("pin"), f"{spot}.pin"),
                "value": _require_nonempty(entry.get("value"), f"{spot}.value"),
                "provenance": _fact_provenance(entry.get("provenance"), f"{spot}.provenance"),
                **({"mode": mode} if (mode := _fact_mode(entry, spot)) is not None else {}),
            })
        facts["required_caps"] = checked

    if "nc_pins" in raw:
        entry = raw["nc_pins"]
        spot = f"{where}.nc_pins"
        _check_keys(entry, ("pins", "provenance"), spot)
        pins_raw = entry.get("pins")
        if not isinstance(pins_raw, list) or not pins_raw:
            raise PartError(f"{spot}.pins: expected a non-empty list")
        facts["nc_pins"] = {
            "pins": [_fact_pin(pin, f"{spot}.pins[]") for pin in pins_raw],
            "provenance": _fact_provenance(entry.get("provenance"), f"{spot}.provenance"),
        }

    if "must_connect" in raw:
        entries = raw["must_connect"]
        if not isinstance(entries, list) or not entries:
            raise PartError(f"{where}.must_connect: expected a non-empty list")
        checked = []
        for i, entry in enumerate(entries):
            spot = f"{where}.must_connect[{i}]"
            _check_keys(entry, ("pin", "to", "provenance", "mode"), spot)
            checked.append({
                "pin": _fact_pin(entry.get("pin"), f"{spot}.pin"),
                "to": _require_nonempty(entry.get("to"), f"{spot}.to"),
                "provenance": _fact_provenance(entry.get("provenance"), f"{spot}.provenance"),
                **({"mode": mode} if (mode := _fact_mode(entry, spot)) is not None else {}),
            })
        facts["must_connect"] = checked

    if "pull_required" in raw:
        entries = raw["pull_required"]
        if not isinstance(entries, list) or not entries:
            raise PartError(f"{where}.pull_required: expected a non-empty list")
        checked = []
        for i, entry in enumerate(entries):
            spot = f"{where}.pull_required[{i}]"
            _check_keys(entry, ("pin", "to", "expected_value", "provenance"), spot)
            checked.append({
                "pin": _fact_pin(entry.get("pin"), f"{spot}.pin"),
                "to": _require_nonempty(entry.get("to"), f"{spot}.to"),
                "expected_value": _require_nonempty(
                    entry.get("expected_value"), f"{spot}.expected_value"
                ),
                "provenance": _fact_provenance(entry.get("provenance"), f"{spot}.provenance"),
            })
        facts["pull_required"] = checked

    if "led" in raw:
        entry = raw["led"]
        spot = f"{where}.led"
        _check_keys(entry, ("vf_v", "if_max_ma", "provenance"), spot)
        facts["led"] = {
            "vf_v": _fact_range(entry.get("vf_v"), f"{spot}.vf_v"),
            "if_max_ma": _fact_number(entry.get("if_max_ma"), f"{spot}.if_max_ma"),
            "provenance": _fact_provenance(entry.get("provenance"), f"{spot}.provenance"),
        }

    if "ldo" in raw:
        entry = raw["ldo"]
        spot = f"{where}.ldo"
        _check_keys(entry, ("dropout_max_mv", "condition", "provenance"), spot)
        facts["ldo"] = {
            "dropout_max_mv": _fact_number(entry.get("dropout_max_mv"), f"{spot}.dropout_max_mv"),
            "condition": _require_nonempty(entry.get("condition"), f"{spot}.condition"),
            "provenance": _fact_provenance(entry.get("provenance"), f"{spot}.provenance"),
        }

    return facts


def _require_nonempty(value: Any, where: str) -> str:
    text = _as_str(value, where)
    if not text:
        raise PartError(f"{where}: must be a non-empty string")
    return text


def entry_from_json(raw: Any, where: str = "<part>") -> PartEntry:
    """Validate one entry. Strict: an unknown key is an error, not ignored."""
    if not isinstance(raw, dict):
        raise PartError(f"{where}: expected an object")
    _check_keys(raw, _ENTRY_KEYS, where)
    for required in ("key", "lcsc", "deviceUuid", "libraryUuid"):
        if not raw.get(required):
            raise PartError(f"{where}: {required!r} is required and must not be empty")
    params = raw.get("params") or {}
    if not isinstance(params, dict):
        raise PartError(f"{where}.params: expected an object")
    prov_raw = raw.get("provenance") or {}
    if not isinstance(prov_raw, dict):
        raise PartError(f"{where}.provenance: expected an object")
    _check_keys(prov_raw, _PROVENANCE_KEYS, f"{where}.provenance")
    designators = prov_raw.get("designators") or []
    if not isinstance(designators, list):
        raise PartError(f"{where}.provenance.designators: expected a list")
    notes = raw.get("notes") or []
    if not isinstance(notes, list):
        raise PartError(f"{where}.notes: expected a list")

    verified = _as_opt_bool(
        raw.get("footprint_name_verified"), f"{where}.footprint_name_verified"
    )
    if verified is True and not looks_like_library_uuid(
        _as_str(raw.get("libraryUuid"), f"{where}.libraryUuid")
    ):
        # The only route to a verified name runs through `lib.device.get` →
        # `association.footprintUuid` → `lib.footprint.get`, so an entry whose
        # library uuid cannot even be a key has no way to have been verified.
        # Accepting the claim would be a file asserting a check that could not
        # have happened (measured: the two personal-library entries arrive with
        # the library's *name* there, and `lib.device.get` answers `found:false`).
        raise PartError(
            f"{where}: footprint_name_verified is true but libraryUuid "
            f"{raw.get('libraryUuid')!r} is not a library uuid, so the check "
            "that would have set it cannot have run"
        )

    category = _as_str(raw.get("category"), f"{where}.category")
    if category and category not in CATEGORY_VOCABULARY:
        raise PartError(
            f"{where}.category: {category!r} is not in the vocabulary; the "
            "table is extended by decision, not by typo"
        )
    facts = raw.get("facts")
    if facts is not None:
        facts = _facts_from_json(facts, f"{where}.facts")

    return PartEntry(
        key=_as_str(raw.get("key"), f"{where}.key"),
        value=_as_str(raw.get("value"), f"{where}.value"),
        mpn=_as_str(raw.get("mpn"), f"{where}.mpn"),
        lcsc=_as_str(raw.get("lcsc"), f"{where}.lcsc"),
        manufacturer=_as_str(raw.get("manufacturer"), f"{where}.manufacturer"),
        deviceUuid=_as_str(raw.get("deviceUuid"), f"{where}.deviceUuid"),
        libraryUuid=_as_str(raw.get("libraryUuid"), f"{where}.libraryUuid"),
        footprint_name=_as_str(raw.get("footprint_name"), f"{where}.footprint_name"),
        footprint_name_verified=verified,
        params={str(k): _as_str(v, f"{where}.params[{k}]") for k, v in params.items()},
        datasheetUrl=_as_str(raw.get("datasheetUrl"), f"{where}.datasheetUrl"),
        datasheetPdfUrl=_as_str(raw.get("datasheetPdfUrl"), f"{where}.datasheetPdfUrl"),
        basic=_as_opt_bool(raw.get("basic"), f"{where}.basic"),
        category=category,
        facts=facts,
        provenance=PartProvenance(
            kind=_as_str(prov_raw.get("kind"), f"{where}.provenance.kind"),
            source=_as_str(prov_raw.get("source"), f"{where}.provenance.source"),
            designators=[_as_str(d, f"{where}.provenance.designators[]") for d in designators],
            note=_as_str(prov_raw.get("note"), f"{where}.provenance.note"),
        ),
        notes=[_as_str(n, f"{where}.notes[]") for n in notes],
    )


def entry_to_json(entry: PartEntry) -> dict[str, Any]:
    """Serialise one entry. Round-trips with :func:`entry_from_json`.

    ``category`` and ``facts`` are written **only when present**: the 92
    pre-facts entries must round-trip byte-identically (task 011b §五), and
    an empty ``"category": ""`` on every one of them would be noise that
    pretends a classification happened.
    """
    body: dict[str, Any] = {
        "key": entry.key,
        "value": entry.value,
        "mpn": entry.mpn,
        "lcsc": entry.lcsc,
        "manufacturer": entry.manufacturer,
        "deviceUuid": entry.deviceUuid,
        "libraryUuid": entry.libraryUuid,
        "footprint_name": entry.footprint_name,
        "footprint_name_verified": entry.footprint_name_verified,
        "params": dict(sorted(entry.params.items())),
        "datasheetUrl": entry.datasheetUrl,
        "datasheetPdfUrl": entry.datasheetPdfUrl,
        "basic": entry.basic,
        "provenance": {
            "kind": entry.provenance.kind,
            "source": entry.provenance.source,
            "designators": sorted(set(entry.provenance.designators)),
            "note": entry.provenance.note,
        },
        "notes": list(entry.notes),
    }
    if entry.category:
        body["category"] = entry.category
    if entry.facts is not None:
        body["facts"] = entry.facts
    return body


def library_from_json(raw: Any, where: str = "<library>") -> PartLibrary:
    """Validate a whole library document."""
    if not isinstance(raw, dict):
        raise PartError(f"{where}: expected an object")
    _check_keys(raw, ("kind", "version", "sources", "notes", "parts"), where)
    kind = _as_str(raw.get("kind"), f"{where}.kind")
    if kind != PART_LIBRARY_KIND:
        raise PartError(f"{where}.kind: expected {PART_LIBRARY_KIND!r}, got {kind!r}")
    if raw.get("version") != SCHEMA_VERSION:
        raise PartError(f"{where}.version: expected {SCHEMA_VERSION}, got {raw.get('version')!r}")
    parts_raw = raw.get("parts")
    if not isinstance(parts_raw, list):
        raise PartError(f"{where}.parts: expected a list")
    parts = [entry_from_json(item, f"{where}.parts[{i}]") for i, item in enumerate(parts_raw)]

    seen: dict[str, str] = {}
    for part in parts:
        if part.key in seen:
            raise PartError(f"{where}: duplicate key {part.key!r}")
        seen[part.key] = part.lcsc
    by_lcsc: dict[str, str] = {}
    for part in parts:
        if part.lcsc in by_lcsc and by_lcsc[part.lcsc] != part.key:
            raise PartError(
                f"{where}: C-number {part.lcsc} appears under two keys "
                f"({by_lcsc[part.lcsc]!r} and {part.key!r}); one part is one entry"
            )
        by_lcsc[part.lcsc] = part.key

    return PartLibrary(
        parts=sorted(parts, key=lambda p: p.key),
        kind=kind,
        version=SCHEMA_VERSION,
        sources=[_as_str(s, f"{where}.sources[]") for s in (raw.get("sources") or [])],
        notes=[_as_str(n, f"{where}.notes[]") for n in (raw.get("notes") or [])],
    )


def library_to_json(library: PartLibrary) -> dict[str, Any]:
    """Serialise a library, deterministically (sorted keys, sorted history)."""
    return {
        "kind": PART_LIBRARY_KIND,
        "version": SCHEMA_VERSION,
        "sources": sorted(set(library.sources)),
        "notes": list(library.notes),
        "parts": [entry_to_json(p) for p in sorted(library.parts, key=lambda p: p.key)],
    }


def load_parts(path: str | Path) -> PartLibrary:
    """Read a part library. A missing file is an empty shelf, not an error."""
    file = Path(path)
    if not file.is_file():
        return PartLibrary()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PartError(f"{file}: cannot read: {exc}") from exc
    except ValueError as exc:
        raise PartError(f"{file}: not JSON: {exc}") from exc
    return library_from_json(raw, str(file))


def save_parts(library: PartLibrary, path: str | Path) -> Path:
    """Write a library as JSON."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(library_to_json(library), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return file


def find_facts(
    library: PartLibrary, *, mpn: str | None = None, lcsc: str | None = None
) -> PartEntry | None:
    """Resolve a board part to its shelf entry — **exact match only**.

    MPN first, then the C-number, then ``None``. No prefix, no fuzzy, no
    case-folding: #202's regression was a part number's ``330`` being read as
    a resistance, and the same failure one level up would be "close enough"
    identity feeding rules that then cite the wrong datasheet. A part whose
    identity cannot be resolved exactly is the rules' UNKNOWN case, not a
    best guess (task 011b §2.4).
    """
    if mpn:
        for part in library.parts:
            if part.mpn and part.mpn == mpn:
                return part
    if lcsc:
        for part in library.parts:
            if part.lcsc and part.lcsc == lcsc:
                return part
    return None


# ---------------------------------------------------------------------------
# Corrections — the sidecar a curated library correction rides in (008b tail)
# ---------------------------------------------------------------------------

CORRECTIONS_KIND = "boardwise-part-corrections"

#: A library document uuid: 32 hex characters. Anything else cannot be a key in
#: the library, which is the whole reason this file exists.
_UUID_SHAPED = re.compile(r"^[0-9a-fA-F]{32}$")


def looks_like_library_uuid(value: str) -> bool:
    """Whether ``value`` can be a library uuid at all.

    Measured 2026-09-16: two entries harvested from a **personal** library carry
    the library's *name* (`"FOC"`) where the uuid belongs, so `lib.device.get`
    rejects the pair with `found:false` on both paths. The test is shape-only on
    purpose — it is a local, checkable criterion, so "which entries need
    re-anchoring" is reproducible without the bridge.
    """
    return bool(_UUID_SHAPED.match((value or "").strip()))


@dataclass(frozen=True)
class IdentityOverride:
    """One entry's identity, corrected on evidence, keyed by C-number.

    Lives beside the library rather than inside it, exactly like the golden
    fixture's overrides (§G.3): the *harvest* stays a faithful function of its
    sources, and the correction is a separate, reviewable claim. The harvest
    applies it, so the committed library is still reproducible byte for byte —
    which an edit made in place would have destroyed.
    """

    lcsc: str
    deviceUuid: str
    libraryUuid: str
    #: Verbatim prose stored on the entry, so the artifact explains the change
    #: without anyone having to re-read this file.
    note: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "lcsc": self.lcsc,
            "deviceUuid": self.deviceUuid,
            "libraryUuid": self.libraryUuid,
            "note": self.note,
        }


@dataclass(frozen=True)
class DatasheetOverride:
    """One entry's datasheet PDF link, read off the product page, keyed by C-number.

    Same reasoning as :class:`IdentityOverride`, and the same necessity: a
    harvest reads boards, and a board carries a datasheet *web page* and not a
    file, so the PDF link can only come from the network. Keeping it in the
    sidecar is what lets an offline `--check` still be a byte-for-byte claim.

    The harvest applies the **URL only**, not :attr:`note`: the record's prose
    documents the fact inside this file, while the entry carries the fact. That
    asymmetry is deliberate — the tool that fills the links edits the library in
    place (it has no bridge, and a re-harvest without one would wipe the names a
    `--verify` run settled), and a note the harvest added but the tool did not
    would make those two writers disagree about a *wording*.
    """

    lcsc: str
    pdfUrl: str
    note: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"lcsc": self.lcsc, "pdfUrl": self.pdfUrl, "note": self.note}


@dataclass(frozen=True)
class CuratedOverride:
    """Curated entry fields keyed by C-number (task 011b).

    The facts a **datasheet** carries and no board can supply — supply-pin
    ranges, required capacitors, dropout — plus, for a part that appears on no
    harvest source at all, its whole identity. The harvest applies the fields
    **over** what the boards produced, or appends the payload as a new entry
    when the C-number is on no source, so the committed library stays a
    deterministic function of sources + sidecar.

    ``facts`` and ``category`` are validated right here, because a malformed
    fact must be refused at the door, not discovered by a rule at run time.
    Every other field is validated when the harvest merges them through
    :func:`entry_from_json` — same validators, one gate.
    """

    lcsc: str
    fields: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"lcsc": self.lcsc, "fields": self.fields, "note": self.note}


@dataclass
class LibraryCorrections:
    """Every correction a harvest applies: identities and datasheet links.

    Two sections rather than two files because both are the same kind of thing
    — a fact the harvest cannot derive from its sources — and one file means one
    loader, one flag, and one place to look when a value in the library is not
    what the boards said.
    """

    identity: dict[str, IdentityOverride] = field(default_factory=dict)
    datasheets: dict[str, DatasheetOverride] = field(default_factory=dict)
    curated: dict[str, CuratedOverride] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.identity and not self.datasheets and not self.curated

    def identity_for(self, lcsc: str) -> IdentityOverride | None:
        return self.identity.get((lcsc or "").strip().upper())

    def datasheet_for(self, lcsc: str) -> DatasheetOverride | None:
        return self.datasheets.get((lcsc or "").strip().upper())

    def curated_for(self, lcsc: str) -> CuratedOverride | None:
        return self.curated.get((lcsc or "").strip().upper())


def _as_lcsc(raw: Any, where: str) -> str:
    if not raw:
        raise PartError(f"{where}: 'lcsc' is required and must not be empty")
    lcsc = _as_str(raw, where).upper()
    if not lcsc:
        raise PartError(f"{where}: empty")
    return lcsc


def _identity_from_json(raw: Any, where: str) -> IdentityOverride:
    if not isinstance(raw, dict):
        raise PartError(f"{where}: expected an object")
    _check_keys(raw, ("lcsc", "deviceUuid", "libraryUuid", "note"), where)
    for required in ("lcsc", "deviceUuid", "libraryUuid"):
        if not raw.get(required):
            raise PartError(f"{where}: {required!r} is required and must not be empty")
    lcsc = _as_lcsc(raw.get("lcsc"), f"{where}.lcsc")
    device_uuid = _as_str(raw.get("deviceUuid"), f"{where}.deviceUuid")
    library_uuid = _as_str(raw.get("libraryUuid"), f"{where}.libraryUuid")
    if not looks_like_library_uuid(library_uuid):
        raise PartError(
            f"{where}.libraryUuid: {library_uuid!r} is not a library uuid; an "
            "identity override exists to replace a non-uuid with one"
        )
    return IdentityOverride(
        lcsc=lcsc,
        deviceUuid=device_uuid,
        libraryUuid=library_uuid,
        note=_as_str(raw.get("note"), f"{where}.note"),
    )


def _datasheet_from_json(raw: Any, where: str) -> DatasheetOverride:
    if not isinstance(raw, dict):
        raise PartError(f"{where}: expected an object")
    _check_keys(raw, ("lcsc", "pdfUrl", "note"), where)
    for required in ("lcsc", "pdfUrl"):
        if not raw.get(required):
            raise PartError(f"{where}: {required!r} is required and must not be empty")
    return DatasheetOverride(
        lcsc=_as_lcsc(raw.get("lcsc"), f"{where}.lcsc"),
        pdfUrl=_as_str(raw.get("pdfUrl"), f"{where}.pdfUrl"),
        note=_as_str(raw.get("note"), f"{where}.note"),
    )


def _curated_from_json(raw: Any, where: str) -> CuratedOverride:
    if not isinstance(raw, dict):
        raise PartError(f"{where}: expected an object")
    _check_keys(raw, ("lcsc", "fields", "note"), where)
    for required in ("lcsc", "fields"):
        if not raw.get(required):
            raise PartError(f"{where}: {required!r} is required and must not be empty")
    fields = raw["fields"]
    if not isinstance(fields, dict):
        raise PartError(f"{where}.fields: expected an object")
    allowed = [key for key in _ENTRY_KEYS if key != "lcsc"]
    _check_keys(fields, tuple(allowed), f"{where}.fields")
    # The two keys whose shape this module owns are validated now, so a bad
    # fact cannot even sit in the sidecar; the rest go through the entry
    # validator when the harvest applies them.
    if "category" in fields:
        category = _as_str(fields["category"], f"{where}.fields.category")
        if category and category not in CATEGORY_VOCABULARY:
            raise PartError(
                f"{where}.fields.category: {category!r} is not in the vocabulary"
            )
    if "facts" in fields:
        _facts_from_json(fields["facts"], f"{where}.fields.facts")
    return CuratedOverride(
        lcsc=_as_lcsc(raw.get("lcsc"), f"{where}.lcsc"),
        fields=fields,
        note=_as_str(raw.get("note"), f"{where}.note"),
    )


def corrections_from_json(raw: Any, where: str = "<corrections>") -> LibraryCorrections:
    """Validate a corrections file. An unknown key or a bad record is an error."""
    if not isinstance(raw, dict):
        raise PartError(f"{where}: expected a JSON object")
    _check_keys(raw, ("kind", "version", "note", "identity", "datasheets", "curated"), where)
    kind = _as_str(raw.get("kind"), f"{where}.kind")
    if kind != CORRECTIONS_KIND:
        raise PartError(f"{where}.kind: expected {CORRECTIONS_KIND!r}, got {kind!r}")
    out = LibraryCorrections()
    for section, builder in (
        ("identity", _identity_from_json),
        ("datasheets", _datasheet_from_json),
        ("curated", _curated_from_json),
    ):
        items = raw.get(section) or []
        if not isinstance(items, list):
            raise PartError(f"{where}.{section}: expected a list")
        seen: set[str] = set()
        for index, item in enumerate(items):
            record = builder(item, f"{where}.{section}[{index}]")
            # The invariant is *within* one section: two identity records for one
            # C-number cannot both win. Across sections it is not a conflict but
            # the expected case — a part re-anchored by --rehome can also need
            # its datasheet link backfilled, and rejecting that would make the
            # two tools unable to touch the same part (measured: C2861195 and
            # C49423996 are in both).
            if record.lcsc in seen:
                raise PartError(
                    f"{where}.{section}: {record.lcsc} appears twice in its section"
                )
            seen.add(record.lcsc)
            # Section -> store, explicitly: an if/else here silently routed a
            # new third section into `datasheets` (caught by the count
            # assertion during task 011b, not by the type system).
            target = {
                "identity": out.identity,
                "datasheets": out.datasheets,
                "curated": out.curated,
            }[section]
            target[record.lcsc] = record
    return out


def load_corrections(path: str | Path) -> LibraryCorrections:
    """Read a corrections sidecar. A missing file means "no corrections"."""
    file = Path(path)
    if not file.is_file():
        return LibraryCorrections()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PartError(f"{file}: cannot read: {exc}") from exc
    except ValueError as exc:
        raise PartError(f"{file}: not JSON: {exc}") from exc
    return corrections_from_json(raw, str(file))


def save_corrections(corrections: LibraryCorrections, path: str | Path) -> Path:
    """Write a corrections sidecar, sorted by C-number for a stable file."""
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": CORRECTIONS_KIND,
        "version": SCHEMA_VERSION,
        "note": (
            "Facts a harvest of the source boards cannot derive, kept beside the "
            "library instead of edited into it, so that `blocklib/parts.json` "
            "stays a deterministic function of sources + this file (the same "
            "rule as the golden fixture's overrides). `identity` re-anchors an "
            "entry whose stored library uuid is a library *name* (a personal "
            "library), resolved by C-number through `lib.device.search`, which "
            "accepts an item only on an exact, unique match. `datasheets` holds "
            "the PDF link read from the product page; a part the service does "
            "not answer for is absent, never guessed. `curated` (task 011b) "
            "carries datasheet facts per C-number — and, for a part on no "
            "harvest source, its whole identity — and the harvest applies the "
            "fields over what the boards produced. Every curated fact names "
            "its datasheet page; a fact that cannot is not recorded."
        ),
        "identity": [corrections.identity[key].as_json() for key in sorted(corrections.identity)],
        "datasheets": [
            corrections.datasheets[key].as_json() for key in sorted(corrections.datasheets)
        ],
        "curated": [
            corrections.curated[key].as_json() for key in sorted(corrections.curated)
        ],
    }
    file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return file


__all__ = [
    "CATEGORY_TO_PREFIX",
    "CORRECTIONS_KIND",
    "CuratedOverride",
    "DEFAULT_CATEGORY",
    "DESIGNATOR_CATEGORIES",
    "DatasheetOverride",
    "FOOTPRINT_ALIASES",
    "FOOTPRINT_CATEGORIES",
    "FootprintQuery",
    "IdentityOverride",
    "LibraryCorrections",
    "PART_LIBRARY_KIND",
    "PartEntry",
    "PartError",
    "PartLibrary",
    "PartProvenance",
    "ResistanceQuery",
    "SCHEMA_VERSION",
    "CATEGORY_VOCABULARY",
    "FACTS_KEYS",
    "category_of",
    "corrections_from_json",
    "entry_from_json",
    "entry_to_json",
    "expand_footprint_words",
    "find_facts",
    "footprint_matches",
    "library_from_json",
    "library_to_json",
    "load_corrections",
    "load_parts",
    "looks_like_library_uuid",
    "make_key",
    "package_slug",
    "save_corrections",
    "parse_resistance_field",
    "quantities_in_description",
    "quantity_slug",
    "resistance_of_declared_field",
    "resistance_query",
    "save_parts",
]
