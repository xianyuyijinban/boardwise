"""E 批（return-path-power-bus）：供给母线名 ``V_<数字>V``（``V_310V``）.

岳 2026-10-30 实报：``pcb-foc-return-path`` 把 ``V_310V`` 落进未识别清单，因为
这个拼法既不是栅极/开关节点/相电流名，也不在任何前缀族里 —— 而它是功率级的
高压母线，回流路径的第一件事就是它。本批只在 :func:`is_power_net` 上补**一族
窄名字**（:data:`POWER_BUS_NET_PATTERN`），并让 ``POWER_NET_PREFIXES`` 同步一个
``"V_"`` 词条，使 R11/R13/R5 行里插值的词表不漂移。

本文件钉的**只有名字面与它的投影后果**：

* ``V_310V`` / ``V_5V`` / ``V_3.3V``（含大小写、空白、小数）被接纳；
* 形似名（``VCC`` / ``VDD`` / ``V310`` / ``NET1`` / ``V_FOO`` / ``V_`` /
  ``V_310`` / ``V_3V3`` 等）不误收 —— 判据是「名字写不写自己的电压」，不是
  ``startswith("V_")``；
* D 批的六路栅极名（``UH``/``UL``/``VH``/``VL``/``WH``/``WL``）与 ``GH``/``GL``
  旧拼法照旧；
* 实跑 :class:`FocReturnPath`：把 1.0.0 板上原本落在未识别清单里的 ``+24V``
  **只改名**成 ``V_310V``，它就从清单里搬到一条投影测量行；改名成 ``V_FOO`` 则
  仍留在清单里。**只改名不改几何**，所以两边的 ``return_path_cover`` 读数必须
  相同 —— 这条就是「本批没动 ``return_path_projection`` / ``return_path_cover`` /
  PLANE 语义」的钉子；
* ``V_310V`` 一类母线进的是**同一个**筛子，所以 R11 也会为它出一条（INFO）
  宽度读数 —— 这是补名字族的已知代价，钉在这里而不是留给读者猜。

**合成，不声称复测实板**：报这块 ``V_310V`` 的真实板不在仓库里（``tests/fixtures``
里没有任何网名匹配该 pattern，实测 0 条），证据缺口记在
``outputs/review/return-path-power-bus.md``。
"""

from __future__ import annotations

import copy
import functools
from pathlib import Path

import pytest

from boardwise.core.parts import load_parts
from boardwise.parsers.epro2_model import build_design_model
from boardwise.parsers.epru import extract_board, load_epro2_source
from boardwise.rules.facts import default_library_path
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.foc import (
    GATE_NET_PATTERN,
    POWER_BUS_NET_PATTERN,
    POWER_NET_PREFIXES,
    FocGateTraceWidth,
    is_power_net,
)
from boardwise.rules.pcb.focground import FocReturnPath, return_path_cover

FIXTURES = Path(__file__).parent / "fixtures"
#: 毕设FOC 1.0.0 — the board whose ``+24V`` rail sits on the power stage and
#: whose layers 15 / 16 are ``PLANE`` (the two measured anchors this file needs).
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"

#: The one net this file renames: it carries 4 tracks and sits on the bulk
#: capacitor, so it is a genuine power-stage net under a name the old sieve
#: could not place.
RAIL = "+24V"


@functools.lru_cache(maxsize=1)
def _foc() -> tuple[object, object]:
    """``(board, model)`` for 1.0.0's PCB1, parsed once per test session."""
    source = load_epro2_source(FOC_100)
    document = next(iter(source.documents_of_type("PCB")))
    return (
        extract_board(document, source.footprints(), source.stats),
        build_design_model(source, document),
    )


@functools.lru_cache(maxsize=1)
def _library():
    return load_parts(default_library_path())


def _renamed(old: str, new: str) -> tuple[object, object]:
    """The same board with **one net renamed** — geometry untouched.

    Only the name travels: the net's pads and tracks keep their coordinates,
    layers and widths, and the ``nets`` index is re-keyed. This is what makes
    「projection unchanged, name changed」 a fair comparison.
    """
    board, model = _foc()
    board = copy.deepcopy(board)
    net = board.nets.pop(old)
    net.name = new
    for pad in net.pads:
        pad.net = new
    for track in net.tracks:
        track.net = new
    board.nets[new] = net
    return board, model


def _r5(board, model) -> list:
    return FocReturnPath().check_with_library(
        PcbReviewContext(board=board, pcb_model=model), _library()
    )


def _list_nets(rows: list) -> set[str]:
    """The nets of the row that calls itself the 未识别清单 (exactly one)."""
    listed = [row for row in rows if "未识别清单" in row.message]
    assert len(listed) == 1, [row.message[:40] for row in rows]
    return set(listed[0].target.net_refs)


def _projection_row(rows: list, net: str):
    hits = [row for row in rows if row.target.net_refs == [net]]
    assert len(hits) == 1, [row.target.net_refs for row in rows]
    return hits[0]


# ---------------------------------------------------------------------------
# 一、名字面：母线正例、形似名反例、D 批栅极族与旧拼法不受影响
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "V_310V",
        "V_5V",
        "V_24V",
        "V_3.3V",
        "V_12.75V",
        "V_01V",
        "v_310v",
        "V_310v",
        "V_310V",  # repeated on purpose: the family is not case-sensitive
        "  V_310V  ",  # editor-side whitespace is folded
        "V_1000V",
    ],
)
def test_a_bus_name_that_states_its_voltage_is_a_power_net(name):
    assert POWER_BUS_NET_PATTERN.match(name.strip().upper()), name
    assert is_power_net(name), name


@pytest.mark.parametrize(
    "name",
    [
        "VCC",
        "VDD",
        "V310",          # no separator: could be a signal index
        "V3.3V",         # no separator
        "NET1",
        "V_FOO",         # the prefix without the voltage
        "V_",            # the prefix alone
        "V_310",         # no unit
        "V_3V3",         # the unit in the middle
        "V_310V_1",      # trailing suffix: not the stated family
        "V_310 V",       # space inside
        "$V_310V",       # editor-generated prefix
        "310V",
        "X_V_310V",      # the family is anchored at the start of the name
        "TIM1_CH1",
        "",
    ],
)
def test_names_that_only_look_like_a_bus_are_refused(name):
    assert not is_power_net(name), name


def test_the_bus_entry_is_a_word_list_fact_not_a_prefix_test():
    """``"V_"`` in the tuple must not become ``startswith("V_")``.

    The tuple is interpolated into R11/R13/R5 rows as the sieve's word list, so
    the family has to be in it; the *matcher* is the pattern. A reader who took
    the tuple as the test would admit ``V_FOO`` — which is why this file pins
    the difference rather than only the presence of the string.
    """
    assert "V_" in POWER_NET_PREFIXES
    assert POWER_NET_PREFIXES.count("V_") == 1
    assert len(set(POWER_NET_PREFIXES)) == len(POWER_NET_PREFIXES)
    assert "V_FOO".startswith("V_") and not is_power_net("V_FOO")
    assert POWER_BUS_NET_PATTERN.pattern == r"^V_\d+(?:\.\d+)?V$"


def test_the_gate_families_and_the_legacy_spelling_are_untouched():
    """D 批的六路名与 ``GH``/``GL`` 照旧 —— 本批不碰栅极名族。"""
    for name in ("UH", "UL", "VH", "VL", "WH", "WL", "GH", "GL"):
        assert is_power_net(name), name
        assert is_power_net(name + "1"), name
        assert GATE_NET_PATTERN.match(name), name
    for name in ("UH", "UL", "VH", "VL", "WH", "WL", "GH", "GL"):
        alternatives = GATE_NET_PATTERN.pattern
        assert name in alternatives, name
        assert name in POWER_NET_PREFIXES, name
    # A bus name is not a gate name: the two families stay disjoint.
    assert not GATE_NET_PATTERN.match("V_310V")
    assert not GATE_NET_PATTERN.match("V_5V")


# ---------------------------------------------------------------------------
# 二、实跑 R5：改名成母线 → 投影行；改名成形似名 → 仍在未识别清单
# ---------------------------------------------------------------------------


def test_baseline_rail_is_in_the_unrecognised_list_before_the_rename():
    """The measured starting point: ``+24V`` has tracks, is on the power stage,
    and no sieve family places it — so it is listed, not projected."""
    board, model = _foc()
    assert len(board.tracks_for_net(RAIL)) == 4
    rows = _r5(board, model)
    assert RAIL in _list_nets(rows)
    assert not [row for row in rows if row.target.net_refs == [RAIL]]


def test_r5_gives_v_310v_an_actual_projection_row():
    board, model = _renamed(RAIL, "V_310V")
    rows = _r5(board, model)
    row = _projection_row(rows, "V_310V")
    assert row.rule_id == "pcb-foc-return-path"
    assert row.severity == "INFO"
    assert "return-path projection of 'V_310V'" in row.message
    assert "covered-by-construction 4 over 4 trace(s)" in row.message
    assert "no gap found on any reference layer" in row.message
    assert "V_310V" not in _list_nets(rows)
    # The list shrinks by exactly the one net that changed name.
    baseline, baseline_model = _foc()
    assert _list_nets(rows) == _list_nets(_r5(baseline, baseline_model)) - {RAIL}


def test_the_projection_geometry_is_the_same_before_and_after_the_rename():
    """Only the name moved: ``return_path_cover`` reads identically.

    This is the pin for 「本批不动 ``return_path_projection`` / ``return_path_cover``
    / 阈值」 — if a future change altered the projection, the two readings would
    part company while the rename still looked harmless.
    """
    board, _model = _foc()
    renamed, _renamed_model = _renamed(RAIL, "V_310V")
    assert return_path_cover(renamed, "V_310V")[0] == return_path_cover(board, RAIL)[0]
    assert return_path_cover(renamed, "V_310V")[0] == {"covered-by-construction": 4}


def test_a_bus_lookalike_still_lands_in_the_unrecognised_list():
    """``V_FOO`` is the near-miss: the prefix without the voltage stays UNKNOWN."""
    board, model = _renamed(RAIL, "V_FOO")
    rows = _r5(board, model)
    assert "V_FOO" in _list_nets(rows)
    assert not [row for row in rows if row.target.net_refs == ["V_FOO"]]
    baseline, baseline_model = _foc()
    assert _list_nets(rows) == (
        _list_nets(_r5(baseline, baseline_model)) - {RAIL}
    ) | {"V_FOO"}


def test_plane_layers_still_read_covered_by_construction_for_the_bus_net():
    """既有的 PLANE 语义不动：1.0.0 的 15/16 是 PLANE，母线照旧构造性覆盖。"""
    board, model = _renamed(RAIL, "V_310V")
    assert board.layer(15).layer_type == "PLANE"
    assert board.layer(16).layer_type == "PLANE"
    row = _projection_row(_r5(board, model), "V_310V")
    evidence = "\n".join(row.evidence)
    assert "**PLANE** layer" in evidence
    assert "构造性完整覆盖" in evidence
    assert "no segment on any reference layer read as partial or uncovered" in evidence
    assert "gap on trace" not in evidence


def test_r11_reads_the_bus_family_too_and_still_applies_no_threshold():
    """The已知代价 of one shared sieve: R11 measures the rail as well.

    It stays INFO 出数不出判定 — TI's 20 mil is quoted and **not applied** —
    which is the same contract the gate rows have; naming this here keeps the
    widening honest instead of leaving a surprise row on real boards.
    """
    board, _model = _renamed(RAIL, "V_310V")
    rows = FocGateTraceWidth().check(PcbReviewContext(board=board))
    hits = [row for row in rows if "V_310V" in str(row.target.net_refs)]
    assert len(hits) == 1, [row.target.net_refs for row in rows]
    row = hits[0]
    assert row.severity == "INFO"
    assert "power-path net 'V_310V'" in row.message
    assert "4 track(s)" in row.message
    assert "'V_'" in row.message or "'V_'" in "\n".join(row.evidence)
    assert "**not applied**" in "\n".join(row.evidence)
    assert row.target.measurement is not None
    assert row.target.measurement["kind"] == "width"
