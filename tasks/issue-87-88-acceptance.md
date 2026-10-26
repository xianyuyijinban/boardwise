# issue #87 / #88 验收矩阵与边界

> 日期：2026-10-26。候选代码：`3398e8adc911ba3658c58948eaccbf997fcf881b`
> （`3398e8a`，父提交 `bd5809f`）。初次核对时两个 issue 均为 **OPEN**；提出人随后
> 确认 #88 的 1/295 验收锚并授权关单，#88 现为 **CLOSED**，#87 仍为 **OPEN**。
> 本文是验收记录；最终关单状态以 issue 与评论回执为准。

## 1. 结论先行

| issue / 项 | 当前判定 | 不能夸大成的结论 |
| --- | --- | --- |
| #87① 引擎版本 | **已实现，候选集成证据通过** | 不等于另外四项完成 |
| #87② PCB `export.render` / 目视 | **未解决**；本批未改 connector，也未完成 PCB 真机复测 | SOP 披露不是渲染修复，几何读取不是视觉通过 |
| #87③ summary 重跑合并 | **已实现，真实 CLI 重跑证据通过** | 不把 finalize 校验当成整板结论 |
| #87④ finding 元素身份 | **部分完成，结构化目标未达成** | 不能宣称所有 finding 或 kind+component+pin+layer 已结构化 |
| #87⑤ readback value/mpn | **离线归档替代已完成**；在线取档未复测 | `sch.readback` 本身未新增 value/mpn |
| #88 rings / void / 性能 | **代码主体与集成证据完成，提出人已验收并授权关单** | element_ids 唯一性另立，不混入本项 |
| #88 岛数锚 | **已接受 1 岛 / 295 成员及四视图**：pre-#83 15=281+14 / bd5809f 50 / rings 边+弦 containment 56 / HEAD 1=295；差账 55=14+35+6 | 15 不是 rings 原型值；历史更正已显式确认，不是暗中改锚 |

#87 整单不能关闭：②、④仍开放，⑤只完成离线替代。#88 的 1/295 验收锚和四视图
已获提出人确认，issue 已按授权关闭；`element_ids` 唯一性另立。

## 2. 基准、范围与证据纪律

- #87①③⑤、#88 代码均在 `3398e8a`；`3398e8a^..3398e8a` 对 `connector/`、
  `dsh-plugin/` 无 diff，故没有 PCB render 或在线 readback 的新宿主通道证据。
- 全量读数在工作树同时含有**暂缓提交的 201H 绘制改动**时取得；本文件涉及的审查
  行为代码与 `3398e8a` 一致；本批后续仅文档叙事/指纹同步，无行为变化。201H 不在
  本验收范围，也不借本记录提交。
- 真实 CLI 集成探针只读仓库公开/合成夹具，输出在 `.tmp_issue87_acceptance/`；
  #88 前后测量在 `.tmp_issue88_acceptance/`。这些目录不是新的真实工程夹具。
- 之前的历史计数只作背景。本文件写明的是本轮实际命令和读数，不把其他轮次的
  463 / 249 / 141 冒充本轮输出。

## 3. #87 逐项证据与边界

### ① 报告带引擎版本 —— 候选通过

- `report.json` 顶层 `toolVersion = "0.5.22"`；`report.md` 头部和 CLI 首行同步。
- schema 对旧报告保持可选兼容；差分 golden、schema hash 与 producer 指纹已由生成器更新。
- 真实命令：
  `.venv/Scripts/python.exe -m boardwise.cli checkup --file tests/fixtures/ch340_golden.epro2 --out .tmp_issue87_acceptance/checkup`
- 该夹具因缺手册与待分诊返回 **exit 3 / completion=incomplete**，这是如实的覆盖结论，
  不是板子干净，也不是版本功能失败。

### ② PCB render / 目视 —— 未解决，整单开放

- 本批没有 connector 改动，没有完成 PCB `export.render` 真机复测，也没有新增已验的
  PCB 目视通道；issue 中 `canvas.highlight` 相关诉求也没有本批关闭证据。
- `docs/review-sop.md` 与 `docs/pits.md` 现在只要求诚实披露：几何读取不等于视觉通过，
  PNG 采集成功不等于有人看过，缺图必须写 missing / 人工待办。
- 后续若关闭此项，需在明确授权的测试 PCB 与可复现宿主版本上完成 render + 真视觉复核；
  不能用离线几何或 SOP 文案代替。

### ③ 重跑保留 summary —— 真实 CLI 重跑通过

`.tmp_issue87_acceptance/integration87.py` 对实际 CLI 产物写入两个人工列标记及
1/3/4 节标记，将文件转换为 CRLF 后在同一 `--out` 再跑 `checkup`：

- 5 个标记全部保留；CRLF 保持不变。
- 新 finding 留空、消失进 2b、复活回主表、重复 identity、损坏旧文件保留等边界由
  `tests/test_537d_finalize_validation.py` 与 `tests/test_checkup_cli.py` 覆盖。
- 本轮专属测试：
  `pytest tests/test_doc_claims.py tests/test_checkup_cli.py tests/test_537d_finalize_validation.py`
  → **196 passed**。

### ④ finding 元素身份 —— 仅字符串级、限网对 finding

只读审计（`3398e8a`）确认：

- `pcb-voltage-spacing` 的 `target.measurement` 在会产出 finding 的网对行上包含
  `element_a` / `element_b`，但它们是**字符串 label**（如 `pad U1.2 on layer 1`），
  不是 `{kind, component, pin, layer}` 结构对象。
- `component_a` / `component_b` 另有字符串字段，`within_one_footprint` 为布尔；
  pin 与 layer 仍需从 label 解析，`shared_layer_ids` 未拷入该 measurement。
- 无电压、超表上限的 UNKNOWN INFO 行只有 `net_refs`，`measurement = null`；合格、
  豁免或不可测网对本来就不产 finding。其他 PCB 规则没有 systematic 使用
  `element_a/b`；`_clearance_measurement` 只有 `ipc.py` 一处调用。

因此只能说：#85 已为部分网对 finding 提供字符串级身份和同封装判断；#87④的
kind+component+pin+layer 结构化目标尚未达成，更不能外推到全部 finding。本批不扩改，
此项保持开放。

### ⑤ readback 缺 value/mpn —— 离线替代通过，在线未验

- SOP 的原代码块已实际执行：公开夹具中 C3 读到 `330uF 400V` 和非空 MPN；C1 的空
  Value 仍为 `""`，没有补猜。
- 这是 `.epro2` 归档 + `build_project_model` 的只读替代；`sch.readback` 本身没变，
  `sys.get_project_file` 在线取档传输未复测。机器结果见
  `.tmp_issue87_acceptance/integration-result.json`。

## 4. #88 三个硬条件

| 条件 | 候选证据 | 边界 |
| --- | --- | --- |
| rings 与 void | 每个 `PourShape` 实例直接消费 `pour.rings or [pour.points]`；外环减 void；不按共用 record id 配 rings | 无 rings 的旧 POLY/POUR/KiCad 记录仍回退 points |
| 精确性与性能 | bbox 下界有界扫描，不做距离近似；独立暴力参考对拍、调用次数上限与真实板性能锚 | 性能墙钟是粗 backstop，确定性调用次数才是主闸 |
| 跨层口径 | plan-view 与 same-layer 分开；跨层投影不再写成同层隔离 | 默认 `net_clearance` 的 plan-view 合同未偷改 |

原来的 5 条 `xfail(strict=True)` 已全部移除。合同、差分、schema 与规则指纹本轮命令：
`pytest tests/test_540c_differential.py tests/test_540c_generator_validation.py tests/test_540c_schema_semantics.py tests/test_126a_pcb_review_plumbing.py`
→ **198 passed**；跨语言进程另为 **21 passed**，5 个差分 case 一致。

### 4.1 实测读数（2026-10-26，HEAD `3398e8a`，单进程；证据 `.tmp_issue88_acceptance/`）

实板 F/B 对应仓库既有只读夹具，映射留在本地探针（`.tmp_issue88_acceptance/`），
公开产物只用代号。三组净空用
`net_clearance(..., same_layer_only=True)`，HEAD 逐位复现 issue 标称：

| 网对 | bd5809f（弦） | HEAD |
| --- | --- | --- |
| F `+12V↔GND` | 0.0（判短路） | **11.213162658** mil（track 3d0cdb965933df32 / pad U4.2，层 1） |
| F `GND↔VCC` | 0.0（判短路） | **3.538172961** mil（pad U1.31 / track 03d13fd9b5027b71，层 1） |
| B `PGND↔AGND` | 3.661407542 mil | **14.095168282** mil（pad R6.1 / pour `2b57e2c0f6d33289`，层 1） |

实板 F 的 `GND` 岛数四视图（面积 **2 210 304.226455** sq mil、层 **[1, 2, 15, 16]** 全程不变）：

| 视图 | 岛数 | 构成 |
| --- | --- | --- |
| 135 口径（恢复 #83 前恒真 containment） | **15** | 281 + 14 |
| bd5809f（#83 已修，弦） | **50** | 246 + 49 |
| rings 边+bbox、弦 containment | **56** | 240 + 55 |
| HEAD（rings 边+bbox+实心 containment） | **1** | 295 = 68 track + 172 via + 47 pad + 8 poured |

15 是 **pre-#83 历史读数**，不是 rings 原型；rings 距离视图读 **56**。15→1 的差账是
**55 = 14 + 35 + 6**（14 在 pre-#83 已孤岛、35 由 #83 暴露、6 由 rings 边暴露），
55 个 via 全部位于两个 GND poured 结果的实心铜内。14 个历史 via 的 ID/层/面积逐条见
`.tmp_issue88_acceptance/fourteen_vias.csv`。

- rings/void/共用 record id：8 个 POURED `PourShape` 只有 2 个 record id（`3fa…` ×3、
  `0a00…` ×5）；代码在同一 `_Shape(...)` 里按对象消费 `pour.rings or [pour.points]`，
  没有按 id 取 rings 的路径；union-find 按 flat index。实板：每个 pour 的 `points`
  100% 落在自身 `rings[0]` 内；自 bbox 差 210.65 / 126.199（弦深），跨岛 915.59 /
  1126.24；void 环内取点 `_point_in_solid=False`。
- 性能：`pour_connectivity(GND)` **2.42 s**、`net_clearance(GND,VCC,same_layer)`
  **1.13 s**；精确 `_segment_distance` 合计 **12 378** 次（上限 100 000；全交叉约 11 M）。
- 聚焦测试：**47 passed in 25.55s**（`test_88_pour_rings.py`、`test_88f_measure_perf.py`、
  135 锚点、131f 岛数表、133d R9）。
- 残余边界：`element_ids` 295 个成员只有 **289** 个不同 id（POURED 多岛共用 record id
  导致标签重复）。岛/连通按 index 计算，本轮不扩改；下游若以 element id 为键需另立批。

## 5. 候选整体验证

在同一候选代码上已执行：全量 Python **8291 passed / 19 skipped / 0 failed**；
connector **536 passed** + typecheck；DSH **127 passed / 1 skipped** + typecheck/build；
Rust **45 passed / 4 ignored** + fmt/clippy；Python/Rust 5 case 的 normalized SHA-256
完全一致。ignored 是需显式语料的可选项，不写成已运行。

## 6. issue 评论收据（2026-10-26 已发布）

以下为发布时正文摘要；实际评论与开放状态以链接为准。

### [#87 —— 部分落地，整单保持 OPEN](https://github.com/xianyuyijinban/boardwise/issues/87#issuecomment-6415800085)

> 候选 `3398e8a`：①③已有真实 CLI 集成证据；⑤完成离线归档替代，在线取档未复测。
> ②未改 connector、未完成 PCB render 真机复测，SOP 披露不算修复。④目前
> `element_a/b` 是字符串 label，component 另有独立字段，但 pin/layer 未结构化，
> UNKNOWN 行无 measurement，其他规则也未形成统一覆盖。因此①③⑤（⑤仅离线）可验收，
> ②④继续开放，整单不关闭。

### [#88 —— 代码主体完成与四视图证据](https://github.com/xianyuyijinban/boardwise/issues/88#issuecomment-6415806004)

> 候选 `3398e8a`：三组实板净空逐位复现（F `+12V↔GND` **11.213162658**、
> F `GND↔VCC` **3.538172961**、B `PGND↔AGND` **14.095168282** mil）；rings/void
> 按对象配对、未按共用 record id 串岛；性能 12 378 次精确线段调用 / 2.42 s 有界。
> 岛数请确认四个读数：**15 = 281 + 14 是 pre-#83 历史值**（用恢复 #83 前
> containment 的源码复现），bd5809f 弦视图 **50 = 246 + 49**，rings 边+bbox /
> 弦 containment **56 = 240 + 55**，当前 **1 = 295**（68 track + 172 via + 47 pad
> + 8 poured；面积 2 210 304.226455 sq mil、层 1/2/15/16 不变）。55 = 14 + 35 + 6，
> 所以 15→1 不是「14 个 via 直接并回」，15 也不是 rings 视图的读数；请确认以
> 1/295 为验收锚并接受该历史更正。确认前不关单。

随后提出人明确接受 **1 岛 / 295 成员**及四视图为新验收依据，并裁定
`element_ids` 唯一性另立。[验收确认与关单评论](https://github.com/xianyuyijinban/boardwise/issues/88#issuecomment-6417112874)
已发布，#88 已按授权关闭（2026-10-26T13:25:03Z）；#87 未受影响，仍为 OPEN。

## 7. 后续边界

1. #87②：授权测试 PCB + 可复现宿主上的 render/视觉验证；不能拿 readback 或 SOP 替代。
2. #87④：若要达到 issue 建议的结构化目标，另立合同批定义 element 对象、pin/layer
   字段及 UNKNOWN 行的身份边界；本批不以文字说明冒充结构变更。
3. #87⑤：在线取档单独立项复测；不修改 `sch.readback` 的既有结论。
4. #88：1/295 与四视图已获确认并已关单；`element_ids` 唯一性另立，不在本关单中扩改。
5. 三条评论已按授权发布：#88 已按明确授权关闭，#87 仍为 OPEN；未 push。
   后续评论、关闭、推送或新 git 提交仍按各自授权执行。
