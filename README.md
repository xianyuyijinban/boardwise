# boardwise

English | [中文](#中文)

An agent harness for hardware engineers.

It lets an AI assistant (Claude Code, DeepSeek, Kimi Code — any of them)
actually read your schematic — components, nets, pins, not screenshots —
and do real work on it: review the board, mark the problems, edit with
your sign-off, export the fab files. EasyEDA Pro is the platform we know
inside-out today; KiCad is next, and the architecture has been
multi-platform from day one.

## What it does

**Review.** With the editor open, one command:

```bash
boardwise checkup
```

You get a report: ERC/DRC, fourteen design-rule families, which parts
still lack datasheets, and every finding pointing at a concrete
component, pin and net — with markers drawn on the canvas where the
problems are. On real boards it has caught things the designer had
missed — a current-sense circuit with no bias, that kind of problem.
You don't find those by matching rules against a netlist; you have to
check whether the architecture makes sense together.

**Edit.** Find a problem, get a change preview; nothing moves until you
approve; afterwards it reads back and re-reviews to confirm the problem
is actually gone. Edit kinds today: change a component value, add a
missing part, repair a single pin connection, insert an RC/divider
subcircuit, move a functional block.

**Export.** BOM, netlist, Gerber, pick-and-place — one command each.

**Draw.** You state the circuit intent — a divider, an RC low-pass, an
LDO; parts, values, which pin joins which net — and the drawing
compiler turns it into a sheet a human can read: where parts sit, how
wires run, where text goes so it doesn't sit on a wire. Wrong
connectivity, not enough room, a conflict with your locked placement —
it refuses rather than hand you a bad drawing. It compiles offline, and
it can also land into the open editor itself — placement, pin readback
before any wire, save, and a render of the result. Several modules
compose onto one page: what is already on the page becomes keep-outs,
your locked placements are honoured, every rail gets a flag, and one
`draw discard` takes a landed page back off.

## Architecture and roadmap

Three layers, all on your own machine — nothing goes through a cloud:

```
AI assistant
  │  calls short commands (CLI / skill / dsh plugin)
  ▼
offline engine      parse · review rules · drawing compiler · change plans
  │  loopback only
  ▼
daemon + editor extension      reads design data; writes go preview → approve → readback
  ▼
EasyEDA Pro (today) · KiCad (planned)
```

Standing rules: the workflow lives in tools, not in prompts; every
conclusion carries evidence; writes are preview → authorize → readback;
on a timeout or disconnect it reads back first and never blindly
retries.

| Stage | Status |
|---|---|
| Schematic review (rule families + datasheet gate + eval harness) | Usable, in maintenance |
| Review-to-local-edit (preview / authorize / readback / re-review) | Usable |
| Drawing compiler (divider / RC / LDO) | Modules and multi-module pages land in the editor |
| Full schematic capture → PCB → SPICE simulation | In that order |
| KiCad platform | Planned |

One sentence on how the review rules are scored: the annotated eval
sets are signed and split into a tuning pile and an acceptance pile,
and the harness is built so the acceptance pile cannot leak into the
scores — `--split` defaults to `dev` and holdout records enter no
denominator. Two tuning constants predate the split discipline; their
comments declare their evidence boards, and
`tests/test_doc_claims.py` keeps this paragraph honest.
Details in `outputs/017_generalization.md`.

## Install & supported environments

Three artifacts in [Releases](https://github.com/xianyuyijinban/boardwise/releases):

| File | For |
|---|---|
| `boardwise-windows-x.x.x.exe` | Anyone who doesn't want Python: single-file CLI, part library embedded |
| `boardwise-connector-x.x.x.eext` | Everyone: the extension you import into EasyEDA |
| `boardwise-dsh-x.x.x.tgz` | DeepSeek users: the dsh plugin, optional |

Environment: Windows. Python ≥ 3.10 (source installs only; 3.9 and
below are not supported). EasyEDA Pro **3.2.149 / 3.2.186 / V4.1.60**
are all verified on real machines; older versions are not guaranteed.
macOS/Linux are untested — the offline review probably runs, the bridge
is unverified.

Fastest path: [`docs/install.md`](docs/install.md) (Chinese — every
step says what you should see). For the impatient: `pip install .` →
import the `.eext` in the editor → `boardwise doctor` all green →
`boardwise checkup`.

Getting the review checklist into your AI: `boardwise install-skill`
installs it for Kimi Code and Claude Code (one side only: `--harness kimi`
or `--harness claude`; a different file already there is backed up to
`SKILL.md.bak-<YYYYMMDD-HHMMSS>`, never quietly replaced, and a second
install on the same day gets its own file rather than displacing the first).
Using another agent —
Codex, Hermes, anything? `boardwise install-skill --agent` prints a short
prompt to paste into your AI, and it puts the file where it looks for
skills, which it knows better than we do. If your AI is working inside a
clone of this repo, [`AGENTS.md`](AGENTS.md) already points it at the
checklist — nothing to install.

## Common errors & notes

- **Nothing connects** — nine times out of ten it's one of three: the
  daemon isn't running (`boardwise bridge start`), the extension's
  *external interaction* permission wasn't granted, or the extension
  never activated. The extension's **About…** menu tells you which.
- **Several project windows open** — name one: `--project <name>`. It
  refuses to guess.
- **Encrypted `.epro2` export** — unreadable; re-export with encryption
  off.
- **A `.eprj2` file holds no drawing** — it's just the project shell.
  Read live through the bridge, or export an `.epro2` backup.
- **Exit code 3 is not "the board is clean"** — it means the online
  state could not be stated. Whatever could not run is marked
  `{checked: false}` with no counts.
- **It always previews before touching your drawing.** Don't skip the
  confirmation out of habit — the readback after your yes is the point,
  not the ceremony.
- Canvas screenshots return a cached frame on 3.2.186 — use the OS
  snipping tool when you need a real one.

## Acknowledgments

We're glad these projects exist:

- [easyeda-agent](https://github.com/zhoushoujianwork/easyeda-agent)
  (zhoushoujianwork) — our thanks for the ideas and the inspiration in
  the details. It is their continued progress that let us sidestep the
  pitfalls and reach our own goals faster and more efficiently.
- [@jlceda/pro-api-types](https://www.npmjs.com/package/@jlceda/pro-api-types) —
  the official API type definitions the connector stands on.
- The EasyEDA team — opening real extension APIs to the community is
  what makes any of this possible. Thank you.

## License

MIT

---

## 中文

硬件工程师的 Agent Harness。

让 AI 助手（Claude Code、DeepSeek、Kimi Code……哪个都行）真正读懂你的
原理图——器件、网络、引脚，不是截图——然后替你干活：审板子、标问题、
按你的授权改图、导出制板文件。目前吃透的是立创 EDA 专业版，KiCad 是
下一个平台，架构从一开始就按多平台设计。

### 它能做什么

**审板子。** 编辑器开着，一条命令：

```bash
boardwise checkup
```

输出一份报告：ERC/DRC、十四类设计规则、哪些器件还缺数据手册、每条问题
各自指着具体的器件、引脚和网络；顺手把问题标记在画布上。它在真板子上
抓到过设计者自己没注意到的问题——比如一个该做偏置而没做的电流采样
电路。这类问题不是查规则书能查出来的，得先理解整个架构自不自洽。

**改图。** 发现问题后，它给修改预览，你点头它才动，动完自己回读、再跑
一遍审查确认问题真的消失。已经支持的改法：改器件值、补一颗缺失的器件、
修单个引脚连接、插入 RC/分压子电路、局部移动一个功能块。

**导出。** BOM、网表、Gerber、坐标文件，各一条命令。

**画图。** 你写电路意图——分压、RC 低通、LDO，器件、参数、哪个脚接
哪个网——画法编译器负责把它变成一张能给人看的图：器件怎么摆、线怎么
走、字放哪不压线。接法错、空间不够、和你的锁定冲突，它宁可拒绝也不交
出一张烂图。离线出图之外，它已经能直接落进开着的编辑器——放件、
拉线前先回读引脚、保存、再出一张渲染图。多个模块能组合进同一页：
页上已有的图元自动变成禁布区、你锁定的位置被尊重、每条电源轨都有
旗标，一条 `draw discard` 能把落好的整页撤下来。

### 架构和规划

三层，全跑在你自己电脑上，不经过任何云端：

```
AI 助手
  │  调很短的命令（CLI / skill / dsh 插件）
  ▼
离线引擎      解析工程文件 · 审查规则 · 画法编译 · 修改计划
  │  本机回环
  ▼
daemon + 编辑器扩展      读工程数据，写之前先预览、你授权、它回读
  ▼
立创 EDA 专业版（现在） · KiCad（规划）
```

规矩就几条：工作流住在工具里，不住在 prompt 里；每个结论带证据；
写操作一律预览 → 授权 → 回读；超时断连先读回，绝不盲目重试。

路线图：

| 阶段 | 状态 |
|---|---|
| 原理图审查（规则族 + 数据手册闸 + 评测体系） | 可用，维护中 |
| 审查到局部修改（预览/授权/回读/复查） | 可用 |
| 画法编译器（分压/RC/LDO） | 单模块与多模块整页均已能落进编辑器 |
| 完整原理图绘制 → PCB → SPICE 仿真 | 按序推进 |
| KiCad 平台 | 规划中 |

审查规则的评测方式说一句人话：我们有一套签名标注过的评测集，分成
调参用和验收用两摞；harness 在结构上堵死验收摞混进分数——`--split` 默认
`dev`，验收摞不进任何分母。有两条调参常量先于分堆制度诞生，它们的注释
里写明了取证板，`tests/test_doc_claims.py` 盯着这段话不许它过期。
细节在 `outputs/017_generalization.md`。

### 安装包和环境支持

[Releases](https://github.com/xianyuyijinban/boardwise/releases) 里三样：

| 文件 | 给谁 |
|---|---|
| `boardwise-windows-x.x.x.exe` | 不想装 Python 的人：单文件 CLI，器件库已内嵌 |
| `boardwise-connector-x.x.x.eext` | 所有人：立创 EDA 里导入的扩展 |
| `boardwise-dsh-x.x.x.tgz` | DeepSeek 用户：dsh 插件，可选 |

环境：Windows；Python ≥ 3.10（仅开发/源码安装需要，3.10 以下不支持）；
立创 EDA 专业版 **3.2.149 / 3.2.186 / V4.1.60** 都真机验证过，更低版本
不保证。macOS/Linux 没测过——理论上离线审查能跑，桥没验证。

最快的路：`docs/install.md`（给朋友看的版本，全程中文，每步写了
"应该看到什么"）。熟手：`pip install .` → 编辑器导入 `.eext` →
`boardwise doctor` 全绿 → `boardwise checkup`。

把审查清单装进你的 AI：`boardwise install-skill` 给 Kimi Code 和 Claude Code 装上
（只装一侧加 `--harness kimi` 或 `--harness claude`；目标位置已有别的版本会先备份成
`SKILL.md.bak-<年月日-时分秒>`，不会静默覆盖；同一天装两次是两个备份文件，第二个不覆盖第一个）。用的不是这两个 agent——Codex、Hermes
之类——跑 `boardwise install-skill --agent`：它打印一段引导指令，粘给你在用的 AI，
放哪儿由它自己定，它比我们清楚。AI 就在本仓库 clone 里干活的话，根目录
[`AGENTS.md`](AGENTS.md) 已经指到了清单，不用装。

### 常见错误和注意事项

- **连不上**，九成是三件事之一：daemon 没起（`boardwise bridge start`）、
  扩展的"外部交互"权限没给、扩展没激活。扩展菜单里的 **About…** 会直接
  告诉你卡在哪步。
- **开了好几个工程窗口**：命令要指名，`--project <名字>`，否则它拒绝猜。
- **`.epro2` 导出时勾了加密**：读不了，重新导一次别勾加密。
- **`.eprj2` 单文件里没有图纸**：那只是工程壳，图纸要么在线走桥读，
  要么导出 `.epro2` 备份。
- **退出码 3 不是"板子干净"**：是**说不清**——在线状态读不出来（daemon 没起、扩展没连上），
  或者 `completion.verdict` 是 `incomplete`（没读到模型 / 有器件缺手册未审 / 骨架没生成 /
  覆盖有缺口）。`review --live` 拿到了模型、但模型是空的（0 器件 0 网络）也算（075）——
  它与"根本没拿到模型"是两句话，两句都不许读成通过。审查没跑成的部分报告里会写
  `{checked: false}`，不带计数。**CI 里别把 3 当通过**（073 起 `review` / `checkup` 都这样；
  有 ERROR 仍是 1，`complete-with-open-items` 仍是 0）。
- **它要改你的图之前**一定会先给预览，别图快跳确认——确认完它自己
  还会回读验证，这一步省不掉也不该省。
- 画布截图在 3.2.186 上返回的是缓存帧，要真实截图请用系统截图工具。

### 致谢

站在这些项目的肩膀上，我们很庆幸它们存在：

- [easyeda-agent](https://github.com/zhoushoujianwork/easyeda-agent)（zhoushoujianwork）——
  感谢 EasyEDA-Agent 提供的一些思路和细节上的灵感。正是他们的不断前进，
  才让我们少踩了坑，能够以更高效、更快速的方式接近自己的目标。
- [@jlceda/pro-api-types](https://www.npmjs.com/package/@jlceda/pro-api-types)——
  官方 API 类型定义，connector 开发站在它上面。
- 立创 EDA 团队——愿意把扩展接口真正开放给社区，这个项目才有机会存在。谢谢。

### License

MIT
