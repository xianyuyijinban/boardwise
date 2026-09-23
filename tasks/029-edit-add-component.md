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
