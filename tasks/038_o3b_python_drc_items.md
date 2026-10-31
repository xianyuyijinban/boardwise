# 任务书：V4 O3b Python 消费逐条 ERC 响应（2026-10-31）

> 总计划 `tasks/038_v4_live_gaps.md`，前置 O3a connector 已完成。本批不改 connector、不热更。

## 完成条件

1. `engines/drc.py` 对 `entryShape=per-item` 优先消费 connector 的 `byType/total/items`；
   V3 aggregate 仍从原始 `{type,count}` 读取。`counts` 原数组继续作证据，不要求每项补 count。
2. `_unparsable_entries` 在 per-item 模式只读 `payload.unparsed`，不得把每条无 count 的合法 V4
   对象再算成519个坏条目。`pages` 保留 entryShape/items；section 的 passed=None 保持 unknown，
   不得压成 false。
3. host-wide 去重继续：两页相同519对象只报519 WARN一次，不报1038；不同则 sum-of-pages。
   per-item notes/summary detail必须说逐条在 pages[].items，不再写“没有逐项”。
4. 真正未知形状：unparsed>0 时进入 `countsIncomplete`、附 count=null ERROR，exit不能因
   total=0变0。合法V4则 counts/warnings/passed正确，不抬 severity。
5. `bridge/protocol.py` 的动作说明同步两种形状；sys_Log的“只有聚合”限定为V3实测，不能覆盖V4。
   不改connector/CLI/schema/规则。

## 允许文件域

- `src/boardwise/engines/drc.py`
- `src/boardwise/bridge/protocol.py`
- `tests/test_025c_drc_mapping.py`
- `tests/test_action_catalogue.py`（如合同钉需要）
- 新增 `outputs/review/v4-o3b-python-drc.md`；探针 `.tmp_038_o3b/`，pytest `.tmp_pt_038_o3b`

禁止connector/其他Python/schema/fixtures/git写/真机/热更。

## 验证

1. 合成V4两页相同：per-item+byType+items，section total=519/host-wide/passed=false，
   summary WARN519不翻倍，unparsableEntries=0，detail不撒谎。V3旧锚不变。
2. passed=None保持unknown；未知entry使unparsed>0 → countsIncomplete=true + count=null + exit1。
3. 相邻：`test_025c_drc_mapping.py`、`test_025d_checkup_report.py`、
   `test_072_coverage_gate.py`、`test_checkup_cli.py`、`test_action_catalogue.py`、
   `test_doc_claims.py`。
4. 至少两处变异：per-item仍读原count得0；unparsed不进countsIncomplete。cp备份→红→恢复→SHA。
5. 交真实计数、合成响应摘要、变异哈希和未覆盖项。最多40步或30分钟。
