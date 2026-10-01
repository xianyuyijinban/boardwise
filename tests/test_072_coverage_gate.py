"""072: the boundary-failure dispositions and the coverage gate (issues #28/#29/#30).

Three families, one root — *the information was there, but it gated nothing*:

* **#28 structural breakage** — a legal `.enet`/`.epru` whose *structure* is wrong
  used to escape as a bare `AttributeError` traceback with exit 1 (the same code as
  "the board has an ERROR"), so a machine could not tell garbage input from a
  defective design. Six shapes, two commands, one answer each: exit 2, one
  `boardwise:` line with the position, no traceback. The error type follows
  `core.parts.PartError`, the precedent `library_from_json` set.
* **#29 an archive that reads nothing** — a truncated/damaged `.epro2` is a legal
  ZIP whose record stream is cut, and the parser's (correct) tolerance turned it
  into a 0-component 0-net model that `completion` called `complete` with exit 0:
  a silent false pass on the CI path. It is the extreme form of the coverage gate
  below, not a special case.
* **#30 the coverage gate** — `completion.verdict` counted only "known bad things"
  and never "did the review cover the board at all". The coverage section now sits
  beside the five existing gates — `parseIncomplete`, `pagesDropped`,
  `rulesRefused`, `recordsDropped`, `rulesErrored`, plus `modelEmpty` (the one
  distinction those five cannot express) — and any of them means the verdict cannot
  be `complete`; the whole review having no input at all is `incomplete`.

Everything here is offline: real fixtures are **read only** (a truncated copy is
built in `tmp_path`, never written back), and no editor is involved.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.cli import (
    _completion_coverage_gates,
    _completion_section,
    _conclusion_skeleton_gates,
    _review_conclusion,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.parsers.enet import NetlistShapeError, enet_dict_to_model

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SHELF = ROOT / "blocklib" / "parts.json"
GOLDEN = FIXTURES / "ch340_golden.epro2"
BOARD24V = FIXTURES / "board24v.enet"

#: The six crash shapes issue #28 measured, each with the position its message
#: must name. Every one of them used to raise a bare `AttributeError`.
BAD_ENET_SHAPES: dict[str, tuple[object, str]] = {
    "components-is-a-list": ({"components": [1, 2]}, "components"),
    "components-is-null": ({"components": None}, "components"),
    "component-item-is-an-int": ({"components": {"a": 42}}, "components[a]"),
    "props-is-a-list": ({"components": {"a": {"props": [1]}}}, "components[a].props"),
    "pininfomap-is-a-list": (
        {"components": {"a": {"props": {}, "pinInfoMap": [1]}}},
        "components[a].pinInfoMap",
    ),
    "top-level-is-a-list": ([1, 2, 3], "(顶层)"),
}

#: The coverage section of a reading that was covered **whole** — the shape a
#: reader sees on a board that parsed cleanly.
CLEAN_COVERAGE: dict = {
    "parseIncomplete": False,
    "modelEmpty": False,
    "pagesDropped": 0,
    "rulesRefused": 0,
    "recordsDropped": 0,
    "rulesErrored": [],
}


def _write(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _truncated(source: Path, target: Path, *, keep: float) -> Path:
    """Issue #29's reproduction: cut the inner `.epru`, repack a **legal** ZIP.

    Download interruptions, full disks and cut transfers all produce exactly this:
    a ZIP the reader can open whose record stream stops in the middle.
    """
    with zipfile.ZipFile(source) as archive:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as out:
            for name in archive.namelist():
                data = archive.read(name)
                if name.endswith(".epru"):
                    data = data[: int(len(data) * keep)]
                out.writestr(name, data)
    target.write_bytes(buffer.getvalue())
    return target


def _synthetic_epro2(target: Path, records: list[str]) -> Path:
    """A minimal but real `.epro2`: a ZIP with a `project2.json` and one `.epru`."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("project2.json", json.dumps({"title": "synthetic"}))
        archive.writestr("proj.epru", "\n".join(records) + "\n")
    target.write_bytes(buffer.getvalue())
    return target


def _checkup(tmp_path: Path, board: Path, name: str = "out") -> tuple[int, dict | None, Path]:
    out = tmp_path / name
    code = cli.main(
        ["checkup", "--file", str(board), "--out", str(out), "--library", str(SHELF)]
    )
    report_path = out / "report.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None
    )
    return code, report, out


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """Never touch the real `~/.boardwise` (config, audit, sidecars)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))


# --------------------------------------------------------------------------
# #28 — structural breakage: exit 2, one line, no traceback
# --------------------------------------------------------------------------


@pytest.mark.parametrize("shape", sorted(BAD_ENET_SHAPES), ids=sorted(BAD_ENET_SHAPES))
def test_review_of_a_structurally_wrong_enet_is_a_clean_exit_2(shape, tmp_path, capsys):
    """`exit 1` means "the board has an ERROR"; garbage input may not borrow it."""
    payload, position = BAD_ENET_SHAPES[shape]
    path = _write(tmp_path / f"{shape}.enet", payload)
    json_out = tmp_path / "r.json"

    code = cli.main(["review", str(path), "--json", str(json_out)])
    captured = capsys.readouterr()

    assert code == 2, f"{shape}: exit {code}, not 2"
    assert "Traceback" not in captured.err + captured.out, captured.err
    assert "AttributeError" not in captured.err, captured.err
    assert captured.err.startswith("boardwise: "), captured.err
    assert position in captured.err, f"{shape}: no position in {captured.err!r}"
    assert not json_out.exists(), "no report is written for an input that cannot be read"


@pytest.mark.parametrize("shape", sorted(BAD_ENET_SHAPES), ids=sorted(BAD_ENET_SHAPES))
def test_checkup_of_a_structurally_wrong_enet_is_the_same_clean_exit_2(shape, tmp_path, capsys):
    """`checkup --file` is the CI path: same disposition, and no half-written `--out`."""
    payload, position = BAD_ENET_SHAPES[shape]
    path = _write(tmp_path / f"{shape}.enet", payload)

    code = cli.main(
        ["checkup", "--file", str(path), "--out", str(tmp_path / "out"), "--library", str(SHELF)]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert "Traceback" not in captured.err
    assert position in captured.err
    assert not (tmp_path / "out" / "report.json").exists()


def test_the_shape_error_is_the_parsers_own_type_and_names_the_first_wrong_place():
    """The `PartError` precedent, at the netlist reader: one type, one sentence."""
    with pytest.raises(NetlistShapeError) as caught:
        enet_dict_to_model({"components": {"a": 42}})
    assert "components[a]" in str(caught.value)

    # `NetlistShapeError` is a `ValueError`, which is the channel every existing
    # reader of these parsers already handles — that is what makes the CLI's
    # exit-2 mapping hold without a new catch clause per command.
    assert issubclass(NetlistShapeError, ValueError)


def test_a_wellformed_enet_still_parses_unchanged():
    """The validator may not become a wall: the real fixture is read as before."""
    model = enet_dict_to_model(json.loads(BOARD24V.read_text(encoding="utf-8")))
    assert model.components and model.nets


def test_the_epro2_netlist_view_validates_the_props_it_joins(tmp_path, capsys):
    """`parsers/epro2_model.py` is the same path for the board view: one shape gate."""
    board = _synthetic_epro2(
        tmp_path / "bad-device.epro2",
        [
            '{"type":"DOCHEAD","ticket":0,"id":"d1"}'
            '||{"docType":"DEVICE","uuid":"dev1","editVersion":"1"}',
            '{"type":"META","ticket":1,"id":"dev1"}||{"title":"T","attributes":[1,2]}',
            '{"type":"DOCHEAD","ticket":2,"id":"p1"}'
            '||{"docType":"PCB","uuid":"pcb1","editVersion":"1"}',
            '{"type":"COMPONENT","ticket":3,"id":"c1"}'
            '||{"x":0,"y":0,"attrs":{"Designator":"U1","Device":"dev1"}}',
        ],
    )

    code = cli.main(["review", str(tmp_path / "bad-device.epro2"), "--view", "pcb"])
    captured = capsys.readouterr()

    assert code == 2
    assert "Traceback" not in captured.err
    assert "attributes" in captured.err and "dev1" in captured.err
    assert board.is_file(), "the crafted archive is the input, not a fixture"


# --------------------------------------------------------------------------
# #29 — an archive that reads nothing is not a clean board
# --------------------------------------------------------------------------


def test_a_truncated_archive_reports_incomplete_and_says_so(tmp_path, capsys):
    """Issue #29's reproduction: 1/3 of the `.epru`, repacked as a legal ZIP."""
    trunc = _truncated(GOLDEN, tmp_path / "trunc.epro2", keep=1 / 3)

    code, report, out = _checkup(tmp_path, trunc, name="trunc-out")
    capsys.readouterr()

    assert report is not None, "a readable archive still produces a report"
    assert report["model"]["components"] == 0 and report["model"]["nets"] == 0
    completion = report["completion"]
    coverage = completion["coverage"]
    assert coverage["parseIncomplete"] is True
    assert coverage["modelEmpty"] is True
    assert completion["verdict"] == "incomplete", (
        "an archive that reads nothing must never come out of the gate as a pass"
    )
    why = " ".join(completion["verdictWhy"])
    assert "归档读不出内容/模型为空" in why or "模型为空" in why
    assert "可能被截断" in why and "损坏" in why
    # The two sections agree, and the quotable line may not claim a pass (#21).
    assert report["summary"]["conclusion"] != "无 ERROR"
    markdown = (out / "report.md").read_text(encoding="utf-8")
    assert "**verdict：`incomplete`**" in markdown
    assert "覆盖" in markdown, "the coverage section is rendered, not only stored"
    # 073 changed this: the *verdict* is the 053 contract a CI reads, and an
    # `incomplete` one now decides the exit code too — 3, "nothing may be stated"
    # (this assertion was `== 0`; the behaviour change is this batch's purpose).
    # #29's ruling still keeps exit 2 for structural damage.
    assert code == 3


def test_the_intact_archive_of_the_very_same_bytes_has_a_clean_coverage(tmp_path, capsys):
    """The control: the gate discriminates, it does not fire on every board."""
    code, report, _out = _checkup(tmp_path, GOLDEN, name="whole-out")
    capsys.readouterr()

    assert report is not None
    assert report["model"]["components"] > 0
    assert report["completion"]["coverage"]["parseIncomplete"] is False
    assert report["completion"]["coverage"]["modelEmpty"] is False


def test_a_partially_truncated_archive_cannot_be_complete(tmp_path, capsys):
    """Issue #30's table: a 75% cut still yields parts (17 -> 2), so only the
    *stream* signal can catch it — and it may not come out `complete`."""
    trunc = _truncated(GOLDEN, tmp_path / "trunc75.epro2", keep=0.75)

    _code, report, _out = _checkup(tmp_path, trunc, name="t75-out")
    capsys.readouterr()

    assert report["model"]["components"] > 0, "this shape is not the empty-model one"
    coverage = report["completion"]["coverage"]
    assert coverage["parseIncomplete"] is True
    assert coverage["modelEmpty"] is False
    assert report["completion"]["verdict"] != "complete"
    assert any("解析流" in reason for reason in report["completion"]["verdictWhy"])


def test_an_empty_enet_is_read_as_an_empty_board_not_silence(tmp_path, capsys):
    """`空 ≠ 干净` — the ruling's accepted cost, on the netlist path too."""
    empty = _write(
        tmp_path / "empty.enet",
        {"version": "2.0.0", "components": {}, "designRule": {}, "differentialPair": {},
         "netClass": {}, "equalLengthNetGroup": {}},
    )

    code = cli.main(["review", str(empty)])
    output = capsys.readouterr().out

    assert code == 3, "073：空模型 → verdict incomplete → exit 3（原为 0）"
    assert "(0 components, 0 nets)" in output
    assert cli.EMPTY_MODEL_NOTE in output, (
        "the reader has to be told the file read as nothing at all"
    )


def test_the_pcb_view_hint_survives_the_unified_stance(capsys):
    """A schematic-only export asked for with `--view pcb`: the file is fine, the
    view is wrong — so that more specific sentence is the one printed, unchanged."""
    code = cli.main(["review", str(GOLDEN), "--view", "pcb"])
    output = capsys.readouterr().out

    assert code == 3, "073：没读到就是 incomplete → 3（原为 0），即便是「看错视图」的形态"
    assert cli.EMPTY_PCB_VIEW_NOTE in output
    assert cli.EMPTY_MODEL_NOTE not in output


# --------------------------------------------------------------------------
# #30 — the coverage gate, field by field, into the verdict
# --------------------------------------------------------------------------


def _body(**overrides) -> dict:
    from boardwise.cli import _completion_body

    kwargs = {
        "scope": {"rules": 14, "boards": 1, "pages": 1},
        "summary": {"errorCount": 0},
        "unreviewed": [],
        "triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
        "coverage": dict(CLEAN_COVERAGE),
    }
    kwargs.update(overrides)
    return _completion_body(**kwargs)


def test_a_clean_coverage_leaves_the_verdict_alone():
    """The gate is additive: nothing known to be missing still reads `complete`."""
    section = _body()
    assert section["verdict"] == "complete"
    assert section["verdictWhy"] == []
    assert section["coverage"]["parseIncomplete"] is False


@pytest.mark.parametrize(
    "field,value,word",
    [
        ("parseIncomplete", True, "解析流"),
        ("pagesDropped", 2, "页"),
        ("rulesRefused", 7, "withheld"),
        ("recordsDropped", 3, "丢弃"),
        ("rulesErrored", ["decap-required-caps"], "decap-required-caps"),
    ],
)
def test_every_coverage_field_holds_the_verdict_back(field, value, word):
    """One field at a time: `complete` is unreachable, and the reason names it."""
    section = _body(coverage={**CLEAN_COVERAGE, field: value})

    assert section["coverage"][field] == value
    assert section["verdict"] == "complete-with-open-items", section["verdictWhy"]
    assert any(word in reason for reason in section["verdictWhy"]), section["verdictWhy"]


def test_an_empty_model_is_incomplete_not_merely_open_items():
    """#29's ruling: no input at all is a weaker statement than "some items open"."""
    section = _body(coverage={**CLEAN_COVERAGE, "parseIncomplete": True, "modelEmpty": True})

    assert section["verdict"] == "incomplete"
    assert any(
        "模型为空" in reason and "可能被截断或损坏" in reason for reason in section["verdictWhy"]
    )


def test_a_coverage_failure_adds_a_reason_without_hiding_the_others():
    section = _body(
        summary={"errorCount": 3},
        unreviewed=[{"designator": "U9"}],
        coverage={**CLEAN_COVERAGE, "pagesDropped": 1, "rulesErrored": ["param-led-current"]},
    )

    assert section["verdict"] == "incomplete"
    why = " ".join(section["verdictWhy"])
    assert "3 项 ERROR" in why and "未审" in why and "页" in why and "param-led-current" in why


def test_the_coverage_gate_survives_a_regate(tmp_path):
    """`need-datasheet` / `triage` rebuild `completion` from the report; a gate that
    lived only in the CLI's memory would be dropped exactly there."""
    from boardwise.cli import _completion_from_report

    report = {
        "completion": {
            "scope": {"rules": 14, "boards": 1, "pages": 1},
            "coverage": {**CLEAN_COVERAGE, "rulesErrored": ["param-led-current"]},
        },
        "model": {"components": 5, "nets": 5},
        "summary": {"errorCount": 0},
        "unreviewed_parts": [],
        "warning_triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
    }

    section = _completion_from_report(report, needs_datasheet=[])

    assert section["coverage"]["rulesErrored"] == ["param-led-current"]
    assert section["verdict"] == "complete-with-open-items"


def test_an_empty_model_regated_from_a_report_is_still_incomplete():
    from boardwise.cli import _completion_from_report

    report = {
        "completion": {
            "scope": {"rules": 14, "boards": 1, "pages": 0},
            "coverage": {**CLEAN_COVERAGE, "parseIncomplete": True, "modelEmpty": True},
        },
        "model": {"components": 0, "nets": 0},
        "summary": {"errorCount": 0},
        "unreviewed_parts": [],
        "warning_triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
    }

    section = _completion_from_report(report, needs_datasheet=[])
    assert section["verdict"] == "incomplete"


# --------------------------------------------------------------------------
# #30 fork 2 — a rule that raises: report anyway, name the rule
# --------------------------------------------------------------------------


def _crash(monkeypatch, rule_id: str):
    from boardwise.engines import review as review_engine

    victim = next(rule for rule in review_engine.BUILTIN_RULES if rule.id == rule_id)

    def boom(model):  # noqa: ANN001 - the rule's own signature
        raise RuntimeError(f"synthetic crash in {rule_id}")

    monkeypatch.setattr(victim, "check", boom)
    return victim


def test_a_rule_that_raises_still_produces_a_report(monkeypatch, tmp_path, capsys):
    victim = _crash(monkeypatch, "param-led-current")

    code, report, out = _checkup(tmp_path, GOLDEN, name="crash-out")
    capsys.readouterr()

    assert report is not None, "the report is written even though a rule blew up (#30 fork 2)"
    assert (out / "report.md").is_file()
    coverage = report["completion"]["coverage"]
    assert coverage["rulesErrored"] == [victim.id]
    assert any(victim.id in reason for reason in report["completion"]["verdictWhy"])
    # The other rules ran to the end: their findings are still in the report.
    assert report["findings"], "the surviving rules still report"
    # 073: this reading is `incomplete` (unreviewed parts), so 3 — a crashed rule is
    # a coverage *gap* (complete-with-open-items), not the reason for the code.
    assert code == 3


def test_review_survives_a_rule_that_raises_and_says_which_one(monkeypatch, capsys):
    victim = _crash(monkeypatch, "param-led-current")

    code = cli.main(["review", str(GOLDEN)])
    captured = capsys.readouterr()

    assert "Traceback" not in captured.err + captured.out
    assert victim.id in captured.out + captured.err
    assert code in (0, 1)


def test_the_rule_runner_still_raises_for_a_caller_that_asked_for_no_collector(
    monkeypatch,
):
    """The catch is scoped to a caller that wants a partial report: `edit plan` and
    the repair flows pass no collector, so a broken rule stays a hard stop there
    rather than quietly reading as "no violation"."""
    from boardwise.engines.review import check_rules

    _crash(monkeypatch, "param-led-current")
    with pytest.raises(RuntimeError, match="synthetic crash"):
        check_rules(DesignModel())


# --------------------------------------------------------------------------
# #21 — one arithmetic, two sections: the conclusion and the verdict
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "coverage",
    [
        dict(CLEAN_COVERAGE),
        {**CLEAN_COVERAGE, "parseIncomplete": True},
        {**CLEAN_COVERAGE, "parseIncomplete": True, "modelEmpty": True},
        {**CLEAN_COVERAGE, "pagesDropped": 3},
        {**CLEAN_COVERAGE, "rulesRefused": 7},
        {**CLEAN_COVERAGE, "recordsDropped": 2},
        {**CLEAN_COVERAGE, "rulesErrored": ["param-led-current"]},
        {**CLEAN_COVERAGE, "rulesErrored": ["param-led-current"], "pagesDropped": 1},
    ],
    ids=lambda coverage: ",".join(
        key for key, value in coverage.items() if value not in (False, 0, [])
    )
    or "clean",
)
def test_the_conclusion_quotes_a_pass_exactly_when_the_coverage_verdict_is_complete(coverage):
    """The cross-invariant, with the coverage gate in the enumeration."""
    summary = {"errorCount": 0}
    completion = _completion_section(
        model=DesignModel(),
        summary=summary,
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 4, "filled": 4, "stale": 0}},
        coverage=coverage,
    )
    conclusion = _review_conclusion(
        summary,
        unreviewed_count=0,
        marked_count=0,
        pending_triage=0,
        **_conclusion_skeleton_gates(architecture={"totals": {}}, completion=completion),
        **_completion_coverage_gates(completion=completion),
    )

    assert (conclusion == "无 ERROR") == (completion["verdict"] == "complete"), (
        f"coverage={coverage} conclusion={conclusion!r} "
        f"verdict={completion['verdict']!r} why={completion['verdictWhy']}"
    )


def test_the_report_renders_the_coverage_section_from_the_json(tmp_path):
    """`render only what the JSON says`: the numbers in `report.md` are the
    section's own, and a section that is not there is not invented."""
    trunc = _truncated(GOLDEN, tmp_path / "trunc.epro2", keep=1 / 3)
    _code, report, out = _checkup(tmp_path, trunc, name="render-out")

    coverage = report["completion"]["coverage"]
    markdown = (out / "report.md").read_text(encoding="utf-8")
    line = next(line for line in markdown.split("\n") if line.startswith("- 覆盖："))
    assert "不完整" in line and "空模型" in line
    assert f"少页 {coverage['pagesDropped']}" in line
    assert f"规则 withheld 结论 {coverage['rulesRefused']}" in line
    assert f"解析丢弃记录 {coverage['recordsDropped']}" in line
    assert f"规则报错 {len(coverage['rulesErrored'])}" in line


def test_the_parse_stats_reach_the_report(tmp_path):
    """Issue #30's adjacent gap: the drop counters were console-only (#33: three)."""
    _code, report, _out = _checkup(tmp_path, GOLDEN, name="stats-out")

    stats = report["source"]["parseStats"]
    assert stats["pins_dropped_no_number"] == 0
    assert stats["components_without_symbol"] == 0
    assert stats["instances_without_designator"] == 0
    # ... and the gate's own number is their sum, read from one place. This
    # fixture parses clean, so all three are 0 and the equality cannot tell the
    # terms apart — `test_the_records_dropped_sum_reads_all_three_counters` is
    # where the wiring is pinned down, on distinct values. What this one holds
    # is the *contract*: the sum has three terms, so unwiring the third here
    # reads as a broken assertion rather than a passing one.
    assert report["completion"]["coverage"]["recordsDropped"] == (
        stats["pins_dropped_no_number"]
        + stats["components_without_symbol"]
        + stats["instances_without_designator"]
    )


def test_the_coverage_section_reads_the_tier_ladder_and_the_parse():
    """The five fields are *read*, not guessed: one synthetic ladder, one parse."""
    from boardwise.cli import _coverage_section
    from boardwise.core.geometry import ParseStats

    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1", pins=[Pin("1", "VIN", "VCC")])
    model.nets = {"VCC": Net("VCC", [("U1", "1")])}
    stats = ParseStats(
        pins_dropped_no_number=2, components_without_symbol=1, malformed_records=1
    )
    attempts = [
        {"tier": "project-file", "ok": False},
        {
            "tier": "per-page", "ok": True,
            "pages": [
                {"pageUuid": "a", "ok": True},
                {"pageUuid": "b", "ok": False},
                {"pageUuid": "c", "ok": False},
            ],
        },
    ]

    coverage = _coverage_section(
        model=model, board=None, attempts=attempts, parse_stats=stats,
        rules_errored=["decap-required-caps", "decap-required-caps", "led"],
    )

    assert coverage["pagesDropped"] == 2, "two pages of three never arrived"
    assert coverage["recordsDropped"] == 3, (
        "2 pins + 1 part without a symbol, and 0 parts without a designator"
    )
    assert coverage["parseIncomplete"] is True and coverage["modelEmpty"] is False
    assert coverage["rulesErrored"] == ["decap-required-caps", "led"], "ids, deduped+sorted"
    assert coverage["rulesRefused"] == 0, "nothing is welded here, so nothing is refused"


def test_the_records_dropped_sum_reads_all_three_counters():
    """Issue #33: ``instances_without_designator`` is a producer too, so it gates.

    The three counters carry **distinct** values and two ungated counters carry
    live decoy values, so the sum names the exact three fields: swap the third
    term for any other ``ParseStats`` int and the total moves off 10. Equal
    values would not witness that — adding a zeroed field looks identical.
    """
    from boardwise.cli import _coverage_section
    from boardwise.core.geometry import ParseStats

    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1", pins=[Pin("1", "VIN", "VCC")])
    model.nets = {"VCC": Net("VCC", [("U1", "1")])}
    stats = ParseStats(
        pins_dropped_no_number=2,
        components_without_symbol=3,
        instances_without_designator=5,
        # Not gated, and deliberately non-zero so a wrong term cannot add up.
        pads_without_net=9,
        empty_body_records=11,
    )

    coverage = _coverage_section(
        model=model, board=None, attempts=[], parse_stats=stats, rules_errored=[],
    )

    assert coverage["recordsDropped"] == 10, (
        "2 pins + 3 parts without a symbol + 5 parts without a designator; "
        "pads_without_net=9 / empty_body_records=11 are not producers and must "
        "not be in the sum"
    )


#: The `ParseStats` counters `coverage.recordsDropped` sums. Named explicitly
#: (not read from `_coverage_section`'s source) so that rewiring the sum has to
#: come through here too.
DROP_COUNTERS: tuple[str, ...] = (
    "pins_dropped_no_number",
    "components_without_symbol",
    "instances_without_designator",
)

#: The int counters on `ParseStats` that deliberately do **not** gate, and why.
NOT_WIRED: dict[str, str] = {
    "total_records": "a total, not a loss — it is what the drops are counted against",
    "pcb_records": "records seen in the PCB document, not dropped",
    "pads_without_net": "an unnamed pad is still a pad on the board; not a record loss",
    "empty_body_records": "a body with no geometry is still a component in the model",
    "malformed_records": "gates on its own field — coverage.parseIncomplete",
    "attrs_attached_by_parent_id": "counts how attributes arrived, not what was lost",
}


def test_every_int_counter_on_parse_stats_is_gated_or_explained():
    """The drift gate issue #33 asks for: a new drop counter cannot go unwired.

    Scans `ParseStats` backwards, so adding a counter that drops records — and
    forgetting to wire it into `coverage.recordsDropped`, which is exactly how
    #33 shipped — turns this test red instead of silently under-reporting.
    Declining to gate one is allowed, but only by saying why, here.
    """
    import dataclasses
    import typing

    from boardwise.core.geometry import ParseStats

    hints = typing.get_type_hints(ParseStats)
    int_fields = {f.name for f in dataclasses.fields(ParseStats) if hints[f.name] is int}

    assert int_fields, "the scan found no int field — has the scan itself gone stale?"
    assert not int_fields - set(DROP_COUNTERS) - set(NOT_WIRED), (
        "these ParseStats counters are neither summed into coverage.recordsDropped "
        "nor registered in NOT_WIRED: gate them, or say here why not"
    )
    assert not set(DROP_COUNTERS) - int_fields, (
        "DROP_COUNTERS names a field ParseStats no longer has — a rename left the "
        "gate reading a name that is gone"
    )


def test_refused_conclusions_counts_instances_not_the_registry(monkeypatch):
    """#30's field ③: the **withheld verdicts**, not `source.unprovenNets.rulesRefused`.

    The two numbers answer different questions and the report keeps both: the
    registry's length says how many rules *can* refuse (7, on every per-page
    reading), this says how many conclusions this reading actually withheld.
    """
    from boardwise.engines.review import BUILTIN_RULES, refused_conclusions
    from boardwise.rules.base import Outcome
    from boardwise.rules.unproven import UNPROVEN_BY_NAME

    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1", pins=[Pin("1", "VIN", "VCC")])
    model.nets = {"VCC": Net("VCC", [("U1", "1")])}
    assert refused_conclusions(model) == 0, "a proven reading refuses nothing"

    model.unproven_nets = {"VCC": ("p1", "p2")}
    victim = next(rule for rule in BUILTIN_RULES if rule.id == "decap-required-caps")
    monkeypatch.setattr(
        victim, "outcomes",
        lambda board: [
            Outcome(rule_id=victim.id, state="UNKNOWN", subject="U1 pin1", message="a",
                    missing_fact=f"a verified connection for net 'VCC': {UNPROVEN_BY_NAME}"),
            Outcome(rule_id=victim.id, state="UNKNOWN", subject="U1 pin2", message="b",
                    missing_fact="facts for U1: no shelf entry"),
            Outcome(rule_id=victim.id, state="VIOLATION", subject="U1 pin3", message="c"),
        ],
    )

    assert refused_conclusions(model) == 1, (
        "one withheld conclusion: the UNKNOWN that names the unproven net, not the "
        "UNKNOWN that names a missing datasheet and not the violation"
    )


def test_real_boards_report_a_clean_coverage(tmp_path):
    """The regression guard behind the 072 sweep: no fixture trips the gate."""
    for name in ("ch340_golden.epro2", "llc_board.epro2"):
        _code, report, _out = _checkup(tmp_path, FIXTURES / name, name=f"sweep-{name}")
        assert report["completion"]["coverage"] == CLEAN_COVERAGE, name
        assert report["completion"]["verdict"] == "incomplete", (
            "these boards are incomplete for their own (pre-existing) reasons"
        )


def test_the_gate_reads_the_coverage_it_is_given_not_the_model_argument():
    """The empty-model reading comes from `coverage`, never from the model object.

    Two reasons, and both are contracts: `_completion_section` is also called with
    a stub model by the tests that only want the section's arithmetic, and the
    re-gate path (`_completion_from_report`) has no model at all — it has a report.
    So the flag is computed where the parse is, and carried in `coverage`.
    """
    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1", pins=[Pin("1", "VIN", "+5V")])
    model.nets = {"+5V": Net("+5V", [("U1", "1")])}
    kwargs = {
        "summary": {"errorCount": 0},
        "unreviewed": [],
        "triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
    }

    assert _completion_section(model=model, **kwargs)["verdict"] == "complete"
    assert (
        _completion_section(model=DesignModel(), **kwargs)["verdict"] == "complete"
    ), "an empty stub with no coverage passed is not how the gate reads an empty model"
    assert (
        _completion_section(
            model=model, coverage={**CLEAN_COVERAGE, "parseIncomplete": True, "modelEmpty": True},
            **kwargs,
        )["verdict"]
        == "incomplete"
    )
