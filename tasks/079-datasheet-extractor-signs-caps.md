# 079：datasheet 提取器符号与电容口径批（#34 / #49 / #50）

三个 issue 同一文件 `src/boardwise/engines/datasheet.py`，一次触碰修完，**验收形各自独立**
（岳在 #49 留言的原话：「建议一起修、各自验收，否则修了一支漏另一支」）。

## 1. #34 — `_PAIR` 把列分隔短横读成负号（岳已裁定：紧贴数字才算负号）

`_PAIR`（:59）的符号段是 `[−–—-]?\s?\d`——`\s?` 让带空格的列分隔 `-` 被当负号：
`VBAT ... operating voltage - 1.55 3.6 V` → v_operating=[-1.55, 3.6]（真值 1.55–3.6）。

**修法**：符号段改 `[−–—-]?\d`（去掉 `\s?`）——真规格书里真负值恒紧贴数字
（`–0.3`/`-0.5`），带空格的分隔短横不再当负号；模棱写法宁可读正（区间放宽=保守方向，
岳在四份真规格书上的实测依据见 #34 评论）。

**验收**：`... - 1.55 3.6 V` → [1.55, 3.6]；`VCC –0.3 6 V` → [-0.3, 6]；
`VDD -0.5 6.5 V` → [-0.5, 6.5]（真负值不丢）。

## 2. #49 — `_RANGE` 区间分支丢前导负号（与 #34 同函数相邻分支，方向相反）

`_RANGE`（:51-55）两个分支的 `(\d+(?:\.\d+)?)` 都不收前导符号，且只有 `_PAIR` 分支
做了符号归一化（:185 那一串 replace）——`-0.5V to 6.5V`（绝对最大值典型写法）读成
[0.5, 6.5]，「低于地 0.5V 的裕量」消失。真规格书实例见 issue（MPU-6050 p.7/p.9 三行）。

**修法**：
- `_RANGE` 两分支的**低位**数字加前导符号段 `[−–—-]?`（紧贴，同 #34 裁定）；**高位也加**
  （`-6V to -0.5V` 全负区间合法，同族不遗漏——岳「边界外的同族崩溃也要修」的既有裁定）。
- **`_TRIPLE`（:56）同族一并修**（三个数字段同样可能带符号），加测试。
- **符号归一化只写一份**：抽 `_signed_float(text)`（映射 `−–—`→`-`、去空格、float），
  `_RANGE`/`_TRIPLE`/`_PAIR` 三处共用——071「一个判据一个实现」，#49 原话「别再各写一份」。
- 注意 `_RANGE` 第一分支的分隔符集合本身就含 `-`：符号段必须**紧贴数字**（不收 `\s?`），
  否则分隔符与符号歧义复活——这与 #34 的裁定是同一条。

**验收**（与 #34 分开钉）：`-0.5V to 6.5V` → [-0.5, 6.5]；`-0.5 V to 2 V` → [-0.5, 2.0]；
`3V to 6V` → [3, 6]（无符号照常）；MPU-6050 三行原文逐字（issue #49 里）端到端
`candidate_facts` 各得负下界；#34 的三条验收不回归。

## 3. #50 — `required_caps` 只收 bypass/decoupl 电容，与 curated 口径分裂

`candidate_facts`（:302）的过滤是 `_DECOUPLING.search(probe) and \bpin`——只认关键词，
MPU-6050 p.22 外部元件表 4 颗必需电容只提 2 颗（Regulator Filter / Charge Pump 被丢），
下游 `decap-required-caps`（ERROR 级）对缺电容的板假通过。curated 口径（parts.json 里
MPU-6050/AMS1117/RT9013 三条）证明设计意图是「必需外部电容」全集，不是去耦子集。

**修法**（岳的方向 1 为底，方向 2 作护栏，**禁走「再补几个关键词」**——071 反复教训：
白名单只覆盖被写的那个 witness）：
- 判据改**结构形**：一行同时满足「电容功能词 + `(Pin N)` + `_CAP_VALUE` 可读值」即收，
  `bypass|decoupl` 门删除。
- **「Capacitor ≠ Capacitance」**：`Input Capacitance (Pin 8) 10pF` 是特性 spec 不是 BOM 件，
  过收会让 decap 规则假 VIOLATION——功能词判据要能分开这两个词（中文「电容」两义，
  用 section/上下文护栏，岳的方向 2：标题含 `Bill of Materials|External Components|外部
  元件|Application` 的段内放宽）。具体判据由执行者**在真语料上量出来**（见下），任务书
  不预写死；但两条硬验收必须过。
- `_DECOUPLING` 若不再被引用则连正则一起删，别留死常量。

**验收**：
1. MPU-6050（`inputs/smart_pillbox/datasheets/MPU-6050_C24112.pdf`）提取 = **4 颗**
   （pin 8/10/13/20，值 10nF/0.1uF/0.1uF/2.2nF 逐颗对上 p.22 表）。
2. **curated 幂等钉**（#38 harvest 幂等同理）：`blocklib/parts.json` 里凡有 curated
   `required_caps` 且本仓有其 datasheet 文本的器件，提取器结果必须**覆盖** curated
   （curated ⊆ extracted；超收逐条申报理由）。这条进测试，防「策划收 4、提取提 2」再分裂。
3. **过收回归**：AMS1117 / RT9013 / STM32（语料里有的）提取的 required_caps 不爆炸
   （before/after 对照，新增颗颗申报，Capacitance-spec 形不得混入）。

## 4. 硬规则（范围钉死）

- 只许动：`engines/datasheet.py`、`tests/` 里 datasheet 相关测试文件、（如需幂等钉）
  `tests/test_harvest.py`。逻辑外文件一行不动。
- 不碰：`core/power_domains.py`、`rules/decap.py`（下游消费方语义不变，只是事实变全）、
  `blocklib/parts.json`（curated 是基准不是被改对象）、`inputs/`、`tests/fixtures/`。
- 三个 issue 的验收测试**分开命名分开钉**（test_034_* / test_049_* / test_050_*），
  不许合并成一个「符号修好了」大断言。

## 5. 纪律

- pytest 必带 `--basetemp=.tmp_pt_home`；全量主跑一遍报数。
- 变异 ≥2 组（建议：`_PAIR` 的 `\s?` 加回 / `_RANGE` 低位符号段删除 / Capacitor-Capacitance
  区分失效），备份放 `.tmp_mut/`（禁放 basetemp 内）、字节级 replace、`cp` 还原 + sha256
  核对，证据落 `evidence/079/`。
- 改文件用 Edit 或字节级脚本（Windows GNU sed 吃 CRLF）；零 git 写操作；不写 PROGRESS.md。
- 纯离线批：不重启 daemon、不碰真机。规格书 PDF 只读。

## 6. 交卷

改动文件 sha256 before/after；三个 issue 各自的验收实证（逐条对 issue 原文的例子）；
`_range_of` / `candidate_facts` 全部调用方审计；语料 before/after 对照（required_caps
全语料清单 diff）；变异证据；边界外发现（只报不改）。
