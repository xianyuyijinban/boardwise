# 任务书：190 — 判型口径收口（声明优先、前缀兜底）+ 三条数值/披露小账

- 批号：**190**　日期：2026-10-16　来源：岳 10-16 反馈第七节（U 位号 330 kΩ 电阻被按 IC 判）→ 189B 只修了 derating 一处，
  其余落点盘在 `outputs/189b/prefix_judgement_sites.txt`（67 行，A 类 = 真判型门）。
- 原则：**判型一处说了算**。189B 的 `METADATA_TYPE_KEYS`（读 `LCSC Part Name` / `Supplier Footprint` 等元数据）和 127b 的
  `distance.classify_device` 已经是两个口径，本批收成一个公共入口，其余规则全部改调它；前缀只在元数据读不出时兜底，且兜底要能在报告里看出来。

## A. 公共判型入口

- 新增（或提升）一个公开函数，建议放 `core/` 或 `rules/facts.py` 附近（看现有依赖方向，别造环）：
  `classify_part(component, facts=None) -> PartKind`，返回 `kind`（ic / resistor / capacitor / inductor / diode / connector / unknown …）
  + `basis`（`metadata` / `shelf` / `prefix`）。读序：货架 category → 元数据（`METADATA_TYPE_KEYS`）→ 位号前缀。
- 189B derating 那处、127b `classify_device` 改为调用它（行为不变——用现有测试钉住，**先跑一遍记基线**）。

## B. 改调用点（A 类真判型门，逐处）

1. `rules/connectivity.py::DecouplingPerIC`（最像 ⑦）：U 位号但判型为电阻/电容 → 不要求去耦；C 位号但判型为连接器 → 不算电容。
   message 里「matches designator prefixes only」那句边界说明随之改写。
2. `rules/connectivity.py::ShuntSenseLink`：分流电阻与 IC 都走判型。
3. `rules/facts.py::ShelfIntake.ics()` 及 745-752 的逐件回路。
4. `rules/sensebias.py`（半门：保留 `or category == "ic.opamp"`，前缀那半走判型）。
5. 清单里 B/C 类（非判型门/展示用）**不动**，evidence 里逐条写「为什么不动」。
- 每处给一个「U 位号电阻」的合成回归用例；实板A（在场才跑）断言 U4/U6~U12 这类件不再出 IC 类 finding。

## C. 三条小账

1. **NTC/PTC**（189B 遗留，夹具里 verdict 零变化）：裁决——NTC/PTC 判为 `thermistor`（独立 kind），**不进**电阻的降额/值码路径；
   值码解不出不记 `UNDECODABLE`。
2. **去耦按轨分档**（189B 遗留）：`decoupling` 距离阈值目前产出轨/消耗轨同一档 200 mil。本批**只做披露**：finding 里写明该轨对本 IC 是
   VIN 还是 VOUT（189B 已有侧别字段，接到 message 上）；VOUT 侧距离超限降一级（WARN→INFO）。阈值数值不改，等岳裁。
3. **`mpn_voltage_rating` 读不出 `6R3`**（6.3 V 的 R 记法）：补 `<d>R<d>` 电压码；顺查 `1H/1E/0J` 这类 EIA 字母电压码是否已覆盖，没覆盖的列清单不实现。
4. `needs_datasheet` facts 行补 `shelfMatchedBy`（186 已在 unreviewed_parts 上有，这里补齐，同名同义）。

## D. 测试与纪律

- 改了 `rules/**` → 重钉 `tests/test_126a_pcb_review_plumbing.py` recursive/direct 指纹 + 台账注释。
- 新测试 `tests/test_190_part_kind.py`；每处改动的回归用例做变异（还原该处判型调用 → 对应用例红）。
- 全量绿：`--basetemp=.tmp_pt_190` `-n 4 --dist loadfile`；并行前场各用各的 basetemp。
- 夹具 verdict 对照表：全部 epro2 夹具 + 实板A 的 finding 数 前/后，**任何 verdict 变化逐条解释**。
- 红线同 190S；证据 `outputs/190/evidence.md`；PROGRESS.md append 一行；**不要 commit**。
