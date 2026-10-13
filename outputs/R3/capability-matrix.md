# KiCad 能力矩阵（R3 阶段一侦察）

> 宿主：KiCad **10.0.6**（Windows x64，2026-08-29 发布）。下载自 GitHub 官方发布页
> `KiCad/kicad-source-mirror`（`kicad-10.0.6-x86_64.exe`，sha256 `9e24dc47…16ce48`，与发布页记录的 digest 一致）。
> **（fixB 待验：这条摘要不可核验——仓库里没有该安装包、没有 `sha256sum` 记录、也没有发布页快照；
> 审查机与本次修复机 `which kicad-cli` 均为空、`D:\tools\kicad-10.0.6` 已不在。要么把摘要存进本目录，要么删掉这一句。）**
> 安装方式：用 7-Zip 把 NSIS 安装包**解包**到 `D:\tools\kicad-10.0.6`，**没有运行安装程序**，不写注册表、不进 PATH，
> 符合任务书「隔离环境」的要求。kicad-cli 和自带的 Python 都从这个目录直接调用。
>
> 样本工程为**自建**（`tests/fixtures/kicad_min/`，生成器 `tools/R3_make_kicad_fixture.py`），没有用任何第三方设计。
> 文中凡标「实测」的结论，都以 KiCad 自己的输出作为基准：原理图连通性用 kicad-cli 的网表器，
> PCB 几何用 pcbnew 的读数。

## 1. 文件格式（实测；无产物者已在 §1.1 内联标「待验」，汇总见 §6）

| 文件 | 本质 | 内容 | boardwise 怎么读 |
|---|---|---|---|
| `.kicad_pro` | JSON | 只有工程设置（网络类、文本变量、元数据），**不含设计数据** | 只用来找同名的 `.kicad_sch` / `.kicad_pcb` |
| `.kicad_sch` | S 表达式，`(version 20260306)`，generator `eeschema` 10.0 | 嵌入式 `lib_symbols`（派生符号已展平；引脚号、名、电气类型、位置、朝向，**库坐标 y 向上**）；`symbol` 实例（`lib_id`、`at x y rot`、`mirror x\|y`、`unit`、Reference/Value/Footprint/Datasheet 及自定义字段如 `LCSC`/`MPN`、`in_bom`/`on_board`/`dnp`）；`wire`、`junction`、`label`/`global_label`/`hierarchical_label`、`no_connect`、`sheet`（层次）；电源符号（库符号带 `(power)`，网名取其 Value） | **文件里没有网络**，连通关系由几何推出：引脚端点 + 导线端点 + 结点 + 标签 + 电源符号 |
| `.kicad_pcb` | S 表达式，`(version 20260206)`，generator `pcbnew` 10.0 | `layers` 表；`footprint`（`at X Y rot`、层 F.Cu/B.Cu、属性）；`pad`（号、`smd`/`thru_hole`/`np_thru_hole`、形状、`at`=封装局部坐标+**绝对**朝向、`size`、`drill`、`layers`、`net`、`pinfunction`、`pintype`）；`segment`/`arc`（走线）；`via`；`zone`（轮廓 + `filled_polygon` 铺铜结果，洞用切缝拼进单一轮廓）；`gr_*` 在 `Edge.Cuts` 上（板框） | **每个焊盘都直接写着网络**，几何全部显式 |

### 1.1 几个实测出来的格式事实（不照搬立创的逆向假设，都是对着 KiCad 输出量的）

- **原理图引脚变换**：图纸坐标 = `at` + 镜像( 旋转(rot) · (x, −y) )。也就是库坐标先翻 y，再按 rot 旋转（`x' = x cos + y sin, y' = −x sin + y cos`，视觉上逆时针），**最后**在图纸坐标里做 `mirror x`（y 取反）或 `mirror y`（x 取反）。
  **变换顺序实测**：夹具里那颗带旋转又带镜像的 R3（`4.7k`）由 kicad-cli 写成 `(rot 270, mirror x)`（等价于生成器想要的 rot 90 + mirror y），「先旋转后镜像」复现它的网表逐引脚全等；「先镜像再旋转」会让这两个引脚对调（fixB 变异实测 4 红）。
  **但 `mirror y` 这个分支本身没有对拍**（fixB 更正）：`kicad-cli sch upgrade` 会把 `(rot 90, mirror y)` 归一化成 `(rot 270, mirror x)`，所以提交的夹具里**没有任何 KiCad 写出的 `mirror y`**；该分支只由 `tests/test_r3_kicad.py` 里一条**合成**单元断言覆盖，不是对拍。
- **网名约定**（kicad-cli 网表器）：根图的本地标签记为 `/NAME`，全局标签和电源符号记为 `NAME`，无名网记为 `Net-(REF-PadN)`。
  **（fixB 待验：夹具与 `kicad_min.net` 里 `Net-(` 出现 0 次——夹具没有无名网，所以「无名网叫 `Net-(REF-PadN)`」这条只有 KiCad 公开约定 + 本仓库一条单元断言，没有对拍。）**
- **电源符号**：同名的多个电源符号连成一个网（`+3V3`、`GND` 各放了 2 个以上，实测合一）。
- **标签挂在导线中段**也能连通（LED_A 实测）；T 型交点带结点时连通（+5V 总线实测）。
- **PCB 层号**（KiCad 10）：F.Cu=0、B.Cu=2、内层为偶数（In1.Cu=4…），非铜层为奇数；单位 mm，y 向下。
- **焊盘**：`at` 里的位置是**封装局部坐标、未旋转**，角度是**绝对**朝向；绝对位置 = 封装位置 + 旋转(封装 rot)·局部坐标。底层封装由 KiCad 写成翻转后的样子（R1 放底层后 rot 变成 180，焊盘已镜像，实测）。
- **网络**：KiCad 10 写 `(net "名")`，KiCad 6–9 写 `(net 序号 "名")`，两种都读。**（fixB 更正「两种都要兼容」）** KiCad 5 及更早的**裸 `(net 序号)`**（只有 id、名字在顶层 `(net N "NAME")` 表里）**不读**：`_net_name` 对它**按名拒绝**（抛 `KicadFormatError`，提示先 `kicad-cli pcb upgrade`），不再把它读成网名 `"3"`——原来的行为（裸 `(net 1)` 读成字符串 `"1"`）是错的。依据：夹具是 KiCad 10 写的，全部是 `(net "名")`（`grep -o '(net [^)]*)'` 只有带引号的形态），旧形态无对拍。
- **铺铜结果**：`filled_polygon` 显式存在（不用自己算），洞以切缝方式并进单一轮廓，even-odd 判点直接可用。
- **ERC/DRC**：kicad-cli 输出 JSON，逐条列出违规（type / severity / description / items）。这一点和立创不同，立创的 ERC 只给计数（坑 27）。
  **（fixB 待验：本 PR 与 fixB 都没有任何 `*.drc.json` / `*.erc.json` / 命令行记录落盘，这条「逐条违规」在仓库里查无产物；本机装不了 KiCad，补不了。）**

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

## 3. 自动化通道（实测；kipy 与 kicad-cli 子命令清单**无产物**，见 §6 待验清单）

| 通道 | 状态 | 能读 | 能写 | 读不到 / 限制 |
|---|---|---|---|---|
| **直接读文件**（纯 Python，本 PR 实现） | ✅ 不需要 KiCad | 原理图符号、字段、几何连通、PCB 全部几何与焊盘网络 | 不写 | 层次图 / 总线：最小闭环只做单页平铺图，遇到层次图明确拒绝 |
| **kicad-cli**（10.0.6） | ✅ 无界面、即用即退（**2026-10 fixB：本仓库无任何 kicad-cli 命令行记录，本机也装不了 KiCad，以下子命令清单只是文档/用法，不是实测产物**） | `sch export netlist`（kicadsexpr / kicadxml / …）、`bom`、`pdf`/`svg`；`sch erc --format json`（逐条违规）；`pcb drc --format json`；`pcb export gerbers/drill/pos/ipc2581/odb/step`；`pcb render`；`pcb import`（Altium / PADS / Eagle / …） | 只有 `upgrade` 会改写文件 | 没有放件、改值这类编辑命令 |
| **pcbnew Python（SWIG）** | ✅ 在 10.0.6 自带的 Python 3.11.5 下可用（本侦察和夹具生成器都用它） | 板上全部对象 | 能建板、放封装、布线、铺铜、存盘（夹具就是这样生成的） | 只有 PCB，没有原理图 API；第三方资料说 KiCad 11 会移除 SWIG（**未核实**） |
| **IPC API**（kicad-python / kipy 0.8.0） | ⚠️ 需要 KiCad **图形界面**在运行并启用 API（官方文档原话：remotely control a **running instance**） | 板（`get_board`）、工程（`get_project`） | 板编辑 | **原理图不可用**：kipy 0.8.0 的 `kipy.schematic` 一 import 就报错（`cannot import name 'PageSettings'`，**fixB 待验**：无 import 记录、无 traceback 落盘，本机也无 kipy 可试）。没有无界面模式。要做立创那样的在线桥，就得开着 GUI，而且只有 PCB 半边 |

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
- DRC 「实测」**（fixB 更正 + 待验）**：KiCad 自己的 DRC「只报 C2/R3 间距 0.15 mm（`clearance`）与 `courtyards_overlap`」这句**没有产物落盘**——仓库里没有 `*.drc.json`、没有 `kicad-cli` 命令行记录，本机也装不了 KiCad，**KiCad 侧这一半待验**。
  boardwise 一侧**可离线复现**，已落盘 `outputs/R3/fixB-offline-readings.json`：夹具 C2/R3 焊盘边到边距离 = **5.9055 mil = 0.1500 mm**，而生成器声明的是 0.15 mm（`5.9055 mil` 与 `0.15 mm` 是同一个数）；`pcb-component-spacing` 报的是它的四舍五入值 5.9 mil。也就是说「boardwise 的读数与 0.15 mm 一致」这一半有证据，「KiCad 的 DRC 也报 0.15 mm」这一半没有。

## 6. fixB 待验清单（2026-10，PR #80 审查后补记）

以下结论在本仓库**查无产物**，且本轮修复机没有 KiCad（`which kicad-cli` 为空、`D:\tools\kicad-10.0.6` 已不在），无法就地补证，一律标**待验**，不得再当「实测」引用：

| 结论 | 位置 | 缺什么 |
|---|---|---|
| KiCad 10.0.6 安装包 sha256 `9e24dc47…16ce48` 与发布页 digest 一致 | 本文档头部 | 安装包本体、`sha256sum` 输出、发布页快照 |
| KiCad 自己的 DRC 在夹具上只报 0.15 mm `clearance` + `courtyards_overlap` | §5 | `*.drc.json` / DRC 命令行记录（boardwise 一侧的 0.1500 mm 读数已另行落盘） |
| `sch erc --format json` / `pcb drc --format json` 逐条列出违规 | §1.1、§3 | 任何 ERC/DRC JSON 产物 |
| kipy 0.8.0 `kipy.schematic` 一 import 报 `cannot import name 'PageSettings'` | §3 | import 记录 / traceback |
| 无名网叫 `Net-(REF-PadN)` | §1.1 | 夹具里没有无名网（`Net-(` 计数 0） |
| `mirror y` 分支的网表对拍 | §1.1 | kicad-cli 会把 `mirror y` 归一化掉，夹具里没有这种放置 |
| `thru_hole`/`np_thru_hole`/`drill`/`plated`、内层与过孔 span、`gr_arc`/`gr_rect`/`gr_poly`/`gr_circle` 板框、`arc` 走线、`keepout`、`circle`/`oval`/`trapezoid`/`custom` 焊盘 | §2、解析器 | 夹具与测试都没走到（本轮只补了畸形输入的拒绝测试，没补这些分支的正常路径对拍） |
