# 任务书：038F4 eprj3 PCB source 适配器（2026-10-31）

> 总计划：`tasks/038_v4_isolation_plan.md`。shared adapter 独立小批，F1/F2 已完成。
> 为保持容器隔离，本批先于 CLI 覆盖修正，供后续 F3/F5 复用。

## 完成条件

1. 在 `parsers/eprj3.py` 增加确定性的 `pcb_files(path)`：只找 `pcb/**/*.epcb2`，根目录与
   index 文件入口一致，路径去重/排序纪律与 `page_files` 相同。
2. 增加 `load_eprj3_pcb_source(path) -> Epro2Source`：
   - 读取真实 `pcb/*.epcb2` 文本，**不做 schematic y-flip**；
   - `split_documents` 后构造现有 `Epro2Source`，复用 `build_design_model` /
     `build_board_geometry`，不得复制 PCB 业务 parser；
   - `project_meta` 继承 index，并设置 PCB 文档实际 title（本样本 PCB1），版本复用 F2 规则；
   - 无 PCB 明确报错；本垂直切片只接一 PCB，多 PCB 在缺少映射证据时明确拒绝，
     不得悄悄选第一张。
3. 公共返回是现有 source/model/geometry，不改 CLI、Report、规则或 schema。F1 EOF 与 F2
   版本行为保持。
4. 本批只提供适配器，不开放 `_load_model(view='pcb')`，不宣称 checkup Tier-B 已完成。

## 允许文件域

- `src/boardwise/parsers/eprj3.py`
- 新增 `tests/test_038f4_eprj3_pcb_source.py`
- 新增 `outputs/review/v4-eprj3-pcb-source.md`；探针 `.tmp_038f4/`，pytest `.tmp_pt_038f4`

禁止改 CLI/epru_stream/schematic/epru/epro2_model/几何/规则/schema/fixtures/connector/DSH/Rust；
不做 git 写、不连接编辑器、不修改或复制真实样本。

## 验证

1. 合成最小 PCB+library 测试：根目录/index 一致；无 PCB；多 PCB拒绝；title；版本唯一/冲突；
   PCB y 不翻；source 可被两个现有 builder 消费；无原理图页时 PCB source 仍能独立读取。
2. 相邻：`test_038f2_eprj3_version.py`、`test_038f1_epru_eof.py`、
   `test_038_eprj3.py`、`test_epru_parser.py`、`test_072_coverage_gate.py`、
   `test_101_b2_parser_hardening.py`、`test_162b_epru_truth.py`、`test_doc_claims.py`。
3. 真实 V4 样本只读复跑，主代理将独立核对：
   - model 128 器件/88 网，GHA=Q7.4+U10.5；
   - geometry.name=PCB1，60 层、502 pads、730 tracks、244 vias、75 pours；
   - stats.malformed=0、edit_version=4.1.60、pads_without_net=76 原样披露；
   - POUR/POURED 不得自行换算或改几何。
4. 至少两处变异：对 PCB 错做 y-flip；多 PCB 悄悄取第一张。cp备份→目标红→cp恢复→SHA一致。
5. 交实际命令/计数、样本读数、变异哈希与未覆盖项。最多40步或30分钟，不跑全量。
