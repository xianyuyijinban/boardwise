# boardwise checkup 报告

**结论：50 项 ERROR；另有 116 颗器件缺手册未审；另有 7 条 warning 待分诊**（退出码 1）

- 工程：`outputs\bug98\live\foc.epro2`
- 数据来源：`file` — 离线文件（--file）：不连编辑器
- 模型：155 器件 / 147 网，位号 C1、C10、C11、C115、C116、C12、C13、C14、C15、C16、C17、C18、C19、C2、C20、C21、C22、C23、C24、C25、C26、C27、C28、C29、C3、C30、C31、C32、C33、C34、C35、C36、C37、C38、C39、C4、C40、C41、C42、C43、C44、C45、C46、C5、C6、C7、C8、C9、CN1、CN2、CN3、D2、L1、L2、L3、L4、LED1、LED2、Q1、Q2、Q3、Q4、Q7、Q8、R1、R10、R11、R12、R13、R14、R15、R16、R17、R18、R19、R2、R20、R21、R22、R23、R24、R25、R26、R27、R28、R29、R3、R30、R31、R32、R4、R43、R5、R6、R7、R8、R9、RST1、SCREW1、SCREW2、SCREW3、SCREW4、SWD1、U1、U10、U11、U12、U13、U14、U15、U16、U2、U3、U4、U5、U6、U7、U8、U9、USB1、X1
- 计数：50 ERROR / 7 WARN / 167 INFO
- 板：`Board1`（2 页 / 105 器件 / 99 网）、`Board2`（1 页 / 11 器件 / 13 网）、`Board3`（1 页 / 39 器件 / 35 网）

> 本工程有 3 块板（Board1、Board2、Board3）：模块按板再按页/连通性划分，findings 带板归属；模块按「含警告优先」排序，含警告的模块：Board1/P1；PCB 审查：179 条 finding 已并入 findings[]（pcb- 前缀，见 pcb_review 节）

## 整板报告（一键：ERC + DRC + 模块 + 器件）

### 整工程能不能投板：不能投板：先改 50 项 ERROR（逐条见下）

- 排序依据：严重度（ERROR → WARN → INFO）× 模块权重（同级内 PCB 模块级 > 器件级 > 通用）
  - **PCB 模块级**（rank 0）：路线图第二步（按模块检查）＝重中之重：DRC 过只说明「能造」，模块级决定「好不好活」（噪声/发热/EMI/寿命）——权重最高
  - **器件级**（rank 1）：路线图第三步（器件检查）＝收口：封装一致性/极性/丝印/降额，逐颗器件的物理可实现性——居中
  - **通用**（rank 2）：第一步 DRC 与原理图侧 ERC／连通性：门票与电路正确性——最轻
- 本表给人读：ERC + DRC + 模块规则 + 器件规则合成一份，按「板 → 模块/规则族」分组，每条一句话（位号/网/问题/依据）。机器细节（完整 message、evidence、定位链、规则等级）留在 `report.json` 的 findings[]，本表一个字都不新增结论。

### 基线（ERC / DRC）

- 原理图 ERC：未查 —— 未检查 —— 离线路径（--file）不连编辑器，因此没有主机 ERC；这一段的空是「没查」，不是「零错误」
- PCB DRC：未查 —— 未检查 —— 离线路径（--file）不连编辑器，因此没有主机 PCB DRC；要它就给一个在线工程
- PCB DRC 规则集：未读 —— 未读 —— 离线路径（--file）不连编辑器，因此没有主机 DRC 规则集；离线也读不到规则集（它在编辑器里，不在归档里）

### 板：Board1（PCB 文档 `PCB1`，105 器件，4 铜层，40 ERROR / 6 WARN / 108 INFO）

#### 器件检查（器件级）—— 14 ERROR / 0 WARN / 11 INFO

- **ERROR** `PCB1` · C26 —— PCB1 C26 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C27 —— PCB1 C27 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C28 —— PCB1 C28 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C29 —— PCB1 C29 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C30 —— PCB1 C30 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C31 —— PCB1 C31 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C35 —— PCB1 C35 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C36 —— PCB1 C36 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C41 —— PCB1 C41 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C42 —— PCB1 C42 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C43 —— PCB1 C43 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · C44 —— PCB1 C44 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · U10 —— PCB1 U10 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB1` · U14 —— PCB1 U14 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB1` · R11、R25、R3、C11、C15、C16 —— PCB1 电阻降额读数：认出 34 颗电阻（另有 0 Ω 跳线 0 颗、位号像电阻但值与库件都没说是电阻的 0 颗，本规则不判它们）； 〔器件检查 / pcb-derating-package〕
- **INFO** `PCB1` · USB1 —— PCB1 USB1 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB1` · （未点名位号） —— PCB1 封装对账（原理图 Board1）：比了 105 个两边都有的器件——一致 90，焊盘数不符 0，尺寸码不符 14，封装族不符 0，无从比较 1，PCB 侧读不出封装 0； 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB1` · LED1、LED2、LED0805 —— PCB1 上 2 颗极性器件共用封装 'LED0805-RD'（顶层），方向却有 2 种：[90.0, 270.0]——同封装同朝向是生产工艺习惯，不统一只作提醒（岳 2026-10-11 裁：降 INFO） 〔器件检查 / pcb-polarity-orientation〕
- **INFO** `PCB1` · LED0805 —— PCB1 极性器件读数：2 颗极性器件（其中 2 颗原理图声明了极性脚、0 颗只有库件类型词），涉及 1 种封装名，量出印刷方向标记的 2 颗 〔器件检查 / pcb-polarity-orientation〕
- **INFO** `PCB1` · U4、U6 —— PCB1 有 2 个位号**在宽字形模型下**压到焊盘（最窄档 0.4 量不出相交）：2 处，压不压取决于字形实际多宽，本规则不判 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB1` · R20、L1 —— PCB1 有 1 处位号丝印**部分**落在别的器件本体轮廓内（没被完全盖住，仍看得见一部分）：本规则不判 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB1` · C1、C10、C11、C12、C13、C15、C16、C17、C18、C19、C2、C20、C21、C22、C23、C24、C25、C26、C27、C28、C29、C3、C30、C31、C32、C33、C34、C35、C36、C37、C38、C39、C4、C40、C41、C42、C43、C44、C45、C46、C5、C6、C7、C8、C9、CN1、L1、L2、L3、L4、LED1、LED2、R1、R10、R11、R12、R13、R14、R15、R16、R17、R18、R19、R2、R21、R22、R24、R25、R26、R27、R28、R29、R3、R30、R31、R32、R4、R5、R6、R7、R8、R9、U1、U10、U11、U12、U13、U14、U15、U16、U2、U3、U5、U7、U8、U9、USB1、X1 —— PCB1 有 100 个位号的丝印被关掉（``valueVisible=false``）：板上不会印出这些位号——本规则只报读数，不判「是不是忘了打开」 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB1` · （未点名位号） —— PCB1 BOT_SILK（3 个位号）文字方向分布：0°×1, 90°×1, 270°×1 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB1` · （未点名位号） —— PCB1 TOP_SILK（2 个位号）文字方向分布：0°×1, 270°×1 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB1` · （未点名位号） —— PCB1 丝印读数：105 个位号记录（显示 5、关掉 100），板上焊盘 430 只、器件本体轮廓 104 个； 〔器件检查 / pcb-silk-designator〕

#### 原理图连通性（通用）—— 26 ERROR / 1 WARN / 0 INFO

- **ERROR** `Board1` · U15 —— U15 is used by more than one placed part on one page 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · U16 —— U16 is used by more than one placed part on one page 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C1 —— C1 is placed on more than one board (Board1、Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C10 —— C10 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C11 —— C11 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C12 —— C12 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C13 —— C13 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C2 —— C2 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C3 —— C3 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C4 —— C4 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C5 —— C5 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C6 —— C6 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C7 —— C7 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C8 —— C8 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · C9 —— C9 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R1 —— R1 is placed on more than one board (Board1、Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R18 —— R18 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R2 —— R2 is placed on more than one board (Board1、Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R3 —— R3 is placed on more than one board (Board1、Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R4 —— R4 is placed on more than one board (Board1、Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R5 —— R5 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R6 —— R6 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · R8 —— R8 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · U1 —— U1 is placed on more than one board (Board1、Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · U14 —— U14 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board1` · U2 —— U2 is placed on more than one board (Board1、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **WARN** `Board1` · U11（网 NET10） —— U11 pin5: the grounded capacitor on 'NET10' is only 100nF (< required 1uF) 〔原理图连通性 / decap-required-caps〕

#### Board1/P1（PCB 模块级）—— 0 ERROR / 5 WARN / 46 INFO

- **WARN** `PCB1` · R18 —— R18 and U16 are 15.1 mil apart edge-to-edge (pads 1 / 3), under the 20 mil house rule 〔DFM 通用 / pcb-component-spacing〕
- **WARN** `PCB1` · R22 —— R22 and USB1 are 19.2 mil apart edge-to-edge (pads 1 / 11), under the 20 mil house rule 〔DFM 通用 / pcb-component-spacing〕
- **WARN** `PCB1` · R24 —— R24 and USB1 are 19.2 mil apart edge-to-edge (pads 2 / 2), under the 20 mil house rule 〔DFM 通用 / pcb-component-spacing〕
- **WARN** `PCB1` · U8 —— U8 and USB1 are 13.8 mil apart edge-to-edge (pads 5 / 14), under the 20 mil house rule 〔DFM 通用 / pcb-component-spacing〕
- **WARN** `PCB1` · X1 —— X1's region carries **4** copper element(s) on Bottom Layer: track 2bbdb921d0bf3fc9 @ IA+ 〔MCU 最小系统 / pcb-mcu-crystal-keepout〕
- **INFO** `PCB1` · U11（网 +5V） —— U11 sits on the supply net '+5V', and no high-frequency decoupling capacitor bridging it to ground was found on the net… 〔电源去耦 / pcb-decap-distance〕
- **INFO** `PCB1` · U11（网 NET10） —— U11 sits on the supply net 'NET10', and no high-frequency decoupling capacitor bridging it to ground was found on the ne… 〔电源去耦 / pcb-decap-distance〕
- **INFO** `PCB1` · U13（网 +5V） —— U13 sits on the supply net '+5V', and no high-frequency decoupling capacitor bridging it to ground was found on the net… 〔电源去耦 / pcb-decap-distance〕
- **INFO** `PCB1` · U7（网 +24V） —— U7 sits on the supply net '+24V', and no high-frequency decoupling capacitor bridging it to ground was found on the net… 〔电源去耦 / pcb-decap-distance〕
- **INFO** `PCB1` · C7（网 $1N74368） —— C7 on '$1N74368' sits 157.8 mil edge-to-edge from U2.29 ('DVDD') 〔FOC/功率驱动 / pcb-foc-decap-proximity〕
- **INFO** `PCB1` · C3（网 $1N74457） —— C3 on '$1N74457' sits 187.4 mil edge-to-edge from U2.2 ('VM') 〔FOC/功率驱动 / pcb-foc-decap-proximity〕
- **INFO** `PCB1` · C4（网 $1N74457） —— C4 on '$1N74457' sits 112.9 mil edge-to-edge from U2.2 ('VM') 〔FOC/功率驱动 / pcb-foc-decap-proximity〕
- **INFO** `PCB1` · R30、R11（网 PGND、AGND） —— ground domain pair 'PGND' (power) ↔ 'AGND' (logic): **no direct copper connection** between 'PGND' and 'AGND': nearest c… 〔FOC/功率驱动 / pcb-foc-ground-domains〕
- **INFO** `PCB1` · R11（网 AGND、PGND） —— ground domain pair 'PGND' (power) ↔ 'AGND' (logic): **每对域恰好一颗 0R — 合规**（岳 2026-10-11 裁）：R11 (value '0R') bridges 'AGND'… 〔FOC/功率驱动 / pcb-foc-ground-tie〕
- **INFO** `PCB1` · R25（网 GND、PGND） —— ground domain pair 'PGND' (power) ↔ 'GND' (logic): **每对域恰好一颗 0R — 合规**（岳 2026-10-11 裁）：R25 (value '0R') bridges 'GND' (l… 〔FOC/功率驱动 / pcb-foc-ground-tie〕
- **INFO** `PCB1` · R3（网 +24V、$1N74457） —— R3 (value '0R') parses to exactly 0 Ω but its two pins sit on '+24V' and '$1N74457' (domains none / none) — **not a grou… 〔FOC/功率驱动 / pcb-foc-ground-tie〕
- **INFO** `PCB1` · U2、R11、DRV1（网 $1N74368、$1N74369、$1N74382、$1N74383、$1N74384、$1N74385、$1N74457、DRV_EN、INHA、INHB、INHC、INLA、INLB、INLC、MISO、MOSI、NFAULT、NSCS、SCK、SHA、SHB、SHC、SLA、SLB、SLC） —— **未识别清单**: 25 net(s) that carry tracks and sit on a power-stage part but whose **name** this rule's power-path sieve doe… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · U2（网 GND） —— thermal pad of U2: pad 'e9', pin '33', net 'GND', 126 × 126 mil (= 15876 sq mil), shape 'RECT', copper on layer(s) [1] —… 〔FOC/功率驱动 / pcb-foc-thermal-exit-path〕
- **INFO** `PCB1` · U2（网 GND） —— thermal pad of U2: pad 'e9', pin '33', net 'GND', 126 × 126 mil (= 15876 sq mil), shape 'RECT', copper on layer(s) [1] —… 〔FOC/功率驱动 / pcb-foc-thermal-via-array〕
- **INFO** `PCB1` · U2（网 GND） —— thermal pad of U2: pad 'e9', pin '33', net 'GND', 126 × 126 mil (= 15876 sq mil), shape 'RECT', copper on layer(s) [1] —… 〔FOC/功率驱动 / pcb-foc-thermal-via-style〕
- **INFO** `PCB1` · X1 —— X1's region carries **15** copper element(s) on Top Layer: pad X1.4 @ GND 〔MCU 最小系统 / pcb-mcu-crystal-keepout〕
- **INFO** `PCB1` · X1 —— X1's region carries **2** copper element(s) on Inner1: via af0e64b627ae4fa3 @ GND 〔MCU 最小系统 / pcb-mcu-crystal-keepout〕
- **INFO** `PCB1` · X1 —— X1's region carries **2** copper element(s) on Inner2: via af0e64b627ae4fa3 @ GND 〔MCU 最小系统 / pcb-mcu-crystal-keepout〕
- **INFO** `PCB1` · U1 —— U1 declares oscillator pin(s) PC14-OSC32_IN, PC15-OSC32_OUT with **no net at all** — an unpopulated low-frequency branch… 〔MCU 最小系统 / pcb-mcu-crystal-placement〕
- **INFO** `PCB1` · X1（网 OSC-IN） —— X1.1 @ 'OSC-IN' sits 147.2 mil edge-to-edge from U1.12 ('PH0-OSC_IN' @ 'OSC-IN') — the **same net**, so this is the osci… 〔MCU 最小系统 / pcb-mcu-crystal-placement〕
- **INFO** `PCB1` · X1（网 OSC-OUT） —— X1.3 @ 'OSC-OUT' sits 77.1 mil edge-to-edge from U1.12 ('PH0-OSC_IN' @ 'OSC-IN') — a **cross-net** reading (the crystal'… 〔MCU 最小系统 / pcb-mcu-crystal-placement〕
- **INFO** `PCB1` · X1（网 OSC-IN） —— X1.1 @ 'OSC-IN' sits 154.4 mil edge-to-edge from U1.13 ('PH1-OSC_OUT' @ 'OSC-OUT') — a **cross-net** reading (the crysta… 〔MCU 最小系统 / pcb-mcu-crystal-placement〕
- **INFO** `PCB1` · X1（网 OSC-OUT） —— X1.3 @ 'OSC-OUT' sits 77.1 mil edge-to-edge from U1.13 ('PH1-OSC_OUT' @ 'OSC-OUT') — the **same net**, so this is the os… 〔MCU 最小系统 / pcb-mcu-crystal-placement〕
- **INFO** `PCB1` · C20（网 OSC-IN） —— C20 on 'OSC-IN': 实测容值 20pF (20pF), 串联等效 CL 15pF, against 规格 CL 20pF — three columns side by side and **no verdict**: 岳 h… 〔MCU 最小系统 / pcb-mcu-crystal-placement〕
- **INFO** `PCB1` · C21（网 OSC-OUT） —— C21 on 'OSC-OUT': 实测容值 20pF (20pF), 串联等效 CL 15pF, against 规格 CL 20pF — three columns side by side and **no verdict**: 岳… 〔MCU 最小系统 / pcb-mcu-crystal-placement〕
- **INFO** `PCB1` · U1（网 NRST） —— U1 pin 14 'NRST' @ 'NRST': 3 external member(s) — pull-up candidate (a resistor reaching a supply net): R29 〔MCU 最小系统 / pcb-mcu-reset-boot〕
- **INFO** `PCB1` · U1（网 $1N74472） —— U1 pin 94 'BOOT0' @ '$1N74472': 1 member(s) set the strap — R32 value 10K → other terminals on GND (223.3 mil edge-to-ed… 〔MCU 最小系统 / pcb-mcu-reset-boot〕
- **INFO** `PCB1` · U1（网 AGND） —— U1 supply group 'AGND' — 1 pin(s) (pin 19 'VSSA' (GND)) 〔MCU 最小系统 / pcb-mcu-supply-groups〕
- **INFO** `PCB1` · U1（网 GND） —— U1 supply group 'GND' — 5 pin(s) (pin 10 'VSS' (GND), pin 26 'VSS' (GND), pin 49 'VSS' (GND), pin 74 'VSS' (GND), pin 99… 〔MCU 最小系统 / pcb-mcu-supply-groups〕
- **INFO** `PCB1` · U1（网 VCC） —— U1 supply group 'VCC' — 6 pin(s) (pin 6 'VBAT' (IN), pin 11 'VDD' (IN), pin 27 'VDD' (IN), pin 50 'VDD' (IN), pin 75 'VD… 〔MCU 最小系统 / pcb-mcu-supply-groups〕
- **INFO** `PCB1` · U1（网 VCCA） —— U1 supply group 'VCCA' — 1 pin(s) (pin 21 'VDDA' (IN)) 〔MCU 最小系统 / pcb-mcu-supply-groups〕
- **INFO** `PCB1` · U1（网 VREF） —— U1 supply group 'VREF' — 1 pin(s) (pin 20 'VREF+' (IN)) 〔MCU 最小系统 / pcb-mcu-supply-groups〕
- **INFO** `PCB1` · U1（网 $1N66421） —— U1 pin 48 'VCAP' sits on net '$1N66421', which is an internal-regulator output and **not** a supply group — pin_role ans… 〔MCU 最小系统 / pcb-mcu-supply-groups〕
- **INFO** `PCB1` · U1（网 $1N74470） —— U1 pin 73 'VCAP' sits on net '$1N74470', which is an internal-regulator output and **not** a supply group — pin_role ans… 〔MCU 最小系统 / pcb-mcu-supply-groups〕
- **INFO** `PCB1` · U11（网 +5V） —— U11's nearest high-frequency bypass capacitor on its VIN net '+5V' is C30 at 537.7 mil edge-to-edge (pads 4 / 2) — measu… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U11（网 +5V） —— U11's nearest energy storage capacitor on its VIN net '+5V' is C28 at 32.4 mil edge-to-edge (pads 2 / 2) — measurement o… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U11（网 $1N74453） —— U11 has no high-frequency bypass capacitor measurable against its VOUT net '$1N74453' — the VOUT high-frequency bypass p… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U11（网 $1N74453） —— U11 has no energy storage capacitor measurable against its VOUT net '$1N74453' — the VOUT energy storage pool is empty o… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U13（网 +5V） —— U13's nearest high-frequency bypass capacitor on its VIN net '+5V' is C30 at 58.8 mil edge-to-edge (pads 3 / 1) — measur… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U13（网 +5V） —— U13's nearest energy storage capacitor on its VIN net '+5V' is C38 at 47.9 mil edge-to-edge (pads 1 / 1) — measurement o… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U13（网 $1N66627） —— U13's nearest high-frequency bypass capacitor on its VOUT net '$1N66627' is C41 at 115.9 mil edge-to-edge (pads 5 / 1) —… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U13（网 $1N66627） —— U13's nearest energy storage capacitor on its VOUT net '$1N66627' is C40 at 43.4 mil edge-to-edge (pads 5 / 1) — measure… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U7（网 +24V） —— U7 has no high-frequency bypass capacitor measurable against its VIN net '+24V' — the VIN high-frequency bypass pool is… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U7（网 +24V） —— U7's nearest energy storage capacitor on its VIN net '+24V' is C17 at 26.4 mil edge-to-edge (pads 4 / 1) — measurement o… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U7 —— U7 declares no pin whose name reads as VOUT, so its VOUT side has no net to measure and neither VOUT pool is examined —… 〔电源调节器 / pcb-regulator-cap-distance〕
- **INFO** `PCB1` · U7（网 $1N66466） —— U7's feedback divider R20/R23 at the U7.5 FB pin on '$1N66466': upper leg R20 at 646.4 mil (pads 6 / 1) 〔电源调节器 / pcb-regulator-fb-placement〕

#### FOC/功率驱动（PCB 模块级）—— 0 ERROR / 0 WARN / 38 INFO

- **INFO** `PCB1` · （未点名位号）（网 GHA） —— power-path net 'GHA': 6 track(s), width min 12 mil / max 12 mil, 1282.5 mil total — TI §4's 20 mil reference is quoted i… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 GHB） —— power-path net 'GHB': 8 track(s), width min 10 mil / max 12 mil, 1263.0 mil total — TI §4's 20 mil reference is quoted i… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 GHC） —— power-path net 'GHC': 4 track(s), width min 12 mil / max 12 mil, 525.0 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 GLA） —— power-path net 'GLA': 5 track(s), width min 12 mil / max 12 mil, 1217.5 mil total — TI §4's 20 mil reference is quoted i… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 GLB） —— power-path net 'GLB': 11 track(s), width min 12 mil / max 12 mil, 1417.8 mil total — TI §4's 20 mil reference is quoted… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 GLC） —— power-path net 'GLC': 4 track(s), width min 12 mil / max 12 mil, 234.5 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IA） —— power-path net 'IA': 11 track(s), width min 10 mil / max 10 mil, 854.5 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IA+） —— power-path net 'IA+': 12 track(s), width min 10 mil / max 10 mil, 755.3 mil total — TI §4's 20 mil reference is quoted i… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IA-） —— power-path net 'IA-': 5 track(s), width min 10 mil / max 10 mil, 599.6 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IB） —— power-path net 'IB': 9 track(s), width min 10 mil / max 10 mil, 627.4 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IB+） —— power-path net 'IB+': 8 track(s), width min 10 mil / max 10 mil, 752.2 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IB-） —— power-path net 'IB-': 4 track(s), width min 10 mil / max 10 mil, 572.7 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IC） —— power-path net 'IC': 9 track(s), width min 10 mil / max 10 mil, 615.3 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IC+） —— power-path net 'IC+': 6 track(s), width min 10 mil / max 10 mil, 933.4 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 IC-） —— power-path net 'IC-': 5 track(s), width min 10 mil / max 10 mil, 653.0 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB1` · （未点名位号）（网 PGND、GND） —— ground domain pair 'PGND' (power) ↔ 'GND' (logic): 'PGND' and 'GND' read distance 0.0 but **not overlapping** on any sha… 〔FOC/功率驱动 / pcb-foc-ground-domains〕
- **INFO** `PCB1` · （未点名位号）（网 AGND） —— net 'AGND' breaks into 1 copper island(s) — **one island**, pour area 1.425e+06 sq mil = 28.9% of the board area — INFO… 〔FOC/功率驱动 / pcb-foc-ground-plane〕
- **INFO** `PCB1` · （未点名位号）（网 GND） —— net 'GND' breaks into 28 copper island(s) — **no single island**: the largest is 2.164e+04 sq mil — INFO 出数； 〔FOC/功率驱动 / pcb-foc-ground-plane〕
- **INFO** `PCB1` · （未点名位号）（网 PGND） —— net 'PGND' breaks into 4 copper island(s) — **no single island**: the largest is 3.064e+05 sq mil — INFO 出数； 〔FOC/功率驱动 / pcb-foc-ground-plane〕
- **INFO** `PCB1` · （未点名位号）（网 GHA） —— return-path projection of 'GHA': covered-by-construction 6 over 6 trace(s) — no gap found on any reference layer； 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 GHB） —— return-path projection of 'GHB': covered-by-construction 8 over 8 trace(s) — no gap found on any reference layer； 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 GHC） —— return-path projection of 'GHC': covered-by-construction 2, none 2 over 4 trace(s) — **2 gap(s)** at 36e7f7dcefaa3ea1 (l… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 GLA） —— return-path projection of 'GLA': covered-by-construction 5 over 5 trace(s) — no gap found on any reference layer； 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 GLB） —— return-path projection of 'GLB': covered-by-construction 7, none 4 over 11 trace(s) — **4 gap(s)** at 5610b8971af4a521 (… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 GLC） —— return-path projection of 'GLC': covered-by-construction 4 over 4 trace(s) — no gap found on any reference layer； 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IA） —— return-path projection of 'IA': covered-by-construction 11 over 11 trace(s) — no gap found on any reference layer； 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IA+） —— return-path projection of 'IA+': covered-by-construction 2, none 10 over 12 trace(s) — **10 gap(s)** at baf598ce527f131c… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IA-） —— return-path projection of 'IA-': covered-by-construction 2, none 3 over 5 trace(s) — **3 gap(s)** at 3e9a12919ec977f2 (l… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IB） —— return-path projection of 'IB': covered-by-construction 9 over 9 trace(s) — no gap found on any reference layer； 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IB+） —— return-path projection of 'IB+': covered-by-construction 2, none 5, partial 1 over 8 trace(s) — **6 gap(s)** at d94e41f4… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IB-） —— return-path projection of 'IB-': covered-by-construction 1, none 1, partial 2 over 4 trace(s) — **3 gap(s)** at 0d8665b5… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IC） —— return-path projection of 'IC': covered-by-construction 9 over 9 trace(s) — no gap found on any reference layer； 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IC+） —— return-path projection of 'IC+': covered 1, covered-by-construction 2, none 2, partial 1 over 6 trace(s) — **3 gap(s)**… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 IC-） —— return-path projection of 'IC-': covered 1, covered-by-construction 2, none 1, partial 1 over 5 trace(s) — **2 gap(s)**… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB1` · （未点名位号）（网 $1N66641） —— 55 non-obtuse fold(s) in this board's routing, on 23 net(s) 〔FOC/功率驱动 / pcb-foc-track-corners〕
- **INFO** `PCB1` · （未点名位号）（网 IA+） —— power-path net 'IA+' bends 135.0° at (448.8, -1641.2) on layer 2 (tracks 2b89caa0f8442e14 / 2bbdb921d0bf3fc9) — a measur… 〔FOC/功率驱动 / pcb-foc-track-corners〕
- **INFO** `PCB1` · （未点名位号）（网 IA+） —— power-path net 'IA+' bends 135.0° at (448.8, -1457.4) on layer 2 (tracks 8488aa2c888f0a7f / ff283eb15e9f1b0b) — a measur… 〔FOC/功率驱动 / pcb-foc-track-corners〕
- **INFO** `PCB1` · （未点名位号）（网 IA+） —— power-path net 'IA+' bends 135.0° at (451.1, -1459.8) on layer 2 (tracks 2bc1f10dd75c7b54 / 8488aa2c888f0a7f) — a measur… 〔FOC/功率驱动 / pcb-foc-track-corners〕

#### 安规间距（IPC-2221）（PCB 模块级）—— 0 ERROR / 0 WARN / 3 INFO

- **INFO** `PCB1` · （未点名位号）（网 VCC） —— net 'VCC' has no established voltage, so its spacing against every other net cannot be judged — establish it at requirem… 〔安规间距（IPC-2221） / pcb-voltage-spacing〕
- **INFO** `PCB1` · （未点名位号）（网 VCCA） —— net 'VCCA' has no established voltage, so its spacing against every other net cannot be judged — establish it at require… 〔安规间距（IPC-2221） / pcb-voltage-spacing〕
- **INFO** `PCB1` · （未点名位号）（网 VREF） —— net 'VREF' has no established voltage, so its spacing against every other net cannot be judged — establish it at require… 〔安规间距（IPC-2221） / pcb-voltage-spacing〕

#### 元件参数/选型（通用）—— 0 ERROR / 0 WARN / 9 INFO

- **INFO** `Board1` · R29、C36 —— RC R29(1e+04Ω) + C36(2.2uF) on 'VCC': fc = 7 Hz (-3 dB cutoff 〔元件参数/选型 / param-rc-cutoff〕
- **INFO** `Board1` · R29、C45 —— RC R29(1e+04Ω) + C45(100nF) on 'VCC': fc = 159 Hz (-3 dB cutoff 〔元件参数/选型 / param-rc-cutoff〕
- **INFO** `Board1` · U14、C42 —— RC U14(1000Ω) + C42(10nF) on 'NET13': fc = 15,915 Hz (-3 dB cutoff 〔元件参数/选型 / param-rc-cutoff〕
- **INFO** `Board1` · U14、C41 —— RC U14(1000Ω) + C41(100nF) on 'NET13': fc = 1,592 Hz (-3 dB cutoff 〔元件参数/选型 / param-rc-cutoff〕
- **INFO** `Board1` · U14、C40 —— RC U14(1000Ω) + C40(2.2uF) on 'NET13': fc = 72 Hz (-3 dB cutoff 〔元件参数/选型 / param-rc-cutoff〕
- **INFO** `Board1` · R26、C32 —— RC R26(47Ω) + C32(2.2uF) on '5VA': fc = 1,539 Hz (-3 dB cutoff 〔元件参数/选型 / param-rc-cutoff〕
- **INFO** `Board1` · R26、C33 —— RC R26(47Ω) + C33(10uF) on '5VA': fc = 339 Hz (-3 dB cutoff 〔元件参数/选型 / param-rc-cutoff〕
- **INFO** `Board1` · U11 —— U11 的固定输出是 3.3 V（货架条目 ic.rt9013_33gb 的 Output Voltage = '3.3V'），但它输出轨 NET10 的轨压读不出，所以对拍无从做起：这条轨 'NET10' 的电压只从被审的 U11 自己推… 〔元件参数/选型 / sel-ldo-fixed-output〕
- **INFO** `Board1` · U13 —— U13（value ''，料号 'TPLP2981-30DBVR'，货架条目 C22435132）的固定输出是 3 V（货架条目 ic.tplp2981_30dbvr 的 Output Voltage = '3V'），但货架事实没有指明它的… 〔元件参数/选型 / sel-ldo-fixed-output〕

#### 架构闭合/意图（通用）—— 0 ERROR / 0 WARN / 1 INFO

- **INFO** `Board1` · U1 —— U1 pin14（NRST）在网 'NRST' 上有 4 个成员（U1.14, RST1.1, R29.1, C39.1）—— 复位脚不裸奔（测量行）。 〔架构闭合/意图 / arch-nrst-closure〕

### 板：Board2（PCB 文档 `PCB2`，11 器件，2 铜层，4 ERROR / 0 WARN / 16 INFO）

#### 原理图连通性（通用）—— 4 ERROR / 0 WARN / 0 INFO

- **ERROR** `Board2` · SCREW1 —— SCREW1 is placed on more than one board (Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board2` · SCREW2 —— SCREW2 is placed on more than one board (Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board2` · SCREW3 —— SCREW3 is placed on more than one board (Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕
- **ERROR** `Board2` · SCREW4 —— SCREW4 is placed on more than one board (Board2、Board3) 〔原理图连通性 / conn-duplicate-designators〕

#### Board2/P1（PCB 模块级）—— 0 ERROR / 0 WARN / 1 INFO

- **INFO** `PCB2` · R1 —— this PCB document carries 1 ground-class net(s) and **no power-domain ground**: no net name matches 'PGND', 'P_GND', 'PO… 〔FOC/功率驱动 / pcb-foc-ground-domains〕

#### FOC/功率驱动（PCB 模块级）—— 0 ERROR / 0 WARN / 4 INFO

- **INFO** `PCB2` · （未点名位号） —— no net on this board has a power-path name that core.measure's reader recognises ('GH', 'GL', 'MOT', 'IA', 'IB', 'IC' fa… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB2` · R31 —— this PCB document reads 2 copper layer(s) in its physical stackup, below the 4-layer threshold, so it is a **two-layer b… 〔FOC/功率驱动 / pcb-foc-ground-plane〕
- **INFO** `PCB2` · （未点名位号） —— no power-domain ground on this board (no net name matches 'PGND', 'P_GND', 'POWER_GND', 'EARTH'), so there is no power/l… 〔FOC/功率驱动 / pcb-foc-ground-tie〕
- **INFO** `PCB2` · （未点名位号）（网 $1N11） —— 1 non-obtuse fold(s) in this board's routing, on 1 net(s) 〔FOC/功率驱动 / pcb-foc-track-corners〕

#### 安规间距（IPC-2221）（PCB 模块级）—— 0 ERROR / 0 WARN / 1 INFO

- **INFO** `PCB2` · （未点名位号）（网 VCC） —— net 'VCC' has no established voltage, so its spacing against every other net cannot be judged — establish it at requirem… 〔安规间距（IPC-2221） / pcb-voltage-spacing〕

#### 器件检查（器件级）—— 0 ERROR / 0 WARN / 10 INFO

- **INFO** `PCB2` · R1、R2、R3 —— PCB2 电阻降额读数：认出 4 颗电阻（另有 0 Ω 跳线 0 颗、位号像电阻但值与库件都没说是电阻的 0 颗，本规则不判它们）； 〔器件检查 / pcb-derating-package〕
- **INFO** `PCB2` · SCREW1 —— PCB2 SCREW1 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB2` · SCREW2 —— PCB2 SCREW2 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB2` · SCREW3 —— PCB2 SCREW3 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB2` · SCREW4 —— PCB2 SCREW4 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB2` · （未点名位号） —— PCB2 封装对账（原理图 Board2）：比了 11 个两边都有的器件——一致 7，焊盘数不符 0，尺寸码不符 0，封装族不符 0，无从比较 4，PCB 侧读不出封装 0； 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB2` · （未点名位号） —— PCB2 极性器件读数：0 颗极性器件（其中 0 颗原理图声明了极性脚、0 颗只有库件类型词），涉及 0 种封装名，量出印刷方向标记的 0 颗 〔器件检查 / pcb-polarity-orientation〕
- **INFO** `PCB2` · SCREW1、SCREW2、SCREW3、SCREW4 —— PCB2 有 4 个位号的丝印被关掉（``valueVisible=false``）：板上不会印出这些位号——本规则只报读数，不判「是不是忘了打开」 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB2` · （未点名位号） —— PCB2 TOP_SILK（7 个位号）文字方向分布：90°×3, 270°×4 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB2` · （未点名位号） —— PCB2 丝印读数：11 个位号记录（显示 7、关掉 4），板上焊盘 30 只、器件本体轮廓 7 个； 〔器件检查 / pcb-silk-designator〕

### 板：Board3（PCB 文档 `PCB3`，39 器件，2 铜层，6 ERROR / 1 WARN / 43 INFO）

#### 器件检查（器件级）—— 6 ERROR / 1 WARN / 14 INFO

- **ERROR** `PCB3` · R1 —— R1 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB3` · R2 —— R2 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB3` · R3 —— R3 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB3` · R4 —— R4 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB3` · R5 —— R5 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） 〔器件检查 / pcb-footprint-consistency〕
- **ERROR** `PCB3` · R6 —— R6 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） 〔器件检查 / pcb-footprint-consistency〕
- **WARN** `PCB3` · D2 —— PCB3 D2 的位号丝印压在焊盘上：1 只焊盘被压（最深的 D2 pin 1、15.0 mil），最窄字宽档（0.4）下就已经压上 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB3` · R18、R43、R8 —— PCB3 电阻降额读数：认出 3 颗电阻（另有 0 Ω 跳线 0 颗、位号像电阻但值与库件都没说是电阻的 0 颗，本规则不判它们）； 〔器件检查 / pcb-derating-package〕
- **INFO** `PCB3` · CN3 —— PCB3 CN3 无从比较：原理图没有声明封装（字段是 '-'），没有可比的对造。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB3` · SCREW1 —— PCB3 SCREW1 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB3` · SCREW2 —— PCB3 SCREW2 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB3` · SCREW3 —— PCB3 SCREW3 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB3` · SCREW4 —— PCB3 SCREW4 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB3` · U14 —— PCB3 U14 无从比较：原理图没有声明封装（字段是 '-'），没有可比的对造。 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB3` · （未点名位号） —— PCB3 封装对账（原理图 Board3）：比了 33 个两边都有的器件——一致 27，焊盘数不符 0，尺寸码不符 0，封装族不符 0，无从比较 2，PCB 侧读不出封装 4； 〔器件检查 / pcb-footprint-consistency〕
- **INFO** `PCB3` · C1、C115、C116、C4、C5、C6、P5、D0 —— PCB3 上 6 颗极性器件共用封装 'CAP-TH_BD10.0-P5.00-D0.6-FD-A'（顶层），方向却有 2 种：[0.0, 90.0]——同封装同朝向是生产工艺习惯，不统一只作提醒（岳 2026-10-11 裁：降 INFO… 〔器件检查 / pcb-polarity-orientation〕
- **INFO** `PCB3` · C1、P5、D0、C115、C116、C4、C5、C6 —— PCB3 有 6 颗极性器件的原理图侧**没有声明哪只脚是正极**（符号脚名只有 1/2）：丝印上的方向标记无法与原理图核对，装配只能靠丝印本身——这是原理图符号的事实缺口，本规则如实记下、不猜 〔器件检查 / pcb-polarity-orientation〕
- **INFO** `PCB3` · P5、D0 —— PCB3 极性器件读数：7 颗极性器件（其中 1 颗原理图声明了极性脚、6 颗只有库件类型词），涉及 2 种封装名，量出印刷方向标记的 7 颗 〔器件检查 / pcb-polarity-orientation〕
- **INFO** `PCB3` · C1、C13、CN3、Q1、Q2、Q3、Q4、Q7、Q8、R18、R43、R8、SCREW1、SCREW2、SCREW3、SCREW4、U1、U2 —— PCB3 有 18 个位号的丝印被关掉（``valueVisible=false``）：板上不会印出这些位号——本规则只报读数，不判「是不是忘了打开」 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB3` · （未点名位号） —— PCB3 TOP_SILK（15 个位号）文字方向分布：0°×6, 90°×4, 180°×2, 270°×3； 〔器件检查 / pcb-silk-designator〕
- **INFO** `PCB3` · （未点名位号） —— PCB3 丝印读数：33 个位号记录（显示 15、关掉 18），板上焊盘 125 只、器件本体轮廓 29 个； 〔器件检查 / pcb-silk-designator〕

#### Board3/P1（PCB 模块级）—— 0 ERROR / 0 WARN / 4 INFO

- **INFO** `PCB3` · R1（网 PGND） —— this board carries a power-domain ground (PGND) and **no logic/analog-domain ground**, so R1 has no pair to read and no… 〔FOC/功率驱动 / pcb-foc-ground-domains〕
- **INFO** `PCB3` · C5 —— high-current loop C5 (330uF) ↔ Q1: polygon area 5.878e+04 sq mil, bbox area 2.016e+05 sq mil — **both 口径 are reported**… 〔FOC/功率驱动 / pcb-foc-power-loop-area〕
- **INFO** `PCB3` · C5 —— high-current loop C5 (330uF) ↔ Q3: polygon area 1.642e+04 sq mil, bbox area 9.263e+04 sq mil — **both 口径 are reported**… 〔FOC/功率驱动 / pcb-foc-power-loop-area〕
- **INFO** `PCB3` · C4 —— high-current loop C4 (330uF) ↔ Q7: polygon area 1.091e+05 sq mil, bbox area 2.059e+05 sq mil — **both 口径 are reported**… 〔FOC/功率驱动 / pcb-foc-power-loop-area〕

#### FOC/功率驱动（PCB 模块级）—— 0 ERROR / 0 WARN / 21 INFO

- **INFO** `PCB3` · （未点名位号）（网 GHA） —— power-path net 'GHA': 3 track(s), width min 15 mil / max 15 mil, 356.1 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 GHB） —— power-path net 'GHB': 5 track(s), width min 10 mil / max 10 mil, 479.6 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 GHC） —— power-path net 'GHC': 4 track(s), width min 12 mil / max 12 mil, 280.3 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 GLA） —— power-path net 'GLA': 2 track(s), width min 15 mil / max 15 mil, 262.8 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 GLB） —— power-path net 'GLB': 6 track(s), width min 10 mil / max 12 mil, 277.5 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 GLC） —— power-path net 'GLC': 2 track(s), width min 12 mil / max 12 mil, 161.0 mil total — TI §4's 20 mil reference is quoted in… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 MOTA） —— power-path net 'MOTA': 2 track(s), width min 10 mil / max 10 mil, 370.6 mil total — TI §4's 20 mil reference is quoted i… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 MOTB） —— power-path net 'MOTB': 2 track(s), width min 10 mil / max 10 mil, 288.2 mil total — TI §4's 20 mil reference is quoted i… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · （未点名位号）（网 MOTC） —— power-path net 'MOTC': 2 track(s), width min 10 mil / max 10 mil, 275.6 mil total — TI §4's 20 mil reference is quoted i… 〔FOC/功率驱动 / pcb-foc-gate-trace-width〕
- **INFO** `PCB3` · R31 —— this PCB document reads 2 copper layer(s) in its physical stackup, below the 4-layer threshold, so it is a **two-layer b… 〔FOC/功率驱动 / pcb-foc-ground-plane〕
- **INFO** `PCB3` · （未点名位号）（网 PGND） —— this board carries a power-domain ground (PGND) and no logic/analog ground, so no tie and no 0 Ω search is reported 〔FOC/功率驱动 / pcb-foc-ground-tie〕
- **INFO** `PCB3` · （未点名位号）（网 GHA） —— return-path projection of 'GHA': none 3 over 3 trace(s) — **3 gap(s)** at bec1d962d0b5677b (layer 1→2), aa9fb7fde9dde0bf… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 GHB） —— return-path projection of 'GHB': none 5 over 5 trace(s) — **5 gap(s)** at f8bde6f5b85e9afb (layer 1→2), 52f7a851edd9c280… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 GHC） —— return-path projection of 'GHC': none 4 over 4 trace(s) — **4 gap(s)** at 731fbc0043b5790f (layer 1→2), eb6f39f7fd510437… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 GLA） —— return-path projection of 'GLA': none 2 over 2 trace(s) — **2 gap(s)** at f7fa5d5a8a6b4e16 (layer 1→2), de248d1697722e9a… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 GLB） —— return-path projection of 'GLB': none 6 over 6 trace(s) — **6 gap(s)** at a084c6888a88aa16 (layer 2→1), 3c48593e81bf5e6c… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 GLC） —— return-path projection of 'GLC': none 2 over 2 trace(s) — **2 gap(s)** at 8c6940c6f38dcd80 (layer 1→2), 64c3a17c5b96d57a… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 MOTA） —— return-path projection of 'MOTA': none 2 over 2 trace(s) — **2 gap(s)** at 16a9cfeab7466f2c (layer 1→2), ccf296e66381db6… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 MOTB） —— return-path projection of 'MOTB': none 2 over 2 trace(s) — **2 gap(s)** at 5d02eff9faf4784b (layer 1→2), 75479c77771d6b5… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号）（网 MOTC） —— return-path projection of 'MOTC': none 2 over 2 trace(s) — **2 gap(s)** at 35d0f2e6c1553873 (layer 1→2), 58f6fc04c7ebbbc… 〔FOC/功率驱动 / pcb-foc-return-path〕
- **INFO** `PCB3` · （未点名位号） —— this board has **no non-obtuse fold** in its routing — every one of its 29 track(s) either runs straight through a joint… 〔FOC/功率驱动 / pcb-foc-track-corners〕

#### 元件参数/选型（通用）—— 0 ERROR / 0 WARN / 1 INFO

- **INFO** `Board3` · D2 —— D2: 关断电压 40 V ≥ 所挂轨 +24V = 24 V，比值 1.67x； 〔元件参数/选型 / sel-tvs-standoff-rail〕

#### 原理图连通性（通用）—— 0 ERROR / 0 WARN / 3 INFO

- **INFO** `Board3` · R43、L1 —— R43 (10mΩ): no IC pins found on its terminal nets IA+ / PGND. L1 capability boundary: the sense link may run through ser… 〔原理图连通性 / shunt-sense-link〕
- **INFO** `Board3` · R8、L1 —— R8 (10mΩ): no IC pins found on its terminal nets IB+ / PGND. L1 capability boundary: the sense link may run through seri… 〔原理图连通性 / shunt-sense-link〕
- **INFO** `Board3` · R18、L1 —— R18 (10mΩ): no IC pins found on its terminal nets PGND / Symbol. L1 capability boundary: the sense link may run through… 〔原理图连通性 / shunt-sense-link〕

**整工程合计：50 ERROR / 7 WARN / 167 INFO**

## 完成状态（completion）

**verdict：`incomplete`**（50 项 ERROR；116 颗器件缺手册未审；7 条 warning 待分诊）

- 检查范围：23 条规则 / 3 块板 / 4 页
- 欠账：ERROR 50 · 未审器件 116 · 待分诊 warning 7 · 架构槽位 stale 0（槽位 264，已填 0，TODO 264）
- 覆盖：解析完整 · 少页 0 · 规则 withheld 结论 0 · 解析丢弃记录 0 · 规则报错 0
- 源版本：ruleset `a0c5e0a0` · rulebody `dad6b777`
- 注意：`summary.mayClaimPassed` 是**窄义**字段（只回答「有没有器件缺手册未审」）；完整结论以本节的 `verdict` 为准。

## 错误（ERROR）

- `ERROR` 1x conn-duplicate-designators（findings[0]）
- `ERROR` 1x conn-duplicate-designators（findings[1]）
- `ERROR` 1x conn-duplicate-designators（findings[2]）
- `ERROR` 1x conn-duplicate-designators（findings[3]）
- `ERROR` 1x conn-duplicate-designators（findings[4]）
- `ERROR` 1x conn-duplicate-designators（findings[5]）
- `ERROR` 1x conn-duplicate-designators（findings[6]）
- `ERROR` 1x conn-duplicate-designators（findings[7]）
- `ERROR` 1x conn-duplicate-designators（findings[8]）
- `ERROR` 1x conn-duplicate-designators（findings[9]）
- `ERROR` 1x conn-duplicate-designators（findings[10]）
- `ERROR` 1x conn-duplicate-designators（findings[11]）
- `ERROR` 1x conn-duplicate-designators（findings[12]）
- `ERROR` 1x conn-duplicate-designators（findings[13]）
- `ERROR` 1x conn-duplicate-designators（findings[14]）
- `ERROR` 1x conn-duplicate-designators（findings[15]）
- `ERROR` 1x conn-duplicate-designators（findings[16]）
- `ERROR` 1x conn-duplicate-designators（findings[17]）
- `ERROR` 1x conn-duplicate-designators（findings[18]）
- `ERROR` 1x conn-duplicate-designators（findings[19]）
- `ERROR` 1x conn-duplicate-designators（findings[20]）
- `ERROR` 1x conn-duplicate-designators（findings[21]）
- `ERROR` 1x conn-duplicate-designators（findings[22]）
- `ERROR` 1x conn-duplicate-designators（findings[23]）
- `ERROR` 1x conn-duplicate-designators（findings[24]）
- `ERROR` 1x conn-duplicate-designators（findings[25]）
- `ERROR` 1x conn-duplicate-designators（findings[26]）
- `ERROR` 1x conn-duplicate-designators（findings[27]）
- `ERROR` 1x conn-duplicate-designators（findings[28]）
- `ERROR` 1x conn-duplicate-designators（findings[29]）
- `ERROR` 1x pcb-footprint-consistency（findings[45]）
- `ERROR` 1x pcb-footprint-consistency（findings[46]）
- `ERROR` 1x pcb-footprint-consistency（findings[47]）
- `ERROR` 1x pcb-footprint-consistency（findings[48]）
- `ERROR` 1x pcb-footprint-consistency（findings[49]）
- `ERROR` 1x pcb-footprint-consistency（findings[50]）
- `ERROR` 1x pcb-footprint-consistency（findings[91]）
- `ERROR` 1x pcb-footprint-consistency（findings[92]）
- `ERROR` 1x pcb-footprint-consistency（findings[93]）
- `ERROR` 1x pcb-footprint-consistency（findings[94]）
- `ERROR` 1x pcb-footprint-consistency（findings[95]）
- `ERROR` 1x pcb-footprint-consistency（findings[96]）
- `ERROR` 1x pcb-footprint-consistency（findings[97]）
- `ERROR` 1x pcb-footprint-consistency（findings[98]）
- `ERROR` 1x pcb-footprint-consistency（findings[99]）
- `ERROR` 1x pcb-footprint-consistency（findings[100]）
- `ERROR` 1x pcb-footprint-consistency（findings[101]）
- `ERROR` 1x pcb-footprint-consistency（findings[102]）
- `ERROR` 1x pcb-footprint-consistency（findings[103]）
- `ERROR` 1x pcb-footprint-consistency（findings[104]）

## 未审器件（116）

本节非空时**不得宣称审查通过**：只能说 DRC/连接性已审，116 颗器件缺手册未审。三通道（工程师给 / 立创找 / 官网搜）逐条列在下面。

| 位号 | MPN | 供应商 | 缺哪些 fact | 工程师给 | 立创找 | 官网搜 |
|---|---|---|---|---|---|---|
| C10 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C11 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C12 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C13 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C15 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C16 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C17 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C18 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C2 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C20 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C21 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C22 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C23 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C24 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C25 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C3 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C32 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C33 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C34 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C37 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C38 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C39 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C4 | CGA0805X5R106K500MT | C6119889 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C40 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C45 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C46 | C1608X5R1V225KT000E | C342978 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C5 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C6 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C7 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C8 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C9 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L1 | FXL1040-330-M | C475918 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L2 | DFE252012PD-2R2M=P2 | C237482 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L3 | DFE252012PD-2R2M=P2 | C237482 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L4 | DFE252012PD-2R2M=P2 | C237482 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R1 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R10 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R11 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R12 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R13 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R14 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R15 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R16 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R17 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R18 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R19 | RCA03392KFLF | C22369707 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目只有商品页链接（PDF 链接要回商品页取） | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R2 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R20 | 0805W8F1003T5E | C149504 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R21 | FRC0805F4122TS | C2933440 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R22 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R23 | 0805W8F1003T5E | C149504 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R24 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R25 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R26 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R27 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R28 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R29 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R3 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R30 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R31 | 0603WAF1503T5E | C22807 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R32 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R4 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R5 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R6 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R7 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R8 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R9 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U1 | STM32H743VIT6 | C114409 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U10 | FRC0805J471 TS | C2907329 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U13 | TPLP2981-30DBVR | C22435132 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U14 | FRC0805J471 TS | C2907329 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U2 | DRV8350SRTVR | C2861195 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U3 | ZX-MX1.25-4PWT | C7430470 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U4 | HX PZ2.54-2x6P TP | C32713286 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U6 | HX PZ2.54-2x6P TP | C32713286 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U7 | LM5164DDAR | C477928 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U8 | MX1.25-LT-3 | C9900097986 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C1 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R1 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R2 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R3 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R4 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW1 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW2 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW3 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW4 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U1 | TLE5012BE1000 | C123083 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C1 | PA50V330M10x15 | C46550457 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C10 | HGC1206R5106K500NSPJ | C7432781 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C11 | HGC1206R5106K500NSPJ | C7432781 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C115 | PA50V330M10x15 | C46550457 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C116 | PA50V330M10x15 | C46550457 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C12 | HGC1206R5106K500NSPJ | C7432781 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C2 | CGA0603X7R104K500JT | C6119867 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C4 | PA50V330M10x15 | C46550457 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C5 | PA50V330M10x15 | C46550457 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C6 | PA50V330M10x15 | C46550457 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C7 | HGC1206R5106K500NSPJ | C7432781 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C8 | HGC1206R5106K500NSPJ | C7432781 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C9 | HGC1206R5106K500NSPJ | C7432781 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R1 | 0805W8J0100T5E | C25278 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R18 | JER2512F3R005 | C46634460 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R2 | 0805W8J0100T5E | C25278 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R3 | 0805W8J0100T5E | C25278 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R4 | 0805W8J0100T5E | C25278 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R43 | JER2512F3R005 | C46634460 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R5 | 0805W8J0100T5E | C25278 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R6 | 0805W8J0100T5E | C25278 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R8 | JER2512F3R005 | C46634460 | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW1 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW2 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW3 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW4 |  |  | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U1 | PZ2.54-2*6 | C5224012 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U14 | MR30PW-M30.G.Y | C19268036 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U2 | PZ2.54-2*6 | C5224012 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |

- `C10` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C11` 官网通道建议查询词：`100pF datasheet pdf`；`100pF 数据手册 规格书`
- `C12` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C13` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C15` 官网通道建议查询词：`2.2uF datasheet pdf`；`2.2uF 数据手册 规格书`
- `C16` 官网通道建议查询词：`100pF datasheet pdf`；`100pF 数据手册 规格书`
- `C17` 官网通道建议查询词：`4.7UF datasheet pdf`；`4.7UF 数据手册 规格书`
- `C18` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C2` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C20` 官网通道建议查询词：`20pF datasheet pdf`；`20pF 数据手册 规格书`
- `C21` 官网通道建议查询词：`20pF datasheet pdf`；`20pF 数据手册 规格书`
- `C22` 官网通道建议查询词：`56pF datasheet pdf`；`56pF 数据手册 规格书`
- `C23` 官网通道建议查询词：`22uF datasheet pdf`；`22uF 数据手册 规格书`
- `C24` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C25` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C3` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C32` 官网通道建议查询词：`2.2uF datasheet pdf`；`2.2uF 数据手册 规格书`
- `C33` 官网通道建议查询词：`10uF datasheet pdf`；`10uF 数据手册 规格书`
- `C34` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C37` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C38` 官网通道建议查询词：`2.2uF datasheet pdf`；`2.2uF 数据手册 规格书`
- `C39` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `C4` 官网通道建议查询词：`CGA0805X5R106K500MT datasheet pdf`；`CGA0805X5R106K500MT 数据手册`；`HRE(芯声) CGA0805X5R106K500MT datasheet`；`CGA0805X5R106K500MT site:hre.com`
- `C40` 官网通道建议查询词：`2.2uF datasheet pdf`；`2.2uF 数据手册 规格书`
- `C45` 官网通道建议查询词：`100nF datasheet pdf`；`100nF 数据手册 规格书`
- `C46` 官网通道建议查询词：`C1608X5R1V225KT000E datasheet pdf`；`C1608X5R1V225KT000E 数据手册`；`TDK C1608X5R1V225KT000E datasheet`；`C1608X5R1V225KT000E site:tdk.com`
- `C5` 官网通道建议查询词：`1uF datasheet pdf`；`1uF 数据手册 规格书`
- `C6` 官网通道建议查询词：`1uF datasheet pdf`；`1uF 数据手册 规格书`
- `C7` 官网通道建议查询词：`1uF datasheet pdf`；`1uF 数据手册 规格书`
- `C8` 官网通道建议查询词：`100pF datasheet pdf`；`100pF 数据手册 规格书`
- `C9` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `L1` 官网通道建议查询词：`FXL1040-330-M datasheet pdf`；`FXL1040-330-M 数据手册`；`cjiang(长江微电) FXL1040-330-M datasheet`；`FXL1040-330-M site:cjiang.com`
- `L2` 官网通道建议查询词：`DFE252012PD-2R2M=P2 datasheet pdf`；`DFE252012PD-2R2M=P2 数据手册`；`muRata(村田) DFE252012PD-2R2M=P2 datasheet`；`DFE252012PD-2R2M=P2 site:murata.com`
- `L3` 官网通道建议查询词：`DFE252012PD-2R2M=P2 datasheet pdf`；`DFE252012PD-2R2M=P2 数据手册`；`muRata(村田) DFE252012PD-2R2M=P2 datasheet`；`DFE252012PD-2R2M=P2 site:murata.com`
- `L4` 官网通道建议查询词：`DFE252012PD-2R2M=P2 datasheet pdf`；`DFE252012PD-2R2M=P2 数据手册`；`muRata(村田) DFE252012PD-2R2M=P2 datasheet`；`DFE252012PD-2R2M=P2 site:murata.com`
- `R1` 官网通道建议查询词：`15K datasheet pdf`；`15K 数据手册 规格书`
- `R10` 官网通道建议查询词：`1K datasheet pdf`；`1K 数据手册 规格书`
- `R11` 官网通道建议查询词：`0R datasheet pdf`；`0R 数据手册 规格书`
- `R12` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `R13` 官网通道建议查询词：`15K datasheet pdf`；`15K 数据手册 规格书`
- `R14` 官网通道建议查询词：`15K datasheet pdf`；`15K 数据手册 规格书`
- `R15` 官网通道建议查询词：`1K datasheet pdf`；`1K 数据手册 规格书`
- `R16` 官网通道建议查询词：`1K datasheet pdf`；`1K 数据手册 规格书`
- `R17` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `R18` 官网通道建议查询词：`15K datasheet pdf`；`15K 数据手册 规格书`
- `R19` 官网通道建议查询词：`RCA03392KFLF datasheet pdf`；`RCA03392KFLF 数据手册`；`HKR(香港电阻) RCA03392KFLF datasheet`；`RCA03392KFLF site:hkr.com`
- `R2` 官网通道建议查询词：`1K datasheet pdf`；`1K 数据手册 规格书`
- `R20` 官网通道建议查询词：`0805W8F1003T5E datasheet pdf`；`0805W8F1003T5E 数据手册`；`UNI-ROYAL(厚声) 0805W8F1003T5E datasheet`；`0805W8F1003T5E site:uni-royal.com`
- `R21` 官网通道建议查询词：`FRC0805F4122TS datasheet pdf`；`FRC0805F4122TS 数据手册`；`FOJAN(富捷) FRC0805F4122TS datasheet`；`FRC0805F4122TS site:fojan.com`
- `R22` 官网通道建议查询词：`5.1K datasheet pdf`；`5.1K 数据手册 规格书`
- `R23` 官网通道建议查询词：`0805W8F1003T5E datasheet pdf`；`0805W8F1003T5E 数据手册`；`UNI-ROYAL(厚声) 0805W8F1003T5E datasheet`；`0805W8F1003T5E site:uni-royal.com`
- `R24` 官网通道建议查询词：`5.1K datasheet pdf`；`5.1K 数据手册 规格书`
- `R25` 官网通道建议查询词：`0R datasheet pdf`；`0R 数据手册 规格书`
- `R26` 官网通道建议查询词：`47R datasheet pdf`；`47R 数据手册 规格书`
- `R27` 官网通道建议查询词：`4.7K datasheet pdf`；`4.7K 数据手册 规格书`
- `R28` 官网通道建议查询词：`120R datasheet pdf`；`120R 数据手册 规格书`
- `R29` 官网通道建议查询词：`10K datasheet pdf`；`10K 数据手册 规格书`
- `R3` 官网通道建议查询词：`0R datasheet pdf`；`0R 数据手册 规格书`
- `R30` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `R31` 官网通道建议查询词：`0603WAF1503T5E datasheet pdf`；`0603WAF1503T5E 数据手册`；`UNI-ROYAL(厚声) 0603WAF1503T5E datasheet`；`0603WAF1503T5E site:uni-royal.com`
- `R32` 官网通道建议查询词：`10K datasheet pdf`；`10K 数据手册 规格书`
- `R4` 官网通道建议查询词：`1K datasheet pdf`；`1K 数据手册 规格书`
- `R5` 官网通道建议查询词：`15K datasheet pdf`；`15K 数据手册 规格书`
- `R6` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `R7` 官网通道建议查询词：`15K datasheet pdf`；`15K 数据手册 规格书`
- `R8` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `R9` 官网通道建议查询词：`1K datasheet pdf`；`1K 数据手册 规格书`
- `U1` 官网通道建议查询词：`STM32H743VIT6 datasheet pdf`；`STM32H743VIT6 数据手册`；`ST(意法半导体) STM32H743VIT6 datasheet`；`STM32H743VIT6 site:st.com`
- `U10` 官网通道建议查询词：`FRC0805J471 TS datasheet pdf`；`FRC0805J471 TS 数据手册`；`FOJAN(富捷) FRC0805J471 TS datasheet`；`FRC0805J471 TS site:fojan.com`
- `U13` 官网通道建议查询词：`TPLP2981-30DBVR datasheet pdf`；`TPLP2981-30DBVR 数据手册`；`TECH PUBLIC(台舟) TPLP2981-30DBVR datasheet`；`TPLP2981-30DBVR site:tech public.com`
- `U14` 官网通道建议查询词：`FRC0805J471 TS datasheet pdf`；`FRC0805J471 TS 数据手册`；`FOJAN(富捷) FRC0805J471 TS datasheet`；`FRC0805J471 TS site:fojan.com`
- `U2` 官网通道建议查询词：`DRV8350SRTVR datasheet pdf`；`DRV8350SRTVR 数据手册`；`TI(德州仪器) DRV8350SRTVR datasheet`；`DRV8350SRTVR site:ti.com`
- `U3` 官网通道建议查询词：`ZX-MX1.25-4PWT datasheet pdf`；`ZX-MX1.25-4PWT 数据手册`；`Megastar(兆星) ZX-MX1.25-4PWT datasheet`；`ZX-MX1.25-4PWT site:megastar.com`
- `U4` 官网通道建议查询词：`HX PZ2.54-2x6P TP datasheet pdf`；`HX PZ2.54-2x6P TP 数据手册`；`hanxia(韩下) HX PZ2.54-2x6P TP datasheet`；`HX PZ2.54-2x6P TP site:hanxia.com`
- `U6` 官网通道建议查询词：`HX PZ2.54-2x6P TP datasheet pdf`；`HX PZ2.54-2x6P TP 数据手册`；`hanxia(韩下) HX PZ2.54-2x6P TP datasheet`；`HX PZ2.54-2x6P TP site:hanxia.com`
- `U7` 官网通道建议查询词：`LM5164DDAR datasheet pdf`；`LM5164DDAR 数据手册`；`TI(德州仪器) LM5164DDAR datasheet`；`LM5164DDAR site:ti.com`
- `U8` 官网通道建议查询词：`MX1.25-LT-3 datasheet pdf`；`MX1.25-LT-3 数据手册`
- `C1` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `R1` 官网通道建议查询词：`100R datasheet pdf`；`100R 数据手册 规格书`
- `R2` 官网通道建议查询词：`100R datasheet pdf`；`100R 数据手册 规格书`
- `R3` 官网通道建议查询词：`100R datasheet pdf`；`100R 数据手册 规格书`
- `R4` 官网通道建议查询词：`100R datasheet pdf`；`100R 数据手册 规格书`
- `SCREW1` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `SCREW2` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `SCREW3` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `SCREW4` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `U1` 官网通道建议查询词：`TLE5012BE1000 datasheet pdf`；`TLE5012BE1000 数据手册`；`Infineon(英飞凌) TLE5012BE1000 datasheet`；`TLE5012BE1000 site:infineon.com`
- `C1` 官网通道建议查询词：`PA50V330M10x15 datasheet pdf`；`PA50V330M10x15 数据手册`；`JIERR(捷而瑞) PA50V330M10x15 datasheet`；`PA50V330M10x15 site:jierr.com`
- `C10` 官网通道建议查询词：`HGC1206R5106K500NSPJ datasheet pdf`；`HGC1206R5106K500NSPJ 数据手册`
- `C11` 官网通道建议查询词：`HGC1206R5106K500NSPJ datasheet pdf`；`HGC1206R5106K500NSPJ 数据手册`
- `C115` 官网通道建议查询词：`PA50V330M10x15 datasheet pdf`；`PA50V330M10x15 数据手册`；`JIERR(捷而瑞) PA50V330M10x15 datasheet`；`PA50V330M10x15 site:jierr.com`
- `C116` 官网通道建议查询词：`PA50V330M10x15 datasheet pdf`；`PA50V330M10x15 数据手册`；`JIERR(捷而瑞) PA50V330M10x15 datasheet`；`PA50V330M10x15 site:jierr.com`
- `C12` 官网通道建议查询词：`HGC1206R5106K500NSPJ datasheet pdf`；`HGC1206R5106K500NSPJ 数据手册`
- `C2` 官网通道建议查询词：`CGA0603X7R104K500JT datasheet pdf`；`CGA0603X7R104K500JT 数据手册`；`HRE(芯声) CGA0603X7R104K500JT datasheet`；`CGA0603X7R104K500JT site:hre.com`
- `C4` 官网通道建议查询词：`PA50V330M10x15 datasheet pdf`；`PA50V330M10x15 数据手册`；`JIERR(捷而瑞) PA50V330M10x15 datasheet`；`PA50V330M10x15 site:jierr.com`
- `C5` 官网通道建议查询词：`PA50V330M10x15 datasheet pdf`；`PA50V330M10x15 数据手册`；`JIERR(捷而瑞) PA50V330M10x15 datasheet`；`PA50V330M10x15 site:jierr.com`
- `C6` 官网通道建议查询词：`PA50V330M10x15 datasheet pdf`；`PA50V330M10x15 数据手册`；`JIERR(捷而瑞) PA50V330M10x15 datasheet`；`PA50V330M10x15 site:jierr.com`
- `C7` 官网通道建议查询词：`HGC1206R5106K500NSPJ datasheet pdf`；`HGC1206R5106K500NSPJ 数据手册`
- `C8` 官网通道建议查询词：`HGC1206R5106K500NSPJ datasheet pdf`；`HGC1206R5106K500NSPJ 数据手册`
- `C9` 官网通道建议查询词：`HGC1206R5106K500NSPJ datasheet pdf`；`HGC1206R5106K500NSPJ 数据手册`
- `R1` 官网通道建议查询词：`0805W8J0100T5E datasheet pdf`；`0805W8J0100T5E 数据手册`
- `R18` 官网通道建议查询词：`JER2512F3R005 datasheet pdf`；`JER2512F3R005 数据手册`；`JIERR(捷而瑞) JER2512F3R005 datasheet`；`JER2512F3R005 site:jierr.com`
- `R2` 官网通道建议查询词：`0805W8J0100T5E datasheet pdf`；`0805W8J0100T5E 数据手册`
- `R3` 官网通道建议查询词：`0805W8J0100T5E datasheet pdf`；`0805W8J0100T5E 数据手册`
- `R4` 官网通道建议查询词：`0805W8J0100T5E datasheet pdf`；`0805W8J0100T5E 数据手册`
- `R43` 官网通道建议查询词：`JER2512F3R005 datasheet pdf`；`JER2512F3R005 数据手册`；`JIERR(捷而瑞) JER2512F3R005 datasheet`；`JER2512F3R005 site:jierr.com`
- `R5` 官网通道建议查询词：`0805W8J0100T5E datasheet pdf`；`0805W8J0100T5E 数据手册`
- `R6` 官网通道建议查询词：`0805W8J0100T5E datasheet pdf`；`0805W8J0100T5E 数据手册`
- `R8` 官网通道建议查询词：`JER2512F3R005 datasheet pdf`；`JER2512F3R005 数据手册`；`JIERR(捷而瑞) JER2512F3R005 datasheet`；`JER2512F3R005 site:jierr.com`
- `SCREW1` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `SCREW2` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `SCREW3` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `SCREW4` 官网通道建议查询词：`(没有 MPN) datasheet pdf`；`(没有 MPN) 数据手册 规格书`
- `U1` 官网通道建议查询词：`PZ2.54-2*6 datasheet pdf`；`PZ2.54-2*6 数据手册`
- `U14` 官网通道建议查询词：`MR30PW-M30.G.Y datasheet pdf`；`MR30PW-M30.G.Y 数据手册`
- `U2` 官网通道建议查询词：`PZ2.54-2*6 datasheet pdf`；`PZ2.54-2*6 数据手册`

每个器件问同一件事：核对该器件周边配置是否符合规格书典型应用（去耦/上下拉/限流/耐压），并确认可用型号

## 本报告依赖的未知项（needs_datasheet：facts 85 条 / 审查者标记 0 项）

本节非空期间，本报告不得宣称审查通过。

### facts 触发（规则判不了的器件，85 条）

| 位号 | MPN | 供应商 | 缺哪些 fact | 为什么在清单上 | 依赖的 findings | 工程师给 | 立创找 | 官网搜 |
|---|---|---|---|---|---|---|---|---|
| C10 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C10、pcb-silk-designator@C10 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C11 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C11、pcb-derating-package@C11、pcb-silk-designator@C11 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C12 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C12、pcb-silk-designator@C12 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C13 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C13、pcb-silk-designator@C13 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C15 |  |  | — | 无 MPN；供应商字段为空 | pcb-derating-package@C15、pcb-silk-designator@C15 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C16 |  |  | — | 无 MPN；供应商字段为空 | pcb-derating-package@C16、pcb-silk-designator@C16 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C17 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C17 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C18 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C18 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C2 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C2、pcb-silk-designator@C2 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C20 |  |  | — | 无 MPN；供应商字段为空 | pcb-mcu-crystal-placement@C20、pcb-silk-designator@C20 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C21 |  |  | — | 无 MPN；供应商字段为空 | pcb-mcu-crystal-placement@C21、pcb-silk-designator@C21 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C22 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C22 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C23 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C23 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C24 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C24 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C25 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C25 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C3 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C3、pcb-foc-decap-proximity@C3、pcb-silk-designator@C3 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C32 |  |  | — | 无 MPN；供应商字段为空 | param-rc-cutoff@C32、pcb-silk-designator@C32 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C33 |  |  | — | 无 MPN；供应商字段为空 | param-rc-cutoff@C33、pcb-silk-designator@C33 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C34 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C34 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C37 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C37 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C38 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C38 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C39 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@C39 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C4 | CGA0805X5R106K500MT | C6119889 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | conn-duplicate-designators@C4、pcb-foc-power-loop-area@C4、pcb-polarity-orientation@C4、pcb-foc-decap-proximity@C4、pcb-silk-designator@C4 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C40 |  |  | — | 无 MPN；供应商字段为空 | param-rc-cutoff@C40、pcb-silk-designator@C40 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C45 |  |  | — | 无 MPN；供应商字段为空 | param-rc-cutoff@C45、pcb-silk-designator@C45 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C46 | C1608X5R1V225KT000E | C342978 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-silk-designator@C46 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C5 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C5、pcb-foc-power-loop-area@C5、pcb-polarity-orientation@C5、pcb-silk-designator@C5 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C6 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C6、pcb-polarity-orientation@C6、pcb-silk-designator@C6 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C7 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C7、pcb-foc-decap-proximity@C7、pcb-silk-designator@C7 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C8 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C8、pcb-silk-designator@C8 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C9 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C9、pcb-silk-designator@C9 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L1 | FXL1040-330-M | C475918 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | shunt-sense-link@L1、pcb-silk-designator@L1 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L2 | DFE252012PD-2R2M=P2 | C237482 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-silk-designator@L2 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L3 | DFE252012PD-2R2M=P2 | C237482 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-silk-designator@L3 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| L4 | DFE252012PD-2R2M=P2 | C237482 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-silk-designator@L4 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R1 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R1、pcb-footprint-consistency@R1、pcb-foc-ground-domains@R1、pcb-silk-designator@R1、pcb-derating-package@R1 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R10 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R10 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R11 |  |  | — | 无 MPN；供应商字段为空 | pcb-derating-package@R11、pcb-foc-ground-domains@R11、pcb-foc-ground-tie@R11、pcb-foc-return-path@R11、pcb-silk-designator@R11 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R12 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R12 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R13 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R13 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R14 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R14 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R15 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R15 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R16 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R16 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R17 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R17 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R18 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R18、shunt-sense-link@R18、pcb-derating-package@R18、pcb-silk-designator@R18、pcb-component-spacing@R18 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R19 | RCA03392KFLF | C22369707 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-silk-designator@R19 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目只有商品页链接（PDF 链接要回商品页取） | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R2 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R2、pcb-footprint-consistency@R2、pcb-silk-designator@R2、pcb-derating-package@R2 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R20 | 0805W8F1003T5E | C149504 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-silk-designator@R20 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R21 | FRC0805F4122TS | C2933440 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-silk-designator@R21 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R22 |  |  | — | 无 MPN；供应商字段为空 | pcb-component-spacing@R22、pcb-silk-designator@R22 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R23 | 0805W8F1003T5E | C149504 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | — | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R24 |  |  | — | 无 MPN；供应商字段为空 | pcb-component-spacing@R24、pcb-silk-designator@R24 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R25 |  |  | — | 无 MPN；供应商字段为空 | pcb-derating-package@R25、pcb-foc-ground-tie@R25、pcb-silk-designator@R25 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R26 |  |  | — | 无 MPN；供应商字段为空 | param-rc-cutoff@R26、pcb-silk-designator@R26 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R27 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R27 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R28 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R28 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R29 |  |  | — | 无 MPN；供应商字段为空 | param-rc-cutoff@R29、pcb-silk-designator@R29 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R3 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R3、pcb-footprint-consistency@R3、pcb-derating-package@R3、pcb-foc-ground-tie@R3、pcb-silk-designator@R3 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R30 |  |  | — | 无 MPN；供应商字段为空 | pcb-foc-ground-domains@R30、pcb-silk-designator@R30 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R31 | 0603WAF1503T5E | C22807 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-foc-ground-plane@R31、pcb-silk-designator@R31 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R32 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R32 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R4 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R4、pcb-footprint-consistency@R4、pcb-silk-designator@R4 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R5 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R5、pcb-footprint-consistency@R5、pcb-silk-designator@R5 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R6 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R6、pcb-footprint-consistency@R6、pcb-silk-designator@R6 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R7 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R7 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R8 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@R8、shunt-sense-link@R8、pcb-derating-package@R8、pcb-silk-designator@R8 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R9 |  |  | — | 无 MPN；供应商字段为空 | pcb-silk-designator@R9 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U1 | STM32H743VIT6 | C114409 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | conn-duplicate-designators@U1、arch-nrst-closure@U1、pcb-silk-designator@U1、pcb-mcu-crystal-placement@U1、pcb-mcu-reset-boot@U1、pcb-mcu-supply-groups@U1 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U10 | FRC0805J471 TS | C2907329 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | pcb-footprint-consistency@U10、pcb-silk-designator@U10 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U13 | TPLP2981-30DBVR | C22435132 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | sel-ldo-fixed-output@U13、pcb-decap-distance@U13、pcb-regulator-cap-distance@U13、pcb-silk-designator@U13 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U14 | FRC0805J471 TS | C2907329 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | conn-duplicate-designators@U14、param-rc-cutoff@U14、pcb-footprint-consistency@U14、pcb-silk-designator@U14 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U2 | DRV8350SRTVR | C2861195 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | conn-duplicate-designators@U2、pcb-silk-designator@U2、pcb-foc-return-path@U2、pcb-foc-thermal-exit-path@U2、pcb-foc-thermal-via-array@U2、pcb-foc-thermal-via-style@U2 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U3 | ZX-MX1.25-4PWT | C7430470 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | pcb-silk-designator@U3 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U4 | HX PZ2.54-2x6P TP | C32713286 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | pcb-silk-designator@U4 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U6 | HX PZ2.54-2x6P TP | C32713286 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | pcb-silk-designator@U6 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U7 | LM5164DDAR | C477928 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | pcb-decap-distance@U7、pcb-regulator-cap-distance@U7、pcb-regulator-fb-placement@U7、pcb-silk-designator@U7 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| U8 | MX1.25-LT-3 | C9900097986 | supply_pins、required_caps、nc_pins、must_connect、led、ldo、pull_required | 货架没有可驱动规则的 facts（条目没有 facts） | pcb-component-spacing@U8、pcb-silk-designator@U8 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C1 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@C1、pcb-polarity-orientation@C1、pcb-silk-designator@C1 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW1 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@SCREW1、pcb-footprint-consistency@SCREW1、pcb-silk-designator@SCREW1 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW2 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@SCREW2、pcb-footprint-consistency@SCREW2、pcb-silk-designator@SCREW2 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW3 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@SCREW3、pcb-footprint-consistency@SCREW3、pcb-silk-designator@SCREW3 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| SCREW4 |  |  | — | 无 MPN；供应商字段为空 | conn-duplicate-designators@SCREW4、pcb-footprint-consistency@SCREW4、pcb-silk-designator@SCREW4 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 没有 —— 库条目没有任何 datasheet 链接 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C115 | PA50V330M10x15 | C46550457 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-polarity-orientation@C115 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| C116 | PA50V330M10x15 | C46550457 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | pcb-polarity-orientation@C116 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |
| R43 | JER2512F3R005 | C46634460 | — | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） | shunt-sense-link@R43、pcb-derating-package@R43、pcb-silk-designator@R43 | 没有 —— .tmp_datasheets/ 下没有这颗料的 PDF（工程师给手册用 `parts fetch --file`） | 有 —— 库条目自带 PDF 链接，`parts fetch` 可直接下载 | 未（AI 走） —— CLI 不搜官网：这一通道由 AI 用 WebSearch 走，报告只给建议查询词与厂商名 |

同一器件两源命中时按 marked 展示（该条 `factSeed: true`），计数只算一次；每个器件问同一件事：核对该器件周边配置是否符合规格书典型应用（去耦/上下拉/限流/耐压），并确认可用型号

## 主机 DRC

- 原理图 ERC：**未检查** —— 离线路径（--file）不连编辑器，因此没有主机 ERC；这一段的空是「没查」，不是「零错误」
- PCB DRC：**未检查** —— 离线路径（--file）不连编辑器，因此没有主机 PCB DRC；要它就给一个在线工程


- PCB DRC 规则集：**未读** —— 离线路径（--file）不连编辑器，因此没有主机 DRC 规则集；离线也读不到规则集（它在编辑器里，不在归档里）

## 模块

### Board1

#### Board1/P1（105 器件）

- 依据：page
- 板：Board1
- 页：5f0f4e169f1745e789501f939bb10851
- 器件：C1、C10、C11、C12、C13、C14、C15、C16、C17、C18、C19、C2、C20、C21、C22、C23、C24、C25、C26、C27、C28、C29、C3、C30、C31、C32、C33、C34、C35、C36、C37、C38、C39、C4、C40、C41、C42、C43、C44、C45、C46、C5、C6、C7、C8、C9、CN1、L1、L2、L3、L4、LED1、LED2、R1、R10、R11、R12、R13、R14、R15、R16、R17、R18、R19、R2、R20、R21、R22、R23、R24、R25、R26、R27、R28、R29、R3、R30、R31、R32、R4、R5、R6、R7、R8、R9、RST1、SWD1、U1、U10、U11、U12、U13、U14、U15、U16、U2、U3、U4、U5、U6、U7、U8、U9、USB1、X1
- findings：[0] conn-duplicate-designators、[1] conn-duplicate-designators、[2] conn-duplicate-designators、[3] conn-duplicate-designators、[4] conn-duplicate-designators、[5] conn-duplicate-designators、[6] conn-duplicate-designators、[7] conn-duplicate-designators、[8] conn-duplicate-designators、[9] conn-duplicate-designators、[10] conn-duplicate-designators、[11] conn-duplicate-designators、[12] conn-duplicate-designators、[13] conn-duplicate-designators、[14] conn-duplicate-designators、[15] conn-duplicate-designators、[16] conn-duplicate-designators、[17] conn-duplicate-designators、[18] conn-duplicate-designators、[19] conn-duplicate-designators、[20] conn-duplicate-designators、[21] conn-duplicate-designators、[22] conn-duplicate-designators、[23] conn-duplicate-designators、[24] conn-duplicate-designators、[25] conn-duplicate-designators、[30] decap-required-caps、[31] arch-nrst-closure、[32] param-rc-cutoff、[33] param-rc-cutoff、[34] param-rc-cutoff、[35] param-rc-cutoff、[36] param-rc-cutoff、[37] param-rc-cutoff、[38] param-rc-cutoff、[39] sel-ldo-fixed-output、[40] sel-ldo-fixed-output
- 注：该页含 26 个重号位号（C1、C10、C11、C12、C13、C2）：模型按位号索引，同名跨板记在 model.crossBoardDesignators（该板与其他板同名），同名同板跨页记在同板模型的 crossPageDesignators

### Board2

#### Board2/P1（11 器件）

- 依据：page
- 板：Board2
- 页：0876ea4e415ed158
- 器件：C1、CN2、R1、R2、R3、R4、SCREW1、SCREW2、SCREW3、SCREW4、U1
- findings：[26] conn-duplicate-designators、[27] conn-duplicate-designators、[28] conn-duplicate-designators、[29] conn-duplicate-designators
- 注：该页含 10 个重号位号（C1、R1、R2、R3、R4、SCREW1）：模型按位号索引，同名跨板记在 model.crossBoardDesignators（该板与其他板同名），同名同板跨页记在同板模型的 crossPageDesignators

### Board3

#### Board3/P1（39 器件）

- 依据：page
- 板：Board3
- 页：40daf13560b1086b
- 器件：C1、C10、C11、C115、C116、C12、C13、C2、C3、C4、C5、C6、C7、C8、C9、CN3、D2、Q1、Q2、Q3、Q4、Q7、Q8、R1、R18、R2、R3、R4、R43、R5、R6、R8、SCREW1、SCREW2、SCREW3、SCREW4、U1、U14、U2
- findings：[41] sel-tvs-standoff-rail、[42] shunt-sense-link、[43] shunt-sense-link、[44] shunt-sense-link
- 注：该页含 28 个重号位号（C1、C10、C11、C12、C13、C2）：模型按位号索引，同名跨板记在 model.crossBoardDesignators（该板与其他板同名），同名同板跨页记在同板模型的 crossPageDesignators

## 规则 findings（224）

> 有 179/224 条 finding 的定位链不完整，缺的那一环在表里写成「未标注」——逐条看得见，不静默省略。本次缺：page 179 条、refs 14 条

| # | 级别 | 规则 | 板 | 位号 | 定位链 | 说明 |
|---|---|---|---|---|---|---|
| 0 | ERROR | conn-duplicate-designators | Board1 | U15 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U15 | U15 is used by more than one placed part on one page; the model kept the first placement |
| 1 | ERROR | conn-duplicate-designators | Board1 | U16 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U16 | U16 is used by more than one placed part on one page; the model kept the first placement |
| 2 | ERROR | conn-duplicate-designators | Board1 | C1 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C1 | C1 is placed on more than one board (Board1、Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 3 | ERROR | conn-duplicate-designators | Board1 | C10 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C10 | C10 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 4 | ERROR | conn-duplicate-designators | Board1 | C11 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C11 | C11 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 5 | ERROR | conn-duplicate-designators | Board1 | C12 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C12 | C12 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 6 | ERROR | conn-duplicate-designators | Board1 | C13 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C13 | C13 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 7 | ERROR | conn-duplicate-designators | Board1 | C2 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C2 | C2 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 8 | ERROR | conn-duplicate-designators | Board1 | C3 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C3 | C3 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 9 | ERROR | conn-duplicate-designators | Board1 | C4 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C4 | C4 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 10 | ERROR | conn-duplicate-designators | Board1 | C5 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C5 | C5 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 11 | ERROR | conn-duplicate-designators | Board1 | C6 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C6 | C6 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 12 | ERROR | conn-duplicate-designators | Board1 | C7 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C7 | C7 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 13 | ERROR | conn-duplicate-designators | Board1 | C8 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C8 | C8 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 14 | ERROR | conn-duplicate-designators | Board1 | C9 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → C9 | C9 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 15 | ERROR | conn-duplicate-designators | Board1 | R1 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R1 | R1 is placed on more than one board (Board1、Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 16 | ERROR | conn-duplicate-designators | Board1 | R18 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R18 | R18 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 17 | ERROR | conn-duplicate-designators | Board1 | R2 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R2 | R2 is placed on more than one board (Board1、Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 18 | ERROR | conn-duplicate-designators | Board1 | R3 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R3 | R3 is placed on more than one board (Board1、Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 19 | ERROR | conn-duplicate-designators | Board1 | R4 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R4 | R4 is placed on more than one board (Board1、Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 20 | ERROR | conn-duplicate-designators | Board1 | R5 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R5 | R5 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 21 | ERROR | conn-duplicate-designators | Board1 | R6 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R6 | R6 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 22 | ERROR | conn-duplicate-designators | Board1 | R8 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R8 | R8 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 23 | ERROR | conn-duplicate-designators | Board1 | U1 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U1 | U1 is placed on more than one board (Board1、Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 24 | ERROR | conn-duplicate-designators | Board1 | U14 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U14 | U14 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 25 | ERROR | conn-duplicate-designators | Board1 | U2 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U2 | U2 is placed on more than one board (Board1、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 26 | ERROR | conn-duplicate-designators | Board2 | SCREW1 | outputs\bug98\live\foc.epro2 → Board2 → 页:P1（0876ea4e） → SCREW1 | SCREW1 is placed on more than one board (Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 27 | ERROR | conn-duplicate-designators | Board2 | SCREW2 | outputs\bug98\live\foc.epro2 → Board2 → 页:P1（0876ea4e） → SCREW2 | SCREW2 is placed on more than one board (Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 28 | ERROR | conn-duplicate-designators | Board2 | SCREW3 | outputs\bug98\live\foc.epro2 → Board2 → 页:P1（0876ea4e） → SCREW3 | SCREW3 is placed on more than one board (Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 29 | ERROR | conn-duplicate-designators | Board2 | SCREW4 | outputs\bug98\live\foc.epro2 → Board2 → 页:P1（0876ea4e） → SCREW4 | SCREW4 is placed on more than one board (Board2、Board3); the project's netlist, BOM and layout share one name for two parts (oracle ruling A1, 2026-09-19) |
| 30 | WARN | decap-required-caps | Board1 | U11 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U11（网 NET10） | U11 pin5: the grounded capacitor on 'NET10' is only 100nF (< required 1uF) |
| 31 | INFO | arch-nrst-closure | Board1 | U1 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U1 | U1 pin14（NRST）在网 'NRST' 上有 4 个成员（U1.14, RST1.1, R29.1, C39.1）—— 复位脚不裸奔（测量行）。控制器判据：货架 category=ic.mcu（ic.stm32h743vit6） |
| 32 | INFO | param-rc-cutoff | Board1 | R29、C36 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R29、C36 | RC R29(1e+04Ω) + C36(2.2uF) on 'VCC': fc = 7 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists) |
| 33 | INFO | param-rc-cutoff | Board1 | R29、C45 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R29、C45 | RC R29(1e+04Ω) + C45(100nF) on 'VCC': fc = 159 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists) |
| 34 | INFO | param-rc-cutoff | Board1 | U14、C42 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U14、C42 | RC U14(1000Ω) + C42(10nF) on 'NET13': fc = 15,915 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists) |
| 35 | INFO | param-rc-cutoff | Board1 | U14、C41 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U14、C41 | RC U14(1000Ω) + C41(100nF) on 'NET13': fc = 1,592 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists) |
| 36 | INFO | param-rc-cutoff | Board1 | U14、C40 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U14、C40 | RC U14(1000Ω) + C40(2.2uF) on 'NET13': fc = 72 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists) |
| 37 | INFO | param-rc-cutoff | Board1 | R26、C32 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R26、C32 | RC R26(47Ω) + C32(2.2uF) on '5VA': fc = 1,539 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists) |
| 38 | INFO | param-rc-cutoff | Board1 | R26、C33 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → R26、C33 | RC R26(47Ω) + C33(10uF) on '5VA': fc = 339 Hz (-3 dB cutoff; reported, not graded -- no requirement channel exists) |
| 39 | INFO | sel-ldo-fixed-output | Board1 | U11 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U11 | U11 的固定输出是 3.3 V（货架条目 ic.rt9013_33gb 的 Output Voltage = '3.3V'），但它输出轨 NET10 的轨压读不出，所以对拍无从做起：这条轨 'NET10' 的电压只从被审的 U11 自己推出来（U11 RT9013-33GB output, decoded from the MPN suffix — a guess: no datasheet fact declares it），拿它对拍 U11 的规格等于拿零件自己的名字验零件自己；intent-missing: 写进合同 requirements.rails[net=NET10].targetVoltage，或让轨名自己写着电压 |
| 40 | INFO | sel-ldo-fixed-output | Board1 | U13 | outputs\bug98\live\foc.epro2 → Board1 → 页:P1（5f0f4e16） → U13 | U13（value ''，料号 'TPLP2981-30DBVR'，货架条目 C22435132）的固定输出是 3 V（货架条目 ic.tplp2981_30dbvr 的 Output Voltage = '3V'），但货架事实没有指明它的输出脚（supply_pins 与 required_caps 合起来指不出唯一一个非供电脚），所以它输出的是哪条轨读不出来 |
| 41 | INFO | sel-tvs-standoff-rail | Board3 | D2 | outputs\bug98\live\foc.epro2 → Board3 → 页:P1（40daf135） → D2 | D2: 关断电压 40 V ≥ 所挂轨 +24V = 24 V，比值 1.67x；击穿电压 44.4 V（Voltage - Breakdown）；钳位电压 64.5 V（Clamping Voltage） —— 这是测量行：本工具不发明裕度系数（要按自家规矩留多少余量，请拿这个比值自己判） |
| 42 | INFO | shunt-sense-link | Board3 | R43、L1 | outputs\bug98\live\foc.epro2 → Board3 → 页:P1（40daf135） → R43、L1 | R43 (10mΩ): no IC pins found on its terminal nets IA+ / PGND. L1 capability boundary: the sense link may run through series resistors or a filter network, which a connectivity-only check cannot see. |
| 43 | INFO | shunt-sense-link | Board3 | R8、L1 | outputs\bug98\live\foc.epro2 → Board3 → 页:P1（40daf135） → R8、L1 | R8 (10mΩ): no IC pins found on its terminal nets IB+ / PGND. L1 capability boundary: the sense link may run through series resistors or a filter network, which a connectivity-only check cannot see. |
| 44 | INFO | shunt-sense-link | Board3 | R18、L1 | outputs\bug98\live\foc.epro2 → Board3 → 页:P1（40daf135） → R18、L1 | R18 (10mΩ): no IC pins found on its terminal nets PGND / Symbol. L1 capability boundary: the sense link may run through series resistors or a filter network, which a connectivity-only check cannot see. |
| 45 | ERROR | pcb-footprint-consistency | PCB3 | R1 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R1 | R1 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） |
| 46 | ERROR | pcb-footprint-consistency | PCB3 | R2 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R2 | R2 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） |
| 47 | ERROR | pcb-footprint-consistency | PCB3 | R3 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R3 | R3 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） |
| 48 | ERROR | pcb-footprint-consistency | PCB3 | R4 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R4 | R4 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） |
| 49 | ERROR | pcb-footprint-consistency | PCB3 | R5 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R5 | R5 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） |
| 50 | ERROR | pcb-footprint-consistency | PCB3 | R6 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R6 | R6 在原理图 Board3 上有、PCB PCB3 上没摆：这块板没有实现原理图的这颗件（conn-library-pins 的同一口径：板级对称漂移按 ERROR 报） |
| 51 | WARN | pcb-silk-designator | PCB3 | D2 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → D2 | PCB3 D2 的位号丝印压在焊盘上：1 只焊盘被压（最深的 D2 pin 1、15.0 mil），最窄字宽档（0.4）下就已经压上 |
| 52 | INFO | pcb-derating-package | PCB3 | R18、R43、R8 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R18、R43、R8 | PCB3 电阻降额读数：认出 3 颗电阻（另有 0 Ω 跳线 0 颗、位号像电阻但值与库件都没说是电阻的 0 颗，本规则不判它们）；两脚都有价的 0 颗、封装档认得出的 3 颗、串联串 0 条 |
| 53 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GHA） | power-path net 'GHA': 3 track(s), width min 15 mil / max 15 mil, 356.1 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 54 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GHB） | power-path net 'GHB': 5 track(s), width min 10 mil / max 10 mil, 479.6 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 55 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GHC） | power-path net 'GHC': 4 track(s), width min 12 mil / max 12 mil, 280.3 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 56 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GLA） | power-path net 'GLA': 2 track(s), width min 15 mil / max 15 mil, 262.8 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 57 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GLB） | power-path net 'GLB': 6 track(s), width min 10 mil / max 12 mil, 277.5 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 58 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GLC） | power-path net 'GLC': 2 track(s), width min 12 mil / max 12 mil, 161.0 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 59 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 MOTA） | power-path net 'MOTA': 2 track(s), width min 10 mil / max 10 mil, 370.6 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 60 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 MOTB） | power-path net 'MOTB': 2 track(s), width min 10 mil / max 10 mil, 288.2 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 61 | INFO | pcb-foc-gate-trace-width | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 MOTC） | power-path net 'MOTC': 2 track(s), width min 10 mil / max 10 mil, 275.6 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 62 | INFO | pcb-foc-ground-domains | PCB3 | R1 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R1（网 PGND） | this board carries a power-domain ground (PGND) and **no logic/analog-domain ground**, so R1 has no pair to read and no clearance is claimed |
| 63 | INFO | pcb-foc-ground-plane | PCB3 | R31 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → R31 | this PCB document reads 2 copper layer(s) in its physical stackup, below the 4-layer threshold, so it is a **two-layer board and R31 does not apply to it** — TI §1.2's concern is a continuous return path across the inner layers, which a board this thin does not have. No island count and no coverage figure is claimed |
| 64 | INFO | pcb-foc-ground-tie | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 PGND） | this board carries a power-domain ground (PGND) and no logic/analog ground, so no tie and no 0 Ω search is reported |
| 65 | INFO | pcb-foc-power-loop-area | PCB3 | C5 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → C5 | high-current loop C5 (330uF) ↔ Q1: polygon area 5.878e+04 sq mil, bbox area 2.016e+05 sq mil — **both 口径 are reported** and neither is marked as the answer (岳's ruling on which one is 「环路面积」 has not arrived); measurement only |
| 66 | INFO | pcb-foc-power-loop-area | PCB3 | C5 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → C5 | high-current loop C5 (330uF) ↔ Q3: polygon area 1.642e+04 sq mil, bbox area 9.263e+04 sq mil — **both 口径 are reported** and neither is marked as the answer (岳's ruling on which one is 「环路面积」 has not arrived); measurement only |
| 67 | INFO | pcb-foc-power-loop-area | PCB3 | C4 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → C4 | high-current loop C4 (330uF) ↔ Q7: polygon area 1.091e+05 sq mil, bbox area 2.059e+05 sq mil — **both 口径 are reported** and neither is marked as the answer (岳's ruling on which one is 「环路面积」 has not arrived); measurement only |
| 68 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GHA） | return-path projection of 'GHA': none 3 over 3 trace(s) — **3 gap(s)** at bec1d962d0b5677b (layer 1→2), aa9fb7fde9dde0bf (layer 1→2), 30864ee2f46ffa94 (layer 1→2)；出数不出判定 |
| 69 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GHB） | return-path projection of 'GHB': none 5 over 5 trace(s) — **5 gap(s)** at f8bde6f5b85e9afb (layer 1→2), 52f7a851edd9c280 (layer 1→2), 2d2986a267f69dfc (layer 1→2), …；出数不出判定 |
| 70 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GHC） | return-path projection of 'GHC': none 4 over 4 trace(s) — **4 gap(s)** at 731fbc0043b5790f (layer 1→2), eb6f39f7fd510437 (layer 1→2), 91f7c8512a2d807c (layer 1→2), …；出数不出判定 |
| 71 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GLA） | return-path projection of 'GLA': none 2 over 2 trace(s) — **2 gap(s)** at f7fa5d5a8a6b4e16 (layer 1→2), de248d1697722e9a (layer 1→2)；出数不出判定 |
| 72 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GLB） | return-path projection of 'GLB': none 6 over 6 trace(s) — **6 gap(s)** at a084c6888a88aa16 (layer 2→1), 3c48593e81bf5e6c (layer 2→1), 18ff3ef36361086b (layer 2→1), …；出数不出判定 |
| 73 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 GLC） | return-path projection of 'GLC': none 2 over 2 trace(s) — **2 gap(s)** at 8c6940c6f38dcd80 (layer 1→2), 64c3a17c5b96d57a (layer 1→2)；出数不出判定 |
| 74 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 MOTA） | return-path projection of 'MOTA': none 2 over 2 trace(s) — **2 gap(s)** at 16a9cfeab7466f2c (layer 1→2), ccf296e66381db6a (layer 1→2)；出数不出判定 |
| 75 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 MOTB） | return-path projection of 'MOTB': none 2 over 2 trace(s) — **2 gap(s)** at 5d02eff9faf4784b (layer 1→2), 75479c77771d6b5f (layer 1→2)；出数不出判定 |
| 76 | INFO | pcb-foc-return-path | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注（网 MOTC） | return-path projection of 'MOTC': none 2 over 2 trace(s) — **2 gap(s)** at 35d0f2e6c1553873 (layer 1→2), 58f6fc04c7ebbbc6 (layer 1→2)；出数不出判定 |
| 77 | INFO | pcb-foc-track-corners | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | this board has **no non-obtuse fold** in its routing — every one of its 29 track(s) either runs straight through a joint or bends at or above core.measure.OBTUSE_CORNER_DEG, so the list 133a's track_corner_angle returns is empty and no per-fold row is claimed |
| 78 | INFO | pcb-footprint-consistency | PCB3 | CN3 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → CN3 | PCB3 CN3 无从比较：原理图没有声明封装（字段是 '-'），没有可比的对造。原理图声明 '-'，PCB 实摆 'CONN-TH_XT30PW-M' |
| 79 | INFO | pcb-footprint-consistency | PCB3 | SCREW1 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → SCREW1 | PCB3 SCREW1 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。原理图声明 '插件'，PCB 实摆 (空——没有声明封装) |
| 80 | INFO | pcb-footprint-consistency | PCB3 | SCREW2 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → SCREW2 | PCB3 SCREW2 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。原理图声明 '插件'，PCB 实摆 (空——没有声明封装) |
| 81 | INFO | pcb-footprint-consistency | PCB3 | SCREW3 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → SCREW3 | PCB3 SCREW3 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。原理图声明 '插件'，PCB 实摆 (空——没有声明封装) |
| 82 | INFO | pcb-footprint-consistency | PCB3 | SCREW4 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → SCREW4 | PCB3 SCREW4 PCB 侧读不出封装：PCB 上这颗器件压根没有指定封装（COMPONENT 没有 ATTR key='Footprint'），板子上没有它的焊盘。原理图声明 '插件'，PCB 实摆 (空——没有声明封装) |
| 83 | INFO | pcb-footprint-consistency | PCB3 | U14 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → U14 | PCB3 U14 无从比较：原理图没有声明封装（字段是 '-'），没有可比的对造。原理图声明 '-'，PCB 实摆 'CONN-TH_MR30PW-M30-G-Y' |
| 84 | INFO | pcb-footprint-consistency | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB3 封装对账（原理图 Board3）：比了 33 个两边都有的器件——一致 27，焊盘数不符 0，尺寸码不符 0，封装族不符 0，无从比较 2，PCB 侧读不出封装 4；另：原理图有而 PCB 没摆 6 个，PCB 摆而原理图没有 0 个 |
| 85 | INFO | pcb-polarity-orientation | PCB3 | C1、C115、C116、C4、C5、C6、P5、D0 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → C1、C115、C116、C4、C5、C6、P5、D0 | PCB3 上 6 颗极性器件共用封装 'CAP-TH_BD10.0-P5.00-D0.6-FD-A'（顶层），方向却有 2 种：[0.0, 90.0]——同封装同朝向是生产工艺习惯，不统一只作提醒（岳 2026-10-11 裁：降 INFO） |
| 86 | INFO | pcb-polarity-orientation | PCB3 | C1、P5、D0、C115、C116、C4、C5、C6 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → C1、P5、D0、C115、C116、C4、C5、C6 | PCB3 有 6 颗极性器件的原理图侧**没有声明哪只脚是正极**（符号脚名只有 1/2）：丝印上的方向标记无法与原理图核对，装配只能靠丝印本身——这是原理图符号的事实缺口，本规则如实记下、不猜 |
| 87 | INFO | pcb-polarity-orientation | PCB3 | P5、D0 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → P5、D0 | PCB3 极性器件读数：7 颗极性器件（其中 1 颗原理图声明了极性脚、6 颗只有库件类型词），涉及 2 种封装名，量出印刷方向标记的 7 颗 |
| 88 | INFO | pcb-silk-designator | PCB3 | C1、C13、CN3、Q1、Q2、Q3、Q4、Q7、Q8、R18、R43、R8、SCREW1、SCREW2、SCREW3、SCREW4、U1、U2 | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → C1、C13、CN3、Q1、Q2、Q3、Q4、Q7、Q8、R18、R43、R8、SCREW1、SCREW2、SCREW3、SCREW4、U1、U2 | PCB3 有 18 个位号的丝印被关掉（``valueVisible=false``）：板上不会印出这些位号——本规则只报读数，不判「是不是忘了打开」 |
| 89 | INFO | pcb-silk-designator | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB3 TOP_SILK（15 个位号）文字方向分布：0°×6, 90°×4, 180°×2, 270°×3；其中 8 个落在 0°/180° 两个相反方向上 |
| 90 | INFO | pcb-silk-designator | PCB3 |  | outputs\bug98\live\foc.epro2 → PCB3 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB3 丝印读数：33 个位号记录（显示 15、关掉 18），板上焊盘 125 只、器件本体轮廓 29 个；文字宽度：实测（宿主 primitive bbox） 0 个、估算值（字宽比带，非读数） 15 个 |
| 91 | ERROR | pcb-footprint-consistency | PCB1 | C26 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C26 | PCB1 C26 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 92 | ERROR | pcb-footprint-consistency | PCB1 | C27 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C27 | PCB1 C27 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 93 | ERROR | pcb-footprint-consistency | PCB1 | C28 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C28 | PCB1 C28 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 94 | ERROR | pcb-footprint-consistency | PCB1 | C29 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C29 | PCB1 C29 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 95 | ERROR | pcb-footprint-consistency | PCB1 | C30 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C30 | PCB1 C30 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 96 | ERROR | pcb-footprint-consistency | PCB1 | C31 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C31 | PCB1 C31 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 97 | ERROR | pcb-footprint-consistency | PCB1 | C35 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C35 | PCB1 C35 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 98 | ERROR | pcb-footprint-consistency | PCB1 | C36 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C36 | PCB1 C36 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 99 | ERROR | pcb-footprint-consistency | PCB1 | C41 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C41 | PCB1 C41 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 100 | ERROR | pcb-footprint-consistency | PCB1 | C42 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C42 | PCB1 C42 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 101 | ERROR | pcb-footprint-consistency | PCB1 | C43 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C43 | PCB1 C43 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 102 | ERROR | pcb-footprint-consistency | PCB1 | C44 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C44 | PCB1 C44 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'C0603' |
| 103 | ERROR | pcb-footprint-consistency | PCB1 | U10 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U10 | PCB1 U10 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'R0603' |
| 104 | ERROR | pcb-footprint-consistency | PCB1 | U14 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U14 | PCB1 U14 封装尺寸码不符：原理图声明尺寸码 0805，PCB 摆的是 0603。原理图声明 '0805'，PCB 实摆 'R0603' |
| 105 | WARN | pcb-component-spacing | PCB1 | R18 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R18 | R18 and U16 are 15.1 mil apart edge-to-edge (pads 1 / 3), under the 20 mil house rule |
| 106 | WARN | pcb-component-spacing | PCB1 | R22 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R22 | R22 and USB1 are 19.2 mil apart edge-to-edge (pads 1 / 11), under the 20 mil house rule |
| 107 | WARN | pcb-component-spacing | PCB1 | R24 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R24 | R24 and USB1 are 19.2 mil apart edge-to-edge (pads 2 / 2), under the 20 mil house rule |
| 108 | WARN | pcb-component-spacing | PCB1 | U8 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U8 | U8 and USB1 are 13.8 mil apart edge-to-edge (pads 5 / 14), under the 20 mil house rule |
| 109 | WARN | pcb-mcu-crystal-keepout | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1 | X1's region carries **4** copper element(s) on Bottom Layer: track 2bbdb921d0bf3fc9 @ IA+; track dfbd69b2b06ce1d5 @ IB+; via af0e64b627ae4fa3 @ GND; via 7b3641e73a33bd61 @ GND — no pour region on this layer inside the region — **WARN**：其中 2 件是**别网铜**（track 2bbdb921d0bf3fc9 @ IA+, track dfbd69b2b06ce1d5 @ IB+），落在晶振净空区（外扩 9.84 mil）内；岳 2026-10-11 裁：以外 WARN |
| 110 | INFO | pcb-decap-distance | PCB1 | U11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U11（网 +5V） | U11 sits on the supply net '+5V', and no high-frequency decoupling capacitor bridging it to ground was found on the net — whether one is required is the datasheet's required_caps question (decap-required-caps); this row says only that the layout has none to place |
| 111 | INFO | pcb-decap-distance | PCB1 | U11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U11（网 NET10） | U11 sits on the supply net 'NET10', and no high-frequency decoupling capacitor bridging it to ground was found on the net — whether one is required is the datasheet's required_caps question (decap-required-caps); this row says only that the layout has none to place |
| 112 | INFO | pcb-decap-distance | PCB1 | U13 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U13（网 +5V） | U13 sits on the supply net '+5V', and no high-frequency decoupling capacitor bridging it to ground was found on the net — whether one is required is the datasheet's required_caps question (decap-required-caps); this row says only that the layout has none to place |
| 113 | INFO | pcb-decap-distance | PCB1 | U7 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U7（网 +24V） | U7 sits on the supply net '+24V', and no high-frequency decoupling capacitor bridging it to ground was found on the net — whether one is required is the datasheet's required_caps question (decap-required-caps); this row says only that the layout has none to place |
| 114 | INFO | pcb-derating-package | PCB1 | R11、R25、R3、C11、C15、C16 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R11、R25、R3、C11、C15、C16 | PCB1 电阻降额读数：认出 34 颗电阻（另有 0 Ω 跳线 0 颗、位号像电阻但值与库件都没说是电阻的 0 颗，本规则不判它们）；两脚都有价的 2 颗、封装档认得出的 34 颗、串联串 0 条 |
| 115 | INFO | pcb-foc-decap-proximity | PCB1 | C7 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C7（网 $1N74368） | C7 on '$1N74368' sits 157.8 mil edge-to-edge from U2.29 ('DVDD'); **same copper layer**: U2 pin 29 on [1] and C7 on [1] — they share one; no via stands in the corridor between C7's pad(s) and U2.29; C7 declared value '1uF' = 1 µF；value reading (153b's 口径)：两视图不一致，判定用**原理图**值：原理图 '1uF' / PCB 文档 '100nF'; component-level distance U2 ↔ C7: 157.8 mil edge-to-edge (pads 30 / 1) — a **different** measurement from the loop leg above, because core.measure.component_distance refuses same-net pairs and would answer with some other net's gap; quoted so a reader who wants the placement distance has it; TI SLVA959B §5.3.1 reference: within 200 mil (0.2 in) of the supply pin — **岳 2026-10-11 裁：以内 INFO、以外 WARN**，数字沿用该建议值；实测 157.8 mil <= 200 mil，故本行 INFO 出数 — 实测 157.8 mil 在 200 mil 以内（岳 2026-10-11 裁：以内 INFO），本行 INFO 出数 |
| 116 | INFO | pcb-foc-decap-proximity | PCB1 | C3 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C3（网 $1N74457） | C3 on '$1N74457' sits 187.4 mil edge-to-edge from U2.2 ('VM'); **same copper layer**: U2 pin 2 on [1] and C3 on [1] — they share one; no via stands in the corridor between C3's pad(s) and U2.2; C3 declared value '100nF' = 0.1 µF；value reading (153b's 口径)：原理图页未写该值，**回退 PCB 文档值** '100nF'（口径：本板板链读出的原理图页没有声明，只能取 PCB 文档的副本）; component-level distance U2 ↔ C3: 180.5 mil edge-to-edge (pads 1 / 1) — a **different** measurement from the loop leg above, because core.measure.component_distance refuses same-net pairs and would answer with some other net's gap; quoted so a reader who wants the placement distance has it; TI SLVA959B §5.3.1 reference: within 200 mil (0.2 in) of the supply pin — **岳 2026-10-11 裁：以内 INFO、以外 WARN**，数字沿用该建议值；实测 187.4 mil <= 200 mil，故本行 INFO 出数 — 实测 187.4 mil 在 200 mil 以内（岳 2026-10-11 裁：以内 INFO），本行 INFO 出数 |
| 117 | INFO | pcb-foc-decap-proximity | PCB1 | C4 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C4（网 $1N74457） | C4 on '$1N74457' sits 112.9 mil edge-to-edge from U2.2 ('VM'); **same copper layer**: U2 pin 2 on [1] and C4 on [1] — they share one; no via stands in the corridor between C4's pad(s) and U2.2; C4 declared value '10uF' = 10 µF；value reading (153b's 口径)：原理图页未写该值，**回退 PCB 文档值** '10uF'（口径：本板板链读出的原理图页没有声明，只能取 PCB 文档的副本）; component-level distance U2 ↔ C4: 101.7 mil edge-to-edge (pads 1 / 1) — a **different** measurement from the loop leg above, because core.measure.component_distance refuses same-net pairs and would answer with some other net's gap; quoted so a reader who wants the placement distance has it; TI SLVA959B §5.3.1 reference: within 200 mil (0.2 in) of the supply pin — **岳 2026-10-11 裁：以内 INFO、以外 WARN**，数字沿用该建议值；实测 112.9 mil <= 200 mil，故本行 INFO 出数 — 实测 112.9 mil 在 200 mil 以内（岳 2026-10-11 裁：以内 INFO），本行 INFO 出数 |
| 118 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GHA） | power-path net 'GHA': 6 track(s), width min 12 mil / max 12 mil, 1282.5 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 119 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GHB） | power-path net 'GHB': 8 track(s), width min 10 mil / max 12 mil, 1263.0 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 120 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GHC） | power-path net 'GHC': 4 track(s), width min 12 mil / max 12 mil, 525.0 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 121 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GLA） | power-path net 'GLA': 5 track(s), width min 12 mil / max 12 mil, 1217.5 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 122 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GLB） | power-path net 'GLB': 11 track(s), width min 12 mil / max 12 mil, 1417.8 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 123 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GLC） | power-path net 'GLC': 4 track(s), width min 12 mil / max 12 mil, 234.5 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 124 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA） | power-path net 'IA': 11 track(s), width min 10 mil / max 10 mil, 854.5 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 125 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA+） | power-path net 'IA+': 12 track(s), width min 10 mil / max 10 mil, 755.3 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 126 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA-） | power-path net 'IA-': 5 track(s), width min 10 mil / max 10 mil, 599.6 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 127 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IB） | power-path net 'IB': 9 track(s), width min 10 mil / max 10 mil, 627.4 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 128 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IB+） | power-path net 'IB+': 8 track(s), width min 10 mil / max 10 mil, 752.2 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 129 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IB-） | power-path net 'IB-': 4 track(s), width min 10 mil / max 10 mil, 572.7 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 130 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IC） | power-path net 'IC': 9 track(s), width min 10 mil / max 10 mil, 615.3 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 131 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IC+） | power-path net 'IC+': 6 track(s), width min 10 mil / max 10 mil, 933.4 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 132 | INFO | pcb-foc-gate-trace-width | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IC-） | power-path net 'IC-': 5 track(s), width min 10 mil / max 10 mil, 653.0 mil total — TI §4's 20 mil reference is quoted in the evidence and **not applied** (岳 has ruled on no threshold in this pack) |
| 133 | INFO | pcb-foc-ground-domains | PCB1 | R30、R11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R30、R11（网 PGND、AGND） | ground domain pair 'PGND' (power) ↔ 'AGND' (logic): **no direct copper connection** between 'PGND' and 'AGND': nearest copper pair is 49.8 mil edge-to-edge (pad R30.2 on layer 1 ↔ pad R11.1 on layer 1) on shared layer 1 = Top Layer (id=1, TOP) — the isolation TI §1.3.1 asks for **holds by this measurement**, stated as a number and not as a verdict — INFO 出数，本行不出判定 |
| 134 | INFO | pcb-foc-ground-domains | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 PGND、GND） | ground domain pair 'PGND' (power) ↔ 'GND' (logic): 'PGND' and 'GND' read distance 0.0 but **not overlapping** on any shared layer (shared layers: none — a cross-layer pair, whose distance is a plan-view projection and not a surface gap). No copper connection is claimed, and no clearance violation is claimed either — INFO 出数，本行不出判定 |
| 135 | INFO | pcb-foc-ground-plane | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 AGND） | net 'AGND' breaks into 1 copper island(s) — **one island**, pour area 1.425e+06 sq mil = 28.9% of the board area — INFO 出数；「够不够」不是本工具的判定（岳裁定未到） |
| 136 | INFO | pcb-foc-ground-plane | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GND） | net 'GND' breaks into 28 copper island(s) — **no single island**: the largest is 2.164e+04 sq mil — INFO 出数；「够不够」不是本工具的判定（岳裁定未到） |
| 137 | INFO | pcb-foc-ground-plane | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 PGND） | net 'PGND' breaks into 4 copper island(s) — **no single island**: the largest is 3.064e+05 sq mil — INFO 出数；「够不够」不是本工具的判定（岳裁定未到） |
| 138 | INFO | pcb-foc-ground-tie | PCB1 | R11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R11（网 AGND、PGND） | ground domain pair 'PGND' (power) ↔ 'AGND' (logic): **每对域恰好一颗 0R — 合规**（岳 2026-10-11 裁）：R11 (value '0R') bridges 'AGND' (logic domain) and 'PGND' (power domain) and nothing else joins this pair. Its distance to the nearest power-stage bulk electrolytic is **unmeasurable** — no bulk capacitor is placed on this document; 出数不出判定, no proximity threshold is in force |
| 139 | INFO | pcb-foc-ground-tie | PCB1 | R25 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R25（网 GND、PGND） | ground domain pair 'PGND' (power) ↔ 'GND' (logic): **每对域恰好一颗 0R — 合规**（岳 2026-10-11 裁）：R25 (value '0R') bridges 'GND' (logic domain) and 'PGND' (power domain) and nothing else joins this pair. Its distance to the nearest power-stage bulk electrolytic is **unmeasurable** — no bulk capacitor is placed on this document; 出数不出判定, no proximity threshold is in force |
| 140 | INFO | pcb-foc-ground-tie | PCB1 | R3 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R3（网 +24V、$1N74457） | R3 (value '0R') parses to exactly 0 Ω but its two pins sit on '+24V' and '$1N74457' (domains none / none) — **not a ground-domain tie**, so it is not counted toward any domain pair's single point 岳's ruling describes. Reported because a 0 Ω part somewhere on a ground net is the shape a reader would otherwise look for and not find |
| 141 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GHA） | return-path projection of 'GHA': covered-by-construction 6 over 6 trace(s) — no gap found on any reference layer；出数不出判定 |
| 142 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GHB） | return-path projection of 'GHB': covered-by-construction 8 over 8 trace(s) — no gap found on any reference layer；出数不出判定 |
| 143 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GHC） | return-path projection of 'GHC': covered-by-construction 2, none 2 over 4 trace(s) — **2 gap(s)** at 36e7f7dcefaa3ea1 (layer 2→16), ade73f5b61c07b52 (layer 2→16)；出数不出判定 |
| 144 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GLA） | return-path projection of 'GLA': covered-by-construction 5 over 5 trace(s) — no gap found on any reference layer；出数不出判定 |
| 145 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GLB） | return-path projection of 'GLB': covered-by-construction 7, none 4 over 11 trace(s) — **4 gap(s)** at 5610b8971af4a521 (layer 2→16), 8170cf598df47f6a (layer 2→16), bc4f859c57ce58ad (layer 2→16), …；出数不出判定 |
| 146 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 GLC） | return-path projection of 'GLC': covered-by-construction 4 over 4 trace(s) — no gap found on any reference layer；出数不出判定 |
| 147 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA） | return-path projection of 'IA': covered-by-construction 11 over 11 trace(s) — no gap found on any reference layer；出数不出判定 |
| 148 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA+） | return-path projection of 'IA+': covered-by-construction 2, none 10 over 12 trace(s) — **10 gap(s)** at baf598ce527f131c (layer 2→16), 2bbdb921d0bf3fc9 (layer 2→16), 2b89caa0f8442e14 (layer 2→16), …；出数不出判定 |
| 149 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA-） | return-path projection of 'IA-': covered-by-construction 2, none 3 over 5 trace(s) — **3 gap(s)** at 3e9a12919ec977f2 (layer 2→16), 7e0e3e6b280f6662 (layer 2→16), cf3ddfb153114bad (layer 2→16)；出数不出判定 |
| 150 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IB） | return-path projection of 'IB': covered-by-construction 9 over 9 trace(s) — no gap found on any reference layer；出数不出判定 |
| 151 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IB+） | return-path projection of 'IB+': covered-by-construction 2, none 5, partial 1 over 8 trace(s) — **6 gap(s)** at d94e41f4119298a1 (layer 2→16), 91bb415249137d1b (layer 2→16), 84138e865d3553fc (layer 2→16), …；出数不出判定 |
| 152 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IB-） | return-path projection of 'IB-': covered-by-construction 1, none 1, partial 2 over 4 trace(s) — **3 gap(s)** at 0d8665b553cbcd20 (layer 2→16), 9e0b7cc4319b3226 (layer 2→16), 2f8c095177da71c9 (layer 2→16)；出数不出判定 |
| 153 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IC） | return-path projection of 'IC': covered-by-construction 9 over 9 trace(s) — no gap found on any reference layer；出数不出判定 |
| 154 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IC+） | return-path projection of 'IC+': covered 1, covered-by-construction 2, none 2, partial 1 over 6 trace(s) — **3 gap(s)** at d53371a452344082 (layer 2→16), 3e5a051d1a728b75 (layer 2→16), 7f352eb856e47f31 (layer 2→16)；出数不出判定 |
| 155 | INFO | pcb-foc-return-path | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IC-） | return-path projection of 'IC-': covered 1, covered-by-construction 2, none 1, partial 1 over 5 trace(s) — **2 gap(s)** at 77f4b2f52622c860 (layer 2→16), ab766e5de6247798 (layer 2→16)；出数不出判定 |
| 156 | INFO | pcb-foc-return-path | PCB1 | U2、R11、DRV1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U2、R11、DRV1（网 $1N74368、$1N74369、$1N74382、$1N74383、$1N74384、$1N74385、$1N74457、DRV_EN、INHA、INHB、INHC、INLA、INLB、INLC、MISO、MOSI、NFAULT、NSCS、SCK、SHA、SHB、SHC、SLA、SLB、SLC） | **未识别清单**: 25 net(s) that carry tracks and sit on a power-stage part but whose **name** this rule's power-path sieve does not recognise. They are UNKNOWN here, not 「signal nets」 — no projection is claimed for them, and listing them is how the gap becomes visible instead of silent. Measured instance: ROBOT ctrl FOC's gate nets are ``TIM1_CH1`` / ``TIM1_CH2`` / ``TIM1_CH3`` (MCU timer channels driving ``DRV1``'s gate pins), which no power-path prefix matches |
| 157 | INFO | pcb-foc-thermal-exit-path | PCB1 | U2 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U2（网 GND） | thermal pad of U2: pad 'e9', pin '33', net 'GND', 126 × 126 mil (= 15876 sq mil), shape 'RECT', copper on layer(s) [1] — region copper over the pad's projection: layer 1: 7, layer 2: 6, layer 15: 4, layer 16: 4; the pad is in island 9 of 'GND' (16 member(s), layers [1, 2, 15, 16]); the island carries 21644 sq mil of pour; island 9 holds 08c9e04412d58b82, 0f8763b4140b68b2 (2 of this pad's 4 thermal via(s), the pad's own island); island 25 holds b6c0a96a68201cfb (1 of this pad's 4 thermal via(s), a separate island from the pad's); island 26 holds fc857a938cb885e8 (1 of this pad's 4 thermal via(s), a separate island from the pad's); across 3 island(s) for 4 via(s). continuous vs broken 出数不出判定 |
| 158 | INFO | pcb-foc-thermal-via-array | PCB1 | U2 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U2（网 GND） | thermal pad of U2: pad 'e9', pin '33', net 'GND', 126 × 126 mil (= 15876 sq mil), shape 'RECT', copper on layer(s) [1] — **4 vias** in the projection — an array-shaped group; nearest-neighbour pitch 61.1, 57.5, 54.5, 54.5 mil, spread 6.7 mil, so the regularity is visible in the numbers without any pitch threshold being applied; hole 12.008 mil, pad 24.016 mil (TI 参考值 孔 8mil / 盘 20mil，**只写 evidence 不出判定**）; 出数不出判定 |
| 159 | INFO | pcb-foc-thermal-via-style | PCB1 | U2 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U2（网 GND） | thermal pad of U2: pad 'e9', pin '33', net 'GND', 126 × 126 mil (= 15876 sq mil), shape 'RECT', copper on layer(s) [1] — 4 via(s) in the projection, all net 'GND', via_type 'NORMAL', hole 12.008 mil, pad 24.016 mil; 0 of 4 do not reach every copper layer; 「直连 vs thermal relief」与「阻焊覆盖」在模型里**读不出（UNKNOWN）**，如报不作；出数不出判定 |
| 160 | INFO | pcb-foc-track-corners | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 $1N66641） | 55 non-obtuse fold(s) in this board's routing, on 23 net(s); sharpest 45.0° on '$1N66641' — TI §4 图 4-3's 「look at right-angle bends on gate / switching nodes」 is quoted, **nothing is graded** |
| 161 | INFO | pcb-foc-track-corners | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA+） | power-path net 'IA+' bends 135.0° at (448.8, -1641.2) on layer 2 (tracks 2b89caa0f8442e14 / 2bbdb921d0bf3fc9) — a measurement: TI §4 图 4-3 says to look at such bends, and looking is not a verdict |
| 162 | INFO | pcb-foc-track-corners | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA+） | power-path net 'IA+' bends 135.0° at (448.8, -1457.4) on layer 2 (tracks 8488aa2c888f0a7f / ff283eb15e9f1b0b) — a measurement: TI §4 图 4-3 says to look at such bends, and looking is not a verdict |
| 163 | INFO | pcb-foc-track-corners | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 IA+） | power-path net 'IA+' bends 135.0° at (451.1, -1459.8) on layer 2 (tracks 2bc1f10dd75c7b54 / 8488aa2c888f0a7f) — a measurement: TI §4 图 4-3 says to look at such bends, and looking is not a verdict |
| 164 | INFO | pcb-footprint-consistency | PCB1 | USB1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → USB1 | PCB1 USB1 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。原理图声明 'SMD'，PCB 实摆 'USB-C-SMD_TYPE-C-6PIN-2MD-073' |
| 165 | INFO | pcb-footprint-consistency | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB1 封装对账（原理图 Board1）：比了 105 个两边都有的器件——一致 90，焊盘数不符 0，尺寸码不符 14，封装族不符 0，无从比较 1，PCB 侧读不出封装 0；另：原理图有而 PCB 没摆 0 个，PCB 摆而原理图没有 0 个 |
| 166 | INFO | pcb-mcu-crystal-keepout | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1 | X1's region carries **15** copper element(s) on Top Layer: pad X1.4 @ GND; pad X1.3 @ OSC-OUT; pad X1.2 @ GND; pad X1.1 @ OSC-IN; track 59e774f9b7bcb8aa @ GND; track dfb977756e9b7bb7 @ OSC-IN; track 0d54e0b99f1b69d1 @ OSC-IN; track b17fb2e56e04eef2 @ OSC-OUT; track 449b3ea5eae5a125 @ OSC-OUT; track 33a566b8d117386c @ GND; track e12d54e3628dabab @ GND; track 370a8ba4c3a6f0de @ GND; track ba3cf60ef1ce07b2 @ GND; via af0e64b627ae4fa3 @ GND; via 7b3641e73a33bd61 @ GND — no pour region on this layer inside the region — 区内没有别网铜（晶振自身网：'GND', 'OSC-IN', 'OSC-OUT'；网不明的件 0 件按 UNKNOWN 不计判定）；岳 2026-10-11 裁：以内 INFO，本行维持测量 |
| 167 | INFO | pcb-mcu-crystal-keepout | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1 | X1's region carries **2** copper element(s) on Inner1: via af0e64b627ae4fa3 @ GND; via 7b3641e73a33bd61 @ GND — no pour region on this layer inside the region — 区内没有别网铜（晶振自身网：'GND', 'OSC-IN', 'OSC-OUT'；网不明的件 0 件按 UNKNOWN 不计判定）；岳 2026-10-11 裁：以内 INFO，本行维持测量 |
| 168 | INFO | pcb-mcu-crystal-keepout | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1 | X1's region carries **2** copper element(s) on Inner2: via af0e64b627ae4fa3 @ GND; via 7b3641e73a33bd61 @ GND — no pour region on this layer inside the region — 区内没有别网铜（晶振自身网：'GND', 'OSC-IN', 'OSC-OUT'；网不明的件 0 件按 UNKNOWN 不计判定）；岳 2026-10-11 裁：以内 INFO，本行维持测量 |
| 169 | INFO | pcb-mcu-crystal-placement | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1 | U1 declares oscillator pin(s) PC14-OSC32_IN, PC15-OSC32_OUT with **no net at all** — an unpopulated low-frequency branch, so no crystal, no load capacitor and no distance is claimed for it |
| 170 | INFO | pcb-mcu-crystal-placement | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1（网 OSC-IN） | X1.1 @ 'OSC-IN' sits 147.2 mil edge-to-edge from U1.12 ('PH0-OSC_IN' @ 'OSC-IN') — the **same net**, so this is the oscillator loop's own leg — measurement only, no crystal-loop threshold is in force yet |
| 171 | INFO | pcb-mcu-crystal-placement | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1（网 OSC-OUT） | X1.3 @ 'OSC-OUT' sits 77.1 mil edge-to-edge from U1.12 ('PH0-OSC_IN' @ 'OSC-IN') — a **cross-net** reading (the crystal's other oscillator pad against this pin), reported because the loop is closed by both and a reader comparing the two numbers needs both — measurement only, no crystal-loop threshold is in force yet |
| 172 | INFO | pcb-mcu-crystal-placement | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1（网 OSC-IN） | X1.1 @ 'OSC-IN' sits 154.4 mil edge-to-edge from U1.13 ('PH1-OSC_OUT' @ 'OSC-OUT') — a **cross-net** reading (the crystal's other oscillator pad against this pin), reported because the loop is closed by both and a reader comparing the two numbers needs both — measurement only, no crystal-loop threshold is in force yet |
| 173 | INFO | pcb-mcu-crystal-placement | PCB1 | X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → X1（网 OSC-OUT） | X1.3 @ 'OSC-OUT' sits 77.1 mil edge-to-edge from U1.13 ('PH1-OSC_OUT' @ 'OSC-OUT') — the **same net**, so this is the oscillator loop's own leg — measurement only, no crystal-loop threshold is in force yet |
| 174 | INFO | pcb-mcu-crystal-placement | PCB1 | C20 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C20（网 OSC-IN） | C20 on 'OSC-IN': 实测容值 20pF (20pF), 串联等效 CL 15pF, against 规格 CL 20pF — three columns side by side and **no verdict**: 岳 has ruled on no tolerance, so whether the two agree is a human reading, and the numbers are placed together so it cannot be skipped |
| 175 | INFO | pcb-mcu-crystal-placement | PCB1 | C21 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C21（网 OSC-OUT） | C21 on 'OSC-OUT': 实测容值 20pF (20pF), 串联等效 CL 15pF, against 规格 CL 20pF — three columns side by side and **no verdict**: 岳 has ruled on no tolerance, so whether the two agree is a human reading, and the numbers are placed together so it cannot be skipped |
| 176 | INFO | pcb-mcu-reset-boot | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 NRST） | U1 pin 14 'NRST' @ 'NRST': 3 external member(s) — pull-up candidate (a resistor reaching a supply net): R29; capacitor to ground: C39; switch / button: RST1; other member (unclassified): (none); nearest external member **C39** at 34.7 mil edge-to-edge — inventory only, no reset-time / RC / button-distance threshold has been ruled on, and 毕设FOC 1.0.0's own three parts sit 608–638 mil away, which is why this rule prints the numbers and does not judge them |
| 177 | INFO | pcb-mcu-reset-boot | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 $1N74472） | U1 pin 94 'BOOT0' @ '$1N74472': 1 member(s) set the strap — R32 value 10K → other terminals on GND (223.3 mil edge-to-edge) — inventory only, no boot-mode requirement has been ruled on |
| 178 | INFO | pcb-mcu-supply-groups | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 AGND） | U1 supply group 'AGND' — 1 pin(s) (pin 19 'VSSA' (GND)); nearest 高频旁路 (< 1 µF): **C10** 100nF @ 22.3 mil; nearest 储能池 (>= 1 µF): **C33** 10uF @ 553.6 mil — measurements only, no supply-bypass distance threshold is in force yet, and 岳 has ruled on none |
| 179 | INFO | pcb-mcu-supply-groups | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 GND） | U1 supply group 'GND' — 5 pin(s) (pin 10 'VSS' (GND), pin 26 'VSS' (GND), pin 49 'VSS' (GND), pin 74 'VSS' (GND), pin 99 'VSS' (GND)); nearest 高频旁路 (< 1 µF): **C21** 20pF @ 25.6 mil; nearest 储能池 (>= 1 µF): **C46** 2.2uF @ 32.7 mil — measurements only, no supply-bypass distance threshold is in force yet, and 岳 has ruled on none |
| 180 | INFO | pcb-mcu-supply-groups | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 VCC） | U1 supply group 'VCC' — 6 pin(s) (pin 6 'VBAT' (IN), pin 11 'VDD' (IN), pin 27 'VDD' (IN), pin 50 'VDD' (IN), pin 75 'VDD' (IN), pin 100 'VDD' (IN)); nearest 高频旁路 (< 1 µF): **C37** 100nF @ 123.5 mil; nearest 储能池 (>= 1 µF): **C36** 2.2uF @ 683.4 mil — measurements only, no supply-bypass distance threshold is in force yet, and 岳 has ruled on none |
| 181 | INFO | pcb-mcu-supply-groups | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 VCCA） | U1 supply group 'VCCA' — 1 pin(s) (pin 21 'VDDA' (IN)); nearest 高频旁路 (< 1 µF): **C43** 100nF @ 951.1 mil; nearest 储能池 (>= 1 µF): **C44** 2.2uF @ 1011.3 mil — measurements only, no supply-bypass distance threshold is in force yet, and 岳 has ruled on none |
| 182 | INFO | pcb-mcu-supply-groups | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 VREF） | U1 supply group 'VREF' — 1 pin(s) (pin 20 'VREF+' (IN)); nearest 高频旁路 (< 1 µF): **C10** 100nF @ 22.3 mil; nearest 储能池 (>= 1 µF): **none** — the pool holds no capacitor at or above 1 µF that this document places — measurements only, no supply-bypass distance threshold is in force yet, and 岳 has ruled on none |
| 183 | INFO | pcb-mcu-supply-groups | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 $1N66421） | U1 pin 48 'VCAP' sits on net '$1N66421', which is an internal-regulator output and **not** a supply group — pin_role answers None for this name, and the datasheet's capacitor on it is a part of the regulator, not a bypass this MCU's supply is judged by; the net carries: C15 value 2.2uF (116.0 mil edge-to-edge; 两视图不一致，判定用**原理图**值：原理图 '2.2uF' / PCB 文档 '100nF') |
| 184 | INFO | pcb-mcu-supply-groups | PCB1 | U1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U1（网 $1N74470） | U1 pin 73 'VCAP' sits on net '$1N74470', which is an internal-regulator output and **not** a supply group — pin_role answers None for this name, and the datasheet's capacitor on it is a part of the regulator, not a bypass this MCU's supply is judged by; the net carries: C46 value 2.2uF (32.7 mil edge-to-edge; 原理图页未写该值，**回退 PCB 文档值** '2.2uF'（口径：本板板链读出的原理图页没有声明，只能取 PCB 文档的副本）) |
| 185 | INFO | pcb-polarity-orientation | PCB1 | LED1、LED2、LED0805 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → LED1、LED2、LED0805 | PCB1 上 2 颗极性器件共用封装 'LED0805-RD'（顶层），方向却有 2 种：[90.0, 270.0]——同封装同朝向是生产工艺习惯，不统一只作提醒（岳 2026-10-11 裁：降 INFO） |
| 186 | INFO | pcb-polarity-orientation | PCB1 | LED0805 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → LED0805 | PCB1 极性器件读数：2 颗极性器件（其中 2 颗原理图声明了极性脚、0 颗只有库件类型词），涉及 1 种封装名，量出印刷方向标记的 2 颗 |
| 187 | INFO | pcb-regulator-cap-distance | PCB1 | U11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U11（网 +5V） | U11's nearest high-frequency bypass capacitor on its VIN net '+5V' is C30 at 537.7 mil edge-to-edge (pads 4 / 2) — measurement only, no pool threshold is in force yet |
| 188 | INFO | pcb-regulator-cap-distance | PCB1 | U11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U11（网 +5V） | U11's nearest energy storage capacitor on its VIN net '+5V' is C28 at 32.4 mil edge-to-edge (pads 2 / 2) — measurement only, no pool threshold is in force yet |
| 189 | INFO | pcb-regulator-cap-distance | PCB1 | U11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U11（网 $1N74453） | U11 has no high-frequency bypass capacitor measurable against its VOUT net '$1N74453' — the VOUT high-frequency bypass pool is empty on this net (no capacitor on the net at all) |
| 190 | INFO | pcb-regulator-cap-distance | PCB1 | U11 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U11（网 $1N74453） | U11 has no energy storage capacitor measurable against its VOUT net '$1N74453' — the VOUT energy storage pool is empty on this net (no capacitor on the net at all) |
| 191 | INFO | pcb-regulator-cap-distance | PCB1 | U13 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U13（网 +5V） | U13's nearest high-frequency bypass capacitor on its VIN net '+5V' is C30 at 58.8 mil edge-to-edge (pads 3 / 1) — measurement only, no pool threshold is in force yet |
| 192 | INFO | pcb-regulator-cap-distance | PCB1 | U13 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U13（网 +5V） | U13's nearest energy storage capacitor on its VIN net '+5V' is C38 at 47.9 mil edge-to-edge (pads 1 / 1) — measurement only, no pool threshold is in force yet |
| 193 | INFO | pcb-regulator-cap-distance | PCB1 | U13 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U13（网 $1N66627） | U13's nearest high-frequency bypass capacitor on its VOUT net '$1N66627' is C41 at 115.9 mil edge-to-edge (pads 5 / 1) — measurement only, no pool threshold is in force yet |
| 194 | INFO | pcb-regulator-cap-distance | PCB1 | U13 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U13（网 $1N66627） | U13's nearest energy storage capacitor on its VOUT net '$1N66627' is C40 at 43.4 mil edge-to-edge (pads 5 / 1) — measurement only, no pool threshold is in force yet |
| 195 | INFO | pcb-regulator-cap-distance | PCB1 | U7 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U7（网 +24V） | U7 has no high-frequency bypass capacitor measurable against its VIN net '+24V' — the VIN high-frequency bypass pool is empty on this net (no capacitor on the net at all) |
| 196 | INFO | pcb-regulator-cap-distance | PCB1 | U7 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U7（网 +24V） | U7's nearest energy storage capacitor on its VIN net '+24V' is C17 at 26.4 mil edge-to-edge (pads 4 / 1) — measurement only, no pool threshold is in force yet |
| 197 | INFO | pcb-regulator-cap-distance | PCB1 | U7 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U7 | U7 declares no pin whose name reads as VOUT, so its VOUT side has no net to measure and neither VOUT pool is examined — the pin names this rule could not classify are in the evidence |
| 198 | INFO | pcb-regulator-fb-placement | PCB1 | U7 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U7（网 $1N66466） | U7's feedback divider R20/R23 at the U7.5 FB pin on '$1N66466': upper leg R20 at 646.4 mil (pads 6 / 1); lower leg R23 at 560.1 mil (pads 6 / 2); FB-node capacitor C22 at 38.8 mil from U7 (pads 6 / 1); the upper leg's non-tap end is on '+5V', which is the non-ground net of a capacitor on this regulator's output node (+5V) — the divider senses on the output-capacitor end; the nearest high-frequency bypass capacitor on that output node is C23 at 33.8 mil from the upper leg R20 (pads 1 / 1) — measurement only, no FB threshold is in force yet |
| 199 | INFO | pcb-silk-designator | PCB1 | U4、U6 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → U4、U6 | PCB1 有 2 个位号**在宽字形模型下**压到焊盘（最窄档 0.4 量不出相交）：2 处，压不压取决于字形实际多宽，本规则不判 |
| 200 | INFO | pcb-silk-designator | PCB1 | R20、L1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → R20、L1 | PCB1 有 1 处位号丝印**部分**落在别的器件本体轮廓内（没被完全盖住，仍看得见一部分）：本规则不判 |
| 201 | INFO | pcb-silk-designator | PCB1 | C1、C10、C11、C12、C13、C15、C16、C17、C18、C19、C2、C20、C21、C22、C23、C24、C25、C26、C27、C28、C29、C3、C30、C31、C32、C33、C34、C35、C36、C37、C38、C39、C4、C40、C41、C42、C43、C44、C45、C46、C5、C6、C7、C8、C9、CN1、L1、L2、L3、L4、LED1、LED2、R1、R10、R11、R12、R13、R14、R15、R16、R17、R18、R19、R2、R21、R22、R24、R25、R26、R27、R28、R29、R3、R30、R31、R32、R4、R5、R6、R7、R8、R9、U1、U10、U11、U12、U13、U14、U15、U16、U2、U3、U5、U7、U8、U9、USB1、X1 | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → C1、C10、C11、C12、C13、C15、C16、C17、C18、C19、C2、C20、C21、C22、C23、C24、C25、C26、C27、C28、C29、C3、C30、C31、C32、C33、C34、C35、C36、C37、C38、C39、C4、C40、C41、C42、C43、C44、C45、C46、C5、C6、C7、C8、C9、CN1、L1、L2、L3、L4、LED1、LED2、R1、R10、R11、R12、R13、R14、R15、R16、R17、R18、R19、R2、R21、R22、R24、R25、R26、R27、R28、R29、R3、R30、R31、R32、R4、R5、R6、R7、R8、R9、U1、U10、U11、U12、U13、U14、U15、U16、U2、U3、U5、U7、U8、U9、USB1、X1 | PCB1 有 100 个位号的丝印被关掉（``valueVisible=false``）：板上不会印出这些位号——本规则只报读数，不判「是不是忘了打开」 |
| 202 | INFO | pcb-silk-designator | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB1 BOT_SILK（3 个位号）文字方向分布：0°×1, 90°×1, 270°×1 |
| 203 | INFO | pcb-silk-designator | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB1 TOP_SILK（2 个位号）文字方向分布：0°×1, 270°×1 |
| 204 | INFO | pcb-silk-designator | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB1 丝印读数：105 个位号记录（显示 5、关掉 100），板上焊盘 430 只、器件本体轮廓 104 个；文字宽度：实测（宿主 primitive bbox） 0 个、估算值（字宽比带，非读数） 5 个 |
| 205 | INFO | pcb-voltage-spacing | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 VCC） | net 'VCC' has no established voltage, so its spacing against every other net cannot be judged — establish it at requirements.rails[net=VCC].voltage (or .targetVoltage) in the design-intent contract, or let the architecture enumeration find it (a net name that states its voltage, or a shelf regulator's output). This rule never reads a voltage out of a net's name |
| 206 | INFO | pcb-voltage-spacing | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 VCCA） | net 'VCCA' has no established voltage, so its spacing against every other net cannot be judged — establish it at requirements.rails[net=VCCA].voltage (or .targetVoltage) in the design-intent contract, or let the architecture enumeration find it (a net name that states its voltage, or a shelf regulator's output). This rule never reads a voltage out of a net's name |
| 207 | INFO | pcb-voltage-spacing | PCB1 |  | outputs\bug98\live\foc.epro2 → PCB1 → 页:（本档无页信息） → 未标注（网 VREF） | net 'VREF' has no established voltage, so its spacing against every other net cannot be judged — establish it at requirements.rails[net=VREF].voltage (or .targetVoltage) in the design-intent contract, or let the architecture enumeration find it (a net name that states its voltage, or a shelf regulator's output). This rule never reads a voltage out of a net's name |
| 208 | INFO | pcb-derating-package | PCB2 | R1、R2、R3 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → R1、R2、R3 | PCB2 电阻降额读数：认出 4 颗电阻（另有 0 Ω 跳线 0 颗、位号像电阻但值与库件都没说是电阻的 0 颗，本规则不判它们）；两脚都有价的 0 颗、封装档认得出的 4 颗、串联串 0 条 |
| 209 | INFO | pcb-foc-gate-trace-width | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | no net on this board has a power-path name that core.measure's reader recognises ('GH', 'GL', 'MOT', 'IA', 'IB', 'IC' families, gate nets matching '^(?:GH\|GL)[A-Z]?\\d*$'), so no gate trace width is reported — the net **name** is the only place the drawing states a net is a gate net, and a gate net spelled outside these families would land here |
| 210 | INFO | pcb-foc-ground-domains | PCB2 | R1 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → R1 | this PCB document carries 1 ground-class net(s) and **no power-domain ground**: no net name matches 'PGND', 'P_GND', 'POWER_GND', 'EARTH'. R1 asks whether two ground domains touch in copper, and with one domain there is nothing to compare — so **no pair is reported** rather than a pair against a domain that is not there (「absent, not empty」) |
| 211 | INFO | pcb-foc-ground-plane | PCB2 | R31 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → R31 | this PCB document reads 2 copper layer(s) in its physical stackup, below the 4-layer threshold, so it is a **two-layer board and R31 does not apply to it** — TI §1.2's concern is a continuous return path across the inner layers, which a board this thin does not have. No island count and no coverage figure is claimed |
| 212 | INFO | pcb-foc-ground-tie | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | no power-domain ground on this board (no net name matches 'PGND', 'P_GND', 'POWER_GND', 'EARTH'), so there is no power/logic pair to tie and no 0 Ω single point to look for — **R1b is silent by construction** here rather than filing a finding about a domain that is not there. Measured: ROBOT ctrl FOC and 智能药箱 both read this way |
| 213 | INFO | pcb-foc-track-corners | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注（网 $1N11） | 1 non-obtuse fold(s) in this board's routing, on 1 net(s); sharpest 45.0° on '$1N11' — TI §4 图 4-3's 「look at right-angle bends on gate / switching nodes」 is quoted, **nothing is graded** |
| 214 | INFO | pcb-footprint-consistency | PCB2 | SCREW1 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → SCREW1 | PCB2 SCREW1 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。原理图声明 '插件'，PCB 实摆 'M3螺丝' |
| 215 | INFO | pcb-footprint-consistency | PCB2 | SCREW2 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → SCREW2 | PCB2 SCREW2 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。原理图声明 '插件'，PCB 实摆 'M3螺丝' |
| 216 | INFO | pcb-footprint-consistency | PCB2 | SCREW3 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → SCREW3 | PCB2 SCREW3 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。原理图声明 '插件'，PCB 实摆 'M3螺丝' |
| 217 | INFO | pcb-footprint-consistency | PCB2 | SCREW4 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → SCREW4 | PCB2 SCREW4 无从比较：两边的封装名没有共同的可比 token（尺寸码 / 封装族 / 尺寸数都没有交集），本规则不比较。原理图声明 '插件'，PCB 实摆 'M3螺丝' |
| 218 | INFO | pcb-footprint-consistency | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB2 封装对账（原理图 Board2）：比了 11 个两边都有的器件——一致 7，焊盘数不符 0，尺寸码不符 0，封装族不符 0，无从比较 4，PCB 侧读不出封装 0；另：原理图有而 PCB 没摆 0 个，PCB 摆而原理图没有 0 个 |
| 219 | INFO | pcb-polarity-orientation | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB2 极性器件读数：0 颗极性器件（其中 0 颗原理图声明了极性脚、0 颗只有库件类型词），涉及 0 种封装名，量出印刷方向标记的 0 颗 |
| 220 | INFO | pcb-silk-designator | PCB2 | SCREW1、SCREW2、SCREW3、SCREW4 | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → SCREW1、SCREW2、SCREW3、SCREW4 | PCB2 有 4 个位号的丝印被关掉（``valueVisible=false``）：板上不会印出这些位号——本规则只报读数，不判「是不是忘了打开」 |
| 221 | INFO | pcb-silk-designator | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB2 TOP_SILK（7 个位号）文字方向分布：90°×3, 270°×4 |
| 222 | INFO | pcb-silk-designator | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注 〔缺 refs〕 | PCB2 丝印读数：11 个位号记录（显示 7、关掉 4），板上焊盘 30 只、器件本体轮廓 7 个；文字宽度：实测（宿主 primitive bbox） 0 个、估算值（字宽比带，非读数） 7 个 |
| 223 | INFO | pcb-voltage-spacing | PCB2 |  | outputs\bug98\live\foc.epro2 → PCB2 → 页:（本档无页信息） → 未标注（网 VCC） | net 'VCC' has no established voltage, so its spacing against every other net cannot be judged — establish it at requirements.rails[net=VCC].voltage (or .targetVoltage) in the design-intent contract, or let the architecture enumeration find it (a net name that states its voltage, or a shelf regulator's output). This rule never reads a voltage out of a net's name |

## 警告（WARN）

- `WARN` 1x decap-required-caps（findings[30]）
- `WARN` 1x pcb-silk-designator（findings[51]）
- `WARN` 1x pcb-component-spacing（findings[105]）
- `WARN` 1x pcb-component-spacing（findings[106]）
- `WARN` 1x pcb-component-spacing（findings[107]）
- `WARN` 1x pcb-component-spacing（findings[108]）
- `WARN` 1x pcb-mcu-crystal-keepout（findings[109]）

## 警告分诊（7）

逐条填 `verdict`（有益 / 有害 / 无害）与 `reason`（xianyuyijinban的审查三步之②）：用 `boardwise triage --out <本目录> --key <key> --verdict 有益|有害|无害 --reason …` 写回（key 见下表，它是这条警告的身份；判决同时写进 `warning-triage.json`，所以重跑 `checkup` 不会丢）。主机 ERC 的条目**没有逐条文本**——它的答复只有按 kind 的合计（见 drc.schematic），逐条详情在编辑器底部面板且没有读取接口。

| # | key | 来源 | 级别 | 计数 | 归属模块 | 文本 | verdict | 理由 |
|---|---|---|---|---|---|---|---|---|
| 0 | boardwise-rule:decap-required-caps:U11,pin:5,net:NET10 | boardwise-rule | WARN | 1 | Board1/P1 | U11 pin5: the grounded capacitor on 'NET10' is only 100nF (< required 1uF) | （待填） | （待填） |
| 1 | boardwise-rule:pcb-silk-designator:D2 | boardwise-rule | WARN | 1 | Board3/P1 | PCB3 D2 的位号丝印压在焊盘上：1 只焊盘被压（最深的 D2 pin 1、15.0 mil），最窄字宽档（0.4）下就已经压上 | （待填） | （待填） |
| 2 | boardwise-rule:pcb-component-spacing:R18 | boardwise-rule | WARN | 1 | Board1/P1 | R18 and U16 are 15.1 mil apart edge-to-edge (pads 1 / 3), under the 20 mil house rule | （待填） | （待填） |
| 3 | boardwise-rule:pcb-component-spacing:R22 | boardwise-rule | WARN | 1 | Board1/P1 | R22 and USB1 are 19.2 mil apart edge-to-edge (pads 1 / 11), under the 20 mil house rule | （待填） | （待填） |
| 4 | boardwise-rule:pcb-component-spacing:R24 | boardwise-rule | WARN | 1 | Board1/P1 | R24 and USB1 are 19.2 mil apart edge-to-edge (pads 2 / 2), under the 20 mil house rule | （待填） | （待填） |
| 5 | boardwise-rule:pcb-component-spacing:U8 | boardwise-rule | WARN | 1 | Board1/P1 | U8 and USB1 are 13.8 mil apart edge-to-edge (pads 5 / 14), under the 20 mil house rule | （待填） | （待填） |
| 6 | boardwise-rule:pcb-mcu-crystal-keepout:X1 | boardwise-rule | WARN | 1 | Board1/P1 | X1's region carries **4** copper element(s) on Bottom Layer: track 2bbdb921d0bf3fc9 @ IA+; track dfbd69b2b06ce1d5 @ IB+; via af0e64b627ae4fa3 @ GND; via 7b3641e73a33bd61 @ GND — no pour region on this layer inside the region — **WARN**：其中 2 件是**别网铜**（track 2bbdb921d0bf3fc9 @ IA+, track dfbd69b2b06ce1d5 @ IB+），落在晶振净空区（外扩 9.84 mil）内；岳 2026-10-11 裁：以外 WARN | （待填） | （待填） |

## 架构骨架 ⊕ 设计意图（合并视图）—— 264 槽

- 骨架：`architecture.md`（自动生成，手填无效）
- 设计意图：`design-intent.md`（工程师所有，生成器只读）——本次不存在，已建全 TODO 模板；projectUuid `file-706893908adb`
- 槽位：合计 264 / 已填 0 / **stale 0** / 待填 264
- 骨架计数：11 轨 / 12 模拟链 / 7 控制链 / 6 总线类

- 其余 264 槽仍是 `TODO`（欠账不是空白）：逐槽填进 `design-intent.md`（填不出来就**显式问工程师**，不许编）。

## 设计意图合同（intent）—— 264 槽 / 已填 0 / 缺 264（必填缺 23）

- 合同：`C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` **不存在**（本报告的槽位清单来自当前工程的枚举；A1 不自动建文件——要生成/重生成契约：`boardwise arch outputs/bug98/live/foc.epro2 --intent C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json`）
- 契约版本：`intentVersion 1`；弱词：`ai_asserted`（**草稿**：buses 'CAN': ai_asserted — an unconfirmed requirement may only be read as a hint (052 §4), never as the yardstick a rule judges a board against；buses 'I2C': ai_asserted — an unconfirmed requirement may only be read as a hint (052 §4), never as the yardstick a rule judges a board against）
- 弱词 `ai_asserted` = AI 猜的：它可以当提示，**不许**当作判违规的尺子（052 §4：未确认的声明只能以明确标注的草稿出门）。
- 重生成差量：新增 TODO 条目 33 · 图纸里已消失（stale，不删只标）0 · 枚举已不再问、但合同里还答着的槽 0

### 必填槽没声明（23）—— `intent-missing`

`intent-missing`（与 `facts-missing` 同族）：这些是**必填槽**，合同里没有声明；工具不会替人补，也不会因此拒绝读合同——它只点名缺哪一句、该写进哪个文件哪个键。

- intent-missing: 轨 `+24V` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=+24V].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:+24V/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `+24V` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=+24V].targetVoltage`（槽位 id `file-706893908adb/7dca2922104db3df/intent:+24V/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `+5V` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=+5V].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:+5V/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `NET10` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=NET10].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:NET10/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `NET11` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=NET11].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:NET11/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `NET12` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=NET12].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:NET12/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `NET18` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=NET18].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:NET18/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `VCC` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=VCC].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:VCC/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `VCC` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=VCC].targetVoltage`（槽位 id `file-706893908adb/5455a645b144c024/intent:VCC/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `VCCA` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=VCCA].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:VCCA/targetVoltage`）；工具只提问，不改写
- intent-missing: 轨 `VREF` 的 `targetVoltage`（目标电压） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.rails[net=VREF].targetVoltage`（槽位 id `file-706893908adb/d5c055266ef55000/intent:VREF/targetVoltage`）；工具只提问，不改写
- intent-missing: 模拟链 `DRV_EN` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=DRV_EN].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:DRV_EN/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `IA` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=IA].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:IA/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `IB` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=IB].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:IB/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `IC` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=IC].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:IC/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `NET14` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=NET14].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:NET14/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `NET30` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=NET30].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:NET30/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `NET4` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=NET4].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:NET4/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `NRST` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=NRST].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:NRST/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `OSC-IN` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=OSC-IN].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:OSC-IN/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `OSC-OUT` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=OSC-OUT].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:OSC-OUT/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `SWCLK` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=SWCLK].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:SWCLK/polarity`）；工具只提问，不改写
- intent-missing: 模拟链 `SWDIO` 的 `polarity`（极性（单向 / 双向）） 没声明 —— 写进 `C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json` 的 `requirements.signals[net=SWDIO].polarity`（槽位 id `file-706893908adb/d5c055266ef55000/analog:SWDIO/polarity`）；工具只提问，不改写

- 其余 241 槽仍是 TODO（欠账不是空白）：逐槽填进合同（`C:\Users\xiangyu\.boardwise\design-intent\file-706893908adb.json`），填不出来就**显式问工程师**，不许编。
- 工具只校验与提问，永不改写：本节点名缺哪一句、写进哪个文件哪个键；填的人是工程师或模型。缺槽**不**抬 verdict（A1 只报告，评级归 A2/A3）——重生成契约用 `boardwise arch <export> --intent <path>`（已有答案逐字节保留）。

## AI 槽位（要模型做的三件事）

### 1. 需要查规格书的器件（116）

| 位号 | 名称 | 值 | 封装 | MPN | 供应商 | 为什么要查 |
|---|---|---|---|---|---|---|
| C10 | CAP_0402 |  | 0402 |  |  | 无 MPN；供应商字段为空 |
| C11 | CAP_0402 | 100pF | 0402 |  |  | 无 MPN；供应商字段为空 |
| C12 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C13 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C15 | CAP_0603 | 2.2uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C16 | CAP_0402 | 100pF | 0402 |  |  | 无 MPN；供应商字段为空 |
| C17 | CAP_1206 | 4.7UF | 1206 |  |  | 无 MPN；供应商字段为空 |
| C18 | CAP_0805 |  | 0805 |  |  | 无 MPN；供应商字段为空 |
| C2 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C20 | CAP_0402 | 20pF | 0402 |  |  | 无 MPN；供应商字段为空 |
| C21 | CAP_0402 | 20pF | 0402 |  |  | 无 MPN；供应商字段为空 |
| C22 | CAP_0805 | 56pF | 0805 |  |  | 无 MPN；供应商字段为空 |
| C23 | CAP_0805 | 22uF | 0805 |  |  | 无 MPN；供应商字段为空 |
| C24 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C25 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C3 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C32 | CAP_0603 | 2.2uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C33 | CAP_0603 | 10uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C34 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C37 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C38 | CAP_0603 | 2.2uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C39 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| C4 | CGA0805X5R106K500MT |  | 0805 | CGA0805X5R106K500MT | C6119889 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C40 | CAP_0603 | 2.2uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C45 | CAP_0603 | 100nF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C46 | C1608X5R1V225KT000E |  | 0603 | C1608X5R1V225KT000E | C342978 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C5 | CAP_0603 | 1uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C6 | CAP_0603 | 1uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C7 | CAP_0603 | 1uF | 0603 |  |  | 无 MPN；供应商字段为空 |
| C8 | CAP_0402 | 100pF | 0402 |  |  | 无 MPN；供应商字段为空 |
| C9 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| L1 | FXL1040-330-M |  | SMD,11.5x10mm | FXL1040-330-M | C475918 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| L2 | DFE252012PD-2R2M=P2 |  | 1008 | DFE252012PD-2R2M=P2 | C237482 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| L3 | DFE252012PD-2R2M=P2 |  | 1008 | DFE252012PD-2R2M=P2 | C237482 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| L4 | DFE252012PD-2R2M=P2 |  | 1008 | DFE252012PD-2R2M=P2 | C237482 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R1 | Res_0603 | 15K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R10 | Res_0603 | 1K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R11 | Res_1206 | 0R | 1206 |  |  | 无 MPN；供应商字段为空 |
| R12 | Res_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| R13 | Res_0603 | 15K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R14 | Res_0603 | 15K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R15 | Res_0603 | 1K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R16 | Res_0603 | 1K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R17 | Res_0402 |  | 0402 |  |  | 无 MPN；供应商字段为空 |
| R18 | Res_0603 | 15K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R19 | RCA03392KFLF |  | 0603 | RCA03392KFLF | C22369707 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R2 | Res_0603 | 1K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R20 | 0805W8F1003T5E | 100kΩ | 0805 | 0805W8F1003T5E | C149504 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R21 | FRC0805F4122TS |  | 0805 | FRC0805F4122TS | C2933440 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R22 | Res_0402 | 5.1K | 0402 |  |  | 无 MPN；供应商字段为空 |
| R23 | 0805W8F1003T5E | 100kΩ | 0805 | 0805W8F1003T5E | C149504 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R24 | Res_0402 | 5.1K | 0402 |  |  | 无 MPN；供应商字段为空 |
| R25 | Res_1206 | 0R | 1206 |  |  | 无 MPN；供应商字段为空 |
| R26 | Res_0603 | 47R | 0603 |  |  | 无 MPN；供应商字段为空 |
| R27 | Res_0603 | 4.7K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R28 | Res_0603 | 120R | 0603 |  |  | 无 MPN；供应商字段为空 |
| R29 | Res_0402 | 10K | 0402 |  |  | 无 MPN；供应商字段为空 |
| R3 | Res_1206 | 0R | 1206 |  |  | 无 MPN；供应商字段为空 |
| R30 | Res_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| R31 | 0603WAF1503T5E |  | 0603 | 0603WAF1503T5E | C22807 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R32 | Res_0603 | 10K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R4 | Res_0603 | 1K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R5 | Res_0603 | 15K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R6 | Res_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| R7 | Res_0603 | 15K | 0603 |  |  | 无 MPN；供应商字段为空 |
| R8 | Res_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| R9 | Res_0603 | 1K | 0603 |  |  | 无 MPN；供应商字段为空 |
| U1 | STM32H743VIT6_C114409 |  | LQFP-100(14x14) | STM32H743VIT6 | C114409 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U10 | FRC0805J471 TS | 1kΩ | 0805 | FRC0805J471 TS | C2907329 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U13 | TPLP2981-30DBVR |  | SOT-23-5 | TPLP2981-30DBVR | C22435132 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U14 | FRC0805J471 TS | 1kΩ | 0805 | FRC0805J471 TS | C2907329 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U2 | DRV8350SRTVR |  | WQFN-32-EP(5x5) | DRV8350SRTVR | C2861195 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U3 | ZX-MX1.25-4PWT |  | SMD,P=1.25mm,卧贴 | ZX-MX1.25-4PWT | C7430470 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U4 | HX PZ2.54-2x6P TP |  | SMD,P=2.54mm | HX PZ2.54-2x6P TP | C32713286 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U6 | HX PZ2.54-2x6P TP |  | SMD,P=2.54mm | HX PZ2.54-2x6P TP | C32713286 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U7 | LM5164DDAR |  | SO-8-EP | LM5164DDAR | C477928 | 货架没有可驱动规则的 facts（条目没有 facts） |
| U8 | MX1.25-LT-3 |  | MX1.25-LT-3P | MX1.25-LT-3 | C9900097986 | 货架没有可驱动规则的 facts（条目没有 facts） |
| C1 | CAP_0603 |  | 0603 |  |  | 无 MPN；供应商字段为空 |
| R1 | Res_0603 | 100R | 0603 |  |  | 无 MPN；供应商字段为空 |
| R2 | Res_0603 | 100R | 0603 |  |  | 无 MPN；供应商字段为空 |
| R3 | Res_0603 | 100R | 0603 |  |  | 无 MPN；供应商字段为空 |
| R4 | Res_0603 | 100R | 0603 |  |  | 无 MPN；供应商字段为空 |
| SCREW1 | M3螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| SCREW2 | M3螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| SCREW3 | M3螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| SCREW4 | M3螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| U1 | TLE5012BE1000 |  | SO-8 | TLE5012BE1000 | C123083 | 货架没有可驱动规则的 facts（条目没有 facts） |
| C1 | PA50V330M10x15 | 330uF | 插件,D10xL15mm | PA50V330M10x15 | C46550457 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C10 | HGC1206R5106K500NSPJ | 10uF | 1206 | HGC1206R5106K500NSPJ | C7432781 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C11 | HGC1206R5106K500NSPJ | 10uF | 1206 | HGC1206R5106K500NSPJ | C7432781 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C115 | PA50V330M10x15 | 330uF | 插件,D10xL15mm | PA50V330M10x15 | C46550457 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C116 | PA50V330M10x15 | 330uF | 插件,D10xL15mm | PA50V330M10x15 | C46550457 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C12 | HGC1206R5106K500NSPJ | 10uF | 1206 | HGC1206R5106K500NSPJ | C7432781 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C2 | CGA0603X7R104K500JT |  | 0603 | CGA0603X7R104K500JT | C6119867 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C4 | PA50V330M10x15 | 330uF | 插件,D10xL15mm | PA50V330M10x15 | C46550457 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C5 | PA50V330M10x15 | 330uF | 插件,D10xL15mm | PA50V330M10x15 | C46550457 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C6 | PA50V330M10x15 | 330uF | 插件,D10xL15mm | PA50V330M10x15 | C46550457 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C7 | HGC1206R5106K500NSPJ |  | 1206 | HGC1206R5106K500NSPJ | C7432781 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C8 | HGC1206R5106K500NSPJ |  | 1206 | HGC1206R5106K500NSPJ | C7432781 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| C9 | HGC1206R5106K500NSPJ | 10uF | 1206 | HGC1206R5106K500NSPJ | C7432781 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R1 | 0805W8J0100T5E |  | 0805 | 0805W8J0100T5E | C25278 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R18 | JER2512F3R005 | 10mΩ | 2512 | JER2512F3R005 | C46634460 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R2 | 0805W8J0100T5E |  | 0805 | 0805W8J0100T5E | C25278 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R3 | 0805W8J0100T5E |  | 0805 | 0805W8J0100T5E | C25278 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R4 | 0805W8J0100T5E |  | 0805 | 0805W8J0100T5E | C25278 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R43 | JER2512F3R005 | 10mΩ | 2512 | JER2512F3R005 | C46634460 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R5 | 0805W8J0100T5E |  | 0805 | 0805W8J0100T5E | C25278 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R6 | 0805W8J0100T5E |  | 0805 | 0805W8J0100T5E | C25278 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| R8 | JER2512F3R005 | 10mΩ | 2512 | JER2512F3R005 | C46634460 | MPN 里的值码解不出（按 values.py 的白名单判定，不是值不存在） |
| SCREW1 | M2螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| SCREW2 | M2螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| SCREW3 | M2螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| SCREW4 | M2螺丝 |  | 插件 |  |  | 无 MPN；供应商字段为空 |
| U1 | PZ2.54-2*6 |  | 插件,P=2.54mm | PZ2.54-2*6 | C5224012 | 货架没有这颗料 |
| U14 | MR30PW-M30.G.Y |  | - | MR30PW-M30.G.Y | C19268036 | 货架没有这颗料 |
| U2 | PZ2.54-2*6 |  | 插件,P=2.54mm | PZ2.54-2*6 | C5224012 | 货架没有这颗料 |

每个器件问同一件事：核对该器件周边配置是否符合规格书典型应用（去耦/上下拉/限流/耐压），并确认可用型号

### 2. 画布图（0）

无图。离线路径（--file）不连编辑器，因此不出画布图；要图就给一个在线工程

### 3. 总结模板（原样留槽，由模型填写）

```text
【结论先行】这台板子<可以直接投板 / 需要先改 N 处 / 问题较多建议重审>：
  主机 ERC <warn/error 计数>，PCB DRC <分组计数>，boardwise 规则 <ERROR/WARN/INFO 计数>。

【错误与归因】（逐条说清是哪一类，不要合并成一句）
  - <位号/规则>: <现象> —— 归因：<设计意图不符 / 器件选型 / 布局布线 / 网表与实物不一致>
  - ...

【警告提醒】（不阻塞投板，但要有人知道）
  - <位号/规则>: <现象> —— 建议：<改 / 可接受，理由>

【建议动作】（给用户的下一步，按优先级）
  1. 先改 <条目>：<怎么做>
  2. 再确认 <条目>：<找谁/查什么>
  3. 存疑项：<unknown_parts 里需要查规格书的器件，逐条写结论>

【本报告依赖的未知项】（needs_datasheet；**这一节空着才允许写"通过"**）
  - <位号/管脚>：<为什么解释不了> —— 需要：<哪份手册的哪一节，或找谁要>
  - 清单非空时，依赖它的条目只能写「无法确认（等资料）」，不许写「通过/不符合」

<可选一段：读画布图看到的问题（摆放、位号可读性、网络标识、区分度）>
```

## 元数据

- 生成时间：2026-10-13T23:07:38+0800
- report schema：`boardwise.checkup/7`
- tier：`file`；pageAttribution：`archive`
- 宿主：(未知)；connector：(未知)
- --file：outputs\bug98\live\foc.epro2
- attempt `file`：ok
