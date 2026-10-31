# 任务书：038F3 eprj3 PCB 覆盖诚实性（2026-10-31）

> 总计划：`tasks/038_v4_isolation_plan.md`。CLI/report 独立小批，F1/F2/F4 已完成。
> 本批只修“有 PCB 但未审”的披露，不开放 Tier-B。

## 完成条件

1. 离线 `checkup --file <eprj3>` 用 F4 的 `looks_like_eprj3` / `pcb_files` 判断真实 PCB
   文件存在性，**不得**读 index 的 `pcb_count` 当权威，也不在 CLI 重写 glob。
2. 有 `.epcb2` 但 PCB runner 未运行时：
   - `completion.coverage.pcbReviewMissing=true`，沿用既有离线 incomplete/exit 语义；
   - canvas note 明说“工程有 PCB，但当前 PCB 审查档尚未接入/未出结果”，不得说“没有 PCB 文档”；
   - evidence.archivePcb 反映有文档但证据缺失/未审，不是 `not-applicable`。
3. 真正无 `.epcb2` 时保留“没有 PCB 文档/通道不适用”旧语义。`.epro2`/KiCad/在线路径不变。
4. F1 的正常 EOF 不再触发 parseIncomplete；F2 的版本在 `source.parseStats.editor_version`
   可见。Report schema、conclusion 权威、规则与退出码优先级不改。

## 允许文件域

- `src/boardwise/cli.py`
- 新增 `tests/test_038f3_eprj3_pcb_coverage.py`
- 新增 `outputs/review/v4-eprj3-pcb-coverage.md`；探针 `.tmp_038f3/`，pytest `.tmp_pt_038f3`

禁止改 eprj3/epru_stream/schematic/epru/epro2_model/几何/规则/schema/fixtures/connector/DSH/Rust；
不做 git 写、不连接编辑器、不修改或复制真实样本。

## 验证

1. 合成 eprj3 checkup 测试：index `pcb_count=0` 但有 PCB 文件；覆盖/文案/evidence 三者一致；
   正常 EOF 不增加 parseIncomplete；版本可读。无 PCB 对照仍为 not-applicable。
2. 相邻：`test_038f4_eprj3_pcb_source.py`、`test_038f2_eprj3_version.py`、
   `test_038f1_epru_eof.py`、`test_038_eprj3.py`、`test_126d_pcb_verdict_gate.py`、
   `test_166_online_pcb_review.py`、`test_189c_canvas_render.py`、`test_072_coverage_gate.py`、
   `test_checkup_cli.py`、`test_doc_claims.py`。
3. 真实样本在 `.tmp_038f3/checkup/` 新跑一轮，不复用旧报告：记录真实 exit/conclusion；
   `parseIncomplete=false`、`pcbReviewMissing=true`、canvas note 不再说无 PCB、archivePcb 非
   not-applicable、editor_version=4.1.60；两个重号 ERROR 保持不变。
4. 至少两处变异：忽略 eprj3 PCB 文件存在性；或把 archivePcb 强行写成不适用。cp备份→
   目标测试红→cp恢复→SHA一致。
5. 交实际命令/计数、报告字段摘要、变异哈希和未覆盖项。最多40步或30分钟，不跑全量。
