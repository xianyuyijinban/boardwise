# 100 / B1 快速守卫批（issue #57 之 #3 #9 #10 #15 #16 #19）

来源：外部审计 `.tmp_bug_report.md`（仓库根，gitignored 临时文件；各条含执行复现）。
跟踪 issue：GitHub #57。**每条先写红测复现，红测本身就是该条的复验。**
全部离线，**不碰 daemon / 真机 / 编辑器**。

## 六条（逐条：红测 → 修 → 绿）

### #3 param-rc-cutoff 除零 — `src/boardwise/rules/params.py:1319` (+:1413)
电阻清单有 `ohms > 0` 守卫（:1316），电容清单只有 `is not None`（:1319）。
`parse_capacitance_farads("0uF")` 返回 `0.0` 通过守卫 → :1413 `1/(2π·R·0)` ZeroDivisionError。
checkup 被 `rules_errored` 吞掉整条规则；`review_eval.py:325-327` 无 try/except 直接中止。
修法（审计原话）：`if farads is not None and farads > 0:`。审计已确认全 fixtures 无零值电容（0 hits），零移动。

### #9 patchpin.same_point 对缺/非数坐标 TypeError — `src/boardwise/engines/patchpin.py:58-62`
`_number` 逐元素返回 None，但 `same_point` 只守卫元组本身不守卫元素。
复现载荷：`{"ComponentType":"netflag","Net":"GND"}`（无 X/Y）或 `{"X":"200"}`（字符串坐标）
→ :210 TypeError。兄弟读者 `addcomponent.component_origins`（:181-183）把 `x is None or y is None`
当预期形状跳过；cli.py:14116-14117 / 14567-14568 只捕 `AttachmentRefused`，TypeError 以原始
traceback 逃逸。修：元素为 None 时按「不是同一点」处理（与 addcomponent 同款耐受），别吞别的异常。

### #10 .enet 把 JSON null 读成字符串 "None" — `src/boardwise/parsers/enet.py:162-163, :170-175`
`dict.get(key, default)` 只对**键缺失**生效；键在值为 `null` 时得到 `None`。
复现：`{"props":{"Designator":"R1","Value":null,...},"pinInfoMap":{"1":{"number":null,"name":null,"net":"GND"}}}`
→ pin 变 `('None','None','GND')`，`c.value.strip()` AttributeError；幻影引脚 "None" 进网表比较。
兄弟 `epro2_model._clean`（:76-81）就是把 None→"""；enet.py:157-159 对 `net` 已硬化——文件只硬了一半。
修：value/footprint/number/name 同款 None→""。**注意**：若任何既有夹具带显式 null，输出会变——零移动对照必须跑。

### #15 `__all__` 虚标 — `core/presentationspec.py:76` / `engines/grammar/ldo.py:107`
`FLOW_EDGE_KEYS` 实际叫 `_FLOW_EDGE_KEYS`（:162）；`CORE_ROLES` 实际叫 `CORE_PIN_ROLES`（:128）。
星号导入 AttributeError（审计已执行验证）。修 `__all__` 指向真实名。
`tests/test_083_value_unification.py:722` 已有「imported but not promised」断言样板可照抄。

### #16 SVG 预览裁掉自己 caption 尾行 — `src/boardwise/engines/svgpreview.py:128` vs `:285-297`
画布写死 `height + 90`，`_caption` 却产出 4 固定行 + 至多 4 条 notes（4–8 行），
`height+16+index*15`，index≥5 掉出图外。实测 7 行时丢含几何哈希/verdict 的尾行。
修：高度由 `len(lines)` 推导。**这是有意的可见输出变化**：跑五族预览零移动对照，
凡是 caption >5 行的预览高度会变——逐张申报（哪些变了、为什么、变化=不再裁尾行）。

### #19 UTF-8 BOM 不剥，流首条记录被静默丢弃 — `parsers/epru_stream.py:298`，同款 `eprj3.py:297,301`、`enet.py:128`
`raw.decode("utf-8")` → U+FEFF 让 `json.loads` 失败，首条计 malformed 静默丢，exit 0。
审计实测：丢的是库 FOOTPRINT DOCHEAD（不是板），但属无解释数据丢失。
修：`raw.decode("utf-8-sig")`（三处文件四个点，逐处红测）。

## 纪律

- pytest 必带 `--basetemp=.tmp_pt_home`；交付前全量亲跑（基线 **3252 passed**，增量应恰=新测试数）。
- **变异 ≥2 组**（cp 备份 + sha256 还原，禁 sed/git apply/git checkout）：
  M1 摘掉 #3 的 `farads > 0` → #3 红测必须回红；M2 把 #19 一处改回 `utf-8` → 对应红测回红。
- **零移动对照**：五族预览 + apply 家族（054/056/057）按惯例跑；#16 引起的变化逐张申报，
  其余五条应逐字节不动。
- 测试集中放 `tests/test_100_b1_quick_guards.py`（如某条需要可归入就近既有文件，说明理由）。
- 不碰 git、不写 PROGRESS、删除一律回收站、不碰 `tests/fixtures/` 既有夹具与 outputs/011e* 等禁地。
- 交付：`outputs/100/`（SUMMARY.txt + 每条的复现输出 + 变异记录 + 零移动对照 + 全量结果行）。
- 拿不准的（比如 #16 高度公式怎么算才对、#9 该返回 False 还是跳过）先按审计与兄弟代码的同族做法修，
  仍拿不准写进 SUMMARY 遗留，不要自行扩大改动面。
