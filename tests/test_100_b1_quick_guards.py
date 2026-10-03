"""100 / B1 quick guards: six offline defects, one red test each.

Source: the external audit (repo root ``.tmp_bug_report.md``, gitignored) and the
task book ``tasks/100-b1-quick-guards.md``. Every test below was written against
the revision that shipped the defect and was **red** there; each asserts the
defect's own payload — the audit's reproduction — rather than the shape of the
fix, so a different-but-correct fix still passes.

Sections, in the audit's numbering:

* **3** — ``param-rc-cutoff`` divided by zero on a 0-valued capacitor, which took
  the whole rule down (`checkup` swallowed it, ``review-eval`` aborted).
* **9** — ``patchpin.same_point`` raised ``TypeError`` on a missing or
  non-numeric coordinate instead of answering "not the same point".
* **10** — the ``.enet`` reader turned an explicit JSON ``null`` into the literal
  string ``"None"``.
* **15** — two ``__all__`` lists promised names that do not exist, so a star
  import raised ``AttributeError``.
* **16** — the SVG preview clipped its own caption: a fixed 90-unit strip for a
  caption that can be 8 lines. This is the batch's one **intended** output change.
* **19** — a UTF-8 BOM was never stripped, so a stream's first record was counted
  malformed and dropped with no error. Five decode sites, one test each: the
  ``.epro2`` archive stream (strict and fallback), both branches of the eprj3 page
  reader, and the ``.enet`` reader. The audit named four; the fifth is the
  ``epru_stream`` fallback — the same decode, one line below, where a stream that
  is BOM'd *and* damaged lost the record a second time.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import pytest

from boardwise.core.annotations import AnnotationSet
from boardwise.core.geometry import ParseStats
from boardwise.core.layoutplan import LayoutPlan
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.core.parts import PartLibrary
from boardwise.engines import patchpin, svgpreview
from boardwise.engines.review_eval import evaluate_annotations
from boardwise.parsers.enet import enet_dict_to_model, parse_enet
from boardwise.parsers.eprj3 import load_eprj3_text
from boardwise.parsers.epru_stream import iter_epru_records, load_epru_text
from boardwise.rules.params import RcCutoff

SVG = "{http://www.w3.org/2000/svg}"

#: The three bytes a UTF-8 BOM is made of, as a file on disk writes them.
BOM = b"\xef\xbb\xbf"


# ==========================================================================
# 3. param-rc-cutoff: a 0-valued capacitor is not a capacitor
# ==========================================================================


def _rc_model(res_value: str = "10k", cap_value: str = "100nF") -> DesignModel:
    """One RC low-pass on ``MID``: R1 from ``SIG``, C1 from ``MID`` to ``GND``."""
    model = DesignModel()
    model.components["R1"] = Component(
        uid="r1", designator="R1", value=res_value,
        pins=[Pin("1", "A", "SIG"), Pin("2", "B", "MID")])
    model.components["C1"] = Component(
        uid="c1", designator="C1", value=cap_value,
        pins=[Pin("1", "A", "MID"), Pin("2", "B", "GND")])
    model.nets = {
        "SIG": Net("SIG", [("R1", "1")]),
        "MID": Net("MID", [("R1", "2"), ("C1", "1")]),
        "GND": Net("GND", [("C1", "2")]),
    }
    return model


def _rc_rule() -> RcCutoff:
    return RcCutoff(library=PartLibrary(parts=[]))


def test_a_zero_valued_capacitor_is_skipped_like_a_zero_ohm_resistor():
    """``0uF`` parses to ``0.0``, which is not a capacitance to divide by.

    The resistor inventory has had its ``ohms > 0`` guard since the rule was
    written; the capacitor inventory only checked ``is not None``, so ``C1 = 0uF``
    entered the pair list and ``fc = 1 / (2*pi*R*0)`` raised ``ZeroDivisionError``
    inside the rule. A part whose value states no capacitance is skipped, exactly
    as a ``0Ω`` resistor is: the pair is not measured, and the survey row is not
    claimed either way.
    """
    assert _rc_model("10k", "0uF").components["C1"].value == "0uF"
    outcomes = _rc_rule().outcomes(_rc_model("10k", "0uF"))
    assert not [item for item in outcomes if "fc =" in item.message]
    # The same board with a real capacitance is measured: the guard must skip the
    # zero and only the zero, not silently stop measuring RC pairs.
    measured = _rc_rule().outcomes(_rc_model("10k", "100nF"))
    assert [item for item in measured if "fc =" in item.message]


def test_review_eval_does_not_abort_on_a_zero_valued_capacitor():
    """``review-eval`` runs the rules with no try/except, unlike ``checkup``.

    ``checkup`` files the ``ZeroDivisionError`` into ``rules_errored`` and loses
    the rule's conclusions silently; the harness path (``evaluate_annotations``)
    has no such collector, so one bad capacitor aborted the whole run.
    """
    board = AnnotationSet(board="synthetic", source="(synthetic)")
    evaluation = evaluate_annotations(board, _rc_model("10k", "0uF"), [_rc_rule()])
    row = next(item for item in evaluation.metrics if item.rule_id == "param-rc-cutoff")
    assert row.violations == 0


# ==========================================================================
# 9. patchpin.same_point: a coordinate the host did not report is not a point
# ==========================================================================


def test_a_coordinate_that_is_missing_is_not_the_same_point():
    """``_number`` answers ``None`` per element, so the *tuple* is never ``None``.

    ``same_point`` guarded the tuple and subtracted the elements, which raised
    ``TypeError`` for ``(None, 200.0)``. "No coordinate" means "not this point" —
    the same tolerance the sibling reader
    (:func:`boardwise.engines.addcomponent.component_origins`) applies when it
    skips a component with no ``X``/``Y``.
    """
    at = (200.0, 200.0)
    assert patchpin.same_point((None, 200.0), at) is False
    assert patchpin.same_point(at, (200.0, None)) is False
    assert patchpin.same_point((None, None), (None, None)) is False
    assert patchpin.same_point(None, at) is False


def test_a_netflag_without_coordinates_is_refused_not_a_traceback():
    """The audit's payload, at the reader the refusal comes from.

    ``{"ComponentType": "netflag", "Net": "GND"}`` has no ``X``/``Y`` at all, and
    a **string** coordinate is the same shape to ``_number``. Both used to escape
    ``attachment_on_pin`` as a raw ``TypeError`` — the CLI call sites catch only
    ``AttachmentRefused`` — instead of the actionable refusal ("nothing
    recognisable attaches"). A part with coordinates is unaffected; the flag is
    then found, which is the attachment this slice names and refuses.
    """
    pin_at = (200.0, 200.0)
    without = {"components": [{"state": {"ComponentType": "netflag", "Net": "GND"}}]}
    with pytest.raises(patchpin.AttachmentRefused) as missing:
        patchpin.attachment_on_pin(without, pin_at)
    assert "nothing recognisable attaches (200, 200)" in missing.value.detail

    as_text = {"components": [
        {"state": {"ComponentType": "netflag", "Net": "GND", "X": "200", "Y": "200"}},
    ]}
    with pytest.raises(patchpin.AttachmentRefused) as stringly:
        patchpin.attachment_on_pin(as_text, pin_at)
    assert "nothing recognisable attaches (200, 200)" in stringly.value.detail

    real = {"components": [
        {"state": {"ComponentType": "netflag", "Net": "GND", "X": 200.0, "Y": 200.0}},
    ]}
    assert patchpin.flag_on_pin(real, pin_at) is True
    assert patchpin.flag_on_pin(without, pin_at) is False


# ==========================================================================
# 10. the .enet reader: an explicit JSON null is not the string "None"
# ==========================================================================


def test_an_explicit_null_attribute_reads_as_empty_not_as_none():
    """``dict.get(key, default)`` only defaults a **missing** key.

    A key present with value ``null`` came through as ``None`` and was then
    stringified: the pin became ``('None', 'None', 'GND')`` — a phantom pin that
    joins every downstream netlist comparison — and ``value.strip()`` raised
    ``AttributeError``. The sibling ``epro2_model._clean`` maps ``None -> ""``;
    ``enet.py`` already documents that ``net`` is handled this way, so the
    component's own fields now are too.
    """
    model = enet_dict_to_model({
        "components": {"c-r1": {
            "props": {"Designator": "R1", "Value": None, "Footprint": None},
            "pinInfoMap": {"1": {"number": None, "name": None, "net": "GND"}},
        }},
    })
    component = model.components["R1"]
    assert component.value == ""
    assert component.footprint == ""
    assert component.value.strip() == ""
    assert [(pin.number, pin.name, pin.net) for pin in component.pins] == [
        ("", "", "GND")]
    assert "None" not in [pin.number for pin in component.pins]


def test_a_pin_without_a_null_keeps_the_key_and_the_string_it_had():
    """Only ``None`` changes: a missing key still falls back, a value still stringifies."""
    model = enet_dict_to_model({
        "components": {"c-r2": {
            "props": {"Designator": "R2", "Value": "10k", "Footprint": "R0402"},
            "pinInfoMap": {
                "1": {"number": 1, "name": "A", "net": "GND"},
                "2": {"name": "B"},
            },
        }},
    })
    component = model.components["R2"]
    assert (component.value, component.footprint) == ("10k", "R0402")
    assert [(pin.number, pin.name) for pin in component.pins] == [("1", "A"), ("2", "B")]


# ==========================================================================
# 15. __all__: a promise that does not resolve
# ==========================================================================


@pytest.mark.parametrize(
    "module_name",
    ["boardwise.core.presentationspec", "boardwise.engines.grammar.ldo"],
)
def test_every_promised_name_resolves(module_name):
    """``__all__`` is a promise; two of them named a constant that was renamed.

    ``FLOW_EDGE_KEYS`` only exists as ``_FLOW_EDGE_KEYS``, and ``CORE_ROLES`` as
    ``CORE_PIN_ROLES`` — both stale renames left by a refactor the promises did
    not follow. ``from module import *`` raised
    ``AttributeError: ... has no attribute 'FLOW_EDGE_KEYS'``.
    """
    module = __import__(module_name, fromlist=["__all__"])
    missing = [name for name in module.__all__ if not hasattr(module, name)]
    assert missing == [], f"{module_name}.__all__ promises names that do not exist: {missing}"


# ==========================================================================
# 16. the preview's caption strip: derived from the lines it holds
# ==========================================================================


def _caption_geometry(svg: str) -> tuple[float, list[float]]:
    """The canvas height and the caption lines' baselines (they start at x=8)."""
    root = ElementTree.fromstring(svg)
    height = float(root.get("height"))
    baselines = [
        float(node.get("y"))
        for node in root.iter(f"{SVG}text")
        if node.get("x") == "8"
    ]
    return height, baselines


def test_a_caption_with_notes_keeps_every_line_inside_the_canvas():
    """The strip was a hardcoded ``height + 90``; the caption is 4 to 8 lines.

    Four fixed lines (title, geometry digest, verdict, soft metrics) plus at most
    four notes, drawn at ``height + 16 + index * 15``: from the sixth line on
    (index 5 and up) the text fell off the bottom of the image — including the
    provenance footer a reviewer reads the digests from. Measured on the audit's
    ``draw compile`` run: 7 caption lines, canvas 520x430, the last two baselines
    at 431 and 446.
    """
    for notes in ([f"note {index}" for index in range(count)] for count in (2, 3, 4)):
        plan = LayoutPlan(notes=list(notes))
        svg = svgpreview.render_svg(plan, {}, title="100 caption")
        height, baselines = _caption_geometry(svg)
        assert len(baselines) == 4 + len(notes)
        assert max(baselines) + svgpreview.PREVIEW_FONT_SIZE <= height, (
            f"{len(baselines)} caption lines do not fit a {height:.0f}-unit canvas"
        )
        assert notes[-1] in svg, "the last note is drawn, so it has to be readable"


def test_a_caption_that_already_fitted_keeps_the_height_it_had():
    """The five lines a plan with at most one note produces stay inside 90 units.

    The strip guessed right for 4 and 5 lines, which is most plans: deriving the
    height from the line count may not move those previews — every recorded SVG
    of a plan with ≤1 note has to stay byte-identical (the batch's zero-movement
    check).
    """
    assert _caption_geometry(svgpreview.render_svg(LayoutPlan(), {}, title="t"))[0] == 90.0
    one_note = LayoutPlan(notes=["one note"])
    height, baselines = _caption_geometry(
        svgpreview.render_svg(one_note, {}, title="t"))
    assert height == 90.0
    assert len(baselines) == 5
    assert max(baselines) + svgpreview.PREVIEW_FONT_SIZE <= height


def test_a_real_compiled_plan_keeps_its_provenance_footer_visible():
    """The audit's own board: the geometry hash and verdict lines used to be cut.

    ``draw compile`` on a compiling scene with the notes the compiler produces
    (3+ of them, so 7+ caption lines) — the tail of the footer is what
    disappeared, so the check is on the compiled plan rather than a hand-built
    one.
    """
    import test_053b_drawcompiler as b053

    scene = b053.scenes()[4]
    plan = b053.best_of(scene)[1]
    assert len(plan.notes) >= 3, plan.notes
    svg = svgpreview.render_svg(plan, b053.library(), title="100 scene 4")
    height, baselines = _caption_geometry(svg)
    assert len(baselines) == 4 + min(len(plan.notes), 4)
    assert max(baselines) + svgpreview.PREVIEW_FONT_SIZE <= height
    assert plan.geometry_sha256()[:12] in svg
    assert str(plan.evidence.verdict) in svg


# ==========================================================================
# 19. a UTF-8 BOM: the first record of a stream is not a casualty
# ==========================================================================


def _record(envelope: dict, body: dict | None = None) -> str:
    """One record line — ``envelope || body |`` — the shape both containers write.

    The *envelope* is where ``yAxisDirection`` lives, which is why the builder
    takes the whole dict: a page's document type and frame are envelope facts.
    """
    head = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
    if body is None:
        return head + "|||"
    return head + "||" + json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "|"


def _document(**envelope: Any) -> dict:
    """An ``.epru`` envelope with the ticket every record carries."""
    return {"ticket": 1, **envelope}


def test_a_bom_on_the_epru_stream_costs_no_record(tmp_path):
    """``raw.decode("utf-8")`` kept U+FEFF, ``json.loads`` refused the first line.

    The record was counted malformed and dropped, and the only trace was a
    counter nothing surfaces — exit 0, no message. Measured by the audit: the
    stream's first ``DOCHEAD`` disappeared (``malformed=1``, ``total`` one short).
    """
    lines = [
        _record(_document(type="DOCHEAD", id="h1"),
                {"docType": "PCB", "uuid": "u1", "editVersion": "3.2.91"}),
        _record(_document(type="COMPONENT", id="c1"),
                {"partId": "p1", "x": 10, "y": 20, "rotation": 0}),
    ]
    path = _epro2(tmp_path, BOM + ("\n".join(lines) + "\n").encode("utf-8"))
    text, _meta = load_epru_text(path)
    assert not text.startswith("\ufeff"), "the BOM is part of the container, not of the record"
    stats = ParseStats()
    records = list(iter_epru_records(text, stats))
    assert stats.malformed_records == 0
    assert records[0].type == "DOCHEAD"


def test_a_bom_on_a_bommed_and_damaged_stream_is_still_stripped(tmp_path):
    """The same fix on the fallback branch: ``decode("utf-8", errors="replace")``.

    A stream that is BOM'd **and** not valid UTF-8 took the fallback decode, which
    kept the BOM — so the reader that was already guessing about one damaged byte
    also lost the first record. The byte below is genuinely undecodable, which is
    what puts the read on the fallback branch rather than the strict one.
    """
    lines = [
        _record(_document(type="DOCHEAD", id="h1"),
                {"docType": "PCB", "uuid": "u1", "editVersion": "3.2.91"}),
        _record(_document(type="TEXT", id="t1"), {"content": "hi"}),
    ]
    damaged = ("\n".join(lines) + "\n").encode("utf-8").replace(
        b'"content":"hi"', b'"content":"\xff"', 1)
    assert b'"content":"\xff"' in damaged
    with pytest.raises(UnicodeDecodeError):
        damaged.decode("utf-8")
    text, _meta = load_epru_text(_epro2(tmp_path, BOM + damaged))
    assert not text.startswith("\ufeff")
    stats = ParseStats()
    records = list(iter_epru_records(text, stats))
    assert stats.malformed_records == 0, "U+FFFD is what the replacement writes"
    assert [record.type for record in records] == ["DOCHEAD", "TEXT"]


def test_a_bom_on_an_eprj3_page_reads_the_same_stream_as_a_page_without_one(tmp_path):
    """The page reader: ``read_text(encoding="utf-8")`` kept the BOM.

    The first line of a page file is its ``DOCHEAD``, and that line is what
    declares the document type the y-flip transform keys on. With the BOM the
    line did not parse, so the document type was never declared and **no** record
    in the whole page was flipped — a y-up board read in the wrong frame, with no
    error. The two reads have to be the same text.
    """
    page = _eprj3_page(y_up=True)
    plain = load_eprj3_text(_eprj3_project(tmp_path / "plain", page))[0]
    bommed = load_eprj3_text(_eprj3_project(tmp_path / "bom", BOM + page))[0]
    assert bommed == plain
    assert "yAxisDirection" not in bommed
    # The board really is read in the V3 frame: the component's y is flipped from
    # the +500 the y-up page states. Without the flip the assertion below is what
    # fails, which is the damage the BOM did silently.
    assert '"y":-500.0' in plain, plain


def test_a_bom_before_an_undecodable_byte_is_still_stripped(tmp_path):
    """The second branch: a page that is not valid UTF-8 is read with ``replace``.

    The fallback decode had the same missing ``-sig``, so a damaged page — the
    one case where the reader is already guessing — also lost its first record.
    The byte below is genuinely undecodable, which is what puts the read on the
    fallback branch rather than the strict one.
    """
    page = _eprj3_page(y_up=True)
    damaged = page.replace(b'"zIndex":10', b'"zIndex":10,"title":"\xff"', 1)
    assert b'"title":"\xff"' in damaged
    with pytest.raises(UnicodeDecodeError):
        damaged.decode("utf-8")
    plain = load_eprj3_text(_eprj3_project(tmp_path / "plain", damaged))[0]
    bommed = load_eprj3_text(_eprj3_project(tmp_path / "bom", BOM + damaged))[0]
    assert bommed == plain
    assert "\ufffd" in bommed, "the damaged byte is replaced, not swallowed"


def test_a_bom_on_an_enet_file_is_stripped(tmp_path):
    """``.enet`` is JSON, so the BOM was not a dropped record but a hard refusal."""
    path = tmp_path / "bom.enet"
    path.write_bytes(BOM + json.dumps({
        "components": {"c-r1": {
            "props": {"Designator": "R1", "Value": "10k"},
            "pinInfoMap": {"1": {"number": "1", "name": "A", "net": "GND"}},
        }},
    }).encode("utf-8"))
    model = parse_enet(path)
    assert model.components["R1"].value == "10k"


# ------------------------------------------------------------------ builders


def _epro2(directory: Path, stream: bytes) -> Path:
    """An ``.epro2`` archive holding exactly this ``.epru`` stream."""
    path = directory / "bom.epro2"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("board.epru", stream)
    return path


def _eprj3_page(*, y_up: bool) -> bytes:
    """One schematic page, in the shape :func:`boardwise.parsers.eprj3` reads."""
    marker = {"yAxisDirection": "up"} if y_up else {}
    sign = -1.0 if y_up else 1.0
    lines = [
        _record({"type": "DOCHEAD", **marker},
                {"docType": "SCH_PAGE", "uuid": "page-1"}),
        _record({"type": "CANVAS", **marker},
                {"originX": 0, "originY": sign * 0.0, "unit": "0.01inch"}),
        _record({"type": "COMPONENT", "id": "c-u1", **marker},
                {"partId": "inst-u1", "x": 300.0, "y": sign * -500.0, "rotation": 0,
                 "isMirror": False, "zIndex": 10}),
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _eprj3_project(root: Path, page: bytes) -> Path:
    """A folder project: the index plus one page under ``sch/``."""
    page_dir = root / "sch" / "Schematic1"
    page_dir.mkdir(parents=True, exist_ok=True)
    (root / "bom.eprj3").write_text(json.dumps({
        "name": "bom",
        "owner_uuid": "0123456789abcdef0123456789abcdef",
        "format": "folder",
        "profile": {"schematics": {}, "sheets": {}, "pcbs": {}},
    }, ensure_ascii=False), encoding="utf-8")
    (page_dir / "P1.esch2").write_bytes(page)
    return root
