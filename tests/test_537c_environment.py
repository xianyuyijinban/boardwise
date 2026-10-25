"""537C2: `checkup` 的结构化环境 / 版本 / 只读披露.

Why this file exists. The review report already recorded *what* version the
connector announced (``source.connectorVersion``) and nothing else: no expected
version to compare it with, no statement that the review was read-only, and no
place that says what the run could **not** establish. A reader — human or model —
then had to guess whether "no findings" meant "checked live and clean" or "read
an archive offline", and whether any next step was allowed to write.

So every report now carries a top-level ``environment`` section:

* ``tier`` — the data tier the run actually used;
* ``expectedConnectorVersion`` / ``runningConnectorVersion`` — a plain string
  comparison (no semver inference), either side may be ``null``;
* ``connectorVersionStatus`` — ``not-applicable`` (offline), ``match``,
  ``mismatch``, ``unknown``;
* ``writeAllowed: false`` — **this review is not authorised to write** (not a
  claim about the daemon's global configuration);
* ``allowedNextActions`` — exactly three safe next steps, in a fixed order, none
  of which applies anything to a real project;
* ``limitations`` — one row per thing this run could not establish, each with a
  Chinese message that says what the limitation *costs*.

What these tests pin, in order:

1. the section is always present and additive (``source`` untouched);
2. each status is derived the way the contract says, including "offline is
   never a mismatch" and "a missing side is unknown, not match";
3. the per-tier limitations, and that a ``match`` invents none;
4. the three next actions are frozen, in order, and never offer a real-project
   apply;
5. ``report.json`` / ``report.md`` / ``review-summary.md`` / stdout all disclose
   the same section (and the review-summary's existing skeleton survives);
6. a hand-built report with no ``environment`` renders no environment text —
   the old rendering stays byte-compatible.

All inputs here are anonymous/synthetic: a bare :class:`DesignModel` for the
report-shape tests and the repository's synthetic CH340 fixture for the one
end-to-end run. No editor, no daemon, no real project.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.model import DesignModel
from boardwise.engines.checkup import finding_chains, render_report_markdown, render_review_summary

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = FIXTURES / "ch340_golden.epro2"
LIBRARY = FIXTURES.parent.parent / "blocklib" / "parts.json"

#: The frozen key set of the section. A new key here is a contract change, not a
#: convenience — the report is what downstream readers (and the SOP) parse.
ENVIRONMENT_KEYS = {
    "tier",
    "expectedConnectorVersion",
    "runningConnectorVersion",
    "connectorVersionStatus",
    "writeAllowed",
    "allowedNextActions",
    "limitations",
}

#: The three safe next steps, in their frozen order.
ACTION_IDS = ["offline-plan", "engineer-manual", "authorized-test-project"]

#: The two real-time evidence channels an offline run cannot see.
LIVE_AFFECTS = ["liveSchematic", "livePcb"]

#: Every limitation code the section can carry.
LIMITATION_CODES = {
    "offline-no-live-evidence",
    "connector-version-mismatch",
    "connector-version-unverified",
    "per-page-connectivity-limit",
    "connectivity-only-model",
}

_AUTO = object()


def _report(
    monkeypatch,
    tier: str = "project-file",
    *,
    running: str = "0.5.21",
    expected: str = "0.5.21",
    environment=_AUTO,
) -> dict:
    """One report assembled through the real :func:`boardwise.cli._checkup_report`.

    The expected version is a monkeypatched ``_repo_connector_version`` — the
    fixture must not depend on which connector this machine happens to have
    checked out, and the comparison under test is a plain string comparison.
    """
    monkeypatch.setattr(cli, "_repo_connector_version", lambda: expected)
    source = {
        "project": {"friendlyName": "synthetic"},
        "pageUuid": None,
        "pageType": None,
        "hostVersion": "3.2.186",
        "connectorVersion": running,
        "file": "synthetic.epro2" if tier == "file" else None,
    }
    summary = {
        "errorCount": 0,
        "errors": [],
        "warningCount": 0,
        "warnings": [],
        "infoCount": 0,
        "exitCode": 0,
        "countsIncomplete": False,
    }
    kwargs = {} if environment is _AUTO else {"environment": environment}
    return cli._checkup_report(
        tier=tier,
        source=source,
        model=DesignModel(),
        attempts=[],
        notes=[],
        drc={},
        findings=[],
        summary=summary,
        modules=[],
        slots={},
        **kwargs,
    )


def _codes(environment: dict) -> list[str]:
    return [row["code"] for row in environment["limitations"]]


# ---------------------------------------------------------------------------
# 1. shape: always present, additive, source untouched
# ---------------------------------------------------------------------------


def test_the_report_always_carries_the_environment_and_leaves_source_alone(monkeypatch):
    report = _report(monkeypatch, "project-file", running="0.5.18", expected="0.5.21")

    environment = report["environment"]
    assert set(environment) == ENVIRONMENT_KEYS
    assert environment["tier"] == "project-file"
    assert environment["expectedConnectorVersion"] == "0.5.21"
    # The running version is the *same reading* `source` already carries: one
    # source of truth, two readers.
    assert environment["runningConnectorVersion"] == report["source"]["connectorVersion"] == "0.5.18"
    assert environment["connectorVersionStatus"] == "mismatch"
    assert environment["writeAllowed"] is False
    # The additive promise, pinned literally: nothing was renamed or removed.
    assert report["source"]["tier"] == "project-file"
    assert report["source"]["hostVersion"] == "3.2.186"
    assert "connectorVersion" in report["source"]
    # `tier` is the one name the source section already used; the *new* keys did
    # not get folded into `source` (that would bury the disclosure in a section
    # this file's contract says must stay unchanged).
    assert (ENVIRONMENT_KEYS - {"tier"}).isdisjoint(report["source"])


def test_an_explicit_environment_argument_costs_no_second_computation(monkeypatch):
    """Tests (and future callers) may hand the section in; it travels as given."""
    handed = {"tier": "file", "marker": True}
    report = _report(monkeypatch, "file", environment=handed)
    assert report["environment"] == handed


# ---------------------------------------------------------------------------
# 2. the four statuses
# ---------------------------------------------------------------------------


def test_offline_file_tier_is_not_applicable_never_a_mismatch(monkeypatch):
    """Offline has no connector to compare, so an empty running version is *not*
    a mismatch — this is exactly the misreading the section must prevent."""
    environment = _report(monkeypatch, "file", running="", expected="0.5.21")["environment"]

    assert environment["connectorVersionStatus"] == "not-applicable"
    assert environment["runningConnectorVersion"] is None
    assert environment["expectedConnectorVersion"] == "0.5.21"
    assert _codes(environment) == ["offline-no-live-evidence"]
    assert "mismatch" not in json.dumps(environment, ensure_ascii=False)


def test_matching_versions_are_match_and_invent_no_version_limitation(monkeypatch):
    environment = _report(
        monkeypatch, "project-file", running="0.5.21", expected="0.5.21"
    )["environment"]

    assert environment["connectorVersionStatus"] == "match"
    assert environment["runningConnectorVersion"] == "0.5.21"
    # A match must not fabricate a limitation; the full-project tier has nothing
    # else to disclaim.
    assert environment["limitations"] == []


def test_a_version_mismatch_is_named_with_both_versions_and_blocks_confirmation(monkeypatch):
    environment = _report(
        monkeypatch, "project-file", running="0.5.18", expected="0.5.21"
    )["environment"]

    assert environment["connectorVersionStatus"] == "mismatch"
    rows = [row for row in environment["limitations"] if row["code"] == "connector-version-mismatch"]
    assert len(rows) == 1
    row = rows[0]
    assert row["affects"] == ["liveSchematic", "livePcb", "schematicImage", "pcbImage"]
    # Both strings are in the message, because a reader cannot chase a version
    # difference the report only points at.
    assert "0.5.21" in row["message"] and "0.5.18" in row["message"]
    assert "confirmed" in row["message"], "受影响实时结论不得标 confirmed"


def test_a_missing_expected_version_is_unknown_not_a_match(monkeypatch):
    environment = _report(
        monkeypatch, "project-file", running="0.5.21", expected=""
    )["environment"]

    assert environment["expectedConnectorVersion"] is None
    assert environment["connectorVersionStatus"] == "unknown"
    rows = [row for row in environment["limitations"] if row["code"] == "connector-version-unverified"]
    assert len(rows) == 1
    assert rows[0]["affects"] == ["liveSchematic", "livePcb", "schematicImage", "pcbImage"]
    assert "match" in rows[0]["message"], "缺失不能当成 match"
    assert "0.5.21" in rows[0]["message"]


def test_a_missing_running_version_is_unknown_not_a_pass(monkeypatch):
    environment = _report(
        monkeypatch, "project-file", running="", expected="0.5.21"
    )["environment"]

    assert environment["runningConnectorVersion"] is None
    assert environment["connectorVersionStatus"] == "unknown"
    assert _codes(environment) == ["connector-version-unverified"]


# ---------------------------------------------------------------------------
# 3. per-tier limitations, unique, and what a match costs
# ---------------------------------------------------------------------------


def test_per_page_tier_declares_that_names_are_not_verified_cross_page_wiring(monkeypatch):
    environment = _report(
        monkeypatch, "per-page", running="0.5.21", expected="0.5.21"
    )["environment"]

    assert environment["connectorVersionStatus"] == "match"
    rows = [row for row in environment["limitations"] if row["code"] == "per-page-connectivity-limit"]
    assert len(rows) == 1
    assert rows[0]["affects"] == ["crossPageConnectivity", "archivePcb"]
    assert "同名" in rows[0]["message"]
    assert "PCB" in rows[0]["message"]


def test_netlist_tier_declares_connectivity_only_model(monkeypatch):
    environment = _report(
        monkeypatch, "netlist", running="0.5.21", expected="0.5.21"
    )["environment"]

    assert environment["connectorVersionStatus"] == "match"
    rows = [row for row in environment["limitations"] if row["code"] == "connectivity-only-model"]
    assert len(rows) == 1
    assert rows[0]["affects"] == ["values", "mpn", "archivePcb"]
    assert "Value" in rows[0]["message"] and "MPN" in rows[0]["message"]


def test_limitations_never_repeat_and_every_row_is_a_chinese_impact_statement(monkeypatch):
    environment = _report(
        monkeypatch, "per-page", running="0.5.18", expected="0.5.21"
    )["environment"]

    codes = _codes(environment)
    assert codes == ["connector-version-mismatch", "per-page-connectivity-limit"]
    assert len(codes) == len(set(codes))
    assert set(codes) <= LIMITATION_CODES
    for row in environment["limitations"]:
        assert set(row) == {"code", "affects", "message"}
        assert row["affects"], "each limitation names the conclusions it affects"
        # Chinese prose, not a one-word pass/fail flag.
        assert re.search(r"[\u4e00-\u9fff]", row["message"])
        assert row["code"] not in row["message"], "the message explains the impact, it does not echo the code"


# ---------------------------------------------------------------------------
# 4. the three safe next steps
# ---------------------------------------------------------------------------


def test_allowed_next_actions_are_the_three_frozen_safe_options(monkeypatch):
    environment = _report(monkeypatch)["environment"]

    actions = environment["allowedNextActions"]
    assert [action["id"] for action in actions] == ACTION_IDS
    assert [action["mode"] for action in actions] == [
        "offline", "manual", "explicit-authorization",
    ]
    assert actions[0] == {
        "id": "offline-plan",
        "mode": "offline",
        "description": "生成离线 ChangePlan；不连接编辑器、不修改设计",
    }
    assert actions[1] == {
        "id": "engineer-manual",
        "mode": "manual",
        "description": "由工程师在编辑器中核对并手动修改",
    }
    assert actions[2] == {
        "id": "authorized-test-project",
        "mode": "explicit-authorization",
        "projects": ["test", "test2"],
        "description": "仅在任务明确授权且完成工程身份核对后，按测试工程流程执行",
    }


def test_no_allowed_next_action_offers_to_apply_anything_to_a_real_project(monkeypatch):
    environment = _report(monkeypatch)["environment"]

    blob = json.dumps(environment["allowedNextActions"], ensure_ascii=False).lower()
    assert "apply" not in blob, "the next steps must not name an apply against any project"
    assert "真实" not in blob or "不" in blob
    # writeAllowed=false is scoped to this review, not claimed as daemon policy.
    assert environment["writeAllowed"] is False


def test_the_console_line_renders_the_sections_own_write_flag(monkeypatch):
    """The console is one more *rendering* of `environment`, not a second opinion.

    A hard-coded ``writeAllowed=false`` in the console formatter would agree with
    a section that says ``true`` and therefore diverge from `report.json` — the
    exact drift the shared section exists to prevent. So the line is rendered
    from the value, like `render_environment_markdown` does. This test flips a
    **copy** (renderer honesty only: production stays read-only, which the
    second half pins).
    """
    from boardwise.engines.checkup import environment_console_line, environment_section

    environment = environment_section(
        tier="project-file",
        source={"connectorVersion": "0.5.21"},
        expected_connector_version="0.5.21",
    )
    # the production section is, and must stay, read-only
    assert environment["writeAllowed"] is False
    assert "writeAllowed=false" in environment_console_line(environment)
    assert _report(monkeypatch, "file")["environment"]["writeAllowed"] is False

    flipped = copy.deepcopy(environment)
    flipped["writeAllowed"] = True
    line = environment_console_line(flipped)
    assert "writeAllowed=true" in line
    assert "writeAllowed=false" not in line


# ---------------------------------------------------------------------------
# 5. disclosure in report.json / report.md / review-summary.md / stdout
# ---------------------------------------------------------------------------


def test_an_offline_run_discloses_the_environment_in_every_artifact(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(cli, "_repo_connector_version", lambda: "0.9.9")
    monkeypatch.setenv("BOARDWISE_HOME", str(tmp_path / "home"))
    out = tmp_path / "out"

    code = cli.main([
        "checkup", "--file", str(GOLDEN), "--out", str(out), "--library", str(LIBRARY),
    ])
    printed = capsys.readouterr().out

    assert code in (0, 1, 3), "an offline run over the synthetic fixture must still run"
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    environment = report["environment"]
    assert set(environment) == ENVIRONMENT_KEYS
    assert environment["tier"] == "file"
    assert environment["expectedConnectorVersion"] == "0.9.9"
    assert environment["runningConnectorVersion"] is None
    assert environment["connectorVersionStatus"] == "not-applicable"
    assert environment["writeAllowed"] is False
    # The limitation is a report section, not a buried `source.notes` line.
    assert "offline-no-live-evidence" not in " ".join(report["source"].get("notes") or [])

    # --- stdout: one environment line, naming the comparison and the next steps.
    lines = [line for line in printed.splitlines() if line.strip().startswith("environment:")]
    assert len(lines) == 1, printed
    line = lines[0]
    for token in (
        "expected=0.9.9", "running=", "status=not-applicable",
        "writeAllowed=false", *ACTION_IDS,
    ):
        assert token in line, (token, line)

    # --- the two Markdown products carry the same disclosure.
    for name in ("report.md", "review-summary.md"):
        text = (out / name).read_text(encoding="utf-8")
        assert "审查环境与权限" in text, name
        assert "not-applicable" in text, name
        assert "writeAllowed" in text and "`false`" in text, name
        assert "offline-no-live-evidence" in text, name
        assert "liveSchematic" in text and "livePcb" in text, name
        for action_id in ACTION_IDS:
            assert action_id in text, (name, action_id)

    # --- the renderer did not move the verdict it was rendering.
    assert code == report["summary"]["exitCode"]


def test_report_md_and_the_review_summary_show_a_mismatch_and_its_limitation(monkeypatch):
    report = _report(monkeypatch, "project-file", running="0.5.18", expected="0.5.21")

    markdown = render_report_markdown(report)
    review = render_review_summary(report, [])

    for text in (markdown, review):
        assert "审查环境与权限" in text
        assert "mismatch" in text
        assert "0.5.21" in text and "0.5.18" in text
        assert "connector-version-mismatch" in text
        assert "writeAllowed" in text and "`false`" in text
        for action_id in ACTION_IDS:
            assert action_id in text


def test_the_review_summary_keeps_its_skeleton_around_the_new_section(monkeypatch):
    report = _report(monkeypatch, "per-page")
    report["findings"] = [
        {"rule_id": "decap-required-caps", "severity": "WARN", "message": "synthetic", "refs": ["U1"]}
    ]
    report["summary"]["conclusion"] = "无 ERROR"

    chains = finding_chains(report)
    text = render_review_summary(report, chains)

    # The pre-existing sections are still there, in order, and so are the two
    # blank columns the model must fill.
    for heading in ("## 1. 连接状态", "## 2. 逐条问题", "## 3. 待确认", "## 4. 下一步"):
        assert heading in text, heading
    assert "<!-- 分析：为什么是问题、根因在哪 -->" in text
    assert "<!-- 建议：怎么改/怎么确认 -->" in text
    assert "per-page-connectivity-limit" in text
    assert text.index("## 2. 逐条问题") < text.index("审查环境与权限") < text.index("## 3. 待确认")


def test_rendering_the_environment_does_not_move_the_verdict(monkeypatch):
    report = _report(monkeypatch, "netlist", running="0.5.18", expected="0.5.21")
    before = copy.deepcopy(report["summary"])

    render_report_markdown(report)
    render_review_summary(report, [])

    assert report["summary"] == before
    assert "completion" not in report or report["completion"] == {}


# ---------------------------------------------------------------------------
# 6. compatibility: a hand-built report with no environment
# ---------------------------------------------------------------------------


def _hand_built_report() -> dict:
    """A report dict of the shape a test (or an older run) builds by hand."""
    return {
        "source": {"tier": "file", "tierLabel": "离线文件（--file）：不连编辑器",
                   "file": "board.epro2", "notes": ["a note"]},
        "model": {"view": "schematic", "components": 0, "nets": 0,
                  "designators": [], "boards": []},
        "summary": {"errorCount": 0, "warnCount": 0, "infoCount": 0,
                    "exitCode": 0, "countsIncomplete": False,
                    "conclusion": "无 ERROR", "errors": [], "warnings": []},
        "drc": {},
        "modules": [],
        "findings": [],
        "ai_slots": {},
    }


def test_a_report_without_environment_renders_no_environment_text():
    report = _hand_built_report()

    markdown = render_report_markdown(report)
    review = render_review_summary(report, [])

    for text in (markdown, review):
        assert "审查环境与权限" not in text
        assert "writeAllowed" not in text
        assert "allowedNextActions" not in text
        assert "limitations" not in text
    # The review skeleton is unchanged: same four sections, same empty rows.
    for heading in ("## 1. 连接状态", "## 2. 逐条问题", "## 3. 待确认", "## 4. 下一步"):
        assert heading in review, heading
    assert "本次审查没有 finding" in review
