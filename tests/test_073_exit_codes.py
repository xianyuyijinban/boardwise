"""073: an `incomplete` verdict is exit 3, and two more epru shape gates.

Two families, one root — *the run that could not state a result must not exit 0*,
and *a record whose body is the wrong shape must not crash the parser*:

* **A — the exit code of `incomplete`** (岳's ruling on the CI hole 072 left open):
  `completion.verdict: incomplete` means the review did not see the whole board, so
  nothing may be stated from it — yet both commands exited 0 as long as no ERROR was
  found, and a CI reads exit 0 as "passed". They now return **3**, the code this CLI
  already uses for "the state cannot be stated" (a live model no tier produced, a
  write whose outcome is unknown, an update with no conclusion). The priority is
  `2` bad input > `1` an ERROR was found > `3` incomplete > `0`, so this only ever
  raises a 0: a run with an ERROR keeps its 1, and `complete-with-open-items` keeps
  its 0 (an open item is a statement about the board; `incomplete` is the absence
  of one).
* **B — `epru.py`'s own shape gates**: a `COMPONENT` record whose ``attrs`` is a
  list/str/int used to escape as a bare `TypeError` traceback with exit 1 (the same
  code as "the board has an ERROR") or as an internal ``dictionary update sequence``
  message. The same family #28 and 072 closed for `.enet` and the DEVICE records:
  one `NetlistShapeError`, one `boardwise:` line naming the record and the field,
  exit 2, no traceback.

Offline only: fixtures are read, never written; crafted archives live in `tmp_path`.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.parsers.epru import collect_pcb_context
from boardwise.parsers.enet import NetlistShapeError

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
SHELF = ROOT / "blocklib" / "parts.json"
GOLDEN = FIXTURES / "ch340_golden.epro2"
BOARD24V = FIXTURES / "board24v.enet"
#: A board with an ERROR for the offline rule engine (`DCDC-12V9V转5V3V3`): the
#: priority test needs a run that must keep exit 1, not move to 3.
DCDC = FIXTURES / "DCDC-12V9V转5V3V3_2026-09-27.epro2"
INJECTED = ROOT / "reviewsets" / "injected"
LDO_NO_HEADROOM = INJECTED / "ldo-no-headroom.epro2"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    """Never touch the real `~/.boardwise` (config, audit, sidecars)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))


def _truncated(source: Path, target: Path, *, keep: float = 1 / 3) -> Path:
    """Issue #29's reproduction: cut the inner `.epru`, repack a **legal** ZIP."""
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


# --------------------------------------------------------------------------
# A — exit 3 for an `incomplete` verdict
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "board",
    [GOLDEN, FIXTURES / "llc_board.epro2", INJECTED / "fixed-base.epro2"],
    ids=["ch340_golden", "llc_board", "fixed-base"],
)
def test_an_incomplete_verdict_without_errors_exits_3(board, tmp_path, capsys):
    """The CI hole: `verdict: incomplete` used to come back as exit 0 — "passed"."""
    code, report, _out = _checkup(tmp_path, board, name=board.stem)
    printed = capsys.readouterr().out

    assert report is not None
    assert report["completion"]["verdict"] == "incomplete"
    assert report["summary"]["errorCount"] == 0, "this shape is the no-ERROR one"
    assert code == 3, "incomplete and no ERROR: 3, not 0 (a CI reads 0 as passed)"
    assert "  exit: 3" in printed
    assert cli.INCOMPLETE_EXIT_SENTENCE in printed, (
        "exit 3 gets its own sentence — the exit-0 wording ('nothing is an ERROR') "
        "would read as a pass"
    )


def test_the_truncated_archive_the_coverage_gate_catches_is_exit_3(tmp_path, capsys):
    """072's #29 reproduction, now with the exit code the verdict always implied."""
    trunc = _truncated(GOLDEN, tmp_path / "trunc.epro2")

    code, report, out = _checkup(tmp_path, trunc, name="trunc-out")
    capsys.readouterr()

    assert report["completion"]["verdict"] == "incomplete"
    assert report["completion"]["coverage"]["modelEmpty"] is True
    assert code == 3


def test_the_report_and_the_process_agree_on_the_exit_code(tmp_path, capsys):
    """#15's single-source discipline: one value, three renderings.

    `summary.exitCode`, the markdown header and the process exit code are all the
    run's own decision — a report that says 3 while the shell saw 0 (or the other
    way round) is the disagreement issue #15 was about.
    """
    code, report, out = _checkup(tmp_path, GOLDEN, name="agree-out")
    capsys.readouterr()

    assert report["summary"]["exitCode"] == 3
    assert code == 3
    assert f"（退出码 {code}）" in (out / "report.md").read_text(encoding="utf-8")


def test_an_error_keeps_exit_1_and_beats_the_incomplete_code(tmp_path, capsys):
    """The priority: `1` (an ERROR was found) > `3` (nothing may be stated)."""
    code, report, _out = _checkup(tmp_path, DCDC, name="dcdc")
    printed = capsys.readouterr().out

    assert report["summary"]["errorCount"] > 0
    assert report["completion"]["verdict"] == "incomplete"
    assert code == 1
    assert "  exit: 1" in printed
    assert "(ERROR present — see the errors above)" in printed


def test_a_bad_input_still_returns_2(tmp_path, capsys):
    """Bad input outranks everything: 2 > 1 > 3 > 0."""
    code = cli.main(
        [
            "checkup", "--file", str(tmp_path / "does-not-exist.epro2"),
            "--out", str(tmp_path / "nope"), "--library", str(SHELF),
        ]
    )
    capsys.readouterr()

    assert code == 2


@pytest.mark.parametrize(
    "code,verdict,expected",
    [
        (0, "complete", 0),
        (0, "complete-with-open-items", 0),
        (0, "incomplete", 3),
        (1, "incomplete", 1),
        (1, "complete", 1),
        (2, "incomplete", 2),
    ],
)
def test_the_mapping_only_ever_raises_a_zero(code, verdict, expected):
    """`complete-with-open-items` stays 0 on purpose — 岳 named `incomplete` only."""
    assert cli._exit_code_with_verdict(code, verdict) == expected


def test_review_of_an_empty_model_is_exit_3(tmp_path, capsys):
    """`review`'s own `incomplete`: the reading came out empty (072's #29 predicate)."""
    empty = tmp_path / "empty.enet"
    empty.write_text(
        json.dumps(
            {"version": "2.0.0", "components": {}, "designRule": {},
             "differentialPair": {}, "netClass": {}, "equalLengthNetGroup": {}}
        ),
        encoding="utf-8",
    )

    code = cli.main(["review", str(empty)])
    printed = capsys.readouterr().out

    assert "(0 components, 0 nets)" in printed
    assert cli.EMPTY_MODEL_NOTE in printed
    assert code == 3
    assert cli.INCOMPLETE_EXIT_SENTENCE in printed


def test_review_of_the_pcb_view_that_read_nothing_is_exit_3(capsys):
    """The narrower sentence (wrong view) is the same state: nothing was reviewed."""
    code = cli.main(["review", str(GOLDEN), "--view", "pcb"])
    printed = capsys.readouterr().out

    assert cli.EMPTY_PCB_VIEW_NOTE in printed
    assert cli.EMPTY_MODEL_NOTE not in printed
    assert code == 3


def test_review_that_read_something_still_exits_0(capsys):
    """The对照: a reading with content is not touched by any of this."""
    code = cli.main(["review", str(BOARD24V)])
    printed = capsys.readouterr().out

    assert "components, " in printed and "(0 components" not in printed
    assert code == 0
    assert cli.INCOMPLETE_EXIT_SENTENCE not in printed


def test_review_with_an_error_keeps_exit_1(capsys):
    """`review` keeps its documented 1 for a found ERROR — 3 never masks it."""
    code = cli.main(["review", str(LDO_NO_HEADROOM)])
    printed = capsys.readouterr().out

    assert "ERROR" in printed
    assert code == 1


# --------------------------------------------------------------------------
# B — epru record bodies: one shape gate, one sentence, exit 2
# --------------------------------------------------------------------------


def _pcb_archive(target: Path, records: list[str]) -> Path:
    """A `.epro2` whose PCB document carries `records` (one envelope per line)."""
    return _archive(target, pcb_records=records)


def _archive(
    target: Path,
    *,
    pcb_records: list[str] | None = None,
    footprint_records: list[str] | None = None,
) -> Path:
    """A `.epro2` with an optional FOOTPRINT document and one PCB document."""
    records: list[str] = []
    if footprint_records:
        records.append(
            '{"type":"DOCHEAD","ticket":0,"id":"f1"}'
            '||{"docType":"FOOTPRINT","uuid":"fp1","editVersion":"1"}'
        )
        records.extend(footprint_records)
    records.append(
        '{"type":"DOCHEAD","ticket":0,"id":"p1"}'
        '||{"docType":"PCB","uuid":"pcb1","editVersion":"1"}'
    )
    records.extend(pcb_records or [])
    return _synthetic_epro2(target, records)


#: The `attrs` shapes issue #28's family measured: a non-object is never a mapping.
#: ``int`` used to be a bare `TypeError` traceback with exit 1; ``str`` and a list
#: of strings were ``ValueError``s whose message was the interpreter's ("dictionary
#: update sequence element #0 has length 10"), naming no record and no field.
BAD_ATTRS: dict[str, str] = {
    "list": '["Designator","U1"]',
    "str": '"Designator"',
    "int": "5",
    "list-of-pairs": '[["Designator","U1"]]',
}


@pytest.mark.parametrize("shape", sorted(BAD_ATTRS), ids=sorted(BAD_ATTRS))
def test_a_component_attrs_that_is_not_an_object_is_a_clean_exit_2(shape, tmp_path, capsys):
    board = _pcb_archive(
        tmp_path / f"attrs-{shape}.epro2",
        [
            '{"type":"COMPONENT","ticket":1,"id":"c1"}'
            f'||{{"x":0,"y":0,"attrs":{BAD_ATTRS[shape]}}}',
        ],
    )

    code = cli.main(["review", str(board), "--view", "pcb"])
    captured = capsys.readouterr()

    assert code == 2, "a wrong shape is unusable input, not a defect found on the board"
    assert "Traceback" not in captured.err
    assert "c1" in captured.err and "attrs" in captured.err, (
        "the sentence names the record and the field: that is the useful half"
    )
    assert "不是对象" in captured.err


def test_the_missing_and_null_attrs_keys_still_parse(tmp_path, capsys):
    """The regression guard for the gate: absence and `null` are not shape errors."""
    board = _pcb_archive(
        tmp_path / "attrs-none.epro2",
        [
            '{"type":"COMPONENT","ticket":1,"id":"c1"}||{"x":1,"y":2}',
            '{"type":"COMPONENT","ticket":2,"id":"c2"}||{"x":3,"y":4,"attrs":null}',
            '{"type":"COMPONENT","ticket":3,"id":"c3"}||{"x":5,"y":6,"attrs":{}}',
            '{"type":"COMPONENT","ticket":4,"id":"c4"}'
            '||{"x":7,"y":8,"attrs":{"Designator":"U9"}}',
        ],
    )

    code = cli.main(["review", str(board), "--view", "pcb"])
    printed = capsys.readouterr().out

    assert code == 0
    assert "(4 components, 0 nets)" in printed


def test_the_parser_raises_its_own_type_and_names_the_place(tmp_path):
    """`NetlistShapeError`, not `TypeError`/`AttributeError`: one class, one channel."""
    from boardwise.parsers.epru import load_epro2_source

    board = _pcb_archive(
        tmp_path / "raises.epro2",
        ['{"type":"COMPONENT","ticket":1,"id":"c1"}||{"x":0,"y":0,"attrs":[1]}'],
    )
    source = load_epro2_source(board)

    with pytest.raises(NetlistShapeError) as caught:
        collect_pcb_context(source.first_document("PCB"), {}, source.stats)

    assert "attrs" in str(caught.value) and "c1" in str(caught.value)


#: The other two body fields this module used to convert blind: a `PAD` record's
#: `defaultPad` block (`block.get(...)` on a list is an `AttributeError`) and a
#: `VIA`'s `unusedInnerLayers` (`list(5)` is a `TypeError`, and `list("12")`
#: silently became two layers). A pad template lives in a **FOOTPRINT** document
#: (`pad_templates` walks exactly those), a via in the PCB document.
BAD_BLOCKS: dict[str, tuple[str, str, str]] = {
    "pad-defaultpad-is-a-list": (
        '{"type":"PAD","ticket":1,"id":"pad1"}||{"num":"1","defaultPad":[1,2]}',
        "defaultPad",
        "footprint",
    ),
    "via-unused-inner-layers-is-an-int": (
        '{"type":"VIA","ticket":2,"id":"v1"}||{"centerX":0,"centerY":0,'
        '"unusedInnerLayers":5}',
        "unusedInnerLayers",
        "pcb",
    ),
    "via-unused-inner-layers-is-a-string": (
        '{"type":"VIA","ticket":3,"id":"v2"}||{"centerX":0,"centerY":0,'
        '"unusedInnerLayers":"12"}',
        "unusedInnerLayers",
        "pcb",
    ),
}


@pytest.mark.parametrize("shape", sorted(BAD_BLOCKS), ids=sorted(BAD_BLOCKS))
def test_the_same_family_blocks_are_refused_the_same_way(shape, tmp_path, capsys):
    record, field, document = BAD_BLOCKS[shape]
    board = _archive(
        tmp_path / f"{shape}.epro2",
        pcb_records=[record] if document == "pcb" else [],
        footprint_records=[record] if document == "footprint" else [],
    )

    code = cli.main(["review", str(board), "--view", "pcb"])
    captured = capsys.readouterr()

    assert code == 2
    assert "Traceback" not in captured.err
    assert field in captured.err
