# 一次性提交清单 — 015（审查规则 M2 批①：MPN 解码器越界修复 + decoupling-per-ic 退役）

> 2026-09-21 整理。执行者：岳翔宇（AI 不动 git，等你点头）。
> 基线：最后提交 `d8a1490`（PROGRESS→013）之后全部未提交改动属于 **015 批① + gs-02 补图**（013 遗留一张），边界干净。
> 复验后状态：pytest **1139** / connector **279** / tsc 干净（三线 Kimi 亲跑）；holdout 检出 33/33、hp-prec 33/40 = 0.82。
> 任务书：`tasks/015-review-rules-m2.md`（§六 执行者交卷 + §七 Kimi 复验落笔）。

## 1. 建议的提交方式

单一提交（与历次先例一致）。

```bash
git add README.md docs/ src/ tests/ tasks/
git add -f outputs/015_*
git commit   # 建议标题见下
```

建议标题：
`015: review rules M2 batch 1 — MPN decoder rejects non-EIA notations (electrolytic/voltage-tail/R-decimal → UNKNOWN), decoupling-per-ic retired from builtins, holdout hp-precision 33/40, pytest 1139`

注意：`git add -f outputs/015_*` glob 实测 **8 份**（2026-09-21 干跑审计）：
`015_bishe_a2a_unknown.txt`、`015_board24v_{before,after,mpn_diff}.txt`、`015_eval_{dev,holdout}.txt`、`015_eval_bishe_only_{dev,holdout}.txt`。
011 时代的 013/014 命名文件不被此 glob 触及；`docs/images/gs-02-extension-menu.png` 在 `git add docs/` 范围内（docs/ 不 ignore）。

## 2. 文件清单（git status 逐条归置）

**Modified（11）**

| 文件 | 来自 |
|---|---|
| `src/boardwise/rules/values.py` | 批①核心：三守卫（`_R_NOTATION_RE`/`_VOLTAGE_TAIL_RE`/`_ELECTROLYTIC_RE`）+ 整 token 拒解；sha256 `dde2ed41…b22b95` |
| `src/boardwise/rules/params.py` | UNKNOWN message 补"或写成非 EIA 记法" + 类 docstring |
| `src/boardwise/engines/review.py` | `decoupling-per-ic` 退役出 `BUILTIN_RULES`（15→14）+ 注释；sha256 `ce0410b6…8f979b` |
| `tests/test_011d_rules.py` | +3 钉子（解码器拒绝、A2a→UNKNOWN、退役） |
| `tests/test_annotations.py` | mpn 对账收窄 A2b 7 条 + A2a 断言 UNKNOWN（标注集 JSON 未动，sha256 `db1f5834…` 不变） |
| `tests/test_review_eval.py` | exception (10,10)→(10,7)；decoupling 行改"无 metric" |
| `tests/test_cli.py` | llc 7W→0、md `No findings.`、tiny enet 断言退役规则不再出声 |
| `tests/test_epro2_model.py` | `assert findings` → 逐规则跑 |
| `README.md` | 中英两段规则列表 15→14 |
| `docs/epru-format.md` | llc_board 实测注退役后 0/0/0（执行者顺手，复验认可） |
| `docs/getting-started.md` | gs-02 截图位注 + 正文嵌入（013 遗留，岳手截图落位） |

**New（3）**：`tasks/015-review-rules-m2.md`（任务书 + §六 交卷 + §七 复验）、
`docs/images/gs-02-extension-menu.png`（岳手截：顶栏 boardwise 菜单 + V3.2.186 同框）、
`tasks/015-commit-checklist.md`（本清单）。

**不提交**：`.tmp_015/`（变异脚本+日志，gitignore 内）、`.tmp_pt_home/`、`connector/`（零 TS 改动）。

## 3. 真机/实测结论速览（提交信息可引）

- 毕设板 A2a 三条（R43/C115/C116）VIOLATION → UNKNOWN；board24v 15 条 MPN 误报全消失、零新增（`015_board24v_mpn_diff.txt`，按料号分组与 triage A1a/b/c 逐条对上）
- eval：dev 5/5 与 5/5 不变；holdout 检出 33/33 = 1.00 不变、hp-prec 33/46 → **33/40 = 0.82**（任务书预测逐项兑现）
- 变异验证 4/4（执行者）+ 1/1（Kimi 独立抽验加回退役规则）全 CAUGHT，还原逐字节一致
- 全仓 11 块板扫描只减不增（另减 高速电机 C40、ROBOT R5，机制同 A2a）

## 4. 提交后同步项（PROGRESS.md，AI 已备口径）

- baseline：commit→新号；pytest **1139** / connector **279** / connector version 仍 **0.4.10**（未动）；日期 2026-09-21。
- Milestones 加行：`015 review rules M2 batch 1 | DONE 2026-09-21 | tasks/015-review-rules-m2.md（批②矛盾幅度待 oracle A/B/C 裁决）`
- Git anchors 加一行。

## 5. 遗留（不阻塞本提交）

- 批②（矛盾幅度 A/B/C）：等岳裁决，裁决后另起任务书段落或 016。
- gs-01/03 两张截图待岳手截；gs-02b（扩展管理器）图岳若另存到 `docs/images/` 可随下批带入。
- `.tmp_015/` 变异现场保留备查，下批前清理。
