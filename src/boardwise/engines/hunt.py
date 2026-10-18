"""Bulk datasheet addressing: one board's parts, one channel decision each (520).

`parts fetch` answers "get me the datasheet for *this* part". A review of a real
board asks it for forty parts at once, and a list of forty search terms is a list
nobody works through. This module is the batch half, split the way the project's
boundary says a harness should be:

* **planning is pure** — :func:`judge_channel` decides, from the board's own
  identity fields, which of three channels a part is on: a C-number the detail
  API can be asked about, an MPN a search engine has to be handed, or neither.
  No network, no file, no clock.
* **execution is one function** — :func:`execute` turns one address into PDF
  bytes and text through seams the caller fills (:class:`Executor`), so the real
  downloader and the real pypdf runner stay in `cli.py` where `parts fetch`
  already owns them, and a test can prove that a call did not happen.

Three things this module refuses to do, each of them a way to produce confident
garbage:

* **trust `Component.lcsc_part`.** Measured on `tests/fixtures/llc_board.epro2`:
  4 of its 27 non-empty `lcsc_part` values hold a part number (`B3M040065H`), not
  a C-number. Asking the product endpoint about one of those spends a request to
  learn that the catalog has never heard of a part number, so the guard is
  shape-based (:func:`is_c_number`) and a non-matching value is treated as the
  MPN it actually is.
* **feed HTML to the extractor.** Both vendors answer a 404 or a throttled
  request with a landing page and a 200 status, and a text dump of that page
  extracts to nothing — which reads exactly like "the datasheet says nothing
  about this part". Bytes are a PDF when the magic says `%PDF` (`text/html` is a
  refusal on its own, because that *is* the landing page), and anything else is
  `download-failed` and never reaches
  :func:`boardwise.engines.datasheet.candidate_facts`.
* **merge the three blanks of a product answer.** "This part has no PDF", "the
  catalog does not know this C-number" and "the service did not answer" are three
  different next steps; they leave as `pdf-unavailable`, `service-unknown` and
  `no-pdf-url`.

**Privacy is a property of the request, not a promise.** The only request this
module can make is `productCode=<C-number>` (:data:`catalog.DETAIL_URL`) or the
URL an answer or an `--apply` file handed over; the only query text it can
*generate* is :func:`search_query`, and :func:`assert_query_is_safe` refuses
anything that is not that template with the MPN substituted.
:class:`AuditLog` records every call's request string — verbatim identity,
enforced by :func:`assert_request_is_identity` — so "what left this machine" is
checkable afterwards instead of asserted.

`--offline` is the same pipeline with the two outbound seams unused: the cache is
still read (a warm cache is a local file), every part whose address is already
known (a C-number, or an `--apply` URL) comes back `deferred-online` — a re-run
without the flag fetches it — and only the parts whose sole channel is a search
engine come back `needs-search`. See :func:`execute`'s ``offline`` branch for why
that line sits where it does.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from .catalog import (
    DETAIL_ANSWERED,
    DETAIL_NO_PDF_FIELD,
    DETAIL_UNKNOWN,
    DETAIL_UNANSWERED,
    ProductDetail,
    ProductFetcher,
    fetch_product_detail,
)

#: A 立创商城 supplier part number: `C` then at least four digits (`C2977777`,
#: `C46634460`). Anchored, because the measured fixture carries part numbers in
#: this field and a substring test would accept `B3M040065H`.
C_NUMBER_RE = re.compile(r"^C\d{4,}$")

# --- the closed outcome vocabulary -----------------------------------------
#
# Ten values, no synonyms: each one is a different next step. `pdf-unavailable`
# ("the vendor publishes no PDF for this part") and `service-unknown` ("the
# catalog does not hold this C-number") are one line apart in a report and three
# different phone calls in a review.
EXTRACTED = "extracted"
PDF_UNAVAILABLE = "pdf-unavailable"
SERVICE_UNKNOWN = "service-unknown"
NO_PDF_URL = "no-pdf-url"
DOWNLOAD_FAILED = "download-failed"
#: The PDF was read (text and page count are real) but this extractor found
#: nothing it recognises in it. Split from `parse-failed` because they are two
#: different sentences about two different subjects: `parse-failed` says "this
#: document could not be read", `no-facts` says "it was read, and the reader's
#: vocabulary does not cover it" — 45 passives and a 52-page TI gate driver
#: datasheet both land here, and a reader who is told they are "unparseable"
#: will go hunting for a better PDF that does not exist.
NO_FACTS = "no-facts"
PARSE_FAILED = "parse-failed"
NEEDS_SEARCH = "needs-search"
#: The tool can obtain this part **itself**; this run simply did not go online.
#: It is not `needs-search`: a search engine is the *expensive* channel, and
#: putting a C-number part on the work order asks a reader (or an AI) to spend
#: web-search turns on something one un-flagged re-run answers. The difference
#: matters most under `--offline`, which is the mode chosen precisely when the
#: network may not be used — a work order full of parts the tool could fetch is
#: the wrong advice for the one mode that must give advice it can stand behind.
DEFERRED_ONLINE = "deferred-online"
NO_IDENTITY = "no-identity"
UNKNOWN_DESIGNATOR = "unknown-designator"
CACHED = "cached"

#: Every outcome this module can produce, in report order. A value outside this
#: tuple is a bug, and :func:`counts_of` says so rather than quietly grouping it.
OUTCOMES: tuple[str, ...] = (
    EXTRACTED,
    CACHED,
    PDF_UNAVAILABLE,
    SERVICE_UNKNOWN,
    NO_PDF_URL,
    DOWNLOAD_FAILED,
    NO_FACTS,
    PARSE_FAILED,
    DEFERRED_ONLINE,
    NEEDS_SEARCH,
    NO_IDENTITY,
    UNKNOWN_DESIGNATOR,
)

# --- the two channels (plus the one that is not a channel) ------------------

CHANNEL_C_NUMBER = "c-number"
CHANNEL_MPN_ONLY = "mpn-only"
CHANNEL_NO_IDENTITY = "no-identity"


def is_c_number(value: str) -> bool:
    """Whether ``value`` is shaped like a 立创 C-number — and nothing more.

    Case-folded before the match, and that is a fold rather than a relaxation: a
    board that spellt the column `c2977777` still holds a C-number, and sending
    it down the MPN branch would spend a search on a supplier code. The shape
    requirement (a `C` and at least four digits) is exactly what the guard exists
    for: a `lcsc_part` holding `B3M040065H` is not a C-number at any case.

    Shape only, either way. Whether the catalog *knows* the number is the
    service's answer (`service-unknown`), never this function's.
    """
    return bool(C_NUMBER_RE.match((value or "").strip().upper()))


def judge_channel(component: object) -> str:
    """Which channel a board component is on: ``c-number`` / ``mpn-only`` /
    ``no-identity``.

    A valid C-number wins; anything else falls through to the part number. That
    order plus :func:`is_c_number`'s guard is the whole reason this is a function:
    a `lcsc_part` holding `B3M040065H` must become `mpn-only`, not a
    `service-unknown` that blames the catalog for a request nobody should have
    made. "The part number" therefore includes the **mislabelled C-number field**
    — :func:`identity_of` decides what a part's MPN is, and this function reads
    that answer rather than a second copy of the rule, so the channel and the
    identity cannot disagree about the same component.

    Duck-typed on ``lcsc_part`` / ``mpn``, like ``core.parts.resolve_component_facts``,
    so a parsed :class:`~boardwise.core.model.Component` and a live page's item are
    judged by one rule.
    """
    if is_c_number(str(getattr(component, "lcsc_part", "") or "")):
        return CHANNEL_C_NUMBER
    if identity_of(component)["mpn"]:
        return CHANNEL_MPN_ONLY
    return CHANNEL_NO_IDENTITY


def identity_of(component: object) -> dict[str, str]:
    """The two identity strings a part is addressed by, as the board spells them.

    ``lcsc`` is **the valid C-number or empty**: a `lcsc_part` holding an MPN is
    reported under ``mpn`` and not smuggled through as an address. ``mpn`` falls
    back to that mislabelled field — "the board put a part number in the C-number
    column" is still the reader's evidence of the part number.
    """
    lcsc = str(getattr(component, "lcsc_part", "") or "").strip()
    mpn = str(getattr(component, "mpn", "") or "").strip()
    if is_c_number(lcsc):
        return {"lcsc": lcsc.upper(), "mpn": mpn}
    return {"lcsc": "", "mpn": mpn or lcsc}


# --- the search query, and the guard that keeps it a template ---------------

#: The **whole** template. Not a format string with slots filled from board data:
#: a part's MPN is the only thing a query may carry, and it is the only thing that
#: goes in.
QUERY_TEMPLATE = '"{mpn}" datasheet pdf'

#: Everything a well-formed query may contain once the MPN is removed: the two
#: template words, the two quotes, and spaces.
_QUERY_ALLOWED_TAIL = frozenset('datasheetpdf" ')


class IdentityLeak(ValueError):
    """A generated query or audit request carries something that is not identity."""


def assert_query_is_safe(query: str, mpn: str) -> str:
    """Refuse a query that is anything other than :data:`QUERY_TEMPLATE`.

    The test is **equality with the template**, and the residue check below only
    exists to say *what* leaked. Equality is the stronger rule and the right one:
    a subtractive check alone would accept the same characters in another order
    (`datasheet pdf "ACME1"`), which is still a query nobody wrote — and the
    whole claim is that one template produced every query this tool can make.

    A guard function rather than a comment because the privacy claim is "the tool
    only ever sends a C-number or an MPN", and a template is only as good as the
    code allowed to skip it.
    """
    if not (mpn or "").strip():
        raise IdentityLeak("a search query needs an MPN; this one has none")
    expected = QUERY_TEMPLATE.format(mpn=mpn)
    if query == expected:
        return query
    if mpn not in query:
        raise IdentityLeak(
            f"query {query!r} does not carry the MPN {mpn!r} verbatim — the "
            "template is the only way a query may be built"
        )
    stray = sorted(
        {
            character
            for character in query.replace(mpn, "", 1)
            if character not in _QUERY_ALLOWED_TAIL
        }
    )
    if stray:
        raise IdentityLeak(
            f"query {query!r} carries more than the MPN and the template words "
            f"(offending: {''.join(stray)!r}); nothing from the board may be sent"
        )
    raise IdentityLeak(
        f"query {query!r} is not {expected!r}: the template is the only shape a "
        "query may take, so a reordering is a rewrite nobody asked for"
    )


def search_query(mpn: str) -> str:
    """The one query this tool generates for a part, guarded on the way out."""
    return assert_query_is_safe(QUERY_TEMPLATE.format(mpn=mpn), mpn)


def assert_request_is_identity(request: str, *, lcsc: str = "", mpn: str = "") -> str:
    """Refuse an audit ``request`` that is not **verbatim** one of the two ids.

    The audit log is the only artefact that can prove what left the machine, so it
    must not be able to record a URL (which would document the opposite), a
    designator, or a redacted form (`C2977…`). Verbatim equality with the
    C-number or the MPN, or the line is not written: a recorder that accepted
    anything would make the whole file decoration.
    """
    request = str(request or "")
    for value in (lcsc, mpn):
        if value and request == value:
            return request
    raise IdentityLeak(
        f"audit request {request!r} is neither the C-number {lcsc!r} nor the MPN "
        f"{mpn!r} verbatim; the audit log may only record a part's identity"
    )


# --- execution: the seams --------------------------------------------------


@dataclass
class Download:
    """One fetched body, as the download that produced it saw it.

    The payload is held in memory (a datasheet is a few megabytes and a batch has
    one in flight at a time) so the header test, the magic-byte test and the write
    all judge the same bytes — checking a file after writing it is how an HTML
    page ends up on disk next to a `download-failed` line.
    """

    ok: bool
    payload: bytes = b""
    content_type: str = ""
    status: int | None = None
    note: str = ""


#: `url -> Download`. The seam: a test passes a recorder and no test touches a
#: network, exactly as `catalog.ProductFetcher` is the seam for the detail API.
Downloader = Callable[[str], Download]


@dataclass
class Executor:
    """Everything :func:`execute` is allowed to call — the whole of its authority.

    ``fetch_detail`` is `catalog.fetch_product_detail`'s fetcher (a C-number in, a
    response object out), ``download`` takes a URL and gives bytes, and
    ``pdf_text`` runs the pypdf helper. Three seams, because those are the three
    places a test must be able to say "this did not happen"; the real ones are
    wired in `cli.py`, so `parts hunt` and `parts fetch` cannot drift apart about
    what a download or an extraction is.
    """

    fetch_detail: ProductFetcher
    download: Downloader
    pdf_text: Callable[[Path], tuple[str, str]]


def extract_pages(marked: str) -> list[str]:
    """`datasheet.pages_from_marked_text`, imported here so the seam stays visible."""
    from .datasheet import pages_from_marked_text

    return pages_from_marked_text(marked)


@dataclass
class Located:
    """One part addressed — the plan's output, before anything is fetched.

    ``url`` is set only by `--apply` (an answer handed back in). An empty one
    means "ask the detail API" on the ``c-number`` channel and "this part needs a
    search" on the other two.
    """

    designator: str
    channel: str
    identity: dict[str, str]
    url: str = ""
    notes: list[str] = field(default_factory=list)
    #: Bypass the cache: `--apply`'s hand-picked URL is a newer answer than the
    #: PDF already on disk, and serving the stale one would silently ignore the
    #: correction the engineer just made.
    force_download: bool = False


@dataclass
class Outcome:
    """One part's result, in the report's own shape (``outcome`` + ``pdf``)."""

    designator: str
    channel: str
    identity: dict[str, str]
    outcome: str
    url: str = ""
    notes: list[str] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    pdf: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "designator": self.designator,
            "channel": self.channel,
            "identity": dict(self.identity),
            "outcome": self.outcome,
            "url": self.url,
            "notes": list(self.notes),
            "pdf": dict(self.pdf),
            "facts": self.facts,
        }


def _detail_outcome(detail: ProductDetail) -> tuple[str, str]:
    """``(outcome, note)`` for a C-number that produced no PDF URL.

    The blanks :class:`ProductDetail` separates are the outcomes this report
    separates. Merged, a reader cannot tell "the vendor publishes no datasheet"
    (search elsewhere) from "the catalog does not hold this number" (the number is
    wrong) from "the service did not answer" (try again).
    """
    if detail.state == DETAIL_NO_PDF_FIELD:
        return NO_PDF_URL, "服务的回答里根本没有 `pdfUrl` 字段"
    if detail.state == DETAIL_ANSWERED:
        return PDF_UNAVAILABLE, "服务回答了这颗料，但回答里没有 PDF 链接（`pdfUrl` 为空）"
    if detail.state == DETAIL_UNKNOWN:
        return (
            SERVICE_UNKNOWN,
            "服务不认识这个 C 号（`result: null`）—— 记下的是一次查号失败，不是这颗料没有 PDF",
        )
    if detail.code is not None:
        return NO_PDF_URL, f"服务回了 code={detail.code}，没有 `result` 对象"
    return NO_PDF_URL, "服务没有给出可用的回答（没有 `result` 对象）"


def _content_type_is_pdf(content_type: str) -> bool | None:
    """``True``/``False`` when the header speaks, ``None`` when it says nothing.

    `application/octet-stream` is every vendor's favourite and means nothing, so
    an unrecognised type is *no information* and the magic bytes still decide.
    Only `text/*` is a refusal on its own — that is the landing page this
    pipeline exists to keep out of the extractor.
    """
    value = (content_type or "").split(";")[0].strip().lower()
    if not value:
        return None
    if value.startswith("text/"):
        return False
    if value in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        return True
    return None


def execute(
    located: Located,
    executor: Executor,
    *,
    cache: "Cache | None",
    audit: "AuditLog",
    label: str = "",
    offline: bool = False,
) -> Outcome:
    """One addressed part → one :class:`Outcome`. The whole fetch path, in one place.

    The order is the discipline, not an implementation detail: an `--apply` URL
    wins over everything (it is the answer a human just found), then the cache is
    read **before** any call (a warm cache makes the run able to answer without a
    network at all), and the bytes are checked **before** the extractor sees them
    (a landing page's text extracts to nothing, and "extracted nothing" is
    indistinguishable from "a datasheet this narrow extractor cannot read").

    ``offline`` makes the two outbound seams unreachable by construction — not by
    a flag checked at each call site, but by the branch below returning before
    them. A part that already has an address (a C-number, or an `--apply` URL)
    then lands on `deferred-online`: the tool can obtain it, this run did not go
    online. Such a part is **not** on the work order — a search engine is the
    expensive channel, and asking for one on a part a re-run answers is the wrong
    advice. What still lands on `needs-search` is the part whose **only** channel
    is a search engine (MPN without a C-number), and :func:`plan_rows` drops it
    when it has no MPN to search for.
    """
    from .datasheet import candidate_facts

    identity = dict(located.identity)
    lcsc, mpn = identity.get("lcsc", ""), identity.get("mpn", "")
    labelled = label or mpn or lcsc

    # --- the cache first: the identity is the key, so a warm cache answers
    # without resolving an address at all (and `--offline` can still hand over
    # facts it already has). An `--apply` URL bypasses it, because a hand-picked
    # link is a newer answer than whatever is on disk. A part with no identity has
    # no key, so it is not asked about — the branches below say what it is.
    if cache is not None and not located.force_download and (lcsc or mpn):
        pdf_path = cache.path_for(identity)
        if pdf_path.is_file() and pdf_path.read_bytes()[:4] == b"%PDF":
            return _from_cache(
                cache, identity, located, located.url, labelled, pdf_path, executor
            )

    # --- the address: what `--apply` handed over, else the detail API -------
    url = located.url
    detail: ProductDetail | None = None
    if not url:
        if located.channel == CHANNEL_NO_IDENTITY:
            return Outcome(
                designator=located.designator, channel=located.channel, identity=identity,
                outcome=NO_IDENTITY,
                notes=[*located.notes, "板上既没有合法 C 号也没有 MPN，工具搜不到这颗"],
            )
        if located.channel == CHANNEL_MPN_ONLY:
            return Outcome(
                designator=located.designator, channel=located.channel, identity=identity,
                outcome=NEEDS_SEARCH,
                notes=[
                    *located.notes,
                    "只有 MPN，没有可下载的地址；要搜索引擎兜底（hunt-plan.json）",
                ],
            )
        # `c-number`, and no address yet: this is the detail API's branch.
        if offline:
            return Outcome(
                designator=located.designator, channel=located.channel, identity=identity,
                outcome=DEFERRED_ONLINE,
                notes=[
                    *located.notes,
                    "--offline：一次外呼都没有，这颗的 C 号还没问过 detail API；"
                    "去掉 --offline 重跑，工具自己能取，不用搜",
                ],
            )
        detail = fetch_product_detail(executor.fetch_detail, lcsc)
        audit.record(
            channel="lcsc-detail",
            request=assert_request_is_identity(lcsc, lcsc=lcsc),
            http="" if detail.code is None else str(detail.code),
        )
        url = detail.pdf_url
        if not url:
            outcome, note = _detail_outcome(detail)
            return Outcome(
                designator=located.designator, channel=located.channel,
                identity=identity, outcome=outcome,
                notes=[*located.notes, note],
            )

    if offline:
        # An `--apply` URL under `--offline`: the URL is a local fact the file
        # already carried, but fetching it is not local, so this stays owed. It is
        # *not* a work order — nothing has to be searched, only fetched, and the
        # address is already in hand. Said out loud, because a reader who passed
        # both flags deserves to know which one won.
        return Outcome(
            designator=located.designator, channel=located.channel, identity=identity,
            outcome=DEFERRED_ONLINE, url=url,
            notes=[
                *located.notes,
                "--offline：没有外呼；这条地址是回灌文件给的，去掉 --offline 就会去取",
            ],
        )

    # --- the download ------------------------------------------------------
    downloaded = executor.download(url)
    audit.record(
        channel=located.channel,
        request=assert_request_is_identity(lcsc or mpn, lcsc=lcsc, mpn=mpn),
        http="" if downloaded.status is None else str(downloaded.status),
        payload=downloaded.payload,
    )
    if not downloaded.ok:
        return Outcome(
            designator=located.designator, channel=located.channel, identity=identity,
            outcome=DOWNLOAD_FAILED, url=url,
            notes=[*located.notes, downloaded.note or "下载失败"],
        )
    if _content_type_is_pdf(downloaded.content_type) is False:
        # The landing-page case, refused by the header alone. The extractor is not
        # called: a text dump of "Please wait, verifying your browser" would be a
        # document the curator reads and the tool believes.
        return Outcome(
            designator=located.designator, channel=located.channel, identity=identity,
            outcome=DOWNLOAD_FAILED, url=url,
            notes=[
                *located.notes,
                f"Content-Type 是 {downloaded.content_type!r}（落地页/错误页），没有交给提取器",
            ],
        )
    if not downloaded.payload.startswith(b"%PDF"):
        head = downloaded.payload[:60].decode("utf-8", "replace").replace("\n", " ")
        return Outcome(
            designator=located.designator, channel=located.channel, identity=identity,
            outcome=DOWNLOAD_FAILED, url=url,
            notes=[
                *located.notes,
                f"下载回来的不是 PDF（{len(downloaded.payload)} B，开头 {head!r}），"
                "没有交给提取器",
            ],
        )
    if cache is None:
        raise IdentityLeak(
            "no cache directory: a PDF would have nowhere to land, and a run that "
            "downloaded it anyway would have nothing to show for the bytes"
        )
    pdf_path = cache.path_for(identity)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.write_bytes(downloaded.payload)
    cache.write_meta(identity, url=url, channel=located.channel, size=len(downloaded.payload))

    try:
        marked, extractor = executor.pdf_text(pdf_path)
    except ValueError as exc:
        return Outcome(
            designator=located.designator, channel=located.channel, identity=identity,
            outcome=PARSE_FAILED, url=url,
            notes=[*located.notes, f"PDF 文本提取失败：{exc}"],
            pdf={"file": str(pdf_path), "bytes": str(len(downloaded.payload))},
        )
    cache.write_pages(identity, marked)
    cache.write_text(identity, marked)
    pages = extract_pages(marked)
    facts, notes = candidate_facts(pages, label=labelled, url=url)
    return Outcome(
        designator=located.designator,
        channel=located.channel,
        identity=identity,
        outcome=EXTRACTED if facts else NO_FACTS,
        url=url,
        notes=[*located.notes, *notes],
        facts=facts,
        pdf={
            "file": str(pdf_path),
            "bytes": str(len(downloaded.payload)),
            "extractor": extractor,
            "pages": str(len(pages)),
        },
    )


def _from_cache(
    cache: "Cache",
    identity: dict[str, str],
    located: Located,
    url: str,
    labelled: str,
    pdf_path: Path,
    executor: Executor,
) -> Outcome:
    """The cached branch: extract from what is on disk, never download again.

    A cache entry with no page dump (an earlier run interrupted between the write
    and the extraction) is extracted from the stored PDF rather than re-fetched —
    the bytes are the expensive half and they are already here. The URL comes from
    the cache's own meta file when the caller has none, so a cached row in an
    `--offline` report still says where the file came from.
    """
    from .datasheet import candidate_facts

    url = url or str(cache.read_meta(identity).get("url", ""))
    pages = cache.read_pages(identity)
    if pages is None:
        try:
            marked, _how = executor.pdf_text(pdf_path)
        except ValueError as exc:
            return Outcome(
                designator=located.designator, channel=located.channel, identity=identity,
                outcome=PARSE_FAILED, url=url,
                notes=[*located.notes, f"缓存里的 PDF 读不出文本：{exc}"],
                pdf={"file": str(pdf_path)},
            )
        cache.write_pages(identity, marked)
        cache.write_text(identity, marked)
        pages = extract_pages(marked)
    facts, notes = candidate_facts(pages, label=labelled, url=url)
    if not facts:
        return Outcome(
            designator=located.designator, channel=located.channel, identity=identity,
            outcome=NO_FACTS, url=url,
            notes=[*located.notes, *notes, "缓存里的 PDF 提取不出任何事实"],
            pdf={"file": str(pdf_path)},
        )
    return Outcome(
        designator=located.designator, channel=located.channel, identity=identity,
        outcome=CACHED, url=url,
        notes=[*located.notes, *notes, "命中缓存，没有重新下载"],
        facts=facts, pdf={"file": str(pdf_path)},
    )


# --- the cache -------------------------------------------------------------


class Cache:
    """A cross-board PDF store keyed by the part's own identity.

    ``<root>/<key>/<key>.pdf`` beside ``<key>.txt`` (the `<<<page N>>>` dump, what
    a curator reads), ``<key>.pages.json`` (that dump, split per page) and
    ``<key>.meta.json`` (where the bytes came from, so a cached row can still name
    its URL). Small files rather than a database because they are what a person
    opens when a fact looks wrong, and because the key has to be guessable: one
    part reached from two boards, or from the detail API and from `--apply`, must
    land on one file.

    The key prefers the C-number: one C-number is one part by definition, while
    two MPNs differing in case or in a vendor's own suffix are not certainly the
    same part, and a shared cache entry is a wrong datasheet nobody re-checks.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def key(self, identity: dict[str, str]) -> str:
        lcsc = (identity.get("lcsc") or "").strip()
        if lcsc:
            return lcsc.upper()
        mpn = re.sub(r"[^A-Za-z0-9._-]+", "_", identity.get("mpn") or "").strip("_")
        if not mpn:
            raise IdentityLeak("a cache key needs an identity; this part has none")
        return mpn

    def directory(self, identity: dict[str, str]) -> Path:
        return self.root / self.key(identity)

    def path_for(self, identity: dict[str, str]) -> Path:
        key = self.key(identity)
        return self.directory(identity) / f"{key}.pdf"

    def text_path(self, identity: dict[str, str]) -> Path:
        key = self.key(identity)
        return self.directory(identity) / f"{key}.txt"

    def pages_path(self, identity: dict[str, str]) -> Path:
        key = self.key(identity)
        return self.directory(identity) / f"{key}.pages.json"

    def meta_path(self, identity: dict[str, str]) -> Path:
        key = self.key(identity)
        return self.directory(identity) / f"{key}.meta.json"

    def write_pages(self, identity: dict[str, str], marked: str) -> None:
        path = self.pages_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(extract_pages(marked), ensure_ascii=False), encoding="utf-8"
        )

    def write_text(self, identity: dict[str, str], marked: str) -> None:
        path = self.text_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(marked, encoding="utf-8")

    def write_meta(
        self, identity: dict[str, str], *, url: str, channel: str, size: int
    ) -> None:
        path = self.meta_path(identity)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"url": url, "channel": channel, "bytes": size}, ensure_ascii=False
            ),
            encoding="utf-8",
        )

    def read_meta(self, identity: dict[str, str]) -> dict[str, Any]:
        path = self.meta_path(identity)
        if not path.is_file():
            return {}
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return meta if isinstance(meta, dict) else {}

    def read_pages(self, identity: dict[str, str]) -> list[str] | None:
        """The cached per-page text, or ``None`` when it was never written."""
        path = self.pages_path(identity)
        if not path.is_file():
            return None
        try:
            pages = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(pages, list):
            return None
        return [str(page) for page in pages]


# --- the audit log ---------------------------------------------------------


def payload_digest(payload: bytes) -> str:
    """sha256 of a reply, or ``""`` when there was no body to digest."""
    return hashlib.sha256(payload).hexdigest() if payload else ""


@dataclass
class AuditLog:
    """Every outbound call, one JSON line each — the only proof of what was sent.

    ``request`` is **never** a URL: the URL is a link the service handed us (or a
    file an answer named), and recording it would document the opposite of the
    claim this file exists to support. What the line says is the part's identity —
    the C-number or the MPN, verbatim — and :func:`assert_request_is_identity`
    refuses anything else. ``sha256`` ties a downloaded PDF to the line that
    fetched it.

    Lines are appended as they happen, so a run killed halfway still has the
    record of what it had already sent.
    """

    path: Path
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(
        self, *, channel: str, request: str, http: str = "", payload: bytes = b""
    ) -> None:
        entry = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "channel": channel,
            "request": request,
            "http": http,
            "bytes": len(payload),
            "sha256": payload_digest(payload),
        }
        self.entries.append(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    @property
    def outbound(self) -> int:
        return len(self.entries)


# --- the report shapes -----------------------------------------------------


def counts_of(outcomes: Iterable[Outcome]) -> dict[str, int]:
    """Counts over :data:`OUTCOMES`, **every key present**.

    Zero is a fact about this board ("no part came back cached"), and a report
    that omitted the zeros would make a reader diff two runs to learn whether a
    channel was used at all.
    """
    counts = {outcome: 0 for outcome in OUTCOMES}
    for item in outcomes:
        if item.outcome not in counts:
            raise IdentityLeak(f"outcome {item.outcome!r} is not in the vocabulary")
        counts[item.outcome] += 1
    return counts


def plan_rows(outcomes: Iterable[Outcome]) -> tuple[list[dict[str, str]], list[str]]:
    """``(rows, notes)`` — the search work order, ``{designator, mpn, query}`` only.

    "Needs a search" is read as **"has an MPN and this run did not obtain a PDF"**,
    which is the state an `--offline` run leaves every unresolved part in, not only
    the ones whose only channel is a search engine. That is deliberate: `--offline`
    is chosen for CI and for boards whose identity may not leave the machine, and
    the work order is what those runs owe the reader. The ``channel`` field in the
    report keeps the difference visible — a `c-number` row here is a part the tool
    *could* have fetched itself, so "re-run without `--offline`" is the cheaper
    answer and the markdown says so first.

    A `no-identity` part is **not** on the list even though it also needs a
    datasheet: there is no part number to search for, so the row would be a query
    for the empty string — the kind of work item that looks like coverage and is
    not. Those are counted in the report and named as the engineer's own job. A
    ``needs-search`` part with no MPN at all (a C-number-only part under
    `--offline`) is dropped with a note rather than raising: a report that could
    not be written would be worse than one that says what it left out.
    """
    rows: list[dict[str, str]] = []
    notes: list[str] = []
    for item in outcomes:
        if item.outcome != NEEDS_SEARCH:
            continue
        mpn = item.identity.get("mpn", "")
        if not mpn:
            notes.append(
                f"{item.designator} 要取但没有 MPN，进不了搜索工单"
                "（它有合法 C 号，联网跑就会走 detail API）"
            )
            continue
        rows.append({"designator": item.designator, "mpn": mpn, "query": search_query(mpn)})
    return rows, notes


#: The outcome vocabulary as a reader should read it, in report order.
OUTCOME_MEANING: dict[str, str] = {
    EXTRACTED: "下到 PDF，并提取出了候选 facts",
    CACHED: "命中缓存（已提取过），没有重新下载",
    PDF_UNAVAILABLE: "服务回答了，但这颗料没有 PDF",
    SERVICE_UNKNOWN: "服务不认识这个 C 号（`result: null`）",
    NO_PDF_URL: "服务的回答里没有 pdfUrl 字段",
    DOWNLOAD_FAILED: "下载回来不是 PDF（落地页/404），没有交给提取器",
    NO_FACTS: "PDF 读下来了（页数和全文都在），但这个提取器在文档里没找到它认识的条目——"
    "是提取器的覆盖面窄，不是资料有问题；全文已落盘给 AI/人看",
    PARSE_FAILED: "PDF 的文本本身读不出来（提取器报错），这一条是文档/环境的问题",
    NEEDS_SEARCH: "还没拿到 PDF，且只有 MPN —— 要搜索兜底（在 hunt-plan.json 里）",
    DEFERRED_ONLINE: "工具自己能取，只是这次没联网（`--offline`）；去掉它重跑即可，不用搜",
    NO_IDENTITY: "既无合法 C 号也无 MPN，只能由工程师自己给",
    UNKNOWN_DESIGNATOR: "回灌文件里点了板上没有的位号",
}


def markdown_report(
    *,
    board: dict[str, Any],
    outcomes: list[Outcome],
    counts: dict[str, int],
    outbound: int,
    offline: bool,
    plan_notes: list[str] | None = None,
) -> str:
    """The one-page human read: what came out, and what is left to do."""
    lines = [
        f"# 数据手册寻址 — {board.get('file', '')}",
        "",
        f"- 器件 {len(outcomes)} 颗；板：{board.get('title', '') or '-'}"
        f"（{board.get('boards', '') or 0} 块板）",
        f"- 外呼 {outbound} 次" + ("（--offline：一次都没有）" if offline else ""),
        "",
        "## 结果分布",
        "",
        "| outcome | 颗数 | 含义 |",
        "| --- | --- | --- |",
    ]
    for outcome in OUTCOMES:
        if counts.get(outcome):
            lines.append(f"| `{outcome}` | {counts[outcome]} | {OUTCOME_MEANING[outcome]} |")
    if not any(counts.values()):
        lines.append("| （空） | 0 | 这颗板上没有要寻址的器件 |")

    lines += ["", "## 还剩什么要人做", ""]
    todo: list[str] = []
    search = [o for o in outcomes if o.outcome == NEEDS_SEARCH]
    if offline and search:
        fetchable = [o for o in search if o.channel == CHANNEL_C_NUMBER]
        todo.append(
            f"- **本次是 `--offline`，一次外呼都没有**：{len(search)} 颗还没拿到 PDF"
            + (
                f"，其中 {len(fetchable)} 颗有合法 C 号 —— 去掉 `--offline` 重跑，"
                "工具自己就能问 detail API 取回"
                if fetchable
                else ""
            )
        )
    if search:
        searchable = [o for o in search if o.channel == CHANNEL_MPN_ONLY]
        if searchable:
            verb = "剩下的" if offline else ""
            todo.append(
                f"- **{verb}搜索兜底 {len(searchable)} 颗**："
                "用 `hunt-plan.json` 里的 query 找到 PDF，"
                "把 {designator, url} 写进 answers.json，再 `--apply` 回灌"
                "（下载 + 提取 + 落架走同一条路径）"
            )
    blank = [o for o in outcomes if o.outcome == NO_IDENTITY]
    if blank:
        names = "、".join(item.designator for item in blank[:12])
        todo.append(
            f"- **无身份 {len(blank)} 颗**（{names}{'…' if len(blank) > 12 else ''}）："
            "板上既没有合法 C 号也没有 MPN，工具搜不到，只能人给身份"
        )
    empty = [o for o in outcomes if o.outcome == NO_FACTS]
    if empty:
        roots = sorted(
            {
                str(Path(str(item.pdf.get("file"))).parent.parent)
                for item in empty
                if (item.pdf or {}).get("file")
            }
        )
        where = f"（缓存在 {roots[0]} 的 `<C号>/` 目录下，全文 `.txt` 与 PDF 同目录）" if roots else ""
        todo.append(
            f"- **{len(empty)} 颗 PDF 读下来了、提取器提不出它认识的条目**{where}"
            "：这是**提取器的覆盖面**问题，不是资料问题 —— 让 AI/人读那份 `.txt` 写 facts，"
            "或等提取器扩面（见 docs/roadmap.md §7）"
        )
    broken = [o for o in outcomes if o.outcome == PARSE_FAILED]
    if broken:
        todo.append(
            f"- **{len(broken)} 颗的 PDF 文本读不出来**：换一份文件（`--apply`），"
            "或看提取器自己报的错"
        )
    failed = [o for o in outcomes if o.outcome == DOWNLOAD_FAILED]
    if failed:
        todo.append(f"- **{len(failed)} 颗下载失败**：换一个地址（`--apply`）或重试")
    blank_service = [
        o for o in outcomes if o.outcome in (PDF_UNAVAILABLE, SERVICE_UNKNOWN, NO_PDF_URL)
    ]
    if blank_service:
        todo.append(
            f"- **{len(blank_service)} 颗服务那一侧没有可用的 PDF**："
            "补一个正确的 C 号，或当作搜索兜底处理"
        )
    for note in plan_notes or []:
        todo.append(f"- {note}")
    if not todo:
        todo.append("- 没有：每颗器件都拿到了 PDF 与候选 facts")
    lines += todo

    lines += [
        "",
        "## 诚实边界",
        "",
        "喂 PDF ≠ 清闸；hunt 只产出 candidate 条目，规则仍然不认它。",
        "提取出来的 facts 一律 `facts_verified: false`，要清闸仍需逐条对着页码核过、"
        "再 `boardwise parts add … --verified` 翻 true。",
        "",
        "外呼边界：只发 C 号（detail API）或 MPN（搜索 query）——"
        "`hunt-audit.jsonl` 逐条记 request 字段，它是「没把板子信息发出去」的唯一证据。",
        "",
    ]
    return "\n".join(lines)
