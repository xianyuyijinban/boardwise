# 031 export.render PNG 超时 → SVG 回退（issue #5）

## 背景

issue #5（岳工作电脑 3.2.149.88089769，connector 0.4.17 实测）：`export.render format=png scope=page`
超时 30s（3/3），**同一秒内** `format=svg` 正常返回（166012 bytes）。已排除 object 字面量、瞬时故障、
参数写错、页面差异——同一调用路径只差 `fileType`。**宿主 UI 被卡死（进度条卡住）而连接层完全正常**
（心跳正常、routed 22）——socket 健康 ≠ 宿主健康。

未验证假设（**本任务不做受控 A/B**，需岳的 149 机器且要再吃一次 UI 卡死，另议）：
画布上存在 review-mark 的 indicator marker 时 PNG 光栅化卡死，SVG 不受影响。

## 工作项

### 1. connector `export.render`（0.4.20）

- **TIMEOUT 文案改为双假设**：现文案咬定"宿主不喜欢某个参数"（那是字面量坑的修法，会把排查引错方向）。
  新文案并列两个假设：① 参数不被宿主接受（发布版与 .d.ts 不符的前科）；② 宿主 PNG 光栅化路径卡死
  （3.2.149 实测，SVG 同刻可用）——并给出实用指引"可试 format=svg"。details 里已有 format/scope，保留。
- **新增 `params.timeoutMs`**：clamp 1000..60000，缺省 = 现常量 30s（缺省行为一字不变）。
  参照 `place_netlabel` 的 timeoutMs 透传前例（clamp 防关掉）。
- 版本 0.4.19 → **0.4.20**（extension.json + 相关断言）。其余动作一个都不碰。

### 2. cli.py `_render_canvas_images`（checkup 画布阶段）

- 每页 PNG 用 `timeoutMs=10000`（正确调用 ~100–200ms，10s 足够宽容；每次卡死本来就要让用户吃一个
  卡住的 toast，快失败省的是真人时间）。
- PNG 抛 `TIMEOUT` → **同页回退一次 `format=svg`**（默认 30s）：成功则落盘 `canvas-<stem>.svg`，
  entry 记 `"format": "svg"` + `"pngError": "TIMEOUT: …"`（原错误要留痕，不许静默换格式）；
  svg 也失败 → entry.error 如实记（两条都写）。
- **只有 TIMEOUT 触发回退**：BAD_REQUEST / NOT_IMPLEMENTED / 其他错误不回退（那些不是光栅化卡死，
  回退只会掩盖真问题）。
- entry schema 只加字段不改动既有键（`file`/`bytes`/`sha256` 描述的是实际落盘的文件）。
- report.md 若渲染 canvas_images 链接，确认 .svg 也能正确出链（查模板，最小改动）。
- 其他 `export.render` 调用方（bridge render / edit 验收图）**不动**——它们要自己选格式。

### 3. 文档

- **SKILL.md 坑 23**：宿主 UI 卡死 ≠ 连接断（issue #5 实测：png 三连超时 + 编辑器进度条卡死，
  同时 `bridge status` connected、routed 22）——**心跳连续不能用来排除宿主故障**；
  3.2.149 上 PNG 光栅化可卡死而 SVG 同刻可用；checkup 画布阶段已内置 png→svg 回退。
- `docs/bridge.md`：export.render 条目（timeoutMs 参数 + 双假设超时语义）+ §10 补一条事实。
- 文案中文跟周围一致。

### 4. 测试

- connector 单测：timeoutMs clamp（<1000/>60000/非数 → 各归位）、TIMEOUT 文案含双假设与 svg 指引、
  缺省 30s 不变。
- pytest（fake bridge  scripted 应答）：① png TIMEOUT → svg 成功：落盘 .svg、entry format/pngError 齐；
  ② png TIMEOUT → svg 也 TIMEOUT：entry.error 含两条；③ png BAD_REQUEST：**不回退**（直接 error entry）；
  ④ png 正常：零回退、零新字段（向后兼容断言）。
- 变异 ≥2：回退漏触发（全灭 ①）、非 TIMEOUT 也回退（灭 ③）。

### 5. 真机（本机 3.2.186，只碰 test 窗）

- connector 热更 0.4.20 到 test 窗（`--instance` 显式寻址，先 `bridge status` 读 id）；
  test2 / ROBOT 不寻址、不更新。
- 回归：正常 `export.render format=png` 在 186 仍成功（真 PNG 落盘）。
- 回退腿实证：`format=png timeoutMs=1` 强制超时 → 随后 `format=svg` 真返回（两条腿各自有真机字节）。
- 证据 `outputs/031_*.txt`。

## 守卫

- connector 只动 `export.render`；daemon 零改动；pytest 必带 `--basetemp=.tmp_pt_home`；
- 变异用 cp 备份 + sha256/cmp 还原，禁 `git checkout --`；
- 真机只碰 test 窗；ROBOT 禁地全程只读；
- 不做 149 marker A/B（见背景）；PROGRESS 由主代理更。

## 交卷记录

### 031 · 交卷（2026-09-24，子代理 agent-43；最终回传被超时切断，摘要在 `outputs/031_summary.txt`）

- **connector 0.4.20**：`export.render` TIMEOUT 文案改**双假设**（① 宿主丢弃不喜欢的参数不 reject——
  .d.ts 坑；② PNG 光栅化路径卡死——3.2.149 实测 SVG 同刻可用）+ `format=svg` 指引；新增
  `params.timeoutMs`（clamp 1000..60000，缺省 30s 行为一字不变），判定抽成纯函数
  `exportRenderTimeoutMs`。**只动 export.render**，daemon 零改动。
- **cli.py 画布阶段**：PNG 用 10s 短绳（`CANVAS_PNG_TIMEOUT_MS`）；**仅 TIMEOUT** 触发同页 SVG 回退
  （落盘 `canvas-<stem>.svg`，entry 记 `format`+`pngError` 原错误留痕）；svg 也失败则 error 含两条；
  BAD_REQUEST 等不回退。entry schema 只加字段，正常 PNG 页键集逐键断言不变；report.md 按 `file`
  出链自动正确。其他调用方（draw 验收图）未动。
- **文档**：SKILL 坑 23（宿主 UI 卡死 ≠ 连接断；心跳连续不能排除宿主故障）；bridge.md §4
  export.render 行 + §10.28（issue #5 实测事实 + "触发因未验证"的诚实边界）。
- **三线**：pytest **1447**（+4）；connector **407**（+4）；tsc 干净。变异 **2/2 CAUGHT**
  （M1 删回退腿 → 2 红；M2 全错误回退 → 1 红）。
- **真机（186，只碰 test 窗）**：热更 0.4.20 verified（新连接 `inst-041111825-srk0ukn3`）；
  PNG 回归 156678B 真 PNG；强制超时实证（project-scope `timeoutMs=1` → 1475ms TIMEOUT 新文案）
  + 同实例 SVG 1970ms 真返回 57709B；checkup 4 页全 PNG 且 entry 零新字段（向后兼容真机验到）。
  ROBOT/test2 全程未寻址。
- **诚实边界**：page-scope PNG 在 186 无法天然超时（~0.2s 完成，clamp 下限 1s），回退编排的证据 =
  离线 scripted 用例 + 真机两条腿各自成立；149「marker 卡死 PNG」假设仍未验证。

### 主代理复验（2026-09-24）

- sha256 抽核 9 件（8 跟踪文件 + dist 254610B `e451e03e…`）与交卷值逐字一致 ✔；
- 三线复跑：pytest **1447 passed**（111s）/ connector **407 pass 0 fail** / tsc 干净 ✔；
- 变异记录定向红、还原 sha 回基线 ✔；
- **裁决①（子代理遗留 §五.2）**：daemon `ACTION_TIMEOUT=30s` 会盖住 timeoutMs 上限 60s——**接受为已知限制**，
  本批守约不动 daemon；实际天花板就是 30s，超时Ms 传 60000 只会在 30s 被 daemon 接管。
  真有 >30s 导出需求再开 daemon `timeout=` 参数的小任务。
- **裁决②（§五.3）**：protocol.py `params_schema` 未列 `timeoutMs`——**接受**：contract-drift 只比动作名，
  纯文档性漂移；权威文档是 bridge.md（已更新）。
- issue #5 建议①（错误文案分家）以"超时文案双假设 + svg 指引"落地、建议②（心跳≠宿主健康）入 SKILL 坑 23；
  建议③（149 marker A/B）维持不做，需岳的 149 机器且再吃一次 UI 卡死，由岳定夺。
