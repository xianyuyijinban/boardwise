# 一次性提交清单 — 018（朋友内测版：基础体验 + 安装包 + skill 统合 + 审查主线）

> **范围更新（2026-09-22 10:4x）**：019（review 空板视图诊断提示）已交卷，同载 cli.py/i18n.py/文档，按同一理由折入本合并提交——现为 **016+018+019 单提**。

> 2026-09-22 整理。执行者：岳翔宇（AI 不动 git，等你点头；点头后谁执行都行）。
> 基线：最后提交 `91b67f3`（PROGRESS→M3 入口记录）之后全部未提交改动 = **016 + 018**，边界干净。
> 复验后状态：pytest **1259** / connector **305 pass** / tsc 干净（三线 Kimi 串行亲跑，019 后终值）。
> 任务书：`tasks/018-beta-basic-experience.md`；016 任务书：`tasks/016-review-to-local-edit.md`（§十.7 波②实测）。

## 1. 建议的提交方式：016+018 合并为单一提交（对"一任务一 commit"的一次破例）

**原因**：`src/boardwise/cli.py` 一个文件同时装着 016（edit plan/preview/apply 族 + exit 2→3 收尾）
和 018（sys.identity 接入 apply 守卫链、review --latest/--md）。git 按文件暂存，
拆两个提交要么产生中间不过测试的坏提交，要么要求你手工 `git add -p` 挑 hunk——都不值。
016 清单（`tasks/016-commit-checklist.md`）因此标注"由本清单取代"。

```bash
git add src/ tests/ connector/src/ connector/tests/ connector/extension.json connector/package.json connector/package-lock.json \
        docs/ scripts/ .kimi-code/ AGENTS.md README.md PROGRESS.md \
        tasks/016-review-to-local-edit.md tasks/016-commit-checklist.md \
        tasks/018-beta-basic-experience.md tasks/018-commit-checklist.md
git add -f outputs/016_* outputs/018_*
git commit   # 建议标题见下
```

建议标题：
`016+018+019: review-to-local-edit（值修改闭环+四保护+saved_verified）& 朋友内测版（daemon单活跃防护/写前身份判定/安装包/skill统合/review --latest+中文摘要/空板视图提示）, pytest 1259, connector 305, eext 0.4.11`

注意：
- **`tasks/017-eval-set-expansion.md` 不随本提交**（草稿，三个决策点待岳裁）。
- **`connector/boardwise-connector-0.4.11.eext` 不入库**（.gitignore 已挡，与先例一致；
  发布渠道 = 朋友直接从仓库文件拷或岳转发）。
- `.tmp_pt_home/`、`.tmp_018*` 等一切临时文件不提交。

## 2. 文件清单（git status 35 条逐条归置）

### 016 部分（Review-to-local-edit，M3 首切片）

| 文件 | 内容 |
|---|---|
| M `src/boardwise/rules/base.py` | `FindingTarget` + `Finding.target`（可选，默认 None） |
| M `src/boardwise/rules/facts.py` | `findings_from` 放宽三元组（向后兼容） |
| M `src/boardwise/rules/params.py` | `_human_value` + VIOLATION 行三元组（仅 ValueMpnMatch） |
| M `src/boardwise/cli.py`（与 018 共载） | `edit plan/preview/apply` 子命令族 +1178 行；**收尾**：apply 断连 exit 2→3 |
| N `src/boardwise/core/changeplan.py` | ChangePlan 纯离线模型（438 行） |
| N `tests/test_016_edit_cli.py` | 51 用例 |
| N `tasks/016-review-to-local-edit.md` / `016-commit-checklist.md` | 任务书（含 §十 真机记录）/ 清单 |
| 证据 | `outputs/016_*` 9 份（probe/apply×3/plan/scene4/事故/清污/wave2_review，`-f` 纳入） |

### 018 部分（朋友内测版）

| 文件 | 内容 |
|---|---|
| M `src/boardwise/bridge/daemon.py` | **单活跃 connector 防护**：hello 三态（接纳/`CONNECTOR_ALREADY_ACTIVE` 拒绝/旧死接管）+ `connector_rejected` 审计 + `bridge status` 显示 |
| M `src/boardwise/bridge/protocol.py` | hello-ack 带 `minConnectorVersion="0.4.10"` |
| M `src/boardwise/cli.py`（续） | `sys.identity` 接入 edit apply 守卫链（不一致→exit 4 零写入；老 connector 降级放行）；`review --latest [目录]` + `--md` 中文摘要节；**019**：`_pcb_view_read_nothing` 判据 + 空板提示行 |
| N `src/boardwise/rules/i18n.py` | 15 规则 id 中文名（`--json` schema 逐字节不变）；**019**：空板中文提示 |
| M `tests/test_bridge.py` / `test_bridge_cli.py` | daemon 防护 + sys.identity/exit3/--latest 测试（+690 行） |
| N `tests/test_018_cli_review.py` | review --latest/--md 用例 |
| N `tests/test_019_empty_board_hint.py` | 019 空板提示 11 用例 |
| N `tasks/019-review-empty-board-hint.md` | 019 任务书+交卷复验 |
| M `connector/src/actions.ts` | `sys.identity` 新动作（两层焦点+consistent+活动页） |
| M `connector/src/transport.ts` / `index.ts` | 拒绝帧处理、版本展示 |
| M `connector/src/version.ts` + `extension.json` + `package.json` + `package-lock.json` | **0.4.11** |
| M `connector/tests/transport.test.mjs` / `wiring.test.mjs`；N `identity.test.mjs` / `version.test.mjs` | connector 侧测试（305 总） |
| M `docs/bridge.md` | sys.identity 动作行 |
| N `docs/install.md` | 朋友六步安装指南（全程中文，面向硬件工程师） |
| N `scripts/` | `install.bat` / `start-daemon.bat` / `stop-daemon.bat` / `build-connector.bat`（GBK+CRLF 为裁定，见 outputs/018_packaging_survey.txt） |
| N `.kimi-code/skills/boardwise/SKILL.md` + `AGENTS.md` | 仓库首份项目级 skill（197 行）+ 轻量红线指向（26 行） |
| M `README.md` / `docs/getting-started.md` | --latest 用法 + install.md 指引（中英） |
| M `PROGRESS.md` | baseline → 1259/305/0.4.11 |
| N `tasks/018-beta-basic-experience.md` | 任务书 + 交卷记录 + 补记 |
| 证据 | `outputs/018_*` 3 份（install_test / packaging_survey / skill_survey，`-f` 纳入） |

### 不提交

`tasks/017-eval-set-expansion.md`（草稿）、`.eext` 产物、`.tmp*`、其余 outputs 历史文件保持不动。

## 3. 实测结论速览（提交信息可引）

**016**：三命令闭环 plan→preview→apply；四保护全落地有测试（快照失效拒 4 / 范围外零触碰 /
回读不符即败 2 / 断连只回读不重试 **3**）；幂等 `already_applied` 零写入；变异 3/3+抽验 CAUGHT；
评审基线 015b 逐字节不变。真机波②：场景 1/3 exit 0、场景 2 stale exit 4、场景 5 断连
（抓到 exit 2 bug 已修为 3）、场景 4 不可模拟、**场景 6 挂起待岳重开工程**（如实记录）。
副作用发现：`.eprj2` 是工程目录册，器件级持久化只能走编辑器通道验证（§十.6）——场景 6 已按此口径闭环（saved_verified，`outputs/016_scene6_final.txt`）。

**019**：空板视图提示——变异双 CAUGHT、真实样本两 view 亲跑符合预期；--json 逐字节不变。

**018**：daemon 单活跃防护**真 daemon 五拍验证**（接纳→拒绝点名占用者→status 列拒绝→
旧死接管→断开无残留）；写前身份判定机制化（sys.identity 进 apply 守卫链，变异 M1/M2 双
CAUGHT）；doc.open 跨工程报错含指引；`review --latest`+中文摘要真机走通；install.bat
**干净沙盒实测 PASS**（outputs/018_install_test.txt）；connector 0.4.11 eext 已打包（46.8KB）。

## 4. 提交后同步项

- PROGRESS.md 已在工作区同步（1259/305/0.4.11，随本提交一起进）。
- 提交后只剩一件事：把 Git anchors 的新 commit 号补进 PROGRESS.md（下次提交顺带即可，
  不为这一行单开提交）。

## 5. 遗留（不阻塞本提交）

- ~~016 场景 6~~（已闭环：2026-09-22 上午 PASS，saved_verified）。
- 017 评测集扩充三个决策点（选板 / board24v triage / 标注节奏）——等岳裁。
- tests/test_bridge_cli.py 有 35 行×2 逐字节重复测试（波②发现，待裁删）。
- 连接器被拒后无限退避重连无友好提示（§A/§B 提过，未做）；daemon 无协议级 ping（既有决策）。
