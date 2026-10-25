"""537D1a: ``boardwise review-read`` — four read-only projections of one report.

Why this file exists. 537D §2 says a routine review must stop hand-writing
one-off JSON parsing scripts: the same four questions were answered by ad-hoc
``python -c`` reads every run, and a mis-typed key in one of them silently
became 「零问题」. This command is the one structured read:

* ``verdict`` — the board-level answer, and **only** ``report.conclusion``.
  ``summary.conclusion`` is a sentence; deriving a verdict dict from it would be
  the exact thing 185/537D forbid ("板级结论仍以 `report.conclusion` 为唯一权威").
  A report with no conclusion section is ``status: "missing"``, never a
  recomputation;
* ``findings`` — the findings list plus the triage ledger's counts, counted
  through checkup's own ``triage_slot_is_closed`` / ``triage_slot_is_manual``.
  A ``needs-manual`` row stays **pending** and is counted again as
  ``warningsNeedsManual``; it is not a way to close a warning. A missing or
  non-list ``findings``/``warning_triage`` is a ``ValueError`` (exit 2), not an
  empty list — "the report did not say" is not "there are none";
* ``crossView`` — every board that carries a crossView dict, in the report's own
  order, with ``title``/``boardUuid`` and the section **verbatim**: ``checked:
  false`` stays false, ``suspected`` / ``missing`` / candidate mappings are not
  filtered, summed or re-judged. No board with a section at all is
  ``status: "missing"`` with ``boards: []`` — a report with no ``pcb_review`` is
  not evidence that the two views agree;
* ``coverage`` — the environment/evidence ledgers and the completion coverage,
  with every section the report does not carry **named** in ``missingSections``
  (in the frozen order environment, evidence, completion). A pre-537C report is
  readable and says what it lacks; nothing is guessed to fill the gap.

What this file also pins, because a read command is a trust boundary:

* the envelope is the same for every section — ``schema``, ``section``,
  ``report: {path, schema}``, ``payload`` — and carries **no** ``ok``-ish field
  that could be mistaken for a board pass;
* the same input bytes produce the same output bytes, twice (stable pretty
  JSON + one trailing newline), on stdout and in a file;
* the input report is never mutated, and neither are the other products beside
  it: ``report.md`` / ``board-report.md`` / ``review-summary.md`` /
  ``live-evidence.json`` sentinels survive byte for byte;
* ``--json PATH`` may create a new file but **must not** overwrite one of the
  five protected inputs of the review directory, however it is spelled
  (``..``, absolute, case): that is exit 2 with every byte unchanged — a
  read-only command may not be the way to destroy the evidence it reads;
* exit codes describe **this read**: 0 projected, 2 unusable input (no object,
  broken JSON, a projection ``ValueError``, an output that cannot be written),
  3 no ``report.json`` at all. None of them is a board verdict;
* no re-gate: ``_completion_from_report`` / ``_completion_section`` /
  ``conclusion_section`` are patched to raise, and all four sections still
  read. Structured reading is not recomputation.

Everything here is anonymous and synthetic — no editor, daemon, project file,
netlist or image, and no real report.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.engines.reviewread import (
    REVIEW_READ_SCHEMA,
    REVIEW_READ_SECTIONS,
    review_read_section,
)

SECTIONS = ("verdict", "findings", "crossView", "coverage", "netlist")
PROTECTED = (
    "report.json",
    "report.md",
    "board-report.md",
    "review-summary.md",
    "live-evidence.json",
)

REPORT_MD_SENTINEL = "# synthetic report.md — review-read 不得改写\n"
BOARD_MD_SENTINEL = "# synthetic board-report.md — review-read 不得改写\n"
SUMMARY_SENTINEL = (
    "# synthetic review-summary\n\n"
    "| 位置 | 结论（人写的） | 证据 |\n"
    "| --- | --- | --- |\n"
    "| PWR/TP1 | 人工分析，只读命令不得覆盖 | 目测 |\n"
)
LIVE_EVIDENCE_SENTINEL = (
    '{"schema": "boardwise.live-evidence/1", "sentinel": true}\n'
)

#: ``summary.conclusion`` is a sentence, deliberately different from the
#: authoritative section: a read that turned it into ``conclusion`` would be the
#: 「从 summary 文案另算一个结论」 this batch forbids.
SUMMARY_SENTENCE = "1 项 ERROR（合成）；见 report.md"


def synthetic_report() -> dict:
    """One fully synthetic report, shaped like ``boardwise.checkup/7``."""
    return {
        "schema": "boardwise.checkup/7",
        "source": {
            "project": {"projectUuid": "proj-synthetic", "name": "SYNTH"},
            "tier": "project-archive",
        },
        "summary": {
            "exitCode": 1,
            "conclusion": SUMMARY_SENTENCE,
            "errorCount": 1,
            "errors": [{"kind": "synthetic", "count": 1}],
            "mayClaimPassed": False,
        },
        "conclusion": {
            "verdict": "incomplete",
            "exitCode": 1,
            "mayClaimPassed": False,
            "mayQuotePassed": False,
            "oneLiner": SUMMARY_SENTENCE,
            "blockers": ["1 项 ERROR"],
        },
        "completion": {
            "verdict": "incomplete",
            "warningsPendingTriage": 2,
            "warningsNeedsManual": 1,
            "verdictWhy": ["1 项 ERROR", "2 条 warning 待分诊"],
            "coverage": {
                "modelEmpty": False,
                "pcbReviewMissing": False,
                "checksRun": ["cross-view", "synthetic"],
            },
        },
        "findings": [
            {
                "rule": "synthetic-rule",
                "severity": "ERROR",
                "message": "合成 finding：不得被命令改写",
                "locations": ["PWR/U1.1"],
            },
            {
                "rule": "synthetic-warn",
                "severity": "WARN",
                "message": "合成 warning finding",
                "locations": ["CTRL/R7.2"],
            },
        ],
        "warning_triage": [
            {
                "key": "boardwise-rule:xtal-load-caps:Y1",
                "source": "rule",
                "text": "合成的一条有文本警告",
                "verdicted": True,
                "verdict": "有害",
                "reason": "合成：文本已判",
            },
            {
                "key": "host-erc:warn",
                "source": "host-erc",
                "text": "",
                "count": 3,
                "verdict": "needs-manual",
                "reason": "合成：来源只有合计，没有逐条文本",
            },
            {
                "key": "boardwise-rule:unjudged:U9",
                "source": "rule",
                "text": "合成的一条还没人判的警告",
            },
        ],
        "pcb_review": {
            "boards": [
                {
                    "title": "SYNTH-B1",
                    "boardUuid": "board-uuid-1",
                    "components": 12,
                    "copperLayers": 4,
                    "findings": [0],
                    "crossView": {
                        "checked": False,
                        "lonelyPins": [],
                        "reason": "合成：归档两侧都没读到可比对的网",
                    },
                },
                {
                    "title": "SYNTH-B2",
                    "boardUuid": "board-uuid-2",
                    "components": 7,
                    "copperLayers": 2,
                    "findings": [],
                    "crossView": {
                        "checked": True,
                        "status": "suspected",
                        "lonelyPins": [{"net": "SYNTH_NET", "pins": ["U1.44"]}],
                        "candidateMappings": [
                            {
                                "net": "SYNTH_NET",
                                "schematicRef": "U1",
                                "schematicPin": "44",
                                "sources": ["archivePcb", "archiveSchematic"],
                            }
                        ],
                    },
                },
            ]
        },
        "environment": {
            "connectorVersion": {"expected": "0.0.0", "running": "0.0.0"},
            "limitations": [{"code": "synthetic", "note": "合成环境限制"}],
        },
        "evidence": {
            "schema": "boardwise.review-evidence/1",
            "channels": {
                "liveSchematic": {"status": "missing"},
                "archivePcb": {"status": "ok"},
                "livePcb": {"status": "missing"},
                "schematicImage": {"status": "ok"},
                "pcbImage": {"status": "missing"},
                "datasheets": {"status": "unavailable"},
            },
            "delivery": {
                "status": "partial",
                "note": "合成：delivery 只描述证据覆盖",
                "requiredDisclosures": [{"code": "live-pcb-missing"}],
            },
        },
    }


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def run_cli(*argv: str) -> int:
    return cli.main(["review-read", *argv])


def write_out(tmp_path: Path, report: dict | None = None) -> Path:
    """A review directory: report.json plus the four products beside it."""
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report if report is not None else synthetic_report(),
                   ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out / "report.md").write_text(REPORT_MD_SENTINEL, encoding="utf-8")
    (out / "board-report.md").write_text(BOARD_MD_SENTINEL, encoding="utf-8")
    (out / "review-summary.md").write_text(SUMMARY_SENTINEL, encoding="utf-8")
    (out / "live-evidence.json").write_text(LIVE_EVIDENCE_SENTINEL, encoding="utf-8")
    return out


def hashes(out: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((out / name).read_bytes()).hexdigest()
        for name in PROTECTED
        if (out / name).exists()
    }


def read_stdout_json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == "", captured.err
    assert captured.out.endswith("\n")
    return json.loads(captured.out)


# ---------------------------------------------------------------------------
# 1) the four projections
# ---------------------------------------------------------------------------


def test_verdict_projects_the_authoritative_conclusion_verbatim():
    report = synthetic_report()
    payload = review_read_section(report, "verdict")

    assert payload == {
        "status": "ok",
        "conclusion": report["conclusion"],
        "completion": report["completion"],
        "summaryExitCode": 1,
        "delivery": report["evidence"]["delivery"],
        "authority": "report.conclusion",
    }
    assert payload["conclusion"] is not report["conclusion"]


def test_verdict_missing_conclusion_is_not_fabricated_from_summary():
    report = synthetic_report()
    report.pop("conclusion")

    payload = review_read_section(report, "verdict")

    assert payload["status"] == "missing"
    assert payload["conclusion"] is None
    # The summary still carries its sentence; nothing may promote it.
    assert report["summary"]["conclusion"] == SUMMARY_SENTENCE
    assert payload["authority"] == "report.conclusion"
    assert payload["completion"] == report["completion"]


def test_verdict_non_dict_conclusion_is_missing_and_delivery_is_null_without_evidence():
    report = synthetic_report()
    report["conclusion"] = SUMMARY_SENTENCE  # a string is not a conclusion section
    report.pop("evidence")

    payload = review_read_section(report, "verdict")

    assert payload["status"] == "missing"
    assert payload["conclusion"] is None
    assert payload["delivery"] is None


def test_verdict_without_completion_is_null_not_invented():
    report = synthetic_report()
    report.pop("completion")
    report.pop("summary")

    payload = review_read_section(report, "verdict")

    assert payload["status"] == "ok"
    assert payload["completion"] is None
    assert payload["summaryExitCode"] is None


def test_findings_projects_the_list_and_counts_needs_manual_as_pending():
    report = synthetic_report()

    payload = review_read_section(report, "findings")

    assert payload["status"] == "ok"
    assert payload["findings"] == report["findings"]
    assert payload["warning_triage"] == report["warning_triage"]
    # closed: the "有害" row with text. pending: needs-manual + unjudged.
    assert payload["warningsPendingTriage"] == 2
    assert payload["warningsNeedsManual"] == 1
    assert payload["findings"] is not report["findings"]


def test_findings_empty_list_is_a_legal_empty_answer():
    report = synthetic_report()
    report["findings"] = []
    report["warning_triage"] = []

    payload = review_read_section(report, "findings")

    assert payload["status"] == "ok"
    assert payload["findings"] == []
    assert payload["warning_triage"] == []
    assert payload["warningsPendingTriage"] == 0
    assert payload["warningsNeedsManual"] == 0


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r.pop("findings"), id="findings-absent"),
        pytest.param(lambda r: r.update(findings={"rows": []}), id="findings-dict"),
        pytest.param(lambda r: r.update(findings=None), id="findings-null"),
        pytest.param(lambda r: r.pop("warning_triage"), id="triage-absent"),
        pytest.param(lambda r: r.update(warning_triage={"key": "x"}), id="triage-dict"),
    ],
)
def test_findings_refuses_a_ledger_it_cannot_read(mutate):
    report = synthetic_report()
    mutate(report)

    with pytest.raises(ValueError):
        review_read_section(report, "findings")


def test_cross_view_keeps_every_board_verbatim_even_checked_false():
    report = synthetic_report()

    payload = review_read_section(report, "crossView")

    assert payload["status"] == "ok"
    assert [board["title"] for board in payload["boards"]] == ["SYNTH-B1", "SYNTH-B2"]
    assert [board["boardUuid"] for board in payload["boards"]] == [
        "board-uuid-1",
        "board-uuid-2",
    ]
    first, second = payload["boards"]
    assert first["crossView"] == report["pcb_review"]["boards"][0]["crossView"]
    assert first["crossView"]["checked"] is False
    assert second["crossView"] == report["pcb_review"]["boards"][1]["crossView"]
    # suspected + the candidate mapping are carried, not resolved or filtered.
    assert second["crossView"]["status"] == "suspected"
    assert second["crossView"]["candidateMappings"] == [
        {
            "net": "SYNTH_NET",
            "schematicRef": "U1",
            "schematicPin": "44",
            "sources": ["archivePcb", "archiveSchematic"],
        }
    ]
    assert first["crossView"] is not report["pcb_review"]["boards"][0]["crossView"]


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda r: r.pop("pcb_review"), id="pcb-review-absent"),
        pytest.param(lambda r: r.update(pcb_review={}), id="pcb-review-empty"),
        pytest.param(
            lambda r: r["pcb_review"].update(
                boards=[{"title": "B", "boardUuid": "u", "components": 1}]
            ),
            id="boards-without-cross-view",
        ),
    ],
)
def test_cross_view_without_any_section_is_missing_and_empty(mutate):
    report = synthetic_report()
    mutate(report)

    payload = review_read_section(report, "crossView")

    assert payload == {"status": "missing", "boards": []}


def test_coverage_names_every_missing_section_in_order():
    report = synthetic_report()
    report.pop("environment")
    report.pop("evidence")
    report.pop("completion")

    payload = review_read_section(report, "coverage")

    assert payload == {
        "status": "missing",
        "environment": None,
        "evidence": None,
        "completionCoverage": None,
        "verdict": None,
        "missingSections": ["environment", "evidence", "completion"],
    }


def test_coverage_partial_report_names_only_what_is_absent():
    report = synthetic_report()
    report["environment"] = "not-a-dict"

    payload = review_read_section(report, "coverage")

    assert payload["status"] == "missing"
    assert payload["missingSections"] == ["environment"]
    assert payload["environment"] is None
    assert payload["evidence"] == report["evidence"]
    assert payload["completionCoverage"] == report["completion"]["coverage"]
    assert payload["verdict"] == "incomplete"


def test_coverage_ok_copies_both_ledgers():
    report = synthetic_report()

    payload = review_read_section(report, "coverage")

    assert payload["status"] == "ok"
    assert payload["missingSections"] == []
    assert payload["environment"] == report["environment"]
    assert payload["evidence"] == report["evidence"]
    assert payload["environment"] is not report["environment"]
    assert payload["evidence"] is not report["evidence"]
    assert payload["completionCoverage"] == report["completion"]["coverage"]
    assert payload["verdict"] == "incomplete"


def test_coverage_completion_without_the_two_keys_is_null_not_guessed():
    report = synthetic_report()
    report["completion"] = {"warningsPendingTriage": 0}

    payload = review_read_section(report, "coverage")

    assert payload["status"] == "ok"
    assert payload["completionCoverage"] is None
    assert payload["verdict"] is None


def test_unknown_section_is_refused_by_name():
    with pytest.raises(ValueError):
        review_read_section(synthetic_report(), "everything")
    with pytest.raises(ValueError):
        review_read_section(synthetic_report(), "")


@pytest.mark.parametrize("value", [None, [], "report", 7, ["conclusion"]])
def test_a_non_object_is_refused_by_the_api_too(value):
    with pytest.raises(ValueError):
        review_read_section(value, "verdict")


@pytest.mark.parametrize("section", SECTIONS)
def test_projection_never_mutates_the_report(section):
    report = synthetic_report()
    before = copy.deepcopy(report)

    payload = review_read_section(report, section)
    assert report == before

    # And a caller that edits the payload cannot reach back into the report.
    if isinstance(payload, dict):
        payload["status"] = "tampered"
        payload["__probe__"] = {"deep": True}
        for value in payload.values():
            if isinstance(value, list):
                value.append({"injected": True})
    assert report == before


# ---------------------------------------------------------------------------
# 2) the CLI: envelope, stdout, file, exit codes
# ---------------------------------------------------------------------------


def test_schema_and_sections_are_the_contract_names():
    assert REVIEW_READ_SCHEMA == "boardwise.review-read/1"
    # 537D1a2b adds exactly one section, between `coverage` and `netlist`; the
    # four earlier ones and the netlist keep their places and signatures.
    assert tuple(REVIEW_READ_SECTIONS) == (*SECTIONS[:-1], "artifacts", SECTIONS[-1])


@pytest.mark.parametrize("section", SECTIONS)
def test_stdout_is_the_same_envelope_for_every_section(section, tmp_path, capsys):
    out = write_out(tmp_path)

    assert run_cli("--out", str(out), "--section", section) == 0
    envelope = read_stdout_json(capsys)

    assert set(envelope) == {"schema", "section", "report", "payload"}
    assert envelope["schema"] == REVIEW_READ_SCHEMA
    assert envelope["section"] == section
    assert Path(envelope["report"]["path"]) == (out / "report.json").resolve()
    assert envelope["report"]["schema"] == "boardwise.checkup/7"
    assert envelope["payload"] == review_read_section(synthetic_report(), section)
    # no field that could be mistaken for a board pass
    assert "ok" not in envelope
    assert "passed" not in envelope


def test_stdout_is_stable_utf8_pretty_json_and_repeats_byte_for_byte(tmp_path, capsys):
    out = write_out(tmp_path)

    assert run_cli("--out", str(out), "--section", "findings") == 0
    first = capsys.readouterr().out
    assert run_cli("--out", str(out), "--section", "findings") == 0
    second = capsys.readouterr().out

    assert first == second
    assert first.endswith("\n") and not first.endswith("\n\n")
    assert first.startswith("{\n  ")
    # UTF-8 text is written as text, not \u escapes: this is the plugin's feed.
    assert "合成" in first
    assert "\\u" not in first
    assert json.loads(first)["section"] == "findings"


def test_dash_writes_the_envelope_to_stdout_and_creates_nothing(tmp_path, capsys):
    out = write_out(tmp_path)
    before = sorted(path.name for path in out.iterdir())

    assert run_cli("--out", str(out), "--section", "verdict", "--json", "-") == 0
    envelope = read_stdout_json(capsys)

    assert envelope["section"] == "verdict"
    assert sorted(path.name for path in out.iterdir()) == before


def test_json_path_writes_the_same_bytes_and_keeps_stdout_empty(tmp_path, capsys):
    out = write_out(tmp_path)
    target = tmp_path / "projection.json"

    assert run_cli(
        "--out", str(out), "--section", "coverage", "--json", str(target)
    ) == 0
    captured = capsys.readouterr()
    assert captured.out == ""

    blob = target.read_bytes()
    assert blob.endswith(b"\n")
    assert json.loads(blob.decode("utf-8"))["section"] == "coverage"

    # The file form and the stdout form are the same bytes.
    assert run_cli("--out", str(out), "--section", "coverage") == 0
    assert capsys.readouterr().out.encode("utf-8") == blob

    # And so is a second write to the same path.
    assert run_cli(
        "--out", str(out), "--section", "coverage", "--json", str(target)
    ) == 0
    assert capsys.readouterr().out == ""
    assert target.read_bytes() == blob


def test_a_missing_report_is_exit_three(tmp_path, capsys):
    out = tmp_path / "nothing-here"
    out.mkdir()

    assert run_cli("--out", str(out), "--section", "verdict") == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "report.json" in captured.err

    assert run_cli("--out", str(tmp_path / "absent"), "--section", "verdict") == 3
    assert "report.json" in capsys.readouterr().err


def test_broken_report_json_is_exit_two(tmp_path, capsys):
    out = write_out(tmp_path)
    (out / "report.json").write_text("{not json", encoding="utf-8")

    assert run_cli("--out", str(out), "--section", "verdict") == 2
    assert capsys.readouterr().out == ""


def test_a_report_that_is_not_an_object_is_exit_two(tmp_path, capsys):
    out = write_out(tmp_path)
    (out / "report.json").write_text("[1, 2, 3]\n", encoding="utf-8")

    assert run_cli("--out", str(out), "--section", "verdict") == 2
    assert capsys.readouterr().out == ""


def test_a_projection_value_error_is_exit_two(tmp_path, capsys):
    report = synthetic_report()
    report.pop("findings")
    out = write_out(tmp_path, report)

    assert run_cli("--out", str(out), "--section", "findings") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "findings" in captured.err


def test_an_output_that_cannot_be_written_is_exit_two(tmp_path, capsys):
    out = write_out(tmp_path)

    # A directory as the target, and a target whose parent does not exist.
    assert run_cli(
        "--out", str(out), "--section", "verdict", "--json", str(tmp_path)
    ) == 2
    assert capsys.readouterr().out == ""
    assert run_cli(
        "--out", str(out), "--section", "verdict",
        "--json", str(tmp_path / "no-such-dir" / "out.json"),
    ) == 2
    assert capsys.readouterr().out == ""


def test_section_and_out_are_required(tmp_path):
    with pytest.raises(SystemExit) as missing_section:
        run_cli("--out", str(tmp_path))
    assert missing_section.value.code == 2

    with pytest.raises(SystemExit) as missing_out:
        run_cli("--section", "verdict")
    assert missing_out.value.code == 2

    with pytest.raises(SystemExit) as bad_section:
        run_cli("--out", str(tmp_path), "--section", "everything")
    assert bad_section.value.code == 2


# ---------------------------------------------------------------------------
# 3) read-only: the products beside the report are not this command's to write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section", SECTIONS)
def test_the_whole_review_directory_is_byte_identical_after_a_read(
    section, tmp_path, capsys
):
    out = write_out(tmp_path)
    before = hashes(out)

    assert run_cli("--out", str(out), "--section", section) == 0
    capsys.readouterr()

    assert hashes(out) == before


@pytest.mark.parametrize(
    "alias",
    [
        "report.json",
        "report.md",
        "board-report.md",
        "review-summary.md",
        "live-evidence.json",
    ],
)
def test_json_path_cannot_overwrite_the_inputs_it_reads(alias, tmp_path, capsys):
    out = write_out(tmp_path)
    before = hashes(out)

    assert run_cli(
        "--out", str(out), "--section", "verdict", "--json", str(out / alias)
    ) == 2
    assert hashes(out) == before
    captured = capsys.readouterr()
    assert captured.out == ""

    # The same file spelled with `..` and in absolute form is the same file.
    spelled = out / ".." / out.name / alias
    assert run_cli(
        "--out", str(out), "--section", "verdict", "--json", str(spelled)
    ) == 2
    assert hashes(out) == before
    assert capsys.readouterr().out == ""

    resolved = str((out / alias).resolve())
    assert run_cli(
        "--out", str(out), "--section", "verdict", "--json", resolved
    ) == 2
    assert hashes(out) == before
    assert capsys.readouterr().out == ""


def test_json_path_may_still_create_a_new_file_beside_the_report(tmp_path, capsys):
    out = write_out(tmp_path)
    before = hashes(out)
    target = out / "review-read.json"

    assert run_cli(
        "--out", str(out), "--section", "findings", "--json", str(target)
    ) == 0
    capsys.readouterr()

    assert target.exists()
    assert hashes(out) == before  # the five inputs untouched, one new file added


# ---------------------------------------------------------------------------
# 4) structured reading is not recomputation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section", SECTIONS)
def test_no_re_gate_is_called(section, tmp_path, capsys, monkeypatch):
    out = write_out(tmp_path)

    def refuse(*args, **kwargs):  # pragma: no cover - only on the wrong path
        raise AssertionError("review-read 调用了 re-gate/写口")

    for name in (
        "_completion_from_report",
        "_completion_section",
        "conclusion_section",
        "_apply_warning_triage",
    ):
        monkeypatch.setattr(cli, name, refuse, raising=True)

    assert run_cli("--out", str(out), "--section", section) == 0
    read_stdout_json(capsys)


def test_the_projection_module_does_not_reach_back_into_the_cli():
    import ast
    import inspect

    import boardwise.engines.reviewread as reviewread

    tree = ast.parse(inspect.getsource(reviewread))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    assert not any(name.endswith("cli") or "boardwise.cli" in name for name in imported)
