# 201G 证据：反激整页 0 候选的两个真因（诊断，未改 src/）

- 批号 **201G**，诊断。HEAD `dbd5b9a`（0.5.18）+ 工作树既有未提交改动。
- **未改 `src/` 一个字节**：`git diff --stat src/boardwise/engines/drawcompiler.py src/boardwise/engines/placement.py`
  为空；本批全部读数由 monkeypatch 探针取得（`.tmp_201g/`）。
- 夹具 `blocklib/specs/flyback_uc3845.{circuit,presentation,library}.json`，
  `CompileBudget(max_candidates=64)`，载入方式照抄 `.tmp_201f/time_only.py` 的 `library_from()` + `CircuitSpec.load`。
- 复现命令（单进程，一次编译 ≈ 11 s）：

  ```bash
  .venv/Scripts/python.exe .tmp_201g/probe_a.py         # 上下文/槽位/关系原文
  .venv/Scripts/python.exe .tmp_201g/probe_a2.py        # 逐档全量违反清单 + 解存在实验
  .venv/Scripts/python.exe .tmp_201g/probe_a3.py        # _honour_bound_orders 是否碰过这两条
  env 201G_MODE=drop 201G_DROP="<kind>:<subject>:<object>" \
      .venv/Scripts/python.exe .tmp_201g/probe_a2.py    # 「删一条关系」实测
  .venv/Scripts/python.exe .tmp_201g/probe_b.py         # 旗标 ladder 逐档 + 空白量化
  env 201G_FORCE=2 .venv/Scripts/python.exe .tmp_201g/probe_b_gate.py  # 「席位不再是问题」实测
  ```

  日志：`probe_a.log` / `probe_a2_dump.log` / `probe_a3.log` / `drop_*.log` /
  `probe_b.log` / `gate_f2.log`（全在 `.tmp_201g/`）。

**基线读数（本批实测，与本批之外无冲突）**：`ok=False candidates=0 rejected=25 failures=1`，
`spacing_ladder=1x,1.5x,2.2x`，6 基线档 + 18 加宽档（`pose-variant=2..7`）+ 1 拓扑档 = 25。

---

## 0. 先把 failure 全文拿到（任务书 §二 第一件事）

201E 的日志（`.tmp_201e/run_default.log:31`）与证据 md 都在「a s」处截断——那是 201E 探针自己
打印时的切片，不是编译器的话。

全文在**源码**里：`drawcompiler._rail_flag_room_failure`（`src/boardwise/engines/drawcompiler.py:8655-8688`）
把 `detail` 拼成固定模板 + `blocked_by`；`blocked_by` 那段字面量就在 `_rail_flag_seat` 的
`return`（:8805-8814）。运行时的原文与它逐字相同（本批用同一套载入跑完 `dc.compile(...)` 后打印
`res.rejected[-1].failure.detail` 核对过，只有 net / member / 坐标四处代入）：

```text
category: layout-unsat | subject: SEC_12V
net 'SEC_12V' is a rail drawn as a wire and every power flag on it must be stated (069 sec.7),
but no legal place to hang one was found at the pin that supplies it, D3.1 at (90, 150):
every reach every ladder tries — a straight vertical run at 25, 30, the grid's step and the
two long ones, up and down, then a run out along the pin's own side with a turn, and then the
other three directions — lands the glyph, its name row and their clearance on a part, a text
row, another net's wire or the page's edge. The flag is not drawn on the pin instead — a flag
standing on its own pin opens its glyph across the run that leaves the pin and prints its name
row over whatever is beside it, which is the shape 岳 read as a short on the landed page
```

这句话里的「25, 30, the grid's step and the two long ones」与代码逐字对应
（`FLAG_JOG=25` :277、`FLAG_LEAD=30` :270、`grid*2=10`、`2*FLAG_LEAD=60`、`4*FLAG_LEAD=120`），
所以 message **不含**具体对象名——任务书要的那张表必须自己量，**§二**就是。

---

## 一、疑点 A：`same-column(Q1, R5)` 为什么在全部 42 个变体里都不成立

### A.1 结论：**不是「关系无解」，是两条链条叠在一起，而 note 的「同一条关系」是读数假象**

拆成两句，都有实测：

| 关系 | 几何上有没有解 | 构造阶梯（`_place_chain_and_shelf`）找得到吗 |
| --- | --- | --- |
| `same-column(Q1, R5)` | **有解**（R5 转 90°/270° 即成立，实测见 A.3） | 6 基线档找不到（pose 只走 0/1）；18 加宽档**已经找到了** |
| `right-of(D3, T1)` | 有解（拓扑搜索保住了它，实测 `CLEAN`） | **找不到**：两端都是 chain，`right-of` 按 origin 量，chain 全在同一根轴上 → 恒不成立 |
| `right-of(C10, U5)` 等 | — | 部分档找不到（见 A.4 表） |

⇒ 归因是 **1+3 的混合**，但**主因不是 `same-column`**：
`same-column` 属于「解存在但不被找到」（被全局 `pose_index` 与报告截断卡住），
真正让 24 档全灭的是另一条 `right-of(D3, T1)`（在构造求解器里无解）。

### A.2 岳的代码读法**核实为真**（`drawcompiler.py:3834-3846`）

```python
fixed = {part_id for part_id in ctx.slots
         if ctx.locked(part_id) is not None or part_id in ctx.chain}
...
here_fixed, there_fixed = here in fixed, there in fixed
if here_fixed and there_fixed:
    continue
```

本夹具 `ctx.chain = ['T1', 'D3', 'Q1', 'R5', 'U5']`（`probe_a.log`），
Q1 与 R5 都是 `kind=chain`（同日志的槽位表）。实测把 `_honour_bound_orders` 包一层计数
（`.tmp_201g/probe_a3.py`，日志 `probe_a3.log`）：

```text
all 'SKIPPED: both ends fixed' relations, by name:
   ('right-of', 'D3', 'T1')
   ('same-column', 'Q1', 'R5')
any relation actually MOVED: 103 moves
   ('spacing=1 pose-variant=0', 'above',  'D1',  'Q1', 'MOVED ...')
   ('spacing=1 pose-variant=0', 'below',  'C10', 'U5', 'MOVED ...')
   ...
```

⇒ 24 个档里，**只有这两条**被 `continue` 掉；relax pass 本身是活的（103 次移动，全是单端 chain
或双端 branch 的关系）。**岳的读法完全正确。**

### A.3 `same-column(Q1, R5)` 的判据与「解存在」实测

- 判据：`SAME_COLUMN ∈ placement._PIN_KINDS`（`placement.py:274`）→
  按**两端在共享网上的引脚端点**量（`relation_points_between`，`placement.py:707-750`）；
  容差 `grid/2 = 2.5`（`relation_holds`，`placement.py:791-792`）。
  **不是**按包围盒边，也不是按器件中心——`docs/drawing-algorithm-brief.md` 记的
  「按引脚端点判」这一形态确认，但它在这里不是病根（2.5 的容差 vs 20 的偏差，放宽到 20 也不可能）。实测点对：
  `same-column(Q1, R5) points=((0.0, -200.0), (-20.0, -245.0))`（`probe_a.log`）
  = `Q1.3`（S，在 `SRC` 上）与 `R5.1`（在 `SRC` 上），间距 **20**。
- 结构：`R5` 是 0603，两脚在 **local x 轴上**（`(-20,0)`/`(20,0)`），而 chain 把 origin 铺在
  `progress=(0,-1)` 的轴上（`drawcompiler.py:2944-2957`），所以 R5 的 origin 在 x=0 而它的 SRC 脚在 x=∓20。
- **解存在，实测直接证**（`probe_a2.py` 里的 controlled experiment，同一份 origins、只把 R5 换成它
  自己 accepted 集合里的另一个 pose）：

  ```text
  === experiment: keep every origin, turn ONLY R5 ===
      R5 pose[0] = SymbolPose(rotation=0, mirror=False):   same-column(Q1,R5) BROKEN
      R5 pose[1] = SymbolPose(rotation=0, mirror=True):    same-column(Q1,R5) BROKEN
      R5 pose[2] = SymbolPose(rotation=90, mirror=False):  same-column(Q1,R5) HOLDS
      R5 pose[3] = SymbolPose(rotation=270, mirror=False): same-column(Q1,R5) HOLDS
  ```

  ⇒ **「解存在但不被找到」**，不是「无解」。
- 而且加宽档**确实找到了**：`pose-variant=2..7`（18 档）的违反清单里**没有** `same-column(Q1,R5)`
  （`probe_a2_dump.log`，见下表 A.4 头几行）。
  原因在 `_variants`（:5961-5967）只走 `pose_index` 0/1，`_widened_variants`（:6271-6278）才走
  `2..widest-1`，且 **`pose_index` 是全局一个下标**，一档里所有部件一起换 pose——所以换到 R5 的
  90° 时，T1/D3 也跟着换了，于是死在 `right-of(D3, T1)`。

### A.4 为什么 24 档全灭：`right-of(D3, T1)` 在构造阶梯里无解

- `right-of` **不在** `_PIN_KINDS`（`placement.py:274`）→ 按 **origin** 量（`placement.py:801-802`）。
  实测点对：`right-of(D3, T1) measured points: ((0.0, -100.0), (0.0, 0.0))`（`probe_a.log`）。
- chain 把 5 个成员全放在同一根轴上，实测 `chain origins x: T1=0.0, D3=0.0, Q1=0.0, R5=0.0, U5=0.0`
  （同日志）。D3 本可以被 `_park_unordered_chain`（:3464-3519）**横向挪开**，但它是
  「有 chain order 的」——`_has_chain_order`（:3538-3545）把 `right-of(D3,T1)` 算作 order，
  于是被跳过。⇒ **origin 的 x 恒相等 ⇒ `right-of(D3, T1)` 在这条求解器里结构性无解**，
  且 relax pass 又因两端都是 chain 而 `continue`。
- 该关系出自 flyback grammar（`src/boardwise/engines/grammar/flyback.py:781-795`，
  岳 110 裁决 a：副边件在 T1 的输出侧），grammar 自己的注释（:764-776）写着
  「201B 的搜索能保住全部 33 条关系」——**这是真的**：本批实测拓扑档 `_relation_failures` 返回**空**
  （`probe_a2_dump.log` 末行 `topology-search: CLEAN`）。

### A.5 逐档全量违反清单（实测，`probe_a2_dump.log`）

`spacing=1 pose-variant=0` 起共 24 档；`pose-variant=2..7` 是加宽档：

| 档 | 全部被破坏的关系 |
| --- | --- |
| 1 / 0 | `same-column(Q1, R5)`, `right-of(D3, T1)` |
| 1 / 1 | `same-column(Q1, R5)`, `right-of(D3, T1)`, `left-of(R8, U4)`, `left-of(U5, U4)`, `right-of(C10, U5)` |
| 1.5 / 0 | `same-column(Q1, R5)`, `right-of(D3, T1)` |
| 1.5 / 1 | `same-column(Q1, R5)`, `right-of(D3, T1)`, `right-of(C10, U5)` |
| 2.2 / 0 | `same-column(Q1, R5)`, `right-of(D3, T1)`, `near(C13, T1)` |
| 2.2 / 1 | `same-column(Q1, R5)`, `right-of(D3, T1)`, `near(C13, T1)`, `right-of(C10, U5)` |
| 1 / 2..7 | **无** `same-column`；`right-of(D3, T1)`, `right-of(C10, U5)`（个别还多 `below(C10,U5)`/`left-of(U5,U4)`） |
| 1.5 / 2..7 | 同上 |
| 2.2 / 2..7 | `near(R15, R3)`, `near(R15, T1)`, `right-of(D3, T1)`, `right-of(C10, U5)`（+`near(C10,U5)` 在 2） |

⇒ **`right-of(D3, T1)` 出现在全部 24 档里**（唯一一条 100% 出现的），`same-column(Q1,R5)` 只出现在
6 个基线档里。

### A.6 note 里那句「同一条关系」是读数假象（代码定位）

- `_place_chain_and_shelf` 把 `_relation_failures` 的**全部**违反算出来，却只 `return conflict[0]`
  （`drawcompiler.py:3067-3069`）——每档只报**第一条**冲突。
- `_widening_blocker_label`（:6201-6211）只看 `item.failure`（= 那条第一冲突），
  再 `sorted(named)[0]` 取字典序最小的一个。`same-column(Q1, R5)` / `near(R15, R3)` 都是这样被
  「代表」了 24 个各不相同的档。
  ⇒ **note 的文字不能当作死因统计**，201E 表格里「24 档死因 = 关系检查」是对的，「同一条关系」是错的。

### A.7 「删一条关系能活几档」实测（`201G_MODE=drop`，每条一次完整编译）

| 删掉的关系 | `ok` / candidates / rejected | 剩下谁挡路（实测） |
| --- | --- | --- |
| （不删，基线） | False / 0 / 25 | 基线 6 档 `same-column(Q1,R5)`；加宽 18 档 `right-of(D3,T1)`；拓扑档 `SEC_12V` 旗标 |
| `same-column(Q1, R5)` | False / **0** / 25 | 24 档**全部**改死在 `right-of(D3, T1)`（`drop_*.log`） |
| `right-of(D3, T1)` | False / **0** / 25 | 基线 6 档 `same-column(Q1,R5)`；加宽档 `right-of(C10, U5)`(1/1.5×)、`near(C13,T1)`、`near(C11,T1)`、`near(U5,U4)`…（`drop_rt.log`） |
| `near(R15, R3)` | False / 0 / 25 | 无变化 |
| `right-of(C10, U5)` | False / 0 / 25 | 无变化 |
| **两条一起删** | False / **0** / 7 | `spacing=1 pose-variant=0` **关系全过**，进闸后被 readability 拒 **10 条硬违反**；拓扑档 18 条（`drop_both2.log`） |

⇒ **没有任何单条/双条关系的删除能让这一页出候选。** 「删关系」这条路的最远处是
「1 档走到可读性闸，闸报 10 条硬违反」。

---

## 二、疑点 B：`SEC_12V` 在 `D3.1 (90,150)` 为什么无处可挂

### B.0 席位在哪一步失败的（代码定位）

- 席位由 `_seat_wire_flags`（:8818-8894）在**布线前**决定并预留；预留没拿到（`lead is None` 就 `continue`，
  :8879-8880，那一档的 `failure` **被丢弃**）时，轮到布线后的 `_rail_flag`（:8539-8560）**重新决定**，
  这时才把 failure 报出去。⇒ 本批报出的那一次，是**布线之后**、`router.edges` 已有 70 条异网线的那一次
  （实测 `solids=65 bodies=57 foreign edges=70 own edges=6 blocked points=93 reserved lanes=111`，
  `probe_b.log`）。
- `page_box = None`（`CompileBudget()` 默认）⇒ **页边不是本夹具的约束**（`inner=None`），
  failure 里的「or the page's edge」这半句在本夹具**从未触发**。

### B.1 ladder 逐档表（实测）

`_rail_flag_seat`（:8774-8790）先走**直线竖杆**两遍（`hang = +1` 向上、`-1` 向下），
每遍的长度序列由 `_flag_anchor`（:8177-8183）给出：
`leads=(FLAG_JOG=25,)` → `25, 30(FLAG_LEAD), 10(grid*2), 60, 120, 0`。
表里 anchor/rotation 是实测重算的候选点（与真实调用的 trace 逐步对上，
`probe_b.log` 的 `### the trace of the real call (168 events)` 是同一份真值）。
「失败原因」栏里带 id 的对象名由 `_body_box` / `_pin_walls` / `_text_walls` 反查（探针自建的名字表）。

| ladder 档 | anchor | rotation | lead | 失败原因（具体对象 + 坐标） |
| --- | --- | --- | --- | --- |
| +1 / 25 | (90,175) | 0 | (90,150)-(90,175) | **run 被 `body(D3)` 切断**（D3 器体 (82.5,161.5,98.5,175.5) 就在脚正上方）；glyph 盒 (74.3,175,105.7,195.5) 压 `body(D3)`；且压 `SEC_SW` 线 (50,190)-(90,190) |
| +1 / 30 | (90,180) | 0 | (90,150)-(90,180) | run 被 `body(D3)` 切断；glyph 盒 (74.3,180,105.7,200.5) 压 `SEC_SW` (50,190)-(90,190) |
| +1 / 10 | (90,160) | 0 | (90,150)-(90,160) | run 通；**glyph 盒 (74.3,160,105.7,180.5) 压 `body(D3)`** |
| +1 / 60 | (90,210) | 0 | (90,150)-(90,210) | run 被 `body(D3)` 切断；glyph 盒压 (58,203.25,144,212.25)、(93.5,225.5,148.5,234.5) |
| +1 / 120 | (90,270) | 0 | (90,150)-(90,270) | run 被 `body(D3)` 切断；glyph 盒压 (58,203.25,144,212.25) |
| +1 / 0 | (90,150) | 0 | 无 lead | 069 sec.8 的落点，**148 已把「站在自己脚上」改成拒绝**，不再考虑 |
| −1 / 25 | (90,125) | 180 | (90,150)-(90,125) | run 被 (88.5,122.5,103.5,131.5) 切断；glyph 盒压 `body(R7)`; 且 **lead 在 (90,145) 穿过 `LED_K` 的线 (125,145)-(85,145)** |
| −1 / 30 | (90,120) | 180 | (90,150)-(90,120) | 同上 + 压 (92.5,93,147.5,102) |
| −1 / 10 | (90,140) | 180 | (90,150)-(90,140) | run 通；glyph 盒 (74.3,119.5,105.7,140) 压 `body(R7)` 与 (88.5,122.5,103.5,131.5)；且 **lead 在 (90,145) 穿过 `LED_K` (125,145)-(85,145)** |
| −1 / 60 | (90,90) | 180 | (90,150)-(90,90) | run 被 (88.5,122.5,103.5,131.5)、(88.5,108.5,161.5,117.5) 切断；glyph 盒压 `body(C11)`+`body(U4)`；lead 在 (90,100) 穿过 `FB_SENSE` (75,100)-(120,100) |
| −1 / 120 | (90,30) | 180 | (90,150)-(90,30) | run 被 `body(U4)`(64.5,-10.5,95.5,80.5) 切断；glyph 盒压 `body(U4)` |
| −1 / 0 | (90,150) | 180 | 无 lead | 同上，148 后不再考虑 |
| 竖杆全灭 → 弯杆 `_flag_pin_lead`（:9234-9241），先本脚方向再另外三个方向 | | | | |
| dir (0,−1) 再 (0,+1)（本脚方向）| 同竖杆的 (90,*) 档，但**没有 25 这一档**（`leads=()`） | 0/180 | 同竖杆 | 同竖杆（`_flag_pin_lead` 把竖杆又走了一遍，实测 trace 里 (90,120),(90,140),(90,90),(90,30) 与 (90,180),(90,160),(90,210),(90,270) 各再现一次） |
| dir (−1,0)，档 = 30/10/60/120，jog ±25、±12.5、0 | corner (60,150)/(80,150)/(30,150)/(−30,150)，anchor 如 (60,175)、(60,125) | 0/180 | (90,150)→corner→竖 | 横段**通**；竖段被**文字盒 (1.0,160,69,169)**（宽 68、高 9，器件值行）与 `body(R9)`、`body(Q1)` 切断；corner (−30,150) 更早死在 `vertex_clear`=假 |
| dir (+1,0)，同上 | corner (120,150)/(100,150)/(150,150)/(210,150) | 0/180 | (90,150)→corner→竖 | 横段**通**；竖段被**文字盒 (106.5,158.5,268,167.5)**（宽 161.5、高 9，最长的一条值行）、(136.5,118.5,206,127.5)、`body(C13)` 切断 |

### B.2 关键算术：**向上的每一档都不可能**（两条独立理由）

- D3 是竖放（`origin=(90,170) pose=rotation=90`），它的 K 脚 `D3.1` 落在 **(90,150)**，
  而**它自己的器体** `body(D3) = (82.5,161.5,98.5,175.5)` 就在同一个 x=90 上、脚正上方 11.5 单位。
- ① 凡 `length > 11.5` 的向上档，**lead 的直线段 (90,150)-(90,150+L) 必然穿过自己的器体** →
  `_span_free(..., boxes=bodies, wire=False)` 直接拒（实测：+1/25、+1/30、+1/60、+1/120 全是这一条）。
- ② 唯一不穿器体的 `length=10` 档，**glyph+名字行盒 (74.3,160,105.7,180.5) 又压在器体上**
  （盒高 20.5 > 净空 11.5）。
- ⇒ **向上方向对该符号该 pose 无解，且与 clearance 松紧无关**：盒高 20.5 是
  `_flag_box` 的几何（glyph + `textmetrics.flag_name_box` + margin），净空 11.5 是器体到脚的距离。
- 向下方向：盒不再压自己的器体，但**每一档长度 ≥ 5 的 lead 都在 (90,145) 穿过 `LED_K` 的线
  (125,145)-(85,145)** —— `LED_K` 恰好从 pin 下方 5 单位横穿 x=90（上方 5 单位还有另一段
  (0,155)-(125,155)）。这是 074 的硬规矩（「不许穿异网线」），不是 clearance。

### B.3 空白量化（实测，`probe_b.log`）

| 量化 | 值 |
| --- | --- |
| pin 半径 40 内的空格点数（5 单位格） | **191 / 289**（66%） |
| 半径 75 内 | **640 / 961**（67%） |
| 半径 150 内 | **2635 / 3721**（71%） |
| pin **正上方**连续可用格 | **2 格 = 10 单位**（第 3 格起就是 `body(D3)`） |
| pin **正下方**连续可用格 | **0 格**（第 1 格 y=145 处就是 `LED_K` 的横线） |
| 把「glyph+名字行盒」整个放上去、且**不压任何 solid** 的向上档 | 只有 length ≥ 85（但那些档的 lead 全被 `body(D3)` 切断） |
| 同条件下可用的**向下**档 | **NONE**（0..150 全被 `body(R7)` / 文字盒 / `body(U4)` / `body(C11)` 占住） |

⇒ 整张纸**空得很**（71% 空白），**不是页面级拥挤**；但 `D3.1` 这个 pin 被**自己的器体（上）**
和**异网 `LED_K` 的绕行（下，各 5 单位）**夹在一条 10 单位宽的缝里。

### B.4 三归因判定：**「布局太挤」（局部）**，不是「求解器过保守」

判据与实测：

1. **不是 clearance 松**：
   - box 测试的**松**的一档已经在用——`fits` 传的是 `margin=0.0` 的紧盒对着 solids，
     全 margin 的盒只对着导线（`_flag_room`，:8368-8409，069 sec.11）。
   - 挡路的对象统计：24 个失败档里，**绝大多数是被器体（`body(D3)`/`body(R7)`/`body(U4)`/`body(C11)`/
     `body(Q1)`）或异网导线挡住**，被「文字盒」单独挡住的只有 −1/60 那类少数。
     其中两个反复出现的裸盒子已确认是**文字行**：(88.5,108.5,161.5,117.5) 正是
     `texts[27] '17.8k 1% TH'`（见 `.tmp_201g/gate_f2.log` 的硬违反清单），
     (1.0,160,69,169) 是 `texts[31] '1k 1% 0805'`。
   - 决定性的反证：**把整个 box 测试对 `SEC_12V` 关掉**（`201G_FORCE=2`，只放宽
     `router.reserved_exempt == 'SEC_12V'` 期间的 `fits`，`_span_free`/`_lead_crossing` 不动），
     竖杆**仍然一个都没过**——因为拦它的是 `_span_free`（run 穿自己的器体），不是 box。
2. **不是文字盒估算**：把 `solids` 里的文字盒全去掉也救不了向上档（②的理由是盒高 20.5 vs 净空 11.5，
   与文字盒无关；`+1/10` 档的失败原因原文就是 `solid body(D3)`）。
3. **放宽 074 会退回 148 拒绝过的形状**：向下唯一能腾出空间的办法是允许 lead 穿过 `LED_K`
   在 (90,145) 的那条线，也就是 `outputs/147/FINDINGS.md` §0.3 岳读成短路的「旗标压线」。
   **不能放宽。**
4. ⇒ **归因 = 布局把器件堆到了这里**：052 的拓扑搜索目标函数里**没有「旗标席位」这一项**，
   于是它把 D3 摆成「K 脚朝下、器体压在脚正上方」，又让 `LED_K` 的绕行从该 pin 上下 5 单位穿过。
   这是「大改：改动面与代价」，符合任务书 §三 的第二条分支。

### B.5 但「修 B」不产出候选——实测（必须让下一批知道）

在 `SEC_12V` 的席位被强行解掉之后（两种强度都试了）：

| 实验 | 做法 | 结果 |
| --- | --- | --- |
| `201G_FORCE=2` | 只在**布线后**那一次 `_rail_flag` 里把 `fits` 恒真（**布线不变**） | 席位落在了弯杆档 (60,125)；拓扑档随后被 readability 闸拒 **27 条硬违反**，其中只有 **3 条**与那面旗有关（`wire-through-body segments[7]+powerSymbols[1]`、`powerSymbols[1] name + parts[R7]`），**其余 24 条是这一版布局自己的导线/文字互压** |
| `201G_FORCE=1` | 连**预留通**也让位（布线因此改变） | 拓扑档被 readability 闸拒 **24 条硬违反**，其中只有 2 条关于那面旗 |

完整 27 条见 `.tmp_201g/gate_f2.log`。⇒ **B 是拓扑档的死因，但不是整页 0 候选的最后一道关。**

---

## 三、一句总判断：**先修 B**

理由一句话：**A 的那条链路（构造阶梯）已经被 201B 的拓扑搜索兜住了**（实测拓扑档
`_relation_failures` = 空，33 条关系全保住），所以 A 不是当前「卡住」的点——它只是让 note 的
统计文字误导人；而 **B 是拓扑档唯一未过的关**，也是 `ok=False` 报告出来的那条 `layout-unsat`。

**但下一批必须把这件事一起排进去**：修完 B 不会立刻出候选——同一档马上会撞上**可读性闸
（27 条硬违反，其中 24 条与旗标无关）**。所以 B 是**必要不充分**；正确的批次切法是
「修 B + 立刻量拓扑档的可读性账」，而不是「修 B 就发版」。

---

## 四、我没测到的 / 读数不确定的地方（如实）

- **没跑任何 pytest**（本批不需要），也没跑 connector / tsc。
- **`201G_FORCE` 两个强度都是我造的旁路**，不是真的修法：它们分别改变了「布线后的旗位」与
  「预留通 + 布线」。**「修完 B 之后拓扑档到底报几条硬违反」的准确值未定**（27 与 24 两个读数
  都包含我伪造的那面旗自己造成的新违规），但量级远大于 0、且绝大多数与旗无关，这一点在两个
  强度下一致。
- **拓扑档的 `_relation_failures` 为「空」是实测**（`probe_a2_dump.log` 末行 `topology-search: CLEAN`），
  但那是**布线前**的关系检查；可读性闸的结果是另一层（B.5）。
- **`near(R15, R3)` 那条关系**：本批只测到它在 `spacing=2.2` 的加宽档是第一冲突，
  未逐条核它的几何是否有解（不在两个疑点内）。
- **两处 docstring 与代码不符**（读到，未修，本批不动 src）：
  ① `_place_chain_and_shelf` 的 docstring（:2887-2888）写着「**Not called by :func:`compile`
  since 201B stage 2**」，但 `_place`（:2875-2879）对每一个非拓扑档都 `return _place_chain_and_shelf(...)`，
  `_build_candidate`（:7008）又对每个档调 `_place` —— 本批实测它在 24 个档里各被调用一次；
  ② 见下一条。
- **`_park_unordered_chain` 的历史注释已过时**（:3470-3480 说 D3「grammar says `near(D3, T1)` and
  nothing else」），现在 grammar 还给了它 `right-of(D3, T1)`（`flyback.py:781-795`），
  于是 D3 永远不进这条 park 分支。**这条是 A 的结构性根因的一半，本批只是读到，未修。**
- **耗时读数**：本批一次编译 9.5–26.8 s（`drop` 实验里删掉 `right-of(D3,T1)` 那次 26.8 s，因为
  D3 被 park 到侧边后布线变重），比 201F 记的 11.05 s 有波动；本批的耗时数字只作参考，**不与
  201F 的 A\* 读数比较**（工作树同时有别的代理在改 `rules/`、`core/partkind.py`）。
- **未做**：`_flag_seat_pins`（:8629-8652）对 `gnd` 类网的就近降级阶梯没测（`SEC_12V` 是 power，
  走 `_power_flag_pin` 的单点答案，本批只覆盖了这条）。
- **本批未执行任何 git 操作、未删除任何文件**；所有临时产物在 `.tmp_201g/`。
