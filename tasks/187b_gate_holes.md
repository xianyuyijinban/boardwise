# 任务书：187B — 发布闸必拦（186/185 系四洞）

- 批号：**187B**　日期：2026-10-16　来源：挖洞 swarm agent-344（探针 `C:\Users\xiangyu\.tmp_audit186\`）与 agent-343 报告
- 范围：186-H1、186-H2、hygiene 基线+编码+性能（中4/中5/中6）、185-中1；其余中低项不做（记 188）

## 1. 186-H1 四处规则查找改道（`src/boardwise/rules/pcb/`）

- `mcusupply.py:457`、`mcureset.py:260`、`regulator.py:300`、`focground.py:734` 的 `find_facts(mpn, lcsc)` 改走 `resolve_component_facts`（器件名兜底，与 checkup 闸门同尺）
- 修完加 **grep 级不变量测试**：`rules/` 下不得再出现 `find_facts(`（豁免须带注释批号）；把 `tests/test_186_pdf_facts_path.py` 那条只压 FactsRule 的测试升级成覆盖这 4 条规则的同尺断言
- `mcusupply.py:448-451` 与 `crystal.py:357` 两句互相矛盾的 docstring 修正
- 指纹：rules/ 全动 → 重钉 test_126a recursive/direct + 台账

## 2. 186-H2 货架写读一致（`cli.py` + `resources.py` + `engines/checkup.py`）

- frozen 形态：`parts add` 写入位置改为**用户数据目录**（`~/.boardwise/parts.json`）；读侧 `default_library_path()` 顺序改为：用户目录存在则优先（用户增补架），否则 frozen 内置架——checkout 开发态行为不变（仓库 blocklib 优先）
- `resources.parts_library()` docstring 更新；`tests/test_resources.py` 的冻结态钉子按实重钉
- 报告「未审器件」节的清闸文案：印出本次审查**实际读取的货架路径**（`report.json` 加 `shelfPath` 键，schema 只加）+ 固定文案带 `--library <该路径>`
- 验证：模拟 frozen（`sys.frozen`/`_MEIPASS`）下 add→checkup 读同一架

## 3. hygiene 敏感串闸三修（`tools/check_repo_hygiene.py`）

- **基线（中5）**：名单文件支持豁免行（格式 `path<TAB>word` 或注释约定），豁免=该词在该路径的历史存在；全量扫描报全部命中但 **exit 码只反映非豁免命中**；岳首次启用可把既有命中写进豁免，之后只拦新增
- **编码（中4）**：按 BOM/候选嗅探（utf-8-sig → utf-16 → gbk）读文本；二进制/解不出的文件跳过并计 `unscanned` 数打印（静默换披露）
- **性能（中6）**：词表复合成单条 alternation 正则单遍扫描（或按扩展名跳二进制）；目标：12 词全库 < 3s
- 测试：三态（命中/未命中/豁免）+ UTF-16/GBK 命中 + 性能粗测；`tests/test_repo_hygiene.py` 与 186 里跑真仓敏感闸的测试改成对临时词表跑（真仓只测容器闸——否则岳本机名单生效后全量红，测试不再机器无关）

## 4. 185-中1 折叠行补板别（`engines/checkup.py`）

- `needs_datasheet_section` 折叠行补 `boards` 字段（该位号出现在哪些板、每块的 mpn/name/value），`mpn` 字段保留首到值不动（schema 只加）
- docstring（checkup.py:1651 那句"其余字段不变"）改成实话
- SOP（docs/review-sop.md）口径同步：`needsDatasheetTotal` = 去重位号数（不是 placement 行数），报「还差几份手册」时注意多板同位号
- 测试：多板同位号夹具（毕设FOC 3 板有现成的）断言折叠行带 boards 且内容正确

## 5. 测试与纪律

- 新测试 `tests/test_187b_gate_holes.py`
- 全量绿：`.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_187b`（sources 在位）
- 红线：不动 git；删除走回收站；真实项目名零出现（R4b）；schema 只加不改
- 证据 `outputs/187b_gate_holes/evidence.md`；PROGRESS.md append 一行
- **不要 commit**，交回主代理收口
