# KiCad 能力矩阵（R3 阶段一侦察）

> 宿主：KiCad **10.0.6**（Windows x64，2026-08-29 发布）。下载自 GitHub 官方发布页
> `KiCad/kicad-source-mirror`（`kicad-10.0.6-x86_64.exe`，sha256 `9e24dc47…16ce48`，与发布页记录的 digest 一致）。
> 安装方式：用 7-Zip 把 NSIS 安装包**解包**到 `D:\tools\kicad-10.0.6`，**没有运行安装程序**，不写注册表、不进 PATH，
> 符合任务书「隔离环境」的要求。kicad-cli 和自带的 Python 都从这个目录直接调用。
>
> 样本工程为**自建**（`tests/fixtures/kicad_min/`，生成器 `tools/R3_make_kicad_fixture.py`），没有用任何第三方设计。
> 文中凡标「实测」的结论，都以 KiCad 自己的输出作为基准：原理图连通性用 kicad-cli 的网表器，
> PCB 几何用 pcbnew 的读数。

## 1. 文件格式（实测）

| 文件 | 本质 | 内容 | boardwise 怎么读 |
|---|---|---|---|
| `.kicad_pro` | JSON | 只有工程设置（网络类、文本变量、元数据），**不含设计数据** | 只用来找同名的 `.kicad_sch` / `.kicad_pcb` |
| `.kicad_sch` | S 表达式，`(version 20260306)`，generator `eeschema` 10.0 | 嵌入式 `lib_symbols`（派生符号已展平；引脚号、名、电气类型、位置、朝向，**库坐标 y 向上**）；`symbol` 实例（`lib_id`、`at x y rot`、`mirror x\|y`、`unit`、Reference/Value/Footprint/Datasheet 及自定义字段如 `LCSC`/`MPN`、`in_bom`/`on_board`/`dnp`）；`wire`、`junction`、`label`/`global_label`/`hierarchical_label`、`no_connect`、`sheet`（层次）；电源符号（库符号带 `(power)`，网名取其 Value） | **文件里没有网络**，连通关系由几何推出：引脚端点 + 导线端点 + 结点 + 标签 + 电源符号 |
| `.kicad_pcb` | S 表达式，`(version 20260206)`，generator `pcbnew` 10.0 | `layers` 表；`footprint`（`at X Y rot`、层 F.Cu/B.Cu、属性）；`pad`（号、`smd`/`thru_hole`/`np_thru_hole`、形状、`at`=封装局部坐标+**绝对**朝向、`size`、`drill`、`layers`、`net`、`pinfunction`、`pintype`）；`segment`/`arc`（走线）；`via`；`zone`（轮廓 + `filled_polygon` 铺铜结果，洞用切缝拼进单一轮廓）；`gr_*` 在 `Edge.Cuts` 上（板框） | **每个焊盘都直接写着网络**，几何全部显式 |

### 1.1 几个实测出来的格式事实（不照搬立创的逆向假设，都是对着 KiCad 输出量的）

- **原理图引脚变换**：图纸坐标 = `at` + 镜像( 旋转(rot) · (x, −y) )。也就是库坐标先翻 y，再按 rot 旋转（`x' = x cos + y sin, y' = −x sin + y cos`，视觉上逆时针），**最后**在图纸坐标里做 `mirror x`（y 取反）或 `mirror y`（x 取反）。
  在 rot 0/90/180/270、mirror x、mirror y 的组合上用 kicad-cli 网表逐引脚验证过；先镜像再旋转的顺序会让 `rot 90 + mirror y` 那颗 R3 的两个引脚对调（实测）。
- **网名约定**（kicad-cli 网表器）：根图的本地标签记为 `/NAME`，全局标签和电源符号记为 `NAME`，无名网记为 `Net-(REF-PadN)`。
- **电源符号**：同名的多个电源符号连成一个网（`+3V3`、`GND` 各放了 2 个以上，实测合一）。
- **标签挂在导线中段**也能连通（LED_A 实测）；T 型交点带结点时连通（+5V 总线实测）。
- **PCB 层号**（KiCad 10）：F.Cu=0、B.Cu=2、内层为偶数（In1.Cu=4…），非铜层为奇数；单位 mm，y 向下。
- **焊盘**：`at` 里的位置是**封装局部坐标、未旋转**，角度是**绝对**朝向；绝对位置 = 封装位置 + 旋转(封装 rot)·局部坐标。底层封装由 KiCad 写成翻转后的样子（R1 放底层后 rot 变成 180，焊盘已镜像，实测）。
- **网络**：KiCad 10 的 `(net "名")` 只写名字，旧版本写 `(net 序号 "名")`；两种都要兼容。
- **铺铜结果**：`filled_polygon` 显式存在（不用自己算），洞以切缝方式并进单一轮廓，even-odd 判点直接可用。
- **ERC/DRC**：kicad-cli 输出 JSON，逐条列出违规（type / severity / description / items）。这一点和立创不同，立创的 ERC 只给计数（坑 27）。

## 2. 与 `.epro2` 模型的映射表

| boardwise 字段 | `.epro2`（立创，既有） | KiCad 来源（R3） | 换算 / 备注 |
|---|---|---|---|
| `Component.designator` | 原理图 `ATTR Designator` | 符号属性 `Reference` | 以 `#` 开头的位号（电源 / 标志符号）不算元件，这是 KiCad 约定 |
| `Component.value` | `ATTR Value` / 器件名 | 属性 `Value` | 原样 |
| `Component.footprint` | 器件的 Supplier Footprint | 属性 `Footprint`（`Lib:Name`） | **去掉库昵称**只留 `Name`，完整 id 存 `props["Footprint"]`。实测：带着昵称时，`pcb-footprint-consistency` 会从 `Package_TO_…` 读出封装族 `to`，和板上的 `sot` 对不上，出一条误报 ERROR |
| `Component.lcsc_part` / `mpn` / `manufacturer` | 器件属性 | 自定义字段 `LCSC` / `MPN`（或 `Manufacturer Part Number`）/ `Manufacturer` | KiCad 没有标准字段，读常见写法，读不到留空 |
| `Component.pins[]` | 符号引脚 + 网络 | `lib_symbols` 的引脚（号 + 名）+ 几何连通 | 多单元器件：取 unit 0（公共）和本单元的引脚 |
| `Net.name` | 网络标签 / 自动名 | 标签 / 全局标签 / 电源符号的名字；无名网用 `Net-(REF-PadN)` | 根图本地标签**去掉 `/` 前缀**（规则按用户写的名字认电源轨） |
| 重复位号 | `duplicate_designators`（保留第一处放置） | 同上，语义一致（049 / 105 / 107） | 被丢弃的那处放置所触及的网记入 `unproven_nets` |
| `ComponentPlacement` | `COMPONENT` | `footprint` | mm→mil，y 取反；`layer_id` F.Cu→1、B.Cu→2 |
| `PadGeometry` | 封装 PAD + PAD_NET | `pad` | 位置按上面的变换算；`thru_hole`→`plated=True`、`np_thru_hole`→`False`（直接对上 R2-2 的三态）；`*.Cu`→`MULTI_LAYER_ID`(12) |
| `TrackSegment` | `LINE` | `segment`（`arc` 按弦拆分） | 层号映射同上 |
| `ViaGeometry` | `VIA` | `via` | `size`→`via_diameter`，`drill`→`hole_diameter` |
| `PourShape(poured)` | `POURED`（1:10） | `zone` 的 `filled_polygon` | 已是板坐标，无需缩放 |
| `BoardOutline` | `POLY BOARD_OUTLINE` | `Edge.Cuts` 上的 `gr_line`/`gr_rect`/`gr_arc`/`gr_poly` 首尾相接 | |
| 层表 | `LAYER` / `LAYER_PHYS` | `layers` + `setup/stackup` | **桥接说明**：boardwise 的层号沿用立创那一套（顶 1、底 2、内层 15 起、多层 12），因为规则里写死了这些号。KiCad 的层先翻译成这套号再交给规则。这是**模型接口的约定**，不是在假设 KiCad 的文件长得像立创 |

## 3. 自动化通道（实测）

| 通道 | 状态 | 能读 | 能写 | 读不到 / 限制 |
|---|---|---|---|---|
| **直接读文件**（纯 Python，本 PR 实现） | ✅ 不需要 KiCad | 原理图符号、字段、几何连通、PCB 全部几何与焊盘网络 | 不写 | 层次图 / 总线：最小闭环只做单页平铺图，遇到层次图明确拒绝 |
| **kicad-cli**（10.0.6） | ✅ 无界面、即用即退 | `sch export netlist`（kicadsexpr / kicadxml / …）、`bom`、`pdf`/`svg`；`sch erc --format json`（逐条违规）；`pcb drc --format json`；`pcb export gerbers/drill/pos/ipc2581/odb/step`；`pcb render`；`pcb import`（Altium / PADS / Eagle / …） | 只有 `upgrade` 会改写文件 | 没有放件、改值这类编辑命令 |
| **pcbnew Python（SWIG）** | ✅ 在 10.0.6 自带的 Python 3.11.5 下可用（本侦察和夹具生成器都用它） | 板上全部对象 | 能建板、放封装、布线、铺铜、存盘（夹具就是这样生成的） | 只有 PCB，没有原理图 API；第三方资料说 KiCad 11 会移除 SWIG（**未核实**） |
| **IPC API**（kicad-python / kipy 0.8.0） | ⚠️ 需要 KiCad **图形界面**在运行并启用 API（官方文档原话：remotely control a **running instance**） | 板（`get_board`）、工程（`get_project`） | 板编辑 | **原理图不可用**：kipy 0.8.0 的 `kipy.schematic` 一 import 就报错（`cannot import name 'PageSettings'`，实测）。没有无界面模式。要做立创那样的在线桥，就得开着 GUI，而且只有 PCB 半边 |

## 4. 结论与建议

- **侦察门槛「离线读原理图 + PCB」：可行 ✅**。PCB 的网络和几何全部显式；原理图的连通关系可以由几何推出，而且这套推法已经在自建夹具上被 KiCad 自己的网表器逐引脚验证过。
- **建议离线优先**：纯 Python 直接读文件，boardwise 的「标准库 + websockets」依赖面不变；kicad-cli 作为**可选**的对拍基准，以及 KiCad 原生 ERC/DRC JSON 的来源（下一步，本 PR 不做）。
- **在线桥暂缓**：IPC 在 KiCad 10 上只有 PCB、而且必须开着 GUI，原理图要等 KiCad 11。等到 11 再评估，届时它可以对标立创 connector 的读写面。
- 阶段二（本 PR）做的是最小闭环：`parsers/kicad.py` 把 KiCad 工程读成 `DesignModel` + `BoardGeometry`；`checkup` / `review` 按扩展名分派；夹具上 L1 规则和距离类 PCB 规则出判决。

## 5. 证据位置

- 夹具与基准：`tests/fixtures/kicad_min/`
  - `kicad_min.net`：kicad-cli 导出的网表；
  - `kicad_min.pcbnew.json`：pcbnew 自己的读数；
  - 生成器：`tools/R3_make_kicad_fixture.py`。
- DRC 实测：KiCad 自己的 DRC 在夹具 PCB 上只报了两处故意留的缺陷：C2 与 R3 间距 0.15 mm（`clearance`）、`courtyards_overlap`；其余都是丝印类告警。boardwise 的 `pcb-component-spacing` 在 KiCad 输入上报的是 5.9 mil，与 0.15 mm 一致。
