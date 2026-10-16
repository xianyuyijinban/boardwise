# 任务书：191D — 去耦距离按电源轨分档（岳 2026-10-17 裁）

- 批号：**191D**　来源：岳 10-17「去耦阈值要按电源轨分档」；190 已在 finding 上带了侧别（`_rail_side` → VIN / VOUT / 未声明），并临时把「VOUT 侧超 200 mil」降成 INFO。本批把那条临时降级换成真正的分档阈值。
- 代码位置：`src/boardwise/rules/pcb/distance.py`（`DECAP_DISTANCE_MIL = 200.0`、`_one_net`、`_rail_side`、`_SIDE_VOUT`，约 129 / 640-900 行）；FOC 包的 `rules/pcb/foc.py::TI_DECAP_REFERENCE_MIL` 与它同口径，一起看。

## 分档（初值，主代理定；都是 house rule，不是标准，docstring 照现有写法写明「可随反馈调」）

| 档 | 判据（该 IC 在这条轨上的脚） | 阈值 | 超限 |
|---|---|---|---|
| 消耗端供电脚 | 脚名 VDD / VCC / AVDD / DVDD / VDDA / VBAT / VS 等（IC 吃这条轨） | 200 mil | WARN |
| 稳压器输入 | VIN / PVIN（IC 是稳压器、这条轨是它的输入） | 300 mil | WARN |
| 稳压器输出 | VOUT / SW 之后的输出轨（这条轨是该 IC 产出的） | 500 mil | WARN |
| 侧别读不出 | 以上都不是 | 200 mil | WARN |

- 去掉 190 的「VOUT 超限 → INFO」临时降级：VOUT 侧现在有自己的阈值，超了就 WARN（severity 回到「超限即 WARN」一个口径）。
- 档位判据复用 `_rail_side` 的脚名读法；**消耗端 vs 侧别读不出** 的区分是新的，脚名词表放常量，测试钉住。
- 储能/大电解那一支（「storage belongs near the power entry」，约 731 行）不在本批范围，不改。
- finding message：写出命中的档名 + 阈值 + 实测距离（「稳压器输出档 500 mil，实测 1146 mil」）；report 里的数字与常量同源，不许手抄。
- 同一颗电容同时服务两颗 IC（`+5V` 既是 U5 的 VIN 又是 U11 的 VOUT，131b 的例子）：按每个 (IC, 轨) 对各自的档判，各出各的行——现状若已是逐对出行就保持。

## 测试与纪律

- 新测试 `tests/test_191d_decap_tiers.py`：四档各一个合成用例（刚好在阈值内 / 刚好超）；双服务电容用例；message 含档名与阈值。
- 改了 `rules/**`：**不要重钉 test_126a 指纹**（另有子代理同时改 rules，指纹由主代理合并时统一重钉）；全量里 test_126a 两条指纹用例红属预期，交卷时列出即可，其它红必须为零。
- 夹具对照：全部 epro2 夹具 + 实板A（`.tmp_bug98b/`，只读）的 decap 类 finding 前/后数量与 severity，逐条解释变化。
- 变异：把 VOUT 档阈值改回 200 → 新测试红（cp + sha256 还原）。
- 全量 `--basetemp=.tmp_pt_191d -n 4 --dist loadfile`。红线同 190S；证据 `outputs/191d/evidence.md`；PROGRESS.md append 一行；**不要 commit**。
