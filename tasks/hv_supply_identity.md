# 任务书：高压网身份与电压间距静默（A，2026-10-30）

> 用户实报：`V_310V` 零输出，手工测 310V 对 7 网 43.0–55.6 mil，IPC B2 要 100 mil。
> 主代理选择建议 **1+2**，不新增第 3 项功率级 UNKNOWN 人口启发式。

## 1. 根因与完成条件

1. **合同/声明电压读数**：`core/values.py::parse_voltage_volts` 增加严格 full-match 的
   `V_310V`、`V310`、`DC310`、`310VDC`、`3V3D` 形式；保留既有 3V3/3.3V/+310V、
   符号、finite 与拒绝路径。不得接受任意前后缀、多 token 或把旧 `V3` 负例变成电压。
2. **架构 rail 定价**：实际管线还经过 `core/power_domains.py::voltage_from_net_name`，
   必须同步支持同一组新 rail 写法；不能用允许裸数字的 parser 替换白名单。
3. **功率脚**：`core/architecture.py::_SUPPLY_PIN` 增加精确 `P`、`+`、`-`、`DRAIN`、
   `SW`、`PVIN`、`HV`，使整流桥/IPM 功率脚能进入 rails；return-only/ground 排除不动。
4. **端到端**：构造含 `V_310V` 的原理图/PCB 合成上下文：
   - rail 能进架构并得到 310V；若某路径未定价，至少出 UNKNOWN，不得静默；
   - `pcb-voltage-spacing` 对 310V↔GND 的 43.0 mil 同层几何出 WARN，要求 100 mil，
     measurement 保留 #87④ detail；原文案/severity/exit code 语义不扩改。
   - `3V3D` 为 3.3V；既有 VCC/无电压 rail 仍 UNKNOWN，普通信号网不得被新增兜底扫入。
5. 不修改 `rules/pcb/ipc.py` 的 UNKNOWN 人口：第 1+2 项已使本案例进入既有 rail/UNKNOWN
   通道。若实现发现仍被早退，停止交主代理，不自行新增功率级人口。

## 2. 允许文件域

- `src/boardwise/core/values.py`
- `src/boardwise/core/power_domains.py`
- `src/boardwise/core/architecture.py`
- 新增 `tests/test_hv_supply_identity.py`
- 邻域测试：`tests/test_083_value_unification.py`、`tests/test_architecture.py`、
  `tests/test_092_rail_ratings.py`、`tests/test_139_intent_rails.py`、
  `tests/test_126c_pcb_ipc_rules.py`、`tests/test_127b_blind_review_fixes.py`、
  `tests/test_164c_silent_truth.py`、`tests/test_516_same_potential_spacing.py`
- 新增 `outputs/review/hv-supply-identity.md`；探针 `.tmp_hv_supply/`，pytest `.tmp_pt_hv_supply`

不改 rules、shared parser/model、CLI、schema、fixtures、connector/DSH/Rust、绘制线；
不覆盖既有未提交改动，不做 git 写或真机操作。

## 3. 验证与证据

1. 先写新写法正例、旧写法兼容、任意字符串/旧负例、功率脚和 43 mil WARN 反例。
2. 聚焦跑新测试及以上邻域、`tests/test_540_cli_review.py`、`tests/test_owner_rules.py`、
   `tests/test_doc_claims.py`；本批不改 rulebody。
3. 至少两处有效变异：删除一种新电压形式支持、删除 P 功率脚支持；目标测试先红，
   `cp` 备份恢复并核 SHA-256，日志 `.tmp_hv_supply/mutations/`。
4. 真实 7 网读数目前只有用户 oracle，仓库没有可识别的该高压板匿名夹具；不得声称独立
   复测了那 7 网。证据明确区分用户实报与合成复现，不索取或读取真实工程。
5. 交实际文件、命令、计数、几何读数、变异和剩余授权缺口；不跑全量。
