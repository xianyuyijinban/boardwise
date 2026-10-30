# 任务书：200A 报告整合（E5，2026-10-30）

> 主代理范围裁决。依据 `tasks/200_v060_scope.md`、`tasks/122-pcb-review-roadmap.md`
> 第三步与 `outputs/200a/evidence.md`。E1–E4 已落，不重开器件规则或 derating 货架接线。

## 1. 唯一缺口与完成条件

把现有人读报告收口为 **DRC/ERC 门票 → 按模块 → 器件**，并把器件清单合成一个大节。

1. **顺序**：`report.md` 的主机 DRC、模块、器件读取顺序符合上述次序；
   `board_report` 的分组顺序也按通用门票 → PCB 模块 → 器件。严重度只在同一阅读层内排序。
   不把 WEIGHT_RANK 的重要性语义偷换成阅读顺序；需要独立阅读顺序键。
2. **器件大节**：把 `unreviewed_parts`、`accepted_unknown`、`needs_datasheet` 按
   `(board, ref)` 合并，每颗器件每板只一行，行内保留未审原因、接受未审信息及 facts/未知项状态。
   同名位号在不同板不得合并；空来源不得制造假行或重复标题。
3. **两份产物同源**：`report.md` 与 `board-report.md` 使用同一个器件大节渲染器，
   器件行逐字相同，阅读顺序一致。
4. **兼容**：既有 `report.json` 顶层键、三个来源数组、finding、severity、verdict、
   exit code、`conclusion` 权威读口与 schema 版本不变；不新增平行 JSON 器件清单。

完成定义：上述行为有合成正/反例、真实 CLI 产物和聚焦测试证据，主代理复验通过。

## 2. 允许文件域

- `src/boardwise/engines/checkup.py`
- `tests/test_154_board_report.py`
- `tests/test_185_conclusion.py`
- `tests/test_039c_review_flow.py`
- `tests/test_058_needs_datasheet.py`
- `tests/test_191a_accept_unknown.py`
- `tests/test_184_value_decode_coverage.py`（主代理复验时补入：仅同步旧器件标题断言）
- `tests/test_checkup_cli.py`（主代理复验时补入：仅同步旧器件标题断言）
- 新增 `tests/test_200a_report_integration.py`
- `docs/review-sop.md`
- 新增 `outputs/200a/report-integration-evidence.md`
- 探针与 CLI 产物仅放 `.tmp_200a_report/`，pytest 用 `.tmp_pt_200a_report`

既有测试若仅需调整旧顺序/旧三小节断言，可在上述文件内改；不得改断言来掩盖信息丢失。
若发现必须改其他生产文件才能满足范围，停止并交回主代理，不自行扩项。

## 3. 禁止事项

- 不改 `rules/**`、shared parser/model/core/CLI、connector、DSH、Rust 或绘制线。
- 不改 schema、verdict、结论、规则指纹；不重开 E1–E4，不接 derating 货架。
- 不碰当前 #87④ 候选的其他修改文件，尤其 `tests/test_126a_pcb_review_plumbing.py`。
- 不碰真机或真实工程，不读写既有 `.tmp_200a/` 证据，不修改 `outputs/200a/evidence.md`。
- 不执行 commit/add/checkout/restore/push，不删除文件，不发布或评论 issue。

## 4. 验证与交卷

1. 先写会失败的行为测试，再实现；保留旧 JSON 数组与多板/空态/接受未审反例。
2. 聚焦测试至少覆盖上述六个既有测试文件、新测试、`tests/test_540_cli_review.py`、
   `tests/test_owner_rules.py`、`tests/test_doc_claims.py`。
3. 实际运行两次只读 CLI（公开夹具 `ch340_golden.epro2` 与 `llc_board.epro2`），输出到
   `.tmp_200a_report/`；exit 3/incomplete 是覆盖结论，不得写成板子通过。核对两份 Markdown
   的器件行一致与阅读顺序。
4. 至少两处有效变异：分别破坏器件去重和阅读顺序，目标测试必须变红；每次先 `cp` 备份，
   用 `cp` 恢复并核对 SHA-256，禁止 git 恢复。日志放 `.tmp_200a_report/mutations/`。
5. 交卷写清实际文件、命令、计数、CLI 产物、变异与恢复哈希、未解决项；不跑全量，
   不宣称 200A 全部完成。主代理随后独立复验。
