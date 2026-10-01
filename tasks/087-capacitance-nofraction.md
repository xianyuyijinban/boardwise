# 087 — 077 跟进：电容中缀无分数族放开（`100n`/`330u`/`22u`）+ 036 期望重钉

岳已裁（授权主代理）：放开无分数族。纯 Python 批：**不碰 connector TS、dsh-plugin、真机**。

## 背景与动机（已核实）

- 077 落了窄形状（分数必填），无分数族（`100n`/`330u`/`22u`/`1n`）留下未读，登记在 `tasks/077-capacitance-infix.md` 待裁线。
- 现状裂缝：我们自己的货架键就是 `cap.100n_0402`（`core/parts.quantity_slug` 管这族叫 "the schematic spelling"）——同一项目两套拼写口径，071 §2 同族问题。
- 083 边界①：`22u` vs `22uF` 在 compare 成了假差异（values_equal 委托解析器后，读不出 `22u` 就退化字符串不等）。本批放开后该假差异消失——**加一条 compare 证人钉死**（grep values_equal 找测试家）。
- 主代理探针实测：`_mid_letter_readings` 对无分数族读数全对（`100n`→1e-7、`330u`→3.3e-4、`22u`→2.2e-5、`1n`→1e-9、`540N`→5.4e-7）；既有拒收不受影响（`2N2222`/`1N4148` 四位分数 scan 拒、`0603n` 尺寸码剥、`0n` 前导零拒）。**唯一闸口**是字段正则 `_CAP_NOTATION_FIELD_RE`（`core/values.py:396`）的 `\d+[unpµμ]\d+`。

## 改动（执行者不得改设计）

1. **`core/values.py:396`**：`_CAP_NOTATION_FIELD_RE` 的字母后 `\d+` → `\d*`（分数可空）。**只动这一个字符类**：锚定（fullmatch）纪律不变、`m/M` 不收不变、scan 侧的分数长度帽/尺寸码剥/前导零拒全部不变。
2. **docstring 对齐**：:372-396 的注释块与 `_mid_letter_farads` docstring（:399-429）里「the fraction is **required**」「presence of a fraction」相关段落重写为已实现态——无分数族 087 起放开（`100n`=100 nF 是本库货架拼法），收录理由与 036 闸门故事一句话留痕；`:461-469` 的中缀族注释同步。
3. **SKILL.md 坑 34**（`.kimi-code/skills/boardwise/SKILL.md`）：077 改写的值拼写口径再更新一句（无分数族 `100n`/`22u` 起可读）。

## 036 期望重钉（本批唯一已知连带）

`tests/test_036_subcircuit.py::test_apply_insert_rc_lowpass_deletes_places_wires_and_saves` 的场景板把值写成 `1n`：放开后它可读 → RC 配对浮现 → 新 finding → `edit apply`「不得新增 finding」闸拒存 → 该测试红。**重钉**：先读懂场景意图（它考的是 edit-apply 机械，不是值可读性），选保持场景语义的钉法（例如把场景声明值换成仍不可读的拼写，或按新事实更新期望），理由写进测试注释。**不许**为了让测试过而削弱 edit-apply 闸。

## 回归闸（077 同款，逐条申报）

077 交卷记录（`tasks/077-capacitance-infix.md` 末尾）里有全部命令，照跑到 `evidence/087/`：

1. **语料回归**：2272 token + 2316 值字符串 + 21 板三类。预期新增可读 token **恰好**是 077 实测过的 4 条（`100n`/`330u`/`540n`/`540N`）；多出任何一条 = 停下报告。
2. **eval**：holdout 59/59 检出与精确必须保持，dev 对照不移动；任何移动逐条申报。
3. **变异 ≥2**（agent 先做，cp+sha256 还原）：①无分数族重新拒读（正则退回 `\d+`）→ 新钉子红；②锚定放松成子串匹配（fullmatch→search）→ `C4u7` 钉子红。

## 测试（`tests/test_011d_rules.py` 为主，077 的钉子同文件）

- 正读法：`100n`/`330u`/`22u`/`1n`/`540N` → 各值钉死。
- 拒读法保持：`2N2222`/`1N4148`/`2N7002`/`0603n`/`0n`/`C4u7`/`4u7F`/`u7`/`0u1`/`12345u7`/`4m7`/`4M7`（077 既有钉子全绿 + 该补的补）。
- compare 证人：`22u` ≡ `22uF` 判等（083 边界①收口）。
- rc 端到端：`C='100n'` 的 RC 网络正常配对算 fc（077 的 `4u7` 端到端同形状）。

## 验收

- `.venv/Scripts/python.exe -m pytest tests/test_011d_rules.py tests/test_036_subcircuit.py -q --basetemp=.tmp_pt_home_agent087` 全绿（**必须用这个 basetemp**，`.tmp_pt_home` 主代理全量专用）。
- 跑全量期间不写 src。
- **不 commit、不 push、不写 PROGRESS.md**。

## 边界

- `4N35` 今天就可读（4.35 nF，分数在）——既有行为，本批不动。
- 电压侧中缀（`3V3`）已由 083 的 `parse_voltage_volts` 另族处理，本批不碰。
- 电阻侧无分数（`100K` = 100 kΩ）本来就由 scan 读（`47R` 先例），本批不动电阻。
- 语料/eval 任何意外移动 = 停下报告，不自行解释通过。

---

## 交卷记录（执行者填，主代理复验）

> 执行者：boardwise 执行子代理（agent-128）。主代理派单，岳（oracle）终裁。

### 结论一句话

无分数族放开落地（`100n`/`330u`/`22u`/`1n`/`540N` 读得出），**核心改动 = 一个字符类**
（`_CAP_NOTATION_FIELD_RE` 的 `\d+`→`\d*`），锚定与 scan 侧拒收全未动；语料八类里
只有"读数变多"非零且**恰好 4 条**（`100n`/`330u`/`540n`/`540N`），eval 两树**逐字节
相同**；036 按"闸不动、fixture 不弯、如实钉新事实"重钉；变异 2/2 CAUGHT，`cp`+`sha256` 还原。
**pytest 全量 2904 passed**（086 记的 2902 + 本批净增 2）。

### 1. 落点（sha256 见 `evidence/087/hashes.txt`）

| 文件 | 改了什么 |
|---|---|
| `src/boardwise/core/values.py` | **唯一的实现改动**：`_CAP_NOTATION_FIELD_RE`（:406）字母后 `\d+`→`\d*`；docstring/注释三处对齐（形状注释块 :372-405、`_mid_letter_farads` 的 `540N`/`IRF540N` 段与两条问题清单、中缀族注释 :476-484） |
| `src/boardwise/core/compare.py` | **只改 docstring**：`values_equal` 把「unit-less `22u` 读不出」当拒收范例，那句今天不成立了（083 边界①已收口），改成记明 087 把它变成 step 3 的等值 |
| `tests/test_011d_rules.py` | 077 的"无分数是记录在案的缺口"段落改写成已实现态；新增 `test_the_capacitance_parser_reads_the_fraction_free_trade_spelling`（正读法 + 拒读法 + 三种 µ 拼法 + 与 `100nF` 同值）、`test_param3_an_rc_pair_with_a_fraction_free_capacitor_is_measured`（rc 端到端，`fc = 1,592 Hz`）；语料不变量 `test_023_...` 的 notation 正则 `\d{1,2}`→`\d{0,2}`，docstring 那个"多少 token 是挖出来的"数字按实测改 43→39 |
| `tests/test_036_subcircuit.py` | 036 重钉，见 §3；顺带把 `test_apply_insert_fails_when_a_rule_reports_something_new` 的 docstring 与断言补成"两条规则都说话"（现在 rc 测量行也在 new 里） |
| `tests/test_083_value_unification.py` | 083 边界①收口：`("22u","22uF")` 从**不等**清单移出，新增 `test_the_fraction_free_capacitor_spelling_is_one_value_not_a_false_difference`（`22u`≡`22uF`、`100n`≡`100nF`≡`0.1uF`、量纲邻居仍不等）；模块 docstring 的"拒收清单"同步 |
| `.kimi-code/skills/boardwise/SKILL.md` | 坑 34 一句：077 只作废了分数形那半，**087 起 `'100n'`/`'330u'`/`'22u'`/`'540N'` 才真读得出**，并把"插入值读得出的 RC 低通会被 finding 闸拦存（同坑 40）"写在同一句里 |

零 git 写操作；未碰 `connector/`、`dsh-plugin/`、`tests/fixtures/`、`reviewsets/` 既有内容、
真机、`PROGRESS.md`。

### 2. 测试清单

| 测试 | 钉什么 | 改前树 |
|---|---|---|
| `test_the_capacitance_parser_reads_the_fraction_free_trade_spelling`（新） | `100n`/`330u`/`22u`/`1n`/`540N` + 三种 µ 与大小写 + 与 `100nF` 同值；`100`/`0n`/`00n`/`IRF540N`/`0603n`/`12345n`/`4u7F`/`C4u7` 仍拒 | **红** |
| `test_param3_an_rc_pair_with_a_fraction_free_capacitor_is_measured`（新） | rc 端到端：`R1=1K + C1=100n` → `fc = 1,592 Hz`，证据行引 `'100n'` 原文 | **红** |
| `test_the_fraction_free_capacitor_spelling_is_one_value_not_a_false_difference`（新，083 文件） | compare 证人：`22u`≡`22uF`、`100n`≡`100nF`≡`0.1uF`、`22U`≡`22uF`；`22u`≢`22`、`100n`≢`100` | **红** |
| `test_apply_insert_rc_lowpass_writes_the_circuit_and_stops_at_its_measurement`（036 改名重钉） | 机械腿全留（写序、双证、范围、wiresVanished、wire net 名），新事实：`new_findings` exit 2、`persistence` 为空、唯一新增 finding 是 `param-rc-cutoff\|INFO\|...fc = 159,155 Hz` | **红**（改前是 exit 0 + 保存） |
| `test_the_capacitance_mid_letter_notation_refuses_its_neighbours`（改） | 077 的四条"缺口"断言改成事实钉；补 `0n`/`0603n`/`12345n`/`u` 仍拒 | 绿 |
| `test_023_the_capacitance_parser_reads_only_fields_that_state_a_value`（改） | 不变量正则放开分数，docstring 数字按实测 | 红（4 条 token） |
| `test_apply_insert_fails_when_a_rule_reports_something_new`（改） | 补 decap 那条仍在 new 里的断言 | 绿 |

改前树实测（`PYTHONPATH=.tmp_087_base/src`）：`evidence/087/tests_before_fix.txt`，4 红 36 绿。

### 3. 036 重钉：选钉法与理由

场景的意图是 **edit-apply 的机械**（先删旧网 → 放两件 → 放三根线 → 放地旗 → 保存），
不是值可读性。放开后 `1n` 读得出 → RC 配对浮现 → `param-rc-cutoff` 多一条 INFO 测量行
→ 036 的"改动不许新增 finding"闸（按身份、不看严重度）exit 2 拒存。

选了**按新事实更新期望**，而不是把场景值换成仍不可读的拼法，理由三条：

1. 087 之后**再没有"自然"的不可读容值拼法了**：分数形、后缀形、小数不带 `F` 形之外，
   `1n`/`100n`/`22u`/`1nF`/`0.1uF` 全读得出。要让这条测试保住"保存"，只能挑一个
   **因为读不出才挑**的怪拼法（`0u1`、带耐压后缀之类），那是拿夹具骗闸；
2. 拒存不是 087 造的**新行为**，是 036 早就有的：SKILL 坑 40 白纸黑字记着
   "`param-rc-cutoff` 命中 → `new_findings` exit 2 不保存，036 规矩按身份不看严重度"，
   触发条件只是"板上有个值读得出的 RC 对"。087 把更多拼法送进了这同一道闸；
3. **"插入能保存"那条腿没有丢**：`test_apply_insert_divider_is_a_pure_create_and_judges_the_export`
   （divider 插入，两只电阻、不产生测量行）仍然 exit 0 并写 `sch.doc.save`。

闸的一行代码没动，fixture 一个值没弯。测试改名是因为原名 `..._and_saves` 今天不成立了。

### 4. 三条线尾行

```
pytest tests/test_011d_rules.py tests/test_036_subcircuit.py -q --basetemp=.tmp_pt_home_agent087
  → 144 passed in 2.37s
pytest tests/ -q --basetemp=.tmp_pt_home_agent087full
  → 2904 passed in 422.03s   （286 记 2902 + 本批净增 2：011d +2、083 +1 新测试 -1 参数化行、036 ±0）
connector / dsh-plugin 三条：未跑（本批零 TS 改动，且派单禁止碰这两个目录）
```

### 5. 语料回归（`evidence/087/corpus_regression.txt`，逐条申报）

```
[1a] token（2358）：变少 0 / 变多 4 / 改写 0   —— 100n 1e-7、330u 3.3e-4、540n 5.4e-7、540N 5.4e-7
[1b] 值字符串（2402）：变少 0 / 变多 4 / 改写 0  —— 同上四条
[2]  电阻侧 0   [3] MPN 电阻读数 0   [4] MPN EIA 值码 0
[5]  规则状态迁移 0   [6] 新判定行 0   [7] 未归类 0   [8] 同行文字变化 0
```

**恰好 4 条，与 077 实测的那 4 条一字不差**，没有第 5 条。
（`22u`/`1n` 三字符，进不了这套 4 字符下限的语料口径——077 §边界外发现 3 依然成立。）

### 6. eval 对照（`evidence/087/eval_comparison.txt`）

| split | 指标 | before | after |
|---|---|---|---|
| holdout | 检出 | 57/59 = 0.97 | 57/59 = 0.97 |
| holdout | 高优精确 | 57/57 = 1.00 | 57/57 = 1.00 |
| dev | 检出 / 高优精确 | 4/5、4/5 | 4/5、4/5 |

两份 JSON **逐字节相同**（`diff` 0 行），ruleset/rulebody 指纹两树一致。

**申报（重要）**：077 交卷记的 holdout 基线是 **59/59**，本批的 **before 树就已经是
57/59**（检出少 2，另有 "holdout items excluded here: 1"）。这条基线在 077 之后的批次里
移动过，**与 087 无关**——本批的闸是"两树同分"，不是"59/59"。若 oracle 认为 59/59 才是
应有基线，那是另一条待查线（078–086 之间），本批不自行解释通过。

### 7. 变异证据（2 条，cp 备份 + sha256 还原 + `cmp` 一致）

| # | 变异 | 结果 | witness |
|---|---|---|---|
| ① | 正则退回 `\d+`（分数必填） | **CAUGHT：3 条红** | 无分数族读法 / rc 端到端 `C='100n'` / compare 证人 |
| ② | `fullmatch`→`search` 且去掉 span 检查 | **CAUGHT：4 条红**；语料 +102 读数 | `C4u7`（+`4u7F`）、无分数族里的 `IRF540N`、011d 语料不变量、料号钉 |

还原后 `sha256sum` 回到 `e76b75d4…56c`、`cmp` 静默（两份 restore 各验一次）。

**申报**：与 077 同款——只把 `fullmatch` 换成 `search`、**不**动 span 检查时，
`C4u7` 仍读不出（span 检查独立挡着），所以变异②按 077 M2 的形状做成两处，`C4u7` 才真的红。

### 8. 自决项清单

1. **036 重钉选了"更新期望"而非"换不可读拼法"**（理由见 §3）。这是本批唯一的设计性自决。
2. **连带改了 `core/compare.py` 的 docstring 与 `tests/test_083_value_unification.py`**：
   派单的改动点清单只列了 `values.py`/SKILL.md/036/011d，但 083 边界①的
   `("22u","22uF")` 不等断言今天被本批的解析器直接推翻，不改就是留一条红的假事实。
   两处都只动"事实陈述"，没动 `values_equal` 的任何一行逻辑。
3. **011d 语料不变量的 notation 正则同步放开**（`\d{1,2}`→`\d{0,2}`），并把它 docstring 里
   那个数字按实测改成 39（改前 43）——`evidence/087/probe_invariant_count.py` 是机具。
   顺带发现：那个数字原本写的是 **108**，用 077 的口径在本树的语料上复现不出来
   （43/39 才对），说明它是在更早的语料快照上量的；本批按可复现的数落笔。
4. **`540N` 读得出 = 540 nF**，而 `IRF540N` 读不出：锚定救了料号，代价是语料里多了
   `540n`/`540N` 这一对（各 1 条）。如实申报，不解释为"无害"。
5. **`4u7 `（尾空格）仍读得出**、`0u1`/`0603n`/`12345n` 仍读不出：与 077 同规则，未新增例外。

### 9. 边界外发现

1. **产品面行为变了，不只是测试变了**：087 之后，任何**值读得出的** RC 低通插入
   （`--c 1n` 是 CLI 文档里的写法）在 `edit apply`/`draw apply` 上都会被 finding 闸拦停，
   exit 2、图在页面上没落盘。闸的口径（自伤式 report-only 测量行该不该计入"新增 finding"）
   是 036 的待裁线，本批按任务书**没碰**。SKILL 坑 34 已把这条写进同一句。
2. **eval 基线与 077 记录不符**（59/59 → 57/59），见 §6 申报。
3. `22u`/`1n` 仍是 3 字符，进不了 #18 那套 4 字符下限的语料口径——本批靠测试钉子覆盖，
   语料机具看不见它们（077 同款结论，未变）。
4. `12345n` 读不出：扫描器把 mantissa 截到后三位得 345，但 `_cap_spelling` 的
   "读数必须覆盖字段自己的数字"这道检查挡住了它。这道检查 077 就有，087 没动它，
   只是现在**无分数族也走这条路**，于是它成了一条新的、有效的守门。
