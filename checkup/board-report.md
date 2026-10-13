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
