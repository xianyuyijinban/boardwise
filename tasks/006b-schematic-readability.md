# 任务 006b：原理图可读性——黄金几何回放 + 标签命名 + 自产渲染验收

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 依赖：006 连通性半验收已盖（逐 pin diff 0 + 参考栈 bridge-check 全零，Kimi 独立复验）。
> 前置阅读：`tasks/006-ch340-vertical-slice.md` 修订二~五、`src/boardwise/engines/generate.py`、`src/boardwise/parsers/epro2_model.py`（黄金 SCH_PAGE 的 COMPONENT/WIRE 几何）、候选构建器的 file↔canvas 坐标变换（y 符号坑，已修过一次）、参考 skill 文档：`C:\Users\xiangyu\.claude\skills\easyeda-agent\` 下的 `schematic-layout-conventions.md` / `schematic-wiring.md` / `schematic-placement.md`（间距表/朝向表/分区约定的数值来源——约束抄数值，代码不照搬）。

## 背景：006 的判决书

岳翔宇真人复核 P6 原话：**走线凌乱、随意穿过器件、没有分区放置、没有放置在原理图中心区域、随意越过原理图边框，完全不可用**。参考栈仪器量化：clusters 12 处重叠 + 1 出界；DRC 9 fatal（官方 DRC 只回聚合数，逐条明细要靠自产 lint）。

## 架构决策（Kimi 定稿）：布局即数据

**默认回放黄金几何，不重新发明布局求解器。** 黄金 `.epro2` 的 SCH_PAGE 里有人类（岳翔宇）排好的全部坐标：COMPONENT 的 x/y/rotation/mirror、WIRE 的 LINE 段（lineGroup 分组）、ATTR 位置。draw 默认把黄金布局经 file→canvas 变换（归一化 + 在 drawable area 内居中）**回放**到新页——分区、朝向、间距直接继承人类成果，可读性零成本达标。通用求解器（分区/居中/避让）降级为"无参考几何时的兜底"，本任务只需最简版。

**岳翔宇规则（优先级最高）**：信号网命名**一律用 net 标签，禁用 I/O 端口**（netport 从 draw 默认路径移除，动作本身保留）；电源/地仍用旗标（标准画法，不在禁令内）。

## 工作项

1. **回放生成器**：file→canvas 坐标变换（**注意 y 符号**——候选构建器踩过）；内容 bbox 在 drawable area 内居中；器件 x/y/rotation/mirror 照抄黄金。页框/标题栏几何从 `sch.geometry` **实测**（参考 skill 的 sheet-geometry 思路：图框图元推 bbox、标题栏在右下），禁止名义尺寸脑补。
2. **导线按黄金 WIRE 的 LINE 段回放**；修订三五条硬约束自检对回放结果照跑（人画的几何应天然全过；出现违例 = 变换错，修变换而不是修几何）。
3. **net 标签路径**（取证优先）：`createNetLabel` 挂起传闻（参考 issue #191，同宿主 3.2.186）先在**带超时的探针**里复现——不许吊死动作槽；真挂则穷举官方类型包里全部 netlabel 相关入口找替代；**若确认无路，带证据回来找岳翔宇裁量，不许擅自退回端口方案**。
4. **自产渲染动作** `export.render`（文档渲染 PNG，不信视口截图——修订四），验收图由此产出；此后不再依赖参考 CLI 出验收图。
5. **自产 layout-lint**（重叠/出界/穿器件/悬浮命名/标注叠压）进 draw 自检与收尾报告——官方 DRC 只回聚合数，逐条明细必须自产。

## 验收（三道闸门，缺一不可）

1. `compare` 逐 pin 0 差异（既有裁判）；
2. 自产 lint 0 违例；
3. 岳翔宇亲验 `export.render` 产出的图，判"可读"。

## 不许动的部分

005/006 已验收的连通性链路（解析、比较器、draw 编排语义）；桥协议信封；TOFU 配对。

---

## 实现记录（2026-09-14，执行者：WorkBuddy/Claude）— 离线全部就绪，真机探针/验收待执行

### 1. 回放生成器（工作项 1/2）

- **新增 `parsers/schematic.py::collect_page_layout`**：黄金页的**布局**（既有连通性链路一字未动）。
  实测反推的三条语义（写进模块注释与测试）：
  - **导线与符号图形怎么区分**：两者都是带 `lineGroup` 的 `LINE`，黄金夹具实测 40 个 group / 128 条
    line / 33 个 `WIRE` 头。规则 = **每个 `WIRE` 头"拥有其后第一条 LINE"的 group**（33 头 → 33 个
    互不重复的 group），旁证 = **27 个 `NET` 属性的 parentId 全部落在这 33 个 group 内**，剩下 7 个
    group 既无头也无 NET（是符号的引脚引线图形）。两条都钉了测试。
  - 分支导线按端点度数拆成多条 polyline（`_chain_segments`，含"优先直行"以减少无谓折点）。
  - 页框声明（`Width`/`Height`/`Border`/`Title Block Position`…）挂在**图框元素**（zIndex=None）的
    属性组里，随布局一并取出。
- **新增 `parsers/schematic.py::collect_symbol_bodies`**：符号**实测绘制范围** = 该 SYMBOL 文档的
  `RECT`/`POLY`/`CIRCLE` 记录的并集（CH340G = (-30,45)-(30,-45)，晶振 = ±20，0402 电容的极板+引线
  POLY 也计入），**不含 `PIN`**（引脚是连接点，IC 的引脚引线远在体框之外）。
- **新增 `engines/replay.py`**：file→canvas（`y → -y`，全工程唯一一处转换）+ 内容 bbox 在
  **实测 drawable area** 内居中（偏移吸 5 格栅保引脚格点；撞标题栏则左移/上移并**留下 note**；
  夹不住就报违例）+ 器件 x/y/rotation/mirror **照抄** + 导线按黄金 LINE 段回放 + 电源/地旗标与
  信号 net label 按人类的锚点放置。
- **页框几何全部实测**：`sch.geometry` 的 `bboxes` 段（`sch_Primitive.getPrimitivesBBox`，一次一个
  id——该 API 对数组只回一个并集框）；拿不到实测时退回黄金页的**声明尺寸**（带 provenance 标注），
  两者都没有就**拒绝回放**，绝不脑补 A4。标题栏 = sheet bbox 右下按 A 系列横向比例 0.6×0.24 切出
  （与参考实现的表一致，且**用一张真实渲染页交叉验证过**：标题栏确实在右下，实测块略小于比例框，
  即比例框是保守 keep-out）。

### 2. 自检照跑（工作项 2）——这条最有价值

修订三说"人画的几何应天然全过；出现违例 = 变换错，修变换而不是修几何"。**首跑 182 条违例**，
逐条归因后**全部是模型的错，不是人类几何的错**，共修掉四处：

| 违例 | 数量 | 真因（模型侧） | 修法 |
|---|---|---|---|
| BOX_OVERLAP | 19 | 包围盒 = 引脚展幅 + 20 pad，把"贴在 IC 旁边的去耦电容"判成重叠 | 改用**实测绘制范围**、pad=0（实测：pad 20 → 19 条假重叠；pad 0 → 0 条） |
| WIRE_THROUGH_BOX | 25 | 同上（线只是**端在**体框边上） | 同上；且 `_segment_crosses_rect` 本就是**内部相交**判定，边界相触不算 |
| ENDPOINT_NOT_TERMINAL | 13 | ① 每条导线单独成 route → 看不见"同网另一条线在端点处的交汇"；② 带 net label 的线端**本来**就是合法终端 | ① route 按**网**归并；② 端点带同网标注即合法；③ 短"出头"（实测：一处 VCC 支路越过交汇点 4 units）给 10 units 容差，变换错会差几十上百，藏不住 |
| CROSS_NET_SHORT | 6 | 同名电源轨的**独立短桩**端点落在 GND 母线上——编辑器**正是要**在那打结点（文件里就有人类这么画的） | 有效网名改用模型的连通性 + 编辑器规则（引脚尖落线上、端点落线上都算连通）做 union-find 归属 |

**终态：黄金板回放 0 违例**（17 器件 13 网 45 折线 27 命名 12 NC）。这组数字同时是仪器校准：
模型若错，人类几何不可能全过。

### 3. net 标签路径（工作项 3）：动作已改造成"带证据的探针"

- `sch.place_netlabel`：**8s 上限**（`timeoutMs` 可覆盖，夹 200..30000ms）——不许吊死动作槽；
  超时/未返回时**回读 `sch_PrimitiveAttribute.getAll()`**，在错误里明确回答"到底落没落"
  （`landedAnyway` + matches + elapsedMs），并写明 **do NOT retry**（参考实现的教训：超时的那次
  写入可能已经成功，盲重试会叠出重复标注）。
- **穷举官方类型包里 netlabel 相关入口的结论**：全局只有 `sch_PrimitiveAttribute.createNetLabel`
  一处（`sch_PrimitiveNetLabel` 命名空间**在类型包里不存在**——这也是 `sch.geometry` 的
  `netlabels: available=false` 的原因），`SCH_PrimitiveAttribute` 的其余方法只有 get/getAll/modify/
  delete，**没有第二条创建路径**。
- 因此真机探针是**唯一**的判据：若确认不可用且什么都没落，按任务书**带证据回来找岳翔宇裁量**，
  不擅自退回端口（回放路径目前**完全不产生 netport**，已由测试钉住）。

### 4. `export.render`（工作项 4）

- 新增动作 `export.render` = `sch_ManufactureData.getPngFile(fileName?, {width?,height?})`（beta，
  v3.2.183+）→ base64。**文档渲染，不是视口截图**（修订四）。
- 多图页时该 API 可能返回 zip → 动作**如实报 `format: 'zip'`** + note，不会把压缩包写成 .png。
- `export.screenshot` 保留但**降级为诊断**（报告里标注 "diagnostic only"），验收图只认 `export.render`。
- daemon 侧给它 60s 预算（与截图同档）。

### 5. 自产 layout lint（工作项 5）

- **`boardwise lint --from <golden> [--plan replay|solver] [--json]`**：完全离线（不需要 daemon），
  打印逐条违例 + 分类计数，退出码 0/1。
- 新增四类**标注**违例（`layout.lint_annotations`）：`LABEL_FLOATS` / `LABEL_ON_COMPONENT` /
  `LABEL_OVERLAP` / `LABEL_ON_TITLE_BLOCK`；连同既有五大约束一起进 `generate_plan` 的自检门禁
  （有违例 → `SelfCheckFailed` → **一个桥调用都不发**）。
- 标注预测框用**同一把尺**（参考实现的硬规矩）：旗标 = 实测符号图形 ∪ 6 units/字符的文字带；
  net label = 文字带（高度 9，由"人类自己的标签间距是 10 且读得清"反推）。首版用了参考实现的
  netport 下限 31 → 把人类的 "TX" 标签判成压到旁边的电容，实测后改成 label 用自己的宽度。

### 6. 测试与产物

- Python **239**（206 → +33，新增 `tests/test_replay.py`）；connector **116**（106 → +10，新增
  `tests/actions006b.test.mjs`）；`tsc --noEmit` 干净。
- connector **0.3.4**（16681 B）双验（`testzip()` None + 包内 md5 与磁盘一致），0.3.3 已删。

### 7. 真机待办

1. 重启 daemon（动作目录新增 `export.render`；旧进程会回 `UNKNOWN_ACTION`）。
2. 侧载 0.3.4 + 重启编辑器，test 工程前台。
3. 探针：`sch.geometry`（实测 sheet bbox）+ 导线 net 是否生效 + `sch.place_netlabel`
   （带 timeoutMs）→ 结论写回本文件。
4. `boardwise lint`（离线，应 0 违例）→ `boardwise draw --render out.png` → 三道闸门
   （逐 pin 0 差异 / lint 0 违例 / 岳翔宇读 `export.render` 图判"可读"）。

---

## 实现记录（第 2 轮：真机探针，2026-09-14）

### 8. 已实测的三条结论

**8.1 `sch.geometry` 的实测 sheet bbox —— 通过。**
`meta.available.bboxes = true`，`bboxes[b5ba3517…] = {0,0,1170,825}`，`meta.sheets` 给出页图元 id。
**1170×825 正好等于黄金页声明的 `Width`/`Height`** —— 即"图框是量出来的"这条设计在真机上成立，
且 004 侦察里"sheet 的 `getState_*` 只有锚点没有范围"这一判断被再次印证（`Width`/`Height` 出现在
声明属性里，实测范围由 `getPrimitivesBBox` 给出，两者一致）。

**8.2 `sch.place_netlabel` 在 3.2.186 上不可用 —— 挂起且不落地。**
```
TIMEOUT; elapsedMs 6963 (bound 6000); landedAnyway false; matches 0
```
根因在**类型包**而非宿主：`createNetLabel` 文档标注 **"ADD since EDA v4"**，宿主是 v3.2 线。
所以在 3.2.186 上它不是"偶发挂起"，而是**注定不会 settle**；超时保护把它变成可上报的失败
（而不是吊死动作槽），readback 排除了"超时但已生效"。类型包内**无替代路径**
（`createNetFlag` 只吃 `Power/Ground/AnalogGround/ProtectGround`；`sch_PrimitiveNetLabel`
不是命名空间）。→ 单独立卷：`tasks/006b-netlabel-finding.md`，等岳翔宇裁决。

**8.3 `export.render` 在 3.2.186 上返回 `NOT_IMPLEMENTED`。**
`detail.path = "sch_ManufactureData.getPngFile"`（带方法名 → 是"方法缺失"分支，不是"命名空间缺失"）。
对照：旧 API `export.screenshot` **可用**（80820 B PNG）。`getPngFile` 声明门槛是 **v3.2.183**
< 3.2.186，与 8.2 的机制**不一致** → 需要成员枚举才能定案。

### 9. 本轮新增（为定案 8.3 而做）

**connector 0.3.5** —— 新增**只读**诊断动作 `sys.probe`：

- 返回编辑器版本、`eda` 顶层绑定的命名空间全名单、每个请求命名空间的**真实成员名**；
- 走**原型链**枚举（`Object.keys` 在类实例上返回 `[]`——这是 09-14 踩过的坑）；
- 缺命名空间报 `present: false` 而**不是抛错**（缺一个东西 ≠ 某一步失败）；
- 纯只读：**不调用任何方法**，每个分支都留痕（`8.3` 的"缺一个东西"就是靠这个说清的）。

同时：`docs/bridge.md` / `docs/draw.md` 更新了实测结论与探针命令；`docs/draw.md` 的
"已知限制"改为指向本文件的证据。

**测试**：connector **120**（116 → +4，`sys.probe` 的四条：版本+成员、原型链、缺命名空间、
多命名空间）；Python **241**（+1，`bridge --help` 覆盖 `export.render` + `sys.probe`）。

### 10. 当前阻塞

`sys.probe` 进了 catalogue → **daemon 必须重启**（11:32 那个进程是旧 ACTIONS）。
**0.3.5 需要侧载 + 编辑器重启**（侧载会重置扩展存储 → 一次 UNAUTHENTICATED 波，属已知行为，
重连后即恢复；本轮已观察到 11:16 / 11:42 各一次）。

重启后按序：`sys.probe`（定案 8.3）→ `boardwise lint`（已过：0 违例）→
`boardwise draw --render out.png`。

### 11. 离线闸门（已过，无需编辑器）

```
$ boardwise lint --from tests/fixtures/ch340_golden.epro2
plan source: golden replay
components: 17  nets named: 27  wires: 45  NC pins: 12  notes: 3  violations: 0
  note: shifted left of the title block
  note: page offset (0, 50) from the golden coordinates
  note: 35 wire run(s) carry no net name in the source (the editor derives them from the flags)
layout lint: 0 violations
```

### 12. 待裁决项（不静默降级）

信号网命名在本宿主上无可用 API 路径（8.2）。**不动 `sch.place_netport`**。
选项与建议见 `tasks/006b-netlabel-finding.md` §3。

---

## 修订（第 3 轮：Kimi 真机探针定稿，2026-09-14 下午）— 命名策略定案 + 整改清单

> 执行者：DeepSeek。本轮基于 Kimi 在真机上完成的 wire.net 探针（证据见下）。
> **注意**：探针在 P1 页留了残留（R1/R2/R3 三颗 0603 电阻 + 一条导线，其中 R1/R3 叠在
> (100,100)——`place_component` 首次超时但落地了）。**验证用 draw 不许用 P1**；按岳翔宇新规，
> 建新页前必须先问他。

### A. 探针判决（实测，已复核）

1. **wire.net 被编辑器网表器承认**。P1 页纯 API 图元（3 电阻 + `net="PROBE_WIRE_NET"` 导线，
   无任何标签/旗/端口），`getNetlistFile` 导出的网表里 `R1.2/R2.2/R3.1 → PROBE_WIRE_NET`。
   → 信号网可以"电气上有名、视觉上无标签"，**无需标签也无需端口**。
2. **H-A 假设证伪（收窄）**：纯器件+导线的 API 页导出**正常**。之前失败页的共同特征是
   netport/旗标图元 → 新假设：**netport 才是网表导出的毒药**（draw 验证时复核）。
3. **`place_component` 有"超时但落地"坑**（首次库解析 >30s）：第一次调用 TIMEOUT 但电阻已放上，
   造成叠件。netlabel 的同款坑在放置动作上同样存在。

### B. 命名策略（岳翔宇已授权 Kimi 定稿）

生成器加**命名策略开关**，四档：`wire`（默认，导线携带 net——本轮实测）/ `text`
（wire + 在导线旁放 `sch_PrimitiveText` 伪装标签，纯装饰不参与连通，报告里必须如实标注
"信号网名以文本呈现，非原生标签"）/ `label`（v4 dormant 路径，保留超时保护）/ `none`。
**默认 `text`**（岳翔宇规则的原意是"信号网要看得见名字"，TEXT 是最接近的合法形态；
闸门 3 他亲验渲染图时若否决伪装标签，拨到 `wire` 即可，零返工）。电源/地旗标不变。
回放路径继续**零 netport**（既有测试钉住）。

### C. 整改清单（做掉再跑闸门）

1. **`place_component` 超时硬化**：与 netlabel 同款的 landedAnyway 回读（按坐标/bbox 查
   新落件），超时错误里如实报"落没落、落了几颗"；首次库冷启动慢——放置超时单独放宽到
   60s 或加 `timeoutMs` 参数。测试钉住。
2. **`sys.probe` 枚举修复**：原型链遍历对宿主 exotic object 全军覆没（所有命名空间都抛
   `reading 'prototype'`）——改 `Object.getPrototypeOf` 安全循环 + 每级
   `getOwnPropertyNames`，任何一级异常只记 `error` 不中断。修完重探
   `sch_ManufactureData`（getPngFile/getSvgFile 定案 8.3）+ `dmt_EditorControl/dmt_Schematic`
   （找 tab 切换 API，为 006c `doc.open` 铺垫——结果写进 `docs/api-survey.md`）。
3. **draw 验证路径恢复网表首选**：netport 退出默认路径后，API 页导出应恢复可用——
   draw 收尾先 `sch.doc.save` 再 `sch.netlist`；成功则以权威网表跑 compare，geometry
   回退保留为兜底；若仍失败，把失败页的图元类型分布记下来（复核"端口毒化"假设）。
4. 版本 → **0.3.6**（命名策略 + 放置硬化 + probe 修复），重新打包双验。

### D. 收尾流程（修订）

**建页授权：岳翔宇已批准验证 draw 在 test 工程新建一页（2026-09-14，一次性）。**
侧载 0.3.7 + 重启编辑器 → Kimi revoke 重配对 → `sys.probe` 复探（names 模式定案
getPngFile/getSvgFile + tab 切换 API 侦察）→ `boardwise draw`（新页，默认 `text` 策略）→ 三闸门：
逐 pin 0 差异（首选网表路径）+ lint 0 违例 + 岳翔宇亲验渲染图。
若 `getPngFile`/`getSvgFile` 实锤全缺：验收图暂用 `export.screenshot` 但**标注
diagnostic-only 并先报 Kimi**，不悄悄当验收图。


---

## 实现记录（第 3 轮，2026-09-14 深夜）— §B/§C/§D 离线部分全部落地，真机待执行

> 执行者：WorkBuddy/Claude（DeepSeek）。connector **0.3.6** 已打包双验；Python **252 passed**；
> connector **129 passed** + `tsc --noEmit` 干净。以下按任务书 §B/§C 逐条对账。

### 13. §B 命名策略：四档全链路打通

- `engines/generate.py`：`NAMING_STRATEGIES = ("wire","text","label","none")`、
  `DEFAULT_NAMING_STRATEGY = "text"`、`normalise_strategy()`（未知值回落默认）。`NetNameStep`
  加 `kind="text"` 与 `decorative`；`ActionPlan.naming_strategy` + `decorative_names`；
  `naming_steps_for(route, attach, strategy)` 统一裁决 —— 电源/地永远走旗标，信号网按策略。
- `engines/replay.py`：`build_replay_plan(..., strategy=)` / `replay_or_solver(..., strategy=)`
  透传；黄金页 label 段按策略产 `text`（decorative）/ `label` / 跳过（wire/none）。
  **回放路径依旧零 netport**（既有测试钉住）。
- `engines/draw.py` + `cli.py`：`boardwise draw|lint --naming {wire,text,label,none}`；
  闸门与验收报告都打印策略名，`text` 档带 "(decorative, NOT native net labels)" 免责行；
  JSON 输出带 `naming` / `decorative_names`。
- **关键修正（本轮的坑）**：`wire`/`none` 档下 golden replay 曾报 **10 条假
  `ENDPOINT_NOT_TERMINAL`**——因为 `annotation_points` 只从 `plan.net_names` 取，而这两档
  不放置任何命名图元，人类标签锚点处的导线端点就被判成"非终端"。
  **修法**：`annotation_points` 改为**始终**并入黄金页 `labels`/`flags` 的锚点 —— 锚点是
  **几何事实**（人类把导线画到那里并命名），与当前策略是否*绘制*名字无关。
  这是"修变换而不是修几何"，符合 §2 的规矩。四档现在**全部 0 违例**，已有参数化回归测试
  （`test_the_goldens_geometry_lints_clean_under_every_strategy`）钉住。

### 14. §C.1 `place_component` 超时硬化 ✅

- connector 新增 `PLACE_COMPONENT_TIMEOUT_MS = 30_000` 与 `componentsNear(eda,x,y,tol=30)`
  回读（当前页 `sch_PrimitiveComponent.getAll`，按 X/Y 容差）。
- `sch.place_component` 现在返回 `elapsedMs`；超时抛 `ActionError('TIMEOUT', …)`，detail 带
  `{device, x, y, elapsedMs, timeoutMs, landedAnyway, landedCount, near}`，message 按落没落
  分别写 **"do NOT retry"** / "nothing appeared"。
- daemon 侧 `PLACEMENT_TIMEOUT = 60.0`，`timeout_for("sch.place_component")` 返回 60s ——
  **故意长于 connector 自己的 30s deadline**，让 connector 的回读答案先到，而不是 daemon 先超时。
- 测试 4 条：未落地 / 已落地（`landedAnyway: true`）/ 远处件不算 / 成功带 `elapsedMs`。

### 15. §C.2 `sys.probe` 枚举修复 ✅

- connector 新增共享 walker `walkPrototypeNames(object, filter?, errors?)`：**从对象自身开始**
  逐级 `getOwnPropertyNames` → `getPrototypeOf`，每级单独 try，异常记入 `errors`，深度上限 32，
  跳过 `Object.prototype`/`Function.prototype`。三个调用点共用（`snapshot` / `deepDump` / `sysProbe`）。
- **踩过的坑**：初版从 `getPrototypeOf(object)` 开始 → 普通对象命名空间（如 `sys_Log`）的成员
  是 **own 属性**，全被跳过（`sys_Log.add` 找不到）。这正是"两条观测矛盾时先怀疑观察者"。
- `sysProbe` 返回 `{present, kind, ownNames, functions, data?, errors?}`，单个命名空间取值也
  try（记 `read <key>`），缺命名空间报 `present: false` 不抛错。
- 测试 2 条：Proxy `getPrototypeOf` 抛错 → 断言 `ns.errors` 含 `getPrototypeOf`；exotic primitive
  下 `snapshot` 不丢字段。
- **真机复探仍待执行**（§D）：`sch_ManufactureData`（`getPngFile`/`getSvgFile` 定案 8.3）+
  `dmt_EditorControl`/`dmt_Schematic`（tab 切换 API，为 006c `doc.open` 铺垫）→ 结果写
  `docs/api-survey.md`。

### 16. §C.3 draw 验证恢复网表首选 ✅（+ 新增失败页 census）

- draw 收尾顺序已是 **`sch.doc.save` → `sch.netlist`（首选）→ `sch.geometry`（兜底）**，
  `candidate_source` 如实标注是 `netlist export` 还是 `geometry readback`。
- **本轮新增**：网表失败时先跑 `_census_primitives` —— 读 `sch.geometry` 并按图元类型计数，
  结果进 `DrawResult.netlist_census` 并在报告打印 `page census (netlist failed): <type>=<n>, …`。
  标签键依次尝试 `type`/`primitiveType`/`kind`/`className`/`name`，**读不出的进 `<unlabelled>`
  桶，绝不静默丢弃**（会隐藏的正是最可疑的那一行）。这就是复核"端口毒化"假设的仪器。
- 测试 2 条：census 不漏任何图元（含 2 条 unlabelled）；无 primitives 列表时返回 `{}`。

### 17. §C.4 版本 0.3.6 + 打包双验 ✅

- `connector/package.json`、`connector/extension.json` → `0.3.6`。
- `npm run build` → `dist/index.js` 67.1kb；`npm run package` → `boardwise-connector-0.3.6.eext`
  （2 entries: `extension.json` 2149B + `dist/index.js` 68663B，archive 17905B）。
- **双验**：① 自产打包器报告的 entries/大小；② **Python `zipfile` 独立复核** ——
  `testzip() -> OK`，`namelist() == ['extension.json','dist/index.js']`，
  `extension.json` 的 `name/version/entry` = `boardwise-connector / 0.3.6 / ./dist/index`，
  且两条中央目录记录时间戳均为固定 DOS `(1980,1,1,0,0,0)`（可复现构建）。

### 18. 离线闸门状态

- `boardwise lint --from tests/fixtures/ch340_golden.epro2 --naming {wire,text,label,none}`
  → **四档全部 `0 violations`**。
- Python **252 passed**；connector **129 passed**；`tsc --noEmit` 干净。
- `docs/bridge.md`（新动作 `sch.place_text`、`place_component` 硬化、probe 修法）与
  `docs/draw.md`（命名策略表、census、验收流程 0.3.6、禁用 P1）已更新。

### 19. 真机待执行（需岳翔宇/Kimi 动手，本轮无法代劳）

按 §D：侧载 0.3.6 + 重启编辑器 → Kimi revoke 重配对 → `sys.probe` 复探 →
**问岳翔宇可否建新页**（新规）→ `boardwise draw`（**新页**，默认 `text`；**禁用 P1**，有探针残留）
→ 三闸门。若 `getPngFile`/`getSvgFile` 实锤全缺：验收图暂用 `export.screenshot` 但
**标注 diagnostic-only 并先报 Kimi**。闸门 3 若否决伪装标签 → `--naming wire` 零返工重跑。

---

## 架构决定（第 4 轮，2026-09-14 傍晚，Kimi 定，已实现）— 放弃通用枚举，改两条更稳的路

> 执行者：WorkBuddy/Claude（DeepSeek）。connector **0.3.7** 已打包双验；Python **256 passed**；
> connector **135 passed** + `tsc --noEmit` 干净。

### 20. 候选名来自离线类型包（不是运行时枚举）✅

- 新增 **`tools/api_names.py`**：从 `@jlceda/pro-api-types/index.d.ts` 文本里抠出目标命名空间的
  全部方法名 + 每条方法上的 `ADD since EDA v…` / `@beta` / `@internal` 标注。纯离线、完备、
  不需要编辑器。
- 用法：`--methods-only`（贴进 checks）、`--json`、`--emit-ts <path>`（生成 TS 模块）。
- 生成物 **`connector/src/api-names.ts`**：`PROBE_CHECKS`（五个命名空间的**完整**声明面：
  `sch_ManufactureData` 13 / `dmt_EditorControl` 20 / `dmt_Schematic` 17 / `dmt_Pcb` 7 /
  `sch_Document` 9）与 `ADDED_SINCE`（`getPngFile`/`getSvgFile` = v3.2.183）。文件头写明
  "Generated — do not edit by hand" 与重生成命令。
- **`tests/test_api_names.py`** 在内存里重跑生成器并与磁盘产物逐字比较 —— 升类型包而没重生成
  时测试直接红。另有三条：检查表里的名字必须真的在包里声明（防手误变永久 missing）、
  自带 sample fixture 覆盖解析规则、`{@link https://…}` 的散文花括号不参与括号计数。
- **解析器踩的坑（值得记）**：初版用注释剥离后再数括号，`{@link https://…}` 里的 `//` 被截断，
  留下一个孤立 `{`，把**运行深度永久抬高 1** → 之后每个 class 都"没闭合"，成员全折进前一个类
  里（症状：`SYS_ClientUrl` 报 544 个成员）。**修法**：注释行完全不参与括号计数。这是
  "两条观测矛盾时先怀疑观察者"的又一例 —— 不是类型包怪，是我的尺子坏了。

### 21. `sys.probe` 加 `names` 模式 ✅

- 参数 **`{"checks": {"<namespace>": ["methodA", …]}}`**：对每个名字只做
  **`typeof ns[name]`** —— 属性访问穿透原型链是语言本身的行为，**根本不需要枚举**，对
  exotic object 免疫。
- 结果按 `function` / `object` / `undefined` 如实上报，**外加两个不与它们混淆的值**：
  `threw: <message>`（读本身失败）与 `namespace-absent`（命名空间不在）。每个命名空间返
  `{present, kind, checked, missing, status, notes?}`。
- `notes`：类型包标注 `ADD since EDA v…` 而实机读回 `undefined` 的方法，报告**直接带上这条
  矛盾**（`declared ADD since v3.2.183 on this host`），不留给读者自己对照。
- **`checks: true`** 用离线表（`PROBE_CHECKS`），即"类型包声明的完整面"；显式对象可逐名覆盖。
- **通用枚举保留**（`namespace`/`namespaces`/`functionsOnly`），任何一级异常只记
  `errors` 不中断 —— 它是**预测性**模式：能找到没人想过的名字，这是类型包给不了的。
- daemon `protocol.py` 的 `sys.probe` 条目已更新（params 加 `checks`，returns 写清两种模式）。

### 22. 测试钉住真实形状 ✅（connector +6 = 135）

- **`hostThatBreaksEnumeration(members)`**：Proxy，`getPrototypeOf` 与 `ownKeys` 都抛
  `Cannot read properties of undefined (reading 'prototype')`，**`constructor` 取不到**——
  复现这次真机崩溃的形态。断言：枚举会死，而 **checks 模式照样给出真答案**。
- 原型链穿透：`class Parent extends Grandparent`，两个方法分别在两级，checks 全中。
- 抛错的读 vs 不存在的读：`threw: host said no` 与 `undefined` **分开报**。
- 命名空间缺席 → `namespace-absent`（不是 `undefined`）。
- ADD-since 方法缺失 → `notes` 有那条矛盾，未缺失的方法**不**记 notes。
- `checks: true` → 断言五个命名空间齐、且每个 `checked > 0`（生成表被清空或名字漂移时直接红）。

### 23. 版本 0.3.7 + 打包双验 ✅

- `connector/package.json`、`connector/extension.json` → `0.3.7`。
- `npm run build` → `dist/index.js` 71.9kb；`npm run package` → `boardwise-connector-0.3.7.eext`
  （2 entries：`extension.json` 2149B + `dist/index.js` 73589B，archive 19232B）。
- **双验**：① 自产打包器报告的 entries/大小；② **Python `zipfile` 独立复核** ——
  `testzip() -> OK`，`namelist() == ['extension.json','dist/index.js']`，
  `extension.json` 的 `name/version/entry` = `boardwise-connector / 0.3.7 / ./dist/index`，
  两条中央目录记录时间戳均为固定 DOS `(1980,1,1,0,0,0)`（可复现构建）。
- 产物内容复核：`dist/index.js` 里含 `namespace-absent` / `declared ADD since` / 生成表
  的名字（确认 import 没被 tree-shake 掉）。

### 24. 文档

- `docs/bridge.md`：`sys.probe` 目录行改双模式；新增第 372 行的双模式原理段。
- `docs/draw.md`：机器探针清单改成 `0a` checks（首选，免疫 exotic）+ `0b` 枚举（预测性），
  前置版本 → 0.3.7。
- `docs/api-survey.md`：新增 §3「roadmap 依赖的命名空间的声明面」，含五个表 + 复现命令 +
  为何用离线抽取而非运行时枚举。

### 25. 真机待执行（不变，现在用 checks 模式复探）

侧载 **0.3.7** + 重启编辑器 → Kimi revoke 重配对 →
`bridge call --action sys.probe --params '{"checks": true}'`（**首选**，免疫 exotic）→
**问岳翔宇可否建新页**（新规）→ `boardwise draw`（新页，默认 `text`；**禁用 P1**）→ 三闸门。
`sch_ManufactureData` 的 `getPngFile`/`getSvgFile` 定案（若 `undefined` → `notes` 会带上
`ADD since v3.2.183` 的矛盾）；`dmt_EditorControl`/`dmt_Schematic` 找 tab 切换 / 建页 API
（为 006c `doc.open` 铺垫）→ 结果写 `docs/api-survey.md`。

---

## 修订（第 4 轮：Kimi 验证 draw 取证，2026-09-14 傍晚）— 回放脆性根因与修复令

> 执行者：DeepSeek。第 3 轮修订的产物（0.3.7，命名策略 `text`）已实测：draw 在新建页
> 跑完全流程，但 compare 报 **51 差异**。逐条取证（Kimi 独立复核，证据如下）后定性：
> **不是回放几何错，是"库件替换"在三个不同的缝上撕开了回放假设。**

### E. 取证记录（全部实测）

1. **解析替换失真（R24/R27/U3）**：黄金 R24/R27 = `Res_0402`（无 LCSC）、U3 =
   `FRC0805J471 TS`（470Ω 0805）；实际放置 = 0603 5.1K 与 `RN1WS1KΩFT/BA1`（1kΩ）。
   封装/值全错 → 回放的金色导线端点打不到大号 0603 符号的引脚尖 → 引脚悬空 →
   网成员丢失 → "net missing" 级联差异。U3 value 差异同源。
2. **同件异版（USB1）**：黄金有 LCSC `C2765186` 且**放置解析正确**（MPN 同为
   TYPE-C 16PIN 2MD(073)），但**库符号已演进**：黄金引脚编号 1–14，现行库用
   Type-C pad 名（A1B12/B5…）→ ① 引脚位置变了，回放导线全部打空（放置后网表
   USB1 全引脚 net=""）；② 编号体系变了，28 条 pin 差异是假账。
3. **架构定性**：回放默认"放下的符号与黄金符号全同"，**没有任何环节验证这个假设**。
   006 能活是因为它的布线从回读引脚坐标自适应；006b 照抄黄金坐标，脆性暴露。
4. **附带胜利**：本页（旗标+TEXT+导线，零 netport）`getNetlistFile` 导出成功——
   "netport 毒化网表导出"假设再获一票支持，网表首选路径已恢复可用。
5. 黄金模型的引脚**名字段全空**（解析器没取 SYMBOL 的 PIN 名）——名字段 reconciliation
   的数据基础要先补。

### F. 修复令（做掉再重跑闸门）

- **F1 解析保真**：把 .epro2 的 DEVICE 文档 META 接到原理图组件上（device uuid /
  libraryUuid / lcsc——005 已证 28/28 DEVICE 带 META）；放置解析顺序 =
  **uuid → lcsc → 封装约束关键字**（`Res_0402` 必须搜 "5.1K 0402" 类）；逐件上报解析保真度。
- **F2 放置后校验门禁（fail fast）**：每件放置后回读实际引脚布局，与黄金符号建
  **引脚映射**（先按 number；编号体系分叉时按 **name**——为此解析器必须补取黄金
  SYMBOL 的 PIN 名字段）；建不出映射的件**立即停止**，出逐件报告，不许画破页。
- **F3 端点重映射**：回放几何照抄，**唯独以引脚为目的地的导线端点**按 F2 的映射
  吸附到放下符号的实际引脚位置。符号全同时映射=恒等（纯回放语义不变）。
- **F4 比较器**：编号分叉时按映射后的身份比对，并在报告里显式标注"该件编号体系
  已与库版本漂移"，不拿 28 条假 pin 差异充数。
- 重跑三闸门前先清掉本次验证页（岳翔宇手动删，我们无删除能力——设计如此）。

---

## 实现记录（第 4 轮修复令 F1–F4，2026-09-14，版本 0.3.8）

> 结论先行：**F1/F2/F4 全部落地并通过测试；F3 按字面不可实现——但失败原因是一个
> 比实现更重要的实测事实，见 §I-3。全部 275 条 Python 测试 + 135 条 connector 测试通过。**

### G. 交付物

| 项 | 文件 | 状态 |
|---|---|---|
| F1 解析保真 | `parsers/schematic.py`（DEVICE META join + 引脚名捕获）、`engines/generate.py::_keyword_for` | ✅ |
| F2 校验门禁 | **新增** `core/verify.py`（`build_pin_map` / `verify_placements`）、`engines/draw.py::_verify_placements` | ✅ |
| F3 端点重映射 | **不实现**（见 §I-3 的实测依据）；改为 F2 门禁 + F4 身份比对承载其目的 | ⚠️ |
| F4 比较器 | `core/compare.py::compare_models(pin_maps=)` | ✅ |
| 测试 | **新增** `tests/test_verify.py`(9)、`tests/test_compare_identity.py`(8)、`test_candidate_draw.py`(+3)、`test_calibration.py`（方向性 enrichment） | ✅ |
| 版本 | connector **0.3.8**，`testzip` 独立复验通过 | ✅ |

### H. F1 —— 解析保真（DEVICE META join）

1. **新增 `_collect_device_meta(records)`**：`.epro2` 的 DEVICE 文档 META → 字段字典
   （`lcsc_part`/`mpn`/`manufacturer`/`datasheet`/`footprint`/`name_template`/`title`/`symbol`）。
2. **新增 `resolve_component_identity(inst_attrs, device_meta)`**：**实例有值则胜，META 只填空白**。
   返回 `(fields, provenance)`，provenance 逐字段记 `"<field>=instance|device|missing"`，
   并入 `component.props["identity_provenance"]` —— 逐件解析保真度据此可查。
   *为什么方向不能反：* 实例字段可以是**过期值**（实测 U3 实例 `Value='1kΩ'` 而 DEVICE META
   `title='FRC0805J471 TS'` 即 470Ω），但实例非空就说明是人手改过的，应当尊重；
   只有空白才轮到库真值。
3. **引脚名捕获**：`_collect_symbols` 重写为 run 式 —— `PIN` 打开一个 run，
   随后的 `ATTR key="Pin Name|Pin Number|Pin Type"` 归属该 run，遇下一个 `PIN` 时提交。
   ATTR 顺序任意（USB-C 先 Name 后 Number），空值/字面量 `"null"` 不采。
   黄金模型由此获得 `Pin(name=...)`，这是 F2/F4 的全部数据基础。
4. **实测结果**（黄金夹具）：
   - `U3` → `lcsc=C2907329`（device）、`mpn=FRC0805J471 TS`（instance）、`footprint=0805`
   - `U1` → `lcsc=C14267`/`mpn=CH340G`/`footprint=SOP-16`
   - `R24` → `lcsc=''`、`footprint=0402`（device）、`device_name=Res_0402`
   - USB1 引脚名 `GND/VBUS/CC1/DN2…` 全部填充。
5. **放置解析顺序（`_keyword_for`）**：`uuid → lcsc → 封装约束关键字`。
   无 LCSC 时关键字 = **`f"{value} {footprint}"`**（`R24` → `"5.1K 0402"`），
   否则退 `device_name`，最后才裸 value。
   *这就是 round-4 根因的直接修复：裸 `"5.1K"` 搜出 0603，`"5.1K 0402"` 才锁定 0402。*

### I. F2 / F3 / F4

#### I-1. F2 门禁（`core/verify.py`）

- **判据阶梯（最强键优先）**：
  1. 件不在页上 → `unmappable`；
  2. 黄金每个 pin number 都在放下件上 → **`exact`**（映射=恒等）；
  3. number 不齐但**名字**可一一对上 → **`drifted`**（库重画符号、改了编号，信号没变）；
  4. 两把钥匙都不行 → **`unmappable`**。
- **重复名处理**：Type-C 天然有两个 `GND`/`VBUS`/`SHELL`。按**同名内序位**配对
  （第 1 个黄金 `GND` → 第 1 个放下 `GND`），确定性且标准；名字**数量**不一致则
  整组放弃 → 落到 `unmappable`，绝不硬配。
- **`PlacementReport.ok`**：`unmappable` 或**孤儿引脚**任一存在即 `False`。
  **`drifted` 不阻塞**（端点按名字重映射、报告里显式标注）。
- **接线（`draw.py::_verify_placements`）**：放置完成后 **save → 导出网表 → 建 candidate →
  verify → 不 ok 立即 return**（一根线都不画）。**读回不可用时不停**（"不知道" ≠ "知道坏了"），
  只记一条失败步骤 —— 否则会回退 006 已能跑的板子。
- **副产品**：这份读回 candidate 直接复用为最终 diff 的 candidate，省掉第二次
  导出（该导出在本机是实测脆弱的），`candidate_source` 如实改为
  `"netlist export (placement readback)"`。

#### I-2. F4 比较器（`compare_models(pin_maps=)`）

- 只对 `kind == drifted` 的件翻译**寻址**：pin 级把黄金号换成放下号，net 级把成员
  元组换成放下侧的元组。**判定本身一个字不改** —— 真断的线照样报。
- **已复现 round-4 的 28 条假差异并证明其消失**（`tests/test_compare_identity.py`）：
  | 场景 | pin 差异 |
  |---|---|
  | drifted，**无** map | **28**（= 任务书记录的假账） |
  | drifted，**有** map | **0** |
  | drifted + 真断线，有 map | **2**（精确指出 `USB1.11`/`USB1.2`，都是 VBUS） |
- 无 map / 非 drifted 件走旧路径 → 完全向后兼容（`total` 相等已断言）。

#### I-3. F3 为什么不实现 —— 实测：**放下符号的引脚几何在任何 API 上都拿不到**

F3 原文要求"按 F2 的映射**吸附到放下符号的实际引脚位置**"。要吸附就得知道
**放下后的引脚坐标**。本轮把每一条可能的路都实测堵死了：

| 路径 | 实测结果 |
|---|---|
| `sch_PrimitivePin.getAll()` | 原理图页返回**空** —— pin 属符号，不属图元集 |
| 组件 state 的 `Symbol` 字段 | **空对象** —— 编辑器拒绝序列化符号引用 |
| `lib_Symbol.get()` | 返回 `ILIB_SymbolItem`：只有 uuid/name/type/分类，**无引脚几何** |
| `lib_Device.get().association.symbol` | 只有符号 uuid + libraryUuid，**无几何** |
| 网表 `pinInfoMap` | 每 pin 只有 `name`/`number`/`net`/`props.Pin Number`，**无坐标** |
| geometry 转储 `pins` | 黄金页实测 `len(pins) == 0` |

**⇒ 不存在"放下符号的实际引脚位置"这个可读量。** 位置只能由（放置点 + 黄金符号
偏移）**推算**，那正是回放已经在做的事。

**因此 F3 的目的改由两件可做且已做的事承载**：

1. **F2 门禁**：映射建不出来（几何不可信）→ **拒绝画**，而不是画一条"自信地错"的线；
2. **F4 身份比对**：映射建得出来（`drifted`，即库重画但信号可辨）→ 比对按名字走，
   假差异清零。

**对"端点位置"本身的诚实交代**：F3 字面要求的**坐标吸附**在 drifted 件上做不到，
所以回放的端点**仍然落在黄金引脚尖**。这在"库重画符号但**焊盘位置未变**"时**恰好正确**
（只是编号变了）；在"焊盘位置也变了"时不正确 —— 而这种情形**当前无法与几何不匹配区分**，
只能靠 F2 的映射建不出来时拒绝。**这是本机 API 面下的能力边界，必须写进文档，
不能装作已实现。** 若将来需要真正吸附，唯一出路是拿到库符号的引脚几何
（`lib_Symbol` 的文档源或 `getRenderImage` 之外的接口），需要一次专门的 API 侦察。

### J. 校准夹具的方向性 enrichment（F1 的必然副作用）

F1 之后 `test_calibration` 的 tripwire 多出 18 条 `footprint differs`，全部是
**candidate 侧读了 `Footprint`（封装文档 uuid）而 golden 侧读了 `Supplier Footprint`
（`0402`/`SOP-16` 语义串）**。修法：`candidate_from_netlist` 改为**语义 footprint 优先**
（`Supplier Footprint` → `Footprint` 兜底），与 golden 侧对齐。18 条 → 1 条。

剩 1 条 `U3: lcsc differs; golden='C2907329' candidate=''` **不是 bug**：它是 F1 引入的
**方向性 enrichment** —— golden 侧从 DEVICE META 拿到了 `C2907329`，而网表导出只反映
**实例属性**、没有 join，所以 candidate 为空。tripwire 的 enrichment 豁免因此改为
**只豁免元数据字段（lcsc/manufacturer/mpn/datasheet）的"golden 有、candidate 空"**；
`value`/`footprint` 的单边差异仍是真 bug。

### K. 测试增量

- Python **275 passed**（F1 前 256）。新增：`tests/test_verify.py`(9)、
  `tests/test_compare_identity.py`(8)、`test_candidate_draw.py` 三个集成测试
  （fail-fast 不画线 / 读回不可用仍继续 / 网表复用）。
- connector **135 passed**，`tsc --noEmit` 干净。
- `.eext` 独立复验：`zipfile.testzip()` → 无损坏，manifest `0.3.8`，
  `dist/index.js` 73589 bytes。

### L. 真机执行清单（待岳翔宇）

1. 侧载 `boardwise-connector-0.3.8.eext`，**重启编辑器**（唯一可靠恢复路径），
   `sys.probe` 复探一次；
2. **手动删掉本轮验证页**（我们无删除能力，设计如此）；
3. 问过岳翔宇后再建新页 → `boardwise draw`；
4. 三闸门：`draw` 自报 placement check（drifted / unmappable）+ compare 逐 pin 0 差异
   （首选网表路径）+ 岳翔宇读 `export.render` 图判可读。

> **F2 首次真机运行时最该盯的一件事**：`verify.placements` 那行的
> "N parts, M drifted, 0 unmappable"。若 `M > 0`，说明库确实重画了符号 ——
> 此时**先看 `R24/R27/U3` 是否还在 unmappable 里**（F1 的关键字修复是否生效），
> 再看 `USB1` 是否 `drifted`（这正是 round-4 的第二个缝）。

---

## 修订（第 5 轮：收官轮，2026-09-15，Kimi 整理岳翔宇裁决）

> 执行者：DeepSeek。前置事实：上一轮 draw 已达成 **net 0 / pin 0 差异**（Kimi 独立抽查
> USB1 全引脚网归属，正确）；闸门 3 岳翔宇已判"**摆放接线没啥问题**"（可读 ✅）。
> 剩 25 条 component 行，岳翔宇裁决：**全部真修，不豁免**。

### G. 岳翔宇裁决记录（2026-09-15）

1. **R24/R27**：放置件 `TCH35P5K10JE` 封装错——黄金是 0402，它不是。**必须换成真 0402 的
   5.1K**（用 F 轮的 `lib_Footprint.get` 反查验证放置后的真实封装名，报告里写出来）。
2. **U3**：黄金的 `1kΩ` 是岳翔宇当年的人为错误（他本人确认）；正确值 **2.2kΩ 0805**。
   库件 `FRC0805J471 TS`（470Ω）也不对，弃用。
3. **黄金更正机制**：夹具 `ch340_golden.epro2` **一字不动**（它是证据）；新增
   `tests/fixtures/ch340_golden.overrides.json` 旁车文件，compare 加载时在报告里带
   provenance（"U3 value: 黄金 1kΩ → 2.2kΩ，岳翔宇 2026-09-15 更正"）。结构自定，
   但报告必须可读、可审计。
4. **25 条真修令**：`docs/component-diff-inventory.md` 的 Group A/B 全修——
   放置后 `modify(Value=…)` 写真值（8 条）；`lib_Footprint.get(uuid)` 反查封装名对齐（20 条，
   该能力同时就是 R24/R27 的验证仪器）。

### H. 收官判据（三闸门终版）

1. compare **字面 0 差异**（overrides 应用后；override 命中要在报告里显式列出）；
2. lint 0 违例（既有）；
3. 可读 ✅（2026-09-15 岳翔宇已签）。

版本 → 0.3.17。完成后写实现记录，Kimi 独立复验后盖 006b 验收戳。

### I. G.4 机制变更批准（2026-09-15，Kimi 批，岳翔宇可否决）

DeepSeek 真机测量推翻 G.4 原指定机制，证据两条：

1. 网表导出的封装 uuid 是**工程内局部**的，`lib_Footprint.get` 加不加 libraryUuid 都抛错；
   只有**库**封装 uuid 可查。
2. 两套命名是**不同词汇表**，不是同一封装的两种写法：黄金 `0603` vs 库 `C0603`；
   `插件,P=2.54mm` vs `HDR-TH_3P-P2.54-V-M_PZ254V-11-03P`；`SMD` vs
   `USB-C-SMD_TYPE-C-6PIN-2MD-073`。

**批准的替代机制**：

- 写动作泛化为 `sch.set_component_attribute`，放置后同时写真 `Value` 与
  `Supplier Footprint` 两个属性——两侧网表导出比的是同一字段，差异才能归零。
- 封装身份校验走**库链路**：place_component 返回的 device uuid →
  `lib.device.get().association.footprint` → `lib.footprint.get()` 名字，按
  `expect_footprint` 校验，不符即报错；解析结果写进报告。
- 报告必须**如实并列两套命名**（黄金人读标签 / 库部件全名），不许只报一边。

**外部佐证**：easyeda-agent 的成熟选型库 `standard-parts.json`（143 件）存的就是
**库词汇表**封装名（`R0402`、`C0603`、`SOP-16_L10.0-W3.9-P1.27-LS6.0-BL`）+
库级 `deviceUuid`，从不在人读标签与库名之间做对齐。我们的测量结论与其一致：
**库名是唯一的封装身份词汇表**。这一点同时写进 008 的选型管线设计要求
（curated 件库存 deviceUuid + 库封装名 + LCSC C 号，实测放置验证后入库）。

## 修订（第 6 轮：0.3.18 终跑复盘 —— 两个缺陷，Kimi 实测定位，2026-09-15）

0.3.18 终跑（151 动作，2 失败）：net 0 / pin 0 保持，但 25 条 component 差异原样。
Kimi 用 daemon 审计日志 + 单件闭环探针（C1）定位到**两个独立缺陷**，全部有真机证据：

### J.1（connector，`schSetComponentAttribute`）：`modify` 的 `otherProperty` 是**整表替换**，不是合并

真机实测序列（C1, primitiveId=7999ea7014c75f30）：

1. 终跑写入后读 `sch.geometry` state：`OtherProperty = {"Supplier Footprint": "0603", "Value": "", …}`
   —— footprint 写进去了，Value 是空的；
2. Kimi 探针单写 `Value=100nF` → 重读：`Value="100nF"` 但 **`Supplier Footprint` 被抹成 `""`**。

结论：每次 `modify(primitiveId, {otherProperty: {key: value}})` 调用**整体替换** OtherProperty
映射，draw 的逐键写入（先 Value 后 Supplier Footprint）导致只有**最后那键**存活。
这解释了 8 条 Value 差异：它们被同组件的 footprint 写抹掉了。

**修复要求**：改为**一次 modify 调用写全量键**（动作参数从单 key/value 改为接受映射，
或先读回现有 OtherProperty 合并后整体写回）。**并且动作必须带写后读回**（写后读
OtherProperty 实际内容返回，不得只信 modify 返回值）——本次若有读回，缺陷当场暴露。
`applied` 字段的定义也要改成"读回值 == 目标值"，不是"modify 返回非空"。

### J.2（engine，`draw.py:1016-1019`）：库链路解析名**覆盖**了 diff 操作数

```python
for designator, name in result.footprint_names.items():
    component = candidate.components.get(designator)
    if component is not None:
        component.footprint = name   # ← 库名 'C0603' 覆盖网表字段，差异永不为零
```

§I 批准的机制是"写标签 → 两侧比同一字段；库链路只做 `expect_footprint` **独立校验**"。
实现却把库名**替换**进 compare 的候选侧——即使写入的标签被导出正确读出，差异也
必然存在（两套词汇表之差）。这是构造性失配，不是数据问题。

**修复要求**：diff 的 footprint 操作数保持网表导出的 `Supplier Footprint`（即写入的标签字段）；
`footprint_names` 只用于 (a) `expect_footprint` 校验（保留）、(b) 报告并列两套命名（§I 要求）。
若修复后网表导出**仍读不到**写入的 OtherProperty 字段（导出路径可能不经过它），
如实测量上报，不许默默改回 uuid 回退。

### J.3（已更正，2026-09-15 Kimi 订正）：`sch.netlist` 导出**没有**流程外归空问题

原记录"流程外返回 0 组件"是 **Kimi 探针的解析错误**：动作的返回载荷是
`{type, source, size, text}`，组件在 `json.loads(text).components` 里，不在结果顶层。
更正后同一时刻实测：导出 44934 字符、17 组件，一切正常。**bridge.md §10 第 9 条若按
"流程外读数不是证据"写了导出归空，需要回改为只保留 DeepSeek 实测的真现象**
（编辑器异步重算连通性导致的**陈旧**读数——那是另一回事，已由 `_settled_netlist` 解决）。

### J.4 验收（第 6 轮）

- 版本 → **0.3.19**；daemon 动作表若变，**由 Kimi 重启 daemon**（本次 0.3.18 首跑
  就是 daemon 未重启动作表导致的 20 连 UNKNOWN_ACTION——同一坑第三次，写进 implementation-log）。
- 修复后终跑判据不变：compare **字面 0 差异**（overrides 命中显式列出）、lint 0、可读（已签）。
- Kimi 独立复验项新增：写完后用 geometry 读回**每个组件的 OtherProperty 全表**，
  确认 Value 与 Supplier Footprint **同时**存活（防 J.1 回归）；测试里补
  "两次连续 set_component_attribute 不同键互不抹除"的用例。

---

## 验收戳（006b 正式收官，2026-09-15，Kimi）

三闸门全过，**独立复验**（非采信报告）：

| 闸门 | 判据 | 复验方式与结果 |
|---|---|---|
| 1 compare | 字面 0 差异 | DeepSeek 终跑 exit=0（`no differences — designs match`，163 动作/1 已知失败）；Kimi 真机抽查：`U1.16→VCC`（R5 拆线修复实锤）、USB1 全引脚映射（A1B12/B1A12→GND、A4B9/B4A9→+5V、A6/B6→D+、A7/B7→D-、A8/B8/13/14 NC）、派生网成员逐脚一致（黄金 NET5={R24.1,USB1.CC2}=候选 $27N30，NET6 同理）、C1/U3/R24/R27 的 Value 与 Supplier Footprint **双键同时存活**于导出 props（J.1 防回归实测通过） |
| 2 lint | 0 违例 | Kimi 自跑 `boardwise lint --from golden`：`layout lint: 0 violations` |
| 3 可读 | 岳翔宇签 | 2026-09-15 已签"摆放接线没啥问题" |

测试计数 Kimi 亲自复跑：**Python 291 / connector 142 / tsc 干净**（与报告一致）；
0.3.19 包 testzip + md5 双验通过。

本轮关键沉淀：R5 走线规则（T 点拆线，吸附后再拆一次）、`_settled_netlist`
（异步重算 → 连续两次读数一致才作判据）、`otherProperty` 整表替换（宿主行为）。
**006b 验收通过。** 下一任务：006c。
