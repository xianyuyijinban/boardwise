# boardwise

English | [中文](#中文)

## English

boardwise is an AI harness for [EasyEDA Pro](https://pro.easyeda.com/) (JLCEDA Pro).
The long-term vision is a three-in-one tool — **review + generate + simulate** —
built on a design-rule library curated from professional hardware engineering
practice. Two pieces exist today:

1. **An offline reviewer (stage 1).** Reads a schematic netlist exported from
   EasyEDA (`.enet`, UTF-8 JSON) or a project backup (`.epro2`), runs a rule
   engine, and prints a report where every finding carries concrete evidence
   (component / pin / net references). One file in, full report out — no
   separate netlist export, no editor.
2. **A live bridge (v0, read-mostly).** A local daemon plus an EasyEDA
   extension, so the reviewer can also ask *what is open right now*, capture a
   native screenshot of the canvas, and draw markers on the exact primitives a
   finding refers to. It reads the editor; it never writes to the design.
   See [`docs/bridge.md`](docs/bridge.md).

### Install

```bash
pip install .
```

The offline reviewer uses only the Python standard library (Python >= 3.10).
The bridge additionally needs [`websockets`](https://pypi.org/project/websockets/),
which `pip install .` brings in; `boardwise review` still works without it.

### Usage

```bash
# Print a summary to the terminal
boardwise review path/to/board.enet

# Single-file review: an .epro2 project backup needs no netlist export
boardwise review path/to/board.epro2

# Also write machine-readable and human-readable reports
boardwise review path/to/board.epro2 --json report.json --md report.md
```

The input type is picked from the extension:

| Input | What it is | What you get |
|---|---|---|
| `.enet` | schematic netlist export (UTF-8 JSON) | netlist review |
| `.epro2` | project backup (board + netlist in one file) | netlist review **plus** a board line (pads / tracks / vias) |

An encrypted `.epro2` export cannot be read — the reviewer says so and asks you
to re-export with the encryption option disabled, rather than failing with a
stack trace.

Exit code is `1` when any ERROR-level finding exists, `0` otherwise; `2` means
the input could not be read at all.

Built-in rules (all L1-connectivity heuristics; each message states its limits):

- `decoupling-per-ic` — every `U*` IC should share a pin net with a capacitor.
- `xtal-load-caps` — crystal pins should each see a capacitor to ground.
- `shunt-sense-link` — milliohm shunts should reach a sense input on an IC.

### Live bridge

```bash
cd connector && npm install && node build.mjs   # build the editor extension
boardwise bridge start                          # run the daemon (foreground, Ctrl-C to stop)
boardwise doctor                                # 7 checks: daemon · extension · versions · project (exit 1 + a fix per line)
boardwise bridge status                         # daemon up? connector attached? paired with whom?
boardwise bridge screenshot shot.png --fit      # native canvas capture
boardwise bridge highlight <uuid> --color "#FF0000"
boardwise bridge highlight --clear
boardwise review-mark report.json               # draw a `review --json` pass on the schematic (`clear` removes it)
boardwise bridge export-fab --out fab/          # Gerber + P&P + BOM + manifest.json
boardwise bridge revoke                         # forget the paired connector
```

New to this? [`docs/getting-started.md`](docs/getting-started.md) walks the whole path — install
the editor, import the `.eext`, start the daemon, get `doctor` green, then the first review and the
first fab export — with the expected output at every step.

### Comparing against the golden board (`compare`)

`boardwise compare` is the referee for AI-drawn designs (task 005): it parses a
candidate `.epro2` into a design model and diffs it against the golden board at
three levels — components (presence, footprint, value, lcsc), nets (names and
members), and **per-pin** net mappings (every pin of every common component).
Values compare with engineering normalisation (`10k` == `10K` == `10000`);
designators, net names and pin numbers are exact.

```bash
boardwise compare candidate.epro2                 # vs tests/fixtures/ch340_golden.epro2
boardwise compare candidate.epro2 --golden other.epro2
boardwise compare candidate.epro2 --json          # machine-readable (AI loop)
```

Exit codes follow the review semantics: `0` no differences, `1` differences
found (one human-readable line each, sorted), `2` bad input — a missing or
encrypted file prints a reason instead of a traceback. The golden fixture is a
schematic-only project, so both sides are parsed through the schematic model
(`parsers/schematic.py`); the per-pin report is the acceptance gate for
`boardwise draw` (task 005's vertical slice).

### Drawing a golden board from scratch (`draw`)

`boardwise draw` (task 006) closes the loop the referee opened: it takes the
golden board's connectivity as the only design input, draws the schematic on a
blank page of the open project through the bridge, and diffs the editor's own
understanding against the golden netlist per pin. It prints the action plan
and waits for confirmation before touching anything (`--yes` skips), names
nets with net flags and net ports (never the net-label API that hangs on the
measured host), and reports every failed placement and every candidate-source
decision.

```bash
boardwise draw --from tests/fixtures/ch340_golden.epro2
boardwise draw --from tests/fixtures/ch340_golden.epro2 --yes \
    --screenshot drawn.png
```

Exit codes: `0` drawn and zero differences, `1` differences or failed
actions, `2` bad input, aborted gate, or no daemon. Requires connector 0.3.0+
and the write actions it ships; the operator manual, the machine-probe
checklist and the measured host traps are in [`docs/draw.md`](docs/draw.md).

### Assembling a board from blocks (`--spec`, task 008a)

The second design source: instead of replaying one golden page, the page is
**composed**. A block template (`blocklib/blocks/*.json`) carries a block's parts,
the symbol geometry they need, its internal wires and flags, its parameters and
its ports; a board spec (`blocklib/specs/*.json`) says which blocks, where, with
which numbers, and how their ports are wired. Blocks are tied together by net
**names** only, and the assembled page goes through the *same* replay planner,
the same five hard constraints and the same lint as a golden replay.

```bash
# offline: does the specification reproduce the golden?
boardwise compare --spec blocklib/specs/ch340g_usb_uart.json \
    --golden tests/fixtures/ch340_golden.epro2 \
    --overrides tests/fixtures/ch340_golden.overrides.json
boardwise lint --spec blocklib/specs/ch340g_usb_uart.json      # 0 violations

# draw it (the two checks above run as gates before any bridge call)
boardwise draw --spec blocklib/specs/ch340g_usb_uart.json \
    --golden tests/fixtures/ch340_golden.epro2 --render out.png
```

Template format, the coordinate contract, the three refusals (a boundary that
cuts a wire, two circuits that would share a net name, a rail port with no flag)
and what 008a explicitly does **not** claim: [`docs/blocks.md`](docs/blocks.md).

### Choosing a part (`parts select`, task 008b)

`blocklib/parts.json` is a shelf of **verified** parts, harvested from boards the
designer already built: MPN, LCSC C-number, the library's device and footprint
uuids, the **library** footprint name (`R0402`, never the human `0402`), and the
electrical parameters verbatim.

```bash
boardwise parts select "100nF 0805"            # offline, zero network
boardwise parts select "5mΩ 2512" --json
boardwise parts select "330mΩ 0805" --online   # explicit opt-in: JLC SMT compare
boardwise parts select "CH340N" --resolve      # resolve the C-number via the bridge
boardwise bom export --spec blocklib/specs/ch340g_usb_uart.json --out bom.csv
                                               # the BOM the spec implies: JLC's
                                               # five columns + open questions
```

An explicit resistance query is **gated** (#202): the value must come from a
named field and match numerically, the SI prefix is case-sensitive (`330mΩ` is
`0.33Ω`, never `33Ω`), nothing in an MPN or a C-number can supply a resistance,
and **no exact candidate means exit code 1** rather than a fuzzy recommendation.
A size word maps to a library name only through an explicit table. The online
path never runs from the connector (the webview cannot make cross-origin
fetches) and the tests never touch a network. See
[`docs/parts.md`](docs/parts.md).

The daemon listens on `127.0.0.1:61190` only (`--port` / `BOARDWISE_PORT`). It keeps two
secrets apart: `~/.boardwise/token` for the CLI, and `~/.boardwise/connector-token` for the
editor. **There is nothing to paste** — the connector generates its own token on first run and
the daemon trusts the first one to connect (trust on first use), then only that one. It also
reports which random source produced it (Web Crypto, or a `Math.random` fallback) in the log panel
and in **About…**; see `docs/bridge.md` §9. Every request is appended to
`~/.boardwise/audit/YYYY-MM-DD.jsonl`; `boardwise bridge revoke` forgets the pairing so the next
connector pairs afresh.

Three things account for nearly every "nothing connects": the daemon is not
running, the extension's **external interaction** permission was not granted,
or the extension never reached `activate()`. The extension's **About…** menu item
reports which, and shows the pairing fingerprint to match against
`boardwise bridge status`. Since 0.2.5 the connector does not wait for
`activate()` at all: the connection starts when the extension's bundle is
evaluated — the one window the host measurably keeps alive — and every later
evaluation reuses that connection instead of opening another one. It says so in
the log panel (`connect: url=…`) rather than failing silently; if no editor
global was bound at evaluation time, the panel says that too.
Full protocol, error codes and a step-by-step verification checklist:
[`docs/bridge.md`](docs/bridge.md).

### Architecture

Architecture diagram: placeholder (TBD).

```
src/boardwise/
  core/model.py          # normalized design model (DesignModel / Component / Net / Pin)
  core/geometry.py       # BoardGeometry: pads / tracks / vias / pours / outline
  core/compare.py        # golden-vs-candidate referee (identity-aware since 0.3.8)
  core/verify.py         # placement verification: golden pins -> placed pins (F2/F4)
  core/candidate.py      # candidate model from the editor (netlist first, geometry fallback)
  core/blocks.py         # block templates + board specs: schema, loaders, parameter checks
  core/parts.py          # curated part library: schema, the value gate, the footprint table
  parsers/enet.py        # .enet netlist -> DesignModel
  parsers/epru.py        # .epro2 -> documents -> BoardGeometry (one parse)
  parsers/epro2_model.py # .epro2 -> DesignModel (same parse, netlist view)
  parsers/schematic.py   # .epro2 schematic page -> DesignModel (+ DEVICE META join)
  parsers/eprj2.py       # .eprj2 local project -> documents + library identity
  rules/base.py          # Rule / Finding framework
  rules/connectivity.py  # first L1 connectivity rules
  engines/review.py      # run rules -> findings -> markdown / json reports
  engines/generate.py    # DesignModel -> ActionPlan (offline, self-checked)
  engines/replay.py      # the golden page's own layout, translated to the new page
  engines/cut.py         # .epro2 + a designer's boundary -> a block template
  engines/bom.py         # board spec + the shelf -> the bill of materials
  engines/assemble.py    # block templates + a board spec -> a drawable design
  engines/harvest.py     # boards -> the curated part library (idempotent)
  engines/catalog.py     # JLC SMT catalog client (opt-in, behind a fetcher seam)
  engines/select.py      # part selection: offline ranking, online compare, C# resolve
  engines/draw.py        # run_draw: gate, placements, placement check, wires, diff
  bridge/protocol.py     # frame envelope, action catalogue, error codes
  bridge/daemon.py       # loopback WebSocket server: auth, routing, audit
  bridge/client.py       # what the CLI uses to talk to the daemon
  cli.py                 # boardwise review | draw | lint | compare | parts | bridge ...

blocklib/                # block library + board specs (data; see docs/blocks.md)
  blocks/*.json          #   one file per block: parts, symbol geometry, wires, ports, params
  specs/*.json           #   a board: which blocks, where, connections, parameter values
  parts.json             #   the curated part library (see docs/parts.md)
  sources/*.eprj2        #   岳翔宇's boards, the harvest's input (read-only);
                         #   exported boards live in tests/fixtures/*.epro2
tools/                   # offline tools, not part of the installed package
  extract_block.py       #   cut a block out of a board, or re-derive a committed one
  harvest_parts.py       #   harvest the part library (--check, --verify)

connector/               # TypeScript extension (the only code that touches eda.*)
  src/protocol.ts        #   mirror of bridge/protocol.py
  src/transport.ts       #   handshake, heartbeat, reconnect
  src/actions.ts         #   document.current / sch|pcb.readback / screenshot / highlight
  src/index.ts           #   menu commands (reconnect, stop, re-pair, auto-connect, about)
  dist/index.js          #   built artifact the editor loads
```

Both `.epro2` views come from **one** parse: `load_epro2_source()` decodes the
backup once, and geometry and netlist are two views of the same cached PCB
context, cross-referenced by designator. Format notes live in
[`docs/epru-format.md`](docs/epru-format.md).

## 中文

boardwise 是一个面向 EasyEDA 专业版（嘉立创EDA）的 AI 画板 harness。愿景是
「审查 + 生成 + 仿真」三合一，核心护城河是职业硬件工程师的设计规则库。
目前已有两块：

1. **离线审查器（第一阶段）**——读取 EasyEDA 导出的网表文件（`.enet`，UTF-8
   JSON）**或工程备份文件（`.epro2`，单文件即含板子与网表）**，跑规则引擎，
   输出带证据（器件 / 引脚 / 网络）的审查报告。一个文件进、一份报告出，不需
   要单独导网表。
2. **实时桥（v0，只读为主）**——本地 daemon + EasyEDA 扩展，让审查器还能知道
   「现在开着什么」、抓一张画布原生截图、并在发现项对应的图元上画标记。它只
   读编辑器，不改设计。协议与验证清单见 [`docs/bridge.md`](docs/bridge.md)。

### 安装

```bash
pip install .
```

离线审查路径只依赖 Python 标准库（Python >= 3.10）。桥额外需要
[`websockets`](https://pypi.org/project/websockets/)，由 `pip install .` 一并装上；
没装也不影响 `boardwise review`。

### 使用

```bash
# 终端打印摘要
boardwise review path/to/board.enet

# 单文件审查：.epro2 工程备份，无需另导网表
boardwise review path/to/board.epro2

# 同时输出 JSON / Markdown 报告
boardwise review path/to/board.epro2 --json report.json --md report.md
```

按扩展名自动选择解析器：`.enet` 走网表，`.epro2` 走工程备份（额外打印焊盘 /
走线 / 过孔数量）。备份若勾选了加密导出则无法读取，此时会提示重新导出时取消
加密，而不是抛栈。

存在 ERROR 级发现时退出码为 `1`，否则为 `0`；输入根本读不出来时为 `2`。

内置规则（全部为 L1 连通性级启发式，message 中如实标注了局限性）：

- `decoupling-per-ic`：每个 U 前缀 IC 的引脚网络中应至少有一个与电容共享。
- `xtal-load-caps`：晶振每个引脚网络上应各有一个落到地的电容。
- `shunt-sense-link`：毫欧级分流电阻应能到达某个 IC 的采样引脚。

### 实时桥

```bash
cd connector && npm install && node build.mjs   # 构建编辑器扩展
boardwise bridge start                          # 起 daemon（前台，Ctrl-C 停）
boardwise doctor                                # 七项体检：daemon · 扩展 · 版本 · 焦点工程（未通过则逐条给建议，退出 1）
boardwise bridge status                         # daemon 在不在？扩展接没接上？跟谁配对的？
boardwise bridge screenshot shot.png --fit      # 画布原生截图
boardwise bridge highlight <uuid> --color "#FF0000"
boardwise bridge highlight --clear
boardwise review-mark report.json               # 把 `review --json` 的发现画到原理图上（`clear` 清掉）
boardwise bridge export-fab --out fab/          # Gerber + 坐标 + BOM + manifest.json
boardwise bridge revoke                         # 忘掉已配对的扩展
```

第一次装？看 [`docs/getting-started.md`](docs/getting-started.md)：装编辑器 → 导入 `.eext` →
起 daemon → doctor 全绿 → 第一次 review 与第一次导出打板文件，每一步都写了预期输出。

### 与黄金板比对（`compare`）

`boardwise compare` 是「AI 画得对不对」的裁判（任务 005）：把候选 `.epro2` 解析成设计模型，
与黄金板做三级比对——器件级（在位、footprint、value、lcsc）、网络级（名字与成员）、
以及**逐 pin** 的引脚-网络映射（共有器件的每个脚）。value 带工程记数归一化
（`10k` == `10K` == `10000`）；位号、网络名、引脚号精确比对。

```bash
boardwise compare candidate.epro2                 # 默认对 tests/fixtures/ch340_golden.epro2
boardwise compare candidate.epro2 --golden other.epro2
boardwise compare candidate.epro2 --json          # 机器读格式（给 AI 闭环）
```

退出码与 review 一致：`0` 无差异，`1` 有差异（每条一行人读输出，按位号排序），
`2` 输入错误——文件缺失或加密时给出原因而不是堆栈。黄金夹具是纯原理图工程，
两侧都走原理图模型（`parsers/schematic.py`）；逐 pin 报告就是 `boardwise draw`
（005 垂直切片）的验收闸门。

### 从零重画黄金板（`draw`）

`boardwise draw`（任务 006）把裁判闭成环：以黄金板的连通性为唯一设计输入，通过桥在当前
工程的空白图页上重画原理图，再把编辑器自己理解到的网表与黄金板逐 pin 比对。执行前打印
动作计划并等待人工确认（`--yes` 跳过）；网络命名一律用电源旗标/网络端口（不用在该宿主上
实测会挂起的 net-label API）；每个失败的放置、每个候选来源的选择都如实写进报告。

```bash
boardwise draw --from tests/fixtures/ch340_golden.epro2
boardwise draw --from tests/fixtures/ch340_golden.epro2 --yes \
    --screenshot drawn.png
```

退出码：`0` 画完且零差异，`1` 有差异或有失败动作，`2` 输入错误、闸门中止或 daemon 不在。
需要 connector 0.3.0+ 及其写动作；操作手册、真机探针步骤与实测宿主陷阱见
[`docs/draw.md`](docs/draw.md)。

### 按块装配画板（`--spec`，任务 008a）

第二个设计来源：不再回放某一页黄金，而是**把页面拼出来**。块模板
（`blocklib/blocks/*.json`）自带一个块的器件、它们需要的符号几何、块内导线与旗标、
参数与对外端口；板规格（`blocklib/specs/*.json`）说明用哪些块、摆在哪、数值多少、
端口之间怎么连。块与块之间**只靠网名**相连，装配出来的页面走的是**同一个**回放规划器、
同一套五条硬约束、同一条 lint。

```bash
# 离线：规格能不能复现黄金？
boardwise compare --spec blocklib/specs/ch340g_usb_uart.json \
    --golden tests/fixtures/ch340_golden.epro2 \
    --overrides tests/fixtures/ch340_golden.overrides.json
boardwise lint --spec blocklib/specs/ch340g_usb_uart.json      # 0 violations

# 画出来（上面两项会作为闸门，在碰任何桥动作之前先跑）
boardwise draw --spec blocklib/specs/ch340g_usb_uart.json \
    --golden tests/fixtures/ch340_golden.epro2 --render out.png
```

模板格式、坐标契约、三条拒绝（边界切到导线 / 两个电路最终同名 / 轨道端口没有旗标可命名）
以及 008a **明确不主张**的东西，见 [`docs/blocks.md`](docs/blocks.md)。

### 选件（`parts select`，任务 008b）

`blocklib/parts.json` 是一份**已验证**器件的货架，从设计者自己画过的板上收割：MPN、
立创 C 号、库 device/封装 uuid、**库词汇表**的封装名（`R0402`，不是人读的 `0402`），
以及电气参数原文（单位保留）。

```bash
boardwise parts select "100nF 0805"            # 离线，零网络
boardwise parts select "5mΩ 2512" --json
boardwise parts select "330mΩ 0805" --online   # 显式 opt-in：JLC SMT 比对
boardwise parts select "CH340N" --resolve      # 按 C 号走桥解析身份
boardwise bom export --spec blocklib/specs/ch340g_usb_uart.json --out bom.csv
                                               # 规格蕴含的 BOM：立创五列 + 开放问题清单
```

显式阻值查询**带门禁**（#202 纪律）：数值必须来自具名属性字段并做数值相等匹配，
SI 前缀区分大小写（`330mΩ` 等于 `0.33Ω`，永不等 `33Ω`），料号/C 号里的数字不能当阻值，
**无精确候选时退出码 1**、不给模糊推荐。封装词只经一张显式表映射到库名。
在线路径**不从 connector 发出**（webview 不能跨域 fetch），测试也从不打真网络。
详见 [`docs/parts.md`](docs/parts.md)。

daemon 只监听 `127.0.0.1:61190`（可用 `--port` / `BOARDWISE_PORT` 改），并把两个密钥分开存：
CLI 用 `~/.boardwise/token`，编辑器用 `~/.boardwise/connector-token`。**没有东西需要粘贴**——
connector 首次运行会自己生成一个 token，daemon 信任第一个连上来的（TOFU，首次使用即信任），
之后只认它；它还会在日志面板和 **About…** 里说明这个 token 来自哪个随机源（Web Crypto，
还是 `Math.random` 兜底），见 `docs/bridge.md` §9。每个请求都会落到
`~/.boardwise/audit/YYYY-MM-DD.jsonl`；`boardwise bridge revoke` 会忘掉配对，下一个连上来的
扩展重新配对。

「连不上」几乎总是这三件事之一：daemon 没起、扩展的**外部交互权限**没授权、
扩展根本没跑到 `activate()`。扩展的 **About…** 菜单会告诉你卡在哪一步，
并显示配对指纹，可与 `boardwise bridge status` 对照。第三件事自 0.2.5 起不再存在：
connector **不再等 `activate()`**——bundle 求值时（实测宿主唯一会保活的窗口）就发起连接，
之后的重求值复用同一条连接而不是再开一条；日志面板会打 `connect: url=…`，
若求值时编辑器全局还没绑上，面板里也会明说。
自 0.2.4 起这套兜底**可观测且可手动触发**：每个延迟探针的结论都会记录并在 About 里显示
（`self-arm: …`），而且**打开 About… 本身就会触发连接**——菜单是实测唯一不依赖 activate
也能跑的入口。

### 架构

架构图：占位（待补）。目录结构见上方英文节——含 `bridge/`（daemon 侧）与
`connector/`（扩展侧，唯一接触 `eda.*` 的代码）。
