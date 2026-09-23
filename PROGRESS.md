# PROGRESS — milestones, versions, reproducible baselines

Living index. Details live in `tasks/*.md` (one book per task) and
`docs/implementation-log.md` (the connector debugging arc). This file only
collects the current truth and the pointers.

## [2026-09-21] M3 入口复核与上手文档收尾

### Problem / Task
- 复核 013 真机验收、015b 审查评测和现有桥写入能力，确定下一阶段的产品主线。

### Resolution
- 确认当前基线适合进入 M3“审查到局部修改”：连接器已有属性修改后读回、页守卫、保存、原理图回读和未知写入状态。
- 将首个垂直切片定为单器件值修改，要求变更预览、前置条件、读回、复查和持久化核验；独立评测集扩充与 M3 并行。
- 修正 `docs/getting-started.md` 对 `gs-03` 配对公告截图的描述，使文案与实际素材一致。

### Prevention / Follow-up
- 先建立 `ChangePlan`/变更合同和独立 benchmark，再扩展补器件、修单脚和局部重排；暂缓 PCB 自动布局布线与模型成本调度。

### Verification
- `git diff --check` 通过。
- `docs/getting-started.md` 的 6 个图片引用均存在；未重跑完整 pytest/connector 套件（本次为架构复核与文档修正）。

### Commit
- Branch: `main`
- Commit: `83f910e`（getting-started + 两张截图；本记录随 PROGRESS.md 单独提交）
- Status: committed
- Files:
  - `docs/getting-started.md`
  - `docs/images/gs-01-editor-about.png`
  - `docs/images/gs-03-daemon-start.png`
  - `PROGRESS.md`

## Current baseline (2026-09-22, commit `383e524` on `4448c59`; published on GitHub)

- pytest: **1388 passed** (run with `--basetemp=.tmp_pt_home` on Windows —
  the host's safe-delete hook otherwise eats the summary line and fakes
  exit 1)
- connector: **365 pass / 0 fail** (`cd connector && npm test`)
- `npx tsc --noEmit`: clean
- connector version: **0.4.15** (`connector/extension.json`)
- Verified host: EasyEDA Pro **3.2.186** (the only host the bridge is
  calibrated against; every real-host fact in the task books names it)

## Milestones

| Milestone | State | Proof |
|---|---|---|
| M0 baseline & unified entry | **DONE 2026-09-19** | tag `m0-baseline`; four real-host persistence scenarios PASS (`docs/persistence-baseline.md`); P0a write-path validation; P0d three-state persistence + 009d2 disconnect honesty (exit 3 exists); golden replay real-host netlist diff zero (010c M6) |
| M1 useful schematic review | **DONE 2026-09-20** | `5958b1c`; annotations + metrics harness + 15 rules + injected boards + holdout 33/33 detection (`tasks/011-review-rules-m1.md`) |
| 012 basic experience（内测版 0.4.6） | **DONE 2026-09-21**（真机验证走 013） | `e2bb78c`; delete/modify + multi-project + export-fab + lib.recommend + review-mark + doctor（`tasks/012-basic-experience.md`、`tasks/012-commit-checklist.md`） |
| 013 real-host verification（0.4.10） | **DONE 2026-09-21** | `1798d7e`; doctor 7/7 真机、review.mark 毕设板 9/9、export.fab 三件套（BOM filter 极性修复）、lib.recommend supplierId 键、同事视角走查+截图（`tasks/013-realhost-verification.md`、`tasks/013-commit-checklist.md`） |
| 015 review rules M2 批①+批② | **DONE 2026-09-21** | `501a2f4`/`5ff0a1d`; MPN 解码器拒非 EIA 记法、decoupling-per-ic 退役、矛盾幅度 R 3x/C 25x（oracle 裁 A）+ 注入变体重签 4.7k；**holdout 33/33 双 1.00，011 §十晋级判据达成**（`tasks/015-review-rules-m2.md`；dev hp-prec 4/5 已知代价，oracle 终裁①接受） |
| 016 review-to-local-edit（M3 首切片） | **波①+波②主体 DONE 2026-09-22，场景 6 待岳重开验证** | ChangePlan + edit plan/preview/apply CLI + Finding.target 结构化；真机：apply exit 0（saved_unverified）、幂等 already_applied、stale_before exit 4、断连 exit 3；四保护全过（`tasks/016-review-to-local-edit.md` §十.7） |
| 018 朋友内测基础体验 | **DONE 2026-09-22**（随 `15b3da2` 入库） | daemon 单活跃 connector 防护（真 daemon 五拍验证：接纳/CONNECTOR_ALREADY_ACTIVE 拒绝/接管）、sys.identity、doc.open 诊断式报错、review --latest + --md 中文摘要、install.bat 四件套 + docs/install.md、项目级 SKILL.md + AGENTS.md、connector 0.4.11 .eext（`tasks/018-beta-basic-experience.md`） |
| 020 上游 issue 加固 | **DONE 2026-09-22** | `ffbdf77`; WI-1 解析静默丢脚可观测（ParseStats + review note：console EN / --md CN，--json 逐字节不变；llc 实测 14，毕设板 0）+ WI-2 update-connector 版本回读（verified→0 / mismatch→1 / timeout→3 UNKNOWN，`--no-verify` 保留旧行为）；真机 verified 0.4.11；变异 3/3 CAUGHT（`tasks/020-upstream-issue-fixes.md`；上游对照 #220-adjacent、#250/#252） |
| 021 多工程=多窗口实测 + hello 身份登记 | **DONE 2026-09-22** | `d70f59b`; 三工程=三窗口一进程实测钉死（eda API 窗口级，跨窗口枚举结构性不通）；connector hello 带 projectName/projectUuid → daemon 登记活跃+被拒实例 → status `projects seen`；方案=文件审查不挑窗口 + 写操作人机协作换窗（`tasks/021-multiproject.md`；已知限制：reload 时序 null，daemon 主动查补登待做） |
| 022 全新 clone 三 issue | **DONE 2026-09-22** | `4448c59`; Fixes #1（夹具守卫比内容不比字节——逐成员 sha256 + CRLF normalize，夹具零改动）+ Fixes #2（dev 依赖组 + install.bat 可选装）+ Fixes #3（doctor 首项离线安装版本预检，桥读项交叉复核）；doctor 七项→八项；变异 4/4 CAUGHT（`tasks/022-fresh-clone-issues.md`） |
| 023 多窗口路由（向 easyeda 看齐） | **DONE 2026-09-22** | `383e524`; 拆 018 单活跃 → 窗口 hub（全接纳注册）+ response context 回流（切文档身份保鲜）+ `--project`/`--instance` 路由（三态诚实报错列在线窗口）+ per-window 写互斥；**三窗口真机八项全过**：三工程注册/test2 直达/禁地只读/建删页零误伤/hello-null 自愈/三窗逐个热更（`tasks/023-multiwindow-routing.md`；架构对齐上游 `internal/daemon/hub.go`+`dispatch.go`） |
| 025 审查工作流 v2（checkup 一条命令） | **DONE 2026-09-23** | 四批全收官（批 1/2/3 随 `d6dca3b`/`dbd4570`/`7ccf0a2` 入库）；`boardwise checkup` = 三级数据路（project-file 满血 → per-page → netlist，--file 离线兜底）+ 主机 ERC/PCB DRC 归一 + 自有规则 + 模块聚类 + 逐页画布 PNG + `report.json`/`report.md`（schema `boardwise.checkup/2`）+ AI 槽位三件套（unknown_parts/canvas_images/summary_template）；SKILL §3 重写为「checkup 优先 + AI 填槽」SOP；exit 1 可达、exit 3 诚实（没查≠干净板）；真机 test 工程全链实录 + 零残留；pytest 1384，connector 365；离线 eval 逐字节不变；变异累计 10/10 CAUGHT（`tasks/025-review-flow-v2.md` §7） |

## Coordinate contract (the thing that cost the most sessions)

File ≡ canvas, y up; `.epro2` stores `y = −canvas`; the parser negates once
at its boundary and nowhere else. Rotation: the file's angle reads CCW, the
editor API turns CW, `θ_file ≡ −θ_API`; `transform_point` (CCW) computes
landings, `draw.py::_editor_rotation` (negation) is the only conversion
point. Full measurement history: `tasks/010c-coordinate-convention.md`
(appendices A→C, including the wrong turn).

## Git anchors

- `1251971` initial commit
- tag `m0-baseline` — M0 exit state (before the 010 arc)
- `d409026` connector 0.4.5 lock-window retry (010b)
- `ce044a6` coordinate convention + AMS1117 idiom block (010+010c)
- `5958b1c` M1 review rules (011)
- `e2bb78c` 012 basic experience, connector 0.4.6
- `1798d7e` 013 real-host verification, connector 0.4.10
- `501a2f4` 015 review rules M2 batch 1 (decoder guards + decoupling retired)
- `5ff0a1d` 015 review rules M2 batch 2 (amplitude tolerances R 3x/C 25x + variant re-sign; M2 graduation: holdout 33/33 both 1.00)
- `15b3da2` 016+018+019 combined (review-to-local-edit closed loop & friend-beta readiness)
- `a69906c` MIT LICENSE; repo published: https://github.com/xianyuyijinban/boardwise
- `ffbdf77` 020 upstream-issue hardening (parse-drop observability + update-connector verified reload; pytest 1276)
- `d70f59b` 021 multi-window reality + hello project-identity registration (pytest 1281)
- `4448c59` 022 fresh-clone fixes: content-based fixture guard + dev deps + offline editor floor check (GitHub #1/#2/#3 closed; pytest 1298)
- `383e524` 023 multi-window hub + project/instance routing + response context (three-window real host verified; pytest 1321)
- `ac465ae` 024 connector bootstrap for EasyEDA 3.2.149 skipped-activate host defect (connector 0.4.12; 336/336) — **现场验证 2026-09-23（issue #4）**：扩展正式入库后 3.2.149.88089769 冷启动**正常派发** `activate()`（`activation: … ok`、`activateObserved=yes evaluations=3 state: connected`，关窗再开同样）——「跳过 activate」是上游报告、本机未复现，bootstrap 保留但定位改为**幂等防御**（真正覆盖 reload-without-restart）；149 上第二个窗口仍需页面重载才上线（窗口冻结，非派发问题，多窗口基线仍是 3.2.186）
- 024b About box reads the shared runtime, not the clicking evaluation's empty copy (connector **0.4.13**; menu-click re-evaluations no longer report `never ran / idle` while connected — the fake diagnosis that would have misled the 3.2.149 field test; all box timestamps now local clock, was UTC; `SHARED_RUNTIME_MEMBERS` covers the full `OwnedTransportRuntime` interface; real-host verified on 3.2.186: `activateObserved=yes evaluations=3 state: connected`; connector 340/340)
- 025 batch 1 probe: online DRC/export actions (`sys.get_document_file` / `sys.get_document_source` / `sch.drc_check` / `pcb.drc_check`, connector **0.4.14**) + `sys.probe` `call` whitelist channel; P1 document-level epro2 full-fidelity path **works** (offline pipeline reused unchanged), P2 getDocumentSource **rejected** as A2 (drops footprint + connectivity), P3/P4 work (P4 PCB-page only, host throws instead of typed `undefined`); connector 359/359, pytest 1321 unchanged (`tasks/025-review-flow-v2.md` §7, `outputs/025_probe_*`)
- 025 batch 2 data path: `sys.get_project_file` permission **GRANTED** on real host (whole-project .epro2 1.7 MB — tier A1 full-fidelity established) + per-page merge fallback A1' verified identical designator sets; `boardwise checkup` skeleton with three-tier ladder (A1 → A1' → A3-netlist; A2 not enabled per batch 1) + `review --live`; report.json schema `boardwise.checkup/1` with pending batch-3/4 sections; pytest **1336** (+15), connector **365** (+6), offline evals byte-identical to `d6dca3b`; mutations 3/3 caught; known follow-up: `update-connector` false-FAILED when the reload has not landed yet
- 025 batch 3 DRC mapping: `engines/drc.py` (counts stay counts — no fabricated leafs; unchecked ≠ clean; per-leaf render evidence tags; severity from the host's own tab path via parentId); checkup fills `drc`/`findings`/`summary`, **exit 1 first reachable**; findings byte-identical in shape to `review --json` (pinned by an equality test); ERC counts measured host-wide, not per-page (task-book assumption corrected); schema `boardwise.checkup/2`; pytest **1363** (+27), connector 365 unchanged; offline evals byte-identical to `dbd4570`; mutations 4/4 caught; PCB per-device leaf sampling deferred — 毕设FOC驱动板 not open in the editor, R3 stop
- 025 batch 4 report + slots + skill (checkup 收官): `engines/checkup.py` (806 行 — modules by page or non-ground connectivity, conservative ≥1/3 naming else `未命名模块 N`; page attribution by a positional shallow pass, **not** id join; `ai_slots` unknown_parts/canvas_images/summary_template; `report.md` rendered same-source as report.json; `pending` now empty but kept) + cli.py canvas stage & console lines; docs: README EN/CN checkup section, getting-started step 5.0, **SKILL §3 rewritten** to the checkup-first SOP, bridge.md §8 command row; pytest **1384** (+21), connector 365 unchanged; offline evals byte-identical to `7ccf0a2`; real-host `outputs/025d_checkup_full.txt` (online exit 1 on a real PCB-DRC hit, 4 page PNGs focus-restored zero-residue; `--file` exit 0 with `offline-not-available`); mutations 3/3 caught (restore sha256 `checkup.py 688ce48f…` / `cli.py 9c80cf50…`)
- 025e update-connector false-FAILED fix: verdict changed from "version" to "**identity + version**" — only a connection that was NOT online before the write (reload mints a new instance id) reporting a non-stored build counts as mismatch; a lingering old socket is "not back yet" (wait), budget exhausted → exit 3 UNKNOWN, stored build sighted → exit 0; pre-write window-table snapshot, missing snapshot disables mismatch; `_running_connector_version()` deleted (probe read is answerable by any window, carries no identity); three-state semantics unchanged; pytest **1388** (+4, incl. the regression pin that was red before: `assert 1 == 3`), connector 365 unchanged; mutations 3/3 caught; live hot-update drill folded into 026 task 0 (`tasks/025-review-flow-v2.md` §7, `outputs/025e_update_connector_false_failed.txt`)
