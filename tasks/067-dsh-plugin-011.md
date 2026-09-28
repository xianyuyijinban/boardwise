# 067：boardwise-dsh 0.1.1 —— peerDep 拓宽 + 已验证版本记录（dsh 0.1.7/0.2.0 适配落地）

## 背景（066 实测已定论，直接引用，别重测）

`outputs/066_dsh_matrix/VERDICT.md`（agent-87 实测，零 FAIL）：

- 插件现状（peerDep `@deepseek-ai/dsh-tools >=0.0.1-rc.1 <0.2.0`）在 **dsh 0.1.7-rc.2 与
  0.2.0-rc.1 上全通**：`dsh plugin --profile add` exit 0、bundle patch 生效（`tool-boardwise`
  进组合树）、4 工具在真实 `ToolRuntime` 注册、`boardwise_arch` 真调 exit 0 且两版输出逐字节相同。
- **唯一的坑在 npm 路径**：在装有 `dsh-tools@0.2.0-rc.1` 的项目里 `npm install file:tgz`
  会 `ERESOLVE` 硬拒（peer 范围 `<0.2.0`）。dsh 自己的 profile 安装走 pnpm
  `autoInstallPeers: false`，只告警不拒——告警在 0.1.7 上同样存在，与 `<0.2.0` 无关。
- agent-87 建议：peerDep 改成 `>=0.0.1-rc.1 <0.3.0`（`<0.2.1` 会在 0.2.0 正式版再撞边界）。
- cordis 侧：latest 4.0.4 与插件 node_modules 内 4.0.4 类型逐字节相同，peerDep
  `^4.0.1` 不动。
- 源码/API：`defineTool`、`Context`、`ctx.tools.register` 到 0.2.0-rc.1 无破坏性变化，
  **本批不改任何 .ts 源码**。

## 任务（只动 dsh-plugin 域，半小时内交卷）

1. `cd E:/boardwise/dsh-plugin`：
   - `package.json`：`version` `0.1.0` → `0.1.1`；
     peerDep `"@deepseek-ai/dsh-tools": ">=0.0.1-rc.1 <0.2.0"` → `">=0.0.1-rc.1 <0.3.0"`。
     `cordis` 的 `^4.0.1` 不动。
   - `README.md`「安装」节末尾加一小节「已验证的 dsh 版本」：
     0.1.7-rc.2 ✔ / 0.2.0-rc.1 ✔（2026-09-29 实测，`outputs/066_dsh_matrix/VERDICT.md`）；
     注明 npm 直接 `npm install file:tgz` 到装了 dsh-tools 0.2.x 的项目时需 peer 范围
     ≥0.2.0（0.1.1 起已覆盖）；低于 0.1.0-rc.6 的 dsh 未验证。
2. **漂移哨兵**：`E:/boardwise/tests/test_dsh_plugin_sync.py` 现有哨兵看一眼（别重写），
   把「已验证 dsh 版本对」加进去——最小做法：哨兵读 `dsh-plugin/package.json` 断言
   peerDep 恰好是 `>=0.0.1-rc.1 <0.3.0`，并断言 README 含 `0.1.7-rc.2` 与 `0.2.0-rc.1`
   两个已验证版本字符串。保持既有断言不动。
3. 四线里的 dsh-plugin 线全绿：`npm run typecheck && npm test && npm run build`，
   然后 `npm pack` 出 `boardwise-dsh-0.1.1.tgz`（旧 0.1.0 tgz 删掉——**进回收站**，
   PowerShell VisualBasic FileIO DeleteFile，见 SKILL §7）。
4. pytest 侧只跑哨兵：`.venv/Scripts/python.exe -m pytest tests/test_dsh_plugin_sync.py -q --basetemp=.tmp_pt_home`。
5. **dsh-market 上架调研（只读）**：`export https_proxy=http://127.0.0.1:7890`，
   读 https://github.com/dsh-market/dsh-market 的 README.md 与 UPDATE-API-V1.md，
   在交卷消息里回答：上架要提交什么（格式/字段/PR 流程）、我们的 tgz 不发 npm registry
   能不能上架、每次更新要同步什么。**只调研，不提交任何 PR/issue。**

## 红线

- 不改 `src/`、`connector/`、Python 审查/画法代码；不动 git（不 add/commit/checkout/restore）。
- 不碰岳的真实 dsh 安装（npx 缓存、`~/.dsh/profiles/`、Downloads 启动器）。
- 删除一律进回收站；npm 操作只在 `dsh-plugin/` 内。
- 交卷消息列：改动文件 sha256 before/after、四线结果原文、哨兵测试原文、新 tgz sha256、
  market 调研三问答案。

## 交卷标准

- `boardwise-dsh-0.1.1.tgz` 落盘且 sha256 申报；旧 tgz 已进回收站。
- 哨兵新断言自己先变异一次（把 peerDep 改回 `<0.2.0` → 哨兵必须红 → sha256 还原）。
- 仓库 `git status` 仅 `dsh-plugin/package.json`、`dsh-plugin/README.md`、
  `tests/test_dsh_plugin_sync.py` 三个 M（tgz/lib 是 gitignore 产物）。
