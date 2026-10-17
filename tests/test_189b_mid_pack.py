"""189B: intent 三态 / stale 渲染崩溃 / derating 判型 / 轨归因披露 / skill 备份窗.

One file for the batch's five seams, because each one is a *behaviour at a seam*
rather than a subsystem: the report writer, the intent renderer, the derating
rule's type reading, the decap-distance row's attribution, and `install-skill`'s
backup window. The ④ seam is the one the feedback was measured on: a contract
with a stale entry used to take the whole `report.md` down (`entry.get` on a
`str`), so the tests here build the section the way `checkup` builds it and
assert both that the row prints and that a renderer which does raise still leaves
the rest of the report standing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from boardwise import skill_install
from boardwise.cli import _intent_contract_console_state, _write_checkup_report
from boardwise.core.designintent import DesignIntent, IntentRail
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.checkup import (
    intent_section,
    render_intent_markdown,
    render_report_markdown,
    stale_mark_rows,
)
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.derating import (
    DeratingPackage,
    _is_resistor,
    declared_type_text,
)
from boardwise.rules.pcb.distance import _rail_attribution, _rail_side


# ---------------------------------------------------------------------------
# ③ intent: 读入 / 读不了 / 不存在 是三句话，不是两句
# ---------------------------------------------------------------------------


def _hr(title: str) -> None:
    """A section per state."""


def _section(**kwargs) -> dict:
    return intent_section(facts={"slots": 0, "filled": 0}, contract_file="/tmp/c.json", **kwargs)


def test_the_three_contract_states_are_three_lines():
    """A present-but-unreadable contract must not read as a missing one (③).

    The reader sent to 「不存在」 goes and checks paths and project uuids while the
    real message (the parse error) was already in hand — that is the whole of the
    feedback. The three states are asserted on the **rendered** text and on the
    console one-token form, because those are the two places a human reads them.
    """
    read = _section(present=True)
    unreadable = _section(present=False, read_error="bad slot key 'volts'")
    absent = _section(present=False)

    assert read["contract"]["state"] == "read"
    assert unreadable["contract"]["state"] == "unreadable"
    assert absent["contract"]["state"] == "absent"

    lines: list[str] = []
    render_intent_markdown(lines, read)
    assert "（本次读入：槽位与答案以它为准）" in "\n".join(lines)
    assert "不存在" not in "\n".join(lines)

    lines = []
    render_intent_markdown(lines, unreadable)
    text = "\n".join(lines)
    assert "**读不了**：bad slot key 'volts'" in text
    assert "不存在" not in text, "an unreadable contract is not a missing one"

    lines = []
    render_intent_markdown(lines, absent)
    assert "**不存在**" in "\n".join(lines)

    assert _intent_contract_console_state(read["contract"]) == "（读入）"
    assert "读不了" in _intent_contract_console_state(unreadable["contract"])
    assert "bad slot key" in _intent_contract_console_state(unreadable["contract"])
    assert "不存在" in _intent_contract_console_state(absent["contract"])


# ---------------------------------------------------------------------------
# ④ the stale seam: the mark has two shapes and the renderer needs the dicts
# ---------------------------------------------------------------------------


def _stale_facts() -> dict:
    """What `designintent.merge` hands the section for one disappeared object."""
    return {
        "slots": 3,
        "filled": 1,
        "missing": [],
        "added": [],
        "stale": ["rails:+24V"],
        "staleEntries": [{"section": "rails", "object": "+24V"}],
        "extras": [],
    }


def test_the_stale_mark_renders_a_named_object_and_does_not_raise():
    """The ④ seam: stale non-empty ⇒ the row prints and the renderer survives.

    Before the fix the section carried ``facts["stale"]`` (``section:identity``
    strings) while the renderer called ``entry.get("object")`` on each row, so a
    single stale mark raised ``AttributeError`` **out of the whole report** —
    minutes of rules producing nothing.
    """
    section = intent_section(
        facts=_stale_facts(), contract_file="/tmp/c.json", present=True
    )
    assert section["stale"] == ["rails:+24V"], "the count's own reading is kept"
    assert section["staleEntries"] == [{"section": "rails", "object": "+24V"}]
    # 192B ⑨: two names, because these are two questions — this pass's marks, and
    # the standing set the heading below counts. They happen to be equal here,
    # which is exactly why one name used to look right.
    assert section["totals"]["newlyStale"] == 1
    assert section["totals"]["staleTotal"] == 1

    lines: list[str] = []
    render_intent_markdown(lines, section)
    text = "\n".join(lines)
    assert "合同里记着、图纸里已没有的对象（1，不删只标）" in text
    assert "- `+24V`（rails）" in text

    report = {"intent": section, "source": {}, "model": {}, "summary": {}}
    markdown = render_report_markdown(report)
    assert "`+24V`（rails）" in markdown, "and through the writer a reader actually opens"


def test_the_old_string_shape_still_prints_instead_of_vanishing():
    """A report written by an older build carries only ``stale`` (④, one shape).

    A re-gate re-renders a stored report, so both shapes have to print: rows that
    silently stop appearing are the failure this section exists to prevent.
    """
    assert stale_mark_rows({"stale": ["rails:+24V"]}) == [
        "- `rails:+24V` —— 值保留，只标 stale"
    ]
    assert stale_mark_rows({}) == []
    assert stale_mark_rows({"staleEntries": ["a bare string"]})[0].startswith("- `a bare")


def test_a_broken_intent_renderer_costs_its_own_section(monkeypatch):
    """The fallback ④ asks for: the intent section fails, the body still comes out.

    «a report that took minutes of rules must not be zero output» is the promise
    under test, so the failure is injected rather than hoped for.
    """
    import boardwise.engines.checkup as checkup

    def boom(lines, section):
        lines.append("## 设计意图合同（intent）—— 半个节")
        raise ValueError("simulated shape mismatch")

    monkeypatch.setattr(checkup, "render_intent_markdown", boom)
    report = {
        "schema": "boardwise.checkup/6",
        "intent": intent_section(facts=_stale_facts()),
        "source": {},
        "model": {},
        "summary": {"errorCount": 2},
        "ai_slots": {},
    }
    markdown = render_report_markdown(report)
    assert "**intent 节渲染失败：ValueError: simulated shape mismatch**" in markdown
    assert "半个节" not in markdown, "the half-written section is dropped"
    assert "# boardwise checkup 报告" in markdown, "the body above it survives"
    assert "AI 槽位" in markdown, "and the sections after it still render"


def test_a_broken_section_body_leaves_the_document_up_to_the_break():
    """Whatever a section does, `report.md` is not an empty file with a traceback."""
    report = {
        "schema": "boardwise.checkup/6",
        "source": {},
        # Two boards with no pages/components: the 「板」 line reads the keys the
        # section below the header needs, so this raises *after* the header.
        "model": {"boards": [{"title": "a"}, {"title": "b"}]},
        "summary": {},
    }
    markdown = render_report_markdown(report)
    assert markdown.startswith("# boardwise checkup 报告")
    assert "报告渲染中断：KeyError" in markdown
    assert "请直接读 `report.json`" in markdown


def test_report_json_is_written_even_when_a_section_builder_raises(tmp_path, monkeypatch):
    """`report.json` is the artifact the rules paid for — deriving a section must
    not cost it (④'s «不产出» clause, one level up from the renderer)."""
    import boardwise.cli as cli

    def boom(*args, **kwargs):
        raise ValueError("simulated section failure")

    monkeypatch.setattr(cli, "board_report_section", boom)
    monkeypatch.setattr(cli, "conclusion_section", boom)
    report = {"schema": "boardwise.checkup/6", "summary": {}, "findings": []}
    path = _write_checkup_report(tmp_path, report)
    written = path.read_text(encoding="utf-8")
    assert path.name == "report.json"
    assert "board_report 节派生失败：ValueError: simulated section failure" in written
    assert "conclusion 节派生失败：ValueError: simulated section failure" in written
    assert '"board_report": {}' in written
    assert "conclusion" not in report, "an underivable conclusion is absent, not faked"


# ---------------------------------------------------------------------------
# ⑦ derating: 判型读立创元数据，位号前缀不参与
# ---------------------------------------------------------------------------


def _derating_ctx(parts: dict[str, dict], nets: dict[str, list[tuple[str, str]]]):
    """A synthetic context whose parts carry **arbitrary props**."""
    components = {}
    for designator, spec in parts.items():
        members = [(d, p) for group in nets.values() for d, p in group if d == designator]
        components[designator] = Component(
            uid=designator,
            designator=designator,
            value=spec.get("value", ""),
            footprint=spec.get("footprint", ""),
            mpn=spec.get("mpn", ""),
            props=spec.get("props", {}),
            pins=[Pin(number=pin, name=pin) for _d, pin in members],
        )
    model = DesignModel(
        components=components,
        nets={
            name: Net(name=name, pins=[tuple(member) for member in members])
            for name, members in nets.items()
        },
    )
    return PcbReviewContext(
        board=None, board_title="SYNTH", model=model, pcb_model=model,
    )


def test_a_u_designated_resistor_is_read_from_the_lcsc_metadata():
    """The reported case (⑦): ``U`` designator, no readable value, metadata says 电阻.

    `330kΩ ±1% 1/4W 厚膜电阻` is what 立创 writes in ``LCSC Part Name`` — and it is
    the *only* place the type is stated on such a part, because ``Type`` is empty
    and the value field carries nothing the ohms door can read. The rule must
    recognise it as a resistor **on the metadata**, and name that metadata in the
    evidence rather than silently judging a ``U`` part.
    """
    ctx = _derating_ctx(
        {
            "U1": {
                "value": "",
                "footprint": "R1206",
                "props": {"LCSC Part Name": "330kΩ ±1% 1/4W 厚膜电阻"},
            }
        },
        {"A": [("U1", "1")], "B": [("U1", "2")]},
    )
    rows = DeratingPackage().check(ctx)
    summary = [row for row in rows if row.severity == "INFO"]
    assert summary, "the per-board reading is always emitted"
    assert "认出 1 颗电阻" in summary[0].message

    # The door itself, quoted: the part is a resistor **because of the metadata**,
    # and the reason names the words that decided it (the same string a verdict's
    # evidence carries when the part is over its package limit).
    metadata = declared_type_text(
        Component(
            uid="U1",
            designator="U1",
            value="",
            props={"LCSC Part Name": "330kΩ ±1% 1/4W 厚膜电阻"},
        )
    )
    assert metadata == "330kΩ ±1% 1/4W 厚膜电阻"
    is_resistor, why = _is_resistor("", "R1206", metadata)
    assert is_resistor is True
    assert "厚膜电阻" in why


def test_a_designator_prefix_alone_never_makes_a_part_a_resistor():
    """No metadata, no readable value ⇒ not judged — `U` is not evidence (⑦).

    The mirror image of the reported defect: the rule must not swing the other way
    and start guessing from the designator letter. A part nobody declared is
    simply not this rule's subject (architecture decision 5).
    """
    ctx = _derating_ctx(
        {"U7": {"value": "", "footprint": "R1206", "props": {}}},
        {"A": [("U7", "1")], "B": [("U7", "2")]},
    )
    rows = DeratingPackage().check(ctx)
    summary = [row for row in rows if row.severity == "INFO"]
    assert "认出 0 颗电阻" in summary[0].message
    assert "0 颗" in summary[0].message


def test_declared_type_text_reads_the_metadata_fields_in_priority_order():
    """The reader itself: `Type`, then the 立创 part name, then the supplier footprint."""
    component = Component(
        uid="U1",
        designator="U1",
        props={
            "Type": "厚膜电阻",
            "LCSC Part Name": "330kΩ ±1% 1/4W",
            "Supplier Footprint": "1206",
            "Value": "ignored",
        },
    )
    text = declared_type_text(component)
    assert text == "厚膜电阻 330kΩ ±1% 1/4W 1206"
    assert declared_type_text(Component(uid="x", designator="x")) == ""


def test_the_ic_judgement_that_still_reads_the_prefix_was_rewritten_by_190():
    """The measured remainder of ⑦, **flipped by 190** — deliberately.

    189B read declarations only (derating) and left the schematic-side judgement
    ``decoupling-per-ic`` (``rules/connectivity.py``) asking for a capacitor on
    every part whose designator starts with ``U``; its message said so itself
    (「matches designator prefixes only (U*/C*)」), and this test pinned that as
    the batch's claim's counter-anchor, with a note that **a later batch making
    it declaration-based must rewrite this test deliberately, not by accident**.
    190 is that batch: both halves of the judgement now go through
    :func:`boardwise.core.partkind.classify_part`, so the same ``U``-designated
    330 kΩ resistor is no longer asked for a capacitor, and the message says
    which basis each side was read on instead of admitting a prefix test.

    Kept in this file rather than moved, because it is the *same* case read
    again: the part is the ⑦ part, and what changed is which batch's口径 owns it.
    """
    from boardwise.rules.connectivity import DecouplingPerIC

    model = DesignModel(
        components={
            "U1": Component(
                uid="U1",
                designator="U1",
                value="",
                footprint="R1206",
                props={"LCSC Part Name": "330kΩ ±1% 1/4W 厚膜电阻"},
                pins=[Pin(number="1", name="1", net="A"), Pin(number="2", name="2", net="B")],
            ),
        },
        nets={"A": Net(name="A", pins=[("U1", "1")]), "B": Net(name="B", pins=[("U1", "2")])},
    )
    assert DecouplingPerIC().check(model) == []

    # …and the rule still fires on a part that really is one, with a message that
    # no longer claims a prefix test it does not run.
    rows = DecouplingPerIC().check(_decoupling_model_with_an_ic())
    assert [row.severity for row in rows] == ["WARN"]
    assert "matches designator prefixes only" not in rows[0].message


def _decoupling_model_with_an_ic() -> DesignModel:
    """One three-pin ``U`` part the declarations say nothing about, no capacitor:
    the rule still fires, and the message must not claim a prefix test it no
    longer runs."""
    return DesignModel(
        components={
            "U2": Component(
                uid="U2",
                designator="U2",
                pins=[
                    Pin(number="1", name="VIN", net="A"),
                    Pin(number="2", name="GND", net="GND"),
                    Pin(number="3", name="OUT", net="B"),
                ],
            ),
        },
        nets={
            "A": Net(name="A", pins=[("U2", "1")]),
            "B": Net(name="B", pins=[("U2", "3")]),
            "GND": Net(name="GND", pins=[("U2", "2")]),
        },
    )


# ---------------------------------------------------------------------------
# ⑨ the decap row says which rail it measured, and on which side
# ---------------------------------------------------------------------------


def test_the_rail_side_is_read_from_the_pin_names():
    """`VIN 侧` / `VOUT 侧` / both / undeclared — over this part's pins on *that* net."""
    component = Component(
        uid="U1",
        designator="U1",
        pins=[
            Pin(number="1", name="VIN", net="+12V"),
            Pin(number="2", name="VOUT", net="3V3"),
            Pin(number="3", name="FB", net="FB1"),
        ],
    )
    assert _rail_side(component, "+12V") == "VIN 侧"
    assert _rail_side(component, "3V3") == "VOUT 侧"
    assert _rail_side(component, "FB1") == "脚名未声明侧别"
    assert _rail_side(component, "nowhere") == "脚名未声明侧别"

    both = Component(
        uid="U2",
        designator="U2",
        pins=[Pin(number="1", name="VIN", net="X"), Pin(number="2", name="OUT", net="X")],
    )
    assert _rail_side(both, "X") == "VIN+VOUT 两侧"


def test_the_attribution_says_the_rail_the_capacitor_serves():
    """岳的 ⑨: 「规则报的是 +12V 轨上的距离，归因不对」 — so the row says the rail.

    Two statements, and the second is the one that answers the case: the rail a
    capacitor sits on is the rail it serves (the row measures both pads on that
    net), and *which side of this part* that rail is — because a rail that is one
    part's input may be another part's output.
    """
    attribution = _rail_attribution("U1", "+12V", "VIN 侧")
    assert "'+12V'" in attribution.short and "VIN 侧" in attribution.short
    assert "电容服务的那条轨" in attribution.short
    assert "the rail the capacitor serves" in attribution.evidence
    assert "core.pinrole" in attribution.evidence
    assert "one part's input may be another part's output" in attribution.evidence


# ---------------------------------------------------------------------------
# ⑧ install-skill: 备份窗 —— 留最近 3 份，更老的进回收站
# ---------------------------------------------------------------------------


def _stamped(directory: Path, stem: str, stamps) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for stamp in stamps:
        path = directory / f"{stem}.bak-{stamp}"
        path.write_text(f"old {stamp}\n", encoding="utf-8")
        written.append(path)
    return written


def _fake_recycler(path: Path) -> str:
    """Stand in for :func:`skill_install.recycle` and move the file like it does.

    The real one hands the file to the OS shell; a test that only recorded the call
    would leave the file in place and then assert on a directory that still holds
    it — which is exactly what makes a "pruned" claim unprovable.
    """
    path.unlink()
    return ""


def test_the_backup_window_keeps_three_and_recycles_the_rest(tmp_path):
    directory = tmp_path / "skills"
    _stamped(
        directory,
        "SKILL.md",
        ["20260101-000001", "20260102-000001", "20260103-000001",
         "20260104-000001", "20260105-000001"],
    )
    kept, recycled, note = skill_install.prune_backups(
        directory, "SKILL.md", recycler=_fake_recycler
    )
    assert kept == 3 and note == ""
    assert [path.name for path in recycled] == [
        "SKILL.md.bak-20260101-000001",
        "SKILL.md.bak-20260102-000001",
    ]
    assert sorted(path.name for path in directory.glob("SKILL.md.bak-*")) == [
        "SKILL.md.bak-20260103-000001",
        "SKILL.md.bak-20260104-000001",
        "SKILL.md.bak-20260105-000001",
    ]


def test_the_window_is_three_even_when_a_second_install_shares_the_second(tmp_path):
    """The `-2` collision suffix counts as an ordinary backup, and sorts last."""
    directory = tmp_path / "skills"
    _stamped(
        directory,
        "SKILL.md",
        ["20260101-000001", "20260102-000001", "20260103-000001"],
    )
    (directory / "SKILL.md.bak-20260103-000001-2").write_text("second\n", encoding="utf-8")
    kept, recycled, _note = skill_install.prune_backups(
        directory, "SKILL.md", recycler=_fake_recycler
    )
    assert kept == 3
    assert [path.name for path in recycled] == ["SKILL.md.bak-20260101-000001"]


def test_a_file_this_module_did_not_write_is_never_recycled(tmp_path):
    directory = tmp_path / "skills"
    _stamped(directory, "SKILL.md", ["20260101-000001", "20260102-000001",
                                    "20260103-000001", "20260104-000001"])
    (directory / "SKILL.md.bak-keepme").write_text("mine\n", encoding="utf-8")
    (directory / "SKILL.md.orig").write_text("also mine\n", encoding="utf-8")
    kept, recycled, _note = skill_install.prune_backups(
        directory, "SKILL.md", recycler=_fake_recycler
    )
    assert kept == 3
    assert [path.name for path in recycled] == ["SKILL.md.bak-20260101-000001"]
    assert (directory / "SKILL.md.bak-keepme").exists()
    assert (directory / "SKILL.md.orig").exists()


def test_a_refused_recycle_keeps_the_file_and_says_so(tmp_path):
    """No recycle bin (or a shell error) ⇒ the old backups stay, and why is reported.

    The hygiene step must never degrade into the deletion the red line forbids.
    """
    directory = tmp_path / "skills"
    _stamped(directory, "SKILL.md", ["20260101-000001", "20260102-000001",
                                    "20260103-000001", "20260104-000001"])
    kept, recycled, note = skill_install.prune_backups(
        directory, "SKILL.md", recycler=lambda path: "this platform has no recycle bin (linux)"
    )
    assert recycled == ()
    assert kept == 4, "nothing left, so all four are still there"
    assert "没有直删" in note and "no recycle bin" in note
    assert len(list(directory.glob("SKILL.md.bak-*"))) == 4


def test_install_reports_the_window_it_left(tmp_path, monkeypatch):
    """End to end: install twice, and the outcome carries the counts the CLI prints."""
    directory = tmp_path / "skills"
    source = tmp_path / "bundled-SKILL.md"
    source.write_bytes(b"# new\n")
    _stamped(directory, "SKILL.md", ["20260101-000001", "20260102-000001",
                                    "20260103-000001"])
    (directory / "SKILL.md").write_text("# an older install\n", encoding="utf-8")
    monkeypatch.setattr(skill_install, "recycle", _fake_recycler)

    outcome = skill_install.install(source, directory, now="20260404-050607")

    assert outcome.outcome == "updated"
    assert outcome.backup == directory / "SKILL.md.bak-20260404-050607"
    assert outcome.backupsKept == 3, "the new backup is one of the three kept"
    assert [path.name for path in outcome.recycled] == ["SKILL.md.bak-20260101-000001"]
    assert (directory / "SKILL.md").read_bytes() == b"# new\n"


def test_the_cli_prints_how_many_backups_were_kept(tmp_path, monkeypatch, capsys):
    from boardwise.cli import main as cli_main

    home = tmp_path / "kimi" / "skills" / "boardwise"
    monkeypatch.setenv(skill_install.SKILL_HOME_ENVS["kimi"], str(home))
    monkeypatch.delenv(skill_install.SKILL_HOME_ENVS["claude"], raising=False)
    source = tmp_path / "bundled-SKILL.md"
    source.write_bytes(b"# new\n")
    _stamped(home, "SKILL.md", ["20260101-000001", "20260102-000001",
                                "20260103-000001"])
    (home / "SKILL.md").write_text("# an older install\n", encoding="utf-8")
    monkeypatch.setattr(skill_install, "recycle", _fake_recycler)

    code = cli_main(["install-skill", "--harness", "kimi"])
    printed = capsys.readouterr().out

    assert code == 0
    assert f"保留最近 {skill_install.KEPT_BACKUPS} 份 `*.bak-*`" in printed
    assert "1 份已进回收站" in printed


@pytest.mark.skipif(skill_install.os.name != "nt", reason="the recycle bin is a Windows facility")
def test_the_real_recycler_moves_the_file_out_of_the_directory(tmp_path):
    """The OS call itself, exercised once for real: the file leaves, nothing is deleted."""
    victim = tmp_path / "throwaway.bak-20260101-000001"
    victim.write_text("old\n", encoding="utf-8")
    assert skill_install.recycle(victim) == ""
    assert not victim.exists()
