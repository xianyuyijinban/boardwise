# boardwise 安装（给朋友看的版本）

这份文档只讲**怎么把 boardwise 装到你这台 Windows 机器上**，大概 20 到 30 分钟。
装完之后怎么用，看 [`getting-started.md`](getting-started.md)（那份六步走，每一步都带真机截图）。

面向的是**硬件工程师**：你不需要会写代码，但要在命令行里敲几条命令、在编辑器里点几下。
凡是需要你动手的地方，本文都写了"应该看到什么"和"不对怎么办"。

## 第 0 步 · 拿到仓库

同事（岳翔宇）会把两样东西发给你：**仓库压缩包**（zip）和**扩展文件**（`.eext`）。

1. 把 zip 解压到一个你有写权限、路径里**没有中文和空格**的目录，比如 `E:\boardwise`——
   下面所有"在仓库目录里敲"说的就是它；
2. `.eext` 先放桌面就行，第 3 步才用。

> 仓库目录装完**别删也别挪**（原因见第 2 步末尾）。

## 你需要准备什么

| 东西 | 要求 | 没有怎么办 |
|---|---|---|
| Windows | 10 或 11 | — |
| 立创 EDA Pro | **3.2.183 或更高**（推荐最新版） | 到 <https://pro.easyeda.com/> 下载桌面版 |
| Python | **3.10 或更高** | 见第 1 步，官网下载；安装脚本没找到会给你链接 |
| Node.js | 20.15 以上（**只有你自己构建扩展才需要**） | 同事给你 `.eext` 的话不用管 Node |
| 网络 | 能访问 PyPI（装 Python 包用） | 公司内网要配代理或换镜像，见"常见问题" |

> **一次只开一个编辑器窗口。** 每个窗口里的扩展都会各自连上 daemon；0.4.11 起 daemon 只认
> 先到的那一个，后来者的连接会被直接拒绝（daemon 窗口会打印一行提示），活跃窗口不受影响。
> 所以开着多个窗口时，只有先连上的那个窗口能用 boardwise——为避免搞混，把多余的编辑器窗口关掉。

## 五步速览

| 步骤 | 你要做的 | 做完的标志 |
|---|---|---|
| 1 | 装 Python 3.10+ | 命令行里 `python --version` 有输出 |
| 2 | 双击 `scripts\install.bat` | 最后打印"下一步"，`.venv` 建好、boardwise 装上 |
| 3 | 编辑器里导入 `boardwise-connector-*.eext`，**然后完全重启编辑器** | 顶栏出现 `boardwise` 菜单 |
| 4 | 双击 `scripts\start-daemon.bat`，窗口保持开着 | 窗口里出现带指纹的"配对"公告 |
| 5 | 命令行跑 `boardwise doctor` | 七行全绿 |

> **命令怎么写**：本文里的 `boardwise xxx` 都指 boardwise 命令。装完之后它不在你的 PATH 上，
> 所以在仓库目录里用**完整写法**最省事：
> `.venv\Scripts\python.exe -m boardwise.cli xxx`（比如 `.venv\Scripts\python.exe -m boardwise.cli doctor`）。
> 想少敲一点就先激活虚拟环境：`.venv\Scripts\activate.bat`，之后 `boardwise` 和上面等价；
> 关掉窗口就失效，下次要重新激活。

---

## 第 1 步 · 装 Python

到官网下载：<https://www.python.org/downloads/windows/>（选 **3.10 以上**的稳定版）。

安装时**务必勾上 `Add python.exe to PATH`**（把 Python 加进命令行能找得到的地方）。

装完打开"命令提示符"（开始菜单搜 `cmd`），敲：

```bat
python --version
```

预期：打印 `Python 3.1x.x`。

不对怎么办：

- 提示"不是内部或外部命令"：PATH 没勾上，重新运行安装程序选 `Modify` → 勾上 `Add python.exe to PATH`。
- 弹出去微软商店：那是 Windows 自带的"占位"python，不算安装。照上面装官网版本，
  装完**关掉这个命令行窗口重开**（PATH 才会生效）。
- 已经装过 3.8/3.9：不用卸载，装个新版即可。

> 截图位：`docs/images/install-01-python-version.png` —— `python --version` 的输出。

---

## 第 2 步 · 双击 `scripts\install.bat`

这个脚本放在仓库的 `scripts\` 文件夹里，双击它就行。它会依次做五件事，每一步都有中文提示：

1. 找 Python（3.10 以上），找不到就给你官网链接并退出；
2. 在仓库目录里建虚拟环境 `.venv`（已经有了就复用，不会覆盖）；
3. 把 pip 升到新版（失败不致命，会提示你继续）；
4. 装 boardwise 本身（`pip install -e .`，联网从 PyPI 下载 `websockets`）；
5. 跑一遍 `boardwise doctor`，然后打印"下一步"。

预期：窗口最后停在"下一步，按顺序："那段话。在这之前会看到一句
`doctor 退出码 1：现在有红项。`——**首次装完 doctor 是红的很正常**，
因为 daemon 还没起、编辑器还没装扩展；脚本会把每条红项的修复建议列出来，照着做即可。

不对怎么办（脚本会直接告诉你原因，这里列最常见的）：

- **没有 Python**：装第 1 步，然后重跑本脚本。
- **`pip install` 失败**：多半是网络。公司内网换镜像再试（在仓库目录里敲）：
  ```bat
  .venv\Scripts\python.exe -m pip install -e . -i https://pypi.tuna.tsinghua.edu.cn/simple
  ```
- **权限问题**：把仓库放在你有写权限的目录（比如 `E:\boardwise`），不要放 `C:\Program Files`。
- **想重装**：直接重跑本脚本；要彻底重来就先删掉 `.venv` 再跑。

两条要知道的规矩：

- **仓库目录别删也别挪**。boardwise 是"就地安装"（editable）的：它按仓库里的相对路径
  找 `connector/`、`blocklib/`；目录一挪，`doctor` 会有一项说不清。
- **脚本是 ANSI/GBK 编码，第 2 行用 `chcp 936` 切控制台代码页**。这是 Windows 批处理显示
  中文的可靠做法（cmd 按控制台代码页解析批处理文件，UTF-8 批处理会被解析错位）。
  用编辑器打开看到乱码时，按 GBK/ANSI 重新打开即可；改动脚本请保留"第 2 行 chcp"这笔。

> 截图位：`docs/images/install-02-bat-output.png` —— `install.bat` 跑完停在"下一步"的画面。

---

## 第 3 步 · 在编辑器里装扩展（`.eext`）

`.eext` 是给编辑器用的插件，负责"替你把话传给编辑器"。**两条路拿它**：

- 同事（岳翔宇）已经给你 `boardwise-connector-<版本>.eext`：直接用，跳过下面的构建；
- 自己从仓库构建：双击 `scripts\build-connector.bat`（需要 Node.js 20.15 以上，
  脚本会打印产物路径，形如 `connector\boardwise-connector-0.4.11.eext`）。

导入步骤：

1. 立创 EDA Pro → `扩展`（设置里的扩展管理）→ `导入扩展` → 选中那个 `.eext`；
2. **完全关闭编辑器，再重新打开**。这一步不能省：编辑器只在启动时读一次扩展代码，
   热导入常常"看起来成功、其实还在跑旧版本"；
3. 首页 / 原理图页 / PCB 页的顶栏应该出现 **boardwise** 菜单。

预期：点 `boardwise → About...` 会弹出一个小框，显示连接状态与版本
（`V0.4.11` 之类；**不会**显示 token 本身）。

不对怎么办：顶栏没有 boardwise → 导入没生效，重做本步（记得完全重启编辑器）。
已经装过旧版、想确认编辑器里跑的是哪一版：`boardwise doctor` 的
"运行中的 connector 版本与仓库一致"那一项会分别报出两边版本号；
不一致时用 `boardwise bridge update-connector` 热更新（不用重新导入、不用重启编辑器）。

> 截图位：`docs/images/install-03-import-eext.png` —— 扩展管理页的"导入扩展"按钮与导入后的
> 扩展列表（显示 boardwise Connector 已启用）。

---

## 第 4 步 · 启动 daemon 并配对

双击 `scripts\start-daemon.bat`。会开一个标题为 **boardwise daemon** 的窗口：

```text
boardwise bridge: listening on 127.0.0.1:61190
  token file: C:\Users\<你>\.boardwise\token
  audit log:  C:\Users\<你>\.boardwise\audit
  pairing:    C:\Users\<你>\.boardwise\connector-token
  waiting for the EasyEDA extension to connect (Ctrl-C to stop)
```

- **这个窗口要保持开着**：关掉它或按 `Ctrl-C` 就等于把桥拆了。
- 窗口里**每 60 秒会打印一次连接状态**（只打含 `connector:` 的那两行），
  这样不用切窗口就知道编辑器连上没有。
- 编辑器里的扩展连上来的**第一次**会自动配对，daemon 窗口打印一条带指纹（8 位）的公告
  ——那就是"这台编辑器被信任了"。之后只有持有那个 token 的连接能进来。
- 要停：双击 `scripts\stop-daemon.bat`，或者直接关掉那个窗口。
- 换端口：先设环境变量 `BOARDWISE_PORT`，`start-daemon.bat` / `stop-daemon.bat` 都认它。

配对出问题（换了机器、想重新配对）：双击停止脚本后，在仓库目录里敲

```bat
.venv\Scripts\python.exe -m boardwise.cli bridge revoke
```

再重新启动 daemon，下一个连上来的扩展就会被信任。

> 截图位：`docs/images/install-04-daemon-pairing.png` —— daemon 窗口的启动横幅与那条配对公告。

---

## 第 5 步 · 让 `doctor` 全绿

在仓库目录里敲（也可以再双击一次 `install.bat`，它最后就跑这个）：

```bat
.venv\Scripts\python.exe -m boardwise.cli doctor
```

它一口气查七件事，**全绿才算装好**（退出码 0），每一条红项都自带修复建议：

| 检查 | 在问什么 | 红了怎么办 |
|---|---|---|
| daemon 可达 | 本机能连上 daemon | 跑第 4 步；端口不同时加 `--port` |
| 扩展已连接 | 编辑器里的扩展真的连上来了 | 打开编辑器、确认扩展启用；不行重做第 3 步 |
| 关键方法在位 | 编辑器暴露了 harness 要用的 5 个接口 | 编辑器太旧，升级立创 EDA Pro |
| 编辑器版本 ≥ 3.2.183 | 打标/缩放接口存不存在 | 升级立创 EDA Pro |
| daemon 版本与本机一致 | 跑着的 daemon 是不是你这份代码 | 重启 daemon（改了代码更要重启） |
| connector 版本与仓库一致 | 编辑器里跑的是不是最新那份 `.eext` | `boardwise bridge update-connector`（热更新，不用重装） |
| 当前工程焦点可读 | 编辑器里有没有打开一个工程 | 打开一个工程再跑 |

想要一份机器可读的报告：加 `--json doctor.json`。断开状态下 doctor 不会崩，
它会逐行说"未验证：……"并退出 1。

> 截图位：`docs/images/install-05-doctor-green.png` —— 七行全绿的输出
> （可复用 `gs-04-doctor-green.png` 的画法：真实输出渲染成终端样式）。

---

## 装好了 · 第一次审查

**先导出工程**：在编辑器里导出**工程备份**（`.epro2`，一个文件里同时带原理图和板子数据；
具体的菜单位置随编辑器版本不同，在"导出"相关的菜单里找"工程 / 备份"字样）。
导出对话框里**不要勾"加密"**：加密的导出 boardwise 读不了，它会明确告诉你重新导出、
而不是丢一堆报错给你。

```bat
rem 审查一个工程备份，同时生成人和机器都能读的报告
.venv\Scripts\python.exe -m boardwise.cli review D:\导出\你的板子.epro2 --json report.json --md report.md

rem 把发现画到编辑器画布上（需要第 4 步的 daemon 开着、编辑器里打开着对应原理图页）
.venv\Scripts\python.exe -m boardwise.cli review-mark report.json

rem 看完清掉标记
.venv\Scripts\python.exe -m boardwise.cli review-mark clear
```

`review` 的退出码：`1` 表示有 ERROR 级发现（是"发现问题"，不是命令失败）、`0` 表示没有、
`2` 表示文件读不了。`.epro2` 的 `--view` 缺省是 `pcb`；只画了原理图的工程在 pcb 视图里
读到的是 0 器件 0 网络，这时要加 `--view schematic`（终端和 `--md` 报告都会提示这一句）。
全部参数看 `boardwise review --help`；
`review-mark` 的用法、截图注意事项（`bridge screenshot` 在 3.2.186 上返回的是缓存空帧，
别拿它当证据）见 [`getting-started.md`](getting-started.md) 第 5 步。

> 截图位：`docs/images/install-06-first-review.png` —— 第一次 `review` 的终端输出与 `report.md` 的开头。

---

## 常见问题

| 症状 | 先看什么 |
|---|---|
| `python` 命令找不到 / 弹去商店 | 第 1 步，重装并勾 `Add python.exe to PATH`，然后重开命令行窗口 |
| `pip install` 报网络错 | 换镜像（见第 2 步），或确认代理设置 |
| 顶栏没有 `boardwise` 菜单 | 第 3 步没生效：重导 `.eext` 并**完全重启编辑器** |
| 任何 `boardwise bridge …` 说 `daemon not reachable` | 第 4 步的窗口还开着吗（用 `scripts\stop-daemon.bat` 确认/停止） |
| 报 `UNKNOWN_ACTION` | daemon 是旧的：按 `Ctrl-C` 停掉再重新双击 `start-daemon.bat` |
| 报 `NO_CONNECTOR` | 编辑器没连上：`boardwise → About...` 看状态，不行重做第 3 步 |
| 报 `PAGE_MISMATCH` | 编辑器焦点不在你以为的那一页/那块板上：切过去，或先 `bridge call --action doc.list` |
| 打标成功但画布上看不到 | 标记画在**最后聚焦的那块画布**上：用 `--page <pageUuid>` 指定，或先点一下目标页 |
| 命令打到了别的窗口 | 你开了多个编辑器窗口：只留一个（见开头那段警告） |
| 想看 boardwise 到底做了什么 | `C:\Users\<你>\.boardwise\audit\` 里当天日志，每个动作都有记录 |

装好之后想做什么：仓库根目录的 [`README.md`](../README.md)；桥的协议与全部动作见
[`docs/bridge.md`](bridge.md)。

## 给维护者（这段不是朋友看的）

- `scripts\*.bat` 是 **GBK/ANSI + CRLF**，第 2 行 `chcp 936`。原因见第 2 步末尾：
  cmd 按控制台代码页解析批处理文件，UTF-8 + `chcp 65001` 会被解析错位（实测会出现
  "把某一行的尾巴当命令执行"）。改脚本时不要把它存成 UTF-8，也不要删 `chcp` 那一行。
- 四个脚本各自的作用：`install.bat`（装 Python 环境）、`start-daemon.bat` / `stop-daemon.bat`
  （起停 daemon）、`build-connector.bat`（打 `.eext`）。
- 详细调查（打包流程、Python 包现状、doctor 覆盖范围、脚本的静态与实测验证）见
  `outputs/018_packaging_survey.txt`。
