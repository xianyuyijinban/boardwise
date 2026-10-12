# 179 connector 0.4.31：两个动作的真 bug（178b 立案）

任务编号 179。类型：connector bug 修复 + 版本 bump + 真机验证。178b 探针立案，原始证据在
`outputs/178b/evidence.md` 的「坑立案」节与 `outputs/178b/live/02_fullsrc_b4298962367251c8.json`。

## Bug 1（主）：`sys.get_document_source` 忽略 `uuid` 参数

**实测**：先 `doc.open` 到 P22，再调 `sys.get_document_source {uuid: P1的uuid}`，回来的
DOCHEAD 是 P22 的（`790ff841f8a73c11`）——**总返回当前活动文档**，`uuid` 参数被静默丢弃；
`maxChars` 参数有效。API 说谎比 API 报错可怕：调用方以为读到了指定文档。

**先做的事（决定修法）**：
1. 全仓 grep 生产侧调用方（`src/boardwise/cli.py`、dsh-plugin、connector 自身）谁在用
   `sys.get_document_source`、传的 uuid 是不是总是活动文档的——评估修复的行为影响面。
2. 查宿主 API（connector 源码里 eda.* 的用法 + 既有注释/证据）：有没有「按 uuid 读文档
   内容而不切换活动文档」的原生通道。

**修法二选一，按调查结果定**：
- 宿主支持 → 按 uuid 如实读（不切换活动文档；切换是副作用，不是本动作的契约）；
- 宿主不支持 → **诚实拒绝**：uuid 与活动文档不一致时回结构化错误（`DOC_NOT_ACTIVE`，
  附「先 doc.open」指引），绝不静默回错文档。uuid 省略时保持现行为（读活动文档）。
不管哪条，`maxChars` 行为不许变。

## Bug 2（次）：`doc.rename` 假动作

**实测**：对新建页调 `doc.rename` 回 `{"renamed": false}`，名字没变。查参数名/宿主能力，
能修就修成真的；宿主做不到就回结构化 `NOT_SUPPORTED`（别回 false 装没事）。

## 红线与验收

- 先读 E:\boardwise\AGENTS.md（41 行）。禁 git、禁 rm；connector 目录内干活。
- 版本 bump：connector `package.json` / `extension.json` → **0.4.31**；daemon 侧动作表
  若需同步（`bridge/protocol.py` 之类）按既有版本制同步。
- 四线里 connector 两线必跑：`cd connector && npm test && npm run typecheck` 全绿；
  改动若碰 Python 侧调用方，pytest 受影响文件走 `--basetemp=.tmp_pt_179`。
- 真机验证（test 工程窗口，`--project test`，只读为主）：修后 `sys.get_document_source`
  按 uuid 读到正确文档（或诚实拒绝）；`doc.rename` 在 scratch 页验证后**删页复原**
  （178b 的手法：建→验→删，终态与探前一致）。**写操作只限 test 工程 scratch 页**。
- 打包 `npm run package` 出新 `.eext`，但不发 release（v0.5.11 统一发）。
- 变异验证 ≥2（cp 备份 + sha256 还原）：至少一组「修后的校验被拿掉 → 测试红」。
- 证据落 `outputs/179/evidence.md`（append + grep -c 防双写），真机读数落 `outputs/179/live/`。

## 交卷

两 bug 各：根因（文件:行号）/ 修法与理由 / 影响面评估 / 测试与真机证据 / 遗留。
顺带回答：生产侧哪个调用方依赖了 Bug 1 的旧行为（若有），修复对它有无影响。
