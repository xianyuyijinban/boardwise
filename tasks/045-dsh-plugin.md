# 045：boardwise × DeepSeek Harness 插件（boardwise-dsh）

日期：2026-09-27。动机：岳的 DeepSeek 主力 harness 是 **DeepSeek Harness（dsh）**
（本机 `~/.dsh/` 已装 web/headless/desktop 三 profile）。审查是 Boardwise 的当前定位，
dsh 是岳实际跑审查模型的宿主——把 Boardwise 工具面接进 dsh，AI 在 dsh 里直接调
checkup/arch，不用切窗口。岳原话："我们先适配 DeepSeek harness，做个插件。"

## §1 架构裁决（主代理定，不再议）

1. **薄适配层，零逻辑复制**：dsh 插件只 spawn 本地 boardwise CLI
   （`boardwise.exe` 或 `python -m boardwise.cli`），把 stdout/exit code 包装成
   dsh tool 返回值。审查逻辑、解析器、规则引擎全部留在 Python 侧——
   **harness 是我们的产品，dsh 插件只是接线**。任何"在 TS 里重算"的想法都拒绝。
2. **只读优先**：MVP 三个工作流工具全是只读（checkup/arch/doctor）。
   bridge 透传作为高级逃生舱第四工具，description 里写明"建议只读动作"，
   不加白名单机械拦截（过度设计；写操作走 CLI 是既有纪律）。
3. **仓库内子项目** `dsh-plugin/`（connector/ 同款先例：TS 子项目、自己的
   package.json/tsconfig/vitest），不进 npm registry——`npm pack` 出 tgz，
   `file:` 装进 profile（岳本机 dsh-plugin-check 就是这个装法）。
4. **契约参照物**：`D:\dsh\dsh-plugin-check-main\`（岳本机已装的工作插件）——
   ESM、`main: lib/index.js`、`dsh.bundle.patch` → `cordis.patch.yml`
   （`- insert: - id: tool-boardwise  name: boardwise-dsh`）、
   peerDeps `@deepseek-ai/cordis ^4` / `@deepseek-ai/dsh-tools`、
   `export const name/inject=['tools']`、`apply(ctx)` 里
   `ctx.tools.register(defineTool({...}))`。逐字学它的骨架，不发明轮子。

## §2 工具面（MVP 四个）

| 工具名 | 包装 | 关键参数 | timeoutMs |
|---|---|---|---|
| `boardwise_checkup` | `checkup [--file F \| --project P \| --instance I] --out <tmp>` | file/project/instance 三选一、out 可选（缺省 mkdtemp） | 600_000 |
| `boardwise_arch` | `arch <file> [--out]` | file 必填 | 120_000 |
| `boardwise_doctor` | `doctor [--project/--instance]` | 可选寻址 | 60_000 |
| `boardwise_bridge` | `bridge call --action A --params J [--project/--instance]` | action/params 必填 | 120_000 |

统一约定：
- **CLI 解析顺序**：env `BOARDWISE_EXE` → PATH 找 `boardwise.exe` →
  找 `python`/`py` 配 `-m boardwise.cli`（开发机 fallback）。找不到 = 明确报错
  指明三出路（装 exe / 设 env / 仓库 venv）。
- 返回值 = exit code + stdout（截断保护：>32KB 留头尾）+ 关键产物路径
  （report.json / architecture.md）。`output.render` 照 plugin-check 样例回 text。
- 参数原样透传不解释（薄！），但 file 路径必须存在否则执行前拒绝；
  checkup 的 --out 目录由插件建（mkdtemp 前缀 `boardwise-dsh-`），把路径告诉 AI。
- **永不**在日志/返回值里打印 daemon token。

## §3 工程骨架

```
dsh-plugin/
  package.json        # name boardwise-dsh, type module, private, dsh.bundle.patch
  cordis.patch.yml    # insert id tool-boardwise
  tsconfig.json       # → lib/
  src/index.ts        # name/inject/apply + 四个 defineTool
  src/cli.ts          # 可执行解析 + spawn 包装（超时/截断/错误）
  tests/              # vitest：mock spawn 覆盖四工具参数组装与错误路径
  README.md           # 安装（npm pack → dsh plugin --profile web add file:...tgz）
```

验收命令：`npm run typecheck && npm test && npm run build && npm pack`。

## §4 真机验收（岳本机）

1. `npm pack` 出 tgz → 装进 headless profile（desktop/web 任选其一再验一个）。
2. dsh 里让模型跑 `boardwise_doctor`（daemon 在线应 8/8 或列出实际状态）。
3. `boardwise_checkup --file` 跑 `tests/fixtures/ch340_golden.epro2` 离线
   （不依赖编辑器），确认 report/architecture 路径返回正确。
4. 真机在线 checkup 只碰 **test 窗**（禁地纪律原样适用）。

## §5 非目标（本任务不做）

- 不做 dsh 客户端（浏览器半边）插件、不做主题/UI；不发布 npm registry；
- 不在 TS 侧实现任何审查逻辑；不做写操作工具（edit apply 走 CLI）；
- dsh 的 SKILL 加载机制与我们的 SKILL.md 衔接（后续任务，先工具面）。

## §6 交卷记录（MVP，2026-09-27，DeepSeek agent-51 实现 + 主代理真机验收）

**交付**：`dsh-plugin/`（boardwise-dsh 0.1.0）——四工具（`boardwise_checkup`/`boardwise_arch`/`boardwise_doctor`/`boardwise_bridge`），薄适配层 spawn 本地 CLI（解析序 `BOARDWISE_EXE`→PATH `boardwise.exe`→python fallback，指 python 自动补 `-m boardwise.cli`）；stdout>32KB 头尾截断、kill 超时、exit code 透传、token 打码；vitest **48 过 1 跳过**（POSIX 执行位用例 Windows 豁免）+ tsc 干净 + `npm pack` 出 tgz 21.3KB；独立变异 4 组全 CAUGHT（首轮一组曾自我指涉误过，改硬编码断言后转红）；真 CLI 冒烟四步全过（doctor 在线 / arch 夹具 / checkup 夹具三件产物 [present] / 两条错误路径文案）。

**主代理批准的偏离（3 条）**：① checkup **必须显式寻址**（file xor project/instance），无参"读焦点"被拒绝——与多窗口"daemon 不猜窗口"纪律同源；② 超时/取消=抛错，部分输出不当成功；非零 exit 仍作结果返回；③ bridge `params` 只做 JSON 语法预校验（原样透传，数组/非对象拒）。子项目 `.gitignore` + 根 `.gitignore` 三行（node_modules/lib/*.tgz）由主代理补。

**真机验收（主代理亲手，岳授权）**：官方 `dsh plugin --profile headless add file:…tgz` 装入（dsh.bundle  reconcile 自动进层栈）；`--dump-config` 组合树里 `tool-boardwise` 层在册；headless 单发任务实测两轮——第一轮（无 env）DeepSeek 模型发现工具、调用、收到**设计好的报错**（PATH 上 Python3.14 无 boardwise + "set BOARDWISE_EXE"hint），第二轮 `BOARDWISE_EXE=<仓库venv python>` 返回真 doctor 输出（多窗 `WINDOW_UNSPECIFIED` 按设计列出候选窗口）。**工具注册/发现/执行/错误路径在真 dsh 运行时全链 PASS**。

**遗留**：`BOARDWISE_EXE` 持久化（建议岳的 `Open-DeepSeekHarness.ps1` 加一行 `$env:BOARDWISE_EXE='E:\boardwise\.venv\Scripts\python.exe'`，待岳点头）；web/desktop profile 未装（同一条 add 命令，profile 名换一下）；npm registry 发布照旧不做。

## §7 市场上架（到时候）与同步纪律（岳 2026-09-27 定）

**上架路径**：dsh-market 仓库只是市场**应用**，目录在 curated
**awesome-dsh-plugin registry**——上架 = 向 registry 提一个 PR（一条目），
市场与站点一天内自动拾取；别向 dsh-market 本仓 PR 条目。安装源的优先级是
**npm 验证包 → 作者 GitHub Release 预构建 tarball → 仓库源码**；我们走第二档：
**release 从 v0.4.26 起带第三附件 `boardwise-dsh-<version>.tgz`**（exe/eext/dsh
三件套），registry 条目指向 release tarball，不发 npm registry 照旧。
时机由岳定（朋友验证过后），本任务保持 open 直到上架。

**同步纪律（长期，写进 SKILL 交付纪律）**：每次 boardwise 出新功能——
1. 落盘时检查 dsh-plugin 工具面要不要跟（新 CLI 命令/新参数该不该暴露成 dsh
   工具；该就跟，不该在任务书交卷记录里说一句为什么不跟）；
2. 跟了就要 `dsh-plugin` 版本 bump + `npm pack` 重出 tgz；
3. release 时三件套一起发；（上架后）registry 条目版本同步 PR。
机械哨兵：`tests/test_dsh_plugin_sync.py` 钉死"插件 spawn 的每个 CLI 命令名
必须在 cli.py 存在"（改名/删除方向）；反向（新命令未包装）属评审判断不拦截。
