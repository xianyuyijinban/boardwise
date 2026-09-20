# 任务 011d：DECAP/PARAM 族 + 兑现 no-rule 栏 + 注入缺陷板

> 2026-09-19 Kimi 立项。执行：DeepSeek；复验：Kimi。011 任务书 §三/§六/§八 的第四步。
> 前置：011a/011b/011c 均已通过复验，基线 **984/187/tsc**。
> oracle 新裁决（2026-09-19）：**V3 query → 真 defect**（板没跑过，无实测反证，
> 按 CH340 手册 3.3V 模式接法判定）；USB1 补录 category=connector 批准。

## 一、前置：oracle 裁决落地（先于规则——地面真值先行）

`reviewsets/ch340g_golden.json`：

1. **U1 V3 query → defect**（severity `WARN`：不损毁器件，但手册接法错误、
   功能可能不工作；oracle 确认该板从未上电，无实测反证）。
   `rule_hint: "decap-required-caps"`（本任务 §三.1 实现，模式敏感）。
   note 写明：VCC=3.3V（RT9013 供）= 3.3V 模式 ⇒ 手册 p.3 §5.1 要求 V3 短接 VCC；
   板上 V3 接 0.1uF（C1）到 GND 是 5V 模式接法。
2. 旁车 `blocklib/parts.corrections.json`：C2765186（Type-C 座）curated 字段加
   `category: "connector"`，并经 harvest 重新生成 parts.json 验证（可复现性纪律：
   不许手改 parts.json）。
3. 更新落地后跑一次 review-eval：U3 defect（param-value-mpn-match）、V3 defect
   （decap-required-caps）、R24/R27 exception（conn-usb-cc-pulldown）应全部出现在
   "no registered rule" 栏，等 §三 的规则逐条把它们摘出去。

## 二、schema 小扩（parts v2 兼容扩展，版本号不动）

1. `supply_pins` / `required_caps` 条目加**可选 `mode` 字符串**（如 `"5V"` / `"3.3V"`）。
   同件多模式时各记录标 mode；无 mode ⇒ 无条件适用。loader 白名单加键。
   **CH340G 条目回填**：两条 supply_pins 分别标 `"5V"`/`"3.3V"`；V3 的
   required_caps 标 `mode: "5V"`；must_connect 加一条 V3→VCC 标 `mode: "3.3V"`。
   （must_connect 条目同步加可选 `mode`。）
2. facts 白名单加 **`pull_required`**：`[{"pin": "4", "to": "GND",
   "expected_value": "5.1k", "provenance": "..."}]`——CONN 族的"此脚必须有下拉/上拉"事实。
   C2765186（Type-C 座）录入：pin4/pin10（CC1/CC2）各一条 `to: GND, 5.1k`，
   provenance 引 USB Type-C 规范 Rd 条款（查得到页码/章节才录，查不到停下来报告）。

## 三、规则实现（全部 OutcomeRule 四态；适用条件/未知/source 齐全）

### 三.1 `decap-required-caps`（DECAP-1，模式敏感——V3 defect 由它兑现）

有 facts 的 IC：每条 `required_caps` 检查——该脚所在网上存在到 GND 的电容，
且**容值与 `value` 声明一致**（容值解析走 parts.py 的既有值门控，不许字符串模糊比）。
- **模式敏感**：条目带 `mode` 时，先用域电压判定该件命中哪个模式
  （落在哪个 mode 的 supply_pins operating 区间）；只查命中模式的 required_caps；
  模式判不出（域电压未知）⇒ UNKNOWN。同时反向查：`must_connect` 带 mode 且命中 ⇒
  该脚必须在指定网（V3 在 3.3V 模式必须在 VCC 网——**V3 defect 就是这条**）。
- 共享电源网"有电容"不自动证明每芯片合规（DECAP-2 是适用条件，不单列规则）：
  判定**逐件逐脚**，不许"网上有一个电容就全 OK"。
- 黄金板预期：U1 pin16（VCC）0.1uF——查 C6/C7 是否其一落在 U1.16 的网（VCC）✓；
  U1 pin4（V3）：3.3V 模式命中 ⇒ must_connect V3→VCC 未满足 ⇒ **VIOLATION（兑现 defect）**；
  U5（RT9013）pin1/pin5 各 ≥1uF：查 C4(+5V)/C9(VCC)——按实测如实报。

### 三.2 `param-led-current`（PARAM-1）

LED（category=led 或封装名 LED*）的阳极/阴极网 → 网上找 category=resistor 的件
（**不许按位号前缀**——U3 的教训）→ 限流计算：`(域电压 − vf) / R`。
- 区间：下限 0.5mA（看得见），上限 facts 的 `led.if_max_ma` × 50%（留裕量）——
  **house rule，source 标 "house rule (Yue, 2026-09)"**，oracle 确认后可调。
- 黄金板预期：LED1 通路 VCC(3.3V) − vf≈2V → U3：value 1k ⇒ 1.3mA 在区间内 ⇒ OK。
  （U3 的 defect 由 §三.4 的规则抓，不由本条——分工写进代码注释。）
- LED 无 facts（vf 未知）⇒ UNKNOWN；网上找不到电阻 ⇒ VIOLATION（无限流）；
  多个电阻 ⇒ 取总串联值。

### 三.3 `param-divider-output`（PARAM-2）与 `param-rc-cutoff`（PARAM-3）

- PARAM-2：分压输出（含电阻容差）落在负载脚声明的输入范围。负载脚范围未知 ⇒ UNKNOWN。
  **黄金板无分压场景**——合成 model 单测覆盖四态即可，不硬找真实案例。
- PARAM-3：RC −3dB 截止报数值（INFO，不定级）；无需求声明不报级。合成单测。
- 两条都标清 source；不为了凑数把 UNKNOWN 写成 OK。

### 三.4 `param-value-mpn-match`（兑现 U3 defect）

电阻/电容：MPN 解码值（如 `FRC0805J471` → 470Ω；`...103` → 10nF）与图纸 `value`
字段矛盾 ⇒ VIOLATION。解码规则白名单化（EIA 三位码；封装码/电压码不吃），
**解不出 ⇒ UNKNOWN**（"MPN 不含可解码值"），不许硬猜。
- 黄金板预期：U3（value 1k vs MPN 470Ω）⇒ **VIOLATION，兑现 defect**；
  R24/R27（value 5.1K，无 MPN）⇒ UNKNOWN；C 系列按实测如实报。

### 三.5 `conn-usb-cc-pulldown`（兑现 R24/R27 exception）

connector 且有 `pull_required` facts：每个指定脚所在网必须有到 `to` 网的、
阻值匹配的电阻。缺失 ⇒ VIOLATION；阻值不符 ⇒ WARN。
- 黄金板预期：USB1 pin4←R27、pin10←R24 各 5.1k ⇒ **OK ×2**（exception 记录
  保持安静——它们钉的就是"不许报这里"）。

## 四、注入缺陷板（oracle 审清单后执行）

**先列清单给岳翔宇审，审完才造**（011 §六：注入的必须是真实会犯的错）。
建议清单（每条注明造法与预期抓它的规则）：

1. 删 C1（CH340G V3 退耦缺失，5V 模式语义）→ decap-required-caps；
2. 重复位号（第二页放一个 R1）→ conn-duplicate-designators；
3. RT9013 pin4（NC）接 GND → conn-nc-and-must-connect；
4. `+5V` 网名改 `+9V`（超 RT9013 abs 6V）→ pwr-domain-vs-range ERROR；
5. RT9013 输入改由 3.3V 供（压差 0V < 400mV）→ path-ldo-dropout；
6. LED 限流改 100Ω（电流超区间）→ param-led-current；
7. U3 value 改 2.2k、MPN 不动（470Ω）→ param-value-mpn-match（单错型）。

造法：脚本从 `ch340_golden.epro2` 派生（JSON 行定点手术），**脚本入仓**
`reviewsets/injected/`，一变体一 .epro2 + 对应标注（defect 记录指向预期规则）。
注入板进 dev split；holdout 划分等 011e 统一做。

## 五、验收集扩容（真实板）

仓内可用：`ProPrj_CH340G_2026-09-13`（完整工程）、`ProPrj_智能药箱_2026-09-17`、
`ProPrj_ROBOT ctrl FOC_2026-09-16`、`ProPrj_毕设FOC驱动板_2026-09-17`、
`ProPrj_高速电机控制器_2026-09-16`、`llc_board.epro2`、`board24v.enet`。
本任务只做**一步**：每块板跑一遍 review-eval 生成**未标注基线报告**
（`outputs/011d_baseline_<board>.txt`），看四态分布——**不标注**（标注是 oracle 的活，
011e 做）。报告里 UNKNOWN 清单就是 facts 录入优先级表。

## 六、测试与变异

- 每条新规则四态单测（合成 model）+ 黄金板实测预期（§三右列）；
- schema 扩展：mode/pull_required 白名单、缺 provenance 拒绝；
- 注入板：每个变体的预期规则命中各一条测试（注入缺陷被抓住才算注入成功）；
- 变异 ≥4（建议：模式敏感改模式盲；MPN 解码 UNKNOWN 改硬猜；pull_required 不查阻值；
  LED 电流区间不查下限），还原逐字节一致。

## 七、交卷标准

- pytest 全绿（基线 984 + 新增）、connector 187 / tsc 不动（应零 TS）；
- 黄金板 review-eval：**no registered rule 栏清空**（五条 hint 全部兑现），
  U3 + V3 两条 defect det=2，R24/R27 exception 保持安静，queries excluded=0；
- 注入清单经岳翔宇审签；注入板变体与标注入仓；
- 6 块真实板基线报告落盘；交卷记录写 011 任务书（交卷记录 D），写完独立数标记。

## 八、明确不做

- holdout 划分与晋级测量（011e）；真实板标注（011e，oracle 的活）；
- CONN-3 真机 resolver（仍离线 UNKNOWN）；
- 数字接口族 / MCU 外围族 / 固件接口族（第二批）；
- 不改既有规则 id 与语义（xtal 修复那类回归守卫不许退化）。

## 九、纪律

同前：注释全英文；不动 git；`.tmp_*` 用完删（**上轮的 bak_tmp 是我抓的，别再留**）；
append 后独立数标记；pytest `--basetemp=.tmp_pt_home`；与预期不符停下来如实报告。

---

## 交卷记录 E：注入板已签子集生成（2026-09-20）

**oracle 签署**：#1–#5、#7（岳翔宇，2026-09-19）；#6 原案撤下，替换案待签。本记录只覆盖已签子集。

### 交付物

| 落点 | 内容 |
|---|---|
| `reviewsets/injected/make_variants.py` | 签名门闩改为**已签子集模式**：每个提案带 `signed` 日期；`--generate` 无参数⇒全部已签，指定 id⇒只要有一个未签就**整体拒绝**（exit 2）；新增 `--check`（重建并逐字节比对落盘产物）。**每个编辑都是值定位**（按位号/属性键/值/lineGroup 查找，每次查找断言唯一命中），每条被改写的行都按"解析后重新序列化 == 原文"自检——格式漂移会当场炸，不会静默污染夹具。记录 id 由 `sha1(变体:用途:序号)` 派生、归档用固定 DOS 时间戳 ⇒ **重建逐字节可复现**。 |
| `reviewsets/injected/<id>.epro2` ×6 | 派生板；每变体一个真实错误（删器件 / 新页重复位号 / 清 NO_CONNECT 后接线 / 改网名 / 改走线 / 改 Value） |
| `reviewsets/injected/<id>.json` ×6 | 标注集：**一条 defect**，`rule_hint` = 预期规则，`reviewed_by` = 签名人与日期，`split: dev`（注入板进 dev；holdout 归 011e） |
| `tests/test_injected_variants.py` | 14 条：逐变体"故障确实在派生板上且**不在**基底板"+"预期规则 det=1/1 且无误报、严重级与标注一致"+门闩拒绝+重建逐字节一致 |
| `src/boardwise/engines/review_eval.py` | **配对改为两趟**（见下"真 bug"）；`tests/test_review_eval.py` 加钉 |
| `outputs/011d_variants_report.md` | 逐变体指标表 + 两处必须让 oracle 知道的事 + 变异记录 |

### 逐变体（`outputs/011d_variants_summary.txt` / 各自 `outputs/011d_variant_<id>.txt`）

| 变体 | 预期规则 | ref | 严重级 | det/hinted | 交叉 | 误报 | 基底板 |
|---|---|---|---|---|---|---|---|
| v3-decap-missing | decap-required-caps | U1 | WARN | 1/1 | 0 | 0 | **1/1 不隔离** |
| duplicate-designator | conn-duplicate-designators | R24 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| nc-pin-grounded | conn-nc-and-must-connect | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| overvoltage-rail | pwr-domain-vs-range | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| ldo-no-headroom | path-ldo-dropout | U5 | ERROR | 1/1 | 0 | 0 | 0/1 ✓ |
| value-mpn-mismatch | param-value-mpn-match | U3 | WARN | 1/1 | 0 | 0 | **1/1 不隔离** |
| led-overcurrent | param-led-current | LED1 | WARN | — | — | — | **未生成（未签）** |

### 两处需要 oracle 裁决/知情

1. **两个变体不是隔离实验**（已写进 `oracle_note` 与专门测试）：
   - `v3-decap-missing`：黄金板**本来**就违反 V3 接线（3.3V 模式要求 V3 短接 VCC，板上没接），
     删掉 C1 后规则报的是**同一件事**（V3 网因重排由 NET1 变 NET12）。它是**回归板**，
     不是"缺失电容被抓到"的证明。要隔离这条路径需**新提案**：先把 V3 正确接到 VCC，再删 C1。
   - `value-mpn-mismatch`：U3 的 `1kΩ` vs MPN 470Ω **本来就矛盾**（011c/011d 的 U3 defect）。
     本次编辑拉大到 2.2kΩ，**同时**把 LED 限流从"跨阈值 UNKNOWN"推成"低于下限 VIOLATION"
     （0.05–0.27 mA）——一次编辑两个后果。
2. **签名严重级以规则实测为准**：写入时先把 6 条逐一实测，`v3-decap-missing` 由初拟 ERROR
   改为 **WARN**、`ldo-no-headroom` 由初拟 WARN 改为 **ERROR**（测试现在钉住"标注严重级 ==
   规则实际报告的严重级"，两处不一致会被咬红）。

### harness 的一处真 bug（已修）

配对原来**边走 finding 边归属**：交叉匹配会**抢走**本该归给被提示规则的缺陷。实测触发——
`value-mpn-mismatch` 板上 `param-led-current` 的 finding 也提到 U3（它读的就是 LED 限流电阻），
而该规则在 `BUILTIN_RULES` 里排在 `param-value-mpn-match` **之前** ⇒ 缺陷被交叉匹配吞掉，
预期规则 det=0/1。修法：**两趟配对**（第 1 趟只做"提示规则自身"的精确配对，第 2 趟才做交叉/
例外/无解释），语义只收紧不放松——原交叉匹配测试（被提示规则沉默时）仍绿。

### 一个生成期的真坑（已修）

新记录**必须插进原理图页区**，不能追加到文件尾：解析器只在"最近的 DOCHEAD 是 SCH_PAGE"时
保留记录，追到文件尾的记录落进 CONFIG/BLOB 文档被直接跳过——现象是"线没画上"（引脚变悬空、
网数 13→14），而不是报错。首版两个走线变体都因此跑偏（U5.4 落进自己的新网、U5.1 悬空），
靠逐变体实跑抓回。⇒ **变异 M3 专门钉这条**（把插入点改回文件尾 ⇒ 只有重建逐字节比对能咬住，
因为测试读的是已落盘夹具，生成期缺陷必须靠重建抓）。

### 验证

- pytest **1031 passed**（基线 1013，+18）；connector 187 / tsc 干净（零 TS 改动）。
- **变异 4 个全 CAUGHT**，源码与 12 个产物**逐字节还原**：①关掉两趟配对的第 1 趟；
  ②门闩不再拒绝未签项；③新记录追加到文件尾；④记录 id 不再由变体 id 派生。
- `--check`：6 块重建与落盘**逐字节一致**（固定时间戳 + 派生 id）。

### 待办

- `led-overcurrent` 替换案（4.7Ω，理由见提案表）等 oracle 签署；签署后 `/generate led-overcurrent`
  即可，门闩会自动放行。
- 若要"缺失电容"的隔离实验，请签一条新提案（先修 V3 接线再删 C1）。