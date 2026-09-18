# 任务 008：生成管线——从 BOM/固件/datasheet 到 0.8 版原理图

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> **总方向（岳翔宇 2026-09-15 定）**：输入 = BOM + 固件代码 + 相关芯片 datasheet PDF；
> 产出 = 0.8 版原理图 + 待裁决开放问题清单；终极验收 = AI 从零生成岳翔宇的 FOC 毕设板原理图
> （三样输入都齐全；他的毕设图纸只作验收参照，不作输入）。
> 前置阅读：`docs/architecture.md`（模型自由度边界 + 三坐标空间）、`docs/schematic-conventions.md`
> （R1~R4 可读性宪法）、`tasks/006b-schematic-readability.md`（三闸门与回放机制）、本文件。

## 架构宪法（不许重开）

1. **块模板 = 微型黄金**。每块自带内部几何（拓扑+走线固化）与对外接口网清单。
   画板 = 摆块 + 块内回放 + 块间只走网络标签（R2）。**没有任何"从零布局"环节暴露给模型。**
2. **模型只做三件事**：选块、填参数、列开放问题。布局/走线/命名/验收全是确定性代码 + 硬闸门。
3. **模板三来源**：教科书经典拓扑（手建）/ datasheet 典型应用提取（AI 提取、模板固化）/
   岳翔宇旧板切块（解析器已有）。
4. **参数化粒度**：拓扑与几何固化在模板里；**数值全部是参数**（电阻值、电容值、分压比……），
   参数由 datasheet 约束校验器把关（如 VOUT 分压公式、耐压裕量），不许模型拍脑袋。
5. **固件理解只到接口事实**：引脚占用表（哪个脚干什么：GPIO/UART/PWM/ADC/电平）。
   不理解软件逻辑。

## 分段路线图（总览，逐段开工逐段验收）

| 段 | 内容 | 验收 |
|---|---|---|
| **008a**（本任务书正文） | 块模板格式 + 装配引擎；从块规格重建 CH340 板 | 与黄金 compare 连通性零差异 + lint 0 + 岳翔宇签可读 |
| 008b | curated 件库 + 在线比对选型（daemon 侧，easyeda-agent 模式） | 离线命中已验证件；在线比对带库存/价格/basic 证据 |
| 008c | BOM/固件/datasheet 输入理解 → 模型出块方案 → 机器校验 | 块方案过引脚数/电平/电源树校验 |
| 008d | 终极验收：FOC 毕设板从零生成 | 岳翔宇判 0.8 |

---

# 008a：块模板格式 + 装配引擎

## 目标

证明全架构最大的赌注：**给定块规格（哪些块、摆哪、参数值、块间怎么连），装配引擎能产出
过三闸门的原理图**。用 CH340 板做靶——黄金在手，compare 闸门现成。

**诚实的边界**：008a 的模板允许从黄金切块获得（源 3 的机械验证）。这验证的是**装配机制**，
不是模板创作质量——后者归 008c/d 管。报告里不许混为一谈。

## 工作项

### 1. 块模板格式（`blocklib/` 新目录，JSON）

每块一个文件，字段至少含：

- `name` / `description` / `provenance`（textbook | datasheet-extract | board-extract + 来源引用）；
- `interface`：端口列表 `[{role, net_class(power|signal|gnd), position}]`——position 是块内坐标，
  装配时在该处放标签；
- `components`：`[{ref(块内位号模板), device(绑定规则：curated 件库 key 或参数化规则), params}]`；
- `geometry`：块内走线/旗标/器件位姿，**坐标空间 = file 空间**（与黄金同约定，
  转换唯一入口仍是 `canvas_pin_offsets`，006c 宪法不许破）；
- `params`：`[{name, role, default, constraint}]`——constraint 是可执行校验规则的引用
  （如 `resistor_value` / `voltage_derate(0.8)` / `divider_ratio(vout, vref)`）。

### 2. 切块工具（`tools/` 下，`extract_block`）

从 `.epro2` 黄金按设计器清单 + 包围盒切出一个块模板：子模型提取 → 块内坐标归一化
（平移到块原点）→ 端口推断（块边界上的标签/旗标点）→ 写 JSON，**附 provenance**。
端口推断不许脑补：边界上有什么写什么，没有就留空让人补。

### 3. 装配引擎（`engines/assemble.py`）

输入 = 块规格 JSON（块清单 + 格子坐标 + 参数赋值 + 块间网连接 by 端口）；输出 = 走既有
draw 链路画板。规则：

- 块内几何**逐点回放**（同 006b 回放语义，含 R5 拆线规则）；
- 块间连接**只放标签**（命名策略沿用 draw 的默认 `text`，报告如实标注）；
- 器件解析走 `lib.device.search`/curated 绑定，放置后 `set_component_attribute` 写真值
  （Value + Supplier Footprint，006b §I 机制）；
- 建页走确认门禁（006c），CLI `--yes` 逃生门。

### 4. 规格驱动 compare（`compare --spec` 或等效）

装配的判据来源不是黄金几何，而是**从块规格推导的规格网表**（块内模板自带连通性 +
块间标签连接）。差异三分类沿用既有惯例，候选侧仍是编辑器网表导出（`_settled_netlist`）。

### 5. CH340 端到端

手写一份 CH340 板块规格（块从黄金切出），装配 → 三闸门：
compare（对黄金网表，双重核对：规格网表 == 候选 == 黄金）/ lint 0 / 岳翔宇签可读。

## 验收

1. `compare`：候选 vs 黄金 **net 0 / pin 0**；component 行只允许 overrides 旁车覆盖的项，
   命中带 provenance。
2. `lint` 0 违例。
3. 岳翔宇在编辑器里亲眼判"可读"（R1~R4）。
4. 测试全绿，计数只增不减（基线 **Python 372 / connector 167 / tsc 干净**）；
   新增：模板 schema 校验测试、切块 round-trip 测试、装配 compare 负向测试
   （改一个参数值必须报差异）。
5. 完成记录写回本任务书；若需新桥动作，列出来由 Kimi 评估（daemon 重启归 Kimi）。

## 不许动的部分

006b/006c 全部既有语义（回放变换、命名策略、门禁、守卫）；黄金夹具一字不动
（更正仍走旁车）；模型自由度宪法三坐标空间规则；不做 008b/c/d 的内容。

---

# 008a 完成记录（2026-09-16）

## 交付物

| 路径 | 角色 |
|---|---|
| `src/boardwise/core/blocks.py` | 模板 / 板规格 schema + 加载器 + **可执行参数约束**注册表 |
| `src/boardwise/engines/cut.py` | 从 `.epro2` 切块（`extract_block` / `recut`） |
| `src/boardwise/engines/assemble.py` | 模板 + 规格 → 设计（DesignModel + PageLayout + offsets + bodies） |
| `tools/extract_block.py` | 切块 CLI（单块切 + `--recut` 重新推导） |
| `blocklib/blocks/*.json` | 四个块模板（提交物，可确定性再生） |
| `blocklib/specs/ch340g_usb_uart.json` | CH340 板规格（块 / 摆位 / 连接 / 全部数值） |
| `docs/blocks.md` | 格式与管线的正式说明（含非目标） |
| `tests/test_blocks.py` / `test_cut.py` / `test_assemble.py` / `test_spec_cli.py` | 78 个新用例 |
| `parsers/schematic.py` | 新增 `collect_symbol_details`（一次解析拿到 offsets + pin 名 + 实测盒）；`collect_symbol_defs`/`collect_symbol_bodies` 改为它的包装，去掉三份重复的解析循环 |

**加动作的 5 触点一个都没动**：`protocol.py` 未改（`ACTIONS` 仍 29 条），
`daemon.py` 只 import `protocol`、**不 import engines** ⇒ **本轮不需要新桥动作，
也不需要重启 daemon**（008a 的 `--spec` 走 CLI，不经 daemon）。

## 工作项落地

### 1. 块模板格式 —— 见 `docs/blocks.md`

字段：`provenance` / `origin_file` / `bbox_file` / `symbols` / `components[]`
（含 `placement` + `device{}` + `params{}` + `pins[]`）/ `interface[]` / `params[]` / `geometry`。
坐标是**块内 file 坐标**（绝对减 `origin_file`）；**装配 = 局部 + `at`**
（`at - origin_file` 会重复扣一次，正是第一版装配器的 bug：网表对、几何偏 240）。

`params[].constraint` 引用 `core/blocks.py::CONSTRAINTS` 里的**可执行**校验器
（`free_text` / `resistor_value` / `capacitor_value` / `frequency`）；**未知约束名是错误**
（拼错的约束若静默通过，模板就在宣称一个并不存在的检查）。切块工具按证据推断约束并
**说明依据**：器件名以 `Res` 开头或封装形如 `R####` ⇒ 电阻；值以法拉单位收尾 ⇒ 电容；
值含 `Ω` ⇒ 电阻；**证据不足 ⇒ `free_text` + 一条 note**（`104` 既是电阻标记也是电容标记，
没有封装证据就不猜），需要指定时用 `--constraint REF=NAME`。

### 2. 切块工具

按「设计器清单 + 包围盒」切；**边界不许切导线**（半个 run 要么拖出短线、要么丢掉
连通性已经算过的铜），**端口不许脑补**（端口 = 框内标签/旗标且该网有成员在块外；
边界上没锚的跨网**不给端口，只留 note 给人补**）。四个包围盒把黄金页**恰好切干净**：
45 个 wire run，没有一条落在两块里，也没有一条落在所有块外。

### 3. 装配引擎

`assemble()` 输出既有 draw 链路正好需要的四样东西，交给**同一个** `build_replay_plan`——
所以装配出的页面用的是同一套五条硬约束、同一条注解 lint、同一个 R5 拆线，
**没有新校验器、没有给 R1~R5 开例外**，file→canvas 转换仍只有一处。

**连接以规格为准**：`connections` 决定每个局部网在页面上的名字，名字不同就在块内
重命名该网的导线/旗标/标签/引脚。三条拒绝：**同一位号出现在两块**（008a 一块一实例、
不重编号）；**两个电路最终同名却没被连接合并**（这条错误会让两个网悄悄变成一个）；
**电源/地端口所在位置没有旗标 —— 但只对带几何的块**（2026-09-17 岳翔宇裁决修订）。

第三条的修订：原来它是一刀切的，理由写的是"轨道端口需要编辑器的旗标符号，凭空造一个
不在选项里"——**那句话已被证伪**（`sch.place_power` 不收 symbol uuid，编辑器按
kind+net 自解析；空 `symbol_uuid` 在回放里优雅降级，见 `tools/_probe_flag_anchor.py`）。
新规则按**块是否带几何**分流：

- **带几何的块**（`board-extract`）：原有拒绝一字不动。它的旗标是切块量到的锚点，
  缺一个就是模板/切块的缺陷。`position` 必填且必须落在其中一个旗标/标签上。
- **空几何的块**（`datasheet-extract` / `textbook`）：装配器**逐引脚端点合成锚点** ——
  轨道端点上加一格短线 + 旗标，信号端点上放网络标签。`position` **禁止**填写
  （`[0,0]` 不是"没有位置"，是"锚点在块原点"这个没人量过的断言，loader 拒绝）。

合成规则、格距方向、端口兼任、以及"锚点落进器件 body 只记 note 不 raise"，
见 `docs/blocks.md` 的 "Anchors: two paths" 一节。

### 4. 规格驱动 compare

`boardwise compare --spec <spec> --golden <epro2> [--overrides <sidecar>]` —— 离线，
无编辑器。judgement 来源是**规格网表**（块内连通性 + 块间连接），不是黄金几何。
`compare` **只在 `--overrides` 明确给出时**才吃旁车（005 的契约是裸文件对文件比较，
默认改黄金会让既有命令换了含义）；`draw` 仍沿用「黄金旁边的旁车」这一既有默认。

## 三个闸门的离线证据（真机项见下）

```
$ boardwise compare --spec blocklib/specs/ch340g_usb_uart.json \
      --golden tests/fixtures/ch340_golden.epro2 \
      --overrides tests/fixtures/ch340_golden.overrides.json
no differences — designs match                       (exit 0)

$ boardwise lint --spec blocklib/specs/ch340g_usb_uart.json
components: 17  nets named: 27  wires: 57  NC pins: 12  naming: text  violations: 0
layout lint: 0 violations                            (exit 0)
```

**双重核对（规格 == 黄金）**：`compare_models(黄金+旁车, 规格网表)` 空 ——
net 0 / pin 0 / component 0。装配出的设计是**在规格自己的格子上**的
（四块全部移过位，不是把黄金摆回去），块间连通完全靠网名承载。

**切块-装配 round-trip**：把 `at` 全部还原成 `origin_file` 后重装，
黄金页的 parts（17）/ wires（45）/ flags（17）/ labels（10）**逐字段完全相等**，
网表也完全相等。**模板可再生**：`tools/extract_block.py --recut` 从模板自己记录的
provenance 重切，与提交的 JSON **逐字节相同**（`tests/test_cut.py` 钉住）。

**负向测试**（验收项 4）：改一个参数（`usb.r24_value: 5.1K → 10K`）必须报差异 ——
恰好 1 条 component 差异（R24 value），net/pin 差异为 0；且新值确实进了
`PlacementStep.value`（会写到编辑器的 `Value` 属性上）。

## 计数

**Python 372 → 450**（+79）；**connector 167 → 167**（未改）；`tsc --noEmit` 干净。
基线只增不减 ✓。`testzip` 类产物本轮无新 `.eext`（连接器未改）。

## 设计取舍（写下来免得当成遗漏）

- **四块而不是五块**：黄金页上状态灯（LED1 + U3）的接地轨与稳压块**共用同一根导线**
  （`C6.2 → LED1.1` 是同一个 primitive）。在两者之间画边界就是切铜——工具会拒绝。
  所以电源块的定义是「3.3V 轨 + 它的去耦 + 挂在它上面的指示灯」，模板 description 与
  spec 的 note 都如实写了。这是 R1「块按功能划分」的一次判断，不是机械切分。
- **不做块标题/边框**：R1 允许「清晰留白」这一形态，spec 的摆位就是靠留白分块
  （238 / 60 / 117 / 172 单位）；合成 caption 会引入一个新的 lint 面。已记进
  `docs/schematic-conventions.md` 的非目标，是决定不是疏漏。
- **一块一实例、位号原样**：`components[].ref` 就是黄金位号，跨块重名直接报错。
  按实例分配位号属 008c。

## 待真机（岳翔宇在场）

按 `docs/draw.md` 的验收步骤：

1. 停掉 61190 上不是当前 daemon 的东西；`boardwise bridge start`（**本任务不需要重启
   daemon，但如果 daemon 是旧的，仍需按惯例重启以对齐代码**）。
2. 侧载 connector **0.4.1**、重启编辑器、`bridge status` 应 connected。
3. 离线两项先跑（上面那两条命令，两处都必须 0）。
4. **问过岳翔宇再建新页**（硬规则；`--spec` 模式自带的 `sch.doc.new` 走同一个创建门禁），
   然后：
   ```
   boardwise draw --spec blocklib/specs/ch340g_usb_uart.json \
       --golden tests/fixtures/ch340_golden.epro2 --render out.png
   ```
   禁 P1（有探针残留）。报告开头是装配清单（每块去了哪、每个端口/连接），
   然后是双重核对结论，再是 `plan source: golden replay` 与三闸门。
5. 门禁 3：岳翔宇看 `out.png` 判可读（R1~R4）。

**最该盯**：`placement check: 17 parts, M drifted, 0 unmappable`（`M>0` = 库确实重画了
符号，先看 R24/R27/U3 是否还在 unmappable、USB1 是否 drifted），以及 diff 是否为
`no differences — designs match`。

**风险提示（诚实的边界）**：块间连通靠**导线自带的 net 名**承载（`wire` 策略的依据，
2026-09-14 实测：编辑器网表认导线自身的 net 属性）。黄金页的 D+/D- 本身就是分开的两段，
所以这条机制在黄金页上已经被 006b 的 0 差异验证过；但**「把块搬开之后仍然成立」只在
离线判据上验证过**（lint 0 + 规格网表不变），真机才是终判。


---

## 验收戳（008a 正式收官，2026-09-16，Kimi）

**离线复验（Kimi 亲跑）**：Python **451** / connector **167**（本轮未动）/ `tsc` 干净；
`compare --spec` exit=0 字面零差异（overrides 命中带 provenance）；`lint --spec` 0 违例。

**真机验收（0.4.1，岳翔宇在场）**：

| 闸门 | 结果 |
|---|---|
| 1 compare | 真机终跑 `no differences — designs match`（162 动作，仅 export.render 已知失败）；Kimi 活页抽查：17 件/13 网、`U1.16→VCC`、+5V/VCC/D+ 跨块连通归属逐脚正确 ✅ |
| 2 lint | 0 违例 ✅ |
| 3 可读 | 岳翔宇 2026-09-16 亲签"没啥问题"（四块搬位、块间纯标签形态获认可）✅ |

**架构赌注兑现**：块模板 + 装配引擎路线成立——块搬离原位后连通性仍由网名承载且零差异。
这验证的是装配机制（模板来自 board-extract）；模板创作质量归 008c/d 验收，不混。

**008a 验收通过。** 下一任务：008b（curated 件库 + 在线比对选型）。
