# 一次性提交清单 — 016（Review-to-local-edit：单器件值修改闭环，M3 首切片）

> 2026-09-21 整理。执行者：岳翔宇（AI 不动 git，等你点头）。
> 基线：最后提交 `91b67f3`（PROGRESS→M3 入口记录）之后全部未提交改动属于 **016**，边界干净。
> 复验后状态：pytest **1196** / connector **279** / tsc 干净（三线 Kimi 亲跑）。
> 任务书：`tasks/016-review-to-local-edit.md`（§一~§七 规格、§八 执行者交卷、§九 Kimi 复验、§十 真机记录）。
> **定稿注记（2026-09-22）**：波②已落卷（§十.7），但 cli.py 同载 016 与 018 改动、按文件不可拆，
> 故**提交方式以 `tasks/018-commit-checklist.md` 的 016+018 合并单提为准**，本清单§1 的方案废止；
> §2/§3 的文件归属与实测结论仍有效（测试数已被 018 刷新为 pytest 1248 / connector 305，
> connector 版本经 018 升至 0.4.11；§4 的 0.4.10 口径随之作废）。

## 1. 建议的提交方式

~~单一提交（与历次先例一致）。~~ **已由 018 清单的 016+018 合并单提取代**（原因见该清单§1）。

```bash
git add src/ tests/ tasks/016-review-to-local-edit.md tasks/016-commit-checklist.md
git add -f outputs/016_*
git commit   # 建议标题见下
```

建议标题：
`016: review-to-local-edit — component-value ChangePlan (plan/preview/apply), Finding.target, four protections, pytest 1196`

注意：
- **`tasks/017-eval-set-expansion.md` 不随本提交**（草稿，待岳裁决选板/triage/节奏后再提，或单独小提）。
- `git add -f outputs/016_*` 纳真机证据（probe + 6 场景，波②落卷后按实际文件核对）。

## 2. 文件清单（git status 逐条归置）

**Modified（4，全部 016 波①）**

| 文件 | 来自 |
|---|---|
| `src/boardwise/rules/base.py` | `FindingTarget` 22-41 + `Finding.target` 63（可选，默认 None） |
| `src/boardwise/rules/facts.py` | `findings_from` 100-124 放宽三元组（向后兼容） |
| `src/boardwise/rules/params.py` | `_human_value` 112-140 + VIOLATION 行三元组 301-314（仅 ValueMpnMatch） |
| `src/boardwise/cli.py` | `edit plan/preview/apply` 子命令族 +1178 行（dispatch 4751） |

**New（3）**：`src/boardwise/core/changeplan.py`（438 行，纯离线）、`tests/test_016_edit_cli.py`（51 用例）、`tasks/016-review-to-local-edit.md`（任务书，含 §八/§九 交卷复验）。

**不提交**：`tasks/017-eval-set-expansion.md`（草稿）、`.tmp_pt_home/`、`connector/`（零 TS 改动）、`outputs/016_*` 走 `-f`。

## 3. 实测结论速览（提交信息可引）

- 三命令闭环：`edit plan`（离线，规则→ChangePlan）→ `edit preview`（sha256 快照 + 语义差异）→ `edit apply`（前置重读→单次单 key 写入→双重回读→save→复查）。
- 四个保护全部落地并有测试：快照失效拒绝（退出 4）、范围外零触碰（clobberedOtherKeys 亮出）、回读不符即失败（退出 2）、超时/断连只回读不重试（退出 3）。
- 幂等：重复 apply → `already_applied` 零写入；幂等检查先于失效检查（3983/3993 顺序）。
- 变异验证：执行者 3/3 + Kimi 独立抽验（changeplan kind 门 ⇒ 2 红）全 CAUGHT，sha256 还原一致。
- 评审基线零侵入：`outputs/015b_eval_{dev,holdout}.txt` 与基线逐字节相同。
- 真机 6 场景（§十.7 实测，证据 `outputs/016_*`）：场景 1 成功 exit 0（四保护全过，saved_unverified，`016_apply1.json`）；场景 3 幂等 exit 0 `already_applied` 零写入（`016_apply2_idempotent.json`）；场景 2 人工改动 exit 4 `stale_before` 零写入（`016_apply3_stale.json`）；场景 5 断连实测 exit 2 → **判波① bug，已修 cli.py return 3 + 补测试**；场景 4 保存失败不可模拟（`016_scene4_save_path.txt`）；**场景 6 PASS（saved_verified）**：整编辑器重启后 R1 带 1k 复活、`review --view schematic` 导出 #2 findings 0/0/0（`016_scene6_final.txt`；今晨一度误判 FAIL，系编辑器同步滞后陈旧视图 + 缺省 view=board 双坑，教训进 skill 坑表 13/14/15）。插曲：身份双查抓到编辑器焦点实为 ROBOT ctrl FOC 禁地（§十.5），守卫未放行越界写。

## 4. 提交后同步项（PROGRESS.md，AI 已备口径）

- baseline：commit→新号；pytest **1196** / connector **279** / connector version **0.4.10**（未动）；日期 2026-09-21。
- Milestones 加一行：`016 review-to-local-edit（M3 首切片） | DONE 2026-09-21 | edit plan/preview/apply 闭环 + 四保护 + 真机 6 场景；tasks/016-review-to-local-edit.md`。
- Git anchors 加一行。

## 5. 遗留（不阻塞本提交）

- 波②待裁/口径项（若 §八.7 有新增待裁，落卷后在此补列）。
- 复查口径长期解：`.eprj2` 解析或 readback→model 适配（M3 后续任务候选）。
- 017 评测集扩充（等岳裁决）；M3 后续变更类型（补器件/修单脚/插 RC/移块，按岳定顺序）。
