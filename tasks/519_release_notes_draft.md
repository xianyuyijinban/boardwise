# v0.5.19 内测 · release notes 草稿

> 状态：草稿（2026-10-19 夜）。等三条修复缝全部回归后定稿。
> 规矩：正式版一周最多一发、何时发由岳定；内测版不影响这条。

## 这一版是什么

不是新功能。**四批「工具说了它没做的事」**，外加一块绘图线的性能与真因。

## 1. `bridge update-connector --no-reload`（528A）

给一个**不 reload 就换 connector** 的选择：只写进编辑器扩展存储，不派发 reload，exit 0 并告诉你「点一次扩展菜单生效」。
用它的场景是「窗口里有未保存的编辑」——默认路径仍然会 reload，那是预期行为。

**首次使用要注意**：如果编辑器里跑的是 528A 之前的 build，它**不认**这个开关，会照样 reload 并把
`reloadInMs: 500` 写进回复。所以第一次请先做一次默认更新（`boardwise bridge update-connector --yes`）落地新 build，
之后 `--no-reload` 才免 reload。CLI 会读回 `reloadInMs` 并明说「它仍然 reload 了」，不会像早期版本那样
断言「没有派发 reload」——那会让人以为未保存的编辑还在。

**`--version` 的语义收紧了**：它只写存储记录里的 version 字段，而 connector 上报的是 **bundle 内嵌版本**
（build 时从 `connector/package.json` 注入 `__BOARDWISE_VERSION__`）。两者不一致时验收永远不可能满足，所以
显式给出且不一致会 **exit 2、零写入**。要区分两份 build，请改 `package.json` 的版本号后重新 build 一份 bundle。

（这一版把闸的**前提读对了**：之前它比的是 `connector/extension.json`，而 `extension.json` 只出 uuid，
版本自始至终来自 `package.json`。两份 manifest 现在有一条一致性测试钉着——**改版本时两个文件都要改**。）

`--version " 0.5.18"`（带首尾空白，脚本里从文件读版本时很常见）不再绕过闸写进记录——那会产生一次必然的
假 FAILED 并劝你去卸载重装。`--version ""`（`--version "$VAR"` 而变量为空）现在视同没给，走默认路径，
不再抛 connector 的 `BAD_REQUEST`。被版本闸拒绝的命令也不会再顺手拉起 daemon / 生成 token。

**`--all --no-reload` 是逐窗的**：写共享存储记录只有一次，但「点菜单生效」要**每个在线窗口各点一次**
（或让它重载）。R4 实验④真机量到的就是这个语义。`DISCONNECTED` 也不再报「写入被拒」，
改说「连接断了，**不确定**这次写入有没有落地，重连后用 `--no-reload` 或 `bridge status` 核对」。

## 2. `parts classify` 的证据落货架（527D2）

`--from/--page/--quote` 三件套现在落到 `category_provenance`，`parts show` 能读回。
机器档分类终于能事后追溯出处，与 521「每条 fact 自带出处」的口径对齐。

**`source` 现在是硬的**：http(s) 必须与缓存里那份文档的 url **一致**（不一致 exit 2、零写入），
`http://` 这种没有主机名的串、`file:` 后面没有路径的串都会被拒。之前只要以 `http(s)` 开头就收，
等于让编造的 URL 也能当权威出处。

**⚠️ 单向兼容**：`category_provenance` 是**新键**。用 0.5.19 写过带证据的分类之后，回退到旧版本
（含 0.5.18 exe）会因 `unknown key(s) category_provenance` 让**整份** `~/.boardwise/parts.json`
加载失败（exit 2）——不是丢一条，是所有依赖货架的判定一起报错。要么别回退，要么回退前手工删掉这些条目里的该键。

**显示端更诚实了**：引文块只在机器档打印；机器档但没记引文会明说「未记录出处（该条目在 527D2 之前写入）」；
人签但带着引文会明说「这条分类是人签的，落盘的引文不参与判定」。
`docs/parts.md` 里那句「absent = a human is behind it」已改——缺引文只说明**没记**，谁签的只看 `category_trust`。

**整档重排**：`parts classify` / `parts add` 写回时会把整份货架按自己的格式重排（`indent=2` 等），
值不丢但 diff 是全文件。这条一直如此，现在文档写明了。

## 3. 分类读点的分档感知（527D3）

`entry.category` 的 17 个直读点全部改走 `partkind.declared_category` / `category_verdict`。
判据是 522 的老口径：**该规则产出的是「数字」还是「结论」**。数字类吃机器核验，结论类必须人签。

**关键的一条**：结论类遇到「机器核验的分类」时，规则出**带免责的 finding 或 UNKNOWN 行**，绝不静默跳过——
因为「档位不够」和「不是本规则的对象」是两件事，塌成同一个 `None` 会让一件真 MCU（只是分类没签字）
静默不被检查，那比改之前更糟。

现有货架（`blocklib/parts.json` 的 109 条）里 `category_trust` 一个都没有 ⇒ **这道闸对现状是恒等映射**，
产物逐字节不变。只有你自己用 `parts classify` 授予机器档之后才会看到新增的免责行。

## 4. 绘图线：A\* 换可采纳下界（201F）

A\* 的启发式从纯曼哈顿换成「从 goal 出发的反向 Dijkstra」，每步 1.0、进入异网线内部加 `CROSS_COST`、
**忽略转弯与共线禁止**（只减代价、只删路径 ⇒ 严格可采纳）。

- 反激整页编译 **23.0 s → 11.05 s**（2.08×）
- A\* 合计 **14.2 s → 2.05 s**（6.9×，其中建场 1.5 s）
- **83 个预览逐字节相同**（`tools/117_zero_move.py`），`final_cost` 一字不差

**别把它读成整页收益**：那 14.2 s 是在反激这个 `ok=False / candidates=0`、只走到 10 次 `route` 就早退的页上量的。
反激目前仍然 0 候选——原因不在 A\* 快不快，见下。

## 已知边界（不修，但要知道）

0. **frozen exe 里没有 `connector/package.json`**（`packaging/boardwise.spec` 只带 `extension.json`），
   所以打包版上版本闸走的是「读不到就回落 extension.json」的兜底。功能不受影响（两份 manifest 由测试钉相等），
   但「全链一个来源」在 exe 上是打折的。下个版本把 `package.json` 加进 spec 与 `resources.connector_package_json()`，
   兜底就永远不触发。`boardwise --version`（顶层显示）也仍读 `extension.json`。
1. **反激整页仍然 0 候选**，201G 已把真因拆成三层：① 构造阶梯的 `right-of(D3,T1)` 在 chain 上结构性无解
   （已被拓扑搜索兜住）② 拓扑档 `SEC_12V` 在 `D3.1` 的旗标席位（局部太挤）③ **修完 ② 之后 readability
   立刻拒 27 条，全是「文字 vs 几何」**。第③层才是真正的大山，下一批的主攻。
2. `pcb.geometry` 在原理图焦点下仍返回 `bboxes: 0` 且 exit 0（这条 528/527 都没修）。
3. `.eprj2` 仍不读，错误信息里给的是「导出 `.epro2`」的下一步。
4. `_FIELD_LATTICE_LIMIT` 的余量 95~182×，页规以上的页它拦不住（性能债，见 `outputs/201f/evidence.md` §八 F2）。

## 验证

- **pytest 全量 6621 passed / 25 skipped / 0 failed**（7:28；比挖洞前的 6567 多 54 条，均为本批新增回归）
- connector **536 passed** + `npm run typecheck` 干净
- dsh-plugin **50 passed / 1 skipped** + `npm run typecheck` + `npm run build` 干净
- 真机：`--no-reload` 在 `test` 窗验过（instance id 前后都是 `inst-124815447-jjcl4qpr` ⇒ 真没 reload；
  同时也反证了新 build 在跑，因为旧 build 不认 `reload:false`、缺省 reload 必执行）
- 83 个预览逐字节相同（`tools/117_zero_move.py` A/B）

## 挖洞与修复（这一版的主要工作量在这里）

四条缝各派一个**只读红队**，共挖出 **21 条**，修了 **20 条**（1 条只进 release notes）：

| 缝 | 洞 | 最重的一条 |
|---|---|---|
| 528A bridge | 5 + 3 附带 | 旧 connector 在场时 `--no-reload` **静默 reload**，而 CLI 打印「不会丢未保存状态」并跳过确认闸 |
| 527D2 证据落盘 | 6 | `source` 从来不是「引文被核对的那份文档」，编个 URL 就能落盘成权威出处 |
| 527D3 分档闸 | 9 | 草稿档电容把 DECAP-1 从 UNKNOWN 翻成**假 WARN** |
| 201F 启发式 | 1 + 3 记账 | memo key 漏了墙的三项输入（墙变少时旧场会高估），**实测 0 命中 ⇒ 直接删掉 memo** |

修复共 **14 组变异**验证，全部按预期变红后逐字节还原。
其中三条是本批**比改动前更糟**的真回归（527D3 的 S1/S2/S3），也就是说：**没有这轮红队，这三条会随版本发出去。**
