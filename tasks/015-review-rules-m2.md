# 任务书 015 — 审查规则 M2：MPN 解码器越界修复 + decoupling-per-ic 退役 + 晋级复跑

> 2026-09-21 主代理（Kimi）写。执行者：coder 子代理（默认 `commandcode/deepseek/deepseek-v4.1-flash`）。
> 上游契约：`tasks/011-review-rules-m1.md`（晋级判据 §十、交卷记录 E/F/H/I）、`tasks/014-bishe-annotation-closeout.md`（签名落地 + 晋级判定表）。

## 一、背景（为什么有 M2）

M1 晋级判定（014 交卷，holdout = 2 注入板 + 毕设板）：

| 指标 | 014 基线 | 门槛 |
|---|---|---|
| 注入+原生缺陷检出 | 33/33 = 1.00 | ≥90% ✓ |
| 高优确定问题精确率 | 33/46 = 0.72 | ≥95% ✗ |

分母 46 的构成：**33 TP**（30 重复位号 + B1 缺 bulk 电容 + 2 注入）、**10 exception**（A2，oracle 已裁"规则报错了"）、**3 B2 observation**（decoupling-per-ic 的 L1 启发式噪声）。oracle 对两类的裁决都指向 M2：

- **A2a 解码器越界（3 条）**：`R43`（MPN `JER2512F3R005` 的 `3R005` 被当 EIA 误读）、`C115`/`C116`（电解料号 `PA50V330M10x15` 的 `330M`）。board24v 的 15 条 MPN 矛盾同归因（011e 记录：四位 `R001` 记法、`K500N` 耐压码、电解料号非 EIA）。
- **A2b 解码正确但位置不敏感（7 条）**：`U10`/`U14`（MPN 解出 470Ω vs value 1kΩ）、`C28`/`C29`/`C36`/`C42`/`C44`（100nF vs 2.2µF/10nF）。oracle 原话"这个本没错，不要定的太死" ⇒ 需要"矛盾幅度"概念。
- **B2（3 条）**：oracle 裁 observation"记一次"，**M2 退役 `decoupling-per-ic`**（011f 记录 G、014 晋级判定表均记此账）。

014 的换算：修解码器（−10）、退役 decoupling（−3）⇒ **33/33 = 1.00**。本任务书把这笔账兑现。

## 二、范围

### 批①（无阻塞，本任务书直接执行）

**① MPN 解码器越界修复**（`param-value-mpn-match`，`src/boardwise/rules/params.py`）

- 非 EIA 编码**不得硬解**：电解料号（`PA50V330M10x15` 的 `330M`）、耐压码（`K500N`）、四位 R 记法（`JER2512F3R005` 的 `3R005`）等形态，解码器返回"不可解"（None），规则输出 **UNKNOWN**（不产出 finding），而不是今天的 VIOLATION。
- 严格 EIA 形态（三位码、R 小数点记法等既有已支持形态）解码行为**一字不变**。
- 断言：毕设板 A2a 三条（R43/C115/C116）从 VIOLATION 变 UNKNOWN；board24v 对应行同类变化（该板不在 eval split 内，出前后对比清单即可）。

**② `decoupling-per-ic` 退役**

- 从 `BUILTIN_RULES`（`src/boardwise/engines/review.py`）移除；**规则类与单测保留**（退役 ≠ 删代码，先例：011d `v3-decap-missing` 变体退役——留盘、可复检、不进 eval）。
- 移除处加注释指向 011f B2 裁决与本任务书；新增测试钉住"`BUILTIN_RULES` 不含 `decoupling-per-ic`"。
- 毕设板标注集 B2 的 observation 记录**不动**：hint 变 unregistered 后由 014 的 cross-match 语义自然承接（unregistered hint 不参与 cross 配对、不进 M1 分母），报告"unregistered"栏列出即"退役留史"。
- README 中英两段规则列表 15 → 14 条同步（去掉 decoupling 行，其余不动）。

**③ 复跑 eval 对账**（dev + holdout，同 014 口径）

预测（任务书断言，实测偏离必须解释）：

| 指标 | 014 基线 | 批①预测 | 依据 |
|---|---|---|---|
| dev 检出 | 5/5 | **5/5 不变** | 注入变体不碰这两条规则 |
| holdout 检出 | 33/33 | **33/33 不变** | A2a/B2 本就不是 defect |
| holdout hp-prec | 33/46 = 0.72 | **33/40 = 0.825** | −3（A2a→UNKNOWN）−3（B2 退役） |
| 毕设板 exception | 10 | **7**（A2b 还在） | A2a 三条不再产出 finding |
| dev hp-prec | 5/5 | 以复跑为准 | 若黄金/注入板上有 decoupling/mpn finding 会动，如实报 |

### 批②（oracle 已裁：**A，分类阈值 R 3x / C 25x**，2026-09-21）

A2b 的"矛盾幅度"。裁决链：oracle 先裁 **A**（幅度阈值 + 重签注入变体）；主代理把 A 放到实测数据上复算，发现**单一全球阈值不成立**（见下"决策数据"：五颗电容 10x–22x 在 3x 下照样报，晋级仍破）⇒ oracle 二裁 **R 3x / C 25x**（AskUserQuestion 四选项，亲选）。实现规格：

**① `ValueMpnMatch` 幅度分级**（`src/boardwise/rules/params.py`）

- 新增两个命名常量：电阻 `MPN_AMPLITUDE_TOLERANCE_R = 3.0`、电容 `MPN_AMPLITUDE_TOLERANCE_C = 25.0`，注释引 oracle 2026-09-21 二裁与决策数据（R 样本 2.13x 放行 / 4.7x 咬住；C 样本 22x 放行、无上限证据，25x 是主代理插值 oracle 确认）。
- `ratio = max(declared, decoded) / min(declared, decoded)`；`min <= 0` 时比值无意义，维持现状判 VIOLATION。
- `ratio < 阈值` → **OK**（不放行装没看见——消息如实写幅度与裁决出处，例：`board value 1kΩ vs MPN 470Ω differ 2.13x, below the 3x tolerance (oracle ruling 015 batch-2: "不要定的太死")`），走四态 OK 列、不进任何精确率分母（rc-cutoff 数值行先例）。
- `ratio ≥ 阈值` → VIOLATION（现状文案 + 幅度值）。
- 已知代价（oracle 知情）：黄金板 U3（2.13x < 3x）转 OK，dev 检出 5/5 → **4/5**，报告 missed 栏如实呈现；011c 该 defect 的 annotation **不改写**（冲突留史，oracle 若要改裁另说）。

**② 注入变体重签**（oracle 裁 A 即签署，先例 011d 门闩）

- `reviewsets/injected/make_variants.py`：`value-mpn-mismatch` 把 U3 value `'2.2kΩ'` → `'4.7kΩ'`（4.7x ≥ 3x 仍 VIOLATION）；`--generate value-mpn-mismatch` 重生成，`--check` 全板（含标注集）逐字节一致。
- 变体标注集 JSON 的 defect note 追加 `FINAL RULING 2026-09-21`（A + R3/C25 裁决出处）； pinning 该变体 finding 文案的测试同步（2.2k→4.7k）。

**③ 复跑对账**（写 `outputs/015b_eval_{dev,holdout}.txt`）

| 指标 | 批①基线 | 批②预测 |
|---|---|---|
| holdout 检出 | 33/33 | **33/33 不变** |
| holdout hp-prec | 33/40 = 0.82 | **33/33 = 1.00**（A2b 七条全转 OK ⇒ 011 §十 ≥95% **达成**） |
| 毕设板 value-mpn VIOLATION | 7 | **0**（OK 列 +7） |
| dev 检出 | 5/5 | **4/5**（黄金 U3 missed，oracle 知情代价） |
| dev hp-prec | 5/5 | **5/5**（黄金 U3 转 OK 不进分母） |
| 注入变体 det | 1/1 | **1/1**（4.7x ≥ 3x） |

**④ 变异验证**（全 CAUGHT + 逐字节还原）：R 阈值 3.0→2.0（U10/U14 应变 VIOLATION ⇒ 红）；C 阈值 25.0→5.0（五颗电容应变 VIOLATION ⇒ 红）；生成器回退 2.2kΩ（变体 det 应掉 ⇒ 红）。

#### 批② 决策数据（2026-09-21 全仓实测，`outputs/015_amplitude_scan.txt` + 扫描脚本 `.py`）

13 块板全扫，value-mpn VIOLATION **全仓只剩 9 条**（批①已把 A2a 类清成 UNKNOWN）：

| 板 | 位号 | 比值 | oracle 已有裁决 |
|---|---|---|---|
| 毕设板 | U10/U14（R） | **2.13x** | A2b **放行**（"本没错"） |
| 毕设板 | C28/C29/C36/C42/C44（C） | 10x–22x | A2b **放行** |
| CH340G 黄金板 | U3（R） | **2.13x** | 011c **判 defect**（LED 限流位） |
| 注入变体 | U3（R） | 2.20x（批②改 4.7x） | 011d **签署 defect**；批② A 重签 |

**单一全球阈值不成立**（裁决链第一段）：A2b 五颗电容 10x–22x，3x 全球阈值只能放行 U10/U14，电容照样报 ⇒ holdout 33/38 = 0.87，晋级仍破；而能同时满足"22x 电容放行 + 4.7x 电阻咬住"的纯幅度形态只有**分类阈值**。2.13x 同时出现在裁决两侧（U10/U14 放行 vs 黄金 U3 defect）——黄金 U3 放行是 oracle 知情的既定代价。

## 三、不做

- ~~批②的任何内容~~（批② 已经 oracle 二裁放行：A，R 3x / C 25x——规格见 §二批②）。
- 自动修复（M3）、真机写入、board24v 的标注集落地。
- 规则类删除、既有 exception/defect 记录改写（黄金 U3 的 011c defect 维持原样，冲突留史）、harness 语义变更。

## 四、交卷标准

1. 三线全绿：pytest（基线 1136，只增不减）/ connector 279 / `npx tsc --noEmit` 干净。
2. **变异验证**（全 CAUGHT + 逐字节还原）：①解码器：R001 记法/耐压码/电解料号各一条"重新硬解"变异必须咬红；②退役：把 `decoupling-per-ic` 加回 `BUILTIN_RULES` 的变异必须咬红。
3. 复跑报告落 `outputs/015_eval_{dev,holdout}.txt` + board24v 前后对比 `outputs/015_board24v_mpn_diff.txt`；预测表逐项兑现，偏离给机制解释。
4. 黄金板/注入板 det 与 finding 数不变（硬断言）；毕设板 A2a 三条转 UNKNOWN 的实测证据。
5. README 中英同步完成；本任务书交卷记录（含实测 vs 预测表）。

## 五、风险与纪律

- **dev 5/5 是硬底线**：解码器改动若波及严格 EIA 形态，注入变体 det 会掉——复跑第一时间看这条。
- 退役只做引擎层移除，任何人把规则加回列表都会被变异②咬住。
- 真机铁律 R1–R3 不涉及（本批离线）。git 不动，提交等岳点头（gs-02 截图+注与本批变更一起请批）。
- append 落盘后立即独立计数防双执行（AGENTS.md 复验纪律）。

---

## 六、交卷记录（执行者，2026-09-21；复验待 Kimi）

批①三条全部落地，**批②一字未碰**。git 未动。

### ① MPN 解码器越界修复（`src/boardwise/rules/values.py`）

| 位置 | 改动 |
|---|---|
| 44-69 | 三组"看着像 EIA、其实不是"的记法标记 + 说明：**拒绝是整 token 拒绝，不是丢候选**（丢候选会顶出另一个：`C1608X5R1V225KT000E` 丢 `225` 就只剩 `000` → 0 F） |
| 70 | `_R_NOTATION_RE = \d[Rr]\d{1,3}`（R 当小数点） |
| 71 | `_VOLTAGE_TAIL_RE = \d{3}[A-Z]\d{3}`（值+公差字母+耐压） |
| 72 | `_ELECTROLYTIC_RE = \d[xX]\d\|\d+[Vv]\d{3}`（电解外形：封装尺寸 `10x15`／"电压在值前" `50V330`） |
| 75-82 | `_digit_run`：封装码豁免要取"该位所在的整段数字" |
| 86-90 | `_r_as_decimal_point`：`RE2512F3R001` 判真；`CC0603KRX7R9BB104` 的 `X7R9` 判假（它后面还有数字 `104`，故 R 不是小数点） |
| 94-108 | `_voltage_rating_tail`：**逐起始位**扫描（`finditer` 非重叠会先吃 `206R510`——封装 1206 段——而漏掉真尾 `106K500`），且封装码所在段豁免（`FRC0805J471` 不被读成"值+公差+耐压"） |
| 112-117 | `_non_eia_notation`：三守卫取或 |
| 166 | `mpn_value_code` 的 token 过闸，命中即 None |
| 未动 | `decode_eia_3digit`、`parse_capacitance_farads`、候选扫描逻辑本身一字未改（严格 EIA 形态解码行为不变，逐条实测见下） |

`src/boardwise/rules/params.py`：UNKNOWN 的 message 补"（或写成非 EIA 记法）"（116-122 行）；`ValueMpnMatch` docstring 记明"拒绝记法也走 UNKNOWN，不再产出 finding"（78-88 行）。

严格形态实测未变（同一批断言里逐条钉）：`FRC0805J471 TS`→471、`FRC0805J102 TS`→102、`FRC0603J103 TS`→103、`CL10A225KA8NNNC`→225、`CL10B105KA8NNNC`→105、`CL10B473KB8NNNC`→473、`CC0603KRX7R9BB103/104`、`CC0805KRX7R9BB104`、`CC0402JRNPO9BN300`、`CL05B104KB54PNC`、`CL21B104KCFNNNE`、`CL21A225KBQNNNE`、`GRM1885C1H122JA01D`、`CH340G`→340。

### ② `decoupling-per-ic` 退役（`src/boardwise/engines/review.py`）

- `BUILTIN_RULES` 15→14 条（43-58 行）；35-42 行加注释指向 011f B2 裁决与本任务书，并写明"把它加回本列表，`test_decoupling_per_ic_is_retired_from_the_builtin_rules` 会红"。
- `DecouplingPerIC` 的导入从 `review.py` 删除（避免空引用），**类本体留在 `rules/connectivity.py`、`rules/__init__.py` 导出不变、`tests/test_rules.py` 的 3 条单测原样保留**。
- 新增钉子 `tests/test_011d_rules.py::test_decoupling_per_ic_is_retired_from_the_builtin_rules`（id 不在列表 + `len == 14` + 类自身仍可实例化）。
- README 中英两段 15→14（第 60 行、第 308 行，去掉 decoupling 那行，其余不动）。
- **超出任务书字面的一处文档改动（需知悉）**：`docs/epru-format.md:499` 写着"`llc_board` 实测 0E/7W，全是 decoupling-per-ic"——退役后该板变成 0E/0W/0I，故保留原测量并加一句标注退役后行为。任务书只点名 README，这条是我加的。

### ③ eval 复跑 vs 任务书预测（§二批①③）

报告落盘：`outputs/015_eval_dev.txt`（dev 5 板口径，同 011e/014 晋级判定表）、`outputs/015_eval_holdout.txt`（holdout 3 板口径）。**另加两份补充证据**（见下"产物"）。

| 指标 | 014 基线 | 任务书预测 | 实测 | 判定 |
|---|---|---|---|---|
| dev 检出 | 5/5 | 5/5 不变 | **5/5 = 1.00** | ✓ |
| dev 高优精确率 | 5/5 | 以复跑为准 | **5/5 = 1.00**（无变化：dev 五板上 decoupling/mpn 均无 finding） | ✓ |
| holdout 检出 | 33/33 | 33/33 不变 | **33/33 = 1.00** | ✓ |
| holdout 高优精确率 | 33/46 = 0.72 | 33/40 = 0.825 | **33/40 = 0.82**（报告四舍五入；`7 contradicted an exception, 0 had no oracle record`） | ✓ |
| 毕设板 exception 配对 finding | 10 | 7 | **7**（`10 exceptions_hinted, 7 fp_on_exception`；A2a 三条 R43/C115/C116 不再产出 finding） | ✓ |
| 毕设板 findings | 30E/14W/12I | — | **30E/8W/12I**（−3 A2a −3 decoupling WARN） | 说明见下 |

dev/holdout 逐板逐规则 diff：除"decoupling-per-ic 整行消失"外**逐字节一致**（其余各规则分子分母、各 state 计数全同）——即 MPN 改动未碰 dev/holdout 上任何其它数字。毕设板的 14W→8W 中，3 条是 A2a（解码器），3 条是 decoupling 退役（B2），两者都在本批预期的账上。

`--split dev` 的 014 口径（单块毕设板）也复跑留证：`outputs/015_eval_bishe_only_dev.txt` / `outputs/015_eval_bishe_only_holdout.txt`；与 `outputs/014_eval_*.txt` 的差 = decoupling 行消失 + mpn `0/10`→`0/7`（"所有 A2a 条不再配对"），无其它差异。

### ④ board24v 前后对比（`outputs/015_board24v_mpn_diff.txt`）

- before `outputs/015_board24v_before.txt`（跑前先复现：与固定快照**逐字节一致**）→ **0 ERROR / 15 WARN / 27 INFO**
- after `outputs/015_board24v_after.txt` → **0 ERROR / 0 WARN / 27 INFO**
- 15 条 WARN 全部消失，**0 条新增**（无 finding 被改判成更重）；27 条 `param-rc-cutoff` INFO 两侧不动。
- 按料号分组：`PA50V330M10x15` ×6（电解外形）、`HGC1206R5106K500NSPJ` ×6（耐压码）、`RE2512F3R001` ×3（R 记法）。与 `reviewsets/board24v-triage.md` 的 A1a/A1b/A1c 逐条对上。

### ⑤ 全板回归扫描（11 块板，逐 finding 比对）

用"015 前解码器 vs 现在"跑全部 fixture/reviewset 板：**只减不增**——毕设板 −3、board24v −15、高速电机控制器 −5（含 C40 `HGC0603R5225K500NTHJ`）、ROBOT ctrl FOC −1（R5 `RE1206F1R100`：value 0.1Ω vs 误读 10Ω 的假矛盾）；其余 7 块（含 dev 五板、ch340 黄金板、llc）**±0**。无任何板出现新增 finding，`decap-required-caps` 等其它规则未见联动（`mpn_value_code` 在 decap 里只是电容身份的信号，实测无一例翻转）。

### ⑥ 三线

| 线 | 命令 | 结果 |
|---|---|---|
| pytest | `.venv/Scripts/python.exe -m pytest --basetemp=.tmp_pt_home -q` | **1139 passed**（基线 1136 + 3 条新测，无删无改计数） |
| connector | `cd connector && npm test` | **279 pass / 0 fail** |
| TS | `cd connector && npx tsc --noEmit` | 干净（exit 0） |

新增 3 条测试：

| 测试 | 钉什么 |
|---|---|
| `test_011d_rules.py::test_the_mpn_code_finder_refuses_notations_that_are_not_eia` | 三类记法各自**独立证人** + 严格形态不变 + 封装/介质码不误伤 |
| `test_011d_rules.py::test_param4_the_a2a_exceptions_become_unknown_not_contradictions` | A2a 三条 → UNKNOWN 且无 finding；同板 A2b（U10）仍 VIOLATION（修的是解码器，不是哑掉规则） |
| `test_011d_rules.py::test_decoupling_per_ic_is_retired_from_the_builtin_rules` | 退役（变异②的靶子） |

改动 4 个既有测试文件（退役的连带，逐条列明；`tests/test_011d_rules.py` 只加不减）：

| 文件 | 改动 | 原因 |
|---|---|---|
| `tests/test_annotations.py` | mpn 例外对账从"10 条全等"改为"A2b 7 条相等 + A2a 三条断言 UNKNOWN"；`len(mpn_exceptions) == 10` 保持 | **标注集一字未动**，是规则侧变了：三条已裁"规则读错"的记录不再配 finding |
| `tests/test_review_eval.py` | `(exceptions_hinted, fp_on_exception)` (10,10)→**(10,7)**；`decoupling-per-ic` 行改为"无 metric 行 + 高优 unexplained 归零"；B2 段注释改写为退役留史 | 同上一行 + 规则退役 |
| `tests/test_cli.py` | epro2 smoke: `0 ERROR, 7 WARN`→`0 ERROR, 0 WARN`、summary `{0,7,0}`→`{0,0,0}`、md 断言改 `"No findings." in md`；tiny enet 用例改为断言退役规则**不再出声**且仍 exit 0 | llc_board 的 7 条 WARN 全是该规则的 |
| `tests/test_epro2_model.py` | `assert findings`（空列表会红）→ `run_review(model) == []` + **逐规则**跑一遍（规则仍要能在 epro2 模型上作答、finding 形状合法） | 同上；顺带把"只有落在这块板上的才能被检"换成"14 条规则都要答" |

### ⑦ 变异验证（任务书 §四.2，全 CAUGHT + 逐字节还原）

`pristine sha256`：`values.py = dde2ed414926b31a1134bac7d8ce5f92331790f44df7dafc5c096f5b52b22b95`、`review.py = ce0410b638c5251e15ae432781fae2a0989537b25a00187e5cf5c132cf8f979b`（= 交卷时两份文件的实测 sha256，逐字节相同）。四次变异各自跑**全量** pytest（`--basetemp=.tmp_pt_home`），跑完立刻从副本还原并复核 sha256；变异脚本与日志留在 gitignore 内的 `.tmp_015/`（`run_mutations.py`/`mutations.txt`），可原样复跑。

| # | 变异 | 结果 | 咬住的测试 |
|---|---|---|---|
| A | 关掉 R 记法守卫（`RE2512F3R001` 重新硬解成 `001`） | **CAUGHT** 4 红 | 解码器钉子 / A2a 钉子 / `test_annotations` 毕设板 / `test_review_eval` 毕设板 |
| B | 关掉耐压码守卫（`HGC1206R5106K500NSPJ` 重新硬解成 `500`） | **CAUGHT** 1 红 | `test_the_mpn_code_finder_refuses_notations_that_are_not_eia` |
| C | 关掉电解守卫（`PA50V330M10x15` 重新硬解成 `330`） | **CAUGHT** 4 红 | 同 A 的四个 |
| D | 把 `decoupling-per-ic` 加回 `BUILTIN_RULES`（连导入一起加） | **CAUGHT** 5 红 | 退役钉子 / `test_cli` ×2 / `test_epro2_model` / `test_review_eval` 毕设板 |

四次还原均**逐字节一致**（`sha256` 前后相同，脚本最后再独立复核一遍）。变异用临时副本+就地改写、立即还原，未动 git。

**B 号变异第一轮其实没咬住（必须记录的实情）**：初版 R 守卫写成 `\d[Rr]\d{3}`，而每个耐压码证人（`HGC…R5106K500NSPJ` 的 `6R510`、`HHV…R7475K101NSPJ` 的 `6R747`、`CGA…7R104`）**同时**命中 R 守卫，于是关掉耐压守卫时全量 1139 条仍全绿——两个守卫重叠，谁也测不出谁。修法两条：(a) R 守卫改成 `\d[Rr]\d{1,3}` + "数字到此结束"（`X7R9BB104` 的 `9` 后面还有 `104` → 判假，故介质码不误伤）；(b) 耐压尾改逐起始位扫描（`finditer` 非重叠会先匹配 `206R510` 并把封装段豁免掉，从而漏掉真尾 `106K500`）。修完 A/B/C 才各自独立咬住。**这是本批里唯一一处"预测之外"的实测**，机制就是守卫重叠 + 非重叠扫描，不是规则语义。

### ⑧ 与预测不符之处 / 需知悉的边界（不包装）

1. **dev「检出」口径**：任务书说"参考 014 的命令、用同样标注集跑 `outputs/015_eval_{dev,holdout}.txt`"，但 014 的两份报告是**单块毕设板**口径（`split=dev, 1 board(s)`，dev 项全在 holdout ⇒ 全落 unexplained），而预测表的 dev 行（5/5）只能由 **011e/014 晋级判定表的 5 板口径**量出来。我按预测表口径出 `015_eval_{dev,holdout}.txt`（5 板 / 3 板），另外补跑 014 单板口径两份（`015_eval_bishe_only_*.txt`）供逐字节对账。两套都在盘上，谁都不缺。
2. **`_ELECTROLYTIC_RE` 的第二个标记会顺带拒绝 `C1608X5R1V225KT000E`**（TDK 的 `1V225` 是耐压码、不是电解"电压在值前"）。该料号在**本仓所有板上本来就是 None**（歧义：`225` vs 封装 `000`），实测零影响；但它是"宁可拒"的取舍，写在了代码注释里。
3. **未被证人的边界**：本仓的电解料号只有一种形态（`PA50V330M10x15`：封装尺寸 `10x15` + `50V`），"电解"这一类只有这一个证人；理论上既看不出封装尺寸、也不带"电压在值前"的料号仍会被硬解，但没有实测样本，未据此加更宽的启发式（`PA50V330M` 这种"电压在值前、无封装尺寸"的形式已覆盖并钉在测试里）。
4. **`llc_board` 夹具（不在任何 split）findings 7→0**，连带 4 处测试断言改动（见上表）；它不进 M1 分母，不改变任何晋级数字。
5. `C1608X5R1V225KT000E`、`0805W8F1003T5E`、`FRC0805F4122TS` 等本来就 None 的料号**行为逐字节不变**（既不是"新拒"也不是"新解"）。
6. 毕设板 A2a 三条转 UNKNOWN 的逐条实测（value/mpn/解码码/state/message）落 `outputs/015_bishe_a2a_unknown.txt`；同板 `param-value-mpn-match` VIOLATION 主体实测 = `C28, C29, C36, C42, C44, U10, U14`（A2b 七条，批②再裁）。

### ⑨ 产物与"没碰"的证据

产物：`outputs/015_eval_dev.txt`、`outputs/015_eval_holdout.txt`、`outputs/015_eval_bishe_only_dev.txt`、`outputs/015_eval_bishe_only_holdout.txt`、`outputs/015_board24v_after.txt`、`outputs/015_board24v_mpn_diff.txt`、`outputs/015_bishe_a2a_unknown.txt`。（`015_board24v_before.txt` 是任务书给定的固定快照，未改。）

没碰：`reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`（sha256 `db1f5834…a18b7205`，与 014 交卷记录的 pristine 值相同，mtime 仍是 09-21 01:07）、`src/boardwise/engines/review_eval.py`（sha256 `802b52dd…`，mtime 09-21 00:36，均早于本批作业时间）、`connector/` 一字未动、git 未动、批②未动。

## 七、Kimi 复验落笔（2026-09-21，全部亲为）

- **三线亲跑**：pytest **1139 passed**（两次：交卷态一次、review.py 手术后再一次）；connector **279 pass / 0 fail**；tsc 干净。
- **eval 报告亲读**：`outputs/015_eval_holdout.txt` 尾部 = 检出 33/33 = 1.00、hp-prec 33/40 = 0.82（7 撞 exception、0 无记录）；`outputs/015_eval_dev.txt` = 5/5 与 5/5。预测表逐项兑现。
- **抽 diff 亲看**：`values.py` 三守卫（R 记法/耐压尾/电解外形）+"整 token 拒绝不丢候选"的理由链、`review.py` 退役注释、`test_011d_rules.py` 新钉子，与交卷记录一致。
- **独立变异抽验（自做）**：`DecouplingPerIC` 加回 `BUILTIN_RULES` → `test_decoupling_per_ic_is_retired_from_the_builtin_rules` 红 → 还原 sha256 `ce0410b6…8f979b` 逐字节一致。**事故与教训**：还原时误用 `git checkout --`（变更未提交，checkout 拉回的是 HEAD 旧版），靠 diff 记录重建 + LF 行尾修复后哈希对齐——**未提交变更的变异还原必须 cp 备份，禁用 git checkout**（AGENTS.md 复验纪律拟增补此条）。
- **边界核对**：标注集 sha256 `db1f5834…a18b7205`、`review_eval.py` sha256 `802b52dd…` 均未动；git status = 11 改 + 2 新（gs-02 图、本任务书），无越界文件。
- **结论**：批①通过复验。待岳：①批② A/B/C 裁决（任务书 §二批②）；②本批 + gs-02 图/注的提交点头。

## 八、批②交卷记录（执行者，2026-09-21；复验待 Kimi）

批②按 §二批② 规格逐条落地。**git 未动**：批①已在 `501a2f4`（+ PROGRESS `1bee292`）提交，本批改动全部在工作树（8 改 + 1 任务书 + 3 份新证据）。变异现场与日志在 `.tmp_015b/`（gitignore 内，可原样复跑）。

### ① `ValueMpnMatch` 幅度分级（`src/boardwise/rules/params.py`）

| 位置 | 改动 |
|---|---|
| 54-80 | 两个命名常量的裁决注释（oracle 2026-09-21 二裁 A；三条决策数据：10x–22x 电容把单一全球阈值证伪 ⇒ 必须分类；2.13x 同时落在裁决两侧 ⇒ 黄金板 U3 转 OK 是**知情代价**；25x 是主代理插值、oracle 确认，非实测） |
| 81-82 | `MPN_AMPLITUDE_TOLERANCE_R = 3.0`、`MPN_AMPLITUDE_TOLERANCE_C = 25.0` |
| 115-124 | 类 docstring 补"可读 MPN 按幅度判、小幅度以 OK 且**如实写幅度**" |
| 195-197 | 原"470 vs 1000 is a contradiction"注释改写（等值判断只留 `isclose` 一档） |
| 212-263 | 分级主体：`tolerance` 按 `kind` 取常量；`low, high = sorted(...)`；`ratio = high/low if low > 0 else None`；`ratio < tolerance` → **OK**（消息 = `board value X vs MPN Y differ R Rx, below the Tx tolerance (oracle ruling 015 batch-2: "不要定的太死")`，带 value/mpn evidence）；否则 **VIOLATION**（原文案 + `(R Rx apart, at or above the Tx tolerance)`）；`low <= 0` → VIOLATION 且消息写"ratio undefined" |

`min <= 0` 走 VIOLATION，与规格一致；`decoded` 为 0（如码 `000`）同样落这一支。等值（`isclose`）一档文案与行为**一字未改**。

### ② 注入变体重签（`reviewsets/injected/`）

- `make_variants.py`：`value-mpn-mismatch` 表项 `fault` 改 4.7k（4.70x）+ `oracle_note` 记重签与 4.7k 的**已知连带效应**（见下"与预测不符"）；新增 `final_ruling` 字段（229-236）；新增 `_final_ruling()` 助手（702-711）把该字段**追加**到生成标注集的 `notes` 与 **defect item note**（766/778）；`build_value_mpn_mismatch` 输出 4.7kΩ（646-663）；`--list` 增印 `ruling:` 行（1017-1018）。
- 重签动作：`.venv/Scripts/python.exe reviewsets/injected/make_variants.py --generate value-mpn-mismatch` → `--check` 输出 **`--check: 7 board(s) and their annotation sets rebuild byte-identically`**（全板含标注集，逐字节）。
- 新字节：`value-mpn-mismatch.epro2` sha256 `0a26446b…0e2925`（旧 `b254e081…`）、`value-mpn-mismatch.json` sha256 `1b883928…4ed35cd`。`fixed-base.*` 未变（`--check` 绿已证）。
- defect note 尾部实测原文：`FINAL RULING 2026-09-21 (task 015 batch 2; oracle decision A, category tolerances R 3x / C 25x). The ruling's own words for the complaint are quoted in the rule (MPN_AMPLITUDE_TOLERANCE_R, src/boardwise/rules/params.py): the injected value moved 2.2k -> 4.7k ohm so that the disagreement reads 4.70x and stays a violation at or above the 3x tolerance.` `reviewed_at` 保持 `2026-09-19`（它是**签署日**字段，规格只要求 note 追加裁决；若岳要落 09-21 另裁，一行即可）。

### ③ 复跑对账（`outputs/015b_eval_{dev,holdout}.txt` + `015b_bishe_a2b_waived.txt`）

命令形态与批①逐字相同（先复现批①报告验证过命令，见下"口径"）：

```
.venv/Scripts/boardwise.exe review-eval --annotations reviewsets/ch340g_golden.json \
  reviewsets/injected/fixed-base.json reviewsets/injected/overvoltage-rail.json \
  reviewsets/injected/ldo-no-headroom.json reviewsets/injected/value-mpn-mismatch.json \
  --split dev > outputs/015b_eval_dev.txt
.venv/Scripts/boardwise.exe review-eval --annotations reviewsets/injected/duplicate-designator.json \
  reviewsets/injected/nc-pin-grounded.json reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json \
  --split holdout > outputs/015b_eval_holdout.txt
```

关键行原文：

```
outputs/015b_eval_dev.txt:17   param-value-mpn-match  1  0  1  0  0  0  —  0/1 = 0.00  0  —
outputs/015b_eval_dev.txt:102  param-led-current     0  0  0  0  0  1  0/1 = 0.00  —  1  0/1 = 0.00   ← 变体上的第二条 finding（无记录认领）
outputs/015b_eval_dev.txt:105  param-value-mpn-match  1  1  0  0  0  0  1/1 = 1.00  1/1 = 1.00  1  1/1 = 1.00
outputs/015b_eval_dev.txt:114    defect detection (injected + native): 4/5 = 0.80  (cross-caught 0, missed 1)
outputs/015b_eval_dev.txt:115    high-priority precision (ERROR/WARN findings): 4/5 = 0.80  (0 contradicted an exception, 1 had no oracle record)

outputs/015b_eval_holdout.txt:47  board ProPrj_毕设FOC驱动板…: 121 components, 85 nets, findings 30 ERROR / 1 WARN / 12 INFO
outputs/015b_eval_holdout.txt:61  param-value-mpn-match  0  0  0  0  0  0  —  —  0  —
outputs/015b_eval_holdout.txt:66  OK  … param-value-mpn-match=8 …（批① 为 1，+7）
outputs/015b_eval_holdout.txt:72    defect detection (injected + native): 33/33 = 1.00  (cross-caught 0, missed 0)
outputs/015b_eval_holdout.txt:73    high-priority precision (ERROR/WARN findings): 33/33 = 1.00  (0 contradicted an exception, 0 had no oracle record)
```

毕设板 A2b 七条逐条（value / mpn / state / message / evidence）落 `outputs/015b_bishe_a2b_waived.txt`：U10/U14 = 2.13x、C42 = 10.00x、C28/C29/C36/C44 = 22.00x，七条全 OK，该板该规则 **findings = 0**；批① `outputs/015_eval_*.txt` 是批①截面（已随 501a2f4 提交），**未改**，用当前代码重跑会差 34 行（dev）/18 行（holdout），差异全部落在上表列出的那些行——即"批②动了哪几行"的自证。

### ④ 预测表逐项实测

| 指标 | 批①基线 | 批②预测 | 批②实测 | 判定 |
|---|---|---|---|---|
| holdout 检出 | 33/33 | 33/33 不变 | **33/33 = 1.00** | ✓ |
| holdout hp-prec | 33/40 = 0.82 | 33/33 = 1.00（≥95% **达成**） | **33/33 = 1.00** | ✓ |
| 毕设板 value-mpn VIOLATION | 7 | **0**（OK 列 +7） | **0**；OK 1 → **8** | ✓ |
| dev 检出 | 5/5 | 4/5 | **4/5 = 0.80**（missed = 黄金板 U3，011 §十口径） | ✓ |
| dev hp-prec | 5/5 | 5/5 | **4/5 = 0.80** | ✗ 见⑤ |
| 注入变体 det | 1/1 | 1/1（4.7x ≥ 3x） | **1/1 = 1.00**（`param-value-mpn-match` 行） | ✓ |

### ⑤ 与预测不符：dev hp-prec 5/5 → **实测 4/5 = 0.80**（不包装）

**机制**：`value-mpn-mismatch` 板上的 U3 **就是 LED1 的限流电阻**。4.7kΩ 落在 `param-led-current` 的 [470, 2200] 窗口**外**（`params.py` 里那句"4.7k is the counter-example and violates"说的是同一件事），于是该板多出第二条 finding：`param-led-current WARN LED1`（`outputs/015b_eval_dev.txt:102`，fp-unexpl=1）。它的 ref 是 `LED1`，变体标注集只有一条 `U3` 记录 ⇒ 进 dev 高优精确率分母却无人认领 ⇒ 4/5。

这条**不是**阈值算错，是**结构性冲突**：1k 的 MPN 要满足 ≥3x 需要 value ≥ 3000Ω，而窗口上限只有 2200Ω（= 2.20x）——**同一块板上不存在既 ≥3x 又在窗口内的 value 改写**。原 2.2k 之所以能"单缺陷"，正因为它压在窗口上限 2200Ω 上，而它恰好是 2.20x < 3x（这就是规格必须把它改成 4.7k 的原因）。两条已签裁决（011c/011d 的 LED 窗口、批②的 R 3x）在这块板上互斥，我用规格给的值执行并如实报数，**没有**自行改设计。已知可选处置（都需岳点头）：
1. **接受**：dev 是调参 split，不是门槛（门槛 holdout hp-prec = 1.00 已达成）；代价就是这 0.80。
2. **给标注集加第二条记录**（`ref: LED1, rule_hint: param-led-current, kind: defect, severity: WARN, split: dev`）：dev 检出 6/6、hp-prec 5/5 = 1.00，注记"4.7k 越窗是 011d 已签的反例"——但这是给"一条注入编辑"认领第二条缺陷，是签名级改动。
3. **改注入落点/形态**（换一个非 LED 限流位的 ref，或改 MPN 侧）——后者需要岳提供一个**真实**料号（同系列 100Ω 兄弟号本仓无实测依据，凭空写属于伪造目录号，批①已明确拒绝过同类做法）。

其余预测偏差：无。dev 5 板里除上述两条外逐行不变；holdout 三块板只动毕设板（-7 条 mpn WARN / -7 fp-exc）。

### ⑥ 变异验证（3/3 CAUGHT + 逐字节还原）

`pristine sha256`：`params.py = 229aaed1…3d79`、`make_variants.py = ddde8538…2bbe`、`value-mpn-mismatch.epro2 = 0a26446b…92925`、`.json = 1b883928…35cd`。**每次变异跑全量 pytest**（`--basetemp=.tmp_pt_home`），跑完 `cp` 还原（**禁用 git checkout**：工作树未提交，checkout 会拉 HEAD 冲掉改动）并 `sha256sum` + `cmp` 复核。备份/日志/汇总在 `.tmp_015b/`（`mutations.txt` + 三份 log）。

| # | 变异 | 结果 | 咬住的测试 |
|---|---|---|---|
| 1 | R 阈值 3.0 → 2.0 | **CAUGHT**（exit 1，11 红 / 1134 绿） | 阈值常量钉子、2.13x 放行钉子、U10 见证、黄金板 U3 转 OK、毕设板 A2b 七条、标注集对账、dev/holdout 两处 mpn 精确率、CLI 0.00 断言 |
| 2 | C 阈值 25.0 → 5.0 | **CAUGHT**（exit 1，6 红 / 1139 绿） | 阈值常量钉子、per-kind/边界钉子、R 恰 3.00x 钉子、毕设板 A2b 七条、标注集对账、毕设板 mpn 测量 |
| 3 | 生成器回退 2.2kΩ（并 `--generate value-mpn-mismatch` 重生成） | **CAUGHT**（exit 1，4 红 / 1141 绿） | 变体携带故障、**逐 dev 板 det 断言**（det 1→0）、CAUGHT 表参数化用例、两条 finding 钉子 |

三次还原均 `cmp` 逐字节一致 + 哈希回到上列 pristine 值；变异 3 额外复核 `--check` 仍打印 7 板逐字节一致。变异 1/2 只改常量一行，变异 3 的现场值（回退后板 = 批②前的 `b254e081…`）顺带证明"回退即让注入不可见"（该板在该规则下 findings = 0）。

### ⑦ 三线

| 线 | 命令 | 结果 |
|---|---|---|
| pytest | `.venv/Scripts/python.exe -m pytest --basetemp=.tmp_pt_home -q` | **1145 passed**（基线 1139 + 6 条新测，无删无改计数；日志 `.tmp_015b/final_full_suite.log`） |
| connector | `cd connector && npm test` | **279 pass / 0 fail**（`connector/` 本批零改动，跑一遍只为确认没被带坏） |
| TS | `cd connector && npx tsc --noEmit` | 干净（exit 0） |

新增 7 条测试 / 改动 4 条既有测试：

| 测试 | 钉什么 |
|---|---|
| `test_011d_rules.py::test_param4_a_contradiction_past_the_tolerance_is_the_violation` | 10x → VIOLATION 且消息带幅度（**替换**原 `…_value_mpn_contradiction_is_the_violation`：那个 1k-vs-470 用例现在是 OK 侧） |
| `…::test_param4_a_contradiction_below_the_tolerance_is_ok_with_its_amplitude` | 2.13x → OK，消息含幅度 + `015 batch-2` + 中文裁决原话；带 evidence；`check()` 不产出 finding |
| `…::test_param4_the_amplitude_tolerances_are_the_oracles_ruling` | 常量 3.0 / 25.0（**变异 1/2 的靶子**） |
| `…::test_param4_the_tolerance_is_per_kind_and_the_boundary_is_inclusive` | C 10x/22x 放行、**25.00x 咬住**（`ratio >= 阈值` 的边界） |
| `…::test_param4_a_resistor_at_the_r_tolerance_is_not_waived` | R 恰 3.00x 咬住、C 24.9x 放行（防两常量被对调） |
| `…::test_param4_a_zero_side_leaves_the_ratio_undefined_and_stays_a_violation` | `min <= 0` → VIOLATION + "ratio undefined" |
| `…::test_the_graduation_boards_a2b_seven_are_ok_and_the_rule_has_no_violation_left` | 真板 A2b 七条逐 ref 幅度 + 全板该规则零 VIOLATION |
| （改）`…::test_param4_the_a2a_exceptions_become_unknown_not_contradictions` | U10 由 VIOLATION 改 OK，新增 U11(10kΩ) 作为"规则没被哑掉"的 VIOLATION 见证 |
| （改）`…::test_the_golden_board_matches_the_task_book_expectations` | 黄金板 U3 由 VIOLATION 改 OK（含幅度与出处）；已知代价写在注释里 |
| （改）`test_annotations.py::test_load_annotations_reads_the_bishe_a_and_b_rulings` | 10 条 mpn 例外：A2a 三条 UNKNOWN + A2b 七条 OK（逐 ref 断幅度/出处），全板零 VIOLATION；标注集 JSON **一字未动** |
| （改）`test_injected_variants.py::test_value_mpn_mismatch_carries_two_findings_and_the_second_is_unclaimed` | **替换**原 `…_now_has_exactly_one_finding`：单缺陷属性已失（4.7k 连带 LED 越窗），两条 finding + "第二条无人认领"如实钉住，并把 2.2k→4.7k 的因果与结构性冲突写进 docstring |
| （改）`test_injected_variants.py::test_the_two_native_defects_are_gone_from_the_base_and_still_there_on_the_golden` | 黄金板两条 defect 的 detected 期望分规则给（decap 1 / mpn 0） |
| （改）`test_review_eval.py::test_the_real_ch340g_annotation_set_measures_the_known_false_positive` | 黄金板 mpn (1,1) → (1,0,missed 1)、`recall 0.0 / precision None` |
| （改）`test_review_eval.py::test_the_bishe_boards_a_section_is_detected_and_explained` | 毕设板 mpn (10 exception, **0** fp)、零 VIOLATION、precision/recall 均 None |
| （改）`test_review_eval.py::test_review_eval_measures_the_real_annotation_set` | 旧断言 `"0.00" not in stdout` 过粗（会连"recall 0/1"一起禁掉）；改为"xtal 行无 0.00 + 全报唯一一处 0.00 就是 mpn 的 0/1" |

### ⑧ 改动文件清单 / 边界

**Modified（8 + 本任务书）**：`src/boardwise/rules/params.py`、`reviewsets/injected/make_variants.py`、`reviewsets/injected/value-mpn-mismatch.epro2`、`reviewsets/injected/value-mpn-mismatch.json`、`tests/test_011d_rules.py`、`tests/test_annotations.py`、`tests/test_injected_variants.py`、`tests/test_review_eval.py`、`tasks/015-review-rules-m2.md`（本 §八）。
**New（gitignore 内，需 `git add -f`）**：`outputs/015b_eval_dev.txt`、`outputs/015b_eval_holdout.txt`、`outputs/015b_bishe_a2b_waived.txt`。

**没碰**：`src/boardwise/rules/values.py`（sha256 `dde2ed41…22b95`，批①成果，本批零改动）、`src/boardwise/engines/review_eval.py`（harness 语义）、`src/boardwise/engines/review.py`、`reviewsets/ch340g_golden.json`（黄金 U3 的 011c defect 记录**冲突留史**，未改）、`reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`（10 条 exception 记录未改）、`reviewsets/injected/fixed-base.*`（`--check` 绿已证未变）、`README.md`（规则无增减）、`connector/`、git。

## 九、Kimi 复验落笔（批②，2026-09-21，全部亲为）

- **三线亲跑**：pytest **1145 passed**；connector **279 pass / 0 fail**；tsc 干净。
- **eval 亲读**：`015b_eval_holdout.txt` 尾部 = 检出 **33/33 = 1.00**、hp-prec **33/33 = 1.00**（0 撞 exception、0 无记录）——**011 §十晋级判据（holdout ≥95% 精确率 + ≥90% 检出）正式达成**；`015b_eval_dev.txt` = 4/5 与 4/5（黄金 U3 missed 在 `:17`、LED1 次生 WARN 在 `:102`）。
- **独立变异抽验（自做）**：`MPN_AMPLITUDE_TOLERANCE_R` 3.0→2.0 → **11 红 / 1134 绿**（CAUGHT）；cp 备份还原 sha256 `229aaed1…` 前后一致（未用 git checkout）。
- **抽 diff 亲看**：`params.py:54-80` 裁决注释（三条实测事实 → 两个常量）、`make_variants.py` 重签与 `final_ruling` 落法，与 §二批②规格一致；任务书 §八 计数 1（无双执行）。
- **边界核对**：`values.py dde2ed41…`、`review_eval.py 802b52dd…`、黄金/毕设标注集 sha256 均未动。
- **一处实测偏离（执行者已如实上报，机制成立，待 oracle 三选一）**：dev hp-prec 实测 **4/5 = 0.80**（预测 5/5）——注入板 U3 兼是 LED1 限流电阻，4.7k 落在 `param-led-current` 的 [470,2200] 窗口外 ⇒ 同板多出一条 LED1 WARN，变体的单条 U3 记录解释不了。**结构性冲突**：MPN 锚 1k 时 ≥3x 需 value ≥ 3000Ω，窗口顶 2200Ω（=2.20x）——这块板上"≥3x"与"窗口内"互斥，2.2k 当年能单错型正因为它踩在窗口顶。选项：①接受（dev 是调参 split，晋级 holdout 已 1.00）；②给 LED1 补一条标注记录（dev 变 6/6 与 5/5，签字级改动）；③重锚注入 ref 或改从 MPN 侧注入（后者需 oracle 给真实料号，不臆造）。
- **结论**：批②通过复验。待岳：①上述 dev hp-prec 三选一；②批②全部变更的提交点头。
