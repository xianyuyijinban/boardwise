# 077：电容侧中缀值解析（issue #23 跟进②）

> 执行者：DeepSeek 子代理（boardwise 执行代理）。主代理派单，岳（oracle）终裁。
> 本批为 issue #23 的**跟进②**：071 §2 只并了电阻侧的两个解析器，电容侧的
> 中缀读法当时明确"没做"，本批补它。

## 来源与裁定

issue #23 现状：`parse_resistance_ohms('4K7') → 4700` ✅（071 §2 并解析器后成立），
但 `parse_capacitance_farads('4u7')` / `('2n2') → None` ❌。后果不是算错数，是**整件
被跳过**：`param-rc-cutoff` 拿到读不出的板值就不把该电容放进库存，于是 `C='4u7'` 的
RC 网络报"no pair found"（一条把"读不出来"说成"没有这个拓扑"的话），而同一颗件写
`4.7uF` 就能算出 fc。岳已回帖确认方向。

## 已定设计（执行者不得改）

1. **形状**：电容中缀 = `数字 + 单位字母 + 数字`，单位字母只收 `u/U/µ`、`n/N`、`p/P`
   （`4u7` = 4.7µF、`2n2` = 2.2nF、`5p1` = 5.1pF）。**`m`/`M` 一律不收**（毫法拉太
   偏门，收进来全是伪读法），docstring 写明拒绝理由。单位字母后的数字位数对齐电阻侧
   既有实现的约束，逐对称镜像：空 run 不产、字母后字母不产、剥前导尺寸码（电阻侧有
   → 电容侧同样要有）。
2. **锚定（071 哲学）**：中缀读法只在**整 token** 层产出——整个值字符串就是中缀形状；
   **绝不许在更长字符串里子串匹配出中缀**。
3. **调用方审计**：grep 出 `parse_capacitance_farads` 全部调用方，逐个说明喂的是什么、
   会不会把 MPN 类字符串带进来；会的话在中缀判据上加整 token 限定把它挡死，并为
   `2N2222`/`1N4148`/`2N7002` 各加一条"不得产出电容读法"的钉子。
4. **rc 规则通路**：`C='4u7'` 的板改后能正常配对算出 fc，写一条端到端钉子；改前报
   "no pair found" 的行为留一条对照说明（不保留旧行为）。
5. **语料回归**：既有解析结果 **0 变化**是红线；新解析出的 token（改前 None）逐个列出
   并人工核对正确性。有意外 = 停下报告。
6. **eval**：holdout 59/59 检出与精确必须保持；任何移动逐条申报原因。dev 对照。
7. **变异 ≥2**（cp+sha256 还原）：①中缀读法去掉 → 钉子红；②锚定放松成子串匹配 →
   `2N2222` 钉子红。
8. **文档**：grep README/docs/SKILL 里讲值解析/中缀的段落，该补补；没有就不动。

## 验收

- 同域测试文件 `tests/test_011d_rules.py` 内加钉子（正读法、拒读法、料号钉子、
  rc 端到端、decap 端到端、语料不变量），改前必须红。
- 语料回归（2272 token + 2316 值字符串 + 21 板）三类逐条申报，`evidence/077/`。
- eval holdout/dev 双跑对照。
- 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 绿
  （跑全量期间不写 src）。
- 变异 ≥2，①/②各一条，另补分数位数上限一条（理由见交卷记录）。
- 交卷：改动文件 sha256 before/after、测试清单、调用方审计表、语料回归、eval 对照、
  变异证据、自决项清单、边界外发现。

## 边界与纪律

- 零 git 写操作；不碰真机（全离线）；不改 `PROGRESS.md`；不碰 `tests/fixtures/` 与
  `reviewsets/` 既有内容；不碰历史证据（`outputs/011e*` / `014_*` / `015b_*` / `016_*`）。
- 只碰 `src/boardwise/rules/values.py`、`tests/test_011d_rules.py`、`.kimi-code/skills/
  boardwise/SKILL.md`（坑 34 的值拼写口径）、`tasks/077-*.md`、`evidence/077/`。
- 与已定设计冲突就停下来交卷说明，不自行改设计。

## 交卷记录（执行者填，主代理复验）

### 结论一句话

电容侧中缀读法落地（`4u7`/`2n2`/`5p1` …），整 token 锚定、无分数不读、`m`/`M` 不收；
**四线全绿（pytest 2641 passed，基线 2635 + 新增 6 钉）**，语料八类全 0 变化，
eval holdout 59/59 / 59/59 与 dev 4/5 原样保持。
**一处必须由 oracle 裁的点**：设计 §1 的"形状"与"对称镜像电阻侧"两条读法在"分数可以为空"
上冲突（详见 §自决项 1 与 §待裁），本批按**形状**（分数必填）落地，把按镜像（`100n` 可读）
的完整实测一同交上。

### 1. 落点（sha256 before/after 见 `evidence/077/hashes.txt`）

| 文件 | before | after | 改了什么 |
|---|---|---|---|
| `src/boardwise/rules/values.py` | `dfcfbbb6…c10d00f` | `8bc9a5c7…eb41c952` | 中缀记法参数化（`_MID_LETTER_KINDS`）+ 电容读法 `_mid_letter_farads`/`_cap_spelling`/`_CAP_NOTATION_FIELD_RE` + `parse_capacitance_farads` 接中缀分支 + docstring |
| `tests/test_011d_rules.py` | `0a1482f2…546ab9bc` | `3a8db1ce…ec5a7a1` | 6 条新钉子（见 §2） |
| `.kimi-code/skills/boardwise/SKILL.md` | `e9fb7b3a…ae49c8f22` | `d7b2a293…0cab5c382b` | 坑 34 一句作废重写（值拼写口径；`'22u'` 读不出 → 077 起中缀读法也读） |

未动：`rules/connectivity.py`（电阻侧已是 `values.py` 的唯一实现，本批不碰）、
`rules/params.py`、`rules/decap.py`、`core/`、`engines/`、测试夹具、`PROGRESS.md`。
零 git 写操作。

### 2. 测试清单（全部落在 `tests/test_011d_rules.py`）

| 测试 | 钉什么 | 改前 |
|---|---|---|
| `test_the_capacitance_parser_reads_the_trade_mid_letter_notation` | `4u7`/`2n2`/`5p1`/`1u0`/`4u70` + 三种 µ 拼法 + 后缀文法原样 | 红 |
| `test_the_capacitance_mid_letter_notation_refuses_its_neighbours` | `4m7`/`4M7`、`4u7F`、`C4u7`、`u7`、`0u1`、`4u700`、`12345u7`、**无分数拼法**（`100n`/`330u`/`22u`/`1n`，缺口如实钉住） | 红（正控在末尾） |
| `test_the_capacitance_notation_never_mines_a_part_number` | `2N2222`/`1N4148`/`2N7002` + `1N4007`/`2N5401`/`1N5819`/`IRF540N`/`CL10A225KA8NNNC`/`DRV8313PWPR`/`250uA`/`510nm` 不得产出电容读法；`2n2`/`5n4` 必须读 | 红（正控） |
| `test_param3_an_rc_pair_spelled_in_the_trade_notation_is_measured` | issue #23 复现路径端到端：`R1=1K` + `C1=4u7` 配对算出 fc（1/(2π·1k·4.7µF) = 33.86Hz → `fc = 34 Hz`），并断言改前那条"no pair found"调查行**不再出现**（不保留旧行为） | 红 |
| `test_decap_a_cap_written_in_the_trade_notation_meets_its_requirement` | 第二个消费方：板值 `4u7` 的 C9（货架认它是电容、MPN 解不出值）从 UNKNOWN 变 satisfied（4.7µF ≥ 1µF） | 红 |
| `test_023_the_capacitance_parser_reads_only_fields_that_state_a_value` | 语料不变量：2288 token 里凡读得出者必是"后缀文法"或"中缀记法"**整字段**（防子串挖掘） | 绿（不变量性质，防回归） |

改前树实测：6 条里 5 条红（`evidence/077/tests_before_fix.txt`）。

### 3. 四线尾行（`evidence/077/line_summary.txt`）

```
pytest tests/ -q --basetemp=.tmp_pt_home → 2641 passed in 260.69s   （基线 2635 + 6 钉）
connector: npm test → 419 pass / 0 fail;  npm run typecheck → 无错
dsh-plugin: typecheck ok; npm test → 48 passed | 1 skipped; build ok
```

### 4. 调用方审计表（grep 实证 `evidence/077/callers.txt`）

| 调用点 | 喂进去的是什么 | 带得进 MPN 类字符串吗 |
|---|---|---|
| `decap.py:145` `looks_like_capacitor(value)` | 板值字段 | **不会**：同函数 MPN 走 `mpn_value_code`（160/175 行） |
| `decap.py:193` `candidate_farads` | `CapCandidate.value`（= `Component.value`） | **不会**：候选的 MPN 另存 `mpn` 字段 |
| `decap.py:255` `decide_required_cap(declared_text)` | facts 的 `required_caps[].value` / addcomponent 的 recipe | **不会**：blocklib 实测 6 个 distinct（`0.1uF/100nF/10nF/1uF/2.2nF/22uF`），全是值不是料号 |
| `params.py:144` `_kind_of(comp)` | 板值字段 | 不会 |
| `params.py:341` `ValueMpnMatch` | 板值字段（MPN 侧走 anchor 版） | 不会 |
| `params.py:1050` `RcCutoff` | 板值字段 | 不会 |
| `cli.py:12434` `same_board_value` | 两个板值字段（页面回读 vs plan before/after） | 不会：5 个调用点（14741/15459/15469/15518/15576）传的都是 Value |
| `outputs/015_amplitude_scan.py`、`outputs/048_numeric_exponent.*` | 历史证据目录里的源码快照 | 不在运行路径 |

→ **今天没有任何调用方把 MPN 字符串喂进来**；整 token 限定是防未来的（071 §1 C 哲学），
`2N2222`/`1N4148`/`2N7002` 三条钉子即为此立。

### 5. 语料回归（`evidence/077/corpus_regression.txt`）

同一份语料（2288 token + 2332 值字符串 + 21 块板）在改前树与工作树上各跑一遍：
**读数变少 0 / 变多 0 / 改写 0；电阻侧 0；MPN 读数 0；MPN 值码 0；规则状态迁移 0；
新判定行 0；未归类 0；同行文字变化 0**。新解析出的 token = **0**（本仓库语料里没有
`4u7` 形状的字符串：`2u2`/`1n2` 只有 3 字符、进不了 4 字符的语料口径；`100n`/`330u`
属"字母后无数字"，本批按形状拒读）。

**零变化不是空转，有正对照**：把形状闸拿掉（变异④）同一套机具立刻报 4 条新读数
（`100n`/`330u`/`540n`/`540N`）——`evidence/077/mutation_M4_corpus_control.txt`。

### 6. eval holdout/dev 对照（`evidence/077/eval_*`，同一命令两个 src 根）

| split | 指标 | before | after |
|---|---|---|---|
| holdout | 检出（injected + native） | 59/59 = 1.00 | **59/59 = 1.00** |
| holdout | 高优精确 | 59/59 = 1.00 | **59/59 = 1.00** |
| dev | 检出 / 高优精确 | 4/5、4/5 | 4/5、4/5 |

两份报告 `diff` 只差 provenance 的 `rulebody`（`ad2b4c28` → `48e07307`，规则源码变了
必然变；ruleset 指纹 `232eee40` 与 15 块板逐行数字一字未动）。**没有任何用例移动**。

### 7. 变异证据（4 条，cp 备份 + sha256 还原 + `cmp` 字节一致，`evidence/077/mutation_*`）

| # | 变异 | 结果 | 钉住它的 witness |
|---|---|---|---|
| ① | 中缀读法去掉 | CAUGHT：5 条钉子红 | 正读法 / 拒读法 / 料号 / rc 端到端 / decap 端到端 |
| ② | 整字段锚定放松成子串（`fullmatch`→`search` + 去掉 span 检查） | CAUGHT：`refuses_its_neighbours` 红；语料 +10 读数 | `4u7F`→4.7µF、`C4u7`→4.7µF、`12345u7`→345.7µF；语料里 `item.szlcsc.com/datasheet/AGM12N10A/6380600.html`→12.1nF（MOSFET 料号 URL 读成电容） |
| ③ | 分数位数上限去掉（共享扫描器一行） | CAUGHT：料号钉子红 + 电阻侧 30 个 MPN token 移动 | `2N2222`→2.2222nF、`1N4148`→1.4148nF、`2N7002`→2.7002nF；`4K700` 电阻侧跟着变（**一份实现被证明是共享的**） |
| ④ | 形状闸去掉（正对照，= "分数可空"的宽变体） | CAUGHT：语料 +4；`test_036_subcircuit.py` 红 | `100n`/`330u`/`540n`/`540N` 变可读；036 的 RC 插入场景板值 `1n` → 新增 finding → `edit apply` 拒存 |

**申报**：设计里写的"变异② → `2N2222` 钉子红"**没有按字面成立**。`2N2222` 被两道
互相冗余的闸挡着（整字段锚定 + 扫描器分数上限），只放松锚定它仍被上限拒掉；把它读出来
需要合上两道闸（= 变异②+③）。因此我把两条闸各自的专属 witness 分开立钉与分开变异，
证据在 `mutation_M2_*` / `mutation_M3_*`。

### 8. 自决项清单

1. **分数必填**（形状 `\d+[单位字母]\d+`）。设计 §1 的"形状 = `数字+单位字母+数字`"按字面
   落地；同时设计又说"数字位数对齐电阻侧既有实现的约束"，而电阻侧那位约束（`len(fraction)>2`）
   允许 0 位。两条读法冲突，我选了**形状**（较窄、爆炸半径 0），并把宽变体的完整实测交上
   （§待裁）。代码注释里如实写明这是"记录在案的缺口"而非疏忽。
2. **µ 的三码点**：中缀也收 `U+00B5` / `U+03BC` / `U+039C` 三种拼法（055 的既成口径，
   后缀文法本来就都收；只收一种会让 `4μ7` 与 `4.7μF` 待遇不一致）。
3. **`4u7 `（尾空格）读得出**（`strip()` 与电阻侧同规则）；`4u7F` 读不出（F 不被覆盖）——
   两条都写进测试当边界说明。
4. **尺寸码剥离/空 run/前导零**沿用共享实现（`0603u1`→不读、`u7`→不读、`0u1`→不读），
   与电阻侧逐条对称；`0u1`（0.1µF 的少见写法）因此仍不读——与 `0K1` 同待遇，未新增
   板文法规避（电阻侧的 `0R5`/`0R01` 有板文法兜底，电容侧没有）。
5. **`_CAP_NOTATION_FIELD_RE` 不写分数上限**（`\d+`），把"分数位数 ≤2"留给共享扫描器
   一行实现——一处规则一份实现；这样变异③能干净地隔离那条上限。
6. **文档只动 SKILL.md 坑 34 一句**：README/docs 里没有讲值解析或中缀记法的段落
   （grep `中缀`/`4K7`/`parse_capacitance` 全空），按任务书"没有就不动"只改了这处
   **已作废的口径**（原文写死"`'22u'` 读不出"）。`PROGRESS.md` 按纪律不动。

### 9. 待裁（oracle 一条）

**分数可空要不要开？** 开了以后：
- `100n`/`330u`/`1n`/`22u` 都能读（`core/parts.quantity_slug` 把这族拼法叫 "the
  schematic spelling"，货架键就是 `cap.100n_0402`）；
- 代价实测：`tests/test_036_subcircuit.py::test_apply_insert_rc_lowpass_deletes_places_wires_and_saves`
  变红——该场景的 RC 插入把 C1 写成 `1n`，读得出之后 `param-rc-cutoff` 多一条 INFO finding，
  `edit apply` 的"改动不许新增 finding"闸于是拒绝保存（exit 2）。这是**36 号闸的判据问题**
  （要么闸的口径、要么场景的值拼写要一并裁），不是解析器的正则问题。
- 与本批已落地的窄形状相比，语料侧差异只有 4 条 token（`100n`/`330u`/`540n`/`540N`）、
  板级 0 行迁移、eval 0 移动。

建议：单开一小批（"036 场景值拼写 or apply 闸口径 + 中缀无分数放开"），本批维持窄形状。
若 oracle 直接判"放开"，改动量是 `_CAP_NOTATION_FIELD_RE` 去掉 `\d+` 末尾 → `\d*` 一行
加 036 那一条期望的重钉。

### 10. 边界外发现

1. **小数点拼法仍不读**：`4.7u`、`1.5n`（`_CAP_RE` 要求结尾 `F`）。改前也不读，非本批引入；
   与"无分数"同族缺口，属同一条待裁线。
2. **`parse_capacitance_farads` 的 64 字符长度闸**对中缀同样生效（`_too_long` 在最前），
   中缀扫描只吃整字段、无子串回溯，性能面无新增风险。
3. 语料口径的天花板：`2u2`/`1n2` 这类 3 字符中缀值**进不了** #18 口径的 token 语料
   （4 字符下限）——将来的语料回归若只靠这套口径，会看不见它们；本批用测试钉子覆盖。
