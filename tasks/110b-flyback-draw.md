# 110b / 反激电源·棒B：落图（test 工程 P1，机械执行）

棒A 规划 + 主代理闸口修正已完成。**你的唯一施工图是
`E:\boardwise\outputs\110\plan.corrected.json`**——按它摆放、按它连线、按它回读。
这不是设计任务，是执行任务：**图纸里有的照着做，图纸里没有的不许发明**
（拿不准的写进报告，别替设计做决定）。

## 思考纪律（硬规矩）

机械执行，**单步思考超 200 字就先把手头状态写进 `outputs/110/b/LOG.md` 再动**。
所有坐标/脚位/回读结果都落文件，不靠记忆。上一轮有个代理攒了 3 万字符思考被岳杀了。

## 现场与身份（每次写会话开头必做，R1）

- daemon 61190；窗口 **`inst-025818455-rzuh015n`**——另一个窗口是禁地。
- 身份复核：`doc.list --instance` 页清单逐字含 P22/P23/P24 + P1 + schematic1 + PCB1（=test 工程）。
- **只写 P1**。U3（UC3845B, C347460, (610,535) rot 0）原位保留。

## 步骤

### 0. 残局存档与清场

- 先 `export.render` 一张当前 P1（上一轮被杀代理的残局，存 `outputs/110/b/remnant.png`）。
- 页上现有散落器件全部删掉（`sch.delete_primitives`，删除预算约 150s——撞预算就
  `doc.open` 重激活分批删），清到「只剩图幅 + U3」。**清完不保存**。

### 1. 摆放（按 regions）

- 按 plan.corrected.json 的 parts 与 regions 逐件放置（LCSC 料号取件；
  R3/R15 的 75kΩ 0603 用 catalog 只读搜索实测（topN≤3），**查不到就停下报告，不许虚构**）。
- 每放一件，`component_pins` 实测脚位落 `outputs/110/b/pins_<位号>.json`——
  **连线一律按实测脚名映射**（T1 的 P1/P2/A1/A2/S1/S2 意图标号到实测脚号的映射表、
  U4 的 A/K/REF、U5 的 1A/2K/3E/4C、BR1 的 +/−/~/~、二极管阴阳极，全部按脚名不按脚号；
  TL431 SOT-23-3 脚序依厂商而变，必须看脚名）。
- T1 绕组参数（Lp=1mH、Np:Ns=7.2:1、Naux:Ns=1.2:1）写进符号属性（`sch.set_component_attribute`）。

### 2. 连线与旗标（按 nets，26 网）

- 逐网布线/打标签。旗标纪律（岳）：PGND/SEC_GND/HVDC/+12V 旗**竖直**；
  同属性远脚打网络标签不硬连；旗与网名一一对应，有旗不反复标。
- **PGND 与 SEC_GND 永不合并**；除 T1/U5 符号本体外，任何线不跨隔离带（regions 里有写）。
- T1 同名端：P1（HVDC 侧）与 S1（副边热端）反激相位——以符号圆点核对，反了就把
  S1/S2 对调并在报告里写明。

### 3. 分批回读（双证，每模块一次）

- 每完成一个模块（M1 输入/M2 整流/M3 功率级/M4 采样/M5 控制/M6 输出/M7 反馈），
  `sch.netlist` 回读该模块各网成员，与 plan.corrected.json 的 nets 逐脚对：
  计划有的都在、不该连的不连。不符先修再继续。**不许攒到最后一次回读。**

### 4. 收尾

- `sch.doc.save`（30s 超时重发一次）。
- `export.render` PNG（`outputs/110/b/render_final.png`）。
- ERC：`sch_Drc.check`（结果落 `outputs/110/b/erc.json`）。
- 报告 `outputs/110/b/REPORT.md`：每模块落图记录、75k 选型证据、T1 脚号映射表、
  回读双证结论、ERC 结果、你拿不准/没照图做的事（诚实写）。

## 纪律

- 删除（文件）一律回收站；编辑器内删件走 `sch.delete_primitives` 正常通道。
- 不碰 git、不写 PROGRESS.md、不碰 P22/P23/P24/PCB1 与另一个窗口。
- 撞坑表里的坑（cmdKey TypeError/宿主并线/save 超时/删除预算）按 SKILL.md §6 的既定处理，
  并把坑名记进 REPORT.md。
