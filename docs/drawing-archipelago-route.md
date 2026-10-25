# 岛群→子岛绘制路线（路线草案 + 536 契约 / 538 块级独立子岛编译已落）

> **状态：路线草案；536 的契约能力与 538 的块级独立子岛编译已落，整条路线远未完成。**
> 536（[tasks/536_archipelago_schema.md](../tasks/536_archipelago_schema.md)）已落：`group` / `owner` /
> `kind` / `side` schema、结构/网表 hard 校验、`LayoutPart` 的 `group`/`island`、`PackedPage`
> stamping，以及 compile / module_plan / page apply 的 partition 回验。
> 538（[tasks/538_island_compile.md](../tasks/538_island_compile.md)）已落**块级**能力：
> 单岛独立编译（[`engines/islandcompile.py`](../src/boardwise/engines/islandcompile.py) 的
> `compile_island` / `compile_islands`：局部 block/plan/gate、scoped identity 与
> `LayoutEvidence`），以及**显式单岛重编译 / 局部回滚**（`recompile_island`：只重算指定岛，
> 旧结果与其它成功结果不动，没有自动重试）。它仍不调整页 compile/pack、不接 `ChangePlan`、
> 不落图。本文其余章节（组内装配、页级 pack、连接收尾、迁移）仍是设计，不是现成功能。
>
> 三点边界，全文以此为准：
>
> 1. **schema 已接受**：archipelago island 的 `group` / `owner` / `kind` / `side`、结构/网表
>    hard 校验、plan 的 `group`/`island` 身份与 partition 回验都已生效（§2.2 / §2.3 / §5）。
> 2. **最小例仍不可 compile**：`docs/examples/archipelago_min/` 是 `.draft.json`，通用
>    `GENERIC-*` symbolRef、`provenance: ai_asserted`、没有真实 library profile；它进了 536
>    的聚焦测试，但**不能**据此声称可以 draw compile，也不能声称 B/C 验收。538 的块级编译同样
>    需要真实 profile，不改变这一点。
> 3. **多群与普通 pagecompiler 明确拒绝**：多群直接 `drawcompiler.compile` 因组装配器未
>    实现而 hard 拒绝；任何 archipelago 进普通 `pagecompiler` 也 hard 拒绝（丢岛风险）。
>    多群 schema 可解析不等于多群排版支持；538 只在已声明岛内部编译，不改变这两条拒绝。

本文定义「岛群（module）→ 子岛（island）」的绘制契约：网表权威、不变量、回滚粒度、空间预留、
plan 回验口径与验收分层。绘制规格不复述，只引用 `docs/schematic-style-spec.md` 的 S-01 /
S-05 / S-12 / S-15 / S-16 / S-20 / S-21 与 `docs/drawing-brief-v2.md` 的 FlagReservation。

## 1. 原则

1. **大岛群 ≠ 巨岛**：module 是归属与打包单位，子岛才是布局与阅读单位。
2. **显式属主先于坐标**：先声明 part → island → module，再谈位置；坐标是派生物。
3. **局部失败局部回滚**：失败优先回到最小受影响层级，一个子岛排不下不该让整页重来。

## 2. 契约与不变量

### 2.1 网表权威

- `CircuitSpec` 是**唯一网表权威**，presentation 不重复 `nets`、不维护第二份连接表；内部网/外部
  端口由「网表里的网落在哪些子岛」**推导**，不手写。

### 2.2 岛群与子岛（536 已落的生产契约）

现有 `modules` 当岛群、`islands` 当子岛；首版由工程师显式填写并可覆盖，自动语义分组后置。
536 起 archipelago island 显式声明三个必填字段和一个可选字段：

- `group` 指向所属 module；`owner` 指向该群核心子岛内、这个子岛实际服务的器件。
  核心岛有多件时，owner 可以是不同于 `module.core` 的另一核心件；`module.core` 本身仍必须
  落在核心子岛。
- `kind` 子岛类别，本批契约枚举 `core` / `decoupling` / `bulk` / `clock` / `programming`。
  `decoupling` 服务供电脚高频去耦，`bulk` 服务局部储能；首版由工程师显式区分，不按容值猜。
  最小例不实例化 `bulk`。
- `side` 可选 `left` / `right` / `top` / `bottom`，省略表示未声明岛级偏好；`role` 继续表达
  电气角色，与 `kind` 正交。既有 page → module 的 `sidePreferences` 覆盖规则不变，`side`
  只约束群内装配；`userLocks` 若存在仍是精确锁，不得被侧偏好静默移动。
- 独立 `decoupling` / `bulk` 子岛是有属主的语义对象，不是核心岛排不下后产生的 overflow。

读法：一个 `islands` 列表里**任一** entry 声明了这四个键中的任意一个，整个列表就按
archipelago 读（`PresentationSpec.is_archipelago`），此时**每个** entry 都必须声明
`group` / `owner` / `kind`；一个都不声明的列表仍是原来的扁平读法，语义、字节与 digest 一律
不变，不 bump `specVersion`。同一规格新旧混写被拒绝——不允许“一半 entry 有属主”。

### 2.3 新增 hard 校验（536 已落）

结构校验（`islands.validate_archipelago_structure`，解析期即执行）：

- 每个 part **恰属一个** module；每个 island **恰属一个** group。
- `island.parts` 是所属 `module.parts` 的**子集**；`module.parts` 等于其子岛 `parts` 的
  **无重复并集**。
- 每个 group 必须声明 `core`，且它在该群唯一的 `kind=core` 子岛内；每个 `owner` 也必须在
  该核心子岛内。

网表校验（`core.archipelago.validate_archipelago`，在 draw compile 的前置失败检查里、几何
搜索之前执行）：

- 每个非 core 子岛必须与 `owner` 至少共享一网；`decoupling` / `bulk` 还不得含 signal 网，
  且必须与 `owner` 共享至少一条 power 网。这里只校验归属连通和网类，不凭位号猜器件类型。
- presentation 必须恰好放置 `CircuitSpec` 的器件，不得多、不得少。

推论：岛群不是排版原子，**不允许子岛之外的散件**。这些规则现在由生产校验器执行，不再是
“必须新增的规则”，也不再维护测试里的第二套参考实现；未声明新字段的既有扁平规格保持原语义。

两个由“还没实现”导致的 hard 拒绝，与上面的契约校验分开看：

- **多群直接走 `drawcompiler.compile` 被拒绝**：组装配器未实现，多群不得被扁平化成一张图。
- **任何 archipelago 进普通 `pagecompiler` 也被拒绝**：普通 pagecompiler 只有 module 的扁平
  视图，让它编译一个 archipelago 就是丢岛风险。

**多群 schema 可解析不等于多群排版支持。** 单个声明岛的 archipelago 则保留普通布局路径，
在产出时写入身份并在闸前回验，不再出现 compile 成功但 plan 无身份的死路。

### 2.4 跨子岛连接

跨子岛信号用 **net labels**；电源/地用 **flags**；**禁全页电源母线**。旗标可汇聚多个就近
引脚，但不拉全板母线。连接一律来自 2.1 的推导。

### 2.5 decoupling 子岛示例（536 起可被 schema 解析，仍不等于可编译）

```json
{ "id": "mcu_decoupling", "parts": ["C1", "C2"], "role": "secondary", "name": "MCU decoupling", "group": "mcu_cluster", "owner": "U1", "kind": "decoupling", "side": "left" }
```

这段现在是合法的 archipelago island（536 的 schema 接受它）；它只是形状示例，能不能编译见
§2.3 的两条拒绝与 §6 的分层。

## 3. 编译流水线

契约校验 → 空间预算/禁地预留（含推导端口数）→ 子岛独立编译（器件、文字、flags、
端口位一体排版）→ 核心+卫星组内装配 → 岛群页级打包 → 推导端口并连接 →
生成边界与最终校验。

536 落实了第一步的契约校验，以及既有 island page 的身份 stamping/回验。538 落实了
**子岛独立编译**这一步的块级版本：`compile_island` / `compile_islands` 只把已声明岛投成
本岛画面并跑局部闸；`recompile_island` 是显式的局部回滚——只重编译指定岛，未改输入仍是
同一答案（不是新 variant），没有自动重试。**核心+卫星组内装配、岛群页级打包、推导端口并
连接、边界生成与最终校验仍未实现**，仍是本文的设计（§9）。

| 阶段 | 失败回滚粒度 |
| --- | --- |
| 契约校验 | 整批拒绝，不产生落盘产物 |
| 空间预算/禁地预留 | 先重算受影响子岛/群预算，不进入坐标硬凑 |
| 子岛独立编译 | 只重编译该子岛（538 已落：显式 `recompile_island`，无自动重试） |
| 核心+卫星组内装配 | 只重排该群的卫星；必要时重编译失败子岛 |
| 岛群页级打包 | 只调整群间顺序/位置，不改子岛内部 |
| 推导端口并连接 | 先重做相关端口层；无解才退回所属群装配 |
| 边界生成与最终校验 | 回到最小相关子岛/群；禁止靠遮挡、缩字硬凑 |

## 4. 空间

- 器件、位号/值文字、flags、端口标签、**标题栏禁地**从布局早期参与计算，不留在收尾。
- 边界与文字空间**先预留**，再放器件。
- 细折线边界在**子岛布局完成后**按结果生成；不能先画死框再塞器件。
- 群内用**留白**区分子岛。
- 独立去耦/bulk 子岛不改写 S-05 的 ≤30 距离目标与合法例外；“IC 每条电源网至少 1 只”
  仍须满足，独立成岛不能让某条电源网失去去耦。也不得用“所有电容必须物理触碰 IC
  引脚”的旧措辞否定这种布局。器件类型与逐电源网覆盖在实现批结合 SymbolProfile 回验。

## 5. plan 身份与回验（536 已落）

- `LayoutPlan` / `LayoutPart` 已有**机器可读**的 `group` / `island`：多岛由
  `IslandBlock.plan` / `PackedPage.plan` 共用的 stamping helper 按 block 写入；单岛则在
  `_build_one_variant` 的普通布局路径产出时写入唯一声明岛，避免为了身份改换布局器。已有
  不同身份会 hard 拒绝，不被覆盖。序列化 round-trip 后可与 presentation 声明做
  **精确 partition** 回验。archipelago 的 group/island 计入
  `geometry_sha256`：即使坐标相同，身份变化也必须让旧预览与去重 digest 失效。两者只在
  非空时写，所以 536 之前的计划字节与 digest 一字不变；身份**不再**靠 `notes`，也禁止按坐标猜归属。
- 回验覆盖四类入口，统一走 `core.archipelago.validate_archipelago_plan`：drawcompiler 编译
  产出之后、普通 `drawapply.module_plan` 构造 ChangePlan 之前、page 的 `_draw_plan_from_page`
  构造之前，以及 `_cmd_draw_apply_page` 连接编辑器之前。partition 必须**精确相等**；缺失、
  错配、重复一律 hard 拒绝。
- **本管线的 `ChangePlan` 只能由已回验的 `LayoutPlan` 构造**：它不带声明，不是独立的岛身份
  文档，单独拿出来无法回验；手工拼出的 ChangePlan 也不能拿来证明岛群分区正确。
- 未声明新字段的普通 plan 与普通 page change 不带任何岛键，读取、回验与 digest 保持原样。
- `plan.part_id` 必须始终等于 `CircuitSpec` 的 part id；presentation 是划分的**唯一权威**。
- **538 的块级独立子岛 plan 走同一条身份规则**：`compile_island` 用
  `IslandBlock.plan(source=原始整份 circuit/presentation 哈希)` 出局部 plan，再由
  `validate_archipelago_island_plan(plan, presentation, island_id)` 在本岛声明范围内回验；
  成功 plan 的 `LayoutEvidence` 是**块级**证据（局部 readability + tolerated 主机自印行），
  不是整页证据。它不进入 `ChangePlan`、不落图：`recompile_island` 只返回一个新结果，不改旧
  结果或其它成功结果；相同输入的重编译 digest 与 evidence 不变。
- `PagePort.x/y` 是编译结果的落盘电气锚点，不是在 presentation 里手写端口；两者不得混为一谈。
- **仍未做**：子岛级 `frame` / `offset` 的结构化落盘。今天 plan 只有群/岛身份，没有子岛框与
  偏移字段；将来补时必须新增序列化字段并纳入同一 partition 回验，**禁止**用 `notes` 记、
  也不许拿坐标反推（§9）。

## 6. 验收分层

分层：**A｜契约 / JSON**——字段、不变量、示例形状；536 之后 A 层包含 **schema + plan 契约**
（岛身份可序列化、可读取、并与声明精确核对）。**B｜本例的 compile / readability `ok=True`**
——需真实 library 与后续引擎阶段，536 不声称。**C｜最终三关**——编译闸、逐脚连通、渲染视觉自审。

**A 通过不等于 B/C。** 536 做到的是 A 层的契约与 plan 回验，不是图能画或画得对；B/C 本文
一项都不声称。538 在真实 LDO 两岛上给出**块级** `ok=True`（每岛独立编译 + 局部 readability），
这是 B 层里的一块：它**不是**整板 `draw compile ok=True`，不含组内装配/页级 pack，也不构成
`ChangePlan`、落图或视觉验收。`archipelago_min` 仍没有真实 library profile，538 之后照样
不能据此声称可 compile。

可执行参考校验：

- [tests/test_536_archipelago_schema.py](../tests/test_536_archipelago_schema.py)——536 本批的
  schema / 结构 / 网表 / plan 身份聚焦用例；
- [tests/test_538_island_scope.py](../tests/test_538_island_scope.py)——538A 的 scoped
  readability 与 scoped identity 用例；
- [tests/test_538_island_compile.py](../tests/test_538_island_compile.py)——538B/538C 的单岛
  独立编译、失败隔离与显式单岛重编译用例；
- [tests/test_archipelago_contract.py](../tests/test_archipelago_contract.py)——前批的契约用例，
  已改跑生产校验器。

面积与线长只作次要比较指标，不能抵消文字接触、旗标缺失或逐脚连通失败。

## 7. 最小例子

- 网表：[mcu_cluster.circuit.json](examples/archipelago_min/mcu_cluster.circuit.json)
- 表现草稿：[mcu_cluster.presentation.draft.json](examples/archipelago_min/mcu_cluster.presentation.draft.json)

一个 `mcu_cluster`，群核心 `core = U1`，四个子岛：

| 子岛 id | parts | kind | side | owner |
| --- | --- | --- | --- | --- |
| mcu_core | U1 | core | —（省略） | U1 |
| mcu_decoupling | C1, C2 | decoupling | left | U1 |
| mcu_clock | Y1, C3, C4 | clock | right | U1 |
| mcu_swd | H1 | programming | top | U1 |

通用器件，不含真实库 profile；因此文件仍是 `.draft.json`，不是可落图的正式 spec。
536 的聚焦测试用这份草案验 schema 与 plan 身份——**schema 已接受它，不等于它能 compile**，
通过的是 §6 的 A 层契约。

这个最小例是单群，module **不声明** `grammarRef`（只有顶层 `grammarRef` 是“ic-periphery”），
所以 `pagecompiler.wants_page` 对它为假，不会被误送普通 pagecompiler；即使被送去，也会按
§2.3 被 archipelago 拒绝，而不是静默扁平化。

## 8. 预期端口

| 子岛 id | 端口 |
| --- | --- |
| mcu_core | VDD / GND / SWDIO / SWCLK / OSC_IN / OSC_OUT |
| mcu_decoupling | VDD / GND |
| mcu_clock | GND / OSC_IN / OSC_OUT |
| mcu_swd | VDD / GND / SWDIO / SWCLK |

端口由网表推导，不在 presentation 重列。

## 9. 后续批次

1. ~~schema、plan 岛身份与 2.3 hard 校验~~——**536 已完成**（§2.2 / §2.3 / §5，A 层）；
   无新字段的旧规格保持原语义与 digest。
2. ~~子岛独立编译与局部回滚~~——**538 已落块级能力**：单岛/批量独立编译（§3）与显式
   单岛重编译（`recompile_island`，只碰指定岛，无自动重试）；成功 plan 带原始整份哈希、
   scoped identity 与块级 `LayoutEvidence`。**组内装配、页级 pack、跨群连接仍未做**。
3. 核心+卫星组内装配器（多群 `drawcompiler.compile` 因此仍 hard 拒绝）。
4. 岛群页级 pack 与标题栏禁地避让，单独验收；子岛 `frame`/`offset` 的结构化落盘随此批。
5. 跨群命名连接、生成边界、离线 compile/readability 与源网表逐脚回验。
6. CH343/534 离线迁移另行批准；真机 `test` 与最终视觉验收再另批，不由本路线草案预授权。

除第 1 项（536）与第 2 项的块级部分（538）外，本文**不声称**其余任何一项已实现；538 也不
声称页级组装配、跨群连接、`ChangePlan`、落图或视觉验收。
