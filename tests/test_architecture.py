"""044 M1: the architecture skeleton — determinism, the four chain families, slots.

The batch's claim is narrow and testable: the tool can write a **skeleton** of the
project's chains that an AI can walk, with every judgement it cannot make left as
an explicit ``TODO`` slot. The assertions below are therefore about the skeleton's
*shape*, never about a judgement:

* determinism (two runs, byte-identical — a skeleton that varies cannot be diffed,
  and the diff is how a human reviews it);
* the golden board's power tree and USB bus (the easy end: a project with no
  controller candidate produces no chains and still a valid document);
* the ROBOT board's U-phase current chain — the task's soul case. Its chain must
  exist, its members must name the shunt (``R4``), its slots must all be TODO, and
  the evidence must show that the shunt's other end is ``GND``, because that is
  what lets the AI see the missing bias;
* degenerate inputs (an empty model, a board with unnamed nets) do not crash;
* the checkup integration writes ``architecture.md``, carries the count summary in
  ``report.json`` under ``architecture``, and bumps the schema to ``/4``.

Offline throughout: the fixtures are read as files, no bridge, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.architecture import (
    ANALOG_SLOTS,
    ARCH_FILE_NAME,
    CONTROL_SLOTS,
    INTENT_SLOTS,
    POWER_SLOTS,
    SLOT_VOCABULARY,
    TODO,
    generate_architecture,
)
from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.parsers.schematic import build_project_model

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "ch340_golden.epro2"
ROBOT = FIXTURES / "ProPrj_ROBOT ctrl FOC_2026-09-16.epro2"
SHELF = Path("blocklib/parts.json")


@pytest.fixture(scope="module")
def golden():
    return build_project_model(GOLDEN)


@pytest.fixture(scope="module")
def robot():
    return build_project_model(ROBOT)


def _slots_in(markdown: str, slot: str) -> list[str]:
    """Every ``- <slot>: …`` line in the document (the skeleton's own format)."""
    return [
        line for line in markdown.splitlines()
        if line.startswith(f"- {slot}: ")
    ]


# ---------------------------------------------------------------- determinism


def test_two_runs_are_byte_identical(robot, golden):
    """The contract the artifact's usefulness rests on: same model, same bytes."""
    first = generate_architecture(robot)
    second = generate_architecture(robot)
    assert first.markdown == second.markdown
    assert first.section == second.section
    # ... and again from a freshly parsed model of the same file, so nothing in
    # the result depends on object identity or dict insertion order.
    again = generate_architecture(build_project_model(ROBOT))
    assert again.markdown == first.markdown
    assert generate_architecture(golden).markdown == generate_architecture(golden).markdown
    # No timestamp, no locale-dependent formatting: the header says so and the
    # text proves it.
    assert "generatedAt" not in first.markdown
    assert not any(line.startswith("> 生成时间") for line in first.markdown.splitlines())


# ------------------------------------------------------------- the easy board


def test_the_golden_board_gets_rails_and_a_usb_bus(golden):
    result = generate_architecture(golden, library=None)
    markdown = result.markdown
    # A rail whose name parses as a voltage, and one an LDO feeds (the shelf is
    # absent here, so the second is only a rail because a supply pin sits on it).
    assert "#### 轨 `+5V`" in markdown
    assert "#### 轨 `VCC`" in markdown
    # `+5V`'s voltage comes from its own name even with no shelf in hand: the
    # library is only needed for the regulator half of the inference.
    assert "- voltage: 5 V（net name '+5V'）" in markdown
    # `source` is never asserted by the tool: it is a slot, and the slot is TODO.
    sources = _slots_in(markdown, "source")
    assert sources and all(line.endswith(TODO) for line in sources)
    # The USB bus line is there, and it lists the two data nets.
    assert "#### USB（2 网）" in markdown
    assert "- `D+`：" in markdown and "- `D-`：" in markdown
    assert "#### UART（2 网）" in markdown
    # No controller candidate on this board → no chains, and the document says so
    # rather than inventing one.
    assert "控制器候选：**无**" in markdown
    assert "（没有符合口径的模拟链。）" in markdown
    assert result.section["totals"]["analogChains"] == 0
    assert result.section["totals"]["controlChains"] == 0


# ----------------------------------------------------------------- the soul


def test_the_robot_board_exposes_the_phase_current_chain(robot):
    """The chain the blind review missed: shunt top → DRV PGND → STM32 PA7.

    Everything asserted here is *shape*: the chain exists, it names the shunt, its
    slots are all TODO, and the evidence prints where the shunt's other end goes
    (``GND``). The missing-bias judgement is the AI's; the skeleton's job is to
    put the two facts side by side.
    """
    result = generate_architecture(robot, library=None)
    markdown = result.markdown
    analog = {chain["net"]: chain for chain in result.section["chains"]["analog"]}
    assert "U+" in analog, sorted(analog)
    assert "W+" in analog, "both measured phase-current nets must be there"
    u_phase = analog["U+"]
    assert u_phase["board"] == "Board1"
    assert any(member.startswith("R4.") for member in u_phase["members"]), u_phase
    assert "U1.21(PA7)" in u_phase["members"], "the MCU endpoint is the anchor"
    assert "DRV1.6(PGND1)" in u_phase["members"], "the driver's own shunt node"
    assert any(member.startswith("R5.") for member in analog["W+"]["members"])

    block = markdown.split("#### 链 `U+`", 1)[1].split("####", 1)[0]
    for slot in ANALOG_SLOTS:
        assert f"- {slot}: {TODO}" in block, slot
    # The reference evidence: the shunt's other terminal is on the ground net.
    assert "邻接 R4→GND" in block
    # ... and the anchor's evidence is stated, not assumed.
    assert "锚点 U1.21" in block and "P<端口><数字>" in block


def test_the_robot_board_scaffolds_the_control_chains_and_the_bus_table(robot):
    result = generate_architecture(robot)
    control = {chain["net"] for chain in result.section["chains"]["control"]}
    assert {"TIM1_CH1", "TIM1_CH2", "TIM1_CH3"} <= control, sorted(control)
    assert "FOC_EN" in control
    markdown = result.markdown
    # The endpoint-consistency slot is the TIM1 case's mechanical entry, and it is
    # a TODO like every other judgement.
    assert len([line for line in markdown.splitlines()
                if line.startswith("- endpointConsistency: ")]) == len(control)
    assert "TIM1_CH1" in markdown
    # 网名 vs 端点: the net's name and the pin's own name are both printed, and the
    # AI (not the tool) decides whether they agree.
    assert "`U1.44(PA10)`" in markdown, "the TIM1_CH1 net's MCU endpoint"
    buses = {(entry["family"]): entry["nets"] for entry in result.section["chains"]["bus"]}
    assert buses["CAN"] == ["CAN_H", "CAN_L", "CAN_RX", "CAN_TX"]
    assert buses["USB"] == ["D+", "D-", "VBUS"]


def test_every_slot_the_summary_counts_is_written_as_todo(robot):
    """The count and the document are two views of one thing; they must agree.

    ``todoSlots`` is what the report carries; the prose is what the AI walks. A
    drift between them would mean the AI is filling slots nobody counted (or the
    reverse), so the arithmetic is checked against the rendered lines.
    """
    result = generate_architecture(robot)
    markdown = result.markdown
    totals = result.section["totals"]
    chains = result.section["chains"]
    expected_chain_slots = (
        len(chains["rails"]) * len(POWER_SLOTS)
        + len(chains["analog"]) * len(ANALOG_SLOTS)
        + len(chains["control"]) * len(CONTROL_SLOTS)
        + len(chains["bus"]) * len(SLOT_VOCABULARY["bus"])
    )
    # Each *key* is counted once: `consistency` is a slot of three chain kinds,
    # and counting it per kind would count the same lines three times.
    keys = sorted(set(POWER_SLOTS + ANALOG_SLOTS + CONTROL_SLOTS + SLOT_VOCABULARY["bus"]))
    written = sum(len(_slots_in(markdown, slot)) for slot in keys)
    assert written == expected_chain_slots
    # ... and the intent table has one row per rail/chain, each row all-TODO.
    intent_rows = [
        line for line in markdown.splitlines()
        if line.startswith("| 轨 ") or line.startswith("| 模拟链 ") or line.startswith("| 控制链 ")
    ]
    assert len(intent_rows) == totals["intentObjects"]
    assert all(row.count(TODO) == len(INTENT_SLOTS) for row in intent_rows)
    assert totals["todoSlots"] == expected_chain_slots + len(intent_rows) * len(INTENT_SLOTS)


# ------------------------------------------------------------ degenerate input


def test_an_empty_model_still_produces_a_valid_skeleton():
    result = generate_architecture(DesignModel())
    assert result.markdown.startswith("# 架构骨架（architecture.md）")
    for heading in ("### 1. 电源树", "### 2. 模拟链", "### 3. 控制链", "### 4. 总线表", "### 5. 设计意图槽位"):
        assert heading in result.markdown
    assert result.section["totals"]["rails"] == 0
    assert result.section["boards"][0]["components"] == 0


def test_unnamed_nets_pins_and_parts_do_not_break_the_skeleton():
    """The shapes a real export can hand over: no net names, no pin names, a part
    with no pins at all, a net with a single pin."""
    model = DesignModel()
    model.components["U1"] = Component(uid="u1", designator="U1", pins=[
        Pin("1", "PA0", "NET1"), Pin("2", None, None),
        Pin("3", "PA1", None), Pin("4", "PA2", None), Pin("5", "PA3", None),
    ])
    model.components["R1"] = Component(uid="r1", designator="R1")  # no pins
    model.components["R2"] = Component(uid="r2", designator="R2", pins=[
        Pin("1", "", "NET1"), Pin("2", "", "NET2")])
    model.nets = {
        "NET1": Net("NET1", [("U1", "1"), ("R2", "1")]),
        "NET2": Net("NET2", [("R2", "2")]),
        "": Net("", [("U1", "2")]),
    }
    result = generate_architecture(model)
    assert "NET1" in result.markdown
    assert result.section["totals"]["rails"] == 0
    # U1 has four port-named pins, so it is a controller candidate and NET1 is a
    # chain even though nothing on this model has a name — the skeleton is written
    # with the same slot blocks, all TODO.
    assert result.section["totals"]["analogChains"] == 1
    # Every slot is still written, so nothing downstream has to guess a format.
    assert f"- quantity: {TODO}" in result.markdown


# ------------------------------------------------------- checkup integration


def test_checkup_writes_the_architecture_beside_the_report(tmp_path, capsys):
    code = cli.main([
        "checkup", "--file", str(ROBOT), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ])
    out = capsys.readouterr().out
    assert code == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert report["schema"] == "boardwise.checkup/4"
    section = report["architecture"]
    assert section["file"] == ARCH_FILE_NAME
    assert section["totals"]["analogChains"] >= 1
    assert section["totals"]["todoSlots"] > 0
    assert [board["title"] for board in section["boards"]] == ["Board1"]
    written = tmp_path / "out" / ARCH_FILE_NAME
    assert written.is_file()
    text = written.read_text(encoding="utf-8")
    assert text.startswith("# 架构骨架（architecture.md）")
    # The file the report points at is byte-identical to a fresh generation with
    # the same shelf: the report's summary and the artifact describe one skeleton.
    from boardwise.core.parts import load_parts

    expected = generate_architecture(
        build_project_model(ROBOT), library=load_parts(SHELF)
    ).markdown
    assert text == expected
    assert "architecture.md" in out


def test_the_key_is_absent_when_the_skeleton_cannot_be_generated(tmp_path, capsys, monkeypatch):
    """``layout_review``'s rule, applied to the skeleton: absent, never empty."""
    from boardwise.core import architecture as arch_module

    def explode(*_args, **_kwargs):
        raise RuntimeError("no skeleton today")

    monkeypatch.setattr(arch_module, "generate_architecture", explode)
    code = cli.main([
        "checkup", "--file", str(GOLDEN), "--out", str(tmp_path / "out"),
        "--library", str(SHELF),
    ])
    capsys.readouterr()
    assert code == 0
    report = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert "architecture" not in report
    assert not (tmp_path / "out" / ARCH_FILE_NAME).exists()
    assert any("架构骨架生成失败" in note for note in report["source"]["notes"])


def test_the_arch_command_prints_or_writes_the_skeleton(tmp_path, capsys):
    path = tmp_path / "arch.md"
    assert cli.main(["arch", str(GOLDEN), "--out", str(path)]) == 0
    out = capsys.readouterr().out
    assert "architecture:" in out and "TODO 槽位" in out
    assert path.read_text(encoding="utf-8").startswith("# 架构骨架（architecture.md）")

    assert cli.main(["arch", str(GOLDEN)]) == 0
    assert capsys.readouterr().out.startswith("# 架构骨架（architecture.md）")

    code = cli.main(["arch", str(tmp_path / "nope.epro2")])
    assert code == 2
    assert "boardwise arch:" in capsys.readouterr().err
