"""521: `parts hunt --apply-facts` — AI reads the page dump, the tool checks it.

The stage exists because of a measurement, not a preference. 520 got **0** facts
out of a real 46-part board's 15 PDFs, `UCC21520DWR`'s 52 clean pages included,
and widening the extractor's vocabulary from 11 supply names to 39 moved that
count from 0/15 to 0/15 — a real recommended-operating-conditions table is laid
out in *columns* (`VCCI VCCI Input supply voltage 3 18 V`) and a pin name may sit
on a line of its own, which is a shape no addition to a word list reaches.

So the reading is handed over and the tool does the half it can do honestly: it
checks the **evidence**, never the conclusion. Every test below is about that
gate. Where an assertion could be satisfied by a report the run did not deserve,
the test asserts the *absence* instead — no shelf entry, no sidecar file, no
download — because those are the things a gate that only printed a word would
still have done.

Zero network anywhere in this file. The cache is a directory of files that stage
one already wrote, which is exactly what makes `--offline` meaningful here: a
page dump is UTF-8 on disk, so reading a datasheet's facts needs no socket.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import Component, DesignModel
from boardwise.core.parts import load_parts
from boardwise.engines import hunt

#: The real corpus 520 left behind: `UCC21520DWR` (C601651), 52 pages of TI
#: datasheet with the page dump beside the PDF. Used as `--cache` — never
#: downloaded, so the end-to-end below has one outbound call at most and that one
#: is an assertion failure.
REAL_CACHE = Path(r"E:\boardwise\.tmp_cache_hunt520")

#: A four-page document shaped like the real thing, including the two features
#: that broke the regex extractor: a pin table row and a **column-laid-out**
#: range (`3 18 V`), plus a name on a line of its own.
PAGES = [
    "ACME9 Cover page\nRevision A",
    (
        "Pin Functions\n"
        "VCCI 3 P Primary-side supply voltage.\n"
        "VDDA 16 P Secondary-side power for driver A.\n"
        "VDDB 11 P Secondary-side power for driver B.\n"
        "VCCI 8 P Primary-side supply voltage. Internally shorted to pin 3.\n"
    ),
    "Ordering Information\nACME9DWR SOIC-16",
    (
        "6.3 Recommended Operating Conditions\n"
        "MIN MAX UNIT\n"
        "VCCI VCCI Input supply voltage 3 18 V\n"
        "VDDA,\n"
        "VDDB Driver output bias supply 9.2 25 V\n"
    ),
]
DOCUMENT = "\n".join(PAGES)


def write_cache(root: Path, *, lcsc: str = "C601651", pages: list[str] | None = None) -> Path:
    """A cache entry the way stage one writes it: `<key>/<key>.pages.json`."""
    pages = PAGES if pages is None else pages
    directory = root / lcsc
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{lcsc}.pages.json").write_text(json.dumps(pages), encoding="utf-8")
    (directory / f"{lcsc}.txt").write_text(
        "\n".join(f"<<<page {index}>>>\n{page}" for index, page in enumerate(pages, 1)),
        encoding="utf-8",
    )
    # The PDF magic, because a cache entry without one does not count as this
    # part's datasheet to stage one — and stage three reads what stage one left.
    (directory / f"{lcsc}.pdf").write_bytes(b"%PDF-1.4 stub")
    return root


def board(**components: Component) -> DesignModel:
    return DesignModel(components=dict(components))


def ucc21520() -> DesignModel:
    return board(
        U2=Component(
            uid="u2", designator="U2", lcsc_part="C601651", mpn="UCC21520DWR"
        )
    )


#: The true reading of pages 2 and 4 — pin 3/8 = VCCI, 16 = VDDA, 11 = VDDB,
#: recommended operating range 3–18 V. Written here by hand from the text above,
#: which is the point: this is what a reader returns, and what the gate judges.
GOOD_FACTS = {
    "supply_pins": [
        {
            "pins": ["3", "8"],
            "name": "VCCI",
            "mode": "operating",
            "v_operating": [3, 18],
            "provenance": "file:C601651.pdf, p.4",
        },
        {
            "pins": ["16"],
            "name": "VDDA",
            "mode": "operating",
            "provenance": "file:C601651.pdf, p.2",
        },
        {
            "pins": ["11"],
            "name": "VDDB",
            "mode": "operating",
            "provenance": "file:C601651.pdf, p.2",
        },
    ]
}

GOOD_QUOTES = [
    {"page": 2, "text": "VCCI 3 P Primary-side supply voltage."},
    {"page": 4, "text": "VCCI VCCI Input supply voltage 3 18 V"},
]


def answers(path: Path, records: list[dict]) -> Path:
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_hunt(
    tmp_path: Path,
    *,
    claims: list[dict],
    model: DesignModel | None = None,
    cache_root: Path | None = None,
    monkeypatch=None,
    shelf: Path | None = None,
    out: str = "out",
    extra: list[str] | None = None,
) -> tuple[int, Path]:
    """Run the command offline and hand back ``(exit code, report path)``."""
    if monkeypatch is not None:
        monkeypatch.setattr(
            cli, "_load_model", lambda *a, **k: (model or ucc21520(), None)
        )

        def refuse(*_a, **_k):  # pragma: no cover - a call here is the failure
            raise AssertionError("--apply-facts must not touch the network")

        monkeypatch.setattr(cli, "_fetch_url", refuse)
        monkeypatch.setattr(cli, "urllib_product_fetcher", refuse, raising=False)
        monkeypatch.setattr(cli, "_pdf_text", refuse)

    out_dir = tmp_path / out
    argv = [
        "parts", "hunt",
        "--file", str(tmp_path / "board.epro2"),
        "--out", str(out_dir),
        "--offline",
        "--cache", str(cache_root if cache_root is not None else write_cache(tmp_path / "cache")),
        "--apply-facts", str(answers(tmp_path / f"{out}.answers.json", claims)),
    ]
    if shelf is not None:
        argv += ["--shelf", str(shelf)]
    argv += extra or []
    return cli.main(argv), out_dir / "hunt-report.json"


def report_rows(report_path: Path) -> dict[str, dict]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {part["designator"]: part for part in report["parts"]}


def gates_of(row: dict) -> set[str]:
    return {refusal["gate"] for refusal in row.get("refusals") or []}


# --------------------------------------------------------------------------
# §1 the gate itself, as a pure function — the four refusals one at a time
# --------------------------------------------------------------------------


def test_a_verbatim_quote_on_its_page_is_accepted():
    facts, refusals = hunt.check_claim(
        facts=GOOD_FACTS, quotes=GOOD_QUOTES, pages=PAGES, document=DOCUMENT
    )
    assert refusals == []
    assert facts["supply_pins"][0]["v_operating"] == [3.0, 18.0]


def test_one_changed_character_in_a_quote_is_quote_not_found():
    """**The batch's whole reason to exist.**

    A hallucinated pin table is one keystroke away from a real one: `3 18 V`
    becomes `3 19 V`, the sentence still reads like a datasheet, and nothing but
    a verbatim comparison can tell the two apart. This is the unit-level half of
    that guarantee; the command-level half is
    :func:`test_a_quote_with_one_changed_character_is_refused_and_nothing_lands`.
    """
    almost = [dict(quote) for quote in GOOD_QUOTES]
    almost[1]["text"] = "VCCI VCCI Input supply voltage 3 19 V"
    _facts, refusals = hunt.check_claim(
        facts=GOOD_FACTS, quotes=almost, pages=PAGES, document=DOCUMENT
    )
    assert [item["gate"] for item in refusals] == [hunt.QUOTE_NOT_FOUND]


def test_a_quote_that_differs_only_in_whitespace_is_still_the_same_sentence():
    """Folding is the **only** relaxation, and it is not a fudge factor.

    A PDF's text layer wraps a cell across two lines, so a quote that crosses the
    wrap is still that sentence on that page. Everything else — case, digits,
    units — is compared exactly, which is what keeps this from becoming the
    fuzziness that lets a wrong table through.
    """
    wrapped = [{"page": 4, "text": "VCCI  VCCI Input   supply voltage\n3 18 V"}]
    _facts, refusals = hunt.check_claim(
        facts={"nc_pins": {"pins": ["3"], "provenance": "file:x p.4"}},
        quotes=wrapped,
        pages=PAGES,
        document=DOCUMENT,
    )
    assert refusals == []


def test_a_cited_page_past_the_end_is_page_out_of_range():
    quotes = [{"page": 99, "text": "VCCI 3 P Primary-side supply voltage."}]
    _facts, refusals = hunt.check_claim(
        facts=GOOD_FACTS, quotes=quotes, pages=PAGES, document=DOCUMENT
    )
    assert [item["gate"] for item in refusals] == [hunt.PAGE_OUT_OF_RANGE]


def test_a_pin_the_document_never_prints_is_pin_not_in_document():
    """Occurrence only — the tool does not pretend to know what a pin does.

    A 16-pin package claiming pin 77 is the cheap hallucination a form-feeding
    model makes, and "77 appears nowhere in this document" is a statement a regex
    can make honestly.
    """
    facts = {
        "supply_pins": [
            {
                "pins": ["3", "77"],
                "name": "VCCI",
                "provenance": "file:C601651.pdf, p.2",
            }
        ]
    }
    _facts, refusals = hunt.check_claim(
        facts=facts, quotes=GOOD_QUOTES, pages=PAGES, document=DOCUMENT
    )
    assert [item["gate"] for item in refusals] == [hunt.PIN_NOT_IN_DOCUMENT]


def test_a_pin_inside_a_longer_token_does_not_count():
    """`3` must not be found inside `VDDA3` or `30`, or every claim passes.

    The boundary is "not adjacent to a letter or a digit", so `VDDA-3` *does*
    match — a hyphen is a separator in every table this reads (`3-18 V`), and a
    gate that treated it as part of the token would refuse half the real corpus.
    What it does refuse is the failure that actually happens: a pin number glued
    to a word, or a digit inside a longer number.
    """
    assert hunt.pin_appears("3", "VCCI 3 P Primary-side") is True
    assert hunt.pin_appears("3", "VDDA3 supply") is False
    assert hunt.pin_appears("3", "pin 30 of 31") is False
    assert hunt.pin_appears("3", "VDD 30V") is False
    # A separator, not a token character.
    assert hunt.pin_appears("3", "VDDA-3 supply") is True


def test_an_unknown_key_in_facts_is_a_schema_refusal():
    """The schema is `core.parts`'s, not a second copy — so nothing can be
    accepted here that the shelf would then refuse to load."""
    facts = {
        "supply_pins": [
            {
                "pins": ["3"],
                "name": "VCCI",
                "voltage": [3, 18],
                "provenance": "file:C601651.pdf, p.2",
            }
        ]
    }
    body, refusals = hunt.check_claim(
        facts=facts, quotes=GOOD_QUOTES, pages=PAGES, document=DOCUMENT
    )
    assert body == {}
    assert [item["gate"] for item in refusals] == [hunt.SCHEMA]


def test_a_claim_with_no_quotes_is_refused():
    _facts, refusals = hunt.check_claim(
        facts=GOOD_FACTS, quotes=[], pages=PAGES, document=DOCUMENT
    )
    assert [item["gate"] for item in refusals] == [hunt.QUOTE_NOT_FOUND]


def test_pins_are_collected_from_every_fact_kind_that_carries_one():
    """The pin gate reads the **validated** shape, so a claim cannot pass it by
    hiding a pin in a kind this module forgot to look at.

    `required_caps`, `must_connect`, `pull_required` and `nc_pins` all name pins
    at the top level; a gate that only walked `supply_pins` would let an invented
    bypass capacitor pin through, which is exactly the claim a reader would
    catch last.
    """
    facts = {
        "supply_pins": [
            {"pins": ["3"], "name": "VCCI", "provenance": "file:x.pdf, p.2"}
        ],
        "required_caps": [
            {"pin": "42", "value": "1nF", "provenance": "file:x.pdf, p.2"}
        ],
        "must_connect": [
            {"pin": "43", "to": "GND", "provenance": "file:x.pdf, p.2"}
        ],
        "pull_required": [
            {
                "pin": "44",
                "to": "VCCI",
                "expected_value": "10k",
                "provenance": "file:x.pdf, p.2",
            }
        ],
        "nc_pins": {"pins": ["45"], "provenance": "file:x.pdf, p.2"},
    }
    _body, refusals = hunt.check_claim(
        facts=facts, quotes=GOOD_QUOTES, pages=PAGES, document=DOCUMENT
    )
    refused = {item["detail"].split("'")[1] for item in refusals}
    assert refused == {"42", "43", "44", "45"}, (
        "every kind's pins are checked, and the real pin 3 is not among them"
    )


# --------------------------------------------------------------------------
# §2 the command: what lands, and what must not
# --------------------------------------------------------------------------


def test_an_accepted_claim_lands_as_a_candidate_and_the_shelf_stays_closed(
    tmp_path, monkeypatch, capsys
):
    from boardwise.core.parts import PartLibrary, save_parts

    shelf = tmp_path / "parts.json"
    save_parts(PartLibrary(parts=[]), shelf)
    code, report_path = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": GOOD_FACTS, "quotes": GOOD_QUOTES}],
        monkeypatch=monkeypatch,
        shelf=shelf,
    )
    capsys.readouterr()
    assert code == 0
    row = report_rows(report_path)["U2"]
    assert row["outcome"] == hunt.FACTS_ACCEPTED
    assert row["facts"]["supply_pins"][0]["pins"] == ["3", "8"]

    library = load_parts(shelf)
    assert len(library.parts) == 1
    entry = library.parts[0]
    # The gate: accepted evidence is still not a verified fact.
    assert entry.facts_verified is False
    assert entry.facts is None, "a rule must not be able to read this"
    assert entry.candidate_facts["supply_pins"]
    assert entry.provenance.kind == "hunt-read", (
        "a reading is not an extractor's guess; provenance says which produced it"
    )


def test_a_quote_with_one_changed_character_is_refused_and_nothing_lands(
    tmp_path, monkeypatch, capsys
):
    """**The test this batch exists for.**

    One digit in a quote — `3 18 V` → `3 19 V` — and the row must be
    `facts-rejected` / `quote-not-found`, with a shelf that is **byte-identical**
    to what it was and no `<designator>.candidate.json` anywhere. Asserting the
    report's word alone would pass on an implementation that printed the right
    outcome after having already written the file.
    """
    from boardwise.core.parts import PartLibrary, save_parts

    shelf = tmp_path / "parts.json"
    save_parts(PartLibrary(parts=[]), shelf)
    before = shelf.read_bytes()

    tampered = [dict(quote) for quote in GOOD_QUOTES]
    tampered[1]["text"] = "VCCI VCCI Input supply voltage 3 19 V"
    code, report_path = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": GOOD_FACTS, "quotes": tampered}],
        monkeypatch=monkeypatch,
        shelf=shelf,
    )
    capsys.readouterr()
    assert code == 0
    row = report_rows(report_path)["U2"]
    assert row["outcome"] == hunt.FACTS_REJECTED
    assert gates_of(row) == {hunt.QUOTE_NOT_FOUND}
    assert shelf.read_bytes() == before, "拒收的 claim 一个字都不许落架"
    assert not (tmp_path / "out" / "candidates" / "U2.candidate.json").is_file(), (
        "the sidecar is the file someone hands to `parts add --facts`; a refused "
        "claim that wrote one would walk past the gate that just refused it"
    )


def test_a_page_past_the_end_is_refused_by_the_command(tmp_path, monkeypatch, capsys):
    code, report_path = run_hunt(
        tmp_path,
        claims=[
            {
                "designator": "U2",
                "facts": GOOD_FACTS,
                # The sentence is real; the page it is cited at is not in the
                # document, and a citation past the last page points at evidence
                # that does not exist.
                "quotes": [{"page": 99, "text": GOOD_QUOTES[0]["text"]}],
            }
        ],
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    assert code == 0
    row = report_rows(report_path)["U2"]
    assert row["outcome"] == hunt.FACTS_REJECTED
    assert hunt.PAGE_OUT_OF_RANGE in gates_of(row)


def test_a_pin_the_document_never_prints_is_refused_by_the_command(
    tmp_path, monkeypatch, capsys
):
    facts = {
        "supply_pins": [
            {"pins": ["77"], "name": "VDDX", "provenance": "file:C601651.pdf, p.2"}
        ]
    }
    code, report_path = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": facts, "quotes": GOOD_QUOTES}],
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    assert code == 0
    row = report_rows(report_path)["U2"]
    assert row["outcome"] == hunt.FACTS_REJECTED
    assert hunt.PIN_NOT_IN_DOCUMENT in gates_of(row)


def test_an_unknown_designator_is_its_own_row_and_the_rest_still_run(
    tmp_path, monkeypatch, capsys
):
    code, report_path = run_hunt(
        tmp_path,
        claims=[
            {"designator": "U2", "facts": GOOD_FACTS, "quotes": GOOD_QUOTES},
            {"designator": "U404", "facts": GOOD_FACTS, "quotes": GOOD_QUOTES},
        ],
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    assert code == 0
    rows = report_rows(report_path)
    assert rows["U2"]["outcome"] == hunt.FACTS_ACCEPTED
    assert rows["U404"]["outcome"] == hunt.UNKNOWN_DESIGNATOR


def test_an_unknown_key_in_the_answer_file_is_a_file_error(tmp_path, monkeypatch, capsys):
    """A closed shape, refused at the door rather than per claim.

    A misspelt `quote` (for `quotes`) that was silently ignored would turn a
    well-evidenced claim into a refused one for a reason its author cannot see —
    and a mis-typed key is a property of the whole file, not of one record.
    """
    monkeypatch.setattr(cli, "_load_model", lambda *a, **k: (ucc21520(), None))
    path = answers(
        tmp_path / "bad.json",
        [{"designator": "U2", "facts": GOOD_FACTS, "quote": GOOD_QUOTES}],
    )
    code = cli.main(
        [
            "parts", "hunt", "--file", str(tmp_path / "b.epro2"),
            "--out", str(tmp_path / "out"), "--offline",
            "--cache", str(write_cache(tmp_path / "cache")),
            "--apply-facts", str(path),
        ]
    )
    capsys.readouterr()
    assert code == 2
    assert not (tmp_path / "out" / "hunt-report.json").is_file()


def test_a_part_with_no_page_dump_yet_is_refused_with_say_so(tmp_path, monkeypatch, capsys):
    """`no-document` is not `quote-not-found`: nothing was judged.

    A reader may be quoting a datasheet this machine has never seen, and telling
    them their quote is wrong would send them to audit a sentence that is fine.
    """
    code, report_path = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": GOOD_FACTS, "quotes": GOOD_QUOTES}],
        monkeypatch=monkeypatch,
        cache_root=tmp_path / "empty-cache",
    )
    capsys.readouterr()
    assert code == 0
    row = report_rows(report_path)["U2"]
    assert row["outcome"] == hunt.FACTS_REJECTED
    assert gates_of(row) == {hunt.NO_DOCUMENT}


def test_two_claims_for_one_part_are_both_refused(tmp_path, monkeypatch, capsys):
    """The second would silently win, and its author would believe both ran."""
    code, report_path = run_hunt(
        tmp_path,
        claims=[
            {"designator": "U2", "facts": GOOD_FACTS, "quotes": GOOD_QUOTES},
            {"designator": "U2", "facts": GOOD_FACTS, "quotes": GOOD_QUOTES},
        ],
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    assert code == 0
    rows = report_rows(report_path)
    assert rows["U2"]["outcome"] == hunt.FACTS_REJECTED
    assert hunt.DUPLICATE_CLAIM in gates_of(rows["U2"])


def test_offline_apply_facts_makes_no_call_at_all(tmp_path, monkeypatch, capsys):
    """**The confidential-board case.**

    Everything stage three needs is a UTF-8 page dump on disk, so `--offline` and
    `--apply-facts` is a usable combination — and the run_hunt helper has already
    armed `_fetch_url` / `urllib_product_fetcher` / `_pdf_text` to raise on any
    call, so a green here is the counterfactual, not the absence of a symptom.
    """
    code, report_path = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": GOOD_FACTS, "quotes": GOOD_QUOTES}],
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    assert code == 0
    assert report_rows(report_path)["U2"]["outcome"] == hunt.FACTS_ACCEPTED
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["outbound"] == 0
    audit = (tmp_path / "out" / "hunt-audit.jsonl").read_text(encoding="utf-8")
    assert audit.strip() == "", "审计文件必须是空的：一次外呼都没有"


def test_the_markdown_report_names_the_gate_that_refused(tmp_path, monkeypatch, capsys):
    """"0 accepted" is not actionable; "quote-not-found on U2" is."""
    tampered = [dict(quote) for quote in GOOD_QUOTES]
    tampered[1]["text"] = "VCCI VCCI Input supply voltage 3 19 V"
    code, _report = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": GOOD_FACTS, "quotes": tampered}],
        monkeypatch=monkeypatch,
    )
    capsys.readouterr()
    assert code == 0
    markdown = (tmp_path / "out" / "hunt-report.md").read_text(encoding="utf-8")
    assert "被拒收" in markdown
    assert "quote-not-found" in markdown


# --------------------------------------------------------------------------
# §3 the real board, end to end, on 520's own leftovers (zero outbound)
# --------------------------------------------------------------------------

#: The true facts of `UCC21520DWR`, read off the 52-page TI text 520 downloaded:
#: VCCI on pins 3 and 8, VDDA on 16, VDDB on 11, and a recommended operating
#: range of 3–18 V. Quotes copied verbatim from pages 4 and 5.
REAL_QUOTES = [
    {"page": 4, "text": "VCCI 3 P Primary-side supply voltage."},
    {"page": 4, "text": "VCCI 8 P Primary-side supply voltage. This pin is internally shorted to pin 3."},
    {"page": 4, "text": "VDDA 16 P Secondary-side power for driver A."},
    {"page": 4, "text": "VDDB 11 P Secondary-side power for driver B."},
    {"page": 5, "text": "VCCI VCCI Input supply voltage 3 18 V"},
]

REAL_FACTS = {
    "supply_pins": [
        {
            "pins": ["3", "8"],
            "name": "VCCI",
            "mode": "operating",
            "v_operating": [3, 18],
            "provenance": "file:C601651.pdf, p.5",
        },
        {
            "pins": ["16"],
            "name": "VDDA",
            "mode": "operating",
            "v_operating": [6.5, 25],
            "provenance": "file:C601651.pdf, p.5",
        },
        {
            "pins": ["11"],
            "name": "VDDB",
            "mode": "operating",
            "v_operating": [6.5, 25],
            "provenance": "file:C601651.pdf, p.5",
        },
    ]
}


@pytest.mark.skipif(
    not (REAL_CACHE / "C601651" / "C601651.pages.json").is_file(),
    reason="520's cached UCC21520DWR corpus is not on this machine",
)
def test_the_real_gate_driver_datasheet_is_read_and_accepted(tmp_path, monkeypatch, capsys):
    code, report_path = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": REAL_FACTS, "quotes": REAL_QUOTES}],
        monkeypatch=monkeypatch,
        cache_root=REAL_CACHE,
    )
    capsys.readouterr()
    assert code == 0
    row = report_rows(report_path)["U2"]
    assert row["outcome"] == hunt.FACTS_ACCEPTED, row["notes"]
    assert row["facts"]["supply_pins"][0] == {
        "pins": ["3", "8"],
        "name": "VCCI",
        "mode": "operating",
        "v_operating": [3.0, 18.0],
        "provenance": "file:C601651.pdf, p.5",
    }
    assert len(row["quotes"]) == 5


@pytest.mark.skipif(
    not (REAL_CACHE / "C601651" / "C601651.pages.json").is_file(),
    reason="520's cached UCC21520DWR corpus is not on this machine",
)
def test_the_real_gate_driver_with_one_character_changed_is_refused(
    tmp_path, monkeypatch, capsys
):
    """Same board, same reading, one digit wrong: `3 18 V` → `3 19 V`.

    This is the reading the whole batch is built to survive — a plausible pin
    table with one number quietly off — and it must be refused while the true one
    a few lines up is accepted.
    """
    tampered = [dict(quote) for quote in REAL_QUOTES]
    tampered[-1]["text"] = "VCCI VCCI Input supply voltage 3 19 V"
    code, report_path = run_hunt(
        tmp_path,
        claims=[{"designator": "U2", "facts": REAL_FACTS, "quotes": tampered}],
        monkeypatch=monkeypatch,
        cache_root=REAL_CACHE,
    )
    capsys.readouterr()
    assert code == 0
    row = report_rows(report_path)["U2"]
    assert row["outcome"] == hunt.FACTS_REJECTED
    assert gates_of(row) == {hunt.QUOTE_NOT_FOUND}
    assert row["facts"] == {}


# --------------------------------------------------------------------------
# §4 the vocabulary stays closed
# --------------------------------------------------------------------------


def test_the_two_new_outcomes_are_in_the_vocabulary_and_counted():
    counts = hunt.counts_of([])
    assert hunt.FACTS_ACCEPTED in counts and hunt.FACTS_REJECTED in counts
    assert set(hunt.OUTCOME_MEANING) == set(hunt.OUTCOMES)


def test_a_refused_claim_carries_no_facts_into_its_row():
    """The report's `facts` field is what a reader copies; a folded-in claim is
    a refusal that landed."""
    located_row = hunt.Located(
        designator="U2", channel=hunt.CHANNEL_C_NUMBER,
        identity={"lcsc": "C601651", "mpn": "UCC21520DWR"},
    )
    claim = hunt.Claim(locators={"designator": "U2"})
    claim.refuse(hunt.QUOTE_NOT_FOUND, "第 5 页里找不到引文")
    claim.facts = dict(GOOD_FACTS)
    outcome = hunt.claim_outcome(claim, located_row)
    assert outcome.outcome == hunt.FACTS_REJECTED
    assert outcome.facts == {}
    assert outcome.read_by_someone is False
