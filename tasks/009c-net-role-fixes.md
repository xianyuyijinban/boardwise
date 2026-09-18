# 任务 009c（M0-P0c）：电平转换语义修正 + 网络角色修正

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`tasks/009-schematic-review-m0.md`（M0 立项书）、
> `docs/roadmap-2026-09-18.md` §3"三个早期修正"第三条及其后
> "另一个值得尽早清理的基础假设"段。
> 注意：`engines/validate_spec.py` 刚被 P0a+b 重构（五闸 + benchmark 旗标 +
> spec_hash），本文行号以**当前代码**为准，动手前先重新定位。

## 裁决已定（照做，不自行改道；有异议写进交卷报告）

### 1. level_shifter 布尔豁免：删除

现状：`_gate_levels` 里，同网多电平域时只要参与块声明
`level_shifter: true` 就降级 note 放行。

错误语义：电平转换器连接的是**两个不同网络**（低压侧/高压侧各有电平域），
合法转换**根本不触发**同网混接。该豁免的唯一效果是把真错误放行。

修法：

- 同网多电平域 → 永远 fail，无豁免。
- `BlockTemplate.level_shifter` 字段**整体删除**：`core/blocks.py` 的字段
  （约 :453）、序列化白名单（约 :485）、解析（约 :883）一并删。
  **已核实 `blocklib/` 无任何块声明它**，无迁移负担。
- 删除后块 JSON 再出现 `level_shifter` 键会被 `_check_keys` 报多余键——
  这是期望行为（逼声明者更新），不要为它加兼容。

### 2. VEE 归地：移出地表

现状两处（重复实现，顺手统一）：

- `core/model.py:18-30` `GROUND_NET_PREFIXES` + `is_ground_net`
- `engines/layout.py:375` 独立正则 `^(GND|AGND|DGND|PGND|VSS|VEE)`

VEE 在模拟/ECL 电路里是**负电源**，不是地。

修法：

- VEE 从 `GROUND_NET_PREFIXES` 移除；`layout.py:375` 改用 `is_ground_net`
  （消除重复实现）。
- VEE 移出后落到"非地"：布局不给它挂 GND 符号（正确——负电源不该挂
  地符号），规则不再当地处理。
- **不**新增"负电源"角色（那是 M1 器件事实库的事）。在
  `is_ground_net` 的 docstring 写一句：名称推断只是候选，网络角色应来自
  声明和器件事实。
- 已核实 `blocklib/` 无 VEE 网，无迁移负担。

### 3. 存量隐患顺手修（P0a+b 交卷时发现）

`_gate_levels` 里 `evidence=silent or named`：`named` 未定义，因 `silent`
必非空短路而永不求值。读代码判断本意：若该路径本应存在则修正变量名并
补一个触发该路径的测试；若是死代码则删除并在交卷报告说明依据。

## 验收场景（写成测试）

1. 同网混接两个电平域 → fail（无豁免）。再证：块 JSON 带
   `level_shifter` 键在加载期即被 `_check_keys` 拒。
2. 合法双侧转换：转换器两个端口各接不同网络、各侧电平与端口声明一致
   → pass。
3. VEE 网络不被 `is_ground_net` 判地；布局不给 VEE 挂 GND 符号。
4. 既有 831 条 pytest 语义不动。**例外**：若有测试断言"level_shifter
   豁免放行"或"VEE 是地"，那是被证伪的旧语义，可改，但交卷报告逐条
   列出改了哪条、为什么。
5. `named` 隐患处置后，`_gate_levels` 全路径有测试覆盖。

## 交卷标准

pytest（831+N）/ connector `npm test`（183）/ `tsc --noEmit` 三线全绿。
变异验证至少 2 个（例：把 VEE 加回地表应咬红场景 3；恢复豁免应咬红
场景 1），咬住了、还原复跑全绿，才算数。

纪律：不动 git；不碰真机；代码/注释全英文；Windows 坑（文件显式
`encoding='utf-8'`、控制台 `PYTHONIOENCODING=utf-8`、不用 /tmp，临时
文件用仓内 `.tmp_*`）；最小改动，不顺手重构。

交卷报告：改动文件清单、测试数变化、被改既有测试逐条清单及理由、
变异验证记录、`named` 隐患的处置与依据。

---

## ✅ 已落地（2026-09-18）

三条全绿：pytest **837 passed**（基线 831，+6）/ connector **183 pass** / `tsc --noEmit` 干净。

**改动文件清单**：

| 文件 | 改动 |
|---|---|
| `src/boardwise/engines/validate_spec.py` | `_gate_levels` 删豁免分支（同网多域永远 VIOLATION）；删 `evidence=silent or named` 的死分支；模块 docstring 第 3 条改写 |
| `src/boardwise/core/blocks.py` | 删 `BlockTemplate.level_shifter` 字段 + `_TEMPLATE_KEYS` 白名单项 + `template_from_json` 解析 |
| `src/boardwise/core/model.py` | `GROUND_NET_PREFIXES` 删 `VEE`；`is_ground_net` docstring 写明"名称只是候选，角色来自声明与器件事实" |
| `src/boardwise/engines/layout.py` | `_net_kind` 改调 `is_ground_net`，删掉自带正则（第二处实现消除） |
| `tests/test_validate_spec.py` | 见下"被改既有测试"；新增 2 条路径覆盖测试 |
| `tests/test_blocks.py` | 新增 1 条：retired 键被 `_check_keys` 拒 |
| `tests/test_layout.py` | 新增 2 条：地表只有一处实现；VEE 不给地符号 |
| `tests/test_generate.py` | 新增 1 条：负电源不挂地旗标（计划级） |
| `tests/test_enet_parser.py` | `test_is_ground_net`：VEE 移入非地组（见下） |

**测试数变化**：831 → **837**（+6 = test_blocks +1、test_validate_spec +2、test_layout +2、
test_generate +1）。`test_enet_parser` 与两条重写的 levels 测试是原地修改，净增 0。

**被改既有测试逐条清单及理由**（共 4 条，其余 827 条一字未动）：

1. `tests/test_enet_parser.py::test_is_ground_net` —— 原来断言 `VEE` 是地。
   **被证伪的旧语义**（本任务裁决 2 明令 VEE 移出地表）。VEE 移入非地组，并补
   `VEE-5V` / `vee` 两个拼写。
2. `tests/test_validate_spec.py::test_a_declared_level_shifter_on_the_net_is_allowed`
   —— 原来断言"声明 `level_shifter` 就放行"。**就是本任务要删的豁免本身**。
   改写为 `test_no_declaration_makes_two_domains_on_one_net_legal`：同一场景现在必须
   FAIL，且断言违规文案含 "two IO domains"。
3. `tests/test_validate_spec.py::test_two_domains_without_a_shifter_between_them`
   —— 旧前提（"转换器不在犯事网上就不授权"）属于豁免的词汇表，豁免删掉后该前提不再
   指涉任何东西。改写为 `test_a_two_sided_shifter_joins_two_nets_each_in_one_domain`
   ——即**验收场景 2**：转换器两侧各接一张网、各侧电平与端口声明一致 ⇒ PASS。这条正是
   "合法转换根本不触发同网混接"的直接证明。
4. `tests/test_validate_spec.py` 的 `template_body` / `level_spec` 两个 helper —— 删除
   `level_shifter` 参数与那行 `body["level_shifter"] = True`。字段已删，helper 若不删会
   在加载期被 `_check_keys` 拒，属于 fixture 随字段删除的必要同步，不是语义改动。

**变异验证记录**（4 个，脚本先备份、断言锚点唯一、跑完还原并 sha256 复核；全部
"CAUGHT + restored byte-identical"）：

| # | 变异 | 结果 |
|---|---|---|
| M1 | `VEE` 加回 `GROUND_NET_PREFIXES` | **3 failed, 1 passed** —— 见下说明 |
| M2 | 同网多域降级为 `note`（恢复豁免的效果） | 3 failed |
| M3 | `level_shifter` 加回 `_TEMPLATE_KEYS` | 1 failed |
| M4 | 删掉 `_gate_levels` 的 `not entries` 守卫 | 1 failed, 2 passed |

M1 里通过的那条是 `test_the_layout_does_not_keep_its_own_ground_list`：它断言的是**两处
实现逐名一致**（VEE 加回后两边一起变，故仍一致）。这是刻意的分工——那条测试守"不许长出
第二处实现"，语义由另外三条明确断言 VEE 的测试承载，四条合起来才完整。M4 同理：它只负责
逼出守卫，另两条 levels 测试不受影响。

**`named` 隐患的处置与依据** —— 判定为**死代码，已删除**（`evidence=silent or named`
→ `evidence=silent`），并在原位留注释说明不变量。依据：

- `:825` 的 `if not entries or ...: continue` 保证进入后续代码时 `entries` 非空；
- `:855` 的 `if not domains` 意味着**没有任何**端口声明 level ⇒ `:845` 算出的 `silent`
  = `entries` 全体 ⇒ `silent` 必非空；
- 故 `silent or named` **必然短路**，`named` 永不被求值；而 `named` 在本函数内无任何
  定义 ⇒ 一旦求值就是 `NameError`。**"它不可能是活的"正是"它从未被跑过"的证明。**
- 分支本身可达（`test_a_net_with_no_levels_at_all_is_undecidable` 覆盖），只有备选操作数
  是死的，所以修法是删备选、不删分支。

**验收场景对照**：

| 场景 | 测试 |
|---|---|
| 1 同网混接 fail（无豁免） | `test_no_declaration_makes_two_domains_on_one_net_legal`、`test_two_domains_on_one_net_is_a_violation` |
| 1 键在加载期被拒 | `test_the_retired_level_shifter_flag_is_an_unknown_key` |
| 2 合法双侧转换 pass | `test_a_two_sided_shifter_joins_two_nets_each_in_one_domain` |
| 3 VEE 不判地 + 不挂地符号 | `test_is_ground_net`、`test_vee_is_not_given_a_ground_symbol`、`test_a_negative_supply_is_not_flagged_as_a_ground` |
| 4 既有语义不动 | 827 条未动；4 条例外见上 |
| 5 `_gate_levels` 全路径覆盖 | 6 条：skip-无端口(`test_a_connection_that_names_no_real_block_is_skipped`)、skip-非信号(`test_a_rail_on_the_same_page_does_not_switch_off_the_level_check`)、多域违规、无域不可判、部分静默不可判、全一致 pass |

**一处刻意不改（交卷说明）**：`parsers/schematic.py:1049` 另有一处硬编码地名集合
`("GND","AGND","PGND","DGND")`。它回答的是**另一个问题**——从**实测旗标**的 device title
前缀（`Ground-GND` / `Power-VCC`）判该旗标属于哪个图形族，且不含 VEE。它不是在问"这张网
是不是地"。按"最小改动、不顺手重构"的纪律未动，在此报备。

