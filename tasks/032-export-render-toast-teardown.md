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

（子代理交文本，主代理 append 并复验。）
