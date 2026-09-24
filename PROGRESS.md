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

## Current baseline (2026-09-24, 033 export.render 导出前自激活; published on GitHub)

- pytest: **1447 passed** (run with `--basetemp=.tmp_pt_home` on Windows —
  the host's safe-delete hook otherwise eats the summary line and fakes
  exit 1)
- connector: **415 pass / 0 fail** (`cd connector && npm test`)
- `npx tsc --noEmit`: clean
- connector version: **0.4.22** (`connector/extension.json`)
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
- 026 probe batch (Worker watchdog 定案): 形态 A（Worker 闹钟）**定案**——P2 否了形态 B（Worker 里无 `eda`）、P5 否了宿主 `sys_Timer`（回调与页面时钟同吃一张节流时刻表，大间隔逐一重合）、P3 证实 A 前提（页面时钟压到整分钟级时 Worker 153/153 一次不落）、P1 证实扩展页可起 `blob:` Worker（往返 8 ms）；任务 0 真机热更 exit 0 verified（025e 修复闭环）；P4 sideload 冷启动 12.5 s 自愈（卸载重导入腿需岳手动）；临时动作 `sys.worker_probe`（connector **0.4.16**，PROBE-ONLY，15 mock 用例）；去留已定：实现批删 4 个测量模式、`status` 改名 `sys.connector_status` 并入 doctor；connector **380** (+15)，pytest 1388 不变；变异 4/4 CAUGHT（`tasks/026-worker-watchdog.md` §六，`outputs/026_probe.md`）
- 027 EDITOR_API_FLOOR (3,2,183)→(3,2,149): 旧立论（<183 无 generateIndicatorMarkers/zoomToRegion）被 3.2.149.88089769 现场证伪（8/8 成员 probe 全 function 带 arity、activate 冷启动正常、render 实跑 308KB PNG）；常量+注释重写（实测点仅 149/186 两台、行为级验收另立批次、typeof 证否不证用三条边界）、doctor 文案随常量动态化、getting-started 7 处+install.md 2 处+SKILL 坑表同步；pytest 1388 不变（无语义新增）、connector 380 回归、变异 3/3 CAUGHT（FLOOR 边界/outdated_running/floor_text 拼接）；假安装树实跑：149 过/148 卡（`tasks/027-editor-api-floor.md` §五）
- 026b batch 2a (Worker 闹钟形态 A 实现): 新模块 `connector/src/watchdog.ts`（内联 blob Worker：15s 查活性 / 页面沉默 45s 起每拍发 wake，解冻即连不等节流心跳；降级报原因不吹"免疫"）；`transport.ts` 四处活性上报 + `wake()` 四分支 + `reconnectNow()` 退避复位；`index.ts` `ensureWatchdog()` 单例挂 024 共享运行时 + About `watchdog:` 行；`actions.ts` 删 4 个测量模式（−703 行）、`status` 转正 `sys.connector_status`、`sys.worker_probe` 仅留 `nativeWs`（P6 页面侧判定靠它，2b 跑完即删，主代理裁决）；daemon 零改动；connector **418**（删 15 + 新增 24+29），pytest 1388 不变，dist 0.4.17 `8fe4f591…` 256827B；变异 2/2 CAUGHT（wake 不动作 5 红 / 重求值双 Worker 2 红）；P6 daemon 侧实测通（Node 原生 WS 51ms 连上收 banner）；主代理复验三线+sha256 一致（`tasks/026b-worker-watchdog-impl.md` §六，`outputs/026b_impl_2a.txt`）
- 027 行为级验收（岳工作电脑 3.2.149.88089769 + connector 0.4.17，2026-09-24）：五步全绿——doctor **8/8**（floor PASS）、checkup 全链 exit 1、`review-mark` **marker 实落 R7 @(205,485)**——`generateIndicatorMarkers`/`zoomToRegion` 在 149 从"typeof 证否不证用"升级为行为实证，FLOOR (3,2,149) 立论闭环；未了项：149 第二窗口上线验证（026b 2b-5）未测，issue #4 多窗口症状保持开放（`tasks/027-editor-api-floor.md` 末节）
- 026b/026c/026d (Worker 闹钟实现+两轮规格修正，多窗口后台冻结收官): 形态 A 落地（`watchdog.ts` 内联 blob Worker + `transport.ts` wake 四分支 + `ensureWatchdog()` 挂 024 运行时单例 + About 行）；026c 判死规格「wake + 任一未答心跳即死」+ `reconnectNow()` 去 `setTimeout(0)`（节流页把 0 延时也压到下一拍）；026d「wake 即探针」（健康 wake 同步 sendPing、上线证据代替自我盖戳）+ 静默 45→30 s——**真机同法对照：2b 135–152 s（未达标）→ 2c 62.8–114.9（相位项）→ 2d 39.6/27.1/45.8（3/3 ≤90 s，相位项消除）**；`sys.worker_probe` 删净（真机 UNKNOWN_ACTION 实证）；`status` 转正 `sys.connector_status`；P6 两半真机实测通（形态 B′ 连通性无障碍）；附带事实：3.2.186 第二窗口是「上线但匿名」（projectName=None 至重连）；变异 2a 2/2 + 2c 1/1 + 2d 1/1 全 CAUGHT；connector **405** / 0.4.19，pytest 1388 不变，dist `378a59bb…` 253495B；遗留：test2/ROBOT 窗等页面 reload 自然升级、149 第二窗口验证归岳、「长调用误判死亡」按裁决接受（`tasks/026b-worker-watchdog-impl.md` §六，`outputs/026{,b,c,d}_*`）
- 028 batch 3a+3b (内测分发三件套实现): PyInstaller onefile **boardwise.exe**（11.2MiB，冷启动 median 0.72s，内嵌 connector 0.4.19 与 eext 同源 `378a59bb…`）——`resources.py` 冻结/仓库两态解析（`_MEIPASS/resources/` 镜像仓库树）、`packaging/{spec,entry,build_exe.py}`、`--version` 双号；干净目录全链真机验证（doctor 8/8、内嵌 bundle 热更 verified、无 Python 模拟三项 exit 0）；`doctor` 新增 `--project/--instance`（多窗在线时 4/8→8/8）；`install-skill` 四态（装/幂等/备份/卸载）+ 本机真装落盘 sha 一致；getting-started 新增「第 0 步（朋友专用）」7 步 + 修正"只认最后注册窗口"过期事实；pytest **1404**（+16），connector 405 不变，变异 2/2 CAUGHT；Release 发布属 3c（`tasks/028-distribution-trio.md` §六，`outputs/026e_*`）
- 028 batch 3c (Release v0.4.19 发布，三件套收官): prerelease 上架，附件 `boardwise.exe`（11.2MiB `5cff0611…`）+ `boardwise-connector-0.4.19.eext`（62.3KB `95923f2c…`），**GitHub 服务端 digest 与本机 sha256 逐字节一致**；notes 经岳过目（下载双 sha + 7 步安装 + SmartScreen + 三卖点 + token 本地）；同日 issue #6 两半全修（af2ac90 地址参数 + 141df88 fix 文案按错误码分岔，本机三窗复现 4/8→寻址指引，pytest 1407）、issue #4 三件事闭环建议关闭（149 第二窗口=匿名上线+watchdog 84s 自愈，岳现场数据）
- 029 batch a (M3 第 2 片 add-component 离线核心): `decap-required-caps` 补 FindingTarget（锚点 IC/供电脚/网/facts 配方串，UNKNOWN 不给 target）；**幂等探测与规则判定同一函数**（`cap_candidates_on` + `decide_required_cap`，层规则强制落 `engines/addcomponent.py`）；changeplan 增 `add-component`（`to_jsonable` 按 kind 分支，016 component-value JSON 一字未变）；`edit plan --report`（阶梯 `LANDING_GRID=5`=layout.GRID 固定 9 位耗尽抛 LadderExhausted 绝不落原点、位号最小空闲、连接 wire-or-label 二选一拒绝静默）；apply 编排 11 离线用例（幂等走活工程 export→parse、范围差异恰好 +1、连接以工程网表回执判定）；pytest **1418**（+11），变异 2/2（幂等漏判/兜底放原点）；主代理裁决 3 条含"029-b 必须含异网线段页面盯 wire 不错连"；遗留 `edit preview` 认 add-component + report.json 显式 schema 测试（`tasks/029-edit-add-component.md` §六）
- 029 batches b/c/d (M3 第 2 片 add-component 全线收官): 真机暴露三 bug 修复（wire state 带 `Net` 原名假设错→`nearest_wire_point` 按网过滤错连结构不可能；plan 错用锚点 IC 脚号；无架 `looks_like_capacitor` 崩）+ 三宿主硬事实入码（**对角线挂死 place_wire**⇒`wire_route()` 强制正交；**落点=原点≠引脚**⇒wire 从新件自己的脚画起；**place_netlabel 本机不可用**）；GND 端机制=**power-flag**（`sch.place_power` probe 过、旗标放新件引脚、范围差异单计 flags、轨道网判定归 `layout._net_kind` 唯一处）；apply 内置重审（save 后双导出指纹一致→重跑规则→resolved/still-present，facts UNKNOWN 不算 resolved）+ 幂等探测前置（重复 apply=already_applied 零写入）；真机 case a 两次真成功（重审 findings 0）+ b/c/d/f + 无 GND 几何新形态全链；pytest **1435**（+27 over 1407），变异 2+2+2 全 CAUGHT；`export.screenshot` 本机只回 1×1 PNG 入账（`tasks/029-edit-add-component.md` §六，`outputs/029{b,c,d}_*`）
- 030 update-connector 多窗三档（岳四坑收编）: 无寻址+多窗**写前拒绝**（exit 2 列窗口表+两条出路）；`--instance` 不变；`--all` 新增（逐窗写/reload/验收，exit 0/1/3 三态沿用 025e）；**verified 收紧**=只认目标窗旧身份消失+写后新连接报出版本（共享存储下异窗应答是假 yes，真机证到：test 的连接全程在线时 test2 的 verified 等到它自己 10:55:51 的新连接）；坑 4 精修（匿名期 `--instance` 调一次即恢复 `--project`，不必等 4 分钟）；`--all` 真机未跑（会 reload 禁地 ROBOT，主代理裁决 (c) 维持现状+SKILL 坑 22 加注禁地守卫）；pytest **1443**（+8），connector/tsc 未动，变异 2/2 CAUGHT；现场 test2 升 0.4.19、ROBOT 一字未写（`tasks/030-update-connector-multiwindow.md` §五，`outputs/030_*`）

- 031 export.render PNG 超时 → SVG 回退（issue #5 收编，connector **0.4.20**）: 149 实测 PNG 光栅化卡死而 SVG 同刻可用、宿主 UI 冻结时心跳/连接全部正常（**心跳连续不能排除宿主故障** → SKILL 坑 23）；connector TIMEOUT 文案双假设 + svg 指引 + `timeoutMs`（clamp 1..60s，缺省 30s 不变）；checkup 画布阶段 PNG 10s 短绳、**仅 TIMEOUT** 同页回退 SVG（entry 留 `format`+`pngError`，schema 只加字段）；真机 186：0.4.20 热更 verified、PNG 回归 156678B、`timeoutMs=1` 强制超时新文案 + SVG 1970ms 真返回、checkup 4 页零新字段；pytest **1447**（+4）connector **407**（+4），变异 2/2 CAUGHT；主代理裁决两条遗留（daemon 30s 盖 60s 上限=已知限制、protocol schema 漂移=接受）；149 marker A/B 未做（`tasks/031-export-render-png-fallback.md` §交卷记录，`outputs/031_*`）

- 032 export.render toast 自清除（issue #5 症状正案，connector **0.4.21**）: 岳 149 新证据推翻 #5 原诊断——PNG **成功**（664KB 落盘）UI 照样卡 99%，卡死 = ManufactureData 导出管线**漏进度条 toast**（与成败无关），031 回退只治超时失败不治卡死；移植上游 finally 修法（400ms 后 `destroyProgressBar`+`destroyLoading`，幂等 best-effort，成功/超时两路都拆）+ TIMEOUT 文案末句改"自拆，仍挂才 reload"；真机 186：热更 verified、probe 两函数在册、PNG 回归 sha 与 031 逐字节相同；connector **410**（+3）pytest 1447 不变，变异 2/2 CAUGHT；**视觉验收归岳（149 上 toast 应 ~1s 自灭），验收前 #5 保持开放**（`tasks/032-export-render-toast-teardown.md` §交卷记录，`outputs/032_*`）

- 033 export.render 导出前自激活（issue #5 毛病 A 正案，connector **0.4.22**）: 岳受控对照（149+0.4.21，同窗同页隔 4 分钟）钉死真因——**页面自载入后未激活 ⇒ 导出挂死（png/svg 无差别）**，doc.open 激活后 ~2s 成功；一条机制解释全部历史观测（checkup 逐页 doc.open 所以从未失败、裸调全挂、孤例 svg 成功是文档还热）；**撤回**"PNG 卡死 SVG 可用"单样本旧结论，SKILL 坑 23 与 bridge.md §10.28 纠错重写；`exportRender` 新增 `pageUuid`，scope=page 先解析目标（参数 ?? 活动文档）→ `openDocument` 激活**成功后才导出**，激活失败三态全拒绝；真机 186：热更 verified、带 pageUuid 导出后 doc.list active 真换页、无参与有参 sha 逐字节相同、checkup 4 页零回归；connector **415**（+5）pytest 1447 不变，变异 2/2 CAUGHT；毛病 B（toast 漏）岳两样本验证闭环；毛病 A 根治验收归岳（149 裸调 render 应直接成功）（`tasks/033-export-render-auto-activate.md` §交卷记录，`outputs/033_*`）
