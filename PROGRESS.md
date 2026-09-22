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

## Current baseline (2026-09-22, working tree — 016/018/019 待提交)

- pytest: **1259 passed** (run with `--basetemp=.tmp_pt_home` on Windows —
  the host's safe-delete hook otherwise eats the summary line and fakes
  exit 1)
- connector: **305 pass / 0 fail** (`cd connector && npm test`)
- `npx tsc --noEmit`: clean
- connector version: **0.4.11** (`connector/extension.json`)
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
| 018 朋友内测基础体验 | **DONE 2026-09-22（待提交）** | daemon 单活跃 connector 防护（真 daemon 五拍验证：接纳/CONNECTOR_ALREADY_ACTIVE 拒绝/接管）、sys.identity、doc.open 诊断式报错、review --latest + --md 中文摘要、install.bat 四件套 + docs/install.md、项目级 SKILL.md + AGENTS.md、connector 0.4.11 .eext（`tasks/018-beta-basic-experience.md`） |

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
