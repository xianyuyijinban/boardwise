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
| A2 | 审查规则（params/decap） | 冲突时按 intent 给**双向**修复建议（改值 or 重选料），rail 声明进 decap/额定核算 | 发现→修复依据 |
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
