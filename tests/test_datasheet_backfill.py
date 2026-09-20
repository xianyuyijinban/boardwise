"""The datasheet-link backfill, driven by recorded responses (008b tail).

A board declares a datasheet **web page** (`Datasheet`), never a file, so every
harvested entry starts with an empty `datasheetPdfUrl`. The product page knows
it::

    GET https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C2977777
      -> {"code":200,"result":{ ..., "pdfUrl":"https://datasheet.lcsc.com/..." }}

Measured on the machine 2026-09-17. An unknown C-number is **not** an error
status there — the service answers `{"code":200,"result":null,"ok":true}` — so
"the catalog does not know this number" is one of the outcomes this file pins,
and it must be reported as that rather than as a malformed response.

No test touches a network: the fetcher is a required argument of `backfill()`,
which is what makes that structural rather than a promise.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from boardwise.core.parts import load_corrections, load_parts, save_parts
from boardwise.engines.catalog import (
    CatalogError,
    fetch_product_detail,
    urllib_product_fetcher,
)

ROOT = Path(__file__).resolve().parents[1]

PDF = "https://datasheet.lcsc.com/datasheet/pdf/a3b2ca2c.pdf?productCode=C2977777"


def _load_tool(name: str, relative: str):
    """`tools/` is not a package, so the module is loaded by path."""
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOL = _load_tool("backfill_tool", "tools/backfill_datasheets.py")


def recorded(payload: dict):
    """A fetcher that answers from a table of recorded responses."""

    calls: list[str] = []

    def fetch(product_code: str) -> dict:
        calls.append(product_code)
        return payload

    fetch.calls = calls  # type: ignore[attr-defined]
    return fetch


def failing(message: str = "connection reset"):
    """A transport failure of the kind `urllib_product_fetcher` raises."""

    def fetch(product_code: str) -> dict:
        raise CatalogError(message)

    return fetch


# --------------------------------------------------------------------------
# The reader
# --------------------------------------------------------------------------


def test_the_measured_response_shape_yields_the_pdf_link():
    detail = fetch_product_detail(
        recorded({"code": 200, "result": {"pdfUrl": PDF, "productModel": "CH340N"}}),
        "c2977777",
    )
    assert detail.pdf_url == PDF
    assert detail.answered is True and detail.code == 200 and detail.notes == []
    assert detail.lcsc == "C2977777"  # normalised, so the sidecar key is stable


def test_an_unknown_c_number_says_so_rather_than_blaming_the_response():
    """Measured: `{"code":200,"result":null,"ok":true}` for a number the catalog
    does not hold. Two entries in the real library answer this way."""
    detail = fetch_product_detail(
        recorded({"code": 200, "msg": None, "result": None, "ok": True}), "C9900097986"
    )
    assert detail.answered is False and detail.pdf_url == ""
    assert any("does not know this C-number" in note for note in detail.notes)


def test_a_product_without_a_pdf_is_answered_and_left_empty():
    detail = fetch_product_detail(recorded({"code": 200, "result": {"pdfUrl": None}}), "C160183")
    assert detail.answered is True
    assert detail.pdf_url == ""
    assert any("carries no `pdfUrl`" in note for note in detail.notes)


def test_a_response_that_is_not_a_product_is_reported():
    for payload, marker in (
        ({"code": 500, "result": None}, "code=500"),
        ({"code": 200, "ok": True}, "no `result` object"),
        ({"code": 200, "result": "nope"}, "no `result` object"),
    ):
        detail = fetch_product_detail(recorded(payload), "C1")
        assert detail.answered is False and detail.pdf_url == ""
        assert any(marker in note for note in detail.notes), payload


def test_a_transport_failure_is_one_outcome_and_leaves_a_blank():
    detail = fetch_product_detail(failing("timeout"), "C1")
    assert detail.answered is False and detail.pdf_url == ""
    assert any("request failed" in note for note in detail.notes)


def test_a_non_object_response_is_refused():
    detail = fetch_product_detail(lambda _code: ["not", "a", "mapping"], "C1")
    assert detail.pdf_url == ""
    assert any("not an object" in note for note in detail.notes)


def test_no_c_number_means_no_request():
    fetch = recorded({"code": 200, "result": {"pdfUrl": PDF}})
    detail = fetch_product_detail(fetch, "   ")
    assert fetch.calls == []
    assert detail.pdf_url == ""
    assert any("no C-number" in note for note in detail.notes)


def test_the_real_fetcher_is_the_only_thing_that_can_dial_out():
    """`urllib_product_fetcher` exists, and nothing here calls it."""
    assert callable(urllib_product_fetcher)
    with pytest.raises(TypeError):
        # `fetcher` has no default on purpose: an optional argument that reaches
        # a network is how a test ends up hitting one.
        TOOL.backfill(_library())  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


def _library(*parts):
    from boardwise.core.parts import PartLibrary

    return PartLibrary(parts=list(parts))


def test_every_bucket_is_reported_and_only_an_answer_writes():
    from tests.test_parts_library import entry

    library = _library(
        entry(key="a", lcsc="C1"),                                  # answered
        entry(key="b", lcsc="C2", datasheetPdfUrl="https://x/y.pdf"),  # already there
        entry(key="c", lcsc="C3"),                                  # answered, no PDF
        entry(key="d", lcsc=""),                                    # nothing to look up
    )

    def fetch(code: str):
        if code == "C1":
            return {"code": 200, "result": {"pdfUrl": PDF}}
        if code == "C3":
            return {"code": 200, "result": {"pdfUrl": ""}}
        raise CatalogError("boom")

    report = TOOL.backfill(library, fetcher=fetch)

    assert [lcsc for lcsc, _url in report.filled] == ["C1"]
    assert report.kept == ["C2"]
    assert [lcsc for lcsc, _reason in report.answered_without_pdf] == ["C3"]
    assert report.skipped and report.skipped[0][0] == "d"
    assert report.ok is True
    by_key = {p.key: p for p in library.parts}
    assert by_key["a"].datasheetPdfUrl == PDF
    assert by_key["b"].datasheetPdfUrl == "https://x/y.pdf"
    # A blank stays blank: an answered-but-empty and an unanswered part are both
    # facts, and neither is a licence to guess a URL.
    assert by_key["c"].datasheetPdfUrl == ""
    assert by_key["d"].datasheetPdfUrl == ""
    # Only the answered entry is recorded for the sidecar.
    assert set(report.records) == {"C1"}
    assert report.records["C1"].note.strip()


def test_a_fetch_failure_is_not_ok_and_changes_nothing():
    from tests.test_parts_library import entry

    library = _library(entry(key="a", lcsc="C1"))
    report = TOOL.backfill(library, fetcher=failing())
    assert report.ok is False
    assert report.failed == [("C1", "request failed: connection reset")]
    assert library.parts[0].datasheetPdfUrl == ""


def test_a_second_run_on_a_complete_library_does_nothing():
    from tests.test_parts_library import entry

    library = _library(entry(key="a", lcsc="C1"))
    first = TOOL.backfill(library, fetcher=recorded({"code": 200, "result": {"pdfUrl": PDF}}))
    assert len(first.filled) == 1
    fetch = recorded({"code": 200, "result": {"pdfUrl": PDF}})
    second = TOOL.backfill(library, fetcher=fetch)
    assert second.filled == [] and second.kept == ["C1"] and fetch.calls == []


def test_refresh_asks_again():
    from tests.test_parts_library import entry

    library = _library(entry(key="a", lcsc="C1", datasheetPdfUrl="https://old/x.pdf"))
    fetch = recorded({"code": 200, "result": {"pdfUrl": PDF}})
    report = TOOL.backfill(library, fetcher=fetch, refresh=True)
    assert fetch.calls == ["C1"]
    assert library.parts[0].datasheetPdfUrl == PDF
    assert report.filled == [("C1", PDF)]


def test_limit_bounds_the_lookups_and_leaves_the_rest_alone():
    from tests.test_parts_library import entry

    library = _library(*(entry(key=f"k{i}", lcsc=f"C{i}") for i in range(5)))
    report = TOOL.backfill(
        library, fetcher=recorded({"code": 200, "result": {"pdfUrl": PDF}}), limit=2
    )
    assert len(report.filled) == 2
    assert sum(1 for p in library.parts if p.datasheetPdfUrl) == 2


# --------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------


def _tiny_library(path: Path) -> None:
    from tests.test_parts_library import entry

    save_parts(_library(entry(key="ic.ch340n", lcsc="C2977777")), path)


def test_the_command_writes_the_library_and_the_sidecar(tmp_path, capsys):
    library_path, sidecar = tmp_path / "parts.json", tmp_path / "corrections.json"
    _tiny_library(library_path)
    code = TOOL._cli(
        ["--library", str(library_path), "--corrections-file", str(sidecar)],
        fetcher=recorded({"code": 200, "result": {"pdfUrl": PDF}}),
    )
    out = capsys.readouterr().out
    assert code == 0, out
    assert "filled 1" in out and "written:" in out
    assert load_parts(library_path).parts[0].datasheetPdfUrl == PDF
    assert load_corrections(sidecar).datasheet_for("C2977777").pdfUrl == PDF


def test_the_command_writes_nothing_when_everything_is_already_there(tmp_path, capsys):
    library_path, sidecar = tmp_path / "parts.json", tmp_path / "corrections.json"
    _tiny_library(library_path)
    fetch = recorded({"code": 200, "result": {"pdfUrl": PDF}})
    assert TOOL._cli(
        ["--library", str(library_path), "--corrections-file", str(sidecar)], fetcher=fetch
    ) == 0
    before = (library_path.read_text(encoding="utf-8"), sidecar.read_text(encoding="utf-8"))
    assert TOOL._cli(
        ["--library", str(library_path), "--corrections-file", str(sidecar)], fetcher=fetch
    ) == 0
    out = capsys.readouterr().out
    assert "nothing to write" in out
    # Byte-identical: a re-run is a no-op, not a rewrite.
    assert (library_path.read_text(encoding="utf-8"), sidecar.read_text(encoding="utf-8")) == before


def test_a_dry_run_writes_nothing(tmp_path):
    library_path = tmp_path / "parts.json"
    _tiny_library(library_path)
    before = library_path.read_text(encoding="utf-8")
    assert TOOL._cli(
        ["--library", str(library_path), "--dry-run"],
        fetcher=recorded({"code": 200, "result": {"pdfUrl": PDF}}),
    ) == 0
    assert library_path.read_text(encoding="utf-8") == before


def test_the_command_exits_one_when_a_part_could_not_be_asked(tmp_path, capsys):
    library_path = tmp_path / "parts.json"
    _tiny_library(library_path)
    code = TOOL._cli(["--library", str(library_path)], fetcher=failing())
    captured = capsys.readouterr()
    assert code == 1
    assert "could not ask C2977777" in captured.out
    assert load_parts(library_path).parts[0].datasheetPdfUrl == ""


def test_the_command_reports_an_empty_library_rather_than_writing_one(tmp_path, capsys):
    library_path = tmp_path / "absent.json"
    code = TOOL._cli(["--library", str(library_path)], fetcher=recorded({}))
    assert code == 2
    assert "holds no entries" in capsys.readouterr().err
    assert not library_path.exists()


def test_the_artifacts_are_json_and_hold_only_what_was_asked_for(tmp_path):
    """The sidecar is a data file: no timestamps, no run details, stable order."""
    library_path, sidecar = tmp_path / "parts.json", tmp_path / "corrections.json"
    _tiny_library(library_path)
    TOOL._cli(
        ["--library", str(library_path), "--corrections-file", str(sidecar)],
        fetcher=recorded({"code": 200, "result": {"pdfUrl": PDF}}),
    )
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["kind"] == "boardwise-part-corrections"
    assert "2026" not in sidecar.read_text(encoding="utf-8")
    # "curated" (task 011b) is a fixed section like the other two, present
    # even when empty - the sidecar's shape does not depend on the run.
    assert list(payload) == ["kind", "version", "note", "identity", "datasheets", "curated"]
