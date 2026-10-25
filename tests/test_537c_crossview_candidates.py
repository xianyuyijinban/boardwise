"""537C1：跨视图差异只标 ``suspected``，并给出机器可读的候选映射。

189A2 把「原理图视图说某脚孤零零、PCB 视图说这个网有伴」做成了报告上的差异
（``pcb_review.boards[].crossView.lonely``）。差异本身是对的，但它到人手里时是
一段散文，读者只能自己去归档里翻「同名网上到底有谁」，手工拼出来的候选既容易
拼错，也容易在下一句话里被读成「已确认」。537C 的处置不是重写算法，而是：

* ``cross_view_lonely_pins`` 的**行形状与算法一字不动**（本文件第 9 节逐字段钉住）；
* ``cross_view_section`` 只在 ``checked:true`` **且** ``lonely`` 非空时，**加性**
  写入 ``status='suspected'`` 与 ``candidateMappings``；空 ``lonely`` 与全部
  ``checked:false`` 的字典**逐字段不变**，不添加 ``status`` / ``candidateMappings``
  / ``confirmed``；
* 每条映射只从**同名网**（``schematic.nets`` 键名逐字等于该行的 ``pcbNet``）的
  归档原理图成员里取候选，不拿 PCB 成员或电路常识去猜；同位号不同脚（``U9.3``
  对 ``U9.1``）原样保留——它正是「这条差异可能是位号重编号」的那一半证据；
* 映射是**人工核查候选**，不是判决：两侧都是**归档**读数，谁都不是 live 证据，
  模块不判哪一侧正确。

合成模型全部匿名（``U9``/``R9``/``ALPHA``），不涉及任何真实工程。
"""

from __future__ import annotations

import json

import pytest

from boardwise.core.model import Component, DesignModel, Net, Pin
from boardwise.engines.pcbreview import (
    CROSS_VIEW_MIN_PINS,
    cross_view_lonely_pins,
    cross_view_section,
)

#: 189A2 的原始行形状：这六个键与这个顺序是本文件要保住的兼容面。
OLD_ROW_KEYS = [
    "designator", "pin", "schematicNet", "schematicMembers", "pcbNet", "pcbMembers",
]

#: 537C1 的映射形状（逐字按契约）。
MAPPING_KEYS = [
    "pcbPin", "pcbNet", "pcbMembers", "schematicCandidates", "evidence",
]

EVIDENCE = {
    "pcb": "archivePcb",
    "schematic": "archiveSchematic",
    "basis": "same-net-name",
}


# --------------------------------------------------------------------------
# anonymous synthesised models
# --------------------------------------------------------------------------


def _model(
    parts: dict[str, list[str]],
    nets: dict[str, list[tuple[str, str]]] | None = None,
) -> DesignModel:
    """A ``DesignModel``: pin numbers per designator, then ``name -> members``."""
    model = DesignModel()
    for designator, numbers in parts.items():
        model.components[designator] = Component(
            uid=f"uid-{designator}",
            designator=designator,
            pins=[Pin(number=number, name=f"n{number}") for number in numbers],
        )
    for name, members in (nets or {}).items():
        model.nets[name] = Net(name=name, pins=list(members))
    return model


def _board() -> tuple[DesignModel, DesignModel]:
    """One lonely pin whose PCB net has company **and** a same-named schematic net.

    ``U9.1`` sits alone on the schematic's ``NET7`` while the PCB puts it on
    ``ALPHA`` with ``R9.1`` and ``U9.3``. The schematic has its own ``ALPHA`` —
    ``R9.1`` and ``U9.3`` — so the row's candidates are exactly those two: the
    same designator's *other* pin must survive, because «this is a renumbering»
    is one of the two readings the difference allows.
    """
    schematic = _model(
        {"U9": ["1", "2", "3", "4", "5", "6"], "R9": ["1", "2"]},
        {
            "NET7": [("U9", "1")],
            "ALPHA": [("R9", "1"), ("U9", "3")],
            "BETA": [("U9", "2"), ("R9", "2")],
        },
    )
    pcb = _model(
        {"U9": ["1", "2", "3", "4", "5", "6"], "R9": ["1", "2"]},
        {
            "ALPHA": [("R9", "1"), ("U9", "1"), ("U9", "3")],
            "BETA": [("U9", "2"), ("R9", "2")],
        },
    )
    return schematic, pcb


def _agreed() -> tuple[DesignModel, DesignModel]:
    """Both views carry the same pin on the same-named net: nothing to suspect."""
    schematic = _model(
        {"U9": ["1", "2", "3"], "R9": ["1", "2"]},
        {"ALPHA": [("U9", "1"), ("R9", "1")]},
    )
    pcb = _model(
        {"U9": ["1", "2", "3"], "R9": ["1", "2"]},
        {"ALPHA": [("U9", "1"), ("R9", "1")]},
    )
    return schematic, pcb


class _Exploding:
    """A model whose netlist reading raises — the third ``checked: false``."""

    components: dict = {}

    @property
    def nets(self):
        raise RuntimeError("model went sideways")


class _OneReadNets:
    """A schematic whose ``nets`` may be read once and chokes on the second read.

    The lonely pass is the first read; building the candidate mappings is a
    second one. If *that* read raises, the section may not come back
    ``checked: true`` with the mappings silently missing — the failure has to
    land in the existing ``checked: false`` disclosure, reason and all.
    """

    def __init__(self, model: DesignModel) -> None:
        self._model = model
        self._reads = 0

    @property
    def components(self) -> dict[str, Component]:
        return self._model.components

    @property
    def unproven_nets(self) -> dict[str, tuple[str, ...]]:
        return self._model.unproven_nets

    @property
    def nets(self) -> dict[str, Net]:
        self._reads += 1
        if self._reads > 1:
            raise RuntimeError("candidate pass went sideways")
        return self._model.nets


# --------------------------------------------------------------------------
# 1. the mapping: shape, PCB members, same-name candidates
# --------------------------------------------------------------------------


def test_a_lonely_pin_carries_one_suspected_mapping():
    schematic, pcb = _board()
    section = cross_view_section(schematic, pcb)

    assert section["checked"] is True
    assert section["status"] == "suspected"
    assert len(section["candidateMappings"]) == 1
    mapping = section["candidateMappings"][0]

    assert list(mapping) == MAPPING_KEYS
    assert mapping == {
        "pcbPin": "U9.1",
        "pcbNet": "ALPHA",
        "pcbMembers": ["R9.1", "U9.1", "U9.3"],
        "schematicCandidates": ["R9.1", "U9.3"],
        "evidence": EVIDENCE,
    }


def test_the_pcb_members_are_the_real_whole_net_not_a_count():
    """``cross_view_lonely_pins`` only reported a count; the mapping lists them."""
    schematic, pcb = _board()
    mapping = cross_view_section(schematic, pcb)["candidateMappings"][0]

    real = {f"{designator}.{number}" for designator, number in pcb.nets["ALPHA"].pins}
    assert set(mapping["pcbMembers"]) == real
    assert "U9.1" in mapping["pcbMembers"]  # the lonely pin itself is a member
    assert len(mapping["pcbMembers"]) == len(pcb.nets["ALPHA"].pins)


def test_candidates_come_only_from_a_same_named_schematic_net():
    """A same designator's *other* pin is kept — it is evidence, not a mismatch."""
    schematic, pcb = _board()
    mapping = cross_view_section(schematic, pcb)["candidateMappings"][0]

    assert mapping["schematicCandidates"] == ["R9.1", "U9.3"]
    assert "U9.1" not in mapping["schematicCandidates"]
    assert mapping["schematicCandidates"] != mapping["pcbMembers"]


def test_no_same_named_schematic_net_is_an_empty_candidate_list():
    """No net by that name on the schematic side: candidates ``[]``, not a guess."""
    schematic = _model(
        {"U9": ["1", "2", "3"], "R9": ["1", "2"]},
        {"NET7": [("U9", "1")]},
    )
    pcb = _model(
        {"U9": ["1", "2", "3"], "R9": ["1", "2"]},
        {"ALPHA": [("U9", "1"), ("R9", "1")]},
    )
    mapping = cross_view_section(schematic, pcb)["candidateMappings"][0]
    assert mapping["pcbNet"] == "ALPHA"
    assert mapping["schematicCandidates"] == []
    assert mapping["pcbMembers"] == ["R9.1", "U9.1"]


def test_duplicate_members_are_deduped_and_pins_sort_numerically():
    """``U9.2`` before ``U9.10``; a repeated member is written once."""
    schematic = _model(
        {"U9": ["1", "2", "3", "9", "10"], "R9": ["1", "2"]},
        {"NET7": [("U9", "1")],
         "ALPHA": [("U9", "10"), ("U9", "9"), ("U9", "10"), ("R9", "2"), ("U9", "2")]},
    )
    pcb = _model(
        {"U9": ["1", "2", "3", "9", "10"], "R9": ["1", "2"]},
        {"ALPHA": [("U9", "10"), ("U9", "2"), ("U9", "10"), ("R9", "1"), ("U9", "1")]},
    )
    mapping = cross_view_section(schematic, pcb)["candidateMappings"][0]
    assert mapping["pcbMembers"] == ["R9.1", "U9.1", "U9.2", "U9.10"]
    assert mapping["schematicCandidates"] == ["R9.2", "U9.2", "U9.9", "U9.10"]


def test_mappings_keep_the_lonely_rows_order():
    schematic = _model(
        {"U9": ["1", "2", "3"], "R9": ["1", "2"]},
        {"NET7": [("U9", "1")], "NET8": [("U9", "2")],
         "ALPHA": [("R9", "1"), ("U9", "3")], "BETA": [("R9", "2")]},
    )
    pcb = _model(
        {"U9": ["1", "2", "3"], "R9": ["1", "2"]},
        {"ALPHA": [("U9", "1"), ("R9", "1")], "BETA": [("U9", "2"), ("R9", "2")]},
    )
    section = cross_view_section(schematic, pcb)
    assert [row["pin"] for row in section["lonely"]] == ["1", "2"]
    assert [mapping["pcbPin"] for mapping in section["candidateMappings"]] == [
        "U9.1", "U9.2",
    ]
    assert [mapping["schematicCandidates"] for mapping in section["candidateMappings"]] == [
        ["R9.1", "U9.3"], ["R9.2"],
    ]


# --------------------------------------------------------------------------
# 2. suspected, never confirmed
# --------------------------------------------------------------------------


def test_a_same_net_name_is_a_candidate_not_a_confirmation():
    schematic, pcb = _board()
    section = cross_view_section(schematic, pcb)
    assert section["status"] == "suspected"
    assert "confirmed" not in json.dumps(section)
    for mapping in section["candidateMappings"]:
        assert mapping["evidence"]["basis"] == "same-net-name"


def test_both_sides_are_named_as_archive_readings():
    """Neither side is live evidence: the evidence block says which archive read it."""
    schematic, pcb = _board()
    mapping = cross_view_section(schematic, pcb)["candidateMappings"][0]
    assert mapping["evidence"] == {
        "pcb": "archivePcb",
        "schematic": "archiveSchematic",
        "basis": "same-net-name",
    }


# --------------------------------------------------------------------------
# 3. the old shapes: byte-for-byte, no new keys
# --------------------------------------------------------------------------


def test_an_empty_lonely_list_keeps_the_old_exact_shape():
    """「一致」 is a reading, and it may not have ``status`` invented onto it."""
    schematic, pcb = _agreed()
    section = cross_view_section(schematic, pcb)
    assert section == {"checked": True, "minPins": CROSS_VIEW_MIN_PINS, "lonely": []}
    assert list(section) == ["checked", "minPins", "lonely"]
    assert "candidateMappings" not in section and "status" not in section


def test_all_unchecked_paths_keep_the_old_exact_shape():
    """Three ``checked: false`` reasons, none of them carrying a partial suspicion."""
    schematic, pcb = _board()
    unchecked = cross_view_section(None, pcb)
    no_netlist = cross_view_section(schematic, None)
    choked = cross_view_section(_Exploding(), pcb)

    for section in (unchecked, no_netlist, choked):
        assert list(section) == ["checked", "reason"]
        assert section["checked"] is False
        assert "candidateMappings" not in section
        assert "status" not in section
        assert "confirmed" not in json.dumps(section)

    assert "未查" in unchecked["reason"] and "不是一致" in unchecked["reason"]
    assert "RuntimeError" in choked["reason"] and "model went sideways" in choked["reason"]


def test_a_candidate_read_that_chokes_is_disclosed_not_a_bare_suspected():
    """No ``checked: true`` may exist without its ``candidateMappings``."""
    schematic, pcb = _board()
    section = cross_view_section(_OneReadNets(schematic), pcb)

    assert section["checked"] is False
    assert "RuntimeError" in section["reason"]
    assert "candidate pass went sideways" in section["reason"]
    assert "lonely" not in section
    assert "candidateMappings" not in section
    assert "status" not in section


# --------------------------------------------------------------------------
# 4. the raw rows and the old helper are untouched
# --------------------------------------------------------------------------


def test_the_raw_lonely_rows_are_not_rewritten():
    schematic, pcb = _board()
    rows = cross_view_lonely_pins(schematic, pcb)
    assert rows == [{
        "designator": "U9",
        "pin": "1",
        "schematicNet": "NET7",
        "schematicMembers": 1,
        "pcbNet": "ALPHA",
        "pcbMembers": 3,
    }]
    assert list(rows[0]) == OLD_ROW_KEYS
    assert cross_view_section(schematic, pcb)["lonely"] == rows


def test_the_old_helper_answers_on_its_own_without_the_mapping_layer():
    """``cross_view_lonely_pins`` keeps its own contract: counts, no mappings."""
    schematic, pcb = _board()
    rows = cross_view_lonely_pins(schematic, pcb)
    assert isinstance(rows[0]["pcbMembers"], int)
    assert "candidateMappings" not in rows[0]
    assert cross_view_lonely_pins(schematic, pcb, min_pins=2) == rows


@pytest.mark.parametrize("board", [_board, _agreed], ids=["differ", "agree"])
def test_checked_sections_never_carry_a_half_written_suspicion(board) -> None:
    """The structural invariant, over both a differ and an agree board."""
    schematic_part, pcb_part = board()
    section = cross_view_section(schematic_part, pcb_part)
    assert section["checked"] is True
    if section["lonely"]:
        assert section["status"] == "suspected"
        assert len(section["candidateMappings"]) == len(section["lonely"])
        for mapping in section["candidateMappings"]:
            assert list(mapping) == MAPPING_KEYS
    else:
        assert "status" not in section
        assert "candidateMappings" not in section
