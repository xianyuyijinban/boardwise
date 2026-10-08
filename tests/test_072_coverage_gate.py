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


def _board(title: str, parts: int) -> "BoardModel":
    """A project board holding ``parts`` components, under a real ``BoardRef``.

    Issue #30 ⑥'s reproduction needs a board's **title** — it is what the
    `verdictWhy` clause names — and `BoardRef` is frozen, so the title is passed
    to the constructor rather than assigned.
    """
    from boardwise.core.model import BoardModel, BoardRef

    board = BoardModel(board=BoardRef(uuid=f"uuid-{title}", title=title))
    for index in range(parts):
        component = Component(
            uid=f"{title}-{index}", designator=f"U{index}",
            pins=[Pin("1", f"P{index}", "NET")],
        )
        board.components[component.designator] = component
    return board

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
#: reader sees on a board that parsed cleanly. 126d added `pcbReviewMissing` to
#: the same dict: a reading is covered whole only if the PCB was looked at too,
#: so the clean value is False. #30 ⑥ added `boardsEmpty`/`boardsEmptyNames`
#: (the count of boards that came out with no parts, and which ones): a clean
#: single-board project has one board with parts on it, so the count is 0 and the
#: name list is empty — **present** here because `_coverage_section` always
#: emits both, and a report carrying this section must compare equal to it.
#: Tests that build their own coverage section (rather than spreading this one)
#: must be read with that in mind — every key is read with `.get` everywhere in
#: `cli`, so an older section without any of them still works.
CLEAN_COVERAGE: dict = {
    "parseIncomplete": False,
    "modelEmpty": False,
    "boardsEmpty": 0,
    "boardsEmptyNames": [],
    "pagesDropped": 0,
    "rulesRefused": 0,
    "recordsDropped": 0,
    "rulesErrored": [],
    "pcbReviewMissing": False,
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
        # #30 ⑥: a board that came out with no parts is a coverage gap of
        # its own — the same one-field-at-a-time contract as the five above.
        ("boardsEmpty", 1, "块板读出 0 器件"),
    ],
)
def test_every_coverage_field_holds_the_verdict_back(field, value, word):
    """One field at a time: `complete` is unreachable, and the reason names it."""
    section = _body(
        coverage={
            **CLEAN_COVERAGE,
            field: value,
            # The names are the annotation of the same fact, not a second
            # field under test — they ride along so the clause can say B2.
            **({"boardsEmptyNames": ["B2"]} if field == "boardsEmpty" else {}),
        }
    )

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


def test_a_regate_of_a_report_written_before_the_board_gate_does_not_crash():
    """#30 ⑥ follows 126d's ``pcbReviewMissing`` precedent, key by key.

    A report written by an older build carries a ``/6`` coverage section with no
    ``boardsEmpty`` and no ``boardsEmptyNames``. ``need-datasheet`` and ``triage``
    re-gate through ``_completion_body``, so a ``[...]`` read here would make both
    commands crash on **every** old report — the exact trap 126d's comment
    records. Absent means 0 / no names, which is also the right reading: an old
    report is not re-litigated by a gate that postdates it.
    """
    from boardwise.cli import _completion_from_report

    legacy_coverage = {
        key: value for key, value in CLEAN_COVERAGE.items()
        if key not in ("boardsEmpty", "boardsEmptyNames")
    }
    assert legacy_coverage != CLEAN_COVERAGE, "the fixture must really lack the keys"
    report = {
        "completion": {
            "scope": {"rules": 14, "boards": 2, "pages": 3},
            "coverage": dict(legacy_coverage),
        },
        "model": {"components": 5, "nets": 5},
        "summary": {"errorCount": 0},
        "unreviewed_parts": [],
        "warning_triage": [],
        "architecture": {"totals": {"slots": 4, "filled": 4, "stale": 0}},
    }

    section = _completion_from_report(report, needs_datasheet=[])

    assert section["verdict"] == "complete", section["verdictWhy"]
    # The section is passed through, not rewritten: no key is invented for a
    # reading that never ran the producer.
    assert "boardsEmpty" not in section["coverage"], section["coverage"]


def test_the_markdown_coverage_line_renders_empty_boards_with_their_names():
    """#30 ⑥'s renderer follows the JSON: empty boards appear, named (#132).

    The truncated-fixture test above proves the line renders the JSON's own
    numbers; this one pins the ⑥ segment itself — without it, an empty board
    would be gated in the JSON but invisible in the document engineers read.
    """
    from boardwise.engines.checkup import render_report_markdown

    coverage = dict(CLEAN_COVERAGE)
    coverage["boardsEmpty"] = 1
    coverage["boardsEmptyNames"] = ["B2"]
    report = {
        "schema": "boardwise.checkup/7",
        "source": {"tier": "file", "tierLabel": "离线文件", "project": {"friendlyName": "合成工程"}},
        "model": {"components": 5, "nets": 5},
        "summary": {"errorCount": 0, "warningCount": 0, "infoCount": 0, "exitCode": 0},
        "findings": [],
        "completion": {
            "verdict": "complete-with-open-items",
            "verdictWhy": [],
            "coverage": coverage,
            "architectureSlots": {"total": 0, "filled": 0, "stale": 0},
            "openTodos": 0,
        },
        "architecture": None,
    }

    markdown = render_report_markdown(report)

    line = next(line for line in markdown.split("\n") if line.startswith("- 覆盖："))
    assert "空板 1（B2）" in line, line
    # Zero stays silent — an all-clean reading must not grow the segment.
    coverage["boardsEmpty"] = 0
    coverage["boardsEmptyNames"] = []
    markdown = render_report_markdown(report)
    line = next(line for line in markdown.split("\n") if line.startswith("- 覆盖："))
    assert "空板" not in line, line


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
        {**CLEAN_COVERAGE, "boardsEmpty": 1, "boardsEmptyNames": ["B2"]},
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


# --------------------------------------------------------------------------
# #66 — every refusal phrasing counts, and the gate the count feeds
# --------------------------------------------------------------------------

#: The real board whose unproven nets are **all** 107 truncations (none is the
#: cross-page same-name merge): five nets, one reason each. Issue #66 measured
#: ``rulesRefused: 0`` on it and two rules that really did withhold.
DCDC = FIXTURES / "DCDC-12V9V转5V3V3_2026-09-27.epro2"


def board_reason(board, net):
    """107's reason code for one unproven net — the model's own wording."""
    return (getattr(board, "unproven_reasons", None) or {})[net][0]


def test_every_refusal_phrasing_counts_not_just_the_cross_page_one():
    """Issue #66: the counter asked ``UNPROVEN_BY_NAME in missing_fact``, which is
    one of **three** sentences the unproven reading produces — 107's two
    truncation phrasings do not contain it, so every one of their refusals read as
    zero. This walks the real DCDC fixture (all five unproven nets truncated by a
    duplicate designator, none of them a cross-page same-name merge) and asks the
    two questions that must not disagree: how many refusals did the walk actually
    file, and how many did the counter report."""
    from boardwise.engines.review import BUILTIN_RULES, refused_conclusions
    from boardwise.rules.unproven import NET_MEMBERSHIP_RULES, is_unproven_refusal
    from boardwise.parsers.schematic import build_project_model

    model = build_project_model(DCDC)
    unproven = [
        (board, net, board_reason(board, net))
        for board in model.boards
        for net in (getattr(board, "unproven_nets", None) or {})
    ]
    assert len(unproven) == 5, [net for _b, net, _r in unproven]
    assert {reason for _b, _net, reason in unproven} == {
        "truncated-by-duplicate-designator"
    }, "this fixture's gap is truncation, not the cross-page merge"

    withheld = [
        (rule.id, outcome.subject)
        for board in model.boards
        if getattr(board, "unproven_nets", None)
        for rule in BUILTIN_RULES
        if rule.id in NET_MEMBERSHIP_RULES and hasattr(rule, "outcomes")
        for outcome in rule.outcomes(board)
        if outcome.state == "UNKNOWN" and is_unproven_refusal(outcome.missing_fact)
    ]
    assert len(withheld) >= 2, (
        withheld,
        "the walk really did withhold conclusions on this board — that is what "
        "the counter is supposed to report",
    )
    assert refused_conclusions(model) == len(withheld), (
        "the counter and the walk are two readings of one number"
    )



def test_the_withheld_count_keeps_the_verdict_from_saying_complete(tmp_path):
    """The other end of issue #66, measured **end to end on the real fixture**.

    The counter is the only source of ``coverage.rulesRefused``, and that field is
    one of the gates that turns a verdict from ``complete`` into
    ``complete-with-open-items``. So ``checkup`` is driven on ``DCDC-12V9V转5V3V3``
    — the board issue #66 measured ``rulesRefused: 0`` on — and the report is
    read for three things that must hold together:

    * ``rulesRefused >= 2``: two rules really withheld on this board;
    * the clause is in ``verdictWhy``;
    * ``verdict != "complete"``.

    The fixture is ``incomplete`` for its own pre-existing reasons (two
    duplicate-designator ERRORs, 19 parts with no datasheet), so this pins the
    strongest statement this board supports; ``test_refused_conclusions_gates_a_
    complete_verdict`` isolates the ``complete`` side, where the withheld count is
    the *only* thing that decides. Between them both directions are pinned.
    """
    _code, report, _out = _checkup(tmp_path, DCDC, name="issue-66-dcdc")
    coverage = report["completion"]["coverage"]
    assert coverage["rulesRefused"] >= 2, coverage
    assert any("withheld" in why for why in report["completion"]["verdictWhy"])
    assert report["completion"]["verdict"] != "complete", report["completion"]
    # The report itself never lied: the truncation reasons were already in
    # ``source.unprovenNets.reasons``; what was missing was the gate that turns
    # them into a verdict. Pin both halves so a future change cannot fix one and
    # drop the other.
    reasons = report["source"]["unprovenNets"]["reasons"]
    assert set(reasons.values()) == {"truncated-by-duplicate-designator"}, reasons


def test_a_checkup_with_a_contract_counts_the_contract_scoped_refusals(tmp_path):
    """Issue #66 A2, measured end to end: the same board, two runs.

    The rules that read a contract run as per-run instances (:func:`_rules_for`),
    and three of them — ``pwr-cap-voltage-rating``, ``path-ldo-dissipation``,
    ``arch-rail-voltage-clash`` — return ``[]`` with no contract at all, because
    the rail declarations *are* their subject. Counting against the module-level
    registry therefore cannot see their refusals, so the number the gate reads
    was strictly **smaller** on a ``--intent`` run than on the same board without
    one. This drives both runs and pins the direction: with the contract, the
    count is **higher**.
    """
    plain_out = tmp_path / "plain"
    code = cli.main([
        "checkup", "--file", str(DCDC), "--out", str(plain_out),
        "--library", str(SHELF),
    ])
    plain = json.loads((plain_out / "report.json").read_text(encoding="utf-8"))
    assert code in (0, 1)

    contract = tmp_path / "intent.json"
    assert cli.main([
        "arch", str(DCDC), "--out", str(tmp_path / "arch.md"),
        "--library", str(SHELF), "--intent", str(contract),
    ]) == 0
    contract_out = tmp_path / "with-intent"
    cli.main([
        "checkup", "--file", str(DCDC), "--out", str(contract_out),
        "--library", str(SHELF), "--intent", str(contract),
    ])
    with_intent = json.loads(
        (contract_out / "report.json").read_text(encoding="utf-8")
    )

    before = plain["completion"]["coverage"]["rulesRefused"]
    after = with_intent["completion"]["coverage"]["rulesRefused"]
    assert after > before, (
        f"the contract run must see at least as many withheld conclusions: "
        f"{before} -> {after}"
    )
    assert after >= 2


def test_refused_conclusions_gates_a_complete_verdict(tmp_path):
    """A reading that withheld conclusions and has nothing else wrong.

    The #66 claim, isolated: with a **clean** coverage section and every other
    ``verdictWhy`` clause empty, ``rulesRefused > 0`` is the one thing that stops
    the verdict from being ``complete``. Both directions are pinned in one test —
    the count is 0 ⇒ ``complete``, the count is 2 ⇒ ``complete-with-open-items`` —
    because "the gate exists" and "the gate is wired" are different claims and a
    test that only saw the second would pass on a counter stuck at 0.
    """
    from boardwise.cli import _completion_section

    base = dict(
        summary={"errorCount": 0, "errors": [], "countsIncomplete": False},
        unreviewed=[], triage=[], needs_datasheet=[],
        architecture={"totals": {"slots": 18, "filled": 18, "stale": 0}},
        model=object(),
    )
    assert _completion_section(**base, coverage=dict(CLEAN_COVERAGE))["verdict"] == "complete"

    refused = dict(CLEAN_COVERAGE, rulesRefused=2)
    gated = _completion_section(**base, coverage=refused)
    assert gated["verdict"] == "complete-with-open-items", gated
    assert any("withheld" in why for why in gated["verdictWhy"]), gated["verdictWhy"]
    # The clause names the family, not one of its three sentences: quoting the
    # cross-page phrasing would have been wrong on exactly the boards (#66) that
    # made the count non-zero.
    clause = next(why for why in gated["verdictWhy"] if "withheld" in why)
    assert "#19/#107" in clause and "截断" in clause, clause


def test_the_count_uses_this_runs_rule_list_not_the_module_registry(monkeypatch):
    """Issue #66 A2: counting against ``BUILTIN_RULES`` cannot see the refusals of
    the run that has a contract.

    ``pwr-cap-voltage-rating`` is a ``NET_MEMBERSHIP_RULES`` member, but its
    ``_rows`` returns ``[]`` with no intent — the rail declarations *are* its
    subject — so the module-level instance can never withhold anything. The
    instances :func:`_rules_for` builds for a ``--intent`` run do, and those are
    the ones that judged the board.

    The two readings of the same board, measured: 0 against the registry, >=1
    against the run's own list. A test that only pinned the first would have
    passed all along, which is why both are here.
    """
    from boardwise.core import designintent as di
    from boardwise.core.model import Component, DesignModel, Net, Pin
    from boardwise.core.parts import PartEntry, PartLibrary
    from boardwise.engines.review import BUILTIN_RULES, _rules_for, refused_conclusions
    from boardwise.rules.railratings import CapVoltageRating

    model = DesignModel()
    model.components["C1"] = Component(
        uid="c1", designator="C1", value="100nF", mpn="CAP1",
        pins=[Pin("1", "", "+24V"), Pin("2", "", "GND")],
    )
    model.nets = {"+24V": Net("+24V", [("C1", "1")]), "GND": Net("GND", [("C1", "2")])}
    model.unproven_nets = {"+24V": ("p1", "p2")}
    model.unproven_reasons = {
        "+24V": ("truncated-by-duplicate-designator", "detail"),
    }

    shelf = PartLibrary(parts=[
        PartEntry(key="cap.100n_0603", mpn="CAP1", lcsc="C1",
                  params={"Voltage Rating": "50V"}),
    ])
    intent = di.IntentSource(
        document=di.DesignIntent(rails=[di.IntentRail(net="+24V")]),
        path="mem://contract.json",
    )
    rules = _rules_for(intent)
    registry = next(r for r in rules if r.id == "pwr-cap-voltage-rating")
    assert isinstance(registry, CapVoltageRating) and registry.intent is not None
    module_level = next(r for r in BUILTIN_RULES if r.id == "pwr-cap-voltage-rating")
    assert module_level.intent is None, (
        "the module-level instance is contract-free, which is exactly why "
        "counting against the registry read 0"
    )

    # This run's cap rule really did withhold on this board; the module-level one
    # has no subject at all, so the same walk finds nothing. The two numbers are
    # the A2 claim, measured rather than argued.
    assert refused_conclusions(model, rules=rules) >= 1
    assert refused_conclusions(model) == 0, (
        "the registry's blind spot, measured rather than argued"
    )


def test_a_rule_that_raises_while_being_re_counted_does_not_kill_the_report(monkeypatch):
    """#66 A3: this second walk was the one #30's ``_run_rules`` fork never
    covered, and its caller (``cli._coverage_section``) sits outside any except —
    so a rule raising here aborted ``checkup`` outright. The fork is the same one:
    hand in a collector and the count is partial with the broken id named; leave
    it out and the exception stands, because ``edit plan`` must not read "the rule
    crashed" as "the rule found nothing"."""
    from boardwise.engines.review import BUILTIN_RULES, refused_conclusions
    from boardwise.rules.base import Outcome
    from boardwise.rules.unproven import (
        TRUNCATION_PHRASES,
        TRUNCATED_BY_DESIGNATOR,
    )

    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1", pins=[Pin("1", "VIN", "VCC")])
    model.nets = {"VCC": Net("VCC", [("U1", "1")])}
    model.unproven_nets = {"VCC": ("p1", "p2")}

    # Both rules are handed in explicitly, so this does not depend on the
    # registry's order: ``broken`` comes first and ``counted`` second.
    broken = next(r for r in BUILTIN_RULES if r.id == "decap-required-caps")
    counted = next(r for r in BUILTIN_RULES if r.id == "conn-usb-cc-pulldown")

    def boom(board):
        raise RuntimeError("this rule is broken")

    monkeypatch.setattr(broken, "outcomes", boom, raising=False)
    monkeypatch.setattr(counted, "outcomes", lambda board: [
        Outcome(rule_id=counted.id, state="UNKNOWN", subject="USB1 pin4", message="a",
                missing_fact=TRUNCATION_PHRASES[TRUNCATED_BY_DESIGNATOR] + "detail")
    ], raising=False)
    walk = [broken, counted]

    errored: list[str] = []
    assert refused_conclusions(model, rules=walk, rules_errored=errored) == 1, (
        "the other rule's refusal still counted — the count is partial, not zero"
    )
    assert errored == ["decap-required-caps"], errored

    # Without a collector the exception stands: a caller that asks for the
    # hard stop keeps it (the `_run_rules` fork, unchanged).
    with pytest.raises(RuntimeError):
        refused_conclusions(model, rules=walk)


def test_the_refusal_family_is_defined_once_and_the_counter_only_asks_it():
    """The maintainability half of #66, and the reason the hole happened twice.

    The sentences live in ``rules.unproven``; ``engines/review`` must *ask*
    (:func:`is_unproven_refusal`) rather than restate one, or the next phrasing
    added to the family re-opens the same hole. A test that failed on a duplicate
    literal keeps the two sides from drifting back apart — this is the pin that
    makes issue #62's "don't write the same string in two places" enforceable for
    this one."""
    review_src = (ROOT / "src" / "boardwise" / "engines" / "review.py").read_text(
        encoding="utf-8"
    )
    assert "UNPROVEN_BY_NAME" not in review_src, (
        "engines/review no longer names a refusal sentence itself"
    )
    assert "is_unproven_refusal" in review_src

    from boardwise.rules.unproven import (
        REFUSAL_SENTENCES,
        TRUNCATION_PHRASES,
        UNPROVEN_BY_NAME,
        is_unproven_refusal,
        unproven_missing_fact,
    )

    assert set(REFUSAL_SENTENCES) == {UNPROVEN_BY_NAME, *TRUNCATION_PHRASES.values()}
    assert is_unproven_refusal(None) is False
    assert is_unproven_refusal("a datasheet nobody has read") is False
    for sentence in REFUSAL_SENTENCES:
        assert is_unproven_refusal(f"{sentence}some detail"), sentence


def test_the_coverage_clause_for_withheld_conclusions_names_the_family():
    """The ``verdictWhy`` clause must not quote a single sentence of the family.

    Issue #66's report clause read "…(issue #19: agreement by name is not a
    verified connection)" — true of the phrasing it was written against, and
    false on the truncation refusals that make the count non-zero. Both boards
    reach the reader through the same clause, so it names the gap instead."""
    from boardwise.cli import _coverage_reasons

    reasons = _coverage_reasons(dict(CLEAN_COVERAGE, rulesRefused=3))
    assert len(reasons) == 1
    clause = reasons[0]
    assert "3 条规则结论被 withheld" in clause
    assert "agreement by name is not a verified connection" not in clause, clause


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
# --------------------------------------------------------------------------
# #30 ⑥ — a multi-board project whose *one* board came out empty
# --------------------------------------------------------------------------


def _project_coverage(model: object) -> dict:
    """``_coverage_section`` over a parse that produced nothing but the model."""
    from boardwise.cli import _coverage_section
    from boardwise.core.geometry import ParseStats

    return _coverage_section(
        model=model, board=None, attempts=[], parse_stats=ParseStats(),
        rules_errored=[],
    )


def _project_verdict(model: object) -> dict:
    """The `completion` section for a project reading, through the live path."""
    return _completion_section(
        model=model,
        summary={"errorCount": 0},
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 4, "filled": 4, "stale": 0}},
        coverage=_project_coverage(model),
    )


def test_a_project_with_one_empty_board_is_not_complete_and_names_it():
    """Issue #30 ⑥, verbatim: B1 holds 5 parts, B2 holds none.

    Before this batch every counter read zero and the verdict read `complete`,
    while the report's own ``model.boards[]`` said ``components: 0`` for B2 — the
    issue's own pattern, "the information was there, nothing gated on it". The
    ruling is ``complete-with-open-items`` and not ``incomplete``: the project
    *did* have input, and an intentionally-empty sub-board is an engineer's call,
    not a missing review.
    """
    from boardwise.core.model import ProjectModel

    model = ProjectModel(boards=[_board("B1", 5), _board("B2", 0)])

    coverage = _project_coverage(model)
    assert coverage["boardsEmpty"] == 1
    assert coverage["boardsEmptyNames"] == ["B2"]
    # #29's own reading is untouched: the project as a whole did read.
    assert coverage["modelEmpty"] is False
    assert coverage["parseIncomplete"] is False

    section = _project_verdict(model)
    assert section["verdict"] == "complete-with-open-items", section["verdictWhy"]
    clause = next(reason for reason in section["verdictWhy"] if "0 器件" in reason)
    assert "B2" in clause, clause
    assert "B1" not in clause, "the clause names the empty board, not the whole project"
    # The other coverage fields stay at zero — this is board-level, and a test
    # that only checked the verdict would also pass if the whole parse had been
    # declared truncated.
    for field in ("pagesDropped", "rulesRefused", "recordsDropped"):
        assert coverage[field] == 0, field


def test_a_project_whose_boards_are_all_empty_is_still_incomplete():
    """`modelEmpty` keeps its meaning (#29): a total of zero is 「no input at all」.

    Both fields fire here and the stronger one wins, which is the point: the
    count is additive to #29 rather than a replacement for it. ``B2`` is still
    named, because "which boards" is the actionable half of the sentence even
    when the verdict is already ``incomplete``.
    """
    from boardwise.core.model import ProjectModel

    model = ProjectModel(boards=[_board("B1", 0), _board("B2", 0)])
    coverage = _project_coverage(model)

    assert coverage["modelEmpty"] is True and coverage["parseIncomplete"] is True
    assert coverage["boardsEmpty"] == 2 and coverage["boardsEmptyNames"] == ["B1", "B2"]

    section = _project_verdict(model)
    assert section["verdict"] == "incomplete", section["verdictWhy"]
    assert any("模型为空" in reason for reason in section["verdictWhy"])


def test_a_single_board_reading_is_not_a_board_with_nothing_on_it():
    """#30 ⑥ is board granularity: it must not re-open a single-board reading.

    A plain `DesignModel` has no ``boards`` list, so an empty schematic stays
    exactly what #29 made it — `modelEmpty` → `incomplete` — with no 「0 器件的板」
    clause beside it. The two gates answer different questions, and one board is
    not a project whose one board is empty: a single-board project *is* the
    model, so "no parts" and "nothing was read" are the same fact and counting it
    twice would print it twice.
    """
    empty = DesignModel()
    coverage = _project_coverage(empty)
    assert coverage["boardsEmpty"] == 0, "a single board is not an empty *board* of a project"
    assert coverage["boardsEmptyNames"] == []
    section = _completion_section(
        model=empty,
        summary={"errorCount": 0},
        unreviewed=[],
        triage=[],
        architecture={"totals": {"slots": 4, "filled": 4, "stale": 0}},
        coverage={**CLEAN_COVERAGE, "modelEmpty": True, "parseIncomplete": True},
    )
    assert section["verdict"] == "incomplete"
    # 「块板读出 0 器件」 is ⑥'s clause and not a substring of #29's
    # 「模型为空（0 器件 0 网络）」 — matching on plain "0 器件" would hit
    # the other reason and pass vacuously.
    assert not any(
        "块板读出 0 器件" in reason for reason in section["verdictWhy"]
    ), section["verdictWhy"]


def test_a_single_board_project_that_read_something_reports_no_empty_board():
    """The zero-impact half: the new field exists and is 0, it is not `None`.

    Chosen over **absent** because `_coverage_section` always emits both keys —
    the same shape `pcbReviewMissing` set (126d) — and because a caller that
    spreads `CLEAN_COVERAGE` compares the whole dict. Absent-not-empty is the
    discipline that applies to a key whose *producer* may not have run (a
    re-gate of an older report); here the producer always runs.
    """
    from boardwise.core.model import ProjectModel

    model = ProjectModel(boards=[_board("B1", 5)])
    coverage = _project_coverage(model)

    assert coverage["boardsEmpty"] == 0
    assert coverage["boardsEmptyNames"] == []
    assert _project_verdict(model)["verdict"] == "complete"


def test_a_board_with_nets_but_no_parts_is_still_an_empty_board():
    """The ruling is 「0 器件」, so nets do not buy a board a pass.

    #29's copper clause exempts 「nothing was read」 from the damage hint — it is
    about *the whole reading*. Here the project did read (B1 carries parts), so
    B2's own emptiness is the open item: a net name is not a placed part and no
    placement rule can judge a board with none. An intentionally netlist-only
    sub-board is exactly the case the engineer confirms and flips.
    """
    from boardwise.core.model import ProjectModel

    netted = _board("B2", 0)
    netted.nets = {"N1": Net("N1", [])}
    model = ProjectModel(boards=[_board("B1", 5), netted])

    coverage = _project_coverage(model)
    assert coverage["boardsEmpty"] == 1 and coverage["boardsEmptyNames"] == ["B2"]
    assert coverage["modelEmpty"] is False, "the project as a whole did read"
    assert _project_verdict(model)["verdict"] == "complete-with-open-items"


def test_the_boards_empty_clause_is_written_once_per_section():
    """The count and the names are two readings of one fact, so they cannot
    disagree; a second clause would print the same loss twice."""
    from boardwise.cli import _coverage_reasons

    reasons = _coverage_reasons(
        {**CLEAN_COVERAGE, "boardsEmpty": 1, "boardsEmptyNames": ["B2"]}
    )
    assert len(reasons) == 1, reasons
    # No names (a section carrying only the count) still produces a clause — the
    # gate does not depend on the annotation existing. The seam is where the name
    # list would have been: straight from "0 器件" to the following colon.
    bare = _coverage_reasons({**CLEAN_COVERAGE, "boardsEmpty": 2})
    assert len(bare) == 1, bare
    assert "2 块板读出 0 器件：" in bare[0], bare
    assert "B2" in reasons[0] and "）" not in reasons[0].split("（")[0], reasons[0]


def test_the_boards_empty_clause_comes_last_among_the_coverage_clauses():
    """「coverage 理由排最后」 (053) and 126d's `pcbReviewMissing` is last there.

    `boardsEmpty` sits beside the parse clause rather than at the end: it is the
    board-level sibling of ④ (a reading that came out short), and ⑤/③/④ keep
    their places relative to each other. This pins the order so a later batch
    cannot quietly move an existing clause.
    """
    from boardwise.cli import _coverage_reasons

    reasons = _coverage_reasons({
        **CLEAN_COVERAGE,
        "boardsEmpty": 1,
        "boardsEmptyNames": ["B2"],
        "pagesDropped": 2,
        "rulesErrored": ["led"],
        "pcbReviewMissing": True,
    })

    assert len(reasons) == 4, reasons
    assert "B2" in reasons[0]
    assert "页" in reasons[1] and "led" in reasons[2] and "PCB" in reasons[3]
