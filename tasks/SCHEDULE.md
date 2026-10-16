# 排期（2026-10-16 起；主代理维护，岳裁）

发版规矩不变：挖洞 swarm + 上机 + 实测三闸全过才发；同一天只发一版；内测一律 prerelease；connector 版本 = 发布版本。

| 版本 | 内容 | 状态 | 依赖 |
|---|---|---|---|
| **v0.5.14**（内测） | main 上已落：187c / 188A / 188B / 189A1 / 189A2 / 189B / 189C / 189Cf；+ **190S** 底层丝印定标（含 editor_pose 上机对拍）+ **190** 判型收口 | 190S、190 开工 | 190S 要 test 窗口在线 |
| **v0.5.15**（内测） | **191A** accept-unknown 真通道 · **191B** 用户架合并 + boards 同形 · **191C** KiCad 裸 net 序号 | 待 v0.5.14 发后开工 | 191A 动 completion 语义，发前岳过一眼文案 |
| **v0.6.0**（正式） | **122 E 阶段**（器件检查收口 + 报告整合）+ **高速 A 档 1~3**（跨分割、换层伴随地孔、差分对内等长/同层/对称过孔；架子 `core/highspeed.py` + `rules/pcb/highspeed.py`，调研 `outputs/highspeed_rules_survey/README.md`） | 待写任务书 | 191C（差分对要网序号） |

## 待岳拍板（不排期就不动）

- R4 真热更（草案 `outputs/R4/design-proposal.md`，realm 探针已过）· R5 SPICE 侦察 · 121 反激规划落图（10-06 暂停）· 041 跨板网络（DRAFT，040b 已落地）
- 两份过时 DRAFT（051 / 088b-deltas）是否标注归档
- 189A2 跨视图检查在 4 块夹具板出声 7/8/6/2 条：`CROSS_VIEW_MIN_PINS` 抬不抬
- 189A1 `read_stackup.used_copper_layer_ids` 维持「文档声明口径」还是改物理读数
- 去耦阈值按轨分档的数值（190 只做披露和 VOUT 降级）
