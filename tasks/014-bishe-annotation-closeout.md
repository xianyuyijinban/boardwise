# 任务书 014：毕设板标注集收官（三条终裁落地 + 签名）+ M1 晋级材料

> 2026-09-20 Kimi 立项。小任务，一次交卷。执行：DeepSeek；复验：Kimi。
> 前置：013 已交卷并通过 Kimi 复验（1070/187/tsc，变异咬住）。
> oracle（岳翔宇）2026-09-20 三条终裁：**①U1.12 defect ②B2 按 3 条确认 ③B3 落 exception**。

## 〇、纪律

不动 git；append 后独立计数；pytest 用 `--basetemp=.tmp_pt_home`；三线全绿才交卷。

## 一、落三条终裁（`reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`）

### 1. 新增 defect：U1.12 晶振输入接错网

```json
{"kind": "defect", "rule": "conn-osc-pin-net", "ref": "U1", "severity": "ERROR",
 "split": "holdout",
 "note": "oracle FINAL RULING 2026-09-20: defect. Measured in 013: the STM32's PH0/OSC_IN (pin 12) sits on net IB- (members R10.1, U4.11 -- the phase-B current-sense return), while the OSC-IN label on the crystal page carries only X1.1 + C20.2. Pin-level evidence is clean (the same instance's pin 13 lands on OSC-OUT correctly), so this is not a parser artifact: the 25 MHz crystal never drives the MCU, which has been running on HSI all along (the board worked because HSI is good enough for this loop). `conn-osc-pin-net` is an UNREGISTERED hint -- no M1 rule can detect this class; it is M2 backlog (cross-page label continuity / MCU osc-pin net assignment). It must land in the harness's no-registered-rule column and stay out of every M1 denominator."}
```

### 2. B3 落 exception（xtal-load-caps, X1）

```json
{"kind": "exception", "rule": "xtal-load-caps", "ref": "X1", "severity": "WARN",
 "split": "holdout",
 "note": "oracle FINAL RULING 2026-09-20: the board HAS load caps (C20/C21, 20 pF). The WARN was a false positive rooted in the parser dropping early-placed basic parts' pins; after the 013 Symbol-fallback fix C20/C21 join OSC-IN/OSC-OUT (cross-confirmed against PCB PAD_NET) and the rule is quiet (1 -> 0). Recorded as exception so the history is not lost."}
```

注意：xtal-load-caps 修复后**不再报** X1——这条 exception 配对不到 finding。如实记录 harness 的实际行为（进哪栏、计数如何），写进交卷记录；若现行语义下它无处可去，就在 note 里补一句并如实断言。

### 3. B2 observation 重写（5 → 3）

把 observations 里 `section B2 ruled: decoupling-per-ic ... (U1, U8, USB1, U7, U6)` 那条改为：

- topic 里的 ref 清单改为 **(U1, U8, USB1)**——013 修复后只剩这三个（`outputs/013_bishe_findings.md` 第 76/82/86 行实测）。
- note 末尾追加：`Amended 2026-09-20: the set shrank 5 -> 3 after 013. U6/U7's warnings were not heuristic false positives at all -- their decoupling caps were among the 25 pin-less parts and simply came back. The remaining three are the true L1-heuristic limitations as originally ruled.`

### 4. 清理过期观察

- 删 `section B3 still pending -- awaiting Kimi's confirmation` 整条（已被 §1.2 取代）。
- 首条 observation（"section B is ruled except B3 ... holds the DRAFT stamp"）改写为：B 段全部裁完，013 修复兑现了 B3，B2 收缩为 3 条；签名落定。

## 二、签名

`"reviewed_by": "Yue Xiangyu"`,`reviewed_at` 填今天。**这是毕设板标注集摘 DRAFT 的时刻**——落完先跑 harness 确认报告不再带 DRAFT 标再签。

## 三、复跑与测试

1. 复跑 `outputs/014_eval_dev.txt`、`outputs/014_eval_holdout.txt`（新文件，不覆盖 011 历史）。
2. `tests/test_review_eval.py` 受影响断言逐条更新，**每条在交卷记录里列明**：预期至少含——毕设板 unregistered 栏 0→1（conn-osc-pin-net 逐条在列、不进分母）；B2 的 `fp_unexplained == 3` 不动（observation 不进分母，语义不变）；B3 exception 落地后 xtal 行的计数实测更新。
3. 晋级判定表更新（dev/holdout 两行的检出/精确率新数字）写进交卷记录。

## 四、变异验证（标注集是被看守的数据文件）

四个靶子全 CAUGHT：①删 U1.12 defect ⇒ unregistered 断言红；②删 B3 exception ⇒ 红；③签名但删任一 item ⇒ 红；④B2 观察改回 5 条 ⇒ 红。还原逐字节（sha256 前后一致）。

## 五、更新 `tasks/011-commit-checklist.md`

- 013 折进 M1 一次性提交（它是 011 标注依赖的地基修复，不是独立变更）。
- 014 的标注集改动 + 测试更新同属 M1 提交。
- 012 保持单列（M1 提交后独立提交）。

## 六、交卷标准

- 三线全绿（pytest 预期 1070+ 小幅变化；connector 187 不动；tsc 干净）
- 变异 4/4 CAUGHT
- 报告落盘 + 晋级判定表新数字
- 交卷记录写进本文件（含每条测试改动理由 + harness 对"配对不到的 exception"的实际行为记录）

---

## 七、交卷记录（DeepSeek，2026-09-21 00:xx 执行；oracle 终裁日 2026-09-20）

### 三条终裁落地

`reviewsets/ProPrj_毕设FOC驱动板_2026-09-17.json`：items 41→43（+U1.12 defect
conn-osc-pin-net / +X1 exception xtal-load-caps）；observations 9→8（B2 ref 清单
5→3 + amendment note、"B3 still pending" 整条删除、首条改写为"全裁完+签名"）；
`reviewed_by="Yue Xiangyu"`、`reviewed_at="2026-09-20"`（终裁日；执行跨午夜至 21 日，
harness 只读 `reviewed_by` 判 DRAFT）。notes 里旧的 DRAFT 理由段同步改写为签名理由
（任务书未点名 notes，但留着会与签名自相矛盾）。harness 报告头部实测 **[reviewed]**，
DRAFT 摘除。

### 任务书示例 JSON 的两处 schema 笔误（照实修正）

1. 示例用 `"rule"` 键——schema（`core/annotations.py` `_ITEM_KEYS`）是 **`rule_hint`**；
2. exception 带 `"severity": "WARN"` 被 loader 拒绝（"only defects carry an expected
   severity"）——已去掉该字段，测试里钉住"全部 exception severity 为空"。

### harness 对"配对不到的 exception"的实际行为（§一.2 要求如实记录）

X1 exception 的 rule_hint 是已注册的 xtal-load-caps ⇒ 进 `exceptions_hinted`（=1，
"oracle 看过并裁过"），**且仅此一栏**：规则修复后不再报 X1，无 finding 可配 ⇒
`fp_on_exception=0`、`fp_unexplained=0`、violations=0。文本报告的表格不含
exceptions_hinted 列，故报告上 xtal 行全空——数字在 metrics/JSON 里，测试已钉。

### 超出任务书字面的一处代码改动（需知悉）

`engines/review_eval.py` `_any_defect`：**unregistered hint 的 defect 不参与 cross
配对**（一行条件 + 注释写明 014 出处）。不加它，实测 U1.12 defect 会经 ref 撞车
cross-match 吞掉 decoupling 的 U1 WARN：fp_unexplained 3→2、hp-prec 变 1/3——同时
违反任务书两条明文（"B2 的 fp_unexplained == 3 不动"、"stay out of every M1
denominator"），并用配对机制覆盖 oracle 对 B2 的独立裁定。连带：旧钉子测试
`test_an_unregistered_defect_caught_by_a_registered_rule_is_listed_not_credited`
（钉 011c 旧语义"列出不 credit"）改写为
`test_an_unregistered_defect_never_cross_explains`（钉新语义：不 cross、finding 落
catching rule 的 fp_unexplained、记录仍逐字在 unregistered 栏）。

### 测试改动逐条清单

| 文件 | 改动 | 理由 |
|---|---|---|
| `tests/test_review_eval.py` 毕设板用例 | docstring 扩写；+`evaluation.reviewed` 断言；+unregistered 栏 len==1 且含 U1/conn-osc-pin-net；+`cross_matches == []` | 签名生效、unregistered 0→1（任务书 §三.2 预期项）、cross 不发生 |
| 同上 | B2 `fp_unexplained == 3` **不动**（observation 不进分母，语义不变） | 任务书明文 |
| 同上 | +xtal `(exceptions_hinted, fp_on_exception) == (1, 0)` | 配对不到的 exception 的实际行为 |
| 同上 xtal | `fp_unexplained` 保持 013 的 0 | B3 裁定不改 013 的测量 |
| `tests/test_review_eval.py` 钉子用例 | 旧 cross 语义改写为新语义（见上） | review_eval 语义变更的直接跟随 |
| `tests/test_annotations.py` 毕设板用例 | reviewed_by/at 断言 31→32 defects、10→11 exceptions、observations 9→8、"still pending" 不在、B2 topic == (U1, U8, USB1) 且无 U7/U6、osc/X1 两条新记录逐字段断言、exception severity 全空 | 标注集内容变更的机械跟随 |
| 同上 | mpn exception refs 对账从"全部 exceptions"收窄为"mpn 组" | X1 不再参与该对账（by design） |

pytest **1070** 全绿（013 的 1070 + 014 净 0）；connector **187** 不动；tsc 干净。

### 变异验证（4/4 CAUGHT，逐字节还原）

`.tmp_mutate_014.py`（跑完已删）：①删 U1.12 defect → 2 红；②删 X1 exception → 2 红；
③保签名删任一 item（拿一条 duplicate 开刀）→ 2 红；④B2 观察改回 5 条 → 1 红。
pristine sha256 `db1f5834…a18b7205`，四次还原均逐字节一致。

### 晋级判定表（取代 011 记录 I 的草稿表；口径同 011e）

| split | 板数（有记录） | 缺陷检出 | 高优确定问题精确率 |
|---|---|---|---|
| dev（5 注入板，字节级不变） | 5 | **5/5 = 1.00** | **5/5 = 1.00** |
| holdout（2 注入板 + 毕设板） | 3 | **33/33 = 1.00** | **33/46 = 0.72** |

分母 49→46：B3 的 1 条随 013 修复消失（且已落 exception 留史）、B2 5→3。换算 M2
动作（修 MPN 解码器 -10、退役 decoupling -3）：**33/33 = 1.00**——011e 时是 33/34
= 0.97，**≥95% 晋级门槛从"差一条"变为"达成"**；检出率 33/33 ✓。

### 报告产物

`outputs/014_eval_dev.txt`（毕设板 dev split：items 全在 holdout ⇒ 全部落
unexplained，holdout 语义的正确表现）、`outputs/014_eval_holdout.txt`（30E/14W/12I、
unregistered 1 条逐字在列、B2=3、xtal 行安静）。011 历史 outputs 未覆盖。

### 遗留（不阻塞）

`review_eval.py` 的 cross-match 修复影响面核对过：黄金板/注入板无 unregistered 记录
（全部 0），行为不变；全量 pytest 绿即证。任务书 §三.2 预期的"unregistered 栏 0→1"
在修复后成立。
