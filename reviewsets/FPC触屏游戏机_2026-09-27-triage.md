# Triage 草稿 —— `FPC触屏游戏机_2026-09-27`（任务 017 评测集扩充）

Board: `tests/fixtures/FPC触屏游戏机_2026-09-27.epro2`
Model: **56 components, 60 nets**（schematic 视图）
Findings: **0 ERROR / 1 WARN / 7 INFO**
另有工具提示一行：`note: 12 pin(s) dropped during parse (missing pin number) — review coverage is incomplete`

## 视图口径（先看这一节）

本草稿用 **schematic 视图**，即任务书指定的命令：

```bash
.venv/Scripts/python.exe -m boardwise.cli review tests/fixtures/FPC触屏游戏机_2026-09-27.epro2 --view schematic
```

选它的原因：这是评测 harness（`review_eval`）与既有基线的口径，也是设计真相——
SCH（`.epru`）文档里的原始记录为准；**pcb 文档会携带陈旧属性副本**，读出的器件值可能是错的。

| 条目 | pcb 视图（旧口径） | schematic 视图（本草稿） |
|---|---|---|
| findings 合计 | 0 ERROR / **4 WARN** / 11 INFO | 0 ERROR / **1 WARN** / 7 INFO |
| `conn-usb-cc-pulldown` `USB1 pin4` / `pin10` | 报 2 × WARN（`R27`/`R24` 读到 `1e+04Ω`，与声明的 5.1k 不符） | **不报** |
| `decap-required-caps` `U5 pin5` | 1 × WARN | 1 × WARN（同一条，两视图一致） |
| `param-value-mpn-match` `R1` | 1 × WARN（`400mΩ` vs 译码 `40 Ω`） | **不报** |
| `param-rc-cutoff` | 11 × INFO | 7 × INFO（且 `C11` 的值读作 `10UF`，fc 从 159 Hz 变 2 Hz） |

**已经核实的真相**（主代理对 `.epru` 原始记录逐案核对，2026-09-27；不是我的推断）：

- SCH 文档里 `R24`/`R27` 的 `Value` 原始记录 = **`5.1K`** —— CC 下拉值是对的，
  pcb 视图报的 `10k` 是陈旧副本。**所以那两条 WARN 在真相口径下不存在，板子是对的。**
- `R1` 在 SCH 里 `Value` 是**空**（`MPN` = `FRL1210FR400TS` 有值），所以
  `param-value-mpn-match` 在真相口径下根本不对它开口（该规则只在能读到板值时判）。

**外部规格书证据（已核实，作为上下文保留，不是裁决）**：`FRL1210FR400TS` = FOJAN
**400mΩ ±1%**（1210 封装）——pcb 视图那条消息里译码器给出的 `40 Ω` **是错的**，板上
`400mΩ` 与规格书一致。这条只对 pcb 视图的那条 WARN 有意义；本草稿里它不对应任何待裁条目，
登记在此以免上一版的信息丢失。

下面所有 `[WARN]`/`[INFO]` 引文与计数都只来自 **schematic 视图**。标"**补充事实（非规则输出）**"
的段落取自同一 loader（`boardwise.cli._load_model`，`view='schematic'`）。

**这份草稿怎么读。** 每一行都只是"规则报了它"加上规则给出的原文证据，不是对设计的判断，
不含预判。裁决词只有四个：

| 裁决 | 进入标注集的方式 |
|---|---|
| `defect` | 真问题；落成 defect 记录（带 rule hint） |
| `exception` | 规则报了，但**不是**问题；落成 exception 记录（必须写明理由） |
| `observation` | 值得记一笔，但不下结论（例如 report-only 的数字） |
| `backlog` | 不是裁决：这是事实库**还供不上**的一条事实 |

---

## A. 批量小节（同一类、裁定必然一致，一个决定覆盖整节）

### A1. `param-rc-cutoff` —— 7 × INFO（report-only 的测量值，同一类）

规则不判对错，只报 fc = 1/(2πRC)；`source` 逐字：`house rule (report-only): fc = 1 / (2*pi*R*C)`。
类文档要点：**没有"设计要求"这条通道**，所以只报不判（"发明一个 pass/fail 比沉默更糟"）。

逐字引文（7 条，全部原文照录）：

```
[INFO] param-rc-cutoff: RC R12(1e+04Ω) + C11(10UF) on 'TVDD': fc = 2 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists)
[INFO] param-rc-cutoff: RC R12(1e+04Ω) + C12(100nF) on 'TVDD': fc = 159 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists)
[INFO] param-rc-cutoff: RC R12(1e+04Ω) + C13(100nF) on 'TVDD': fc = 159 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists)
[INFO] param-rc-cutoff: RC R30(1e+04Ω) + C73(100nF) on 'NRST': fc = 159 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists)
[INFO] param-rc-cutoff: RC R11(1e+04Ω) + C11(10UF) on 'TVDD': fc = 2 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists)
[INFO] param-rc-cutoff: RC R11(1e+04Ω) + C12(100nF) on 'TVDD': fc = 159 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists)
[INFO] param-rc-cutoff: RC R11(1e+04Ω) + C13(100nF) on 'TVDD': fc = 159 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists)
```

**补充事实（非规则输出）**：`C11` 的 `Value` 字段字面是 `10UF`（大写 UF，不是 `10uF`），
规则按 10 µF 计算，得 fc = 2 Hz（1/(2π·10 kΩ·10 µF) ≈ 1.6 Hz）；pcb 视图把同一颗 `C11`
读作 `100nF`（那条对应的 INFO 是 159 Hz），两视图不一致。`C12`/`C13` = `100nF`，
`R11`/`R12`/`R30` = `10K`。同一批里 `R9/C8`、`R10/C9`、`R16/C10`、`R16/C16` 这几对
**只出现在 pcb 视图**（见「视图口径」）。

裁决（整节一个决定即可；INFO 不进高优先精确率分母）：

- [ ] `observation` × 7 —— 记一笔"这些 RC 网络的 -3dB 截止就是这些数"
- [ ] 不记录 —— 数字已印在报里，无需进标注集
- [ ] 拆开（指出要单独记的那几条）：______

---

## B. 单独条目（逐条列，各自勾选）

### B1. `decap-required-caps` —— 1 × WARN（`U5 pin5`：VCC 上的接地电容只有 100nF）

> `U5 pin5: the grounded capacitor on 'VCC' is only 100nF (< required 1uF)`

**补充事实（非规则输出，schematic 视图）**：`U5` = `RT9013-33GB`（SOT-23-5），pin1 在 `+5V`、
pin5 在 `VCC`。`VCC` 上可确认容值的电容：`C6` = `100nF`、`C7` = `10nF`，另有一颗 `C3`
（`Value` 为空，`MPN` = `CGA0603X7R104K500JT` 即 100nF 级）——**没有任何 ≥1µF 的**。

规则自述（`source`，逐字）：

> the part's own required_caps / must_connect facts (datasheet provenance); mode sensitivity per task 011d sec.3.1

同板同规则的 `U5 pin1` 在真相口径下是 **UNKNOWN** 而不是 OK：
`U5 pin1: a capacitor is present on '+5V' (C2), but its value cannot be established, so the required 1uF cannot be checked`
（`C2` 的 `Value` 为空）——即输入侧的结论本轮拿不到，只有输出侧这条是确定的。

裁决：

- [ ] `defect` —— 输出侧应有 ≥1µF，板上只有 100nF + 10nF
- [ ] `exception` —— 100nF/10nF 的组合即设计意图（请给理由）
- [ ] `backlog` —— 先核事实库 `required_caps` 的数值与出处
- [ ] 其它：______

---

## C. 本板未产生 finding 的规则（含 UNKNOWN，**不需要勾选**）

口径：CLI 打印只出 VIOLATION；OK / UNKNOWN / NOT_APPLICABLE 只在规则的四态接口里
（`src/boardwise/rules/base.py::OUTCOME_STATES`），下表为 schematic 视图下逐规则调 `outcomes()` 的结果。

| 规则 | VIOLATION / OK / UNKNOWN / NOT_APPLICABLE | 说明 |
|---|---|---|
| `conn-duplicate-designators` | 0 / 1 / 0 / 0 | OK：`all 56 designators are unique across the parsed pages` |
| `conn-nc-and-must-connect` | 0 / 1 / 6 / 0 | OK：`U5 pin4 is NC and touches no net`；UNKNOWN：`U1 U2 U3 U4 U7 U8`（`U1`/`U4` 是"有条目但无 facts"，其余是"无 shelf 条目"） |
| `conn-library-pins` | 0 / 0 / 1 / 0 | 离线无 resolver，恒 1 条 UNKNOWN |
| `pwr-supply-on-known-domain` | 0 / 1 / 6 / 0 | OK：`U5 pin1 (VIN) sits on '+5V' at 5.0 V — net name '+5V'` |
| `pwr-domain-vs-range` | 0 / 1 / 6 / 0 | OK：`U5 pin1 at 5.0 V fits operating range of mode(s): VIN` |
| `path-ldo-dropout` | 0 / 1 / 2 / 0 | OK：`U5: headroom 1700 mV >= dropout 400 mV`；UNKNOWN：`U1`、`U4`（条目无 `category`） |
| `decap-required-caps` | 1 / 0 / 7 / 0 | 1 条即 B1；`U5 pin1` 是 UNKNOWN（`C2` 容值不可读） |
| `param-led-current` | 0 / 0 / 0 / 0 | 未产出任何 subject（本视图 LED 的封装字段不含 `LED`） |
| `param-divider-output` | 0 / 1 / 0 / 0 | OK：`no resistor divider between a known domain and ground was found on this board` |
| `param-rc-cutoff` | 0 / 7 / 0 / 0 | 7 条即 A1（数字坐在 OK 态，以 INFO 报出） |
| `param-value-mpn-match` | 0 / 8 / 10 / 0 | OK 8 个：`C73 C6 C7 U4 C8 C9 C15 C10`（原文形如 `C73: board value 1e-07 F matches MPN code 104 (1e-07 F)`、`U4: board value 1000 Ω vs MPN 470 Ω differ 2.13x, below the 3x tolerance`）；UNKNOWN 10 个：`C11 C12 C13 R12 R24 R27 R30 C4 C14 R11`（**MPN 为空**；`R1`/`R9` 等因 `Value` 为空不进该规则） |
| `conn-usb-cc-pulldown` | 0 / 0 / **2** / 0 | UNKNOWN ×2：`USB1 pin4`、`USB1 pin10`（原话见 §D.1） |
| `xtal-load-caps` / `shunt-sense-link` | — | 两条都是 `LEGACY`（没有四态侧，只会报 VIOLATION）；本板未报 |

**事实 backlog**：`U1`（`STM32G431RBT6`，条目 C431633 无 facts）、`U4`（条目 C2907329
即 `FRC0805J471 TS` 那颗被 U 前缀的电阻，无 facts）、`U2`（`TP4056` C725790）、
`U3`（`WS-1001-ACW09026` C42377833）、`U7`（`XPT2046` C19076）、`U8`（`PS7516` C2887248）
六类一次可关掉 `conn-nc-and-must-connect` / `pwr-supply-on-known-domain` /
`pwr-domain-vs-range` / `decap-required-caps` 四条规则（每条 6 个 UNKNOWN）。

---

## D. 附注与存疑（供主代理/oracle 判读，**不是 finding**）

1. **CC 下拉在真相口径下拿不到 OK——规则的 UNKNOWN 原文**（schematic 视图）：

   ```
   [UNKNOWN] USB1 pin4 | USB1 sits between USB1 pin4 and 'GND', but its value does not parse as a resistance
   [UNKNOWN] USB1 pin10 | USB1 sits between USB1 pin10 and 'GND', but its value does not parse as a resistance
   ```

   已核实：SCH 里 `R24`/`R27` 的 `Value` = `5.1K`，`parse_resistance_ohms('5.1K')` 能正常解析成
   5100。**代码依据**（不是裁决）：`src/boardwise/rules/facts.py:1244-1256` 的 `_resistance_to()`
   取该网上"第一个同时也碰到 `GND` 的元件"当候选电阻——先撞到的是连接器自己 `USB1`
   （其 pin1/12 在 `GND` 上），于是把 `USB1`（`Value` 空）当成了"阻值读不出的电阻"，
   消息主语也错成了 `USB1`。**板子是对的，规则在这个视图下够不到那条正确值**；要不要按规则
   缺陷处理请 oracle/主代理定，我未下结论。
2. **`C11` 的 `Value` 字面是 `10UF`**（大写 UF）：规则按 10 µF 解析（`parse_capacitance_farads('10UF')`
   = 1e-05 F），于是 `TVDD` 上 fc 报 2 Hz；pcb 视图把同一颗读作 `100nF`（那条 INFO 是 159 Hz）。
   同一器件两视图值不同，登记在此，供 oracle 判断"FC 数字该以哪一版为准"。
3. **解析覆盖提示**：schematic 视图输出 `note: 12 pin(s) dropped during parse (missing pin number)
   — review coverage is incomplete`（pcb 视图没有这行）。若 oracle 要判断本板"是否查全了"，
   这行要算进去。
4. schematic 视图**不打印板级几何**（pcb 视图才有 `board: 253 pads, 350 tracks, 1167 vias` 那一行）。
