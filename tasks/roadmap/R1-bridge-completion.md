# R1 → v0.5.12：桥能力补齐（四件小事，全是真机实测过的缺口）

主题：connector/桥层的四个已知缺口。都是小件，但每一件都有实测证据和明确验收。
估计工作量：1-2 天。

## 背景与证据指针

- connector 是跑在立创编辑器里的扩展：`connector/src/actions.ts`（动作实现）、
  `connector/src/protocol.ts`（动作/错误码表）；Python 侧镜像：
  `src/boardwise/bridge/protocol.py`（ACTIONS 表，两边必须同步）。
- 真机证据惯例：`outputs/178b/`、`outputs/179/` 是上一轮探针的样板（含 live/ 原始读数）。
- 版本号纪律（v0.5.11 起）：connector 版本 = 发布版本。本包做完 connector 应为
  **0.5.12**（`connector/package.json` + `connector/extension.json` 同步改）。

## 任务

### R1-1 `pcb.place_component`（或等价）桥动作 —— 最重要

**缺口**：桥上能读 PCB（`pcb.geometry`/`pcb.readback`）、能改/删图元，
**唯独不能往 PCB 上放封装**。后果：丝印实测的真机演示缺对象（test 工程 PCB1 是空板），
PCB 侧绘制也永远没有下手处。

**做什么**：
1. 侦察宿主 API 能不能往 PCB 放封装（看 `connector/src/actions.ts` 里 pcb 系动作
   怎么调宿主、dsh/eda API 的类型声明里有没有 place 类调用；`docs/bridge.md` 是
   动作文档的权威）。
2. 有 → 新动作 `pcb.place_component`（参数建议：deviceUuid+libraryUuid+x+y+rotation+
   boardUuid 页防串，照 `sch.place_component` 的现有形状）；没有 → 如实写
   「宿主不支持」并把证据落盘，换最小替代（比如能不能复制既有图元）。
3. 真机验证：test 工程 PCB1（空板）放一颗 0603 → `pcb.geometry` 读回它的 bbox →
   删掉复原。**写操作只限 test 工程**。

**验收锚**：新动作进双 protocol 表 + connector 测试；真机证据落 `outputs/R1/live/`；
放-读-删三件套原始读数齐全。

### R1-2 `sys.get_document_source` 省略 `uuid` 时返回带文档身份

**缺口**（179 遗留）：宿主调用只读活动文档，省略 uuid 时返回值里没有「这是哪个文档」
——调用方无法核对读到的是不是自己想要的。

**做什么**：返回 JSON 加 `uuid`/`name`/`type`（从活动文档读，`activeDocument`  helper
已在 actions.ts 里）。纯增量，不改既有键。

**验收锚**：connector 测试 + 真机读回（test 工程）的 uuid 与 `doc.list` 一致。

### R1-3 `doc.rename` 的 `setDocumentSource` 通路侦察

**缺口**（179 遗留）：页改名在宿主 3.2.186 上「接了不做」（已修成 NOT_SUPPORTED 诚实报）。
`docs/pits.md` #47 提到另一条没验过的路：`setDocumentSource`。

**做什么**：侦察（真机 test scratch 页，建→验→删复原）：`setDocumentSource` 改源码里的
页名/文档名是否生效。生效 → `doc.rename` 内部改走这条路（保持列表确认制）；不生效 →
把「此路也不通」钉进 pits #47 与 bridge.md。**不许把 NOT_SUPPORTED 改回静默成功。**

**验收锚**：侦察结论 + 原始读数；若改通路，列表确认制测试必须还在。

### R1-4 Power 旗是否也恒一颗字形（178b 的 Power 半边）

**缺口**：178b 实测 `place_power(kind=Ground, net=X)` 恒落 `Ground-GND`（按 kind 不按 net），
180 把地旗改走按符号放置。**Power 旗（VCC/5V/…）没探过**——如果 `place_power(kind=Power)`
也恒落一颗 `Power-*`，电源轨的旗在画布上也无法分轨。

**做什么**：test scratch 页放三颗轨旗（net=VIN5 / +5V / SEC_12V 之类），读回落的符号名
（178b 的手法，outputs/178b/live/ 是样板）。若也恒一颗 → 把 180 的按符号放置推广到
rail 旗（`cli.py` `_draw_apply_flow` 第 8 段，`ground_device` 改成 `flag_device(net)`，
查 `Power-<net>` 与 `Ground-<net>` 两族）。若按 net 挑 → 如实记录「Power 无恙」。

**验收锚**：uuid 级证据；若推广了 180 路径，`tests/test_180_ground_flag_by_symbol.py`
同型测试加 rail 侧（test_054 的 fake 已有 `ground_symbols`，可加 `power_symbols`）。

## 交卷（写进 PR 描述）

四件各自的结论 + 证据路径；connector 两线绿（npm test + tsc）；pytest 受影响文件绿；
动了 `rules/` 就重钉指纹（本包按设计不该动）；变异验证记录。
