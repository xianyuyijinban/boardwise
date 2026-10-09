"""143d: the page a drawing lands on — the `--new-page` flag, and the census guard.

Two of the batch's holes live here, and both are "a reader that did not read".

1. **`--new-page` on a page that is already settled.** `_draw_apply_flow` resolved
   the page as ``args.page or plan.source.page_uuid``, so a plan bound to a page
   (or an explicit ``--page``) made the create branch unreachable: `draw apply
   <plan> --new-page` landed on the plan's own page, created nothing and reported
   exit 0. 054 C1's discipline is the opposite — a *named flag* either happens or
   is refused, never ignored — so it is now a refusal (exit 5), decided before the
   bridge is opened.
2. **the census had no label leg and no "un-numbered part" leg.** `sch.geometry`
   is contracted to carry four primitive sections (`components`, `wires`, `pins`,
   `netlabels`), and 054 C5's digest was computed from two of them. A hand edit
   that only added a **net label** — or a part the editor has not numbered yet
   (``R5?``, which `addcomponent.component_origins` drops on purpose) — left every
   counter and the whole digest unchanged, so the guard reported "the page is the
   one the plan was built against" over a page somebody had changed.

The fake editor and the plan fixture are 054's (`test_054_draw_cli`), so this file
adds no second way of landing a drawing.
"""

from __future__ import annotations

import json

import test_054_draw_cli as m054
import test_057_draw_page_cli as m057

from boardwise import cli
from boardwise.core.changeplan import (
    DRAW_MODULE_KIND,
    ChangePlan,
    PlanChange,
)
from boardwise.engines import drawapply


# --------------------------------------------------- hole 1: --new-page


def test_new_page_on_a_page_bound_plan_is_refused_not_ignored(tmp_path, capsys):
    """The witness: the plan carries its page, and the flag used to vanish.

    The plan is bound to ``page-1``; the daemon is *not* stubbed, so a run that
    reached the bridge at all would answer "daemon not reachable" (exit 3). Exit 5
    with the flag named is the proof that the refusal was decided offline.
    """
    plan_path, plan = m054._plan(tmp_path, page="page-1")
    assert plan.source.page_uuid == "page-1"
    code = cli.main(["draw", "apply", str(plan_path), "--new-page"])
    err = capsys.readouterr().err
    assert code == 5, err
    assert "--new-page" in err and "page-1" in err
    assert "daemon" not in err, "the flag was judged before the bridge was opened"


def test_new_page_beside_an_explicit_page_is_refused(tmp_path, capsys):
    """The second spelling of the same hole: `--page` also settled the page."""
    plan_path, _plan = m054._plan(tmp_path)
    code = cli.main(
        ["draw", "apply", str(plan_path), "--page", "page-1", "--new-page"]
    )
    err = capsys.readouterr().err
    assert code == 5, err
    assert "--new-page" in err and "page-1" in err
    assert "daemon" not in err


def test_new_page_still_creates_one_for_an_unbound_plan(monkeypatch, tmp_path, capsys):
    """The refusal is exactly as wide as the contradiction, no wider."""
    plan_path, plan = m054._plan(tmp_path)
    editor = m054._FakeEditor(
        exists=False, netlists=[{"components": {}}, m054._live_netlist_for(plan)]
    )
    m054._stub_editor(monkeypatch, editor)
    m054._stub_export(monkeypatch, components={}, findings=[])
    code = cli.main([
        "draw", "apply", str(plan_path), "--project", "test", "--new-page",
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    assert editor.created, "an unbound plan with --new-page still gets its page"


def test_page_name_without_a_new_page_is_reported_as_unused(monkeypatch, tmp_path, capsys):
    """`--page-name` is the same shape one notch smaller: read by nobody.

    It reaches `sch.doc.new` only, so a run that creates no page did not use it —
    said out loud rather than left for the reader to wonder why the page kept its
    name.
    """
    plan_path, plan = m054._plan(tmp_path)
    editor = m054._page_with(plan)
    m054._stub_editor(monkeypatch, editor)
    m054._stub_export(monkeypatch, components={}, findings=[])
    report = tmp_path / "apply.json"
    code = cli.main([
        "draw", "apply", str(plan_path), "--page", "page-1",
        "--page-name", "not used here", "--json", str(report),
    ])
    printed = capsys.readouterr().out
    assert code == 0, printed
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert any("--page-name" in note and "creates no page" in note
               for note in payload["notes"]), payload["notes"]
    assert not editor.created


def test_a_page_document_refuses_new_page_beside_page(monkeypatch, tmp_path, capsys):
    """The page route builds its plan at apply time and takes the same rule."""
    editor = m057._PageEditor(page="page-1")
    m057._stub_editor(monkeypatch, editor)
    m057._stub_export(monkeypatch, findings=[])
    code, out, circuit, presentation = m057._plan_page(monkeypatch, tmp_path, editor)
    assert code == 0
    document = out.with_name(out.stem + ".page.json")
    assert document.exists(), "the page document is the thing `draw apply` eats"
    code = cli.main([
        "draw", "apply", str(document), "--page", "page-1", "--new-page",
        "--circuit", str(circuit), "--presentation", str(presentation),
        "--profiles", str(m057.LIBRARY),
    ])
    err = capsys.readouterr().err
    assert code == 5, err
    assert "--new-page" in err and "--page" in err


# --------------------------------------------------- hole 2: the census


def _geometry(**extra):
    """The two-section dump 057's own census tests use, plus a label section."""
    base = {
        "components": [
            {"primitiveId": "sheet", "state": {"ComponentType": "sheet", "X": 0, "Y": 0}},
            {"primitiveId": "c1", "state": {
                "ComponentType": "part", "Designator": "R5", "X": 100, "Y": 200,
                "SupplierId": "C25744", "OtherProperty": {"Value": "10k"}}},
            {"primitiveId": "f1", "state": {
                "ComponentType": "netflag", "Net": "GND", "X": 100, "Y": 100}},
        ],
        "wires": [{"primitiveId": "w1", "state": {"Line": [100, 250, 100, 300],
                                                  "Net": "SIG"}}],
        "bboxes": {"c1": {"minX": 90, "minY": 150, "maxX": 110, "maxY": 250}},
    }
    base.update(extra)
    return base


def _labelled(**state):
    geometry = _geometry()
    geometry["netlabels"] = [{
        "primitiveId": "nl1",
        "state": {"Net": "TAP", "Text": "TAP", "X": 50, "Y": 60, **state},
    }]
    return geometry


def test_a_net_label_is_a_census_row():
    """`census_items` promised "every primitive … one row each" and was false."""
    rows = [row for row in drawapply.census_items(_labelled()) if row["kind"] == "netlabel"]
    assert rows == [{
        "id": "nl1", "kind": "netlabel", "net": "TAP", "text": "TAP",
        "x": 50.0, "y": 60.0, "rotation": None,
    }]


def test_a_label_added_by_hand_moves_the_census_digest():
    """The guard's own question: "is this the page the plan was built against?"."""
    before = drawapply.canvas_census(_geometry())
    after = drawapply.canvas_census(_labelled())
    assert before.netlabel_count == 0 and after.netlabel_count == 1
    assert before.digest != after.digest, (
        "a page that gained a label is not the page the plan recorded"
    )


def test_a_part_the_editor_has_not_numbered_moves_the_digest():
    """`R5?` is dropped from the designator set *on purpose* (036b's occupancy rule).

    So the digest has to carry the fact somewhere else, or a hand-placed part is
    invisible to every leg of C5.
    """
    unnumbered = _geometry()
    unnumbered["components"] = list(unnumbered["components"]) + [{
        "primitiveId": "c9",
        "state": {"ComponentType": "part", "Designator": "R9?", "X": 300, "Y": 300},
    }]
    before = drawapply.canvas_census(_geometry())
    after = drawapply.canvas_census(unnumbered)
    assert after.components == before.components, "the designator set keeps 036's meaning"
    assert after.unnumbered_count == 1 and before.unnumbered_count == 0
    assert before.digest != after.digest


def test_a_label_that_vanishes_or_is_renamed_is_a_change():
    before = drawapply.census_items(_labelled())
    assert drawapply.census_changes(before, before) == []
    gone = drawapply.census_changes(before, drawapply.census_items(_geometry()))
    assert gone and "TAP netlabel (nl1) is no longer on the page" in gone[0]
    renamed = drawapply.census_changes(
        before, drawapply.census_items(_labelled(Net="VIN")),
    )
    assert renamed and "net 'TAP' → 'VIN'" in renamed[0]


def test_a_label_moved_or_retexted_is_a_change_with_the_field_named():
    moved = drawapply.census_changes(
        drawapply.census_items(_labelled()),
        drawapply.census_items(_labelled(X=55)),
    )
    assert moved and "x 50.0 → 55.0" in moved[0]
    retexted = drawapply.census_changes(
        drawapply.census_items(_labelled()),
        drawapply.census_items(_labelled(Text="OUT")),
    )
    assert retexted and "text 'TAP' → 'OUT'" in retexted[0], retexted


def test_an_existing_label_is_a_keepout():
    """057 sec.2: every existing primitive a keep-out — including the printed names."""
    boxes, labels, notes = drawapply.census_keepouts(_labelled())
    index = labels.index("existing TAP label nl1")
    assert boxes[index] == (-5.0, 5.0, 105.0, 115.0), (
        "the anchor's own point ± the assumed half, grown one step"
    )
    assert any("TAP label" in note for note in notes), (
        "an assumed box is declared, never implied"
    )
    assert len(drawapply.census_keepouts(_geometry())[0]) == 3, (
        "a page with no label is unchanged: 2 components + 1 wire segment"
    )


def test_a_label_the_page_measured_is_a_keepout_of_its_own_size():
    geometry = _labelled()
    geometry["bboxes"] = dict(geometry["bboxes"])
    geometry["bboxes"]["nl1"] = {"minX": 44, "minY": 54, "maxX": 96, "maxY": 66}
    boxes, labels, _notes = drawapply.census_keepouts(geometry)
    index = labels.index("existing TAP label nl1")
    assert boxes[index] == (39.0, 49.0, 101.0, 71.0)


def _plan_with(baseline) -> ChangePlan:
    """A draw-module plan carrying a census, without compiling anything.

    The document reader and the C5 guard are both functions of the *baseline*, so a
    plan is the right carrier and a compiled drawing is not needed: this file is
    about what the census reads, not about how a drawing was made. (Compiling here
    would also make these tests fail for whatever reason the compiler is unhappy
    that day.)
    """
    return ChangePlan.from_jsonable({
        "planVersion": 1,
        "source": {"inputSha256": "0" * 64, "pageUuid": baseline.page_uuid},
        "target": {"module": "143d census test"},
        "change": {
            "kind": DRAW_MODULE_KIND,
            "layoutSha256": "1" * 64,
            "circuitSha256": "2" * 64,
            "presentationSha256": "3" * 64,
            "profiles": [{"symbolRef": "R0402", "geometryHash": "4" * 64}],
            "parts": [{
                "specId": "R1", "designator": "R1", "prefix": "R",
                "lcsc": "C25744", "value": "10k", "valueKey": "Value",
                "symbolRef": "R0402", "symbolHash": "4" * 64, "x": 0.0, "y": 0.0,
                "pins": [{"number": "1", "dx": 0.0, "dy": 50.0}],
            }],
            "wires": [{"net": "TAP", "points": [[0.0, 50.0], [0.0, 80.0]]}],
            "baseline": _baseline_document(baseline),
        },
    })


def _baseline_document(baseline) -> dict:
    """The baseline as it sits inside a plan document (the same keys `to_jsonable` writes)."""
    return {
        "pageUuid": baseline.page_uuid,
        "components": list(baseline.components),
        "wireCount": baseline.wire_count,
        "netflagCount": baseline.netflag_count,
        "netlabelCount": baseline.netlabel_count,
        "unnumberedCount": baseline.unnumbered_count,
        "pinCount": baseline.pin_count,
        "digest": baseline.digest,
        "findingsRead": baseline.findings_read,
    }


def test_the_baseline_document_carries_the_new_counters():
    """The round-trip: what a plan records is what apply reads back."""
    baseline = drawapply.canvas_census(_labelled())
    plan = _plan_with(baseline)
    again = ChangePlan.from_jsonable(plan.to_jsonable())
    assert again.change.draw_baseline.netlabel_count == 1
    assert again.change.draw_baseline.digest == baseline.digest
    assert again.to_jsonable()["change"]["baseline"]["netlabelCount"] == 1


def test_a_document_written_before_the_new_counters_still_reads():
    """An old plan has no such key; 0 is exactly what its census could see."""
    plan = _plan_with(drawapply.canvas_census(_geometry()))
    payload = plan.to_jsonable()
    for key in ("netlabelCount", "unnumberedCount", "pinCount"):
        payload["change"]["baseline"].pop(key)
    again = ChangePlan.from_jsonable(payload)
    assert again.change.draw_baseline.netlabel_count == 0
    assert again.change.draw_baseline.unnumbered_count == 0


def test_the_recorded_census_guard_refuses_a_page_that_gained_a_label():
    """054 C5 end to end over the new leg: the page is read, not trusted."""
    plan = _plan_with(drawapply.canvas_census(_geometry()))
    assert drawapply.guard_problems(plan, geometry=_geometry()) == []
    problems = drawapply.guard_problems(plan, geometry=_labelled())
    assert problems and "1 label(s)" in problems[0]


def test_the_created_page_emptiness_test_counts_every_section():
    """A "just created" page that already holds a label is not empty.

    143d: the test read parts, wires and flags, so a page carrying a label (or a
    part nobody numbered) passed for empty and the drawing landed on top of it.
    """
    assert cli._census_is_not_empty(drawapply.canvas_census(_labelled()))
    assert cli._census_is_not_empty(drawapply.canvas_census(_geometry()))
    assert not cli._census_is_not_empty(drawapply.canvas_census({}))
