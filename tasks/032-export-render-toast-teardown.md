# 032 export.render 进度条自清除（issue #5 症状正案）

## 背景

岳 2026-09-24 在 3.2.149 的新证据**推翻了 issue #5 的部分诊断**：

- checkup 画布阶段 PNG **成功**（`canvas-sch.png` 664172B 落盘，无 pngError、无 format:svg，回退零触发），
  编辑器**照样卡在 99%**。同日另一窗 `canvas-P1.png` 326KB 成功 + 卡 99%，同形。
- 结论：**UI 卡死与导出成败无关**——是 ManufactureData 导出管线**漏进度条 toast**，成功也漏、超时也漏。
  031 的"PNG 短绳 + SVG 回退"修的是"checkup 不再因超时失败"（真改进），**不阻止 UI 卡死**；
  issue #5 不按"已修复"关闭。

上游 easyeda-agent 有**同款症状的实锤与现成修法**（其 `extension/src/actions.ts` schematicExportImage 的
finally 块，注释原文）："the export resolves (2-3s, file delivered) but the editor's progress bar stays
stuck at 99% until the user closes it by hand (live-reported twice)"——他们在 finally 里 400ms 后调
`eda.sys_LoadingAndProgressBar.destroyProgressBar()` + `destroyLoading()`（两者 @public、幂等、
无进度条时调用安全；live 实证 `showProgressBar(99)` → `destroyProgressBar()` 清除）。
延迟 400ms 是为了不跟平台自己的 teardown 抢跑；超时路径同样能清掉卡 1% 的 toast。

`sys_LoadingAndProgressBar` 在 3.2.149 的 99 命名空间探针清单里**在册**（岳 2026-09-24 探针），
本批真机要补 typeof 核成员。

## 工作项

### 1. connector `exportRender`（0.4.21）

- 导出调用区包 try/**finally**：finally 里 `setTimeout(400ms)` → typeof 守卫后 best-effort 调
  `destroyProgressBar()` 与 `destroyLoading()`（各自 try/catch，任何失败不影响导出结果）。
  两条路径（成功 / TIMEOUT）都走 finally。
- TIMEOUT 文案末句改：不再说"reload the document to clear it"——connector 自己 ~0.4s 后拆 toast；
  仍挂着才 reload。
- 版本 0.4.20 → **0.4.21**（extension.json + package.json + dist 重建 + source-guard 版本断言）。
  只动 export.render，daemon 零改动。

### 2. connector 测试

- 假 eda 挂 `sys_LoadingAndProgressBar` 记录调用：**成功**与**超时**两条路径各自断言 teardown 被排期
  （捕获 setTimeout 回调手动触发），且 destroy 抛错不影响导出结果/报错形状。
- 缺 `sys_LoadingAndProgressBar` 命名空间时静默跳过（typeof 守卫用例）。

### 3. 文档

- SKILL.md 坑 23 **修订**：卡死 = 导出管线漏 toast，**与导出成败无关**（岳 149 两次实测：成功也卡）；
  connector 0.4.21 起自清除；031 的 PNG→SVG 回退仍是"PNG 超时"的兜底，两件事别混。
- `docs/bridge.md` export.render 行 + §10.28 修订（同口径）。

### 4. 真机（本机 3.2.186，只碰 test 窗）

- 热更 0.4.21 到 test 窗（`--instance` 显式寻址，先 `bridge status` 读 id）；test2/ROBOT 不寻址。
- PNG 渲染回归（字节 + magic）。
- `sys.probe` 核 `sys_LoadingAndProgressBar.destroyProgressBar` / `destroyLoading` typeof=function。
- 证据 `outputs/032_*.txt`。

### 5. 不做

- 149 marker A/B 仍不做；**真正的视觉验收归岳**：149 上跑一次 checkup/render，卡 99% 的 toast 应在
  ~1 秒内自己消失（031 的回退与 032 的自清除叠加后，149 上 checkup 应既不败也不留疤）。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 ≥2（cp 备份 + sha256/cmp 还原，禁 `git checkout --`）；
真机只碰 test 窗，ROBOT 禁地全程只读；不碰 git 与 PROGRESS（主代理收尾）。

## 交卷记录

### 032 · 交卷（2026-09-24，子代理 agent-43；摘要 `outputs/032_summary.txt`）

- **connector 0.4.21**：`exportRender` 导出调用区包 try/**finally**——`scheduleExportTeardown(eda)`
  在应答后 400ms best-effort 调 `sys_LoadingAndProgressBar.destroyProgressBar()` + `destroyLoading()`
  （`readMember` 读命名空间而非 `namespaceOf`——后者缺命名空间会抛 NOT_IMPLEMENTED，与 best-effort
  相悖；逐个 typeof 守卫、各自 try/catch）。**成功与超时两条路径都拆**（成功路径才是正案——岳 149
  实测成功也卡）。TIMEOUT 文案末句改：connector 应答后 ~400ms 自拆，仍挂着才 reload。
- **测试**：connector +3 条（成功 / 超时+refusing host / 缺命名空间）→ **410 passed**；pytest 未动
  python，**1447** 不变；tsc 干净。变异 **2/2 CAUGHT**（M1 删 finally teardown → 3 红；M2 拆
  try/catch → 1 红）。dist 构建确定性可复现（两次同 sha `15cfc732…`，255504B）。
- **真机（186，只碰 test 窗）**：热更 0.4.21 verified（新连接 `inst-065453418-6y202jn4`）；
  `sys.probe` 核 `destroyProgressBar`/`destroyLoading` typeof=function arity=0；PNG 回归 156678B
  **sha256 与 031 那次逐字节相同**（teardown 不影响渲染内容）；超时腿复核出新文案末句。
  ROBOT 0.4.17 / test2 0.4.19 全程未寻址。
- **文档**：SKILL 坑 23 改写（卡死 = 导出管线漏 toast，与成败无关；0.4.21 起自清除；031 回退是
  另一件事——超时的兜底）；bridge.md export.render 行 + §10.28 同口径。

### 主代理复验（2026-09-24）

- sha256 抽核 7 件（6 跟踪文件 + dist `15cfc732…`）与交卷值逐字一致 ✔；
- 三线复跑：pytest **1447**（111s，python 未动）/ connector **410 pass 0 fail** / tsc 干净 ✔；
- 变异记录定向红、还原 sha 回基线 ✔；
- **子代理遗留①（149 视觉验收）**：转给岳——本机 186 不留 toast，自清除效果只能在 149 上看
  （跑 checkup 或任意 export.render，卡 99% 的进度条应 ~1s 内自灭）。验收通过前 issue #5 保持开放。
- **子代理遗留②（"上游现行源码已看不到那段 finally"）**：**不成立**——引文来源是主代理当日 10:51
  从上游 main 分支实拉的 `extension/src/actions.ts:4240-4254`（finally + 400ms setTimeout +
  两个 destroy 调用，注释原文照录于本任务书 §背景），亲见。子代理大概查了过时克隆或别的路径，
  不影响本批实现（按引文移植，且有 live 实证背书）。
