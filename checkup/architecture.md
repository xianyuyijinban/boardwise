# 架构骨架（architecture.md）

> **自动生成，手填无效——设计意图请填 `design-intent.md`**（生成器对该文件只读：不存在就建全 TODO 模板，存在则一字不改）。
> 工具只列**骨架与槽位**，判不出来的一律留 `TODO`——填槽与自洽性走查是 AI 的活（SKILL「架构走查」）；推断不了的设计意图要**显式问工程师**，不许编。
> 生成器：`boardwise arch`（044 M1）。骨架对**模型**确定：同输入逐字节相同；报告里的合并视图（骨架 ⊕ design-intent.md）对**（模型 + 意图文件）**确定。
> 槽位键（英文）是给机器解析用的，TODO 是**欠账**不是空白。

<!-- board: Board1 -->

## 板：Board1（105 器件 / 99 网）

参考地（3）：`AGND`、`GND`、`PGND`
控制器候选（1）：`U1` — 货架 category=ic.mcu（ic.stm32h743vit6）

### 1. 电源树（9 轨）

#### 轨 `+24V`
- voltage: 24 V（net name '+24V'）
- source: TODO
- sourceCandidates: （无候选：没有任何器件声明自己是源）
- loads（8）：`C17.1`、`R3.1`、`R31.1`、`U6.10`、`U6.12`、`U6.8`、`U7.2`、`U7.3`

#### 轨 `+5V`
- voltage: 5 V（net name '+5V'）
- source: TODO
- sourceCandidates: U11（ic.ldo）、U13（ic.ldo）
- loads（13）：`C19.2`、`C23.2`、`C28.2`、`C29.2`、`C30.2`、`C38.2`、`L1.2`、`L2.1`、`R20.2`、`U11.1`、`U11.3`、`U13.1`、`U13.3`

#### 轨 `NET10`
- voltage: 3.3 V（U11 RT9013-33GB output, decoded from the MPN suffix — a guess: no datasheet fact declares it）
- source: TODO
- sourceCandidates: U11（ic.ldo）
- loads（5）：`C26.1`、`C27.1`、`L3.1`、`U10.1`、`U11.5`

#### 轨 `NET11`
- voltage: TODO（no source names the voltage of net 'NET11'）
- source: TODO
- sourceCandidates: （无候选：没有任何器件声明自己是源）
- loads（4）：`C3.1`、`C4.1`、`R3.2`、`U2.2`

#### 轨 `NET12`
- voltage: TODO（no source names the voltage of net 'NET12'）
- source: TODO
- sourceCandidates: （无候选：没有任何器件声明自己是源）
- loads（3）：`C34.2`、`R26.1`、`U9.4`

#### 轨 `NET18`
- voltage: TODO（no source names the voltage of net 'NET18'）
- source: TODO
- sourceCandidates: （无候选：没有任何器件声明自己是源）
- loads（2）：`C7.1`、`U2.29`

#### 轨 `VCC`
- voltage: TODO（no source names the voltage of net 'VCC'）
- source: TODO
- sourceCandidates: CN1（conn）
- loads（22）：`C13.1`、`C35.2`、`C36.2`、`C37.2`、`C45.1`、`CN1.2`、`L3.2`、`R12.1`、`R29.2`、`R6.2`、`R8.1`、`SWD1.4`、`U1.100`、`U1.11`、`U1.27`、`U1.50`、`U1.6`、`U1.75`、`U12.3`、`U3.3`、`U5.5`、`U5.8`

#### 轨 `VCCA`
- voltage: TODO（no source names the voltage of net 'VCCA'）
- source: TODO
- sourceCandidates: （无候选：没有任何器件声明自己是源）
- loads（6）：`C43.2`、`C44.2`、`L4.2`、`U1.21`、`U15.8`、`U16.8`

#### 轨 `VREF`
- voltage: TODO（no source names the voltage of net 'VREF'）
- source: TODO
- sourceCandidates: （无候选：没有任何器件声明自己是源）
- loads（3）：`C10.2`、`U1.20`、`U9.5`

### 2. 模拟链（12 条）

判定口径：**非电源非地**、≥2 个成员、且至少有 1 个成员接在控制器候选的引脚上（控制器候选 = 货架 `category: ic.mcu`，或符号里 ≥4 个引脚用 `P<端口><数字>` 命名）。工具只列链与槽位；量程/极性/参考点这些**必须由 AI 或工程师给**。

#### 链 `DRV_EN`（4 成员）
- members: `C14.2(2)` — `R17.2(2)` — `U1.44(PE14)` — `U2.22(ENABLE)`
- evidence: 锚点 U1.44：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C14→GND
- evidence: 邻接 R17→GND
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、GND、IA、IB…(+32)
- evidence: 邻接 U2→GHA、GHB、GHC、GLA、GLB、GLC…(+25)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `IA`（5 成员）
- members: `C8.1(1)` — `R5.2(2)` — `U1.23(PA1)` — `U15.1(OUTA)` — `U15.7(OUTB)`
- evidence: 锚点 U1.23：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C8→NET19
- evidence: 邻接 R5→NET19
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IB…(+32)
- evidence: 邻接 U15→AGND、NET19、NET24、VCCA
- evidence: 邻接 U15→AGND、NET19、NET24、VCCA
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `IB`（3 成员）
- members: `C11.1(1)` — `R13.2(2)` — `U1.24(PA2)`
- evidence: 锚点 U1.24：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C11→NET3
- evidence: 邻接 R13→NET3
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `IC`（5 成员）
- members: `C16.1(1)` — `R18.2(2)` — `U1.25(PA3)` — `U16.1(OUTA)` — `U16.7(OUTB)`
- evidence: 锚点 U1.25：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C16→NET5
- evidence: 邻接 R18→NET5
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U16→AGND、NET25、NET5、VCCA
- evidence: 邻接 U16→AGND、NET25、NET5、VCCA
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `NET14`（2 成员）
- members: `C46.2(2)` — `U1.73(VCAP)`
- evidence: 锚点 U1.73：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C46→GND
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `NET30`（2 成员）
- members: `R32.1(1)` — `U1.94(BOOT0)`
- evidence: 锚点 U1.94：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 R32→GND
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `NET4`（2 成员）
- members: `C15.2(2)` — `U1.48(VCAP)`
- evidence: 锚点 U1.48：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C15→GND
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `NRST`（4 成员）
- members: `C39.1(1)` — `R29.1(1)` — `RST1.1(1)` — `U1.14(NRST)`
- evidence: 锚点 U1.14：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C39→GND
- evidence: 邻接 R29→VCC
- evidence: 邻接 RST1→GND
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `OSC-IN`（3 成员）
- members: `C20.2(2)` — `U1.12(PH0-OSC_IN)` — `X1.1(OSC1)`
- evidence: 锚点 U1.12：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C20→GND
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 X1→GND、OSC-OUT
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `OSC-OUT`（3 成员）
- members: `C21.2(2)` — `U1.13(PH1-OSC_OUT)` — `X1.3(OSC2)`
- evidence: 锚点 U1.13：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 C21→GND
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 X1→GND、OSC-IN
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `SWCLK`（2 成员）
- members: `SWD1.1(1)` — `U1.76(PA14)`
- evidence: 锚点 U1.76：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 SWD1→GND、SWDIO、VCC
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `SWDIO`（2 成员）
- members: `SWD1.2(2)` — `U1.72(PA13)`
- evidence: 锚点 U1.72：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 SWD1→GND、SWCLK、VCC
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- quantity: TODO  # 被测物理量
- range: TODO  # 量程
- polarity: TODO  # 极性（单向 / 双向）
- reference: TODO  # 参考点（相对谁测）
- gainStage: TODO  # 增益级
- filter: TODO  # 滤波
- sourceImpedance: TODO  # 源阻抗
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

### 3. 控制链（7 条）

判定口径：网名命中控制特征（`TIM`/`PWM`/`GATE`/`EN`/`IN`/`INH`/`FAULT`/`SLEEP`/`RESET`…），且接入控制器候选引脚。`endpointConsistency` 就是 TIM1 那类案子的机械入口：网名说它是什么功能，端点引脚说它是什么功能，两者要对得上。

#### 链 `INHA`（2 成员）
- members: `U1.43(PE13)` — `U2.23(INHA)`
- evidence: 锚点 U1.43：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U2→DRV_EN、GHA、GHB、GHC、GLA、GLB…(+25)
- endpointConsistency: TODO  # 网名 vs 端点复用功能是否一致
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `INHB`（2 成员）
- members: `U1.41(PE11)` — `U2.25(INHB)`
- evidence: 锚点 U1.41：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U2→DRV_EN、GHA、GHB、GHC、GLA、GLB…(+25)
- endpointConsistency: TODO  # 网名 vs 端点复用功能是否一致
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `INHC`（2 成员）
- members: `U1.39(PE9)` — `U2.27(INHC)`
- evidence: 锚点 U1.39：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U2→DRV_EN、GHA、GHB、GHC、GLA、GLB…(+25)
- endpointConsistency: TODO  # 网名 vs 端点复用功能是否一致
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `INLA`（2 成员）
- members: `U1.42(PE12)` — `U2.24(INLA)`
- evidence: 锚点 U1.42：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U2→DRV_EN、GHA、GHB、GHC、GLA、GLB…(+25)
- endpointConsistency: TODO  # 网名 vs 端点复用功能是否一致
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `INLB`（2 成员）
- members: `U1.40(PE10)` — `U2.26(INLB)`
- evidence: 锚点 U1.40：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U2→DRV_EN、GHA、GHB、GHC、GLA、GLB…(+25)
- endpointConsistency: TODO  # 网名 vs 端点复用功能是否一致
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `INLC`（2 成员）
- members: `U1.38(PE8)` — `U2.28(INLC)`
- evidence: 锚点 U1.38：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U2→DRV_EN、GHA、GHB、GHC、GLA、GLB…(+25)
- endpointConsistency: TODO  # 网名 vs 端点复用功能是否一致
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### 链 `NFAULT`（3 成员）
- members: `R8.2(2)` — `U1.45(PE15)` — `U2.17(nFAULT)`
- evidence: 锚点 U1.45：货架 category=ic.mcu（ic.stm32h743vit6）
- evidence: 邻接 R8→VCC
- evidence: 邻接 U1→AGND、CAN_RX、CAN_TX、DRV_EN、GND、IA…(+32)
- evidence: 邻接 U2→DRV_EN、GHA、GHB、GHC、GLA、GLB…(+25)
- endpointConsistency: TODO  # 网名 vs 端点复用功能是否一致
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

### 4. 总线表（5 类）

#### CAN（4 网）
- `CAN_H`：`R28.2`、`U12.7`、`U8.3`
- `CAN_L`：`R28.1`、`U12.6`、`U8.2`
- `CAN_RX`：`U1.70`、`U12.4`
- `CAN_TX`：`U1.71`、`U12.1`
- completeness: TODO  # 成员完整性（终端 / 上下拉 / 收发器 / 方向）
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### I2C（2 网）
- `IIC1_SCL`：`U1.92`、`U3.1`
- `IIC1_SDA`：`U1.93`、`U3.2`
- completeness: TODO  # 成员完整性（终端 / 上下拉 / 收发器 / 方向）
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### SPI（8 网）
- `MISO`：`R6.1`、`U1.30`、`U2.18`
- `MOSI`：`U1.31`、`U2.19`
- `NSCS`：`R12.2`、`U1.28`、`U2.21`
- `SCK`：`U1.29`、`U2.20`
- `SPI3_MISO`：`CN1.5`、`U1.79`
- `SPI3_MOSI`：`CN1.6`、`U1.80`
- `SPI3_NSS`：`CN1.3`、`U1.77`
- `SPI3_SCK`：`CN1.4`、`U1.78`
- completeness: TODO  # 成员完整性（终端 / 上下拉 / 收发器 / 方向）
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### UART（2 网）
- `RX`：`U1.54`、`U5.6`
- `TX`：`U1.53`、`U5.7`
- completeness: TODO  # 成员完整性（终端 / 上下拉 / 收发器 / 方向）
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

#### USB（3 网）
- `D+`：`U5.1`、`USB1.6`、`USB1.8`
- `D-`：`U5.2`、`USB1.5`、`USB1.7`
- `VBUS`：`R30.1`、`R31.2`、`U1.15`
- completeness: TODO  # 成员完整性（终端 / 上下拉 / 收发器 / 方向）
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

### 5. 设计意图槽位（28 条对象）

这些数只存在于工程师脑中：工具推不出来，AI 也不许编。**推断不了的显式问工程师**，答后把答案写进 `design-intent.md`（这份骨架是自动生成的，手填无效）：以后 finding 以它为尺，需求变了就改那里。

| 对象 | targetVoltage | continuousCurrent | peakCurrent | operatingCases |
|---|---|---|---|---|
| 轨 `+24V` | TODO | TODO | TODO | TODO |
| 轨 `+5V` | TODO | TODO | TODO | TODO |
| 轨 `NET10` | TODO | TODO | TODO | TODO |
| 轨 `NET11` | TODO | TODO | TODO | TODO |
| 轨 `NET12` | TODO | TODO | TODO | TODO |
| 轨 `NET18` | TODO | TODO | TODO | TODO |
| 轨 `VCC` | TODO | TODO | TODO | TODO |
| 轨 `VCCA` | TODO | TODO | TODO | TODO |
| 轨 `VREF` | TODO | TODO | TODO | TODO |
| 控制链 `INHA` | TODO | TODO | TODO | TODO |
| 控制链 `INHB` | TODO | TODO | TODO | TODO |
| 控制链 `INHC` | TODO | TODO | TODO | TODO |
| 控制链 `INLA` | TODO | TODO | TODO | TODO |
| 控制链 `INLB` | TODO | TODO | TODO | TODO |
| 控制链 `INLC` | TODO | TODO | TODO | TODO |
| 控制链 `NFAULT` | TODO | TODO | TODO | TODO |
| 模拟链 `DRV_EN` | TODO | TODO | TODO | TODO |
| 模拟链 `IA` | TODO | TODO | TODO | TODO |
| 模拟链 `IB` | TODO | TODO | TODO | TODO |
| 模拟链 `IC` | TODO | TODO | TODO | TODO |
| 模拟链 `NET14` | TODO | TODO | TODO | TODO |
| 模拟链 `NET30` | TODO | TODO | TODO | TODO |
| 模拟链 `NET4` | TODO | TODO | TODO | TODO |
| 模拟链 `NRST` | TODO | TODO | TODO | TODO |
| 模拟链 `OSC-IN` | TODO | TODO | TODO | TODO |
| 模拟链 `OSC-OUT` | TODO | TODO | TODO | TODO |
| 模拟链 `SWCLK` | TODO | TODO | TODO | TODO |
| 模拟链 `SWDIO` | TODO | TODO | TODO | TODO |

### 附：未归类非电源网（49）

这些网既不在电源树上，也没有控制器引脚（或只有 1 个成员），所以没进上面任何一节；它们由规则引擎与模块走查覆盖，这里只登记名字，不猜用途：

`5VA`、`GHA`、`GHB`、`GHC`、`GLA`、`GLB`、`GLC`、`IA+`、`IA-`、`IB+`、`IB-`、`IC+`、`IC-`、`NET1`、`NET13`、`NET15`、`NET16`、`NET17`、`NET19`、`NET2`、`NET22`、`NET23`、`NET24`、`NET25`、`NET26`、`NET27`、`NET28`、`NET29`、`NET3`、`NET31`、`NET5`、`NET6`、`NET7`、`NET8`、`NET87`、`NET88`、`NET89`、`NET9`、`NET90`、`NET91`、`NET92`、`NET96`、`SHA`、`SHB`、`SHC`、`SLA`、`SLB`、`SLC`、`VCC/2`

<!-- board: Board2 -->

## 板：Board2（11 器件 / 13 网）

参考地（1）：`GND`
控制器候选：**无**（本板没有货架标为 `ic.mcu`、也没有 ≥4 个端口命名引脚的器件）——链级走查以别处的控制器为准，跨板链在这里只能留 TODO

### 1. 电源树（1 轨）

#### 轨 `VCC`
- voltage: TODO（no source names the voltage of net 'VCC'）
- source: TODO
- sourceCandidates: CN2（conn）
- loads（3）：`C1.1`、`CN2.2`、`U1.6`

### 2. 模拟链（0 条）

判定口径：**非电源非地**、≥2 个成员、且至少有 1 个成员接在控制器候选的引脚上（控制器候选 = 货架 `category: ic.mcu`，或符号里 ≥4 个引脚用 `P<端口><数字>` 命名）。工具只列链与槽位；量程/极性/参考点这些**必须由 AI 或工程师给**。

（没有符合口径的模拟链。）

### 3. 控制链（0 条）

判定口径：网名命中控制特征（`TIM`/`PWM`/`GATE`/`EN`/`IN`/`INH`/`FAULT`/`SLEEP`/`RESET`…），且接入控制器候选引脚。`endpointConsistency` 就是 TIM1 那类案子的机械入口：网名说它是什么功能，端点引脚说它是什么功能，两者要对得上。

（没有符合口径的控制链。）

### 4. 总线表（1 类）

#### SPI（4 网）
- `SPI3_MISO`：`CN2.5`、`R2.1`
- `SPI3_MOSI`：`CN2.6`、`R1.1`
- `SPI3_NSS`：`CN2.3`、`R4.1`
- `SPI3_SCK`：`CN2.4`、`R3.1`
- completeness: TODO  # 成员完整性（终端 / 上下拉 / 收发器 / 方向）
- consistency: TODO  # 端到端自洽性（这条链是干什么的、能不能闭合）

### 5. 设计意图槽位（1 条对象）

这些数只存在于工程师脑中：工具推不出来，AI 也不许编。**推断不了的显式问工程师**，答后把答案写进 `design-intent.md`（这份骨架是自动生成的，手填无效）：以后 finding 以它为尺，需求变了就改那里。

| 对象 | targetVoltage | continuousCurrent | peakCurrent | operatingCases |
|---|---|---|---|---|
| 轨 `VCC` | TODO | TODO | TODO | TODO |

### 附：未归类非电源网（7）

这些网既不在电源树上，也没有控制器引脚（或只有 1 个成员），所以没进上面任何一节；它们由规则引擎与模块走查覆盖，这里只登记名字，不猜用途：

`NET3`、`NET4`、`NET5`、`NET6`、`NET7`、`NET8`、`NET9`

<!-- board: Board3 -->

## 板：Board3（39 器件 / 35 网）

参考地（1）：`PGND`
控制器候选：**无**（本板没有货架标为 `ic.mcu`、也没有 ≥4 个端口命名引脚的器件）——链级走查以别处的控制器为准，跨板链在这里只能留 TODO

### 1. 电源树（1 轨）

#### 轨 `+24V`
- voltage: 24 V（net name '+24V'）
- source: TODO
- sourceCandidates: CN3（conn）
- loads（32）：`C1.1`、`C115.1`、`C116.1`、`C13.2`、`C2.2`、`C3.2`、`C4.1`、`C5.1`、`C6.1`、`CN3.2`、`D2.2`、`Q1.5`、`Q1.6`、`Q1.7`、`Q1.8`、`Q1.9`、`Q3.5`、`Q3.6`、`Q3.7`、`Q3.8`、`Q3.9`、`Q7.5`、`Q7.6`、`Q7.7`、`Q7.8`、`Q7.9`、`R2.2`、`R4.2`、`R5.2`、`U2.11`、`U2.7`、`U2.9`

### 2. 模拟链（0 条）

判定口径：**非电源非地**、≥2 个成员、且至少有 1 个成员接在控制器候选的引脚上（控制器候选 = 货架 `category: ic.mcu`，或符号里 ≥4 个引脚用 `P<端口><数字>` 命名）。工具只列链与槽位；量程/极性/参考点这些**必须由 AI 或工程师给**。

（没有符合口径的模拟链。）

### 3. 控制链（0 条）

判定口径：网名命中控制特征（`TIM`/`PWM`/`GATE`/`EN`/`IN`/`INH`/`FAULT`/`SLEEP`/`RESET`…），且接入控制器候选引脚。`endpointConsistency` 就是 TIM1 那类案子的机械入口：网名说它是什么功能，端点引脚说它是什么功能，两者要对得上。

（没有符合口径的控制链。）

### 4. 总线表（0 类）

（没有命中已知协议网名的网。）

### 5. 设计意图槽位（1 条对象）

这些数只存在于工程师脑中：工具推不出来，AI 也不许编。**推断不了的显式问工程师**，答后把答案写进 `design-intent.md`（这份骨架是自动生成的，手填无效）：以后 finding 以它为尺，需求变了就改那里。

| 对象 | targetVoltage | continuousCurrent | peakCurrent | operatingCases |
|---|---|---|---|---|
| 轨 `+24V` | TODO | TODO | TODO | TODO |

### 附：未归类非电源网（33）

这些网既不在电源树上，也没有控制器引脚（或只有 1 个成员），所以没进上面任何一节；它们由规则引擎与模块走查覆盖，这里只登记名字，不猜用途：

`GHA`、`GHB`、`GHC`、`GLA`、`GLB`、`GLC`、`IA+`、`IA-`、`IB+`、`IB-`、`IC+`、`IC-`、`MOTA`、`MOTB`、`MOTC`、`NET1`、`NET10`、`NET11`、`NET12`、`NET13`、`NET2`、`NET3`、`NET4`、`NET5`、`NET6`、`NET7`、`SHA`、`SHB`、`SHC`、`SLA`、`SLB`、`SLC`、`Symbol`
