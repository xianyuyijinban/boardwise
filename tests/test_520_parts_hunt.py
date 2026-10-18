"""520: `parts hunt` — the batch half of the datasheet channel.

The properties under test are the ones a batch run can get wrong **confidently**,
so they are asserted as *counterfactuals* wherever possible: not "the download
was refused" but "the extractor was never called"; not "the field is blank" but
"the product endpoint was never asked". A test that only checked the report's
word would pass on an implementation that had already made the call.

No test touches a network. The three seams (`Executor.fetch_detail`,
`Executor.download`, `Executor.pdf_text`) are filled with recorders, exactly as
`tests/test_datasheet_backfill.py` fills `catalog.ProductFetcher` — the parallel
is deliberate, because the discipline is the same one and a reader who knows one
should recognise the other.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import Component
from boardwise.core.parts import load_parts
from boardwise.engines import hunt
from boardwise.engines.catalog import CatalogError

#: A page set the narrow extractor can actually turn into facts: one pin-table
#: row and one specification row, which is the join `candidate_facts` needs.
MARKED = """<<<page 1>>>
Table 5-1 Pin Functions
VCC 3 Supply 3.3V supply voltage
<<<page 4>>>
8.3 Recommended Operating Conditions
Supply voltage, VCC 3 3.6 V
"""


# --------------------------------------------------------------------------
# the recorders (the seams, filled)
# --------------------------------------------------------------------------


@dataclass
class Recorder:
    """Every call a seam saw, and what it answered — the whole of the fake network."""

    detail_calls: list[str] = field(default_factory=list)
    download_calls: list[str] = field(default_factory=list)
    extract_calls: list[Path] = field(default_factory=list)
    detail_answers: dict[str, dict] = field(default_factory=dict)
    bodies: dict[str, "hunt.Download"] = field(default_factory=dict)
    default_body: "hunt.Download | None" = None
    marked: str = MARKED

    def fetch_detail(self, product_code: str) -> dict:
        self.detail_calls.append(product_code)
        if product_code not in self.detail_answers:
            raise CatalogError(f"no recorded answer for {product_code}")
        return self.detail_answers[product_code]

    def download(self, url: str) -> "hunt.Download":
        self.download_calls.append(url)
        if url in self.bodies:
            return self.bodies[url]
        if self.default_body is not None:
            return self.default_body
        return hunt.Download(
            ok=True, payload=b"%PDF-1.4 fake body", content_type="application/pdf", status=200
        )

    def pdf_text(self, path: Path) -> tuple[str, str]:
        self.extract_calls.append(Path(path))
        return self.marked, "stub extractor"

    def executor(self) -> "hunt.Executor":
        return hunt.Executor(
            fetch_detail=self.fetch_detail,
            download=self.download,
            pdf_text=self.pdf_text,
        )


def detail_with_pdf(url: str = "https://example.invalid/ds.pdf") -> dict:
    return {"code": 200, "result": {"pdfUrl": url, "productModel": "X"}}


def detail_unknown() -> dict:
    """Measured 2026-09-17: an unknown C-number answers `result: null`, code 200."""
    return {"code": 200, "msg": None, "result": None, "ok": True}


def detail_without_pdf() -> dict:
    return {"code": 200, "result": {"pdfUrl": None}}


# --------------------------------------------------------------------------
# components — built directly, so no fixture board's identity is typed here
# --------------------------------------------------------------------------


def component(*, lcsc: str = "", mpn: str = "", value: str = "") -> Component:
    return Component(uid="u", designator="U1", lcsc_part=lcsc, mpn=mpn, value=value)


def located(component_obj: Component, designator: str = "U1") -> "hunt.Located":
    return hunt.Located(
        designator=designator,
        channel=hunt.judge_channel(component_obj),
        identity=hunt.identity_of(component_obj),
    )


def run_one(
    recorder: Recorder,
    component_obj: Component,
    *,
    cache: "hunt.Cache | None" = None,
    audit: "hunt.AuditLog | None" = None,
    offline: bool = False,
    designator: str = "U1",
    url: str = "",
    force_download: bool = False,
    audit_dir: Path | None = None,
) -> tuple["hunt.Outcome", "hunt.AuditLog"]:
    item = located(component_obj, designator)
    item.url = url
    item.force_download = force_download
    log = audit or hunt.AuditLog(
        (audit_dir or Path(tempfile.mkdtemp(prefix="hunt520-"))) / "hunt-audit.jsonl"
    )
    outcome = hunt.execute(
        item, recorder.executor(), cache=cache, audit=log, offline=offline
    )
    return outcome, log


# --------------------------------------------------------------------------
# §1 the channel decision
# --------------------------------------------------------------------------


def test_a_valid_c_number_takes_the_detail_channel():
    assert hunt.judge_channel(component(lcsc="C2977777")) == hunt.CHANNEL_C_NUMBER
    assert hunt.judge_channel(component(lcsc="c2977777")) == hunt.CHANNEL_C_NUMBER


def test_a_short_c_prefix_is_not_a_c_number():
    """`C1` is a shelf-number shape, not a catalog C-number (four digits minimum)."""
    assert hunt.judge_channel(component(lcsc="C1", mpn="ACME1")) == hunt.CHANNEL_MPN_ONLY


def test_nothing_usable_is_no_identity():
    assert hunt.judge_channel(component()) == hunt.CHANNEL_NO_IDENTITY
    assert hunt.judge_channel(component(lcsc="   ")) == hunt.CHANNEL_NO_IDENTITY


def test_a_part_number_in_the_c_number_field_becomes_mpn_only():
    """Measured on the LLC fixture: 4 of 27 `lcsc_part` values hold an MPN.

    The strong assertion is the *absence* of the call: the guard exists so the
    catalog is not asked about a part number, and a test that only checked the
    channel label would pass on an implementation that labelled correctly and
    then asked anyway.
    """
    recorder = Recorder()
    dirty = component(lcsc="ACME-MOSFET-60V", mpn="")
    outcome, log = run_one(recorder, dirty, cache=None)
    assert hunt.judge_channel(dirty) == hunt.CHANNEL_MPN_ONLY
    assert outcome.outcome == hunt.NEEDS_SEARCH
    assert recorder.detail_calls == [], "a non-C-number must never reach the detail API"
    assert log.entries == []


def test_a_dirty_c_number_field_keeps_the_part_number_it_holds():
    """The mislabelled field is still evidence of the part number (identity_of)."""
    identity = hunt.identity_of(component(lcsc="ACME-MOSFET-60V", mpn=""))
    assert identity == {"lcsc": "", "mpn": "ACME-MOSFET-60V"}


# --------------------------------------------------------------------------
# §2 the detail channel and its three blanks
# --------------------------------------------------------------------------


def test_a_c_number_with_a_pdf_url_is_downloaded_and_extracted(tmp_path):
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    outcome, log = run_one(
        recorder, component(lcsc="C2977777", mpn="ACME1"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.EXTRACTED
    assert recorder.detail_calls == ["C2977777"], "the request is the C-number alone"
    assert recorder.download_calls == ["https://example.invalid/ds.pdf"]
    supply = outcome.facts["supply_pins"][0]
    assert supply["v_operating"] == [3.0, 3.6]
    # Both halves cite their own page: the pin table and the spec row are on
    # different pages of a real datasheet, and that join is the whole point.
    assert "p.1" in supply["provenance"] and "p.2" in supply["provenance"]
    # The PDF and its text dump landed in the cache, under the C-number.
    assert (tmp_path / "C2977777" / "C2977777.pdf").is_file()
    assert (tmp_path / "C2977777" / "C2977777.txt").read_text(encoding="utf-8") == MARKED
    # Every outbound call is on the audit, and the request is the identity itself.
    assert [entry["request"] for entry in log.entries] == ["C2977777", "C2977777"]


def test_result_null_is_service_unknown_and_not_no_pdf_url(tmp_path):
    """The three blanks are three outcomes; merging any two is the bug this pins."""
    recorder = Recorder()
    recorder.detail_answers["C9900000001"] = detail_unknown()
    outcome, _log = run_one(
        recorder, component(lcsc="C9900000001"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.SERVICE_UNKNOWN
    assert outcome.outcome != hunt.NO_PDF_URL
    assert recorder.download_calls == []


def test_an_answered_product_without_a_pdf_url_is_pdf_unavailable(tmp_path):
    recorder = Recorder()
    recorder.detail_answers["C160183"] = detail_without_pdf()
    outcome, _log = run_one(recorder, component(lcsc="C160183"), cache=hunt.Cache(tmp_path))
    assert outcome.outcome == hunt.PDF_UNAVAILABLE
    assert outcome.outcome != hunt.SERVICE_UNKNOWN
    assert recorder.download_calls == []


def test_an_unanswered_product_is_no_pdf_url(tmp_path):
    recorder = Recorder()
    recorder.detail_answers["C55555"] = {"code": 500, "result": None}
    outcome, _log = run_one(recorder, component(lcsc="C55555"), cache=hunt.Cache(tmp_path))
    assert outcome.outcome == hunt.NO_PDF_URL
    assert recorder.download_calls == []


def test_a_missing_pdf_url_field_is_no_pdf_url(tmp_path):
    recorder = Recorder()
    recorder.detail_answers["C55666"] = {"code": 200, "result": {"productModel": "X"}}
    outcome, _log = run_one(recorder, component(lcsc="C55666"), cache=hunt.Cache(tmp_path))
    assert outcome.outcome == hunt.NO_PDF_URL


# --------------------------------------------------------------------------
# §3 the download check — a landing page never reaches the extractor
# --------------------------------------------------------------------------


def test_an_html_landing_page_is_download_failed_and_never_extracted(tmp_path):
    """The counterfactual is the point: `extract_calls == []`.

    A text dump of "Please wait, verifying your browser" extracts to nothing, and
    "extracted nothing" cannot be told apart from "this datasheet is outside the
    extractor's reach" — so the check has to happen while the answer is still
    "not a PDF".
    """
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    recorder.bodies["https://example.invalid/ds.pdf"] = hunt.Download(
        ok=True,
        payload=b"<!DOCTYPE html><html><body>Please wait</body></html>",
        content_type="text/html; charset=utf-8",
        status=200,
    )
    outcome, _log = run_one(
        recorder, component(lcsc="C2977777"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.DOWNLOAD_FAILED
    assert recorder.extract_calls == [], "the extractor must not see an HTML page"
    assert not (tmp_path / "C2977777" / "C2977777.pdf").exists()


def test_html_bytes_with_a_lying_content_type_are_still_refused(tmp_path):
    """`application/octet-stream` is no information; the magic bytes decide."""
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    recorder.bodies["https://example.invalid/ds.pdf"] = hunt.Download(
        ok=True,
        payload=b"<html>nope</html>",
        content_type="application/octet-stream",
        status=200,
    )
    outcome, _log = run_one(
        recorder, component(lcsc="C2977777"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.DOWNLOAD_FAILED
    assert recorder.extract_calls == []


def test_pdf_bytes_with_a_silent_content_type_are_accepted(tmp_path):
    """The other half: a good PDF must not be refused for a missing header."""
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    recorder.bodies["https://example.invalid/ds.pdf"] = hunt.Download(
        ok=True, payload=b"%PDF-1.4 real body", content_type="", status=200
    )
    outcome, _log = run_one(
        recorder, component(lcsc="C2977777"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.EXTRACTED
    assert recorder.extract_calls == [tmp_path / "C2977777" / "C2977777.pdf"]


def test_a_transport_failure_is_download_failed(tmp_path):
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    recorder.bodies["https://example.invalid/ds.pdf"] = hunt.Download(
        ok=False, note="下载失败：connection reset"
    )
    outcome, _log = run_one(
        recorder, component(lcsc="C2977777"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.DOWNLOAD_FAILED
    assert recorder.extract_calls == []


def test_a_pdf_the_extractor_reads_to_nothing_is_no_facts_not_a_parse_failure(tmp_path):
    """Zero facts is a distinct outcome, and the text dump is kept for the curator.

    `no-facts` and `parse-failed` are two different sentences: this document was
    read (page markers, full text on disk) and the reader's vocabulary simply did
    not cover it. Calling that "unparseable" sends the reader hunting for a better
    PDF that does not exist — 45 passives and a 52-page TI gate-driver datasheet
    measured on a real board were all read fine and all produced this outcome.
    """
    recorder = Recorder()
    recorder.marked = "<<<page 1>>>\nnothing here\n"
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    outcome, _log = run_one(
        recorder, component(lcsc="C2977777"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.NO_FACTS
    assert outcome.facts == {}
    assert (tmp_path / "C2977777" / "C2977777.txt").read_text(encoding="utf-8") == (
        "<<<page 1>>>\nnothing here\n"
    )


def test_a_text_reader_that_raises_is_the_only_parse_failure(tmp_path):
    """The other half of the split: a reader error says so, and stays `parse-failed`."""
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()

    def refuse(_path):
        raise ValueError("cannot read: broken xref")

    recorder.pdf_text = refuse  # type: ignore[method-assign]
    outcome, _log = run_one(
        recorder, component(lcsc="C2977777"), cache=hunt.Cache(tmp_path)
    )
    assert outcome.outcome == hunt.PARSE_FAILED
    assert any("提取失败" in note for note in outcome.notes)


# --------------------------------------------------------------------------
# §4 the cache
# --------------------------------------------------------------------------


def test_a_second_run_is_cached_and_does_not_download_again(tmp_path):
    cache = hunt.Cache(tmp_path)
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    first, _log = run_one(recorder, component(lcsc="C2977777"), cache=cache)
    assert first.outcome == hunt.EXTRACTED
    downloads_after_first = list(recorder.download_calls)

    second_recorder = Recorder()
    second, _log = run_one(second_recorder, component(lcsc="C2977777"), cache=cache)
    assert second.outcome == hunt.CACHED
    assert second.facts == first.facts, "the cached run hands over the same facts"
    assert second_recorder.detail_calls == [], "the address came from the cache's meta"
    assert second_recorder.download_calls == []
    assert second_recorder.extract_calls == []
    assert downloads_after_first == ["https://example.invalid/ds.pdf"]


def test_a_cached_run_still_reports_the_url_it_came_from(tmp_path):
    cache = hunt.Cache(tmp_path)
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf("https://example.invalid/a.pdf")
    run_one(recorder, component(lcsc="C2977777"), cache=cache)
    second = hunt.execute(
        located(component(lcsc="C2977777")),
        Recorder().executor(),
        cache=cache,
        audit=hunt.AuditLog(tmp_path / "audit.jsonl"),
    )
    assert second.outcome == hunt.CACHED
    assert second.url == "https://example.invalid/a.pdf"


def test_force_download_bypasses_the_cache(tmp_path):
    """`--apply`'s hand-picked URL is newer than whatever is on disk."""
    cache = hunt.Cache(tmp_path)
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    run_one(recorder, component(lcsc="C2977777"), cache=cache)

    hand = Recorder()
    hand.bodies["https://example.invalid/hand.pdf"] = hunt.Download(
        ok=True, payload=b"%PDF-1.4 hand", content_type="application/pdf", status=200
    )
    outcome, _log = run_one(
        hand,
        component(lcsc="C2977777"),
        cache=cache,
        url="https://example.invalid/hand.pdf",
        force_download=True,
    )
    assert outcome.outcome == hunt.EXTRACTED
    assert hand.download_calls == ["https://example.invalid/hand.pdf"]


def test_two_boards_reaching_one_c_number_share_a_cache_entry(tmp_path):
    """The key is the identity, so the same part is one file, not one per board."""
    cache = hunt.Cache(tmp_path)
    assert cache.path_for({"lcsc": "C2977777", "mpn": "X"}) == cache.path_for(
        {"lcsc": "c2977777", "mpn": "Y"}
    )


# --------------------------------------------------------------------------
# §5 --offline
# --------------------------------------------------------------------------


def test_offline_makes_no_call_at_all(tmp_path, monkeypatch):
    """Proved with a seam that raises: a call would be a test error, not a quiet pass.

    And the outcome is `deferred-online`, not `needs-search`: this part's address
    is one the tool knows how to get (a C-number), so the honest report is "this
    run did not go online", not "a search engine is needed". The difference is
    what keeps the work order honest -- see :func:`hunt.plan_rows`.
    """

    def explode(*_args, **_kwargs):
        raise AssertionError("--offline must not touch the network")

    monkeypatch.setattr(hunt, "fetch_product_detail", explode)

    recorder = Recorder()
    recorder.download = explode  # type: ignore[method-assign]
    recorder.pdf_text = explode  # type: ignore[method-assign]
    outcome, log = run_one(
        recorder,
        component(lcsc="C2977777", mpn="ACME1"),
        cache=hunt.Cache(tmp_path),
        offline=True,
    )
    assert outcome.outcome == hunt.DEFERRED_ONLINE
    assert log.entries == []
    assert not list((tmp_path).glob("**/*.pdf"))


def test_an_offline_c_number_part_is_not_a_search_work_item(tmp_path):
    """`--offline` owes the reader advice it can stand behind.

    A part the tool could fetch itself must not appear in `hunt-plan.json`: a work
    order is read as "go run a search", and a search on a C-number part is turns
    spent to learn what one un-flagged re-run answers.
    """
    offline = Recorder()
    outcomes = [
        run_one(
            offline,
            component(lcsc="C2977777", mpn="ACME1"),
            cache=hunt.Cache(tmp_path),
            offline=True,
        )[0]
    ]
    rows, notes = hunt.plan_rows(outcomes)
    assert rows == []
    assert all("去掉 --offline" in note for note in notes) or notes == []


def test_offline_still_answers_from_a_warm_cache(tmp_path):
    """A cache is a local file: `--offline` forbids the network, not the disk."""
    cache = hunt.Cache(tmp_path)
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    run_one(recorder, component(lcsc="C2977777"), cache=cache)

    offline = Recorder()
    outcome, log = run_one(
        offline, component(lcsc="C2977777"), cache=cache, offline=True
    )
    assert outcome.outcome == hunt.CACHED
    assert offline.detail_calls == [] and offline.download_calls == []
    assert log.entries == []


# --------------------------------------------------------------------------
# §6 the privacy guards (the two that must throw)
# --------------------------------------------------------------------------


def test_the_generated_query_is_the_template_and_nothing_else():
    assert hunt.search_query("ACME1") == '"ACME1" datasheet pdf'


@pytest.mark.parametrize(
    "query",
    [
        '"ACME1" datasheet pdf U1',          # a designator appended
        '"ACME1" datasheet pdf board1',      # a board title appended
        '"ACME1" datasheet pdf VCC 3.3V',    # a net or a value appended
        '"ACME1" datasheet pdf bom',         # a BOM context word
        'datasheet pdf "ACME1"',             # same words, wrong shape — still refused
        '"ACME2" datasheet pdf',             # the MPN is not this part's
    ],
)
def test_a_query_that_carries_more_than_the_mpn_throws(query):
    with pytest.raises(hunt.IdentityLeak):
        hunt.assert_query_is_safe(query, "ACME1")


def test_a_query_with_no_mpn_throws():
    with pytest.raises(hunt.IdentityLeak):
        hunt.search_query("")
    with pytest.raises(hunt.IdentityLeak):
        hunt.search_query("   ")


def test_the_audit_request_must_be_the_identity_verbatim():
    assert hunt.assert_request_is_identity("C2977777", lcsc="C2977777") == "C2977777"
    assert hunt.assert_request_is_identity("ACME1", mpn="ACME1") == "ACME1"
    for bad in (
        "https://datasheet.lcsc.com/x.pdf",   # a URL is the one thing that must not be recorded
        "C2977…",                             # a redacted form proves nothing
        "C2977777 U1",                        # the designator rides along
        "",                                   # nothing is not an identity
    ):
        with pytest.raises(hunt.IdentityLeak):
            hunt.assert_request_is_identity(bad, lcsc="C2977777", mpn="ACME1")


def test_every_audit_line_carries_identity_and_a_digest(tmp_path):
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    _outcome, log = run_one(
        recorder, component(lcsc="C2977777"), cache=hunt.Cache(tmp_path),
        audit=hunt.AuditLog(tmp_path / "audit.jsonl"),
    )
    lines = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(lines) == 2
    for line in lines:
        assert set(line) == {"ts", "channel", "request", "http", "bytes", "sha256"}
        assert line["request"] == "C2977777"
    assert lines[1]["sha256"] and lines[1]["bytes"] > 0
    assert len(lines[1]["sha256"]) == 64


# --------------------------------------------------------------------------
# §7 the work order
# --------------------------------------------------------------------------


def test_the_plan_lists_only_parts_that_need_a_search():
    needs = hunt.Outcome(
        designator="U1", channel=hunt.CHANNEL_MPN_ONLY,
        identity={"lcsc": "", "mpn": "ACME1"}, outcome=hunt.NEEDS_SEARCH,
    )
    blank = hunt.Outcome(
        designator="U2", channel=hunt.CHANNEL_NO_IDENTITY,
        identity={"lcsc": "", "mpn": ""}, outcome=hunt.NO_IDENTITY,
    )
    got = hunt.Outcome(
        designator="U3", channel=hunt.CHANNEL_C_NUMBER,
        identity={"lcsc": "C2977777", "mpn": "ACME3"}, outcome=hunt.EXTRACTED,
    )
    rows, notes = hunt.plan_rows([needs, blank, got])
    assert rows == [
        {"designator": "U1", "mpn": "ACME1", "query": '"ACME1" datasheet pdf'}
    ]
    assert notes == []


def test_a_no_identity_part_is_counted_but_never_put_on_the_work_order():
    """It cannot be searched, so a row for it would be coverage that is not."""
    blank = hunt.Outcome(
        designator="U5", channel=hunt.CHANNEL_NO_IDENTITY,
        identity={"lcsc": "", "mpn": ""}, outcome=hunt.NO_IDENTITY,
    )
    rows, _notes = hunt.plan_rows([blank])
    assert rows == []


def test_counts_name_every_outcome_including_the_zeroes():
    counts = hunt.counts_of([])
    assert set(counts) == set(hunt.OUTCOMES)
    assert all(value == 0 for value in counts.values())


def test_counts_refuses_a_value_outside_the_vocabulary():
    bogus = hunt.Outcome(
        designator="U1", channel="", identity={}, outcome="made-up"
    )
    with pytest.raises(hunt.IdentityLeak):
        hunt.counts_of([bogus])


# --------------------------------------------------------------------------
# §8 the command, end to end (still no network: the seams are patched)
# --------------------------------------------------------------------------


def test_apply_replays_through_the_same_path_and_keeps_going(tmp_path, monkeypatch):
    """One endpoint, one pipeline: the `--apply` URL goes through download/extract.

    The board has parts with no URL of their own, and the answers file names one
    of them plus a designator the board does not have — the second must become an
    `unknown-designator` row while the first is extracted and a third part is
    still processed normally.
    """
    from boardwise.core.model import DesignModel

    model = DesignModel(
        components={
            "U1": Component(uid="a", designator="U1", lcsc_part="", mpn="ACME1"),
            "U2": Component(uid="b", designator="U2", lcsc_part="", mpn=""),
            "U3": Component(uid="c", designator="U3", lcsc_part="", mpn="ACME3"),
        }
    )
    monkeypatch.setattr(cli, "_load_model", lambda *a, **k: (model, None))
    recorder = Recorder()
    recorder.bodies["https://example.invalid/u1.pdf"] = hunt.Download(
        ok=True, payload=b"%PDF-1.4 u1", content_type="application/pdf", status=200
    )
    monkeypatch.setattr(cli, "_fetch_url", recorder.download)
    monkeypatch.setattr(cli, "_pdf_text", recorder.pdf_text)

    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            [
                {"designator": "U1", "url": "https://example.invalid/u1.pdf"},
                {"designator": "U404", "url": "https://example.invalid/nope.pdf"},
            ]
        ),
        encoding="utf-8",
    )
    code = cli.main(
        [
            "parts", "hunt",
            "--file", str(tmp_path / "board.epro2"),
            "--out", str(tmp_path / "out"),
            "--apply", str(answers),
            "--no-cache",
        ]
    )
    assert code == 0
    report = json.loads((tmp_path / "out" / "hunt-report.json").read_text(encoding="utf-8"))
    by_designator = {part["designator"]: part for part in report["parts"]}
    assert by_designator["U1"]["outcome"] == hunt.EXTRACTED
    assert by_designator["U1"]["url"] == "https://example.invalid/u1.pdf"
    assert by_designator["U1"]["facts"]["supply_pins"], "the same extractor ran"
    assert by_designator["U404"]["outcome"] == hunt.UNKNOWN_DESIGNATOR
    # …and the parts the file did not mention were processed normally.
    assert by_designator["U2"]["outcome"] == hunt.NO_IDENTITY
    assert by_designator["U3"]["outcome"] == hunt.NEEDS_SEARCH
    assert report["counts"][hunt.UNKNOWN_DESIGNATOR] == 1
    assert report["counts"][hunt.EXTRACTED] == 1


def test_apply_accepts_an_identity_locator(tmp_path, monkeypatch):
    from boardwise.core.model import DesignModel

    model = DesignModel(
        components={"U1": Component(uid="a", designator="U1", lcsc_part="C2977777")}
    )
    monkeypatch.setattr(cli, "_load_model", lambda *a, **k: (model, None))
    recorder = Recorder()
    recorder.bodies["https://example.invalid/by-lcsc.pdf"] = hunt.Download(
        ok=True, payload=b"%PDF-1.4 x", content_type="application/pdf", status=200
    )
    monkeypatch.setattr(cli, "_fetch_url", recorder.download)
    monkeypatch.setattr(cli, "_pdf_text", recorder.pdf_text)
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps([{"lcsc": "c2977777", "url": "https://example.invalid/by-lcsc.pdf"}]),
        encoding="utf-8",
    )
    code = cli.main(
        [
            "parts", "hunt", "--file", str(tmp_path / "b.epro2"),
            "--out", str(tmp_path / "out"), "--apply", str(answers), "--no-cache",
        ]
    )
    assert code == 0
    report = json.loads((tmp_path / "out" / "hunt-report.json").read_text(encoding="utf-8"))
    assert report["parts"][0]["outcome"] == hunt.EXTRACTED
    assert report["parts"][0]["url"] == "https://example.invalid/by-lcsc.pdf"


def test_an_answers_file_that_names_nothing_is_refused(tmp_path, monkeypatch):
    from boardwise.core.model import DesignModel

    monkeypatch.setattr(
        cli, "_load_model",
        lambda *a, **k: (DesignModel(components={}), None),
    )
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps([{"url": "https://example.invalid/x.pdf"}]), encoding="utf-8")
    code = cli.main(
        [
            "parts", "hunt", "--file", str(tmp_path / "b.epro2"),
            "--out", str(tmp_path / "out"), "--apply", str(answers), "--offline",
        ]
    )
    assert code == 2


def test_the_shelf_is_only_written_when_asked(tmp_path, monkeypatch, capsys):
    from boardwise.core.model import DesignModel
    from boardwise.core.parts import PartLibrary, save_parts

    model = DesignModel(
        components={"U1": Component(uid="a", designator="U1", lcsc_part="C2977777", mpn="ACME1")}
    )
    monkeypatch.setattr(cli, "_load_model", lambda *a, **k: (model, None))
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    monkeypatch.setattr(cli, "urllib_product_fetcher", recorder.fetch_detail, raising=False)
    monkeypatch.setattr(cli, "_fetch_url", recorder.download)
    monkeypatch.setattr(cli, "_pdf_text", recorder.pdf_text)

    shelf = tmp_path / "parts.json"
    save_parts(PartLibrary(parts=[]), shelf)
    before = shelf.read_bytes()

    # 1) no --shelf: the shelf is untouched
    code = cli.main(
        ["parts", "hunt", "--file", str(tmp_path / "b.epro2"),
         "--out", str(tmp_path / "out1"), "--no-cache"]
    )
    capsys.readouterr()
    assert code == 0
    assert shelf.read_bytes() == before

    # 2) --shelf: one candidate entry lands, gated
    code = cli.main(
        ["parts", "hunt", "--file", str(tmp_path / "b.epro2"),
         "--out", str(tmp_path / "out2"), "--no-cache", "--shelf", str(shelf)]
    )
    capsys.readouterr()
    assert code == 0
    library = load_parts(shelf)
    assert len(library.parts) == 1
    entry = library.parts[0]
    assert entry.facts_verified is False
    assert entry.facts is None, "the gate holds the claim back from every rule"
    assert entry.candidate_facts and entry.candidate_facts["supply_pins"]
    assert entry.lcsc == "C2977777"


def test_the_shelf_never_overwrites_facts_that_drive_rules(tmp_path, monkeypatch, capsys):
    """An unverified claim does not replace something a human vouched for."""
    from boardwise.core.model import DesignModel
    from boardwise.core.parts import PartEntry, PartLibrary, PartProvenance, save_parts

    model = DesignModel(
        components={"U1": Component(uid="a", designator="U1", lcsc_part="C2977777")}
    )
    monkeypatch.setattr(cli, "_load_model", lambda *a, **k: (model, None))
    recorder = Recorder()
    recorder.detail_answers["C2977777"] = detail_with_pdf()
    monkeypatch.setattr(cli, "urllib_product_fetcher", recorder.fetch_detail, raising=False)
    monkeypatch.setattr(cli, "_fetch_url", recorder.download)
    monkeypatch.setattr(cli, "_pdf_text", recorder.pdf_text)

    shelf = tmp_path / "parts.json"
    save_parts(
        PartLibrary(
            parts=[
                PartEntry(
                    key="ic.acme1",
                    lcsc="C2977777",
                    mpn="ACME1",
                    deviceUuid="dev-1",
                    libraryUuid="0819f05c4eef4c71ace90d822a990e87",
                    facts={
                        "supply_pins": [
                            {
                                "pins": ["1"],
                                "name": "VCC",
                                "provenance": "https://x/ds.pdf p.1",
                            }
                        ]
                    },
                    facts_verified=True,
                    provenance=PartProvenance(),
                )
            ]
        ),
        shelf,
    )
    before = shelf.read_bytes()
    code = cli.main(
        ["parts", "hunt", "--file", str(tmp_path / "b.epro2"),
         "--out", str(tmp_path / "out"), "--no-cache", "--shelf", str(shelf)]
    )
    capsys.readouterr()
    assert code == 0
    assert shelf.read_bytes() == before
