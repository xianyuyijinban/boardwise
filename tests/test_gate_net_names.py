"""D 批（gate-net-names）：六路栅极网名 ``UH`` / ``UL`` / ``VH`` / ``VL`` / ``WH`` / ``WL``.

岳 2026-10-30 实报：一块不在仓库里的真实板把六路栅极命名为 U/V/W 相 × H/L 边，
``GATE_NET_PATTERN`` 只认 ``GH`` / ``GL``，R11 于是只出一行「no net … recognises」。

本文件钉的**只有名字面**：

* 六路名及其可选相字母/数字后缀被 :func:`is_power_net` 接纳，``GH``/``GL`` 旧拼法
  照旧；
* 只在字面上「像」一族的名字（``U`` / ``U1`` / ``UHX1`` / ``UHA1B`` / ``TIM1_CH1``
  这类）不误收；
* ``POWER_NET_PREFIXES`` 与 :data:`GATE_NET_PATTERN` 同步，报告里的词表不漂移；
* 实跑 :class:`FocGateTraceWidth`，六路各出一行读数，且 TI 20 mil 参考照旧「引用
  不判定」；没有可识别网名时仍只出一行 no-net INFO。

**合成，不声称复测实板**：报告里没有这块板，测试用合成六路 track 读数；真实板上
的数值仍是证据缺口（``outputs/review/gate-net-names.md``）。
"""

from __future__ import annotations

import re

import pytest

from boardwise.core.geometry import BoardGeometry, NetGeometry, Point, TrackSegment
from boardwise.rules.pcb.base import PcbReviewContext
from boardwise.rules.pcb.foc import (
    GATE_NET_PATTERN,
    POWER_NET_PREFIXES,
    FocGateTraceWidth,
    FocTrackCorners,
    gate_nets_of,
    is_power_net,
)

SIX = ("UH", "UL", "VH", "VL", "WH", "WL")
LEGACY = ("GH", "GL")


def _track(
    track_id: str,
    net: str,
    start: tuple[float, float],
    end: tuple[float, float],
    width: float = 10.0,
    layer_id: int | None = 1,
) -> TrackSegment:
    return TrackSegment(
        id=track_id,
        net=net,
        layer_id=layer_id,
        start=Point(*start),
        end=Point(*end),
        width=width,
    )


def _board(tracks=(), bare_nets=()) -> BoardGeometry:
    """A synthetic board whose net table comes from its copper (+ bare names)."""
    board = BoardGeometry(source="synthetic")
    board.tracks = list(tracks)
    nets: dict[str, NetGeometry] = {
        name: NetGeometry(name=name) for name in bare_nets
    }
    for track in board.tracks:
        if track.net:
            nets.setdefault(track.net, NetGeometry(name=track.net)).tracks.append(track)
    board.nets = nets
    return board


def _six_gate_board(**kwargs) -> BoardGeometry:
    tracks = [
        _track(f"{name.lower()}1", name, (0.0, index * 100.0), (300.0, index * 100.0))
        for index, name in enumerate(SIX)
    ]
    return _board(tracks=tracks, **kwargs)


def _r11(board: BoardGeometry):
    return FocGateTraceWidth().check(PcbReviewContext(board=board))


# ---------------------------------------------------------------------------
# 一、名字面：六路名 + 后缀，旧拼法兼容，形似名不误收
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", SIX)
def test_each_phase_name_and_its_suffixes_is_a_gate_net(name):
    """``UH`` / ``UHA`` / ``UH1`` / ``UHA1`` — the same suffix rule as ``GH``."""
    for spelling in (name, name + "A", name + "1", name + "A1"):
        assert is_power_net(spelling), spelling
        assert is_power_net(spelling.lower()), spelling
        assert GATE_NET_PATTERN.match(spelling), spelling


@pytest.mark.parametrize("name", LEGACY)
def test_the_legacy_gh_gl_spelling_is_still_admitted(name):
    for spelling in (name, name + "A", name + "1", name + "A1"):
        assert is_power_net(spelling), spelling
    # The measured corpus names keep matching.
    assert is_power_net("GHA") and is_power_net("GLC")


@pytest.mark.parametrize(
    "name",
    [
        "U",
        "V",
        "W",
        "U1",
        "V2",
        "W3",
        "UHAB",      # two letters after the prefix, no digits
        "UHA1B",     # trailing letter after the digits
        "UL1A",      # letter after the digits
        "WH_1",      # separator
        "UH A",      # space
        "WHA1B",
        "TIM1_CH1",  # ROBOT's real gate-pin net: a name that states no function
        "$1N147",
        "VCC",
        "VCCA",
        "VDD",
        "SCK",
        "IAX",
        "",
    ],
)
def test_names_that_only_look_like_the_family_are_refused(name):
    assert not is_power_net(name), name


def test_power_net_prefixes_lists_every_gate_family_once():
    """The report's word list and the pattern must not drift apart.

    ``POWER_NET_PREFIXES`` is interpolated into R11/R13's rows, so a gate family
    added to the pattern but not to the tuple (or the reverse) would make the
    row state a sieve it does not use.

    ``"V_"`` joined 2026-10-30 with the **supply-bus** family
    (``POWER_BUS_NET_PATTERN``, ``V_310V``): it is in this tuple as a word-list
    entry, while its matcher is that pattern — see
    ``tests/test_return_path_power_bus.py``. Adding it here changes none of the
    gate assertions below, which is the point of listing it explicitly rather
    than loosening the equality.
    """
    assert POWER_NET_PREFIXES == (
        "GH", "GL", "UH", "UL", "VH", "VL", "WH", "WL", "MOT", "IA", "IB", "IC",
        "V_",
    )
    assert len(set(POWER_NET_PREFIXES)) == len(POWER_NET_PREFIXES)
    alternatives = re.search(r"\(\?:([^)]+)\)", GATE_NET_PATTERN.pattern).group(1)
    assert set(alternatives.split("|")) <= set(POWER_NET_PREFIXES)
    # The sibling families stay in the tuple too.
    assert {"MOT", "IA", "IB", "IC"} <= set(POWER_NET_PREFIXES)


# ---------------------------------------------------------------------------
# 二、实跑 R11：合成六路读数、no-net 反例、TI 参考文案不变
# ---------------------------------------------------------------------------


def test_r11_gives_one_measured_row_for_each_of_the_six_names():
    board = _six_gate_board()
    rows = _r11(board)
    assert len(rows) == 6, [r.target.net_refs for r in rows]
    by_net = {row.target.net_refs[0]: row for row in rows}
    assert set(by_net) == set(SIX)
    for name in SIX:
        row = by_net[name]
        assert row.rule_id == "pcb-foc-gate-trace-width"
        assert row.severity == "INFO"
        assert f"power-path net {name!r}" in row.message
        assert "1 track(s)" in row.message
        assert "min 10 mil / max 10 mil" in row.message
        assert "300.0 mil total" in row.message
        # TI §4's 20 mil stays quoted-and-not-applied, wording untouched.
        assert "20 mil reference is quoted" in row.message
        assert "**not applied**" in " ".join(row.evidence)
        assert row.target.measurement is not None
        assert row.target.measurement["kind"] == "width"
        assert row.target.measurement["value"] == pytest.approx(10.0)


def test_r11_still_says_one_row_when_only_unrecognised_names_carry_copper():
    board = _board(
        tracks=[
            _track("t1", "TIM1_CH1", (0.0, 0.0), (100.0, 0.0)),
            _track("t2", "UHAB", (0.0, 10.0), (100.0, 10.0)),
            _track("t3", "VCC", (0.0, 20.0), (100.0, 20.0)),
        ]
    )
    rows = _r11(board)
    assert len(rows) == 1
    row = rows[0]
    assert "no net on this board has a power-path name" in row.message
    assert "core.measure's reader recognises" in row.message
    assert "gate net spelled outside" in row.message
    # The sieve the row quotes is the widened one.
    assert "'UH'" in row.message
    assert "20 mil" in " ".join(row.evidence)


def test_gate_nets_of_ignores_a_named_net_that_carries_no_copper():
    tracks = [
        _track(f"{name.lower()}1", name, (0.0, index * 100.0), (300.0, index * 100.0))
        for index, name in enumerate(name for name in SIX if name != "VL")
    ]
    board = _board(tracks=tracks, bare_nets=("VL",))
    assert "VL" in board.net_names()
    assert board.tracks_for_net("VL") == []
    assert gate_nets_of(board) == [name for name in SIX if name != "VL"]


def test_r13_narrowed_rows_read_the_same_widened_sieve():
    """A fold on ``WH`` gets its own row: R13 shares :func:`is_power_net` with R11."""
    board = _board(
        tracks=[
            _track("w1", "WH", (0.0, 0.0), (100.0, 0.0)),
            _track("w2", "WH", (100.0, 0.0), (100.0, 100.0)),
        ]
    )
    rows = FocTrackCorners().check(PcbReviewContext(board=board))
    narrowed = [r for r in rows if "power-path net 'WH'" in r.message]
    assert len(narrowed) == 1, [r.message for r in rows]
    assert "matched the power-path name sieve" in " ".join(narrowed[0].evidence)
