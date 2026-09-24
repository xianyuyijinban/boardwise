# 034 activateExportPage 补 activateDocument 半步（issue #5 毛病 A 复修）

## 背景

033（0.4.22）验收**未过**（岳，3.2.149 + 0.4.22 热更 verified）：页面刚载入裸调 `export.render`
仍 TIMEOUT ×2（新文案在跑，排除旧 build）；`doc.open` 后紧接着裸调 **2 秒成功**。

岳把根因钉到行：`activateExportPage` 只调了 `dmt_EditorControl.openDocument(uuid)`
（**开标签页**，是否拿走输入焦点是宿主的事），漏了 `doc.open`（`connector/src/actions.ts:2870` 起）
的另外两步——`activateDocument(tabId)`（**切前台激活**）+ `getCurrentDocumentInfo()` 回读确认
`matchesRequest`。033 把激活责任收进了连接器，方向对，**只收了一半动作**。

附带定案：H1/H2 不必分离——实测表明**每次导出前都要 activate**（不是"载入后激活过一次即可"）。
032 的 toast teardown 在本次验收路径上再次生效（累计 4 样本）。

## 工作项

### 1. connector（0.4.23）——`activateExportPage` 对齐 doc.open 的完整三步

- `openDocument(uuid)` → tabId（拿不到 tabId → 沿用现有 locate/describe 诊断，拒绝导出，不变）；
- **新增** `activateDocument(tabId)`（入参是 tab id 不是 uuid——doc.open 注释里的原话）；
- **新增** `getCurrentDocumentInfo()` 回读，`matchesRequest === true` **才导出**；
  激活/回读任何一步不成立 → 拒绝导出（"The export was NOT attempted" 语义保持不变——岳明确说这个行为是对的）。
- 结果继续带 `activatedPageUuid`，可补 `activated: true` 字样（与 doc.open 的回执风格一致）。
- 版本 0.4.22 → **0.4.23**（extension.json + package.json + dist 重建 + source-guard 断言）。
  只动 exportRender 的激活腿，daemon 零改动。

### 2. connector 测试

- 调用顺序断言：`openDocument` → `activateDocument(tabId)` → `getCurrentDocumentInfo` →
  `getExportDocumentFile`（四步次序钉死）；
- `activateDocument` 返回 false / 抛错 → 拒绝导出；
- 回读 `matchesRequest === false` → 拒绝导出；
- 缺 `activateDocument` 函数 → 诚实报错拒绝导出（不降级成"试试看"，149 实测降级=挂死）。

### 3. 文档

- SKILL.md 坑 23 补一句：`openDocument` ≠ `activateDocument`（开标签 vs 切前台，入参 uuid vs tabId），
  导出前必须**两者都做 + 回读确认**；H1/H2 定案 = 每次导出前都要 activate。
- `docs/bridge.md` §10.28 同口径补一句。

### 4. 真机（本机 3.2.186，只碰 test 窗）

- 热更 0.4.23（`--instance` 显式寻址）；回归：带 `pageUuid` 导出（active 真换页）+ 无参路径。
- 证据 `outputs/034_*.txt`。

### 5. 验收归岳（149）

窗口刚载入、不 doc.open，裸调 `export.render` 应直接成功——这次激活是完整三步，
和 17:33 那次 `doc.open` 后成功所走的动作完全一致。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 ≥2（cp 备份 + sha256/cmp 还原）；
真机只碰 test 窗；不碰 git 与 PROGRESS；交卷文本同时写 `outputs/034_summary.txt`。
**不许**把激活降级成 best-effort（033 变异 M2 已经钉死这条性质）。

## 交卷记录

### 034 · 交卷（2026-09-24，子代理 agent-43；摘要 `outputs/034_summary.txt`）

- **connector 0.4.23**：`activateExportPage` **直接复用 `docOpen` 处理器**（`openDocument(uuid)` →
  `activateDocument(tabId)` → `getCurrentDocumentInfo()` 回读），不另抄三步——同一份"把某页变成
  活动文档"的实现，导出与 `doc.open` **结构上不可能漂移**；no-tab-id 诊断原样透传。**严格不降级**：
  `activated === true` 且 `matchesRequest === true` 才导出，否则拒绝（editorCalls 断言钉死
  "The export was NOT attempted" 语义）；结果带 `activatedPageUuid` + `activated: true`（仅 scope=page）。
  daemon / cli.py / checkup 一字未动。
- **测试**：connector → **419 passed**（四步顺序 + 四种拒绝形态 + 无参自激活）；pytest **1447** 不变；
  tsc 干净。变异 **2/2 CAUGHT**（M1 严格判据放宽成恒真 → 4 红；M2 退回 033 单步激活 → 7 红）。
- **真机（186，只碰 test 窗）**：热更 0.4.23 verified（新连接 `inst-094842387-86etbxar`）；
  带 `pageUuid` 导 P3 → 导出后 doc.list 的 active **真切成 P3**（activateDocument 真把前台切过去了）；
  无参与有参 sha256 逐字节相同（`0860590027…`）。ROBOT/test2 未寻址。
- **文档**：SKILL 坑 23 补句（openDocument ≠ activateDocument；导出前两步都做 + 回读；
  H1/H2 定案 = 每次导出前都要 activate）；bridge.md §10.28 "Three steps, not one (034)"。

### 主代理复验（2026-09-24）

- sha256 抽核 7 件（6 跟踪文件 + dist `44b1c76d…` 257695B）与交卷值逐字一致 ✔；
- 三线复跑：pytest **1447**（108s）/ connector **419 pass 0 fail** / tsc 干净 ✔；
- 变异记录定向红、还原 sha 回基线 ✔；
- **裁量批两条**：① 复用 docOpen 处理器（批准——"结构上不可能漂移" > 错误文案多一句导出语境；
  no-tab-id 文案用 doc.open 的，拒绝行为由测试钉死）；② `activated: true` 只在 scope=page 出现
  （与 033 同口径，批）。
- **诚实边界**：186 无法复现 149 的挂死，真机证据是机制证据（三步真执行 + 回执 + 四步顺序单测）；
  **效果验收归岳**：149 升 0.4.23 后窗口刚载入、不 doc.open，裸调 `export.render` 应直接成功
  ——激活路径与他 17:33 亲手验证成功的那次逐调用一致。~~验收通过前 issue #5 保持开放~~
  **岳 2026-09-24 在 3.2.149 + 0.4.23 验收通过**（刚载入、不 doc.open，裸调直接成功），issue #5 已关闭。
