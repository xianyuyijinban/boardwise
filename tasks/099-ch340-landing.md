# 099 — CH340 真机落图（ic-periphery 首落，V3 test 工程）

098 已落账（`3a4b963`，ic-periphery 离线半全绿、CH340 样板离线亲看过）。本批把它落到真机：
**CH340G + 12MHz 晶振 + 2×22pF 负载 + 100nF 去耦 + 100nF V3 电容 + VCC/GND 旗 +
TXD/RXD/D+/D− 四条声明侧标签**，落 test 工程**新建页 P24**（P1 是 089 的电源入口，不混）。
**先读** `tasks/089-power-entry-landing.md`（真机流程与纪律同款）、`.kimi-code/skills/boardwise/SKILL.md`
§3 流程与 §6 坑表（坑 33/34/35/37/38/40/42/43）、`tests/test_098_ic_periphery.py` 的
`sample_circuit()/sample_presentation()`（场景构造唯一出处——真机规格照它的形状写）。

## 〇、前置（缺一直接停，R3）

- daemon 61190；单窗口 `inst-143042355-nq65k59v`，工程 **test**（uuid `ea80fff6…`），
  当前页 P1。页清单应是 `P1 / P22 / P23 + PCB1`——P22/P23 全程**不许寻址**。
- 098 的两个真机陷阱（交卷 §8 给的）：**`near` 的 300 上限**（挂脚件别离核心太远，符号
  实测脚距大的话先离线编译确认有候选再上机）；**不给声明侧两个镜像都合法**（规格里
  必须写声明侧——TXD/RXD 朝 MCU 侧、D+/D− 朝 USB 侧，照 098 场景 1 的声明写）。

## 一、库探测（SKILL §3.3 探针手法，先探后定）

| 角色 | 首选 | 找不到的替身与记录 |
|---|---|---|
| 核心 CH340G | CH340G（SOP-16） | CH340C（内置晶振——那晶振簇就没了，**不许**用，换 CH340N/CH340B 同理慎用；真没有就换一颗 SOP-16 的多脚 IC 当核心并记录） |
| 晶振 | 12MHz HC-49S（THT 或 SMD 两脚） | 相近频点两脚晶振 |
| 负载 | 22pF 0603 | 同值别封装 |
| 去耦/V3 | 100nF 0603 | 同值别封装 |
| 旗标 | `PWR-VCC` / `Ground-GND`（坑 43 姿态分家核对） | — |

探针页用 `sch.doc.new` 临时建、探完删页（回收站纪律管的是文件不是编辑器图元——
编辑器内删除走 `sch.delete_primitives`/`doc.delete_page` 正常用）。每颗件实测几何
（脚距/体框/脚向）写进规格库的 `source`。

## 二、规格与编译

- `blocklib/specs/ch340_serial.{circuit,presentation,library}.json`（三件套，089 的先例）：
  CircuitSpec（VCC class=power、GND class=gnd、四条信号网、六颗件全带 lcsc）；
  PresentationSpec（`grammarRef: ic-periphery`、模块 `serial` 声明 `core: "U1"`、
  四条信号的声明侧照 098 场景 1）。
- **先离线编译亲看 SVG**（形要像 098 scene01）再上机；页级 mainPath 本批**不碰**。
- plan 与 apply **背靠背**（坑 37）；P24 建新页落图。

## 三、落图与验收（#55 闸下）

1. `draw plan` → `draw apply`：预期 `probe not_satisfied` → 写件/写值/走线/旗 →
   双证回读过 → `range.outOfScope.changed == []` → 保存。
2. 闸行为：INFO 不拦；WARN 评估后该 `--force` 就 force 并逐条写理由；**ERROR 停下报主代理**。
3. `export.render`（png+svg，坑 42 手法解 SVG text 核位号/值/网名/旗朝向）。
4. **主代理亲看渲染**：对照 098 scene01 逐项（晶振簇贴晶振脚侧 / 去耦贴 VCC 脚 /
   V3 电容贴 V3 脚 / 四条标签朝向 / 文字不压线 / 旗竖直）。
5. 回读：活网表分区、8 脚位逐脚（晶振簇+去耦+V3 各就位）、范围外零改动。
6. 撤场演练：`draw discard` 清 P24 → 同 plan 重落 → 两次渲染 sha256 相同。
7. `docs/video-runbook.md` 补一段「CH340 模块」（命令序列+镜头提示，接在 089 那段后）。

## 四、验收与纪律

- 真机纪律 R1–R3；audit 动作清单进交卷；编辑器只动 test 工程、只建/删 P24 与探针页。
- 离线侧零回归：全量 pytest 绿（基线 **3225**，本批不改代码就不该动）；真机逼出代码改动
  先停报主代理。
- **删除一律进回收站（红线#4）**；不动 git、不写 PROGRESS。
- 交卷：库探测结论（含替身）/规格三件套路径/apply 报告关键字段/闸行为实录/渲染亲看材料/
  回读验证/撤场演练/audit 清单/runbook 段落路径/遗留项。
