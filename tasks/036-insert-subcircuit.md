# 036 insert-subcircuit：插入 RC / 分压子电路（M3 第 4 片）

## 背景与入口裁决

M3 顺序第 4 刀（016 改值 ✅ → 029 补件 ✅ → 035 修脚 ✅ → **insert-subcircuit** → move-block）。

本片与前三片的根本差异，先写透：**没有驱动规则**。前三片是「规则发现 → target → plan」；
插 RC / 分压是 **AI 用自己的知识（含 WebSearch 查规格书）判断该插什么**——这正是岳定的产品分工：
AI 决定插什么，harness 保证插得对、可预览、可回读、可幂等。所以入口是 `edit plan` 的**第三个入口**：

| 入口 | 批次 | 驱动 |
|---|---|---|
| `--file` | 016 | 规则在快照上重跑 |
| `--report` | 029/035 | checkup 报告里的 finding + target |
| `--insert <template>` | **036** | **显式请求**：AI/用户点名模板、锚点、配方 |

`_LATER_KINDS` 里 `insert-subcircuit` 已挂号（`core/changeplan.py:85`），本片摘号转正。
**REPAIRABLE_RULES 不动**——没有规则映射进来，`RULE_FOR_KIND` 对 insert-subcircuit 无条目，
apply 末尾的"重审"语义因此不同（见工作项 4）。

## 模板 v1（两枚，刻意一删一不删）

### T1 `rc-lowpass`（串联插入，**含删除**）

场景：源 → 负载脚直连（运放输出→MCU ADC 一类），中间串 R、负载侧对 GND 并 C。
输入：锚点脚 `--pin <位号>.<脚号>`（插在哪个脚上由调用方选）、R/C 的值与 lcsc。
机制（四步，全是既有机器的复合）：
1. **断开**锚点脚 P 与其当前网 N：**035 disconnect 机制原样复用**——附着物必须画布实证
   （wire 端点恰在脚上），label 附着 / T 型 / 多于一个 / 找不到 → 拒绝并点名（035 裁决 1 沿用）。
2. **放 R**：R.1 wire 到 P（新节点 X = {P, R.1, C.1}），R.2 wire 回 N
   （029 `nearest_wire_point` + `wire_route` 强制正交，终点是 N 既有线段的顶点）。
3. **放 C**：C.1 wire 到 X（P 或 R.1 的坐标），C.2 到 GND——**029 `choose_connection` 原样复用**
   （wire → rail power-flag；label 机制**禁用**，本机 `place_netlabel` 不可用，SKILL 坑 9）。
4. 位号 ×2 走 029 的"位号最小空闲"池；前缀 R / C。

### T2 `divider`（抽头，**纯 create**）

场景：从网 N 抽一路分压：R1 上端接 N，R1/R2 中点 = 新节点 X（输出），R2 下端接 GND。
输入：锚点网 `--net <名>`、R1/R2 的值与 lcsc。
机制：**无删除**——R1.1 wire 到 N 既有线段，R1.2 与 R2.1 相接（相邻落点 + 一小段正交线），
R2.2 到 GND（同 T1 第 3 步）。

两枚模板覆盖 035 定案的两条范围核对路径（含删除 → 画布身份级 + 活网表；纯 create → 导出核对），
**判据一句话照旧：导出新鲜当且仅当本 run 无删除**（SKILL 坑 24）。

## 工作项

### 1. ChangePlan（`core/changeplan.py`）

- `SUPPORTED_KINDS` += `insert-subcircuit`；`_LATER_KINDS` 摘除该条（拒绝文案同步）。
- payload（字段名实现定，必须覆盖）：
  - `template`：`rc-lowpass` | `divider`；参数快照（锚点脚/网、各件 value+lcsc+footprint、位号）——
    人签 plan 时要能看懂将要发生什么。
  - `parts: list[PlanPart]`（**多件**，029 单件的扩列；旧 kind 的 JSON 一字不变，回归钉照旧）。
  - `connections: list[PlanConnection]`（每条 pin/net/kind/to，029 形状；kind 只许 `wire`/`power-flag`）。
  - `attachment: PlanAttachment | None`（T1 必有，035 形状；T2 必无）。
  - `before_net`（T1 的 N；T2 空）。
- `from_jsonable` 不变量（各配拒绝用例）：T1 ⇒ 恰好一件 attachment + before_net 非空；
  T2 ⇒ 无 attachment；每件 part 必须有 lcsc；每条 connection 必须有 kind 且在词表内；
  位号两两不同。**016/029/035 JSON 一字不变**（round-trip 回归钉）。

### 2. 离线 plan/preview（`cli.py` + 新 `engines/subcircuit.py`）

- `edit plan --insert rc-lowpass --pin U3.5 --r 1k --r-lcsc Cxxxxx --c 1n --c-lcsc Cyyyyy -o plan.json`
  （`--net` 换 `--pin` 即 T2；值与 lcsc **全部显式**，无默认值——029 红线：未验证配方不静默落件）。
- plan 构建要**看活页**（同 029 `--report` 的活页依赖）：脚坐标、N 的既有线段、位号池、落点。
- **落点组合阶梯**（本片最硬处）：两件器件相对几何由模板自带（如 R 横放距锚点 2 格、C 在 R 下 2 格），
  以锚点为原点逐格试（GRID=5 九宫，029 `LANDING_GRID` 沿用），**两件一起试**；全失败抛
  LadderExhausted，**绝不落原点**（029 红线）。落点合法性 = 不压既有图元（geometry bbox 干涉检查）。
- `edit preview`：列出将放的两件（位号/值/落点）、将删的附着物（T1）、将画的每条线
  （起点/终点/正交路径）、前置条件逐条核对结果；**永不写**。

### 3. apply 编排（`cli.py` 第四条 edit apply 流程）

四保护沿用家规，本片特化：
- **幂等探测先于 stale**（030 §③ 的教训，035 已用在脚上）：plan 位号确定——两件器件已在板上
  且 plan 的 postconditions 已满足 → `already_applied` 零写入。**判据 = plan 自己的 postconditions，
  不是规则重跑**（本片无规则，这是与 029/035 的判据差，写进代码注释）。
- stale（exit 4 零写入）：T1 = P 当前网 ≠ before_net，或附着物按 id 不在脚上；
  T2 = 锚点网段不在（按 plan 记录的顶点坐标核对）。
- 写序：T1 先删附着物，再放件画线；T2 纯放画。写调用逐条记 `write.calls`。
- 范围：T1 含删除 → **画布身份级**（消失的恰为授权附着物，`wiresVanished == [attachment.primitive_id]`，
  另记 wiresAppeared）+ 活网表；T2 纯 create → **导出核对**（`outside_scope_differences`，两侧同仪器）。
- 回读 = plan 的**显式 postconditions**（活网表成员断言 + 画布坐标断言），双证缺一
  exit 3 `verification_disagrees`；断连/超时 = unknown exit 3，读回不重试。
  活网表期望值（T1 例）：N 失 P 得 R.2；X = {P, R.1, C.1}（自动网双名按 035 同岛规则）；
  GND 得 C.2。**自动网名不是身份**（SKILL 坑 24）——比岛屿不比名。
- save + 状态分层沿用（无"关闭重开"只报 `saved_unverified`）。
- **新增 findings 不新增**：apply 后重跑全规则（活工程导出），findings 集合只许减不许增
  （基线 = plan 时快照），新增即 exit 2 报出新增行。

### 4. 测试与验收

- 离线（pytest）：两模板的 plan/preview/apply 编排（活工程 export→parse 实证幂等）、
  label 附着拒绝、歧义/压点落点阶梯耗尽拒绝、T1 无附着物拒绝、位号冲突、
  016/029/035 round-trip 回归。**测试用例与实现同步交付**，不许先实现后补。
- 变异 ≥2：幂等漏判方向 + 范围核对（误拦 / 幻影放行）方向。
- 真机（**只碰 test/test2**，`--project/--instance` 显式寻址；ROBOT 等禁地全程只读）：
  - T1：test 页现场造"两脚直连"形状（放两个既有库器件 + 一条线），插入后活网表三网段成员正确
    + 画布坐标回读 + 幂等重放 already_applied + stale exit 4 零写入 + 保存分层。
  - T2：同标准（无删除腿）。
  - 若模板器件 test 工程库没有，**停下来报主代理**，不许拿禁地工程器件凑数。
- 零残留：scratch 页全删、焦点复位、identity consistent。
- 证据 `outputs/036_*.txt`，交卷文本写 `outputs/036_summary.txt`。

### 5. 文档

- SKILL.md 动作说明区补 insert-subcircuit 一条（用法 + 两模板 + 无规则判据差），坑表踩新坑再加
  ——**归主代理**，子代理不碰 SKILL.md / PROGRESS.md / git。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 cp 备份 + sha256/cmp 还原（禁 `git checkout --`）；
三线（pytest / connector / tsc）全绿才交卷；connector 预期**零改动**——若发现必须动 connector，
停下来报主代理；不碰 git 与 PROGRESS。

## 交卷记录

（子代理交卷全文：`outputs/036_summary.txt`；真机原件：`outputs/036_live.txt`。）

### 子代理交卷浓缩（agent-43，2026-09-25）

- **交付**：`engines/subcircuit.py`（新——两模板、两件一起的九宫落点阶梯、计划自己的 postconditions
  判据、create 路径范围判据）；`core/changeplan.py`（insert-subcircuit 转正，payload 多件化：
  `PlanPart.designator/role/x/y/rotation`、`PlanConnection.designator/toPin`、`change.template/parts/
  baselineFindings`；**016/029/035 JSON 一字不变**，回归钉钉住）；`cli.py`（第三个入口
  `edit plan --insert`，preview insert 分支，第四条 apply 流程）；`tests/test_036_subcircuit.py`（63 条）。
- **真机（只碰 test 窗 `inst-015813234-aw2317s0`）**：
  - **T1 rc-lowpass：applied + saved ✔**——夹具 U3/U9（C47773）+ U3.5→U9.1 线（VOUT_U3）；apply
    删线 + 放 R1(1k,C7250) + C1(100nF,C14663) + 3 线 + GND 旗标 + save；幂等重放 already_applied 零写入；
    现场复核 X={U3.5,R1.1,C1.1} 同岛（`$61N2`）、R1.2 回 VOUT_U3 且 U9.1 仍在、C1.2 在 GND。
  - **T2 divider：applied + saved ✔**——夹具 U1/U2 + DIV_FEED；stale 演示（先删锚点网线）exit 4
    `anchor_moved` 零写入 ✔；apply 放 R1(27k,C22967)+R3(1k,C7250)+2 线+旗标+save；幂等 already_applied ✔。
  - 模板器件 test 工程库自带 0603 R/C，未动禁地；零残留（4 scratch 页全删、6 文档、焦点 P1、
    identity consistent；test2/ROBOT 未寻址）。
- **真机暴露已修三处**（均实证）：① 宿主上报线点重复结点，远端取"离锚点最远的点"（原取最后点=拐角，
  删线后什么都不剩）；② 宿主对撞工程全局的位号静默改名（要 R2 得 R3）⇒ 位号池取「页面 ∪ 工程导出」；
  ③ findings 签名把换措辞/自动网重编号当新增 ⇒ 签名改为 rule|severity|component|pins|命名网。
- **三线/变异**：pytest **1570**（+63）；connector 419 / tsc 干净（零改动）；变异 3/3 CAUGHT
  （幂等漏判 / 范围误拦 / 幻影放行三方向）。
- **遗留裁决**：029 位号池同样只看页面（同盲点）——主代理已批修，立案 036b 随下一批落。

### 主代理复验（2026-09-25）

- sha256 抽核 4 件全对：cli.py `2c30bbb3…`、changeplan.py `0b127246…`、subcircuit.py `b4210b6e…`、
  test_036_subcircuit.py `3f9c9520…`。
- 三线复跑：pytest **1570 passed** / connector **419 passed** / `tsc --noEmit` 干净。
- `git status` 仅 4 件预期改动（017 草稿未跟踪、不混入）；connector/daemon 零改动，仍 0.4.23。
- SKILL.md 动作说明区补 `--insert` 一条（两模板 + 无规则判据差），坑表补第 25 条（三条宿主习性）。
