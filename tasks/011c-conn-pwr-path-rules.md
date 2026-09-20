# 任务 011c：CONN/PWR/PATH 六条规则 + 域推断器 + 遗留修复

> 2026-09-19 Kimi 立项。执行：DeepSeek；复验：Kimi。011 任务书 §三/§八 的第三步。
> 前置：011a（harness）、011b（facts 库 v2 + 3 IC）均已交卷并通过复验，基线 **950/187/tsc**。
> oracle 已审完 `outputs/011b_provenance.md`；U3 三条 query 的裁决已出（见 §二）。

## 一、范围

011 §八 的 011c：**CONN-1/2/3 + PWR-1/2 + PATH-1** 六条新规则。
顺带三个小项（都是已裁决的遗留）：
1. `xtal-load-caps` 误报修复（011a 实测钉住的：跳过已在 GND 网上的晶振脚）；
2. `review --view schematic|pcb`（默认 pcb，不动既有行为——Kimi 已裁）；
3. 标注集落地（§二，oracle 已裁，你负责写入）。

## 二、标注集更新（先做——地面真值先于规则，calibration 的教训）

`reviewsets/ch340g_golden.json`，oracle（岳翔宇 2026-09-19）裁决如下：

1. **query LED1 → defect**（`U3`）：板上 value=`1k`、MPN `FRC0805J471` 解码=470Ω、
   oracle 设计意图=**2.2k**（"LED 统一 2.2k"）——三者互不相同。
   `rule_hint: "param-value-mpn-match"`（**规则不存在，第二批实现**；harness 按 §三.0
   的新栏如实显示）。severity `WARN`（1k/470Ω 电气上烧不了 LED，但 BOM 与图纸矛盾）。
   note 写全三个数。
2. **query U3 → observation**：身份已明——0805 电阻挂 U 前缀位号；
   "位号与器件类型一致性"是第二批规则素材，记 observation 不钉 defect。
3. **query R24/R27 → exception ×2**：Type-C 座（C2765186）CC1/CC2 的 5.1k Rd 下拉，
   受电端标准设计。`rule_hint: "conn-usb-cc-pulldown"`（同样未注册，进 §三.0 栏）。
4. **新增 query U1（V3 模式，Kimi 挖电源树时发现）**：VCC 网 = RT9013 输出 = **3.3V**，
   但 U1.4（V3）接 0.1uF（C1）到 GND——这是 CH340 手册 p.3 §5.1 的 **5V 模式**接法；
   3.3V 模式手册要求 V3 短接 VCC。问 oracle：这板这样跑过吗？有意还是缺陷？
   （`rule_hint: ""`，kind `query`，note 里附手册出处。）
5. `reviewed_by` **保持空**——等 oracle 终审全表后另签。

## 三、规则实现规格

### 三.0 前置：harness 补一栏（小改，先于规则）

`engines/review_eval.py`：defect/exception 的 `rule_hint` **不在规则注册表**时，
今天它们静默消失（`defects_hinted` 不计数）。加一栏
**"no registered rule"**：逐条列出 `ref / hint / kind / note`，不计入任何规则分母。
理由：oracle 的地面真值不被规则进度绑架；未覆盖的 defect 正是规则开发的优先级表。
（现有测试不应破——它们没有未注册 hint；加新测试钉住该栏。）

### 三.1 域推断器（PWR-1/2、PATH-1 的公共依赖，011 假设的"009c 机制"不存在——本任务新建）

`engines/power_domains.py`（新）：输入 schematic model + facts 库，
输出 **net → (电压, 来源证据)**。只有两个来源，都保守：

- **网名数值**：白名单正则（`+5V`、`5V0`、`3V3`、`3.3V`、`1V8`…）。
  裸 `VCC`/`VDD`/`VBUS` **不猜**——名字会撒谎。
- **facts 的稳压器输出**：LDO 输出脚所在网 = 该件输出电压
  （RT9013-**33**GB → 3.3V；输出电压从 facts/MPN 后缀来，不许从网名反推）。
- **两来源冲突 ⇒ UNKNOWN**，消息里两个来源都列出；无来源 ⇒ UNKNOWN。
- 每个推断出的电压**必须带来源字符串**（"net name '+5V'" / "U5 RT9013-33GB output"），
  规则报告时原文转述。

### 三.2 六条规则（全部实现 `OutcomeRule.outcomes()` 四态协议，不只 `check`）

| id | 实现要点 | 黄金板预期（dev 实测验证用） |
|---|---|---|
| CONN-1 重复位号 | **parser 合并多页时位号是 dict 键——重复会被覆盖丢弃**。在 `parsers/schematic.py` 合并处先收集重复对（model 加 `duplicate_designators` 字段），规则只读它。先写 parser 现状测试钉住"今天会丢"，再改。 | 无重复 ⇒ OK |
| CONN-2 NC/must_connect | 板上 IC 按 mpn/lcsc → `find_facts`。`nc_pins` 的脚出现在任何网 ⇒ VIOLATION；`must_connect` 的 `to` **是网名**（GND/VCC）才机判，自由文本（"external 12MHz crystal network"）⇒ UNKNOWN（"目标不可机判"）。板上件无 facts ⇒ UNKNOWN（缺哪个件的 facts 写名字，导向录入优先级）；category 明确非 ic ⇒ NOT_APPLICABLE。 | U1：must_connect 7/8 自由文本 ⇒ UNKNOWN ×2；U3（无 facts）⇒ UNKNOWN；RT9013 pin4 NC 悬空 ⇒ OK |
| CONN-3 库 pin 一致性 | 规则接受**可选 library resolver**；review CLI 离线无 resolver ⇒ UNKNOWN（"library comparison requires bridge"）。用 USB1 库漂移案例（M6）做 resolver 模拟测试。**真机路径不在本任务实现。** | 离线 ⇒ UNKNOWN（一条，写明原因） |
| PWR-1 供电脚在已知域 | facts.supply_pins 的脚 → 所在网 → 域推断器。网电压已知 ⇒ OK；未知 ⇒ UNKNOWN。无 facts ⇒ UNKNOWN；非 ic ⇒ NOT_APPLICABLE。 | U1.16→VCC(3.3V, U5 facts) OK；U5.1→+5V(网名) OK |
| PWR-2 域电压 vs 范围 | 两级：超 `v_abs_max` ⇒ ERROR；超 `v_operating` 但在 abs 内 ⇒ WARN；范围内 ⇒ OK。**多模式件**（CH340G 5V/3.3V 两条 supply_pins）：落在任一模式 operating 内 ⇒ OK，消息写明命中模式。 | U1：3.3V 命中 3.3V 模式 OK；U5：5V ∈ 2.2–5.5 OK |
| PATH-1 LDO 压差 | category=ic.ldo 的件：输入脚网电压 − 输出脚网电压 ≥ `ldo.dropout_max_mv` ⇒ OK，否则 VIOLATION；任一侧电压未知 ⇒ UNKNOWN。 | U5：5 − 3.3 = 1.7V ≥ 400mV ⇒ OK |

**每条规则**声明适用条件 / 未知行为 / source（datasheet 页码或 house rule）——
011 §三原话："空字符串是欠债"。UNKNOWN 的 `missing_fact` 必填（011a 协议已强制）。

### 三.3 xtal-load-caps 修复

引脚所在网**已是 GND** ⇒ 该脚跳过（X1 的 2/4 外壳脚）。修复后黄金板
`xtal-load-caps` 的 fp-exc 应从 1 归 0——标注的 X1 exception 不动，度量自洽。
回归测试：四脚晶振外壳接地场景不再报；两脚晶振正常路径不变。

### 三.4 `review --view schematic|pcb`

`cli.py:514` 现在恒走 `build_design_model`（PCB 侧）。加 `--view`，默认 `pcb`
（既有行为与测试不动）；`--view schematic` 走 `build_schematic_model`。
帮助文本写明：`.epro2` 原理图审查用 `--view schematic`。

## 四、测试与变异

- 每条规则：VIOLATION / OK / UNKNOWN / NOT_APPLICABLE 四态至少各一条单测
  （合成 model，不依赖真机）；外加黄金板 dev 实测的逐条预期（§三.2 右列）。
- 域推断器：网名命中 / facts 命中 / 冲突 UNKNOWN / 无来源 UNKNOWN / 裸 VCC 不猜。
- harness 新栏：未注册 hint 的 defect 出现在清单且不进分母。
- xtal 修复回归 + `--view` 双路径冒烟。
- 变异 ≥4（建议：域推断冲突变 OK；PWR-2 两级合并成一级；CONN-2 自由文本硬判；
  xtal 跳过逻辑反写），每个只咬该咬的测试，还原逐字节一致。

## 五、交卷标准

- pytest 全绿（基线 950 + 新增）、connector 187 不动、tsc 不动（应零 TS 改动）；
- `review-eval --annotations reviewsets/ch340g_golden.json` 跑出六条新规则的
  四态计数 + "no registered rule" 栏（U3 defect、R24/R27 exception 各在其位）；
- 黄金板实测输出落盘 `outputs/011c_golden_eval.txt`；
- 交卷记录写进 `tasks/011-review-rules-m1.md`（交卷记录 C），写完独立数标记。

## 六、明确不做

- DECAP/PARAM 族规则（011d）；注入缺陷板（011d）；holdout 测量（011e）；
- CONN-3 的真机 resolver 接线（只交付离线 UNKNOWN + 模拟测试）；
- V3 query 的裁决（oracle 的事——规则跑出的 UNKNOWN/OK 随交卷报告给他）；
- 不改 3 条既有规则的 id 与判定语义（xtal 修复只加跳过条件）。

## 七、纪律

同 011b：注释全英文；不动 git；临时文件仓内 `.tmp_*` 用完删；
append 后独立数标记；pytest `--basetemp=.tmp_pt_home`；
与预期不符停下来如实报告，不许绕过。
