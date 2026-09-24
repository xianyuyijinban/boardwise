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

（子代理交文本，主代理 append 并复验。）
