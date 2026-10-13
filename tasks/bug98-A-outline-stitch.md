# bug98-A：多段 BOARD_OUTLINE 拼合 + 出板框规则拆分（根修）

现场报告（岳转，已核实一半）：一块 98 器件的板，板框是 16 段独立 BOARD_OUTLINE
（圆角矩形拆段），`parsers/epru.py:1680` 的 `context.outline is None` 只认第一段
（左边一段弧，11 点），`distance.py` 的 `MIN_OUTLINE_CORNERS=3` 护栏按单段点数放行
→ 98 条「器件出板框」假 ERROR 淹没真 ERROR。**本批不许碰 rules/ 以外文档化钉值以外的东西。**

## 任务 1（核心）：解析层拼合

- `parsers/epru.py`：**收集全部** BOARD_OUTLINE 记录（现在只拿第一段；其余段落现在
  还会落进 `non_copper_shapes` 当普通 POLY——拼合后不许再重复落）。
- 拼合：各段 `_path_points` 的多段线按**端点就近**（容差建议 1 mil，写清出处）链成环；
  取最长闭环为板框。拼不成闭环（开放链/碎段）→ `outline=None` + 模型上显性
  `outline_fragments: int`（段数）——**「拼不出」必须是显性事实，不是悄悄拿第一段**。
- 模型（`BoardGeometry`/`BoardOutline` 所在文件）：`BoardOutline` 加 `segments: int`
  与 `closed: bool`（或等价披露字段），docstring 写明语义；单段旧行为逐字节保持。
- 规则侧（`rules/pcb/distance.py` 的 `_outside_outline`）：`MIN_OUTLINE_CORNERS` 改看
  **拼合后的整体**；`outline is None and outline_fragments > 0` 时保持沉默（现有
  沉默语义）——另外确认「板框没读出来」在报告层有披露（126 的既有通道，别新造）。

## 任务 2：拆规则（报告可读性，同批做）

`_outside_outline` 从 `ComponentSpacing` 拆成独立规则类 `BoardOffEdge`，
id `pcb-component-off-board`（间距规则只剩间距）。98 条同名 ERROR 淹报告是本次
教训——拆开后两义各归各。注册进 `BUILTIN_PCB_RULES`（+1）；受影响计数钉/冻结表
按实更新（先全夹具普查：改动前后 finding 差必须只有「规则名变了」这一种，
行为/severity/对象一条不许变——合成夹具证明 + 全夹具零差对拍）。

## 合成夹具（验收的命根子）

tests/fixtures 既有夹具一个不碰。**新合成板**（`parse_epru_text` 路线，别提交真板）：
圆角矩形板框拆 16 段（4 角弧 + 12 边，形状照报告描述），98 颗焊盘全落在真实
并集内——修复前复现「全板误报」，修复后零 finding；再加一颗真的跑出板框的件，
修复后恰好 1 条 `pcb-component-off-board` ERROR。碎段不闭环变体：披露 + 零误报。

## 红线与验收

禁 git、禁 rm；pytest `--basetemp=.tmp_pt_bugA`；变异验证 ≥2（拿掉拼合回退到
`is None` → 合成板必红；把闭环判据拆掉 → 披露测试必红）。**指纹不许钉**——
改了 rules/pcb/distance.py 必然移动，交卷报两值（recursive/direct）我统一钉。
证据 outputs/bugA/（append+grep -c）。受影响测试全绿 + 冻结表零翻转是硬约束。
