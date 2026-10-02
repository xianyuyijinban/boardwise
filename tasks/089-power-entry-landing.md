# 089 — power-entry 真机落图（V3 test 工程）+ 视频 runbook 段

088+088b 已落账（`400837e`，语法离线半全绿），#55 闸分级已按岳裁决 B 实现（`draw apply`/
`edit apply` 三闸同口径：ERROR 必拦 / WARN `--force` 放行留痕 / INFO 只报告）。
本批把岳样板电源入口**落到真机**：XT30 入口 + TVS 贴入口 + 2×330µF、+24V/GND 实体轨、
旗在入口侧、GND 出处符号在远端——三裁决的真机呈现。

## 〇、前置（缺一直接停，R3）

- daemon 在 61190；编辑器开着、**焦点工程 = test**（`doc.list` 逐字核对）；多窗口一律
  `--instance` 路由。禁地照旧：毕设FOC驱动板 / CH340G.eprj2 / ROBOT ctrl FOC.eprj2 及一切真实工程。
- 真机坑表（`.kimi-code/skills/boardwise/SKILL.md` §6）先读：坑 33（真机符号单侧出脚）、
  坑 34/40（值拼写与 findings 闸——#55 新口径）、坑 35（真机落图用实测库）、坑 37/38
  （位号池时序，plan 与 apply 背靠背）、坑 42/43（旗标朝向按符号分家，SVG 解 text 核对）。

## 一、库探测（先探后定，找不到用替身并记录）

岳样板三颗料，按 SKILL §3.3 的探针手法量真实几何（别信离线假库，坑 35）：

1. **连接器**：XT30PW-M（两脚电源座）。探不到 → 任意两脚电源连接器替身，记录替身型号。
2. **TVS**：SMCJ28CA（样板 D1）。探不到 → 同系列 SMB/SMC 封装 TVS 替身。
3. **电解**：330µF THT（样板 CAP-TH_BD10.0-P5.00-D0.6-FD-A）。探不到 → 相近体格 THT 电解。
4. 旗标：`Power-+24V` 或电压声明形态轨名（坑 40 命名约定：`+24V` 形态跳过 param 规则误报）；
   `Ground-GND`。旗标自然姿态按坑 43 分家核对。

## 二、规格与编译

- 规格文件 `blocklib/specs/power_entry_xt30.json`（新）：CircuitSpec（rail `+24V` class=power、
  `GND` class=gnd、openInterfaces 带 `part` 指连接器）+ PresentationSpec（`grammarRef:
  power-entry`，模块声明 + **`branchOrder: ["D1", …]` TVS 最靠入口**（088b 裁决③），
  `sidePreferences.input` 按落图位置选）。
- **先离线编译亲看 SVG**（`draw compile` 或 tools 预览）再上机：形要像 088b 场景 1。
- 两个已钉的公共路径陷阱**绕开**：① 宽轨（≥4 成员）**不标 mainPath**（088 §七.a）；
  ② 编译**不声明 page_box**（088 §七.b 锚点吸附越页边会 0 候选）。

## 三、落图（#55 新闸下）

1. `draw plan` → 检查候选与 evidence；`draw apply`（plan 与 apply **背靠背**，坑 37）。
2. findings 闸预期行为：`param-rc-cutoff` 之类 INFO → 进报告不拦；若出 WARN（如 decap 对
   +24V 的要求）→ 评估后该 `--force` 就 `--force`（放行进 `forcedWarns` 留痕，交卷写明每条
   放行理由）；**出 ERROR 停下来报主代理**，不许 force。
3. 保存后 `export.render`（png+svg 双份，坑 42 手法解 SVG text 核位号/值/网名）。
4. **主代理亲看渲染**：对照岳样板三裁决逐项（TVS 贴入口 / 旗入口侧 / GND 符号远端竖直 /
   轨实体线 / 文字不压线）。
5. 回读验证：活网表分区、引脚回读、范围外零改动（`range.outOfScope.changed == []`）。
6. **撤场路径演练**：`draw discard` 把模块撤掉再走一遍落图（视频要拍「画坏可撤」）。

## 四、视频 runbook 段（本批第二交付物）

落 `docs/video-runbook.md`（新）：从「一句话需求」到「画布上的人样电源入口」的完整可复演
命令序列（每步命令 + 预期输出一句话 + 镜头提示），含撤场重画。写法照「给明天的自己看能
照抄」的标准。另起一段「审查线」空槽（FOC 偏置案的讲法，主代理后补）。

## 五、验收与纪律

- 真机纪律 R1–R3；audit log（`~/.boardwise/audit/`）本批动作列清单进交卷。
- 离线侧零回归：全量 pytest 绿（基线 **2974**，本批不改代码就不该动）；若真机实测逼出代码
  改动（如符号几何适配），按惯例先停报主代理。
- 交卷：库探测结论（含替身）、apply 报告关键字段、闸行为实录、渲染亲看结论、audit 清单、
  runbook 文件路径、遗留项。
