# 104 / B4a 核心正确性批（issue #57 之 #11 #6 #2）

来源：外部审计 `.tmp_bug_report.md` "## 11." "## 6." "## 2." 三节。跟踪 issue：GitHub #57。
每条先红测复现再修。全部离线。**#1（位号混网）独立成 B4b，不在本批。**

## #11 reconcile_names 丢安全元数据 = fail-open — `src/boardwise/core/compare.py:499, :518`

返回的 `DesignModel(raw=...)` 只设 `components`/`nets`，`duplicate_designators`、
`cross_page_designators`、`unproven_nets` 全部回落空默认 ⇒ `unproven_pages()` 返回 None
被读成「已证实」，为「拒绝下结论」而生的规则（`rules/unproven.py`、位号重复规则）反而
下了结论。触发面=任何带这些事实的校准模式 reconcile（`cli._merge_schematic_models`，
`cli.py:4077-4109`）。
修：三个字段随 reconcile 带走（逐字拷贝，别重建别过滤）。红测=审计那段 before/after
逐字复现（dup/cross/unproven 三事实过 reconcile 后仍在、`repeated_designators()` 与
`unproven_pages()` 读数不变）。

## #6 arch-sense-bias-closure 的采样电阻取 shunts[0]（网表顺序）— `src/boardwise/rules/archclosure.py:1371`（收集 :1000，阈值 :1410/:1443/:1468）

`_members`（:272-277）按**网表自己的顺序**返回引脚——:991 docstring 声称
「in designator order」是错的。审计实测：同一块板只换 `nets['U+']` 的引脚顺序，
verdict 在 **ERROR/VIOLATION**（0.1Ω 在前）与 **INFO/OK**（100kΩ 泄放在前）之间翻转，
证据串还把错的件点名成 shunt。引脚顺序不是稳定身份（compare/reconcile 会重排）。
修：按**电气角色**选 shunt——① intent 通道（A3a 的 blocks[]/角色声明）声明了就用
声明的；②无声明时选候选里**阻值最小**的（电流采样件比泄放件小几个数量级，这是它的
电气定义）；选择逻辑与阈值引用同一处。红测=同板两引脚序 verdict+证据串**都**一致
（钉住「不再依赖顺序」），外加审计的两形（0.1Ω 在前 ERROR、100kΩ 在前不得 OK）。
:991 docstring 按事实改正。若 intent 声明与「最小阻值」矛盾（声明了件 A 但件 B 更小），
**别自行裁**，报「声明与结构矛盾」交给规则现有的 refusal 词汇或写遗留。

## #2 compare.plan_membership_renames 批准后未复查，两网焊一 — `src/boardwise/core/compare.py:448-456`（消费 :506-518）

pass 2 边迭代边删 pass 1 的 `renamed` 条目，**从不复查已批准的改名**：X 说要腾空名字
被批准后，后续迭代把 X 自己的改名删了 ⇒ X 没腾空，早先的批准指向被占名字 ⇒ 两网焊一。
审计端到端复现（golden N1/N2/KEEP vs candidate W/N2/N1/KEEP → N2 四引脚 WELD）。
:509-513 注释断言这不可能发生（「setdefault never fires here…#46 closes」）——它会发生，
这是 #46 在校准路径上的回归（draw verdict 路径在此返回 {} 不受影响）。
修：批准不是一次性的——删除发生后必须重验既有批准仍成立（不动点/二段提交均可，
选改动最小的）；:509-513 注释按事实改写。红测=审计的 WELD 场景逐字复现。

## 纪律

- 测试放 `tests/test_104_b4a_reconcile_roles.py`。
- pytest 必带 `--basetemp=.tmp_pt_home`；全量亲跑，基线 **3370 passed**，增量恰=新测试数。
- 变异 ≥3 组（cp+sha256，每条至少一组）：M1 #11 元数据不带走→红；M2 #6 退回 shunts[0]→
  顺序翻转红；M3 #2 复查摘掉→WELD 红。
- 零移动：21 板对账 + 语料（校准路径会被多页合并走到，语料板里若有多页工程重点对）+
  五族预览 83 张；任何移动逐板申报。
- 不碰 git、不写 PROGRESS、删除一律回收站、不碰 `tests/fixtures/` 既有夹具。
- 交付 `outputs/104/`：SUMMARY（红→修→绿、变异、零移动、全量行）。
- 拿不准写遗留，别扩大改动面。
