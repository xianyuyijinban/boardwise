# 视频 runbook：从一句话需求到画布上的电源入口

这一段视频要演完一件事：**一句「把 24V 电源入口画到这张页上」，人看着画布长出连接器、TVS、
两颗 330µF 电解、两条实体轨、入口侧的 +24V 旗和远端的 GND 出处符号；然后把它撤掉再画一遍**，
证明「画坏了能撤、撤了能重画」。

命令照抄即可，每步都写了「预期什么算过」和「镜头给哪」。产物落在 `outputs/089/`。

- 环境：Windows + Git Bash，仓库 `E:\boardwise`，编辑器开着 **test** 工程，
  daemon 在 `127.0.0.1:61190`（`bridge start` 起，死了先重启——动作表是加载期常量，
  改过代码必须重启才生效）。
- 真机纪律：写动作只碰 `test` / `test2`；动手前先核身份（第 0 步）。
- 本批落图目标页 = **P1**；`P22`/`P23` 是参照页，**全程不写**。

## 0. 固定几个值（后面每条命令都用）

```bash
cd /e/boardwise

SPECS="--circuit blocklib/specs/power_entry_xt30.circuit.json \
       --presentation blocklib/specs/power_entry_xt30.presentation.json \
       --profiles blocklib/specs/power_entry_xt30.library.json"
BOX="--page-box 0,0,1170,825"          # A4 实测框（geomentry 读出来的 1170×825）
WIN="--project test --instance <windowKey>"   # `bridge status` 打印的窗口 id
P1=<P1 的 pageUuid>                    # `doc.list` 现读，别抄旧的
```

> `P1` 的 uuid 会随工程重建而变（本批实测机器上是 `b4298962367251c8`）。
> 每次开工现读一次，脚本里别写死。

## 1. 开场：先证身份，再动手（R1）

```bash
.venv/Scripts/python.exe -m boardwise.cli bridge status
.venv/Scripts/python.exe -m boardwise.cli bridge call --action doc.list $WIN
.venv/Scripts/python.exe -m boardwise.cli bridge call --action document.current $WIN
```

预期：`bridge status` 报 `daemon up` + `connector: connected` + 一个窗口；`doc.list` 的焦点
工程名逐字是 `test`、页清单恰好 `P1 / P22 / P23 + PCB1`；`document.current` 的活动文档就是
`P1.Schematic1`，两边工程名一致。

镜头：屏幕给 `bridge status` 那两行 `connector: connected` 与 `project test`；
再说一句「不是 test 就停手，一个字都不许写」。

## 2. 库探测：三颗料在不在库里（找不到才用替身）

```bash
for k in XT30 SMCJ28CA 330uF; do
  .venv/Scripts/python.exe -m boardwise.cli bridge call --action lib.device.search \
      --params "{\"keyword\":\"$k\",\"limit\":20}" $WIN
done
```

预期：三条都有命中。本批实测结论（**三颗料都是真料，没用替身**）：

| 角色 | 型号 | LCSC | 封装 |
|---|---|---|---|
| 入口连接器 | XT30PW-M36（2 脚，同族 XT30PW-M） | C9900222726 | CONN-TH_2P-P5.00_XT30PW-M36 |
| TVS | SMCJ28CA | C356792 | SMC_L6.9-W5.9-LS7.9-BI（SMC/DO-214AB） |
| 电解 | 330uF25V10x13GF | C49332876 | CAP-TH_BD10.0-P5.00-D0.6-FD…（样板同族） |

镜头：搜索结果里把三行点出来（型号 + C 码）；一句话说「型号对得上就不许拿替身凑」。

## 3. 量符号几何：别信离线假库（真机坑 35）

这一步是整段视频的「专业时刻」：编辑器**不提供**库符号几何的读接口，所以先在临时页上放真件、
量完再删。**跳这一步，后面 `draw apply` 会在拉线前 exit 3。**

```bash
CLI=".venv/Scripts/python.exe -m boardwise.cli bridge call"
PROBE=$($CLI --action sch.doc.new --params '{"name":"P89_PROBE"}' --yes $WIN \
        | .venv/Scripts/python.exe -c "import json,sys; print(json.load(sys.stdin)['pageUuid'])")
# 放三颗探针件（坐标随便挑，量的是相对偏移）
$CLI --action sch.place_component --params '{"lcsc":"C9900222726","x":200,"y":600,"pageUuid":"<PROBE>"}' $WIN
$CLI --action sch.place_component --params '{"lcsc":"C356792",  "x":500,"y":600,"pageUuid":"<PROBE>"}' $WIN
$CLI --action sch.place_component --params '{"lcsc":"C49332876","x":800,"y":600,"pageUuid":"<PROBE>"}' $WIN
# 旗标也要量（Power 与 Ground 两家字形朝向相反，坑 43）
$CLI --action sch.place_power --params '{"kind":"Power","net":"+24V","x":200,"y":450,"pageUuid":"<PROBE>"}' $WIN
$CLI --action sch.place_power --params '{"kind":"Ground","net":"GND","x":500,"y":450,"pageUuid":"<PROBE>"}' $WIN
# 逐个量：引脚偏移（component_pins）+ 外框（geometry 的 bboxIds）
$CLI --action sch.component_pins --params '{"primitiveId":"<id>"}' $WIN
$CLI --action sch.geometry --params '{"bboxIds":["<id>", …]}' $WIN
```

预期（本批实测数，写进了 `blocklib/specs/power_entry_xt30.library.json`）：

- XT30PW-M36：两脚都在**左侧** 20 单位处、上下只差 **10**（(180,605)/(180,595) 对原点 (200,600)），
  body `(-10.5,-15.5,10.5,15.5)`；
- SMCJ28CA：两脚左右 ±20（480/520），body `(-10.5,-5.5,10.5,5.5)`；
- 330uF THT：两脚左右 ±20（780/820），body `(-10.5,-7.5,10.5,7.5)`；
- `Power` 旗：连接点就在原点，字形往上伸（+4.5…+10.5）；
  `Ground` 旗：连接点在原点，三道横杠往下挂（−9.5…−19.5）——**两家反着**。

量完清场（先删件、再删页）：

```bash
$CLI --action sch.delete_primitives --params '{"pageUuid":"<PROBE>","primitiveIds":[…5 个 id…]}' $WIN
$CLI --action sch.doc.save $WIN
$CLI --action doc.delete_page --params '{"pageUuid":"<PROBE>"}' $WIN
$CLI --action sch.doc.save $WIN
```

镜头：临时页上四颗料 + 两个旗标的画面；量完一条删除回空页。说一句「探针件不许留在页上」。

## 4. 三份规格文件（这就是「一句话需求」的落地形态）

- `blocklib/specs/power_entry_xt30.circuit.json` —— **电路是什么**：
  `+24V`（class=power，成员 CN1.1/D1.1/C115.1/C116.1）、`GND`（class=gnd，各 .2），
  `openInterfaces` 在 +24V 上写 `{"direction":"input","role":"rail","part":"CN1"}`——
  「这条轨的入口是 CN1」是语法**推导不出来**的那一条事实。
- `blocklib/specs/power_entry_xt30.presentation.json` —— **该怎么读**：
  `grammarRef: power-entry`、`sidePreferences.input: left`、
  模块 `inlet` 声明 `branchOrder: ["D1","C115","C116"]`（**TVS 最靠入口**，岳 2026-10-02 裁决③）。
- `blocklib/specs/power_entry_xt30.library.json` —— 第 3 步**量出来的**符号库
  （三颗器件的 body/引脚 + `PWR-+24V`/`PWR-GND` 两个旗标 profile）。

镜头：三份文件并排，重点给 `branchOrder` 那一行和 `part: "CN1"` 那一行。

```bash
$CLI --action lib.device.search … # （不需要，仅示意）
```

## 5. 离线编译：先看清画法，再上机

```bash
.venv/Scripts/python.exe -m boardwise.cli draw compile $SPECS $BOX \
    --out outputs/089/draw/compile --json outputs/089/draw/compile.json
```

预期：`2 page candidate(s), 0 failure(s)`，排名两个候选的 `legality=0, findings=0, crossings=0`；
写出 `cand1.svg / cand1.page.json / cand2.svg / cand2.page.json`。

镜头：浏览器打开 `outputs/089/draw/compile/cand1.svg`，指一遍「顶轨 +24V、底轨 GND、三条支路
竖挂、D1 在最左（最靠入口）」；再说「离线先看，不满意就改 spec，不用在编辑器里反复试错」。

## 6. 落图：plan 与 apply 背靠背（坑 37）

```bash
# plan 与 apply 之间不要手放件、不要 discard：位号池会变
.venv/Scripts/python.exe -m boardwise.cli draw plan $SPECS $BOX --page $P1 $WIN \
    -o outputs/089/draw/plan.json --json outputs/089/draw/plan.report.json
.venv/Scripts/python.exe -m boardwise.cli draw apply outputs/089/draw/plan.json $WIN $SPECS \
    --layout outputs/089/draw/plan.page.json \
    --render outputs/089/draw/render.png --json outputs/089/draw/apply.json
```

预期：`draw plan` 报 `[planned]`，4 件 / 4 线 / 2 旗，页 census `0 part(s), 0 wire(s), 0 flag(s)`；
`draw apply` **exit 0**，逐段打印：

- `guards checked circuitSha256, presentationSha256, layoutSha256, profiles, pageUuid, census`
- `write 14 call(s)`：4 件 → 4 个 `Value` 写回 → 4 条线 → 2 个旗
- `verify live ok · canvas ok` + 8 条 island（+24V 4 脚、GND 4 脚）
- `range … outOfScope: {items: 0, changed: []}`
- `findings … new: [], newBySeverity: {ERROR: [], WARN: [], INFO: []}`（**没有闸触发 = 不需要 `--force`**）
- `values 4/4 written · read back and equal`
- `save {"ok": true}` / `render … bytes: 168926` / `persistence: saved_unverified`

镜头：整屏给 apply 的输出；在 `verify live ok · canvas ok` 和 `range … changed: []` 上各停一下，
说「落图同时给了两路证据：编辑器自己的网表 + 画布」。

> **闸行为**：`findings` 分级是 ERROR 必拦 / WARN 需 `--force` 放行（放行的写进
> `findings.forcedWarns` + notes）/ INFO 只报告。本批实测基线里那条
> `decap-required-caps|WARN|U1|2|VCC` 是别的页（U1）的，本批 `new: []`，**一次 `--force` 都没用**。
> 真撞上 ERROR：停下来报，不许 force。

## 7. 出图 + 逐条对样板

```bash
$CLI --action export.render --params '{"format":"png","scope":"page","pageUuid":"'$P1'"}' $WIN
$CLI --action export.render --params '{"format":"svg","scope":"page","pageUuid":"'$P1'"}' $WIN \
  | .venv/Scripts/python.exe -c "import json,sys,base64; d=json.load(sys.stdin); \
      open('outputs/089/draw/render.svg','wb').write(base64.b64decode(d['data']))"
```

预期：PNG 168926 B（`sha256=ccb5d2de…`，两次落图逐字节一致）；SVG ≈71.5 KB
（两次渲染只有宿主自己发的主元 id 不同，几何一字不差）。
**PNG 给人看，SVG 给机器看**（`<text>` 节点渲染内容的机器可读记录；`c_partid="netflag"`
组能读「连接点 → 字形往哪边伸」，这正是两族旗标朝向的判据）。

镜头：PNG 上按四条线走一遍（岳样板三裁决 + 轨实体）：

1. **TVS 最靠入口**：CN1（x=140）→ D1（220）→ C115（280）→ C116（340）；
2. **+24V 旗在入口侧**：旗在 (190,765)，引线竖直落在 x=190 的轨上（轨 160→340）；
3. **GND 出处符号在远端、竖直**：符号在 (340,670)，挂在下轨的**最右端**，rot 0；
4. **两条实体轨**：+24V 一条水平线 (160,740)→(340,740)；GND (160,730)→…→(340,700)
   ——这条轨在入口附近下一个台阶（连接器两脚只差 10 单位，支路两极差 40，落差只能靠一段竖直拐）；
5. 文字（C4/C5/CN1/D1 的位号与值）都在件旁边，不压线。

## 8. 回读验证：三路独立读数

```bash
$CLI --action sch.readback $WIN                                   # 页上 4 件 + 2 旗
$CLI --action sch.netlist  $WIN                                   # 活网表：分区
$CLI --action sch.geometry $WIN                                   # 画布：坐标/线/旗
$CLI --action sch.component_pins --params '{"primitiveId":"<id>"}' $WIN   # 逐脚
```

预期：网表里 `C4.1/C5.1/CN1.1/D1.1 → +24V`、`C4.2/C5.2/CN1.2/D1.2 → GND`，`Value` 字段
非空（`330uF / XT30PW-M36 / SMCJ28CA`）；四件的每个引脚相对原点与 plan 的期望逐脚一致
（本批实测 8/8 全中）。

镜头：网表 JSON 上把 `+24V` / `GND` 两个键点给观众看。

## 9. 撤场重画：画坏了能撤（本段的收尾戏）

```bash
.venv/Scripts/python.exe -m boardwise.cli draw discard outputs/089/draw/plan.json $WIN \
    --save --json outputs/089/draw/discard.json
$CLI --action sch.geometry $WIN          # 预期：只剩图框 sheet，0 线 0 旗
# 再画一遍（同一条 apply）
.venv/Scripts/python.exe -m boardwise.cli draw apply outputs/089/draw/plan.json $WIN $SPECS \
    --layout outputs/089/draw/plan.page.json \
    --render outputs/089/draw/render2.png --json outputs/089/draw/apply2.json
```

预期：`discard` 逐件 `match` + 逐相删除（线 → 旗 → 件），`verify remaining [] ·
out of scope unchanged`，`save ok`；`sch.geometry` 回空页；再 apply 仍 **exit 0**，
且 `render2.png` 与第一次的 PNG **sha256 相同**（同一张图，重画不漂）。

镜头：`draw discard` 的输出 + 画布上模块消失的瞬间；再说一句「撤场只删这个 plan 自己画的东西，
按位号 + 坐标 + 值核身份，一件对不上就整批不删」。

## 10. 收尾

```bash
.venv/Scripts/python.exe -m boardwise.cli bridge call --action doc.list $WIN   # 工程清单原样
ls -l outputs/089/draw/render.png outputs/089/draw/render.svg
```

预期：工程还是 `P1 / P22 / P23 + PCB1`；`P1` 上留着画好的电源入口；产物四件齐
（`render.png` / `render.svg` / `apply.json` / `discard.json`）。

---

## 审查线（FOC 偏置案的讲法）

> **主线**：「规则全绿的板子，照样藏着五个数量级的错。」这一段不操作命令，讲的是
> 已经审完的证据（`outputs/ctrlfoc_20261001/review-findings.md`，一块 24V FOC 驱动板，
> 公司细节不出镜——口播就叫「一块 24V FOC 驱动板」，位号可以露，板子全貌不截全屏）。

**节拍 1（10 秒，抛问题）**：FOC 电流采样是双极性的，母线电流有正有负，所以采样节点
必须抬到 1.65V 偏置上。这块板第一版没做偏置——上一轮审查查出来了，工程师补了一套。

**节拍 2（20 秒，翻证据）**：镜头给活网表（`sch.netlist` 摘录）：
`U+: DRV1.6(PGND1), R17.2, R4.2, U1.21(PA7)` + `VCC/2: R10.1, R16.2, R17.1, R18.1`。
口播：R10/R16 两个 1k 分压出 1.65V，再经 R17/R18 两个 10k 往采样节点送。看着有偏置了？

**节拍 3（30 秒，上算术——全片最重的 30 秒）**：白底大字写这个除法：

```
V(采样节点) = 1.65V × 0.1Ω / (500Ω + 10000Ω + 0.1Ω) ≈ 15.7 µV
```

口播：采样电阻只有 0.1 欧，想让节点坐到 1.65V，偏置源内阻必须远小于 0.1 欧——
500 欧串 10k 送进来，物理上就做不到。想要 1.65V，实得 **15.7 微伏，差 5 个数量级**。
正确形态是运放跟随器低阻送入。所以这套「补上的偏置」电气上等于没有，反向电流依然测不到。

**节拍 4（15 秒，点题）**：这套算术不是 AI 现场编的——审查报告里每条 finding 都带
网表证据、器件值、手册页码（DRV8313 p.3：nFAULT 开漏要上拉；VM 每脚 0.1µF）。
镜头扫 review-findings.md 的发现表（F1–F12）。收一句：**规则引擎报 0 ERROR，
但规则绿不等于没问题——这就是 harness 比 skill 值钱的地方。**

镜头素材清单：`review-findings.md` 的 F1 证据节、活网表文本、DRV8313 手册 p.3 截图、
算术大字卡。命令不用真跑（审查已过）；要现场感就在编辑器里打开该工程翻 `VCC/2` 那几颗电阻。
