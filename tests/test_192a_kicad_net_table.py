"""192A-3/4：KiCad 网表的**一把尺**与**重复行**。

**192A-3（两把尺）**：``netIdNote`` 曾经自己重写一遍「``net#`` 前缀」筛选，
而 ``parsers.kicad.unnamed_net_names()`` 才是这个形状的产地。两处必然漂移，而这条
披露的全部价值就是「报告里的数 = 读盘器说的数」。本文件用一条**架构级**断言把
那把尺钉回原产地：前缀筛选只许出现在 ``parsers/kicad.py``。

**192A-4（静默胜出）**：文件自己的 ``(net N "NAME")`` 表给同一个序号写了两行不同
名字时，``_net_table`` 用后写的覆盖先写的——**一声不响**。后果不是排版问题：一条
裸 ``(net 2)`` 的走线会被归到后写的那个名字名下，而文件名里另一处内联写着
``(net 2 "CAN_L")``，同一块铜于是裂成两条网，按网名读的检查两边都看不全。
口径：**保留首次**（先写的行是文件先声明的），并把这次覆盖**披露出来**——和丢名字
那条披露同一个落点（``netIdNote``）。
"""

from __future__ import annotations

from pathlib import Path

from boardwise.engines.pcbreview import run_pcb_review
from boardwise.parsers.kicad import read_kicad_board, unnamed_net_names

FIX = Path(__file__).parent / "fixtures" / "kicad_min"
BARE = FIX / "kicad_bare_net.kicad_pcb"
NAMED = FIX / "kicad_min.kicad_pcb"
REPO = Path(__file__).resolve().parents[1]

#: 一行一行的 ``(net N "NAME")`` 表 + 一条**裸 id** 走线 + 一条**内联名**走线。
#: 序号 2 被写了两次：先 ``CAN_L``，后 ``OTHER``。
DUP_TABLE = (
    '(net 0 "")\n'
    '(net 1 "CAN_H")\n'
    '(net 2 "CAN_L")\n'
    '(net 2 "OTHER")\n'
    '(segment (start 0 0) (end 10 0) (layer "F.Cu") (width 0.25) (net 1))\n'
    '(segment (start 0 5) (end 10 5) (layer "F.Cu") (width 0.25) (net 2))\n'
    '(segment (start 0 8) (end 10 8) (layer "F.Cu") (width 0.25) (net 2 "CAN_L"))\n'
)


def _board(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "t.kicad_pcb"
    path.write_text(
        '(kicad_pcb (version 20230121) (generator "pcbnew")\n'
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal))\n'
        f"{body}\n)",
        encoding="utf-8",
    )
    return path


def test_a_duplicated_id_keeps_the_first_name(tmp_path):
    """The file's first row for an id is the one it declared; the later is noise.

    Both rows are the file's own words, so this reader may not adjudicate — but
    it may not silently *pick the last one* either (which is what it did). The
    bare ``(net 2)`` copper and the inline ``(net 2 "CAN_L")`` copper are one
    net, and it is the net the file named first.
    """
    board = read_kicad_board(_board(tmp_path, DUP_TABLE))
    assert "OTHER" not in board.net_names(), "后写的名字不该覆盖先写的"
    assert "CAN_L" in board.net_names()
    assert len(board.net("CAN_L").tracks) == 2, "裸 id 与内联名是同一条网"


def test_the_overridden_row_is_disclosed_on_the_board_entry(tmp_path):
    """Silently dropping a name is the defect — so the entry says it happened."""
    path = _board(tmp_path, DUP_TABLE)
    _findings, section = run_pcb_review(path)
    note = section["boards"][0]["netIdNote"]
    assert "2" in note and "CAN_L" in note and "OTHER" in note
    assert section["rules_errored"] == []


def test_a_board_without_conflicts_keeps_the_disclosure_absent(tmp_path):
    """Absent, not empty (钉 5): a clean table gets no line."""
    _findings, section = run_pcb_review(NAMED)
    assert "netIdNote" not in section["boards"][0]


def test_the_report_counts_with_the_readers_own_yardstick():
    """192A-3: the disclosed ids are exactly ``unnamed_net_names(board)``."""
    board = read_kicad_board(BARE)
    _findings, section = run_pcb_review(BARE)
    note = section["boards"][0]["netIdNote"]
    for name in unnamed_net_names(board):
        assert name in note
    assert f"{len(unnamed_net_names(board))} 个网序号" in note


def test_the_unnamed_prefix_is_filtered_in_one_place_only():
    """The yardstick lives in ``parsers/kicad.py`` and nowhere else (192A-3).

    A prefix filter over ``board.nets`` is one line, so it will be rewritten
    wherever a consumer wants it; then the number in the report and the number
    the reader means can drift apart, and this one is a **disclosure** — the
    only thing it has to be is the reader's own count.
    """
    offenders = []
    for path in sorted((REPO / "src" / "boardwise").rglob("*.py")):
        if path.name == "kicad.py" and path.parent.name == "parsers":
            continue
        text = path.read_text(encoding="utf-8")
        if "UNNAMED_NET_PREFIX" in text and "startswith(UNNAMED_NET_PREFIX)" in text:
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], f"前缀筛选要在 parsers/kicad.py 的 unnamed_net_names 里做，不在这里：{offenders}"
