# 058：审查 SOP 手册闸前置——`needs_datasheet[]` 双触发 + 「先问再判」（issue #8）

事故原文在 issue #8（2026-09-28，市电输入三相 BLDC 驱动板，只审原理图）：审查者绕过 `checkup` 走 `bridge call sch.netlist` + 人工清单，对一颗辅源 IC 的 `FB`/`ICG` 两脚**在没手册的情况下做了判定**，次日拿到手册证明两条全错（FB 悬空是厂家认可用法；ICG 是相对输出的参考点，接输出侧正确）。代价：一条不符合项撤回、一条存疑作废，设计人白看一遍。

三个既有缺口（issue 原文，裁决接受）：
① 闸只长在 `checkup` 报告里，绕过 checkup 的路径上没有它；
② 闸的判据是"规则判不了的器件"（facts 驱动），不是"审查者读不懂的管脚"；
③ "工程师给手册"是一条被动通道，SOP 里没有一处要求**停下来先索取**。

**本批纯离线**：不碰真机、connector、daemon、dsh。改四处：SKILL SOP、checkup 报告 schema、一个新小命令、报告模板。规则引擎一字不动。

## 一、SKILL SOP 加第 ⓪ 步（`.kimi-code/skills/boardwise/SKILL.md`）

在"审查三步"（§SKILL.md:86 起）**之前**插入第 ⓪ 步，措辞要点（执行者可润色，语义锁定）：

- **⓪ 先问再判（事前动作，阻塞）**：动手判定任何器件/管脚之前，先列出**"功能建立不起来的器件与管脚"**——`needs_datasheet[]`（报告里已有 facts 触发的种子；自己读不懂的管脚用 `boardwise need-datasheet` 标记补入）。清单非空时**一次性向用户索取**对应手册/资料，**资料到位前不得对依赖项下"通过/不符合"结论**，只能写"无法确认（等资料）"。
- **消歧段**（issue 建议 5，必须有）：「不许涂绿」是**事后标记**（判不了就如实说判不了，已有）；「先问再判」是**事前动作**（判之前先把未知项列出来索取资料，本步）。两句分管不同阶段，不许合并成一句。
- ② 手册闸一节同步改口：`needs_datasheet[]` 是唯一未知项清单（`unreviewed_parts[]` 是它的 facts 触发子集，保留原名不动）；`mayClaimPassed` 窄义不动，总闸看 `completion.verdict`。
- 边界（issue 原文，写死）：**不是**"等齐所有手册才准开工"——能算的先算（分压/耐压/降额/驱动电流独立算完），只把**依赖未知器件功能**的条目挂起；**不**默认自动联网抓手册（`parts fetch` 三通道现状不动）。

## 二、报告 schema `/5` → `/6`：`needs_datasheet[]` 一等节

只加不改名（031 家训）。`CHECKUP_SCHEMA = "boardwise.checkup/6"`，大注释块（cli.py:2340-2368）续一段 `/6` 说明。

- checkup 生成报告时即带 `needs_datasheet[]`：**触发源①（facts）** = 现有 `unreviewed_parts[]` 原样纳入（该节本身一字不动，053 窄义纪律）；**触发源②（marked）** = 审查者标记，生成时为空（审查还没开始）。
- 条目形状（字段名可微调，语义锁定）：

```jsonc
{
  "part": "U7", "pins": ["FB", "ICG"],          // facts 触发时 pins 可空（整颗未审）
  "trigger": "facts" | "marked",
  "reason": "…",                                 // marked 必填（审查者写的"为什么解释不了"）
  "dependentFindings": ["param-value-mpn-match@U7", …],  // findings 里 subjects 含该件的条目 ref
  "channels": { … }                              // facts 触发时沿用 unreviewed 的三通道状态
}
```

- `dependentFindings` 从既有 `findings[]` 按 subjects/designator 匹配**计算**得出（不动规则引擎，纯报告层后处理）。
- `summary.mayClaimPassed` **窄义不动**（仍只回答 unreviewed）；**总闸在 `completion`**：`completion.owed` 加 `needsDatasheet` 计数；verdict 规则加一条——`needsDatasheet > 0` ⇒ `incomplete`，`verdictWhy` 加 "N 项管脚/器件待手册（审查者标记）"（facts 触发已被 unreviewedParts 覆盖，不重复计——同一 (part) 两源命中时 marked 优先展示、计数只算一次）。
- `summary.conclusion` 在 marked 非空时加"另有 N 项管脚待手册（已标记）"字样。

## 三、新命令 `boardwise need-datasheet`（顶层叶子命令）

审查者标记通道（触发源②的输入口）：

```
boardwise need-datasheet --out <checkup-out-dir> --part U7 \
    --pins FB,ICG --reason "FB 悬空是否认可用法 / ICG 参考点不明"
```

- 读 `<out>/report.json` + 侧车 `<out>/needs-datasheet.json`（审计痕迹，append-only JSONL 或数组成员，执行者选但要在任务书交卷时说明），把标记合并进 `needs_datasheet[]`（trigger=marked），**重算** §二 全部闸字段（mayClaimPassed 除外——它窄义不动）、`completion.verdict/verdictWhy`、`summary.conclusion`，写回 report.json 并重渲染 report.md。
- **幂等**：同一 `(part, pin)` 重复标记 = 更新 reason、不新增条目；输出报告"已存在，已更新"。无 report.json → exit 3 报错（先跑 checkup）。
- `--pins` 可空（整颗器件读不懂）；空 pins 与 facts 条目撞 part 时合并展示不重复计数。
- 顺带核实：该命令本身**不**触碰编辑器（纯文件操作）；`--json` 输出合并结果。

## 四、报告模板（`render_report_markdown` + `SUMMARY_TEMPLATE`）

- report.md 新增「本报告依赖的未知项」一节：渲染 `needs_datasheet[]` 全量（两触发源分列、reason、dependentFindings、三通道状态）；**该节为空才允许出现"通过"字样**——节非空时节首固定一行"本节非空期间，本报告不得宣称审查通过"。
- `SUMMARY_TEMPLATE`（checkup.py 内）加同一名目的槽位，提示语写明"空着才允许写通过"。
- 既有各节渲染顺序、措辞不动。

## 五、守卫与复验

- 定向 pytest `--basetemp=.tmp_pt_79`；**全量归主代理**。eval holdout 59/59 双 1.00 红线（本批不动规则引擎，预期零波及，仍须复跑确认）。
- 既有套件零波及：checkup/report 家族、review-mark、`test_dsh_plugin_sync`（CLI 面新增叶子命令 = 动作目录同步检查会看见——按该测试既有登记方式登记，不许改测试放过）。
- 变异 ≥2 组，cp+sha256 还原：
  - M1：标记后闸不重算（`completion.verdict` 不变）→ 对应测试必须红；
  - M2：幂等键退化为恒新增 → 重复标记测试必须红。
- 离线场景 ≥4（分母含拒绝）：①checkup 生成即带 needs_datasheet（facts 种子在位、marked 空、schema=/6）；②标记一颗 → 闸全翻（verdict=incomplete、conclusion 带字、report.md 节渲染、dependentFindings 正确）；③重复标记幂等；④无 report.json → exit 3。
- 零 git 操作；不碰 README/PROGRESS/reviewsets/tests/fixtures 既有夹具；SKILL 只动 §审查三步 一带（坑表不动）。
- **上下文 500k 红线**：接近即停批换 resume，主代理看门。

## 六、交卷

- needs_datasheet 数据流（facts 种子 → marked 合并 → 闸重算 → report.md 渲染）+ 场景实测表。
- 自决项逐条；文件 sha256(12) 前后；定向计数；变异组与还原哈希。
- 给 issue #8 的回复草稿（主代理定稿后发）。
