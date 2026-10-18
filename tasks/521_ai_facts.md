# 521 — 让 AI 读 txt 写 facts，工具只当收件闸

> 立项 2026-10-18，依据是 520 的实测（`outputs/520/evidence.md`）：**下载通道已经通了，
> 卡住的是提取**。本任务书的前提全部是实测读数，不是推断。

## 1. 为什么要改方向

`parts hunt` 跑一块 46 颗的真板（24 个唯一 C 号、冷启 41 s、0 次失败），拿到 15 份真 PDF，
`engines/datasheet.py::candidate_facts` 提出 **0 条** facts，包括 `UCC21520DWR` 的 52 页 TI 手册
——那份文本读得很干净。

逐段核对后，根因**不是**词表窄（虽然确实只有 11 个名字）：

```
# page 4 —— pin 表，提取器认的形状，能认出来
VCCI 3 P Primary-side supply voltage. …
VDDA 16 P Secondary-side power for driver A. …

# page 5 —— 推荐工作条件，断在这里
MIN MAX UNIT
VCCI VCCI Input supply voltage 3 18 V
VDDA,
VDDB Driver output bias supply UCC21520ADW – 5-V UVLO version 6.5 25 V
```

- **范围是列布局**：`3 18 V`、`–0.3 20 V`、`–40 125 °C` —— 两个数用空格分隔，
  而 `_RANGE` 只认显式的 `to`/`-`/`~`/`..`。真实表格几乎都长这样。
- **名字跨行**：`VDDA,` 自己一行，`VDDB …` 在下一行。
- **扩词表实测收益为 0**：`.tmp_probe/whitelist.py` 把 `SUPPLY_NAMES` 从 11 个加到 39 个
  （`VCCI/VCCO/VDDA/VDDB/VDDH/VIO/VBUS/VSYS/PVIN/VDD1/VDD2/VEE/VM…`），
  同时改 `_NAMES_RE`（两者是同一个问题的两个答案，见 #75），结果 **0/15 → 0/15，一条没动**。
  原因就是上面那条：pin 行认出来了，也没有范围行可 join。

把正则修到能覆盖列布局 + 跨行 + 各家排版 + 中文手册，是一个没有底的任务，而且每加一条判据
就多一种假阳性。**而 AI 读同一份 txt 一眼就是「VCCI 在 pin 3 和 pin 8，范围 3–18 V」**——
txt 已经落盘、带页码、按页切开（`<C号>/<C号>.txt` + `.pages.json`）。

所以：**理解交给 AI，工具负责校验**。这条与项目定位一致（harness 做确定性的那一半）。

## 2. 要做的事

### 2.1 新入口 `boardwise parts hunt --apply-facts <file>`

与 `--apply`（回灌 URL）并列的第三个阶段：AI/人把**读出来的 facts**交回来。

答案文件形状（闭合，多余键报错）：

```jsonc
[
  {
    "designator": "U2",              // 或 lcsc / mpn，定位顺序 designator > lcsc > mpn
    "facts": {                        // 与 PartEntry.facts 同一份 schema
      "supply_pins": [
        {"pin": "3", "name": "VCCI", "mode": "operating",
         "v_operating": [3, 18], "provenance": "…"}
      ],
      "required_caps": [...],
      "nc_pins": [...]
    },
    "quotes": [                       // 每条事实的出处；**硬闸**
      {"page": 5, "text": "VCCI VCCI Input supply voltage 3 18 V"}
    ]
  }
]
```

### 2.2 四道校验（**这是本批的重点，不是格式美观**）

1. **引文逐字校验**：`quotes[].text` 必须在该 designator 的 `.txt` 的第 `page` 页里**逐字出现**
   （去掉首尾空白、把连续空白折成一个空格后比较）。找不到 → 该条判 `quote-not-found`，
   **不落架、不写 candidate**。这是唯一能挡住「AI 编一段看起来很像的引脚表」的机制。
2. **页码存在**：`page` 必须在 `1..len(pages)` 内。
3. **pin 号在该文档出现过**：`facts.*.pin` 的每个值必须能在该 txt 里以独立 token 出现
   （同一页或同文档），否则判 `pin-not-in-document`。**只查出现、不查语义**——工具不假装懂电路。
4. **schema 校验**：复用 `core/parts.py` 现成的 facts 校验（`_facts_from_json` 那条路），
   不写第二份。

### 2.3 产物

- 追加进 `hunt-report.json` 的 `parts[]`：`outcome` 新增 **`facts-accepted`**，
  `facts` 字段带内容，`notes` 记引文校验结果。
- 失败一侧新增 **`facts-rejected`**，`notes` 逐条写清是哪一道没过（`quote-not-found` /
  `page-out-of-range` / `pin-not-in-document` / `schema`）。
- 落货架仍只在 `--shelf` 给了才写，且**一律 `facts_verified: false`**（与 520 同口径；
  三档可信度是下一批 522 的事，本批不动 schema）。

### 2.4 别做的事

- **不要重写 `engines/datasheet.py`**。它是「窄而诚实」的正则提取器，能提就提；
  本批只把它的实测边界写进文档（§3），改它属于另一个任务。
- **不要给 AI 的 facts 打 `verified`**，也不要新增 `machine_verified`（那是 522）。
- **不要接搜索**。AI 从哪来的 PDF（`--apply` 的 URL 还是缓存）本批不关心。

## 3. 文档

`docs/parts.md` 的 hunt 节补 `--apply-facts`，并把这段实测边界写进去（数字照抄，别软化）：

> 实测 46 颗真板 0 条 extracted；`UCC21520DWR` 52 页 TI 手册文本干净但提不出；
> 扩词表 11→39 个名字，命中 0/15 → 0/15。根因是真实表格是列布局（`3 18 V`）而 `_RANGE`
> 只认 `to`/`-` 显式连接，且 pin 名会跨行。**这条通道的产出是 PDF + 带页码的 txt，
> facts 由 AI 读 txt 产出、工具校验引文。**

## 4. 测试（`tests/test_521_ai_facts.py`，零网络）

至少：

- 一条合法 facts + 引文能在对应页找到 → `facts-accepted`，条目落架且 `facts_verified` 为假
- **引文被改动一个字 → `facts-rejected` / `quote-not-found`，且断言架子没被写**
  （这条是全批最重要的一条：它是防幻觉的唯一闸）
- 引文存在但 `page` 指错页 → `page-out-of-range`
- `pin` 在该文档里从没出现过 → `pin-not-in-document`
- 答案文件点了板上没有的 designator → `unknown-designator`，其余条目照常处理
- facts 里多一个未知键 → schema 报错，不落架
- `--offline` 下 `--apply-facts` 仍可用（**它不该需要网络**：PDF 与 txt 都在磁盘上）——
  这条要专门测，因为它决定了保密场景下这条路能不能走

## 5. 验收

```bash
cd <worktree>
PYTHONPATH=src /e/boardwise/.venv/Scripts/python.exe -m pytest tests/test_521_ai_facts.py -q --basetemp=.tmp_pt_521
PYTHONPATH=src /e/boardwise/.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile \
  --basetemp=.tmp_pt_521f -k "parts or hunt or catalog or datasheet"
```

再跑一次**真板的半条链**（`--offline`，零外呼）：对 `级联多电平-驱动模块` 的 `U2`（`UCC21520DWR`，
52 页 txt 已在 **`E:\boardwise\.tmp_cache_hunt520\C601651\`**，520 实跑留下的真 PDF + 全文，
把它当 `--cache` 指过去），手写一份 answers，facts 取 VCCI=3/8、VDDA=16、VDDB=11、VCCI 3–18 V，
引文照抄第 4/5 页原文 → 必须 `facts-accepted`；然后把引文改一个字重跑同一份 → 必须
`facts-rejected` 且架子不变。**这两个读数贴进交卷。**

## 6. 纪律

见 `AGENTS.md` 与 520 任务书 §纪律：不 commit、不碰主树、删除进回收站（**禁 `rm`**）、
单进程、pytest 必带 `--basetemp`、`-n 4 --dist loadfile`、注释英文且照抄 `hunt.py` 的密度、
变异验证 `cp` + `sha256` 还原（禁 `git checkout --`）、企业名零出现。
