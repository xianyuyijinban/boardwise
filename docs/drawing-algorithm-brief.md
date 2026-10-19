# 原理图自动绘制：困境、已试过的路子、可用接口

> 本文是给**外部算法推演**用的技术简报，不含任何企业内部信息。
> 项目：`boardwise`（开源，github.com/xianyuyijinban/boardwise），Python，给定电路网表自动生成**人类可读**的
> 原理图（器件摆放 + 布线），产出的是一页 SVG。
> 目标读者：一个了解 VLSI 布局/布线、约束求解、组合优化，但**不懂原理图审美**的 AI。
> 每一节末尾的读数都是实测的，不是估计。

---

## 0. 一句话概括困境

**「能连上」已经做到了；「人一眼认得出这是反激」没做到。**
根因不是缺启发式，而是三件事叠在一起：约束的量法与表示不匹配、布局与布线两阶段割裂、约束没有优先级层次。
下面把每一条都给出读数。

---

## 1. 问题定义

### 1.1 输入

| 输入 | 内容 | 规模（反激验收用例） |
|---|---|---|
| `circuit.json` | 网表：器件（位号/值/MPN）+ 网（引脚集合）+ 声明的主路径/反馈路径 | 33 器件、约 30 网 |
| `presentation.json` | **布局意图**：模块划分、流向、端口角色、直连义务、用户锁定位姿 | 1 个模块 `flyback_core`（19 件） |
| `profiles` | 每件的**符号几何**：body 尺寸、引脚相对位置与方向、值文字盒 | 由器件库给出 |
| `page` | 画布，单位 `1 = 0.1 inch` 量级，`grid = 5` | 1170 × 825 |

`presentation.json` 可声明的（`core/presentationspec.py:198-352`）：
`modules[]`（含 `side_preferences` / `branch_order` / `core`）、`flow`、
`main_paths` / `feedback_paths`（每条的 `chain` 器件序列）、`port_roles`（如 `HVDC=input`、`SEC_12V=output`）、
`direct_wiring_obligations`（哪些网**必须**用真线连、不许用网络标签）、`label_policy`、`user_locks`。

### 1.2 输出

- 每件：`x, y, rotation ∈ {0,90,180,270}, mirror ∈ {0,1}`（**位姿集是离散的**，且每件的合法集由符号决定）
- 每网：走线点序列（正交线段集），或一张网络标签 + 旗标（电源/地符号）
- 结果必须过一页 SVG 渲染

### 1.3 目标（**用户的裁定，比"关系全过"高一层**）

用户是硬件工程师，原话：

1. **一眼认出拓扑**：「画的是反激或者 LLC，人家也得能一眼认出来」「比如你在画 RC，就要明确是一个 R 加一个 C，
   而不是你画出来明明是 RC，人家第一眼看上去却像 CR」
2. **高低压分区一眼可见**：「我是把这个模块的高压和低压部分区分开的，让人能一眼看出来哪边是高压区域、哪边是低压区域」
3. **核心拓扑留主环，塞不下的用网络标签拎出去**：「你可以把塞不下的部分（比如 RCD 等）拆出去，但整个模块一定要
   像一个完整的拓扑。拓扑的核心部分必须保留在这个主环路里，像滤波电容以及一些简单的小外围，才可以拆出来放在
   不远处的空白位置」
4. **不许裁字**：值/网名被器件体或别的文字切掉，人就读不了

量化靶子（`docs/roadmap.md:60-79`）：

| 指标 | 当前 | 目标 |
|---|---|---|
| `occupied_ratio` | **2.73%**（挤在左上角） | 居中、留白对称（人类参考 **35.4%**） |
| `crossings` | **12** | ≤4，理想 **0**（人类参考 **0**） |
| `min_text_gap` | **0**（C11 的值被裁） | >0，无裁字 |
| `unaligned_part_pairs` | **156** | 大幅下降 |
| 人类手画参考 | 32 器件 / crossings 0 / occupancy 35.4% / bbox **1044×326** | — |

---

## 2. 硬约束（违反即整候选作废）

`engines/readability.py:253-263,682-786` 的 **11 条闸**，每一条都由一个独立函数判定：

```
netlist-partition-mismatch   从图反推出的网表和输入网表不一致（少了/多了连接）
dangling-wire-end            有悬空线端
undeclared-junction          三线交汇但没画连接点
wire-through-body             线穿过器件体
wire-on-pin-line              线压在引脚引线上（视觉上和引脚混在一起）
text-overlap                  两个文字盒相交
text-on-wire                  文字压在线上
out-of-page                   出画布
user-lock-violated            用户锁定的位姿被改
nc-pin-connected              NC 引脚被接了东西
required-pin-not-connected    必须连接的引脚没接
```

另有页级 8 种（模块框越界等）。**注意 `derive_netlist`**：网表不是"照着抄"，而是**从画出来的图反推**，
再与输入比对——这是防"线画了但连接关系错了"的关键，也是布局/布线必须协同的原因。

### 2.1 关系约束（10 种 kind）

`engines/grammar/base.py:204-212`，反激用例共 **33 条**：

| kind | 含义 | **量什么** |
|---|---|---|
| `same-column` | 两件在同一竖列 | **两件的 pin 尖**（共享网上） |
| `same-row` | 同一横行 | pin 尖 |
| `horizontal-tap` / `vertical-tap` | 抽头方向 | pin 尖 |
| `near` | 邻近 | pin 尖（`hypot <= near_limit = 300`） |
| `above` / `below` / `left-of` / `right-of` | 序关系 | **两件的 origin** |
| `adjacent` | 相邻 | origin |

**这个"两套量法"是所有麻烦的起点**（见 §5.1）：

- `same-column(Q1, R5)` 说的是 **Q1 的源极 pin 尖** 与 **R5 的某个 pin 尖** x 坐标差 `<= grid/2 = 2.5`。
  但 Q1 和 R5 是两个不同符号，它们的引脚在符号上的**相对位置**不同，所以在"两件 origin 对齐"时，
  两个 pin 尖天然差一个固定量（实测恒差 **20** 单位）。
- `right-of(D3, T1)` 说的是 **D3 的 origin 在 T1 的 origin 右边**。

也就是说：同一个布局里，「pin 尖对得齐」与「origin 排得开」可能**数学上互斥**。

`relation_miss(...) -> float` 是同一把尺的连续版本（`0 ⟺ holds`），placement 的修复移动按它算位移。

---

## 3. 当前读数（全部实测）

### 3.1 基线（干净树 `d8a6b05`，`outputs/algo_eval/BASELINE.md`）

| presentation | 候选 | crossings | bends | wire_length | unaligned | min_text_gap | occupied | 耗时 |
|---|---|---|---|---|---|---|---|---|
| **去锁**（无用户锁） | **0** | — | — | — | — | — | — | **26.8 s** |
| 带锁（19 件全锁定） | 1 | 12 | 40 | 5902.5 | 156 | **0** | 2.73% | **141.5 s** |

去锁死因原文：

```
presentation-poor: the relation same-column(Q1, R5) is not honoured ...
measured (200,280) and (180,235)
```

### 3.2 分轮拒因（`failure_rounds`，551A 加的）

同一页在不同**轮**被不同关系拒，历史只报第一条，所以看不到全貌。三档阶梯：

| 轮 | 做法 | 拒因 |
|---|---|---|
| `base` | 一维链种子 + 阶梯间距 × 前 2 个位姿 | `same-column(Q1, R5)` |
| `widened`（119） | 0 候选且所有拒因是同一条关系 → 试剩余位姿 | `right-of(D3, T1)` 的 T1.4 引脚方向 |
| `topology`（201B） | 只在上述全败时跑，位姿集进搜索 | `net 'SRC'` 直连义务走廊 |

### 3.3 拓扑轮已经拿到了好布局，但布不通

`outputs/algo_eval/diag_full/table.md`（拓扑答案，局部坐标）：

```
Q1 (60,105) rot0        R5 (60,50) rot90       R10 (65,80) rot0,mirror
C10 (100,105) rot90     U5 (90,145) rot0,mirror    T1 (55,340) rot180,mirror
D3 (120,330) rot90      R3 (10,220) rot270

33 条关系 miss 全 0；硬项 3 条全 0
代价：wire-length 1680 / pin-facing 677.5 / flow-side 602.5 / spread 379.4
      clearance 108.5 / flag-room 4.5
```

**布局这关过了**。拒绝前移到布线：

```
net 'SRC' has a direct-wire obligation ... could not be joined inside the searched corridor
net 'SW'  has a direct-wire obligation ... could not be joined ...
```

> 注意 `Q1 (190,490)` / `R5 (190,435)` 是掰正方向后的读数（`same-column` 成立、R5 在下），
> 但布线仍拒 `SRC`。这是 **D1** 之后的实测。

### 3.4 一页（150 用例，19 件全锁定）能出图，但那是"照抄用户给的坐标"

HEAD `draw compile` → `ok=True`，1 个合法候选，5 个 rejected 全是 "same geometry"（因为 19 件全 `user_locks`，
所有变体只能摆同一处）。这是**回归保护基线**，不是算法能力。

---

## 4. 已试过的路子（**请勿重复**）

### 4.1 算法层尝试

| 批次 | 做法 | 读数 | 结论 |
|---|---|---|---|
| **394/395** | 走廊代价项（每条 pin 每方向 15×160 矩形） | 密集页 **5051 units²**（真实需要 135），退火靠破关系买它；readability 报 12–21 条 | 否决：代价尺度错 |
| **394/395** | `_corridor_nudge` 循环（每轮重建 placement+布线） | **单轮 >60 s**，`MAX_CORRIDOR_NUDGES` 12→3 仍 200 s 无输出 | 否决：任何"再跑一次 placement"的方案都不合格 |
| **397** | 窄矩形 `wire-corridor`（W=0.1） | 8 个预览文件全绿、零位移闸过，但**一个候选都没出**；证明 `same-column(Q1,R5)` 与「SRC 三针直连」几何互斥 | 声明：权重轴上「出候选」与「不破既有测试」**没有交集** |
| **398** | grammar 补 `RIGHT_OF(error_amp, switch)` | SRC 走廊通了（改拒 `HVDC` 旗位），**但打破 4+ 条既有断言** | 否决：根因是 grammar 里没有一条约束 error_amp 相对开关的位置，它落在 Q1 正上方是 rank 同值的字母序巧合 |
| **算法 A**（构造式行列布局） | 先定行列再填件 | 2 小时零代码落地 | 未达成 |
| **算法 B**（退火增强） | +242/−75 行，加逃逸项 | **调用了从未实现的 `_escape_term`**，一次都没跑过；补掉后去锁仍 0 候选、耗时 26.8→12.4 s（空间被砍） | 否决 |

### 4.2 架构层尝试

| 批次 | 做法 | 读数 | 结论 |
|---|---|---|---|
| **201B 阶段一** | 新模块 `placement.py`：拓扑感知落位 + **位姿进搜索** + 关系分软硬（`relation_miss` 是距离不是布尔）+ 固定种子确定性 | 30 条关系全 0 违反、硬违反 0、单次 **8.90 s**；非零代价：走线 1595 / pin-facing 445 / flow-side 225 / 对角 478 | 模块成立，但**编译仍然 0 候选**（编译器没接它） |
| **201B 阶段一** | 把 `port_roles`（`HVDC=input→左`）置于网类之上当方向 | 反激走线 **1595→3240**、外接框 **478→824** | 否决：被关系反噬，已撤 |
| **201B 阶段二** | 把 `placement` 接进管线，**只在阶梯全败时跑**（"新算法只许补出图，不许换掉已经能画的图"） | 反激 `ok=False cands=0 rejected=15`（阶梯6+加宽8+拓扑1），单次 22.4 s；**拓扑档 readability 0 违反**，卡在旗标 `net 'HVDC' … no legal place … T1.1 at (-85,-695)` | 方向对，死因前移 |
| **201B 阶段二** | 旗标落点进代价函数（`_flag_room_term`，用编译器的 `_flag_box` 算要留多大） | HVDC 死因**消失**；死因变 `net 'SW'` 直连走廊 | 有效，已留 |
| **201B 阶段二** | 全局间距三档对照（`TEXT_CLEARANCE` 15 / 25 / 40） | 15→0 硬违反但旗挂不下；25→**23 条** text-overlap；40→direct-wire 走不通 | 证明「全局间距」这个旋钮不是答案，**必须局部化** |
| **201C** | 布线协商：router 加 `blockers` / `escape_nodes` / `soft` 软预留 + `_negotiate_rip_up`（≤2 轮，择木放回） | `SW` 接通（针尖被邻居值行吞掉，一步出口放行），死因前移 readability **16 条**文本行硬违反 ⇒ 仍 0 候选；整档 **80.1 s**（A\* 68.1 s / 21 次） | 见 4.3——**被踢出发布** |
| **515A** | 拓扑轮补关系闸、`user_locks` 硬锚、全 pinned 输入短路（6000 空转→0） | 116 性能闸 10→40 s | 有效，已留 |
| **519** | 异网 pin 尖最小间距（`pin-clearance`，阈值 `grid*2=10`，权重 40） | 拓扑轮原把 `Q1.3(SRC)` 与 `R5.2(PGND)` 放**同一点**（router 当墙 → SRC 必拒）；修后 `SRC` 不再被拒，死因变 `SW` | 有效；**必须做成第二遍**（见 §5.4） |
| **D1** | 链折返（`PlacementInput.chain` + `_seed_folding`），只在 topology 轮生效 | 破坏关系 2→1 条，仍 0 候选；方向掰正后**拓扑答案 `failures = 0`**，拒绝前移到布线 | 有效，已留 |

### 4.3 201C 为什么被踢出发布（关键教训）

150 落地页回归实锤：

```
HEAD        ok=True   1 合法候选（19 件全 userLocks，5 rejected 全 "same geometry"）
201C        ok=False  4 constructive + 1 topology 全死
```

死因链：软预留走廊占住义务网通道 → 逼 `FB_SENSE` 改走竖段 → 宿主印的网名行沿竖段竖排（盒 **10×37.3**）
→ 压 `R8` 器体 **0.5 单位** → readability 硬拒。

而 `FB_SENSE` 正是 `core/textmetrics.py:126` 记录的 **`WIRE_NAME_MODEL_EXCEPTION`**（16 条具名线里 15 条吻合模型，
它是唯一例外，锚在弧长中点）。**readability 从未接这个例外**。

> **教训**：一个"改进"若把一个能出图的输入变成 0 候选，就是回归——即使它让另一个输入更好了。
> 现在的规则是：**新算法只许补出图，不许换掉已经能画的图**（`drawcompiler._topology_round` 的注释）。

### 4.4 外部推演把「CP-SAT 精确求解」试过了（2026-10-19，结论：**不是解**）

一位算法专家读了本文后给出「层次化构造 + CP-SAT + 布线反馈 + 字典序优化」，并建议最小实验：**只替换
topology 轮的布局求解器，管线其余不动**。做了，六轮（`.tmp_cpsat`，独立 venv 装 ortools）：

| 轮 | 读数 |
|---|---|
| CP-SAT 纯可行 / 加直连走廊 / 失败网回灌 | 33/33 关系全中、零重叠、同晶格，**0.2–0.5 s 全 OPTIMAL**；**19 个解 0 布通** |
| 局部压缩（保关系，压面积/宽高比/主环带） | 面积 −68%、3:1、occupied 60%；13 次 compile **0 布通**，失败从 corridor 前移到 readability |
| 逐网探针（独立 BFS 可达性） | 人类坐标 **7/7 义务网全真线、1 候选**；CP-SAT 解 **21 个 pin 尖埋在邻居 value 行里** |
| 分层 + 层内带优化目标 | **0.094 s** 出首解（8 件 668 变量），19 件压到 314×105；14 个布局 **0 布通** |
| 文字盒 + pin 净空回填进 CP-SAT | 跨器件 bury **4/8/3/3 → 0/0/0/0**；**仍 0 布通** |

**所以「搜索空间小到可以精确求解」这条判断，方向对、用处不对**：CP-SAT 能在 0.2 秒内证明「存在满足全部
关系的布局」，但**这类解在几何上是垃圾**（纯可行性解 = 器件随机摊开），而且**即使把它们压紧、把 pin 净空
补齐，仍然一个都布不通**。瓶颈不在布局求解器，在**布局与布线之间缺一个共享的可行性判据**。

**权重无效的原因也定位了**：不是权重标定坏了，是**加一个目标就爆**——纯可行性 0.11 s 证 OPTIMAL，
一旦把 wire-length 加进目标，40 s 也证不完。所以带质量的 CP-SAT 只能分层（小规模带目标），而分层解同样布不通。

**顺带找到两个真缺陷（已修）**：`_elbow_route` 的拐点不在任何一道闸的检查区间内（`_span_free` 走
`_strictly_on_segment`，端点不算），于是拐点落在异网引脚上会静默并点；`placement.part_box` 不含 texts，
于是邻居的 value 行可以盖住 pin 尖、把那个尖变成 router 的墙节点。修完，阻塞前移到**直连走廊**。

**给下一位推演者的建议**：不要再从布局求解器入手。要的是「这条网在当前布局下能不能通」的**廉价判据**
（30 网规模、逐网一次可达性探测完全可行），以及**布线失败 → 具体约束**的回灌（`201C` 的 `blockers()`
被踢出发布是因为它在 A\* 里加软墙，不是因为它点名的信息没用）。

---

## 5. 我判断的三条根因

### 5.1 约束的量法与表示不匹配（**权重无效**的实证）

`same-column` 量的是**pin 尖**，而链式种子让相邻两件的 **origin** 对齐：

```
链布局：  Q1 ── R5        （origin 同 x）
但 Q1 的源极 pin 在符号底边中间、R5 的 pin 在符号左右两端
⇒ pin 尖 x 恒差 20，与 origin 位置无关
```

实测证据（决定性）：把这个关系的权重 `W_RELATION` 从 **10 → 50**，坐标**一字未变**（16.0 s）；
`W_HARD` 从 200 → 20 也**一字未变**（20.1 s）。

> **不是权重不够，是搜索空间里没有满足解**——或者说，退火的移动集（30% 平移 / 20% 换位姿 / 15% 交换 / 35% 关系修复）
> 到不了那个解。

`same-column` 的判据是 `abs(ax-bx) <= grid/2 = 2.5`，而 pin 尖间距只能是符号几何给出的离散值——**连续距离被判成布尔**，
两者不匹配。

### 5.2 布局与布线两阶段割裂（**拓扑轮过了关系却布不通**的实证）

流程是：

```
placement（退火，只看得见 body/文字盒/关系/旗位预留）
   ↓ 选最优
router（A* over (node, arrival_direction)，只看得见这一张图的墙）
   ↓
readability（11 条硬闸）
```

placement **不知道** router 能不能接上。所以拓扑轮可以做到「33 条关系全 0 违反、硬项全 0」，然后 router 告诉你
`net 'SW'` 的直连义务接不上——因为布局阶段没为它留出一条真正可用的通畅走廊。

人类画图时这两件事是同时想的（"这个节点要往上走，所以 Q1 要往左挪一点"）。

### 5.3 布线协商的代价爆炸（**想打通二者就爆**）

201C 试图用「软预留 + rip-up & reroute」把两阶段捏合，实测：

- 初版软预留**按节点**计价（6.0 步/节点）：150 落地页从 123.3 s `ok=True` 变成 **>600 s 且 `ok=False`**。
  根因：义务走廊铺满大半张纸，A\* 的**曼哈顿启发式失效**（它要绕的区域比启发式估计的大得多）。
- 改**按进门**计价后：127.7 s `ok=True cands=1 rejected=5`。仍然太慢（里程碑预算 60 s/页）。
- 反激：`SW` 接通了，但死因前移到 readability 16 条（见 §4.3），整档 80.1 s，其中 A\* 68.1 s / 21 次调用。

**结论**：把布线可行性引进布局，不能靠"在 A\* 里加软墙"，因为那会让 A\* 从局部搜索退化。

### 5.4 一个隐蔽但重要的事实：退火是**路径搜索**

519 的教训：把 `pin-clearance` 项挂进第一遍 `evaluate()`（即让它参与退火的**每一步**评估），
会让 `098 scene08` 的逐字节 hash 从 `1e7a8583` 变成 `31919a64`——**即使最优点的该代价为 0**。

原因：退火是**路径搜索**，一个在最优解处为 0 的代价项，在**到达最优解的路径上**并不为 0，
它会改变 rng 消耗与移动序列。

所以 519 必须做成**第二遍**（第一遍按历史请求跑，答案仍挤时才跑第二遍修复）。

> 给算法推演的含义：**任何新增代价项都会改变整条搜索轨迹**，不能假设"它只在有问题的地方起作用"。
> 这也是为什么"权重调参"这条路在本项目上从未奏效。

---

## 6. 可用接口（外部 AI 需要知道能调什么）

### 6.1 `engines/placement.py`（2124 行，本批的算法实验田）

```python
PlacementPart(part_id, profile, poses, locked, locked_origin)
#   poses = 全部合法位姿集（由符号决定，不是笛卡尔积）
#   locked_origin = 精确锚点，不吸附格点（515A）

PlacementInput(
    parts, nets, relations, chain,
    flag_seats, pin_clearance, progress, lateral, side_preferences,
    page_box, keepouts,
    grid=5.0, near_limit=300.0, channel=40.0, lane=60.0,
    iterations=6000, restarts=3, seed=201,
)
#   chain 为空 = 历史一维 seed；非空 = 按 chain 折返（D1）

PlacementResult(origins, poses, costs)      # costs: list[CostTerm(name, value, detail, hard)]
```

**代价权重（全部具名常量，`placement.py:91-188`）**：

```
W_RELATION = 10.0     W_WIRE = 1.0       W_FACING = 1.0
W_SIDE = 2.0          W_SPREAD = 0.5     W_CLEARANCE = 1.5
W_FLAG_ROOM = 0.2     W_HARD = 200.0     W_PIN_CLEARANCE = 40.0
TEXT_CLEARANCE = 15.0                    PIN_CLEARANCE_GRID = 2.0
```

**硬项只有三条**：out-of-page / keepout / overlap。**关系违反不算硬项**（这是 201B 的关键决定：关系分软硬，
否则一个关系不满足就整候选判死，搜索没有梯度）。

**退火**：温度 40.0 起、几何冷却 0.9995、`stall >= 2000` 早停；移动混合
30% 平移（梯 1/2/4/8 × grid）/ 20% 换位姿 / 15% 交换 / 35% **关系修复**（沿 `relation_miss` 的梯度挪）。
全 pinned 输入短路返回种子。

**`relation_holds` / `relation_miss` / `relation_points_between`** 是唯一实现（编译器的语法闸、旧求解器、放置搜索
三个读口都委托它，201B 阶段二合的）。

### 6.2 `engines/router.py`（502 行）

```python
_Router.route(start, goal, *, targets=None) -> list[点] | None
#   A* over (node, arrival_direction)
#   启发式 = 曼哈顿步数（116 加的；此前 Dijkstra 两次分别 98 s / 39 s）
#   步 = 1.0，TURN_COST = 0.6，CROSS_COST = 120.0
#   （CROSS_COST 是用户裁的「宁可多绕也不穿干线」；实测 2.0 太便宜）
```

router 认的"家具"：`boxes`（器件体 + 文字盒 + keepout，切入即墙）、`blocked`（异网 pin 尖 / 标签 / 旗 / 异网线顶点）、
`edges` + `edge_nets`（异网线**可垂直穿越、不可并行/转弯**）、`reserved`（软预留：非本网即墙）、
`flag_seats`（旗先定座再布线）、`flag_leads`、`blockers()`（失败时 BFS 点名挡路网）、
`escape_nodes`（戳进 box 的针尖一步出口）。

### 6.3 `engines/drawcompiler.py`（10277 行，管线本体）

```python
compile(circuit_spec, presentation_spec, profiles=None, budget=None, *, intent=None,
        page_ground_domains=None) -> CompileResult(candidates, ranked, failures,
                                                   rejected, notes, grammar, failure_rounds)
```

失败四类：`facts-missing` / `circuit-invalid` / `layout-unsat` / `presentation-poor`。

**变体阶梯**（`_variants`）：`spacing_ladder=(1.0, 1.5, 2.2)` × 前 2 个位姿；
`_widened_variants`（119）只在 0 候选且所有拒因是同一条关系时跑；
`_topology_round`（201B）只在上述全败时跑（`pose_index=-1` 作为"拓扑档"的标记）。

### 6.4 文字盒（**很容易被忽略的一环**）

`core/textmetrics.py`：宿主用 Arial，`RENDER_TEXT_PX = 7.148342059336824`，
`render_width = Σem × 7.148`。150 之前误乘了行距常量 `CANVAS_TEXT_UNITS = 10.0`，导致**每个文字盒宽 1.39893 倍**
——那是"线总是看起来压着字"的一部分原因。

`wire_name_box`：锚 = 最长直段的中点，行按行进方向 start-anchored；16 条具名线里 **15 条**吻合，
唯一例外是 `FB_SENSE`（锚在弧长中点，无解释），常量名 `WIRE_NAME_MODEL_EXCEPTION`。

### 6.5 一个必须知道的坑（如果外部 AI 碰 PCB 侧）

`core/geometry.py`：`PadGeometry.footprint_layer_id` 是封装里写死的层号，**器件翻到背面后不重写**；
铜实际在哪层读 `effective_layer_ids`。已加 `__getattr__` 拦截旧名 `layer_id` 报错。

---

## 7. 我想请你推演的问题

按我判断的重要性排序。**每一条都请给出：表示法、搜索/求解方法、代价或约束的编码、复杂度估计、以及在本规模
（33 器件、约 30 网、画布 234×165 格、每件 4–8 个合法位姿）下是否可行。**

1. **表示法**：33 件 × 离散坐标 × 位姿，关系是"同列/序/邻近"这类**相对**约束。
   - 序列对（sequence pair）？它天然编码相对位置，但中文/原理图还要"同列"这类**对齐**约束。
   - CP-SAT / 整数规划？把 `same-column` 编码成 `|x_a - x_b| <= 2.5` 的整数约束、序关系编码成不等式，
     目标是最小化走线估计。**这类约束的可行域有多大？剪枝能不能把它压到可解？**
   - 层次化：先给"模块/区"分配矩形（floorplan），再在矩形内摆件（placement）？
2. **布局阶段如何看见布线可行性**（§5.2 的核心）：
   - VLSI 的做法是拥塞图（congestion map）/ 概率布线估计。这里规模只有 30 网，能不能**精确**？
   - 能不能反过来：**先算每条网的必要通道（每个网的 pin 尖包围盒 + 曼哈顿最短路的必经区），把它当作布局的保留区**？
     （519 的失败是因为"每条 pin 每方向 15×160"太粗；这里要的是"每条网一个必要时序区"。）
   - 或者：**联合优化但分层近似**——布局时用"走线长度的 L1 估计 + 穿越惩罚"，只在最终候选上跑真 A\*？
3. **约束的优先级层次**（§5.1）：
   - 33 条关系里，哪些是**拓扑本质**（`same-column(Q1,R5)` 是"开关管和源极电阻同列"，这是电路读法），
     哪些是**装饰**（`near`）？
   - 能不能**自动推导**优先级？比如：一条关系若被违反会改变网表的**读图顺序**（用户看完这个再往下看），它就是硬的。
     这个"读图顺序"能不能从 `main_paths`/`chain` 里推出来？
   - 或者干脆：**先解一个"关系全部满足"的约束满足问题**（可能有解，拓扑轮证明了 33 条同时成立是可能的），
     再在这个解的邻域里做布线/审美优化？——如果这样，第一步的求解用什么？
4. **`same-column` 这类"对齐"约束的正确量法**：
   现在量 pin 尖（因为原理图的"同列"在视觉上是**引脚对齐**，不是器件中心对齐）。
   但对齐的实体是"两个不同符号上的两个 pin"，它们的相对位置是符号几何给的。
   **能不能把约束改写成"够近就算对齐"的软约束 + 一个离散的吸附动作**（先自由摆放，再把 pin 尖吸到最近的格点）？
5. **构造式 vs 全局搜索**（§4.1 算法 A 失败但没真做）：
   人类画反激的顺序是：先摆主环（T1/Q1/D1/输出电容），再挂 RCD 吸收，再挂反馈分压，再挂供电。
   **这种"按拓扑核心逐层外扩"的构造式方法，与全局退火相比，在什么条件下更好？** 如何定义"核心"和"外扩距离"？
6. **可计算的"一眼认出"指标**：
   用户的判据是"工程师一眼认得出"。能不能给出**可计算的代理**？
   我的候选：(a) 主环器件的 bbox 长宽比接近人类参考（1044×326 ≈ 3.2:1）；
   (b) 同一 chain 上的器件在一条"视觉带"内（投影到主方向的方差小）；
   (c) 高低压两组的 bbox 沿隔离轴投影不交叠；
   (d) RC 类两件对的读图方向与信号流向一致（左→右 / 上→下）。
   **这四条够吗？有没有更好的、能从 layout plan 直接算出来的指标？**
7. **性能预算**：一页 ≤60 s（用户的耐心上限），现在 26.8 s（0 候选）/ 141.5 s（1 候选，照抄坐标）。
   **算法必须在 60 s 内收敛**。这个预算下，CP-SAT 精确解、或者"约束满足 + 局部优化"两段式，哪个现实？

---

## 8. 附：可以直接跑的实验

```
# 基线（去锁，0 候选）
python outputs/algo_eval/bench.py --tree <repo> --label base \
    --presentation .tmp_board2_draw2/presentation_nolocks.json

# 带锁（1 候选，141.5 s）
python outputs/algo_eval/bench.py --tree <repo> --label locked \
    --presentation outputs/150/presentation_150_r5rot.json
```

输出是一行 TSV：
`candidates, crossings, bends, wire_length, unaligned_part_pairs, min_text_gap, occupied_ratio, seconds, verdict, note`
外加 `summary.json`。底层命令：

```
draw compile --circuit blocklib/specs/flyback_uc3845.circuit.json --page-box 0,0,1170,825
```

**零位移闸**（改算法前后必须过，确保没换掉已经能画的图）：

```
python tools/116_no_move.py previews    # 必须 "N placements compared, 0 with a moved origin"
```

当前基线 `N = 374`。

---

## 9. 一句话给推演者

**这不是一个"调参"问题，也不是"加一个更强的启发式"问题。**
33 个器件、30 个网、每件 4–8 个离散位姿——搜索空间小到**可能可以精确求解**，而现在的失败模式
（权重从 10 加到 50 坐标一字不变）说明瓶颈在**约束表示**和**两阶段割裂**，不在局部搜索的强度。
