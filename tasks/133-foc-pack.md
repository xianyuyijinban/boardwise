# 133 / 阶段 D·FOC（功率驱动）规则包 —— 岳的本行，权重最高

> 路线图：`tasks/122-pcb-review-roadmap.md` 模块特定层第 3 条。
> 设计依据文档：**TI SLVA959B**（电机驱动器 PCB 布局指南，消化表在本任务书末）。
> 岳的裁定（2026-10-08）：②模数地直接分割+单颗 0R 单点接地（0R 近功率电解电容，
> 用户工程约定非 TI 引用）；③多层板回流按投影分析。
> 验收板：毕设FOC 1.0.0（岳亲验）→ ROBOT ctrl FOC → 高速电机控制器。
> 全部规则 **INFO 出数起步**（同电源包/MCU 包纪律），阈值等岳盲审后再定。

## 棒序（每棒独立可验）

### 133a 三个新几何原语（地基）

1. **`via_geometry`**：过孔全属性读出（中心/孔径/盘径/所在层对）—— ViaGeometry 已有
   center/diameters，缺「落在哪个焊盘/区域内」「连接哪几层」的查询封装。
2. **`track_corner_angle`**：走线折点转角检测（同网同层相邻段夹角），报告非钝角折点清单。
3. **`return_path_projection`**（纪律 2 核心，本批唯一重原语）：对给定网/走线，
   取其所在层 → 从层叠（read_stackup）找**相邻参考层**（最近的 GND 类铺铜层）→
   把走线投影到该层 → 查投影区域的铺铜覆盖（region_copper，131f 现成）：
   连续=通过、被分割/无铜=出账。**POUR 已入模型（131f），此原语现在可行。**

### 133b 快赢规则五条（原语现成）

| # | 规则 | TI 依据 | 原语 |
|---|---|---|---|
| R16 | 去耦/旁路电容距 IC <0.5cm 且同层、其间无过孔 | §5.3.1 | component_distance + effective_layer_ids（过孔部分用 via_geometry） |
| R31 | ≥4 层板必须有一整层连续地平面 | §1.2 | read_stackup + pour_connectivity（该层单一地岛+面积占比出数） |
| R11 | 栅极走线宽度 ≥20mil（长度出数不判） | §4 首条 | track_width_stats（GHx/GLx 网名识别） |
| R13 | 走线无 90° 直角弯（栅极/开关节点重点） | §4 图 4-3 | track_corner_angle（133a） |
| R20 | 高电流环路面积（母线电容↔高侧↔低侧） | §6.3.2/§1.4 | loop_area 焊盘锚点；**poly/bbox 双口径都出数**（岳的口径裁定未到，不出判定） |

### 133c 地系统规则（岳裁定 ②③ 落地 + TI §1）

| # | 规则 | 依据 |
|---|---|---|
| R1 | 功率地（PGND 类）与逻辑/模拟地（GND/AGND 类）之间**不得有直接铜连接**；各自铺铜成岛、岛数出账 | TI §1.3.1（物理隔离）|
| R1b | 两域若相连：必须经**恰好一颗 0R**（value 判 0R/0Ω），且该 0R ↔ 功率级电解电容（bulk ≥100µF）距离出账；多颗/直接铜连 → 出账 | **岳 2026-10-08 裁定（oracle ruling，非 TI）** |
| R5 | 栅极/开关节点/采样走线的投影层参考完整 | TI §1.2/§1.3.1 + 岳裁定③（return_path_projection，133a） |

### 133d 热设计规则（栅驱 thermal pad）

| # | 规则 | TI 依据 |
|---|---|---|
| R7 | thermal via 直连（非 thermal relief）、不被阻焊覆盖 | §2.4 |
| R8 | thermal via 尺寸（孔 8mil/盘 20mil 量级）+ 落在 thermal pad 投影内成阵列 | §2.5/§2.6 |
| R9 | thermal pad 到大面积平面的连续出口路径 | §2.2 图 2-2 |

### 文档层（不机械判，写进 SOP 给模型读）

R3 星点位置裁定、R23 VDRAIN Kelvin、R25 采样电阻拓扑位置、R12/R22/R33（等 net_class）、
R26/R27/R28 容值、R14 泪滴、R30 载流半边。

## net_class（后续棒，未排）

R12/R22/R33 全卡在「哪条网是噪声/敏感」的分类上。落地方向：**扩 design-intent 契约**
（intent.json 已有 rails/signals，加 netClasses 段）而非新文件——一落地三条 M 升 T。
不开新文件（两份清单必漂移，122 决策 3 同族）。

## TI SLVA959B 消化表（agent-213，2026-10-08）

33 条规则候选全表（R1-R33，含 TI 节号引文与判定形态）在会话记录；要点：
- TI **没有** 0R 单点接地的形式——0R+电解电容位置是岳的工程约定，规则里标 oracle ruling。
- 图 1-4/6-13/7-6 的关键信息在图内标注里（文本抽取不全），需要时走 PDF 渲染截图。
- 现有 8 原语撑不住的缺口清单：return_path_projection / track_to_track_min_distance /
  via_geometry / track_corner_angle / pair_parallelism / net_class；结构性缺口：
  跨网连通图（net-tie 语义）与拓扑位置判据（shunt 在 source 与星点之间——网表属性，几何量不出）。

## 交付纪律

同 131：子代理执行、焦点+全量、变异 ≥2、禁 git 写、禁改 fixtures、回收站、纯离线、
主代理收口。FOC 包全部规则 `source` 写明 TI 节号或「岳 2026-10-08 裁」。
