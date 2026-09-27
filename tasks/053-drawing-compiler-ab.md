# 053 · 画法编译器 阶段 A+B：最小合同 + 分压/RC/LDO 离线语义编译

> 状态：**已批准方向的任务书**（xianyuyijinban 2026-09-27 拍板，052 终稿 §8 的阶段 A/B 落地）。
> 052（`tasks/052-schematic-drawing-direction.md`）是方向准绳，本文只把它变成合同与验收，不再讨论方向。
> 阶段 A = 最小合同（两份 Spec + SymbolProfile + 独立检查器 + 参考图/预期连接 + 审查三收口）；
> 阶段 B = 三种画法语法的离线编译（文字避让/有限候选/SVG 预览/失败四分类）。
> 真机不碰——阶段 C（053 后续任务书）才接编辑器。

## 一、审查三收口（052 §2，阶段 A 组成部分）

### 2.1 MPN 冲突修复双向化 —— 已由 agent-60 先行（本任务书不再覆盖）

`rules/params.py` finding 只发现矛盾、给双向候选；`suggested_after` 置空；
plan 生成器拒绝默认方向，操作者显式指定；apply 验收维持"回读==计划值"。

### 2.2 设计意图持久化 + 完成状态（本批落地，设计如下为定稿）

**问题**（052 §2.2 实证）：`_write_architecture`（cli.py:2232）覆盖写 architecture.md，
已填 `targetVoltage: 3.3V` 重生成后回到 `TODO`；`mayClaimPassed`（cli.py:2857）只查未审器件。

**方案：骨架与意图分文件，稳定 ID 关联，stale 标记不静默覆盖。**

- `architecture.md`：保持 044 纯生成确定性契约一字不动，文首加横幅
  「自动生成，手填无效——设计意图请填 `design-intent.md`」。
- **`design-intent.md`**（与 architecture.md 同目录，新文件）：
  - 槽位与骨架同构，每个槽位带稳定 ID：`<projectUuid>/<boardUuid>/<sectionKey>/<slotKey>`；
  - 首次生成：不存在则创建全 TODO 模板；**已存在则一字不改**（生成器对它只读）；
  - 值格式：自由文本 + 来源标注（`engineer@2026-09-27` / `ai-proposal@…` / `ai-confirmed@…`）；
  - checkup 报告的 architecture 节 = 骨架 ⊕ 意图**合并视图**（已填值进报告，TODO 仍 TODO）；
  - 图纸变化 → 槽位关联对象签名（电源树节点集 / 链路器件序列，由 044 生成器顺手产出）
    与意图文件记录不符时，该槽在合并视图标 **`stale: 图纸已变，此槽待复核`**——
    不静默删、不覆盖、不阻断，只显式标记。
- **`completion` 节**（report.json 新增，schema `boardwise.checkup/4` → `/5`，只加字段）：
  `scope`（规则数/板数/页数）、`errors`、`unreviewedParts`、`warningsPendingTriage`、
  `architectureSlots{total,filled,stale}`、`openTodos`、`sourceVersions{ruleset,rulebody}`、
  `verdict` 三态——`complete`（errors=0 ∧ 未审=0 ∧ stale=0 ∧ 待分诊=0）/
  `complete-with-open-items`（errors=0 但有开放项）/ `incomplete`（errors>0 ∨ 未审>0）。
- `mayClaimPassed` **保留不改名**（下游与朋友在用），docstring + 文档注明窄义；
  完整结论以 `completion.verdict` 为准。
- 044 确定性契约修订表述：骨架对模型确定；合并视图对（模型 + 意图文件）确定。

### 2.3 口径修正（本批落地）

- `outputs/017_generalization.md:22`「泛化成立」→「**回归证据成立**：15 板的缺陷已参与
  规则迭代（046/048），对新样本的泛化须由未见板验证」。
- 017 任务书 §九 增补评测集角色分家：现 15 板 = **regression**（继续当红线）；
  新板 = **unseen-validation**（进仓即冻结，不参与规则调参；含干净板与不同问题类型）。
- 指标防误读段（进 README「评测」节 + 017 任务书）：112/183 是 (规则×板) 至少一个
  UNKNOWN 的比例不是"61% 没审到"；79/91 是文本/target 定位线索不是编辑器高亮成功率；
  12/14 是任务书登记口径不是前瞻实测；59/59 是回归不是泛化证明。

## 二、阶段 A：三份数据 + SymbolProfile + 独立检查器

### CircuitSpec（dataclass + JSON schema，新 `core/circuitspec.py`）

- `parts: [{id, mpn?, lcsc?, symbolRef, value, params}]`——`id` 是稳定逻辑 ID（非位号、
  非宿主 primitiveId；落图时才分配位号）；
- `nets: [{id, class: power|gnd|signal|other, members: ["<partId>.<pin>"]}]`——
  pairwise `connections` 只作输入糖，规范化为一网多成员，记录页/工程作用域；
- `nc: ["<partId>.<pin>"]` 显式；`openInterfaces: [{net, direction, role}]`；
- `operatingConditions: {…}` 工作条件（电压/电流/频率，自由键值但 schema 留位）；
- `provenance`：**每条事实**三态 `verified_recipe | engineer_confirmed | ai_asserted`
  （052 §4）；ai_asserted 的产物只能是明确标注的草稿态；
- 「没给连接」≠ NC；NC 必须显式。

### PresentationSpec（同文件或 `core/presentationspec.py`）

- `modules: [{id, parts[], role}]`、`mainPaths[]`、`feedbackPaths[]`、
  `portRoles{net → source|load|input|output|feedback}`；
- `grammarRef`（voltage-divider / rc-lowpass / ldo）；
- `directWiringObligations[]`（必须直连不用标签的局部拓扑）；
- `labelPolicy`：`local=wire | crossModule=label | highFanout=label`；
- `sidePreferences`（input:left / output:right / power:top / gnd:bottom，默认可被锁定覆盖）；
- `userLocks: [{partId, x, y, rotation}]`——工程师锁定的合法入口；
- 模型入口**不接受**原始坐标/wire points/connector 动作（schema 直接拒绝，不清洗）。

### LayoutPlan（`core/layoutplan.py`）

- 每器件：实际符号版本/几何哈希、姿态（旋转/镜像合法性来自 SymbolProfile）、位置；
- 线段、junction、标签、电源符号、**每段文字的 bbox**；
- 源 CircuitSpec/PresentationSpec 哈希 + 验收证据 + 目标快照；
- 预览绑定具体计划；实质版式改变 → 旧预览失效重新检查。

### SymbolProfile（`core/symbolprofile.py`）

- **离线来源**：解析器已读的 SYMBOL 文档（.epro2 夹具/库导出），不进编辑器；
- 内容：body bbox、pin tip 坐标+朝向、允许姿态集（0/90/180/270 ± 镜像合法性）、
  位号/值默认位置与文字 bbox、引脚→电气角色映射（facts 供电脚/引脚名推断
  VIN/VOUT/GND/IN/OUT）；
- 库符号不合适 → 选引脚映射已核实的兼容符号**或报告能力边界**；**禁止换脚号迁就版式**。

### 独立检查器（`engines/readability.py`，机器执行可读性合同）

```
check(layoutPlan, circuitSpec, presentationSpec, profiles)
  → {hardViolations[], grammarFindings[], softMetrics{原始值+扣分原因}}
```

- **独立**：不消费生成器内部状态，只消费 LayoutPlan + 两份 Spec + profiles——
  短路/错脚/NC 被接/压字负例必须能被它独立检出（052 §8）；
- 硬约束逐条：推导网表==CircuitSpec（成员分区+命名语义，不比自动网名字符串）/
  线端接实际 pin tip / 无意外 junction / 不穿器件 body / 文字 bbox 不相交 /
  不越页·禁区 / 遵守用户锁定 / NC 未连 / 必接脚已连；
- 画法约束：语法 checker 执行（抽头可见/支路归属/电容归侧）；
- 软指标无总分：交叉/折点/总线长/对齐/间距/留白/位移，保留原始值与原因。

## 三、阶段 B：三种画法语法（`engines/grammar/`）

每种语法 = 角色表 + 相对关系 + 必须可见拓扑 + 允许变体；坐标由真实符号、文字和空间算出。

| 语法 | 角色 | 相对关系 | 必须可见 | 允许变体 |
|---|---|---|---|---|
| voltage-divider | upper_arm / lower_arm / tap / in / gnd | 两电阻竖排同轴，upper 上 lower 下，tap 中点水平引出 | in→upper→tap→lower→gnd 全链直连；抽头直接可见（stub+标签/端口） | 横排镜像、多抽头、并联支路 |
| rc-lowpass | series / shunt / in / out / gnd | in→R→out 主干水平；C 从 out 节点向下支路到地，**视觉归属 out 节点**（贴近不跨模块） | 主干直连；支路直连 | 多 C 并联、R 换磁珠（同构） |
| ldo | core / in_caps[] / out_caps[] / in / out / gnd | in 左 core 中 out 右；电容各归所属节点就近；地表达统一（同符号或同标签不混用） | in→core→out 主干；各电容与所属节点直连 | EN 脚、NR 电容、可调版（组合 voltage-divider） |

## 四、离线编译管线（阶段 B 实现形状，`engines/drawcompiler.py`）

```
compile(circuitSpec, presentationSpec, profiles, budget) → candidates[LayoutPlan]
语义布局：角色→相对位置约束（不是坐标）→ 有限姿态 × 网格阶梯 × 稳定 tie-break
几何布局：真实 bbox 占位；文字 bbox 参与避障（不靠字符数估算——校准 layout.py:1055 缺口）
布线：正交、主干优先、最少交叉；layout.py:455 BFS 升级引脚逃逸/通道/文字障碍
候选 3–8 个 → 硬门禁 → 分层排序（合法性→电路表达→可读性→紧凑，无跨层抵消）
```

- **SVG 离线预览**：纯 Python 生成（无新依赖），xianyuyijinban不开编辑器即可看布局质量；
- 失败报告四分类：`facts-missing / circuit-invalid / layout-unsat / presentation-poor`，
  各带可选动作（扩大区域/放宽锁定/换兼容符号）；有限搜索失败只说预算内未找到，不说无解。

## 五、12 离线场景（用例从 A 定义，B 持续执行）

| # | 场景 | 预期 |
|---|---|---|
| 1 | 分压标准（10k/10k 常规符号） | 竖排同轴、抽头可见、零硬违规 |
| 2 | 分压换符号（轴向/贴片、引脚朝向不同） | 同语法成立，坐标不同关系不变 |
| 3 | 分压长文字（位号 R123456、值 1.00Meg） | 文字 bbox 参与避让，不压字 |
| 4 | 分压多抽头 + 并联支路 | 变体成立，每抽头可见 |
| 5 | RC 标准 | 主干直连、支路归属 out |
| 6 | RC 换符号朝向 | 同 2 |
| 7 | RC 多 C 并联 + 长值文字 | 支路群归属清晰不压字 |
| 8 | LDO 标准（AMS1117 + in/out cap） | 电容各归各侧、地表达统一 |
| 9 | LDO 带 EN / NR 支路 | 变体成立 |
| 10 | 狭窄区域 | 报告空间不足+可选动作，**不许硬挤压字** |
| 11 | 故意错：CircuitSpec 短路/错脚/NC 被接 | 独立检查器检出，编译器拒绝 |
| 12 | 故意错：userLock 与语法冲突 | 报告冲突+可选动作，不静默忽略锁定 |

纪律（052 §8 逐字）：固定正确 CircuitSpec 手写 JSON 测编译器（自然语言→Spec 另测，
不混淆电气推理与布局错误）；**参考图坐标绝不喂给生成器**；预期网络独立指定；
合格输出硬违规为零，成功率分母含拒绝与超时（防全拒绝拿零缺陷）。

## 六、验收（阶段 B 出口）

- 12 场景全过：换符号/长文字/加支路成立，**无逐例调坐标**（code review 级检查：
  语法表内不得出现场景专用常量）；
- 负例（11/12）全部被独立检查器检出；
- 失败报告四分类 + 可选动作各至少一个实证；
- 审查三收口落地：2.1（agent-60）✔ / 2.2（§一.2.2 全件）/ 2.3（§一.2.3 全件）；
- pytest 全绿 + 变异 CAUGHT；eval holdout 59/59 双 1.00 不破；
- 暂定产品目标（校准用，非本批验收线）：支持范围内首次可接受率 ≥90%、
  工程师盲读中位 ≥4/5（阶段 E 才正式测，052 §8）。

## 七、守卫

- 全程离线；真机/connector/reviewsets 标注不碰；
- 标签策略硬编码：局部直连义务优先，跨模块/高扇出才许标签；
- 无全局铁律（不强制左进右出/不禁止交叉/地不一定朝下——052 §6）；
- 分层排序无跨层抵消；软指标无总分；
- dsh 工具面同步检查（045 纪律）；SKILL/docs/README 同步；
- 历史出图（outputs/010c_*）保持原样，只作教训引用。
