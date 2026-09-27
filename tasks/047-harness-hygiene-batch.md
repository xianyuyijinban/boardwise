# 047 任务书：harness 卫生批（四件独立小修）

> 2026-09-27 立。执行者：commandcode/deepseek-v4.1-flash 子代理。
> 四件互不相干，各带实现 + 测试 + 变异验证；**不碰 git / 真机 / bridge / connector /
> reviewsets/*.json / `src/boardwise/rules/` 目录**。
> 定向跑测试：`.venv/Scripts/python.exe -m pytest tests/<文件> -q --basetemp=.tmp_pt_047`
> （全量四线由主代理统一跑，子代理**不跑全量**）。

---

## F1 SCREW 类位号前缀缺口（`src/boardwise/engines/review.py`）

### 病根

`_DESIGNATOR_TOKEN`（`engines/review.py:190`）限 `[A-Za-z]{1,4}`，而毕设FOC板的安装孔
位号是 `SCREW1..4`（5 个字母）——正则根本匹配不到；即便匹配到，`:197` 的
`DESIGNATOR_PREFIXES` 白名单里也没有 `SCREW`。

后果：finding 文本提到 `SCREW1` 时 `finding_refs()` 提取不到，`review-mark` 画不到、
017 的定位成功率统计漏（实测 `conn-duplicate-designators` 定位 30/36，漏的 6 条含
`SCREW1..4`）。原文出处：`PROGRESS.md:163` 的 017 交卷行（"定位 64/80"）与 017 遗留清单。

### 修法

1. `:190` 正则 `{1,4}` → `{1,5}`；注释里 "`U1` yes, `PC14`/`3V3`/`FRC0805J471` no" 的
   说明**保持不变**（放宽的是字母个数，不是严格性——严格性从来由下游白名单把关）。
2. `:197` 白名单加 `"SCREW"`（安装孔/结构件，无货架类别，故进 extras 而非
   `DESIGNATOR_CATEGORIES`）；注释写明 5 字母放宽的理由（017 实测 SCREW）。
3. 周围注释补一句：字母个数放宽到 5 不引入新误报，因为形状匹配出来的候选仍要过白名单。

### 测试

- `finding_refs()` 对含 `SCREW1` 的 finding 文本提取出 `SCREW1`；
- 回归：`AMS1117` / `SS34` / `CH340G` / `FRC0805J471` 仍被白名单挡住
  （`tests/test_review_mark_cli.py:77-93` 已有这几条负例，逐条确认在 `{1,5}` 下仍然红
  得对——`FRC0805J471` 的后缀 `J`、`CH340G` 的后缀 `G` 都由 `(?![A-Za-z0-9_])` 挡下，
  前缀 `AMS`/`SS`/`FRC` 不在白名单，必须**逐条真跑**而不是推演）。

## F2 `review` 文件默认视图翻转 pcb → schematic（`src/boardwise/cli.py`）

### 病根与理由（017 实证）

`review` 对**文件**的默认视图是 pcb，而 pcb 视图读的是 PCB 文档里的**陈旧副本**：
SCH 记录改了值、PCB 文档没同步，pcb 视图就报出幻影 finding。schematic 视图才是设计
真相。4 处 `.epru` 原始记录实证（017）：

- FPC 屏 R24/R27：SCH `Value=5.1K`，pcb 视图读 `10k`；
- DCDC 板 `100NF`/`10UF`：位号以 SCH 为真；
- 毕设滤波采样：R3/R6 `330` 与 U1/U7/U8×3 实体值以 SCH 为真。

017 的 6 份第一版普查数字全因 pcb 视图作废（重出后 70 行四态 0 不符）。
会话口径：`PROGRESS.md:163`，评审记录 `outputs/017_*`。

### 改动点

1. `cli.py:1992` `view = args.view or "pcb"` → `"schematic"`；注释改写（文件默认
   schematic，`--view pcb` 仍显式可选）。`:1960` 的 `--live` 分支不动。
2. `cli.py:254-267` 的 `--view` argparse：注释与 help 重写——一句话讲清理由
   （schematic 是设计真相；pcb 视图在 SCH/PCB 文档不同步时读陈旧副本）。`--live`
   默认 schematic 不变。
3. `cli.py:1447-1451` `_load_model` docstring 里 "``pcb``（the default …）" 的说法改为
   由调用方决定（`review` 默认 schematic、`checkup` 走 `CHECKUP_VIEW`），避免文档与
   行为分家。
4. `cli.py:94-99` `EMPTY_PCB_VIEW_NOTE` 的注释：触发前提从"缺省 view 是 pcb"改为
   "读者**显式**要了 pcb 视图"。
5. `cli.py:1820` `_pcb_view_read_nothing` docstring 同改（`view == "pcb"` 现在是显式选择）。
6. `rules/i18n.py:60-66`（**在红名单目录里，只许改注释文案，不许动判定逻辑**）：
   `EMPTY_PCB_VIEW_HINT` 的常量本体与触发条件都不变；改的只是"为什么要有这句话"的
   注释——翻转后唯一残留触发路径是**显式 `--view pcb` 且 pcb 视图空**（典型：只画了
   原理图的导出被人手动点名 pcb 视图），此时那句"如果你要审查的是原理图，请加
   `--view schematic`"仍然是对的、仍然有用，所以**保留提示本身**，只把注释里的
   "缺省 view 是 pcb"改成"显式 pcb 视图"。
7. `engines/review_eval.py:784-786` docstring 的括注（"the PCB-netlist view that
   `boardwise review` defaults to"）改成新默认。
8. 影响面排查（调用 `review` 命令行/`_cmd_review` 且**不显式传 view** 的测试与文档）：
   逐个确认或修正，清单见交卷记录。

### 测试

- 不带 `--view` 对 `.epro2` 跑 review → 走 schematic（用 `tests/fixtures/ch340_golden.epro2`：
  pcb 视图 0 器件 0 网络，schematic 视图 17 器件 13 网络，落差被同一个文件钉住）；
- 显式 `--view pcb` 仍走 pcb（同一文件 → 0 器件 0 网络 + 019 的空读提示）。

## F3 `blocks.portmeta.json` 内嵌（`cli.py` + `resources.py` + `packaging/boardwise.spec`）

### 病根

`cli.py:1010`（draw）与 `:1341`（validate）的 `--port-meta` 默认值是 cwd 相对路径
`blocklib/blocks.portmeta.json`——冻结 exe 在干净目录运行时找不到文件。045b 已修过
`parts.json` 的同一缺陷，当时把 portmeta 留作排期（`PROGRESS.md:155` 末句、
`outputs/045b_blocklib_embed.txt` §七）。

与货架不同，这个缺口是 **fail-closed** 的（045b §七实测：空目录跑 validate → 6
undecidable、"this is *not* a pass"、exit 1），所以当时没并进 045b。但它同样让 exe 在
朋友目录里**丧失一项能力**，本批照 045b 先例补齐。两个命令都是**读取**
（`Path(args.port_meta).is_file()` → `load_port_meta`），不存在 045b 给写入类命令保留
cwd 相对的那条理由（写进 `_MEIPASS` 会"报成功随进程消失"）。

### 修法（严格照 045b 先例）

1. `packaging/boardwise.spec` DATAS 增
   `(REPO / "blocklib" / "blocks.portmeta.json", "resources/blocklib")`。
2. `src/boardwise/resources.py` 增 `_PORT_META_PARTS` + `portmeta_sidecar()`
   （与 `parts_library()` 同款，只做路径拼装，不读内容）。
3. `src/boardwise/core/portmeta.py` 增 `DEFAULT_PORT_META_PATH`
   （= `"blocklib/blocks.portmeta.json"`）+ `default_port_meta_path()`：仓库态返回常量
   （与今天**逐字节同行为**），冻结态走 `resources.portmeta_sidecar()`；`_MEIPASS`
   缺失（坏 bootstrap）时退回常量，不把异常抛进规则运行——与
   `rules/facts.default_library_path()` 一模一样的形状。
4. `cli.py` 两处 argparse 默认值改为从访问器取（`default=default_port_meta_path()`）。
   访问器是**纯路径拼装、无 I/O**，在 `build_parser()` 期求值安全；`%(default)s`
   的 help 语义因此原样保留（仓库态照旧打印 `blocklib/blocks.portmeta.json`，冻结态
   打印 exe 内嵌路径）。显式 `--port-meta <路径>` 覆盖语义不变，两个消费点一行未动。
5. `tests/test_resources.py`：把 `portmeta_sidecar` 加进 spec/resources 一致性用例的
   解析器清单，并照 045b 的 `test_the_default_shelf_is_the_bundled_copy_when_frozen`
   先例加 portmeta 等价用例（冻结态指向 `resources/blocklib/…` 且文件存在、
   `monkeypatch.chdir` 证明与 cwd 无关、仓库态仍返回相对短拼写；再断言
   `build_parser()` 解析出来的 `--port-meta` 默认值也跟着进程走）。

## F4 `.esch2` 不在卫生闸门格式表（`tools/check_repo_hygiene.py`）

### 病根

`tools/check_repo_hygiene.py:27` 的
`_CONTAINER_RE = re.compile(r"\.(epro2|epro|eprj2|eprj3|epru|esch|epcb)(/|$)", re.I)`：
`.esch2`（V4 eprj3 文件夹格式里的图纸文件）中 `esch` 后面跟的是 `2`，不满足 `(/|$)`
锚 ⇒ **`.esch2` 文件对闸门失明**。公司 V4 工程的图纸文件可以直接无声进仓 = R4 红线
（工程文件永不入库）漏一个口子。

### 修法

1. 正则 alternation 加 `esch2`（放 `esch` 前，保持可读性）；
2. **同 commit 原则补 ALLOWLIST**：`git ls-files -z tests/fixtures/eprj3_synth/` 列出
   该夹具目录下**全部被跟踪文件**，凡命中新正则的一律加进 `ALLOWLIST`（038 进的合成
   V4 夹具，已获批入库，只是正则以前看不见它）；注释里的条数改准。
3. `tests/test_repo_hygiene.py`：加 `.esch2` 正例（未列白名单的 `foo/bar.esch2` 必须
   判违规）+ 否定例（`foo/bar.esch2.tmp` 不违规）；ALLOWLIST 漂移测试
   （`test_allowlist_matches_current_tracked_containers`，断言
   `ALLOWLIST == tracked`）会自动覆盖新增条目。
4. 跑 `python tools/check_repo_hygiene.py` 确认全仓零违规。

### 变异

正则退回旧版（去掉 `esch2`）→ 新的正例测试必须变红。

---

## 纪律

- 不 commit / add / push / checkout / restore；不改 `reviewsets/*.json`；不改
  `src/boardwise/rules/` 的判定逻辑（i18n 注释属文案，F2 明确允许）；不碰
  `tests/fixtures/` 既有夹具字节；不碰真机/bridge/connector。
- 变异验证 ≥1 组/件：`cp` 备份 → 改一行 → 测试变红 → `cp` 还原 → `sha256` 字节一致。
- append 落盘后立刻 `grep -c` 独立计数防双执行。

---

## 交卷记录

### 执行者（DeepSeek 子代理，commandcode/deepseek-v4.1-flash，2026-09-27）

证据全文见 `outputs/047_hygiene_batch.txt`（含每件的行为实测、变异命令与还原哈希）。

**F1 SCREW 位号前缀**

- `src/boardwise/engines/review.py`：`:190` 正则 `{1,5}`；`:197-212` extras 白名单加
  `"SCREW"`；两处注释改口径（放宽字母个数 ≠ 放松严格性，白名单仍在下游把关）。
- `tests/test_review_mark_cli.py` +2 用例（SCREW1/SCREW4 同现、`screw2` 归一化）；
  注释点名的 4 条反例（AMS1117/SS34/CH340G/FRC0805J471）逐条实测仍被挡住。
- 变异 1/1 CAUGHT：正则退回 `{1,4}` → 2 红；`cp` 还原后 sha256 `e708cb6c…` 字节一致。

**F2 文件默认视图翻转 pcb → schematic**

- `src/boardwise/cli.py`：`:2004` `args.view or "schematic"`；`--view` argparse 注释 + help
  重写；`_load_model` docstring、`EMPTY_PCB_VIEW_NOTE` 注释、`_pcb_view_read_nothing`
  docstring 三处改口径。
- `src/boardwise/engines/review_eval.py` docstring 括注改（"the view review defaults to"）。
- `src/boardwise/rules/i18n.py`：**只改注释**（`EMPTY_PCB_VIEW_HINT` 文案与触发条件一字未动）
  ——触碰裁决见证据 §五，主代理可单独 `cp` 还原。
- 文档同步：`docs/getting-started.md` §5.1、`docs/install.md`、`README.md`（中英各一处）、
  `.kimi-code/skills/boardwise/SKILL.md` §3.2 两条 + 坑表 14。
- 测试影响面（逐个确认后修正，全部是"本来就在钉 pcb 视图行为"的用例，改成**显式**
  `--view pcb`，意图不变）：
  | 文件 | 处数 | 为什么 |
  |---|---|---|
  | `tests/test_019_empty_board_hint.py` | 7 | 空读提示现在只在显式 pcb 视图下触发（模块 docstring 同步改） |
  | `tests/test_018_cli_review.py` | 1 | `--latest` 端到端钉的是 pcb 数字；该文件默认视图用例另加 |
  | `tests/test_020_parse_drops.py` | 1 | "pcb 视图不填丢脚计数"钉的就是 pcb 视图（注释 + 模块 docstring 同步） |
  | `tests/test_cli.py` | 1 | `.epro2` 子进程 smoke 钉的是 `board:` 行，只有 pcb 视图有 |
  未动而确认安全的：`test_018` 的 `.enet` 用例 ×6、`test_018` 的 llc `--md` 中文摘要用例
  （schematic 视图对这块板同样 0 发现，两种视图都过，故不改）、`test_020` 的 9 处、`test_038`
  ×1、`test_040b` ×1（原本就显式传 view）、`test_checkup_cli` 的 review-live 3 处（live 恒
  schematic）、`test_019` 的判据单测（纯函数）。
- 新增用例 3 条：`test_018` ×2（默认走 schematic 且**没有**空读提示；显式 pcb 仍读 pcb）、
  `test_038` ×1（eprj3 文件夹不写 view 也能读——旧默认会以 pcb 视图报 "B 档未开"）。
- 变异 1/1 CAUGHT：`"schematic"` 反转回 `"pcb"` → 2 红（`test_018` 新用例 + `test_038` 新用例）；
  `cp` 还原后 sha256 `7fa103aa…` 字节一致。

**F3 portmeta 内嵌**

- `packaging/boardwise.spec` DATAS +1 行；`src/boardwise/resources.py` `_PORT_META_PARTS` +
  `portmeta_sidecar()`（docstring 两处同步）；`src/boardwise/core/portmeta.py`
  `DEFAULT_PORT_META_PATH` + `default_port_meta_path()`（仓库态常量 / 冻结态走 resources /
  坏 bootstrap 退回常量，与 `rules.facts.default_library_path` 同形）；`src/boardwise/cli.py`
  两处 argparse 默认改 `default=default_port_meta_path()`（`build_parser` 内局部 import，纯路径
  拼装；`%(default)s` help 语义保留；两个消费点一行未动）。
- 实测：仓库态默认仍是 `blocklib/blocks.portmeta.json`（help 逐字不变）；冻结态（`_MEIPASS`
  模拟）默认落在 bundle 内且与 cwd 无关；`validate --spec ch340g_usb_uart.json` 双门 pass、exit 0；
  显式坏路径仍 fail-closed（STOPPED、exit 1）。
- 新增用例 3 条 + checkout/frozen 断言 3 处 + spec 一致性用例的解析器清单。
- 变异 2/2 CAUGHT：删 spec DATAS 行 → 1 红；冻结分支返回常量 → 1 红；两次 `cp` 还原
  sha256 均字节一致（spec `2b9bd224…`、portmeta.py `74976f13…`）。

**F4 `.esch2` 闸门**

- `tools/check_repo_hygiene.py`：正则 alternation 加 `esch2`；ALLOWLIST 增
  `tests/fixtures/eprj3_synth/sch/Schematic1/P1.esch2`（`git ls-files -z` 确认全仓被跟踪
  `.esch2` 仅此一个），条数注释 31 → 32。
- `tests/test_repo_hygiene.py` +2 用例（正例含大写与"目录 + 页文件同列"；否例含
  `.esch2.tmp`/`.esch2.bak`/`.epro2.txt`/文件名含 esch2 的 `.md`）；漂移用例自动覆盖新条目。
- `python tools/check_repo_hygiene.py` → 全仓零违规，exit 0。
- 变异 1/1 CAUGHT：正则退回旧版 → 正例红（漂移用例同时红，属预期副作用；否例保持绿）；
  `cp` 还原后 sha256 `dc283c88…` 字节一致。

**定向测试（均带 `--basetemp=.tmp_pt_047`，全绿）**

- `test_review_mark_cli.py` 31 / `test_repo_hygiene.py` 4 / `test_resources.py`+`test_validate_spec.py` 88 /
  `test_018_cli_review.py` 32 / `test_019_empty_board_hint.py` 11 / `test_020_parse_drops.py` 12 /
  `test_038_eprj3.py` 17。
- 13 文件合并一轮 **249 passed**；12 文件合并一轮 **240 passed**；
  017/eval/annotations/011d/025/040 相关 11 文件一轮 **258 passed**；
  **收盘一轮 24 文件合并 507 passed**（22.6s）。
- **未跑全量四线**（任务书要求：全量由主代理统一跑）。
- 工作树里另有一路并发的 046（MPN 译码）未提交改动（`src/boardwise/rules/values.py`、
  `tests/test_011d_rules.py`、`tasks/046-mpn-decoder-gaps.md`），本批一行未碰；上面的读数是在
  这个共享工作树上取的。

**遗留（详见证据 §七）**

1. 全量 pytest 与 connector/tsc/dsh-plugin 三线未跑。
2. spec 已改但**未真跑 `build_exe.py`**：冻结态验证是 `_MEIPASS` 模拟，发版前建议真构建一次并
   核对内嵌资源（045b §四做法）。
3. `PROGRESS.md:163` 的"遗留：review 默认 pcb 视图翻转另案"是 017 历史行，未回写；新进展建议
   主代理补一条 PROGRESS。
4. `SCREW` 只进 review 的 refs 白名单，`core/parts.DESIGNATOR_CATEGORIES`（货架类别）与
   `engines/checkup.py` 的模块归类未动（安装孔无货架类别）。
5. dsh-plugin 无需跟（只包 `checkup`/`arch`，不包 `review`；命令行面未增删）。
6. `src/boardwise/rules/i18n.py` 的注释改动若被判越界，`cp .tmp_047_backup/src/boardwise/rules/i18n.py`
   单独还原即可，无功能影响。

