"""Part selection: query -> ranked candidates (task 008b, work item 3).

The default path is **offline**: the curated library from
:mod:`boardwise.engines.harvest`, zero network, zero editor. The online JLC SMT
comparison is an explicit ``--online``, and the identity of whatever it picks is
resolved deterministically through the bridge by **C-number** — an exact key,
never a fuzzy keyword.

The gate that makes a resistance query trustworthy lives in
:mod:`boardwise.core.parts`; this module only *applies* it, and the wiring is
the whole point of #202:

* an explicit ``Ω``/``ohm`` query that cannot be resolved to one number
  **yields no candidates at all** — not a fuzzy fallback, and exit code ``1``;
* a candidate matches only through its **declared** resistance (a named
  attribute, or the curated `value`), never through a number found in an MPN, a
  C-number or a description;
* a query with no explicit unit stays a fuzzy search, which is why writing
  ``10kΩ`` is how you ask for a *verified* 10k.

Ranking follows the reference's order, which is the order the acceptance's
"spec 匹配 → 库存 ≥ qty → basic → preferred → 最低价" restates: relevance and the
resistance gate decide *who is eligible*, then buildability, then cost.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..core.parts import (
    CATEGORY_TO_PREFIX,
    PartEntry,
    PartLibrary,
    ResistanceQuery,
    expand_footprint_words,
    footprint_matches,
    quantities_in_description,
    resistance_query,
)
from .catalog import CatalogCandidate, CatalogClient

#: Fields of a curated entry that a query's words are matched against, split by
#: how much they *mean*. Identity fields are what the part **is**; prose fields
#: merely mention things. An equal weight would let a description that mentions
#: "100nF" tie with the actual 100nF capacitor.
IDENTITY_FIELDS = ("key", "value", "mpn", "lcsc")
PROSE_FIELDS = ("manufacturer", "footprint_name")


def normalise(text: str) -> str:
    """Fold text for *relevance* only — never for the value gate.

    Lowercases and strips unit noise so ``10kohm``, ``10kΩ`` and ``10k`` agree
    on being the same query word. This is deliberately a different code path
    from the resistance gate: relevance may be sloppy, a quantity may not.
    """
    lowered = str(text or "").lower().replace("µ", "u").replace("μ", "u")
    lowered = lowered.replace("ω", "").replace("ohms", "").replace("ohm", "")
    return re.sub(r"\s+", " ", lowered)


def term_hits(text: str, terms: list[str]) -> int:
    """How many query terms appear in ``text`` (separators collapsed)."""
    collapsed = re.sub(r"[-_.\s]+", "", text)
    hits = 0
    for term in terms:
        if term in text or re.sub(r"[-_.]+", "", term) in collapsed:
            hits += 1
    return hits


@dataclass
class Candidate:
    """One ranked possibility, from either source."""

    source: str
    lcsc: str = ""
    key: str = ""
    mpn: str = ""
    brand: str = ""
    description: str = ""
    footprint_name: str = ""
    deviceUuid: str = ""
    libraryUuid: str = ""
    basic: bool | None = None
    preferred: bool = False
    stock: int = 0
    in_stock: bool = False
    unit_price: Decimal | None = None
    relevance: int = 0
    #: `{"raw": "5.1kΩ ±1%", "ohms": "5100", "from": "attributes.Resistance"}` —
    #: the evidence behind a resistance match, shown so a reader can check it.
    resistance: dict[str, str] | None = None

    def as_json(self) -> dict[str, Any]:
        """The candidate as JSON. Stock keys appear **only** for a live source.

        A curated entry carries no stock and no price, and printing
        ``stock: 0`` for it would read as "out of stock" — a claim nobody made.
        Absent fields are honest; zeroed ones are not.
        """
        payload: dict[str, Any] = {
            "source": self.source,
            "lcsc": self.lcsc,
            "key": self.key,
            "mpn": self.mpn,
            "brand": self.brand,
            "description": self.description,
            "footprint_name": self.footprint_name,
            "deviceUuid": self.deviceUuid,
            "libraryUuid": self.libraryUuid,
            "basic": self.basic,
            "relevance": self.relevance,
        }
        if self.source != "blocklib/parts.json":
            payload.update(
                {
                    "preferred": self.preferred,
                    "stock": self.stock,
                    "in_stock": self.in_stock,
                    "unit_price": None if self.unit_price is None else str(self.unit_price),
                }
            )
        if self.resistance:
            payload["resistance"] = self.resistance
        return payload


@dataclass
class SelectionResult:
    """The picker's answer, including why it is empty when it is."""

    query: str
    resistance: ResistanceQuery
    candidates: list[Candidate] = field(default_factory=list)
    online: bool = False
    unmapped_words: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def gated(self) -> bool:
        """Was this query an explicit-resistance request?"""
        return self.resistance.active

    @property
    def exit_code(self) -> int:
        """``1`` when a gated query found nothing; ``0`` otherwise.

        An explicit resistance query with no exact candidate is a **failure** —
        the caller must not carry on and place a fuzzy near-miss. A fuzzy query
        that finds nothing is simply empty, which is not an error (the reference
        draws the same line).
        """
        if self.candidates:
            return 0
        # A gated query that found nothing is a failure — including one whose
        # resistance could not be read at all, because "I asked for a specific
        # value and got no answer" is not a success in either case.
        return 1 if self.gated else 0

    def as_json(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "source": "jlcpcb.com" if self.online else "blocklib/parts.json",
            "resistance": (
                {
                    "ohms": str(self.resistance.ohms),
                    "parsed": self.resistance.ohms is not None,
                }
                if self.gated
                else None
            ),
            "unmapped_words": self.unmapped_words,
            "candidates": [c.as_json() for c in self.candidates],
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# offline: the curated library
# --------------------------------------------------------------------------


def candidate_from_entry(entry: PartEntry, relevance: int, resistance: Decimal | None) -> Candidate:
    evidence = None
    if resistance is not None:
        raw = entry.params.get("Resistance") or entry.value
        evidence = {
            "raw": raw,
            "ohms": format(resistance.normalize(), "f"),
            "from": "attributes.Resistance" if "Resistance" in entry.params else "value",
        }
    return Candidate(
        source="blocklib/parts.json",
        lcsc=entry.lcsc,
        key=entry.key,
        mpn=entry.mpn,
        brand=entry.manufacturer,
        description="; ".join(f"{k}: {v}" for k, v in list(entry.params.items())[:4]),
        footprint_name=entry.footprint_name,
        deviceUuid=entry.deviceUuid,
        libraryUuid=entry.libraryUuid,
        basic=entry.basic,
        relevance=relevance,
        resistance=evidence,
    )


def _text_terms(words: list[str], categories: list[str], expanded: object) -> list[str]:
    """The query words that are *searched for*, rather than used as a filter.

    Category words and size words are filters — a size is either mapped to
    library names (a constraint) or reported as unmapped (no constraint), and
    either way it is not something to look for in a part's text. Everything else
    is a search term, which is how an MPN query keeps working.
    """
    filtered = set(categories) | set(getattr(expanded, "size_words", ()))
    return [w for w in words if w not in CATEGORY_TO_PREFIX and w not in filtered]


def select_offline(query: str, library: PartLibrary, *, qty: int = 100) -> SelectionResult:
    """Rank curated parts. Pure; the only I/O was reading the library."""
    gate = resistance_query(query)
    result = SelectionResult(query=query, resistance=gate)
    if gate.active and gate.ohms is None:
        result.notes.append(
            f"{query!r} names a resistance that cannot be read as exactly one "
            "number; the gate fails closed rather than offering a rough match"
        )
        return result

    words = [w for w in normalise(gate.remainder).split() if w]
    categories = [w for w in words if w in CATEGORY_TO_PREFIX]
    expanded = expand_footprint_words(words, categories)
    result.unmapped_words = list(expanded.unmapped)
    if expanded.unmapped:
        result.notes.append(
            "not in the footprint vocabulary table, so it did not constrain the "
            "search: " + ", ".join(expanded.unmapped)
        )
    terms = _text_terms(words, categories, expanded)

    survivors: list[Candidate] = []
    for entry in library.parts:
        entry_resistance = entry.resistance()
        if gate.active:
            if entry_resistance is None or entry_resistance != gate.ohms:
                continue
        if expanded.names and not footprint_matches(entry.footprint_name, expanded.names):
            continue
        identity = normalise(
            " ".join([entry.key.replace(".", " ").replace("_", " "), entry.value, entry.mpn, entry.lcsc])
        )
        prose = normalise(" ".join([entry.manufacturer, entry.footprint_name]))
        relevance = 2 * term_hits(identity, terms) + term_hits(prose, terms)
        if terms and relevance == 0:
            continue
        survivors.append(candidate_from_entry(entry, relevance, entry_resistance))

    if terms and survivors:
        best = max(c.relevance for c in survivors)
        survivors = [c for c in survivors if c.relevance == best]

    def basic_rank(candidate: Candidate) -> int:
        return 0 if candidate.basic is True else 1 if candidate.basic is None else 2

    survivors.sort(key=lambda c: (-c.relevance, basic_rank(c), c.key))
    result.candidates = survivors
    if not survivors:
        result.notes.append(
            "no curated part matches; the library holds "
            f"{len(library.parts)} entr{'y' if len(library.parts) == 1 else 'ies'}"
        )
    return result


# --------------------------------------------------------------------------
# online: the JLC SMT catalog (explicit opt-in)
# --------------------------------------------------------------------------


def _catalog_resistance(candidate: CatalogCandidate) -> tuple[Decimal | None, str, str]:
    """``(ohms, raw, from)`` from a catalog row's **named** fields only.

    The category must say resistor first: an inductor's DCR or a ferrite's
    impedance is not the component being asked for, and a `Resistance` attribute
    alone does not make a part a resistor.
    """
    category = candidate.category
    if not re.search(r"\bresistors?\b|电阻", category, re.IGNORECASE):
        return (None, "", "")
    declared = [
        value
        for name, value in candidate.attributes.items()
        if name.strip().lower() in ("resistance", "阻值")
    ]
    if declared:
        if len(declared) != 1:
            return (None, "", "")  # conflicting declarations: no match
        raw = declared[0]
        from ..core.parts import parse_resistance_field

        found = parse_resistance_field(raw)
        if found is None:
            found = _single_quantity(raw)
        if found is None:
            return (None, "", "")
        return (found, raw, "attributes.Resistance")
    values = quantities_in_description(candidate.description)
    if values is not None and len(values) == 1:
        match = re.search(
            r"\d+(?:\.\d+)?\s*[mMkK]?\s*(?:Ω|Ω|(?i:ohms?))", candidate.description
        )
        return (next(iter(values)), match.group() if match else candidate.description, "describe")
    return (None, "", "")


def _single_quantity(text: str) -> Decimal | None:
    values = quantities_in_description(text)
    return next(iter(values)) if values is not None and len(values) == 1 else None


def select_online(
    query: str, *, qty: int = 100, client: CatalogClient | None = None, limit: int = 50
) -> SelectionResult:
    """Rank catalog candidates. **Requires an injected client or a network.**"""
    gate = resistance_query(query)
    result = SelectionResult(query=query, resistance=gate, online=True)
    if gate.active and gate.ohms is None:
        result.notes.append(
            f"{query!r} names a resistance that cannot be read as exactly one number"
        )
        return result

    words = [w for w in normalise(gate.remainder).split() if w]
    categories = [w for w in words if w in CATEGORY_TO_PREFIX]
    expanded = expand_footprint_words(words, categories)
    result.unmapped_words = list(expanded.unmapped)
    terms = _text_terms(words, categories, expanded)

    catalog = client or CatalogClient()
    rows = catalog.compare(gate.remainder.strip() or query, limit=limit)
    result.notes.extend(catalog.notes)
    if not rows:
        result.notes.append(
            "the catalog returned no rows; nothing was searched or cached to hide that"
        )
        return result

    ranked: list[Candidate] = []
    for row in rows:
        ohms, raw, where = _catalog_resistance(row)
        if gate.active and (ohms is None or ohms != gate.ohms):
            continue
        text = normalise(
            " ".join([row.mpn, row.description, row.category])
        )
        relevance = term_hits(text, terms)
        if terms and relevance == 0:
            continue
        ranked.append(
            Candidate(
                source="jlcpcb.com",
                lcsc=row.lcsc,
                mpn=row.mpn,
                brand=row.brand,
                description=row.description,
                footprint_name=row.attributes.get("Supplier Footprint", ""),
                basic=row.basic,
                preferred=row.preferred,
                stock=row.stock,
                in_stock=row.stock >= qty,
                unit_price=row.unit_price(qty),
                relevance=relevance + (1 if gate.active else 0),
                resistance=(
                    {"raw": raw, "ohms": format(ohms.normalize(), "f"), "from": where}
                    if ohms is not None
                    else None
                ),
            )
        )

    if terms and ranked:
        best = max(c.relevance for c in ranked)
        ranked = [c for c in ranked if c.relevance == best]
    # The task's order: spec match, then buildable, then basic, then preferred,
    # then cheapest. A basic part with too little stock therefore yields to an
    # in-stock one — being orderable beats avoiding a feeder fee.
    ranked.sort(
        key=lambda c: (
            -c.relevance,
            not c.in_stock,
            0 if c.basic else 1,
            not c.preferred,
            c.unit_price if c.unit_price is not None else Decimal(9999),
        )
    )
    result.candidates = ranked
    return result


def select(
    query: str,
    library: PartLibrary,
    *,
    qty: int = 100,
    online: bool = False,
    client: CatalogClient | None = None,
) -> SelectionResult:
    """The picker's front door: offline unless ``online`` is asked for."""
    if online:
        return select_online(query, qty=qty, client=client)
    return select_offline(query, library, qty=qty)


# --------------------------------------------------------------------------
# resolving an online pick's identity (bridge; exact key only)
# --------------------------------------------------------------------------

#: Catalog/library keys a C-number may arrive under. `supplierId` is documented
#: in the connector's own `lib.device.search` notes; the rest are fallbacks, and
#: whichever one answers is **reported** rather than assumed.
LCSC_ITEM_KEYS = (
    "supplierId",
    "lcsc",
    "supplierPart",
    "supplier_part",
    "lcscPart",
    "productCode",
    "componentCode",
    "Supplier Part",
)


@dataclass
class Resolution:
    """What the bridge said about a C-number — or why it could not say."""

    lcsc: str
    resolved: bool
    deviceUuid: str = ""
    libraryUuid: str = ""
    footprint_name: str = ""
    matched_key: str = ""
    items_seen: int = 0
    reason: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "lcsc": self.lcsc,
            "resolved": self.resolved,
            "deviceUuid": self.deviceUuid,
            "libraryUuid": self.libraryUuid,
            "footprint_name": self.footprint_name,
            "matched_key": self.matched_key,
            "items_seen": self.items_seen,
            "reason": self.reason,
        }


def _item_value(item: Any, key: str) -> str:
    if not isinstance(item, dict):
        return ""
    value = item.get(key)
    if value is None:
        return ""
    return str(value).strip()


async def resolve_by_lcsc(client: Any, lcsc: str, *, limit: int = 8) -> Resolution:
    """Turn a C-number into a library identity, through the bridge.

    Deterministic by construction: the C-number is an **exact key**, so an item
    is accepted only when one of its fields equals it outright. Zero matches, or
    more than one, is a refusal — a fuzzy keyword search that happened to return
    something is not an identity.

    The exact shape of a search item is not verified in this repo (it needs the
    live editor), so the fields used are reported in ``matched_key`` and a
    missing device uuid is a refusal rather than a partially-filled answer.
    """
    result = Resolution(lcsc=lcsc, resolved=False)
    wanted = lcsc.strip().upper()
    if not wanted:
        result.reason = "no C-number given"
        return result
    try:
        data = await client.call("lib.device.search", {"keyword": lcsc, "limit": limit})
    except Exception as exc:  # noqa: BLE001 — a bridge failure is one outcome here
        result.reason = f"lib.device.search failed: {exc}"
        return result
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        result.reason = "the search returned no item list"
        return result
    result.items_seen = len(items)

    matches: list[tuple[str, Any]] = []
    for item in items:
        for key in LCSC_ITEM_KEYS:
            if _item_value(item, key).upper() == wanted:
                matches.append((key, item))
                break
    if not matches:
        result.reason = (
            f"no returned item carries {lcsc} under any known key "
            f"({', '.join(LCSC_ITEM_KEYS)}); refusing to guess which hit is it"
        )
        return result
    if len(matches) > 1:
        result.reason = (
            f"{len(matches)} returned items carry {lcsc}; an exact key must be unique"
        )
        return result

    key, item = matches[0]
    device_uuid = _item_value(item, "uuid") or _item_value(item, "deviceUuid")
    if not device_uuid:
        result.reason = (
            f"the {lcsc} item matched on {key!r} but carries no device uuid "
            "(known keys: uuid / deviceUuid)"
        )
        return result
    result.resolved = True
    result.matched_key = key
    result.deviceUuid = device_uuid
    result.libraryUuid = _item_value(item, "libraryUuid") or _item_value(item, "library_uuid")
    result.footprint_name = _item_value(item, "footprintName") or _item_value(
        item, "footprint_name"
    )
    return result


__all__ = [
    "Candidate",
    "IDENTITY_FIELDS",
    "LCSC_ITEM_KEYS",
    "PROSE_FIELDS",
    "Resolution",
    "SelectionResult",
    "candidate_from_entry",
    "normalise",
    "resolve_by_lcsc",
    "select",
    "select_offline",
    "select_online",
    "term_hits",
]
