# 039 审查深化批①：parts 工具链 + 事实库第一波

## 背景

审查规则的"四态协议"（OK/VIOLATION/UNKNOWN/NOT_APPLICABLE）设计意图是：**UNKNOWN 驱动事实库
 intake 优先级**。但现状是死结：`blocklib/parts.json` 94 条里只有 3 颗 IC 带 curated
 `facts`（AMS1117-3.3 / CH340G / RT9013-33GB），其余 91 条是板提取的原始参数堆
（`category: null`、无 facts）——规则对它们只能 UNKNOWN，而**没有任何工具把"缺什么"摆出来**。
岳的审查 SOP 里"不懂的器件用 Web Search 搜规格书"目前全靠 AI 自觉，没有工具门禁。

本批把"补事实"做成流水线：**missing（摆清单）→ add（脚手架）→ curation（带出处填 facts）→
verified 闸（未核验不驱动决策）**。facts 词表现状：`supply_pins` / `required_caps` / `nc_pins` /
`must_connect` / `pull_required` / `ldo` / `led`（`rules/facts.py`、`rules/decap.py`、
`rules/params.py` 消费；`core/parts.py` 762–830 行有 facts 形状校验器）。

**不做**：新规则族（电平耐压 `io_abs_max` 等新 fact 键归 039b，先有事实再有规则）；
不动 017（草稿仍待岳审）；纯离线批，**不需要真机**。

## 工作项 0：选型（先量后选）

- 用 `tests/fixtures/` 与 `blocklib/sources/` 里的既有工程导出件，统计 U 前缀器件的 MPN 分布
  （**离线只读**，禁地工程的本地导出件可以用，真机不许碰）。
- 默认候选 5 颗（岳真实板上的、封装小、datasheet 好拿）：**CH340N / SN65HVD230DR /
  TLV9062IDR / REF2033AIDDCR / MPU-6050**。跑出来的分布说了算，可换，但换要给出理由。
  STM32G431/H743、DRV8313/8350 这批多脚复杂件**不进第一波**（留给 039 批②，先证明流水线）。

## 工作项 1：`boardwise parts missing --file <工程>`

- 离线命令，吃 `.epro2` / `.eprj3`（`_load_model` 已两格式通吃，038 红利直接用）。
- 输出每个 U 前缀器件一行：designator / mpn / lcsc / datasheetUrl（raw 条目里有就带）/
  **缺哪些 fact 键**（例如 `supply_pins, required_caps`）/ category 状态。
- 无缺失时 exit 0 且明说"全部可查"；有缺失 exit 0（这是报告不是失败）——退出码语义写进
  `--help`。**JSON 输出** `--json` 必带（AI 消费）。

## 工作项 2：`boardwise parts show <mpn|key>`

- 人类可读 dump：身份（mpn/lcsc/footprint/category）+ facts 全文 + 每条 provenance +
  `facts_verified` 状态。找不到 → exit 2 并给模糊候选（子串匹配前 5 个）。

## 工作项 3：`boardwise parts add <mpn> --lcsc <C码>`

- 往 `parts.json` 追加**候选条目**：category 空、facts 空、`facts_verified: false`、
  `provenance.kind: "manual-curation"`。mpn 已存在 → 拒绝（exit 2）并指向 `parts show`。
- 写盘纪律：保持既有 JSON 结构与键序风格，diff 友好；写前 `cp` 备份 `.tmp`，写后重解析验证。

## 工作项 4：verified 闸（本批唯一动规则层的点）

- `PartEntry` 增 `facts_verified` 字段。**缺省 = true**（兼容既有 94 条——它们没这字段，
  缺省 false 会把 AMS1117 等既有 curated 打回 UNKNOWN，eval 全变，不许）。
- `parts add` 写 `false`；规则读 facts 前查 `facts_verified is false` → **视同无 facts**
  （UNKNOWN，名字点出"候选条目未核验"）。`core/parts.py` 校验器认识新字段。
- 翻 true 的裁决权 = 岳在 git diff 里审（这就是"核验"的物理形态）。

## 工作项 5：第一波 curation（5 颗）

- 逐字段填 `facts`，**每条带 provenance**（datasheet 页码 + URL；拿不到 PDF 就用 LCSC 商品页
  + WebSearch，provenance 如实写来源等级——"lcsc product page" 就是比 "datasheet p.2" 弱，
  不许包装）。参考既有 AMS1117 条目的写法（`supply_pins.v_abs_max` 只填datasheet真说的边）。
- **datasheet 获取约束**：LCSC 的 `datasheetPdfUrl` 是二进制 PDF，FetchURL 大概率吃不下。
  优先 LCSC HTML 页 + WebSearch 交叉；真要读 PDF，在 `.tmp_pdfenv/` 建**隔离 venv** 装
  `pypdf`，**不进项目依赖、不进 requirements**。
- curate 完**直接翻 `facts_verified: true`**（工作项 4 的闸保护的是"未审先生效"，executor
  自审+测试后再翻）——但红线见下：eval delta 必须逐条解释。

## 测试与验收

- verified 闸：`false` → UNKNOWN（点名"未核验"）/ `true` → 正常决策，各一例；
  缺省字段（既有条目形态）→ 行为逐字节不变。
- `parts add` 重复 mpn 拒绝；`missing` 对 `.epro2` 夹具与 eprj3 合成夹具各一例；
  `show` 找不到的模糊候选；JSON 输出形态断言。
- **eval 红线**：`review-eval` 前后各跑一遍。curated 器件若出现在评测板里，读数变化
  **逐条解释**（哪条规则、哪块板、从什么态到什么态、为什么是对的）；
  高优精确率/缺陷召回**不许降**。
- 变异 ≥2：verified 闸失效（false 也驱动决策）/ missing 漏报（少列一颗），各至少 1 红。
- 三线全绿：pytest `--basetemp=.tmp_pt_home` / connector `npm test` / `tsc`。
  connector 预期零改动，要动 → 停下来报主代理。
- 交卷文本 `outputs/039_summary.txt` + 证据 `outputs/039_*.txt`（含工作项 0 的 MPN 分布、
  eval 前后对比）；不碰 git / PROGRESS / SKILL.md（SKILL 审查 SOP 的 curation 循环段归主代理）。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 cp 备份 + sha256/cmp 还原；
真机全程不碰（本批纯离线）；`tests/fixtures/` 既有夹具只读；eprj3/epro2 工程文件只读。

## 批①b：decap 规则硬化 + REF2033 翻闸（批①真机数据挖出的两个既有盲点）

批① curation 用真实板数据照出 `decap-required-caps` 两个既有盲点（证据 `outputs/039_eval_delta.txt`
与 039_summary.txt §三），本批修规则并翻闸：

1. **"电容在、值没填"被报成"没有电容"**：毕设板 U9（REF2033）NET7 上确有电容 C34，但其 `Name`
   属性为 `null` ⇒ `looks_like_capacitor` 不认 ⇒ `decide_required_cap` 返回 `missing` 而非
   `unreadable`。修法：候选判据把"封装/类别像电容但值不可读"与"没有电容"分开——前者报
   `unreadable`（WARN 措辞改为"有电容但值读不出，无法核对 0.1uF 要求"），后者才报 missing。
   修完把 `ic.ref2033aiddcr` 的 `facts_verified` 翻 **true**。
2. **两端同网的电容被当合格退耦**：毕设板 C115（330uF）两端都在 AGND，被判成 U5 pin5 的
   合格退耦（OK）。修法：合格退耦必须**桥接两个不同的网**（供电网 ↔ 地网）；两端同网者
   不算，并给一条单独的 WARN（"电容两端同网，不接任何东西"——这本身是焊接/原理图错误信号）。
   注意边界：若被护脚的网本身就是地网（U5 pin5 落 AGND 的异常形态），不许借这条规则断案，
   如实 UNKNOWN 并指明"脚落在地网"这一事实。

验收：两个盲点各一组正负用例；eval 前后对比，**VIOLATION 不许减**（已知 0 条变化基线），
新增 WARN 逐条解释；REF2033 翻 true 后的 delta 同样逐条解释；变异 ≥2（两个修法各退回一次
看红）；三线全绿；不碰真机、不碰 git / PROGRESS / SKILL.md；交卷 `outputs/039b1_summary.txt`
（注意别踩 039b 审查流程批的文件名，那是下一批）。

## 交卷记录

（子代理交文本，主代理 append 并复验。）
