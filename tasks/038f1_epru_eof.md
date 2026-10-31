# 任务书：038F1 共享记录帧 EOF 假损坏（2026-10-31）

> 总计划：`tasks/038_v4_isolation_plan.md`。这是 shared parser 独立小批，不夹 CLI/报告/规则。

## 根因与完成条件

`iter_epru_records` 无条件把行尾 `|` 当记录终止符。V4 真样本的 EOF 空 body 记录写成
`{envelope}||`：代码误删最后一个语义分隔符，剩下单 `|`，于是计 malformed。完整空 body
`{envelope}|||` 仍必须按旧路径工作。

1. 精确区分三种情况：完整空 body `|||`、EOF 空 body 缺终止符 `||`、真正截断的非空 body。
   前两种合法，第三种仍 malformed；普通非空记录的既有终止/缺终止行为不变。
2. 合法 EOF 空 body 继续计 `empty_body_records` 并跳过 payload；`total_records`、记录类型和
   行号口径不漂移。不得简单“所有无终止符都接受”。
3. 模块 docstring 当前已声称 final line 可缺 terminator，补齐实现与测试，不改公开返回模型。
4. V3 `.epro2` 与 V4 `.eprj3` 共用此修复；不为 V4 复制帧解析器。

## 允许文件域

- `src/boardwise/parsers/epru_stream.py`
- 新增 `tests/test_038f1_epru_eof.py`
- 新增 `outputs/review/v4-eof-frame.md`；探针 `.tmp_038f1/`，pytest `.tmp_pt_038f1`

禁止改 CLI、schematic/eprj3、几何/规则/schema/fixtures/connector/DSH/Rust；不做 git 写、
不连接编辑器、不修改真实样本或将其内容收进测试。

## 测试与真实样本验收

1. 合成测试覆盖：普通完整记录、普通 EOF 缺终止符、完整空 body `|||`、EOF 空 body `||`、
   非空 JSON 缺终止符、坏 envelope、非 dict envelope；分别断言 record/body/stats。
2. 相邻回归：`tests/test_epru_parser.py`、`tests/test_038_eprj3.py`、
   `tests/test_100_b1_quick_guards.py`、`tests/test_101_b2_parser_hardening.py`、
   `tests/test_072_coverage_gate.py`、`tests/test_doc_claims.py`。
3. 对用户已授权的 V4 样本只读复跑：原理图 P1/P2 合并统计 `malformed_records` 从 2→0，
   PCB1 从 1→0；模型计数保持 SCH128/107、PCB128/88，GHA 成员不变。不得复制样本。
4. 至少两处变异：删除 EOF 空 body 特判；或把所有缺终止符都接受。必须 cp 备份、目标测试红、
   cp 恢复并核 SHA-256，禁止 git 恢复。
5. 交实际命令/计数、样本前后读数、变异哈希和未覆盖项。最多40步或30分钟，不跑全量。
