# 033 export.render 导出前自激活（issue #5 毛病 A 正案）

## 背景

岳 2026-09-24 在 **3.2.149 + connector 0.4.21** 做了受控对照（同窗同页相隔 4 分钟）：

| 时刻 | 动作 | 结果 |
|---|---|---|
| 15:48:19 | `export.render png page`，**未先动焦点** | TIMEOUT（30s 未 settle） |
| 15:50:00 | `export.render svg page`，**未先动焦点** | TIMEOUT（同上） |
| 15:53:5x | `doc.open` 目标页（回 `activated: true`） | — |
| 15:54:02 | `export.render png page` | **成功 ~2s**，662229B，magic 校验过 |

**唯一变量 = 导出前有没有把目标页 `doc.open` 过。** 由此撤回 issue #5 的两条旧结论：
① 「svg 同刻可用」不成立（15:50 svg 同样挂死；2026-09-23 18:05:53 那次成功是孤例——几分钟前 checkup
刚 doc.open 过那页，文档还"热"）；②「宿主不接受某个参数」与本症状无关（那是 2026-09-18 .d.ts 坑的
真相，不是本症状的）。**正案：页面自载入后从未被激活 ⇒ 导出挂死（png/svg 无差别）。**

一条机制解释全部历史观测：checkup 从未失败（它本就逐页 doc.open 再渲染——`_render_canvas_images`，
调用方碰巧做对了）；岳每次裸调都挂（没先动焦点）。

032（toast 自清除，毛病 B）岳已**两样本独立验证通过**：15:48 与 15:50 两次超时后浮层都不在了。
B 闭环；本任务修毛病 A。

H1（导出时必须是活动文档）vs H2（载入后至少激活过一次即可）未分离——**修法相同**：导出前立即激活，
两种世界都满足。

## 工作项

### 1. connector `exportRender`（0.4.22）

- 新增可选 `params.pageUuid`。`scope=page` 时先解析目标 uuid（`pageUuid` ?? 当前活动文档），
  调 `dmt_EditorControl.openDocument(uuid)` **激活后再导出**；结果带 `activatedPageUuid`。
- 活动文档解析不到（且没给 pageUuid）→ 诚实报错，不瞎试。
- `openDocument` 失败 → 错误透传（沿用 doc.open 的诊断风格），**不导出**。
- `scope=selection` / `scope=project` 不动（selection 有 ids 语义、project 是全工程 zip，另行有论）。
- TIMEOUT 文案修订：头号假设改为"**目标页自载入后从未激活**（3.2.149 实测，issue #5）——传 `pageUuid`
  或先 `doc.open`"；**撤回** svg 差异化表述；.d.ts 参数坑降为一句历史注脚。
- 版本 0.4.21 → **0.4.22**（extension.json + package.json + dist 重建 + source-guard 断言）。
  只动 export.render，daemon 零改动。

### 2. connector 测试

- `pageUuid` 给出 → `openDocument(uuid)` 先于 `getExportDocumentFile`（调用顺序断言）；
- 无参 → 激活**当前活动文档**再导出（老调用方行为不变且自愈）；
- `openDocument` 抛错 → 错误透传、导出**未被调用**；
- 活动文档解析不到 → 诚实报错。

### 3. 文档纠错（本批重头戏之一——库里现在记录着被推翻的结论）

- **SKILL.md 坑 23 修订**：撤回"PNG 可卡死而 SVG 同刻可用"（单样本被反例推翻）；正案 =
  **页面激活**（导出前目标页必须 doc.open 过；0.4.22 起 export.render 自己做）。toast 漏（032 已修、
  岳两样本验证）与激活挂死（033）是两件事，坑里分开说。
- `docs/bridge.md` §10.28 同口径修订 + `export.render` 行加 `pageUuid` / `activatedPageUuid`。

### 4. 真机（本机 3.2.186，只碰 test 窗）

- 热更 0.4.22 到 test 窗（`--instance` 显式寻址，先 `bridge status` 读 id）；test2/ROBOT 不寻址。
- 带 `pageUuid` 渲染回归（字节 + magic）；无参路径回归（活动文档自激活也成功）。
- 证据 `outputs/033_*.txt`。

### 5. 明确不做

- **checkup 不改**：它逐页 doc.open 再渲染，对本病天然免疫（岳的机制分析已钉死这一点）——
  在文档里写明这个结论，不画蛇添足。
- 149 的 A 病根治验收归岳：窗口刚载入、**不 doc.open**，裸调 `export.render` 应直接成功。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 ≥2（cp 备份 + sha256/cmp 还原）；
真机只碰 test 窗；不碰 git 与 PROGRESS；交卷文本同时写 `outputs/033_summary.txt`。

## 交卷记录

### 033 · 交卷（2026-09-24，子代理 agent-43；摘要 `outputs/033_summary.txt`）

- **connector 0.4.22**：`exportRender` 新增可选 `pageUuid`；`scope=page` 时解析目标 uuid
  （`pageUuid` ?? 当前活动文档，复用 doc.list 的 `activeDocument` 读书器）→
  `dmt_EditorControl.openDocument(uuid)` 激活**成功后才导出**；结果带 `activatedPageUuid`。
  激活失败三态全拒绝导出：解析不到 → 诚实报错；`openDocument` 抛错 → 原错误透传；
  不回 tab id → 沿用 doc.open 的 locate/describe 诊断。selection/project 未动，daemon 零改动。
- **TIMEOUT 文案修订**：头号假设 = "目标页自载入后从未激活（传 pageUuid 或先 doc.open）"；
  **撤回**"PNG 卡死 SVG 可用"（单样本被岳的反例推翻）；.d.ts 参数坑降为历史注脚。
- **测试**：connector +5 改 1 → **415 passed**；pytest **1447** 不变（python 只动注释）；
  tsc 干净。变异 **2/2 CAUGHT**（M1 删激活 → 5 红；M2 激活降级 best-effort → 3 红）。
- **真机（186，只碰 test 窗）**：热更 0.4.22 verified（新连接 `inst-082604830-5940wbyf`）；
  带 `pageUuid` 导 P2 → `activatedPageUuid` 正确 + 导出后 doc.list 的 active 真变成 P2
  （激活不是答案里的字段，是真换页）；无参路径 sha256 与有参**逐字节相同**；checkup 端到端
  回归 4 页 PNG 全落盘、entry 键集不变（checkup 未改，天然免疫结论成立）。ROBOT/test2 未寻址。
- **文档纠错**：SKILL 坑 23 重写（激活才是正案；toast 漏与激活挂死两件事分开说）；
  bridge.md §4 行 + §10.28 同口径重写。
- **判断两条（主代理已批）**：① cli.py 三处注释/docstring 改写（031 写下的被推翻结论连注释
  都不许留，代码零改动）；② `activatedPageUuid` 只在 scope=page 出现（没激活步骤的 scope 不带）。

### 主代理复验（2026-09-24）

- sha256 抽核 8 件（7 跟踪文件 + dist `07f69e24…` 257761B）与交卷值逐字一致 ✔；
- 三线复跑：pytest **1447**（108s）/ connector **415 pass 0 fail** / tsc 干净 ✔；
- 变异记录定向红、还原 sha 回基线 ✔；
- **验收分工**：毛病 B（toast 漏）岳已两样本验证闭环；毛病 A（未激活页面导出挂死）的根治验收
  归岳——149 上升 0.4.22 后，窗口刚载入、**不 doc.open**，裸调 `export.render` 应直接成功。
  验收通过前 issue #5 保持开放。
