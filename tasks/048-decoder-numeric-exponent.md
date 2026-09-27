# 任务书 048 — 厚声**数字指数**四位场（046 遗留第 2 条的收官）

> 2026-09-27 主代理（Kimi）写。执行者：coder 子代理（`commandcode/deepseek/deepseek-v4.1-flash`）。
> 上游：046 交卷记录遗留第 2 条（`tasks/046-mpn-decoder-gaps.md`：`0603WAF1002T5E` = 10 kΩ、
> `0805W8F1003T5E` = 100 kΩ 仍 UNKNOWN，"留给后续任务书"）。纪律与 046 相同（读数集合 additive、
> 每判据独占 witness、变异 ≥2 且 `cp` 还原、不碰 git/真机/connector/标注 JSON）。

## 一、缺口（病根）

厚声（Uni-Royal）F 档（≤±1%）的**阻值字段是四位**：三位有效数字 + 一位指数，
046 只实现了**字母指数**那一半（`J`=10⁻¹ / `K`=10⁻² / `L`=10⁻³），**数字指数**那一半整个漏着：

| token | 字段 | 值 | 现状 |
|---|---|---|---|
| `0603WAF1002T5E` | `1002` | 100×10² = **10 kΩ** | `mpn_resistance_readings` 返回 `[]`，`mpn_value_code` 返回 `None` → 规则 UNKNOWN |
| `0805W8F1003T5E` | `1003` | 100×10³ = **100 kΩ** | 同上 |
| `0805W8J0103T5E` | `0103` | 010×10³ = **10 kΩ**（5% 档，字段首位写 `0`；厚声订购规则里的**原文示例**就是它） | 同上 |
| `0805W8J0100T5E` | `0100` | 010×10⁰ = **10 Ω** | 同上 |

为什么现有三条读法都读不出：`_e96_reading` 要求 token **以四位数字结尾**（`...T5E` 尾不满足）；
中间字母读法在这串里找不到 `R`/`K`/`M`（`WAF1002T5E` 无该字母）；`mpn_value_code` 的 EIA 三位码
候选被"码后必须是单个字母"的规则挡掉（`1002T5E` 的码后是数字）。所以整批料号落在 UNKNOWN——
046 报告 §六.2 与 017 草稿的"事实 backlog"都记了这块口子（`毕设滤波采样` 板 27 条 UNKNOWN 里
15 条、`毕设FOC驱动板` 9 条里 8 条都是它）。

## 二、修法（形状与读法）

在 046 的字母分支旁加**同族兄弟**（不改 046 那个 regex 与其 witness）：

```
_NUMERIC_EXPONENT_FIELD_RE = re.compile(
    r"^(?:01005|0201|0402|0603|0805|1206|1210|1812|2010|2512)"
    r"[A-Z0-9]{2,4}(\d{3})(\d)T[A-Z0-9]+$"
)
```

- 锚定与 046 完全同构：**封装头 `_SIZE_HEADS`** + 功率/容差区 `[A-Z0-9]{2,4}` +
  三位有效数字 + **一位数字指数** + 卷带尾 `T[A-Z0-9]+$`。
- 读法：`int(figures) × 10^digit`，**加进**读数集合（`readings.setdefault`，按值去重），
  notation 文本 `1002 (numeric-exponent field)`。
- 5% 档（字段首位 `0`）天然被同一条读法覆盖：前导零不改变有效数字
  （`int("010") = 10`），与厚声订购规则的原文示例一致。
- 0 Ω 跳线（`0603WAF0000T5E`）读出 0 → 与既有约定一致地拒绝该读数（"a zero reading is not
  evidence of anything"），整 token 仍 UNKNOWN。

### 与 `_e96_reading` 的重叠分析（任务书要求写清）

两条判据在这族 token 上**互斥**：数值指数分支要求 token 以 `T<卷带码>` 结尾，
而 `_E96_FIELD_RE = (?<!\d)(\d{4})([A-Za-z])?$` 要求以四位数字（后至多一个字母）结尾——
`...1003T5E` 的末尾是 `T5E`，`(\d{4})` 无处安放，故 E-96 对本族**本就不读**（测试里用
"`...T5E` token 的 notation 文本里不出现 `(E-96)`"把这条钉住）。

两者真能同时命中时（构造 token，如 `...1003T5E1234`）读数会**同时进集合**：这正是 046 的
additive 教义（板值自己选），且按**值**去重；对真实的厚声家族，`1003` 无论走哪条都是
100×10³ = 100 kΩ，去重后不留歧义（测试用无尾的 `0603WAF1002` → `[(10000.0, "1002 (E-96)")]`
证明同值）。

### 误吞检查（任务书点名的反例）

- `C1608X5R1V225KT000E`：`1608` **不在** `_SIZE_HEADS` → 天然免疫；测试断言其读数逐项不变
  （`5R1 / 5K / 25K / 225K`，一个 `(numeric-exponent field)` 文本都没有）。
- `FRC0805J471`、`RC0603FR-074K7L`、`JER2512F3R005`、`AR03BTCX5001`、`FRL1210FR400TS`、
  `0603WAF220KT5E`、`0603WAF330JT5E`、`PA50V330M10x15`、`CL10A225KA8NNNC`、
  `CC0603KRX7R9BB104`、`RE2512F3R001`、`HGC1206R5106K500NSPJ` 等全部既有 witness 回归不变。

## 三、witness 与判据独立性

| 判据 | 独占 witness | 删掉判据的可见后果 |
|---|---|---|
| 数值指数分支本身 | `0603WAF1002T5E`（10 kΩ 只能来自它；E-96 与中间字母读法都不读该 token） | 048 测试断言 `[(10000.0, "1002 (numeric-exponent field)")]` 变 `[]` |
| 封装头要求（窄度） | `WAF1002T5E`（无头 → 不读） | 头改可选后该 token 也读出 10 kΩ，断言红 |
| 数字指数语义 | `0805W8F1003T5E`（100 kΩ，指数写错即错位） | 指数改 `-1` 后变 10 kΩ，断言红 |
| 5% 前导零形态 | `0805W8J0103T5E` / `0805W8J0100T5E` | 同一函数，指数错则一起红 |

## 四、验收判据

1. 定向 pytest（`--basetemp=.tmp_pt_048`）全绿：048 测试 + 046/011d/015/043 全部既有测试。
2. 变异 ≥2 全 CAUGHT，`cp` 还原后 sha256 一致（禁用 `git checkout --`）。
3. eval 复跑 holdout + dev（命令同 046）：**检出 42/42 与高优精确 42/42 两条红线不许破**；
   UNKNOWN→OK 转化逐条可解释；破了**停下来报告、不许改标注**。
4. 只动 `src/boardwise/rules/values.py` 与其测试。

## 五、交卷记录

（见文末。）

---

## 交卷（2026-09-27，coder 子代理 / DeepSeek）：**红线破了 → 按纪律停下，实现以 patch 交付，tree 已还原**

### 结论先行

数值指数读法**实现正确**（读数、witness、变异、既有 witness 回归全过），但它把
`毕设滤波采样_2026-09-27`（**holdout、带 oracle 记录**）上 **17 条 UNKNOWN 转成 17 条新 VIOLATION**，
高优精确率 `42/42 = 1.00` → **`42/59 = 0.71`（17 条无 oracle 记录）**。
按任务书 §四.3"破了就停下来报告、不许改标注"，**本实现未落地**：`values.py` 与
`tests/test_011d_rules.py` 已用 `cp` 还原到 046 状态（sha256 见下），实现与测试以 **patch 形态**
交付，落地/不落地由主代理与 oracle 决定。

### 一、改动（patch 形态）

| 文件 | 内容 |
|---|---|
| `outputs/048_numeric_exponent.patch.diff` | 可读 diff（046 状态 → 048 patch）+ 落盘 sha256 + `cp` 落地两行命令 |
| `.tmp_048_patch/values.py` | 落地用整文件：`_NUMERIC_EXPONENT_FIELD_RE` + `_numeric_exponent_reading` + 读数循环一行 + 两处 docstring/注释（＝ `outputs/048_numeric_exponent.values.py`，`outputs/` 是 gitignore 的耐久副本） |
| `.tmp_048_patch/test_011d_rules.py` | 落地用整文件：新增 `test_the_numeric_exponent_field_is_read`，并把 046 测试里"数字指数族保持不读"的两行断言改写成"字母分支的 notation 文本"（否则与 048 直接矛盾）（＝ `outputs/048_numeric_exponent.test_011d_rules.py`） |
| `.tmp_048_values_046state.py` / `.tmp_048_tests_046state.py` | 046 状态备份（还原源） |
| `outputs/048_eval_holdout.{txt,json}` / `outputs/048_eval_dev.{txt,json}` | **patch 态**评测（红线破了的那一组） |
| `outputs/048_eval_reverted_holdout.{txt,json}` / `..._reverted_dev.{txt,json}` | **还原后**评测（= 046 状态基线） |
| `.tmp_048_impact.py` / `.tmp_048_corpus.py` / `.tmp_048_shapes.py` / `.tmp_048_corpus_before.txt` | 一次性探针与语料 dump |

sha256：`values.py` 046 状态 = `3b9f374f9dd582e39d15872fc9667161c7c1c30c3fb3bf95f3d3677e3a6f4d5c`，
patch 态 = `56a71790599c15bc2165f33efd699913ecf9e5f25d7486f17611feacd5572849`；
`tests/test_011d_rules.py` 046 状态 = `ba9f7ca51523dc2d69f75077bd20dee5cc48f0fcbea318257e18996a6e515e0e`，
patch 态 = `3620676cde22452fe848cefd2e13e1418d5e6bbcc0b0719d557b1935f991d572`。
**tree 当前 = 046 状态**（上面两个"046 状态"哈希），048 patch **不在** tree 里。

### 二、新增测试与定向结果（patch 态）

新增 **1** 个测试（`tests/test_011d_rules.py`，48 → 49 def）：

```
patch 态：.venv/Scripts/python.exe -m pytest tests/test_011d_rules.py -q --basetemp=.tmp_pt_048
      → 49 passed
还原后  ：同上 → 48 passed（= 046 状态）
```

测试覆盖：`0603WAF1002T5E`→10 kΩ、`0805W8F1003T5E`→100 kΩ、`0805W8J0103T5E`→10 kΩ、
`0805W8J0100T5E`→10 Ω、`0603WAJ0122T5E`→1.2 kΩ、`WAF1002T5E`→不读（窄度）、
无尾 `0603WAF1002`→E-96 10 kΩ（重叠分析）、`...T5E` token 不出现 `(E-96)`（互斥钉住）、
`0603WAF0000T5E`→不读（0 Ω）、`C1608X5R1V225KT000E` 逐项不变（误吞检查）、
046 字母分支回归、以及规则级 `0805W8F1003T5E` + 100 kΩ → OK。

### 三、变异明细（`cp` 备份还原，每次还原后 sha256 一致）

| # | 变异 | 结果 | 还原 |
|---|---|---|---|
| M1 | 读数循环里删掉 `_numeric_exponent_reading(token)` | **CAUGHT**：048 测试红（1 failed / 48 passed） | sha256 一致 |
| M2 | 指数改 `10.0 ** (int(exponent) - 1)` | **CAUGHT**：048 测试红 **+ 既有毕业板测试 `test_the_graduation_boards_a2b_seven_are_ok_and_the_rule_has_no_violation_left` 红**（毕设FOC 的 100 kΩ 两行被读成 10 kΩ → 10x VIOLATION，2 failed / 47 passed） | sha256 一致 |
| M3 | 封装头改可选（窄度判据失效） | **CAUGHT**：`WAF1002T5E` 也读出 10 kΩ，048 测试红（1 failed / 48 passed） | sha256 一致 |

### 四、eval 前后对比（patch 态 vs 046 状态）

```
holdout  patch 态：  defect detection 42/42 = 1.00 (cross-caught 0, missed 0)
                     hp precision    42/59 = 0.71 (0 contradicted an exception, 17 had no oracle record)
holdout  046 状态：  defect detection 42/42 = 1.00 (cross-caught 0, missed 0)
                     hp precision    42/42 = 1.00 (0 contradicted an exception, 0 had no oracle record)
dev     patch 态：   4/5 = 0.80 / 4/5 = 0.80   —— 与 046 状态逐字相同
UNKNOWN coverage：   116/183 = 0.63  两次相同（毕设滤波采样 仍留 10 条 UNKNOWN，配对未消失）
```

**检出 42/42 未掉**（新增的 17 条不是被注释的 defect，成不了 TP，也没挤掉任何既有 defect）；
**高优精确红线破了**：分母 42 → 59，多出来的 17 条全部 `hp_false_positives_unexplained`。

### 五、UNKNOWN 计数逐板变化（逐条可解释）

| 板 | patch 态 | 046 状态 | 变化说明 |
|---|---|---|---|
| `毕设FOC驱动板_2026-09-17`（holdout） | OK 10 / UNK 47 / VIOL 0 | OK 8 / UNK 49 / VIOL 0 | **UNKNOWN→OK ×2**：`R20`/`R23`（`0805W8F1003T5E`，板值 `100kΩ`）——正确转化，正是本任务想要的 |
| `毕设滤波采样_2026-09-27`（holdout） | **VIOL 19** / OK 3 / UNK 10 | VIOL 2 / OK 3 / UNK 27 | **UNKNOWN→VIOLATION ×17**（下表逐条），红线的唯一来源 |
| `级联多电平-驱动模块_2026-09-27` | OK 22 / UNK 8 / VIOL 0 | 同左（逐字相同） | 046 修好的 8 行不受影响 |
| `级联多电平-主拓扑_2026-09-27` | 0/0/0 | 同左 | 该板无 subject |
| 其余 11 块 | 逐字相同 | — | 全 holdout 报告只有上述行变化 |
| eval 侧 `mpn-undecodable` 事实簇计数 | 101 | 120 | **−19 = 17（毕设滤波采样）+ 2（毕设FOC）**，与逐板数字精确对账 |

17 条新 VIOLATION 逐条（`.tmp_048_impact.py` 输出，板值 vs 解码读数）：

| 位号 | MPN | 板值 | 解码读数 | 倍数 |
|---|---|---|---|---|
| `R2` `R5` | `0805W8J0103T5E` | 33kΩ | 10 kΩ | 3.30x |
| `R30` `R31` `R34` `R35` | `0603WAF1002T5E` | 3.3k | 10 kΩ | 3.03x |
| `R32` `R36` `R38` `R39` `R40` `R42` | `0603WAF1002T5E` | 1k | 10 kΩ | 10.00x |
| `R33` `R37` | `0603WAF1002T5E` | 220 | 10 kΩ | 45.45x |
| `R41` | `0603WAF1002T5E` | 0 | 10 kΩ | 比值无定义 |
| `R43` `R44` | `0603WAF1002T5E` | 470 | 10 kΩ | 21.28x |

**这 17 条是"板子的 MPN 列写错了"，不是解码器错**：该板 15 颗电阻共用**同一个** MPN 字符串
`0603WAF1002T5E`（厚声 10 kΩ），而 `Value` 分别是 3.3k/1k/220/470/0 —— BOM 与原理图确实不一致
（照 BOM 采购会装 10 kΩ）。主代理在 017 草稿 §D.2 已经把这件事登记为"一块空白"
（"`R43`/`R44` 的 `Value` 是 `470`，`MPN` 却是 `0603WAF1002T5E`…登记在此，因为 oracle 若要在
'干净'之外评估覆盖，这是块空白"），**但标注集里没有这 17 行的任何记录**（该板只有
U1/U7/U8 dup、R3/R6 两条 MPN 缺陷、4 条 rc-cutoff observation）。

### 六、给主代理/oracle 的三条路（B/C 两路已实测；A 是算术推算，未跑）

| 路 | 动作 | holdout 检出 | holdout 高优精确 |
|---|---|---|---|
| **A（推荐，红线反而不破；未实测，按 `defects_hinted/hp_tp` 定义推算）** | oracle 把这 17 行注成 **defect**（它们确实是 BOM-原理图不一致）后落地 patch | 42+17 = **59/59 = 1.00** | 42+17 = **59/59 = 1.00** |
| B（**已实测**） | 现在就落地（不等标注） | 42/42 = 1.00 | **42/59 = 0.71**（破红线） |
| C（**已实测**，本交卷的 tree 状态） | 维持现状 | 42/42 = 1.00 | 42/42 = 1.00 |

注：若 oracle 把这 17 行注成 **exception**，该行的 finding 会进 `hp_fp_exception`，分母照样是 59
（`42/59`），仍是 B 的结局——所以**只有注成 defect 才能同时守住两条红线并涨检出**。
A 路要真兑现，落地后还需按 eval 定义复跑核对（本交卷未跑，因为标注不是我的活）。
落 A 的落地命令（`cp` 两行）与 sha256 都写在 `outputs/048_numeric_exponent.patch.diff` 开头。

### 七、遗留

1. **本 patch 未落地**，tree 是 046 状态（两条红线完整）。落地前需 oracle 对上述 17 行表态。
2. 17 行里 `R2`/`R5` 的板值 `33kΩ` 与 MPN 的 10 kΩ 只差 3.30x（刚过 3x 阈值），
   一旦 oracle 裁定"板值对、MPN 写错"，本 patch 照旧会报它们——阈值不改（015 裁决的 3x 是 oracle 定的）。
3 该族还有一条尾巴没做：`0603WAF0000T5E`（0 Ω 跳线）读出 0 被拒 → 仍 UNKNOWN；0 Ω 跳线与
   "读不出"语义上不同，是否单独给一条 `0 (numeric-exponent field)` 读数，留给后续任务书（本次
   按"zero-ohm reading is not evidence"的既有约定处理，未改）。
4. `毕设滤波采样` 板的 `CGA0603X7R104K500JT`（10 颗电容）仍是 UNKNOWN —— 那是**电压尾**形状
   （`104K500`）的白名单口子，与 048 无关，属另一块 backlog。

---

## 落地记录（2026-09-27，coder 子代理）：**已落地**（推翻上文"未落地"状态，调查历史保留）

### 一、oracle 裁决词与落地动作

> oracle xianyuyijinban 2026-09-27 裁决（**方案 A**）：毕设滤波采样 17 颗电阻的 **MPN 列写错 = 真缺陷**，
> `注 defect 落地 048`。原话记录：**"是真缺陷，注 defect 落地"**。

落地动作（主代理指令，逐条执行）：

1. `cp outputs/048_numeric_exponent.values.py src/boardwise/rules/values.py` →
   sha256 `56a71790599c15bc2165f33efd699913ecf9e5f25d7486f17611feacd5572849`（与本任务书 §一 记录的
   patch 态**逐字一致**，无出入）。
2. `cp outputs/048_numeric_exponent.test_011d_rules.py tests/test_011d_rules.py` →
   sha256 `3620676cde22452fe848cefd2e13e1418d5e6bbcc0b0719d557b1935f991d572`（同样一致）。
3. `reviewsets/毕设滤波采样_2026-09-27.json` 的 `items[]` 追加 **17 条 defect**（split_default=holdout，
   故不写 `split` 字段）；`severity` 先在 patch 态 eval 里逐条核对，实际全部是 **WARN**（与既有
   R3/R6 两条同形状）；`(ref, rule_hint, kind)` 与既有 5 条不撞。加载器自验：
   `load_annotations` 无异常、`len(items)` **5 → 22**、`items_for_split('holdout') == 22`、
   `(ref, kind)` 无重复。

### 二、17 条标注清单（ref + 板值 + 解码读数）

| ref | MPN | 板值（`Value`） | 解码读数 | 倍数 |
|---|---|---|---|---|
| `R2` | `0805W8J0103T5E` | 33kΩ | 10 kΩ | 3.30x |
| `R5` | `0805W8J0103T5E` | 33kΩ | 10 kΩ | 3.30x |
| `R30` | `0603WAF1002T5E` | 3.3k | 10 kΩ | 3.03x |
| `R31` | 同上 | 3.3k | 10 kΩ | 3.03x |
| `R32` | 同上 | 1k | 10 kΩ | 10.00x |
| `R33` | 同上 | 220 | 10 kΩ | 45.45x |
| `R34` | 同上 | 3.3k | 10 kΩ | 3.03x |
| `R35` | 同上 | 3.3k | 10 kΩ | 3.03x |
| `R36` | 同上 | 1k | 10 kΩ | 10.00x |
| `R37` | 同上 | 220 | 10 kΩ | 45.45x |
| `R38` | 同上 | 1k | 10 kΩ | 10.00x |
| `R39` | 同上 | 1k | 10 kΩ | 10.00x |
| `R40` | 同上 | 1k | 10 kΩ | 10.00x |
| `R41` | 同上 | 0 | 10 kΩ | 比值无定义 |
| `R42` | 同上 | 1k | 10 kΩ | 10.00x |
| `R43` | 同上 | 470 | 10 kΩ | 21.28x |
| `R44` | 同上 | 470 | 10 kΩ | 21.28x |

note 写法：`R2` 段与 `R30` 段各写**批次说明**（含裁决词与根因：MPN 列写错 / 15 颗共用一个
10 kΩ 料号），其余 15 条为简短引用（各自写清本颗板值）。**未动**该文件的 `notes` 字段与
`observations[]`（主代理指令只要求 `items[]`）。

### 三、eval 实测 vs 推算

命令同 048，落 `outputs/048b_eval_{holdout,dev}.{txt,json}`：

| 指标（holdout） | 046 基线 | 048 patch（未注） | 推算（A 路） | **落地后实测** |
|---|---|---|---|---|
| 检出（injected + native） | 42/42 = 1.00 | 42/42 = 1.00 | 59/59 = 1.00 | **59/59 = 1.00** ✓ |
| 高优精确 | 42/42 = 1.00 | 42/59 = 0.71 | 59/59 = 1.00 | **59/59 = 1.00** ✓ |
| x-catch / missed / 无记录误报 | 0 / 0 / 0 | 0 / 0 / **17** | 0 / 0 / 0 | **0 / 0 / 0** ✓ |
| 毕设滤波采样 `param-value-mpn-match` | 2/2（VIOL 2 / UNK 27） | 2/19（VIOL 19 / UNK 10） | det 17 对应 | **19/19（VIOL 19 / 板级 det 19）** ✓ |
| dev | 4/5 / 4/5 | 4/5 / 4/5 | 逐字不变 | **4/5 / 4/5 逐字不变** ✓ |

**推算全部兑现，无一条不符。**

**UNKNOWN 覆盖实测值 = `114/183 = 0.62`（不是 99）——逐条解释**：

1. 该指标数的是 **(rule × board) 配对**中"至少有一条 UNKNOWN 的配对"数
   （`outcome_pairs` / `unknown_pairs`），**不是 UNKNOWN 条数**。`毕设滤波采样` 即便少掉 17 条
   UNKNOWN，仍剩 10 条（`C1/C2/C8/C9/C11/C12/C77/C78/C79/C80` 的 `CGA0603X7R104K500JT`），
   配对照样成立。
2. 而且**标注根本不影响解码与 outcome**：同树同规则、只把 17 条标注去掉的 A/B 测量
   （`.tmp_048b_ab.py`，in-process，绕开 CLI 快照）得 `114/183` **两边完全相同** →
   048 落地对覆盖率的贡献是 **0**。
3. 与 048 那次的 `116/183` 相比少 2，来源是 **049 的在途解析器改动**（`src/boardwise/parsers/
   schematic.py` mtime 17:34:23，`.tmp_049/schematic_with_p1_ready.py` 17:34:17）：`FPC触屏游戏机`
   板的 `conn-usb-cc-pulldown` 配对由 `3/11` 变 `1/11`（该板 nets 60 → 59，两条 UNKNOWN 变 OK），
   **与 048 无关**。该 A/B 同时复现了 CLI 的两组数字（42/59 → 59/59），互为交叉验证。
4. 真正按预期掉的是 UNKNOWN **条数**：`毕设滤波采样` 的 `param-value-mpn-match` UNKNOWN
   `27 → 10`（−17），eval 侧 `mpn-undecodable` 事实簇 `120 → 101`（−19 = 17 板内 + 2 毕设FOC）。

### 四、定向测试

```
.venv/Scripts/python.exe -m pytest tests/test_011d_rules.py tests/test_annotations.py \
    tests/test_review_eval.py tests/test_017_eval_metrics.py tests/test_injected_variants.py \
    -q --basetemp=.tmp_pt_048
→ 160 passed
```

（`test_011d_rules.py` 49 个 def，含 048 新测试；标注加载器/评测/指标/注入变体全绿。）
未跑全量（主代理统一跑）。

### 五、落地后的状态与遗留

- **048 已落地**：`values.py` 的数值指数读法 + 测试 + 17 条 defect 标注都在 tree 里
  （上面两个 patch 态 sha256 即当前文件哈希）。
- 本任务书 §五"红线破了→未落地"的**调查历史保留**（那是裁决前的真实状态），以本段为准。
- 遗留不变：`0603WAF0000T5E`（0 Ω 跳线）仍拒读；`毕设滤波采样` 的
  `CGA0603X7R104K500JT`×10 仍 UNKNOWN（电压尾形状的 backlog）；`R2/R5` 的 3.30x 刚过 3x 阈值，
  阈值按 015 裁决不动。
- 复核提醒：`outputs/048b_*` 落在 049 在途解析器改动**之后**，它的 FPC 数字与 046 时代基线
  不同是 049 的账；主代理收工后应重跑一次作为最终口径。
