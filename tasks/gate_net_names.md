# 任务书：六路栅极网名覆盖（D，2026-10-30）

> 用户实报：UH/UL/VH/VL/WH/WL 六路栅极被 `GATE_NET_PATTERN` 漏掉，规则只出
> “no net … recognises”。本批只扩该名字面，不改测量或阈值。

## 1. 完成条件

1. `rules/pcb/foc.py::GATE_NET_PATTERN` 增加 `UH|UL|VH|VL|WH|WL`，保留 GH/GL，
   支持既有可选相字母和数字后缀；`POWER_NET_PREFIXES` 同步六个前缀，避免报告词表漂移。
2. `is_power_net` 与 `pcb-foc-gate-trace-width` 对六路名及数字后缀实际出行，
   不再落 no-net INFO；其他信号名不误收，TI 20 mil 参考和原有测量文案不变。
3. 用户实板不在仓库，使用合成六路 track 读数，不声称独立复测真实板。
4. 更新 direct/recursive rulebody 账本与官方 differential，保留所有既有记录。

## 2. 允许文件域

- `src/boardwise/rules/pcb/foc.py`
- 新增 `tests/test_gate_net_names.py`
- 邻域：`tests/test_133b_foc_rules.py`、`tests/test_133c_foc_ground.py`、
  `tests/test_133d_foc_thermal.py`、`tests/test_131f_mcu_crystal_keepout.py`、
  `tests/test_126a_pcb_review_plumbing.py`、`tests/test_126b_pcb_distance_rules.py`、
  `tests/test_126c_pcb_ipc_rules.py`、`tests/test_127b_blind_review_fixes.py`、
  `tests/test_164a_foc_view_truth.py`、`tests/test_163b_gate_truth.py`、
  `tests/test_182_highspeed_scaffold.py`
- `contracts/differential/**` 仅官方生成器更新
- 新增 `outputs/review/gate-net-names.md`；探针 `.tmp_gate_names/`，pytest `.tmp_pt_gate_names`

不改 focground、其他规则、shared、CLI、schema、fixtures、connector/DSH/Rust；
不做 git 写或真机操作。E 的 V_310V return-path 识别不在本批。

## 3. 验证

1. 六路名与数字后缀正反例、GH/GL 兼容、普通信号/U 相字母不全匹配反例；
   实际 `FocGateTraceWidth` 六路统计与 no-net 反例。
2. 跑新测试、上述邻域、`tests/test_540_cli_review.py`、`tests/test_owner_rules.py`、
   `tests/test_doc_claims.py`；不跑全量。
3. 至少两处有效变异：删除六路 GATE pattern、删除 POWER_NET_PREFIXES 对应项；
   目标测试先红，`cp` 备份恢复并核 SHA-256，日志 `.tmp_gate_names/mutations/`。
4. 交实际命令、计数、direct/recursive 新值与实板证据缺口。
