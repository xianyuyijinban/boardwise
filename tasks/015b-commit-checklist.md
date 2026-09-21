# 一次性提交清单 — 015 批②（矛盾幅度 R 3x / C 25x + 注入变体重签，M2 晋级达成）

> 2026-09-21 整理。执行者：岳翔宇（AI 不动 git，等你点头）。
> 基线：最后提交 `1bee292`（PROGRESS→015 批①）之后全部未提交改动属于 **015 批②**，边界干净。
> 复验后状态：pytest **1145** / connector **279** / tsc 干净（三线 Kimi 亲跑）；
> **holdout 检出 33/33 = 1.00 + hp-prec 33/33 = 1.00——011 §十晋级判据（≥95% 精确率 + ≥90% 检出）正式达成**。
> 任务书：`tasks/015-review-rules-m2.md`（§二批②规格、§八执行者交卷、§九 Kimi 复验）。

## 1. 建议的提交方式

单一提交（与历次先例一致）。

```bash
git add src/ tests/ tasks/ reviewsets/
git add -f outputs/015b_*
git commit   # 建议标题见下
```

建议标题：
`015 batch 2: value-MPN amplitude tolerances (R 3x / C 25x, oracle ruling A) + injection variant re-signed 4.7k — M2 graduation: holdout 33/33 = 1.00 both metrics, pytest 1145`

注意：`git add -f outputs/015b_*` glob 实测 **3 份**（2026-09-21 干跑审计）：
`015b_eval_dev.txt`、`015b_eval_holdout.txt`、`015b_bishe_a2b_waived.txt`。
批①的 `outputs/015_*`（无 b）已随 `501a2f4` 提交，不被此 glob 触及。

## 2. 文件清单（git status 9 项逐条归置）

**Modified（9，全部批②）**

| 文件 | 来自 |
|---|---|
| `src/boardwise/rules/params.py` | 幅度分级核心：`MPN_AMPLITUDE_TOLERANCE_R/C`（3.0/25.0）+ 裁决注释（`:54-80`）+ ratio 分级（`:212-263`）；sha256 `229aaed1…` |
| `reviewsets/injected/make_variants.py` | 注入变体重签：U3 `1kΩ`→**`4.7kΩ`** + `final_ruling` 字段 + `--list` ruling 行 |
| `reviewsets/injected/value-mpn-mismatch.epro2` / `.json` | 重生成产物（`--check` 全板逐字节可复现；`.epro2 0a26446b…`、`.json 1b883928…`） |
| `tests/test_011d_rules.py` / `test_annotations.py` / `test_injected_variants.py` / `test_review_eval.py` | +7 新测（阈值常量/边界 3.00x 与 25.00x/min≤0/A2b 七条真实板）、1 替换、6 改动 |
| `tasks/015-review-rules-m2.md` | §二批②规格（oracle 二裁）+ §八交卷 + §九复验 |

**New（1）**：`tasks/015b-commit-checklist.md`（本清单）。

**不提交**：`.tmp_015b/`（变异现场，gitignore 内）、`.tmp_pt_home/`、`connector/`（零 TS 改动）、`outputs/015b_*` 走 `-f`。

## 3. 实测结论速览（提交信息可引）

- **晋级判据达成**：holdout 检出 33/33 = 1.00 + hp-prec 33/33 = 1.00（批①时 33/40 = 0.82，批② A2b 七条转 OK 列清零）
- 毕设板 value-mpn VIOLATION 7 → 0（OK 列 +7，`015b_bishe_a2b_waived.txt` 逐位号）
- 已知代价（oracle 知情）：dev 检出 4/5（黄金 U3 2.13x 转 OK 进 missed 栏；011c defect 记录未改写，冲突留史）
- 待裁遗留（不阻塞）：dev hp-prec 4/5——注入板 U3 兼 LED 限流，4.7k 出 LED 窗口 [470,2200]，次生 LED1 WARN；oracle 三选一（①接受 ②补标注 ③重锚 ref），§九
- 变异验证：执行者 3/3 + Kimi 独立抽验（R 3.0→2.0 ⇒ 11 红）全 CAUGHT，还原逐字节一致

## 4. 提交后同步项（PROGRESS.md，AI 已备口径）

- baseline：commit→新号；pytest **1145** / connector **279** / connector version **0.4.10**（未动）；日期 2026-09-21。
- Milestones 改 015 行：`015 review rules M2（批①+批②） | DONE 2026-09-21 | holdout 33/33 双 1.00 晋级达成；tasks/015-review-rules-m2.md`。
- Git anchors 加一行。

## 5. 遗留（不阻塞本提交）

- dev hp-prec 三选一（§九，oracle 裁后若选②另起小变更）。
- gs-01/03 手截图、gs-02b 另存（岳）。
- `.tmp_015/`、`.tmp_015b/` 变异现场保留备查，下批前清理。
