# 201H — 反激岛页 T1 值行按 S-21 隐藏（真实 `valueVisible=false`）

- 批次：201H（201G 接缝调查的落实批）
- HEAD：`5287b38`
- 生产文件域：`src/boardwise/engines/islandlayout.py`（唯一）
- 测试文件域：`tests/test_532_part_visibility.py`、`test_531_text_ruler.py`、`test_530c_island_routing.py`、`test_530f_gate_tolerance.py`、`test_530g_title_block_keepout.py`、`test_551a_failure_rounds.py`、`test_145a_walls.py`、`test_single_module_pin_text_gate.py`（仅在真实失败后按独立真值窄改）；全量补充锚：`test_530e_islands_propose_apply.py`、`test_530d_component_names.py`、`test_119_pose_ladder_widening.py`（同上，只改旧读数锚）
- 证据：`evidence/201h/`、`.tmp_201h/`

## 用户裁定（2026-10-26）

按 S-21「值应隐藏」处理 T1 的值行：**隐藏 T1 值、保留位号**，走真实
`valueVisible=false`，**不做模型假绿**（不在模型里把盒子挪到外侧而宿主照旧打印）。
理由：值行由符号库声明的 text item 决定（`core/textmetrics.symbol_rows` 读
`SymbolProfile.texts`，宿主不随 pose 转行），T1 的 `value` 锚点 `(-20,-30)`、行宽
50.27、高 10，顶边 y=-20 正好压在 pin2/pin5 的轴上，与自身 `pinName[2]`（重叠
4.91）、`pinName[5]`（4.91）、`pinNumber[5]`（0.91）三重相压；这是符号自带排版，
任何摆位都分不开，落在 `pin-text-press` 类（HEAD 严格 readability 恰 3 条）。

## 目标（验收）

1. `dc.compile(...)` `ok=True` 保持。
2. 严格 `readability.check`：`pin-text-press` **3 → 0**（且 `ok=True`）。
3. 交付闸 `tolerated: ` 行 **3 → 0**。
4. plan 的 `value` 行 **19 → 18**；T1 的 `value_visible is False`，
   `EE16_3+3_V02` 不再出现在 plan `texts` 与 SVG 中；其余 18 个 value 仍可见。
5. `parts` / `wires` / `flags` / 连通数据与保存基线一致（允许 `evidence`/`notes`
   与 T1 value 文本变化）。
6. T1 的隐藏 note 写明真实原因（自身 pin 名/号压在同一位置、S-21 第一出路）。

## 非目标

- 不改 gate / 容忍额度（`ISLAND_GATE_TOLERATED_LIMITS` 的 `pin-text-press: 3` 保留，
  不删不放宽）；不改 `readability`、router、grammar、连通。
- 不动 shared / CLI / bridge / 其他器件几何。
- 不按 `T1` 位号硬编码；判据必须是通用几何 + 既有 `value_may_be_hidden` 分类。
- R/C/L/IC 的值**永不隐藏**（`VALUE_ALWAYS_PRINTED`），reference 永不隐藏。
- 实施代理不跑全量测试；全量由主代理在交卷前跑**两次**（读数见文末「最终状态」）。
  全程不跑真机 / bridge / 网络，不做 git 写。
- 未上真机，**不声称画布已验**。

## 真机收尾授权（2026-10-26，用户后续明确授权）

上述「全程不跑真机」仅是原实施代理的范围。用户在后续收尾请求中明确授权：先把唯一
在线窗口的 connector 热更新到本机同版 `0.5.22`，再且仅在 **`/test`** 工程
（UUID `ea80fff642fa86cdc95882ab0201b0bb7ee6d966412a8958fec3ff95fa13f489`）的
**`schematic1`**（UUID `d977b19a89c0abb7`）新建 **`201H_VISIBILITY`** 页，写入并
保存 201H 候选；不得改动既有 3 个原理图页，不得触碰其他工程。

落图前以 `doc.list + sys.identity` 逐字复核工程、页和 UUID；写动作使用新页返回的
`pageUuid`。验收至少包括：T1 的真实 `valueVisible=false` 回读、位号仍显示、
`draw lint`、宿主 `export.render` 和连通回验；保存回执按宿主能力如实分级，不把
`saved_unverified` 写成持久化已验。命令与读数补入 `evidence/201h/` 后再交卷。

## 实现要点（在既有路径内）

`_clear_text_rows`（`islandlayout.py:1511`）已返回 `hidden_values` 并驱动
`_add_texts` → `_hide_value_row` → `LayoutPart.value_visible`。它目前只看
`foreign(part_id)`（别家 body/行），**不看自身 pin 行**。本批在同一决策点用
`textmetrics.pin_rows` 的真实盒子补上「value 与自身 `pinName`/`pinNumber` 相压」：

- 仅当 `kind == "value"` 且 `value_may_be_hidden(...)[0] is True` 才隐藏；
- R/C/L/IC（`VALUE_ALWAYS_PRINTED`）与 reference 一律不隐藏，行为不变；
- 路由用的 `part_rows`（`islandlayout.py:2884`）保持原样，故布线/几何不受影响；
- 保留 `readability` 的 `pin-text-press` 检测覆盖（不改检查端）。

## 基线（201G-current，HEAD 5287b38，budget 64）

| 产物 | sha256 |
| --- | --- |
| `.tmp_draw_201g_current/out/cand1.svg` | `91a81a6ccc8af637fb44b564808e729151409a0d3bbe56f4758058545f7eefe3`（31,318 B） |
| `.tmp_draw_201g_current/out/cand1.layout.json` | `76c2996116eee0e3284602e1421980e37060f74c139dae7f21521cfbd5a4240e`（56,990 B） |
| geometrySha256 | `d0db762bfd4819e5b9ae4b175356121ad65a682814731aeb9155e0b239139dda` |

- 读数：`ok=True candidates=1 rejected=0 failures=0 rounds=0`；容忍 3 条
  `pin-text-press`；严格 readability `ok=False hard=3`，全为 `texts[33]
  'EE16_3+3_V02'` × `parts[T1].pinName[2]/pinName[5]/pinNumber[5]`。
- 输入夹具 sha256（circuit/presentation/library）见
  `.tmp_draw_201g_current/summary.md`。

## TDD

1. 先在 `tests/test_532_part_visibility.py` 加精确回归（真实反激编译 + 严格闸），
   跑出预期红（`value_visible is True`、`pin-text-press` 仍 3、`EE16_3+3_V02` 仍在）。
2. 再改 `islandlayout.py`，跑聚焦命令转绿。
3. 历史测试中「3 条 / 全值打印」的锚按独立几何与 S-21 更新；`cap=3` 不删不放宽；
   仅旧读数记录的测试不乱改；`test_551a_failure_rounds.py` 等只有真实失败且确属
   本批才改。

聚焦命令：

```bash
.venv/Scripts/python.exe -m pytest tests/test_532_part_visibility.py tests/test_531_text_ruler.py \
  tests/test_530c_island_routing.py tests/test_530f_gate_tolerance.py \
  tests/test_530g_title_block_keepout.py tests/test_551a_failure_rounds.py \
  tests/test_145a_walls.py tests/test_single_module_pin_text_gate.py -q --basetemp=.tmp_pt_201h
```

## 全量补充锚（首次全量，2026-10-26）

首次全量 `9 failed / 8276 passed / 21 skipped`：除 **5 个非绘制既有失败**外，其余
**4 个恰为本批预期行为的旧读数锚**，只在真实失败后按独立真值窄改（生产源码不动）：

| 测试 | 旧锚 | 新读数 |
| --- | --- | --- |
| `test_530e_islands_propose_apply.py::test_the_declared_island_page_compiles_to_the_same_geometry_as_before` | `e165aede…` | `565ab76d…`（与 530G 同一 digest；仅 T1 `valueVisible` + 少 `EE16_3+3_V02` 一行，非 layout 位移） |
| `test_530d_component_names.py`（names/blobs digest + `test_the_page_the_gate_reads_has_only_the_transformer_s_own_pin_text`） | `e165aede…`；严格 hard=3 | `565ab76d…`；严格 hard=∅（530C/531/532 历史保留，闸测试不删） |
| `test_119_pose_ladder_widening.py::test_the_real_flyback_widens_and_still_refuses_honestly` | 岛路 tolerated=3 | tolerated=0（cap 与加宽历史未动） |

补充聚焦命令：

```bash
.venv/Scripts/python.exe -m pytest tests/test_530e_islands_propose_apply.py \
  tests/test_530d_component_names.py tests/test_119_pose_ladder_widening.py \
  -q --basetemp=.tmp_pt_201h_anchors
```

## 交付

**201H 单点目标已完成（离线）**：T1 值行按 S-21 隐藏、`valueVisible=false`、交付闸
tolerated 3→0、严格 readability `ok=True hard=0`、value 行 19→18，其他几何逐节字节相同。
整页可读性（U4、输出岛、密度、`min_text_gap=0`）**未通过**，留后续批次另立任务。

- `evidence/201h/`：`summary.md`（读数与边界）、`after_summary.json`（before/after 机器
  可比摘要）、`cand1.svg` / `cand1.layout.json` / `cand1.png`（视觉自审用图）。

## 原实施复验（2026-10-26，历史读数）

- **聚焦**：8 锚文件 + `test_540_cli_draw` + owner + `test_dsh_plugin_sync` → `132 passed in
  208.64s`；补充锚 530e/530d/119 → `70 passed / 2 skipped`。
- **全量两次**：第一次 `9 failed / 8276 passed / 21 skipped`（其中 4 个为本批旧锚，已窄改）；
  第二次也是最后一次 `5 failed / 8280 passed / 21 skipped in 678.21s`，5 个仅为既有失败
  （4 个 manifest hash + 1 个 `test_133c` 测量域），**非本批新增，仓库不是全绿**。
- **变异两次**（`cp` 恢复）：①撤 own-pin 证据 → T1 隐藏回归 1 红；②去 `value_may_be_hidden`
  类别闸 → 电阻反例 1 红；恢复后源码 SHA256 =
  `ba789c7178d82a7a33df44f0e9100c1038053b676994668ea3023cf3a0e1ed09`，3 条关键测试 passed。
- **DSH** `127 passed / 1 skipped` + typecheck + build + `smoke:draw`（3 candidates / 6
  artifacts、8 pages / 16 artifacts、lint replay exit 0）；**connector** `536 passed` + typecheck。
- **Rust 未重跑**（本批无 Rust 改动；此前环境把 `link.exe` 解析为 `/usr/bin/link.exe`
  导致 clippy 链接失败）——**不声称 Rust 全绿**。
- **视觉**：主代理与独立视觉代理都看了 `evidence/201h/cand1.png`——`EE16_3+3_V02` 确实消失，
  其他岛无视觉移动；T1 引脚文字只能说不**再被压**，不能说清晰。U4 / 输出岛 / 整页密度与
  `min_text_gap=0` 未解决，**用户人工视觉锚未关闭**。
- **真机画布未验**：`valueVisible=false` 的落盘写未跑。

## 收尾最终状态（2026-10-26，对抗 + 真机尝试后）

- **对抗审查**：独立代理发现 90/270° pin 行可造成错误隐藏（201H-a）、粗盒 note
  假称闸必拒（201H-b）及 hidden-row foreign 覆盖缺口（F3）。均已修复并补锚；主代理
  关键复验 `6 passed`，当前反激 geometrySha256 与修复前相同，仅 notes 改动。
- **最终全量**：`8291 passed / 19 skipped / 0 failed in 695.01s`；原 5 个非绘制失败
  已在审查线修复并归零。上方 9 红/5 红是历史读数，不是当前树状态。
- **Rust**：经既有官方载荷的本地 wrapper，`fmt --check`、零警告 clippy、cargo test
  通过，**45 passed / 4 ignored**；ignored 未冒充已跑。
- **真机已尝试、未验收**：环境 doctor 9/9，connector 0.5.22；仅操作授权的 `/test` 新页
  `e765335b3b9516a1`（宿主实际名 P2）。三次 apply 均在 T1 的
  `sch_PrimitiveComponent.create` 30 s 超时停止；T1 第一件亦失败，证明与第 16 次调用无关。
  两次 15 件半成品均经用户授权逐件核对清理，最终新页只剩图幅，既有三页未改。
  **未进入 valueVisible 写入、lint、render 或保存，不得声称真机通过。** 完整证据见
  `evidence/201h/live/summary.md` 与同目录 apply/cleanup JSON。
- **用户裁决**：先提交审查线与独立文档，**201H 全部生产/测试/任务书改动暂缓提交**。
  后续只有在 T1 能由宿主实际放置后，才可继续 valueVisible 真机验收并另提绘制线。

## drawing-line worktree 续验（2026-10-26）

- 用户授权创建 `E:\boardwise-wt-draw` / `drawing-line`（基点 `b8705c6`）。201H 的
  10 个已跟踪改动与任务书经 patch 逐字节比对一致；主工作区不清理、不 restore。
  新 worktree 以自身 `src` 导入，聚焦 **203 passed / 5 skipped**。
- 库 `lib.device.get` / `lib.symbol.get` / `lib.footprint.get` 均找到目标及关联 UUID。
  经用户再次授权，在既有空白页 `e765335b3b9516a1` 做一次 60 s T1 单件探针；
  首次仍超时且无即时落件。随后用户说明：调用触发器件更新提示导致等待，用户完成更新后
  宿主自动摆放成功。回读确认晚到件 `62bd8dcb2e5063be`，位置 (435,280)，6 脚与 plan
  一致，**不得再放第二颗**；位号仍为 `T?`，命名步骤未随超时完成。
- 经授权执行 `sch.doc.save`（回 `saved:true`）后，`Name` / `Designator` / `Value`
  ATTR 的 `value` 仍为 null，`partvisibility.valueRows` 为空，未猜写整页源。
  用户选择手动把该件改为 `T1`；当前回读仍为 `T?`，手动命名尚待完成。
- 后续只在 Designator ATTR 可寻址、组件身份与 6 脚复核一致时继续：写
  `EE16_3+3_V02`、按 `partvisibility` 设置并回读 `valueVisible=false`、保存并渲染。
  任一步失败均停止，不重试、不删除。**当前仍未执行真实 valueVisible 写入，201H 不提交。**
- worktree 的移除、绘制提交、合并与 push 均需另外授权；旧 `E:\boardwise-wt520` 不碰。

## drawing-line 暂停记录（2026-10-27）

- 守护脚本经真实 pins 应答与 fake Channel 演练后为 **28/28**：大写 `X/Y/PinNumber`、
  唯一坐标模型、三次读源的 uuid/type/truncated 闸门均由主代理独立复跑确认；这些仍不是
  真机可见性验收。详细证据：`evidence/201h/live/worktree-progress.md`。
- worktree 自有 Rust 线为 **45 passed / 4 ignored**，fmt/clippy/build 通过；最终 Python
  全量为 **8213 passed / 97 skipped / 0 failed**。首轮三处 manifest 红是 CRLF/LF 字节差异，
  已撤回 CRLF manifest，只在本地恢复与 HEAD 相同的 LF 源字节后复验；三份源的 Git blob
  与 HEAD 相同，未产生 fixture 内容 diff。97 条 skip 由最终 `-rs` 逐项记录，主要是新
  worktree 不含未入库 outputs/私有证据；connector/dsh-plugin 依赖未安装，不声称四线全验。
- 2026-10-26 23:53 最新回读位号仍为 `T?`，用户选择 **暂不执行 live**。因此未执行守护
  脚本的 Value/可见性写入、保存或渲染，未执行完整 apply，也未生成真机验收图。
  **201H 仍未提交；没有合并、push 或 worktree 移除。** 恢复须等用户明确继续，提交另需授权。

## drawing-line 离线补验（goal round 2，2026-10-27）

- 在不改变「暂不执行 live」边界的前提下补齐 Node 线：connector **536 passed / 0 failed**、
  typecheck 通过；dsh-plugin typecheck/build 通过，Vitest **127 passed / 1 skipped**。
  原缺依赖/产物相关的 Python 检查聚焦复跑 **20 passed**。Rust 与 Python 全量沿用上节
  本 worktree 读数，未跑第三轮全量。
- dsh-plugin 旧锁会解析到冲突的 DSH 0.0.1 树，因此以主目录已验证的明确版本、
  `--no-save --package-lock=false` 安装；未改 package.json/lock，未用 force/legacy。
  `npm ls` 在主目录和本 worktree 都把同一 `dsh-tools@0.2.1-rc.1` 标为 invalid，
  属既有 peer 范围问题；安装另报 15 个依赖漏洞（2 moderate / 13 high），未擅自修复。
- 18 个 tracked `dsh-plugin/lib` 生成物与 HEAD blob 全部一致，未留下构建内容 diff。
  详细命令与边界见 `evidence/201h/live/worktree-progress.md` §七。**live 与提交仍未执行。**

## drawing-line 阻塞复核（goal round 3，2026-10-27）

- 只读复核工程/页身份仍全部匹配，但目标件 `62bd8dcb2e5063be` 仍位于 `(435,280)`、
  位号仍为 **`T?`**；未执行任何设计写入。手动 T1 与新的 live 授权连续第三轮均未出现，
  目标按规则标记 blocked。恢复时先重新读取 T1 与 Designator ATTR，再另行授权 live；
  绘制提交仍需单独授权，不 push。

## T1 真机验收落地（2026-10-27）

- 用户明确恢复 live 后，宿主回读已为 T1。守护脚本离线 28/28、身份/六脚/ATTR/Value
  检查均过，但 `sys.set_document_source` 即时回读为 differs，脚本 exit 2 停止；
  **不得称脚本通过**，也未重试写回。失败凭据：`evidence/201h/live/t1-guard-run-result.json`。
- 独立当前源回读证明 `Name.valueVisible=false`、`Designator='T1'` 且 ref 可见、
  `Value='EE16_3+3_V02'`；随后 PNG/SVG 渲染成功，主代理看图确认值行隐藏、T1 清楚、
  六脚编号无重叠。证据：`t1-after-set-differs-analysis.json`、`t1-current.png`、
  `t1-current-render.json`。
- 按原授权补一次 `sch.doc.save`，返回 `saved:true`，记 **saved_unverified**。保存后源仍
  `valueRowVisible=false`；保存前后仅 DOCHEAD `client/updateTime/version` 变化。
  详见 `t1-after-final-save-analysis.json` 与 `t1-save-source-diff.json`。
- 因此 201H 本步的 **T1 真机值可见性与视觉验收已落地**；完整 201H apply、整页连通/lint、
  关闭重开后的 saved_verified 不在本步，仍未做。201H 仍未提交，提交需单独授权，不 push。
