# 一次性提交清单 — 011（M1 规则与度量线）

> 2026-09-20 整理。执行者：岳翔宇（AI 不动 git）。
> 基线：最后提交 `ce044a6`（010c，09-19 13:11）之后**全部未提交改动都属于 011 线**
> （011a→011f/011g），因此"一次性提交"在边界上是干净的，只有两条非 011 项需要单独裁决。
> 交卷时状态：pytest **1056** / connector **187** / tsc 干净；`make_variants.py --check`
> 7 块注入板（含退役板）与其标注集逐字节可复现。

## 1. 建议的提交方式

单一提交即可（一条任务线一次交卷，与 009d2/010c 的先例一致）。若想按子任务拆，
`git add -p` 的自然切点是 011b（库 v2）/011c（规则族）/011d（注入）/011e（holdout）/
011f+011g（oracle 裁决落地），但 modified 文件跨子任务共享（`parts.py`、`params.py`、
`cli.py` 都被多轮改过），拆分成本高于收益。

```bash
git add src/boardwise/ tests/ reviewsets/ blocklib/ tasks/ docs/roadmap-2026-09-18.md
git add -f <证据文件，见 §3>
git commit   # 建议标题：011: M1 review rules — annotations, metrics harness, CONN/PWR/PATH+PARAM/DECAP rules, injected boards, holdout
```

## 2. 文件清单（git status 的 38 项逐条归置）

**Modified（16，全部 011 线）**

| 文件 | 来自 |
|---|---|
| `src/boardwise/core/parts.py` | 011b schema v2 + 011d mode/pull_required |
| `src/boardwise/core/model.py` | 011c `duplicate_designators`（CONN-1 parser 半边） |
| `src/boardwise/engines/harvest.py` | 011b/011d `_apply_curated` |
| `src/boardwise/engines/review.py` | 011c/011d 规则注册表 |
| `src/boardwise/parsers/schematic.py` | 011c CONN-1 收集 |
| `src/boardwise/cli.py` | 011a `review-eval` + 011c `--view` + 011e hp/totals |
| `src/boardwise/rules/{__init__,base,connectivity}.py` | 011c 四态协议 + CONN 规则 |
| `blocklib/parts.json`（v2，94 件） | 011b/011d |
| `blocklib/parts.corrections.json`（v2，+`curated` 节） | 011b/011d |
| `docs/roadmap-2026-09-18.md` | 009d 勘误（随本批一并入库） |
| `tests/{test_bom,test_cli,test_datasheet_backfill,test_parts_library}.py` | 各轮的机械跟随，逐条理由在各交卷记录 |

**New — 源码与测试（13）**：`core/annotations.py`、`core/power_domains.py`、
`engines/review_eval.py`、`rules/{decap,facts,params,values}.py`；
`tests/{test_011d_rules,test_annotations,test_facts_library,test_facts_rules,
test_injected_variants,test_power_domains,test_review_eval}.py`。

**New — reviewsets/（整目录，ground truth）**：黄金板/毕设板/board24v 标注集与 2 份 triage、
`injected/make_variants.py` + 7 块 `.epro2` 注入板（含退役的 `v3-decap-missing`，**留盘被看守**）
及其 8 份标注集。`reviewsets/injected/*.epro2` 共约 660 KB，是判决的载体，必须入库。

**New — tasks/**：`011-review-rules-m1.md`（立项书 + 交卷记录 A–I）、
`011b/011c/011d/011e` 四份任务书。

## 3. outputs/ 证据（gitignored ⇒ 被 task book 引用的需 `git add -f`）

引用即证据（记录 A–I 里点了名的）：

```text
outputs/011a_eval_smoke.txt            outputs/011b_provenance.md
outputs/011b_parts_diff.txt            outputs/011c_golden_eval.txt
outputs/011d_golden_eval.txt           outputs/011d_injection_list.txt
outputs/011d_variants_report.md        outputs/011d_variants_summary.txt
outputs/011d2_fixed_base_report.md     outputs/011d2_variants_summary.txt
outputs/011d2_v3_decap_analysis.txt    outputs/011e_eval_dev.txt
outputs/011e_eval_holdout.txt          outputs/011e_triage_raw.txt
outputs/011f_bishe_eval.txt            outputs/011f_holdout_draft_with_bishe.txt
outputs/011g_bishe_eval.txt
outputs/011e_baseline_*.txt（7 份）
```

其余 `outputs/011*`（探针、debug、逐页 datasheet 抽取、pytest/connector 日志）是一次性
过程产物，留在盘上即可，不必 `-f`。

## 4. 两条非 011 项（单独裁决，别混进本提交）

| 文件 | 说明 |
|---|---|
| `PROGRESS.md` | "living index"（里程碑索引），untracked、非本轮产物。内容与 011 记录有重叠，提交前请过目是否要它、由谁维护。 |
| `tasks/012-basic-experience.md` | 012 线（基础体验包，国庆内测版）的立项书，Kimi 立项。取代已删的 `012-delete-action.md`（内容并入其 §三）。应与 012 的提交同行，或单独先提。 |

## 5. 提交前的最后一查（全部应绿）

```bash
./.venv/Scripts/python -m pytest -q --basetemp=.tmp_pt_home      # 1056 passed
cd connector && npm test                                          # 187 pass
npx tsc --noEmit                                                  # 干净
./.venv/Scripts/python reviewsets/injected/make_variants.py --check
#   --check: 7 board(s) and their annotation sets rebuild byte-identically
```

## 6. B3 到达后的收尾（不阻塞本提交）

1. `reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`：按 Kimi 确认落 B3
   （defect 或 exception 各一条），`"reviewed_by": "Yue Xiangyu"`（+ `reviewed_at`）；
2. 复跑 `outputs/011e_eval_holdout.txt`（B3 落定后高优精确率会离开 0.67）；
3. 更新 `tasks/011-review-rules-m1.md` 交卷记录 I 的表——或作为后续提交。

---

## 7. 013/014 补记（2026-09-21，DeepSeek 依任务书 014 §五更新）

- **013 折进本提交**：`parsers/schematic.py` 的 Symbol-ATTR 回退是 011 标注依赖的
  地基修复（B2 5→3、B3 1→0 都由它兑现），不是独立变更——与 011 同一提交。
- **014 同属本提交**：毕设板标注集三条终裁 + 签名 + `tests/test_review_eval.py` /
  `tests/test_annotations.py` 断言更新 + `review_eval.py` 的"unregistered 不 cross
  解释"一行修复，全部是 M1 度量线的一部分。
- **012 保持单列**（`tasks/012-basic-experience.md` 与 012 代码同行，M1 提交之后）。
- 文件清单增量：Modified 加 `engines/review_eval.py`（014 cross-match 修复）；
  New 测试加 `tests/test_013_symbol_fallback.py`；New tasks/ 加
  `013-parser-symbol-fallback.md`、`014-bishe-annotation-closeout.md`；
  outputs 证据（`git add -f`）：`outputs/013_*.txt|json|md`、`outputs/014_eval_*.txt`。
- 测试数：**1056 → 1070**（013 +14、014 净 0：新增毕设板断言折进既有用例，
  cross-match 钉子测试改写不增数）。
- §6 的 B3 收尾已由 014 完成（签名 + 报告复跑），本表 §5 复跑命令不变。
