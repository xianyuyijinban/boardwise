# 029 — M3 第 2 片：`add-component`（按已验证配方补一颗缺失器件）

> 016（改值）已于 2026-09-22 闭环（15b3da2，场景 6 saved_verified PASS）。本片是岳扩展顺序的第 2 步：
> **根据已验证配方补一颗缺失的电容或电阻**。`changeplan.py:63 _LATER_KINDS` 里它叫 `add-component`，
> 目前走"后续片所有"的拒绝文案；本片让它可执行。
> 主驱动 finding：`decap-required-caps`（IC 缺去耦电容）——这是原理图审查里"补器件"最高频的真实场景。

## 一、与 016 的代差（为什么这是新的一片，不是 016 加参数）

016 只改一个属性字符串；本片要**创建图元**：放一个新器件 + 连接它 + 分配位号。
范围差异、幂等语义、冲突形态全部升级：

| 维度 | 016（component-value） | 029（add-component） |
|---|---|---|
| 写入 | 1 次 `set_component_attribute` | `place_component` + 连接（wire/label）+ 可能多次 |
| 幂等 | 重写同值天然幂等 | **重复 apply 绝不重复创建**——要先探测"这颗是否已补过" |
| 前置 | 值仍是 before | 锚点 IC 在位 + 位号池没变 + 落点仍无占据 + 配方仍有效 |
| 范围差异 | 语义差异 = 值 | 差异必须**恰好**是 +1 器件 +k 连接，多一个都算事故 |
| 冲突 | 值被人工改 | 落点被占、位号被占、人工已补了一颗 |

## 二、架构决策（主代理定，执行者照做；要改先停下来报）

### 1. finding 侧：`decap-required-caps` 补结构化 target

现在它只产 Outcome/文本。补 `FindingTarget`（`rules/base.py:22` 已有壳，016 在 params.py 用过）：

- `component_ref` = 锚点 IC 位号；`pin_refs` = 需去耦的供电脚；`net_refs` = 供电网名；
- `suggested_after` = 缺失电容的**配方串**（来自 facts 架 `required_caps`，如 `100nF/16V`）；
- 配方**只在 facts 架有具体条目时才进 target**——架上是 UNKNOWN 就不给 target，
  plan 端拒绝得有理有据（"先录入事实"），不许猜料号。

### 2. ChangePlan 扩展（`core/changeplan.py`）

- `SUPPORTED_KINDS` 加 `add-component`（从 `_LATER_KINDS` 摘出，拒绝文案同步减一）。
- change 负载：`{kind, part: {lcsc, value, footprint}, connections: [{pin, net}], recipe_source: "facts:<lcsc>"}`。
  `lcsc` 必须来自 facts 架或用户 `--lcsc Cxxxxx` 显式给——**没有已验证配方就拒绝建 plan**（岳原话"已验证配方"）。
- target 负载：锚点 IC（designator + 解析时点不绑 primitiveId——016 §二.3 的时点教训沿用）+
  拟分配位号（见下）+ 拟落点坐标 + 连接方式声明（wire 还是 label，见 §二.4）。
- preconditions：锚点在页上、落点无占据、拟分配位号仍空闲、配方条目仍在架上。

### 3. 位号由代码分配（路线书 M3 原话）

扫页面前缀（C/R）取**最小空闲号**，写进 plan；apply 前复查仍空闲（人可能刚手放了一个）。
分配结果落 plan，重复 preview/apply 看到的是同一个号。

### 4. 落点与连接（M2 诚实规则适用）

- **落点**：由锚点供电脚几何（`engines/draw.py` 的 pin_positions/census 可复用）+ 固定栅格偏移；
  候选位被占 → 确定性阶梯找下一位（上下左右 1–2 栅格，顺序固定写进任务书）；
  **阶梯耗尽 → 拒绝并报告冲突，绝不放原点**。
- **连接**：目标网在落点 N mil 内有线段 → 短 wire；否则该页该网**已有 net label 用法** → 同名 label；
  两者都不成立 → 拒绝并说明。选哪种必须写进 plan 并在差异报告里对上。**禁止全脚标签假装连通**
  （岳 M2 红线），也禁止静默二选一。
- 真实器件放法：优先复用 `engines/draw.py` 五态写入路径（persistence/readback-after-unknown/
  geometry_fingerprint/census 全是现成的），别新造一套。

### 5. 幂等（岳硬要求："重复执行不会重复创建器件或导线"）

apply 前先探测"这颗是否已补"：锚点供电网上已存在满足配方的电容（值匹配 + 连接匹配）→
报 `already-applied`，零写入。探测逻辑与 `decap-required-caps` 的判定**同一份代码**（规则重跑天然一致），
不许写两套相似但不相同的判断。

### 6. 四个保护 + 结果态

016 §四 的映射原样继承（执行前重读 / 只动目标 / 回读不轻信返回值 / 超时先读回不盲重试）。
结果态沿用 draw.py 五态：`placed / placed_unverified / saved_unverified / saved_verified / unknown`。

## 三、批次

### 029-a（离线核心）

1. `decap-required-caps` 补 target（§二.1）；`changeplan.py` 支持 `add-component` 构建/校验/序列化；
2. `boardwise edit plan` 支持从 report.json 的 decap finding 建 plan（含落点阶梯、位号分配——这两步
   需要 geometry，离线用 fake bridge 喂）；
3. apply 编排器 + fake bridge 离线 10 用例：建 plan、锚点失效、落点阶梯耗尽→拒绝、无配方→拒绝、
   位号被占、幂等 already-applied、中途断连→unknown→读回、范围差异多一处→事故报告、
   重审 resolved、重审 still-present 诚实报；
4. CLI 文案与 report.json schema 同步；三线全绿；变异 ≥2（自选靶：幂等探测漏判 / 阶梯兜底放原点）。

### 029-b（真机，另派）

bw_scratch/test 页给一颗测试 IC 补去耦电容：成功、人工先补→already-applied、重复 apply、
落点被占→阶梯/拒绝、断连恢复、保存+mtime、（岳在场时）编辑器重开验证 saved_verified。
范围外几何零变化（fingerprint + census 对照）。

## 四、验收（两片合并判）

- 离线 10 用例 + 真机 6 形态全过；三线全绿；
- 重复 apply 零新增（岳红线）；范围差异恰好 +1+k；
- 重审后 `decap-required-caps` 对该 IC 从 VIOLATION 变 OK（或明说为什么仍 VIOLATION）；
- 所有拒绝都能说出缺什么事实/什么冲突，不裸奔。

## 五、守卫

- 只碰 test/test2/bw_scratch；`--project/--instance` 显式寻址；禁地只读。
- pytest 必带 `--basetemp=.tmp_pt_home`；变异 cp+sha256；append 后 grep -c；PROGRESS 由主代理更。
- 016 §七 的两条诚实边界（列在 016 任务书）本片同样适用，交卷要复述哪些仍然成立。

## 六、交卷记录

（子代理交文本，主代理 append 并复验。）

### 029-a · 交卷（2026-09-23，子代理 agent-43）

- **① decap 补 target + 判定共享**：两条 VIOLATION 行带 FindingTarget（锚点 IC / 供电脚 / 网 / facts 配方串）；
  架上是 UNKNOWN 就不给 target。**§二.5 的"同一份代码"落成两个模块级函数**（`cap_candidates_on` +
  `decide_required_cap`），规则与 apply 的幂等探测都调它们；`outcomes()` 的三元组行崩点已修。
- **② changeplan 支持 add-component**：新增 `PlanPart/PlanConnection` 与 target 的 anchor/assignedDesignator/x/y/
  connection/connectionDetail；校验 lcsc/value/≥2 连接/connection∈{wire,label}/x,y 为数字；**`to_jsonable` 按 kind 分支**，
  `component-value` 的 JSON 一字未变（016 round-trip 测试仍绿）。`_LATER_KINDS` 摘出 add-component。
- **③ `edit plan --report`**：从 report.json 的 decap finding + 活页面建 plan；阶梯 `LANDING_GRID=5`（= layout.GRID，
  测试断言）固定顺序 9 位，**耗尽抛 LadderExhausted（绝不落原点）**；位号取最小空闲；连接先 wire（落点 100 单位内线段）
  再 label（该页该网已有 label 用法），都不成立即拒绝。`--project/--instance` 全命令贯通。
- **④ apply 编排器 + 11 离线用例**（任务书 10 个 + 1 个额外）：幂等探测走**活工程 export→离线 parse** 后调规则的两个函数；
  范围差异必须恰好 +1；连接以**工程自身网表**回执判定；结果态沿用 016/draw 与 `persistence` 三档。
- 变异 2/2 CAUGHT（M1 幂等漏判 / M2 阶梯兜底放原点），各只打中 1 条目标用例；还原
  `engines/addcomponent.py 6a20100f…`（cp + cmp 一致）。
- 三线：pytest **1418 passed**（1407+11）；connector/tsc 未跑（本批未动 connector）。
- **偏离（主代理裁决见下）**：`addcomponent.py` 因层规则落在 `engines/`；`REPAIRABLE_RULES` 增 `decap-required-caps`，
  016 相应断言/两个 fake 的 `**hint` 已同步更新（接口增长，非放水）。
- **未做**：`edit preview` 仍不认 add-component；report.json 的 target 是 `asdict` 顺带同步（未加显式 schema 测试/文档段）；
  GND 端 pin 硬编码 "2"；wire 分支按"最近线段"而非按网判别。真机一律未碰。

### 主代理复验与裁决（2026-09-23）

- 亲手抽核：三个 sha256 与交卷一致（addcomponent `6a20100f…`、changeplan `115fd632…`、decap `0b6e5b2a…`）；
  `git status` 清单一致；`pytest test_029a_addcomponent.py + test_layer_rules.py` **20 passed**；全量复跑见本节后补。
- **裁决 1（接受偏离）**：`engines/addcomponent.py` 落点是层规则强制（core 不许 import rules），不算偏离是合规。
- **裁决 2（接受）**：`REPAIRABLE_RULES` 增项——表即契约的意图保住（016 断言按新事实更新）。
- **裁决 3（029-b 前必须盯）**：wire 分支"最近线段不按网判别"是本批最弱一环——放行理由：连接是否成立
  最终由**工程自身网表**回读判定，错网会 honest fail 而不是假成功；029-b 真机用例必须包含
  "落点附近有异网线段的页面"，验证 wire 不错连、错连时报告而非装成功。GND pin "2" 硬编码对 2 脚电容成立，
  网表回读兜底，接受为本片边界。
- 遗留入账：`edit preview` 认 add-component、report.json 显式 schema 测试，列入 029-b 或后续小批。

### 029-b · 交卷（2026-09-23，子代理 agent-43）

- **布景**：test 建 bw_scratch（9733d4eb…，编辑器显示 P5）→ 放 `C6186` AMS1117-3.3 为 U9；
  编辑器**自动命名** U9 pin2 所在网为 `NET4`（无需手动连线）；再放一段 NET4 走线给落点候选项。
  checkup → report.json 直接给出带 **structured target** 的 decap finding（U9 pin2 / NET4 / 22uF）✔。
- **case a（成功路径）= 诚实失败**：plan 建出（落点 (300,295) 阶梯第 1 级、连接 `wire → NET4 线段 5 单位`）；
  apply 落件 ✔、范围恰好 **+1** ✔、网表回读 `1→NET4 ok / 2→GND MISSING` → `connection_not_established`、
  **未保存**（exit 2）。⇒ 放行弱点"最近线段不按网判别"在真机上**没有表现为错连**，而表现为**只连一端**。
- **真机暴露并已修的三个问题（主代理已复验，见下）**：① wire 的 state 真形状是 `Line: [x1,y1,x2,y2,…]` + **`Net`**
  （原假设"不带网名"错了）⇒ 现在 `nearest_wire_point` **只认目标网线段，错连结构上不可能**，mock 加"异网更近也不选"断言；
  ② plan 把**锚点 IC 的脚号**当成新电容的脚号 ⇒ 解耦网被写成 GND（第一次 apply 的 `probe net 'GND'` 实证），已修；
  ③ `looks_like_capacitor(library=None)` 崩（`find_facts(None)`），已加无架分支；**遗留**：apply 未把 facts 架传给探测。
- **未跑**：b 人工先补 / c 重复 apply / d 阶梯占满 / f 断连恢复；e 异网线段页只有 mock 判据 + 结构锁死，真机未单做。
  按指示跳过编辑器重开验证（需岳在场）、`edit preview` 认 add-component、report.json 显式 schema 测试。
- **零残留**：两张 bw_scratch 页（含 U9/C1/C2）已 `doc.delete_page` 删除；`doc.list` 6 文档、active P1、
  geometry 1 器件 0 线、`sys.identity consistent` ✔。**未复位**：`front` 报 ok=false，前台未还给编辑器（如实记）。
- 三线：pytest **1418 passed**（修复后）；connector/tsc 未跑（未动 connector）。改动 4 个文件（addcomponent/cli/decap/测试）。

### 主代理复验与 029-c 派遣（2026-09-23）

- 抽核：工作区 4 文件与交卷一致；`nearest_wire_point(net=...)` 按网判别亲读在码（docstring 点名裁决 3）；
  证据 8 份齐（stage/case_a/cleanup + 2 plan + 3 apply + snapshot）。
- **case a 的诚实失败定调**：这是网表回读按设计工作（没连全就不保存），不是系统缺陷；
  但**成功路径还没通**——plan 只执行了 1→NET4 一条连接，GND 端寄托在"落点相连的 stub"上（到不了电容脚）。
- **029-c 派遣内容**：① 每条声明连接都必须显式执行——wire 不可达时 GND 等全局网走 **net label**（页面无 label
  先例时 GND 是通用例外，其他网仍拒绝）；② apply 把 facts 架传给幂等探测（029-b 遗留）；③ case a 跑到
  **真成功**（两端连通 + 网表 ok + 保存 + mtime + 重审 OK）；④ 补跑 b/c/d/f；⑤ 顺带收 029-a 遗留
  （`edit preview` 认 add-component、report.json 显式 schema 测试）。
