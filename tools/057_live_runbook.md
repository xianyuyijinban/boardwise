# 057 真机半：E1–E7 操作清单（在装了立创 EDA Pro 的机器上跑）

本批代码在一台**没有编辑器**的机器上完成：页级落图、census→keepout、页级锁、G4 回读、
`draw discard`、过期守卫都已接好，并用 `tests/test_057_draw_page_cli.py` 的假编辑器逐条跑过
（该假编辑器的页面真的会被写、被读、被删）。**真机结论一条都还没有**——下面是补真机半的逐步清单，
每一步都写了"看什么算过"。凡是本清单没写的动作，照 SKILL.md §4 的 R1–R3 办。

## 0. 每次动手前（R1–R3，逐字对）

```bash
boardwise bridge status                              # daemon 活着？死了先 `boardwise bridge start`
boardwise bridge call --action doc.list              # 焦点工程名必须逐字是 test（或 test2）
boardwise bridge call --action sys.identity          # consistent 必须是 true
```

- 工程名不是 `test`/`test2` → **停手**。禁地（毕设FOC驱动板、`CH340G.eprj2`、`ROBOT ctrl FOC.eprj2`、
  一切真实工程）任何情况下不写。每次 `bridge status` 与 `doc.list` 的原文贴进交卷记录。
- 用一张**新建的空页**做 E1/E3/E5/E7（`draw apply … --new-page`，或先建页再 `--page <uuid>`），
  E2 另开一张页、先手放几件东西。
- **库必须是实测库**（SKILL §3.3、坑 35）：`outputs/054_c1/measured_library.json`（0402 电阻/电容）加
  054 C3 / 055 G2 实测的 AMS1117 与 22µF 条目；`tests/fixtures/drawapply/library.json` 是假库，拿它
  上真机引脚回读必然 exit 3。
- 真机 AMS1117 单侧出脚（坑 33）：LDO 模块用 `"presentation": {"sidePreferences": {"input": "left",
  "output": "bottom"}}`；AMS1117 输出电容 ≥22µF（坑 34）；电容值带单位字母（`22uF`）。

## 1. 页规格（E1 用，E3/E5/E7 复用）

`e1.circuit.json`（`symbolRef` 换成实测库里对应条目的名字）：

```json
{"parts": [
  {"id": "U1", "symbolRef": "<AMS1117 实测>", "value": "AMS1117-3.3", "lcsc": "C6186", "provenance": "verified_recipe"},
  {"id": "C1", "symbolRef": "<0402 电容实测>", "value": "100nF", "lcsc": "C1525", "provenance": "verified_recipe"},
  {"id": "C2", "symbolRef": "<22uF 实测>", "value": "22uF", "lcsc": "C45783", "provenance": "verified_recipe"},
  {"id": "R1", "symbolRef": "<0402 电阻实测>", "value": "10k", "lcsc": "C25744", "provenance": "verified_recipe"},
  {"id": "R2", "symbolRef": "<0402 电阻实测>", "value": "10k", "lcsc": "C25744", "provenance": "verified_recipe"}],
 "nets": [
  {"id": "5V0", "class": "power", "members": ["U1.3", "C1.1", "R1.1"], "provenance": "verified_recipe"},
  {"id": "3V3", "class": "power", "members": ["U1.2", "C2.1"], "provenance": "verified_recipe"},
  {"id": "TAP", "class": "signal", "members": ["R1.2", "R2.1"], "provenance": "verified_recipe"},
  {"id": "GND", "class": "gnd", "members": ["U1.1", "C1.2", "C2.2", "R2.2"], "provenance": "verified_recipe"}]}
```

（AMS1117 的重复 VOUT 脚按坑 33 写进 `"nc": ["U1.4"]`，如果实测符号有它。）

`e1.presentation.json`：

```json
{"modules": [
  {"id": "pwr", "parts": ["U1", "C1", "C2"], "role": "regulator", "grammarRef": "ldo",
   "presentation": {"sidePreferences": {"input": "left", "output": "bottom"}}},
  {"id": "sense", "parts": ["R1", "R2"], "role": "divider", "grammarRef": "voltage-divider"}],
 "flow": [["pwr", "sense"]],
 "portRoles": {"5V0": "input", "3V3": "output"},
 "directWiringObligations": [{"nets": ["5V0", "3V3"], "note": "the regulator's own rails are wired"}]}
```

> **配方修正（2026-09-28 岳裁决，059 真机实测）**：输入轨原名 `VIN`。实测发现 `100nF` 电容与
> 10k 分压同挂 `VIN` 会命中工程规则 `param-rc-cutoff`（INFO，report-only），`draw apply` 的
> "findings 只减不增"按身份不看严重度 → exit 2 不保存（图落好了没落盘，与 054 C3a 同形，
> 证据 `outputs/057_live/e1/apply.txt`）。把轨名写成**自带电压声明的形态**（`5V0`/`+5V` 类，
> 011c whitelist）规则即按"已知电源轨=去耦"跳过，exit 0 正常保存（证据 `outputs/057_live/e1b/`）。
> 这不是版式问题，是命名约定：**电容与分压电阻共处的输入轨，轨名用电压声明形态**。

下文 `SPECS` = `--circuit e1.circuit.json --presentation e1.presentation.json --profiles <实测库>`，
`BOX` = `--page-box 0,0,1170,825`（A4 实测框，SKILL §3.3）。

## E1 空页多模块落图（全链 + 保存后重开仍在）

```bash
boardwise draw compile $SPECS $BOX --out outputs/057_e1/compile --json outputs/057_e1/compile.json
boardwise draw plan    $SPECS $BOX --page <空页 uuid> --project test \
    -o outputs/057_e1/plan.json --json outputs/057_e1/plan.report.json
boardwise draw apply   outputs/057_e1/plan.json --project test $SPECS \
    --layout outputs/057_e1/plan.page.json --render outputs/057_e1/render.png \
    --json outputs/057_e1/apply.json
```

算过：apply exit 0；`apply.json` 的 `verification.nets` 里 `crossModule: true` 的行（5V0、GND）全是
`oneNet: true`；`range.outOfScope.changed == []`；`render.png` **人眼看**（052 问法：哪颗电容属于哪路
电源？信号怎么走？改到愿意交给同事要几分钟？）。关闭重开工程后 `boardwise persistence …` 比对一致，
再跑一次同一条 `draw apply` → `already_applied` exit 0 零写入。

## E2 非空页落图（census → keepout，范围外零改动）

先在另一张页的左上角手放一颗电阻、画一段线、放一个 GND 旗标，然后：

```bash
boardwise bridge call --action sch.geometry --project test > outputs/057_e2/before.json   # 范围外基线（apply 报告的 range.outOfScope 自己也会逐项比）
boardwise draw plan  $SPECS $BOX --page <这页> --project test -o outputs/057_e2/plan.json \
    --json outputs/057_e2/plan.report.json
boardwise draw apply outputs/057_e2/plan.json --project test $SPECS \
    --layout outputs/057_e2/plan.page.json --render outputs/057_e2/render.png --json outputs/057_e2/apply.json
```

算过：`plan.report.json` 的 `keepouts[]` 逐条点名那三件（件的框是 `bboxIds` 实测，`notes` 里没有
"assumed"）；模块框不压它们；apply exit 0 且 `range.outOfScope.items` = 3、`changed == []`。
再做一次"罩满"：把页面铺满（或把手放件摆满可行位置）→ `draw plan` exit 5，`[presentation-poor]`
点名 `existing …`，零写入。

## E3 页级 userLock

在 `e1.presentation.json` 加 `"userLocks": [{"partId": "R1", "x": 800, "y": 500, "scope": "page"}]`
（`x/y` 取页内、在网格上的点），`draw plan --page <新空页>` → `draw apply`。

算过：`bridge call --action sch.geometry` 读回 R1 的 `X/Y` == (800, 500)。冲突：两把页锁互相矛盾
（R1、R2 钉同一点）、锁点出页、锁住 U1 让框出页——`draw plan` exit 5，`[presentation-poor]` 点名锁
（`userLocks[R1@page]`）。

## E4 G4 工程级合并 + findings 只减不增（按身份）

E1 的 `verification.nets` 已证共享网一网。findings：在 `test` 工程另一页放一颗缺输出电容的 AMS1117
（它挂 3V3、会报 `decap-required-caps`），再落 E1 页（3V3 上带 22µF）。

算过：`apply.json` 的 `findings.resolved` 含那条（身份 `decap-required-caps|WARN|U?|2|3V3`），
`findings.new == []`；若出现"修一个引入一个"，计数不变但 `new` 非空 → exit 2 不保存（身份判，不按计数）。

## E5 `draw discard`

```bash
boardwise draw discard outputs/057_e1/plan.json --project test --json outputs/057_e5/discard.json
boardwise draw discard outputs/057_e1/plan.json --project test --json outputs/057_e5/discard2.json
```

算过：第一遍 exit 0，`deletes` 顺序 wires → flags → parts，`verify.remaining == []`、`verify.outOfScope
== []`（页上别的东西没动）；第二遍 `nothing_to_discard` exit 0、零删除。身份不符：重新 apply 后在编辑器里
手改 R1 的值（或挪 R1），discard → exit 4、`selection.mismatches` 点名 R1、**零删除**。`--save` 才保存；
删除 ~3.7 s/件（坑 2），E1 页约 18 个图元约 1 分钟。

## E6 CH340G 完整模块

离线已实测（`tools/057_scenarios.py` → `outputs/057_offline/E6_ch340g.txt`）：核心/晶振/USB 三组**没有
文法**，页级编译 `facts-missing` 点名三个模块；金样板 RT9013 在 `ldo` 文法下 48 种 sidePreferences 全部
无合法姿态。**真机半被编译阶段挡住**，不许为通过特调（052 原话）——等 058 的文法再落。

## E7 过期 plan / 页文档守卫

```bash
boardwise draw plan  $SPECS $BOX --page <新空页> --project test -o outputs/057_e7/plan.json
# 手工在这页放一颗件（或挪动任意图元）
boardwise draw apply outputs/057_e7/plan.json --project test $SPECS --json outputs/057_e7/apply.json
```

算过：exit 4、`reason: canvas_changed`，`steps` 里没有任何写动作，没有保存。页文档直落
（`draw apply outputs/057_e1/compile/cand1.page.json --page <页> $SPECS`）：手放的件压到页文档的模块框
→ exit 4 `canvas_changed`；没压到 → 照常落（页文档的守卫是"框对现状的 keepout 规则"；要"任何变动都拒"
用 `draw plan --page` 产的 plan 或 `--expect-census`）。
