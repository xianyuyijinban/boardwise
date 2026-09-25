# 038 eprj3 适配：V4 离线格式只读接入（A 档）

## 背景与入口裁决

岳的朋友升 V4 当试验田；**本体留 V3** ⇒ 本批是**纯增量**：eprj3 读取器并排新增，
V3 管线一寸不动，**全量回归钉是红线**（pytest 不红、离线 eval 逐字节不变、真机 V3 不回归）。

差距分析已完成：`outputs/v4_eprj3_gap_analysis.md`（逐字段映射表 + 两个真差异 + 容器 8 处调用点）。
关键结论：记录框架逐字同构（`iter_epru_records`/`split_documents` 原样复用）、原理图字段名 1:1、
只有 `load_epru_text()` 知道容器。

**范围 = A 档**：只读 SCH_PAGE，让 `review` / `checkup --file` / eval 管线吃到 eprj3。
B 档（PCB / panel / .ecfg / .evar 全格式）**不开**，等 PCB 主线启动再说。
写路径本就不落盘（全走 bridge API），eprj3 工程一律只读——不存在写兼容问题。

**不在本批**：connector on V4 在线探针（V4 里 activate 派不派发、8 个关键 namespace 在不在、
doctor 过不过）——等朋友机器可用再单列批次，只探不改。

## 工作项 0：夹具策略（许可已核，先定）

- 官方示例工程（`easyeda-pro-eprj3-format` 仓库）**无许可文件** ⇒ **不入库、不提交**；
  开发期对照用脚本拉本地 gitignored 目录（如 `.tmp_eprj3_ref/`），证据里注明来源 URL。
- 规范仓库 `easyeda-pro-format-skill` 是 **MIT** ⇒ 可引用、可摘录（注明出处）。
- 单测夹具 = **按规范手写最小合成 eprj3**（一个文件夹：`.eprj3` 索引 + 一页 `.esch2`，
  两个器件一条线一个 GND 旗 + 一枚 netlabel），我们自有、进 `tests/fixtures/`。
- 终验 = 朋友 V4 真实样本（岳去要；拿到后跑 `review --view schematic` 全链，风险清单定案）。

## 工作项 1：`parsers/eprj3.py` 新读取器

- 文件夹扫描：`<name>.eprj3` 读工程元数据（`name` / `profile.schematics/sheets/pcbs`）；
  `sch/<原理图>/<页>.esch2` 逐文件取 text；多页合并成"按文档取 text"的统一入口。
- `yAxisDirection` 预处理（差距报告 §3）：行内见到 `up` 按官方翻转表翻回并剥字段；
  缺省/`down` 维持 `_page_y()` 现状。**两分支都要有测试**。
- PIN 键修正：SYMBOL 内引脚 ATTR 的 `parentId` 在 eprj3 等于 PIN 行 `id`（V3 我们按 `e<zIndex>` 合成）。
  **先查 V3 既有夹具在新键下是否仍全对**：全对则统一换键（更好）；不对则按格式版本分支。
  不许一拍脑袋换——V3 全量测试是裁决。
- SCH_PAGE 段无 CANVAS 要容忍（官方示例实测缺失）。
- eprj3 白送的 `attrs.DeviceName/SymbolName/FootprintName`：身份解析优先用它，
  比 V3 的 uuid 链更省一步（差距报告 §5 末）。

## 工作项 2：接线（8 处调用点）

- `load_epru_text` 的 8 处调用方改"记录源"注入；`cli.py` / `board_source.py` 后缀分派：
  路径是**目录**且内含 `<同名>.eprj3` → eprj3 工程；`.esch2` 单文件 → 单页模式（页名取文件名）。
- `review --latest` 扫描认 eprj3 目录（按目录 mtime）。
- `.eprj3` 索引自带 `name`/`owner_uuid` → 顺手修好"只有 `.epro2` 才带工程 uuid"的老缺口
  （`cli.py:5799` 附近）。
- `--view pcb` 对 eprj3：**诚实报错**"PCB 读取在 B 档（038 未开）"——不给空模型
  （SKILL 坑 14 的教训：空视图会被误读成"0 组件 0 网"）。

## 工作项 3：测试与验收

- 单测（合成夹具）：`build_schematic_model` 全场运行；器件数/位号/网名/连接关系**绝对断言**；
  yAxisDirection 两分支；PIN id 键；无 CANVAS 容忍；eprj3 → review 全链（exit 码 + findings 形态）。
- **V3 红线**：全量 pytest `--basetemp=.tmp_pt_home` 不红；离线 eval 逐字节不变；
  真机 V3 checkup 一轮不回归（只碰 test 窗）。
- 开发期对照：官方示例工程拉本地 gitignored 目录，解析不崩 + 打印 sanity 行
  （页数/器件数/网数）进 `outputs/038_*.txt`。
- 变异 ≥2：yAxisDirection 分支错向（up 也取反）/ PIN 键退回合成键——各至少 1 红。
- connector / tsc 预期**零改动**；发现要动 connector → 停下来报主代理。
- 交卷文本 `outputs/038_summary.txt`；测试与实现同步交付；不碰 git / PROGRESS / SKILL.md。

## 工作项 4（单列，等朋友机器，本批不做）

connector on V4 在线探针：doctor 8 项、`sys.probe` 8 关键成员、activate 派发观察、
`sys.connector_status` 版本回读。只探不改，结果另立批次处理。

## 守卫

照旧：pytest 必带 `--basetemp=.tmp_pt_home`；变异 cp 备份 + sha256/cmp 还原；
三线全绿才交卷；真机只碰 test/test2 显式寻址，禁地全程只读；eprj3 工程**只读**。

## 交卷记录

（子代理交文本，主代理 append 并复验。）

### 主代理复验（2026-09-25）

- 交卷文本：`outputs/038_summary.txt`；证据 `outputs/038_probe.txt` / `038_pytest.txt`。
- **sha256 抽核 7/7 一致**：eprj3.py / epru_stream.py / schematic.py / cli.py / test_038_eprj3.py /
  合成夹具两件，与 `038_pytest.txt` 表逐字节相同。
- **三线主代理复跑全绿**：pytest **1627 passed**（108.8s，`--basetemp=.tmp_pt_home`）/
  connector **419 pass 0 fail** / `tsc --noEmit` 干净。
- **git status 只出现预期文件**：M cli/epru_stream/schematic + 新 eprj3.py、test_038、fixtures/eprj3_synth；
  `tasks/017-eval-set-expansion.md`（永久草稿）不入提交。
- **V3 红线**：三文件 diff 逐 hunk 审阅——新分支全由 `looks_like_eprj3`（目录含 `*.eprj3` 或 `.eprj3`
  文件）与 `_pin_key_for(meta)`（缺省 `"zIndex"`）把守，`.epro2` 物理上进不了新分支；
  `_collect_symbols` 默认参数路径行为逐字节不变。eval 无同集历史基线（如实降级声明，
  替代论证 = diff 审阅 + 47 器件/40 网/zIndex 锚点测试）。真机 checkup 子代理已跑（test 窗，无回归）。
- **两处偏离裁决**：① 分派放 `load_epru_text` 内部而非改 8 处调用点——**批准**（爆炸半径更小，
  同一容器缝，效果相同）；② `yAxisDirection` 信封/body 两位置都收——**批准**（规范未说明时的
  防御姿态；真样本终验第一件事核对此条）。
- 文档：SKILL.md §3.2 补 eprj3 条目（只读 SCH_PAGE / pcb 诚实报错 / `--latest` 认目录 /
  owner_uuid 修老缺口）；坑表**不新增**（本批为离线格式工作，未踩真机坑）。
- 遗留（照旧挂着）：朋友真实 V4 样本终验（yAxisDirection / NC 引脚 id / CANVAS 缺失定案）；
  connector-on-V4 在线探针（工作项 4，等朋友机器）；`.eprj3` 当 plan 快照属写路径侧，A 档未开。
