# 085 — #33：覆盖闸补齐丢弃类 producer（instances_without_designator 入 recordsDropped）

来源：GitHub issue #33（附实测复现：高速板丢 67 颗无位号器件照判 complete，而 components_without_symbol 却 gate——严重度倒挂）。
纯 Python 批：**不碰 connector TS、不碰 dsh-plugin、不碰真机**。

## 已核实的锚点（直接照做，先读上下文确认再改）

1. **`src/boardwise/cli.py:3113-3115`** —— `_coverage_section` 的 `records_dropped` 目前只加两个计数器。把 `int(parse_stats.instances_without_designator)` 并入。
2. **cli.py:3103-3106** —— `_coverage_section` docstring 里 "recordsDropped — `ParseStats`'s two drop counters, summed" 改为三个，并把三种丢弃语义点明（管脚无编号 / 器件无符号 / 器件无位号——第三种是整颗器件从模型消失，对所有规则不可见，严重度最高）。
3. **cli.py:4443 附近** —— 有注释说 "coverage.recordsDropped is the sum of the two drop counters"，读上下文后对齐为三个。
4. **cli.py:3160-3164** —— `_coverage_reasons` 的 recordsDropped 措辞 "（管脚无编号 / 器件无符号，" 扩成三种（加「器件无位号」）。

## 测试（`tests/test_072_coverage_gate.py`，风格跟随现有用例）

现有 `test_the_coverage_section_reads_the_tier_ladder_and_the_parse`（:550-579）构造 ParseStats 断言 recordsDropped==3（2 pins + 1 part）。在此基础上：

1. **区分值求和证人**：三个计数器各取不同的非零值（如 pins=2 / symbol=3 / designator=5）断言 recordsDropped==10——区分值才能抓「加错字段」（加成 pads_without_net 之类值不变才抓得到）。可以改现有用例也可以新增，但现有的 2+1=3 证人语义要保留。
2. **防漂移闸**（issue 点名要的，与 #19 名单同一课）：在测试文件里显式列出 `DROP_COUNTERS = ("pins_dropped_no_number", "components_without_symbol", "instances_without_designator")`，再用 `dataclasses.fields(ParseStats)` 反扫：**每个 int 型计数字段必须要么在 DROP_COUNTERS 里、要么在测试里显式登记的 NOT_WIRED 字典（字段名→不入闸理由）里**。NOT_WIRED 至少要覆盖：total_records / pcb_records / pads_without_net / empty_body_records / malformed_records（它走 parseIncomplete 单独 gate，:3117）/ attrs_attached_by_parent_id（到达方式计数，不是丢弃）。dict/str 字段不在扫描范围。这样今后谁往 ParseStats 加新的丢弃计数器而没接线，测试就红。

## 验收

- `.venv/Scripts/python.exe -m pytest tests/test_072_coverage_gate.py -q --basetemp=.tmp_pt_home_agent085` 全绿（**必须用这个 basetemp**，`.tmp_pt_home` 是主代理全量专用）。
- `git status` 只应见：cli.py、tests/test_072_coverage_gate.py、tasks/085-coverage-gate-producer.md。
- **不 commit、不 push、不写 PROGRESS.md**（主代理收口）。

## 边界（不做）

- `unknown_types` **不入闸**：它是格式漂移信号（dict），不是记录丢失；issue 里的「可单列 recordsUnknownTypes」是可选项，本批不做，留 fix comment 给岳裁。
- `checkup.py:1731` 的显示文案是泛化写法（"解析丢弃记录 N"），不改。
- 不改 verdict 判定逻辑本身（recordsDropped 非零 → complete-with-open-items 的既有映射不动）。
