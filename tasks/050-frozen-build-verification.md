# 050 冻结 exe 内嵌资源真构建核对

**性质**：验证，不是开发。无源码 / 测试 / spec 改动，无 git 变更，不碰 connector/、不碰真机与 bridge。

**来源**：047 §七.2 遗留原话——「未构建/未验证 exe：spec DATAS 已改，但 `packaging/build_exe.py`
需真跑一次才能说冻结态 exe 真的带上了 portmeta」，做法照 045b §四。涉及两处内嵌：
045b 的 `blocklib/parts.json` 与 047 F3 的 `blocklib/blocks.portmeta.json`
（`resources.parts_library()` / `resources.portmeta_sidecar()` + `core.portmeta.default_port_meta_path()`）。

## 一、做了什么 · 结论

用 **PyInstaller 6.22.3 真构建**一次，产物隔离到 `.tmp_build050/`，**没有替换**
`packaging/out/boardwise.exe`（构建前后 sha256 / mtime 同值）。

```bash
.venv/Scripts/python.exe -m PyInstaller --noconfirm --clean --log-level=INFO \
    --distpath E:/boardwise/.tmp_build050/dist \
    --workpath E:/boardwise/.tmp_build050/build packaging/boardwise.spec
```

（不用 `build_exe.py`：它硬写 `packaging/out/boardwise.exe` 且先 rmtree `packaging/build/`，
与"绝不替换已发布产物"冲突。差别一处：本次**未跑** `npm run build`，内嵌 index.js 用的是工作树
现成的 `d7b19f90…`，与现发布 exe 内嵌份同哈希；发版仍需走 `build_exe.py` 那一步。）

**结论：两处内嵌经真构建核对通过。** 新 exe 归档 `resources/` 下 5 条齐全，逐个
CArchiveReader 直抽后与仓库文件 sha256 逐字节一致；拷进空目录、cwd 在该目录、经 PATH 调用，
四项验证全过：

| # | 项 | 结果 |
|---|---|---|
| a | `doctor`（基线冒烟） | exit 1，3/8 PASS（离线三项）；5 项 FAIL 全是"扩展未连接"，本环境无活编辑器，非本任务范围 |
| b | 货架（parts.json 内嵌） | `parts show CH340G` exit 0；`parts missing --file` 打印的库路径 = `…\_MEI…\resources\blocklib\parts.json` |
| c | portmeta 内嵌 | `validate --spec …ch340g_usb_uart.json` → levels / power-tree 双 **pass**、`verdict: may proceed`、exit 0（缺 portmeta 时是 6 undecidable / STOPPED / exit 1）；显式 `--port-meta <坏路径>` **仍 fail-closed**（同上 exit 1） |
| d | 047 F2 冒烟 | `review <ch340_golden.epro2>` 默认视图 → `17 components, 13 nets`、0 ERROR / 1 WARN，与仓库态 dev CLI 逐字相同；`--view pcb` 对照给 `0 components, 0 nets` |

**对照隔离变量**：老 exe（内嵌 4 条，无 portmeta）在同一个空目录跑同一条 `validate`
→ 6 undecidable、`verdict: STOPPED`、exit 1，与 045b §七 实测吻合。跑了**两份**老 exe：
本机 `packaging/out/boardwise.exe`（`d1148ae9…`，未改动）与 **GitHub 上已发布的 v0.4.25 正式附件**
（`eb391aa5…`，`gh release download` 只读取回，sha256 = 服务端 digest）。唯一变量就是那一个
3 299 B 的 sidecar，即 047 F3 修的病在真构建的 exe 上确实好了。

**顺带钉死一条发版事实**：已发布的 v0.4.25 附件内嵌 4 资源、**没有 portmeta**，
朋友从空目录跑 `validate` 仍是 6 undecidable / STOPPED / exit 1 ⇒ **047 F3 的修还没到用户手上**，
要生效须再发一版（v0.4.26 或重传附件）。发不发归xianyuyijinban/主代理，本次没动 Release、没上传任何东西。

产物：`.tmp_build050/dist/boardwise.exe` 12 121 328 B
sha256 `546099b6a73c3111107b3239c1d3f09f85f1adb7eb4a4e47817ba2cff940ec52`
（旧产物 `packaging/out/boardwise.exe` 12 114 470 B / `d1148ae9…`，**未动**；差 +6 858 B、归档多 1 条：
portmeta 3 299 B + SKILL.md 新版大 431 B 是实差量，余下约 3.1 KB 属打包本身不逐字节确定）。
内嵌工程容器：**无**（R4 卫生红线守住）。构建日志 13 s、exit 0、无 ERROR（warn 文件只有 posix-only 与
PyInstaller 自身条目，无 boardwise 模块缺失）。

完整命令输出、内嵌资源逐条哈希、构建日志全文：`outputs/050_frozen_build_verification.txt`。

## 二、遗留

1. **未跑 pytest / connector / dsh-plugin / tsc**：本任务无代码变更，任务书亦未要求。
2. **未替换已发布产物、未动 Release / 附件 / notes、未 commit**（git 归主代理）。
3. **不算一次完整发版构建**：缺 `npm run build` + 其版本交叉核对（本次手工核过：
   extension.json 与 package.json 都是 0.4.25）。真发版跑 `python packaging/build_exe.py`。
4. doctor 要 8/8 须真机联调（本次不接 bridge）；已发布的 v0.4.25 附件内嵌的 `SKILL.md` 还是
   047 之前那版（`5f62bcdb…` ≠ 仓库当前 `30e7869c…`），portmeta 更缺（见 §一 末段）。
5. 任务书写 `packaging/dist/`，实际发布产物目录是 **`packaging/out/`**；仓里没有 `packaging/dist/`。
6. `outputs/` 是 gitignore 的本地证据目录（045b/047 的同名文件同样未入库），故待提交的只有本任务书。
