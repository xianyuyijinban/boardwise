# 任务书：184 — 值码解码覆盖不足 → 整板阻容误推「未审」

- 批号：**184**　日期：2026-10-15　优先级：高（实板 34/68 条 unreviewed 误触发，completion 卡 incomplete）
- 反馈原文：岳 2026-10-15 实板反馈（实板A，14 料号 0/14 解出 + 6 对照料号）
- 实板：`E:/boardwise/.tmp_bug98b/实板A.epro2`（只读，保密红线同 183）

## 诊断（主代理已确认，不必重查）

两套解码器脱节：
- `core/values.py:1210 mpn_value_code` —— 只读三位 EIA 码白名单；调用方：checkup 闸门（`engines/checkup.py:1093`）、`rules/decap.py:160/175/205`、`mpn_value_code_anchor`
- `core/values.py:1023 mpn_resistance_candidates` —— 电阻五形态 reader（mid-letter/字母指数/数字指数/E-96/shunt，带 anchor）；调用方：`rules/params.py:472`（ValueMpnMatch 电阻分支）
- 板上 value 解析：`core/values.py:448 parse_capacitance_farads`、`:909 parse_resistance_ohms`
- **电容侧没有 candidates 入口**（ValueMpnMatch 电容分支走 mpn_value_code + decode_eia_3digit）

根因：闸门只查 `mpn_value_code`，电阻五形态体系它看不见；电容侧电压码与值码歧义被拒。

## A. 闸门判据改「值不可知」（主修，`engines/checkup.py`）

`unknown_parts` 的 UNDECODABLE 分支改为：

```python
elif prefix in _VALUE_CODE_PREFIXES and not _value_decodable(prefix, component):
    reasons.append(UNKNOWN_REASON_UNDECODABLE)
```

`_value_decodable`（新辅助，放 checkup.py 局部或 values.py，看分层宪法——`tests/test_layer_rules.py`）：
- 板上 `component.value` 可解析（R→`parse_resistance_ohms`，C→`parse_capacitance_farads`，L→查有没有 parse_inductance，没有就跳过这路；RV/RP/RT/FB 按最接近的解析器尝试，解析不了不炸）→ True
- 否则 MPN 任一路径读出：R/RV/RP/RT/FB → `mpn_value_code` 非 None **或** `mpn_resistance_candidates` 非空；C/L → `mpn_value_code` 非 None
- `ERA16V100M5X7`（电解直印 µF）：板上 value 可解析即过（`_foreign_unit_code` 拒 EIA 误读是正确行为，不动）

语义变化写进 `unknown_parts` docstring：UNDECODABLE = "值真的不可知（MPN 解不出且板上 value 也读不出）"。

## B. 解码器补四族（`core/values.py`）

先跑基线矩阵（20 料号 × `mpn_value_code` × `mpn_resistance_candidates`），实测哪些 candidates 已覆盖，再补缺口。预期要补：

1. **FRC 族**：`FRC0603F1000TS` 形态 `FRC[封装][精度字母][4位E96][TS尾]`——精度字母在值码**前**，现有 `_e96_reading` 的尾部单字母 anchor 够不着（`1000TS` 两字母尾）。新增 reader 或放宽 `_E96_FIELD_RE`（注意别放进误读——071 的 anchor 纪律：新形态必须有自己的锚，写 docstring 引用本批实测料号）
2. **WSL 族**：`WSL1206R1000FEA`——`R` 后**四位**数字中置小数点（R1000=0.1Ω）+ `FEA` 尾。`_shunt_reading` 现在只读 `FR400` 尾部形态，扩 `[A-Z]R\d{4}[A-Z]+$` 类形态（同样带 anchor 论证）
3. **电容电压护栏**：`0603B103K500NT`/`CGA1206X7R104K501NT`——精度字母（K）后三位数字（500=50V/501=500V/250=25V）+ `NT` 尾是耐压不是值码，歧义消除后 `103`/`104` 成为唯一候选。护栏形态要窄：`[精度字母]\d{3}NT$` 或实测归纳出的等价形态
4. **国巨粘连**：`RC0603FR-071KL`/`AC0603FR-071KL` 误读 `'071'`——`FR-` 后 `07` 是 vendor 功率码、真值是粘连的 mid-letter（`1K`）。`mpn_value_code` 对 `[封装]FR-\d{2}` 前缀后的三位码拒读（candidates 体系已正确读 1K，有 4K7 先例，不用动）

**不动**：`_foreign_unit_code`、`_non_eia_notation` 的拒绝行为；071 §3②/§4 关掉的 pseudo-reading 不许复活。

## C. 披露口径（schema 只加不改）

`report.json` summary 加 `unreviewedByReason: {reason: count}`；`needs_datasheet` 相关节同步计数。旧键一个不动。

## D. 测试

- `tests/test_184_value_decode_coverage.py`：
  - 20 料号表驱动单测（反馈原表，每个料号断言预期值/预期 code；`CRCW06031K00FKEA` 若 candidates 为空但板上值可解析则断言走 A 路径）
  - 闸门合成测试：板上 value 在+MPN 解不出 → 无 UNDECODABLE；板上 value 缺+MPN 解不出 → 仍有；R4 形态（板上无值、MPN 数字指数可读）→ 无
  - 国巨 `RC0603FR-071KL` 不再返回 `'071'`；`RC0603FR-074K7L` 候选仍含 4.7kΩ（071 族不回归）
- 实板回归：`.tmp_bug98b/实板A.epro2` 跑 `checkup --file`——34 条 UNDECODABLE **预期归零**（个别板上无值且 MPN 真读不出的可留，逐条核对合理性）；`unreviewed_parts` 总数、verdict 变化记录前后对比
- 全量绿；**values.py 在指纹 recipe 内**（rules/ 树？确认 core/ 是否在 recipe——182 批记录 core/parsers/engines 不进摘要，rules/ 进；decap.py 没动就不用重钉；动 checkup.py 同理不在。实测确认）

## E. 纪律

- 不动 git；删除走回收站；pytest `--basetemp`、`-n 4 --dist loadfile`
- values.py 是高压区（015/043/046/071/#22/#25/#27/#32/#72 修复史）：每个新 reader/护栏配 docstring 写明实测料号出处；变异验证 ≥1 组（新护栏删掉→测试红）
- 证据 `outputs/184_value_decode/evidence.md`（基线矩阵、修复后矩阵、实板前后对比、全量尾部）；PROGRESS.md append 一行
- 版本号不动；**不要 commit**，交回主代理收口
