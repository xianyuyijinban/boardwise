# 020 任务书：上游 issue 对照修复——静默丢脚可观测化 + 热更版本回读

> 2026-09-22 中午，岳批准（"修吧，修完记得push"）。
> 执行者：commandcode/deepseek-v4.1-flash 子代理（**两个 work item 串行做，都碰 cli.py，不许并行**）。
> 复验与真机裁决：Kimi。背景与判定全版：`outputs/020_upstream_issues_audit.md`。

## WI-1：解析器静默丢脚可观测化（审查正确性，高优）

**问题**：`src/boardwise/parsers/schematic.py` 有三条静默丢弃路径，零计数零告警：
- `:416` `flush()` 里 `and run_number` 硬门槛——PIN 记录缺 Pin Number 时整脚丢弃
  （实测 `tests/fixtures/llc_board.epro2` 某符号 10 条 PIN 丢 7 个有名脚 Q1G/Q1S/Q2G/Q2S/Q3G/Q3S/Q4G）；
- `:517-519`、`:784`、`:871-872` 的 `symbol_def is None: continue`——symbol 解析不到时整器无脚，同样静默。

**要做**：
1. `ParseStats`（找它的定义处，同模块或 epru_stream）新增计数字段（如
   `pins_dropped_no_number`、`components_without_symbol`——命名沿现有 stats 风格），
   三条路径丢弃时计数。解析结果本身**一字不变**（只多计数）。
2. review 命令（`src/boardwise/cli.py` 的 `_cmd_review`）：当计数 >0 时——
   - 控制台加一行英文 note（跟 019 同机制，参考 `EMPTY_PCB_VIEW_NOTE` 的接法）：
     `note: N pin(s) dropped during parse (missing pin number) and M component(s) without a resolvable symbol — review coverage is incomplete`（按实际计数拼，为 0 的项不说）；
   - `--md` 中文摘要节加一句（复用 `i18n.py` 的 `summary_section(hint=)` 通道，019 已建）：
     `提示：解析中有 N 个引脚因缺少引脚号被丢弃、M 个器件未能解析符号——审查覆盖不完整，结果可能漏报。`
   - **`--json` 逐字节不变**（schema 被 test_review_eval 钉死）。
   - 覆盖范围：schematic view 必做；pcb view（`.epro2` 默认）若走同一解析器通路顺带，
     不走就在交卷报告里如实说明（enent 输入不涉及）。
   - 计数从 ParseStats 到 cli.py 的**通路需要自己查**（解析入口有没有把 stats 带回；
     没有就最小改法带出，别大改）。
3. 测试 `tests/test_020_parse_drops.py`：
   - 真实样本：`tests/fixtures/llc_board.epro2`（只读使用！）走 review schematic view →
     断言 note 出现且计数 ≥1（实测 7，但断言用 ≥1 防库件修复后脆断）；
   - 合成最小用例（mock/直接喂解析器）：缺 Pin Number 的 PIN 记录 → 计数+note；
   - 正常样本（ch340_golden.epro2）→ 无 note；
   - `--json` 无变化。
4. 变异验证一轮：把计数或 note 接法删掉 → 测试红；cp 备份 + sha256 还原。

## WI-2：update-connector 自动版本回读（关上假成功窗口）

**问题**：`cli.py` 的 `bridge update-connector`（约 2966-3077 行）调完 `sys.self_update`
打印 `ok: old->new` 就 return 0；`newVersion` 是回显入参，reload 后无任何回读。
现有单测钉死了这个契约（`tests/test_bridge_cli.py:523-541`，断言含 "0.4.2 -> 0.4.3"
与 "reloading"）——**契约要升级，该测试允许改**。

**要做**：
1. self_update 返回后新增验证阶段（默认开启）：
   - 有界等待重连：轮询 daemon 的 status/probe（看 `bridge status`/`sys.probe` 现有
     客户端封装，别新造轮子），建议间隔 1s、总预算 30s；
   - 重连后读**运行时** connector 版本（`sys.probe` 的 connector 字段，doctor 在
     `cli.py:4883-4898` 有现成读法）与期望版本比对：
     - 匹配 → 打印 `verified: running connector is now X.Y.Z`，exit 0；
     - 超时未重连 → 打印警告（状态不可陈述），exit 3；
     - 重连了但版本不匹配 → 打印失败（假成功实锤证据），exit 1。
   - 加 `--no-verify` 跳过（恢复旧行为），帮助文本写清。
2. 测试：改 `test_bridge_cli.py:523-541` 的 mock 让它带上"重连后 probe 回报新版本"
   并断言 verified 输出；新增用例：不匹配 → exit 1、超时 → exit 3、`--no-verify` →
   旧输出。mock 模式沿用该文件现有写法。
3. 变异验证一轮：删掉比对（恒视为匹配）→ 测试红；cp 备份 + sha256 还原。

## 纪律（写死，违反即返工）

- **只跑子集**：`pytest tests/test_020_parse_drops.py tests/test_bridge_cli.py tests/test_bridge.py tests/test_019_empty_board_hint.py tests/test_018_cli_review.py tests/test_review_eval.py -q --basetemp=.tmp_pt_020`；**禁止全量 pytest 循环**（全量三线 Kimi 复验跑）。connector 侧若未动不用跑 npm。
- 不动 git（commit/push 归 Kimi，岳已批准）；不动 `tests/fixtures/` 既有文件（llc 只读）；
  不动 `outputs/011e*|014_*|015b_*|016_*`；新证据写 `outputs/020_*`。
- 工作目录 `E:\boardwise`，Python 用 `.venv/Scripts/python.exe`。
- 关键行号都给了，但**先读代码再动手**——行号可能漂移，以代码为准。
- 完成报告：两个 WI 各自的改动文件+行号、文案定稿、子集测试结果、变异验证（含 sha256）、
  WI-1 的 view 覆盖范围说明。

## 验收（Kimi 复验）

- 子集绿 + 双变异 CAUGHT + 全量三线绿；
- WI-1 真机/离线：llc fixture review 出 note，毕设板 fixture 不出 note（其丢脚计数应为 0——若不是 0，如实记录）；
- WI-2 真机：`update-connector --yes` 推当前 0.4.11 bundle → 应自动打印 verified（编辑器开着时）。

---

## 交卷记录（2026-09-22，commandcode/deepseek-v4.1-flash 子代理）

两个 WI 串行做完，均离线实现 + 单测 + 变异验证。证据：`outputs/020_wi1_parse_drops.txt`、
`outputs/020_wi2_update_connector_verify.txt`。

### WI-1 解析器静默丢脚可观测化

- 改动文件：`src/boardwise/core/geometry.py`（ParseStats 加 `pins_dropped_no_number` /
  `components_without_symbol`，`as_dict()` 同步）、`src/boardwise/parsers/schematic.py`
  （`_collect_symbols(records, parse_stats=None)` 在 flush 里计无名号脚；`_stats_for()` 私有
  helper；`build_pin_offsets` / `build_schematic_model` 加 `parse_stats=` 关键字并在三处
  `symbol_def is None` 计数）、`src/boardwise/rules/i18n.py`（`parse_drop_hint()`）、
  `src/boardwise/cli.py`（`PARSE_DROP_NOTE_TAIL`、`_parse_drop_note()`、`_load_model(parse_stats=)`、
  `_chinese_summary(parse_drop_hint=)`、`_cmd_review` 接线）。
- 文案按任务书定稿：控制台 `note: 14 pin(s) dropped during parse (missing pin number) — review
  coverage is incomplete`（0 的项不出现）；`--md` 中文 `提示：解析中有14 个引脚因缺少引脚号被丢弃
  ——审查覆盖不完整，结果可能漏报。`
- **解析结果逐字节不变**：拿 HEAD 版源代码并排 import（`git show`，只读），7 份夹具 ×
  `build_schematic_model` + `build_pin_offsets` 全部 `dataclass ==` 且规范化 digest 相同 →
  IDENTICAL。
- 新增测试 `tests/test_020_parse_drops.py`（12 条，含 llc 真样本、ch340 反例、合成缺 Pin Number 与
  缺 symbol 两例、`--json` 字节不变两条、pcb 视图边界两条）。
- **实测与预期不一致（如实报）**：llc 丢脚实测 **14**（任务书写 7）——该晶体管阵列 SYMBOL 文档在
  文件里出现两次（uuid `68f4d86f5f182974` / `510729142f8ef815`），每份 7 个有名无名号脚，7×2=14。
  断言按任务书写 `>= 1`，另附 `== 14`。`components_without_symbol` 在全部 7 份夹具上均为 0。
- **view 覆盖范围**：只有 `--view schematic` 会填这两个计数并出 note。pcb 视图（缺省）的模型来自
  PCB 文档、不读 SYMBOL 文档，计数"恒 0"是结构决定的，故不填、也不渲染（同一份 llc：schematic 报
  14，pcb 一个字不说）。毕设板 schematic 视图：121 器件 / 丢脚 0 / 丢符号 0 → 无 note（符合验收）。

### WI-2 update-connector 自动版本回读

- 改动文件：`src/boardwise/cli.py`（三个计时常量 `UPDATE_VERIFY_INTERVAL_S=1.0` /
  `UPDATE_VERIFY_BUDGET_S=30.0` / `UPDATE_RELOAD_MARGIN_S=0.5`、`_running_connector_version()`、
  `_await_running_connector_version()`、`_cmd_bridge_update_connector` 的回读三分支、`--no-verify`
  参数）、`docs/bridge.md`（子命令表 exit `0/1/2/3`、§8 追加一段、操作员段落改写）、
  `tests/test_bridge_cli.py`（mock 升级 + 原契约用例改写 + 新增 5 条）。
- 契约：匹配 → `verified: running connector is now X.Y.Z` exit 0；重连但版本不同 → exit 1
  （假成功实锤）；30s 内没回来 → exit 3（状态不可陈述）；`--no-verify` → 旧输出 + exit 0。
- 关键次序：**先睡过回复自带的 `reloadInMs`（+0.5s 余量）再读**——否则读到的是将被替换的旧 build，
  会把好更新报成失败。有专门的真时钟顺序测试钉住。
- 比对基准 = `params["version"]`（`connector/extension.json`），与 doctor 同一判据。
- 未做真机（按纪律未对编辑器做任何写操作），留给 Kimi 复验。

### 变异验证（3 轮，均 CAUGHT，cp 备份 + sha256 逐字节复原）

| 变异 | 靶点 | 结果 | 还原 sha256 |
|---|---|---|---|
| A | `schematic.py` `elif parse_stats is not None:` → `is None:` | 5 failed / 7 passed（test_020） | `324f1cc2…` == 基线 |
| B | `cli.py` `if running != expected:` → `if False:` | 1 failed（mismatch 用例，assert 0 == 1） | `ed45f757…` == 基线 |
| C | `cli.py` `if drop_note:` → `if False:` | 4 failed / 19 passed（test_020 + test_019） | `ed45f757…` == 基线 |

### 子集测试

`pytest tests/test_020_parse_drops.py tests/test_bridge_cli.py tests/test_bridge.py
tests/test_019_empty_board_hint.py tests/test_018_cli_review.py tests/test_review_eval.py
-q --basetemp=.tmp_pt_020` → **163 passed, 13.22s**。另补跑改动触及符号的既有文件
（013_symbol_fallback / epru_parser / epro2_model / 016_edit_cli / board_source）→ 148 passed。
全量三线归 Kimi 复验。

### 过程事故（如实报）

第一轮变异 A 的 `cp` 备份放在 `.tmp_pt_020/`（= `--basetemp` 目录），那之后的 pytest 运行按惯例
**清空了 basetemp**，备份随之丢失而源码仍停在变异态；按先记下的变异前 sha256（`324f1cc2…`）
用 Edit 逐字复原并核对哈希一致。后续备份改放 `.tmp_020work/`（同样 gitignore，但 pytest 不碰）。
结论未受影响，但这是一次真实失误，记此备查。

**勘误补充（同日收尾）**：上表 B/C 两行的"还原 sha256 = ed45f757…"是当时 cli.py 的版本；此后 cli.py
只做了一处纯改名（`_chinese_summary` 生成器变量 `hint` → `paragraph`，不触及行为）。为让变异验证
落在交付字节上，B、C 已在最终版 `src/boardwise/cli.py`（sha256 `22f5773b…`）上重跑，结果同样
CAUGHT（B：`-k update_connector` 1 failed / 10 passed；C：test_020 + test_019 4 failed / 19 passed），
cp 复原后哈希逐字节一致。交付版各文件 sha256 与全部原始输出见 `outputs/020_wi1_parse_drops.txt`
末节与 `outputs/020_wi2_update_connector_verify.txt` 末节。
