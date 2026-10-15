# 任务书：186 — 喂 PDF 链路闭环 + hygiene 敏感串防线

- 批号：**186**　日期：2026-10-15　来源：岳的 AI 使用者体验反馈 P1/P2/P3/P4 + 清洗批暴露的防线缺口
- 前置：185（c41f1c1）已落 conclusion 节

## A. 人工 facts 一等入口（P4，核心）

现状（需先核实）：`parts add` 只建空壳条目；清闸要货架条目 `facts_verified: true` + 真实 facts；AI 读得懂手册却没有把 facts 写进货架的路径。

- 摸清：`parts add` 现有参数、货架条目 schema（facts 结构、facts_verified 语义与谁消费它）、`parts fetch --file` 的产出形态
- 扩展 `parts add`（或新增子动作，选与现有 CLI 风格一致的）：支持 `--facts <file.json>` / `--fact key=value`（可重复）写入 facts，并显式 `--verified` 才落 `facts_verified: true`（**不许默认 true**——人工核验是个声明动作）；写入前走既有 validate 管线（`lib device validate --spec` 的等价物若存在）
- 端到端场景必须通：板上 `OCP8201ASAD`（无 MPN 匹配，只有 Name）→ AI 读 PDF → `parts add --facts … --verified` → 重跑 checkup → 该器件从 `needs_datasheet` 清单消失

## B. 本地手册匹配加 Name 兜底（P2）

现状：本地手册只按 `mpn`/`lcsc` 匹配，板上 `Name=OCP8201ASAD`、PDF 同名文件对不上。

- 匹配链加 `device_name`（器件 Name 字段）兜底：MPN/LCSC 不中时按 Name 匹配；命中标 `matched_by: "name"`（证据级别低于 mpn，报告文案体现"按器件名匹配"）
- 文件名规整（去后缀/大小写/连字符变体）按现有匹配器的风格做

## C. 报告出路文案 + 未审分栏（P1 + 2.3）

- checkup 报告「未审器件」节（report.md + review-summary 骨架对应段）加固定说明行：**"给 PDF ≠ 清闸；清闸 = 货架条目带已核验 facts（`boardwise parts add --facts … --verified`），或工程师明示 accept-unknown"**——文案以 CLI 实际命令为准
- `unreviewed_parts`/`needs_datasheet` 展示层分两类：**「工具读不懂」**（UNDECODABLE 等解码类 reason）vs **「真缺资料」**（无 MPN/无供应商/货架无料）；计数用 184 的 `unreviewedByReason` 分组，report.md 里分栏列出
- `parts fetch` facts 为空时输出提示：「facts 提取为空——文档语言/结构可能不在提取范围，可走人工路径」（P3 的止血）

## D. hygiene 敏感串扫描（防 183/184 式复发）

- `tools/check_repo_hygiene.py` 加第二道闸：读**仓库根 `.sensitive-words`**（gitignored 本地文件，每行一个词，支持 `#` 注释），存在则扫描**全部已跟踪文件内容**（含新增 staged），命中即违规列出文件:行
- `.gitignore` 加 `.sensitive-words`（名单本身永不入库）
- 岳本机把企业项目名写进这个文件；clone 者没有该文件 = 该闸自动关闭（注释写明）
- 测试：合成临时词表 + 临时文件验证命中/未命中/无名单三态

## E. 测试与纪律

- 新测试 `tests/test_186_pdf_facts_path.py`（A/B/C 端到端 + D 三态）
- 全量绿：`.venv/Scripts/python.exe -m pytest tests/ -q -n 4 --dist loadfile --basetemp=.tmp_pt_186`（本机 sources 在位，36 条"在场才跑"会真跑）
- 红线：不动 git；删除走回收站；指纹 recipe 只含 rules/（动了才重钉 test_126a）
- 报告 schema 只加不改；`report.json` 键集合快照钉按实重钉（注释批号）
- 证据 `outputs/186_pdf_facts/evidence.md`；PROGRESS.md append 一行
- 版本号不动；**不要 commit**，交回主代理收口
