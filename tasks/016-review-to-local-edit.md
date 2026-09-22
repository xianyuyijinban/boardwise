# 016 — Review-to-local-edit：单器件值修改闭环（M3 首切片）

> 2026-09-21 立项。方向来自岳的 M3 指令（原文在 PROGRESS.md 的"M3 入口复核"条）：
> 读取→发现→解释→**预览局部修改→用户授权→只改相关器件→回读验证→重新审查→保存并验证持久化**。
> 本切片只做**单器件值修改**（`component-value`），其余变更类型（补器件/修单脚/插子电路/移块）是 M3 后续任务。
>
> 基线：commit `91b67f3`，pytest **1145** / connector **279** / tsc 干净 / connector **0.4.10**。
> 执行者：DeepSeek 子代理（commandcode）。本文件是唯一规格来源；交卷写在 §八，复验写在 §九。

## 一、范围

**做**：`boardwise edit` 三命令（plan / preview / apply）+ `Finding` 结构化目标 + `ChangePlan` 数据契约 + 四个保护 + 离线/真机两级验收。

**不做**（越界即返工）：

- 不改 connector（零 TS 改动——`sch.set_component_attribute` 已存在，`docs/bridge.md:374`、`connector/src/actions.ts:986-1094`；契约守卫 `contract-drift.test.mjs` 必须原样绿）。
- 不做补器件、修引脚、插 RC/分压、移功能块（M3 后续）。
- 不做评测集扩充（那是 017 候选：8–12 独立板、dev/holdout 纪律，见路线书 §7）。
- 不动既有 15 条规则的判定逻辑（唯一的规则侧改动是给 `ValueMpnMatch` 的 VIOLATION 行**附带** target，见 §二.1）。
- 不碰 PCB 侧任何动作。

## 二、架构决策（已查证，含行号证据）

### 1. Finding 增加可选结构化目标（`rules/base.py`）

现状缺口（岳原话确认）：`Finding` 只有 `rule_id/severity/message/level/evidence: list[str]`（`rules/base.py:21-33`），位号靠事后正则（`engines/review.py:128-148`）。

新增：

```python
@dataclass
class FindingTarget:
    component_ref: str = ""        # 位号，如 "U3"
    primitive_id: str = ""         # 离线通常为空——见 §二.3
    pin_refs: list[str] = field(default_factory=list)
    net_refs: list[str] = field(default_factory=list)
    expected_before: str = ""      # 当前板上值，如 "4.7k"
    suggested_after: str = ""      # 建议改成的值，如 "1k"

# Finding 增加字段（默认 None，全部既有构造点零改动）：
target: FindingTarget | None = None
```

`Outcome` **不动**（eval harness 的配对语义一字不改）。threading 走 `FactsRule.findings_from`（`rules/facts.py:100-117`）：行元组从 `(Outcome, severity|None)` 放宽为**允许第三个可选元素** `target|None`（`row[2] if len(row) > 2 else None`）——其余 FactsRule 子类全部传二元组，行为不变。`ValueMpnMatch._rows`（`rules/params.py:141-269`）对 VIOLATION 行产出三元组：

- `component_ref = comp.designator`；`expected_before = comp.value`；
- `suggested_after` = decoded 值的人类记法（如 `1k`/`100n`）——**必须能被 `parse_resistance_ohms`/`parse_capacitance_farads` 回读成 decoded ±1e-3**（自洽：改完重审必须看到 OK，用现成的解析器做闭环校验）；
- `pin_refs`/`net_refs` 本切片留空（值修改不碰连接）。

只有 `param-value-mpn-match` 是首个"可修复"规则。其余规则 finding 的 `target=None`，CLI 对它们明确报"该规则不支持自动修改"（见 §四）。

### 2. ChangePlan 数据契约（新模块 `core/changeplan.py`）

不让模型直接生成 API 调用（岳指令）。dataclass + JSON load/dump + 校验，schema 用岳给的原文，仅一处语义修正：

```json
{
  "planVersion": 1,
  "source":  {"inputSha256": "...", "projectUuid": "...", "pageUuid": "...",
              "hostVersion": "3.2.186", "connectorVersion": "0.4.10"},
  "target":  {"primitiveId": "", "designator": "U3", "expectedValue": "4.7k"},
  "change":  {"kind": "component-value", "before": "4.7k", "after": "1k"},
  "preconditions": ["pageUuid still focused", "designator resolves on the page",
                    "Value is still 4.7k"],
  "expectedPostcondition": ["Value reads back as 1k",
                            "target review finding is resolved"]
}
```

校验规则（load 时）：`planVersion == 1`；`change.kind == "component-value"`（其余 kind 拒绝并说明是 M3 后续）；`inputSha256` 是 64 hex；`designator` 非空；`before != after`。

### 3. primitiveId 的时点修正（与岳 schema 的唯一偏差，事实依据）

岳的 schema 把 `target.primitiveId` 写成 plan 时已知。**实测不可行**：解析器的 `Component.uid` 是符号 uuid/part_id（`parsers/schematic.py:754-763`），不是 live primitiveId；位号→primitiveId 解析目前只存在于连接器内 review.mark 的 geometry dump 路径（`actions.ts:5190-5233`）。

**落地语义**：plan 只携带 `designator`；**apply 时在受守卫页上调 `sch.geometry`，按 Designator 解析出 primitiveId 并写进 apply 报告**。`sch.geometry` 返回组件 dump（含 Designator/primitiveId，`docs/bridge.md:357`）。位号解析不到（被删/改名）→ 前置条件失败，拒绝修改。**duplicate designator**（`core/model.py:101-105` 的 `duplicate_designators` 非空且含目标位号）→ plan 直接拒绝（跨页歧义，不猜）。

### 4. 持久化状态词复用 draw.py 五态（`engines/draw.py:117-121, 228-255`）

`not_placed / unknown / placed / saved_unverified / saved_verified`。复用，不新造词。`saved_verified` 桥建不了（无 close/reopen，009d 结论）——apply 报告封顶 `saved_unverified`；`saved_verified` 只由真机场景 6（重开验证）按 `docs/persistence-baseline.md` 的方法人工确认。超时/断连的处理模式照抄 `_call_write`/`_read_back_after_unknown`（`draw.py:323-421`）：**未知即回读，不盲重试**。

### 5. CLI 形态：`boardwise edit {plan,preview,apply}`

挂在现有 cli.py 子命令族里（参照 `_cmd_review` `cli.py:770-814` 与 `_cmd_review_mark` `cli.py:2875` 的风格）。三命令全部输出**结果 JSON**（`--json PATH` 出口）+ 人读摘要。

## 三、执行流逐步语义

### `edit plan --file <工程文件> --rule param-value-mpn-match --designator U3 [--after 1k] [-o plan.json]`

离线。解析文件 → 跑单条规则 → 找该位号的 VIOLATION finding（须带 target）→ 组装 ChangePlan：`inputSha256` = 文件 sha256；`before` = finding 的 expected_before；`after` = `--after` 指定或 suggested_after；`pageUuid/projectUuid` 从文件读取（取不到则置空字符串并在 plan 里注明，apply 时按 §四守卫兜底）。找不到 VIOLATION / 规则不支持 / duplicate 位号 → 非零退出并说明。

### `edit preview plan.json [--file <工程文件>]`

离线。重算文件 sha256 比对 `inputSha256`（不符→退出码 4 "快照已失效"）；重新解析确认目标仍存在且值仍 == `before`；打印语义差异（`U3.Value: 4.7k → 1k`）与将消除的 finding；几何差异说明（值属性改动只动 otherProperty，无位移——如实写"no geometric diff by construction"）。

### `edit apply plan.json [--file <工程文件>]`

真机（走 daemon/bridge）。严格顺序：

1. **前置重读**：`sch.geometry`（带 pageUuid 守卫语义——pageUuid 非空才传，空则先 `doc.focus` 确认当前页并如实记录"pageUuid guard unavailable, focused page used"）→ 位号→primitiveId + 当前 Value。**当前值 != before → 拒绝，退出码 4**（值已被人改动，旧快照失效）。
2. **单次写入**：`sch.set_component_attribute {primitiveId, key:"Value", value:after, pageUuid}`。范围守卫：本切片只允许这一个调用、这一个 key；`clobberedOtherKeys` 非空必须在报告里亮出（它整表替换，合并逻辑在 actions.ts:1059-1064，正常应为空）。
3. **回读验证**：不信 API 的 ok——先看动作自带 `applied`/`readBackAfter`（actions.ts:1071-1084），**再独立调一次 `sch.geometry` 复核** Value == after。不符 → `failed`，退出码 2。
4. **重复执行安全**：步骤 1 发现当前值已 == after → 不写，报 `already_applied`，退出码 0（幂等；值修改无重复创建问题，但必须显式识别）。
5. **超时/断连**：归类为 `unknown`，立即回读实际状态如实报告，**绝不重试**（draw.py:295-421 的模式）。
6. **保存**：`sch.doc.save`，检查应答（`_save_project` draw.py:424-451 的模式；save 抛错则 `saved_unverified`→如实报）。
7. **复查**：保存后重读 `--file` 磁盘文件（mtime 必须晚于 apply 启动时刻，否则复查结论 = `unknown` 并说明"保存未落盘或落盘延迟"）→ 重新解析 → 重跑 `param-value-mpn-match` → 目标位号 VIOLATION 消失 ⇒ `resolved`；仍在 ⇒ `still_present`（连同新 outcome 一起打印）；文件不可读 ⇒ `unknown`。
8. **报告**：结果 JSON（plan 摘要、解析到的 primitiveId、before/after、各步状态、最终 persistence 态、复查结论）+ 人读摘要。

退出码约定：0 成功/already_applied；2 回读失败；3 unknown（沿用 009d 语义）；4 前置条件失败/快照失效；5 用法/计划校验错误。

## 四、四个保护的实现映射（岳指令 → 代码）

| 保护 | 实现 |
|---|---|
| 1. 执行前重读，旧快照失效就拒绝 | §三 apply 步骤 1（geometry 重读 + before 比对）+ preview 的 sha256 检查 |
| 2. 只改目标局部 | 唯一一次 `set_component_attribute`、唯一 key `Value`、报告亮出 `clobberedOtherKeys` |
| 3. 回读不符即失败 | 动作自带 readBack + 独立 geometry 复核，双重（§三步骤 3） |
| 4. 超时/断连先回读、不盲重试 | §三步骤 5（draw.py unknown 模式） |

## 五、验收

**离线 10 用例**（`tests/test_016_*.py`，手工模型风格参照 `test_011d_rules.py:31-124`；CLI 流参照 `test_review_mark_cli.py` 的 stub daemon）：

1. plan：从夹具（注入板 `reviewsets/injected/value-mpn-mismatch.epro2`，U3 4.7k↔MPN 1k）生成，字段逐项断言（含 sha256 实算）。
2. plan：`--after` 覆盖 suggested_after。
3. plan：不支持的规则 id → 拒绝且信息说明。
4. plan：duplicate 位号 → 拒绝（可用毕设板标注集语义或合成模型）。
5. Finding target 线程：`ValueMpnMatch.check()` 的 VIOLATION finding 带 target 且 `suggested_after` 回读自洽（parse 回 decoded ±1e-3）；OK/UNKNOWN 行无 finding（既有行为不破）。
6. ChangePlan load 校验：坏 sha / kind != component-value / before==after / planVersion 错 → 各一条。
7. preview：新鲜快照 → 打印正确差异，退出 0。
8. preview：改动文件后 → sha 不符，退出 4。
9. apply（stub daemon）：前置值不符 → 拒绝，零写入调用（stub 断言 set_component_attribute 未被调）。
10. apply（stub daemon）：值已 == after → `already_applied`，零写入；正常路径 → 写入恰好一次、key 只有 Value、保存恰好一次、报告 JSON 字段齐。

**真机 6 用例**（test.eprj2 或专用 bw_scratch 页，R1–R3 铁律，证据落 `outputs/016_*`）：

1. 成功：放一个 MPN/值矛盾的电阻（如 MPN 解出 1k、值写 4.7k）→ plan→preview→apply → Value 变 1k、报告 `saved_unverified`、复查 `resolved`。
2. 值已被人工改动：apply 前在编辑器手改该值 → apply 拒绝（退出 4）、无写入。
3. 重复执行：连跑两次 apply → 第二次 `already_applied`，无重复写入。
4. 保存失败/异常路径：如实记录（若宿主无法模拟 save 失败，则记录"不可模拟"并把 save-ack 检查代码路径指出来，不许编造）。
5. 执行中断：人为断连（杀扩展/停网）后 apply → `unknown` + 回读如实状态，无重试。
6. 重开验证：apply 后关闭重开工程 → Value 仍为新值 → 人工确认 `saved_verified`（截图/记录落 outputs）。

**回归**：pytest 全量 + connector 279 原样绿 + tsc 干净。评审基线（`outputs/011e/014/015b` 系列数字）不许动——`review --json` 的 finding JSON 加了可选 `target` 字段，eval harness 的配对逻辑不得受影响（`review_eval.py` 只读它认识的键；补一条测试钉住"target 不进配对分母"）。

## 六、执行纪律（照 AGENTS.md 与历次任务书）

- 测试命令：`python -m pytest tests/ -q --basetemp=.tmp_pt_home`（Windows 必带，否则汇总行被吞假 exit 1）。
- 变异验证：交卷前做 ≥2 个变异（建议：①Finding.target 从 VIOLATION 行消失 ⇒ 离线用例 5 红；②apply 跳过前置重读直接写 ⇒ 用例 9 红），cp 备份 + sha256 还原，**禁用 `git checkout --`**。
- 真机作业先 `bridge status` 确认 daemon/connector 在线；R1（身份判定：工程名/页名/器件数/布线态/标记冲突）、R2（写前盘点）、R3（写后回读）。
- append 任务书后 `grep -c` 独立计数防双执行。
- 不动 git；不动 `outputs/011e/014/015b` 历史证据；临时文件写完即清。

## 七、已知的两个诚实边界（不许包装）

1. `sch.set_component_attribute` 的 pageUuid 守卫在 pageUuid 为空时不校验（`actions.ts:1921`）——apply 在 plan.pageUuid 为空时必须如实记录守卫降级（§三步骤 1），不得声称有页守卫。
2. `saved_verified` 无法由桥建立（009d 既有结论），真机场景 6 是人工确认项。

## 八、执行者交卷记录

> 2026-09-21 交卷（执行者：coder 子代理）。**只做离线部分**：§一"做"的范围里除真机 6 场景外的全部 + §五"离线 10 用例"。
> 真机 6 场景**未做**（§五下半），留给下一波。

### 1. 实现清单（文件:行号）

| 文件 | 位置 | 内容 |
|---|---|---|
| `src/boardwise/rules/base.py` | `FindingTarget` 类 22-41；`Finding.target` 字段 63 | 新增可选结构化目标，全部字段有默认值；`Finding` 只加一个字段，既有构造点零改动；`Outcome` 未动 |
| `src/boardwise/rules/facts.py` | `findings_from` 100-124 | 行元组放宽为"允许第三个可选元素"（`row[2] if len(row) > 2 else None`）；其余 FactsRule 子类全部传二元组，行为不变 |
| `src/boardwise/rules/params.py` | `_RESISTOR_PREFIXES`/`_CAPACITOR_PREFIXES` 112-115、`_human_value` 116-140、VIOLATION 行第三元素 301-314 | 只有 `ValueMpnMatch._rows` 的 VIOLATION 行产出三元组（`component_ref`/`expected_before`/`suggested_after`）；`outcomes()` 改 `row[0]` 以容纳三元组；其余 14 条规则一行未动 |
| `src/boardwise/core/changeplan.py`（新，438 行） | `PLAN_VERSION` 54、`ChangePlanError` 73、`sha256_of` 82、`PlanSource/PlanTarget/PlanChange/ChangePlan` 97-281、`component_value_plan` 301、`PageComponent/PageLookup` 353-379、`resolve_on_page` 396 | ChangePlan 数据契约 + JSON load/dump/校验 + 计划组装 + 页 dump 解析。纯离线，**不 import 任何层内模块**（`tests/test_layer_rules.py::test_core_imports_nothing_from_the_package` 绿） |
| `src/boardwise/cli.py`（+1178 行） | `edit` 子命令族 272-405；`REPAIRABLE_RULES` 3180 / `RULE_FOR_KIND` 3185 / `EDIT_WRITE_KEY` 3192 / `UNKNOWN_OUTCOME_CODES` 3200；`_edit_step` 3211、`same_board_value` 3231、`_boardwise_designator` 3264、`_findings_naming` 3280、`_snapshot_identity` 3295；`_cmd_edit_plan` 3360、`_cmd_edit_preview` 3544、`_edit_post_review` 3703、`_render_edit_apply` 3787、`_edit_apply_flow` 3839、`_cmd_edit_apply` 4166、`EDIT_COMMANDS` 4210；dispatch 4751 | plan/preview/apply 三命令，风格照 `_cmd_review`/`_cmd_review_mark` |
| `tests/test_016_edit_cli.py`（新，51 用例） | — | §五离线 10 用例 + 四个保护的真机替代断言 + eval 配对回归 + `_human_value` 全码空间回读 |

**零 TS 改动**：`connector/` 一个字节未碰（`sch.set_component_attribute` 已存在，apply 只是通过 daemon 调用它）。

### 2. 三线实测（016 改动在位）

```
cd /e/boardwise && .venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home
  → 1196 passed in 75.28s        （基线 1145，新增 51 = tests/test_016_edit_cli.py）
cd connector && npm test         → tests 279 / pass 279 / fail 0（与基线同）
cd connector && npx tsc --noEmit → 干净（exit 0）
```

**评审基线复核（target 字段不影响配对分母）**：按 015 任务书的逐字命令复跑两份当前基线报告，**逐字节相同**：

```
diff outputs/015b_eval_dev.txt     /tmp/.../eval_dev.txt      → 无差异
diff outputs/015b_eval_holdout.txt /tmp/.../eval_holdout.txt  → 无差异
```

（`outputs/011e_*`、`014_*` 未复现：它们的数字在 **015b 那批规则改动**里就已移动——011e 的 golden 是 2 WARN、value-mpn-mismatch 是 1 WARN，015b 起是 1 WARN / 2 WARN，差值就是 015b 的幅度容忍裁决，与本任务无关；四个历史文件一个字节未改，`git status` 无 `outputs/` 项。）

### 3. 变异验证（3 个，cp 备份 + sha256 还原，未用 `git checkout`）

| # | 变异 | 期望红 | 实测 | 还原 |
|---|---|---|---|---|
| 1 | `params.py` VIOLATION 行删掉 `FindingTarget(...)` 第三元素 | §五用例 5 红 | **22 failed / 29 passed**，含 `test_the_violation_row_carries_a_target_and_the_other_rows_do_not`、`test_plan_states_every_field_of_the_schema` | `cp` 回填，`sha256sum -c` OK（`a548fdef…`） |
| 2 | `cli.py` apply 跳过前置值比对（`if not holds:` → `if False:`） | §五用例 9 红 | **1 failed / 50 passed**，正是 `test_apply_refuses_a_precondition_mismatch_with_zero_writes`（assert 0 == 4：本该零写入，实际写完了） | `cp` 回填，`sha256sum -c` OK（`8898dda9…`） |
| 3 | `cli.py` apply 忽略独立回读（`if not matched:` → `if not matched and False:`） | 保护 3 的用例红 | **1 failed / 50 passed**，`test_apply_fails_when_the_independent_readback_disagrees`（assert 0 == 2） | `cp` 回填，`sha256sum -c` OK |

三次变异后均重跑 `tests/test_016_edit_cli.py` 全绿（51 passed）。

### 4. 离线 10 用例对照（§五）

| # | 用例 | 测试 |
|---|---|---|
| 1 | plan 字段逐项（含实算 sha256） | `test_plan_states_every_field_of_the_schema`（`hashlib.sha256` 独立实算，不用 `sha256_of`） |
| 2 | `--after` 覆盖 suggested | `test_after_overrides_the_findings_own_suggestion` |
| 3 | 不支持的规则 → 拒绝＋说明 | `test_an_unknown_rule_is_refused_with_the_known_ids`、`test_a_rule_without_a_target_is_refused_by_name`（含"该规则不支持自动修改"原文） |
| 4 | duplicate 位号 → 拒绝 | `test_a_duplicate_designator_is_refused_rather_than_guessed`（用 `duplicate-designator.epro2` 的 R24） |
| 5 | Finding target 线程 + 回读自洽 | `test_the_violation_row_carries_a_target_and_the_other_rows_do_not`、`test_every_suggested_value_round_trips_through_its_own_parser`（90 个 EIA 码 × 2 类全过）、`test_a_hand_built_model_threads_one_target_per_contradiction` |
| 6 | ChangePlan load 校验 4+ 条 | `test_a_plan_this_build_cannot_execute_is_refused`（9 个参数化）、`test_a_bad_kind_says_which_m3_follow_up_owns_it`、`test_a_valid_plan_round_trips_through_json`、`test_a_missing_plan_file_is_refused_not_ignored` |
| 7 | preview 新鲜 → 退出 0 | `test_preview_prints_the_diff_and_the_finding_it_would_silence` |
| 8 | preview 改文件 → sha 不符退出 4 | `test_preview_refuses_a_stale_snapshot_with_exit_4`、`test_preview_refuses_a_target_whose_value_moved`、`test_preview_without_file_refuses_because_it_cannot_check` |
| 9 | apply 前置值不符 → 拒绝、零写入 | `test_apply_refuses_a_precondition_mismatch_with_zero_writes`（`daemon.writes() == []`） |
| 10 | apply already_applied 零写入 / 正常路径一次写入 | `test_apply_recognises_a_value_that_is_already_there`、`test_apply_writes_once_reads_back_saves_and_re_reviews`（写入恰好 1 次、`key` 只有 `Value`、`save` 恰好 1 次、JSON 字段齐） |

额外覆盖（同一批测试里）：写超时 → 退出 3 ＋ 回读 ＋ 不重试（保护 4）、`clobberedOtherKeys` 亮出（保护 2）、页不匹配拒绝、页上无 Value 拒绝、位号歧义拒绝、save 被拒 → `placed`、无 pageUuid 时如实报"守卫降级"、无 daemon 退出 2。

### 5. 偏差与待裁（如实上报，未自行扩 scope）

1. **`target.primitiveId` 在 plan 里恒为空**（§二.3 已授权的唯一偏差）：落地为"apply 时用 `sch.geometry` 解析位号 → primitiveId 并写进 apply 报告"（报告字段 `resolved.primitiveId`）。实测确认 `.epro2` 与解析器都拿不到 live id。
2. **`source.projectUuid` 在 plan 里恒为空**（**新事实，任务书未预告**）：§二.2 的 schema 要求该字段，但 `.epro2` 里**根本没有** project uuid——`project2.json` 只有 `title/cbb_project/editorVersion/introduction/description/tags`（实测），DOCHEAD 只有各文档自己的 uuid。落地：plan 写空串，并在 CLI 摘要里明说原因；**apply 报告用 `doc.list` 的 `projects[].projectUuid` 填 `projectUuid`**（唯一权威）。schema 未加字段。
3. **`edit preview` 强制要 `--file`**（任务书写 `[--file]` 可选）：plan 不携带输入路径（schema 只有 `inputSha256`），没有文件就没有可比对象，protection 1 会形同虚设。缺 `--file` 时报错退出 5 并说明原因，而不是"跳过检查通过"。若岳要"无文件也能预览"，需给 schema 加输入路径字段——**待裁**。
4. **退出码映射的一处收窄解释**：§三只规定了"回读失败=2"，我把 2 读成"**承诺的效果不在板上**"，覆盖：写入被拒、独立回读不符、save 被宿主拒绝、复查 `still_present`。3 仍是"页面状态无法陈述"（超时/断连）。其中 **save 被拒 → 2（不是 0）** 与 **复查 still_present → 2** 两条是任务书未明说处，**待裁**（我认为"改动只在内存里、未落盘"和"改完发现还在"都不该报成功）。
5. **§三步骤 7 的前提在本机不成立（重要事实）**：复查要求"保存后重读 `--file` 磁盘文件，mtime 必须晚于 apply 启动时刻"。但 `sch.doc.save` 保存的是编辑器里的工程，**不会重写 `.epro2` 备份文件**；而 live 工程 `.eprj2` 又不在 `_load_model` 的输入类型里（只支持 `.enet`/`.epro2`）。落地行为：mtime 未前进 → 复查结论 `unknown`＋原因"保存未落盘或落盘延迟"，**绝不冒充 resolved**。真机场景 6/1 若要看 `resolved`，需在 apply 后另存一份新 `.epro2` 再喂给 `--file`——**下一波真机执行者须先定这个口径**（属待裁/待定流程，不是代码缺陷）。
6. **`core/` 不能 import 规则层**，故值比较 `same_board_value` 落在 `cli.py`（`core` 只放数据契约与页 dump 解析）；这条是仓库既有分层铁律（`tests/test_layer_rules.py`），不是自由选择。
7. **plan 的 `-o` 可选**：缺省时把 plan JSON 打到 stdout（人读摘要仍在），`--json` 才是命令结果报告——与 `review --json` 的命名保持一致。
8. **未做**：真机 6 场景（§五下半）、PCB 侧、补器件/修脚/插子电路/移块（M3 后续）、评测集扩充（017）。任务书 `-o` 等其余签名逐字实现。

### 6. 清理

临时文件（变异备份、eval 复跑输出）写完后即删；`git status` 只有 4 个改动文件 + 2 个新文件（`src/boardwise/core/changeplan.py`、`tests/test_016_edit_cli.py`），**未动 git**。

## 九、Kimi 复验落笔（2026-09-21，全部亲为）

- **三线亲跑**：pytest **1196 passed**（73s，`--basetemp=.tmp_pt_home`）；connector **tests 279 / pass 279 / fail 0**；tsc 干净。
- **抽 diff 亲看**：`base.py` FindingTarget（empty `primitive_id` = "离线不可解析" 而非"无 primitive"，语义正确）、`facts.py` 三元组放宽（`row[2] if len(row)>2`，向后兼容）、`params.py` `_human_value`（电阻/电容前缀分表 + 6 位有效数字 + 全 EIA 码空间回读钉住）、`cli.py` apply 核心段（3928-4034：doc.list 页交叉核对→守卫降级如实记录→geometry 前置重读→位号 missing/ambiguous/no-id/no-value 四种拒绝→**幂等先于失效**（3983 先于 3993，顺序正确）→单次单 key 写入→unknown 只回读不重试）。与 §二~§四 一致。
- **独立变异抽验（自做，非执行者那三个）**：`changeplan.py` 删 kind 门（`if kind not in SUPPORTED_KINDS` → `if False`）→ **2 failed / 49 passed**（含 `test_a_bad_kind_says_which_m3_follow_up_owns_it`）；cp 还原 sha256 `815f8822…` OK，还原后 51/51 绿。
- **偏差逐条裁决**：①primitiveId 恒空（§二.3 已授权）、②projectUuid 恒空（.epro2 无此字段，apply 用 `doc.list` 补——新事实，落地合理）、③preview 强制 `--file`（否则保护 1 形同虚设）、④退出码收窄解释（save 被拒→2、still_present→2，"承诺的效果不在板上"——接受，不改报告口径）、⑥core 分层铁律、⑦`-o`/stdout 命名——**全部接受**。⑤复查前提（`.eprj2` 不可解析、save 不重写 `.epro2`）→ **转波②前置：真机先 probe `sch.readback` 是否带 value/mpn/footprint 字段**；够则单规则复查走 readback 轻量模型，不够则流程定为"apply→save→另存新 .epro2→`--file` 喂新文件"，波②派单时先定口径再跑场景 1/6。
- **结论**：波①通过复验。待岳：波①全部变更的提交点头（git status：4 改 `cli.py/base.py/facts.py/params.py` + 4 新 `changeplan.py/test_016_edit_cli.py/016 任务书/017 草稿`，其中 017 草稿可单提或随 016 一起）。

## 十、波②真机执行记录（2026-09-21 21:14–21:24，执行者：coder 子代理）

> **状态：受阻未完成。6 个真机场景 0 个跑完。** 并附带一起 R1 事故报告，必须岳/主代理裁决。
> 本节的写法刻意不是"交卷"——没有一条真机结果被声称完成。

### 1. 结论速览

| 场景 | 状态 | 依据 |
|---|---|---|
| 0 probe（§九.5 前置） | **PASS（已完成）** | 口径判为"不够"，见下 §2；证据 `outputs/016_probe_readback.txt` |
| 1 成功（plan→preview→apply→resolved） | **FAIL/未执行** | 需要磁盘 .epro2，本环境无导出动作，需岳手动导出一次；且环境不可用（§4） |
| 2 值已被人工改动 → 退出 4 | **未执行** | 依赖场景 1 的 plan |
| 3 重复执行 → already_applied | **未执行** | 依赖场景 1 的 plan |
| 4 保存失败 | **不可模拟（已如实记录）** | `outputs/016_scene4_save_path.txt`：宿主无手段让 `sch.doc.save` 失败，路径已点名 |
| 5 执行中断 → unknown | **未执行** | 依赖场景 1 的 plan |
| 6 重开验证 → saved_verified | **未执行** | 需岳关闭重开工程；且依赖场景 1 |

### 2. probe 结论与复查口径（§九.5 前置，已定）

`sch.readback`（含 `includePrimitives`）**不够**：

- 组件行是写死的键集合（`connector/src/actions.ts:619-627`）：`primitiveId/designator/name/footprint/supplier/supplierId/manufacturer/x/y/rotation/net|layer/fields`。**footprint 有**（独立键），**value 无、mpn 无**。
- 决定性的一条：`snapshot()`（`actions.ts:218-241`）只取 `getState_*()` 标量，对象一律降为 `{object: true}`；而 Value 与 Manufacturer Part 位于宿主对象 `OtherProperty` 内——实测行里 `OtherProperty` 正是 `{"object": true}`。`param-value-mpn-match` 要同时拿到 value 与 mpn，缺 mpn ⇒ 规则只会出 UNKNOWN，复查永不可能 resolved。
- 采样限制如实记：test 工程 P1..P4 four pages 每页只有自己的页框（`Counter({'ATTR':32,'LINE':n,'META':1,'COMPONENT':1})`），**没有真实器件可采**，所以本波没有"真器件 fields 里有没有 Value"的直接观测；但上面的结构性证据（mpn 通道不存在）与样本无关，足以定口径。

**定下的复查口径**：`apply → save → 请岳"文件→导出→工程备份"另存一份新 .epro2 → boardwise review --view schematic --file <新文件>`。
（用 `review` 而非 `edit preview`：后者会因 `inputSha256` 失配按设计退出 4。）

**顺带查实**：本环境**没有任何工程导出/备份动作**——`sys.probe` 枚举 `dmt_Project`（12 成员：copy/create/delete/getAllProjectsUuid/getCurrentProjectInfo/getProjectInfo/…/openProject）无 export/backup/saveAs；`sys_FileSystem` 的 saveFile 等只落编辑器自有沙箱；`sys_FormatConversion` 只做 Altium/DISA 库转换；`sch.doc.save` 实测（21:20:58 `{"saved": true}`）**不写 .eprj2、也不生成 test_backup 新文件**。

### 3. R1 事故（必读，未清理）

`sch.doc.save`（21:20:58）与 `sch.doc.new`（21:21:10）**落到了 test2 工程**（不是任务书指定的 test）：
test2 被加进一个**空页 P4**（uuid `d228ce3582bd748f`），且已**落盘**到 `E:\LC Project\test2.eprj2`
（mtime 2026-09-19 13:07 → 2026-09-21 21:21:10；该 uuid 在文件里出现 7 次）。
test 工程与其余工程一字节未动（`test.eprj2` mtime 仍 13:14:20）。**未私自删除**该页。

**根因是环境缺陷，不是岳改工程**：daemon 同时被**两个编辑器实例**抢占 connector 槽位，
自 ~19:19 起严格 5 分钟交替（审计日志 hello）：`…21:07:16 0.4.10 | 21:12:16 0.4.9 | 21:17:16 0.4.10 | 21:22:16 0.4.9…`；
实例↔工程实测锚定：**0.4.9 实例 = /test**，**0.4.10 实例 = /test2**。
⇒ R1 的"写前 doc.list 核对"**天然不够**：我 21:16:51 的核对是对的，21:21:10 的写已换对手；
daemon 无法钉住实例（一个 pair 哈希 `962bf45e`，两实例共用同一 token 文件）。
危险面不止 test/test2——另一实例聚焦哪个工程不可知，若落在生产工程（毕设FOC驱动板/CH340G）上，同样的写就会打上去。

**另推翻任务书步骤 0 的一个前提**：本桥**建不出指定名字的 bw_scratch 页**。
`sch.doc.new`（`actions.ts:1950-1995`）复用 `dmt_Schematic.getCurrentSchematicInfo()` + `createSchematicPage()`，
只往**当前聚焦工程**里追加一页，页名由编辑器编号（故实测得到的是 "P4" 而非 "bw_scratch"），`params.name` 仅在需要 `createSchematic` 时生效。

**建议处置（均未执行）**：① 岳关掉重复的那个编辑器实例，之后连续 ≥12 分钟反复
`sys.probe`+`doc.list` 确认 `connector` 与工程名都不再变，环境才算可用；② P4 的删除（
`bridge call --action doc.delete_page --params '{"pageUuid":"d228ce3582bd748f"}'`，需在 0.4.10 窗口内）或编辑器内手删，**等岳点头**；③ 环境干净后再恢复波②。

**可用判据**（本波实测）：`sys.probe --params '{"checks":true}'` 的顶层 `connector` 字段 + `doc.list` 的 `projects[].name`，一次调用组的头尾各查一次，才能回答"这一秒是谁在应答、它开着哪个工程"。

### 4. 波②恢复时的下一步（已核对过的顺序）

1. 岳：确保只剩一个编辑器实例；把 **test** 工程聚焦。
2. 我：`sys.probe`+`doc.list` 双查 → 建矛盾件（**不用 `sch.doc.new`**，改用 test 已有的空页 P1..P4 之一，
   在其上 `sch.place_component` 放一个 MPN 解出 1k 的真电阻，再 `sch.set_component_attribute` 把 Value 写成 4.7k）；
   `sch.doc.save`。
3. 岳：文件→导出→工程备份，另存 .epro2（导出#1）。
4. 我：`edit plan --file 导出#1 --rule param-value-mpn-match --designator <位号>` → `edit preview` → `edit apply --file 导出#1`
   → 期望 Value=1k、persistence=`saved_unverified`（复查按 §2 口径在导出#2 上做）。
5. 场景 2/3：再建/复用矛盾件，写前 `set_component_attribute` 手改值 → apply 期望退出 4 零写入；场景 1 的件再 apply 一次 → `already_applied`。
6. 场景 5：停 daemon（`taskkill //PID <pid> //F`，**别动编辑器**）→ apply 期望退出 3 unknown + 回读 + 不重试 → `bridge start` 恢复。
7. 场景 6：岳关闭重开 test 工程 → 我回读 Value 仍为 1k → 人工确认 `saved_verified`；同时请岳导出#2 → `review --view schematic --file 导出#2` 确认该位号不再有 VIOLATION（= 场景 1 的 `resolved`）。
8. 收尾：删除为本次作业新增的临时件/页（`doc.delete_page` / `sch.delete_primitives`），把 daemon 与编辑器恢复到本波开始前的状态。

### 5. 本波落盘

- `outputs/016_probe_readback.txt`（场景 0 原始输出 + 口径）
- `outputs/016_scene4_save_path.txt`（场景 4 不可模拟 + `cli.py:4118-4143` / `draw.py:424-451` / `actions.ts:2505-2513` 路径）
- `outputs/016_incident_test2_page.txt`（R1 事故全证据）
- **未动** git；**未动** `outputs/011e|014|015b` 任何历史文件；未动 test.eprj2。

### §十.5 波②阻塞②：两层焦点不一致，编辑器实际打开的是禁地工程（2026-09-21 23:50）

- 现象：doc.list 报 focused=/test（ea80fff），但 document.current 的 tabs 属于工程 8f9de877…（活动=PCB1）——磁盘比对证实 = **ROBOT ctrl FOC.eprj2**（岳的真实工程，禁地）。
- doc.open 对 test 的三个 uuid 形态（页/原理图/PCB）全部 CONNECTOR_ERROR——openDocument 在**活动工程**内寻址，找不到是对的，守卫未放行越界写。
- 结论：**doc.list 的 focused 不可信；写前身份判定必须以 document.current 的活动文档所属工程为准**，两层一致才可写。skill §18 已记的"工程焦点 vs sch 上下文页可报不同答案"升级为：focused 工程都可能不一致。
- 待办：岳手动关 ROBOT ctrl FOC → 打开 test → 打开 P4 页，之后重做 R1 双查再放件。

### §十.6 存储架构实测（2026-09-22 00:0x，修正验证口径）

- test.eprj2（5.2MB）= **工程目录册**：projects / project_structures（165 行页目录快照）/ history_data / project_images。save 落盘的表现 = 结构版本 updateTime 刷新（实测 = save 时刻毫秒戳）+ mtime 跳变。
- **器件级内容不在 .eprj2 内**：新放的 R1（uuid hex/二进制）、MPN、连上午就存在的 sheet 符号 uuid，全部 0 命中；E:\LC Project 全目录、Documents\LCEDA-Pro\{projects,database}、Local cache.model.2 明文扫描均 0。页内容分离存储，物理落点未定位（疑似本地服务端 LevelDB/snappy，明文不可 grep——未坐实，不再追）。
- 推论：上午 S3"save 后 mtime 跳变"只验证了结构层落盘；器件删改的落盘从未被内容级验证。test2 删 P4 验证成立是因为删页动的是结构层。
- 口径修正：**器件级持久化验证只能走编辑器自身通道**（关闭重开 → readback/导出 .epro2 → review --file），即任务书原定复查口径；grep 工程文件此路不通，从验证方案中删除。
- 当前状态：R1 已放 P4（e2e80ca2，Value=4.7k 回读 applied，MPN=0603WAF1001T5E/C21190），save 已发（结构层落盘确认）。等岳导出 #1。

### §十.7 波②场景实测（2026-09-22 00:30，Kimi 亲跑）

- 场景 1（成功）：apply exit **0**。四保护全过：写前 geometry 重读 → 单键写入 → 独立 geometry 回读 '1k' 匹配 → save。target 经 geometry 解析 = d815177955d60842。persistence=**saved_unverified**（无 close/reopen 动作，如设计）。证据 `outputs/016_apply1.json`。
- 场景 3（重复执行）：第二次 apply exit **0**，`already_applied`，零写入。证据 `outputs/016_apply2_idempotent.json`。
- 场景 2（人工改动）：set Value=2.2k 模拟人工 → apply exit **4** `refused: stale_before`，零写入。事后恢复 1k + save。证据 `outputs/016_apply3_stale.json`。
- 场景 5（中断）：taskkill daemon 后 apply → **实测 exit 2（任务书期望 3）**。根因 `cli.py:4201` 连接失败 return 2；按 CLI 自身契约（"3 = the page's state cannot be stated"）连不上时页状态不可陈述，应归 3。**判为波①实现 bug**，列入 016 收尾修复（改 return 3 + 补测试）。不重试 ✓（单次连接失败即退）。
- 场景 4：不可模拟（§十.3 已记录）。
- 场景 6：挂起（需岳关闭重开工程 + 导出 #2）。R1 当前值 1k 已 save。
- 素材注记：R1 初版用 0603WAF1001T5E（EIA-96 4 位码 1001）只会 UNKNOWN——解码器白名单边界，非 bug；已换 FRC0805J102 TS（尾码 102 → 1kΩ 可读）。
- 插曲：apply 前身份双查抓到编辑器实际打开的是 ROBOT ctrl FOC（§十.5）；doc.open 三连拒未放行越界写。

### §十.8 场景 6 终裁（2026-09-22 10:1x，Kimi 亲跑）——PASS，saved_verified

- **推翻 §十.7 后今晨的 FAIL 初判**（outputs/016_scene6_result.txt 已标注作废）：编辑器整关重开后 08:58 读到"P4 只剩 sheet"是**同步滞后的陈旧视图**；~09:03 同步追平，R1（uuid d815177955d60842）带 `Value=1k` 完整复活（OtherProperty.Value 通道实证）。
- 导出 #2（岳重导，同名覆盖 #1）`review --view schematic`：**3 件 6 网，findings 0/0/0**——param-value-mpn-match resolved；直读导出原始记录防伪：R1 ATTR 含 `Value="1k"` + MPN/Supplier Part 齐全（规则是看到一致而通过，非读不到值而跳过）。证据 `outputs/016_scene6_final.txt` / `016_scene6_review2.{json,md}`。
- 现场清理：bridge 删 R1+R3（实验件）→ readback 剩 sheet+R2（岳手件保留）→ save ✓。
- **016 六场景全部落定**：1/2/3/5 波②过、4 不可模拟、6 本场景 PASS（saved_verified）。审查链"保存并验证持久化"器件级成立。
- 教训（已进 skill 坑表 §19）：① 编辑器重启后读数须防同步滞后旧视图；② review .epro2 缺省 view=board，审原理图必须 `--view schematic`（缺省对空 PCB 工程报 0 组件且无提示——朋友 UX 改进候选）；③ 临时脚本勿用未验证的响应键（geometry 无 `parts`，是 `components`）。
