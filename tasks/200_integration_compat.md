# 任务书：200 集成兼容修复（2026-10-30）

> 首轮集成全量：8535 passed / 25 skipped / 6 failed。两项为既有 MSYS/绘制线环境外失败，
> 本批只处理四项审查侧失败，不碰那两项。

## 1. 缺陷与完成条件

1. **192B 真回归**：`render_part_section` 在三份器件来源全空时提前返回，吞掉
   `declaredPassiveExempt` 留痕。调整 `src/boardwise/engines/checkup.py`，使空三源仍不制造
   器件表/假行，但豁免器件及说明继续渲染；保留原空态语义与两份产物同源。
   `tests/test_192b_judgment_gates.py::test_every_exempted_part_is_named_in_the_report`
   必须恢复，并在 `tests/test_200a_report_integration.py` 加空三源+豁免反例。
2. **187B 旧审查者标记小节**：`tests/test_187b_gate_holes.py` 改钉统一器件大节中的
   `未知项 审查者标记`、位号和理由，不断言已移除的 `### 审查者标记`；多板提示仍不得出现在单板。
3. **127B llc 旧净板锚**：`tests/test_127b_blind_review_fixes.py` 的排除集补入
   `pcb-hs-cross-split` / `pcb-hs-via-ground-companion` / `pcb-hs-diffpair-skew` /
   `pcb-hs-diffpair-via-parity`，并在 docstring 说明新规则各自已有锚；原有 127b 距离规则
   静默断言不得削弱。不得把 llc 的 180 条新高速行改成静默。
4. **R2-1 注册位置**：`tests/test_r2_1_keepout.py` 改为 keepout 后追加五个高速规则，
   校验 keepout 类型、来源及完整尾部顺序，不再用旧的 `[-2]` / 单个 182 尾项。

## 2. 允许文件域

- `src/boardwise/engines/checkup.py`（仅 192B 空态豁免留痕）
- `tests/test_200a_report_integration.py`
- `tests/test_192b_judgment_gates.py`
- `tests/test_187b_gate_holes.py`
- `tests/test_127b_blind_review_fixes.py`
- `tests/test_r2_1_keepout.py`
- `outputs/200/acceptance.md`（新建集成证据）
- 探针 `.tmp_200_integration/`，pytest `.tmp_pt_200_integration`

不改其他生产文件、rules、shared、CLI、schema、fixtures、绘制线、connector/DSH/Rust；
不覆盖既有未提交改动，不执行任何 git 写或真机操作。

## 3. 验证

- 先运行四个失败测试确认现状，再改；完成后跑五个受影响文件及
  `test_200a_report_integration.py`、`test_154_board_report.py`、`test_185_conclusion.py`。
- 192B 变异：让空态提前返回再次吞掉豁免，两个目标测试必须红；`cp` 备份恢复并核 SHA-256。
- 交实际命令、计数、diff 与哈希，不跑全量。主代理之后做唯一一次完整复跑。
