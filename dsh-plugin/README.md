# boardwise-dsh

DeepSeek Harness（dsh）的 boardwise 插件：在 dsh 里直接调 boardwise 的审查工具面 ——
`checkup`（一次审查出报告）、`arch`（架构骨架）、`doctor`（本机安装体检）、
`bridge`（连接器动作逃生舱），不用切窗口。

**薄适配层，零逻辑复制**：插件只 spawn 本机 boardwise CLI，把 stdout / exit code /
产物路径包装成 tool 返回值。解析器、规则引擎、报告——全在 Python 侧；
TS 里不重算任何审查结论（任务书 045 §1）。

## 版本策略

**从 0.6.0 起，插件版本与 boardwise 外部版本同号**：发布 0.6.0 时，根 shim
`package.json` 与 `dsh-plugin/package.json` 一起改成 `0.6.0`，不再单独维护 `0.1.x` 线。
`0.1.3` 是 `0.1.x` 的最后一版；0.6.0 之前现有安装照用，不追着改版本号。

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
  非零 exit 是**结果**不是失败（doctor / checkup 就用 exit 报告状态）；
  `checkup` 的 `3` = **说不清**（在线状态读不出来，或 `completion.verdict` 是 `incomplete`——
  审查没看全：空模型 / 器件缺手册未审 / 骨架没生成 / 覆盖有缺口），**不是通过**（073）。
- **stdout 截断**：超过 32KB 时留头 16KB + 尾 16KB，中间标出丢了多少字节；stdout/stderr 里
  任何 token 形状的值一律打码（`token=***`）——daemon token 永不进日志或返回值。
- 运行时**零依赖**（只用 node 内置模块）；`@deepseek-ai/cordis` 与 `@deepseek-ai/dsh-tools`
  是 peerDependencies，由 dsh profile 提供。

## CLI 解析顺序

1. 环境变量 `BOARDWISE_EXE` —— 指向 `boardwise.exe`，或指向一个**装了 boardwise 的 Python 解释器**
   （名字像 `python`/`py` 时自动补 `-m boardwise.cli`）。指向不存在的文件 = **报错**，不会悄悄换别的
   （R3：找不到就停下来说，不自行替代）。
2. PATH 上的 `boardwise.exe`（Windows 只自动执行 **exe**；`.cmd` / `.bat` 不直接 spawn，
   因为 Node 无法在不经 shell 的情况下执行批处理，经 `cmd.exe` 又会把模型给的参数暴露在
   shell 解析下。只有批处理启动器时请改用 `BOARDWISE_EXE` 指向 exe 或 Python）。
3. PATH 上的 `python` / `py` + `-m boardwise.cli`（开发机 fallback；该解释器没装 boardwise 时，
   结果里会附一行 hint 让你改用 `BOARDWISE_EXE`）。

三条都没有 → 报错文案直接给出三出路（装 exe / 设 env / 用仓库 venv）。

注意：**插件不会自动探测仓库里的 `.venv`**。报错文案第三条「用仓库 venv」是一条**人照着做**的
出路——把 `BOARDWISE_EXE` 指向 `<repo>/.venv/Scripts/python.exe`，不是插件的自动行为。
开发机上最常见的首次失败正是第 3 档：PATH 上的 Python 能跑、但没装 boardwise，
于是拿到 `ModuleNotFoundError: No module named 'boardwise'` 和一行 hint，而不是工具结论。

## 安装

### 先决条件：dsh 进程要能找到 boardwise CLI

插件只是 spawn 本机 CLI 的薄适配层，不把审查逻辑搬进 Node。所以装完插件还要保证
**dsh 进程**能按上一节的顺序解析到 CLI；否则第一次调用会返回一条指路错误（不是插件装坏了）。
本机实测能走通的路有两条（另附源码树冒烟时的默认指向）：

**A. 把仓库装进用户级 site-packages（开发机最省事）**

```sh
pip install --user -e <boardwise 仓库>
```

这会生成 `%APPDATA%\Python\Python3xx\Scripts\boardwise.exe`；该目录通常已在 PATH 上，
插件的结果里会写 `cli: path` 并给出这个 exe 的绝对路径。dsh 桌面应用的子进程读同一份
用户级 site-packages，所以**装完即可用，不必重启 dsh、不必设环境变量**。

本机实测（2026-10-24）：`boardwise_doctor` 返回
`cli: path` → `C:\Users\<用户>\AppData\Roaming\Python\Python314\Scripts\boardwise.exe`。
若 `...\Scripts` 不在 PATH 上，改用 B 并把路径写死。

**B. 装发布版 exe，并让 `BOARDWISE_EXE` 指向它**

```sh
setx BOARDWISE_EXE "<boardwise.exe 的绝对路径>"
# 也可以指向装了 boardwise 的 Python 解释器（名字像 python/py 时自动补 -m boardwise.cli）：
setx BOARDWISE_EXE "<boardwise 仓库>\.venv\Scripts\python.exe"
```

`setx` 只影响**之后**启动的进程：重开 dsh 才生效。指向不存在的文件时插件**直接报错**，
不会悄悄换用别的 boardwise（R3：找不到就停下来说）。

**C. 源码树直接跑冒烟**：`npm run smoke` 会自动把 `BOARDWISE_EXE` 指到
`<repo>/.venv/Scripts/python.exe`，不需要额外设变量（这条只是冒烟脚本的默认值，不是第三条安装路）。

### 构建与打包

```sh
cd <boardwise 仓库>/dsh-plugin
npm install
npm run typecheck && npm test && npm run build
npm pack                       # 产出 boardwise-dsh-<version>.tgz
```

### 装进 profile

```sh
dsh plugin --profile desktop add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.3.tgz
dsh plugin --profile web add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.3.tgz
# desktop / web / headless 是**不同** profile，各装一次
dsh plugin --profile headless add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.3.tgz
```

也可以从 GitHub 装（要求仓库根的 shim 已提交，见下节）：

```sh
dsh plugin --profile desktop add github:xianyuyijinban/boardwise
```

或从 npm registry 装（**发布后**才可用，见下节 publish 指引）：

```sh
dsh plugin --profile web add boardwise-dsh
dsh plugin --profile headless add boardwise-dsh
```

包内 `dsh.bundle.patch` 会把本插件插进 profile 的 layer stack（row id `tool-boardwise`）。
验证：

```sh
dsh plugin --profile desktop why boardwise-dsh   # 应报 1 个版本，挂在 dsh-profile-desktop 下
dsh --profile desktop --dump-config | grep tool-boardwise
```

让模型跑一次 `boardwise_doctor`：daemon 在线应看到 `PASS` 行与逐项结论；
多窗口在线时那 4 项会写「未验证」（daemon 设计上不猜窗口），
用 `project=` / `instance=` 指定一个窗口即转 PASS。

### headless profile 的 store 分裂（已裁：新建 profile）

**现象**：headless profile 上的 `dsh plugin --profile headless add <tgz>` 会报
`ERR_PNPM_UNEXPECTED_STORE`——pnpm 认为这个 `node_modules` 是**另一个 store** 物化的，
于是拒绝在它上面继续装。

**本机证据**（2026-10-24 读文件所得，不是猜）：

```text
D:\dsh-home\profiles\headless\node_modules\.modules.yaml
  storeDir:        C:\Users\<用户>\AppData\Local\pnpm\store\v11
  virtualStoreDir: C:\Users\<用户>\.dsh\profiles\headless\node_modules\.pnpm
D:\dsh-home\profiles\desktop\node_modules\.modules.yaml
  storeDir:        D:\.pnpm-store\v11
  virtualStoreDir: D:\dsh-home\profiles\desktop\node_modules\.pnpm
```

headless 的 `node_modules` 是早先 `~/.dsh` 时代物化的，profile 后来搬到了
`D:\dsh-home\profiles\headless`，但 `.modules.yaml` 里记的还是旧的 store 与旧路径；
desktop 则用 `D:\.pnpm-store\v11`。两套 store 对不上，pnpm 就报这个错。

**最小复现**（2026-10-24 实测触发；在已存在的 headless profile 上再装一次即可，不需要先卸载，
pnpm 在解析阶段就拒）：

```sh
dsh plugin --profile headless add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.3.tgz
# → ERR_PNPM_UNEXPECTED_STORE（modules dir 的 store 与当前 store 不一致）
```

**处置（2026-10-24 已裁）**：不要为了消掉这个报错去清空或重链 `DSH_HOME` 的 pnpm store——那会牵动
desktop / web 两个在用的 profile。也不迁移旧 headless 的 `node_modules`；从 headless 模板新建一个干净
profile，在它上面安装：

```sh
dsh --profile boardwise-clean --from-default-profile headless --dump-config
dsh plugin --profile boardwise-clean add file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.3.tgz
```

本机实测：安装 431ms 成功，`--dump-config` 出现 `# == boardwise-dsh` / `tool-boardwise`；旧
`headless` 的 store 与 `node_modules` 一个字节未动。现有 headless 里已经装好的 0.1.3 仍可照用，
需要干净安装就用新 profile。

### web profile：旧 profile 不硬修，新建 `boardwise-web-clean`

现有 `web` profile 的 `node_modules/.modules.yaml` 还记着
`C:\Users\xiangyu\.dsh\profiles\web\node_modules\.pnpm`（profile 搬过家），在原 profile
上安装会报 `ERR_PNPM_UNEXPECTED_VIRTUAL_STORE`。不重建旧 `web` 的依赖，按 headless 同法
从 web 模板新建一个干净 profile：

```sh
# 当前 Desktop CLI；版本目录以本机 host-commands 为准
DSH="$HOME/AppData/Roaming/DSH Desktop/host-commands/desktop/generations/<hash>/bin/dsh.cmd"
"$DSH" --profile boardwise-web-clean --from-default-profile web --dump-config
"$DSH" plugin --profile boardwise-web-clean add \
  file:E:/boardwise/dsh-plugin/boardwise-dsh-0.1.3.tgz
"$DSH" --profile boardwise-web-clean --dump-config | grep -n 'tool-boardwise'
```

本机实测：安装 377ms，`--dump-config` 出现 `# == boardwise-dsh` / `tool-boardwise`。
启动 web 时用 `--profile boardwise-web-clean`；旧 `web` profile 保持原样。

### DSH STORE 那条命令现在能用了（根 shim）

DSH STORE 的安装命令指向的是**仓库根**：

```sh
dsh plugin add github:xianyuyijinban/boardwise
```

**根目录过去没有 `package.json`**，pnpm 只能伪造一份占位清单，把整仓当普通依赖装进去：
不报错、也**不挂任何 bundle**——于是 0 工具注册，插件看着像「装了但用不了」。
这是那条命令的历史死因，**不是配置问题**。

仓库根现在补了一份**纯 shim** `package.json`（`"name": "boardwise-dsh"`、版本与插件同步、
`main` / `types` 指进 `dsh-plugin/lib/`、`dsh.bundle.patch` 指向
`dsh-plugin/cordis.patch.yml`），装上它就能真正挂上 bundle、注册 4 工具。
shim **不是** npm 工程：没有 `scripts`、没有 `dependencies`，根目录不跑构建。

**shim 必须提交进 HEAD 才会生效**：pnpm 的 git 依赖物化的是**提交树**，
工作区里未跟踪的改动一律不进安装结果（实测：根目录新建的未跟踪标记文件在装出来的
`node_modules/<pkg>/` 里**不出现**）。所以 shim 落盘但没 commit 时，商城那条命令
**仍然是老样子**（placeholder + `declares no dsh.bundle`）。

- **首选仍是 tarball**（离线、可重现、不依赖 registry），其次 npm（发布后），
  **商城根命令只作为最后兜底**——它把整仓当依赖拉下来，体积与版本都跟着 git 走。

验证（本机到 github.com:443 不通，离线替身用 `git+file:///E:/boardwise`）：

```sh
# ① 工作区里的 shim 形状对不对（不依赖 commit，装的是工作区本身）：
dsh plugin --profile <临时 profile> add file:E:/boardwise
dsh plugin --profile <临时 profile> list            # 依赖里应见 boardwise-dsh（不是 boardwise）
dsh --profile <临时 profile> --dump-config | grep tool-boardwise
# ② shim 提交之后，商城那条路（git）才等价：
dsh plugin --profile <临时 profile> add git+file:///E:/boardwise
```

②在 shim 未提交时会打 `dsh: warning: … declares no dsh.bundle`——那是 HEAD 里还没有
shim 的**正确**警告，不是命令写错了。

### 发布到 npm registry

发布要仓库 owner 的 npm 账号，**本仓库不代发**：

```sh
npm login                       # 用 owner 账号
cd dsh-plugin
npm publish --access public     # 源码：只要 dsh-plugin/，不是仓库根
```

发布前自查：

```sh
cd dsh-plugin && npm run check  # typecheck + test + build
npm pack                        # 产出 boardwise-dsh-<version>.tgz
tar -tzf boardwise-dsh-<version>.tgz   # 应含 lib/index.js、lib/types/、cordis.patch.yml
npm publish --dry-run           # 只看文件面，不上传
```

`package.json` 的 `files` 白名单决定发布内容（`lib` / `src` / `cordis.patch.yml` / `README.md`）；
`lib/` 已入库（DSH STORE 的固定提交自动化只读 git 树，不跑 `prepare`/`build`）。

### 已验证的 dsh 版本

| dsh | 结果 | 证据 |
|---|---|---|
| `0.1.7-rc.2` | ✔ 全通 | 2026-09-29 实测：`plugin add` exit 0、bundle patch 生效、4 工具注册 4/4、`boardwise_arch` 真调 exit 0 |
| `0.2.0-rc.1` | ✔ 全通 | 同一轮实测，输出与 0.1.7-rc.2 **逐字节相同** |
| `0.2.1-rc.2` | ✔ 桌面版实读 | 2026-10-24 桌面 profile 实测：`plugin why` 报 1 个版本、`--dump-config` 有 `tool-boardwise`、`boardwise_doctor` 真调 exit 1（daemon 在线、结果非失败）、`boardwise_checkup` 真调 exit 3 且 report.json / report.md / architecture.md / design-intent.md 四件产物均 `[present]` |

原始日志与结论：`outputs/066_dsh_matrix/VERDICT.md`（零 FAIL 格；`0.2.1-rc.2`
一行是 2026-10-24 在桌面 profile 上的补读，不是矩阵里那一轮的产物）。

- **peer 范围**：`@deepseek-ai/dsh-tools` peerDep 自 0.1.1 起是三分支范围
  `>=0.0.1-rc.1 <0.3.0 || >=0.1.7-rc.2 <0.2.0-0 || >=0.2.0-rc.1 <0.3.0-0`
  （0.1.0 是 `<0.2.0`）。**为什么必须分三段**：node-semver 只放行「范围里存在同
  major.minor.patch、且自身带预发布标签的比较符」的预发布版本，所以单段 `<0.3.0` 看着宽、
  实际把 `0.1.7-rc.2` / `0.2.0-rc.1` 静默排除（npm 路径报 `ERESOLVE`）；把这两版的 tuple
  显式列进 `||` 分支，npm 消费者才装得上。
- **覆盖表**（npm 自带 semver 实测）：`0.0.1-rc.1` ✔、`0.1.7-rc.2` ✔、`0.2.0-rc.1` ✔、
  `0.1.7` ✔、`0.2.0` ✔、`0.3.0` ✘。**更老的 rc（`0.1.0-rc.6`、`0.1.5-rc.x` 之类）不在 npm
  路径覆盖内**——每一版都要自己的同 tuple 分支，而它们从未实跑过；dsh 自己的 profile 安装走
  pnpm（`autoInstallPeers: false`，不强制 peer），不受这条边界影响。
- **未验证区间**：低于 `0.1.0-rc.6` 的 dsh 从未实跑过（peerDep 下界 `0.0.1-rc.1` 只是语义边界，
  不等于实测边界）。`cordis` peerDep `^4.0.1` 未动（实测 4.0.4 类型与插件内完全一致）。

## 开发

```sh
npm run typecheck     # tsc --noEmit（src 为唯一被检查的源码）
npm test              # vitest run tests —— 52 例（51 过 1 跳过；mock spawn，不起真进程）
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

在受限文件沙箱里跑时，第 3 步可能报 exit 1 而不是 0/3：node 在 `%TEMP%` 建的目录，
沙箱外的子进程 Python 写不进去（`PermissionError: …\report.json`）。这是环境 ACL 限制，
不是插件缺陷——真实桌面 dsh 里同一调用返回 exit 3，四件产物均写出。

## 非目标

不做 dsh 客户端（浏览器半边）插件、不做主题/UI、不发 npm registry、
不在 TS 侧实现任何审查逻辑、不提供写操作工具（edit apply 走 CLI）。
dsh SKILL 加载机制与本仓库 SKILL.md 的衔接是后续任务，本插件只负责工具面。

## 权限与边界（DSH STORE 固定源码审查对应）

- **进程**：spawn 本机 `boardwise` CLI（子进程）；`file` 参数不存在时执行前拒绝，不 spawn。
- **文件**：只写用户显式给的 `--out` 目录；读取工程文件/报告。不碰其它路径。
  没给 `--out` 时（`boardwise_checkup`）自己建一个系统临时目录
  （`os.tmpdir()` 下 `boardwise-dsh-*`，每次一份）——那是**系统临时目录**，不是当前目录，
  也不会在结束时清理（报告要留给模型读）。
- **网络**：仅经本机 loopback 访问 boardwise daemon（127.0.0.1:61190，经 CLI）；**不访问任何外部服务**。
- **失败边界**：CLI 非零 exit 原样作为结果返回（不伪装成功）；stdout 超 32KB 截断并标注；token 形状的值一律打码。
- **依赖**：运行时零依赖（node 内置模块）；`@deepseek-ai/cordis`、`@deepseek-ai/dsh-tools` 为 peerDependencies，由 dsh profile 提供。
