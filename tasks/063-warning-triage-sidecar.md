# 063：warning_triage 侧车 + `boardwise triage` 写回命令（issue #12）

来源：GitHub issue #12（岳亲笔，真机复现）。`warning_triage[]` 是唯一留不住的 AI 槽位：
填了 `verdict`/`reason` 后 ①没有任何命令重算 `completion`（`warningsPendingTriage` 恒为旧值），
②重跑 `checkup` 覆盖 `report.json`，填好的分诊**整份静默丢失**。对照组：`needs_datasheet[]`
在 058 有侧车（`needs-datasheet.json`）+ 写回命令（`need-datasheet`），重跑不丢还有提示。
**同构对齐 058，不发明新形态。**

## 已查证的事实（主代理亲验，子代理不必重复）

- 槽位生成：`src/boardwise/engines/checkup.py:1150 warning_triage_slots`，三个来源三种身份：
  - `host-erc`：每 kind 一行（`drc.schematic.totals`），text 为空；
  - `pcb-drc`：每叶一行，label=ruleName/errorType，带 net；
  - `boardwise-rule`：WARN finding，`rule_id` + `refs`。
  `verdict`/`reason` 留空给模型填；合法 verdict 在 `TRIAGE_VERDICTS`（checkup.py，先读它的定义）。
- completion 重算**已经是现读**：`cli.py:2775` `pending = sum(1 for entry in triage if not verdict.strip())`，
  `_completion_from_report`（cli.py:2866）以 `triage=report.get("warning_triage")` 传入（cli.py:2891）。
  所以 #12 的「另建议」已天然满足——**缺的不是重算逻辑，是触发重算的写回命令**。
- 058 模板全套在 cli.py：`NEEDS_DATASHEET_FILE`（2906）、`_load_need_marks`/`_write_need_marks`/
  `_merge_need_mark`、`need-datasheet` 命令体（3882 起：读 report.json+侧车→合并→
  `_apply_needs_datasheet`（3022：写回+重算 completion）→`_write_checkup_report`+
  `_write_checkup_markdown` 重渲染）；checkup 生成时并入侧车并在 `source.notes` 提示
  （3663-3690），末尾 print 提示未并入标记（3840-3842）。exit 码约定：0 applied / 2 输入不可用 /
  3 没有 report.json。
- `warning_triage_note`（cli.py:3718-3719）现在让模型"逐条填 verdict"——**没给命令名**，
  这是发现性缺口，本次一并修。

## 架构裁决（不再变动）

### 1. 槽位加身份键 `key`（report.json 仅增量加一个字段，无结构破坏）

- `engines/checkup.py` 新增 `triage_key(entry) -> str`，并在 `warning_triage_slots` 生成的
  每个槽里嵌入 `key` 字段。键配方按来源：
  - `host-erc:<severity>`
  - `pcb-drc:<severity>:<label>:<net>`（label 即 ruleName/errorType）
  - `boardwise-rule:<rule_id>:<逗号连接的 refs>`（对齐 036 的 finding 身份纪律）
- 键在生成处一次算好（单点，无漂移）；合并方与命令方都直接读槽里的 `key`，不重算。

### 2. 侧车 `warning-triage.json`（与 needs-datasheet 同构）

- `{"version": 1, "entries": [{"key", "verdict", "reason", "source", "text"}]}`——
  source/text 只为让人读侧车时知道这条在说什么，不参与匹配；匹配只认 `key`。
- 只有 `triage` 命令写它（与 needs-datasheet 的所有权纪律一致）。

### 3. checkup 生成时并入 + 提示

- 生成槽位后读侧车：键匹配 → 回填 `verdict`/`reason`；统计 并入 N 条 / 未匹配 M 条。
- `source.notes` 加一条提示（措辞对齐 needs-datasheet 的既有 note）；末尾 print 区的
  needs_datasheet 提示旁，侧车有未匹配条目时同样点名（未匹配=旧警告可能已消失，条目留在
  侧车里当审计轨迹，**不删**）。

### 4. 新命令 `boardwise triage`

- 参数：`--out <dir>`（必填）、`--key <key>`（必填）、`--verdict`（必填，choices=TRIAGE_VERDICTS）、
  `--reason`（必填，空则 exit 2 并说明理由必填的原因——对齐 need-datasheet 的 --reason 纪律）、
  `--json-path`（可选，对齐 need-datasheet）。
- 流程照 3882 模板：读 report.json + 侧车 → 按 key 找槽（**找不到 = exit 2**，stderr 列出当前
  待分诊的 key 清单—— typo 不许静默）→ 写槽的 verdict/reason → 侧车按 key 幂等 upsert →
  重算 completion（`_completion_from_report` 现读 triage，已满足）→ `_write_checkup_report` +
  `_write_checkup_markdown` 重渲染。`_apply_needs_datasheet` 对 `summary.conclusion` 做了什么，
  这边就做对应的（先读 3022-3050 确认它动了哪些字段，命名 `_apply_warning_triage`）。
- exit 码：0 applied / 2 输入不可用（含未知 key）/ 3 没有 report.json。
- 重复执行同一 key = 更新，不新增行（幂等，与 need-datasheet 同）。

### 5. 发现性

- `warning_triage_note` 改为点名命令：「逐条用 `boardwise triage --out <dir> --key <key>
  --verdict 有益|有害|无害 --reason …` 填」。
- SKILL.md 若 SOP ② 提到"手填 report.json"，改成点名命令（先 grep，没有就不动）。

## 验收

1. 新测试（找 058 的 need-datasheet 测试文件并同构扩展，basetemp `.tmp_pt_85`）：
   - 槽位 `key` 三来源配方各一例钉死；
   - checkup 并入：侧车命中回填 + 未命中保留 + notes/print 提示；
   - `triage` 命令：写入→completion.warningsPendingTriage 立刻减一→report.md 重渲染含 verdict；
     幂等（同 key 两次=更新）；未知 key exit 2 且列出待分诊 key；空 reason exit 2；
     无 report.json exit 3；
   - **#12 复现路径全程回归**：checkup → triage 填 3 条 → 重跑 checkup → 3 条 verdict 还在、
     pending=0、verdict 不再说"待分诊"。
2. 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 全绿（基线 2380）。
3. 变异 ≥2 组（cp+sha256 还原，禁 git checkout）：如 ①并入匹配改成永不命中 → 回填测试红；
   ②幂等 upsert 改成 append → 幂等测试红。
4. PROGRESS.md 不动（主代理收口写）。

## 边界与纪律

- 只碰：`engines/checkup.py`、`cli.py`（checkup/triage 区，**别碰 install-skill/doctor 区——
  另一个任务在改**）、checkup/need-datasheet 相关测试文件、`tasks/063*`、SKILL.md（仅 §5 所述）。
- pytest 必带 `--basetemp`；零 git 写操作；注释密度跟周边一致。
- **真机不碰**：本批全离线（report.json 夹具自造，别用 tests/fixtures 既有夹具，新建自己的）。
