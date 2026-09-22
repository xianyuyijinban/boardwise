# 021 多工程能力实测与成熟方案

> 岳（2026-09-22 午后）："我开了三个工程，你去派 deepseek 测试。五点前把成熟方案摆出来。"
>
> 触发事实：岳在编辑器里开了三个工程，但 Kimi 实测 `doc.list` 的 `projects[]`
> **只报 1 个**（`'/test'`，focused=true），`activeDocument=null`。
> "agent 在多工程下工作得怎么样"的第一答案就是：现在连岳开的工程都看不全。

## 目标

17:00 前产出**实测驱动的多工程成熟方案**，写进本文件 §方案：
AI 要能 ① 看到岳打开的全部工程 ② 自主选择目标工程审查（只读）③ 自主选择目标工程删改（写）。
每一项给"已通 / 实测后通了 / 不通→替代协议"三态结论，不许含糊。

## 已知约束与既有事实（不要重复劳动）

- `doc.list` 的 projects[] 枚举走 `dmt_Project`；012 时 `dmt_Project.openProject`
  typeof=function 已证、**行为从未实测**；其余激活类 API 全 undefined；
  `activateDocument` 只切 tab 层不切工程。（012 任务书 §五）
- 写操作依赖 GUI 焦点工程——这是头号架构限制（012 交卷记录"头号"条）。
- 焦点会无人漂移（012 实测，多窗口+会话恢复所致）；热更 reload 会把焦点重置到别的工程（012v2 S4 实测）。
- daemon 单活跃 connector 防护（018）：第二个编辑器窗口的连接会被 CONNECTOR_ALREADY_ACTIVE 拒绝。
- `sys.identity` 报双层身份（工程焦点 vs 文档焦点）+ 一致性判定。
- `doc.focus`（tabId/pageUuid）只切已打开文档的 tab。
- connector 动作实现：`connector/src/actions.ts`（`doc.list` 约 :2315-2440，projects 枚举约 :2352 起；
  `doc.open` :2710，`doc.focus` :2451，`sys.identity` :2805）。Python 调用入口：
  `.venv/Scripts/python.exe -m boardwise.cli bridge call --action NAME --params 'JSON'`。
  `sys.probe` 可探宿主命名空间（用法参考 `outputs/012v2_probe*` 或 bridge call --help 的 actions 表）。
- daemon 已在跑（端口 61190），connector 0.4.11 在线。

## 真机纪律（红线）

1. **写操作只在 test / test2 工程**。禁地：毕设FOC驱动板、CH340G、ROBOT ctrl FOC 及一切真实工程——
   **包括不许作为 openProject/任何调用目标**，也不许对它们的页做任何写动作。
2. 任何写动作前先 R1：`doc.list` 焦点工程名与预期逐字一致才动手。
3. openProject 行为未知——第一次调用目标**只许是 test2**（若它不在已开列表，先停下来记录事实，不擅自打开别的工程）。
4. 不动 git。测试 `--basetemp=.tmp_pt_021`。证据写 `outputs/021_*`（UTF-8；这台机器 heredoc 重定向默认 GBK，必须显式 utf-8）。
5. 编辑器截图可用 `bridge screenshot`（只读）。

## 实测清单（按序执行，每步落证据）

### A. 宿主视角对齐（只读）
1. `bridge screenshot` 截图看左侧工程树：岳开的三个工程是哪三个、同一窗口还是多窗口。
2. `sys.probe` 枚举 `dmt_Project` 全部成员（typeof 表）——找"列出已打开工程"的可能入口
   （如 getOpenedProjects / getProjectList / openProject / setCurrentProject 之类，以实测为准）。
3. `doc.list` projects[] 现状（已知只 1 个）与 sys.identity 双层一致性。
4. 结论：宿主 API 能不能枚举"所有打开的工程"？不能就是不能，写清楚缺什么。

### B. openProject 行为实测（核心缺口）
1. typeof + 签名（length/probe）。
2. 最小调用：目标 test2（岳已开的三个里若有 test2；没有则按纪律 3 停下记录）。
3. 调用后读回：`doc.list`（focused 变没变）、`sys.identity`、activeDocument。
4. 若焦点切换成功：在 test2 的演练页放一个器件再删掉（R1 先核对），确认写落点跟焦点走。
5. 若调用报错/无效果/打开了意外的东西：逐字记录，不重试蛮干。

### C. 非焦点工程可读性
1. 对非焦点工程的页调 `sch.geometry` / `sch.readback`（传它的 pageUuid）——能读就是"跨工程审查"通了。
2. `review` CLI 对非焦点工程的可行路径（若 bridge 层读不了，review 走文件解析本就与焦点无关——确认 `review --latest` 的取文件逻辑在多工程下选的是不是用户想的那块板）。

### D. 焦点稳定性（短窗观察）
- 实测期间每完成一大项记一次 `sys.identity`，若焦点在无人操作时漂了，如实记录（这是方案里"写前必核"的依据）。

## 方案产出（§方案，实测后写）

按实测结果二选一（或组合）：

- **路线一（openProject 可用）**：设计并实现 `doc.focus_project` 动作——参数（projectUuid/name）、
  守卫（目标必须在已开列表、禁地名单由调用方纪律保证）、切换后自动读回 identity 确认、
  与 R1 的衔接文案。connector 实现 + 单测（npm test 子集）+ 真机验证三态（切成功/目标不存在/目标未打开）。
- **路线二（openProject 不可用）**：人机协作协议——AI 跨工程只读审查路径（哪些已通）、
  写操作前"请用户切焦点"的显式协商流程、doctor 增加多工程检查项的具体设计、
  以及 daemon 单活跃防护在多窗口下的用户指引（岳开多窗口时怎么办）。

无论哪条路线，§方案 必须含：**agent 多工程工作流**（发现→选定→审查→修改 的逐步协议，
每步用什么动作、失败时怎么诚实报错），按"今天朋友就能用"的标准写。

## 交卷要求

- §实测记录 + §方案 写进本文件（UTF-8，append 后 grep -c 防双执行）。
- 证据 `outputs/021_*`：screenshot、probe 表、openProject 调用前后读回、写落点验证。
- 若实现了 connector 动作：npm test 子集 + tsc 干净（全量留给 Kimi 复验）。
- 交卷总结报：三态结论（看/读/写 各是什么状态）、路线选择及依据、与既有事实冲突的任何发现。

---

# 021 实测记录（子代理交卷 2026-09-22 16:50）

> 证据前缀 `outputs/021_*`。**诚实前提一条**：本子代理工具集里**没有图像读取能力**
> （任务书点名要用的 `ReadMediaFile` 不在可用工具内），`outputs/021_screenshot_baseline.png`
> 已按 §A1 截下留档，但**我没有亲眼看它**。§A 改用比截图更硬的**文本证据**：
> OS 顶层窗口标题枚举（PowerShell `EnumWindows`）+ 绑定窗口自己的标签树 + `doc.list`。
> 截图请岳/主代理亲验，其余结论不依赖它。

调用入口一律
`.venv/Scripts/python.exe -m boardwise.cli bridge call --action NAME --params 'JSON'`；
读 error 的 `detail`（`openTabs` / `otherProjects` 等结构化字段）走自建只读小工具
`outputs/021_rawcall.py`（CLI 出错时只打印 errorName/errorMessage/stack 三个键，
`doc.focus` 的 NOT_FOUND 明细会被丢——已实测）。**所有 rawcall 调用必须 `PYTHONIOENCODING=utf-8`**，
否则这台 GBK 机器写出的证据文件是 GBK（已踩一次，见 `outputs/021_geometry_foreignpage.json` 的重跑）。

## A. 宿主视角对齐（只读）

### A1 岳开的三个工程 = 三个编辑器窗口（不是"一个窗口三个工程"）

`outputs/021_editor_windows.txt`（`EnumWindows` 枚举，PID 5240 同一个 `lceda-pro` 进程）：

```
5240 lceda-pro visible=True hwnd=17041766  反激辅助电源 | 嘉立创EDA(专业版) - V3.2.186
5240 lceda-pro visible=True hwnd=6688148   嘉立创EDA(专业版) - V3.2.186          ← 无工程名
5240 lceda-pro visible=True hwnd=3545490   test2 | 嘉立创EDA(专业版) - V3.2.186
```

本桥当前绑定的那个窗口，其 `getCurrentProjectInfo` = `/test`（uuid
`ea80fff642fa86cdc95882ab0201b0bb7ee6d966412a8958fec3ff95fa13f489`）——该 uuid **逐字命中
`E:\LC Project\test.eprj2`**（`grep -a`），且另两个窗口的标题已各自点名 test2 / 反激辅助电源，
故"无工程名"的那个窗口就是本窗口。→ 三个工程 = **`/test`(test.eprj2)、`test2`(test2.eprj2)、
`反激辅助电源`(反激辅助电源.eprj2)**，分属三个窗口，一个进程。

本窗口内确实只有一个工程（`outputs/021_document_current.json`、`021_opentabs_probe.json`）：
标签树 = `Start Page` + `P1.Schematic1` + `P4.Schematic1`，tabId 的 `@` 后缀全是本工程 hash；
`doc.list` 的 6 个文档、1 个工程也吻合。

旁证（daemon 审计，`outputs/021_connector_timeline.txt`）：除本实例
`inst-071907592-d4z9klul`（15:19:07 连上、一直是 active）外，另有**两个长期实例**
`inst-072913736-hv43vkft`（15:29:13 加载）与 `inst-072920682-elmoeou4`（15:29:20 加载）
各被拒 **48 次**、每 20–40 s 重试一次（`021_status_t2.txt` 现场也在刷同两行）
—— 与"15:29 岳开了另两个窗口"逐字吻合。

### A2 `sys.probe` 枚举 `dmt_Project`：12 个成员，没有"列已打开工程"这一号

`021_probe_dmt_Project.json`（枚举）+ `021_probe_checks_arity.json`（typeof + 声明 arity）：

| 成员 | typeof | arity |
|---|---|---|
| `openProject` | function | 1 |
| `getAllProjectsUuid` | function | 3 |
| `getCurrentProjectInfo` | function | 0 |
| `getProjectInfo` | function | 1 |
| `createProject` / `copyProject` / `deleteProject` / `moveProject` / `moveProjectToFolder` / `modifyProject*` | function | 5/5/1/3/2/2 |
| `getOpenedProjects` `getOpenProjects` `setCurrentProject` `activateProject` `openProjectByUuid` `getProjectList` `getAllOpenedProjects` `getProjectsInfo` `switchProject` | **undefined** | — |

`dmt_Workspace`：`getAllWorkspacesInfo`(0) / `getCurrentWorkspaceInfo`(0) / `toggleToWorkspace`(1)，
无"已打开工程"成员。`dmt_EditorControl`：`getAllEditorWindows` 等全 undefined；
`getSplitScreenTree` 是**窗口内**分屏树（doc.focus/doc.open 的 tab 来源）。
`dmt_SelectControl.getCurrentDocumentInfo`(0) 可用。

类型包契约（`connector/node_modules/@jlceda/pro-api-types/index.d.ts:942 / :1032 / :1041 / :1049`）：
- `openProject(projectUuid): Promise<boolean>`，JSDoc 原话：**"如若原先已打开其它工程且有未保存的变更，
  执行本操作将直接丢失所有未保存的数据"**。
- `getAllProjectsUuid(teamUuid?, folderUuid?, workspaceUuid?)` 的语义是"**团队/文件夹/工作区下的**工程"，
  **不是"已打开的工程"**。

### A3 现状读数与 `otherProjects`

`021_doclist_baseline.json`：`projects[]` 仅 1 条（`/test`，`focused: true`，`documents: "full"`）；
`021_identity_t0.json`：`consistent: true`（project-uuid），active = P4 `362924e0e16ce90a`；
`021_docopen_foreign_uuid.json`（doc.open 传外部 uuid 的失败诊断）：
`otherProjects: []`、`listingCount: 6`、`openTabs: []`。

**与 012 既有事实的冲突①（如实报）**：012 记录 `getAllProjectsUuid()` 答"整个工作区"。
本机实测**无参调用只回 1 条 uuid，且恰为焦点工程**（所以 `otherProjects` 恒空）——
而磁盘上 `E:\LC Project` 有 ~30 个 `.eprj2`。即：**在本机、本窗口，它答的是"本窗口已打开工程"**。
单样本，未做参数矩阵（teamUuid/folderUuid/workspaceUuid 三个入参都没试），标记为待复核。

### A4 「看得到全部已打开工程」= 不通（编辑器 API 层）

- 根因是**作用域**，不是缺一个方法：`eda` 上下文是**窗口级**的，每个窗口一套 `eda`、一套
  connector 实例；`getCurrentProjectInfo`/`getAllProjectsUuid` 只答本窗口；不存在跨窗口枚举成员。
- **可行的替代通道（本次未实现，见 §方案 2.3）**：窗口标题（OS）已能点出工程名——本次就是靠它
  定出三个工程；而 connector 的 `hello` 帧已有 `instanceId`/`connectorVersion` 钩子
  （`connector/src/transport.ts:256-262`），daemon 侧有 `ActiveConnector.as_status`
  （`src/boardwise/bridge/daemon.py:552`）与 `recentRejections`。让 hello 带上"本窗口打开的
  工程名/uuid"，`bridge status` 就能列出**所有曾连过的窗口及其工程**，并可做确定性选窗。

## B. `openProject` 行为实测 —— 结论：**调用通道不存在，行为仍未实测**

**没有"调用任意宿主 API"的通道**：动作表 49 个具名动作（`src/boardwise/bridge/protocol.py`），
connector 实现 38 个 handler（`connector/src/actions.ts:6031-6077` 的 `buildHandlers`），
`sys.probe` 只做 `typeof`/枚举且**明确不调用任何东西**（`actions.ts:1690` "Purely read-only: it calls nothing"）。
→ 012 写"`openProject` 行为从未实测"，**真正原因是桥里发不出这次调用**，不是没人试。这是**能力缺口**。

按红线（不新增临时 eval 类动作、不擅自改产品代码去试探一个已知破坏性 API），本次**没有调用
`openProject`**。并如实报一条**事实层面的阻塞**：纪律 3 要求首次调用目标只许 `test2`，而
`test2` 的 projectUuid 在**本窗口**拿不到（`getAllProjectsUuid()` 在本窗口只给焦点工程，
`otherProjects: []`）——即"只许打开 test2"这一条在数据上就无法满足，目标缺失即停（R3），
不擅自换目标、不擅自打开别的工程。

足以支撑路线选择的契约/结构证据（非行为实测，标明为契约证据）：openProject 作用域是**本窗口**
（不可能把别的窗口的工程"拉过来"）；破坏性（丢未保存变更）；目标必须在**本窗口**可见工程集里。

## C. 非焦点工程可读性 —— 不通，且是结构性的

1. **枚举不了**：非焦点工程的页清单拿不到（§A4），连 pageUuid 都没有（A3 的 `otherProjects: []`）。
2. **读通道只有"当前文档"一条**：`sch.readback` 无 `pageUuid` 参数
   （`protocol.py:261-266` 只有 `includePrimitives`），实测在 P4 为焦点时三次调用
   （不带 / `pageUuid:"ffffffffffffffff"` / `pageUuid:"b4298962367251c8"`=P1 真 uuid）
   **逐字节相同**（sha256 均为 `af4dde525a9052eeb580…`：
   `021_readback_noparam.json` / `021_read_foreign_page.json` / `021_read_nonfocused_page.json`）
   → `pageUuid` 被**静默忽略**，既不报错也不换页；`sch.geometry` 只有 `bboxIds`。
   （三次对照必须在**同一焦点**下比、且都按 UTF-8 落盘：先前一次 `021_readback_noparam.json`
   是 GBK 写出的，byte 比对会假报"不同"，已重采。）
3. **读落点跟焦点走（实测）**：`doc.focus` 切到 P1 后重读，内容改变
   （sha256 `9f93353e1064f890…` vs `af4dde525a9052eeb580…`，
   `021_readback_p1.json`（P1 在场）vs `021_readback_noparam.json`（P4 在场））。

`review --latest`（文件解析，与窗口/焦点无关；多工程下反而可靠，但**选文件要当心**）：
实跑其取文件逻辑（`cli.py:1049 _latest_scan_dirs` / `_newest_project_backup`），扫描
`~/Downloads`、`~/Desktop`、`E:/LC Project`，本次选中
`E:\LC Project\test_backup\test_2026-09-22-09-57.epro2`（`021_review_latest_pick.txt`）。
**它认的是"最近导出的 `.epro2`"，不是岳现在开着的那块板** → 多工程下必须显式给文件路径。

## D. 焦点稳定性（短窗观察）

采样 4 次（`021_identity_t0/t1/t2/t3_restored.json`，15:36 / 15:38 / 15:45 / 16:44）：
focused 恒 `/test`、active 恒 P4、`consistent` 恒 `true` —— **无人操作期间零漂移**。
注意本次只有 1 个窗口在场，**不可外推成"多窗口也不漂"**（012 已实测多窗口+会话恢复会漂、
热更 reload 会把焦点重置）。会话中唯一一次焦点变化是我主动 `doc.focus` 到 P1 再切回 P4
（`021_focus_p1.json`），属可解释变化；`doc.list` 前后除包装字段外内容一致（active=P4、6 文档、1 工程）。

## 写落点验证（B4 的等价物，全程在 `test` 工程内、零真机变更）

- **R1 前置**：写前 `doc.list` 焦点工程名 = `/test`（逐字），`sys.identity.consistent = true`。
- 写动作第一道闸 = **焦点页必须等于调用方声明的 pageUuid**（`guardPage`，`actions.ts:2121`）：
  - 声明外部 uuid → `PAGE_MISMATCH`（`021_write_guard_foreign_page.json`）；
  - 焦点已被我移到 P1 后再声明 P4 → `PAGE_MISMATCH actual=b4298962367251c8`
    （`021_write_guard_after_focus_moved.json`）→ **写落点跟的是"当下焦点页"，不是声明页**。
- 正向（零变更）：正确 pageUuid + 不存在的 primitive id → `{deleted: [], notFound: [...], failed: []}`
  （`021_write_guard_correct_page.json`）。
- 收尾：焦点已还原 P4，`doc.list`/`sys.identity` 与开局一致；未删除、未创建任何东西。
- 禁地：`反激辅助电源` 等真实工程全程**零触碰**（未作任何动作目标，连只读调用都没对它发）。

## 三态结论（看 / 读 / 写）

| 能力 | 状态 | 依据 |
|---|---|---|
| ① 看到岳打开的全部工程 | **不通**（编辑器 API 层，窗口级作用域）→ 替代协议：daemon 实例登记（hello 带工程名） | §A1/A4 |
| ② 自主选择目标工程**只读审查** | **不通**（跨工程枚举不到、读只有"当前文档"且焦点绑定）→ 替代：`review <file>` 文件路径 + 人工换窗 | §C |
| ③ 自主选择目标工程**写** | **不通**（② 是它的前提；写落点被钉在焦点页）→ 替代：换窗协商 + R1 + pageUuid 守卫 | §B/§C/写落点 |
| 附：本窗口内"按 uuid 选页读写" | **已通**：`doc.list`→`doc.open`/`doc.focus`→带 pageUuid 守卫的读写；焦点漂移被守卫当场抓住 | 写落点验证 |

# 方案（路线二为交付主体 + 路线一 spec 留档）

**路线选择依据（路线一前提不成立）**：① 桥里没有能调用 `openProject` 的通道（§B）；
② 契约明说是破坏性的（丢未保存变更）；③ 它作用域是本窗口，**治不了"三个窗口"这个真问题**；
④ 纪律 3 指定的首次目标 `test2` 在本窗口拿不到 uuid。因此今天能交付的成熟方案 = 路线二；
路线一写成 spec（§2.4）留待下一棒，且**真机执行前必须岳点头**（破坏性）。

## 2.1 agent 多工程工作流（发现 → 选定 → 审查 → 修改；今天朋友就能用）

**Step 0 发现"谁在场"**
- `bridge status`：active instance + refused 数（refused 数 = 还有几个编辑器窗口；今天没有工程名，
  要问用户一句"另几个窗口是哪些工程"）。
- `doc.list` + `sys.identity`：桥**只跟一个窗口说话**，这两个读数就是那个窗口的工程 → 这是 R1 的基准。
- **诚实报错**：必须说"**你开的另外 N 个窗口我看不到**（桥一次只连一个窗口），我只看到工程「X」"。
  **绝不许**把它说成"你只开了一个工程"。

**Step 1 选定目标**
- 目标 == 当前读数工程 → 进 Step 2/3。
- 目标 != 当前读数工程 → 进 §2.2 换窗协商；**换窗完成前不得有任何写动作**。
- 目标落在禁地名录 → 只允许 `review <file>` 离线审查，不碰桥。

**Step 2 审查（只读）**
- 焦点工程内：`doc.list` → `sch.readback` / `sch.geometry` / `sch.netlist` / `pcb.readback`；
  要审某一页先 `doc.focus`（pageUuid/tabId），切完**复核** `sys.identity` 再读。
- 任意工程（与窗口无关）：`boardwise review <file>` —— **路径必须显式给**
  （`--latest` 在多工程下会选"最近导出的 `.epro2`"，实测选中 test 的备份，见 §C）。
- 非焦点工程的**实机脚本级**审查：做不到 → 原话回"要脚本级审查，请把那个工程换到桥连的窗口来"。

**Step 3 修改（写）**
- R1 三连，全中才动手：`doc.list` 焦点工程名**逐字** == 任务书指定 → `sys.identity.consistent == true`
  → 目标 pageUuid 在 `doc.list` 里。
- 每个写动作都带 `pageUuid`；收到 `PAGE_MISMATCH` = 焦点被移动/漂了 → **立刻停、重核身份、重试不算**。
- 改完：`doc.list` + `sch.readback` 读回复核 → `sch.doc.save` → `bridge screenshot`/`export.render` 留证。

**Step 4 收尾**
- 记尾态 `sys.identity`；交卷写清"动了哪个工程 / 哪个页 / uuid / 改了什么"。

## 2.2 换窗协商（今天可用，无需改代码）

前提事实：桥**一次只连一个窗口**（`CONNECTOR_ALREADY_ACTIVE`，daemon.py:15-21 说明这正是为了
防"多窗口轮流把写打到恰好赢的那个窗口的焦点工程上"）。切换是"**谁先重试谁赢**"——
两个被拒实例每 20–40 s 重试一次（实测各 48 次），**不能指定**。故：

1. AI 停手，明说"要换窗口，需要你操作"；
2. 岳：**只保留目标工程窗口**（其他编辑器窗口关掉），或先 `bridge revoke` 再同样只留目标窗口；
3. 等 `bridge status` 的 active instance 变化（原窗口关闭后 daemon 会接管下一个重试者）；
4. AI：`doc.list` 焦点工程名**逐字**核对 == 目标（今天唯一可用的身份确认手段）；
   不对 → 回 1，**不许猜、不许将就**；
5. 确认后再动手；其它窗口可以再开回来（会被拒，无害——但它们的写永远不经桥）。

注意：`bridge revoke` 是**状态变更**（要人点头），且 revoke 之后**先重试的那个窗口会拿到桥**，
单独 revoke 并不保证选中目标窗口。

## 2.3 daemon / doctor 的多工程检查项（设计，待实现）

1. **hello 带工程身份**（最小、收益最大）：`connector/src/transport.ts:256-262` 的 hello 载荷加
   `projectName`/`projectUuid`（取 `dmt_Project.getCurrentProjectInfo`，取不到就省略，**不编造**）；
   daemon 侧 `ActiveConnector` + 拒绝记录 + `as_status`（`daemon.py:552`、`status_lines:346`）
   带上这两个字段 → `bridge status` 直接列出**每个窗口 + 它的工程名**，"三个窗口都在"变成可读事实。
2. **`bridge windows`（或 `status --json` 的 `instances[]`）**：列所有曾 hello 的实例
   （active + refused，含 lastSeen、connectorVersion、projectFriendlyName），并给确定性选窗的入口
   （例如 `bridge use --project test2`：daemon 只接受匹配该工程的 instance，其余照旧拒绝）。
3. **`boardwise doctor` 新检查项 `multiwindow`**：条件 `projects.length == 1 && refused 实例数 > 0`
   → 黄灯，文案"编辑器里还有 N 个窗口未连上桥（工程：A、B）；桥只会作用于当前连接的工程「X」"；
   带 `--expect-project NAME` 时，焦点工程名不符 → **红灯**（R1 自动化）。
4. `doctor` 现有的 `project` 项（`cli.py:5150-5175`）只报焦点工程，追加一句"另有 N 个编辑器窗口未连接"。

## 2.4 路线一 spec：`doc.focus_project`（下一棒执行，真机需岳点头）

用**具名动作**承载 `openProject`（安全边界靠动作目录，不做通用调用通道）：

- 参数：`projectUuid`(必填)、`confirm: true`(必填——破坏性)。可选 `expectFriendlyName`(核对)。
- 守卫顺序：a) 目标必须在**本窗口** `getAllProjectsUuid()` 返回集内，否则 `NOT_FOUND`，附本窗口可见工程列表；
  b) 目标 == 当前焦点工程 → 直接返回 `{alreadyFocused: true}`（不调宿主）；c) 缺 `confirm` →
  `CONFIRMATION_REQUIRED`；d) **禁地名单不由 connector 判定**（靠调用方纪律 + 人名核对），
  只在返回体回显工程名供人复核。
- 行为：`openProject(uuid)` → 读回 `getCurrentProjectInfo` 确认 → 双层一致性判定（同 `sys.identity`）
  → 返回 `{switched, fromProject, toProject, consistent}`。
- **破坏性必须写进契约**：类型包 JSDoc 明说会丢未保存变更 → 返回体固定带
  `warning: "openProject may discard unsaved changes in the previously open project"`。
  实现前还欠一个读数：**有没有"当前工程是否有未保存变更"的 API**（本次未探到，需 probe；
  探不到就**如实写"无法预检"**，并把确认文案写成"可能丢失未保存修改"）。
- 三态真机验证（岳在场）：① 切成功（前后 `doc.list`/`sys.identity` 对比）② 目标 uuid 不存在 →
  `NOT_FOUND` 且焦点不变 ③ 目标存在但不在本窗口可见集 → `NOT_FOUND` 且焦点不变
  （**这一态就是今天的默认态**，实测见 §A3/§B）。
- 单测：`connector/tests` 用 mock eda 覆盖四态（成功 / 已焦点 / 不可见 / 未确认）；
  交卷跑 `npm test` 子集 + `npx tsc --noEmit`，全量留给主代理复验。

## 2.5 与既有事实冲突 / 更正的清单

1. **012"`getAllProjectsUuid()` 答整个工作区"** → 本机无参实测只回 1 条（=焦点工程），
   与磁盘 ~30 个 `.eprj2` 矛盾；单样本待参数矩阵复核。若成立，012/018 里
   "`otherProjects` 能列出其它已开工程"的前提在本机不成立。
2. **012"openProject 行为从未实测"** → 更正为"**桥里根本没有能调用它的通道**"（38 个 handler 全具名，
   无 eval 类动作，`sys.probe` 不调用）——是**能力缺口**，不是实验缺口。
3. **`guardPage` 文案 bug**：对删除动作也说 "refusing to place"
   （`021_write_guard_foreign_page.json`）→ 建议按动作名定制措辞。
4. **多窗口是常态而非异常**：岳今天三个窗口里有一个是真实工程（反激辅助电源）。
   daemon 单活跃防护在多窗口下的真实含义是"**只能看到 1/3**"，用户指引必须写清
   "boardwise 永远只对一个编辑器窗口生效，且那一个窗口的工程名要每次核对"。
5. **`sch.readback` 的 `pageUuid` 会被静默忽略**（§C 实测逐字节相同）——
   参数会被丢掉而不报错，属"静默降级"，建议要么实现要么在文档里明确划掉。

## 2.6 证据文件清单（`outputs/`）

| 文件 | 内容 |
|---|---|
| `021_screenshot_baseline.png` | §A1 截图（**未经子代理亲验**，本子代理无图像能力） |
| `021_editor_windows.txt` | OS 顶层窗口枚举（三个窗口 + 标题） |
| `021_connector_timeline.txt` / `021_status_t2.txt` | 审计时间线 + 现场 status（两实例各被拒 48 次） |
| `021_probe_dmt_Project.json` / `021_probe_checks_arity.json` / `021_probe_dmt_Workspace.json` | 宿主成员枚举 + typeof/arity |
| `021_doclist_baseline.json` / `021_doclist_final.json` / `021_doclist_after.json` / `021_identity_t0/t1/t2/t3_restored.json` | 焦点/工程读数与稳定性（开局 vs 收尾**逐行一致**） |
| `021_document_current.json` / `021_opentabs_probe.json` | 本窗口标签树（只有本工程） |
| `021_docopen_foreign_uuid.json` | doc.open 失败诊断（`otherProjects: []`、listingCount 6） |
| `021_readback_noparam.json` / `021_read_foreign_page.json` / `021_read_nonfocused_page.json` / `021_readback_p1.json` | 读通道焦点绑定 + pageUuid 被忽略 |
| `021_geometry_foreignpage.json` | `sch.geometry` 同样无页选择 |
| `021_review_latest_pick.txt` | `review --latest` 实选文件 |
| `021_write_guard_foreign_page.json` / `021_write_guard_after_focus_moved.json` / `021_write_guard_correct_page.json` | 写守卫三态（零变更） |
| `021_focus_p1.json` | 会话中唯一一次焦点变化（已还原） |
| `021_rawcall.py` | 只读小工具：打印完整响应/错误 detail（UTF-8，`PYTHONIOENCODING=utf-8`） |

## 2.7 未做 / 留给下一棒

- `openProject` 行为**仍未实测**（无调用通道 + 破坏性 + 目标 uuid 不可得），见 §B。
- §2.3 的 daemon/doctor 改动**未实现**（本次时间只够实测+方案）。
- `dmt_Workspace.getAllWorkspacesInfo` / `toggleToWorkspace` 是否含"多工程"语义**未探**
  （需要能调用宿主 API 的通道；本次没有）。
- 真机零变更：未删除/未创建/未保存任何东西；焦点已还原（P4）；
  收尾 `doc.list` 与开局**逐行一致**（`021_doclist_final.json` vs `021_doclist_baseline.json`）。
- **未改任何产品代码**（`connector/src`、`src/boardwise` 零改动；`git status --short` 只有
  `tasks/021-multiproject.md` 与 gitignore 内的 `outputs/021_*`）→ 三线（pytest / npm test / tsc）
  本次无需跑（按三线纪律只对代码改动生效），全量复验留给主代理。
- **git 未动**（无 add/commit/checkout/restore）。

---

# 021 §2.3 最小落地件：hello 带窗口工程身份 → daemon 登记 → bridge status 列出「窗口 → 工程」映射（子代理交卷 2026-09-22）

> 完整证据（逐字 hello 帧、逐字 status 渲染、兼容性论证、测试数字、局限）：
> `outputs/021_hello_identity.txt`（UTF-8）。一次性证据脚本：
> `outputs/021_hello_capture.mjs`、`outputs/021_daemon_identity_probe.py`。

**改了哪些文件**：`connector/src/transport.ts`（hello 增 `projectName`/`projectUuid`，注入
`projectIdentity()` reader + 1500 ms deadline，读不到/抛错/不 settle 一律省略字段）、
`connector/src/actions.ts`（新增导出 `currentProjectIdentity(eda)`，复用既有 `projectIdentity`
共享读，永不抛、永不编造）、`connector/src/index.ts`（生产装配注入该 reader；依赖方向无环）、
`src/boardwise/bridge/daemon.py`（`_project_identity` 解析；`Connection`/`ActiveConnector`
登记；拒绝记录与 `hello` 审计带工程；`status_lines` 活跃行/拒绝行追加 `  [project name (uuid)]`
后缀 + 末尾 `projects seen:` 汇总行，无工程时输出**逐字节不变**）、
`src/boardwise/bridge/protocol.py`（`Connection` 增两字段）。测试：
`connector/tests/{transport,wiring}.test.mjs`（+5）、`tests/{test_bridge,test_bridge_cli}.py`（+5）。

**三态结论（本件范围内）**：①「看得到岳开了哪些工程」= **已通**（daemon 侧）：
`bridge status` 现在会打印
`projects seen: /test (active), 反激辅助电源 (refused), test2 (refused)`
——被拒窗口就是桥碰不到的另两个工程，其工程名来自它自己被拒前发出的 hello。
② 跨窗口**读**、③ 跨窗口**写**：本件未改变，仍是 §三态结论里的「不通 → 替代协议」。

**协议兼容**：旧 connector（无字段）↔ 新 daemon 照常握手，status 输出逐字节如旧（有专项测试）；
新 connector ↔ 旧 daemon 无碍——旧 daemon 只读 role/token/protocol/client/connectorVersion/
instanceId，`decode_frame` 不校验 params 内部键。

**测试**：`npm test` 310/310 通过、`npm run typecheck` 退出码 0；
`pytest tests/test_bridge.py` 60 passed、`tests/test_bridge_cli.py` 29 passed、
`test_bridge.py+test_bridge_cli.py+test_doctor.py` 112 passed（`--basetemp=.tmp_pt_021`）。
全量三线 + 真机验证留给主代理；真机需**重启 daemon**（本件新字段随进程加载）+
**重新打包 sideload 连接器**（0.4.11 之后的一版才会带这两字段）。

**已知局限（未做，留给下一棒）**：身份只在每次握手读一次——窗口内换工程不会刷新已登记工程名；
`status` 只覆盖 `recentRejections`（上限 5 条）里出现过的窗口；§2.3 的 `bridge windows` /
`bridge use --project` 选窗、doctor `multiwindow` 检查项与 `doctor project` 追加句未实现。

