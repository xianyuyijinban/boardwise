# 017 — 独立评测集扩充：8–12 块真实板/circuit 片段（草稿，待xianyuyijinban审）

> 2026-09-21 起草。来源：xianyuyijinban的 M3 指令并行线——"现在的 33/33 很有价值，但主要来自注入板和少量项目，
> 不能代表广泛泛化"。本任务与 016（edit 闭环）并行，不动规则、不动 harness 语义。
>
> **本任务书是草稿**：选板清单与标注节奏需要xianyuyijinban裁决（见 §六"要xianyuyijinban出的力"），裁完转正式。
> 基线：commit `91b67f3`；既有评测资产：7 注入板（`reviewsets/injected/`）+ 毕设板标注集
> （`reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`）。
> **2026-09-27 xianyuyijinban裁决：board24v 出局**（"早期的，没有任何意义，直接看毕设FOC"），triage 草稿随撤
> （git 历史 `fbc98ad` 仍可溯）；FOC 谱系代表由已在集内、已全裁的毕设FOC担任。

## 一、目标与口径

新增 8–12 个独立原理图/电路片段进评测集，使评测结论不再只由"注入缺陷 + 2 个项目"支撑。
**既有数字一律不改写**：`outputs/011e*/014*/015b*` 是历史基线；新集合的报告全部落 `outputs/017_*` 新文件。

三种样例都要有（xianyuyijinban原话）：**正常样例**（规则应安静或只报 UNKNOWN）、**真实缺陷**（板上原生问题）、
**合理例外**（规则会报但 oracle 判 exception）。UNKNOWN 不是失败——它是指路牌（facts 库 intake 优先级），
但必须统计覆盖率，防止规则用 UNKNOWN 逃避判定。

## 二、选板标准（候选池来自xianyuyijinban的工程库）

| 标准 | 理由 |
|---|---|
| 拓扑多样：LDO/DC-DC、MCU 最小系统、晶振/复位、UART/USB、采样/运放、LED/按键 | 覆盖 15 条规则的适用面，而不是只考同一种电路 |
| 规模 15–100 件 | 太小测不出定位能力，太大标注成本爆炸 |
| 至少 2 块"干净板"（作者认为无缺陷） | 测误报（精确率的真分母） |
| 至少 2 块"已知带病板" | 测检出（带病板从候选池另选；board24v 已于 2026-09-27 被xianyuyijinban裁决出局，见文首） |
| 至少 1 块含陌生器件（facts 库未收录） | 测 UNKNOWN 行为与降级路径 |

候选池（截图所见，xianyuyijinban确认可用性与隐私）：高速电机控制器、反激辅助电源、双管并联100A FOC驱动、
差分电压采样、键盘、基于STM32G431的智能风扇、stm32G4控制板、12V9V转5V3.3V DC-DC、
FPC触屏游戏机、超声波、云台、24V FOC驱动板、UAV遥控器、ROBOT ctrl FOC、M3-DMT-LJB-V1.0.1。
**已在集内的不重复计入**：毕设FOC驱动板、智能药箱（夹具）、CH340G（黄金）。

### 二b、候选池普查（2026-09-27 bridge 在线只读实测，非估计）

5 窗在线拉取 .epro2 跑 review（拉取法：`sys.get_project_file` → 本地解码，免手动导出；此法可替代人工导出步骤）：

| 板 | 器件/网 | ERROR/WARN/INFO | 角色判定 |
|---|---|---|---|
| F28379D开发板26式V2 | 311/210 | 0/0/582 | **朋友的板（第三方，xianyuyijinban 2026-09-27 定性）**：不入库，本地只读评测。超 15–100 上限；用途=大规模干净锚点 + facts 沙漠 UNKNOWN 考场；arch 骨架已验证可跑（9 轨/54 TODO 槽） |
| 级联多电平-主拓扑 | 58/33 | 0/0/0 | 干净正常样例，holdout 候选（待入库权裁决） |
| LLC全桥副边 | 47/25 | 0/0/0 | **= dev 夹具 `llc_board.epro2`**（文件哈希异，47 器件逐值/40 网逐名全同）→ 只 dev 侧，永无 holdout 资格 |
| 级联多电平-驱动模块 | 42/33 | 0/4/10 | 4 WARN 全为 MPN 译码误报（逐条外证，见下）→ "合理例外"样例，holdout 候选 |
| 毕设滤波采样 | 56/32 | 0/2/22 | 2 WARN 同为译码误报 → "合理例外"样例，holdout 候选 |

**WARN 误报外证**（裁定依据，同时是 3 个新 MPN 译码缺口的立案证据）：`0603WAF220KT5E`=厚声 2.2Ω±1%
（立创商城页实证，译码器误读 20kΩ）；`AR03BTCX5001`=Viking 精密薄膜 5.00kΩ（5001=E-96 码，误读 0.03Ω）；
`SPZ1HM100E07O00RAXXX`=Aishi 聚合物 10µF（误读 10pF）。译码修复另立任务书，本任务不动规则。

**证伪记录**：`.eprj2` = SQLite 工程壳（schematics/boards/components 等内容表 0 行），图纸数据不随单文件走
→ .eprj2 支持不值得做，探针杀死于立案前。

## 三、split 纪律（比 011 更严）

- **按板分 split，不按 finding**：每块板整体进 dev 或 holdout，在**任何规则调试之前**确定，
  冻结进测试（沿用 `FROZEN_DEV`/`FROZEN_HOLDOUT` 模式，重抽 = 测试红）。
- holdout 板**不参与**规则开发与调参；dev 板可用于规则改进，但每改一次规则，holdout 只复跑不回头调。
- 目标比例：holdout ≥ 1/3（011 §六的既有标准）。
- 每块板的 split、来源、标注日期、`reviewed_by` 全部写进标注 JSON，签名前一律 `[DRAFT]`（harness 已认这个标记）。

## 四、标注工作流（沿用毕设板模式，逐板一轮）

1. Kimi 对该板跑全量规则，出 **triage 草稿**（`reviewsets/<板名>-triage.md`）：逐条 finding 列规则/位号/证据，
   附"规则自述"（它为什么报）。
2. **xianyuyijinban裁决**：每条勾 defect / exception（写明机制）/ observation（规则没说错但值得记）。
3. Kimi 落标注 JSON（items + observations），变异验证（删记录/降级 ⇒ 测试红），`reviewed_by` 空着直到全板裁完。
4. xianyuyijinban确认后签名 → harness 报告摘 DRAFT 标。

（board24v 原定的"直接走第 2 步"随 2026-09-27 出局裁决作废。）

## 五、度量（在既有检出/精确率之上新增）

| 指标 | 定义 | 现状 |
|---|---|---|
| 高优精确率 / 缺陷检出 | 沿用 review_eval 既有口径 | 已有 |
| UNKNOWN 覆盖 | 有 UNKNOWN outcome 的 (规则×板) 占比 + missing_fact 聚类 top-N | **新增**，harness 加聚合 |
| 定位成功率 | finding 能定位到具体位号/引脚的比例（target 字段非空或 refs 可解析） | **新增**，016 的 Finding.target 落地后更准 |
| 人工确认时间 | xianyuyijinban裁一块板的实际分钟数（triage 草稿时间戳 vs 裁决完成） | 记录即可，不设目标 |
| 修复成功率 | edit apply 后复查 resolved 的比例 | **016 落地后才有**，先在 schema 里留字段 |

模型成本基线（xianyuyijinban指令：M3 之后才优化模型）也从此刻开始记账：每次评测运行记录工具版本、
规则版本、各指标原始分子/分母——不包装小样本（011 既有纪律）。

## 六、要xianyuyijinban出的力（明确报价）

1. **选板**：从候选池勾 8–12 块（含 §二要求的干净/带病/陌生器件配比），指出每块能否进仓库（隐私/客户项目？）。
2. **裁决时间**：每块板 triage 裁决约 10–30 分钟（毕设板 49 条实测量级），可以分批，裁一块落一块。
3. **UNKNOWN 补录优先级**：missing_fact 聚类 top-N 出来后，指定哪些事实先进 facts 库。

## 七、不做

- 不改任何规则判定逻辑（规则改进是发现误报后的独立任务，一规则一任务书）。
- 不改 split 冻结测试的既有集合（注入板×7 + 毕设板原位保留）。
- 不做 PCB 侧评测。
- 不追求板数堆砌——8–12 是上限不是 KPI，标注质量优先。

## 八、验收

- 8–12 块板全部有签名标注 JSON + 变异验证通过；
- `outputs/017_eval_{dev,holdout}.txt` 报告含 §五全部指标（修复成功率字段允许暂缺并注明依赖 016）；
- dev/holdout 冻结测试绿；既有 1145+ 测试与 connector 279 不降；
- 一份《泛化结论》落 outputs：新集合上规则族的真实表现排名 + missing_fact top-N + 给规则改进的输入清单。

## 九、待xianyuyijinban裁决清单

- [ ] 选板：§二b 已实测 3 块 holdout 候选（级联×2 + 毕设滤波采样），**入库权待xianyuyijinban逐板裁决**；DCDC/触屏游戏机/超声波/UAV遥控器 4 块待xianyuyijinban开窗（bridge 拉取）或手动导出 .epro2
- [x] ~~board24v triage 裁决~~ → 2026-09-27 xianyuyijinban裁决出局（早期版无意义，FOC 谱系由毕设FOC代表）
- [x] F28379D 定性 → 朋友的板，本地只读不入库（2026-09-27 xianyuyijinban定性）
- [ ] 标注节奏：一次性排期 vs 裁一块落一块

### 二c、候选池普查第二批（2026-09-27 下午，connector 0.4.25 热更后；入库权xianyuyijinban已下放："你觉得可以进仓就可以进仓"）

新开 6 窗：高速电机控制器 / ROBOT ctrl FOC / 毕设FOC驱动板（均已在仓夹具，身份不变）+ 3 块新候选 + 第一批的毕设滤波采样入库。

| 板 | 器件/网 | ERROR/WARN/INFO | 角色判定 |
|---|---|---|---|
| 超声波 | 24/20 | 0/6/0 | **疑似真实带病板**（xianyuyijinban早期作品）：USB CC 下拉 R1/R2=10k≠5.1k ×2、LED 串阻 20k 超窗、decap ×3——待xianyuyijinban裁决 | **已进仓** `超声波_2026-09-27.epro2`，holdout 候选 |
| 12V9V转5V3.3V DC-DC | 29/9 | 0/2/0 | decap ×2 待裁 | **已进仓** `DCDC-12V9V转5V3V3_2026-09-27.epro2`，holdout 候选 |
| FPC触屏游戏机 | 56/51 | 0/4/11 | USB CC ×2 + decap + R1 MPN 译码误报（`FRL1210FR400TS`=FOJAN 400mΩ，板值 0.4Ω 对，误读 40Ω——第 4 个译码缺口，已外证）→ 缺陷+例外混合样例 | **已进仓** `FPC触屏游戏机_2026-09-27.epro2`，holdout 候选 |
| 毕设滤波采样 | 56/32 | 0/2/22 | 第一批已普查（2 WARN=译码误报） | **已进仓** `毕设滤波采样_2026-09-27.epro2`，holdout 候选 |

入库裁决执行：4 块均为个人学习/毕设谱系板，无公司痕迹，ALLOWLIST 22→29（同 commit 收录）。
**拦截待确认**：级联多电平-主拓扑 / 级联多电平-驱动模块——拓扑像电源产品线（级联多电平+LLC 族），R4 保守不入库，等xianyuyijinban定性。
夹具新鲜度未核：高速电机/ROBOT/毕设FOC 三窗的在线工程与仓内夹具是否同版，另列。

**同批修复（普查暴露的真漏洞）**：repo 卫生闸门对非 ASCII 文件名失明——git quotepath 转义后的引号使 `(/|$)` 锚失配，
3 块中文名既有夹具（智能药箱/毕设FOC/高速电机）一直在闸门视野之外；修=统一 `git -z` NUL 分隔（闸门+测试两处），
ALLOWLIST 补录 3 块既有 + 4 块新板；变异验证=中文名假公司板两条全 CAUGHT。
