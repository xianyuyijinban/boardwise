# 111a — draw lint 增补三规则（L10 出界 / L5b 同名导线段 / L6 聚类+升级）

**来源**：`tasks/111-addendum.md`（岳 2026-10-04 在编辑器亲跑 DRC + 目视后的裁定）
的第 1/2/3 条。第 4 条（sys_Log）不在本棒，另派。

**你接手的现状**（都已核实，别重新普查）：

- 引擎 `src/boardwise/engines/drawlint.py`（1528 行，纯函数零 bridge 依赖）。
  九谓词 L1-L9 已在 `PREDICATES`（drawlint.py:1458）注册，`run_lint`（:1471）
  逐个调用。阈值常量集中在 :132-:189，每条带实测出处注释。
- CLI `boardwise draw lint` 在 `src/boardwise/cli.py:9725-9910`（纯追加块），
  `--json` 输出里有 thresholds 字典（:9898-:9902）要跟着补新常量。
- 测试 `tests/test_111_draw_lint.py`（744 行，31 条）。合成夹具助手在
  :90-:130（`_snapshot`/`_wire`/`_svg`/`_text_node`/`_lint`/`_by_predicate`），
  真实页 fixture `real_pages`（:135-:161）读 `outputs/111/geo_P{1,22,23,24}_live.json`
  + `render_P*.svg`，文件缺席时 skip（本机都在）。
- **校准证据**（本机已有，直接离线重放，不许碰真机）：
  - `outputs/111/geo_P22_live.json` + `render_P22.svg` 等四页 = 验收页
    （P22/P23/P24 已验收零误报；P1 是 110 反激修前态，41 ERROR 的缺陷页）。
  - 离线重放命令：
    `.venv/Scripts/python.exe -m boardwise.cli draw lint --snapshot outputs/111/geo_P1_live.json --render outputs/111/render_P1.svg --json <out>`
- 111 的标定纪律与分布数据在 `outputs/111/SUMMARY.md` §三（先读再动手）。

## 规则一：L10 出界检查（新谓词，ERROR）

元素几何超出图幅框（`sheet.sheet_box`）即 ERROR。岳实证：P1 的 +12V 旗锚点
(1160,325)、图幅宽 1170，旗名文字实际越界；R19 顶部贴上框（没出界，不报）。

- 检查对象：器件 `page_body()`（`local_body` 为 None 时退回原点单点）、导线
  points、旗锚点、文字框（`sheet.texts`，带 `estimate=True` 标记）。
- sheet_box 为 None → 跳过并在 findings 之外不置一词（照 L9 的诚实降级范式）。
- 出界判定留 0.5 单位 eps，框**碰到**框边不算出界，真超出才算。
- 标定：P22/P23/P24 必须 0 命中；P1 修前快照必须在 +12V 旗处命中至少 1 条。
  把四页各元素的最近边距分布量出来写进证据（分布决定 eps 是否合理）。

## 规则二：L5b 同名导线段（新谓词 `L5-wire-multiname`，WARN）

宿主 DRC 报「导线 $1N77 有多个网络名: LED_A、LED_A」——110 的具名短线技术
让同一根导线 primitive 背了多个同名标注。规则：**一根导线 primitive 上附着
的同名标注（annotation 类 TextBox，net 相同）>1 个 → WARN**，文案点名
「宿主 DRC 会报 导线有多个网络名」。

- 载体判定复用 `_label_carriers`（drawlint.py:1279）。
- 只数 annotation（kind=="label"/页面标注），旗不算（旗+标同区是既有 L5 的活）。
- 标定：P1 修前快照应命中岳 DRC 清单里的 $1N 系导线（LED_A/SW×2/RTCT/CS_FILT/
  HVDC 等，导线 id 与网名要对得上）；**注意 P22 的 TAP 双端标大概率也会命中
  （$93N/$94N 系）——那是与宿主 DRC 行为一致的真阳性**，把 real_pages 的期望
  从「0W」改成「枚举这几条 WARN」，并在 SUMMARY 里逐条申报。
- 与既有 L5（`check_duplicate_annotation`）的关系：L5 的 `_same_carrier` 豁免
  照旧（同载体不报 ERROR），L5b 对同载体报 WARN——两者互补不冲突，注释里写清。

## 规则三：L6 交叉——聚类去重 + 条件升 WARN

现状 `check_crossings`（drawlint.py:1303）：逐分段报 INFO，P1 修前 44 条，
其中 SW×HVDC 同一处交叉被报 8 次（多分段导线重复计数）。

- **聚类**：按「无序导线 primitive 对」分组，同对且交叉点间距 ≤
  `L6_CLUSTER_GAP`（初值 20，拿四页分布标定）的并为一簇；每簇报一条，
  带交叉次数与代表坐标。
- **升 WARN**：簇内交叉次数 ≥ `L6_CLUSTER_WARN`（初值 3——同一对导线反复
  交叉永远没有必要），或全页簇数 > `L6_PAGE_WARN`（拿分布定：验收页
  P22/P23/P24 的簇数实测全部低于它，P1 修前高于它）。
- 单簇 1-2 次 = 维持 INFO（110 的 CS_FILT×HVDC 十字是合法形态，岳验收过）。
- 同网对照旧跳过。**先量 P24 的 XO×孤立段×2 是不是同对双交叉**——若是，
  `L6_CLUSTER_WARN` 必须 >2，否则验收页被误伤。
- 去重后 P1 的 INFO/WARN 总数应显著低于 44，把前后对照写进证据。

## 交付纪律（111 同款，一条不许省）

1. **红测先行**：三个规则各先写 failing 测试（合成正反例 + 真实页钉），
   真的跑红再实现。
2. **零误报优先**：每个新阈值注释里写实测出处（哪页哪分布，2026-10-04）。
3. **变异 ≥2 组**（cp 备份 + sha256 还原，禁 git checkout / sed）：例如摘掉
   L10 → P1 检出钉红；L6_CLUSTER_WARN 调到 1 → 验收页误报钉红。sha 前后
   对账落盘。
4. **零移动对账**：五族预览 83 张 + 21 板前后 sha256（照 `outputs/111/`
   里 `zero_move_*.txt` 的方法重做一遍，存 outputs/111a/）。
5. 跑全量期间不许改代码：
   `.venv/Scripts/python.exe -m pytest tests/ -q --basetemp=.tmp_pt_home`
   （约 8-9 分钟，基线 3514 passed）。
6. 证据落 `outputs/111a/`：四页 lint 前后 JSON、标定分布、变异 sha、
   零移动对账、`SUMMARY.md`（仿 outputs/111/SUMMARY.md 格式，含如实申报节）。
7. `PROGRESS.md` 单行追加一条（追加后 `grep -c "111a" PROGRESS.md` 必须 =1）。
8. `tasks/111-addendum.md` 第 1/2/3 条标记已落地（第 4 条与「另」段不动）。
9. **禁 git 一切写操作**；禁碰真机/daemon；删除一律走回收站（PowerShell
   SendToRecycleBin 通道，写法照 `.kimi-code/skills/boardwise/SKILL.md` §7）。
10. cli.py 只许纯追加（thresholds 字典补新常量）；drawlint.py 的模块 docstring
    谓词表、PREDICATES、run_lint 同步更新。
