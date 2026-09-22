# 020 上游 issue 对照审计（easyeda-agent → boardwise）

> 2026-09-22 中午，岳从 easyeda-agent 的 issue 列表提炼 6 条疑似共性坑。
> 取证：explore 子代理 ×2（Python 侧 1/2/4、connector 侧 3/6，只读）+ Kimi 直算审计分布（5）。
> 本文是裁决版：每条 = 判定 + 关键证据 + 建议动作。代码行号见两份子代理原始记录。

## 总览

| # | 事项 | 判定 | 首日（17:00 朋友版）影响 |
|---|---|---|---|
| 1 | 修复后复查不查"反增报"（#236/#228/#114） | **部分存在（设计如此）** | 无（edit 非首日功能） |
| 2 | 多同名脚解析歧义（#145） | **同名覆盖不存在；同族"静默丢脚"存在** | **有——审查正确性** |
| 3 | self_update reload 无版本回读（#250/#252） | **存在（假成功窗口开着）** | 无（朋友直装 0.4.11，不走热更） |
| 4 | 库域 uuid / 实例域 id 混用（#220） | **部分存在（apply 链路干净，解析层有分歧+潜伏）** | 低 |
| 5 | 写动作 p95/p99 分布（#208） | **数据已在，工具未有（已补上数据面）** | 无 |
| 6 | place_wire/place_text 无自我回读（#135/#170） | **部分存在（text 最弱：uuid null 也报成功）** | 低（朋友主用审查=读路径） |

## 逐条

### 1. 修复幂等/反增报 —— 部分存在（设计如此，缺一层）

- 现状：`edit apply` 第 7 步 postReview **只重跑目标规则、只看目标位号**（cli.py:4044/4116/3585 的 `_findings_naming` 过滤）。不跑全规则基线，不看新增 finding，不看其它位号。preview 同样。
- 修复通道只有 `param-value-mpn-match` 一条（cli.py:3485 `REPAIRABLE_RULES`），不可修规则 `edit plan` 点名拒绝（exit 5）——"CLI 修不了"是明示边界，不是上游那种"报了修不了"。
- 上游"修完反增报"在我们这的形式 = **修完根本不看别处**。
- 建议：apply 前后各跑一次全规则（离线模型，成本毫秒级），报"新增 finding 数"。优先级：中（M3 线）。

### 2. 多同名脚（USB-C VBUS×4/GND/EP）—— 同名覆盖不存在，静默丢脚存在 ⚠️

- **不存在的部分**：解析器按 **pin number** 建键，name 只是随行属性（schematic.py:413-419）；6 个夹具实测同名多脚极普遍（毕设板 STM32H743 VDD×5、llc HYG015N10 S×7 等）全部解析正确；ch340_golden 的 TYPE-C 14 脚对照编辑器网表**逐脚全中**；毕设板 USB1 VBUS=None 是**源文件自己的 NO_CONNECT**（parentId+坐标双证据互证，还残留悬空线桩），不是解析歧义。
- **存在的同族缺陷**：**缺 Pin Number 的 PIN 记录被静默丢弃**（schematic.py:416 `and run_number` 硬门槛；517-519/784/871-872 `symbol_def is None: continue` 同样静默）。llc_board 实测：某符号 10 条 PIN 记录 7 条无 number → 7 个有名脚（Q1G/Q1S…）整脚消失，ParseStats 无计数、无 note。若某 USB-C 库件把 VBUS 写成无名号脚，症状与上游 #145 **完全一致**：恒定漏连且零告警。
- 建议：**丢脚进 ParseStats 计数 + 审查输出 note**（让"漏"变得可见），合成最小用例钉测试。优先级：**高（审查正确性，朋友首日就会碰）**。另留一道实测：毕设板真机导出编辑器网表，核对 USB1 VBUS 编辑器侧是否也为 NC（坐实"正确转述"）。

### 3. self_update 无版本回读 —— 存在（假成功窗口开着）

- 证据：CLI 打印 `ok: old->new` 即 return 0（cli.py:3058-3077），`newVersion` 是**回显入参**（self-update.ts:275-293），reload 排 500ms 定时器后无任何回读；单测把这个契约钉死（test_bridge_cli.py:523-541）。审计数据面：self_update p50=26ms / max=52ms = 只写 DB 就返回。
- 缓冲：daemon 在重连 hello 里**已收到**运行时真实版本（daemon.py:643/1129），`bridge status`/`sys.probe`/doctor 都能读——回读源存在，只是 update-connector 不接。
- 建议：update-connector 加"等重连（有界）→ sys.probe 读运行时版本 → 比对报告/超时警告"。今早我自己就是手动跑的 status——恰好证明了缺口。优先级：中高（快修，半天内）。
- 附：extension.json（CLI 读）与 package.json→build.mjs 注入的 `__BOARDWISE_VERSION__` 是两个文件，可 drift——值得加一条发布检查（connector tests 里 version.test.mjs 已钉版本一致性？待核）。

### 4. device identity 域混用 —— 部分存在（apply 干净，解析层有分歧+潜伏）

- **干净的部分**：edit apply 写入链路只用实例域（designator + primitiveId），不碰库域 uuid——apply 不存在"两侧各用一域"。
- **分歧点**：`schematic.py` `_symbol_uuid_of` 实例域优先、库域（DEVICE META `symbol`）兜底，两域**同键空间**查 `symbols` 字典且**从不互校**。llc_board 实测分歧 2 处（CN2/CN3，16 位 vs 32 位），因两份符号文档内容恰好相同未致错。注意：uuid 长度不是域判据（两域都出现 16/32 位）。
- **潜伏**：`plan.target.primitive_id` 装载后**从不被读取/比对**——手写 plan 指定 primitiveId 会被静默忽略、按 designator 自行解析写入（可能写入他处而不告警）；`Component.uid` 两域混装（cli.py:1911、cut.py:293 消费）。
- 建议：apply 增加"plan 带 primitiveId 且与解析结果不一致 → 拒绝/警告"；`_symbol_uuid_of` 分歧记 note；优先级：中。

### 5. 写动作耗时分布 —— 数据已在（已补），工具未有

- 审计日志 39101 行自带 `ms`/`ok` 字段，分布随算随有：`outputs/020_audit_action_latency.txt`。
- 要点：`place_component` p50=2.4s/p95=5.2s/p99=6.9s（max 30011=超时截断）；`lib.device.get` p95=3.0s；`place_wire` p99=72ms；`delete` p95=30011=旧 30s 超时截断（DELETE_TIMEOUT 已提 150s，坑表 2 的 3.7s/件是编辑器逐件重解）。
- 建议：把分析脚本做成 `boardwise bridge stats`（读审计出分布表），写超时时查分布不查点测。优先级：低（工具向）。

### 6. place_wire/place_text 自我回读 —— 部分存在

- `place_wire`：uuid 取自 create 返回对象（**非页面读回**），失败靠 `withCreateRetry`（actions.ts:3569-3582/3505-3532）；
- `place_text`：**uuid null 也返回成功**（actions.ts:3743-3757）——三者最弱，"没落地"静默；
- 对照：`place_netlabel` 有真回读（`netAttributeLanded`，actions.ts:3605-3633）——范式已在仓里；
- draw 流程丢弃返回值（draw.py:1332），末尾靠 netlist 差分间接兜底；wire 数量从未与 plan 比对。
- 建议：wire/text 补 timeout 路径的落地回读（照 netlabel 范式）；text 的 uuid null 至少记录进 records。优先级：低（画线非首日场景）。

## 建议的处理顺序（岳裁）

1. **#2 静默丢脚可观测化**（ParseStats 计数 + note + 合成测试）——唯一直接影响审查正确性的项，朋友首日会碰。
2. **#3 update-connector 自动版本回读**——快修，把"假成功窗口"关上。
3. #1 apply 全规则基线 diff、#4 plan.primitiveId 校验——M3 线顺手做。
4. #5 `bridge stats`、#6 wire/text 回读——工具与健壮性，排期即可。

> 若批准 1+2，开 020 任务书派 deepseek 执行，Kimi 复验；预计各半天内。
