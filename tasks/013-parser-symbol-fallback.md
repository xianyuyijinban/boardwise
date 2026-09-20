# 任务书 013：解析器 Symbol 回退修复（地基级）+ 全量重测

**状态**：待 DeepSeek 执行 | **优先级**：最高（解析器地基，阻塞 M1 收官） | **提出**：Kimi（2026-09-20，根因已查证闭环）

---

## 〇、纪律（先读）

- 不动 git；临时文件用完即清；append 类写入后**独立计数**防双执行。
- pytest 必须 `--basetemp=.tmp_pt_home`；交卷前三线全跑（pytest / connector `npm test` / `tsc --noEmit`）。
- 本任务书附带的**根因证据已全部实测验证**，不要重复调查；你的活是**正式实现 + 测试 + 重测**。

## 一、根因（Kimi 已查证，证据在此）

EasyEDA 对**早期放置的基础件**（R/C/L/TP，ticket 小的老实例）**不在实例里写 `Symbol` ATTR**。毕设板实测：132 个实例带 `Symbol`，25 个不带——与"空引脚组件"清单 1:1 吻合。

但这 25 件的 **Device META 的 `attributes.Symbol` 一直在**，且指向的 SYMBOL 文档在文件里、带完整 PIN 记录（`Capacitance`=`415a1d7e…` 2 脚、`Resistor`=`ca557e40…` 2 脚、电感=`a694e686…` 2 脚）。

解析器 `build_schematic_model`（`src/boardwise/parsers/schematic.py:719`）只读 `inst.attrs["Symbol"]`，缺席即静默跳过引脚实例化 → 25 件引脚为空 → 连接关系全丢。

**独立证据（PCB 侧 PAD_NET）**：C20 pad2→OSC-IN / pad1→GND，C21 pad2→OSC-OUT / pad1→GND。Kimi 临时打补丁验证：修复后原理图侧 25 件全部入网，且 C20/C21 与 PAD_NET **连引脚号都一致**。补丁已还原，源码未动。

## 二、影响面（pre-fix 普查，已实测）

| 夹具 | 空引脚件数 |
|---|---|
| 毕设FOC驱动板 | **25**（C13/15/17/18/20/21/22/23/24/25/32/33/34/37/39、L2/3/4、R22/24/25/26/27/28/29） |
| 智能药箱 | **23**（C1–C14、R1–R8、R30） |
| llc_board | **5**（L1、TP1–TP4） |
| 黄金板×2、注入板×7、ROBOT ctrl FOC、高速电机控制器 | 0（免疫，度量不变） |

已实测的连锁反应（带补丁跑全量 pytest，1055/1056）：唯一红 = `test_review_eval.py::test_the_bishe_boards_a_section_is_detected_and_explained` 钉了 `decoupling-per-ic.fp_unexplained == 5`，修复后为 **3**——**B2 裁的 5 条里有 2 条其实是丢件假阳性**（电容回来了）。B3 的 xtal WARN 预期消失（负载电容 C20/C21 入网）。

## 三、修复要求（最小改法已验证，你负责正式化）

`build_schematic_model` 第 719 行区域：

```python
symbol_uuid = (inst.attrs.get("Symbol") or "").strip()
meta = device_meta.get((inst.attrs.get("Device") or "").strip(), {})
if not symbol_uuid:
    symbol_uuid = str(meta.get("symbol") or "").strip()
```

**实例优先、缺席才回退**——不改变任何现有正常件行为（006b 注释里"实例可能是 stale copy"的教训只适用于实例**有值**的情形，回退只发生在实例为空时）。

**同类模式还有两处，必须一起改**（否则模型/layout/annotation 三个入口行为分裂）：
- `build_pin_offsets`（约 line 492）：`symbols.get((inst.attrs.get("Symbol") or "").strip())`
- power-flag 注入（约 line 838）：同模式

改前先读这三处上下文，确认回退语义一致；`meta` 的获取方式各处可能不同，以现场为准。

## 四、必须新增的测试

1. **fixture 级交叉断言（核心）**：毕设板 25 件全部入网，且**逐件**与 PCB 段 PAD_NET 一致（`["PAD_NET", pcb组件id, pin号, pad]` → padNet；sch↔pcb 经 `Channel ID`="$1"+sch组件id 桥接）。这是双独立证据互证，必须写成测试钉死。
2. 智能药箱 23 件、llc 5 件空引脚清零（TP 测试点若符号本身无 PIN 定义则豁免并写明）。
3. **行为冻结**：黄金板×2 + 注入板×7 修复前后模型无 diff（序列化对比）。
4. 更新 `test_the_bishe_boards_a_section_is_detected_and_explained` 的 5→3，注释写明理由（2 条丢件假阳性，B2 裁决基础已变）。
5. 变异验证至少含：**删掉回退行 → 25 件退回空引脚 → 交叉断言测试必须红**。

## 五、重测矩阵（修复后全跑，逐板报告计数变化）

- 7 注入板 det/precision（预期不变，验证即证明）
- 黄金集（预期不变）
- 毕设板全规则重跑 → **完整 findings 清单**（Kimi 要拿它重裁 B2/B3）
- 智能药箱 / llc / ROBOT / 高速 基线刷新
- holdout/dev 报告重出（`outputs/011e_eval_*.txt` 刷新）

## 六、顺手回答两个疑点（只调查，不改）

1. **OSC-IN 到不了 MCU**：毕设板 OSC-IN 网 = {X1.1, C20.2}，**没有 U1 的脚**（OSC-OUT 有 U1.13）。查 STM32 实例的 pin 12（PH0/OSC_IN）落在哪个网 / 是否 NC / 是否标签名不同（如 `OSC_IN` 下划线）。注意 U1 是重复位号，模型 `components['U1']` 是 8 脚件，STM32 实例要从网侧反查。结论可能是**真 defect**（晶振输入断网），交给 oracle 裁。
2. 25 件的 `component.uid` 会从 part_id 变为 symbol uuid——检查 uid 的全部用途，确认无外部依赖被碰。

## 七、交卷标准

- 三线全绿（pytest 预期 1056+ 新增；connector 187 不动；tsc 干净）
- 变异验证全 CAUGHT（含"删回退行"这条）
- 重测矩阵逐板报告落 `outputs/013_*`
- 交卷记录写进本文件（含所有计数变化的逐条清单——哪些变、为什么变）

---

## 八、交卷记录（DeepSeek，2026-09-20）

### 实现

`src/boardwise/parsers/schematic.py`：新增 `_symbol_uuid_of(inst, device_meta)`（实例优先、
DEVICE META 兜底，docstring 写明 2026-09-20 实测出处与 006b stale-copy 教训），三处调用：
`build_schematic_model`（原 line 719）、`build_pin_offsets`（原 492，该函数新增
`_collect_device_meta` 收集）、power-flag 注入（原 838）。`collect_page_layout` 的
`PlacedPart/PlacedFlag.symbol_uuid`（原 1119/1143）**未改**：其消费者是 replay/cut 的
几何切块，黄金/注入板 0 件受影响，且 `cut.py:293` 已有 `component.uid` 兜底会自动受益
于模型侧回退——改 layout 侧会动 replay 输入而无测试覆盖，超出最小改动。

### 计数变化逐条清单

| 板 | 变化 | 原因 |
|---|---|---|
| 毕设板 | pin-less 25→0；nets 62→85（+23）；findings 30E/17W→30E/14W | 25 件引脚实例化入网 |
| ├ B2 decoupling-per-ic | fp_unexplained **5→3** | 2 条是丢件假阳性（电容回到模型后规则不再报） |
| ├ B3 xtal-load-caps | fp_unexplained **1→0** | 负载电容 C20/C21 入网，WARN 消失 |
| ├ param-rc-cutoff | fp_unexplained 11 不变，OK 0→2、UNKNOWN 1→2 | R28(CAN_H/CAN_L)、L4(MOTC/VCCA) 等 RC 对因新件成形 |
| ├ conn-usb-cc-pulldown | OK 0→2、UNKNOWN 2→0 | C 件入网后 USB CC 下拉对可识别 |
| └ board_hp | 31 不变 | 30 dup + B1 均未受影响 |
| 智能药箱 | pin-less 23→0（C1–C14、R1–R8、R30 全数入网） | 同一回退 |
| llc | pin-less 5→0（L1 + TP1–TP4；TP 符号有 PIN 定义，**豁免未触发**） | 同一回退 |
| ROBOT / 高速 / 黄金×2 / 注入×7 | **逐字节不变**（序列化 dump 对比） | 实例 Symbol 全在，回退不触发 |

### 交叉断言的落地形态（与任务书第 1 条的差异，需知悉）

任务书要求"25 件逐件与 PCB 段 PAD_NET 一致（Channel ID=$1+sch组件id 桥接）"。
**该桥在 fixture 上不可复现**：fixture 的 PCB 段是早期布局快照（33 placement、129 条
PAD_NET），不含 C20/C21；25 件与其交集只有 C13，且全文档搜不到任何 `I<n>` 形态 id
（PCB C13 的 Channel ID `$1I121` 无对应物）。已落地的替代：C20/C21 逐脚网名与 Kimi
从活工程 PAD_NET 独立读得的数字（pad1→GND、pad2→OSC-IN/OSC-OUT）逐字一致，写成测试
钉死（`test_oscillator_load_caps_match_the_pcb_side_pad_net`），出处与 fixture 快照
局限写在测试注释里。**顺带发现（未修，独立于 013）**：fixture 内 33 个可桥接件按
designator 对齐 0/11 一致——sch 侧网名与 PCB 差一个 `+`（IA vs IA+、IC vs IC+），
另 sch 侧多件解析为 AGND 而 PCB 为 +24V/PGND；11 件中仅 C13 属 25 件清单（重复位号），
其余 10 件修复前后行为不变，均为既有现象，留 oracle。

### 疑点回答

1. **OSC-IN 到不了 MCU：真 defect（建议交 oracle 裁）**。`U1.12`（STM32 PH0/OSC_IN）
   落在 `IB-` 网（成员 R10.1、U1.12、U4.11）——不是 NC、不是标签名差异；`U1.13`
   正常在 OSC-OUT。晶振输入被接到相电流采样网。
2. **uid 变化无外部依赖被碰**：`Component.uid` 消费者仅两处——`cli.py` draw 的
   `symbol_defs[comp.uid]` 查表（修复前 25 件 uid=part_id 查不到、静默缺失；修复后
   查得到，是修正）与 `cut.py:293`（uid 当 symbol uuid 用，同理修正）。黄金/注入板
   uid 全走原路径（0 件受影响），变异 M1/M2 下九板 dump 逐字节不变。

### 测试与变异

新增 `tests/test_013_symbol_fallback.py`（14 例）：25 件入网（逐件、每脚有网）、
C20/C21 对 PAD_NET 证据、药箱/llc 清零、九板冻结计数、helper 优先级（合成输入钉
"实例优先、缺席才回退"）。`tests/test_review_eval.py` B2/B3 断言 5→3、1→0（注释写明
两条恢复的理由）。pytest **1070**（1056+14）全绿；connector 187 不动；tsc 干净。

变异（`.tmp_mutate_013.py` 标准形态，跑完已删；pristine sha256
`923da118…ebe931d` 还原前后一致）：
- **M1 删回退行：CAUGHT**（5 红：25 件、C20/C21、药箱、llc、helper 回退分支），
  同时九板 dump 与 pristine 逐字节相同（行为冻结由变异本身实证）；
- **M2 library-first 覆盖实例值：CAUGHT**（1 红：helper 优先级测试）。注：M2 在
  全部 fixture 上与正确实现行为相同（实例值与库值一致），只有合成输入的单元测试
  咬得住——优先级语义必须单元级钉住，fixture 层无判别力。

### 重测矩阵产物

`outputs/013_bishe_eval_holdout.txt/.json`（Kimi 重裁 B2/B3 用）、
`outputs/013_bishe_findings.md`（完整 findings 清单 30E/14W/12I）、
`outputs/013_golden_eval.txt`、`outputs/013_injected_eval.txt`（7 板 det/precision
全数不变，验证即证明）、`outputs/013_board_baselines.txt`（五板模型级基线 +
25 件逐脚网名 + OSC 三网成员）。`outputs/011e_eval_*` 历史文件未动，holdout/dev
报告以 013_* 重出。
