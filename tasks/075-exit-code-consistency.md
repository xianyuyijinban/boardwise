# 075：退出码一致性（re-gate 重算 + `review --live` 空模型）

## 来源与裁定

073 交卷记录「待裁」两节的①②，岳裁：**A 修**、**B 要对齐**。两条互不相干，同一次派单
（A 先、B 后，串行）。073 已把「审查没看全」落成 `verdict: incomplete ⇒ exit 3`，并立下
**一处算出、三处渲染**（进程码 / `report.json` 的 `summary.exitCode` / `report.md` 的
「（退出码 N）」）的单源纪律（#15 同款）。这两条都是那条纪律没铺到的边：

- **A：re-gate 不重算退出码。** `boardwise need-datasheet`（`_apply_needs_datasheet`）与
  `boardwise triage`（`_apply_warning_triage`）会重建 `completion`、重写 `report.json`、
  重渲染 `report.md`，但**不动 `summary.exitCode`**。于是一块 `complete`（exit 0）的板被标上
  一脚 need-datasheet 后，报告里写着 `verdict: incomplete`，紧挨着的却是「（退出码 0）」——
  工具自己自相矛盾。
- **B：`review --live` 的空模型仍退 0。** 空读谓词 `_model_read_nothing`（`empty_pcb_view ∨
  empty_model`）被 `path is not None` 限定（019/072 的既有设计：那条 note 是针对*文件*写的），
  live 分支 `path=None` 绕过了空模型检查。同一个空工程：`checkup` 退 3
  （`completion.coverage.modelEmpty`），`review --live` 退 0。

## 已定设计（执行者不得改）

### A：re-gate 用同一个映射重算 `summary.exitCode`（双向）

- 两处重 gate 在重算 verdict 后，**用同一个 `_exit_code_with_verdict` 映射重算
  `summary.exitCode`**，report.md 的「（退出码 N）」行随同一次重渲染同步（单源纪律，#15/073 同款）。
- **双向都要对**：标上去 `0 → 3`；清掉标记 / 填满分诊回到 `complete` 时 `3 → 0`。
- **命令自身的进程退出码不变**：`need-datasheet` / `triage` 成功就是 `0`（`triage` 仍有
  2 = 坏输入、3 = 没有 report.json）。改的是**报告里记录的板态退出码**，不是这两个命令的
  exit——两者不许搅混，交卷里必须明确核过这一点。
- **先把所有重 gate 写点找全**：073 点名了两个（`_apply_needs_datasheet` /
  `_apply_warning_triage`），执行者要 grep 验证有没有第三个写 verdict/exitCode 的地方漏算，
  清单进交卷。
- 反向（`3 → 0`）在 CLI 上没有"撤销标记"的命令：`need-datasheet` 只加不删（侧车是审计轨迹，
  手工改侧车再重跑 `checkup` 是**重算**而不是 re-gate）。所以反向用函数级测试钉
  （`_apply_needs_datasheet(report, [])` / `_apply_warning_triage(report, [])`），并在
  交卷里说清这一档为什么不是端到端。

### B：`review --live` 拿到模型但模型为空 ⇒ `incomplete` ⇒ exit 3

- 判据 = **0 器件且 0 网**（live 是 schematic 视图，`cli.py` 硬编码，不涉及铜箔判定），与
  `checkup` 的 `completion.coverage.modelEmpty` 对齐。
- **别碰既有 `cli.py:2512` 的 `return 3`**（那是「根本没拿到模型」，另一句话，语义已对）——
  新加的是「拿到了但空」这一档，note 文案要与「没拿到」区分。
- 文件路径的既有空模型行为（`_pcb_view_read_nothing` / `empty_model`，019/072）**一字不动**。

## 验收

- 新测试（A + B 合一个文件）先红后绿；既有断言原则上不动（动了要逐条给理由）。
- A 测试：complete 板 → 标一脚 → `report.json` 的 `summary.exitCode == 3` + `report.md`
  「（退出码 3）」+ `completion.verdict == incomplete` 三同源；反向清除 → 回 0；
  `triage` 填满待分诊项 → verdict 走 `complete` 路径且**仍是 0**（不回归）；
  有 ERROR 的板 re-gate 后仍 `1`；两个 re-gate 命令自己的进程退出码仍 `0`。
- B 测试：`monkeypatch` 桩 `_load_model_online` 返回空模型 → exit 3 + note 点名空（与
  「没拿到模型」的 note 不同）；桩返回非空模型 → `0`；**负例**：有器件但 0 网的模型不许误伤；
  文件路径既有空模型测试（test_019 / test_073 等）一条不动。
- 变异 ≥2（`cp` 备份 + `sha256` 还原，禁 `git checkout`）：① `need-datasheet` 那处重算去掉 →
  钉子红；② `triage` 那处去掉 → 红；③ live 分支空模型检查去掉 → 红；④ 判据错写成
  「0 器件**或** 0 网」→ 负例红。
- 文档同步：README / `docs/getting-started.md` / `docs/bridge.md` / 仓库 `SKILL.md` 里凡讲
  `review --live`（或 review 家族）退出码的段落，grep 核对，该补补。
- 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` 绿（基线 2617，
  只能加不能少）。
- 交卷：改动文件 sha256 before/after、测试清单（每条改过的既有断言给理由）、全量尾行、
  re-gate 写点全清单、变异证据、自决项清单、边界外发现。

## 边界与纪律

- 零 git 写操作；本批**全离线**，不碰真机；不改 `PROGRESS.md`；不碰 `tests/fixtures/` 与
  `reviewsets/` 既有内容；不碰 `outputs/011e*`、`014_*`、`015b_*`、`016_*`。
- 可碰：`src/boardwise/cli.py`、`tests/` 同域文件、docs 与仓库版 `SKILL.md`。`connector/`、
  `dsh-plugin/` 不动（命令面与动作面都没变）。
- 先读 `E:/boardwise/AGENTS.md` 与 `.kimi-code/skills/boardwise/SKILL.md` §7。

## 交卷记录（执行者填，主代理复验）

### 落点

- `cli.py`：新增 `_regate_exit_code(summary, verdict)`（re-gate 专用：从**已记录的**退出码反解
  base 再喂同一个 `_exit_code_with_verdict`，只此一处，两处 re-gate 共用）与只读的
  `_recorded_exit_code(report)`；`_apply_needs_datasheet` / `_apply_warning_triage` 各加一行写回
  `summary["exitCode"]`；`_need_datasheet_lines` / `_triage_lines` 各加一行 `exitCode:`（**板态**
  退出码，并明说本命令自己的退出码不是它）；`_cmd_review` 加 `live_empty_model`（同一函数
  `_model_read_nothing`）+ `LIVE_EMPTY_MODEL_NOTE` / `LIVE_EMPTY_MODEL_HINT`，`read_nothing`
  与 `--md` 中文摘要提示各接一条；`--live` 的 `--help` 文案补这一档。
- 文档：仓库 `SKILL.md`（§3.1 ⓪/①、§3.2 review 退出码、§8 故障速查）、`README.md`（退出码 3
  那条）、`docs/getting-started.md`（§5 的 need-datasheet 段 + §5.1 review 退出码段）、
  `docs/install.md`（review 退出码段）、`docs/bridge.md`（`need-datasheet` / `triage` 两行）。
  **无英文 README**（仓库只有 `README.md`，中文；`ls | grep -i readme` 实证，见
  `evidence/075/docs_grep.txt`）；`docs/bridge.md` 的命令表里**没有** `boardwise review` 一行，
  所以 live 那档补在 SKILL/getting-started/install/README 四处。
- 证据：`evidence/075/`（索引 `00_README.txt`）。

### 数字

| 项 | 结果 |
|---|---|
| 新增测试 | `tests/test_075_exit_codes.py` 18 项（11 个函数：A 7 个 → 含 8 例映射表共 14 项；B 4 项） |
| 全量 pytest | `2635 passed in 203.83s`（基线 `2617 passed in 198.87s`，+18，无删除、无失败） |
| 既有断言变更 | **0 处**（只新增文件；`git status` 的 `tests/` 只有 `?? tests/test_075_exit_codes.py`） |
| 变异 | m1–m4 全红、全部 cp 还原 + sha256 一致；另跑「before-075」整文件对照：17 failed / 1 passed |
| 四线 | pytest 2635 绿 / connector 419 pass + 0 fail + tsc 0 / dsh-plugin typecheck+test(48 pass, 1 skipped)+build 0 |
| 命令面 | 未变（无新命令、无新旗标）⇒ `dsh-plugin` 工具面不动（它只暴露 checkup/arch/doctor/bridge，`checkup` 的 exit-3 描述本就含"空模型"一档，无需改）；`connector/` 未碰 |

### 重 gate / 退出码写点全清单（grep 实证见 `evidence/075/regate_write_points.txt`）

1. `engines/drc.py:706` `"exitCode": 1 if errors else 0` —— **base 的唯一来源**（有 ERROR 1，否则 0）。
2. `cli.py:4608`（`_cmd_checkup`）`summary["exitCode"] = _exit_code_with_verdict(summary["exitCode"], completion["verdict"])`
   —— **生成期唯一一处**算出板态退出码，进程码/report.json/report.md 三处同源（073 已建）。
3. `cli.py:3632`（`_apply_needs_datasheet`）—— 本次补上重算（原先只重建 `completion`）。
4. `cli.py:3756`（`_apply_warning_triage`）—— 本次补上重算（同上）。
5. `cli.py:2471` `_regate_exit_code` → `_exit_code_with_verdict` —— 两处 re-gate 共用的同一个映射。

- 只此四处（base 一处 + 生成一处 + re-gate 两处），**没有第三个漏算的写点**：`report.json`/`report.md`
  只由 `_write_checkup_report` / `_write_checkup_markdown` 写，调用者只有 `_cmd_checkup`、
  `_cmd_need_datasheet`、`_cmd_triage`（`grep -n "_write_checkup_report(\|_write_checkup_markdown("`
  = 3 组调用）；`report["completion"]` 只由 `_completion_body` 产（经 `_completion_section` 生成、
  经 `_completion_from_report` re-gate）写出，调用者同样只这三个命令。`cli.py` 里其余
  `"exitCode": 0` / `report["exitCode"]` 全是 `edit apply` / `draw apply` 那类**另一种报告**
  （plan/apply 结果），不是 checkup 报告，本批不碰。
- **两个退出码是两件事，已核**：`need-datasheet` / `triage` 自己的进程码**没变**（并进报告成功
  就是 0；`triage` 仍 2 = 坏输入 / 3 = 没有 report.json）——测试里对每条 re-gate 路径都断言了
  命令返回 0，同时报告记录的板态码变成了 3；控制台上两者**分行写明**
  （`exitCode: N（报告记录的板态退出码…本命令自己的退出码是 0）`）。

### 反向（3 → 0）为什么是函数级测试

CLI 上**没有**"撤销标记"的命令：`need-datasheet` 只加不删（侧车是审计轨迹，删了等于删证据），
手工改侧车再重跑 `checkup` 走的是**生成期**重算（不是 re-gate）。所以 `3 → 0` 用
`cli._apply_needs_datasheet(report, [])` 钉：报告 → `complete` → `exitCode 0` → `report.md`
的「（退出码 0）」由同一次重渲染带出。**`triage` 侧不存在能走到 `3 → 0` 的输入**：待分诊只把
verdict 落成 `complete-with-open-items`（073 定它仍是 0），从不落 `incomplete`；所以 triage 的
重算是**不变量**（报告记录的码必须等于 verdict 该有的码），它的钉子用「旧 build 留下的
report.json（verdict 已 incomplete、码还是 0）经 triage 重算回 3」这一条钉住——这一档真实可
达（058–072 的 build 就是那么写的），m2 变异即红。

### 变异证据（`evidence/075/mutation/`）

| # | 变异 | 钉子 | 结果 |
|---|---|---|---|
| m1 | 去掉 `_apply_needs_datasheet` 里的重算 | `test_marking_a_pin_moves_the_recorded_exit_code_to_three` | FAILED（`0 != 3`），cp 还原 sha256 一致 |
| m2 | 去掉 `_apply_warning_triage` 里的重算 | `test_a_report_whose_code_fell_behind_is_brought_back_in_line` | FAILED（`0 != 3`），还原一致 |
| m3 | live 分支不进 `read_nothing` | `test_review_live_on_an_empty_model_is_exit_three` | FAILED（退 0、无 exit-3 句），还原一致 |
| m4 | 判据错写成「0 器件**或** 0 网」（`components and nets`） | `test_review_live_with_parts_but_no_nets_is_not_an_empty_read` | FAILED（负例被误伤），还原一致 |
| — | 整个新测试文件对 HEAD 的 `cli.py` | 17 failed / 1 passed | 唯一通过的是 ERROR 优先级回归钉（该行为本来就对）；B 那两条"对照"在 HEAD 上因新常量不存在而报 `AttributeError`——预期之内 |

还原手段是 `cp`（`run.py` / `before_probe.py` 各自先备份再还原，并打印三处 sha256）。

### 自决项清单

1. **base 从已记录的码反解，不加新字段**：`_exit_code_with_verdict` 只升不降，且写进报告的码
   只有 0/1/3（坏输入在写报告前就返回），所以「3 必是 0 被 verdict 抬上来的」——反解无歧义，
   不必往 `summary` 里加一个会漂移的第二字段。已在 docstring 与测试里写明这个定义域前提。
2. **给两个 re-gate 命令各加一行 `exitCode:` 控制台输出**（任务只要求 report.md 同步）：两个退出码
   会被读者混为一谈，分行写明是防混淆最直接的一招；两个函数对应的文档字符串同步改了。
3. **`--live` 的 `--help` 文案也补了这一档**（CLI help 也是文档面）。
4. **`docs/install.md` 一并补**（任务点名的是 README/getting-started/bridge/SKILL；install.md 讲的是
   同一段 review 退出码，漏它会立刻自相矛盾）。
5. **`checkup` 侧一字未动**：`coverage.modelEmpty` 本来就对（073），本次只是让 `review --live` 对齐它。
6. `evidence/075/mutation/*.bak` 保留了两个 906 KB 的 `cli.py` 快照（沿用 073 的先例），
   离线重跑脚本时需要它们。

### 过程申报（不进证据）

全量跑过三轮：baseline（2617，绿）→ 中间一轮**被变异污染**（我在它跑动时做 m1–m4 会改写
`src/boardwise/cli.py`，已 `TaskStop` 丢弃，不进证据）→ 冻结字节后重跑（2635，绿，落
`evidence/075/pytest_full.txt`）。所有改动文件在本轮全量前后 `sha256sum -c` 一致。

### 边界外发现

1. **`triage` 的重算在可达输入上是"不变量"**（见上）：`warningsPendingTriage > 0` 只产生
   `complete-with-open-items`（0），所以"填满分诊把 3 变回 0"这条在现在的状态空间里**没有输入**——
   只有当别的闸同时松开才会走到 3 → 0，而 triage 动不了别的闸。本批按"报告里的码必须等于 verdict
   该有的码"实现，未改任何 gate 的定义（073 的 verdict 规则一字未动）。
2. **`review` 的 `--json`/`--md` 报告里没有退出码字段**（`review --json` 的 payload 只有
   `summary`/`findings`，`summary` 只有 `ERROR/WARN/INFO` 三个计数）：所以 `review` 侧的
   "三处同源"实际只有**进程码 + 控制台**两处，report.md 的中文摘要只是把 exit 3 写在提示句里。
   这一档 073/075 都没动（改它就是改 `review --json` 的契约），交主代理裁。
3. **`docs/bridge.md` 的命令表没有 `boardwise review` 行**（只有 checkup / need-datasheet / triage /
   review-mark / doctor…），所以 live 空模型这档在 bridge.md 里没有落点；offline `review` 的退出码
   散在 getting-started §5.1 与 install.md，两处都补了。
4. 空模型 note 在 live 分支**独立于 `read_nothing` 打印**（`elif live_empty_model:`）——变异 m3 能把
   两者分开，说明它们不是同一个判断；正常路径下 `live_empty_model` 同时决定"是否打印 note"与
   "是否 exit 3"，只有代码被改坏时才会不一致。

