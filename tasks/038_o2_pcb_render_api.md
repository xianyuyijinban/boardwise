# 任务书：V4 O2 PCB render API 能力边界（2026-10-31）

> 总计划 `tasks/038_v4_live_gaps.md`。本批不是“把失败改名”，而是落实已实测的宿主能力边界。

## 根因证据

PCB1 已 doc.open+document.current 激活，随后 `export.render(png,scope=page,timeoutMs=60000)`
仍整 60s TIMEOUT；同会话原理图页秒回。V3 也有同类 PCB 不返回。该 API 是 schematic 出图口，
不能用于 PCB；不是10s太短。不得再盲目重试或加 timeout。

## 完成条件

1. `liveevidence._collect_pcb` 不再对 PCB 调 `export.render`；`pcbImage` 用既有
   `not-applicable` 状态，detail/errors 明确“schematic-only API 不适用于 PCB，已停止调用”，
   不生成伪图像、不把失败藏成 ok。
2. PCB 的 doc.open/current/readback/geometry、focusRestore 与 livePcb 保持；归档 PCB 审查和
   离线几何 SVG 是独立通道，不能写成 live PNG。
3. capture.ok 只由真实必需步骤决定；不调用不适用 API 后，不得再因它制造 failed step。
4. `docs/review-sop.md` 与相关注释同步：原理图 render、PCB几何/归档图和 live 位图的区别。
   connector/daemon/CLI/schema/规则不改。

## 允许文件域

- `src/boardwise/engines/liveevidence.py`
- `tests/test_537c_live_capture.py`
- `tests/test_537c_review_evidence_cli.py`
- `docs/review-sop.md`
- 新增 `outputs/review/v4-o2-pcb-render.md`；探针 `.tmp_038_o2/`，pytest `.tmp_pt_038_o2`

禁止 connector/其他引擎/schema/fixtures/git写/设计写/编辑器或daemon重启。

## 验证

1. PCB 采集 calls 中无 export.render，pcbImage=not-applicable 且理由明确；其余步骤不变，
   livePcb/focusRestore 正常。原理图 export.render 不受影响。
2. 相邻：`test_537c_live_capture.py`、`test_537c_review_evidence_cli.py`、
   `test_537c_live_merge.py`、`test_537c_evidence_coverage.py`、`test_537d_review_read.py`、
   `test_doc_claims.py`。
3. 至少两处变异：重新对 PCB 调 render；把通道写成 ok 或把不适用藏成 failed 而无原因。
   cp备份→测试红→cp恢复→SHA一致。
4. 本批不做真机，主代理随后统一复验。最多40步或30分钟。
