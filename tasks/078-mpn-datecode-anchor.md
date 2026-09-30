# 078：MPN 日期码吞锚点（#32 解码器批）

载体 issue：#32（岳亲报，根因已由主代理在 issue 留言核实修正——真落点是
`values.py` 三位截断与 vendor_prefix 后缀枚举的交互，不是 issue 猜的 setdefault/finditer）。

本批只修**电阻 MPN 中缀读法的锚点归属与零尾缀拒读**，不动 EIA 三位码、不动幅度豁免
（残差见 §5，已报岳裁定）。一份实现 `rules/values.py`，消费方 `rules/params.py`
（param-value-mpn-match）不改逻辑、只可能改预期。

## 1. 背景（实测现状，主代理已复核）

`_mid_letter_readings(token, vendor_prefix=True)`（`src/boardwise/rules/values.py:484` 起）：
digit run 先过 `_without_leading_size`（**只剥尺寸码**，:466），再 `run[-3:]` 三位截断
（:546），然后枚举「不以 0 开头的尾缀」作候选（:552-557），**position 0 无条件拿
`ANCHOR_MID_LETTER`**（:574）。国巨日期码（值码前的 `07`/`08`）不是尺寸码、剥不掉，
于是日期码被吞进最长尾缀 → 伪读法拿走锚点，真值沦为「未锚定猜测」：

| MPN | 真值 | 现在 candidates（值, 写法, 锚点） |
|---|---|---|
| `RC0402FR-0710KL` | 10k | (10k,'10K','') + (**710k**,'710K',锚) |
| `RC0603FR-074K7L` | 4.7k | (4.7k,'4K7','') + (**74.7k**,'74K7',锚) |
| `RC0805FR-071KL` | 1k | (1k,'1K','') + (**71k**,'71K',锚) |
| `RL0805FR-070R1L` | 0.1 | 只有 (**70.1**,'70R1',锚)——**真值 0.1 完全缺席** |
| `CRCW060310K0FKEA` | 10k | (10k,'10K0',锚) ← **合法**（尺寸码剥落后整 run=值，已定位） |

消费链（`rules/params.py:289` 起 `_rows`）：`_closest_reading` 挑离板值最近的读法连其锚点；
isclose → OK；ratio < `MPN_AMPLITUDE_TOLERANCE_R`=3.0 → 豁免 OK（**豁免不需要锚点**，
params.py:260-261 与 :440-443 注释，oracle 015 batch-2「不要定的太死」）；超差时
**无锚 → UNKNOWN、有锚 → WARN**（071 §1 C 锚点门）。由此推出 #32 表全格：

- `RL0805FR-070R1L` + board=0.1（**写对了**）→ 唯一读法 70.1 带锚、ratio 701 → **WARN 正确值**（假阳性，最恶）。
- `RC0402FR-0710KL` + board=1M（100x 错）→ 最近读法 710k、ratio 1.41 < 3.0 → 豁免 → **静默 OK**（漏报）。
- `RC0805FR-071KL` 报错引用根本不存在的 `71k`。

## 2. 修法（裁定两条，主代理已在 #32 留言，岳见过）

**A1 锚点只在「定位过的值段」上产生。** vendor_prefix 模式下，`_without_leading_size`
**实际剥掉了内容**的 run 才算已定位，position 0 拿锚（`CRCW060310K0FKEA` 行为不变）；
**未剥离的 run 是纯猜测枚举，所有读法 anchor=””**——多读法照样全返回（matches 与豁免
路径不受影响，046「两个都要」教义不动），只是谁都无权单独指控 BOM。E96/字母指数/分流/
封装上下文锚点（`_letter_exponent_reading` 等四个）**不动**。

**A2 中缀 R 的零尾缀放松。** vendor_prefix 模式下，中缀字母为 R 且尾缀恰为**单个 `0`**
时收进候选（`070R1` → 补 `0R1`=0.1 读法，无锚）。`0K1` / `0u1` / 电容侧零头**维持拒读**
（:559-566 注释钉死的教义：那些写法在板语法里有别的入口，MPN 扫描不认）。`R`+三位
（`R005` 分流拒读）不动。

**三位截断（:546）保留。** 它是 EIA 长度纪律；`0710`→`710` 的静默吞前缀正是伪读法来源，
但本批通过锚点归属消解其危害，不动截断本身（动了会波及 EIA 契约，另批再议）。

## 3. 验收契约（逐格，全过才算完）

解码层（`mpn_resistance_candidates`）：
- `RC0402FR-0710KL` → [(10k,'10K',''), (710k,'710K','')]（两读法都在、**都无锚**）
- `RC0603FR-074K7L` → [(4.7k,'4K7',''), (74.7k,'74K7','')]
- `RC0805FR-071KL` → [(1k,'1K',''), (71k,'71K','')]
- `RL0805FR-070R1L` → [(0.1,'0R1',''), (70.1,'70R1','')]（**真值回来了**）
- `CRCW060310K0FKEA` → [(10k,'10K0',ANCHOR_MID_LETTER)]（已定位，锚点保留）
- E96（`RK73H1JTTD1002F`）/ 厚声字母（`0603WAF1002T5E`）/ EIA+封装（`CC0603KRX7R9BB104`）锚点逐字不变。

规则层（param-value-mpn-match，合成 model 或既有夹具路径）：
- `RL0805FR-070R1L` + board `0.1` → **OK**（假阳性消除）；+ board `70.1` → OK（歧义代价，如实注释）
- `RC0402FR-0710KL` + board `10k` → OK；+ board `100k`（10x）→ **UNKNOWN**（伪读法失锚，不再是「带权威 WARN 引用 710k」）；+ board `1M`（100x）→ 仍是豁免 OK（**残差，§5 已报岳，本批不追**）
- `RC0603FR-074K7L` + board `4.7k` → OK；+ board `470`（10x）→ UNKNOWN；+ board `470k`（100x）→ 豁免 OK（残差同上）
- 真 mismatch 仍有牙：已定位 MPN（`CRCW060310K0FKEA`）+ board 严重不符 → WARN 照常

## 4. 测试重钉（行号已漂移，按内容定位）

`tests/test_011d_rules.py` 三处把错误行为钉成正确的必须重钉并写明 071→078 决策变更：
- 「Both readings are legitimate」段对 `RC0603FR-074K7L` 的 **candidates 锚点断言**（74K7 带锚 → 改双无锚）
- `test_param4_a_mid_letter_mpn_that_really_disagrees_is_still_a_violation`：现靠 `074K7` 最长读法的锚点
  让 1M 行说话 → 此路变 UNKNOWN，**violation 牙口改由已定位 MPN（CRCW 形）承担**，docstring 重写
- 「② the canonical mid-letter form」段 `FRC0805F4R70TS` 等未定位 run 的锚点断言 → 全部无锚
新增测试至少：§3 解码层六行逐格 + RL 假阳性回归 + `0R1` 可读 / `0K1` 仍拒 + 已定位锚点保留。
**全文件 anchor 断言审计一遍**，不止这三处。

## 5. 残差（**岳已裁定：A 接受现状**，2026-09-30 中午）

100x-high 误差恒落在伪读法 ~1.41x 内（结构使然：伪读法≈真值×71），豁免不需要锚点 →
锚点修得再对，100x-high 仍静默 OK。岳裁「A 接受现状」：豁免教义（oracle 015 batch-2
「不要定的太死」）不动，本批只修锚点倒置+假阳性，残差在 #32 fix comment 里如实记账。

## 5b. 执行后两项追加裁定（agent-120 交卷带出，岳 2026-09-30 中午亲裁）

1. **eval holdout 59/59→57/59：接受，基线重钉 57/59 并记账。** 滤波采样板 R3/R6
   （板值 330，MPN `MF1/4W-1K±1%-ST52` 真值 1k）的 mismatch 从 WARN 落 UNKNOWN——`1K`
   的 digit run 是 `1`，无尺寸码可剥=未定位，A1 把**真值**的锚点也收了（非伪读法失锚）。
   岳裁「接受 57/59」：A1 教义代价，UNKNOWN 仍上报不静默；容差标记定位（±n%）方案**不采用**。
   注：§3 契约格 `RC0603FR-074K7L`+board `470k` 的预测算错（伪读法 ×15.9、ratio 6.29 ≥ 3.0
   够不到豁免，实测 UNKNOWN 而非豁免 OK）——算术修正，未为它对任何东西放宽。
2. **`tests/test_070_triage_key.py` 白名单外改动：追认。** R7 是戴电容料号
   （`CC1206KKX7R0BB107`）的合成 10k 电阻，WARN 一直靠 `X7R0` 伪读法 7Ω 撑着，A1 后
   失锚变 UNKNOWN。agent 最小改动（期望改 UNKNOWN + 补一条实测钉），#13 本体语义未动，
   岳追认；回退方案（R7 换已定位 MPN）作废。

## 6. 硬规则（范围钉死）

- 只许动：`rules/values.py`（A1/A2 + 注释）、`tests/test_011d_rules.py`（重钉+新增）、
  必要时 `rules/params.py` 的**注释/docstring**（逻辑一行不许动）。
- 不碰：EIA 三位码路径、四个定位锚点产生器、幅度豁免与 tolerance 常量、`_too_long` 帽、
  电容侧一切、`tests/fixtures/` 既有夹具、`reviewsets/` 既有内容、历史证据
  （`outputs/011e*` / `014_*` / `015b_*` / `016_*`）。
- 尺寸+日期复合 run（`0603074K7` 形）是已知边界：**申报，不修**（无实证 MPN）。

## 7. 语料与 eval（077 先例，逐字照做）

- 语料回归 0-change；eval holdout **59/59 / 59/59**、dev 4/5 原样保持，任何移动逐条申报。
  做法照 `tasks/077-capacitance-infix.md` §6（同一命令两个 src 根，证据落 `evidence/078/`）。
- param-value-mpn-match 行为变化预期只落在 UNKNOWN↔WARN 档；holdout 若有板移动，
  逐条给出 before/after 行并证明是「伪读法失锚」而非规则漏检。

## 8. 纪律

- pytest 必带 `--basetemp=.tmp_pt_home`；变异 ≥2 组（建议：A1 定位守卫删除 / A2 零尾缀回拒），
  备份放 `.tmp_mut/`（**禁放 basetemp 内**）、字节级 replace（Windows sed 会吃掉 CRLF）、
  `cp` 还原 + sha256 核对，证据落 `evidence/078/`。
- 零 git 写操作；不写 PROGRESS.md；改文件用 Edit 或字节级脚本，保持 CRLF。
- 不重启 daemon、不碰真机（本批纯离线）。
- issue #32 里岳的影响面表与探针 `outputs/bugcheck_071_anchor_20260930/probe_sweep.py`
  可直接复用做 before/after 对照。

## 9. 交卷

改动文件 sha256 before/after、测试清单（新/钉/重钉各几条）、§3 逐格实证表、语料回归、
eval 对照、变异证据、残差申报、调用方审计（`mpn_resistance_candidates` 全部消费者
逐一确认锚点语义变化无漏接）。
