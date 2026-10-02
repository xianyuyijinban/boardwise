# A 主线：设计意图通道（Design Intent Channel）

**北极星（岳 2026-10-02）：AI 独立完成一个小的原理图，达到毕业设计水平。**
参照物现成：毕设 FOC 驱动板（电源入口 / 多路电源 / MCU 最小系统 / 栅驱动 / 三相桥 /
电流采样 / 编码器与 Hall / CAN / UART，约十种模块）——终验收的候选形式：**给 AI 同一份
需求，它画，岳对照自己手绘的原板盲评**。

## 一、为什么「意图通道」是下一块地基

今天三条线上各有一个被实测证明的洞，洞底是同一件事：**系统里没有「设计意图」这个一等公民**。

1. **审查的发现≠修复依据**（052 评审）：MPN 与 Value 冲突时，规则不知道哪边是对的
   （实测 17 颗器件是 MPN 写错、设计值正确；按「改 Value」的建议修会把电路改错）。
2. **架构自洽无人检查**（ctrl FOC 偏置案）：单极性 ADC 输入配双极性采样信号——
   这不是任何一条规则能写的，是「信号链不闭合」。岳当时的原话：让 AI 审查时
   **自己写一份架构图，确保架构自洽**——本通道就是那个架构图的机读形态。
3. **绘制已经两次手工开口**：`openInterfaces[].part`（哪颗是入口）、`branchOrder`
   （哪颗是 TVS）——两次都验证了同一个模式：**模型声明、语法核验、编译器执行**。
   本通道把这个模式从「两处特例」升级为「一份文档」。

持久化纪律（052 的第三个洞）：自动生成的骨架**永不覆盖**已填的意图
（`architecture.md` 重生成把 `targetVoltage: 3.3V` 冲成 TODO 的事故不许再演）。

## 二、DesignIntent 文档（A1 的核心交付）

第四份合同（`src/boardwise/core/designintent.py`），与 CircuitSpec/PresentationSpec/LayoutPlan
平级但**先于**它们。落盘为 JSON：`~/.boardwise/design-intent/<projectUuid>.json`
（`--intent PATH` 显式覆盖；`BOARDWISE_HOME` 跟着 `config.json` 一起挪）。

```jsonc
{
  "intentVersion": 1,
  "requirements": {                    // 需求层：这块板要干什么
    "rails": [                         // 一处 = 一条轨（对象是架构枚举出的轨）
      {"net": "+24V", "targetVoltage": "24V", "continuousCurrent": "5A",
       "peakCurrent": "15A", "role": "bus", "provenance": "user_stated"}
    ],
    "signals": [                       // 一处 = 一条链（模拟链 / 控制链）
      {"net": "IU+", "kind": "current-sense", "polarity": "bidirectional",
       "range": "±3A", "adcSwing": "0..3.3V", "provenance": "verified_recipe"}
    ],
    "buses": []                        // 一处 = 一类总线（成员完整性 / 自洽性）
  },
  "blocks": [                          // 架构层：功能块与其闭合关系
    {"id": "senseU", "kind": "current-sense",
     "requires": ["bias-reference"],   // 自洽检查的事实源：偏置案就是缺这句
     "feeds": ["mcu.adc"]}
  ],
  "decisions": [                       // 决策层：为什么是它（修复依据那一半）
    {"subject": "R4", "decision": "0.1Ω/1% 直采，不加放大器",
     "rationale": "接受只有正半轴与约 7.8bit", "provenance": "user_stated"}
  ]
}
```

**槽位从哪来**：三个段落的**对象**（哪几条轨、哪几条链、哪几类总线）与**每个对象欠哪些键**，
一律来自 `core/architecture.py` 的枚举（044 M1 骨架 / 053 §2.2 合并视图，也就是
`architecture.md` 与 `design-intent.md` 表用的同一份）。本模块只做「枚举 → 三个段落」的
**映射**（`reuse_slots`），不自己再推一遍电源树——两个枚举器就是两份「这块板是什么」的答案。

**可选字段缺省不写出**：没答的槽在文件里**不占位**（`"targetVoltage"` 干脆不出现）——哪些键
该有，是图纸说了算；哪些键答了，是文件说了算。两者相减就是报告里的 `missing` 清单。
条目上另有两个字段：`role`/`kind`/`adcSwing`/`requires`/`feeds`（设计文档自己点名的语义字段），
以及 `provenance`（每条都写，缺省 `ai_asserted`）与 `stale`（只在为真时写出）。

三条铁律（与既有合同同构）：

1. **schema 封闭 + 可选字段缺省不写出**——未知键报错并点名路径；旧文档逐字节回读，
   `intentVersion` 不轻升（不读的版本拒收，不猜）。
2. **provenance 全程跟随**——`user_stated` > `verified_recipe` > `ai_asserted`；
   等级表与 weakest 规则**与语法侧同源**（`core/circuitspec.py` 的一张表，
   `engines/grammar/base.py` 的 `weakest_provenance` 是同一套排序；core 不许 import engines，
   所以共享点在 core）。文档自身的等级 = **最弱的那条**，一条 `ai_asserted` 就让整份文档是
   草稿：审查结论必须能按 provenance 分级（AI 猜的需求不许当作判违规的依据，只能当提示）。
3. **工具只校验与提问，永不改写**——槽位缺失就报 `intent-missing`（与 `facts-missing`
   同族措辞：点名槽位 + 写到哪个文件哪个键）；`polarity: bidirectional` 的 current-sense
   信号没有任何闭合声明时出**提示**（`closure-undeclared`，FOC 偏置案的槽位形态，A3 升级为规则）。
   填的人是工程师或模型，工具不代填、不拦读。

## 二·补、持久化纪律（A1 的命门）

- **落点**：`~/.boardwise/design-intent/<projectUuid>.json`（真机 / checkup 默认读），
  `--intent <path>` 显式覆盖（离线、测试、第二份 profile）。
- **写的人只有一个**：`boardwise arch <export> --intent <path>`（首次 = 生成全 TODO 骨架，
  之后 = 重生成）。`checkup` 只**读**：它报告槽位与缺失，绝不改契约一个字节——
  没被要求重生成的运行不会在用户家目录里凭空建文件。
- **合并语义**（`designintent.merge`）：重生成 = 以当前工程枚举出的槽位为准**新增 TODO 条目**；
  已填值（含人工改过的）**逐字节保留**；工程里已消失的对象标 `"stale": true` 而不删
  （删不删留给 A 后续批）。新增条目插在**该段最前**：JSON 数组元素之间用行尾逗号分隔，
  插到最前则已有行**一个字节都不动**——「全文除新增槽外逐字节」就是靠这一点落地的。
- **回归钉**（052 覆盖案，`tests/test_090_design_intent.py`）：先填 `targetVoltage: 3.3V`
  → 重生成 → 该值原样、该对象其余槽仍是 TODO、已有每一行都还在。

## 三、消费者接入顺序（每步都是独立可验收的批）

| 批 | 消费者 | 闭环 | 证明什么 |
|---|---|---|---|
| A1 | 文档+持久化+审查报告接线 | checkup 报告挂 `intent` 节（槽位总数/已填/缺失 + `intent-missing` 点名）；`design-intent.md` 改由合同渲染 | 文档活着、不丢、不覆盖 |
| A2a | 审查规则（params） | 冲突时按 intent 给**方向**：该位号有 `decisions[].value` → 建议改料号/重选件（按 provenance 分级语气）；没有 → 双向列出 + `intent-missing` 点名 `decisions[].value` | 发现→修复依据（**已落地，091**，见 `tests/test_091_intent_direction.py`） |
| A2b | 审查规则（额定/降额）+ 报告接线 | rail 声明进「耐压 vs 轨压」与「LDO 耗散」两条规则；`checkup` 把合同传进规则走查（A2a 落地记录的「未接线」已补） | **已落地，092**，见 `tests/test_092_rail_ratings.py` 与 §七 |
| A3 | 架构自洽检查器 | 信号链闭合规则（采样链必须有偏置/参考、开漏必须有上拉、单端 ADC 不许直吃双极性信号……第一批 5–8 条，全部来自真案例） | FOC 偏置案可由规则查出 |
| A4 | 绘制侧 | 语法绑定消费 blocks/decisions（TVS/bulk 角色、支路顺序、模块清单由 intent 推出） | 意图→图纸同源 |

## 四、通往「毕设水平」的全程路线（A 主线之后的 backlog，记档）

1. 页级两缺陷修复（宽轨 mainPath、锚点吸附）——088 §七已钉实测。
2. CH340 整模块集成验收（052 定的组合终点）。
3. 语法谱系扩到毕设模块清单：buck、MCU 最小系统（去耦簇/复位/晶振）、栅驱动级、
   三相桥、差分采样、接插件簇——每种都走「样板→语法→真机」的 088 流程。
4. 工程级编排：intent → 模块清单 → 页划分 → 整页组合（project orchestrator）。
5. 产品价值验证：不同模型同一 harness 对比（首过率/读图耗时/返工量），工程师盲读。

## 五、A1 验收标准（090 批已落地，见 `tests/test_090_design_intent.py`）

- `DesignIntent` schema 与封闭性测试；provenance 弱词沿证据链可见（052 §4）：
  报告 `intent` 节带 `provenance`（最弱的一条）与 `draft`/`draftReasons`。
- checkup 报告挂 `intent` 节：槽位总数/已填/缺失清单；缺失必填槽（rail 无电压声明、
  链无极性）报 `intent-missing`（点名槽位 id + 写到哪个文件哪个键）；重生成不覆盖已填
  （回归钉：填过的槽在重生成后逐字节保留，且已有每一行都还在）。
- 一个真实案例走通：`blocklib/intents/robot-ctrl-foc.intent.json`（ctrl FOC 的公开事实）
  进 checkup → 报告 intent 节点出「F1 偏置案对应哪条链、缺哪一句闭合声明」
  （`closure-undeclared: 链 U+ 缺 requires: ["bias-reference"]`）——**只接线不判案**。
- 离线全绿；文档（architecture / 本文件）同步；不动 git 由主代理落账。

### A1 落地时与本节原稿的两处出入（回改记录）

1. **`requirements` 多一个 `buses`**：架构枚举给每一类总线都欠 `completeness`/`consistency`，
   而原稿只列了 rails/signals——欠的槽必须每个都有家，否则「合同是源」这句话是假的。
2. **案例文件的 net 名用导出档自己的**：ROBOT ctrl FOC 的导出（
   `tests/fixtures/ProPrj_ROBOT ctrl FOC_2026-09-16.epro2`）里，轨叫 `+12V`/`VCC`/`VCCA`，
   两条相电流链叫 `U+`/`W+`；`+24V`/`IU+`/`IW+` 是这块板在真机工程里的叫法（原稿按它写的）。
   合同按**导出档的名字**写，接线才指得到真实槽位；`+24V` 这种「合同里有、图纸里没有」
   的对象由 `stale` 规则接住（不删只标），测试里正是拿 `+24V` 钉的这条。

## 六、A2a 落地记录（091 批，见 `tests/test_091_intent_direction.py`）

052 评审点 1 的实案是**发现矛盾 ≠ 知道该怎么修**：一块板上 17 颗器件是 MPN 字段写错、
设计值正确，照「把 Value 改成料号解码值」的建议修会把电路改错。A2a 让 params 规则消费
意图，方向由合同定。

1. **合同侧多一个可选键**：`decisions[]` 的 `value`（如 `"0.1Ω"`）——`decision` 是散文，
   机读值才能和 MPN 对拍。可选、缺省**不写出**、`intentVersion` 不升、未知键照旧报错点名；
   `core.designintent.IntentDecision.stated_value` 是它的属性名（`value(key)` 是条目协议，
   字段不能遮蔽它，映射在 `_RENAMED` 里）。案例
   `blocklib/intents/robot-ctrl-foc.intent.json` 的 R4 决策补上了 `value: "0.1Ω"`。
2. **三态，一个生产者**（`rules/params.py::repair_directions`，规则唯一产出路径都过它）：

   | 合同状态 | 消息 |
   |---|---|
   | 无合同（`intent is None`） | 052 原句**逐字节**：两个方向都列、不选（回归钉） |
   | 该位号有 `value` | 方向 = **改料号/重选件**（设计值是对的），带 `provenance` 与出处文件；`user_stated` 陈述语气，`ai_asserted` 改问句（052 §4），另有「决策值与本板值也不一致」的诚实附句 |
   | 该位号没有 `value` | 两个方向都列 + `intent-missing` 一行：点名文件与 `decisions[subject='X'].value` |

3. **注入缝**：合同以 `core.designintent.IntentSource`（文档 + 它读自哪个文件）随
   `run_review(model, intent=…)` 进规则——`rules` 只许 import `core`（006c 层表），所以载体
   在 core；规则**自己不读盘**，哪份合同是调用方的问题。规则实例是**每次运行新建**的
   （`engines/review.py::_rules_for`），因为 `BUILTIN_RULES` 比一次运行活得久，把答案设在
   共享实例上会漏进下一次读取；没给合同时返回 `BUILTIN_RULES` **本身**（不复制）。
4. **不改判决**：severity / 四态 / evidence / finding target（`suggested_after` 仍为空）
   三态完全一致——`--direction mpn` 这条 change kind 本 build 仍未开放，`edit plan` 的
   纪律（052 §2.1：方向和值由操作者给）一个字没动。意图进评级归 A3。
5. **未接线（留给 A2b）**：`checkup` 的 CLI 还没有把合同传进规则走查——
   `_cmd_checkup` 里规则走查（`run_review`）发生在 shelf/架构枚举/合同加载**之前**，而默认
   合同路径要用枚举出的 projectUuid，所以诚实接线要把这三步整体提到走查之前（会改 notes
   顺序）。本批先把缝做好、并用真实案例（ctrl FOC 导出 + shipped 合同）在测试里走通；
   `checkup --intent` 目前仍只驱动报告里的 `intent` 节。**（092 A2b 已补上，见 §七）**

## 七、A2b 落地记录（092 批，见 `tests/test_092_rail_ratings.py`）

A2a 把「方向」交给了规则，A2b 花同一条通道问两个**图纸上没有**的问题：*这颗电容的耐压
够不够它所在的轨*，*这颗 LDO 耗散多少*。两条规则都只读两份现成文档——合同
（`requirements.rails[].targetVoltage` / `.continuousCurrent`）与货架——都不碰盘。

1. **接线（A2a 的遗留项）**：`_cmd_checkup` 里「shelf 加载 → 架构枚举 → 合同解析」三步整体
   提到 `run_review(model, intent=…)` **之前**（合同默认位要用枚举出的 projectUuid，这是顺序
   的硬理由）。合同以 `core.designintent.IntentSource` 进规则，规则自己不读盘（006c 的层表
   只给 `rules` 留了 `core` 这条路）。**无合同读数逐字节不变**（实测：同一份导出加与不加
   `--intent`，report.json/report.md/architecture.md/design-intent.md 逐字节一致，除
   `generatedAt` 与文件名自身的路径）。**notes 顺序有一处变化**：显式 `--intent` 指向的文件
   不存在时，那条「合同不存在」的 note 从末位提前到首位（它现在在走查之前产生）——既有测试
   没有钉 notes 序，只有「包含」断言，故无一改。
2. **两条规则**（`rules/railratings.py`，进 `BUILTIN_RULES` + `INTENT_RULES`）：
   `pwr-cap-voltage-rating`（R1）与 `path-ldo-dissipation`（R2）。三态一个纪律：**测量永远报
   （INFO，报比值/报压差）、只有拿得准的越限才 WARN、读不到就 UNKNOWN 并点名去哪补**。
   **不发明降额标准**：比较就是 `rating >= rail` 与 `P <= 声明的限值`，没有 80% 系数、没有
   「SOT-223 大约 1 W」这类house rule——装进测量行外衣的判决比沉默更坏。
3. **取值口（按既有顺序，能读才读）**：
   - 轨压 = 合同的 `targetVoltage`（需求）→ 否则图上自己的判断（`infer_net_domains`：网名报电压、
     LDO 输出事实/后缀解码）。两份文档**打架**时不在这里裁（合同是需求、图是图纸，谁错是 A3 的
     架构自洽问题）；
   - 电容耐压 = 货架条目的 `Voltage Rating`/`Rated Voltage` 字段（目录的原始声明，**现成数据**
     ——`blocklib/parts.json` 里 11 颗电容都有）→ 板上 Value 字段里的电压 token（`100nF/50V`）
     → MPN 的 `value+tolerance+voltage` 电压码（`core.values.mpn_voltage_rating`，即 071 §1 C
     的锚点写法；`...106M250` = 25 V）。三种读法在 11 颗有目录的电容上**逐一吻合**（测试钉死）；
   - LDO 限值 = `facts.ldo.max_dissipation_mw`（可选、带出处；这是 092 在 `ldo` 事实里加的第二个
     可选键，与 `fixed_output` 同款）。**没声明就只报测量行**，不编封装限值。
4. **报告出口**：INFO 测量行与 UNKNOWN 行都作为 **INFO finding** 进 `report.json`（四态仍在
   `Outcome.state`）。INFO 恒不拦写入（#55 裁决 B）、不抬 verdict、不动退出码；UNKNOWN 的
   `missing_fact` 就是那条「写进哪个文件哪个键」的工单（`needs_datasheet` 同族措辞）。
5. **两条都进了 `NET_MEMBERSHIP_RULES`**（issue #19）：R1 判「谁在这条轨上」、R2 的压差是两个
   推断轨压之差，都是按网判的结论，per-page 档上对被焊过的网名一律只报 UNKNOWN。
6. **ctrl FOC 实测（导出 + shipped 合同）**：R1 报 6 条 INFO 测量（C10 2.08x、C7 7.58x、
   C13/C14/C16/C18 15.15x）、6 条「耐压读不出」UNKNOWN（C5/C6/C9 @+12V，C1/C15/C8 @VCC）与
   1 条「轨压读不出」UNKNOWN（C17 @VCCA——它有 50 V 耐压，但这条轨谁都没定价）；R2 报 U8
   （AMS1117-3.3）压差 **8.7 V** 的 INFO 测量行 + 一条 `intent-missing`（VCC 的
   `continuousCurrent` 没声明）。**该板 C4 不进名单**：它两脚落在 DRV1 的 `NET2`/`NET3`，
   合同与图上的推断都不把那里当轨——R1 比的是「电容 vs **轨**」，不在轨上的电容没有轨压可比
   （任务书举例的 C 系名单来自真机工程的编号，本导出档 49 颗件的编号与之不同，实测名单以导出
   档为准）。
