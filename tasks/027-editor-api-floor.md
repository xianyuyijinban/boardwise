# 027 — EDITOR_API_FLOOR 降到 3.2.149（任务书 v1）

> 2026-09-23 立。触发：岳在工作电脑 **3.2.149.88089769** + connector 0.4.15 上的现场证据，
> 把 `EDITOR_API_FLOOR = (3, 2, 183)`（`src/boardwise/cli.py:6059`）的立论连根拔掉。

## 一、证伪记录（岳现场实测，2026-09-23）

旧立论（`cli.py:4639-4642` 注释原文）："Below it, generateIndicatorMarkers/zoomToRegion
and friends are declared absent"——**在 3.2.149.88089769 上不成立**：

- 成员级 probe **8/8 全 `function` 带 arity**：`sys_WebSocket.register`(5)、
  `sys_FileManager.getProjectFile`(3)/`getDocumentFile`(3)/`getDocumentSource`(0)、
  `sch_Drc.check`(0)、`pcb_Drc.check`(0)、
  `dmt_EditorControl.generateIndicatorMarkers`(5)/`zoomToRegion`(5)（证据 `sys_probe_checks.json`，岳工作电脑）。
- activate 冷启动正常派发（issue #4 现场：024 声称的"149 不派发 activate()"未复现）。
- `sch_ManufactureData.getExportDocumentFile` **实测能跑**（render 返回 308 KB PNG）——
  同机反证"typeof 证否不证用"：`getPngFile`/`getSvgFile` 在 149 上连声明都没有
  （本机 3.2.186 同样缺——类型包声明超前宿主，不是 149 的残疾；我们不用它们，无碍）。

## 二、判定（Kimi 拍板，岳确认证据）

**`EDITOR_API_FLOOR = (3, 2, 183)` → `(3, 2, 149)`**。三条边界，注释里必须如实写：

1. **不是"149+ 全兼容"的承诺**：实测点只有 3.2.149.88089769 与 3.2.186 两台；
   149 以下没有任何证据，doctor 继续卡。
2. **行为级验收另立批次**（review-mark 真画、checkup 全链、DRC 实跑，在工作电脑
   test 工程）——发现残废就在 doctor 加**行为检查**，不再用版本号卡
   （岳原话："可以靠测量定，不必只看版本号"）。
3. typeof 只证存在、不证行为——这条本身就是本仓库的教训（getPngFile 两机皆缺），
   注释里写明。

## 三、改动面（按文件）

- `src/boardwise/cli.py:6059`：常量改 `(3, 2, 149)`；注释重写（实测点、证伪史、三条边界）。
- `src/boardwise/cli.py:4639-4642`：旧立论注释改写为证伪后的现状。
- `src/boardwise/cli.py:590`：doctor 文案 "editor is ≥ 3.2.183" → 随常量走（拼 `floor_text`，别硬编码）。
- `tests/test_doctor.py`：所有钉 `(3,2,183)` / `"3.2.183"` 的断言改 `(3,2,149)`——
  **语义结构不变**：at_floor 用 "3.2.149"、above 用 "3.2.150"+、below 用 "3.2.148"。
- `docs/getting-started.md`：11/24/26 行三处 3.2.183 → 3.2.149（"推荐 3.2.186"保留）；
  28 行那句 149 实测备注改写为"已实测支持"（不再是"冷启动能连但 doctor 会卡"）。
- `docs/bridge.md:811`：doctor 行 "the editor is ≥ 3.2.183" → 3.2.149。
- **不改**：`docs/api-surface-2026-09-20.md` / `docs/api-survey.md` / `docs/draw.md` /
  `docs/bridge.md:647,1341` 的 `getPngFile` "v3.2.183" 记录——那是类型包声明 vs 宿主实测的
  历史事实，与 FLOOR 无关。

## 四、验收

- 三线全绿：pytest（`--basetemp=.tmp_pt_home`）/ connector / tsc（本任务纯 Python+文档，connector 是回归）。
- 变异 ≥2：FLOOR 边界（149 过/148 卡）、`outdated_running` 逻辑各至少 1 靶；cp 备份 + sha256 还原。
- 不动 git；文件显式 UTF-8。
- 交卷：改动清单、三线计数、变异结果 + 还原 sha256、可 append 到本任务书 §五 的记录文本。

## 五、交卷记录

**027 交卷（执行子代理，2026-09-23）**

改动文件（行号按落盘后终稿）：

- `src/boardwise/cli.py`
  - `:583` 新增局部 `floor_text = ".".join(str(part) for part in EDITOR_API_FLOOR)`（拼常量，同 `:6370`/`:6379` 先例）
  - `:593` doctor 描述由硬编码 `"editor is ≥ 3.2.183"` 改为 `f"editor is ≥ {floor_text}, …"`
  - `:6058-6082` `EDITOR_API_FLOOR = (3, 2, 183)` → `(3, 2, 149)`，注释整段重写：实测点（3.2.149.88089769 / 3.2.186 两台）、证伪史（8/8 成员 probe 带 arity、冷启动 activate 正常派发、getExportDocumentFile 实跑 308 KB PNG）、三条边界（非"149+ 全兼容"；行为级另立批次、残废就加行为检查；typeof 证存在不证行为，getPngFile 两机皆缺即本仓教训）
  - `:6565-6567` 明细文案「generateIndicatorMarkers / zoomToRegion 等接口在该版本后才有」→「这套 harness 依赖的画布接口只在这条线以上实测过——低于它的版本没有证据，不是判定为坏的」（同一条旧立论的第二处落点，属 §三"旧立论注释改写"的同族，一并改）
- `tests/test_doctor.py`
  - `:164-175` below → `3.2.148`、at_floor → `3.2.149`（`"3.2.183"`→`"3.2.149"` 断言同改）
  - `:190`（+`:187-189` 三行注释）notes 样本改写，见下"判断"
  - `:362` `EDITOR_API_FLOOR == (3, 2, 149)`
  - `:395-402`、`:417-420`、`:472-474`、`:481-493`、`:643-655` 一行以下/一行以上的夹具与断言全部落到 148/149 线
  - `:461` `_editor_version_key("v3.2.149") == (3, 2, 149)`
  - **未动**：`:459`（`3.2.149.88089769` 的解析用例，与地板无关）、`:507`（"第二棵陈旧安装树"夹具仍 3.2.149.88089769——该用例考的是两处安装不一致→note 而非版本线，149 落在地板线上仍成立，语义不变）
- `docs/getting-started.md`：`:11`、`:24`、`:26-30`（149 备注改写为「已实测支持」，不再是"冷启动能连但 doctor 会卡"）、`:125`、`:133`、`:149`、`:153`
  - 后四处（doctor 全绿样例输出与表格）任务书 §三 未列，但不改就是"文档样例 vs 真实输出"不符，按 §三 的 3.2.183→3.2.149 规则一并改
- `docs/bridge.md`：`:811` doctor 行 `the editor is ≥ 3.2.183` → `≥ 3.2.149`
  - **该文件同时被并行 026 任务改动**（`:498` 的 `sys.worker_probe` 行），我只动了 811，未碰其改动

notes 样本的判断（任务书要求说明）：原字符串 `declared ADD since EDA v3.2.183 on this host` 挂在 `generateIndicatorMarkers` 上，但生成表 `connector/src/api-names.ts` 的 `ADDED_SINCE` 只含 `sch_ManufactureData.getPngFile`/`getSvgFile`、`sys_FileManager.getSchematicFile`（均 v3.2.183），该成员**永不产生** note；且 doctor 只读 `status`、从不读 `notes`（`_probe_missing`，`cli.py:6709`）。结论：这是仿造样本，但恰好复述被证伪的旧立论，故改写为不带版本号的现状文本 + 三行注释说明 notes 只是提示。判定不受影响，测试语义（`undefined` 成员被点名、note 不改变裁决）保持不变。

三线（本机，改动后）：

- pytest `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home` → **1388 passed**（与改动前基线 1388 一致，未增删用例）
- connector `npm test` → **375 pass / 0 fail**
- `npx tsc --noEmit`（`connector/`）→ **0 error**
  - 附注：第一次跑时撞上并行 026 正在写 `connector/src/actions.ts` 的中间态（文件 mtime 与报错行在两次运行间移动，共 126 行语法错）；等其落盘（15:04:58）后重跑为 0 error。与本任务无关。

变异验证（`cp` 备份 → 变异 → 相关测试必须红 → `cp` 还原 → `sha256sum` 逐字节一致；禁用 `git checkout --`）：**3/3 CAUGHT**

| # | 靶 | 变异 | 结果 |
|---|---|---|---|
| M1 | FLOOR 边界（149 过） | `cli.py:6552` `editor >= EDITOR_API_FLOOR` → `>` | 1 failed（`test_an_editor_below_the_api_floor…:176`） |
| M2 | `outdated_running` | `cli.py:6593` 修复分支选择 `if outdated_running` → `if not outdated_running` | 3 failed（`:176` / `:424` / `:494`） |
| M3 | `floor_text` 拼接（149 卡） | `cli.py:6379` `".".join(…)` → 硬编码 `"3.2.183"` | 3 failed（`:176` / `:403` / `:655`） |

还原后 `src/boardwise/cli.py` sha256 = `dfca999f919b0b74f601efcc5a4b20f27ed771eeab47ef072fb9aae3ff56b7df`（与备份 `cmp` 逐字节一致，三次变异后均复核过同一哈希）。

真跑（非测试，假安装树 + 真实 CLI）：`.tmp_027_sim/{149,148}`（各自 `resources/app/package.json` 写版本，`BOARDWISE_EDITOR_INSTALL` 指过去）的结果——

```text
BOARDWISE_EDITOR_INSTALL=…/149  → PASS 编辑器安装版本 ≥ 3.2.149
                                  安装树 …\149\lceda-pro 的包清单写着 3.2.149.88089769
BOARDWISE_EDITOR_INSTALL=…/148  → FAIL 编辑器安装版本 ≥ 3.2.149
                                  → 先升级编辑器到 ≥3.2.149，其余检查项都排在它后面……
```

`boardwise doctor --help` 也随常量输出 `the editor is ≥ 3.2.149`。临时目录已删。

遗留（**未动**，交主代理裁）：`docs/install.md:24`（"3.2.183 或更高"）与 `:192`（"编辑器版本 ≥ 3.2.183"），以及 `.kimi-code/skills/boardwise/SKILL.md:204-205`（"3.2.183 是下限"。同时 `:205` 有 `sch_ManufactureData.getPngFile` 的声明≠实现记录）。三处都不在 §三 改动面内，故只报不改；`SKILL.md` 是本仓 AI 约定的唯一权威，留着旧下限会继续误导后续子代理，建议下一批一并更新。

### 149 行为级验收（2026-09-24，岳工作电脑 3.2.149.88089769，connector 0.4.17）

岳五步全跑，结果逐条：

| 步骤 | 结果 |
|---|---|
| `git pull` | ✔ 4307369（直连超时，走 7890 代理成功） |
| 重启 daemon | ✔ 61190 应答 |
| `bridge update-connector --yes` | ✔ 0.4.15 → 0.4.17，写入 `User_309b46a8…_v6`，verified |
| `boardwise doctor` | ✔ **8/8 全绿**——floor 检查在 149 上 PASS（本任务预期①成立） |
| `boardwise checkup --out checkup149` | ✔ 全链跑通，exit 1（有发现，预期语义） |
| `boardwise review-mark checkup149/report.json` | ✔ **1 个 marker 落在 R7 @(205,485)** |

结论：`generateIndicatorMarkers`/`zoomToRegion` 在 3.2.149 上不只 `typeof === function`（027 probe），
**行为级可用**——FLOOR (3,2,149) 的立论从"证否不证用"升级为行为实证。
未了项：149 第二窗口上线验证（026b 批 2b 第 5 项）岳尚未测，issue #4 多窗口症状保持开放。
