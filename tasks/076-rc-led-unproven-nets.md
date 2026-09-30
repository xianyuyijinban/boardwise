# 076 —— issue #19 跟进①：rc / led 接进未证实网闸

**背景**：`e3ad570`（issue #19 主体修复）让 per-page 档把「出现在多于一个页的网名」记进
`DesignModel.unproven_nets`，并让 **7 条按网找协同器件的规则**对它们双向 withhold 成 UNKNOWN。
机制的登记表在 `src/boardwise/rules/unproven.py` 的 `NET_MEMBERSHIP_RULES`。

**本批缺口**（岳实测复现）：`param-rc-cutoff` 与 `param-led-current` **没接进这个机制** ——
同一模型只改 `unproven_nets`，输出逐字相同：并板焊出来的 R-C 照样报 `fc = 159 Hz`，LED 照样判 OK。
缓解事实（因此没有假 VIOLATION，但有洞）：rc 是 INFO、led 无轨时自退 UNKNOWN。

---

## 1. 根因

**不是漏登记，是登记表里的判断写错了。** `unproven.py` 当时的原文把这两条排除在外，理由是他们
"read one part's own values"：

> The rules that are **not** here, and why: … ``param-led-current`` / ``param-rc-cutoff`` /
> ``param-value-mpn-match`` read one part's own values. None of them asks "what else is on this net".

这句话对**打印出来的数字**成立（fc 只吃 R、C 两个值；led 只吃串阻的值），对**规则问的问题**不成立。
两条规则找协同器件的路径**都是按网找的**，只是找法不同于前 7 条（前 7 条是「扫某条网的成员」或
「读某条网的电压」，这两条是「按 pin 的网**求交集**」）：

| 规则 | 怎么找协同件 | 结论真正读的网 |
|---|---|---|
| `param-rc-cutoff` | `c_nets ∩ r_nets` 里**非地**的那条 = 这一对共享的网（`shared[0]` 既进 fc 行文字，也决定「已知电源轨=去耦」的跳过） | `shared`（非地共网）。R 的另一端**从不读**；C 的地端只按**名字**判（`is_ground_net`） |
| `param-led-current` | LED 的 pin 网 ∩ 候选电阻的 pin 网 = 配对证据；串阻的**远端**网读出窗口电压 | 共用的网（含地——那是它们相遇的地方，规则照读其成员）+ 读出电压的那条轨（可能是别页的 LDO 输出脚命名） |

所以并板焊接能捏造两种事实：**配对本身**（板 1 的 R 配板 2 的 C）和**轨电压的来源**
（板 2 的 LDO 给板 1 的 LED 定域）。后者对 led 尤其致命：`_supply_side` 会把所有「远端网有名字」的
候选电阻**全部求和**，一个别板的电阻就能把总阻值抬进/抬出窗口。

顺带查明的第二个洞（同一根因的下游）：rc 的「decoupling 跳过」也读 `shared` 的域 —— 焊接让
`domain_of` 从别页 LDO 拿到电压，整对**静默消失**（不报、也不说拒绝）。实测：毕设FOC 的
NET13 三对（U14/C40-C42）在 per-page 档整体消失。闸放在跳过之前，这类行从"无声消失"变成 UNKNOWN。

**边界**（本批未动，按任务书 §6）：`xtal-load-caps` / `shunt-sense-link` 是 legacy `Rule`
（无四状态协议，说不了 UNKNOWN），转 OutcomeRule 是 072 架构批的活；rc/led 核实为
`FactsRule(OutcomeRule)`，两条**本来就会说 UNKNOWN**（led 有两个 UNKNOWN 分支，rc 新增的行
`check()` 按 severity 跳过、不产生 finding），**没有结构障碍，不存在硬塞**。

## 2. 改动

| 文件 | 改了什么 |
|---|---|
| `src/boardwise/rules/params.py` | `RcCutoff._rows`：`shared` 判空后、decoupling 跳过**之前**加 `unproven_nets(model, shared)` 闸 → UNKNOWN；`seen` 同时承担"这对看过"（拒绝时不report「no pair found」的 survey 行，对齐 `param-divider-output` 的先例）。`LedCurrent`：`_series_resistance` 第 4 元素回传共网证据（`shared`），新增 `_watched()` 汇总"本规则真正读的网"（共网 + 读出电压的轨，去重保序），`_rows` 在**所有状态分支之前**加闸。两条规则的 docstring 写明机制、粒度与两条边界事实 |
| `src/boardwise/rules/unproven.py` | 登记表 7 → **9** 条；注释里"这两条只读自身值"的误判改写成事实：两条都在"找协同件"组，并逐条写明各自查哪些网、地网为何不查 |
| `src/boardwise/engines/review.py` | `refused_conclusions` docstring 的「7 on every per-page reading」→ 9（并去掉"running the seven rules"里的硬编码） |
| `tests/test_checkup_cli.py` | 6 条新测试（见 §3），`_part` 加 `footprint=` 形参、`_led_part(anode_net=)` |
| `.kimi-code/skills/boardwise/SKILL.md` | §per-page 段：7 条 → 9 条 + 两条新 id + "每条只查自己真正读的网、地网不查" |

sha256 before/after 见 `hashes.txt`。**规则 id 一律未改**（`review-eval` 的 `rule_count` 14 不变）。

**`rulesRefused` 语义申报**：`source.unprovenNets.rulesRefused` 是**登记表长度**，所以每份 per-page
报告的这个数字从 7 变 9（档位说明、notes 里的「7 条规则」同步变 9）；per-page 的
`completion.coverage.rulesRefused`（**实例数**）也随 rc 的拒绝上升——实测多页夹具上 rc 贡献
49 条拒绝（见 `corpus_regression.txt` §[4] 与 `registry_audit.txt`）。它进 `coverage_gaps` 的是
**布尔**（"有缺口"），不是数值，所以 verdict 不翻转。

## 3. 测试（先写红：`tests_before_fix.txt` —— 3 红 1 绿）

| 测试 | 钉什么 |
|---|---|
| `test_the_welded_rc_pair_is_not_measured_as_one_network` | **岳的复现（rc）**：两页焊出的 R1/C9 → UNKNOWN、点名 `SIG`、`not a verified connection`、无 159、无 survey 行、无 INFO finding |
| `test_the_same_rc_pair_on_one_page_is_still_measured` | 同两件在**一页**上 → 仍报 `fc = 159`（拒绝只针对焊名，不是变哑） |
| `test_the_welded_led_series_resistor_is_not_adopted` | **岳的复现（led）**：板 1 LED + 板 2 串阻焊在 `LEDN` → OK 变 UNKNOWN |
| `test_the_same_led_and_resistor_on_one_page_are_still_graded` | 一页上 → 仍 OK、仍引 `[470, 2200]`（改前树上也绿=正对照） |
| `test_the_led_window_does_not_read_the_other_boards_regulator` | led 的**第二条读**：配对已证明、但轨电压来自别页 LDO → UNKNOWN 点名 `RAILX` |
| `test_no_listed_rule_concludes_on_a_board_whose_every_net_is_welded` | **登记表双向漂移闸**（新增能力）：9 条 id 各给一块"全网红"的板，断言**不得出现 OK/VIOLATION**且**至少一条拒绝行**。`_registry_case` 遇未知 id 直接 raise，登记表增长必带配方 |

第 6 条同时收口了登记表注释里那句过度声明（原注释说该测试双向守门，实际只守了"id 不是内置规则"
一向；9 条里 `conn-usb-cc-pulldown` / `param-divider-output` / `path-ldo-dropout` 三条当时没有任何
拒绝钉子）。现在 9/9 都实测拒绝（`registry_refusal_probe.txt`）。

## 4. 全量 / 四线

- `pytest tests/ -q --basetemp=.tmp_pt_home`：**2646 passed**（跑在 5 条新测试已入库、第 6 条入库前
  的树上；2641 基线 + 5）。第 6 条入库后重跑见 §9 交卷记录。
- 四线：connector `npm test` 419/419、`npm run typecheck` 干净、dsh-plugin
  `typecheck + test 48 passed/1 skipped + build` 退出 0（`connector_test.txt` / `connector_typecheck.txt` / `dsh_plugin.txt`）。
  本批**不改 CLI 命令面**（无新命令/无新动作），按 045 §7 纪律"不跟"：dsh 工具面无需变动。
- 语料回归（`probe.py` + `diff.py`，13 块板 × 2 档 × 12 条规则的全部 outcome 行）：
  `corpus_regression.txt` §[1a]/[1b]/[2] **全 0**，§[3] 92 行（见 §5）。

## 5. 回归申报

**11 个单页夹具、双档（project-file / per-page）逐字节 0 变化**（§[1a] 0、§[1b] 0）——单页不合并，
`unproven_nets` 为空，闸的判据 `is not None` 根本进不去。**2 个多页夹具的 project-file 档也 0**
（§[2]）——不合并就没有未证实网。

**多页夹具 per-page 档（预期内诚实降级，逐条）**：92 行差异 = **49 个 subject**，全部是
`param-rc-cutoff`（两块板上都没有 LED，所以 led 侧 0 行）：

| 夹具 | subject 数 | 其中原本有测量行的 | 原本整对不可见的（decoupling 静默丢弃） |
|---|---|---|---|
| `ProPrj_毕设FOC驱动板_2026-09-17.epro2` | 2（R29/C36、R29/C45，网 `VCC`） | 2 | 0 |
| `ProPrj_高速电机控制器_2026-09-16.epro2` | 47（见 diff 全表） | 41 | 6（R33/C26@NET2、R35/C22&R40@NET4、U10/C26@NET2、U14/C22@NET4、U14/C40@NET13） |

两种迁移逐类解释：**(a) 原本有数字现改 UNKNOWN**（43 行）= 焊接网上的 fc 不是这块板的数字，
按 #19 契约双向 withhold；**(b) 原本无声、现在点名**（6 行）= decoupling 跳过被焊接网触发导致的
静默丢行，本批改为拒绝并点出网名（信息量增加，不是降级）。逐行审计见 `corpus_regression.txt` §[3]。

## 6. eval（`run_eval.sh`，同一条命令两个 src 根）

| split | 指标 | before | after |
|---|---|---|---|
| holdout | 检出（injected + native） | 59/59 = 1.00 | **59/59 = 1.00** |
| holdout | 高优精确 | 59/59 = 1.00 | **59/59 = 1.00** |
| dev | 检出 / 高优精确 | 4/5、4/5 | 4/5、4/5 |

- 两份 JSON 的 `boards` **逐字段完全相同**（`provenance.rulebody` 之外零差异，`rulebody`
  8211e240 → **8963ec7a** 是"规则源码改了"的如实记录；076 §10 复验时以最终树重跑过一遍，
  早先一版写的 4a6d2c85 是中间树的，已按落盘证据改正）。
- **UNKNOWN 覆盖零迁移**：四态表逐板逐规则逐值一致（`diff` 只差输出文件名与 rulebody）。
  #19 当时 UNKNOWN 有迁移，本批**没有**——因为 eval 的 15 块板全走 project-file（无未证实网），
  与"单页/project-file 档一字不变"的红线互为印证。
- rulebody 里 `rule_count` 仍 14（无规则新增/删除）。

## 7. 变异（cp + sha256 还原，3 组全 CAUGHT，还原后 `sha256sum -c` + `cmp` 一致）

| 变异 | 改动 | 结果 |
|---|---|---|
| ① rc 闸去掉 | `welded = unproven_nets(model, shared)` → `[]` | `test_the_welded_rc_pair_is_not_measured_as_one_network` 红 + **登记表闸**红（`('param-rc-cutoff', {'OK'})`）；语料 §[3] 归 0（退回改前行为）。`mutation_M1_red.txt`/`_corpus.txt` |
| ② led 闸去掉 | `welded = unproven_nets(model, self._watched(...))` → `[]` | 两条 led 钉子红（焊接串阻 + 别页 LDO 命名轨）+ 登记表闸红（`('param-led-current', {'OK'})`）。`mutation_M2_red.txt` |
| ③ 错查成"同页网也 withhold" | rc 闸 → `[(net, ()) for net in shared]` | 3 条单页钉子红（011d 的 `param3` 两条 + 本批一页对照），**语料红线炸**：§[1a] 55、§[1b] 55、§[2] 151（证明红线真被钉着、不是空转）。`mutation_M3_red_tests.txt`/`_corpus.txt` |

还原手段：`cp .tmp_076_mut/params.py.bak` + `sha256sum -c` + `cmp`（**未用 `git checkout --`**）。

## 8. 自决项

1. **rc 查 `shared`（非地共网）而不是 R/C 四端**：任务是「R 两端 + C 两端（或它判 fc 真正读的网）」
   二选一。按 decap 先例取"真正读的网"——R 远端**从不读**，C 地端按**名字**读。若照字面查四端，
   `GND` 在多页板上按构造每页都有 → 每一对 RC 都被拒（假警报，不是堵洞）。证据：M3 的语料爆炸。
2. **led 查"共用的网（含地）+ 读出电压的轨"**：led 的交集**不过滤地网**（那是它自己的写法），
   所以它读到哪条网就查哪条网，规则自己不去加过滤。两块多页夹具上都没有 LED，故本批语料对 led
   侧零变化，led 的覆盖靠 3 条测试钉住。
3. **闸放在状态分支之前**（led 放在 `supply_volts is None` 之前）：焊接世界里"没人给这条轨起名"
   也是关于未证实网的结论；且顺带把"本来就被别的洞吞掉"的 rc 对变成点名拒绝。代价：焊名 + 无名轨
   两行文字从"nothing names the rail"变"unproven net"（状态不变，都是 UNKNOWN）。
4. **拒绝行 severity = None**：rc 的 `check()` 按 severity 而不是 state 键控（011e §1.1），所以新
   UNKNOWN 不产出 finding、不进 `edit apply` 的"改动不许新增 finding"闸。
5. **`seen` 兼任"看过这对"**：拒绝时不再报「no pair found」survey 行，对齐 `param-divider-output`
   对焊名分压器 `seen_dividers.add` 的先例。非焊接路径 `seen` 与 `pairs` 同进同出，故 0 行为变化。
6. **新增登记表双向漂移闸**（第 3 节第 6 条测试）：原注释声明存在但实际只有一向，本批补齐并
   逐条实测 9/9；配方表遇新 id 会 raise，逼后续加规则的人补配方。
7. **SKILL.md 的 7→9 同步改了**（仓库内那份）；**用户级副本
   `C:/Users/xiangyu/.kimi-code/skills/boardwise/SKILL.md` 未动**（它本来就落后于仓库版：79793B vs
   80684B，是主代理/岳的安装口，按纪律不越界）。

## 9. 交卷记录

见本文件末尾 §交卷（执行代理填）。

---

## 10. 交卷记录（执行代理，2026-09-30）

**状态：完成，可复验。** 与已定设计无冲突（§8 的 7 条自决均在设计给的口径内：粒度按任务书给的
"或它判 fc 真正读的网"一支，理由与实测证据齐备）。

**红线遵守**：零 git 写操作（只在只读 `git show` 取 HEAD 哈希、`git status` 看清单）；
未改 `PROGRESS.md`；未碰 `tests/fixtures/` 与 `reviewsets/` 既有内容；本批全离线，未连 daemon、
未做任何真机读写。改动文件 5 个（`hashes.txt` 有 sha256 before/after + 行数）：
`src/boardwise/rules/params.py`、`src/boardwise/rules/unproven.py`、
`src/boardwise/engines/review.py`、`tests/test_checkup_cli.py`、
`.kimi-code/skills/boardwise/SKILL.md`。

**验证（最终树，全部自己跑）**：

- 全量 `pytest tests/ -q --basetemp=.tmp_pt_home` → **2647 passed**（183.31s，exit 0；
  基线 2641 + 新测试 6）`evidence/076/pytest_full_run_final.txt`
- 四线：connector `npm test` **419/419 pass**、`npm run typecheck` 干净、dsh-plugin
  `typecheck + test 48 passed/1 skipped + build` exit 0。本批不改命令面/动作面 → 按 045 §7
  dsh 工具面**不跟**（写明理由）
- 语料回归：11 单页夹具双档 + 2 多页夹具 project-file 档 **全 0**；多页 per-page 档 92 行
  （49 subject，逐条在 `corpus_regression.txt`）
- eval：holdout 59/59 = 1.00 双满保持、dev 4/5 不变、**UNKNOWN 零迁移**
- 变异 3 组全 CAUGHT（`cp` 备份 + `sha256`/`cmp` 还原，未用 `git checkout --`）
- 登记表行为审计：**9/9 拒绝**，并已固化成常跑测试（通用漂移闸）

**遗留 / 待裁决**：

1. **PROGRESS.md 未动**（纪律），#19 那条记录里的"7 条规则 + 已知缺口"现已过时——请主代理在
   本轮 PROGRESS 里补一句 076 收口。
2. **用户级 SKILL 副本**（`C:/Users/xiangyu/.kimi-code/skills/boardwise/SKILL.md`）未同步
   （本来就落后于仓库版 79793B vs 80684B），按纪律不越界；要用新说明就 `boardwise install-skill`。
3. **通用漂移闸的一个自洽性质**：它读的是**被测树自己的**登记表——若把 rc/led 从
   `NET_MEMBERSHIP_RULES` 里删掉而不删闸，这条通用闸会静默变窄（7 条）。覆盖它的是本批的
   逐条复现钉子（4 条）+ 登记表长度进档位说明/notes 的既有测试。
4. **未转的两条 legacy 规则**（`xtal-load-caps` / `shunt-sense-link`）仍是已申报缺口，留给
   072 架构批；本批已核实 rc/led **没有**说不了 UNKNOWN 的结构障碍（两条都是
   `FactsRule(OutcomeRule)`，且各自本来就有 UNKNOWN 分支）。

---

## 10. 复验记录（agent-109，换手后独立复核）

换手时 agent-106 的批次**已经跑完并落盘**（§9 交卷记录 12:05:13 写入，全量 2647 已在
`evidence/076/pytest_full_run_final.txt`）。本节是接手方**不采信转述、自己重跑**的结果。

### 10.1 半成品审查结论：全部保留，未改一行 src

逐段对照任务书「已定设计」7 条，未发现与设计冲突之处，**保留**：

| 设计条目 | 复核结论 |
|---|---|
| ① rc 查非地共网 `shared`，闸在 decoupling 跳过**之前** | 符合。`RcCutoff._rows` 里 `welded = unproven_nets(model, shared)` 在 `capped`/`domain_of` 判据之前，`continue` 掉整对 |
| ① led 查共网（含地）+ 读出电压的轨 | 符合。`_watched()` = 所有候选串阻的 `shared` 并集 ∪ `supply_net`，`dict.fromkeys` 去重保序 |
| ① 复用 `UNPROVEN_BY_NAME` 措辞体系 | 符合。走 `unproven_nets()` + `unproven_outcome()`，无新造措辞 |
| ② 岳的复现翻案 | 符合，且实测红→绿（见 10.3） |
| ③ 单页 0 变化 / 多页逐条申报 | 符合，独立重算一致（见 10.4） |
| ④ eval 59/59 | 符合，独立比对一致（见 10.5） |
| ⑤ legacy 两条不转；rc/led 是 `FactsRule(OutcomeRule)` | 符合，两条 `class X(FactsRule)` 且 `FactsRule` 继承 `OutcomeRule` |
| ⑥ 变异 ≥2 | 3 组，CAUGHT，证据齐全 |
| ⑦ SKILL 措辞 | 与既有坑条风格一致（同一 §per-page 段内 7→9，追加了"每条只查自己真正读的网"） |

**发现并改正的一处文档缺陷**（非 src）：`evidence/076/hashes.txt` 曾在 12:03:59 重写后才与最终树
一致（此前记的是中间树 `7601c690`/`c6fffbb9`）；`§6` 与 `README` 里的 `rulebody 4a6d2c85` 是 11:44
那一次 eval 的值，最终树重跑后是 **`8963ec7a`**。两处已按落盘 JSON 改正。

### 10.2 换手期间发现的事故（须报主代理）

**agent-106 在被叫停后并未真正停止，12:03–12:05 仍在同一个仓库里跑完整验证批**：期间它
mutate 了 `src/boardwise/rules/params.py`（`.tmp_076_mut/*.bak` 与 `params.py` 的 mtime 落在
12:03:58–12:04:51），也就是变异①②③ 的还原窗口正好压在接手方进场的时候。接手方第一眼看到的是
「工作树哈希对不上 `hashes.txt`」，实测确认是**变异循环中途**的瞬态，不是残留脏改：

- 12:04:33–12:05:50 连续采样 `params.py` 哈希，稳定在 `6719ce27…`；
- `.tmp_076_mut/params.py.bak` 与工作树 `cmp` **exit 0**（还原干净）；
- `agent-106/wire.jsonl` 末条是 `turn.ended reason=completed`（12:06:06），此后无新写入。

**处置**：接手方在确认静默前**未写任何 src**，只做只读核验；本次交卷的 src 一字未动
（收尾哈希与 `hashes.txt` 的 after 逐字相同）。教训写进 §11。

### 10.3 独立重跑：四线

| 线 | 命令 | 结果 |
|---|---|---|
| pytest | `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` | **2647 passed in 182.64s**，exit 0（基线 2641 + 新测试 6） |
| connector | `cd connector && npm test` | `tests 419 / pass 419 / fail 0` |
| connector | `cd connector && npm run typecheck` | `tsc --noEmit` 干净，exit 0 |
| dsh-plugin | `typecheck + test + build` | typecheck 干净；`3 passed (3) / 48 passed | 1 skipped (49)`；build exit 0 |

**先红后绿（自己重打，不是读 `tests_before_fix.txt`）**：`PYTHONPATH=.tmp_076_base/src` 打同一批
新测试 → `3 failed, 6 passed`：红的正是岳的复现三条
（`test_the_welded_rc_pair_is_not_measured_as_one_network` / `..._welded_led_series_resistor...` /
`test_the_led_window_does_not_read_the_other_boards_regulator`），一页对照与通用闸在改前树上本来就该绿。
换回工作树同批全绿。

**基线树的完整性也自己核过**：`.tmp_076_base/src/boardwise/rules/{params,unproven}.py` 的 sha256 与
`git show HEAD:` 逐字相同（`96b47c83…` / `01c0ea4a…`），所以"改前"那份 dump 确实是改前的。

### 10.4 语料回归（自己重跑分类器）

`python evidence/076/diff.py out_before.json out_after.json` 重算：

```
[1a] 单页夹具 project-file 档（红线：必须 0）: 0
[1b] 单页夹具 per-page 档（红线：必须 0）: 0
[2]  多页夹具 project-file 档（必须 0）: 0
[3]  多页夹具 per-page 档（预期内诚实降级）: 92 行 / 49 subject（全 param-rc-cutoff）
```

与 §5 逐字一致。**另做了一次设计边界探针**（不进测试，只为确认闸没有漏掉 led 的第三条读）：
`_watched()` 的 `supply_net` 分支来自 `_supply_side()` 在**没有候选串阻**时对 LED 自身非地 pin 的
回退读取，所以"焊接轨 + 无串阻"这一格也归闸管——实测 `unproven={'3V3'}` 时该 LED 判 **UNKNOWN**
（点名单条 net），同两件放一页则判 **VIOLATION（0 Ω 超出 [470, 2200]）**，即 oracle 自己的 ERROR
原样保留。设计第 ① 条在这条边界上闭合，无需改动。

### 10.5 eval（自己比对两份 JSON）

| split | before | after |
|---|---|---|
| holdout | 59/59 = 1.00 | **59/59 = 1.00** |
| dev | 4/5 = 0.80 | 4/5 = 0.80 |

结构化比对：两个 split 的 **`boards` 15 块逐字段完全相同**，`provenance` 除 `rulebody` 外相同，
`rule_count` 仍 **14**。UNKNOWN 零迁移属实（eval 的板全走 project-file 档）。

### 10.6 本次交卷唯一改动的文件

| 文件 | 改动 | 性质 |
|---|---|---|
| `tasks/076-rc-led-unproven-nets.md` | 追加 §10；改正 §6 的 `rulebody` 值 | 文档 |
| `evidence/076/README.md` | 改正同一处 `rulebody` 值 | 文档 |

src / tests / SKILL.md **零改动**（哈希与 `evidence/076/hashes.txt` 的 after 相同）。零 git 写操作。

## 11. 给主代理的自决项与建议

1. **【须裁决】并发写事故**：076 实际有两个执行代理同时在 `E:\boardwise` 上跑（agent-106 未真正
   停止）。SKILL.md §7 的派单纪律写的是"并行会同文件撞车"，本批是**正面撞上了**——接手方一度
   看到工作树哈希与证据不符。建议：换手前先确认前一个 agent 的 `wire.jsonl` 末条是
   `turn.ended`，而不是只信"已叫停"的口头状态。
2. **【文档遗留】`PROGRESS.md` 未动**（纪律），其中 #19 那条"7 条规则 + 已知缺口"已过时，请在本轮
   PROGRESS 补一句 076 收口。
3. **【文档遗留】用户级 SKILL 副本**（`C:/Users/xiangyu/.kimi-code/skills/boardwise/SKILL.md`）
   未同步（本来就落后：79793B vs 80684B），按纪律不越界；要用新说明走 `boardwise install-skill`。
4. **【设计遗留】通用漂移闸的自洽性**：它读的是**被测树自己的**登记表——若把 rc/led 从
   `NET_MEMBERSHIP_RULES` 删掉而不删闸，这条通用闸会静默变窄成 7 条。覆盖它的是本批 4 条逐条复现
   钉子 + 既有"登记表长度进档位说明/notes"的测试。
5. **【边界外，未动】**`xtal-load-caps` / `shunt-sense-link` 两条 legacy `Rule` 仍说不了 UNKNOWN，
   留给 072 架构批；本批已核实 rc/led 无结构障碍。
