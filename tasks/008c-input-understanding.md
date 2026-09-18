# 任务 008c：输入理解——意图/固件/datasheet → 块方案 → 机器校验

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`tasks/008-generation-pipeline.md`（架构宪法五条）、`docs/blocks.md`（块模板与
> 装配管线）、`tasks/008b-part-selection.md`（件库与选型门禁）、`docs/architecture.md`
> （模型自由度边界）。008a/008b 已验收，本任务把"模型的输入端"接上。
> **目标板：智能药箱**（第一个生成靶，岳翔宇 2026-09-16 定）。
> **2026-09-18 冻结**：随 `docs/roadmap-2026-09-18.md` 生效，本任务书工作项 3 的余量
> （CH340N → STM32G431 → ESP-01S → MPU-6050 → 蜂鸣器 → 按键/LED）与工作项 5 端到端
> **冻结**（路线图 §8：不批量生成未验电路块）。已有 5 块保留为回放回归资产；
> AMS1117 手工几何改定位为 009-M2「LDO 画法」第一样本。主线转入 `tasks/009-schematic-review-m0.md`。

## 目标

008a 证明了"给定块规格能装出零差异的图"，008b 给了货架。本任务回答规格从哪来：

**输入 = 意图描述 + 固件代码 + datasheet PDF；模型产出 = BoardSpec 草稿 + 开放问题清单；
机器四道校验（闭卷闸 / 引脚预算 / 电平域 / 电源树）是硬闸门，不过在装配之前就不许往下走。**

**没有 BOM 这个输入**（岳翔宇 2026-09-16 定：实际做项目没人先写 BOM——BOM 是原理图的
产物）。器件清单由块模板自带的 `device` 绑定承载：模型按意图与固件证据选块，
件从 008b 货架来；BOM 反过来作为**交付物**从 spec 导出（工作项 1）。

宪法不变：模型只选块、填参数、列开放问题。本任务里模型多做的唯一一件事是**读**
（读意图、读固件、读 datasheet）——读的产出全是 JSON 草稿，每一份都有确定性校验器
等着它。模型依然不碰几何、不碰命名、不碰验收。

## 输入材料（岳翔宇提供，落 `inputs/smart_pillbox/`）

- `intent.md`（一段自然语言：板子干什么、主控与关键芯片是谁——模型选块的唯一意图来源）；
- `firmware/`（智能药箱固件源码）；
- `datasheets/`（AMS1117、CH340N、MPU-6050、STM32G431 等 PDF）；
- **终验参照**：智能药箱 `.epro2`（不加密导出，岳翔宇另行提供，到手前验收项 5 挂着）。

件库已知家底（008b）：智能药箱 13 种器件全部在库（STM32G431RBT6/ESP-01S/CH340N/
MPU-6050/AMS1117-3.3/蜂鸣器/晶振/连接器/按键）。

## 工作项

### 1. BOM 导出器（`engines/bom.py` + `boardwise bom export` CLI）

BOM 是输出不是输入。从 BoardSpec 反推：每块的 `components[].device` 绑定
（件库 key / LCSC）+ 参数值 → 按 LCSC 合并计数 → 导出 CSV（列对齐立创 BOM 习惯：
Comment/Designator/Footprint/LCSC/数量）。

- 每个设计符的器件身份必须能回溯到件库条目；绑定解析不出唯一件 ⇒ 进开放问题，
  **不许挑第一个**（#202 纪律原样适用于导出侧）。
- 负向：spec 里某器件无件库绑定 ⇒ 导出不许静默跳过，开放问题清单里必须有它。

### 2. 固件引脚表（契约 + 校验器）

模型读固件代码，产出 `pintable.json`。固件理解只到接口事实（宪法第 5 条），
不理解软件逻辑。

- 契约：`{mcu: <件库 key 或 LCSC>, pins: [{number, name, function, net}]}`。
- `function` 词汇表是**显式注册表**（仿 `CONSTRAINTS` 的模式：`GPIO` / `UART_TX` /
  `UART_RX` / `I2C_SCL` / `I2C_SDA` / `PWM` / `ADC` / `SWDIO` / `SWDCLK` / `NRST` …，
  按需扩，**表外即错误**）。
- 机器校验（全部失败关门）：
  - 引脚号必须存在于 MCU 块模板的符号上（符号 `offsets` 的键就是证据）；
  - 一个引脚号不许出现两次；
  - **双向差集**：引脚表里每个 `net` 必须在 spec 的 connections 里出现（固件用了脚、
    原理图没接 = 缺陷）；spec 里连到 MCU 块的每个信号端口必须在引脚表里有对应
    （原理图接了、固件没用 = 开放问题，单列清单，不算违例但必须在报告里）。

### 3. datasheet/教科书块提取（模板来源 1、2 的首次实证）

模型读 datasheet 的典型应用章节（或经典拓扑），产出块模板 JSON 草稿：

- `provenance.kind = "datasheet-extract" | "textbook"`，`source` = datasheet 文件名 + 页码
  （教科书块写明拓扑名）。
- **拓扑由岳翔宇亲签**——这是全管线唯一允许的人工判断点，写进报告。
- 新参数约束（如 `divider_ratio(vout,vref)`、`voltage_derate(0.8)`）：约束是可执行代码，
  模型只提议，落进 `CONSTRAINTS` 必须带单元测试 + provenance（datasheet 页码）。
- **几何问题，正面回答**（**2026-09-17 岳翔宇裁决作废重写**）：datasheet 只有拓扑没有坐标，
  所以块模板允许 `geometry` 为空。~~空几何的块在装配时交给既有 generic solver 排块内布局~~
  —— **这句作废**。作废理由（本轮实测）：
  ① `replay_or_solver` 的分流条件是 **`page.parts` 非空**（`replay.py:721`），而装配器总会往
  `page.parts` 放器件 ⇒ **装配产物永远走 replay，永远到不了 solver**；
  ② 空几何块的 `components[].placement` 是**作者签过的摆位**，不是待解的量；
  ③ solver（`generate.py` + `layout.py`）从未质量验证过，不进装配路径。
  正确终态：**装配产物走 replay 就是对的**，块内连通性由装配器**逐引脚合成的锚点**承载，
  不需要走线。规则见 `docs/blocks.md` 的 "Anchors: two paths"。块间仍然只走网络标签，
  R1~R5 与注解 lint 一律不豁免。
- **闭卷所需的全套块**（智能药箱端到端要用，一个不能少）：AMS1117-3.3 电源块、
  CH340N USB 转串口块（注意不是 CH340G——药箱用的是 N）、STM32G431 最小系统块
  （含 8MHz 晶振、去耦、复位、SWD）、ESP-01S 插座块、MPU-6050 块、蜂鸣器驱动块
  （三极管+蜂鸣器，教科书）、按键/LED 块（教科书）。
  第一批是"**装配器合成锚点 + 真机画布可读**"的第一次真机考验——岳翔宇亲签可读才算过。

### 4. 块方案校验器（`engines/validate_spec.py`）

四道闸门，输入 = BoardSpec + pintable + 件库，全部失败关门。**元数据不够时报
"无法判定"而不是放行**——无法判定的通过比不通过更糟。

- **闭卷闸（最先跑）**：spec 引用的每个块模板，其 `provenance.source` 不许追溯到
  目标板自身（生成智能药箱时不许出现从智能药箱切出来的块）；spec 的每个字段
  （块选择、参数值、连接）必须携带指向声明输入（intent / 引脚表 / datasheet 页 /
  件库 key）的证据，无证据字段 = 违例。**答案（黄金 .epro2）只许出现在 compare
  判据侧，任何生成侧产物引用它都是违例。** 这条把"不许抄"从口头变成硬闸门。
- **引脚预算**：工作项 2 的双向差集 + MCU 块已用端口数 ≤ 符号引脚数。
- **电平域**：信号网两端端口声明的 `level` 一致；不一致且中间没有声明为电平转换的块
  = 违例。`level` 是块端口上的可选新字段（如 `"3V3"`/`"5V"`）。
- **电源树**：每条 power 网**恰好一个 source 端口**（零个 = 无源，两个 = 对冲，都报）；
  source 声明电压 == 每个 sink 声明的要求电压（字符串精确匹配，电压值与 provenance
  都写在声明里）；gnd 网豁免 source 唯一性（地就是汇）。

**schema 扩展（可选键，version 仍 1）**：`BlockPort` 加 `direction`（`source|sink`，
仅 power/gnd 类端口需要）与 `voltage`；信号端口加 `level`。旧模板没有这些键 ⇒
跑这三道校验时如数报"无法判定"。**把 CH340 四块的端口元数据补齐**（已知好板，
正好校验校验器：它必须全过）。

### 5. 智能药箱端到端（闭卷）

`inputs/smart_pillbox/` 三样输入 → 模型产出 spec + 开放问题 → 四道校验器 →
`draw --spec` → 三闸门。**绘制落在 test 工程**（岳翔宇 2026-09-17 定），新页仍走
创建确认门禁。

**闭卷纪律（岳翔宇 2026-09-17 定）**：生成全程**不许用任何从智能药箱切出来的块**，
智能药箱 `.epro2` 只作 compare 判据、不作任何生成侧输入——管线的机械正确性 008a
已经证过，不需要再拿自切自装证明一次。块全部来自工作项 3 的 datasheet/教科书来源。

**判据**：四道校验器全过 + compare 对黄金网表的差异**逐条三分类**——
「等价任意选择」（网名、合法范围内的阻值人选）/「有据改进」（带 datasheet 页码证据）/
「真实缺陷」。目标不是字面零差异（那是 008a 机制验证的标准），
而是真实缺陷清零 + 岳翔宇判 0.8。

### 6. 一块多实例 + 位号分配

008a 留下的尾巴（"按实例分配位号属 008c"）。规则：同一块模板被 spec 引用多次时，
块内位号模板按"块内原值 + 实例序号"派生（派生规则写成确定性代码 + 测试）；
跨块位号冲突照旧报错。智能药箱若无重复块实例，本项以合成测试验收。

## 验收

1. BOM 导出器：从端到端 spec 导出的 BOM 与智能药箱实际用料对账（器件种数与数量，
   差异逐条归因）；负向（无绑定的器件必须进开放问题、不许静默跳过）一例。
2. 引脚表：双向差集工作；负向（幽灵引脚号 / 一脚下两名 / 词汇表外 function）各一例。
3. 四道校验器各带负向测试（闭卷：spec 引用目标板自身来源的块必须被拒；电压不匹配 /
   一条 power 网两个 source / 电平域 crossing）；
   **补齐元数据后的 CH340 spec 后三道全过**（已知好板必须过，过不了是校验器错）。
4. 工作项 3 的全套块：岳翔宇逐个签拓扑 + solver 块内布局真机亲签可读。
5. 端到端（闭卷）：spec 全部字段可溯源到输入（意图描述 / 引脚表 / datasheet 页 /
   件库 key），无一字段追溯到智能药箱黄金；compare 对黄金的差异逐条三分类，
   真实缺陷清零，岳翔宇判 0.8。
6. 测试计数只增不减（基线 **Python 625 / connector 167 / tsc 干净**）。
7. 完成记录写回本任务书；新增桥动作先报 Kimi 评估（daemon 重启归 Kimi）。

## 不许动的部分

008a/008b 全部既有语义（块模板既有字段、装配规则、阻值门禁、词汇表）；
约束注册表只增不改既有约束语义；创建确认门禁；不做 PCB、不做仿真、不理解固件逻辑；
在线选型路径仍默认关闭、测试不许打真网络。

---

# 008c 完成记录（逐项写回）

## 工作项 6 — 一块多实例 + 位号派生 ✅（2026-09-17）

**规则（确定性代码，`core/blocks.py`）**：`derive_designator(ref, ordinal)` —— 实例序号 0
**原样保留**模板位号，序号 n 把数字部分加 `DESIGNATOR_STRIDE = 100`（`R1` → `R101`）。模板身份
= **解析后的模板路径**（手工构造的 spec 退化为模板名，已注明）。不是字母+数字形状的位号
（`X1A`/`1`/`R`）**拒绝**，不猜测。

**一个必须一起解决的问题（任务书没写，但不解决则功能不可用）**：块内**未连接**的网
（`NET5`/`NET6` 这种内部无名网）在复制出的实例里会与本体同名 ⇒ 装配器报"两个电路同名"。
所以**重复模板的第二及以后实例，其未被 `connections` 命名的网按实例作用域化**：
`NET5` → `NET5#<block id>`。序号 0 一行不动 ⇒ **一模板一实例的 spec 与 008a 逐字节同义**
（`designator_map` 对既有 CH340 spec 是恒等映射，测试钉住）。

**跨块冲突照旧报错**，但判据改成**页面位号**（派生之后）：两个不同模板都声明 `R1` ⇒ 拒绝；
`R101`(实例0) 与 `R1`(实例1) 撞名 ⇒ 拒绝。另加一条：**重复 block id 直接拒绝**
（所有辅助函数以 block id 为键，重复会**静默覆盖** —— 这是实现时真踩到的假冲突）。

测试：`tests/test_designators.py`（10 例，纯规则 + 边界 + 恒等性）、`tests/test_assemble.py`
（+2 例：两实例并排装配成功且报告派生；模板共享位号仍被拒；重复 id 被拒）。

## 工作项 1 — BOM 导出器 ✅（2026-09-17）

`engines/bom.py` + `boardwise bom export --spec X [--library] [--out] [--json]`（exit 0 完整 /
1 有开放问题或自相矛盾 / 2 输入不可装配）。

- 判据来源 = **spec**：每个块的 `components[].device` 绑定（**C 号是键**，008b 合并同一物理件的
  唯一键）+ spec 赋的参数值 → 按 C 号合并计数 → CSV（`Comment,Designator,Footprint,LCSC,Qty`）。
- **Footprint 列是件库词汇表名**（`R0402`），不是块的人读标签 —— 006b 词汇表规则。
- 位号用**页面位号**（`designator_map`），所以一块两实例的板子出一行两号（`R1,R101`）。
- 三条拒绝：绑定解析不出唯一件（**不挑相近料号、不挑"另一个 5.1k"**）⇒ 开放问题；
  无绑定的器件 ⇒ 开放问题并**点名位号**（绝不静默跳过）；同一 C 号两个值 ⇒ 开放问题且
  **两个值都不打印**（#202 纪律）。导出前先跑 `assemble()`：装不出来的页面没有可信的料表。

**实测（CH340 spec）**：16 个放置件中只有 2 个能解析（`C2765186` USB-C、`C47773` RT9013），
其余 14 个的 C 号**不在件库上** —— 因为件库是从另外四块板播种的。导出如实逐条报出并 exit 1。
这不是缺陷，是"件库覆盖面"的诚实读数；药箱 spec（工作项 5）才是有绑定的那一份。

测试：`tests/test_bom.py`（17 例：解析三态、合并计数、spec 值压模板默认、无绑定点名、
两个值都不打印、页面位号、读序排序、CSV 形状、CLI 三态）。

## 工作项 2 — 固件引脚表 ✅（2026-09-17）

`core/pintable.py`（契约 + `.ioc` 读取 + 交叉核对）+ `engines/pintable_check.py`（三道闸门）
+ `boardwise pintable check`（exit 0 无阻塞 / 1 有缺陷 / 2 输入坏）。

- 契约 `{mcu, pins:[{number, name, function, net}]}`；`PINTABLE_FUNCTIONS` 是**显式注册表**
  （18 个成员，每个带一句含义），**表外即错误** —— 照抄 `CONSTRAINTS` 的形状，理由相同：
  来者不拒的词汇表等于没检查。
- 三条闸门，**跑不了的闸门会说"这不是通过"，绝不静默放行**：
  ① 引脚号必须存在于 MCU 块符号的 `offsets`（幽灵引脚号 ⇒ 缺陷）；
  ② 一脚不许两名（两条读数都进 evidence，因为后一条会默默赢）；
  ③ **双向差集** —— 固件用了脚而原理图没接 = **缺陷**；原理图接了而固件没用 =
  **开放问题**（单列、不阻塞：板子完全可以有固件还没长进去的脚，判成缺陷就是校验器错）。
  power/gnd 端口不参与方向二（`GND` 不是"固件忘了的脚"）。
- **`.ioc` 是引脚分配的确定性基准**（岳翔宇定），模型从 C 代码提取的表必须与它交叉核对，
  **任何不一致进开放问题，不许 silently 信任何一边**。`cross_check()` 只报不判，五类冲突
  各有测试：`missing_from_ioc` / `missing_from_firmware` / `net_mismatch` /
  `function_mismatch` / `firmware_only_net`。
  - `VP_*` 虚拟引脚读进来（好让计数与 CubeMX 对得上）但排除出一切比较 —— 虚拟脚没有球可焊。
  - `PF0-OSC_IN` 取 `PF0` 这一段，否则每块 STM32 的晶振脚都会被判成永久分歧。
  - **`GPIO_Output`/`GPIO_Input` 不是网名，是方向**。这条是实测踩出来的：按网名处理它，
    会让每个 GPIO 脚看起来都有名字，而真正只有 `main.h` 手写宏作证的 `PC4`(LCD_RES)
    反而静默通过。现在方向 ⇒ 基线沉默 ⇒ `firmware_only_net` 正落在它头上。
  - 未建模的设置（`RCC.HSE_VALUE` 等）原样留在 `IocProject.raw`，不必再写第二个解析器。

**实测（智能药箱）**：`Smartbox.ioc` 报 34 脚 = **28 物理 + 6 虚拟**；C 代码侧与它
**28/28 全一致**，唯一分歧是 `PC4`（固件叫 `LCD_RES`，基线无网名）⇒ 1 条开放问题，不是缺陷。
另有三条**不是引脚分歧**的读数写进表的 `notes`：① `SystemClock_Config()` 走 HSI 而 `.ioc`
配 HSE 8MHz（时钟树问题，归 intent 的 8MHz 晶振）；② `spi.c` 的 `_16` vs `.ioc` 的 `_64`
（参数不是引脚）；③ `huart3` 启用了 TX/RX 内部 Swap（PCB 上 ESP-01S 与 MCU 同向），
这是**接口事实**，表按 MCU 自己的命名记 `PB10=USART3_TX`，对端看到的是反的。

文档：`docs/pintable.md`。测试：`tests/test_pintable.py`（37 例：词汇表三个负例中的两个在
加载层、三条闸门各带负例、五类冲突各一例、两份真输入）。

## 工作项 4 — 四道校验器 + CH340 端口元数据 ✅（2026-09-17）

`engines/validate_spec.py`（四道闸门）+ `boardwise validate --spec X`（exit 0 干净 / 1 被拦
/ 2 输入坏）。细节在 `docs/validate_spec.md`，这里只记**判据之外的三个决定**。

**① "无法判定"和"跳过去"是两个不同的结局，都不是通过。**
每道闸门有四种状态：`pass` / `fail` / `undecidable` / `skipped`。**无法判定按违规一样阻塞**
—— 假装同意的报告比拦下来更糟；**跳过去不阻塞**（没有 MCU 的板子是真的存在），但它必须
打印"nothing was checked"，永不允许冒充同意。CH340 的 pin-budget 就是 `skipped` 而不是 pass，
因为这张板没有引脚表可读。

**② 端口元数据走旁车，不进块文件（`core/portmeta.py` + `blocklib/blocks.portmeta.json`）。**
`direction`(source|sink，只许在 power/gnd) / `voltage`(只许在 power) / `level`(只许在 signal)
加起来沿用已验证的通行写法：**在校验之前把旁车合进解析后的 JSON，所以在加载器里只有一处
执法点**（犯错时消息点名旁车而不是文件）。

必须走旁车的理由，是本项目第三次遇到同一件事（006b 黄金更正、008b 件更正）：
`tests/test_cut.py` 要求每个已提交的 `ch340_*` 块**逐字节等于重切一次的结果**，而"这个口是
3V3 且它是汇"是**声明**，不是板子几何能说了算的事实。我先按字面把这三条写进了四个文件，
全量立刻炸出一条新的 `test_cut` 红 —— 我没有去改那条守卫（那等于削掉监管），而是回滚、
改走旁车。**副作用是刻意的**：不带旁车读同一批块 ⇒ 电平闸与电源树闸全部"无法判定" ⇒
照样阻塞（有测试钉住）。

**③ 闭卷闸把"不许抄"从口头变成硬闸门。** 模板 `provenance.source` 追溯到目标板 ⇒ 违规；
目标板的名字出现在 spec 文件正文里 ⇒ 违规（`answer-leak`，连"拿去对比"这句话都不许写）；
declared input 指向目标板 ⇒ 违规。每个字段必须 citing 一个**声明过的输入**
（`references`，词汇表封闭：`intent`/`pintable`/`datasheet`/`part`/`textbook`，各自定义了身份
放在哪个键上）。`--target` **可以重复给**，必须给目标板的每一个别名（导出件 + 本地工程），
日期后缀会被剥掉（`ProPrj_box_2026-09-17.epro2` 与 `ProPrj_box` 是同一块板）；
`ch340x` 不会因为像 `ch340` 而被判。

**实测（CH340，已知好板）**：补元数据后 **电平闸 / 电源树闸全过**，pin-budget `skipped`，
闭卷闸 fail 20 条 ⇒ **符合要求**：这四块正是从它要被对照的那张板上切下来的。
去掉 `--port-meta` 重跑 ⇒ 后两道变成 4+2 条"无法判定"，同样阻塞 —— 这就是第 ② 条决定在真机上
的落脚点，有测试两头钉住。

**一个必须报的事实**：`blocklib/parts.json` 在本轮之外于 **16:08 被重新 harvest**（新增了今天
15:57 导出的 `tests/fixtures/ProPrj_智能药箱_2026-09-17.epro2` 与 `ProPrj_毕设FOC驱动板_2026-09-17.epro2`
两份 fixture，件库 85 → 92 条）。由此全量里有 **3 条既有的红**
（`tests/test_harvest.py` 里钉"件库来自哪些源/等于一次新 harvest/还留有小写封装名"那三条），
**与本工作项无关**，也**没有动它** —— 那是别人盘中状态的调整，改测试或改件库都要你裁。

文档：`docs/validate_spec.md`。测试：`tests/test_validate_spec.py`（68 例）：每道闸门都被问了它
存在的那个问题，也被问了它必须拒绝的那种形状。另有旁车模块 8 例（表外字段、给不存在的端口
annotate、与文件里已有的值构成第二答复、缺失文件报错而非沉默、provenance 落进 notes）。

## 计数

Python 733 → **801**（+68：`tests/test_validate_spec.py`）
/ connector **167**（未改）/ `tsc` 干净。**动作面未变**（29 条）⇒ 不需要重启 daemon。
另：3 条既有的 `test_harvest.py` 红，起因见工作项 4 的"必须报的事实"，非本工作项所改。

---

## 工作项 4 验收（岳翔宇 2026-09-17 亲跑）

**通过**：801 里 798 绿 + 3 条红经核实全部是 harvest 的旧事实；`validate` 真机冒烟四道闸门
行为正确，含 `STOPPED → exit 1`。

**3 条红按 Kimi 顶库的预期状态修**（改测试钉新事实，**不许反向改件库去将就旧测试**）——
见下节"件库顶库后的测试对齐"。

---

## 件库顶库后的测试对齐（2026-09-17，岳翔宇裁决：改测试钉新事实）

Kimi 在 16:08 把件库从 4 源 85 条顶到 **6 源 92 条**（新纳入今天 15:57 导出的
`ProPrj_智能药箱_2026-09-17.epro2` 与 `ProPrj_毕设FOC驱动板_2026-09-17.epro2`）。
这是**预期状态**，所以 `tests/test_harvest.py` 里钉旧数字的三条按新事实改写：

- `HARVEST_SOURCES` 4 → **6 源**；`PILLBOX_EPRO2_ENTRIES = 13` / `THESIS_EPRO2_ENTRIES = 35`
  为**实测**值（13 + 41 + 47 + 15 + 13 + 35 = 164 次出现，合并 **92** 条，共享 72 次）。
- CH340N（C2977777）现在上了**全部六块**板（原来四块）——断言加强，并顺带钉住
  "药箱/毕设两块各被读过两种格式、没有变成两个条目"（合并键是 C 号不是文件）。
- **"还留有小写封装名"那条被推翻，且不是它错了**：`--verify` 在 2026-09-17 把 92 个名字
  全部settle成库的拼写，于是两条**库级拼写计数**（"被不同源拼得不一样"/"只有唯一源拼过"）
  被合法退休。**这是桥跑过的结果，不是数据丢了。**

**由此暴露的一条真规则（写进引擎，不是写进测试）**：库级 notes 里那两条拼写计数与
`BRIDGE_DECIDED_FIELDS` 是**同一类事实的散文半**——只有桥能问出答案，无桥的 harvest 复现不了。
所以新增 `BRIDGE_DECIDED_LIBRARY_NOTE_MARKERS` + `strip_bridge_decided_notes()`，与既有的
`strip_bridge_decided()` 成对；`tools/harvest_parts.py --check` 的 `_diff_keys` 也走它
（**比字段先漏的一处**：字段有忽略集，库级 notes 当时没有，所以 `--check` 会报一条
"library note only on disk"）。同时把两条计数的生成下沉为 `harvest.spelling_notes(parts)`，
**一个规则一份定义**（工具、引擎、测试同源）。

**两处自我纠错（差点写成假断言，值得记）**：

1. 我先把 `+5V` 在块内 0 个 source 当成违规——**错**。整板规则是"每条 power 网全页恰好一个
   source"；单块完全可以是**纯汇**（本块从 USB 座收 +5V）。块自己必须不歧义（它向外供的轨要有
   恰好一个 source + 电压），不是"块内必须自己产电"。
2. 我一度按 `case-preserving` 这条 note 断言"存活下来的是小写"——**错**。该 note 的语义是
   "**两个**源对同一个名字的大小写不一致，所以做了选择"，存活的是**源真用过的那个**（所以
   `BUZ-TH_...` 是大写）。"只有唯一源拼过"是**另一条**信号、落在库级计数上。两条信号我混过一次。

**计数**：Python 801 → **802**（+1 拆出的新用例）/ connector 167 / tsc 干净。
`tools/harvest_parts.py --check`（六源）实测 **matches a fresh harvest** —— 用工具侧独立复核过。

---

## 工作项 3 — datasheet/教科书块提取（进行中，一块一签）

**流程（岳翔宇 2026-09-17 定）**：每块**先出草稿**给他 → 转岳翔宇**亲签拓扑** → 才进
`blocklib/blocks/`。**不许 7 块一口气全写完再给人看**；先拿 **AMS1117 电源块**试流程。

草稿落点：`blocklib/drafts/`（未签的块不进 `blocks/`，`--recut` 守卫也不该看到它们）。

### ① `power_ams1117_3v3` — **已签入** `blocklib/blocks/`（2026-09-17）

`provenance.kind = datasheet-extract`。三件：U1（AMS1117-3.3 / C6186）+
C1（输入 10μF / C6119889）+ C2（输出 10μF / **C6119889，与 C1 同料**）。三个端口
`+5V`(sink,5V) / `VCC`(source,3V3) / `GND`(sink)，元数据**内联**（datasheet 块不走旁车，
见下"元数据归属规则"）。`geometry` 为空（datasheet 无坐标）。`blocklib/drafts/` 已清空。

**岳翔宇 2026-09-17 三条裁决（已落地）**：

1. `provenance` 保持 `datasheet-extract` + 混合性质如实写明 —— **不动**。
2. 输入 10µF —— **不动**。
3. **输出电容不要钽的**：C2 绑定 `cap.10u_0805`（C6119889，10µF 50V X5R），与 C1 同料；
   `c_out_value` 默认 `10uF`。provenance 写**全链条**：datasheet p.4 原文（22µF 钽为
   全工况值 + "ADJ 不旁路时更小电容等效"，固定 3.3V 版无 ADJ 脚）+ 岳翔宇裁决
   —— **MLCC 是有意选择（成本/可得性，ESR 风险由他承担并签字）**。

**datasheet 出处（C6186，8 页，文本层可读）**——用 `tools/_pdftext.py` 提的：

- p.1 *Pin Connections*（3-pin fixed/adjustable）：`1- Ground/Adjust  2 - VOUT  3 - VIN`
  ⇒ U1 的引脚号与引脚名是**读来的**，不是假设的。
- p.4 *Application Hints / Stability*：**"requires the use of an output capacitor as part of
  the device frequency compensation"** + **"The addition of 22mF solid tantalum on the output
  will ensure stability for all operating conditions"**（PDF 文本层把 μ 渲染成 `m`）
  ⇒ 输出电容是**必需件**，且值 22μF 有原文。
- p.4 同段 *Protection Diodes*：**"does not need any protection diodes"** ⇒ 不画保护二极管是
  **有出处的刻意缺席**，不是漏画。
- p.5 Fig.3 只讲 Kelvin 接法（在哪取输出），**不是**应用电路图。

**两条诚实边界**（第 3 条已由裁决关闭）：

1. **datasheet 没有典型应用电路图**。所以拓扑本身是**教科书**三端稳压器接法，
   `provenance.kind` 是 `datasheet-extract`，description 里写明了这个混合性质。
2. **输入电容 10μF 不来自 datasheet**（它没写输入电容要求）。这是教科书惯例选择，
   per-param provenance 里明写 "NOT from the datasheet"，可被推翻。

**已验证的（确定性，非人眼）**：加载器解析通过；三端口元数据自洽
（`+5V` 纯汇 ⇒ 整板 source 由 USB 座提供；`VCC` 恰好一个 source 且电压 3V3）；
引脚网名全部落在 interface 内、无飘网；provenance 里**不含**药箱字样（闭卷闸干净）；
每个 param 与每个 device 绑定都带自己的 citation。

### 元数据归属规则（本轮新立，已加测试钉住）

**端口元数据放哪，由"这个块能不能被重切"决定**：

- **`board-extract` 块** ⇒ 走旁车 `blocklib/blocks.portmeta.json`。因为 `test_cut.py`
  要求块文件逐字节等于 `recut()` 的结果，而端口元数据是**声明**不是几何事实 ——
  写进块文件会被重切抹掉。
- **`datasheet-extract` / `textbook` 块** ⇒ **内联写在块 JSON 里**。没有重切守卫要满足，
  元数据放在不会与块漂移的地方更好。

规则不是"元数据一律走旁车"，而是**"旁车恰好为那些有重切守卫要满足的块而存在"**。
测试：`tests/test_validate_spec.py::test_where_port_metadata_lives_follows_from_whether_the_block_can_be_recut`
（两个方向都做过变异验真）。

### ✅ rail 端口命名锚点 — 已裁决并落地（岳翔宇 2026-09-17）

原阻塞：AMS1117 装不进页面，报
`AssemblyError: ... has no power flag at (100, -100) to name it; the template must
carry one (there is no way to invent a flag symbol)`。我把那句话验伪后提请裁决
（四条证据见下），岳翔宇裁：**空几何块的 rail 端口由装配器合成旗标锚点，模板不带旗标。**

**被证伪的那句话（四条证据，`tools/_probe_flag_anchor.py` 退出码 0）**：

1. `sch.place_power` 签名 `(kind, net, x, y, rotation, mirror)` —— **没有符号 uuid**
   （`connector/src/actions.ts:2746`），编辑器由 `kind` + `net` 自己解析图形；
   `PlacedFlag.symbol_uuid` 为空时 replay **优雅降级**（只用于注释框预测）。
   **给个位置就能造旗标。**
2. **端口位置其实是旗标位置的拷贝**：四个 board-extract 块**每一个** rail 端口的
   position 都精确等于一个旗标位置 ⇒ 那条检查在核对**同一份数据的两份拷贝**。
   board-extract 永远满足（切块带进旗标），所以**这条假设从未被触发过**。
3. **"端口位置"在块内多值**：AMS1117 的 `+5V` 落在**两个**点（`(55,10)`=U1.VIN、
   `(10,0)`=C1.1，均为实测端点）⇒ `[0,0]` 是**如实反映"端口是声明层，不是几何事实"**。
4. 任务书原第 71–74 行的 solver 承诺**已被本裁决作废**（见上文"几何问题，正面回答"）。

**六条裁决（逐条落地）**：

| # | 裁决 | 落地 |
|---|---|---|
| 1 | 锚点合成时机 | **装配器内直接合成**（`assemble()` 先于 `replay_or_solver()` 跑；锚点只需块内引脚端点，本就不依赖 solver） |
| 2 | 格距与方向 | `GRID` = 5.0（`engines/layout.py:85`），纯竖直外扩：power 挂该网文件 y **最大**端点再 **+y** 一格，gnd 挂 y **最小**端点再 **−y** 一格（文件空间 y 向上为正） |
| 3 | 重叠/压器件 | 先按规则出，**不检查不去重**；只有锚点落进器件 body bbox 时**记 note、不 raise** |
| 4 | 端口旗标落点 | **兼任**：power 取 y 最大端点（并列取 x 最小）、gnd 取 y 最小端点，signal 取 x 最小（并列取 y 最小）；该脚不重复放 |
| 5 | signal 网 | **逐引脚放** `NetLabelAnchor`（rotation=0，就放端点上，不打短线）；NC（无网）不放 |
| 6 | solver 分流 | **问题作废** —— 空几何块不需要 solver，装配产物走 replay 就是正确终态 |

**改动清单**：`src/boardwise/engines/assemble.py`（docstring 删假话 + 双路径说明；
新增 `_block_pin_endpoints` / `_extreme_endpoint` / `_synthesise_anchors` / `_component_boxes`；
端口段按 `bool(wires or flags or labels)` 分流）、`src/boardwise/core/blocks.py`
（`position` 改可选 `Point | None`；geometry 后加分流校验；`_port_to_json` 条件写）、
`blocklib/blocks/power_ams1117_3v3.json`（三端口删 `position`；notes[0] 改写）、
`tests/test_assemble.py`（+7 条）、`tests/test_pintable.py`（fixture 三个端口删 `position`）、
`docs/blocks.md`（新增 "Anchors: two paths" 节 + 字段表 + 第三条拒绝改写）、
`tasks/008-generation-pipeline.md`（第三条拒绝改写）、本文件。

**验证**：pytest **816 passed / 0 failed**（原 809，+7；既有测试语义一条没动，只修了
`test_pintable.py` 一处 fixture 数据）；connector **167 pass**；`tsc --noEmit` 干净。
四条新测试做了**变异验真**（方向反转 / 格距改错 / 关掉 position 两个方向的校验各咬住），
还原后逐字节复核、无残留。

**B1（Kimi 转达，2026-09-17 晚，必修）**：`_block_pin_endpoints` 漏了空网引脚 ——
它与 `_resolve_nets`（`:220`）必须一致，否则几何空块会给一根 `net: ""` 的 NC 引脚
合成**无名旗标/标签**（没人写过的名字，编辑器也渲染不出来）。已加
`if not pin["net"]: continue` 并附注释指向 `_resolve_nets`；回归测试
`test_a_pin_with_no_net_is_not_given_an_anchor`（夹具扩了一根 `("", "signal")` 引脚，
断言 page 上无空名 flag/label/wire，且 VCC/SIG/GND 三个网不受影响）。
夹具顺带修正：空网引脚**不再生成 port**（`role` 不许空，接口不该有它）。
变异验真：摘掉守卫 ⇒ 恰好咬住这一条，还原后逐字节 `cmp` 一致。

**N1（顺手）**：`_synthesise_anchors` 的 report 行原来报 `len(page.flags)` /
`len(page.labels)` —— 那是**整页累计值**，会把这个块的产物算上前面所有块的。
改为进函数时记 `flags_before` / `labels_before`，出口做差，报**本块新增**计数。

**B1/N1 后**：pytest **817 passed**（+1，正是预期）；connector 167；tsc 干净。

**这条已解，工作项 3 继续。**

### 待核查（交卷项）：AMS1117 的符号 offsets 无真机出处 — **已关闭（2026-09-17，见文末记录）**

裁决要求核查 `REG-3PIN` / `CAP-2PIN` 的 `offsets` 是否为真实器件符号的实测值。
**当时核查结论：拿不到真机出处，块里是上一轮按 SOT-223 常识编的近似值。**

- 件库（`blocklib/parts.json`）只有**器件**元数据（`deviceUuid` / `libraryUuid` /
  footprint 名，且 footprint 名 verified），**不含符号引脚几何**。
- `blocklib/sources/*.eprj2` **读不了**（本地备份加密，`EncryptedProjectError`）。
- `tests/fixtures/0819f05c4eef4c71ace90d822a990e87` 是个 **SQLite 库文件**，但**全表 0 行**
  —— 只有 schema，没有数据。
- `tests/fixtures/ProPrj_智能药箱_2026-09-17.epro2` 里能找到真机 AMS1117
  （位号 **U11**，C6186），但它的符号定义不在该文件内 ⇒ `build_pin_offsets` 返回 `None`。

**锚点数学全压在这些 offsets 上**，所以这是一个必须让岳翔宇知道的边界：**要真值就得从
真机问库（`sch_PrimitivePin` / 符号定义）**，那需要桥在线的只读查询。真机冒烟时一并取。

### 结转：`port.direction` 目前无人校验（不阻塞，但会咬人）

`direction = "sink" | "source"` 装配器**完全不看**，整板校验器（工作项 4）才用。
AMS1117 声明 `+5V` sink / `VCC` source 是对的，但"块的 source 声明"与
"页面实际有几个 source"之间**现在没有校验**。留到工作项 4 校验器落地时再钉。

---

## 2026-09-17 真机冒烟结果 + AMS1117 符号 offsets 修正

### 冒烟结果：管线跑通，锚点漂浮（offsets 是编的 ⇒ 必然结局）

`boardwise draw --spec blocklib/specs/ams1117_smoke.json` 真机执行了 **11 条桥动作**
（建页、放 3 件、放 7 面合成旗标、铺 7 根单格 stub）。机制全对，但合成锚点**全部漂浮**：
因为块里 `REG-3PIN`/`CAP-2PIN` 的 offsets 是上一轮按常识编的近似值，与真实库符号的引脚
位置对不上 —— 编辑器网表读回显示 **U2/C8/C2 的所有引脚网名全为空**（页面上既有工程件，
我们的件落在 U2/C8/C2 位号上）。锚点合成数学本身无错，错在输入的几何。

**一条排除项**：verify 阶段报的"U1 多出引脚 4..16"**不是我们的件** —— 那是脏宿主工程里
既有的一颗 **CH340G（位号恰好是 U1）**。我们的 AMS1117 落位 U2。真机冒烟前宿主工程
未清空，此读数属串扰。

### 修正：offsets 换真机实测值（2026-09-17，`sch.component_pins` 实测）

对**实际放置的库符号**在画布上实测（放置 rotation=0、mirror=false；画布 y 向下，
文件空间取负转 y 向上）：

- **AMS1117-3.3（C6186，符号 uuid `06f50e10ab7d460599b3fe3ee8717a78`）**：真实符号是
  **四脚** —— 1/2/3 竖排在左（x=−45：VIN 顶 y=+10、VOUT 中、GND 底 y=−10），
  4 脚（VOUT，散热片 tab）在右（+45, 0）。与 datasheet p.1（1=GND/ADJ、2=VOUT、3=VIN）
  加 tab=VOUT 一致；库符号把 1 脚命名为 "GND"（不带 /ADJ）。
- **0805 电容（C6119889，两次测量一致）**：**横放**符号，1 脚 (−20, 0)、2 脚 (+20, 0)。
  （编的版本是竖放 (0,±15)，全错。）

落进 `blocklib/blocks/power_ams1117_3v3.json`：符号键 `REG-3PIN` 改名 `AMS1117-3.3`
（四脚实测符号再叫 3PIN 就是撒谎）；U1 `pins` 补 4 脚（name VOUT、net VCC —— tab 电学上
就是 VOUT，不带网就成了页面上的悬空脚）；两个 `body` 改为按引脚范围**估计**的盒子
（库符号 dump 不含字形图元，无实测 body，notes 里如实声明）。

**摆位随实测几何重排（岳翔宇裁决：作者摆位无签名，属块维护）**：旧摆位是按编的几何排的，
实测几何下 lint 出两条违例（U1.4 tab (145,0) 与 C2.1 (140,0) 的 VCC 旗标 LABEL_OVERLAP；
VCC 端口旗标文本框压 C1 估计 body 的 LABEL_ON_COMPONENT）。裁决后：C1 (40,0)→**(30,0)**、
C2 (160,0)→**(185,0)**、U1 不动 (100,0)。重排后锚点（块内文件空间）：+5V (55,15)端口/(10,5)、
VCC (55,5)端口/(145,5)/(165,5)、GND (55,−15)端口/(50,−5)/(205,−5) ——
**8 旗标 / 8 stub / 0 违例**（`lint --spec ams1117_smoke` 实测）。

**连锁**：VCC 现在有 3 个端点（U1.2、U1.4、C2.1）⇒ 合成 **8 面旗标 / 8 根 stub**
（+5V×2、VCC×3、GND×3）；`blocklib/specs/ams1117_smoke.json` 的 "seven flags" 已改为 8。

**仍待确认**：实测的引脚 X/Y 假定是**连接端点（pin tip）** —— 由重画后的网表 compare
终验（重画后编辑器网表应读出 +5V/VCC/GND 全部落网）。

### 旁支：export.render 移植到 getExportDocumentFile（2026-09-18，视觉能力修复）

008c 主线之外的一次连接器移植，记在这里因为它是"模型理解输入"链路上的视觉证据通道。

**来源**：参考仓库 `easyeda-agent_RE`（`source/extension/src/actions.ts:3135-3269` 的
`schematicExportImage`，issue #166）——该实现**已在真机 3.2.186 上实测可用**。

**之前**：`export.render` 打 `sch_ManufactureData.getPngFile`。类型包标注该方法
*ADD since v3.2.183*、主机报 3.2.186，调用却答 `NOT_IMPLEMENTED`（2026-09-14 实测）——
验收图通道一直是断的，只能靠 viewport 截图（会回缓存帧，不是证据）。

**之后**（connector 0.4.2）：`export.render` 走
`sch_ManufactureData.getExportDocumentFile(fileName, fileType, typeParams, object)`。
参数重订：**`format`**（png|svg|pdf，默认 png；svg 是可缩放矢量，可读性评审用）、
**`scope`**（page|selection|project，默认 page；selection 必须带 `ids`，先调
`sch_SelectControl.doSelectPrimitives` 选中再渲）、**`fileName`**（可选，默认
`render.<ext>`）。**width/height 删除**（新 API 不收尺寸，文档渲染自己定界）。

**关键陷阱（.d.ts 是错的，别"修正"回去）**：`object` 实参必须是字面量
`'Current Page' | 'Current Page Selected Items' | 'Project'`；类型包声明的那套值
（`'All Schematic'|…`）会让宿主 promise 永不 settle——编辑器只剩一个卡在 1% 的 toast。
所以连接器给这个调用套了 30 s 超时护栏，超时错误信息明说"重新加载文档以清掉卡住的
toast"。多页工程可能回 zip，动作如实报 `format: 'zip'`，不给调用方一个名叫 .png 的压缩包。

**同步机制**：动作目录是三处手工保持一致——`protocol.py` 的 `ACTIONS`、
`connector/src/actions.ts` 的 `buildHandlers`、`docs/bridge.md` §4 表——由
`connector/tests/contract-drift.test.mjs`（文本解析三方比对）和
`tests/test_action_catalogue.py`（目录自洽）看守。本次三处 + docs/draw.md 验收图一节
均已改。`PROTOCOL_VERSION` 未动（先例：目录变更从不 bump；daemon 只比 major）。

**待办（建筑师侧）**：daemon 重启（目录变了，旧 daemon 对新参数不感知——虽然
export.render 名字没变，旧 daemon 也能转发，但 --help 渲染的是旧表）；连接器 0.4.2
重新打包 sideload（`npm run package` → `boardwise-connector-0.4.2.eext`，装后授
"external interaction"，用 `sys.probe`/About 确认版本号=0.4.2，防静默没装上）。
