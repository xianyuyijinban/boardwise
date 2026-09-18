"""The JLC SMT catalog client — the **opt-in** online half of part selection.

Task 008b is explicit about the shape of this: the online comparison is
`--online`, never the default, and **tests must not touch the network**. So the
network lives behind a one-method seam (:data:`Fetcher`) that the default
implementation happens to fill with ``urllib`` and the tests fill with a
recorded response. Nothing else in the pipeline knows the difference.

Where it runs is also a requirement, not a preference: **not in the connector.**
The EasyEDA webview cannot make these cross-origin fetches — the reference
implementation hit the same wall — so the call belongs to the Python side
(daemon or tool), which is what this module is.

Honest boundary: this repo has never run this call against the live service.
The request shape and the response keys below come from the reference
implementation's notes (``references/part-selection.md``), which recorded them
as verified on 2026-09. They are therefore *reported* evidence, not measured
here; a live run is a step for whoever holds the network, and the client is
written so that a shape change fails loudly (missing keys become empty fields
plus a note) rather than silently producing an empty list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

#: The endpoint the reference implementation recorded.
JLC_URL = (
    "https://jlcpcb.com/api/overseas-pcb-order/v1/"
    "shoppingCart/smtGood/selectSmtComponentList"
)

#: A browser User-Agent: the endpoint is the site's own XHR, not a documented API.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/136 Safari/537.36"
)

#: `payload -> response dict`. The seam: tests pass a recorded response here and
#: the rest of the pipeline cannot tell the difference.
Fetcher = Callable[[dict[str, Any]], dict[str, Any]]


class CatalogError(RuntimeError):
    """The catalog could not be read."""


def urllib_fetcher(payload: dict[str, Any], *, timeout: float = 15.0) -> dict[str, Any]:
    """The real fetcher. Imported lazily so offline use never loads the stack."""
    import urllib.request

    request = urllib.request.Request(
        JLC_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - network failures are all one thing here
        raise CatalogError(f"JLC SMT request failed: {exc}") from exc
    if not isinstance(decoded, dict):
        raise CatalogError("JLC SMT returned something that is not an object")
    return decoded


@dataclass
class CatalogCandidate:
    """One row of the catalog, in boardwise's vocabulary."""

    lcsc: str
    mpn: str = ""
    brand: str = ""
    description: str = ""
    category: str = ""
    stock: int = 0
    basic: bool = False
    preferred: bool = False
    prices: list[dict[str, Any]] = field(default_factory=list)
    #: Named catalog attributes, verbatim (`{"Resistance": "5.1kΩ ±1%"}`).
    attributes: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def unit_price(self, qty: int) -> Decimal | None:
        """The tier price covering ``qty``.

        Falls back to the first tier when nothing covers ``qty`` — that is the
        *smallest* quantity's price, i.e. the most conservative guess for a
        larger order, and it is reported as a price, never as a stock claim.
        """
        best: Decimal | None = None
        for tier in self.prices:
            start = _to_int(tier.get("startNumber"), 1)
            end = _to_int(tier.get("endNumber"), 10**12)
            price = _to_decimal(tier.get("productPrice"))
            if price is None:
                continue
            if start <= qty <= end:
                return price
            if best is None and start <= qty:
                best = price
        if best is not None:
            return best
        for tier in self.prices:
            price = _to_decimal(tier.get("productPrice"))
            if price is not None:
                return price
        return None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


_ATTRIBUTE_NAME_KEYS = ("attribute_name_en", "attribute_name", "name")
_ATTRIBUTE_VALUE_KEYS = ("attribute_value_name", "attribute_value", "value")


def candidate_from_item(item: dict[str, Any]) -> CatalogCandidate:
    """Map one catalog row. Unknown shapes yield empty fields, never a guess.

    Only keys the reference recorded are read. A row missing ``componentCode``
    is not a part this pipeline can order, so the caller drops it rather than
    inventing an identity for it.
    """
    attributes: dict[str, str] = {}
    raw_attrs = item.get("attributes")
    if isinstance(raw_attrs, list):
        for entry in raw_attrs:
            if not isinstance(entry, dict):
                continue
            name = next(
                (str(entry.get(key)) for key in _ATTRIBUTE_NAME_KEYS if entry.get(key)), ""
            )
            value = next(
                (str(entry.get(key)) for key in _ATTRIBUTE_VALUE_KEYS if entry.get(key)), ""
            )
            if name and value:
                attributes[name] = value

    prices = item.get("componentPrices")
    return CatalogCandidate(
        lcsc=str(item.get("componentCode") or "").strip(),
        mpn=str(item.get("componentModelEn") or "").strip(),
        brand=str(item.get("componentBrandEn") or "").strip(),
        description=str(
            item.get("describe") or item.get("componentSpecificationEn") or ""
        ).strip(),
        category=str(item.get("componentTypeEn") or item.get("secondSortName") or "").strip(),
        stock=_to_int(item.get("stockCount"), 0),
        basic=str(item.get("componentLibraryType") or "").lower() == "base",
        preferred=bool(item.get("preferredComponentFlag")),
        prices=[p for p in prices if isinstance(p, dict)] if isinstance(prices, list) else [],
        attributes=attributes,
        raw=item,
    )


class CatalogClient:
    """Queries the catalog. ``fetcher`` is the only thing that can reach a network."""

    def __init__(self, fetcher: Fetcher | None = None) -> None:
        self._fetcher: Fetcher = fetcher or (lambda payload: urllib_fetcher(payload))
        self.notes: list[str] = []

    def search(
        self, keyword: str, *, limit: int = 20, library_type: str | None = None
    ) -> list[CatalogCandidate]:
        """One catalog query. ``library_type='base'`` restricts it to basic parts."""
        payload: dict[str, Any] = {
            "keyword": keyword,
            "currentPage": 1,
            "pageSize": limit,
        }
        if library_type:
            payload["componentLibraryType"] = library_type
        response = self._fetcher(payload)
        data = response.get("data")
        if not isinstance(data, dict):
            self.notes.append(
                "the response carries no `data` object; nothing could be read from it"
            )
            return []
        page = data.get("componentPageInfo")
        if not isinstance(page, dict):
            self.notes.append(
                "the response carries no `data.componentPageInfo`; nothing could be read"
            )
            return []
        rows = page.get("list")
        if not isinstance(rows, list):
            self.notes.append("`data.componentPageInfo.list` is not a list")
            return []
        return [
            candidate_from_item(row)
            for row in rows
            if isinstance(row, dict) and row.get("componentCode")
        ]

    def compare(self, keyword: str, *, limit: int = 20) -> list[CatalogCandidate]:
        """The comparison query: basic **and** general, merged, deduplicated.

        Basic parts only surface when ``componentLibraryType='base'`` is passed
        explicitly, so one query is not enough; the wanted basic part can also
        rank below other basics, which is why the base query asks for a generous
        page. Merging is by C-number, keeping whichever occurrence came first
        (base first, so a part that is basic in both lists stays marked basic).
        """
        merged: dict[str, CatalogCandidate] = {}
        for library_type in ("base", None):
            for candidate in self.search(
                keyword, limit=limit, library_type=library_type
            ):
                merged.setdefault(candidate.lcsc, candidate)
        return list(merged.values())


# ---------------------------------------------------------------------------
# The product-detail endpoint (008b tail: datasheet PDF links)
# ---------------------------------------------------------------------------

#: The product page's own XHR. A second endpoint rather than a second call of
#: the first one: this is a `GET` keyed by the C-number (not a posted search
#: body), and what it is read for — the datasheet PDF link — is a different
#: question than "which parts match this keyword".
DETAIL_URL = "https://wmsc.lcsc.com/ftps/wm/product/detail"

#: `product code -> response dict`. The seam, for the same reason as `Fetcher`:
#: the tests record an answer and no test touches a network.
ProductFetcher = Callable[[str], dict[str, Any]]


def urllib_product_fetcher(product_code: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """The real product fetcher. Imported lazily so offline use never loads it."""
    import urllib.parse
    import urllib.request

    url = f"{DETAIL_URL}?productCode={urllib.parse.quote(product_code)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - network failures are all one thing here
        raise CatalogError(f"LCSC product request failed: {exc}") from exc
    if not isinstance(decoded, dict):
        raise CatalogError("LCSC product detail returned something that is not an object")
    return decoded


@dataclass
class ProductDetail:
    """What the product page says about one C-number.

    ``answered`` is the field that keeps two different blanks apart: "the
    service said this part has no PDF" and "the service could not be asked"
    both leave :attr:`pdf_url` empty, and only one of them is a fact about the
    part. The caller decides what to do with each; neither is ever filled in by
    a guess.
    """

    lcsc: str
    pdf_url: str = ""
    #: The service's own status code, when it sent one.
    code: int | None = None
    #: True when a `result` object was read, whatever it contained.
    answered: bool = False
    notes: list[str] = field(default_factory=list)


def fetch_product_detail(fetcher: ProductFetcher, lcsc: str) -> ProductDetail:
    """Read one product's datasheet link. Never invents one.

    Measured 2026-09-17 against the live endpoint (C2977777)::

        {"code":200,"result":{ ..., "pdfUrl":"https://datasheet.lcsc.com/...pdf" }}

    A non-200 ``code``, a missing ``result``, and a ``result`` without a
    ``pdfUrl`` are three distinct outcomes, and each is reported rather than
    collapsed into "empty".
    """
    wanted = lcsc.strip().upper()
    detail = ProductDetail(lcsc=wanted)
    if not wanted:
        detail.notes.append("no C-number given")
        return detail
    try:
        response = fetcher(wanted)
    except Exception as exc:  # noqa: BLE001 — a transport failure is one outcome
        detail.notes.append(f"request failed: {exc}")
        return detail
    if not isinstance(response, dict):
        detail.notes.append("the response is not an object")
        return detail
    code = response.get("code")
    if isinstance(code, int):
        detail.code = code
    result = response.get("result")
    if not isinstance(result, dict):
        if detail.code is not None and detail.code != 200:
            detail.notes.append(f"the service answered code={detail.code}")
        elif result is None and "result" in response:
            # Measured 2026-09-17: an unknown C-number is not an error status —
            # the service answers `{"code":200,"result":null,"ok":true}`. That is
            # a fact about the part ("the catalog does not know this number"), and
            # it is worded as such rather than as a malformed response.
            detail.notes.append(
                f"the service answered `result: null` for {wanted} — the catalog "
                "does not know this C-number"
            )
        else:
            detail.notes.append("the response carries no `result` object")
        return detail
    detail.answered = True
    if detail.code is not None and detail.code != 200:
        detail.notes.append(f"the service answered code={detail.code}")
    raw = result.get("pdfUrl")
    if isinstance(raw, str) and raw.strip():
        detail.pdf_url = raw.strip()
    else:
        detail.notes.append("the product carries no `pdfUrl`")
    return detail


__all__ = [
    "CatalogCandidate",
    "CatalogClient",
    "CatalogError",
    "DETAIL_URL",
    "Fetcher",
    "JLC_URL",
    "ProductDetail",
    "ProductFetcher",
    "USER_AGENT",
    "candidate_from_item",
    "fetch_product_detail",
    "urllib_fetcher",
    "urllib_product_fetcher",
]
