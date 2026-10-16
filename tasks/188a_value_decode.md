# 任务书：188A — 值码族补完 + 细长环披露

- 批号：**188A**　日期：2026-10-16　来源：挖洞 swarm agent-342（184 面 3 中）+ 187A 遗留 1
- 探针：`C:\Users\xiangyu\.tmp_184_probe\`（preempt.py / fbtest.py / boards2.py 可复跑）

## 1. 电容尾护栏放宽（184 中-1 + 中-2 合并修，`core/values.py`）

- 现状：`_CAP_VOLTAGE_TAIL_RE = r"(\d{3})[A-Z](\d{3})NT$"` 钉死 NT 包装码；同一字段换包装码（CT/AT/JT/MT/NTHJ/NSPJ/NSLJ…）整 token 拒读；且新 reader 缺封装码豁免会抢读（`X0402K500NT` 旧 '500' → 新 '402' 错误顶读）
- 修法：尾改结构形态 `(\d{3})[A-Z](\d{3})[A-Z]{2,4}$` **且** group1 的整段数字属 `_PACKAGE_TAILS` 时豁免（复用 `_voltage_rating_tail` 的 `_digit_run` 判法）——两个修法一起上，单独裸放宽实测有 6 处误命（`FRC0805J471TSD`→805、`XC6206P332MR`→206 等，swarm 已列清单）
- 验收锚：货架 11 颗电容（`CGA0603X7R104K500JT`/`FCC0603B103K500CT`/`HGC0603R5225K500NTHJ`/`HHV0805R7225K101NSLJ`/`HHV1206R7475K101NSPJ`/`CGA0805X5R106K250MT`/`CGA0805X5R226M250MT` 等）全读对且与货架 value 一致；`X0402K500NT`/`CC1206K500NT`/`GRM0603K500NT` 保持旧读数不被顶；015 的电解/TDK 见证仍 None
- 含 `R` 的耐压档（`6R3`）与 `CT` 包装的真实料号（`0603S226M6R3CT`、`0603B104K500CT`，已 web 核实）要读出
- 全库对拍（1162 文件语料，swarm 有现成脚本）：只允许新增正读、**零处旧读数被改成别的**

## 2. FB/RV 两把尺（184 中-3，`engines/checkup.py` `_value_decodable`）

- FB（磁珠，100MHz 阻抗）与 RV（压敏，电压）的量都不是电阻：按 C/L 同款处理——MPN 只问 `mpn_value_code`，**不走** `mpn_resistance_candidates`（docstring 自己写了"只有已知是电阻的调用方才能问它"）
- RP/RT（排阻/热敏）保持现状评估后写明取舍
- 测试：MF52-103/3435（B 常数 3435 不得读成 34.3MΩ）、7D471K 类压敏——闸门不得因 candidates 放行

## 3. 假绿灯测试修复（184 中-1 附带）

- `tests/test_184_value_decode_coverage.py` 的 `test_no_shelved_passive_is_unreviewed_for_its_value` 现在把 `value=entry.value` 塞进合成器件（只验板值分支）。补一条**板上 Value 为空**的货架遍历——防「MPN 读不出但板值救命」形态掩盖 MPN 缺口

## 4. 细长环 INFO 披露（187A 遗留 1）

- 拼合环 bbox 细长比（长边/短边）> 20:1 时，`outlineNote`/报告加 INFO：「板框极细长（X:1）——细长板/拼板请人工确认拼合正确」；**只披露不拒收**（窄板真存在，不发明拒收语义）
- 阈值 20:1 写在常量里带注释（实板对照：正常板 ~1:1-4:1，细条灯板/拼板可达 10-20:1，2000×0.9 退化环是 2222:1——阈值落在 20 把退化形态框进来又不伤真细长板）

## 5. 纪律

- 全量绿 `--basetemp=.tmp_pt_188a` `-n 4 --dist loadfile`（sources 在位）；values.py 变异验证 ≥1 组
- 指纹：values.py/checkup.py 不在 recipe（rules/ 没动就不用重钉；若动了 rules/ 重钉+台账）
- 红线：不动 git；删除走回收站；真实项目名零出现
- 证据 `outputs/188a/evidence.md`；PROGRESS.md append 一行
- **不要 commit**，交回主代理收口
