# 仿真通路侦察报告（R5，只侦察不实施）

> 本报告只回答「路在哪、通不通」，**没有写任何 boardwise 功能代码**。唯一的脚本是 `tools/R5_ngspice_probe.py`，属于侦察探针。
> 每条结论都附了可复核的来源：命令、读数或文件位置。说「不知道」的地方，都写了下一步实验。
> 环境：立创 EDA Pro 3.2.186 官方安装包，用 innoextract 解包但**不安装、不运行**，只读其中打包的 JS；
> ngspice 47 解包到 `D:\tools\ngspice-47`，属于隔离安装，不进 PATH、不改系统。

## 1. 立创侧：编辑器有什么

| 能力 | 证据 | 结论 |
|---|---|---|
| **导出 SPICE 网表** `sch_ManufactureData.getSimulationNetlistFile(fileName, 'Ngspice')` | 类型包 `@jlceda/pro-api-types` 0.4.25 有声明（@beta）；3.2.186 的 `assets/pro-api/0.3.18…/api.js` 有实现：`rpcCall("getNGspiceNetlist")` → `new File([sourceCode], …)` | **只有仿真页才有**：编辑器端 `assets/pro-sch/3.2.181…/js/sch-main.js` 的 `-getNGspiceNetlist` 处理函数写的是 `if (t.docType === Ie.NGSPICE) { … return {sourceCode, title} }`。也就是说，当前文档必须是「ngspice 仿真原理图」类型（`SIMULATION_SCHEMATIC_PAGE_NGSPICE = 8`）才有返回值，**普通设计页拿到的是 undefined**。这是静态读代码得出的，**未上机验证** |
| **扩展当仿真内核** `SCH_Event.addSimulationEnginePullEventListener` + `SCH_SimulationEngine.pushData` | 类型声明有：拉取事件 `SIMULATE_NETLIST` / `VALIDATE_NETLIST`，推送事件 `SIMULATION_RESULT` / `VALIDATION_RESULT` / `LOG_RESULT` / `ERROR_RESULT`；`api.js` 实现了注册，并限定只有扩展能调（「非扩展无法调用本接口」） | 编辑器把「跑仿真」留成了可插拔接口，理论上 boardwise connector 可以把 ngspice 接成编辑器的仿真后端。**事件在什么条件下触发不知道**，下一步实验见下 |
| **外部仿真程序** | `sch-main.js` 的 `-isSimExe`：先打开 `lceda-sim://open`，再探测 `9002` 端口；官网另有一个单独的下载包「仿真引擎 `lceda-pro-sim-windows-x64-2.7.3`」 | 编辑器自带的仿真是一个独立进程，靠本地端口通信 |
| **库里的仿真模型** | `lib_SimulationModel`（create / get / search / copy）；`ELIB_LibraryType.SIMULATION_MODEL_NGSPICE = '32'`、`SIMULATION_MODEL_SIMULIDE = '33'` | 立创库里有 ngspice 模型，可以按关键字搜到（需要联网的系统库）。这是器件模型的一个潜在来源 |
| 普通网表的类型 | `ESYS_NetlistType` 里有 `DISA_SIMULATION = 'DSNET'` | 和 SPICE 无关，记一笔 |
| boardwise 现状 | `connector/src/actions.ts`：只有 `sch.netlist`（`getNetlistFile`），**没有任何仿真相关动作** | 要接仿真，需要新动作（未做） |

**立创侧下一步实验（真机，test 工程）**：
1. 在普通设计页调 `sys.probe` 查 `getSimulationNetlistFile`，预期返回 undefined；
2. 新建一张仿真页，画一个 RC，再导出，看网表长什么样（器件模型是怎么写进去的）；
3. 注册一个空的仿真引擎监听，在编辑器里点仿真，看 `SIMULATE_NETLIST` 会不会推给扩展、带了什么数据。

## 2. ngspice 通路：能不能从 boardwise 模型生成网表

- **安装**：ngspice 47（SourceForge `ng-spice-rework/47/ngspice-47_64.7z`，sha256 `59225971…518f5a`，与 SourceForge 公布值一致），用 7-Zip 解包后直接用 `Spice64/bin/ngspice_con.exe -b <cir>` 批处理。
- **能做到的**：无源网络。阻容值用 boardwise 现有的 `parse_resistance_ohms` / `parse_capacitance_farads`，拓扑来自模型的网络，地网用 `is_ground_net`，节点名做一次清洗。原型在两块夹具上都跑通了（见 §3）。
- **器件模型从哪来**：
  - **货架（`blocklib/parts.json`）里没有 SPICE 模型**：它的 `params`/`facts` 是数据手册字段（耐压、压差、输出电压），不是模型；
  - 可选来源：① 立创库的 ngspice 模型（`lib_SimulationModel.search`，在线）；② 厂商 SPICE 模型（手工收录）；③ **由货架事实生成行为级宏模型**，例如 LDO 用「输出 = min(Vout, Vin − dropout)」加 `dropout_max_mv`，运放用理想 VCVS。对「审查交叉验证」这个用途，③ 的精度够用，而且不依赖外部库。
- **电源、地、探头怎么映射**：电源轨取设计意图合同里的 `targetVoltage`（065 的 intent 通道，问过一次就不再问）作直流源；滤波器输入加 AC 1；探头就是规则的主语网络；地是 `is_ground_net` 判出来的网。**有多个地域时以哪个为 0 节点，需要一条规则来定，目前没有**。
- **建议先支持的拓扑**：RC 低通（`param-rc-cutoff`，原型已通）；分压（`param-divider-output`，做直流工作点就行）；LDO 压差 / 上电时序（需要 ③ 的宏模型，先攒着）。

## 3. 「审查 + 仿真」的最小闭环：原型与读数

`tools/R5_ngspice_probe.py`：从 `param-rc-cutoff` 报出的一对 R、C 出发，生成两份网表：
- `pair`：只放规则读到的这一对；
- `node`：按画法把这个节点上所有对地的 R/C 都放进去。

两份都交给 ngspice 跑 `ac dec 200 0.001 1g` 加 `meas … vdb(out)=-3.0103`。原始网表和日志在 `outputs/R5/ngspice/`。

| 夹具 / 节点 | 规则报的 fc | ngspice `pair` | ngspice `node` | 读法 |
|---|---|---|---|---|
| 毕设滤波采样 R43(470Ω)+C79(1nF) @NET8 | 338,627.5 Hz | 338,628 Hz | 338,628 Hz（这个节点上只有一颗对地电容） | 算术对拍一致，链路正确。节点上还挂着 U8（运放）的两个引脚，按开路处理并列出 |
| FPC 触屏游戏机 R12(10k)+C12(100nF) @TVDD | 159.15 Hz（同时还报了 C11 → 2 Hz、C13 → 159 Hz） | 159.155 Hz | **1.560 Hz** | 三颗电容（10µF + 100nF + 100nF）并在同一个节点上，真实极点约 1/(2π·10k·10.2µF) = 1.56 Hz。规则**逐对**报数，并写明「只报告不评级」，所以不是误判；但它报出的 159 Hz 不是这个节点的截止频率。**这就是仿真能补上的价值** |

**数据链路还缺的东西**（这个闭环要变成规则的话）：
1. **IC 的行为**：目前把 IC 引脚当开路。TVDD 其实是经 10k 串联电阻给 U7 供电的电源轨，U7 的电源电流会在 10k 上产生压降，这才是更要紧的问题。但**我不知道 U7 的电流**，下一步实验是从数据手册取 U7 的电源电流，作为电流源负载加进去再仿一次。货架里目前没有这个字段。
2. **负载电流和需求通道**：`param-rc-cutoff` 自己写了「没有需求通道（reported, not graded）」，仿真只能给出「真实值」，给不出「对不对」。
3. **地参考**：有多个地域时以哪个为 0 节点，还没有规则。
4. **寄生参数**：电容的 ESR、容差、直流偏压降容都没有建模，结论只到理想元件这一层。
5. **跨板**：多板工程得先按板建模（规则在多板工程上会报「请按板建模」，已经见到）。

## 4. 建议

| 方向 | 建议 | 理由 |
|---|---|---|
| 无源 RC / 分压的仿真复核（ngspice 批处理，作为 INFO 的补充读数） | **值得做** | 依赖面小（只要一个外部可执行文件，可选），能直接纠正「逐对读数 ≠ 节点真实值」这类简化（FPC 板实证） |
| 由货架事实生成的 IC 行为级宏模型（LDO / 运放） | **先攒着** | 先要给货架补字段（电源电流、带宽），并定好「宏模型精度说明」的写法 |
| 接立创的仿真引擎钩子（扩展当仿真后端）/ 导出仿真网表 | **先攒着，先做 §1 的三个真机实验** | 只有仿真页能导出网表，普通设计页导不出；事件什么时候触发不清楚；必须真机实测 |
| 全电路瞬态仿真 | **现在不值得** | 器件模型这一块缺口最大，结果会被模型误差淹没 |
