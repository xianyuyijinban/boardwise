# 080：issue 清仓批（#47 / #36 / #38 / #40 / #41 / #45 / #46 / #35 / #37 / #39 / #43）

2026-09-30 主代理立。15 个 issue 分诊完毕（分诊评论在 GitHub 各 issue 上），四个待裁点岳已拍板
（裁定原文在 #34/#38/#41/#43 的跟进评论）。本任务书是批 0–5 的执行契约；
#32 进 078 解码器批、#34 进 079 提取器批，不在本批。

## 总纪律

- 子代理：**只改代码与测试，不碰 git**（add/commit/push 一律禁止），不写 PROGRESS.md。
- 交付 = 工作树改动 + 自测输出。主代理亲复验（pytest 全量、diff 抽查、变异抽验）后才提交。
- pytest 必带 `--basetemp=.tmp_pt_home`：`.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home`
- connector/ 或 dsh-plugin/ 的树若没动，不跑它们的测试线；动了才跑（本批预期都不动）。
- 不碰 `tests/fixtures/` 既有夹具、`outputs/011e*` / `014_*` / `015b_*` / `016_*`。
- 真机一律不动（本批全是离线修复，不需要 daemon/editor）。
- append 落盘后立即 `grep -c` 防双执行。
- 行号以 5af63c3 为准，定位按内容不按行号（前面批次落地会挪行）。

## 批 0（插队）：#47 replay 的 y 取反残留

- 根因：`src/boardwise/engines/replay.py` 的 `plan.geometry` 构造（5af63c3 时 :488）
  `y=-placed[designator].y + dy`——010c 坐标系翻转时漏删的取反，与同函数 :465
  （`y=part.y + dy`）和 :501（`part.y + dy + oy`）不一致。
- 修法：去掉负号，`y=placed[designator].y + dy`。
- `Placement.x/y` 当前零消费者，属死字段契约修复；若有测试钉着取反行为，一并翻转并
  在交卷里点名。没有就加一条断言 geometry.y 与 part.y 同向的回归测试（小）。

## 批 1：#36 + #38（shipped 命令默认跑不通族）

### #36 validate --root 默认值

- 根因：`src/boardwise/cli.py` validate 子命令 `"--root", default="."`（5af63c3 时 :1910），
  而 spec 的声明输入相对 **spec 文件所在目录** 解析。shipped 的
  `blocklib/specs/ams1117_smoke.json` 在非仓库根 cwd 下被误判。
- 修法：`--root` 默认 None，缺省回落 `Path(args.spec).resolve().parent`。先例就是同文件
  draw 命令（:6135-6141，注释 :6138-6139），照抄其写法与注释风格。
- 验收：`cd` 到非仓库根目录跑 `boardwise validate --spec <仓库>/blocklib/specs/ams1117_smoke.json`
  不再因路径误判失败；显式 `--root` 行为不变。加 CLI 级回归测试（tmp cwd 调 validate）。

### #38 harvest 源清单落成仓库文件（岳裁定：单一来源）

- 新增 `blocklib/harvest.sources.json`：纯路径数组（仓库相对路径字符串），内容 =
  `tests/test_harvest.py` 现有 `HARVEST_SOURCES`（:55-74，6 源：PILLBOX / THESIS / HIGHS /
  ROBOT / PILLBOX_EPRO2 / THESIS_EPRO2）的仓库相对路径。
- `tools/harvest_parts.py`：`--sources` 缺省时读该 JSON（当前 :475-476 是
  `--sources is required (unless --rehome is given)`）。显式 `--sources` 行为不变；
  `--rehome` 路径不变。JSON 缺失/畸形时报错信息要点名文件。
- `tests/test_harvest.py`：`HARVEST_SOURCES` 改为从该 JSON 读（单一来源，不再各写一份）。
- 文档对齐：`docs/parts.md` :185-188 的命令示例改为缺省读 JSON 的用法，并把分诊实测的
  错误数字改对（issue #38：shipped 态实际缺约 57 颗、碎片只 C369933 一个；以你实跑
  `--check` 的输出为准写文档，不许照抄本任务书数字）。
- 验收：仓库根跑 `python tools/harvest_parts.py --check`（不带 --sources）exit 0；
  带 glob 的旧用法行为不变。

## 批 2：#40 + #41（承诺 vs 实现族）

### #40 install-skill .bak 同日覆盖

- 根因：`src/boardwise/skill_install.py`（约 :283-286）备份名 `.bak-<日期>` 粒度是日，
  同日第二次安装静默覆盖第一次的备份。
- 修法：备份名带时分秒 `.bak-<YYYYMMDD-HHMMSS>`（与 config.toml 备份纪律同形），
  永不覆盖既有备份。四处文案同步：`skill_install.py` 自身、`cli.py` 约 :1154 / :18971 /
  :19524（以内容定位：凡是向用户描述 .bak 命名的地方）。
- 加测试：同日连续两次安装 → 两个备份文件都在。

### #41 红线放宽（岳裁定：推翻 047 旧决策，红线优先）

- 根因：`check_repo_hygiene`（在 `src/boardwise/` 内，以 R4 红线内容定位）只认
  `.epro2/.eprj2` 等扩展名紧跟分隔符；`foo.eprj2.bak / .orig / .backup / .old / .txt`
  全逃逸且未被 .gitignore。
- 修法（裁定原文）：放宽匹配为 `\.(ext)(?:\.[^/]*)?(/|$)`——抓派生后缀，
  仍不碰 `docs/esch2-format-notes.md`、`notes/epro2.md` 这类「名字里带扩展名字样」的文档。
- **必须翻转 047 钉死的测试**：`tests/test_repo_hygiene.py:79-92` 把「.bak 不算」翻成
  「.bak 算红线」。这是显式主张「红线优先于防误报」，测试 docstring/注释里写明 047→080
  的决策变更，一句话即可。
- 验收：构造 `bar.epro2.bak` / `bar.epro2.txt` 被判红线；上述两个 docs 文件仍放行；
  `git ls-files` 现状零命中（跑一次贴进交卷）。

## 批 3：#45 + #46（歧义只堵一个方向族）

### #45 assemble 共享 port 静默覆盖

- 根因：`src/boardwise/engines/assemble.py`（约 :266-273）两条 connection 归并同一
  cluster 时 `named[root]` 以后者静默覆盖，一网两名无检查；反向错误（clashes）却有严格拒绝。
- 修法：照 clashes 的姿态硬拒绝——检测到同 cluster 异名即抛 BlockError，消息列出冲突双方
  （两个网名 + 涉及的 connection）。
- 加测试：一网两名 → 明确报错且点名双方；正常合并不受影响。

### #46 重命名两实现碰撞行为对齐

- 根因：`src/boardwise/engines/compare.py`（约 :393-400，`reconcile_names`）碰撞时 merge
  两张网；`src/boardwise/engines/draw.py`（约 :641，`_reconcile_derived_names`）覆盖丢弃。
- 修法（本批只做行为对齐）：两实现都改成「目标名已被占即放弃该次重命名并记录（warning/
  skipped 记录），不 merge 不覆盖」。两份实现收敛为一份留后续批次，本批不许顺手重构。
- 加测试：同一碰撞输入打两个入口，行为逐字一致。

## 批 4：#35 / #37 / #39 小批

### #35 pintable gate 3 引脚级比对

- 根因：`src/boardwise/engines/pintable_check.py` gate 3 方向 1（约 :276）
  `spec_nets = {connection.net ...}` 只比网名；网在 spec 里就计 matched，从不看 MCU 上是哪颗球。
- 修法（issue 建议可直接实施）：网命中时取该网在 MCU block 上的端口 role 集合，与 firmware
  在该网上的引脚号集合比对；不相交 ⇒ 按「firmware 用的引脚原理图没接」报 defect。
  `matched_nets` 只在引脚集合也一致时 +1。方向 2（约 :308-319）同样补引脚级口径。
  role 与 pin.number 同为引脚名，无需额外数据。
- 加测试：issue 复现形（spec PA3→SPI1_SCK vs firmware PB6→SPI1_SCK）必须 defect；
  一致形仍 OK。

### #37 blocks.py 三处裸 AttributeError

- 根因：`src/boardwise/core/blocks.py` 约 :559 / :563 / :653 三处 `(x or {}).items()`，
  x 为非空 list 时裸 AttributeError，绕过 BlockError「点名字段」契约（#28 同族第三处）。
- 修法：照抄同文件 :632-634 的 isinstance 模式（非 dict 即 BlockError 并点名字段）。
- 加测试：offsets / pin_names / params 写成非空 list → BlockError 且消息点名字段。

### #39 bom 裸字符串比值假冲突

- 根因：bom export 对同一 C 号的两个写法（100nF vs 0.1uF，或仅大小写不同）判冲突，
  清 Comment、ok=False、exit 1。
- 修法：比值前走既有值解析器归一化；相等判定必须 `math.isclose(rel_tol=1e-9)`
  （100nF 解析为 1.0000000000000001e-07，等值判等会引入新假冲突）。解析失败的值回退
  现状行为（字符串比对），不许 UNKNOWN 静默放行。
- 验收：shipped spec 两值本就相等，修复后开箱不炸（跑一遍 shipped bom 流程贴输出）；
  加测试 100nF vs 0.1uF 不冲突、100nF vs 220nF 仍冲突。

## 批 5：#43 connector 断连在途写入的错误码（岳裁定：复用 DISCONNECTED）

- 根因：`src/boardwise/bridge/daemon.py` 约 :1510-1514 断连路径抛
  `ErrorCodes.CONNECTOR_ERROR`，而 `src/boardwise/engines/draw.py` 约 :307-320 的未知态
  判定只认 TIMEOUT/DISCONNECTED → 在途写入遇断连被误报 not_placed（M0-P0d 漏了
  connector 这一半，有一页两套器件的真机事故前科）。
- 修法（裁定原文）：`daemon.py:1513` 的 `ErrorCodes.CONNECTOR_ERROR` →
  `ErrorCodes.DISCONNECTED`，消息保留 "connector disconnected while the call was in
  flight"；`daemon.py:1432` 保持 CONNECTOR_ERROR（那是 connector 自己回的错误，
  结局已知=没做）。DISCONNECTED docstring 里 "raised by the client, never by the daemon"
  一句是描述性的，改掉（说明 daemon 在等答案期间窗口消失时也抛它）。
- 加测试：模拟 connector 断连在途写入 → draw 判 unknown_writes 并触发回读路径，
  不报 not_placed；:1432 路径仍 CONNECTOR_ERROR。

## 交卷格式（每批）

1. 改动文件清单 + 每处一句话。
2. 新增/翻转测试清单 + pytest 全量输出末尾 5 行（必带 --basetemp）。
3. 本批验收点逐条过一遍（贴命令与输出）。
4. 已知残留/超纲发现（有就列，没有写无）。
