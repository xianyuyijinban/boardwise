# 066：boardwise-dsh 插件 × 新版 dsh 实测矩阵（只读调查）

## 背景（主代理已查清的，别重做）

岳的 dsh「更新了」，插件要重新适配。现状：

- **他机器实际跑的是 0.1.5-rc.3**，不是启动器打印的 0.1.0-rc.6：
  `%LOCALAPPDATA%\npm-cache\_npx\1e7f6d9597241db0\node_modules\@deepseek-ai\dsh\package.json`
  报 `0.1.5-rc.3`（npx 缓存被一次未钉版本的解析改写，启动器的 `Test-Path` 还在，所以fallback 永不触发，且无任何版本校验）。dsh-tools 同树也是 0.1.5-rc.3。
- npm 线上：`@deepseek-ai/dsh` latest=**0.1.7-rc.2**、next=**0.2.0-rc.1**（2026-09-28 发布）；
  `@deepseek-ai/dsh-tools` latest=0.0.1-rc.1，但有 0.1.7-rc.2 / 0.2.0-rc.1（alpha/next 通道）；
  `@deepseek-ai/cordis` latest=4.0.4，与插件 node_modules 里的 4.0.4 类型逐字节相同。
- **主代理已做过的 API 对比（结论：源码层面兼容，不需要改代码）**：
  - `defineTool` 在 0.2.0-rc.1 仍在，`DefineToolOptions` 只多了可选 `deferLoading`，
    `finalizeContent` 改名 `projectContent`（我们都没用）；`parameters/output/execute/timeoutMs` 形状未变。
  - cordis `Context` / `ctx.tools.register` 类型 4.0.1→4.0.4 无变化。
  - 官方 `packages/bundle/README.md`（HEAD）仍写明：树外 bundle 经
    `dsh plugin --profile <name> add <package>` 安装，`dsh.bundle.patch` 机制在位。
- 插件位置：`E:/boardwise/dsh-plugin/`（src/index.ts 注册 4 个工具：
  boardwise_checkup / arch / doctor / bridge；`cordis.patch.yml` 行 id `tool-boardwise`；
  peerDep `@deepseek-ai/dsh-tools >=0.0.1-rc.1 <0.2.0`）。
- 安装文档：dsh-plugin/README.md「安装」节（`dsh plugin --profile web add file:...tgz`）。

**唯一没验证的：新 dsh 上插件到底装不装得上、工具注不注册得上。** 这就是本任务。

## 任务

在**完全隔离**的环境里实测插件 × 新 dsh 的装载矩阵，交一份 VERDICT。**本任务只读调查，不改仓库任何文件、不动 git、不碰岳的真实 dsh profile 和 npx 缓存。**

### 步骤

1. **基线**：`cd E:/boardwise/dsh-plugin && npm run check`（typecheck+test+build），确认现状绿。
   `npm pack` 出 tgz（若已有 0.1.0 tgz 且 build 无变化可复用）。这一步会在仓库里刷新
   `lib/` 和 tgz —— 允许，这是构建产物；除此之外不许改仓库。

2. **隔离安装两个 dsh 版本**（网络走代理：先 `export https_proxy=http://127.0.0.1:7890`）：

   ```bash
   mkdir -p /tmp/dsh066/v0172 /tmp/dsh066/v020
   cd /tmp/dsh066/v0172 && npm init -y && npm install @deepseek-ai/dsh@0.1.7-rc.2
   cd /tmp/dsh066/v020  && npm init -y && npm install @deepseek-ai/dsh@0.2.0-rc.1
   ```

   入口用 `node node_modules/@deepseek-ai/dsh/lib/bin.js`（查 package.json 的 bin 字段确认真实路径），
   全程**不用 npx**（避免污染岳的 npx 缓存）。

3. **每个版本各建一个一次性 scratch profile**（如 `bw066`），装插件：

   ```bash
   node .../bin.js plugin --profile bw066 add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.0.tgz
   node .../bin.js --profile bw066 --dump-config | grep tool-boardwise
   ```

   profile 数据落在 `~/.dsh/profiles/bw066`——只允许用 `bw066` 这个名，**禁碰** `web` /
   `headless` / `default` 等既有 profile。完事把 `bw066` 整个删掉（进回收站，见家规）。

4. **验证工具注册**：用最便宜的方式让 profile 起一次并列出/调用工具。优先试 headless
   one-shot（`--profile bw066` 起 headless 跑一句「列出你的工具」或直接调
   `boardwise_arch`）。需要模型 token 的活路才走模型；若有纯 CLI 方式 dump 工具清单
   （如 `--dump-config` 已含工具表、或有 `tools list` 类子命令）优先用，零 token。
   设 `BOARDWISE_EXE=E:\boardwise\.venv\Scripts\python.exe`。

5. **真调一次 `boardwise_arch`**（离线、无需 daemon）：
   `file=E:/boardwise/dsh-plugin/tests/fixtures/ch340_golden.epro2`，断言返回里有架构骨架
   （电源树/轨计数）且 exit 0。doctor 会连 61190 daemon——daemon 不一定在跑，**不在线
   不算失败**，记下状态即可，不许为此起写动作。

6. **交 VERDICT**：`E:/boardwise/outputs/066_dsh_matrix/VERDICT.md` + 原始日志：
   - 矩阵：`{0.1.7-rc.2, 0.2.0-rc.1} × {install, bundle patch 生效, 工具注册, arch 真调}`
     逐格 PASS / FAIL + 失败原文（报错全文贴进日志，VERDICT 引用行号）。
   - 明确回答三个问题：
     a. 插件在 0.1.7-rc.2 上能用吗？
     b. 在 0.2.0-rc.1 上能用吗（peerDep `<0.2.0` 会不会被 npm/dsh 拒绝或告警）？
     c. 若某格 FAIL，根因是 peerDep 范围、bundle patch 机制变化、还是 API 行为变化？
   - 若 0.2.0-rc.1 实测全通，建议 peerDep 改成什么（主代理据此在 067 落地）。

### 边界（红线）

- **不改 `E:/boardwise` 仓库任何源码/文档**（仅 `npm run build`/`npm pack` 产物允许刷新）。
  发现需要改代码才能适配 → **停**，写进 VERDICT，不自行改。
- 不动 git（不 add/commit/checkout/restore）。
- 不碰岳的真实 dsh 安装（`~/Downloads/Open-DeepSeekHarness.ps1`、npx 缓存、
  `~/.dsh/profiles/` 下除 `bw066` 外的一切）。
- 不连在线立创编辑器、不起 daemon 写动作；arch/checkup --file 离线路径随便用。
- 删除一律进回收站（PowerShell VisualBasic FileIO DeleteFile/DeleteDirectory，见 SKILL §7）。
- npm install 只在 `/tmp/dsh066/` 下进行；全程 `export https_proxy=http://127.0.0.1:7890`。

### 交卷标准

- VERDICT.md 三个问题都有实测答案（不是推断），每格有日志佐证。
- `bw066` profile 已清理；`/tmp/dsh066` 可留（系统临时区）。
- 仓库 `git status` 除 `dsh-plugin/lib/` 与 tgz 外无变化。
