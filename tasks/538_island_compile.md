# 538 — archipelago 独立子岛编译与局部回滚

- 立项：2026-10-25；前批：536（schema / plan 身份 / hard 校验）、537（审查流程，已关闭）。
- 路线：`docs/drawing-archipelago-route.md` §3/§5/§6/§9。
- 工作方式：主线规划与审查，子代理串行小批实现；每棒先 RED 后 GREEN，主线独立复跑。
  敏感闸至少做两个单点变异，确认测试会红，再以 `cp + sha256` 恢复；禁 `git checkout` 与直删。

## 1. 授权边界

本批只做**块级、离线、确定性的独立子岛编译**，以及失败后**只重编译指定子岛**的能力。
局部 `ok=True` 只表示该子岛通过本批的局部检查，不表示组装配、整页、可落图或视觉验收通过。

明确不做：

- 不接 `drawcompiler.compile` / `_try_island_variants`，不调用 `island_page` / `pack_islands`；
- 不做核心+卫星组内装配、岛群页级 pack、跨群连接、生成边界、`frame`/`offset`；
- 不改 CLI、ChangePlan、draw plan/apply，不迁移 CH343/534；
- 不操作 bridge、canvas、真实工程或真机，不声称 `draw compile ok=True`；
- 不做隐式重试、无限重试、整页重算，不用第二份子 CircuitSpec/PresentationSpec 冒充局部化；
- 不做 git 写操作，不直接删除文件。

## 2. 已核实的现状与设计约束

- `islandlayout.island_subgraph(s)` 已是布局唯一投影：本岛 parts、只含岛内 pin 的 nets、跨岛标记。
  `layout_island` 每次新建 `IslandBlock`；`IslandBlock.plan(source=...)` 已能直接出局部 LayoutPlan。
- 单岛 plan 直接对整份规格跑 `readability.check`，会把岛外未放置件报成
  `required-pin-not-connected`；真实 LDO 两岛的只读探针分别为 4 / 3 条。`_check_locks`
  对岛外未放置锁也有同类问题。其它 netlist/NC 检查不需要放宽。
- 整份 `validate_archipelago(circuit, presentation)` 必须在批次入口先过；
  整份 `validate_archipelago_plan` 要求全量 partition，不能直接拿来验局部 plan。
- 不创建子规格：局部 plan 的 `LayoutSource` 仍写**原始整份** circuit/presentation 哈希，
  避免两套事实源与 digest。`CheckResult` 不增加 scope 字段；编译结果用 island id 明确作用域。
- 本批没有 variant ladder。相同输入重算不是新候选；局部回滚是**不采纳失败结果、保留其它
  成功结果、只响应显式的单岛重编译**，不是重复同一失败直到变绿。

## 3. 串行小批

### 538A — 显式 readability scope 与 scoped 身份回验

文件域：`src/boardwise/engines/readability.py`、`src/boardwise/core/archipelago.py`、
`tests/test_538_island_scope.py`（新）。可复用 536 的真实 LDO/profile helper，不另写第三套 profile。

1. `readability.check` 增加可选的显式部件 scope（建议 frozen `ReadabilityScope`），默认 `None`
   保持整页语义与现有结果形状。只在这两个分支跳过**岛外且未放置**的项：
   `_check_required_pins` 的 `placed_part is None`、`_check_locks` 的 `part is None`。
   岛内缺件/缺脚、岛外件被错误画入、锁坐标不符仍按原规则检查；不得给整页加“允许缺件”开关。
2. `core.archipelago` 抽出共享的 expected partition / 比较逻辑，新增
   `validate_archipelago_island_plan(plan, presentation, island_id)`：原 presentation 的结构先过，
   expected 只取该岛 parts；缺本岛件、画入岛外件、重复、空/错 group/island 都拒绝。
   原 `validate_archipelago_plan` 的全量行为、错误语义与旧 digest 不变，共享比较器而非复制判型。
3. RED 先固定：真实 LDO 局部 plan 对整份规格的 4 / 3 条误报；scoped 后这些岛外缺件消失，
   本岛真实违规仍在；默认整页 plan 少一件仍 hard 拒；scoped identity 缺件/岛外件/错身份均拒。

### 538B — 最小独立编译 API

执行时再分两棒：B1 先做成功结果与证据，B2 再做失败路径和批次内隔离；主线分别复审。

文件域：新 `src/boardwise/engines/islandcompile.py`、新 `tests/test_538_island_compile.py`；
只允许为复用既有 gate/证据逻辑做很小的必要导入，不改整页装配路径。

1. `compile_island(circuit, presentation, island_id, profiles, *, budget=None)`：
   先过整份 `validate_archipelago`，要求 archipelago 与已声明 island；经现有 subgraph/layout
   生成 block/plan，过 scoped identity，再以显式 scope 跑现有 readability 与
   `island_gate_violations` / `soft_floor_violations`。不得调用整页 compile/pack。
2. `compile_islands(...)` 按 `presentation.effective_islands()` 的声明顺序返回结果；整份合同
   失败在任何布局前整批拒绝。单岛布局/identity/gate 失败形成该岛结构化结果，不污染其它岛。
3. `IslandCompileResult` 至少带 `island_id`、`block`、`plan`、`gate`、`refusal`、`tolerated` 与局部 `ok`。
   `refusal` 复用 `GrammarFailure` 四类及现有 hard-kind 分类表；`ok` 由完整结果推导，不能只看 `gate.ok`。
   **失败结果 `block/plan` 必须为 None**，只保留 gate/refusal 作证据，避免 soft-floor 失败留下
   `evidence.verdict=pass` 的可采纳候选；成功结果才携带 block/plan。
4. 成功 plan 写原始两份规格哈希和 `LayoutEvidence`：refusing 为空，hard_violations 为空，
   soft metrics/reasons 保留，tolerated 主机自印行进 notes；局部 ok 不冒充整页交付。
   本批不运行整组 grammar，`grammar_findings=[]` 只表示该层未运行；也不评估 page_box、
   标题栏或页级 keepout。它们需要后续装配/页级上下文，不得写成已经通过。
5. 验收：两岛各自 block/plan/gate、身份通过、顺序与 digest 稳定；同输入两次结果一致；
   成功 plan 的 JSON round-trip 保留原始哈希、group/island 与 LayoutEvidence；
   monkeypatch 证明 `island_page`/`pack_islands` 未调用；布局异常、identity、hard 与 soft-floor
   失败均 `ok=False` 且无候选 plan/block，其它岛仍可成功。

### 538C — 显式单岛重编译、局部回滚与路线收口

文件域：`src/boardwise/engines/islandcompile.py`、`tests/test_538_island_compile.py`、
`docs/drawing-archipelago-route.md`、`tasks/538_island_compile.md`。

1. `recompile_island(result, *, budget=None)` 复用该结果保存的原始输入，只重算其 island id；
   `budget=None` 沿用原 budget，传入新 budget 才改变这一输入。不得修改旧结果或其它岛结果。
2. 批次中的一个岛失败后，调用方只对该岛 recompile；其它成功结果保持对象同一性（`is`）。
   失败岛不被采纳、无部分 plan；成功岛重编译 digest 稳定。相同输入仍是同一结果，refusal/action
   或结果 notes 明说“输入未变不是新 variant；需改变 budget/profiles/规格”。禁止内部自动重试。
3. 路线文档只把“独立子岛编译与局部回滚”标为本批能力；组内装配、页级 pack、跨群连接仍未做。
   同步文首、§3 流水线、§5 身份、§6 验收分层与 §9，不能只勾掉 §9 而留下前后矛盾；
   scoped plan/LayoutEvidence 是块级能力，不写进 ChangePlan 或整页交付口径。
4. 聚焦回归：538A/B/C、536 schema/contract、readability/layout/真实岛页相关测试。
   主线最后跑完整 Python、connector、dsh-plugin/typecheck/build 与 `git diff --check`。

## 4. 完成定义

- 默认整页 readability 与全量 partition 校验没有放宽；scope 只影响岛外未放置项。
- 每个接受岛都有原始规格哈希、scoped 身份回验和 LayoutEvidence；每个失败岛都没有可采纳候选。
- 单岛失败不拖垮其它岛，显式重编译只碰指定岛，成功结果不被重写。
- 没有 group assembly/page pack/CLI/ChangePlan/真机能力或 `draw compile ok=True` 声明。
- 实际 RED/GREEN、主线复跑、哈希和限制写入本文件验收记录；TASKMAP 标“工作树”而非已落。

## 5. 验收记录

- 只读设计核查：完成；真实 LDO 局部 plan 对整份规格出现 4 / 3 条岛外 required-pin 误报。
- **538A（主代理复审通过）**：新增 `ReadabilityScope` 与 `validate_archipelago_island_plan`，
  只在 required-pin/lock 的“scope 外且未放置”分支跳过；错误画入的岛外件仍检查，全量校验不变。
  代理 RED 为新 API ImportError；GREEN 新文件 **26 passed**、联合 **170 passed**。scope 失效与
  scoped-extra 失效两个变异分别红 **2 / 1**，cp+sha256 恢复。主线独立复跑同组 **170 passed**，
  最终 readability/archipelago/test hash 为
  `fb1144c8cc8ca54b2ad173fac2f935ad148da0fa158d7ca0826f4e8cc93b1479` /
  `20eabc074ce1462364b52e978eb8c27fad1a3432a89c3f249e69d0976295ccdb` /
  `4ddb850d14d472f5d208a7805f140982fb85a6b6b72e3cd89be381d214c841df`。
  主线另以真正 `island_subgraphs` 推导 crossing：两岛均见 VIN5/3V3/GND，hard 与 soft-floor 均为空。
- **538B1（主代理复审通过）**：新 `engines/islandcompile.py` 与真实两岛成功 API；
  单/批量共享整份合同、真实 crossing、scoped identity/readability、原始哈希与 LayoutEvidence，
  无 page/grammar/pack。代理 RED 为模块不存在；GREEN 新文件 **16 passed**、联合 **78 passed**。
  去 scope / 清 crossing / 去 profile 守卫三个变异分别红 **14 / 2 / 2** 并恢复。
  主线独立联合 **78 passed**，黑盒两岛 ok、JSON round-trip 与重复 digest 均通过。
  最终模块/测试 hash 为 `14054e874fbb727e7e7124924550b379ee7f827f31cbacd82dda348a9d344220` /
  `2204afa8852a6ca55497312c8a8c40ce245b0847d75d7dd67c1829fa494d671c`。
  留待 B2：布局/identity/readability 异常目前会外抛并可能中断批次，成功路径不作为 B2 已完成的证据。
- **538B2（主代理复审通过）**：layout / plan+identity / readability 分阶段把明确异常转为
  单岛 GrammarFailure；整份合同仍在布局前整批拒绝，TypeError 不外包成 refusal。hard/soft 失败保留
  gate 但 block/plan=None，批次不因一个岛失败而中断。代理 RED **4 failed / 19 passed**，GREEN
  联合 **85 passed**；失败携带候选与 batch 中断两个变异各红 **2** 并恢复。主线独立联合
  **85 passed**，直接注入布局/NC/soft-floor 故障均获正确分类且另一岛成功。最终模块/测试 hash
  `7b625ff001e7481333c7fd60cb286b19d8364e113c7228bb58f459cd0705d833` /
  `4da81c429c9768ebe6e44d406d1522326df16b3632edb51b5fd63a9849bd1c56`。
- 538C：待实现与主审；另需补非 archipelago 输入拒绝的明确测试。
- **538C（本棒实现，待主审；只追加本段，不改既有验收）**：新增
  `recompile_island(result, *, budget=None)`。只接受 `IslandCompileResult`（否则 `TypeError`）；
  缺 `result.request` 给含 `request` 的清晰 `ValueError`。用 request 的原始
  circuit/presentation/island_id/profiles 调**一次** `compile_island`；`budget=None` 沿用
  `request.budget`，传入新 `IslandBudget` 才替换这一项。返回新结果，旧结果与批次里其它成功
  结果对象/字段不动；同输入成功重编译的 geometry digest、plan JSON 与 `LayoutEvidence` 不变
  （evidence 不加 recompile 行）。结果 notes 追加英文：未改 budget 时含 `unchanged input` 与
  `not a new variant`（说明只有改 budget/profiles/规格才会改变答案）；改 budget 时含
  `changed budget` 与其它输入 `reused unchanged`。失败岛重编译仍是同一失败（category/detail/
  action 不变、block/plan=None、不变成成功），无自动重试。另补非 archipelago 输入在布局前
  被 single/batch 明确拒绝的测试。RED 为 `ImportError: cannot import name 'recompile_island'`；
  GREEN 新文件 **32 passed**，五文件联合 **116 passed**（`-n0`，独立 basetemp
  `.tmp_pt_538c_round3`）。变异：recompile 改成重算全部岛 → 相关 spy 测试 1 red（见
  `rail_core`）；去掉 request 缺失拒绝 → 1 red（`AttributeError`）；均 `cp + sha256` 恢复并
  复核模块 hash。最终模块/测试/路线文档 hash 为
  `6ba12f56f107b9a1c3293b297a78b7592ea76a77b5c1b810eeb7017f18c61c09` /
  `caee985a5ccdb4281fb78e4c8c1fec99f74e88aa1b38f1e1447d5b072c549566` /
  `071a5f7a9c31363cba37c04849b6a99f8a052867c69ebed71123dadadcfb8e5f`。
  限制：仍是块级、离线；不接整页 compile/pack、ChangePlan、draw plan/apply 或 CLI，不做
  真机/canvas/git/直删；本棒代理未跑全量（主线最终结果见下条）；`archipelago_min` 无真实
  library profile，仍不可 compile；不声称 `draw compile ok=True`、落图或视觉验收。
- **538 主线最终验收通过**：独立聚焦 **116 passed**；成功/失败/recompile 三个黑盒探针全过，
  只重算目标岛，新 budget 如实传递，同输入 digest/evidence 稳定，缺输入仍失败、缺 request 明确拒绝。
  非 archipelago 的 single/batch 均在布局前拒绝。完整 Python **7708 passed / 19 skipped / 5 xfailed**
  （485.19s）；connector **536 passed** + typecheck；dsh-plugin **113 passed / 1 skipped** +
  typecheck + build。最终模块/测试/路线 hash 与 538C 交卷一致：
  `6ba12f56f107b9a1c3293b297a78b7592ea76a77b5c1b810eeb7017f18c61c09` /
  `caee985a5ccdb4281fb78e4c8c1fec99f74e88aa1b38f1e1447d5b072c549566` /
  `071a5f7a9c31363cba37c04849b6a99f8a052867c69ebed71123dadadcfb8e5f`。
  `IslandCompileRequest` 的公开 recompile 角色文案已同步；`git diff --check` 通过。
  本批至此完成（工作树）：只做独立子岛编译与显式局部回滚，组内装配、页级 pack、跨群连接、
  CH343/534 迁移、真机与视觉验收仍须另批。
