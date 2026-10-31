# 任务书：038F5 CLI/checkup eprj3 Tier-B 接线（2026-10-31）

> 总计划：`tasks/038_v4_isolation_plan.md`。F1/F2/F3/F4 已验收，本批是 CLI/引擎接线，
> 不改 shared parser、规则或报告 schema。

## 完成条件

1. `_load_model(view='pcb')` 对 eprj3 改调 F4 `load_eprj3_pcb_source`，返回现有
   `build_design_model(source)` / `build_board_geometry(source)`；无 PCB/多 PCB 继续明确报错。
2. `engines/pcbreview._review_units` 只增加容器 source 选择：eprj3 用 F4，`.epro2` 用旧入口；
   后续 `_pcb_documents`、footprints/artwork、extract_board/build_design_model 全部共用，
   不复制一套 V4 review driver。
3. `checkup --file` 对有 `.epcb2` 的工程实际调用既有 PCB runner，产出 `pcb_review`、
   findings 和几何 canvas；`pcbReviewMissing` 仅在真实未出结果时为 true，archivePcb/evidence
   与实际一致。F3 的“尚未接入”文案改为当前真实状态，不留过期注释。
4. `review --view pcb` 走同一 `_load_model`；V3/KiCad/在线路径、规则、finding severity、
   ReviewReport/conclusion/exit code 优先级不变。F1/F2/F4 行为保持。
5. 本批完成一单 PCB 垂直切片；多 PCB 仍拒绝，107↔88 网差与 pads_without_net 如实保留，
   不宣称所有 V4 已兼容或在线验收完成。

## 允许文件域

- `src/boardwise/cli.py`
- `src/boardwise/engines/pcbreview.py`
- 新增 `tests/test_038f5_eprj3_tierb.py`
- 必要兼容更新：`tests/test_038_eprj3.py`（无 PCB 仍拒绝）、
  `tests/test_038f3_eprj3_pcb_coverage.py`（用明确 runner 未出结果场景保留披露测试）
- `src/boardwise/parsers/eprj3.py` 仅限过期文档/注释，不改行为
- 新增 `outputs/review/v4-eprj3-tierb.md`；探针 `.tmp_038f5/`，pytest `.tmp_pt_038f5`

禁止改 shared parser逻辑、rules、geometry/model、schema/fixtures/connector/DSH/Rust；
不做 git 写、不连接编辑器、不修改或复制真实样本。

## 验证

1. 合成端到端：`_load_model(view=pcb)`；`review --view pcb`；`run_pcb_review` boards/checksRun；
   `checkup --file` 的 pcb_review/canvas/coverage/archivePcb。无 PCB 与多 PCB 不静默。
2. F3 披露测试不得靠“功能仍缺席”维持：需要未出结果时显式模拟 runner失败/None；
   成功路径由本批新测试承担。
3. 相邻：F1/F2/F3/F4 测试、`test_038_eprj3.py`、`test_126a_pcb_review_plumbing.py`、
   `test_126b_pcb_distance_rules.py`、`test_126d_pcb_verdict_gate.py`、
   `test_166_online_pcb_review.py`、`test_189c_canvas_render.py`、`test_checkup_cli.py`、
   `test_540_cli_review.py`、`test_owner_rules.py`、`test_doc_claims.py`。
4. 真实 V4 样本在 `.tmp_038f5/checkup/` 新跑：
   - `pcb_review.available=true`、一块 PCB1、模型/几何计数和 GHA 对齐；
   - `pcbReviewMissing=false`、archivePcb=ok、parseIncomplete=false、canvas 实际生成；
   - 记录真实 exit/conclusion/findings 变化，两个原理图重号 ERROR 仍在；
   - 不强迫 107↔88 网差消失，不篡改 pads_without_net=76。
5. 至少两处变异：`_load_model` 回退到 Tier-A 拒绝；runner 排除 eprj3。cp备份→目标红→
   cp恢复→SHA一致。
6. 交实际命令/计数、真实报告字段、变异哈希与未覆盖项。最多40步或30分钟，不跑全量。
