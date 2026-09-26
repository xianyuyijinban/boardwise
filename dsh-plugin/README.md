# boardwise-dsh

DeepSeek Harness（dsh）的 boardwise 插件：在 dsh 里直接调 boardwise 的审查工具面 ——
`checkup`（一次审查出报告）、`arch`（架构骨架）、`doctor`（本机安装体检）、
`bridge`（连接器动作逃生舱），不用切窗口。

**薄适配层，零逻辑复制**：插件只 spawn 本机 boardwise CLI，把 stdout / exit code /
产物路径包装成 tool 返回值。解析器、规则引擎、报告——全在 Python 侧；
TS 里不重算任何审查结论（任务书 045 §1）。

## 工具面

| 工具 | 包装的命令 | 关键参数 | timeoutMs |
|---|---|---|---|
| `boardwise_checkup` | `checkup [--file F \| --project P \| --instance I] --out D` | `file` / `project` / `instance` 三选一，`out` 可选 | 600 000 |
| `boardwise_arch` | `arch <file> [--out]` | `file` 必填 | 120 000 |
| `boardwise_doctor` | `doctor [--project/--instance]` | 可选寻址 | 60 000 |
| `boardwise_bridge` | `bridge call --action A --params J [--project/--instance]` | `action`/`params` 必填 | 120 000 |

统一约定：

- **参数原样透传**，插件不解释。唯一的前置校验：`file` 路径必须存在（不存在 → 执行前拒绝，
  不 spawn）；`bridge` 的 `params` 必须是合法 JSON 对象字面量；`checkup` 必须恰好指定
  一个目标（`file` 或 `project`/`instance`），不替模型猜窗口。
- **只读优先**：三个工作流工具全只读。`boardwise_bridge` 是逃生舱（探针与诊断），
  描述里写明优先用只读动作；写动作走 CLI，服从既有的真机身份纪律。
- **返回值** = `exit code` + `cli`（怎么找到的）+ `command` + 产物路径（`report.json` /
  `report.md` / `architecture.md`，逐个标 `present` / `MISSING`）+ stdout（必要时 stderr）。
  非零 exit 是**结果**不是失败（doctor / checkup 就用 exit 报告状态）。
- **stdout 截断**：超过 32KB 时留头 16KB + 尾 16KB，中间标出丢了多少字节；stdout/stderr 里
  任何 token 形状的值一律打码（`token=***`）——daemon token 永不进日志或返回值。
- 运行时**零依赖**（只用 node 内置模块）；`@deepseek-ai/cordis` 与 `@deepseek-ai/dsh-tools`
  是 peerDependencies，由 dsh profile 提供。

## CLI 解析顺序

1. 环境变量 `BOARDWISE_EXE` —— 指向 `boardwise.exe`，或指向一个**装了 boardwise 的 Python 解释器**
   （名字像 `python`/`py` 时自动补 `-m boardwise.cli`）。指向不存在的文件 = **报错**，不会悄悄换别的
   （R3：找不到就停下来说，不自行替代）。
2. PATH 上的 `boardwise`（Windows 依次试 `boardwise.exe` / `.cmd` / `.bat`）。
3. PATH 上的 `python` / `py` + `-m boardwise.cli`（开发机 fallback；该解释器没装 boardwise 时，
   结果里会附一行 hint 让你改用 `BOARDWISE_EXE`）。

三条都没有 → 报错文案直接给出三出路（装 exe / 设 env / 用仓库 venv）。

## 安装

```sh
cd <boardwise 仓库>/dsh-plugin
npm install
npm run typecheck && npm test && npm run build
npm pack                       # 产出 boardwise-dsh-<version>.tgz
```

装进 profile（tarball 方式，不进 npm registry）：

```sh
dsh plugin --profile web add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.0.tgz
# headless / desktop 是**不同** profile，各装一次
dsh plugin --profile headless add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.0.tgz
```

包内 `dsh.bundle.patch` 会把本插件插进 profile 的 layer stack（row id `tool-boardwise`）。
验证：

```sh
dsh --profile web --dump-config | grep tool-boardwise
```

让模型跑一次 `boardwise_doctor`：daemon 在线应看到 `PASS` 行与逐项结论；
多窗口在线时那 4 项会写「未验证」（daemon 设计上不猜窗口），
用 `project=` / `instance=` 指定一个窗口即转 PASS。

## 开发

```sh
npm run typecheck     # tsc --noEmit（src 为唯一被检查的源码）
npm test              # vitest run tests —— 48 例（mock spawn，不起真进程）
npm run build         # → lib/
npm run smoke         # 独立冒烟：import lib/index.js，真起 CLI（见下）
```

`npm run smoke` 是任务书 §2 的独立冒烟脚本，**真机只读**：

1. `boardwise_doctor`：真连 daemon（127.0.0.1:61190），断言真报告（有 PASS 行、提到 daemon）；
2. `boardwise_arch file=tests/fixtures/ch340_golden.epro2`：离线骨架 + TODO 槽位 + 轨计数；
3. `boardwise_checkup --file` 同一夹具，`--out` 进临时目录：断言 `report.json` /
   `architecture.md` **真存在且有内容**，且结果里标 `[present]`，另解析 report.json 校验结构；
4. 三条错误路径：文件不存在（spawn 前拒绝）、`BOARDWISE_EXE` 指向不存在的文件、
   PATH 上什么都没有——各自断言明确报错文案。

它不碰在线编辑器写动作，也不调 `bridge` 任何动作。

## 非目标

不做 dsh 客户端（浏览器半边）插件、不做主题/UI、不发 npm registry、
不在 TS 侧实现任何审查逻辑、不提供写操作工具（edit apply 走 CLI）。
dsh SKILL 加载机制与本仓库 SKILL.md 的衔接是后续任务，本插件只负责工具面。
