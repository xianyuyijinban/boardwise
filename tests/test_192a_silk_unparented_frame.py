"""192A-2：``SilkText.mirrored_frame`` 漏掉 ``designator-unparented``。

**洞**：这个属性原来把「板级记录」写成了一张**来源名单**
（``source in ("designator", "board")``）。``designator-unparented`` 是同一族记录
（PCB 文档里的 ``ATTR key="Designator"``），只是 ``parentId`` 没连上本板的器件
（探针测到 ROBOT 有一条第 50/49 条），它的 x/y/angle 与 parented 那条**逐字段同源**，
却在名单之外 —— 于是底面的这类记录被按**顶面**的帧排版，文字朝反方向走。

**口径**：帧是**记录**的性质，不是来源拼写的性质。名单的反面才是真相：只有
``source == "footprint"`` 要排除（它的锚点已经被 ``ComponentPlacement.transform``
摆好、角度也与器件角复合过，本来就是板坐标几何）。

哨兵角取 **0°**：这时 ``u`` 是 ``(±1, 0)``，两种读法给出**符号相反**的向量，
一眼可辨；90° 时 ``u`` 的 x 分量本身就是 0，镜像只改一个浮点噪声，测不出东西。
"""

from __future__ import annotations

import pytest

from boardwise.core.geometry import SilkText

#: 一条 0° 的底层记录：镜像帧的 ``u`` 是 ``(-1, 0)``，顶面帧是 ``(1, 0)``。
RECORD = dict(
    component="R1",
    text="R1",
    x=100.0,
    y=200.0,
    angle=0.0,
    layer_kind="BOT_SILK",
    layer_id=4,
    font_size=40.0,
    origin="LEFT_BOTTOM",
)

#: 板级记录：``source`` 是「这条 ATTR/STRING 连上了谁」，不是几何来路。
BOARD_RECORD_SOURCES = ("designator", "designator-unparented", "board")


@pytest.mark.parametrize("source", BOARD_RECORD_SOURCES)
def test_board_level_bottom_record_uses_the_bottom_view_frame(source: str) -> None:
    text = SilkText(source=source, **RECORD)
    assert text.mirrored_frame, f"{source} 是板级记录，底面上必须走镜像帧"
    assert text.frame_axes()[0] == pytest.approx((-1.0, 0.0), abs=1e-9)


def test_footprint_string_is_still_excluded() -> None:
    """The one genuine exclusion: a footprint's own STRING is already posed."""
    text = SilkText(source="footprint", **RECORD)
    assert not text.mirrored_frame
    assert text.frame_axes()[0] == pytest.approx((1.0, 0.0), abs=1e-9)


def test_top_face_record_is_never_mirrored() -> None:
    text = SilkText(source="designator-unparented", **{**RECORD, "layer_kind": "TOP_SILK"})
    assert not text.mirrored_frame
    assert text.frame_axes()[0] == pytest.approx((1.0, 0.0), abs=1e-9)
