# 131 / 阶段 D 电源规则包（LDO/Buck 先行，反激待夹具）

> 路线图：`tasks/122-pcb-review-roadmap.md` 模块特定层第 1 条。侦察报告见会话（agent-204，2026-10-08），
> 关键事实全部来自它，本任务书不再复述证据只留结论。
> 主代理裁定三条（2026-10-08，可逆）：①反激包暂缓——三块验收板零反激、货架零反激类别，
> 岳的反激辅助电源未画完，**无可验收对象**；范围=LDO/Buck，岳画完反激板即为验收夹具。
> ②功率环路面积暂缓——loop_area 的 poly/bbox 口径差 55 倍（同锚点 1818 vs 100208），口径先与岳对齐。
> ③电容分池电源包自定义：`<1µF`=高频旁路、`≥1µF`=储能，中间带显式归储能**不判 unknown**。

## 验收板与器件（侦察实测）

- **毕设FOC 1.0.0**（终验基准）：U11=LM5164DDAR（buck 24V→5V，SO-8-EP）、U5=RT9013-33GB（LDO）、
  U6=TPLP2981-30DBVR（LDO）、U20=REF2033（基准源，非稳压器）。
- **ROBOT ctrl FOC**：U8=AMS1117-3.3（LDO）。
- **毕设FOC 1.1.0 无电源器件**（纯功率级）——不做电源包验收板。

## 棒1（131a）：引脚名地基（解析器 + 角色分类）

**根因**：SYMBOL 文档的引脚名（VIN/VOUT/FB/SW/EN/EP/GND）在 `.epro2` 文件里有
（`ATTR key="Pin Name"` 挂 parentId 到 PIN 记录），解析器把 SYMBOL 文档丢了——
`Pin.name` 恒空。连带 `architecture.py::_SUPPLY_PIN` 对全部 .epro2 板失效。

**做什么**：
1. **先查清三条模型链路的 Pin.name 现状**（不许猜）：
   `parsers/schematic.py`（checkup 模型）/ `parsers/epro2_model.py`（PCB 侧模型）/
   architecture 消费哪条。把引脚名补到缺的那条——改动面要全量回归，
   因为 `_SUPPLY_PIN` 复活会改变 architecture 的 rails 识别（行为变化要在回报里逐条说清）。
2. **引脚角色分类器**（rules/pcb 侧可用）：从 Pin.name 识别
   IN/OUT/SW/FB/EN/BST/EP/GND（字符串词表，LM5164 的 `EN/UVLO` 这类复合名要拆）。
   角色判定证据写进 finding evidence（哪只脚、名字原文）。
3. 回归钉：三块夹具板的 rails/architecture 输出变化逐项交代（变好/变差/不变）。

**不做什么**：不改任何规则行为（规则包是棒2/3 的事）；不动货架数据。

## 棒2（131b）：pcb-regulator-cap-distance

- 一颗稳压器 × {VIN, VOUT} × {HF池, 储能池} 出最近边到边距 + 焊盘对证据。
- **池按「IC-引脚角色」分，不按「IC-所在网」分**（1.0.0 的 `+5V` 上 U5/U6 混池
  就是按网分的结构性误判——U6 的输出电容被算进 U5 的去耦池）。
- 分池用裁定 ③ 的定义；落在中间带的电容显式归储能并写进 evidence。
- 验收：1.0.0 上 U11 的 C89（4.7µF，99.5mil）必须被正确识别为「储能池最近」，
  不再出现「该网无电容」式冤案；U5 输出池必须只含 C3/C4 等 `$1N66612` 上的件。

## 棒3（131c）：pcb-regulator-fb-placement

- FB 分压识别复用 `rules/params.py:1133-1150` 的机械判据（已在 1.0.0 验证跑出唯一正确组），
  加一条「上臂所在 rail 是不是本 IC 输出脚所在网」把采样分压排除。
- 检查：FB 上臂电阻 ↔ FB 脚 ↔ FB 脚电容三者距离；**FB 上臂接在输出电容端还是 rail 端**
  （1.0.0 的 R14 接在 `+5V` rail 而非 C3/C4 端——侦察标记的真实可疑项，规则要能报出）。

## 暂缓项（写明，不散落）

- 功率环路面积（等岳对齐 poly/bbox 口径）
- 散热铜皮（货架零 dissipation 事实，先补事实再做）
- 反激隔离带/Y 电容（待夹具）
- 电源器件选型判据（LM5164 额定电流类——#64 的 MPN 规格消费，挂 E 阶段）

## 交付纪律

同 125-130：子代理执行、焦点+全量测试（--basetemp）、变异验证、禁 git 写、
禁改 fixtures、回收站、纯离线、PROGRESS/提交由主代理收口。
