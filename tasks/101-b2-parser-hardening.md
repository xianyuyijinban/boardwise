# 101 / B2 解析器加固批（issue #57 之 #4 #5）

来源：外部审计 `.tmp_bug_report.md`（仓库根，gitignored；读 "## 4." "## 5." 两节）。
跟踪 issue：GitHub #57。**每条先写红测复现，红测即复验。** 全部离线，不碰 daemon/真机/编辑器。

## #4 read_project_meta 在归档守卫外 — `src/boardwise/parsers/epru_stream.py:296` 调 `:234-241`

`load_epru_text` 把 `.epru` 成员的读取（:288-292）包成友好的 `EncryptedProjectError`，
但 :296 调用的 `read_project_meta` **重新打开同一归档**，自己的 handler（:239）只捕
`ValueError`/`UnicodeDecodeError`。审计实测：project2.json 的 CRC 损坏 → 裸
`zipfile.BadZipFile` traceback、exit 1（README 把 exit 1 留给「板子有 ERROR」；
部分拷贝的下载是最常见的真实成因，应得友好错误 exit 2）。
修：让这条路径与 :288-292 同款——`BadZipFile`/`RuntimeError` 转成 `EncryptedProjectError`
（hint 文风照抄既有）。改 `read_project_meta` 自身或包住 :296 调用点，选能让
「同一归档两种读法同一待遇」的那个，别只治这一个调用点而留下别的入口裸奔（先查它还有没有别的调用者）。

## #5 原理图层对空 body 记录不耐受 — `src/boardwise/parsers/schematic.py`

`iter_epru_records` 的硬合同：unknown/malformed 记录「counted and skipped，**永不 raise**」，
空/非对象 body → `EpruRecord.body = None`（`epru_stream.py:161-172`）。`epru.py` 全文件
遵守（:474-476/:205/:1228），`schematic.py` 不遵守——`:240` 等地无条件 `record.body.get(...)`。
审计点名的位置：`:240, :309-311, :379-380, :387, :485, :798, :964, :997, :1055, :1269-1271`。
审计实测六个公开入口全崩（2 记录 `.epro2`，首条 `{"type":"DOCHEAD","id":"d1"}|||`）：
`build_schematic_model / collect_part_devices / collect_page_layout /
collect_symbol_details / build_pin_offsets / collect_part_placements`。
另：`_split_page` 自相矛盾——pass 1 有守卫（:737）、pass 2 没有（:798），60 行之隔。
修：凡 `record.body` 可能为 None 的消费点按 epru.py 同款跳过（不是吞别的异常，只是
「这条记录没有可读的体」就跳过并计数/忽略，与兄弟文件同语义）。六个公开入口逐一出红测
（空 body DOCHEAD/ATTR 各试），修完全绿；`_split_page` 两趟一致性单独一条测试。
**先全文件搜一遍 `record.body` / `.body.get` 确认审计的清单没有漏点**，漏了一并修并申报。

## 纪律

- pytest 必带 `--basetemp=.tmp_pt_home`；交付前全量亲跑（基线 **3268 passed**，增量恰=新测试数）。
- 变异 ≥2 组（cp+sha256，禁 sed/git apply/git checkout）：
  M1 摘掉 schematic.py 任一处新守卫 → 对应红测回红；M2 #4 的转换摘掉 → 红测回红。
- 零移动：全量 pytest + 五族预览对照（既有夹具在有效记录上输出应逐字节不动；
  真实夹具里 LINE/PAD_NET/NET/LAYER 本就有空 body 记录——它们走的是别的路径，若你的守卫
  改变了任何既有夹具输出，逐处申报原因）。
- 测试放 `tests/test_101_b2_parser_hardening.py`。
- 不碰 git、不写 PROGRESS、删除进回收站、不碰 `tests/fixtures/` 既有夹具（新夹具放测试内联
  `tmp_path`）。
- 交付 `outputs/101/`：SUMMARY（每条红→修→绿）、变异记录、零移动结论、全量结果行。
- 拿不准写遗留，别扩大改动面。
