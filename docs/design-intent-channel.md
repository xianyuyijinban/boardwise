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
| A3 | 架构自洽检查器 | 信号链闭合规则（采样链必须有偏置/参考、开漏必须有上拉、单端 ADC 不许直吃双极性信号……第一批 5–8 条，全部来自真案例）；**分级框架**：违反 `user_stated` = ERROR、违反 `ai_asserted`/`verified_recipe` = WARN、无合同零移动、结构性闭合直接 WARN | **A3a/A3b 均已落地，093/094**，见 `tests/test_093_arch_closure.py`、`tests/test_094_sense_bias.py` 与 §八/§九；F2（nFAULT 无上拉）、F3（NRST 裸奔）由规则复现，F1（采样链偏置不闭合）进 A3b：偏置**算术**判定 + 合同 `closure: "waived"` 豁免通道，且合同接进 `draw/edit apply` 的 findings 走查 |
| A4 | 绘制侧 | 语法绑定消费 blocks/decisions（TVS/bulk 角色、支路顺序、模块清单由 intent 推出） | **支路顺序部分已落地（095：power-entry 首吃）**——`branchOrder` > intent > 位号序三来源，冲突并列双源原文拒绝，`dc.compile(..., intent=None)` 可选缝 + CLI `draw compile/plan --intent PATH`；**未落地**：模块清单与 flow 由 blocks 推出的提案器（见下） |

## 四、通往「毕设水平」的全程路线（A 主线之后的 backlog，记档）

1. 页级两缺陷修复（宽轨 mainPath、锚点吸附）——088 §七已钉实测。**已落地，096**（见
   `tasks/096-page-two-defects.md`；判据单一出处 `core.presentationspec.main_path_wire`，
   锚点吸附改朝页内）。同批实测出的第三条**也已落地（097）**：`_annotation_allowance`
   横向估短（只数网名、不数器件自己的位号/值文字），见 `tasks/097-annotation-allowance.md`
   与 `evidence/097/`——096 那次靠吸附的 4 单位增量盖住属运气，097 把两项分量都量准，
   落格点的位移不再需要吸附补位。
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

## 八、A3a 落地记录（093 批，见 `tests/test_093_arch_closure.py`）

A 主线走到这里，intent 第一次**进评级**（090/091/092 都只让它说话，不动严重度）。052 §4 的
红线因此第一次需要成文，就是这一张表——它写在 `rules/archclosure.py` 的模块 docstring 里，
代码里对应 `INTENT_GRADES` + `STRUCTURAL_GRADE`/`MEASUREMENT_GRADE`：

| 情况 | 级别 | 为什么 |
|---|---|---|
| 违反 **`user_stated`** intent（工程师自己声明的架构被图纸违反） | **ERROR** | 与一个人说过的话直接矛盾；`edit/draw apply` 的 findings 闸下必拦，`--force` 也放行不了 |
| 违反 **`verified_recipe`** | **WARN** | 别人验证过的配方，**不是工程师本人声明**（本批的表格只点名两档，中间档的归属是本批的决定，理由与改法都写在表下面） |
| 违反 **`ai_asserted`** intent（AI 草稿与图纸不一致） | **WARN** | 052 §4：猜出来的需求只能当提示，不能当判违规的依据；行里带「确认前不要照改」 |
| 无 intent | **不查，零移动** | 无合同读数逐字节不变（A1/A2 口径延续） |
| 不依赖 intent 的**结构性**闭合 | 违反 **WARN** / 闭合 **INFO 测量行** | 要求来自货架或网表本身（开漏上拉、NRST），有出处、点名、给修法；闭合时出测量行——「查过且没事」与「根本没看」必须能分辨（092 的纪律） |

1. **R1 `arch-rail-voltage-clash`**（A2b 遗留③，依赖合同）：合同的
   `requirements.rails[net=…].targetVoltage` vs 图上自己的判定（`infer_net_domains`）。
   **两个来源的原始字段与值都进消息**（「谁错由人裁」——091 A2a 对 MPN/Value 矛盾的同一条
   拒绝）。图上判不出这条轨的电压 → 不查；合同没声明该槽 → 不查（那是 092 那条规则的
   `intent-missing`）。进 `INTENT_RULES` 与 `NET_MEMBERSHIP_RULES`。
2. **R2 `arch-opendrain-pullup`**（F2 nFAULT 案，结构性）：货架 `pull_required` 里**带
   `open_drain: true` 标记**的脚——所在网成员里有电阻跨到 power-class 轨（网名报电压，或图
   上由 LDO 输出定价）= 闭合 INFO；没有 = WARN（点名脚、网、手册页、修法 10k 上拉）。合同
   `decisions[]` 里 `user_stated` 声明「该脚用 MCU 内部上拉」也判闭合（INFO，注明依据=设计
   决策）；草稿声明不算闭合，但会在 WARN 里被点名（052 §4）。**标记是必要的**：同一个 fact
   kind 也承载连接器 CC 脚的**下拉到地**要求（`conn-usb-cc-pulldown` 的题目），按「所有
   pull_required」判会把每个设计正确的 Type-C 座报成缺上拉。**该规则的 subject 不限位号
   前缀**——`DRV1` 不是 `U<数字>`，而放宽 `IC_PATTERN`（会让这颗件进所有 facts 规则）明确
   不在本批。
3. **R3 `arch-nrst-closure`**（F3 案，结构性）：控制器（`core.architecture.controller_evidence`，
   即货架 `category: ic.mcu` 或符号里 ≥4 个 `P<端口><数字>` 引脚——**复用架构走查的既有识别**，
   不写第二个识别器）的 NRST/RESET 脚（按**引脚名**分段认，`PG10-NRST` 命中）所在网：成员数
   = 1（单成员网：无电容/无按键/无测试点/无编程器引出，图纸里那条网络标签底下什么都没有）→
   WARN；脚不接任何网 → 同样 WARN；成员 > 1 → INFO 测量行。
4. **数据侧（issue #56 的落地）**：`blocklib/parts.corrections.json` 的 `curated` 段给
   `C92482`（DRV8313PWPR）补 `category: ic.motor-driver`（`CATEGORY_VOCABULARY` 同步扩一档）
   + facts——nFAULT(pin18) 的 `pull_required` 标 `open_drain: true`（手册 p.3：open-drain
   output requires an external pullup）、VM(pin4/11) 各 0.1 µF 的 `required_caps`（同页；喂
   decap 既有机制）。`parts.json` 由同一 payload 就地更新，**货架仍是「源 + sidecar」的函数**
   （`tests/test_harvest.py` 的复现测试是这条的看门人）。工具侧的 `IC_PATTERN` 放宽不在本批。
5. **联动（不改代码）**：自洽 ERROR 在 `edit/draw apply` 的 findings 闸下被 #55 的分级必拦
   （ERROR 必拦、`--force` 不豁免 WARN 之外的东西 ⇒ exit 2）。**实测的边界**：apply 的
   `_baseline_findings` 走的是 `run_review(model)`（**不带合同**），所以今天真能到那道闸上的
   是 R2/R3 的结构性 WARN；合同驱动的 R1 ERROR 要等「把合同接进 apply 走查」那一批
   （093 §〇 明确「不改代码」），本批钉的是**分级机制**本身。
6. **ctrl FOC 实测（导出 + shipped 合同）**：R2 报 `DRV1 pin18`（FAULT#）在 `NFAULT`
   （成员 U1.34 / DRV1.18）无上拉 → WARN；R3 报 `U1 pin7`（PG10-NRST）在单成员网 `NRST`
   → WARN；**R1 不报**——shipped 合同的 rails 一个 `targetVoltage` 都没填（阴性对照：把
   `+12V` 按图上自己的判定填成 `12V` 后仍不报）。checkup 的 verdict/退出码/schema `/6`
   一个字没动。

## 九、A3b 落地记录（094 批，见 `tests/test_094_sense_bias.py`）

A3a 让 intent 第一次进评级，但它带来的三条规则读的都是**图纸**（异压、上拉、复位脚成员数）。
A3b 补上这条通道存在的理由本身——**F1 的采样链偏置**——并第一次让规则做**算术**，同时给合同
一个「明示放弃」的出口，最后把合同接进 `apply` 的 findings 走查（A3a §八.5 留的那半条）。

1. **规则 `arch-sense-bias-closure`**（`rules/archclosure.py`，进 `BUILTIN_RULES` +
   `INTENT_RULES` + `NET_MEMBERSHIP_RULES`）。主题 = 合同声明 `signals[].kind =
   "current-sense"` 且 `polarity = "bidirectional"`（或该条 `requires` 里点名 bias 类 token）
   的链。判定**按算术**，不按「有没有画东西」：`R_sense` = 网上到地的那只电阻（分流），
   偏置源 `R_th = (R_up‖R_dn) + Rs`（分压中点经串阻；串阻直接接轨时轨内阻记 0，
   `R_th = Rs`），`V_err = V_bias × R_sense/(R_th + R_sense)`（F1 原式，`V_bias` 由分压比
   × 轨压算出，轨压取自 `infer_net_domains`）。五档：

   | 档 | 条件 | 级别 |
   |---|---|---|
   | 豁免 | 合同 `closure: "waived"` | `user_stated` **INFO**（引 `decisions[]` 的 rationale）/ 更弱档 **WARN**（草稿不能自己豁免自己） |
   | 无偏置网络 | 网上没有任何通往分压中点或 power-class 轨的电阻路径 | 按 `intent_grade()`（`user_stated` = **ERROR**） |
   | 弱偏置 | `R_th ≥ R_sense` | 按 `intent_grade()`（F1 实测：**ERROR**） |
   | 边际 | `R_sense/10 < R_th < R_sense` | **WARN**（比值存疑，数字随行） |
   | 闭合 | `R_th ≤ R_sense/10`，或网里有**运放输出脚**直连 | **INFO 测量行**（报 R_th 与 V_err） |

   **「1/10」是本规则自声明的判据，不是标准**——写在类 docstring 与 `BIAS_CLOSURE_RATIO`
   里，每一行都把判据与它被套用的数字一起打印，读者可以反对那个数而不是反对一个藏在表达式
   里的阈值。**两处不猜**：网上有外来电阻但远端网既不是可定价的 power-class 轨、也不是
   「一上一下」的分压中点 ⇒ UNKNOWN + 点名去哪补；网上没有到地电阻 ⇒ 「R_sense 读不出来」
   UNKNOWN。**一处读不出**：网里有运放但输出脚认不出（符号引脚名无 `OUT` 段、货架条目也没记
   `facts.output_pins`）⇒ UNKNOWN 并点名写进 `parts.corrections.json` 哪里。

2. **合同的豁免通道（本批的合同侧小增量）**：`requirements.signals[].closure`，可选、缺省
   **不写出**（schema 封闭不变）；唯二取值之一 `"waived"` 是「工程师明示放弃闭合」。未知
   token 按路径拒收（`requirements.signals[0].closure`）——一个没人读的声明就是没人查的
   事实。case 文件 `blocklib/intents/robot-ctrl-foc.intent.json` 的 `U+`/`W+` 按 R4 决策补
   `closure: "waived"`。**A1 的 `closure-undeclared` 提示仍然照旧提问**：它问的是
   `requires: ["bias-reference"]` 这个槽，而本批的 waiver 是另一条通道（改提示会移动
   `test_090` 已钉的验收，留给后续批裁决）。

3. **F1 算术逐数对照**（合成模型：3.3V 轨经 1k/1k 分压出 1.65V，10k 串到 0.1Ω 采样节点）：

   | 量 | 报告 F1 原文 | 规则消息 |
   |---|---|---|
   | 分压内阻 | 500Ω | `R_th = (R_up‖R_dn) + Rs = 500Ω + 10000Ω` |
   | 串阻 | 10kΩ | `+ 10000Ω = 10500Ω` |
   | 采样电阻 | 0.1Ω | `R_sense = 0.1Ω`（R4 → GND） |
   | 偏置失误电压 | `1.65V × 0.1Ω/(500 + 10k + 0.1) ≈ 15.7µV` | `1.65V × 0.1Ω/(10500Ω + 0.1Ω) ≈ 15.7µV` |
   | 想要 | 1.65V | `差约 5 个数量级，而想要的是 1.65V` |

4. **ctrl FOC 实测（导出 + shipped 合同）**：规则报 `U+`/`W+` 两行 **INFO 豁免**，引用
   `decisions[subject='R4']` 的 decision 与 rationale 原文（`W+` 没有自己的 decision，行里
   照实说「没有为这条链背书的条目」）；**撤掉** waived 的变体合同 → 同两行变 **ERROR 无偏置
   网络**（导出档 `U+` 只有 3 成员、无 VCC/2 网 = A3a §8.1 的「完全无偏置」形状）。真机现状
   （有偏置但源阻抗不闭合）由合成模型覆盖，见上表的逐数对照。

5. **合同进 `apply` 走查**（A3a §八.5 的遗留）。`_baseline_findings(model, intent=…)` 多一个
   携带合同的参数，**基线两侧同一个合同**：`draw plan` / `edit plan` 记基线那一步与
   `draw apply` / `edit apply` 写后重读都解析
   `<boardwise home>/design-intent/<projectUuid>.json`（apply 家族没有 `--intent` flag；
   显式 flag 缺失时是 note + 退回旧读数，不崩）。**实测**：一次把闭环（运放输出直连）改成
   开环的落图 → 写后重读新增 `arch-sense-bias-closure|ERROR|…|U+` → **exit 2、`sch.doc.save`
   没被调用**，`--force` 仍 exit 2 且 `forcedWarns` 为空；把合同降成 `ai_asserted` 后同一场景
   变成 WARN → 不给 `--force` exit 2，给了才放行并在 `forcedWarns` 与 notes 里点名。
   **口径边界（诚实记录）**：闸比的是「**新增**」签名（036 规则 / #55 裁决 B），所以**写之前
   板上就有的**自洽 ERROR 不算新增、不拦这次写——本批钉的是「写造成的违规必拦」，不是「带病
   板一律不许写」。无合同的项目读数逐字节不变（`_baseline_findings(model) ==
   _baseline_findings(model, intent=None)` 钉死）。

6. **checkup 的退出码移动了一次，且是应该的**：`test_090` 的手写小合同把 `U+` 声明成
   `user_stated` 双向电流采样，而 ROBOT 导出上它没有偏置——新规则报出该板唯一的 **ERROR**，
   退出码从 3（读数不完整）变 1（有错）。这正是「合同发现缺陷要动 verdict」的字面含义，三处
   断言随之改成测量值并写明原因（见交卷报告的碰撞清单）。

## 十、A4 落地记录（095 批，见 `tests/test_095_intent_driven_order.py`）

A1–A3 让 intent 成了**审查**的事实源；A4 让它成为**绘制**的事实源。本批只吃一条事实——
「哪条支路要贴入口」——理由很实在：088b 的 R12 已经把这句话在**每份** PresentationSpec 里
声明了一遍（`modules[].branchOrder`），而合同的 `decisions[]` 早就说过一次（「D1 是 TVS，
贴入口」）。事实说一次，两侧共用；出处（provenance + 条目 + 合同路径）一路进绑定 evidence。

1. **顺序的三来源**（`engines/grammar/power_entry.py`）：`branchOrder`（图纸自己的声明，
   仍是第一优先）> intent（缺省声明时）> 位号序（两者都没说）。**每份图纸只多一层信息，不
   多一套规则**：合同推出顺序时发的还是 088b 那一条 `adjacent` 链，只是 reason 的开头一句
   换成「the design intent states …」——两种来源发同一个 kind、走同一套检查。
2. **读什么、怎么读**：`decisions[subject=<支路>]` 的 prose（`decision` / `rationale`）或
   `blocks[].kind`（`parts` 里点名那条支路）里出现 `tvs` / `clamp`·`钳位` / `泄放` →
   该支路排最靠入口，其余按位号序跟后。token 表**故意短**：`浪涌`/`surge` 也会出现在
   「输入大电容提供浪涌电流」这种非泄放句子里，`diode` 也包含整流管——合同写的是散文，
   语法只读已写明的词，并把那一条原文抄进 evidence 让人自己判断。合同里关于**别的模块**
   支路的条目在这里不读（088 §一.3 的作用域规则：那是那个模块自己的事）。
3. **冲突 = 拒绝，并列双源原文，谁错人裁**。声明与合同**都说话且不一致**时（声明的序里
   有非泄放支路站在泄放支路前面）→ `circuit-invalid`，detail 同时给出声明的列表原文与
   合同的条目原文（含 provenance 与文件），action 给出两种修法。**判据是「claim 这个集合
   有没有被违反」，不是排列**：合同没有说两条泄放类支路之间谁更靠前，那一段是语法自己的
   位号 tie-break，拿它拒绝就是假警报（R2 的成本与误删同价）。
4. **草稿照走但标注**（052 §4）：claim 是 `ai_asserted` 时顺序照执行，但绑定 evidence 写
   `draft (ai_asserted)`，且该支路绑定的 `provenance=` 行随之落到 `ai_asserted`——图纸
   只有它最弱的事实那么可靠。`user_stated` 落在 `verified_recipe` 电路上同理（不改强）。
5. **缝**：`drawcompiler.compile(..., intent=None)` 可选、默认 None（`None` = 与 088/088b
   逐字节同一张图）；合同同时进**两次语法读**——出约束的绑定，与独立检查器
   (`check_grammar`) 的重绑。**实测**：`adjacent` 在成品图上的判据是「横向对齐、纵向错开」
   （`_relation_holds`），与谁更靠入口**无关**（088b 选它的理由），所以「顺序画反了」是
   编译器 rank 走查拦下的，检查器拦不住；检查器读合同的可分辨证据是「声明被合同否掉时它
   报 `grammar-binding-unplaced`」，不带合同读同一张图则零 finding。
6. **一处顺手补的洞**：语法的 provenance 表（`engines/grammar/base.py::_PROVENANCE_RANK`）
   原本不认 `user_stated`——090 A1 把它定为**同一档的另一种拼法**（工程师档），但语法层
   没有条目，因为在此之前没有任何能进语法的文档能拼出这个词。合同是本批第一个。
   实测后果：`weakest_provenance("verified_recipe", "user_stated")` 先把它判成 `unstated`，
   下一句取表就 `KeyError`。补上该键（档位与 `core/circuitspec._PROVENANCE_RANK` 一致，
   两表并存的原因见该处注释：空值的读法不同），新测试钉死三档。
7. **零移动**（申报制证据，`evidence/095/`）：088 的 14 张 + 088b 的 18 张离线预览逐字节
   不动（`git archive HEAD` 树 vs 工作树各跑一遍生成器，逐文件 `cmp`），两份声明版/缺省版
   的几何 sha256 在 HEAD 树与工作树上逐字相同；`intent=None` 与不传参的 `GrammarResult`
   逐字节同一份（测试内断言）。
8. **未落地（归后续批，A4 的另一半）**：① `blocks[]` 推**模块清单**、`flow` 与
   bulk/TVS 角色分工的**提案器**（把 intent 变成一份 presentation 草稿，而不是让语法逐条
   读合同）；② **页级**（057 的 `pagecompiler`）不读合同——页里的模块各自编译，模块边界
   与页级 flow 由页面文档说了算，本批不动；CLI 在页路径上给了 `--intent` 会**明说**它没被
   读（R3 纪律：不许静默忽略）；③ CLI 编译侧只认**显式** `--intent PATH`，用户级默认落点
   `<home>/design-intent/<projectUuid>.json` 够不着——编译发生在读工程之前，那时没有 uuid
   （`draw plan --page` 的 projectUuid 是编译之后才知道的）。要把默认落点接上，得把编译
   挪到 live context 之后，那是改 054 流程的活，留记录。
