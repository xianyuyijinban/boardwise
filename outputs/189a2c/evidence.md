# 527C — 189A2 跨视图检查 7 / 8 / 6 / 2 条的逐条分类

**本批只读代码 + 出证据**：未改任何源码、未跑全量 pytest、未连 bridge、未动编辑器、
零 git 变更。探针脚本在 `.tmp_189a2c/`（不入库）。本轮唯一落盘产物是本文件。

工具：`E:\boardwise\.venv\Scripts\python.exe`（3.14），Windows Git Bash。
全部读数是**当前工作树**（HEAD `09dd343`）在 `tests/fixtures/*.epro2` 上的离线读数。
测量的这几十分钟里同树有并行批在改 `src/boardwise/cli.py`、`core/parts.py`、`rules/facts.py`、
`connector/*`（527B/527D 等），**本批一行未碰**；本检查读的是
`engines/pcbreview.py` 与 `parsers/*`（`git status` 干净、全程未被改动），故读数不受影响。

---

## 0. 结论摘要（先说三件要紧的）

1. **7 / 8 / 6 / 2 不是本检查接线的读数，是一个错配探针的读数。**
   它来自 `outputs/189a2/probe15.py::singles_and_cross`（189A2 当初的测量脚本）：
   它把 **`build_project_model(path).boards[0]`（原理图模型的第 0 块板）** 与
   **`docs[0]`（PCB 文档里的第一个，文件序）** 配对，**没有走 154 的板链**。
   四块板里有两块因此在拿 A 板的 PCB 网表去比 B 板的原理图视图。
   接线后的本检查（`_review_units` + `schematic_board_for`，走 `META board` 链）在同一批夹具上
   实际出声 **7 / 10 / 6+1 / 10 = 34 条**（见 §1.2）。

2. **23 条里 A 类（189A2 要披露的伪网）0 条、C 类（口径外噪声）0 条、B 类（归档自身不一致）13 条，
   另外 10 条是上面的错配（P 类，不是本检查的读数）。**
   判 A/B 的尺子是几何：A 类那个样本（189A2 实板，把 `transform_point` 退回旧序即复现）
   **14 个脚在正确位姿下全部精确落在导线端点上（距离 0.0）**；夹具上这 13 条**没有一个**有这种
   「本该落上、却落偏」的形状（详见 §3、§4）。

3. **把 `min_pins` 抬到 4 = 一条都消不掉（0 条）。** 抬高只会变成钝刀：抬到 17 就会连带吃掉
   09-17 板上那 10 条落在 12 脚器件上的真读数。**不建议抬阈值。**

---

## 1. 哪四块板、怎么确认的

### 1.1 复现 7 / 8 / 6 / 2（错配口径）

跑 `.tmp_189a2c/probe15_clean.py`（= `outputs/189a2/probe15.py` 去掉一行已失效的临时路径）：

```bash
cd E:/boardwise
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .tmp_189a2c/probe15_clean.py
```

输出（节选，逐块板一行）：

```
ProPrj_ROBOT ctrl FOC_2026-09-16.epro2        cross-view lonely   7
ProPrj_毕设FOC驱动板_2026-09-17.epro2           cross-view lonely   8
ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2    cross-view lonely   6
ProPrj_高速电机控制器_2026-09-16.epro2           cross-view lonely   2
（其余 10 块夹具板全 0）
```

即四块板是：

| # | 归档 | probe15 配的是哪一对 | 出声 |
|---|---|---|---|
| 1 | `ProPrj_ROBOT ctrl FOC_2026-09-16.epro2` | PCB1 × 原理图 boards[0]（= 板链指的那块，**配对正确**） | 7 |
| 2 | `ProPrj_毕设FOC驱动板_2026-09-17.epro2` | **PCB3 × 原理图 boards[0]=Board1**（板链说 PCB3→Board3 `7dca2922`） | 8 |
| 3 | `ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2` | PCB1 × boards[0]（= 板链指的那块，**正确**） | 6 |
| 4 | `ProPrj_高速电机控制器_2026-09-16.epro2` | **PCB2 × 原理图 boards[0]=Board1**（板链说 PCB2→Board2 `6e067d9e`） | 2 |

配对错在哪，用板链自己说话（`.tmp_189a2c` 探针输出）：

```
== ProPrj_毕设FOC驱动板_2026-09-17.epro2
   原理图模型里的板（文件序）: d5c055266ef55000(1) 5455a645b144c024(2) 7dca2922104db3df(3)
   PCB 文档: PCB3 link=7dca2922104db3df | PCB1 link=d5c055266ef55000 | PCB2 link=5455a645b144c024
== ProPrj_高速电机控制器_2026-09-16.epro2
   原理图模型里的板: d4e25055678bdfd7(1) 6e067d9e017e2d90(2)
   PCB 文档: PCB2 link=6e067d9e017e2d90 | PCB1 link=d4e25055678bdfd7
```

两块多板工程里 `docs[0]` 都**不是**板链指的那份（09-17 的 PCB 文档文件序是 PCB3/PCB1/PCB2），
所以 probe15 的 `boards[0] × docs[0]` 在 2 号、4 号板上都是跨板错配。

> 顺带：这条错配读数还写进了
> `src/boardwise/engines/pcbreview.py::cross_view_lonely_pins` 的 docstring
> （「of the 23 rows this check reports across the 14 fixtures」）
> 与 `PROGRESS.md` / `tasks/TASKMAP.md` / `tasks/SCHEDULE.md` 里的 7/8/6/2。
> 本批**未改**这些文件（任务书禁改）——请主代理裁要不要连带更正成 34 / 5 块板入口。

### 1.2 接线后的真读数（走板链，`checkup --file` 的口径）

```bash
# 逐脚读数（直接调 cross_view_lonely_pins + schematic_board_for）
PYTHONIOENCODING=utf-8 .venv/Scripts/python.exe .tmp_189a2c/final.py
# 端到端（报告里读到的那一份）
.venv/Scripts/python.exe -c "import sys;sys.path.insert(0,'src');from boardwise.cli import main;\
sys.argv=['boardwise','checkup','--file',r'tests/fixtures/<归档>','--out',r'.tmp_189a2c/out_x'];\
main()"
```

| 归档 | 板入口 | `crossView.lonely` | 逐脚 |
|---|---|---|---|
| ROBOT ctrl FOC | PCB1 | **7** | U1.8/9/10/11/18/19/20 |
| 毕设FOC驱动板_2026-09-17 | PCB3 | **10** | U1.3/4/7/8/11/12、U2.2/4/6/10 |
| 毕设FOC驱动板_2026-09-17 | PCB1 / PCB2 | 0 / 0 | — |
| 毕设FOC驱动板_v1.0.0 | PCB1 | **6** | U10.6/8/9/11/14/16 |
| 毕设FOC驱动板_v1.0.0 | PCB2 | **1** | CN2.5 |
| 高速电机控制器 | PCB2 | **10** | U18.6/8/9/11/14/16、U2.5/7、U4.7/8 |
| 高速电机控制器 | PCB1 | 0 | — |
| 其余 11 块夹具板 | — | 0 | — |

**合计 34 条，落在 4 个归档的 5 个板入口上。** 报告抬头那行的实测样子（`.tmp_189a2c/out_*/report.md`）：

```
> … 原理图/PCB 两视图网表对不上（189A2 一致性检查，只查 ≥3 脚器件）：PCB1：7 个引脚
> （U1.8、U1.9、U1.10、U1.11、U1.18、U1.19…）；… —— 这些引脚在原理图视图里是单成员网…
> 原理图解析漏接（如镜像器件引脚落位错——189A2 就是这个形状）与 PCB 档未同步
> （原理图改过但没重排板，017）都会造成它，两侧都不是天然权威，逐条人工核
```

（`cli._note_cross_view_lonely` 每板只列前 6 个位号，超出打 `…`；逐条读数在
`report.json → pcb_review.boards[].crossView.lonely`。**报告本身不区分 A/B** —— 它把两种成因
并列写在同一条 note 上，这正是 §3.3 要答的那一问。）

---

## 2. 23 条逐条表

分类口径（本表用）：

- **A** = 189A2 要披露的伪网：某个位姿下这个脚**本该落在原理图自己的导线上**，工具没落上 → 该报。
- **B** = 归档自身不一致：原理图视图**读得没错**（脚落在图纸给它画的位置上，或图纸根本没画线），
  两个视图的网表真的不同 → 该报，但报告没把它与 A 分开。
- **C** = 口径外的真连接（2 脚被动件的镜像/翻转、或两侧网名只差大小写/`$1N` 前缀而实为同一根导线）→ 噪声。
- **P** = 本行不是本检查的读数（probe 把 PCB 文档配到了别的板的原理图上）。

| # | 板（归档 / 板入口） | 器件.脚 | 原理图网（成员数） | PCB 网 | PCB 侧成员数 | 分类 | 一句判据 |
|---|---|---|---|---|---|---|---|
| 1 | ROBOT ctrl FOC / PCB1 | U1.8 | `NET42` (1) | `TIM1_CH1` | 3 | **B** | 图纸该脚**无导线**（最近线端 10＝1 格），且原理图侧同名网 `TIM1_CH1`={DRV1.27,U1.44} 恰为 PCB 网去掉此脚 |
| 2 | ROBOT ctrl FOC / PCB1 | U1.9 | `NET43` (1) | `TIM1_CH2` | 3 | **B** | 同上（最近线端 20）；同名网 → 只差此脚 |
| 3 | ROBOT ctrl FOC / PCB1 | U1.10 | `NET16` (1) | `TIM1_CH3` | 3 | **B** | 同上（30）；同名网 → 只差此脚 |
| 4 | ROBOT ctrl FOC / PCB1 | U1.11 | `NET17` (1) | `FOC_EN` | 5 | **B** | 同上（40）；同名网 `FOC_EN`={DRV1.22,24,26,U1.33} → 只差此脚 |
| 5 | ROBOT ctrl FOC / PCB1 | U1.18 | `NET22` (1) | `NSLEEP` | 3 | **B** | 同上（10）；同名网 → 只差此脚 |
| 6 | ROBOT ctrl FOC / PCB1 | U1.19 | `NET23` (1) | `NRESET` | 3 | **B** | 同上（14.14）；同名网 → 只差此脚 |
| 7 | ROBOT ctrl FOC / PCB1 | U1.20 | `NET25` (1) | `VBUS` | 5 | **B** | 同上（10）；同名网 `VBUS`={C11.1,R6.2,R7.1,U1.37} → 只差此脚 |
| 8 | 毕设FOC驱动板_2026-09-17 / **PCB3×Board1(错配)** | U1.1 | `None` (0) | `GHA` | 2 | **P** | 板链说 PCB3→Board3；此行拿 3 号板的 PCB 比 1 号板的原理图，两侧不同板 |
| 9 | 同上 | U1.2 | `None` (0) | `GHB` | 2 | **P** | 同上 |
| 10 | 同上 | U1.3 | `None` (0) | `MOTA` | 12 | **P** | 同上 |
| 11 | 同上 | U1.4 | `None` (0) | `MOTB` | 12 | **P** | 同上 |
| 12 | 同上 | U1.5 | `None` (0) | `GLA` | 2 | **P** | 同上 |
| 13 | 同上 | U1.7 | `None` (0) | `IA+` | 7 | **P** | 同上 |
| 14 | 同上 | U1.8 | `None` (0) | `IB+` | 7 | **P** | 同上 |
| 15 | 同上 | U1.9 | `None` (0) | `IA+` | 7 | **P** | 同上 |
| 16 | 毕设FOC驱动板_v1.0.0 / PCB1 | U10.6 | `SHA` (1) | `MOTA` | 10 | **B** | 脚**精确落在自己的 36 单位网络标签引线上**（`NET` 标签 `SHA`），同名网 `MOTA` 9 成员 = PCB 网去掉此脚 |
| 17 | 同理 / PCB1 | U10.8 | `SLA` (1) | `IA+` | 6 | **B** | 同上（标签 `SLA`）；同名网 `IA+` → 只差此脚 |
| 18 | 同理 / PCB1 | U10.9 | `SLB` (1) | `IB+` | 6 | **B** | 同上（`SLB`）；同名网 `IB+` → 只差此脚 |
| 19 | 同理 / PCB1 | U10.11 | `SHB` (1) | `MOTB` | 10 | **B** | 同上（`SHB`）；同名网 `MOTB` → 只差此脚 |
| 20 | 同理 / PCB1 | U10.14 | `SHC` (1) | `MOTC` | 10 | **B** | 同上（`SHC`）；同名网 `MOTC` → 只差此脚 |
| 21 | 同理 / PCB1 | U10.16 | `SLC` (1) | `IC+` | 6 | **B** | 同上（`SLC`）；同名网 `IC+` 只有 {R15.1}，PCB 侧另 4 个同伴在原理图网名 `Symbol` 上（图纸侧连法也不同） |
| 22 | 高速电机控制器 / **PCB2×Board1(错配)** | U1.1 | `None` (0) | `MOTA` | 15 | **P** | 板链说 PCB2→Board2；此行拿 2 号板的 PCB 比 1 号板的原理图 |
| 23 | 同上 | U1.2 | `None` (0) | `MOTA` | 15 | **P** | 同上 |

**核实过、没出现的东西**：

- 23 条里**没有 2 脚被动件**（`compPins` 分别是 64 / 100 / 33；最小的是 v1.0.0 PCB2 的 CN2=8 脚，
  不在 23 条内），所以 C 类的第一支（2 脚件）**0 条**。
- 23 条里**没有「网名只差大小写 / `$1N` 前缀」的行**（`NET42` vs `TIM1_CH1`、`SHA` vs `MOTA`…都不构成
  同一根导线的两个名字），C 类第二支也 **0 条**。
- 23 条里**没有一条落在 `unproven_nets` 上**，也没有一条点名「原理图器件根本没有的脚」
  （与 docstring 的说法一致，这两条过滤在这批夹具上是空操作）。

---

## 3. 三问的答案

### 3.1 三类各多少条？按板分别多少？

| 分类 | 合计 | ROBOT(7) | 09-17(8) | v1.0.0(6) | 高速(2) |
|---|---|---|---|---|---|
| **A** 真伪网（该报） | **0** | 0 | 0 | 0 | 0 |
| **B** 归档不一致（该报，报告未区分） | **13** | 7 | 0 | 6 | 0 |
| **C** 口径外噪声 | **0** | 0 | 0 | 0 | 0 |
| **P** 错配读数（不是本检查的读数） | **10** | 0 | 8 | 0 | 2 |

按**接线后的真读数**（34 条，5 个板入口）重算：**A 0 / B 34 / C 0**——
09-17 PCB3 的 10 条与高速 PCB2 的 10 条、v1.0.0 PCB2 的 1 条全是 B 型，形状与上表 16–21 行同族
（脚落在自己的网络标签引线上：`SHA/SHB/SLA/SLB/IA-/IB-/IC-/IC+/SLC/SHC/SPI3_MISO`）。

### 3.2 把 `min_pins` 抬到 4 能消掉几条？消掉的是 A 还是 C？

**0 条。** `.tmp_189a2c/sweep.py` 的实测（列＝`min_pins`，格＝该口径下该板入口的出声道数）：

```
case                                              mp=3 mp=4 mp=5 mp=6 mp=10 mp=17 mp=32 mp=33 mp=34 mp=65 mp=101
ROBOT ctrl FOC #PCB1 (板链)                          7    7    7    7     7     7     7     7     7     0      0
09-17 #PCB3 (probe 错配)                             8    8    8    8     8     8     8     8     8     8      0
v1.0.0 #PCB1 (板链)                                  6    6    6    6     6     6     6     6     0     0      0
高速 #PCB2 (probe 错配)                              2    2    2    2     2     2     2     2     2     2      0
09-17 #PCB3 (板链)                                  10   10   10   10    10     0     0     0     0     0      0
高速 #PCB2 (板链)                                   10   10   10   10    10     6     6     6     0     0      0
v1.0.0 #PCB2 (板链)                                  1    1    1    1     0     0     0     0     0     0      0
```

- `mp=4/5/6/10` 与 `mp=3` **逐格相同**：这批读数全落在 12 / 33 / 64 / 100 脚器件上，
  最小的 8 脚件（v1.0.0 的 CN2）也不受影响。
- **消不掉 C（本来也没有）**，能消掉的只有**真读数**：`mp=17` 一把抹掉 09-17 板链口径的
  全部 10 条（那 10 条落在 12 脚器件上），`mp=34` 抹掉 v1.0.0 PCB1 的 6 条（U10 是 33 脚）。
- 结论：**抬 `min_pins` 是坏主意**——它一条噪声都消不掉，只是在某个阈值上开始切掉真发现，
  而且切法跟「哪边对」毫无关系（12 脚的 U1 和 33 脚的 U10 是同一类差异）。
  岳 10-19 已裁「保持 `CROSS_VIEW_MIN_PINS = 3`」，本批的测量**支持这个裁定**。

### 3.3 便宜且不撒谎的降噪办法

先说两个**被数据否掉**的便宜办法：

- **按封装引脚数排除 2 脚件**：`min_pins=3` 已经在做，实测**0 条**受影响 → 是空操作。
- **只在「同名网对」之间报**（即要求原理图里也有一个与 PCB 网同名的网）：
  在 23 条上它会留下 13 条（7 ROBOT + 6 v1.0.0），看起来干净；
  **但它在 A 类样本上同样留下 9 条**——见 §4 的反例实测。它不是降噪，它是**换了一个不成立的判据**。

**推荐（一个）：不改判据、不加分级——改的是「测量与措辞」，两件事：**

1. **把板链修进测量脚本，并把 7/8/6/2 更正为 34 条 / 5 个板入口**（`PROGRESS.md`、
   `tasks/TASKMAP.md`、`tasks/SCHEDULE.md` 与 `pcbreview.py` docstring 里那三处）；
   本批**不动**这些文件，交主代理裁。
   理由：那 10 条错配读数现在被当成「夹具上的既存差异」在账本上挂着，而它们根本不是这个检查的
   输出；账本错会一路传到下一次「嫌吵就抬阈值」的裁决上。

2. **在 note 里把两类成因分成两句、并给出可操作的界线**（不改输出行、不丢任何一条）：
   现在这条 note 把「解析漏接」与「PCB 未同步」并列成一句无差别的话，读者拿不到下一步动作。
   便宜且不撒谎的界线**只有一条**：**这个脚在当前位姿下有没有落在图纸自己的导线上**——
   `cross_view_lonely_pins` 里已经有 `schematicMembers` 与 `schematicNet`，再加两个测量
   （脚 tip 是否精确落在某根导线端点上；该脚所在元件在本板的落线率）就能分开：
   - 「**落上了、但网名/成员不同**」＝图纸把这一脚放在别的网名上（B 型：归档不一致）→
     报告可以说「图纸侧这一脚在 `<schNet>`，PCB 侧在 `<pcbNet>`，两侧连法不同」；
   - 「**没落上，且该脚所在元件的其它脚落线正常**」＝图纸没给这一脚画线（B 型，017 的陈旧板）；
   - 「**没落上，且该元件整块摆放的落线率异常**」＝落位嫌疑（A 型，189A2 的形状）→ 这才是
     「逐条人工核、优先看解析」的那一句。
   落地成本：`cross_view_lonely_pins` 内部本来就持有 `schematic`（元件引脚）与几何，
   但要拿到「导线端点集合」需要把 parser 的 wire 几何传进来——**这不是三行改动能做的**，
   所以本批只出证据，方案请主代理裁。

**它会不会顺带吃掉 A 类的真发现？** 不会——上面两条都不删行。
但它**必须**选对界线：任何**基于网名/成员关系的**便宜判别式都会把 A 吞掉（§4），
只有**几何落线**这一条尺子能分开。

---

## 4. 反例风险实测：A 类样本长得和 B 类一模一样

189A2 的实板样本还在 `.tmp_bug98b/`（只读、不入库、文件名不进本文件）。
把它现在的树读数拿来看是 **0 条**（修复已生效），所以改用**退回旧序**复现那 14 条 A 类读数
（`.tmp_189a2c/real_old.py`，`_transform_point` 换成 `CCW∘镜像` 的旧复合序）：

```
rows: 14
  BT1.1  compPins=3  schNet=NET2   1  pcbNet=ACL     6   sameNameNet=True  isPcbMinusPin=True
  BT1.2  compPins=3  schNet=NET3   1  pcbNet=HL      3   sameNameNet=True  isPcbMinusPin=True
  BT1.3  compPins=3  schNet=NET4   1  pcbNet=$1N120  3   sameNameNet=False isPcbMinusPin=False
  DB1.1  compPins=4  schNet=NET13  1  pcbNet=$1N108  2   sameNameNet=False isPcbMinusPin=False
  DB1.2  compPins=4  schNet=NET14  1  pcbNet=HV      8   sameNameNet=True  isPcbMinusPin=True
  DB1.3  compPins=4  schNet=NET15  1  pcbNet=$1N109  2   sameNameNet=False isPcbMinusPin=False
  DB1.4  compPins=4  schNet=NET16  1  pcbNet=GND    40   sameNameNet=True  isPcbMinusPin=False
  LS1.1  compPins=4  schNet=NET25  1  pcbNet=$1N108  2   sameNameNet=False isPcbMinusPin=False
  LS1.4  compPins=4  schNet=NET26  1  pcbNet=$1N109  2   sameNameNet=False isPcbMinusPin=False
  P7.1   compPins=7  schNet=NET27  1  pcbNet=+12V   14   sameNameNet=True  isPcbMinusPin=True
  P7.2   compPins=7  schNet=NET28  1  pcbNet=LED3    2   sameNameNet=True  isPcbMinusPin=True
  P7.3   compPins=7  schNet=NET29  1  pcbNet=LED2    2   sameNameNet=True  isPcbMinusPin=True
  P7.4   compPins=7  schNet=NET30  1  pcbNet=LED1    2   sameNameNet=True  isPcbMinusPin=True
  P7.5   compPins=7  schNet=NET31  1  pcbNet=GND    40   sameNameNet=True  isPcbMinusPin=False
with same-name net: 9
with same-name net == pcb-minus-pin: 7
```

这 14 条里 **7 条**满足「原理图侧有同名网、且成员恰为 PCB 网去掉这个脚」——与 ROBOT 的 7 条
（表 1–7 行）**在名字与成员关系上不可分辨**。所以：

> **网名/成员关系这一层分辨不出 A 与 B。** 拿它当降噪判据，会静默吞掉一半真伪网。

而**几何落线**这一层分得开（`.tmp_189a2c/real_geom.py`，同 14 个脚）：

| 脚（实板旧序=A 类） | 新旧序下的落线距离 | 修复后（新序） |
|---|---|---|
| BT1.1/1.2/1.3 | 50 / 25 / 68.007 | **0.0 / 0.0 / 0.0** |
| DB1.1/1.2/1.3/1.4 | 9.055 / 21.84 / 31.89 / 32.28 | **0.0 ×4** |
| LS1.1/1.4 | 0.0 / 0.0（rot 180、未镜像 → 两种复合序同值） | 0.0 |
| P7.1–P7.5 | 60 ×5 | **0.0 ×5** |

而夹具那 13 条 B 型的实例位姿**全是 `rot 0°`、`isMirror=false`**（几何探针逐条打印），
纯平移下两种复合序给出同一个点——189A2 那类缺陷在夹具上**物理上不可能产生读数**：

```
ProPrj_ROBOT...              U1.8  rot=0 mirror=False tip=(210,1000) 最近线端=10.0
ProPrj_毕设FOC驱动板_v1.0.0   U10.6 rot=0 mirror=False tip=(1055,855) 最近线端=0.0（落在 SHA 引线上）
ProPrj_毕设FOC驱动板_09-17    U1.3  rot=0 mirror=False tip=(169,369)  最近线端=0.0（落在 SHA 引线上）
ProPrj_高速电机控制器         U18.6 rot=0 mirror=False tip=(201,398)  最近线端=0.0（落在 SHC 引线上）
```

（同一份测量也解释了为什么旧序与新序在 14 块夹具上读数**完全一致**：夹具里没有镜像 90°/270°
摆放，这正是 189A2 藏了那么久的原因。）

### 4.1 一个没能一锤定音的细节（ROBOT 的 7 条）

ROBOT 那 7 个脚的 tip **不是**落在任何 `WIRE` 组上（距离 10–40 单位），
但 `.tmp_189a2c/around2.py` / `lead.py` 量到：**恰好在这 7 个脚的位置各有一条 48 单位长、
形状与同符号其它引线完全一样的 `LINE`**（如 `(210,1000)→(162,1000)`），
而它们**没有 `WIRE` 头记录、也没有 `NET` 标签属性**（同符号其它脚的引线都有：
`y=1010` 有 `WIRE fffa3f5ae13a` + 标签 `NRST`）。它们成两团出现在串流里
（`raw2.py` 记录 4175–4179 的 4 条 + 4225–4228 的 3 条，各带一个
`ELE_PLACEHOLDER {dataType:"WIRE", max:N}`），形状像一次增量保存的改写块。

- 这对本批分类**不构成威胁**：按 040 §WI-2，只有 `WIRE` 头拥有的组算铜；
  而这 7 条即便被当成导线，**另一端（162/166, y）也是悬空的**——最近的另一根导线在 10 单位外，
  所以并进去仍是一个单成员网，读数**不会变**（只是网名会从 `NET42` 变成「无名」）。
- 但它是本批**没查清**的一点：这 7 条到底是「被增量保存改写成无头形态的真导线」，
  还是「符号/图形残留」，本批只有串流层面的形状证据，没有编辑器侧（`sch.netlist`）的对照。

---

## 5. 不确定 / 没查清的点

1. **A 与 B 的物理归属**：本批只能证明「工具读数与图纸一致」（B），**不能**证明
   「哪一边的设计是新的」。按 017 的口径，PCB 档是板子自己那份拷贝，两边都可能陈旧。
   没有编辑器侧 `sch.netlist` 的对照，也没有版本历史可比，本批不裁哪边对。
2. **ROBOT 那 7 条无头 48 单位引线**（§4.1）：形状证据在手，语义未定；需要一次编辑器侧读
   （`sch.netlist` 或 `doc.list` 后的网表回读）才能判它是导线还是图形。
3. **原理图侧没有「编辑器算出来的网表」可比**：`.epro2` 里只有 PCB 文档带 `PAD_NET`
   （`epru.py` 的 `parse_pad_net`），原理图侧没有等价物，所以「图纸的正确网表」只能靠几何重建。
   本批的「工具读得没错」结论就是建立在这个几何重建上的。
4. **`checkup --file` 的报告 note 每板只列前 6 个位号**（`cli._note_cross_view_lonely`），
   ROBOT 的 7 条因此显示成 6 + `…`。这不是缺陷（逐条在报告 JSON 里），只是读数时容易数错。
5. **本轮未跑**：全量 pytest、connector / dsh-plugin / tsc 三线、bridge、编辑器 —— 按本批红线。
   所有断言都是单进程只读探针的读数。
6. **没改任何源码/测试/既有文档**；`PROGRESS.md` / `tasks/TASKMAP.md` / `tasks/SCHEDULE.md` /
   `docs/roadmap.md` / `pcbreview.py` docstring 里那三处 7/8/6/2 与「23 rows」的说法**仍在**，
   请主代理裁是否更正。

---

## 6. 复现清单（全部单进程、只读、无 bridge）

| 脚本（`.tmp_189a2c/`） | 作用 | 关键读数 |
|---|---|---|
| `probe15_clean.py` | 复现 7/8/6/2（= 189A2 的 `probe15.py` 去掉失效路径） | 7 / 8 / 6 / 2 |
| `probe_boards.py` → `boards.json` | 14 块夹具 × 每板 `cross_view_lonely_pins` | 4 个归档非零 |
| `final.py` → `final.json` | 23 条 + 真读数的逐条明细（网名、成员、同名网判定） | 表 §2、§3 |
| `sweep.py` | `min_pins` 3→101 扫描（7 个板入口） | §3.2 |
| `geom2.py` / `tjunction.py` | 逐脚 tip 落线距离、引线组、与其他导线的间距 | §4 |
| `around2.py` / `around.py` / `lead.py` / `raw2.py` | 串流层证据（无头 `LINE`、`WIRE` 头、`NET` 标签、`ELE_PLACEHOLDER`） | §4.1 |
| `real_old.py` / `real_geom.py` | 189A2 实板样本（旧序＝A 类 14 条）的网名/成员与几何对照 | §4 反例 |
| `checkup --file … --out .tmp_189a2c/out_*` | 端到端口径验证（报告 note + `crossView`） | §1.2 |
