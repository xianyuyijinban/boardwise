# 任务书：V4 O1 schematic 容器与 page 采集边界（2026-10-31）

> 总计划 `tasks/038_v4_live_gaps.md`。只改 live evidence 的列举/选择，不热更 connector。

## 根因与完成条件

`doc.list` 的 `type:"schematic"` 是容器，无 tab；`type:"page"` 才是可打开原理图页。
`liveevidence._documents` 当前把两者都折成 schematic page，导致对容器 doc.open、current/readback
失败并连带两通道 failed。

1. `_documents` 只把 `page`/`pcb` 放进可采集文档；`schematic` 容器单独保留 `{uuid,name,
   status:"not-applicable",reason}` 元数据，容器绝不 doc.open/render/readback。
2. selection 的 available/requested/selected/unknown 只按真实页计算；容器信息放在
   `selection.schematic.containers`，不新增频道，不改 capture 根键/频道键/step键/schema。
3. 显式 `--page <容器>` 在导航前拒绝，使用明确 `NOT_AN_ADDRESSABLE_PAGE`，不得报
   `UNKNOWN_DOCUMENT_UUID`（doc.list 里确实存在）。只有容器没有页时两通道仍 failed。
4. 每页动作顺序、netlist一次、focusRestore/finally、coversAll、子集 missing、无PCB
   not-applicable、未知uuid拒绝均保持；V3 pages-only 行为不变。
5. 注释/docstring同步，不改 connector/CLI/ReviewReport/规则。

## 允许文件域

- `src/boardwise/engines/liveevidence.py`
- `tests/test_537c_live_capture.py`
- `tests/test_537c_review_evidence_cli.py`
- 新增 `outputs/review/v4-o1-container.md`；探针 `.tmp_038_o1/`，pytest `.tmp_pt_038_o1`

禁止 connector/CLI/其他引擎/schema/fixtures/git写/设计写/编辑器或daemon重启。

## 验证

1. 容器排在 documents 首位：不打开容器，P1/P2动作和netlist次数不变，两通道按实际成功为 ok，
   coversAll/focusRestore 正常，容器元数据 not-applicable。
2. 只有容器无页：两通道 failed、无导航。显式容器id在导航前以 NOT_AN_ADDRESSABLE_PAGE 拒绝；
   CLI exit 1。未知uuid仍为 UNKNOWN_DOCUMENT_UUID。
3. 相邻：`test_537c_live_capture.py`、`test_537c_review_evidence_cli.py`、
   `test_537c_live_candidates.py`、`test_537d_review_read_artifacts.py`、`test_doc_claims.py`。
4. 至少两处变异：重新把容器加入采集；把显式容器id报成未知。cp备份→测试红→cp恢复→SHA一致。
5. 本批不做真机；主代理随后用V4复验。最多40步或30分钟。
