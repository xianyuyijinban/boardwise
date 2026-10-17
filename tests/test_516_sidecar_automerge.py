"""516 A3: a re-run of ``checkup`` folds the reviewer's ``needs-datasheet.json`` back in.

岳's accident: 15 ``needs-datasheet`` marks, then a re-run of ``checkup`` — and
``reviewerMarked`` read **0**. The section is rebuilt from the board on every
run, so the marks only survived as a line in ``source.notes`` telling the reader
to run ``boardwise need-datasheet`` again (once per mark). The triage sidecar has
auto-merged since 063; the datasheet sidecar now does the same
(:func:`boardwise.engines.checkup.merge_needs_datasheet_sidecar`), reports what it
did on ``completion.sidecarNeedsDatasheet``, and names the marks it could not
match instead of dropping them.

Also pinned here: 516 B2's ``--pins`` semantics — the default is **merge** (a
later call unions pins), and ``--replace-pins`` is the explicit overwrite.

The fixture is the real CH340G board; every command is the real CLI, offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import boardwise.cli as cli
from boardwise.cli import NEEDS_DATASHEET_FILE, NEEDS_DATASHEET_SIDECAR_SCHEMA
from boardwise.engines.checkup import TRIGGER_MARKED

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "ch340_golden.epro2"


def _checkup(out: Path, *extra: str) -> dict:
    code = cli.main(["checkup", "--file", str(GOLDEN), "--out", str(out), *extra])
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    verdict = report["completion"]["verdict"]
    expected = 3 if verdict == "incomplete" else 0
    assert code == expected, f"checkup exited {code} for verdict {verdict}"
    return report


def _write_sidecar(out: Path, marks: list[dict]) -> Path:
    path = out / NEEDS_DATASHEET_FILE
    path.write_text(
        json.dumps(
            {"schema": NEEDS_DATASHEET_SIDECAR_SCHEMA, "marks": marks},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    return path


def _marked(report: dict) -> list[dict]:
    return [row for row in report["needs_datasheet"] if row["trigger"] == "marked"]


def test_a_rerun_keeps_the_reviewers_marks(tmp_path, monkeypatch):
    """15 marks → re-run → ``reviewerMarked`` **stays** 15 (the 岳 symptom in reverse)."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    first = _checkup(out)
    designators = list(first["model"]["designators"])
    assert len(designators) >= 15, designators
    parts = designators[:15]
    _write_sidecar(out, [
        {"part": part, "pin": "", "reason": "datasheet 未到", "at": "2026-10-17T00:00:00+0800"}
        for part in parts
    ])

    second = _checkup(out)
    assert second["completion"]["reviewerMarked"] == 15
    assert len(_marked(second)) == 15
    assert second["completion"]["sidecarNeedsDatasheet"] == {"merged": 15, "unmatched": 0}
    assert {row["part"] for row in _marked(second)} == set(parts)
    # ... and the notes say what happened rather than 「跑 need-datasheet 重新合并」.
    notes = " | ".join(second.get("source", {}).get("notes") or [])
    assert "自动并入" in notes


def test_a_mark_for_a_vanished_designator_is_reported_not_dropped(tmp_path, monkeypatch):
    """One of 15 marks points at no part: merged 14, unmatched 1, and a note."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    first = _checkup(out)
    parts = list(first["model"]["designators"])[:14]
    marks = [
        {"part": part, "pin": "", "reason": "datasheet 未到", "at": "x"}
        for part in parts
    ]
    marks.append({"part": "U99", "pin": "", "reason": "这是错位号", "at": "x"})
    _write_sidecar(out, marks)

    second = _checkup(out)
    assert second["completion"]["sidecarNeedsDatasheet"] == {"merged": 14, "unmatched": 1}
    assert second["completion"]["reviewerMarked"] == 14
    notes = " | ".join(second.get("source", {}).get("notes") or [])
    assert "没有对应器件" in notes
    # The unmatched mark stays in the sidecar — it is the audit trail.
    sidecar = json.loads((out / NEEDS_DATASHEET_FILE).read_text(encoding="utf-8"))
    assert any(mark["part"] == "U99" for mark in sidecar["marks"])


def test_without_a_sidecar_nothing_changes(tmp_path, monkeypatch):
    """No ``needs-datasheet.json`` → the old empty-marks reading, and the key says 0."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    report = _checkup(out)
    assert report["completion"]["sidecarNeedsDatasheet"] == {"merged": 0, "unmatched": 0}
    assert report["completion"]["reviewerMarked"] == 0
    assert not (out / NEEDS_DATASHEET_FILE).exists()


def test_the_batch_merge_flag_imports_a_whole_sidecar(tmp_path, monkeypatch):
    """``need-datasheet --merge <file>`` batches what used to take one call per part."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    report = _checkup(out)
    parts = list(report["model"]["designators"])[:5]
    incoming = tmp_path / "incoming.json"
    incoming.write_text(
        json.dumps({
            "schema": NEEDS_DATASHEET_SIDECAR_SCHEMA,
            "marks": [
                {"part": part, "pin": "3", "reason": "手册未到", "at": "x"}
                for part in parts
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    code = cli.main([
        "need-datasheet", "--out", str(out), "--merge", str(incoming),
    ])
    assert code == 0
    after = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert after["completion"]["reviewerMarked"] == 5
    assert {row["part"] for row in _marked(after)} == set(parts)


def test_pins_merge_by_default_and_replace_pins_overwrites(tmp_path, monkeypatch):
    """516 B2: two calls **union** a designator's pins; ``--replace-pins`` overwrites."""
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"
    report = _checkup(out)
    part = report["model"]["designators"][0]

    assert cli.main([
        "need-datasheet", "--out", str(out), "--part", part,
        "--pins", "19,20,23", "--reason", "r1",
    ]) == 0
    assert cli.main([
        "need-datasheet", "--out", str(out), "--part", part,
        "--pins", "1,2,3", "--reason", "r2",
    ]) == 0
    merged = json.loads((out / "report.json").read_text(encoding="utf-8"))
    row = next(r for r in _marked(merged) if r["part"] == part)
    assert row["pins"] == ["19", "20", "23", "1", "2", "3"], (
        "the default is union: the second call must not drop the first call's pins"
    )

    assert cli.main([
        "need-datasheet", "--out", str(out), "--part", part,
        "--pins", "7", "--reason", "r3", "--replace-pins",
    ]) == 0
    replaced = json.loads((out / "report.json").read_text(encoding="utf-8"))
    row = next(r for r in _marked(replaced) if r["part"] == part)
    assert row["pins"] == ["7"]
