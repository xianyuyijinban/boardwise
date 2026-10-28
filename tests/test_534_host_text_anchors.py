"""534：宿主真的把 Designator / Name 画在哪儿——ch343 页三颗件的实测锚点。

这一批之前的 ch343 库对这三颗件**一句话都没说**（`texts` 空、`valueRow` 空），
于是编译器只能拿自己的 side ladder 猜一个框：框是它自己写的，闸量的也是它自己写的，
宿主画出来的那两行没人量过。本用例把量到的三个姿态钉住，任何人改回猜法都会红。

出处是**宿主自己的页面文档**，不是今天新做的一次真机测量：
`E:/boardwise/evidence/534/discard/document_source.json`（2026-10-23 导出，
`chars=189792`、`truncated=false`）里逐条 ATTR 记录的 x/y。源文档 y 向下，profile 用
y 向上，下面的位移已经换算：

| 件 | 文档里的 origin / pose | Designator | Name | 位移（reference / value） |
| --- | --- | --- | --- | --- |
| USB1（TYPE-C-31-M-12） | (330,-690) rot0 | (305,-755) | (305,-615) | (-25,+65) / (-25,-75) |
| U5（CH343G，当前候选的 U1） | (695,-730) rot180 mirror | (660,-780) | (660,-675) | (-35,+50) / (-35,-55) |
| H1（2x5P-2.54） | (975,-770) rot0 mirror | (965,-800) | (965,-730) | (-10,+30) / (-10,-40) |

`valueRow` 是宿主**真的印出来**的那串：`TYPE-C-31-M-12`、`CH343G`、以及
`PZ254V-22-10-A60-3000`（2x5P 的规格式值写作 `2x5P-2.54`，宿主却按 LCSC 器件名印，
70 单位宽的一行对 40 单位的框——差出来的 30 单位正是闸以前看不见的那块地）。

**本批没做到的事，写在这里而不是藏起来**：加上这三行真实文字之后，当前编译器在这页上
**0 候选**（`.tmp_534/textanchors/compile.log`；ch343 模块的 VCC 旗标无处可挂、hdr 模块的
长 valueRow 与 GND 旗标真重叠），而加上之前是 6 候选。也就是说，旧页之所以合法，是因为
它的文字框是编的。修的方向在编译器侧（模块区域/行分配），不在库——本用例只钉数据。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core import textmetrics
from boardwise.core.symbolprofile import SymbolPose, SymbolProfile

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
LIBRARY = SPECS / "ch343_uart.library.json"

#: symbolRef -> (reference offset, value offset, rotation, mirror, valueRow,
#:               the designator the source document carries)
MEASURED = {
    "TYPE-C-31-M-12-C165948": (
        (-25.0, 65.0), (-25.0, -75.0), 0.0, False, "TYPE-C-31-M-12", "USB1",
    ),
    "CH343G-C2844153": (
        (-35.0, 50.0), (-35.0, -55.0), 180.0, True, "CH343G", "U5",
    ),
    "2x5P-2.54-C49056209": (
        (-10.0, 30.0), (-10.0, -40.0), 0.0, True, "PZ254V-22-10-A60-3000", "H1",
    ),
}

#: The pose the *current* candidate draws each part in
#: (`.tmp_534/textanchors/before/plan.page.json`, byte-identical to the 534 baseline
#: `.tmp_534/stubfix/plan.page.json`; USB1 rot0, U1 rot180+mirror, H1 rot0+mirror).
CANDIDATE_POSE = {
    "TYPE-C-31-M-12-C165948": (0.0, False),
    "CH343G-C2844153": (180.0, True),
    "2x5P-2.54-C49056209": (0.0, True),
}


def _library() -> dict[str, SymbolProfile]:
    payload = json.loads(LIBRARY.read_text(encoding="utf-8"))
    return {
        profile.symbol_ref: profile
        for profile in (SymbolProfile.from_dict(e) for e in payload["profiles"])
    }


#: The five passives whose rows `534 r1` measured on the same render
#: (`.tmp_534/text-profile-measurement-r1/findings.md` sec.2.2): the rot-270 pair is
#: that pose's own measurement, not a rigid turn of the upright declaration.
PASSIVE_MEASURED = {
    "LED0603-RED-C2286": (0.0, -15.0, 20.0, -15.0, -20.0),
    "R0603-5.1k-C23186": (270.0, 10.0, 0.0, 10.0, -10.0),
    "R0603-1k-C21190": (0.0, -10.0, 5.0, -10.0, -15.0),
    "C0805-10uF-C15850": (270.0, 15.0, 0.0, 15.0, -10.0),
    "C0603-100nF-C1590": (0.0, -5.0, 10.0, -5.0, -20.0),
}


def test_the_three_symbols_carry_the_measured_rows_and_no_others():
    """Anchors are stated for the pose they were measured in, and only for it.

    A profile with `texts` empty lets the compiler invent a side ladder; a profile
    with the anchors is the host's own table.  Three profiles of this page are the
    ICs and the header (measured 2026-10-27) and five are the passives (measured
    534 r1 off `actual.svg`); the three rail flags are still deliberately left
    alone — nothing was measured for them, and a guess written into a library is
    worse than an empty list.
    """
    book = _library()
    for symbol, (_ref, _val, rotation, mirror, value_row, _old) in MEASURED.items():
        profile = book[symbol]
        assert [(t.kind, t.x, t.y, t.rotation, t.mirror) for t in profile.texts] == [
            ("reference", MEASURED[symbol][0][0], MEASURED[symbol][0][1], rotation, mirror),
            ("value", MEASURED[symbol][1][0], MEASURED[symbol][1][1], rotation, mirror),
        ], symbol
        assert profile.value_row == value_row, symbol
    for symbol, (rotation, ref_x, ref_y, val_x, val_y) in PASSIVE_MEASURED.items():
        profile = book[symbol]
        assert [(t.kind, t.x, t.y, t.rotation, t.mirror) for t in profile.texts] == [
            ("reference", ref_x, ref_y, rotation, False),
            ("value", val_x, val_y, rotation, False),
        ], symbol
    touched = {s for s, p in book.items() if p.texts or p.value_row}
    assert touched == set(MEASURED) | set(PASSIVE_MEASURED), sorted(touched)


def test_the_box_is_the_measured_anchor_plus_the_string_the_host_draws():
    """`symbol_rows` at the measured pose lands on the measured offset, to the unit.

    The row is anchored at its lower-left corner and is
    :data:`textmetrics.TEXT_ROW_HEIGHT` tall (147/531); the width is the *drawn*
    string's — for H1 that is the 70-unit LCSC device name, not the 40-unit spec
    value, which is the whole reason `valueRow` exists.
    """
    book = _library()
    for symbol, (ref_off, val_off, rotation, mirror, value_row, _old) in MEASURED.items():
        profile = book[symbol]
        rows = textmetrics.symbol_rows(
            profile, (400.0, 300.0), reference="X9", value="spec value",
            pose=SymbolPose(rotation=rotation, mirror=mirror),
        )
        assert [kind for kind, _text, _box in rows] == ["reference", "value"], symbol
        (rkind, rtext, rbox), (vkind, vtext, vbox) = rows
        assert (rbox[0], rbox[1]) == (400.0 + ref_off[0], 300.0 + ref_off[1]), symbol
        assert (vbox[0], vbox[1]) == (400.0 + val_off[0], 300.0 + val_off[1]), symbol
        assert rbox[3] - rbox[1] == pytest.approx(textmetrics.TEXT_ROW_HEIGHT)
        assert vbox[2] - vbox[0] == pytest.approx(
            textmetrics.render_width(value_row), abs=1e-9
        ), f"{symbol}'s value box is the drawn string's width"
        assert vtext == value_row
    header = book["2x5P-2.54-C49056209"]
    assert textmetrics.render_width(header.value_row) > 2 * textmetrics.render_width(
        "2x5P-2.54"
    ), "the long device name is the wider row — otherwise this pins nothing"


def test_the_current_candidate_pose_is_the_pose_the_rows_were_measured_in():
    """The rows have to be readable in the pose the page actually draws.

    Measured for the landed page's own poses (USB1 rot0, U5 rot180+mirror, H1
    rot0+mirror), and the current candidate draws the same three parts in the same
    three poses — so the table is not a comment about a page nobody draws.
    """
    book = _library()
    for symbol, (rotation, mirror) in CANDIDATE_POSE.items():
        profile = book[symbol]
        rows = textmetrics.symbol_rows(
            profile, (0.0, 0.0), reference="X9", value="v",
            pose=SymbolPose(rotation=rotation, mirror=mirror),
        )
        assert len(rows) == 2, (symbol, rotation, mirror)
        assert (rows[0][2][0], rows[0][2][1]) == MEASURED[symbol][0], symbol


@pytest.mark.parametrize("symbol", sorted(MEASURED))
def test_no_entry_claims_to_hold_for_every_pose(symbol: str):
    """Nothing here is written as a universal declaration.

    Both entries are pose-qualified, so the file states "this offset, in this
    pose" twice and never "this offset, always".  That distinction is the whole
    of 531's finding: an upright row and a rotated one are anchored differently
    by the host, and a pose-free entry (the shape 146/147 wrote for the flyback)
    is a claim nobody measured for these three parts.

    Sharp edge, named rather than fixed here (engine side, `textmetrics._pick_text`):
    when no entry matches the part's pose the lookup's documented **last resort**
    is ``entries[0]`` — so a pose nobody measured still borrows this row instead
    of falling back to the caller's ladder.  That is why only measured poses are
    written, and why a second pose needs its own measurement rather than a copy.
    """
    profile = _library()[symbol]
    assert profile.texts, symbol
    for entry in profile.texts:
        assert entry.rotation is not None and entry.mirror is not None, (
            symbol, entry,
        )
    rotation, mirror = CANDIDATE_POSE[symbol]
    exact = textmetrics.symbol_rows(
        profile, (0.0, 0.0), reference="X9", value="v",
        pose=SymbolPose(rotation=rotation, mirror=mirror),
    )
    assert len(exact) == 2, symbol
    assert (exact[0][2][0], exact[0][2][1]) == MEASURED[symbol][0], symbol


def test_every_added_row_names_its_source_and_claims_no_fresh_measurement():
    """The provenance is in the file, and it says what it is: a document read.

    534's discipline (and 531's): a number in a library has to name where it came
    from.  These three say "read out of the exported page document of 2026-10-23"
    and explicitly "NOT a fresh measurement", so nobody later mistakes them for a
    landing made today.
    """
    book = _library()
    for symbol, (_r, _v, _rot, _mir, _row, old) in MEASURED.items():
        source = book[symbol].source
        assert "text rows measured 2026-10-27" in source, symbol
        assert "evidence/534/discard/document_source.json" in source, symbol
        assert "NOT a fresh measurement" in source, symbol
        assert f"{old} at origin" in source, symbol
        assert "truncated=false" in source, symbol
        # the pin/body measurement that was already there is kept, not replaced
        assert "sch.component_pins answered" in source, symbol
