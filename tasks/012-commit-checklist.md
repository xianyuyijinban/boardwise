# 一次性提交清单 — 012（基础体验线：多项目 / fab 导出 / 选型推荐 / 审查回显 / doctor / 打包）

> 2026-09-21 整理。执行者：岳翔宇（AI 不动 git）。
> 基线：最后提交 `5958b1c`（011/M1，09-20）之后**全部未提交改动都属于 012 线**
> （§三~§十 + 连接器硬化），边界干净，无跨线杂物。
> 交卷时状态：pytest **1134** / connector **266** / tsc 干净；
> 产物 `connector/boardwise-connector-0.4.6.eext`（40217 B，被 gitignore，分发用不入库）。
> 唯一未闭环项：**真机验证积压**（编辑器扩展自 09-21 ~13:20 未重连，清单见任务书末节）——
> 不阻塞提交：真机发现的问题走 013 修复轮。

## 1. 建议的提交方式

单一提交（与 009d2/010c/011 先例一致，一条任务线一次交卷）。

```bash
git add README.md connector/ docs/ src/ tests/ tasks/
git add -f <证据文件，见 §3>
git commit   # 建议标题：012: basic experience — sch/pcb delete+modify, multi-project list/focus, export-fab, lib.recommend, review-mark, doctor, connector 0.4.6
```

注意：`connector/` 下 `.eext` 与 `dist/` 均被 gitignore，不会被误带进来；
`connector/tests/actions012*.test.mjs` 是新测试文件，`git add connector/` 会带上。

## 2. 文件清单（git status 的 20 项逐条归置）

**Modified（13，全部 012 线）**

| 文件 | 来自 |
|---|---|
| `connector/src/actions.ts` | §三 delete×2、§四 modify×2、§五 projects[]、§六 export.fab、§七 lib.recommend、§八 review.mark、active:"0" 归一化（+~1900 行） |
| `connector/src/protocol.ts` | NOT_FOUND 错误码（第一批） |
| `connector/extension.json` / `connector/package.json` | 0.4.5 → 0.4.6（两处必须同改，build.mjs 从 package.json 注入 VERSION） |
| `connector/tests/doc-actions.test.mjs` | active:"0" 归一化 4 用例（+65 行） |
| `docs/bridge.md` | §4 动作表/ping 行、§5 错误码 +3 行、§8 self_update 设计说明、§10 item 4、§12 计数与证据、§13 产物行（11 处陈旧修正 + 各批同步） |
| `docs/getting-started.md` 既有段无（见 New） | — |
| `README.md` | 中英 quickstart 各 +§六~§九 指引 |
| `src/boardwise/bridge/daemon.py` | ping 增 `version` 字段（第三批，Kimi 裁决批准） |
| `src/boardwise/bridge/protocol.py` | 动作注册 7 条（delete×2/modify×2/delete_page/export.fab/lib.recommend/review.mark）+ DELETE/FAB/RECOMMEND 超时（+~230 行） |
| `src/boardwise/cli.py` | export-fab 落盘、review-mark、doctor（三分支 uuid=0 措辞）、`_repo_connector_version`（+~1050 行） |
| `src/boardwise/engines/review.py` | `finding_refs` + render_json 每 finding 增 `refs`（纯增量，规则零改动） |
| `tasks/012-basic-experience.md` | 任务书 + 交卷记录（第一批/S1+S3/真机批/第二批/第三批/第四批/第四批补充 + 真机验证积压清单） |
| `tests/test_bridge.py` | ping version 断言（+4 行） |
| `tests/test_doctor.py` | uuid=0 措辞 1 换 3 + 版本从仓库读（绿灯不写死） |

**New（7）**

| 文件 | 内容 |
|---|---|
| `connector/tests/actions012.test.mjs` | §三§四§五 契约测试 17 例 |
| `connector/tests/actions012b.test.mjs` | §六§七 契约测试 32 例 |
| `connector/tests/actions012c.test.mjs` | §八 契约测试 28 例 |
| `docs/getting-started.md` | 非开发者六步上手指南（内测版随附文档） |
| `tests/test_doctor.py` | doctor 19+3 例 |
| `tests/test_fab_export.py` | export-fab 落盘 14 例 |
| `tests/test_review_mark_cli.py` | review-mark CLI 29 例 |

**不提交（gitignore 已挡）**：`connector/boardwise-connector-*.eext`（分发产物）、
`connector/dist/`、`outputs/`（见 §3 例外）、`.tmp_*`。

## 3. `git add -f` 证据清单（outputs/ 被 gitignore，交卷记录引用的必须入库）

```
git add -f outputs/012v2_probe.md outputs/012v2_probe_declarations.txt \
  outputs/012v2_test_inventory.txt outputs/012v2_s3_cleanup.txt \
  outputs/012v2_s4_lifecycle.txt outputs/012v2_s6_s7_offline.txt \
  outputs/012v2_s8_s9_offline.txt outputs/012v2_s9_doctor_nodaemon.json \
  outputs/012v2_P3_before.png outputs/012v2_P4_before.png \
  outputs/012v2_p5_after_doclist.txt outputs/012v2_p5_daemon.log \
  outputs/012v2_p5_delete_attempt1.txt outputs/012v2_p5_disk_verify.txt \
  outputs/012v2_p5_final_doclist.txt outputs/012v2_p5_focus_timeline.txt \
  outputs/012v2_p5_history_nodes.txt outputs/012v2_p5_probe_openproject.txt \
  outputs/012v2_p5_run.log outputs/012v2_p5_save.txt
```

（真机验证完成后产生的新证据随 013 修复轮入库。）

## 4. 提交后同步项（PROGRESS.md，AI 已备草案）

- Current baseline 段：commit → 新提交号；pytest **1134** / connector **266** / connector version **0.4.6**；日期 2026-09-21。
- Milestones 表：M1 行 立项 → **DONE 2026-09-20**（5958b1c）；新增行
  `| 012 basic experience（内测版 0.4.6） | DONE 2026-09-21（真机验证走 013） | 本清单 + tasks/012-basic-experience.md |`
- Git anchors 加一行新提交。

## 5. 真机验证积压（不阻塞本提交；完成后随 013 入库）

按任务书末节"真机验证积压"清单顺序：doctor 首跑 + lib.recommend（不挑工程）→ §五 多项目 → §八 review.mark（岳指定工程）→ §六 export.fab（岳指定工程，BOM 15 列风险）→ 上手文档截图 ×6。
触发条件：编辑器扩展重连（重连后**先重启 daemon**——新动作与 ping.version 是加载期常量——再 `bridge update-connector`，dist 已构建）。
