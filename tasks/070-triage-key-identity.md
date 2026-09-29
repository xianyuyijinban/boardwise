# 070：issue #13 —— triage key 撞车：结构化身份优先 + 唯一性硬断言

## 来源（issue #13，岳亲笔，根因链已全部查实，直接引用）

- `triage_key`（`engines/checkup.py:1184`）用 `refs` 当身份；`refs` 来自启发式
  `finding_refs`（`engines/review.py:220`）正则扫 evidence+message、白名单
  `DESIGNATOR_PREFIXES`（`review.py:206`）过滤。
- 白名单**没有 `EC`**；`param-value-mpn-match` 的 evidence 为空、位号只在 message
  ⇒ `refs=[]` ⇒ key 退化成 `boardwise-rule:param-value-mpn-match:` ⇒ EC1/EC3 两条
  finding 撞同一个 key，一条 triage 命令把同一判定写进两颗器件（逐条判定是
  triage 的全部意义）。
- **同根因**还让 `review-mark` 对这两条 finding 画不出标记（`cli.py` review-mark
  走同一个 `finding_refs`）。
- 结构化位号 `target.component_ref='EC3'` 就在 finding 里、可靠，却没人用。
- 岳的建议（**三条全采纳**）：① key 优先读 target 结构化身份，refs 只作补充；
  ② `finding_refs` 也读 `target.component_ref`（顺带修好 review-mark）；
  ③ 唯一性断言：slots 里出现相同 key 就硬报错（或确定性后缀消歧），撞车不许静默。

## 架构裁决（主代理已定）

1. **key 身份优先级**（`boardwise-rule` 配方）：
   `target.component_ref`（有多个就排序逗号连）→ `target.pin_refs`/`target.net_refs`
   → 旧 `refs` 启发式（保底）。`host-erc` / `pcb-drc` 两种配方**不动**。
2. **`finding_refs` 先读 `target.component_ref`**，再走原启发式；白名单补 `EC`
   （真实位号前缀，电解电容惯例——一行的事，但架构上不再靠扩白名单兜底）。
3. **唯一性**：完整身份后仍撞 key 的 slots，按稳定序（component_ref, pin_refs,
   net_refs, message）加 `#2`/`#3` 后缀消歧——**确定性**（同输入同 key，重跑侧车
   才能并上）；后缀这件事本身要在 report note 里显形（撞车曾是 bug，不许再静默）。
4. **旧侧车兼容**：已存在的退化 key（`boardwise-rule:param-value-mpn-match:`）条目
   留在侧车当审计轨迹，新 slots 身份变了就并不上——`未匹配 M` 如实报，
   **不许发明迁移逻辑**（那些判定本来就语义可疑：一条判定打了两颗器件）。
5. 公开形状不破：slots 仍只加 `key` 字段（063 §1），report.md 分诊表不动结构。

## 任务（串行小批；069 批次在跑 drawcompiler，**禁碰** `engines/drawcompiler.py`
与 `tests/test_053b_drawcompiler.py`；basetemp 一律 `.tmp_pt_070`，**包括全量**）

只碰：`engines/review.py`（finding_refs + 白名单）、`engines/checkup.py`
（triage_key + 唯一性）、`cli.py`（仅当 review-mark 取 refs 的那行需要跟着改）、
相关测试文件（063 的测试在哪就加在哪，或新 `tests/test_070_triage_key.py`）。

1. 按裁决 1/2/3 实现。
2. **新测试**（basetemp `.tmp_pt_070`）：
   - 两条 EC 前缀、同规则、evidence 空的 finding → key 不同且各含自己位号；
   - triage 其中一条 → 另一条 verdict 不动（#13 复现的全程回归）；
   - `finding_refs` 对 `target.component_ref='EC3'`、evidence 空 → refs 含 `EC3`；
   - 完整身份仍相同的两条 → 后缀确定性（同输入跑两遍 key 逐值相同）；
   - 旧退化 key 的侧车条目 → 重跑并入 0、未匹配如实报、不 crash。
3. **#12 全程回归不许破**：checkup → triage 3 条 → 重跑并入存活、pending=0。
4. 变异 ≥2：① key 退回只用 refs → 撞车测试必须红；② finding_refs 不读 target →
   review-mark 测试必须红。cp+sha256 还原。
5. 全量 `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_070` 全绿
   （用 `.tmp_pt_070` 不是 `.tmp_pt_home`——069 在用后者）。
6. review-mark 顺带修好后，在交卷里写明：`cli.py` 那条注释（说 review-mark 走
   `finding_refs`）对应行为现在的变化。

## 边界与纪律

- 零 git 写操作；PROGRESS.md 不动（主代理收口写）；不 comment/close issue（主代理来）。
- 先读 `E:/boardwise/AGENTS.md`、`.kimi-code/skills/boardwise/SKILL.md` §7、
  issue #13 原文（`gh issue view 13 -R xianyuyijinban/boardwise`，代理先设
  `export https_proxy=http://127.0.0.1:7890`）。
- 离线任务，不碰真机/daemon/编辑器。
- 交卷：改动文件 sha256 before/after、测试原文、变异证据、#12 回归证据、
  key 新旧对照表（岳那块板的 3 条 WARN：旧 key → 新 key）、自决项。
