# 098 — 第五种画法语法 `ic-periphery`（离线半）+ CH340 样板验收

岳 2026-10-03 拍板：CH340 走**新语法**路线（不做页级凑合）。本批是 088 同构的三段式
离线半：**语法 + 编译器接入 + 场景 + SVG 预览**；真机落图归 099。
**先读**：`src/boardwise/engines/grammar/power_entry.py`（最近邻实现——本语法是它的泛化：
核心从「入口连接器」变成「任意 IC」，支路从「全跨两轨」变成「各挂各脚」）、
`tasks/088-power-entry-grammar.md`（三段式流程与验收纪律）、052 §五（画法承诺的写法）。

## 一、形状与角色（岳样板 = CH340 模块）

一块 CH340：核心 IC（U1, SOP-16）+ 晶振 X1 跨 XI/XO 两脚 + 负载电容 C1/C2
（XI→GND、XO→GND）+ 去耦 C3（VCC→GND 贴电源脚）+ V3 电容 C4（V3→GND）+
轨 VCC/GND + 跨模块信号 TXD/RXD/D+/D−（出网络标签）。

**角色表 `("core", "bridge", "shunt", "rail", "gnd")`**：

| 角色 | 判据（结构性，不看位号/值/封装——053 §6 红线不动） |
|---|---|
| `core` | 模块内**唯一**脚数 > 2 且严格最多的件 → 结构认出；并列/无 → `facts-missing` 点名声明处 |
| `bridge` | 跨**核心两个脚**的两脚件（晶振跨 XI/XO） |
| `shunt` | 跨**核心一脚网 → rail/gnd** 的两脚件（负载电容/去耦/V3 电容） |
| `rail`/`gnd` | 按 class（power/gnd），措辞照 power-entry 同族 |

**唯一不可推导的事实 = 谁是核心**（power-entry 的 entry 教训同款：结构认不出就给
声明通道+点名拒绝，不许猜）。三通道按 A4 的三来源纪律：
`modules[].core`（新可选键，图纸自己的声明）> intent `blocks[].parts` 里脚数 >2 者
（合同；A4 的缝）> 结构认（唯一严格最多脚）——三者冲突 → 拒绝并列原文（谁错人裁）。

**簇（cluster）是结构可推的**：bridge 与「挂在它两网之一到 rail/gnd」的 shunt 天然
成簇（晶振+两颗负载电容）——按网交集分组，不读任何名字。

## 二、约束与义务（词汇表不新增 kind，能用旧的用旧的）

- `near`（peripheral, core）：挂脚件贴着它的核心读，不跨模块边界。
- 簇内相邻：bridge 与它的 shunt 相邻（`adjacent`，088b 实测过的那个 kind）。
- `left-of`/`right-of` 只用于跨模块信号标签的**朝向**（sidePreferences 驱动：
  TX/RX 朝 MCU 侧、D+/D− 朝 USB 侧——声明侧，语法不发明方向）。
- 义务：`owned-branch`（每个挂脚件读起来属于这个核心）+ `uniform-gnd`。
- **轨不承诺实体线**（与 power-entry 的差别：本语法里轨是供电引用不是主干画法——
  旗/标签照 069 既有规则走，页面级再谈实体）。

## 三、拒绝措辞（钉测试）

- 核心并列多脚件/无多脚件且无声明 → `facts-missing`，点名「写进 `modules[].core`
  （或 intent `blocks[]`）」；
- 声明的 `core` 不存在/不是多脚件 → `circuit-invalid` 点名它实际是什么；
- 模块里一颗两脚件不碰任何核心脚网 → `circuit-invalid` 点名它实际连着谁
  （它不是这个核心的外围——别模块的事别塞这里）；
- 三来源给的核心不一致 → 拒绝并列三处原文。

## 四、场景（进 `tests/` 新文件；SVG 预览落 `outputs/098_preview/`）

1. **CH340 样板**：晶振簇（bridge+两 shunt 相邻、贴 XI/XO 侧）+ 去耦贴 VCC 脚 +
   V3 电容贴 V3 脚 + 四条信号标签朝向正确 + 可读性零硬违规。
2. 镜像（sidePreferences 换侧 → 标签朝向与簇位置同步镜像）。
3. 最小（core + 1 去耦）。
4. 多簇（两个 bridge 各自带 shunt——运放级形状预演）。
5. 核心歧义（两颗多脚件、无声明）→ facts-missing 点名声明处。
6. 不碰核心网的两脚件混进模块 → circuit-invalid 点名。
7. 长文字（长值/长网名）不压线不穿体。
8. 窄区域 → layout-unsat 如实拒绝。
9. 页级集成：CH340 模块 + USB 座模块同页，D+/D− 跨模块走标签/线（069 v3 不回归）。
10. 核心来自 intent（不给 `modules[].core` 给合同 blocks[]）→ 绑定成功且 evidence
    带合同出处。

**既有场景零移动是硬约束**（053b 21 / 056 18 / 088 14 / 088b 18 申报制证据）。

## 五、注册与文档

- 注册面：`engines/grammar/__init__.py`（NAMES/_CLASSES/ROLES_BY_GRAMMAR）+
  `core/presentationspec.py` 的 GRAMMARS 字面量 + `modules[].core` 可选键
  （封闭 schema 加键纪律：可选、缺省不写出、旧文档逐字节、spec_version 不升）。
- 镜像测试 `tests/test_053b_grammar.py` 的注册清单断言加第五个名（唯一既定断言改动）。
- **语法表禁场景常量**（位号/值/封装/网名一个都不许——照 088 的 AST 钉法加测试）。
- `docs/schematic-conventions.md` 新增条目（ic-periphery 的形状承诺与三来源）；
  `docs/architecture.md` 同步；`docs/design-intent-channel.md` §四.2/3  backlog 更新。

## 六、验收与纪律（同 088，逐项交证据）

- 全量 pytest 绿（基线 **3162**）；新测试进 `tests/test_098_ic_periphery.py`；
  预览两遍 byte-identical；变异 ≥2 组（核心三来源调解 + 簇结构判据各至少一组），
  cp+sha256 还原。
- **删除一律进回收站（红线#4，零删除才许交卷）**；纯离线、不动 git、不写 PROGRESS。
- 交卷：改动清单/角色绑定判据实测/每场景候选数与拒绝分类/预览清单/零移动证据/
  变异记录/全量结果行/自决项/遗留项（099 真机半的输入素材）。
