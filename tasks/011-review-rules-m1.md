# 任务 011：M1 有用的原理图审查 —— 立项任务书

> 2026-09-19 Kimi 立项（M0 晋级判定通过后）。执行：DeepSeek；硬件真理与缺陷标注：岳翔宇；
> 复验：Kimi。纪律与 010c 相同：输出落盘、退出码无管道、与预期不符即停、不许绕过。

## 一、前提：M0 给了我们什么

- 规则框架：`rules/base.py`（Rule/Finding，severity 三级，`source` 字段是架构承诺——
  每条规则必须写明出处）+ `rules/connectivity.py`（L1 一族，启发式，消息里写明局限）。
- 事实库底子：`blocklib/parts.json`（92 件，含 mpn/lcsc/footprint/params/provenance，
  全部板提取或库查询得来）。
- 审查入口：`boardwise review`（离线，吃 `.epro2`/`.enet`）——**M1 全程离线可跑，
  真机只在收割新验收集时需要**。
- 诚实性词汇：三态 persistence + `unknown` 的先例（009d/009d2）——M1 的四态报告沿用同一哲学。

## 二、目标（roadmap §M1 的具体化，不多不少）

约 **12 条**有适用条件的审查规则；**5–8 个 IC** 的事实库；验收集约 **10 份**、
**≥30 个独立标注缺陷**（≥1/3 留作 holdout）；holdout 上高优确定问题**精确率 ≥95%**、
注入缺陷**检出率 ≥90%**；逐规则报分子/分母/未知计数，样本小就列原始分数，不包装统计。

## 三、第一批规则（裁决，按"事实便宜 × 价值高"排序）

每条规则必须声明：**适用条件**（不满足 ⇒ NOT_APPLICABLE）、**未知行为**
（事实缺失 ⇒ UNKNOWN，不许硬猜）、**source**（datasheet 页码或 house rule，空字符串
是欠债）。未知脚不得自动判 NC（roadmap 原话）。

### 族 1 连接与身份（CONN，3 条）
| id | 判定 | 适用条件 / 未知 |
|---|---|---|
| CONN-1 | 项目内重复位号 | 多页工程全收录；单文件审查时注明作用域 |
| CONN-2 | 声明 NC 的脚接了网 / `must_connect` 脚悬空 | 需要事实库；无事实 ⇒ UNKNOWN |
| CONN-3 | 封装/库版本与 pin 编号一致性（M6 已撞过 USB1 库漂移，现成动机） | 库可查 ⇒ 比对；查不到 ⇒ UNKNOWN |

### 族 2 供电（PWR，3 条）
| id | 判定 | 适用条件 / 未知 |
|---|---|---|
| PWR-1 | IC 供电脚落在声明的电源域（域来自 009c 的声明机制） | 域未声明 ⇒ UNKNOWN |
| PWR-2 | 域电压 vs 工作范围（warn）与绝对最大（error）**分开两级** | 域电压未知 ⇒ UNKNOWN |
| PWR-3 | 负电源不按地处理 | **已有**（009c 落地，列为回归守卫，不算新规则） |

### 族 3 去耦（DECAP，2 条）
| id | 判定 | 适用条件 / 未知 |
|---|---|---|
| DECAP-1 | 已知 IC 每个供电脚按规定数值/耐压接电容到地 | 无 `required_caps` 事实 ⇒ UNKNOWN |
| DECAP-2 | 共享电源网上"有电容"不自动证明每芯片合规 | 这是**适用条件声明**，不是独立检查 |

### 族 4 常见参数（PARAM，3 条）
| id | 判定 | 适用条件 / 未知 |
|---|---|---|
| PARAM-1 | LED 限流：域电压 − Vf（族表）÷ 目标电流 ⇒ 阻值区间，超区间报 warn | LED 无 Vf 事实 ⇒ UNKNOWN；不能只验证"是个电阻值" |
| PARAM-2 | 分压输出范围（含电阻容差）落在负载脚声明的输入范围内 | 负载脚范围未知 ⇒ UNKNOWN |
| PARAM-3 | RC −3dB 截止频率报出数值，与上下文需求比对 | 无需求声明 ⇒ 报数值不定级（INFO） |

### 族 5 电源路径（PATH，1 条）
| id | 判定 | 适用条件 / 未知 |
|---|---|---|
| PATH-1 | LDO 压差：声明输入域电压 − 输出电压 ≥ dropout 事实 | 无负载预算 ⇒ UNKNOWN；合法多源/OR-ing 不建模（roadmap 原话） |

**明确不在第一批**：数字接口族（方向/模式未知不硬猜）、MCU 外围族（型号特异）、
固件接口族（需要 pin table 管线）。第二批再说。

## 四、事实库 schema 扩展

`parts.json` 的 part 增加可选 `facts` 键（schema 版本 +1，`core/parts.py` 校验）：

```json
"facts": {
  "supply_pins": [{"pins": ["16"], "name": "VCC",
                   "v_operating": [4.5, 5.5], "v_abs_max": [-0.5, 6.5],
                   "provenance": "CH340G datasheet p.x"}],
  "required_caps": [{"pin": "16", "value": "100nF", "provenance": "..."}],
  "nc_pins": ["..."], "must_connect": [{"pin": "...", "to": "GND"}],
  "led": {"vf_v": [1.8, 2.4], "if_max_ma": 20},
  "ldo": {"dropout_max_mv": 1100, "condition": "Iout=800mA", "provenance": "..."}
}
```

**每条事实带 datasheet 页码引用**——与块库同一条引用纪律，不许"大概是"。

## 五、IC 短名单（候选，岳翔宇确认后锁定）

从 `parts.json` 92 件与在役验收集选，标准：**至少出现在一块验收板上**（否则精度没法测）：

- CH340G、RT9013-33GB（黄金板已有，标注基础现成）
- AMS1117-3.3（010 块 +  datasheet 引用现成）
- 智能药箱板上的 MCU / LDO / 充电 IC（岳翔宇指定 2–3 个）
- LED/电阻/电容/接插件的身份事实（无源族，随 PARAM/CONN 需要录入）

## 六、验收集与标注纪律（岳翔宇是 oracle）

1. **~10 份**：CH340G golden 页（标注基础已有）、智能药箱若干页、FOC 板局部、
   合成注入缺陷片段。
2. **≥30 个独立标注缺陷**，**≥1/3 留作 holdout，规则调试期间不许看**。
3. 标注格式：每缺陷一行 `{board, ref, rule_hint, kind, note}`，岳翔宇终审——
   硬件真理以他为准，规则向标注对齐，不许反过来改标注迁就规则。
4. 注入缺陷清单（我们造）也要岳翔宇审：注入的必须是"真实会犯的错"，不是规则的自画像。

## 七、四态报告

`VIOLATION / OK / UNKNOWN / NOT_APPLICABLE` 四态分列计数。UNKNOWN **不算过也不算错**，
单独一行列出"缺什么事实"——这正好导向事实库的录入优先级。报告末尾给逐规则
分子/分母/未知计数。

## 八、执行顺序（验收 harness 先行——地面真值先于规则，calibration 的教训）

| 子任务 | 内容 |
|---|---|
| 011a | 标注格式 + 度量 harness（读标注 → 跑规则 → 出逐规则精确率/检出率/未知计数）+ 第一块板标注 |
| 011b | 事实库 schema + 校验 + 首批 3 个 IC 录入（CH340G / RT9013 / AMS1117，岳翔宇审 datasheet 页码） |
| 011c | CONN + PWR + PATH 族规则（6 条新的） |
| 011d | DECAP + PARAM 族（5 条）+ 验收集扩到 10 份 + 注入缺陷 |
| 011e | 收官：holdout 测量、四态报告定型、晋级判定 |

每个子任务独立交卷：三线全绿 + 变异验证（规则的**极性/阈值翻转必须咬红**）+
逐条翻号理由（若有既有测试改动）。

## 九、明确不做

- 不建通用规则 DSL（为 MVP 过度设计）；
- 不做 PCB 贴近/回流质量判定（原理图证明不了，roadmap 原话）；
- 不做自动修复（那是 M3）；
- 不碰真机写入路径（M1 是审查，只读）；
- 第二批规则族（数字接口/MCU 外围/固件接口）不在本任务书范围。

## 十、晋级判据（M1 → M2）

1. holdout 上高优确定问题精确率 ≥95%、注入缺陷检出 ≥90%（原始分子/分母随报告给出）；
2. 四态报告里 UNKNOWN 项逐条列出缺的事实；
3. 三线全绿、规则变异全咬住；
4. 岳翔宇过目 holdout 报告，认可"误报他能忍、漏报他知道在哪"。

---

## 交卷记录 A：011a（2026-09-19，DeepSeek）

**三线全绿：pytest 934 passed（基线 903，+31）/ connector 187 / tsc 干净。**

### 交付物

| 落点 | 内容 |
|---|---|
| `src/boardwise/core/annotations.py` | 标注格式 `boardwise-review-annotations/1`：loader + 全量校验（未知键拒绝、kind/severity/split 词汇表、defect 必填 severity 与 rule_hint、query 允许空 hint、逐条 note 必填、重复记录拒绝）。**不 import engines** —— rule_hint 对规则注册表的核对由调用方做（分层护栏）。 |
| `src/boardwise/rules/base.py` | 增量加 `Outcome` + `OUTCOME_STATES`（VIOLATION/OK/UNKNOWN/NOT_APPLICABLE）+ `OutcomeRule` 可选协议；UNKNOWN **必须**写明 `missing_fact`。既有 Finding/Rule 零改动。 |
| `src/boardwise/engines/review_eval.py` | 度量 harness：确定性配对（同 hint → 交叉匹配 → 命中例外 → 无解释）、词边界 ref 匹配（`U1` 不吃 `U10`）、逐规则原始分子/分母、四态计数（legacy 规则如实标 "legacy"）、split 过滤（**默认 dev，holdout 必须显式请求**——规则调参想偷看都难）、`load_board_model`（.epro2 走**原理图**解析器）。 |
| `src/boardwise/cli.py` | 新子命令 `boardwise review-eval --annotations ... [--split dev|holdout|all] [--json PATH]`；退出码 0=已测量 / 2=坏输入（测量仪不是门禁）。 |
| `reviewsets/ch340g_golden.json` | 首板标注**草稿**（`reviewed_by` 为空，报告会打 DRAFT 标）：1 条 exception（X1 接地外壳 → xtal 规则现行误报）+ 3 条 query（LED1 无限流电阻？U3 是什么？R24/R27 拉低在 USB 哪两个脚？）+ 2 条 observation（USB1 库漂移动机 CONN-3；"正常样例"不逐件标注的范围说明）。 |

### 首次测量（黄金板，dev split，DRAFT 未审）

```
xtal-load-caps: fp-exc 1, precision 0/1 = 0.00   ← X1 接地外壳误报,被标注钉住
decoupling-per-ic / shunt-sense-link: 无发现
queries excluded: 3
```

### 变异验证（4 个，全 CAUGHT，还原逐字节一致）

1. 精确 hint 配对改"任意 hint"（匹配极性）→ TP 用例红；
2. ref 词边界丢失 → 边界用例红；
3. dev split 静默并入 holdout → 排除用例红；
4. 交叉匹配不再记给被 hint 的规则 → 记账用例红。

### 发现的坑 / 边界（报备）

1. **`boardwise review` 吃 `.epro2` 走的是 PCB 侧模型**（`cli.py:514-518` → `parsers/epro2_model.build_design_model`）；对只有原理图的备份（如黄金夹具）**恒返回 0 components / 0 nets**（"batch runs survive"的设计）。任务书 §一"review 离线吃 .epro2"对 M1 的原理图审查**不成立**。harness 绕开了它（直接 `build_schematic_model`），但**用户入口需要裁决**：给 `review` 加 `--view schematic|pcb`（默认 pcb 不动既有测试），还是改默认。011c 前要定。
2. **xtal-load-caps 在黄金板上就是误报**（4 脚晶振的接地外壳被要求"接一个到地的电容"）——这不是理论推演,是 harness 的第一次实测输出。修法方向（跳过已在地网上的脚）留 011c,标注先把它钉住。
3. **判据要能分辨**（又一次）：黄金板的网络表里 NET2/NET3 这类名字没有对称性陷阱,但标注 schema 的 severity 我一度想设成可选 —— "高优确定问题精确率"的分母需要它,可选就会漏填。defect 必填,validator 拒绝懒惰。
4. 变异脚本的 node id 少写 `tests/` 前缀 → pytest 退出码 4、**"failed" 不在输出里** —— 脚本判据从"看 failed 字样"收紧为"退出码非零 + 输出含 failed",两条都查。

### 待办（011b 前）

- 岳翔宇过目 `reviewsets/ch340g_golden.json`：确认 X1 exception、回答 3 条 query、签 `reviewed_by`；
- IC 短名单确认（§五）后开 011b（schema 扩 `facts` + 首批 3 IC）。


---

## 交卷记录 B：011b（2026-09-19，DeepSeek）

**三线全绿：pytest 950 passed（基线 934，+16）/ connector 187（零 TS 改动）/ tsc 干净。**

### 交付物

| 落点 | 内容 |
|---|---|
| `core/parts.py` | `SCHEMA_VERSION` 1→**2**（v1 文件被 loader 拒绝）；`CATEGORY_VOCABULARY`（14 词，表外词拒绝）；`facts` 白名单六键全量校验——**provenance 硬门槛**：必须含 URL **且** 命中 `p.N / sec.N / Table N / Fig.N / 第N页` 之一，否则拒绝入库；区间 `[min,max]` 允许单侧 null（源只给上限时不许编造下限，实测 RT9013/AMS1117 都是这种）；引脚号必须字符串；`find_facts`（MPN 精确 → lcsc 精确 → None，**禁模糊**）。 |
| `core/parts.py` 旁车 | `LibraryCorrections` 增第三节 **`curated`**（CuratedOverride：按 C-number 承载 curated 字段/完整条目；facts+category 在旁车门就校验）。**这是维持 008b 可复现性纪律的关键**——提交库必须 = 离线收割 + 旁车，直接改 parts.json 会破坏 `test_the_committed_library_is_exactly_a_fresh_harvest`。 |
| `engines/harvest.py` | `_apply_curated`：按 C-number 把 curated 字段盖到收割结果上；源上没有的 C-number 且 payload 为完整条目 ⇒ 追加；datasheet 链接仍由 `datasheets` 节供给。 |
| `blocklib/parts.json` | v1→v2，**93 件**（+CH340G）；diff 结构级核对 = version + 2 件改（仅 +category/+facts）+ 1 件新增，其余 90 件逐字节不动。 |
| `blocklib/parts.corrections.json` | version 2；`curated`×3（C47773/C6186/C14267）；`datasheets` +C14267（90 条）。 |
| `outputs/011b_provenance.md` | 每条事实的页码/章节/URL 清单，**待岳翔宇审**。 |

### 首批 3 IC 的事实（全部页码出处，摘录）

- **CH340G**（新增条目 `ic.ch340g`，C14267）：VCC(16) 5V 模式 **4.0–5.3V**（§6.2）/ 3.3V 模式 **2.9–3.6V**（§6.3）、abs max −0.5–6.0V（§6.1）；V3(4) 与 VCC(16) 各需 0.1uF 退耦（p2/p3，V3 电容限 5V 模式）；XI(7)/XO(8) 需外接 12MHz 晶体（p2/p3，时钟 11.98–12.02MHz 见 p6）。
- **RT9013-33GB**：VIN(1) 工作 **2.2–5.5V**（推荐工作）、abs max 6V（仅上限）；dropout **400mV max**@500mA；CIN/COUT **≥1uF** 陶瓷（p8）；pin4 NC（p2）。
- **AMS1117-3.3**：VIN(3) abs max **15V**（p2，**无工作区间声明 ⇒ 不录 v_operating**）；dropout **1.3V max**@0.8A（p3）；COUT **22uF** 钽保稳（p4，**输入电容无要求声明 ⇒ 不录**）。

### 与任务书不符 / 报备事项

1. **CH340G (C14267) 不在件库里**（只有 CH340N）——任务书"diff 只有版本号 + 3 个 part 的新键"的前提不成立。解锁方式：**只读**桥查（`lib.device.search/get` + `lib.footprint.get`，2026-09-19）拿到全局 uuid 与库封装名，条目以 `board-extract`（源=黄金板自身 attrs）入座；为此把 008b 的旁车机制扩了第三节。**一次写入未碰**。
2. **任务书的 "VCC 4.5–5.5V" 有误**：datasheet §6.2 实测 **4.0–5.3V**。按 datasheet 录。
3. **两处既有测试更新**（语义不变，逐条）：①`test_parts_library::test_a_duplicate_key_or_c_number_is_rejected` 内联库的 `version: 1→2`（schema 升版的机械跟随）；②`test_bom::test_the_ch340_spec_exports_and_names_what_the_shelf_cannot_answer` 的"不可解析"例从 C14267 换成 C25905（CH340G 现在在架上，R24 仍不在——行为断言不变，换例）；③`test_datasheet_backfill` 的工件键清单加 `curated`（节恒在，空也写——工件形状不随运行改变）。
4. **修了旁车 loader 的一个潜伏 bug**：`corrections_from_json` 尾部 `if identity / else datasheets` 会把新节静默塞进 datasheets——被迁移脚本的计数断言当场咬住（"0 个比较看起来像干净的否定"的又一变体），已改为显式映射。
5. **晶振"振荡电容值"与 RT9013 输出精度 ±2% 无 schema 槽位** —— 按纪律不编造，记录在 provenance 文档，011c 定 schema 时裁决。

### 变异验证（4 个，全 CAUGHT，还原逐字节一致）

1. provenance 不再要求页码/章节 → 门槛用例红；2. 区间 min>max 放行 → 用例红；
3. category 词汇表放行任意词 → 用例红（注：首次锚点误只改了报错文案，检查仍在 ⇒
   SURVIVED 是**变异本身写错了**，条件级突变后咬红）；4. find_facts 前缀匹配 → 禁模糊用例红。

### 待办

- 岳翔宇审 `outputs/011b_provenance.md` 的页码；审定后 011b 才算"事实已审"。
- 011c：CONN+PWR+PATH 六条新规则 + `review --view schematic|pcb` 裁决落地。

---

## 交卷记录 C：011c（2026-09-19，DeepSeek）

**三线全绿：pytest 984 passed（基线 950，+34）/ connector 187（零 TS 改动）/ tsc 干净。**

### 交付物（按 §执行顺序）

| 落点 | 内容 |
|---|---|
| `reviewsets/ch340g_golden.json` | §二 oracle 裁决落地：LED1 query→**defect**（hint `param-value-mpn-match`，severity WARN，note 写全 1k / FRC0805J471=470Ω / 意图 2.2k）；U3 query→**observation**（0805 电阻挂 U 前缀位号）；R24/R27 query→**exception ×2**（hint `conn-usb-cc-pulldown`）；新增 **U1 V3 query**（rule_hint 空，note 引 CH340 手册 p.3 §5.1 / §6.3：3.3V 模式要求 V3 短接 VCC，本板 V3 接 0.1uF 到 GND）。`reviewed_by` 保持空。 |
| `engines/review_eval.py` | §三.0 **"no registered rule" 栏**：未注册 hint 的 defect/exception 逐条列出（ref/kind/severity/hint/note 截断 140 字），**不进任何分母**；交叉匹配分支对未注册 hint 不再 KeyError（记 catch、不记账）；渲染在 cross match 后输出该节。CLI 同步：`_cmd_review_eval` **删除**对未注册 hint 的 exit-2 拒绝（原行为让规则进度绑架地面真值）。 |
| `core/power_domains.py`（新） | §三.1 域推断器：网名白名单（`+5V/12V/3.3V/5V0/3V3/1V8` 两种形态；裸 VCC/VDD/VBUS **不猜**）+ facts 稳压器输出（输出电压从 **MPN 后缀**解码 `RT9013-33GB→3.3`，输出脚从 facts 推导——required_caps 里不在 supply_pins 上的那只；AMS1117-ADJ 无固定输出 ⇒ None）；一网一值 ⇒ KNOWN（带来源串）；多值冲突 ⇒ CONFLICT（detail 列出双方）；无候选 ⇒ 无条目（`domain_of` 给 ready-made missing_fact）。 |
| `rules/facts.py`（新） | §三.2 五条：**CONN-2** `conn-nc-and-must-connect`（NC 脚上网 VIOLATION/ERROR；NC 悬空 OK；must_connect 目标是网名才机判，自由文本 UNKNOWN；无 facts UNKNOWN 写名字；category 明确非 ic NOT_APPLICABLE）；**CONN-3** `conn-library-pins`（离线单条 UNKNOWN 指名 bridge；可注入 resolver：board-only ERROR / library-only WARN（USB1/M6 漂移形状）/ 全对 OK）；**PWR-1** `pwr-supply-on-known-domain`（OK 消息**原文转述**来源；按 pin 出行——多模式件一个物理 pin 一条）；**PWR-2** `pwr-domain-vs-range`（两级：超 abs ⇒ ERROR、超 operating 在 abs 内 ⇒ WARN；多模式命中任一 operating ⇒ OK 写明命中模式；无 operating 声明时在 abs 内 ⇒ OK 如实说明）；**PATH-1** `path-ldo-dropout`（headroom ≥ dropout ⇒ OK；否则 VIOLATION；任一侧电压未知 ⇒ UNKNOWN；消息写明 load budget/OR-ing 不建模）。 |
| `rules/connectivity.py` | **CONN-1** `conn-duplicate-designators`（读 parser 收集的 `model.duplicate_designators`；VIOLATION/ERROR 每位号一条；无重复 ⇒ OK）+ **§三.3 xtal 修复**（引脚所在网已是 GND ⇒ 跳过；两脚晶振正常路径不变）。 |
| `parsers/schematic.py` + `core/model.py` | `DesignModel.duplicate_designators`：合并页时**先查后赋**，重复位号收集成列表——"丢器件"变"报缺陷"。 |
| `engines/review.py` | BUILTIN_RULES 注册 9 条（6 新 + 3 旧，新规则排在 L1 之后）。 |
| `cli.py` | §三.4 `review --view schematic\|pcb`（默认 pcb，既有行为/测试不动；帮助文本写明 schematic-only 导出用 `--view schematic`）。 |

### 黄金板 dev 实测（`outputs/011c_golden_eval.txt`，DRAFT 未审）

| 规则 | VIOLATION | OK | UNKNOWN | NOT_APPLICABLE | 任务书预期 |
|---|---|---|---|---|---|
| conn-duplicate-designators | 0 | 1 | 0 | 0 | 无重复 ⇒ OK ✓ |
| conn-nc-and-must-connect | 0 | 1 | 3 | 0 | U1 UNKNOWN×2（自由文本）+ U3 UNKNOWN；U5 pin4 NC OK ✓ |
| conn-library-pins | 0 | 0 | 1 | 0 | 离线 UNKNOWN ✓ |
| pwr-supply-on-known-domain | 0 | 2 | 1 | 0 | U1.16→VCC(3.3V, U5 facts) OK；U5.1→+5V(网名) OK ✓ |
| pwr-domain-vs-range | 0 | 2 | 1 | 0 | U1 3.3V 命中 3.3V 模式 OK；U5 5V∈2.2–5.5 OK ✓ |
| path-ldo-dropout | 0 | 1 | 1 | 1 | U5 1.7V ≥ 400mV OK ✓ |

"no registered rule" 栏：**3 条**（LED1 defect、R24/R27 exceptions）逐条在列；queries excluded: 1（U1 V3）。

### 与任务书不符 / 报备（1 条，需 Kimi 复验确认）

**`power_domains.py` 落在 `core/` 而非任务书写的 `engines/`。** 原因：规则必须导入推断器，而项目的**可执行分层宪法**（`tests/test_layer_rules.py`，006c 立的）只允许 `rules → core`——放 engines 会当场红。推断器只依赖 `core.model` + `core.parts`（纯函数、无 I/O），core 是语义与宪法都正确的家。若 Kimi 裁决必须放 engines，则需同步修宪法（rules→engines 箭头），那是项目级决策。

### 测试与变异

- **+34 条**：`test_power_domains.py`（8：白名单/裸 VCC 不猜/facts 来源/冲突双方/无来源/未查询网/输出脚与电压解码/ADJ 不造值）；`test_facts_rules.py`（26：六条规则四态各至少一条 + parser 重复位号 + xtal 两态）；harness 新栏 3 条 + CLI 放行 1 条。
- **既有测试更新（4 条，逐条理由）**：①`test_review_eval_rejects_an_unknown_rule_hint` → 改名 `test_review_eval_reports_an_unknown_rule_hint_instead_of_rejecting`——§三.0 的裁决正是废除该拒绝行为；②`test_the_real_ch340g_annotation_set...`、③`test_review_eval_measures_the_real_annotation_set`、④`test_load_annotations_reads_the_real_file`——钉的是 011a 草稿标注集的形状，011c §二 oracle 裁决改了标注集（LED1→defect 等），测试跟随地面真值；xtal 断言从 fp-exc 1 → 0（修复生效的度量自洽）。
- **变异 4 个全 CAUGHT，还原逐字节一致**：①CONFLICT 改取首候选 → 冲突用例红；②PWR-2 两级并一级（abs 分支短路）→ 分级用例红；③CONN-2 自由文本硬判 → UNKNOWN 用例红；④xtal 跳过反写 → 接地外壳用例红。（首版 M1 变异写出重复 kwarg 导致 pytest exit 4"假咬"，M2 只改文案——都按"退出码非零 **且** 输出含 failed"判据修正后才算数。）

### 给 oracle 的待决清单（随交卷上报）

1. **U1 V3 query**（规则实测 UNKNOWN 不预判）：VCC=3.3V 但 V3 按 5V 模式接 0.1uF——本板这样跑过吗？有意还是缺陷？
2. USB1 的库条目 category 为空（`''`）——C2765186 需要归类（connector）才能让规则对它给出 NOT_APPLICABLE 而非跳过。
3. 两条未注册 hint 对应的第二批规则（`param-value-mpn-match`、`conn-usb-cc-pulldown`）——011d 实现。

---

## 交卷记录 D：011d（2026-09-19，DeepSeek）

**三线全绿：pytest 1013 passed（基线 984，+29）/ connector 187（零 TS）/ tsc 干净。**

### §一 oracle 裁决落地

- U1 V3 query → **defect**（hint `decap-required-caps`，WARN；note 写明 3.3V 模式手册接法与 5V 模式接法的矛盾）。
- **C2765186（Type-C 座）**：旁车 curated 补 `category: "connector"` + `pull_required`（pin4/pin10 → GND 5.1k，provenance 引 **ST AN5225 Table 6**（UFP CC termination (Rd) requirements: 5.1 kΩ ±10% to GND），URL+Table 命中页码门禁）。
- **U3 defect 重锚**：LED1→**U3**（任务书 §一.3/§七 本来就写 "U3 defect"——矛盾在电阻的 value/MPN 上，不在 LED 上；前缀错配仍是 observation）。重锚后配对成立：`param-value-mpn-match det=1/1, precision 1.00`。
- 复跑 eval：**"no registered rule" 栏清空**、queries excluded=0（五条 hint 全兑现）。

### §二 schema 扩展（v2 兼容，版本号不动）

- `supply_pins` / `required_caps` / `must_connect` 条目加**可选 `mode`**（缺席 ≠ null，round-trip 保持缺席）；**facts 白名单加 `pull_required`**（pin/to/expected_value/provenance，同门槛）。schema 测试 2 条。
- **CH340G 回填**（经旁车 + harvest 代码路径重生成该条目，verify 字段与 notes 保留）：supply_pins 标 5V/3.3V；V3 的 0.1uF 标 mode 5V；新增 must_connect V3→VCC 标 mode 3.3V。
- **LED1 入库**：C51933293（GL0603UG01，翠绿 0603）以 **catalog-select**（库里第二种 provenance kind）完整条目入座——身份来自只读桥查（device.search/get + footprint.get → `LED0603-RD`），facts `led {vf_v: [2.7,3.2], if_max_ma: 30}` 引其 datasheet **p.3**（PDF 不入仓）。件库 **93→94**。

### §三 六条规则（全部 OutcomeRule；注册后 BUILTIN_RULES 15 条）

| id | 黄金板实测 |
|---|---|
| `decap-required-caps` | **V3 defect 兑现**：U1 pin4 "must sit on VCC in mode 3.3V but is on NET1"（det=1/1）；U1.16/U5.1/U5.5 OK（C9/C5 2.2µF ≥ 声明值）；U3 UNKNOWN（架上有条目无 facts）。模式门双向验证（5V 轨用 RT9013-50GB + `5V0` 网名构造，两来源一致）。 |
| `param-led-current` | LED1 **UNKNOWN**——真实 Vf 2.7–3.2V ⇒ 电流 0.10–0.60 mA **跨** 0.5mA 房规下限（任务书草稿的 "1.3mA OK" 按 vf≈2V 假设算，与实测 datasheet 冲突；区间语义如实报 straddle）。vf 改合成 (1.9,2.1) ⇒ OK；无限流 ⇒ VIOLATION/ERROR。 |
| `param-divider-output` / `param-rc-cutoff` | 黄金板无场景 ⇒ 单条 OK 报告；合成四态全覆盖。RC 拓扑**排除已知电源轨上的对**（U3+C6 共享 VCC 是去耦不是滤波——否则每颗去耦电容都被当"滤波器"刷屏）。 |
| `param-value-mpn-match` | **U3 defect 兑现**（1000Ω vs 470Ω，det=1/1）；R24/R27 无 MPN ⇒ UNKNOWN；C1/C6/C7/C25/C3 OK；C4 双候选码 ⇒ UNKNOWN；C9 board value 空 ⇒ UNKNOWN。 |
| `conn-usb-cc-pulldown` | **R24/R27 exception 保持安静**：USB1 pin4/pin10 OK×2（5.1k 匹配）；缺失 ⇒ ERROR、阻值错 ⇒ WARN、值不可解析 ⇒ UNKNOWN、无 pull_required 的 connector ⇒ NA。 |

**过程中修掉的三个真坑**：①EIA 解码数学错误（`base**exp`，电容全错——应为 `10^exp × base`）；②**CH340G 的 "340" 会被解码成 34pF**——U1 差点被当成 VCC 网上的电容（"MPN 含合法 code"≠"这是个电容"；电容认定 = value 可解析 ∨ shelf category ∨ **C 前缀位号 + code 合取**）；③RC 对把去耦场景误当滤波。

### §四 注入板——**框架已交，变体未生成（按你的指示）**

`reviewsets/injected/make_variants.py`：7 个变体提案表（fault/edit/expects/oracle_note）+ `--list` / `--generate`；`--generate` 被 oracle 签名门闩挡住（空签名 ⇒ exit 2），**未生成任何变体**。清单落盘 `outputs/011d_injection_list.txt` 待岳翔宇审。**一处提案修改**：#6 LED 限流的阻值从草稿 100Ω 改提 **4.7Ω**（100Ω 在真实 Vf 下 1–6mA 在房规区间内，不会被抓；4.7Ω 给 21–128mA 整体超上限，干净 VIOLATION）——待 oracle 连清单一起签。

### §五 真实板基线（7 份，未标注，仅四态分布）

`outputs/011d_baseline_*.txt`：CH340G 整板、药箱、ROBOT FOC、毕设 FOC、高速电机、llc_board、board24v.enet（任务书列 6 块，实为 7 个文件，全部跑了）。**真实捕获**：毕设 FOC 驱动板 **30 个重复位号**、高速电机 **16 个**（CONN-1 首战）；board24v 的 MPN/value 矛盾 15 处。UNKNOWN 清单即 facts 录入优先级表。

### §六 测试与变异

- +29 条：`test_011d_rules.py`（27：六规则四态 + 黄金板端到端 + 解析器白名单）+ schema 2 条。
- **既有测试更新（4 条，全部跟随 artifact 演进）**：①`test_review_fixture_smoke`（board24v 不再零发现——钉 exit-code 合同而非钉零）；②`test_load_annotations`（kinds 5 项含 2 defect）；③④`test_the_real_ch340g...` / `test_review_eval_measures...`（no-rule 栏清空、queries=0、det=2、precision 1.00）。
- **变异 4 全 CAUGHT**、还原逐字节一致：①decap 模式门删（5V 记录在 3.3V 板开火 ⇒ 计数断言红）；②MPN 解不出改硬猜（"000"）⇒ UNKNOWN 用例红；③usb-cc 不查阻值 ⇒ WARN 用例红；④LED 下限检查删除 ⇒ straddle 用例红。

### 报备

- **append 双执行又现 3 次**（标注集 notes、测试补丁、SKILL 各一次）——独立计数全部抓到并去重/确认无害。
- `param-led-current` 对黄金板报 UNKNOWN 而非任务书的 OK——**数据与任务书假设冲突**（真实 Vf 2.7–3.2V），按区间语义如实处理；房规数值（0.5mA/50% derate）在 `LED_CURRENT_FLOOR_MA`/`LED_CURRENT_DERATE` 一处，oracle 可调。
- 注入变体的"每个变体一条命中测试"（§六）在 oracle 签清单后随变体生成补——框架先行，测试后行，已在脚本 docstring 写明。
---

## 交卷记录 F：干净基底与变体重派生（2026-09-20）

**oracle 终裁**（2026-09-19）：①U3 正确值 = 1k（value 对，MPN `FRC0805J471` 错）；②V3 正确接法 = 短接 VCC。
按 a–e 五步执行；报告全文见 `outputs/011d2_fixed_base_report.md`。

### a) 标注集写入终裁

`reviewsets/ch340g_golden.json` 两条 defect 的 `note` 末尾各加 `FINAL RULING 2026-09-19`：U3 那条
写明"value 对、MPN 错，已在 fixed-base 修正"；U1 那条写明"正确接法是 V3 短接 VCC，已在 fixed-base 修正"。
**顺手修掉一个重复 JSON 键**（U1 条的 `severity` 出现两次；JSON 容忍、loader 取后者，功能无害，
但会让规范化重写变成隐性改动）——写前先自检"重新序列化 == 原文"，只在差异恰好是那一行时才重写。

### b) 干净基底 `fixed-base`（新概念：基底不是变体）

生成器加 `BASES` 表 + `BASE_BUILDERS`，流水线变为
`golden --[两处修复]--> fixed-base --[六个注入]--> 6 变体`。两处修复：

- **U3**：只改**实例**的 `Manufacturer Part` → `FRC0805J102 TS`（同系列 1k 兄弟）；
- **V3**：把 V3 线上**已有的空 `NET` 标签**改写成 `VCC`（原理图表达"这张网叫 VCC"的正规方式），
  不动走线、不删 C1 ⇒ C1 变成 VCC 退耦电容，即 3.3V 模式参考设计。

**基底干净的实证**（`outputs/011d2_fixed_base_eval.txt`）：**零发现**（0 ERROR / 0 WARN / 0 INFO，
全误报列 0）；黄金集两条 defect 在基上 `det=0 / missed=1 / violations=0`，而**同一份标注集**下的
黄金板仍是 `det=1 / violations=1` ⇒ 是"板修好了"而不是"尺子放水"。模型级：`U3.mpn == FRC0805J102 TS`
（value 1000 vs code 102，规则 OK）、`U1 pin4` 落在 **VCC** 网（与 pin16 同网），网数 13→12。
基底自带标注集 `fixed-base.json`：**3 条 exception**（从黄金集 verbatim 继承，不抄它那两条 defect，
带断言防漂移），0 条 defect。

### c) 变体从基底重派生

| 变体 | 预期规则 | det/hint | 误报 | base-fires | 判定 |
|---|---|---|---|---|---|
| duplicate-designator | conn-duplicate-designators | 1/1 | 0 | 0/1 | ✓ 隔离 |
| nc-pin-grounded | conn-nc-and-must-connect | 1/1 | 0 | 0/1 | ✓ 隔离 |
| overvoltage-rail | pwr-domain-vs-range | 1/1 | 0 | 0/1 | ✓ 隔离 |
| ldo-no-headroom | path-ldo-dropout | 1/1 | 0 | 0/1 | ✓ 隔离 |
| value-mpn-mismatch | param-value-mpn-match | 1/1 | 0 | 0/1 | ✓ 隔离（**首度**成为单错型） |
| v3-decap-missing | decap-required-caps | **0/1** | 0 | 0/1 | **注入不可见（见下）** |

### 必须裁决：`v3-decap-missing` 在新基底下完全静默

删 C1 后两块板的规则输出**逐条相同**（`outputs/011d2_v3_decap_analysis.txt`）：U1 pin4 OK
（3.3V 模式下 V3 只需在 VCC 上；`mode: 5V` 的电容要求不适用）、U1 pin16 OK（该网需要的 0.1uF 由
**C9 2.2uF** 满足）。**不是规则/harness bug**，是这条注入在这块板上本就不可观测；顺带实测：
**本板任何"单颗电容被删"都不触发该规则**（VCC 网上 C1/C6/C7/C9 四颗可确定值电容，规则取最大者比对），
"无电容 / 容值不足"两分支只在**成组删除**时可达。

两个选项（未自行改道）：**①退役 #1**（与 #6 同样处理，"缺失退耦"路径的覆盖靠合成 model 单测，
011d 已有）；**②重新界定 #1** = 改为"删掉 C6（U1 pin16 需要的那颗 0.1uF）"，并让基底的 V3 修复
顺手去掉 C1（3.3V 板不需要那颗 5V 模式电容），使 VCC 网上只剩 C6 为唯一可满足项。选项 ② 需你签新提案。

### d) `led-overcurrent` 已移除

表、`BUILDERS`、文件全清；测试 `test_the_led_overcurrent_proposal_is_gone` 钉住"不建、不列、无编辑函数"。

### e) 门闩 / 确定性 / 逐变体测试同步

- 门闩仍是"已签子集"模式（表内已无未签项）：`--generate` 无参⇒基底+全部已签；指定未签项⇒整体拒绝
  exit 2 且**不落任何文件**。因表内已无未签项，新增测试用 `monkeypatch` **模拟**一条未签提案来钉住机制。
- `--check` **覆盖面扩到标注集**（原先只比 `.epro2`）；并新增"守卫必须只读"的测试。
- 逐变体测试：故障确实在变体上且**不在**基底上（6 条）、预期规则命中且严重级一致（5 条）、
  base-fires 全 0（6 条）、`v3-decap-missing` 静默的机制（1 条）、`value-mpn-mismatch` 的次生效应（1 条）。

### 本轮三个真问题（都已修，教训写进 SKILL）

1. **`--check` 曾"先写后比"** ⇒ 突变态会被写成新基线、之后每次 check 都"一致通过"——变异 M1 因此
   **假存活**。改为**构建到仓内 scratch（`.tmp_variant_check`）只做读比对**；新增测试钉"守卫只读"。
2. **网名标签先到先得**：每根线本就带一条（多为空）`NET` 标签，解析器取第一条 ⇒ 我第一版"新增一条
   VCC 标签"被空标签遮住（基底依旧违反、网数不变）。正解是**改写那条空记录**。教训：给有默认值的字段
   "再加一条"，先问"谁先被读到"。
3. **黄金集重复 JSON 键**（见 a）。

### 验证

- pytest **1043 passed**（基线 1031，+12）；connector **187 / 0 fail**；tsc 干净（零 TS 改动）。
- 变异 **6 个全 CAUGHT**，生成器与 14 个产物逐字节还原：①V3 标签不命名；②U3 的 MPN 修正变空操作；
  ③变体改从 golden 派生；④门闩不拒未签；⑤基底标注集抄进黄金的 defect；⑥**把已落盘的基底换成 golden**
  （产物级，只有内容断言能咬住）。前五个生成器级靠"重建逐字节比对"咬住 —— 这也是把 `--check`
  扩到标注集的原因（否则 ⑤ 静默漏过）。
- `--check`：7 块板**及其标注集**重建逐字节一致。

### 已知局限（明说）

基底只改了 U3 **实例**的 MPN 声明；它指向的本地库文档仍写着 `FRC0805J471`/470Ω 的 `LCSC Part Name`。
真正的设计修复是换器件（连带库文档与供应商字段），而 1k 兄弟的真 C 号需联网核实（属 011b 的
catalog-select），**不臆造**。harness 读实例字段（实例非空优先），规则层不受影响。

---

## 交卷记录 G：011e（2026-09-20，DeepSeek）

**三线全绿：pytest 1051 passed（基线 1043，+8）/ connector 187（零 TS 改动）/ tsc 干净。**
**晋级判定结论留白**——判定由 Kimi 复验后宣布（§五）。

### §一.1 PARAM-3 四态污染整改

**改法**：`rules/params.py::RcCutoff` 的数值报告行从 `VIOLATION` 迁到 **`OK`**（消息带 `fc = <值> <单位>`），
`check()` 的取行依据从"状态是 VIOLATION"改为"该行带 severity 提示"（survey 行不带 ⇒ 保持沉默）。
**Finder 级不变**：产出的仍是 INFO，`boardwise review` 的 md 报告与既有 `"param-rc-cutoff" in md` 断言不受影响。
类 docstring 写明为什么（VIOLATION 是 oracle 读作"规则说有问题"的那一列，而"量了个数"不是问题）。

**实测（整改前后对比，`outputs/011e_baseline_*.txt`）**：

| 板 | 四态 VIOLATION 列 param-rc-cutoff | findings 计数 |
|---|---|---|
| 毕设 FOC 驱动板 | 11 → **0** | 30 ERROR / 17 WARN / 12 INFO（不变） |
| board24v | 27 → **0** | 0 / 15 / 27（不变） |

findings 计数不变是**预期**的（INFO 仍产出），VIOLATION 列只剩真违规正是 §一.1 要的。

**既有测试更新 1 条（逐条理由）**：`test_011d_rules::test_param3_an_rc_pair_reports_its_cutoff_as_info`
原断言 `any(o.state == "VIOLATION" ...)` 钉的正是"数值报告落在 VIOLATION 列"这一**被裁决废除的旧语义**；
改为钉新语义并加强：`not states["VIOLATION"]` + OK 行 subject/`fc =` 断言。其余 1043 条一字未动。

**一处必须说清的边界**：per-rule 的 `precision` 列（把**所有** finding 计入分母）仍会把 INFO 报告计为
`fp-unexpl`（board24v 0/27、毕设板 0/11）。§一.1 只改了状态，§四.1 的"高优确定问题精确率"则要求分母
只算**确定断言**（ERROR/WARN）——两者是两个问题，我用**增量**字段解决（见下），**没有**改既有列的语义。
若 Kimi 认为既有 `precision` 列也该排除 INFO，那是一次公共读数变更，请裁决，我照办。

### §一.2 `v3-decap-missing` 退役

- 表内 `signed: ""` + `retired: "2026-09-20"`，`oracle_note` 写明退役原因（实测：3.3V 模式下 V3 电容
  记录 `mode: 5V` 不适用，VCC 的 0.1uF 由 C9 2.2µF 满足 ⇒ 两块板规则输出逐条相同；一般性质是规则取网上
  **最大**已确定值电容比对 ⇒ **本板任何单颗电容被删都不可见**；造可见性要连改三颗电容 = 为规则画像造缺陷，
  011 §六 禁止）。
- **文件保留在盘上**：`v3-decap-missing.epro2` 仍在，`--check` 继续逐字节比对它（`_tracked_ids()` 含退役板）。
- **标注集清空**：`v3-decap-missing.json` 的 `items` 变 `[]`（`reviewed_by` 空），notes 记明"退役 ⇒ 不作
  ground-truth 声明"。理由：留着那条 defect 会让任何聚合运行的"no-rule/未解释"栏多出一条 oracle 已排除的要求。
- **门闩**：`--generate v3-decap-missing` ⇒ **exit 2**（报文含 "retired"）；`--rebuild-retired` 是**维护动词**
  （只给守卫用：`--check` 必须能重建它，否则会停止看守一个仍在盘上的夹具）。
- 逐变体测试：退役板**不参与**逐变体 det 判据（`_eval_ids()` 不含它）、**参与**字节一致性比对；
  退役原因的测量本身仍被断言（`test_the_retired_variant_stays_unverifiable_and_the_measurement_is_still_asserted`），
  因为"没人能复检的退役"就是传说。

### §二 holdout 划分

- **按板划分**（不按条目——同板条目共享拓扑）。
- **选法是导出的，不是挑的**：`sorted(eval_ids, key=sha1(id))[:HOLDOUT_SIZE]`，`HOLDOUT_SIZE = 2`
  （011e §二指定抽 2 块）。派生规则写在代码注释里，**具体结果冻结在测试里**（`FROZEN_HOLDOUT` / `FROZEN_DEV`）
  ⇒ 事后重抽会以失败测试的形式出现，而不是报告里悄悄变个数。
- 结果：**holdout = `duplicate-designator`、`nc-pin-grounded`**；**dev = `ldo-no-headroom`、`overvoltage-rail`、
  `value-mpn-mismatch`** + `fixed-base` + `ch340g-golden`。sha1 排序已写进 `outputs/011e_generate.txt`。
- 落地：两个 holdout 板标注集的 `split_default` 与 item `split` 均为 `holdout`（生成器写入）。
  harness 默认 `dev` ⇒ 默认报告不含 holdout 条目，且**明说**排除了几条（"holdout items excluded here: N"）；
  测试 2 条钉住（真实家族上：holdout 板在 dev 运行里 0 记录、打开过滤器后 det=1；dev 板在 dev 运行里 det=1）。
- **配额算术（如实报，见"待决"）**：holdout 占**注入家族** 2/5 = 40%（≥1/3 ✓）；占**全部板** 2/7 = 28.6%；
  占**全部标注缺陷** 2/7 = 28.6%（<1/3）。011 §六 的 `≥1/3` 是对"≥30 个标注缺陷"说的，而真实板标注（§三）
  仍是 oracle 的活 ⇒ 现在下结论太早：**两块待裁板里至少一块必须进 holdout**，届时缺陷基数上升，比例达标。

### §三 两块真实板的待裁表（等岳翔宇裁，标注集未落）

| 落点 | 内容 |
|---|---|
| `reviewsets/ProPrj_毕设FOC驱动板_2026-09-17-triage.md` | 121 件 / 85 网；30 ERROR / 17 WARN / 12 INFO。**批量项 A1**：30 个重复位号（含 SCREW1–4）一行裁决；**A2**：`param-value-mpn-match` 10 条分 2 子类（电解电容料号被当 EIA 码 = 解码器越界；`471`/`104` 是正确解码 ⇒ 真矛盾）；单项：`decap-required-caps` U11（1µF 要求 vs 100nF）、`decoupling-per-ic` 5 条启发式、`xtal-load-caps` X1、`shunt-sense-link` R43、`conn-usb-cc-pulldown` UNKNOWN×2。 |
| `reviewsets/board24v-triage.md` | 50 件 / 42 网；0 ERROR / 15 WARN / 27 INFO。**A1**：15 条 MPN/value 矛盾**全部**可归因于解码器越界（三相：电解料号、`K500N` 是 500V 耐压、`R001` 是四位 R 记法）；**A2**：27 条 rc-cutoff 数值无需裁决。另注明该夹具是 `.enet` 平铺网表 ⇒ CONN-1 永不触发、无页级事实。 |
| `outputs/011e_triage_raw.txt` | 两块板的逐条 finding/outcome/UNKNOWN 原始清单（待裁表的事实底稿）。 |
| `outputs/011e_baseline_*.txt` | **7 份基线全部刷新**（011d 那批的 VIOLATION 列已因 §一.1 过时）。 |

待裁表里已区分**四类处置**：`defect` / `exception` / `observation` / `backlog`，并给出**建议**（裁决权在 oracle）。
`reviewed_by` 在裁完前保持空，报告继续打 DRAFT 标。

### §四 晋级测量（011 §十 逐条）

**(1) 两份报告分开落盘，原始分子/分母随报告给出**

| split | 板数（有记录的） | 注入+原生缺陷检出 | 高优确定问题精确率 | 落点 |
|---|---|---|---|---|
| dev | 5（5） | **5/5 = 1.00**（cross 0，missed 0） | **5/6 = 0.83**（0 命中例外，1 无 oracle 记录） | `outputs/011e_eval_dev.txt` |
| holdout | 2（2） | **2/2 = 1.00** | **2/2 = 1.00** | `outputs/011e_eval_holdout.txt` |

阈值：精确率 ≥95%、检出 ≥90% ⇒ **holdout 两项均达标**；**但分母只有 2，样本极小，不足以支撑晋级**——
这正是 §二 要求真实板进 holdout 的原因。

**dev 那 0.83 的 1 条无解释项是已知且真实的**：`value-mpn-mismatch` 板上 `param-led-current` 对 LED1 报
VIOLATION（0.05–0.27 mA < 0.5 mA 房规下限）——一次注入两个后果，标注集里只记了注入的那个。它与
CH340G 板的 LED1（跨阈值 ⇒ UNKNOWN）同源。**这是"误报还是漏记"的裁决点**，我不自行改标注，也不调阈值
（§六）：请 oracle 裁 —— 若认定为真实第二缺陷，就给该变体补一条记录，dev 精确率随之为 1.00；若认定为
规则误报，则如实留在 0.83。

**新增度量口径（增量，不改既有列）**：`RuleMetrics.hp_tp / hp_fp_exception / hp_fp_unexplained` +
`hp_findings` / `hp_precision`；`evaluate_annotations` 在配对时按 **finding 自身严重级**（ERROR/WARN）计数；
文本报告加 `hp-find` / `hp-prec` 两列与 **split totals 块**（>1 板时输出）。totals **只统计"本 split 内有
oracle 记录的板"** —— 未标注板"沉默不是判决"，把它的 finding 算成未解释等于把"oracle 还没看"报成"规则错了"
（板数一并打印，作用域可见）。`--json` 同步输出这五个字段。

**(2) UNKNOWN 逐条列出缺的事实**：holdout 两份报告同格式（四态块 + 无 UNKNOWN 项，因为两块注入板都干净）；
真实板基线里 UNKNOWN 逐条列出缺的事实（毕设板 15 IC × 4 条事实、board24v 3 IC × 4 条 + 8 个 MPN 无码）。

**(3) 三线全绿 + 规则变异全咬住**：见下"验证"。

**(4) holdout 报告交岳翔宇过目** —— 待办，签字是判据本身，不是数字。

### 验证

- **三线**：pytest **1051**（1043+8）/ connector **187** / tsc 干净（零 TS 改动；本轮全在 Python + 夹具 + 报告层）。
- **测试 +8**：`test_review_eval`（4：高优精确率只算确定断言、交叉匹配算"被解释"、totals 两数、totals 排除无记录板）
  + `test_injected_variants`（4：split 派生与冻结账本一致、退役板被看守但不被评分、维护动词只给守卫、
  dev 运行不评 holdout 且仍评 dev）。
- **变异 6 个全 CAUGHT，每个文件逐字节还原**：
  ①rc-cutoff 回到 VIOLATION ⇒ 四态用例红；②退役门闩不拒 ⇒ 退役用例红；③`HOLDOUT_SIZE` 改 1（重抽）⇒
  冻结账本用例红；④INFO 重新进高优分母 ⇒ 高优精确率用例红；⑤退役板保留 ground-truth 记录 ⇒ 退役用例红；
  ⑥`_tracked_ids` 不再看守退役板 ⇒ 退役用例红。
- **确定性**：`make_variants.py --check` ⇒ 7 块板**及其标注集**重建逐字节一致（含退役板）。

### 待决 / 需 oracle 或 Kimi 裁决

1. **`value-mpn-mismatch` 的次生 LED 限流 VIOLATION**：补记（⇒ dev 精确率 1.00）还是认定规则误报（保持 0.83）？
2. **既有 `precision` 列是否也排除 INFO**：我选了"增量加 hp 列、既有语义不动"。若要求改既有列，请裁。
3. **两块真实板的裁决**（`*-triage.md`）：裁完我落标注集，且**至少一块进 holdout**（§二）。
4. **MPN 解码器的三处越界**（board24v A1 实测）：四位 `R001` 记法、`K500N` 这类耐压码、电解料号——
   属规则改进，按 §六 本轮不动，记入 M2 第二批规则族优先级。
5. **011 §六 的 `≥30 个独立标注缺陷` 与 `≥1/3 holdout` 尚未达成**（当前 7 个缺陷、holdout 2 个）。
   真实板标注落地后才有意义；如实报备，不包装。

### 报备

- **append 双执行第 12 次**（本记录首次写入即重复一份，逐字节相同）——独立计数抓到并去重。
- 本轮**未碰真机**、未动 git；`outputs/` 新增 12 份证据（2 报告 + 2 totals 底稿 + 7 基线 + 1 triage 原始清单 + pytest/connector 日志）。

---

## 交卷记录 H：oracle 三裁与毕设板 A 段落定（2026-09-20，DeepSeek）

**三线全绿：pytest 1056 passed（基线 1051，+5）/ connector 187 / tsc 干净（零 TS 改动）。**

### 一、裁决② 落地：`param-led-current` 改为阻值窗口

| | 旧（011d） | 新（2026-09-19 裁决） |
|---|---|---|
| 判据量 | 从 Vf 区间算电流，比 `[0.5mA, 50%×If_max]` | **限流阻值**比 `[470, 2200] Ω`（**闭区间**） |
| 域 | 不限域（只要求供电侧电压已知） | **只在 3V3 域**判定；其他域 UNKNOWN（写明缺的是"该域的窗口"） |
| LED facts | **必需**（无 `vf_v`/`if_max_ma` 即 UNKNOWN） | **不需要**（判据是电阻值） |
| 无限流 | VIOLATION / ERROR | VIOLATION / **ERROR**（0 Ω 是跨电源短路，仍是最重的一档） |
| 越窗口 | VIOLATION / WARN | VIOLATION / **WARN** |
| source | 自拟房规（0.5mA / 50% derate） | **oracle 原话**（3V3 域 [470,2200]Ω、按阻值、4.7k 反例、其他域 UNKNOWN） |

常量集中一处：`LED_SERIES_BOUNDS_3V3` / `LED_WINDOW_DOMAIN_V` / `LED_DOMAIN_TOLERANCE_V`。证据行同时留 **"谁说了这个电压"**（黄金板是 `U5 RT9013-33GB output`，不是网名）——这是 011 家族一贯的"who says so"。

**推导为什么必然如此（不是口味问题）**：黄金板限流是 **1kΩ**，oracle 刚裁"U3 的 value 是对的"；而旧规则对这颗**参考设计**给的判定是 **UNKNOWN**（Vf 2.7–3.2V 跨 0.5mA 下限）——**一把尺子量不出自己家的基准**，判据本身就是错的量。新窗口让 1k ⇒ OK，与 U3 裁决自洽。

### 二、裁决③ 复跑：`outputs/011e_eval_dev.txt`

| | 修订前 | 修订后 |
|---|---|---|
| `value-mpn-mismatch` 板的 LED finding | **VIOLATION**（0.05–0.27mA < 0.5mA） | **消失**（2.2kΩ ∈ [470,2200] ⇒ OK） |
| 该板 findings | 2 | **1**（只剩注入的那条） |
| dev defect detection | 5/5 = 1.00 | 5/5 = 1.00 |
| **dev 高优精确率** | **5/6 = 0.83**（1 条无解释） | **5/5 = 1.00**（0 条无解释） |

顺带：`fixed-base` 与黄金板的 LED1 由 UNKNOWN ⇒ **OK**（1kΩ），三块板的 LED 判定现在都落在 OK。

### 三、裁决① 落地：毕设板 A 段（`reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`）

`split_default: holdout`（011e §2 要的 CONN-1 真实板）；**`reviewed_by` 留空**（B 段未裁 ⇒ 报告继续打 DRAFT）。

| 段 | 裁决 | 条数 | 记录 |
|---|---|---|---|
| A1 `conn-duplicate-designators` | **defect** | **30** | one record each，note 引 oracle 原话"当时疏忽，没在意" |
| A2a 解码器越界 | **exception** | **3** | `R43`(JER2512F3R005 的 `3R005`)、`C115`/`C116`(电解料号 `PA50V330M10x15` 的 `330M`)——**M2 修解码器** |
| A2b 解码正确但**位置不敏感** | **exception** | **7** | `U10`/`U14`(`471`→470Ω vs 1kΩ)、`C28`/`C29`/`C36`/`C42`/`C44`(`104`→100nF vs 2.2µF/10nF)——note 引"这个本没错，不要定的太死"，**M2 输入：该规则需要"矛盾幅度"概念** |

**分组依据是机制、不是手抄表**：生成脚本直接读**规则自己的输出**（`ValueMpnMatch.outcomes` 的 VIOLATION 行 + `mpn_value_code`）来分两组，并用断言钉住 3/7。

**一处必须报的计数不符（已作为 observation 落进标注集，未擅自重贴标签）**：裁决写"A2a ⇒ exception ×7"，但**裁决自己给 A2a 的机制**（电解料号 330M / 四位码 3R005 被当 EIA 误读）在这块板上只覆盖 **3 个 ref**（R43、C115、C116）；**7 个**ref 的恰是"解码正确、位置不敏感"那组（U10、U14 + 五颗电容）。两组同为 exception，合计都是 10，落地无歧义 —— 我按**机制**分组，把标签与数量的错位原样记下（`observations[2]`），而不是替 oracle 改字。

**另一处真实的交叉（同样落成 observation）**：**`U14` 同时属于两批** —— 它是 30 个重复位号之一，也是 A2b 之一。不是笔误：两个器件真的都叫 U14，模型只留最后一个 placement，而**留下来的那个**的值与 MPN 矛盾。修 A1 的人必须回头复核 A2b，因为失去名字的那颗不是 A2b 记录说的那颗。

**该板实测（`outputs/011f_bishe_eval.txt`，A1-only 的中间态留在 `outputs/011f_bishe_eval_a1_only.txt`）**：

| | A1-only | A1+A2 |
|---|---|---|
| `conn-duplicate-designators` | **det 30/30 = 1.00** | **det 30/30 = 1.00** |
| `param-value-mpn-match` | fp-unexpl **10**（全部"无解释"） | fp-unexpl **0**、fp-exc **10** |

**A2 两组"安静"的确切含义（须讲清，否则会被读成精确率跳涨）**：它们从"**无解释**"（oracle 还没看）搬到"**已裁决的误报**"（oracle 看了、判规则错、写明了原因）。**该规则自身的 precision 仍是 0/10，高优精确率也仍把它们计入分母** —— 按 harness 定义，exception 就是"规则报错了"的记录，而 oracle 自己要的 M2 两个修法（解码器越界、矛盾幅度）正是为消除它们。**若你要的是把它们彻底移出精确率分母（例如新增 `known-limitation` 类），那是 harness 语义变更，我没有自行改**。

**holdout 草稿预览**（`outputs/011f_holdout_draft_with_bishe.txt`，把毕设板纳入 holdout 会是什么样）：检出 **32/32 = 1.00**，高优精确率 **32/49 = 0.65**（10 条撞 exception + 7 条 B 段未裁）。 **`011e_eval_holdout.txt`（毕业测量件）未改动**，仍是原两份文件的 2/2 = 1.00 —— 毕设板要等 B 段裁完、`reviewed_by` 签了才进毕业件。

### 四、变异验证（5 个，全 CAUGHT，还原逐字节一致）

1. 窗口上界改开区间 ⇒ 2.2k 用例红；2. 域门被绕过（非 3V3 也按窗口判）⇒ +5V 的 UNKNOWN 用例红；
3. "无限流"从 ERROR 降成 WARN ⇒ 严重级用例红；4. LED 自身网不再作供电侧兜底 ⇒ 无限流用例红；
5. A1 某条 defect 的 severity 写错 ⇒ 标注集契约测试 + 该板实测测试双红。

### 五、改动文件

- `src/boardwise/rules/params.py`：模块 docstring、常量、`LedCurrent` 类 docstring/title/source、新增 `_supply_side`、重写 `_rows`、证据行加"谁说的"。
- `reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`（新，40 条记录 + 4 条 observation）。
- `tests/`：`test_011d_rules.py`（PARAM-1 4→7 条；黄金板断言 UNKNOWN→OK）、`test_injected_variants.py`（"第二个后果"测试改成"只有一条 finding"）、`test_annotations.py`（+1 毕设集契约）、`test_review_eval.py`（+1 该板实测；两趟配对测试的 docstring 说明为何用合成规则钉）。
- `outputs/`：`011e_eval_dev.txt`（复跑）、`011f_bishe_eval.txt`、`011f_bishe_eval_a1_only.txt`、`011f_holdout_draft_with_bishe.txt`。

### 六、未做 / 待裁

- **B 段仍待裁**（triage 的勾选框我一个字没动，标注集与本节才是裁决的落点）。
- **A2 的 exception 是否该移出精确率分母**（见上）。
- A2a 标签与数量的错位：等 oracle 一句确认即可（落地已按机制，无需返工）。


---

## 交卷记录 I：毕设板 B 段落定与晋级判定草稿更新（2026-09-20，DeepSeek）

**三线全绿：pytest 1056 passed（数目不变，两处测试原地更新）/ connector 187（零 TS 改动）/ tsc 干净。**
**变异 4 个全 CAUGHT**（目标是被看守的**数据文件**——判决能被静默改写的就不是 ground truth），
还原逐字节一致。

### oracle 裁决落地（B 段，2026-09-19）

| 项 | 裁决 | 落地 |
|---|---|---|
| B1 `decap-required-caps` U11 pin5 | **defect** | items +1：`U11` / WARN / holdout。NET2 实测 100 nF + 10 nF，datasheet 要求 ≥1 µF 输出 bulk；规则读数正确，缺的是电容 |
| B2 `decoupling-per-ic` ×5 | **observation** | 观察记录 1 条（按裁决"记一次"）：L1 启发式局限，**M2 退役该规则** |
| B4 `shunt-sense-link` R43 | **observation** | 观察记录 1 条：connectivity-only 检查遇上滤波网络，规则没有说错 |
| B5 `conn-usb-cc-pulldown` ×2 | **backlog** | 观察记录 1 条：facts/解析缺口（UNKNOWN 不产出 finding，本就不进分母），并入 §C 队列 |
| B3 `xtal-load-caps` X1 | **待 Kimi 确认** | 未落；是全表唯一未裁行 |

标注集现为 **31 defect（30 重复位号 + B1）+ 10 exception，9 条 observation**；`split_default: holdout`。
待裁表（`*-triage.md`）同步：B1–B5 各补 **Ruling** 行、A 段补 **Ruling record** 汇总块并勾选已裁项。

### 签名状态：`reviewed_by` 仍为空——这是刻意的

B3 未落，全表尚未裁完；在还有一条未裁 finding 时签名，等于让报告摘掉 DRAFT 标的同时
把那条 finding 留在"oracle 未看过"的栏里。A 段落定时同一先例（B 未裁 ⇒ 不签）。
**B3 一到，签名就是一行改动**（`"reviewed_by": "Yue Xiangyu"` + 删掉对应 pending 观察），
随后复跑两份报告即可。

### 晋级判定草稿（更新，取代记录 G §四的表）

| split | 板数（有记录） | 缺陷检出 | 高优确定问题精确率 |
|---|---|---|---|
| dev（不变，字节级一致） | 5 | **5/5 = 1.00** | **5/5 = 1.00** |
| **holdout（2 注入板 + 毕设板）** | 3 | **33/33 = 1.00** | **33/49 = 0.67** |

**真实板进 holdout 把高优精确率从 1.00 拉到 0.67——这是测量在工作，不是它坏了。**
49 个 finding 逐个有着落：33 true positive（30 重复位号 + B1 bulk 缺失 + 2 注入）、
10 与 exception 相抵（A2，规则确要修）、**5 条已裁 observation**（B2，M2 退役）、
**1 条 B3 未裁**。换算成 M2 动作：退役 `decoupling-per-ic`（-5）、修 MPN 解码器（-10），
剩 33/34 = 0.97——**离 ≥95% 的门槛差的那一条，恰是 M2 清单本身**。
检出率 33/33 = 1.00 ✓（≥90% 达标）。

**一个如实报备的语义缺口**：schema 没有 `observation` 这种 item，按 oracle 原话"记一次"落成
观察记录后，B2 那 5 条在报告里落在"无 oracle 记录"栏——字面上与"未看过"同栏，虽然 oracle 已看过。
**数字不受影响**（exception 记录同样计入精确率分母，两种落法算出的 0.67 一致），但栏名有歧义。
若要求栏位也说真话，需要一次 harness 语义变更（新增 kind 或让 observations 参与解释）——**请裁决，未自行改**。

### 变异验证（4 个，目标是被看守的数据文件）

①B1 记录消失 ⇒ 毕设板测试红；②B2 观察记录被删 ⇒ 红；③**B3 未裁却签名** ⇒ 红
（`reviewed_by == ""` 是判决的一部分）；④B1 降级成 exception ⇒ 红。还原逐字节一致。

### 一次性提交清单

见 **`tasks/011-commit-checklist.md`**（本轮新增）：M1 全部产物按 src/tests/reviewsets/blocklib/
tasks/outputs(force-add) 分组，含两条**非 011 线**的待决项（`PROGRESS.md`、`tasks/012-*.md`）。
不动 git；清单只是清单。
