"""516 C: the small polish items from 岳's 实板 A feedback.

C1 the closing line names the rule families it counts; C2 ``--intent`` is made
absolute so a relative path cannot silently miss after a ``cd``; C5 the CLI sets
its standard streams to UTF-8 (already true since an earlier batch — pinned here
so it cannot regress silently).

C3 (`pypdf` needs Python >= 3.9) and C4 (`rule_id` naming) are pinned where they
live: the hint text in ``boardwise/pdf_text.py`` / ``docs/getting-started.md``,
and the triage slot's ``rule_id`` in ``tests/test_516_sidecar_automerge.py``'s
sibling below.
"""

from __future__ import annotations

from pathlib import Path

import boardwise.cli as cli
from boardwise.engines.checkup import (
    board_report_verdict,
    warning_triage_slots,
)


def test_the_closing_line_names_the_rule_families_it_counts():
    """C1: 「先改 5 项 ERROR」 now carries 「按规则：…」 so the type is not a lookup."""
    report = {
        "summary": {"errorCount": 5, "errors": [1, 2, 3, 4, 5], "mayClaimPassed": False},
        "completion": {"verdict": "incomplete", "verdictWhy": ["5 项 ERROR"]},
        "findings": (
            [{"rule_id": "pcb-track-ampacity", "severity": "ERROR"}] * 4
            + [{"rule_id": "conn-nc-and-must-connect", "severity": "ERROR"}]
        ),
    }
    info = board_report_verdict(report)
    assert info["canShip"] is False
    assert "按规则" in info["line"]
    assert "载流 4" in info["line"]
    assert "NC 与必连引脚 1" in info["line"]


def test_a_report_with_no_error_findings_keeps_the_plain_line():
    """C1 is an addition: nothing to count → the line is exactly what it was."""
    report = {
        "summary": {"errorCount": 0, "errors": [], "mayClaimPassed": False},
        "completion": {"verdict": "incomplete", "verdictWhy": ["有器件缺手册未审"]},
        "findings": [{"rule_id": "decap-required-caps", "severity": "WARN"}],
    }
    info = board_report_verdict(report)
    assert "按规则" not in info["line"]


def test_intent_paths_are_made_absolute():
    """C2: a relative ``--intent`` resolves against cwd, so ``cd`` cannot lose it."""
    resolved = cli._resolve_cli_path("design-intent.json")
    assert resolved.is_absolute()
    assert resolved.name == "design-intent.json"
    assert Path(resolved).parent == Path.cwd().resolve()


def test_main_reconfigures_the_standard_streams_to_utf8(monkeypatch, tmp_path):
    """C5: the CLI asks its stdout/stderr for UTF-8 before doing anything else."""
    calls: list[dict] = []

    class _FakeStream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

        def write(self, _text):
            return len(_text)

        def flush(self):
            return None

    monkeypatch.setattr(cli.sys, "stdout", _FakeStream())
    monkeypatch.setattr(cli.sys, "stderr", _FakeStream())
    # A command that parses and returns without touching a model or the bridge:
    # with no report.json there is nothing to mark up, so it exits 3.
    code = cli.main(["need-datasheet", "--out", str(tmp_path / "missing")])
    assert code == 3
    assert [call.get("encoding") for call in calls] == ["utf-8", "utf-8"]


def test_a_rule_triage_slot_carries_the_rule_id_not_only_evidence():
    """C4: the triage slot states its rule under the JSON's snake_case name."""
    from boardwise.core.model import Component, DesignModel, Net, Pin

    model = DesignModel()
    model.components["U1"] = Component(uid="u-U1", designator="U1", pins=[Pin("1", "1", "N")])
    model.nets = {"N": Net(name="N")}
    slots = warning_triage_slots(
        model=model,
        drc={"schematic": {}, "pcb": {"groups": []}},
        findings=[
            {
                "rule_id": "pcb-track-ampacity",
                "severity": "WARN",
                "message": "narrow",
                "refs": [],
                "target": None,
            }
        ],
        modules=[],
    )
    assert slots, "the WARN finding produced a slot"
    assert slots[0]["rule_id"] == "pcb-track-ampacity"
