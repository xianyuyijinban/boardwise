# 516 审查反馈（岳真机实测，2026-10-17）

来源：岳用 v0.5.12+（`8380715` 之后）在实板 A 与多块实板上跑出的真实体验，
按「会不会让审查结论出错」排序。**A 级三条会让结论错，必须修**；B 级费时间；C 级打磨。

纪律照 `AGENTS.md` + `.kimi-code/skills/boardwise/SKILL.md` §7：不动 git、不 `rm`（删除走回收站）、
pytest 必带专用 `--basetemp`、并行只许 `-n 4 --dist loadfile`、变异验证 ≥2（`cp` 备份 + sha256 还原）、
证据落 `outputs/516/evidence.md`、`PROGRESS.md` append 一行并 `grep -c` 防双执行、零企业名（岳的板子一律叫「实板 A」）。

**本批不许碰的文件**（另有批次在途）：
`src/boardwise/engines/drawcompiler.py`、`src/boardwise/engines/router.py`、`src/boardwise/engines/placement.py`
（201C/201D 在途）；`tests/_process_guards.py`、`.githooks/**`、`dsh-plugin/**`、`packaging/**`（515B 刚改完待提交）。
若 `git status` 显示这些文件有改动，**不是你的**，不要 `git restore`、不要试图理解。

---

## A1（高）`pcb-voltage-spacing`：同电位豁免吞掉整对高侧网

**现象**：合同已声明 `HV=311`、`U/V/W=311`、`ACL=311`。报告只出 `GND↔U` 一条 WARN，
`HV` 与 `U/V/W/ACL` 之间零比对。岳手工复算：`HV↔U` 同层最近 **62.99 mil**
（`IPM1.2↔IPM1.1` 封装内），按 311 V 应给 **100.0 mil**，是一条真 WARN——现在它静默消失。

**代码事实**：
- `src/boardwise/rules/pcb/ipc.py:1016`（`VoltageSpacing._one_pair`）在
  `measured = net_clearance(board, first, second)`（:1031）**之前**调
  `_same_potential(first, second, volts_a, volts_b)`，命中就 `return None`。
- `_same_potential`（:1167）现判据：双地 → True；否则 `abs(volts_a - volts_b) <= 1e-9` → True。

**修法（岳裁定 2026-10-17，「同电位豁免只保留双地或几何重合」）**：
1. 豁免只保留两种：
   - **双地**：`is_ground_net(first) and is_ground_net(second)` → 豁免（保持现状）；
   - **几何重合**：`measured.overlapping and measured.distance <= 0.0` → 豁免
     （设计上的单点连接，如 `GND`/`PGND` 在一点汇合）。
2. 其余「标称同电压、不同实体」的网 → **按绝对电压判**：
   `differential = max(abs(volts_a), abs(volts_b))`。
   理由：两条开关相线平均值同为 311 V，瞬时差分可达 311 V（一条在 0、一条在 311），
   按峰峰摆幅上限判才是物理正确的保守估计；两个 5 V 直流轨按 5 V 判 → 4 mil，
   绝大多数间距都过 → 实际仍静默（不会制造噪音）。
3. **不能只做「差分照常判」**：`required_spacing_mil(0.0)` 落在 `0–15 V` 档 = **4 mil**，
   62.99 mil 还是会过——修了等于没修。必须走第 2 条的绝对电压。
4. 文案要写清口径，例如：
   `net 'HV' (311 V) and net 'U' (311 V) share a nominal potential but are not one node,
   so the swing bound max(|311|,|311|) = 311 V is judged: IPC-2221 gives 100.0 mil,
   measured 63.0 mil ...`
5. 实现上把 `net_clearance` 提到判定之前（或把 `board`/`measured` 传进 `_same_potential`）。
   注意 `net_clearance` 为 `None`（pour 盲区）与 `shares_a_layer=False`（跨层）的既有早退语义
   **不变**，它们发生在 `_same_potential` 之后的行为要重新排列但结论不变。

**测试**（新建 `tests/test_516_same_potential_spacing.py`）：
- 两个 311 V 同层近距（合成 `PcbReviewContext`，距离 < 100 mil）→ **WARN**，message 含
  `share a nominal potential` 与 `311`；
- 两个 5 V 同层近距（> 4 mil）→ 静默；
- 双地（`GND`/`PGND` 0 V 0 V）→ 静默；
- 同电位且 `overlapping=True, distance=0` → 静默；
- 既有夹具（`126c` 等）若钉住了「同电压静默」，按新口径改并注明理由。
- 变异：把 `max(abs(a),abs(b))` 改回 `differential` → 必须红；把双地豁免去掉 → 必须红。

---

## A2（高）`pcb-track-ampacity`：只审合同声明的网名，不跟铜走

**现象**：实板 A 同一导体被导出成 `IRbus`（原理图）和 `IRBUS`（PCB）两个名，
`net_clearance(IRbus, IRBUS)` 返回 `distance=0`、同层、`overlapping=True`——物理上是一根铜。
规则只报了 `IRbus` 那一半，`IRBUS` 那侧的 10 mil 铜没判（`Gear/GEAR` 同形态）。

**代码事实**：`src/boardwise/rules/pcb/ipc.py:661` `TrackAmpacity`，主体集
`_declared_net_names(ctx)`（只认合同名）。

**修法**：
1. 主体集按**连通分量**展开：对每个声明网，用 `net_clearance(board, a, b)`
   找 `overlapping and distance <= 0` 的相邻网并入同一分量（再对分量做一次闭包，BFS）；
2. 每个分量**取最窄**测量值判定（最窄的铜才是瓶颈）；
3. 报告里点名分量成员：`net 'IRbus' ≡ 'IRBUS' (one conductor, 2 names)`；
4. 若某个声明网真的连着一个未声明网，至少附一条 **INFO** 说明「声明网连到未声明网 X，
   本规则也测了它的铜」——即使不做全分量判定也不许静默。

**测试**（新建 `tests/test_516_ampacity_component.py`）：两网名同铜（distance=0, overlapping=True）
→ 分量合并、最窄处判 ERROR/WARN；单名无连 → 现状不变（既有 133b/126c 的期望不动）。
变异：去掉闭包（只做一跳）→ 三网链式同铜时漏判，必须红。

---

## A3（高）`needs-datasheet` 侧车重跑不自动并入，`warning-triage` 却自动并入

**现象**：15 项 `need-datasheet` 标记 → 重跑 checkup → `reviewerMarked` 变 0。
`source.notes` 留了一行「侧车有 27 条标记未并入，跑 need-datasheet 重新合并」，但：
- 两个侧车行为不一致（triage 自动、datasheet 手工），文档没解释；
- `need-datasheet` 一次只能标一颗器件，27 条要 27 次命令；
- AI 不读 notes → 报告看起来像「审查者什么都没标」。

**代码事实**：`src/boardwise/engines/checkup.py:3020` `merge_triage_sidecar`（自动并入）；
needs-datasheet 无对应函数。

**修法（三者都做）**：
1. 仿 `merge_triage_sidecar` 写 `merge_needs_datasheet_sidecar`：checkup 在 `--out`
   下发现 `needs-datasheet.json` 时自动并入（同口径：匹配到器件/pin 的才算 merged，
   其余进 `unmatched` 并在 notes 点名计数）；
2. CLI：`boardwise need-datasheet --merge <sidecar.json>` 批量回灌（或 `--pins` 支持追加语义，见 B2）；
3. `completion` 增明确字段（如 `completion.sidecarNeedsDatasheet = {"merged": N, "unmatched": M}`），
   不许只藏在 `source.notes`。

**测试**（新建 `tests/test_516_sidecar_automerge.py`）：15 条标记 → 重跑 → `reviewerMarked` 保持 15；
侧车里有一条指向已不存在的器件 → merged=14, unmatched=1 且有 note；无侧车 → 现状。
变异：把自动并入关掉 → 必须红（复现岳的现象）。

---

## B1（中）在线 checkup 默认合同路径不认旧的 `file-<hash>.json`

**现象**：上一轮合同叫 `file-dbe821bb97d1.json`，本轮不带 `--intent` 时读数「合同缺席」——
同一个工程换一次导出就要记得手动带 `--intent`。

**修法（择一，优先①）**：
1. 报「合同缺席」时扫描 `~/.boardwise/design-intent/`，若存在按导出命名的旧合同
   （`file-<hash>.json` 且内容像是本工程），note 里点名路径并提示「加 `--intent <path>` 或
   `arch --intent` 迁移到 `<projectUuid>.json`」；
2. `arch --intent` 同时写两份（`<projectUuid>.json` + `file-<hash>.json`）；
3. `checkup --intent latest`：取该目录下最新一份合同的约定。

---

## B2（中）`need-datasheet` 的 `--pins` 分两次调用是 replace 不是 merge

**现象**：同一器件先标 `19,20,23`、再标 `1,2,3`，第一次的 pin 被整条覆盖，合并侧车时会丢数据。

**修法**：明确语义并让两种都被支持——默认 **merge**（同器件多次调用取并集），
需要覆盖时用 `--replace-pins`；或 `--pins` 支持逗号/多次追加。文档写清。

---

## B3（中，**需真机，另行排**）bridge 输出信封不一致 + `pcb.readback` null 崩溃

- 错误返回「无 `result` 键」、成功「有 `result` 键」；`sch.readback` 还返回过裸对象。
  → 统一信封（永远有 `ok`/`result`/`error`）。
- `pcb.readback` 在编辑器重载时 `TypeError: Cannot read properties of null (reading 'map')`
  （`getAll` 拿到 null）；同会话 `pcb.geometry` 返回 `bboxes: 0`。
  → readback 前先 `doc.open + activateDocument`，null 时返回明确错误码而不是崩溃。
- 这类改动**必须真机验证**（岳在线时做），不进纯离线批次。

## B4（中，需真机）双窗口自动出现后所有 bridge 命令都要 `--project`

编辑器自己开了第二个工程窗口后，单工程审查也要带 `--project`。
→ 只有一个「像样」的工程时给明确提示（或自动落焦点），至少别每次重敲。

---

## C 级（打磨，可同批做）

| # | 问题 | 修法 |
|---|---|---|
| C1 | `oneLiner` 信息量不足：「不能投板：先改 5 项 ERROR」不带类型 | `oneLiner` 带 top-N 规则摘要，如「1 网表 + 4 载流」 |
| C2 | `--intent` 要绝对路径，相对路径在 `cd` 后静默落空 | 做 `Path.resolve()` 并在启动时 echo 实际使用的路径 |
| C3 | PDF 依赖 `pypdf` 不在主 venv，引导没点名 Python 版本 | `parts fetch` / 读 PDF 的引导里点名 **Python ≥ 3.9**，`getting-started.md` 给一行 `py -3.12 -m venv` |
| C4 | `report.json` 的 finding 键是 `rule_id`，`warning_triage[].ruleId` 是驼峰 | 统一命名（建议 JSON 输出统一 `rule_id`，`ruleId` 作为读入别名兼容） |
| C5 | Windows GBK 终端下 checkup progress 中文乱码 | CLI 启动时主动设 `stdout/stderr` 为 UTF-8（`reconfigure(encoding="utf-8")`，失败静默） |

---

## 交付要求

- 每条 A 级都要「先复现（探针或测试见红）→ 修 → 转回归」，`outputs/516/evidence.md` 逐条记录；
- 动 `src/boardwise/rules/**` 后**重钉** `tests/test_126a_pcb_review_plumbing.py` 两个指纹
  （当前 recursive `fc23ac00`、direct `3de90bc4`，台账注释在文件底部）；
- 全量：`.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_516`
  （**注意**：树上另有 201C 未提交改动，`test_175_*`/`test_178_*` 的 6 条红是 201C 的账，
  不是本批回归——交卷时如实区分）；
- 三线：`connector` 不碰；`dsh-plugin` 不碰；`tsc`/hygiene 若被触碰的文件涉及才跑。
