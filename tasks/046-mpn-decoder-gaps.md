# 任务书 046 — MPN 阻值解码器的四个缺口（017 裁决落地）

> 2026-09-27 主代理（Kimi）写。执行者：coder 子代理（`commandcode/deepseek/deepseek-v4.1-flash`）。
> 上游契约：017 评测基线 `outputs/017_eval_holdout.txt`（holdout 高优精确率 42/46 = 0.91）、
> oracle xianyuyijinban 2026-09-27 裁决（`reviewsets/级联多电平-驱动模块_2026-09-27.json` items 0–3 与
> 同目录 triage 草稿）、043 先例（`tasks/043-mpn-value-decode.md`、`mpn_resistance_readings`
> 的"读数集合"哲学）。

## 一、背景

017 的 holdout 分母 46 = 42 TP + 4 **contradicted an exception**。那 4 条全在
`级联多电平-驱动模块_2026-09-27` 一块板上，成对出现：

| 位号 | 板值 | MPN | 规则当时的读数 | 事实 |
|---|---|---|---|---|
| `2R1` `2R2` | 2.2 Ω | `0603WAF220KT5E` | "decodes to 2e+04 Ω" | 厚声厚膜 2.2 Ω ±1%（立创商品页实证） |
| `5kR1` `5kR2` | 5000 Ω | `AR03BTCX5001` | "decodes to 0.03 Ω" | Viking 精密薄膜 5.00 kΩ（`5001` = E-96 四位码） |

oracle 整节裁 **exception**：板值对、**译码器错**。另有两个缺口由 017 草稿正文登记为"译码器局限"
（G3/G4，见下）——它们在本机当前视图口径下不产出 finding，但同一个根因迟早会在别的视图/
别的板上开口，一并修。

**这不是放宽规则，是把错读数修对**：`param-value-mpn-match` 的判定逻辑（幅值阈值 R 3x /
C 25x、UNKNOWN 不产出 finding）一行不动，只修 `src/boardwise/rules/values.py` 的解码白名单。

## 二、四个缺口（病根分析，已实证）

### G1 厚声 `0603WAF220KT5E` = 2.2 Ω ±1%

- **现状**：`mpn_resistance_readings` 把 `220K` 里的 `K` 当中间字母（×1e3），`220` 这个
  run 产生候选 `220`/`20`（去掉前导位），于是读出 220 kΩ 与 20 kΩ；规则取离板值最近的一个
  → 报 "decodes to 2e+04 Ω"，与板值 2.2 Ω 差 9090.91x。
- **事实（厚声订购规则，见 `docs` 之外的外部佐证：厚声贴片电阻命名规则 PDF 与立创/贸泽商品页）**：
  ≤±1% 档的**阻值字段 = 三位有效数字 + 一位指数字符**；指数为小数时写成字母
  **`J` = 10^-1、`K` = 10^-2、`L` = 10^-3**。故 `220K` = 220×10^-2 = **2.2 Ω**，
  同族的 `330J` = 330×10^-1 = 33 Ω（`0603WAF330JT5E`，立创/TME 均标 33 Ω）；
  四位数字形式（`1002` = 100×10^2 = 10 kΩ、`1003`、`2204`）是 E-96 那一路，不在本缺口内。
- **修法**：把这条**字母指数**读法**加进**读数集合（notation 文本 `220K (letter-exponent field)`）。

### G2 Viking `AR03BTCX5001` = 5.00 kΩ

- **现状**：`AR03` 的 `R` 被当中间字母（run 空、fraction=`03`）→ 读出 0.03 Ω；
  四位 E-96 码（前三有效数字 + 第四位幂次）整个解码器不支持。
- **修法**：实现四位 E-96 读法（白名单形状：token 尾部四位数字，或四位数字 + 单个容差字母；
  四位组**不是**封装尺寸、**不以 0 开头**、**是完整数字 run**），读出 `前三位 × 10^第四位`
  （`5001` → 5000 Ω）**加进**集合。既有 0.03 Ω 读数不删（`R47` = 0.47 Ω 是合法形状）。
  同一 token 里四个位以上不同值 → 弃权（一个都不加）。

### G3 Aishi `SPZ1HM100E07O00RAXXX` = 10 µF 聚合物电容

- **现状**：电容路径走 `mpn_value_code`（**单值**，不是集合）：`100` 被当 EIA 三位码 →
  `10×10^0×1e-12` = 10 pF。Aishi SPZ 系列把容量写在**微法**基准上（`100` = 10 µF）。
- **选择：弃权（返回 None → UNKNOWN）**，理由见 §三.3；不加猜测读数。

### G4 FOJAN `FRL1210FR400TS` = 400 mΩ 合金分流电阻

- **现状**：`mpn_value_code` 把 `400` 当 EIA 码读出 40 Ω；`_r_as_decimal_point` 的
  `\d[Rr]\d{1,3}` 拦不住，因为 `R400` 的 `R` 前是字母 `F` 而非数字。
- **修法**：给 `mpn_resistance_readings` 加 shunt 白名单形状
  **容差字母 + `R` + 2~3 位数字**（`[FJKD]R(\d{2,3})`）→ `fraction/10^len` Ω
  （`FR400` → 0.4 Ω）；同时把该形状加进 `_non_eia_notation`，让 `mpn_value_code` 挡住
  `R400` 的 EIA 误读。

## 三、修法选择与判据

### 1. 解码器哲学（043 先例，必须遵守）

`mpn_resistance_readings` 返回**读数集合** `list[(ohms, notation_text)]`：一个 MPN 可能有多种
合法读法（厂商前缀码与长 mantissa 形状不可分），规则拿板子自己声明的值去匹配集合——
**只要集合里有一个读数与板值一致，就不报 VIOLATION**。所以修缺口的正确方向是
**「把正确读数加进集合」**，不是删除现有读数（除非现有读数被证明是荒谬形状）。
读不出的形状必须弃权（空集合 → UNKNOWN），绝不猜。

### 2. 判据必须足够窄（既有 witness 全过一遍）

新判据在**全部** 15 块评测板的 411 条 MPN 上实测（`outputs/046_evidence_corpus_diff.txt`
口径：解码器输出逐 token 对比），只有下列 token 的解码发生变化，其余一字未动：

| token | 变化 | 是否目标 |
|---|---|---|
| `0603WAF220KT5E` | 集合新增 2.2 Ω | ✅ G1 |
| `0603WAF330JT5E` | 集合新增 33 Ω（与既有 EIA 读数同值，只换标签） | ✅ G1 邻证 |
| `AR03BTCX5001` | 集合新增 5000 Ω | ✅ G2 |
| `FRL1210FR400TS` | 集合新增 0.4 Ω；`mpn_value_code` → None | ✅ G4 |
| `SPZ1HM100E07O00RAXXX` | `mpn_value_code` → None | ✅ G3 |
| `TP4056` `XPT2046` `PS7516` `TLE5012BE1000` | 集合新增四位码读数 | ⚠️ 副作用：这四颗是 IC，`_kind_of` 认不出电阻/电容（value 为空且无货架类别）→ 规则**根本不问**解码器，行为不变（已由评测前后逐板计数核对） |

### 3. G3 的选择：弃权，不读数

电容路径是**单值**（`mpn_value_code` → 调用方按 pF 基准解），没有"加进集合"的退路：
把它读成 `100` 只会再得到 10 pF（正是本缺口）。要读出 10 µF 就得新增一条**返回法拉**的
电容值通道（跨契约变更），超出本任务范围；而 oracle 的 exception 裁决只要求"不许报 VIOLATION"，
UNKNOWN 完全满足。**故选择：识别聚合物系列前缀（`SPZ`/`SPA`）→ 整 token 弃权 → UNKNOWN。**
判据取"整 token 前缀"而不是"三位数字前有电压码"这类形状，是因为后者会误伤普通 EIA 电容
（`CC0603KRX7R9BB104` 那类），而前者只吃掉本族料号——代价是"别的聚合物品牌仍读不出"，
如实登记为遗留。

### 4. 既有 witnesses（全部不许破坏；每条都是既有测试的命根）

`FRC0805J471`（471 = 470 Ω EIA）、`RC0603FR-074K7L`（4K7 = 4.7 kΩ，07 是厂商码）、
`JER2512F3R005`（5 mΩ shunt，弃权）、`HGC1206R5106K500NSPJ`（电压尾弃权）、
`PA50V330M10x15`（电解弃权）、`C1608X5R1V225KT000E`（TDK 电压码弃权）、
`CL10A225KA8NNNC`（225 = 2.2 µF）、`CC0603KRX7R9BB104`（BB104 = 100 nF）、
`RE2512F3R001`（R001 = 1 mΩ 弃权）、`0805W8F1003T5E` / `0603WAF1002T5E`（四位**数字**指数族，
本次不动）、`FRC0805F4122TS`、`GRM1885C1H122JA01D`、`CH340G`、`1m0`、`0R0`。

### 5. guard 独立性（values.py 第 65 行的警告照办）

三个既有 guard 必须各自独立、各有独占 witness；新增的两个拒绝理由（shunt 形状、聚合物系列）
同样：每个新判据至少一个**独占**测试用例，删掉判据必须有测试变红（见 §五 变异验证）。

## 四、验收判据

1. **holdout**：`级联多电平-驱动模块` 的 4 条 VIOLATION 消失（x-catch 4 → 0）；
   split totals 高优精确率 `42/46 = 0.91` → `42/42 = 1.00`；**检出 42/42 不许掉任何一条**。
2. **dev**：`ch340g_golden` 的 miss 1 是既有 DRAFT 板缺口，不要求修复；数字若有意料之外的变化，
   停下来报告，**不许改任何标注 JSON**。
3. 定向 `pytest tests/test_011d_rules.py` 全绿（含 4 个缺口的正例 + 每个新判据的独占 witness +
   全部既有 witness 回归）。
4. 变异验证 ≥2：删掉/反转每个新判据 → 对应测试变红；`cp` 备份还原后 sha256 一致
   （**禁用 `git checkout --`**）。
5. 边界：只动 `src/boardwise/rules/values.py` 与其测试；不碰 git、不碰真机/bridge、
   不碰 `connector/`、不改 `reviewsets/*.json` 标注、不动任何规则的判定逻辑。

## 五、交卷记录

（见文末"交卷"节。）

---

## 交卷（2026-09-27，coder 子代理 / DeepSeek）

### 一、改动文件（只动解码器与其测试）

| 文件 | 改了什么 |
|---|---|
| `src/boardwise/rules/values.py` | `mpn_resistance_readings` 新增四个读数形状中的三个（厚声字母指数 `220K`/`330J`、E-96 四位码 `5001`、shunt `FR400`），全部**加进**读数集合、不删既有读数；`_non_eia_notation` 增加 shunt 形状拒绝理由，`mpn_value_code` 增加 `_foreign_unit_code`（聚合物系列）拒绝理由；既有中间字母读法、既有三个 guard 的判定逻辑一字未动 |
| `tests/test_011d_rules.py` | 新增 4 个测试：G1 字母指数（含"没有封装头就不读"的窄度 witness 与四位数字指数族不动的回归）、G2 四位 E-96（含封装守卫 1206/2512、前导零、lookbehind、尾容差字母）、G3 聚合物系列弃权（解码器级 + 规则级 UNKNOWN）、G4 shunt（含 `AR03BTCX5001`/`RC0603FR-074K7L`/`JER2512F3R005` 三个边界邻证 + 规则级 400 mΩ → OK） |
| `tasks/046-mpn-decoder-gaps.md` | 本任务书（病根分析、修法选择、witness 保护清单、验收） |
| `outputs/046_eval_holdout.{txt,json}` / `outputs/046_eval_dev.{txt,json}` | 复跑评测（holdout / dev） |
| `outputs/046_evidence_corpus_diff.txt` | 证据：15 块板 411 条 MPN 的解码器输出前后逐 token 对比 |
| `.tmp_046_corpus.py` / `.tmp_046_shapes.py` / `.tmp_046_values_046backup.py` / `.tmp_046_corpus_*.txt` | 一次性探针、**046 实现版**的 `cp` 备份（变异还原源，非改动前原版；改动前原版只存在于 `outputs/046_evidence_corpus_diff.txt` 的 before 列）与 411 条 MPN 的前后 dump（`.tmp_*` 不入库） |

### 二、G3 的选择与理由

**弃权（`mpn_value_code("SPZ1HM100E07O00RAXXX") → None` → 规则报 UNKNOWN）**，不读 10 µF。理由：

1. 电容路径是**单值**不是集合——`mpn_value_code` 只回三位码字符串，调用方按 **pF** 基准解
   （`decode_eia_3digit(code, 1e-12)`）。回 `"100"` 必然再得 10 pF（就是本缺口）；要读出 10 µF
   必须新增一条返回**法拉**的电容值通道，属跨契约变更，超出本任务范围。
2. oracle 的 exception 裁决只要求"不许报 VIOLATION"，UNKNOWN 完全满足（且 UNKNOWN 不进
   任何精确率分母）。
3. 判据取"整 token 以 `SPZ`/`SPA` 开头"（`_POLYMER_SERIES_HEADS`），而不是按"三位码前的电压码"
   这类结构形状——后者会误伤普通 EIA 电容（`CC0603KRX7R9BB104` 一类）。代价：别的聚合物
   品牌仍读不出，如实登记为遗留。

### 三、新增测试数与定向测试结果

- 新增测试 **4** 个（`tests/test_011d_rules.py`，46 → 48 个 def），其中 `test_...` 共 48 项全绿：
  `.venv/Scripts/python.exe -m pytest tests/test_011d_rules.py -q --basetemp=.tmp_pt_046` → `48 passed`。
- 相邻测试面（评测/标注/规则/编辑回路/事实规则）：`tests/test_017_eval_metrics.py
  tests/test_review_eval.py tests/test_injected_variants.py tests/test_rules.py
  tests/test_016_edit_cli.py tests/test_facts_rules.py tests/test_annotations.py` → `211 passed`。
- 每个新判据的**独占 witness**：G1 = `0603WAF220KT5E`（只有字母指数读法给出 2.2 Ω），
  窄度 witness = `WAF220KT5E`（去掉封装头就不许读出 2.2 Ω）；G2 = `AR03BTCX5001`
  （5000 Ω 只能来自四位码），守卫 witness = `AR03BTCX1206`/`AR03BTCX2512`/`AR03BTCX0500`/`AR03BTCX05001`；
  G3 = `SPZ1HM100E07O00RAXXX`（只有聚合物 guard 拒绝它）；G4 = `FRL1210FR400TS`
  （0.4 Ω 只能来自 shunt 形状），边界邻证 = `AR03BTCX5001`（`A` 非容差字母）、
  `RC0603FR-074K7L`（`R` 后是 `-`）、`JER2512F3R005`（`R` 前是数字，043 既有拒绝维持）。

### 四、变异验证明细（`cp` 备份 + sha256 还原，禁用 `git checkout --`）

| # | 变异 | 结果 | 还原后 sha256 |
|---|---|---|---|
| M1 | 从 `mpn_resistance_readings` 的读数循环里删掉 `_letter_exponent_reading(token)` | **CAUGHT**：`test_the_letter_exponent_field_is_read_as_a_low_ohm_reading` 红（1 failed / 47 passed） | 一致 |
| M2 | 删掉 `_e96_reading(token)` | **CAUGHT**：`test_the_e96_four_figure_code_is_read` 红（并连带 G4 测试中引用 E-96 读数的那条断言，2 failed / 46 passed） | 一致 |
| M3 | `_foreign_unit_code` 体改 `return False`（删掉聚合物 guard） | **CAUGHT**：`test_a_polymer_electrolytic_mpn_is_not_read_as_a_capacitor_code` 红（`mpn_value_code('SPZ…') == '100'`） | 一致 |
| M3′ | 反转该 guard（`return not token.startswith(...)`） | **CAUGHT**（16 failed）：反转后几乎所有 token 都被拒，可见该正是"整 token 拒绝"的开关 | 一致 |
| M4 | 删掉 `_shunt_reading(token)` | **CAUGHT**：`test_the_shunt_field_between_a_tolerance_letter_and_r` 红 | 一致 |
| M5 | 从 `_non_eia_notation` 删掉 `or _SHUNT_FIELD_RE.search(token)` | **CAUGHT**：同上测试红（`mpn_value_code('FRL1210FR400TS') == '400'`） | 一致 |
| M6 | 把 `_LETTER_EXPONENT_FIELD_RE` 的封装头改成可选（窄度判据失效） | **CAUGHT**：`WAF220KT5E` 也读出 2.2 Ω，G1 测试红 | 一致 |

备份文件 `.tmp_046_values_046backup.py`（046 实现版的 `cp` 备份，变异还原源）与还原后的
`src/boardwise/rules/values.py` 逐次 `sha256sum` 一致：
`3b9f374f9dd582e39d15872fc9667161c7c1c30c3fb3bf95f3d3677e3a6f4d5c`。

### 五、eval 前后逐字对比

holdout（`--annotations reviewsets/*.json reviewsets/injected/*.json --split holdout`）：

```
-  split totals (holdout) over 15 board(s), 8 carrying oracle records in this split:
-    defect detection (injected + native): 42/42 = 1.00  (cross-caught 0, missed 0)
-    high-priority precision (ERROR/WARN findings): 42/46 = 0.91  (4 contradicted an exception, 0 had no oracle record)
+  split totals (holdout) over 15 board(s), 8 carrying oracle records in this split:
+    defect detection (injected + native): 42/42 = 1.00  (cross-caught 0, missed 0)
+    high-priority precision (ERROR/WARN findings): 42/42 = 1.00  (0 contradicted an exception, 0 had no oracle record)
```

`级联多电平-驱动模块_2026-09-27`：`findings 0 ERROR / 4 WARN / 10 INFO` → `0 ERROR / 0 WARN / 10 INFO`；
`param-value-mpn-match` 的 `x-catch 4 / hp-prec 0/4` → 全部消失，该规则 OK 18 → 22。
**检出 42/42 一条未掉**。

dev（`--split dev`）split totals **逐字不变**：

```
  split totals (dev) over 15 board(s), 5 carrying oracle records in this split:
    defect detection (injected + native): 4/5 = 0.80  (cross-caught 0, missed 1)
    high-priority precision (ERROR/WARN findings): 4/5 = 0.80  (0 contradicted an exception, 1 had no oracle record)
```

`ch340g_golden` 的 miss 1 仍是那条既有 DRAFT 缺口，未动。UNKNOWN coverage 116/183 = 0.63 两次相同。
未改任何 `reviewsets/*.json`。

### 六、遗留与须知

1. **本次评测跑在一棵同时带 047 在途改动的树上**。`src/boardwise/engines/review.py`（16:20）、
   `engines/review_eval.py`、`rules/i18n.py`（16:33）等文件的 mtime 晚于 017 基线（15:52），
   且仓库里存在 `.tmp_047_backup/`（047 的 `cp` 备份）。逐文件 diff 证实 047 动了
   `_DESIGNATOR_TOKEN`（前缀 1–4 字母 → 1–5 字母）并把 `SCREW` 加入 `DESIGNATOR_PREFIXES`。
   **这解释了报告里 locate 行的漂移**：`conn-duplicate-designators 30/36 → 34/36`（毕设板
   `SCREW1..4` 的 4 条 finding 现在可定位）与总量 `64/80 → 64/76`（我这边少了 4 条 MPN WARN）
   ——**与本次改动无关**（该规则不 import `values.py`）。检出/精确率两项均不受其影响。
   基线 `rulebody ab7b0129` → 本次 `e900bc0c` 也因此同时含两方改动。
2. **四位数字指数族未动**（`0603WAF1002T5E` = 10 kΩ、`0805W8F1003T5E` = 100 kΩ 仍 UNKNOWN）。
   它们是同一家、同一命名规则的另一半，改动会移动 `毕设FOC驱动板`（`0805W8F1003T5E` + 100 kΩ）
   与 `毕设滤波采样` 的 UNKNOWN 计数，超出本任务四缺口范围，留给后续任务书。
3. **四位码读法对 IC 料号有良性副作用**：`TP4056`/`XPT2046`/`PS7516`/`TLE5012BE1000` 现在也有
   四位码读数，但它们的 value 字段为空且无货架类别 → `_kind_of` 为 None → 规则**根本不问**
   解码器；`outputs/046_evidence_corpus_diff.txt` 与两次 eval 逐板计数均可对账。
4. **G3 只覆盖 `SPZ`/`SPA`**：其它聚合物/电解系列的 µF 基准码仍弃权不了也读不对（现状即
   UNKNOWN 或误读，取决于形状）；本机评测板上没有别的样本。
5. **`values.py` 里 `_FOREIGN_UNIT_CODE` 这条路是"拒读"而不是"读对"**：真要把 10 µF 读出来，
   得给电容值新增一条法拉通道（`mpn_value_capacitance_farads` 之类），属跨契约变更，
   oracle 若要这个能力另开任务书。
