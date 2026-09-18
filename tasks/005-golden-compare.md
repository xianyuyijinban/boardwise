# 任务 005：黄金板比对——"AI 画的对不对"的裁判

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`docs/format-epro2.md`（§8-§12）、`src/boardwise/parsers/epru.py`、`src/boardwise/parsers/epro2_model.py`、`src/boardwise/core/model.py`、现有 CLI 注册方式。
> 背景：用户（硬件工程师）已提供 CH340G USB 转串口板的**不加密 `.epro2` 导出**作为黄金夹具 `tests/fixtures/ch340_golden.epro2`（由岳翔宇手工验证过正确性）。本任务造裁判：候选设计与黄金板逐 pin 比对，输出人能读的差异报告。这是后续"AI 画板 → 自动验收"闭环的地基。

## 夹具实测（2026-09-13 DeepSeek 侦察，直接信任）与前置工作项 0

**夹具验证已通过**：ZIP 完整、未加密明文 `.epru`；`SCH ×1 + SCH_PAGE ×1 + SYMBOL ×29 + FOOTPRINT ×18 + DEVICE ×28`（DEVICE 28/28 带 META，value/lcsc 有数据）。**本工程没有 PCB 段**——而现有 `build_design_model` 只认 PCB/FOOTPRINT/DEVICE（001/002 的范围），对它返回 0 器件。所以本任务的**工作项 0**是先造 SCH 侧模型构建器：

**0. `build_schematic_model()`（新代码，建议进 `parsers/epro2_model.py` 或新模块）**：产出与 `build_design_model` **同一个 `DesignModel` 形状**（器件 designator/value/footprint/lcsc + 逐 pin → net）——一个模型、两个构建器（文件侧本任务；桥 readback 侧归任务 006）、一个比对器。
   - 侦察已固定的 SCH_PAGE 结构：`COMPONENT ×35`（partId + x/y/rotation/mirror）、`ATTR ×525`（parentId 关联，含 Designator/Value/Footprint）、`WIRE ×33`（**几何不在头记录**，跟在后面的 `LINE` 段里，startX/Y→endX/Y，`lineGroup` 分组同一导线）、`TEXT ×1`。
   - 第一步先**穷举 SCH_PAGE/SCH/SYMBOL 三类文档的全部记录类型**（找 NETLABEL/网络旗标/电源符号记录），把结果记进 `docs/format-epro2.md` 新增的 SCH 侧章节（现有文档只有 PCB 侧，必须补上）。
   - 连通性推导：并查集（union-find）合并 ① WIRE 的 LINE 段端点 ② SYMBOL 引脚的绝对坐标（引脚在 SYMBOL 文档的局部坐标，按实例 x/y/rotation/mirror 变换）③ 网络标签（按落点位置附着）④ 电源/地符号（视为全局标签）。浮点坐标匹配用统一容差（建议 0.5 mil 圆整键，注释写明依据）。
   - value/lcsc 经 DEVICE 文档 uuid join（`ATTR key="Device"` → DEVICE uuid → META），与 PCB 侧同款。
   - 测试：黄金夹具 → 模型含 35 器件；U1（CH340G）的 16 个 pin 全部有 net；每个 net 的成员数与人工抽样一致（岳翔宇抽 3 个 net 核对）。

## 比对语义（架构定稿，照此实现）

比对单位是**设计模型**（`DesignModel`，由工作项 0 的 `build_schematic_model` 或 PCB 侧 `build_design_model` 产出），不是几何。规则按严格度分三级：

1. **器件级**：designator 集合差（missing / extra）；共有器件比对 `footprint`、`value`（归一化后）、`lcsc`。
2. **网络级**：net 集合差；每个 net 的成员（designator+pin）集合差。
3. **逐 pin 级**：共有器件的每个 pin → net 映射差异（这是黄金比对的核心，CH340G 的 16 个 pin 一个都不能错）。

归一化规则（写死在实现里，注释说明来源）：

- value：大小写不敏感（`10k` == `10K`）；`10k`/`10K`/`10000` 视为相等（工程记数法解析，单位 Ω/F/H，注意 `472M` 是 4.7nF **不是** 472MΩ——容值 M 后缀歧义按封装语境处理，注释里写明这条坑，解析不了就退化为字符串相等）。
- designator / net 名：大小写敏感，原样比对。
- pin 号：字符串比对（`1` vs `01` 视为不等，原样）。

## 交付物

1. **`src/boardwise/core/compare.py`**：`compare_models(golden, candidate) -> ComparisonReport`。报告结构按上面三级分组，每条差异带：级别、位号/net 名、黄金值、候选值。零差异时报告为空。
2. **CLI**：`boardwise compare <candidate.epro2> [--golden tests/fixtures/ch340_golden.epro2]`。退出码沿用 review 语义：`0` 无差异 / `1` 有差异 / `2` 输入错误。输出人读格式（每行一条差异，按位号排序），结尾一行汇总计数。加 `--json` 开关输出机器读格式（给后续 AI 闭环用）。
3. **测试**：
   - 黄金 vs 黄金 = 0 差异（自反性）。
   - 合成差异：从黄金模型深拷贝后改一处（删一个器件 / 改一个 pin 的 net / 改一个 value），每类都要被正确分级检出。
   - 归一化：`10k` vs `10K` vs `10000` 无差异；`472M 1KV`（电容）vs `472M`（电阻语义）不产生误判（按退化字符串处理）。
   - 加密/坏文件输入 → 退出码 2，不抛栈。
4. **文档**：README 加 `compare` 一节（用途、退出码、示例输出）；`docs/format-epro2.md` 不动。

## 不许动的部分

解析器既有行为（001/002 已验收）；`review` 命令语义；不引入新依赖（值归一化手写，不拉 pint 之类的库）；代码/注释英文；不执行任何 git 命令。

## 验收

- 全测试绿（含上述用例）。
- 黄金自反比对输出 0 差异、退出码 0。
- 岳翔宇真机抽样：报告里 CH340G 的 16 pin 映射与原理图一致（他肉眼抽 3 个 pin 核对）。
- `--json` 输出能被 `python -m json.tool` 解析。

---

## 完成记录（2026-09-13 17:10，执行者：WorkBuddy/Claude）

### 范围修正（如实记录）

比对单位是 `build_design_model` 的产物——但黄金板是**纯原理图工程**（无 PCB），既有解析器
（001/002，只认 PCB/FOOTPRINT/DEVICE）对它返回空模型。逐 pin 比对的前提因此是**原理图侧
设计模型**，本任务连带实现了它（否则"0 差异"毫无意义）：

- **新增 `src/boardwise/parsers/schematic.py`**：SCH_PAGE + SYMBOL → `DesignModel`。
  语义全部实测自黄金夹具（记录在模块 docstring）：组件 = `COMPONENT` + 紧随的 ATTR 流
  （`Symbol`/`Device`/`Designator`/`Value`，关联纯靠流邻接）；引脚 = SYMBOL 的 `PIN` 记录
  （(x,y) 即连接点），**引脚号按流顺序配对**——`Pin Number` 的 `parentId`（`e<z>`）在导出
  重序列化后不可靠（电阻符号实测 e17/e29 对不上 z=2/6）；导线 = `WIRE` 头 + 同 `lineGroup`
  的 `LINE` 段；网络名 = `NET` ATTR（挂 lineGroup）> 电源符号/独立电源旗标的
  `Global Net Name` > 确定性兜底 `NET1..N`（按簇的规范排序，不依赖编辑器自动命名）；
  `NO_CONNECT` 的 parent = `<实例容器id>-e<pin元素id>`（容器 id = 该实例 ATTR 共用的
  parentId）。连通性用并查集（线段端点精确重合 + 引脚点重合）。
  **既有解析器行为零改动**（独立模块、独立记录筛选，001/002 验收不受影响）。

### 交付物对照

| 任务书要求 | 结果 |
|---|---|
| `core/compare.py` `compare_models() -> ComparisonReport` | ✅ 三级分组，每条差异带级别/主体/详情/双侧值 |
| CLI `boardwise compare <candidate> [--golden] [--json]` | ✅ 注册进 `cli.py`，退出码 0/1/2 |
| 黄金自反 = 0 差异、退出码 0 | ✅ 17 器件 22 网络，"no differences"，exit 0 |
| 合成差异分级检出 | ✅ 删器件/加器件/改 value/改 pin net/改网络名 各有对应用例 |
| 归一化规则 | ✅ `10k`==`10K`==`10000`；`4R7`==`4.7`；`1kΩ`==`1000`；`472M` vs `472M 1KV` 不误判（多词退化字符串）；小写 `m` 歧义拒解析 |
| 坏文件 → 退出码 2 不抛栈 | ✅ 复用加密工程的报错文案（提示重新导出），无 Traceback |
| `--json` 可解析 | ✅ `python -m json.tool` 通过 |
| 测试 | ✅ `tests/test_compare.py` 21 条；全套 **164 Python**（143+21）绿 |
| 文档 | ✅ README 中英双节各加 `compare` 一节 |

### 黄金板实测解析结果（岳翔宇抽样核对用）

17 器件：U1(CH340G)、U3、U5、USB1、X1、H1、LED1、C1/C25/C3/C4/C5/C6/C7/C9、R24/R27。
U1 逐 pin：1=GND、2=RX、3=TX、4=NET1(V3+C1)、5=D+、6=D-、7=NET3(XI+X1.1+C3.2)、
8=NET2(XO+X1.3+C25.1)、9–15=NC（原理图 NO_CONNECT 标记）、16=VCC。GND 网含
C1.2/C25.2/C3.1/X1.2/X1.4/H1.3；+5V 含 USB1.2/USB1.11/C4.2。**待岳翔宇肉眼抽 3 个 pin 核对**。

> **✅ 岳翔宇核对通过（2026-09-13 17:36）**——U1 逐 pin 映射与原理图一致，本任务验收全项闭环。

---

## 验收戳（2026-09-13 17:50，Kimi，独立复验）

状态：**ACCEPTED**。复验：全量 `pytest` **164 passed**（7.96s）；黄金自反比对 `boardwise compare ch340_golden.epro2 --golden ch340_golden.epro2` → 17 器件 / 22 网络、"no differences"、**exit 0**；岳翔宇肉眼抽样已签字（上记）。
裁判上线，006 的验收闸门就位。
