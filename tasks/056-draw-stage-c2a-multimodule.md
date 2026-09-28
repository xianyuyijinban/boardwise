# 056：画法编译器 阶段 C2a——多模块单页编译（离线）

052 路线阶段 D 的前半（"多模块端口与标签"）；054 阶段 C2 的离线半。
**本批纯离线，不碰编辑器、不碰 connector、不碰 daemon。** 后续 057（C2b，编辑器半）负责：非空页落图、userLock 作 keepout、G4 findings 工程级合并语义、`draw discard`（G5）、CH340G 完整模块集成验收——057 任务书在本批验收后写。

053B 的单模块编译器（`engines/drawcompiler.py`）与可读性检查器（`engines/readability.py`）是既有资产；本批在其**上方**加页级层，不重写模块内部机制。

## 一、输入形状（裁决，不许推翻）

**一个 CircuitSpec + 一个 PresentationSpec。** CircuitSpec 保持全局唯一电气事实源（网按名字全局，不存在"跨模块接网声明"——同名即同网）。PresentationSpec 增加**模块分组**：

```jsonc
// PresentationSpec 扩展（示例形状，字段名执行者可微调但语义锁定）
"modules": [
  {
    "name": "pwr",
    "grammarRef": "ldo",
    "parts": ["U1", "C1", "C2"],        // CircuitSpec parts 的子集
    "presentation": { /* 该模块自己的 sidePreferences 等覆盖，可空 */ }
  },
  { "name": "sense", "grammarRef": "divider", "parts": ["R1", "R2"] }
],
"flow": [["pwr", "sense"]],              // 模块级主流向边（软指标，非硬约束）
"page": { "box": [0, 0, 800, 600] }      // 或沿用既有 pageBox 字段
```

- 每个 part 必须恰好属于一个模块；漏分/重分 → circuit-invalid 点名。
- 模块内部的编译**完全复用**单模块机制（文法绑定 → 语义布局 → 几何布局 → 布线 → 检查），输出是带模块原点的子 LayoutPlan。
- 共享网：两个模块各自含有同一名称的网成员，该网即跨模块网；编译器从 CircuitSpec **推导**共享网清单，不接受用户另行声明（声明会撒谎，推导不会）。

## 二、页级放置与跨模块连接

- **页级放置**：模块外接框（含文字余量，由模块内编译实测给出）作为刚体，在 page.box 内排布。候选 = 满足 flow 拓扑序的排列子集（flow 给出偏序，不做全排列爆炸；无 flow 边时按模块名排序兜底，确定性第一）。网格对齐，模块间距 ≥ 页级常量（进 LayoutPlan schema 注释，不许魔法数）。
- **labelPolicy 真启用**（053 §七词汇表已定义，本批是首次有跨模块网可裁）：
  - `local`：恒 `wire`（模块内局部拓扑直连义务，既有行为不动）。
  - `crossModule`：默认 `label`——每个模块在自己的边界内为该共享网放本网旗标/标签（同名网由编辑器工程级合并，这正是 G4 的语义地基）；presentation 把某条 flow 边标为 `main-path` 且两模块相邻时允许 `wire`（页级布线器直连两模块的端口点）。
  - `highFanout`：扇出 ≥ budget 的网（GND 类）恒旗标，**禁止**长成跨页级大线树。
- **页级布线器**（只在 crossModule=wire 的边上工作）：端口点 = 模块内该共享网已放置的引脚尖端或旗标点；Dijkstra 网格寻路可复用模块内实现，障碍 = **所有模块外接框 + 所有文字 bbox**；穿过任何模块外接框即非法（外来 body，不管是不是自己的网）。
- **候选与排序**：页级候选同样 3–8 个几何哈希去重，排序沿用分层字典序（合法性 → 电路表达 → 可读性 → 紧凑），**永不求和**；页级新增软指标（跨模块线长、backflow 长度、标签/线一致性）进对应层，不进总分。

## 三、可读性检查器扩展（页级硬约束）

`readability.check` 加页级域（既有九条模块内硬约束逐条不动）：

1. 跨模块线不穿任何模块外接框（含放置它的那对模块——绕行义务在线不在框）。
2. 模块外接框两两不重叠，且间距 ≥ 页级常量。
3. 文字零重叠扩展到全页（模块间文字互不压、不压外模块 body）。
4. 同名共享网的表达全页一致：同网要么全标签要么全旗标，不许一段线接一半再变标签（网级一致性，wire 边例外只允许整条 flow 边）。
5. flow 是软指标不是硬约束；但 presentation 标了 `main-path` 的 flow 边若被迫用标签（几何无解），报 presentation-poor 并点名，不静默降级。
6. userLock/keepout：页级 keepout 与模块放置冲突 → presentation-poor 点名（056 离线场景喂 keepout 即可，真机 census 归 057）。

## 四、场景（离线 ≥8，分母含拒绝钉死）

| # | 场景 | 期望 |
|---|---|---|
| 1 | LDO + 分压共享 VIN/GND | 出图；GND 全旗标；VIN 默认跨模块标签 |
| 2 | LDO → RC → 分压信号链，flow 三条边 | 出图；主流向总体有序（backflow 进软指标） |
| 3 | 同 2，两条 flow 边标 `main-path` 且模块相邻 → crossModule=wire | 出图；端口直连线不穿框；与场景 2 的标签版几何可区分 |
| 4 | page.box 明显装不下三个模块 | presentation-poor，报实测总尺寸 + enlarge 动作，**不许挤压字/间距** |
| 5 | 某模块内部电路非法（短路/错脚） | circuit-invalid **点名模块**，其余模块不背锅 |
| 6 | 页级 keepout 罩住某模块所有可行位置 | presentation-poor 点名 keepout + move-keep-out 动作 |
| 7 | 高扇出网（GND 横跨全部模块） | 出图；零跨模块 GND 走线，全旗标 |
| 8 | 确定性 | 同输入连编两遍，LayoutPlan 序列化逐字节相同 |

每个出图场景落 SVG 预览（`tools/` 固化脚本，与 053B 同款纪律：import 测试模块场景作唯一事实源）；主代理用浏览器亲核至少两张。

## 五、守卫与复验

- 定向 pytest `--basetemp=.tmp_pt_75`；全量归主代理。eval holdout 59/59 双 1.00 红线（本批纯离线，预期零波及，仍须复跑确认）。
- 变异 ≥2 组（建议：页级"穿框非法"退恒真 → 场景必须红；共享网推导改为读用户声明 → 必须红），cp 备份 + sha256 还原。
- 零 git 操作；不碰 README/PROGRESS/reviewsets/tests/fixtures 既有夹具与 `engines/readability.py` 既有九条硬约束语义、`engines/grammar/*` 词汇表（如需措辞更新先申报）。
- **054 既有 12 场景 9 过 3 拒、78 定向、register 全部保持绿**——页级层不许碰单模块路径的行为（模块内编译复用 = 调用，不是改）。
- dsh 工具面零新增。

## 六、交卷

- 数据流图（模块分组 → 模块内编译 → 页级放置 → 跨模块连接 → 页级检查 → 排序）+ 每场景的编译结果表 + 预览清单。
- 自决项逐条；文件 sha256(12) 前后；定向计数；变异组与还原哈希。
- 给 057 的交接：页级 LayoutPlan schema 增量（模块原点/外接框/端口点/标签表达的序列化形状）、G4 语义地基的实际行为（同名标签在 plan 里如何表达）、发现的编译器缺口。
