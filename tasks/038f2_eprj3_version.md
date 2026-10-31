# 任务书：038F2 eprj3 版本元数据（2026-10-31）

> 总计划：`tasks/038_v4_isolation_plan.md`。shared adapter 独立小批，前置 F1 已完成。

## 完成条件

1. `load_eprj3_text` 在 index 未提供 `editorVersion` 时，从内容文档 DOCHEAD 的 `editVersion`
   填版本；只看 `SCH` / `SCH_PAGE` / `PCB` / `PANEL`，**不得**用 SYMBOL/DEVICE/FOOTPRINT
   的库版本冒充编辑器版本。
2. 所有内容文档只有一个非空版本时写 `meta["editorVersion"]`；缺失保持未知；多个冲突版本
   不得任取一个，须以附加 meta 字段明确冲突值，且不改变既有 `editorVersion` 优先级。
3. 不改 `ParseStats` 公共结构。现有 schematic 读取经 `meta.get("editorVersion")` 获得版本；
   `edit_version` 仍按各模型既有语义，不为“两个字段都好看”而乱填。
4. V3 `.epro2` meta 与版本路径不变；F1 EOF 修复保持。

## 允许文件域

- `src/boardwise/parsers/eprj3.py`
- 新增 `tests/test_038f2_eprj3_version.py`
- 新增 `outputs/review/v4-eprj3-version.md`；探针 `.tmp_038f2/`，pytest `.tmp_pt_038f2`

禁止改 CLI/schematic/epru_stream/几何/规则/schema/fixtures/connector/DSH/Rust；不做 git 写、
不连接编辑器、不修改或复制真实样本。

## 验证

1. 合成测试：index 显式版本优先；SCH_PAGE 同版本；多页同版本；库版本不能冒充；无版本；
   内容文档版本冲突；PCB/PANEL 参与而 SYMBOL 不参与；根目录与 index 一致。
2. 相邻：`test_038f1_epru_eof.py`、`test_038_eprj3.py`、`test_epru_parser.py`、
   `test_072_coverage_gate.py`、`test_doc_claims.py`。
3. 真实 V4 样本只读复跑：`build_schematic_model(..., parse_stats=stats)` 的
   `stats.editor_version == "4.1.60"`，模型仍 128/107、malformed=0；记录 `edit_version` 原值，
   不强行改成非空。
4. 至少两处变异：误用库版本；冲突时任取一个。cp 备份→测试红→cp恢复→SHA-256一致。
5. 交实际命令/计数、样本读数、变异哈希和未覆盖项。最多40步或30分钟，不跑全量。
