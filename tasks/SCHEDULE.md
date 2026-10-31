# 排期（2026-10-31 更新；主代理维护，岳裁）

> **2026-10-17 岳裁：v0.6.0 押后到 10 月底**。这段时间不发新版，打磨存量功能，
> 主攻**原理图绘制质量**（目标：先把一个模块画好；布线和布局算法重写），
> 岳会跑测试用例给反馈。0.6.0 的 122 E 阶段 + 高速 A 档冻结到月底前一周再动。

发版规矩不变：挖洞 swarm + 上机 + 实测三闸全过才发；**正式版一周最多一发、何时发由岳定**，其余一律按**内测（prerelease）**发；同一天只发一版；connector 版本 = 发布版本；**dsh 插件从 0.6.0 起与 boardwise 外部版本同号**（`0.1.x` 到 `0.1.3` 止；插件改动用固定 commit 复检到达，不为此挪 tag）。

| 版本 | 内容 | 状态 | 依赖 |
|---|---|---|---|
| **v0.5.14**（内测）✅ 10-17 已发 | main 已落：187c / 188A / 188B / 189A1 / 189A2 / 189B / 189C / 189Cf / 190；+ **190S** 底层丝印真机定标（含 editor_pose 上机对拍） | 190S 开工（10-17） | test 窗口在线 |
| **v0.5.15**（**正式版**，岳 10-17 裁）✅ 10-17 已发 | **515B** 保密闸/dsh/文档 12 洞（pre-push 解析失败拒推、hygiene 读不到文件 exit 1、zlib 假头吞流、`-n +8` 绕过、钩子可执行位、dsh 截断标注…）· **516** 岳审查反馈：A1 同电位豁免按绝对电压判、A2 载流按连通分量展开、A3 needs-datasheet 侧车自动并入 + B1/B2 + C1-C5 · R4 实验④结论记档（菜单点击免重载激活成立）· **201C 布线协商踢出本版** | 三闸全过：挖洞✓（23 洞→12 修复）· 实测✓（6242 passed / 0 failed）· 上机✓（双窗热更 verified、在线离线 47/47 对拍、draw lint 0 error） | — |

> **201C 处置（岳 10-17 裁 A）**：201C 布线协商**不进 v0.5.15**。150 落地页回归已实锤——
> 软预留走廊把义务网通道占住，逼 `FB_SENSE` 改走竖段，host 印的**网名行**沿竖段竖排压在 `R8` 器体上
> 0.5 单位，readability 硬拒；而 `FB_SENSE` 恰是 `core/textmetrics.py:126` 已记录的模型例外
> （`WIRE_NAME_MODEL_EXCEPTION`，15/16 吻合、它是唯一例外），readability 从未接这个例外。
> HEAD 对照：HEAD `ok=True`（1 合法候选，5 rejected 全「same geometry」）→ 201C `ok=False`（5 变体全死）。
> 改动整体 backup 在 `.tmp_201c_hold/`（router.py `3375da5b` / drawcompiler.py `221c8c9a` / 201c.patch /
> test_201c_routing.py / test_116 预算版），复活时**按 A 修**：布线后自检网名行，压器体/文本则把名字行盒
> 加进 `blocked` **单网重布一次**（201D 文本行代价的雏形），不接线例外豁免。
| **v0.5.16**（**内测**，岳 10-18 裁） | **审查线资料获取（R6）三连**：**520** `parts hunt` 批量寻址（C 号 → 立创 detail API → `pdfUrl` → 下载 → 带页码 `.txt`；46 颗板 24 个唯一 C 号冷启 41 s、热缓存 1.2 s / 0 外呼；`--offline` 零外呼出工单；只发 C 号，`hunt-audit.jsonl` 逐条留证）· **521** `--apply-facts` 收 AI 读 txt 的产出（六道闸，最硬一条**引文逐字**；改一个字 → `no candidates/` 目录）· **522** `facts_verified` 布尔 → `facts_trust` 三档（`candidate` / `machine_verified` / `verified`；**判据=结论 vs 数字**，十一条算数字的规则吃机器核验、结论类仍要人工；每条 finding 统一带「未人工确认」；verdict 不涂绿）· 附带：`docs/drawing-algorithm-brief.md`（绘图困境/证伪路子/接口，给外部算法推演用） | 三闸：挖洞（522 自审出 2 处回归并修）· 实测见下 · 上机待做 | 真机 daemon 需重启以载入 0.5.16 |
| **v0.5.17**（**内测**，岳 10-18 裁：修完再做真机核验） | **v0.5.16 挖洞补做**（5 缝只读 swarm，46b9c1f..ea6b1ce）→ 12 条高严重级缺陷全修：**521 的引文闸**（纯子串 → 10 字符/3 token 下限 + 两端词边界；`pin_appears` → `pin_appears_in_evidence`，pin 必须印在这条 claim 引的那几行里，一并钉死「引文与事实不绑定」）· **522 的两条绕过**（`OpenDrainPullup`/`UsbCcPulldown` 直接读 `entry.facts`，现在走 `FactsRule.admissible`；四处裸读 `entry.category` 改走 `shelf_declaration`）· **保密审计**（新增 `dest` 记目标 host、审计每次运行清空、`--apply` 只收 http(s)）· **假话与崩溃**（`--offline` 报告不再说「都拿到了」、`facts_trust: null` 报错、`--shelf` 继承 uuid/params、无身份件不再 `IdentityLeak` 崩、`quotes: 5` 不再 TypeError、`.txt` 无页码改判 `no-document`）。新回归 6 条 | 三闸：挖洞✓（12 修）· 实测见下 · 上机待做 | v0.5.16 的 release notes 已标「请用 0.5.17」 |
| **v0.5.18**（**内测**，2026-10-19 立） | **527 收口批**（0.6.0 之前必须落地的尾巴，任务书 `tasks/527_pre060_loose_ends.md`）：**527A** `IntentSource` 转发 `rails`/`signals`/`buses`（按文档构造的合成上下文里合同曾被静默读成空）· **527B** connector `readback` 页型守卫（B4：焦点不在 PCB 页时 `TypeError`）+ 信封文档（B3）· **527C** 189A2 跨视图 7/8/6/2 条分类与裁定 · **527D** `parts classify` + `category_trust`（523：机器核验的件终于有分类授予路径）· **527E** 文档收口（189A1 结案不改、088b DRAFT 归档） | **✅ 2026-10-19 已发**（内测，tag `v0.5.18`）：挖洞两条缝 16 洞 / 14 修 2 记 · 全量 6472 passed / 25 skipped / 0 failed · connector 532 + tsc · dsh 50/1 + build · 上机 3 窗 connector 0.5.18 verified（B4 正/反例 + 对照组）；产物 exe `8e547a0b…` / eext `48abe3b5…` / dsh `e84862c1…` | — |
| **v0.5.19**（内测，未排） | **R4-C（岳 10-19 裁）**：`bridge update-connector --no-reload`（写记录、不 reload，点一次扩展菜单生效，**528A 已落工作树**，含 528A-a 版本闸：显式 `--version` 与 `extension.json` 不一致直接 exit 2，避免一次必然假 FAILED 把人赶去卸载重装）；**stub 方案冻结到 0.6.x 之后**（实验④已证明「写 + 点一次菜单」可用，stub 只剩「零点击」的增量，却要换来无认证 WS 上执行远端载荷的风险）。真机已验：`--no-reload` exit 0、instance id 前后不变、无 `--yes` 也不问确认（`outputs/528a/evidence.md`） | **✅ 2026-10-20 已发（内测，tag `v0.5.19`）**：+ **527D2** `category_provenance` 落货架 · **527D3** 17 个分类读点分档感知（`category_verdict` 三态）· **201F** A\* 可采纳下界（A\* 14.2 s→2.05 s，83 预览逐字节相同）· **四条缝的只读红队 21 洞 / 20 修**（含 3 条比改动前更糟的真回归）。读数：pytest 6621 passed / 25 skipped · connector 536 + tsc · dsh 50/1 + build。产物 exe `4a2fda98…` / eext `4f672ec7…` / dsh `e84862c1…` | — |
| **v0.5.20**（**内测**，2026-10-23） | **审查线实板反馈修复**：#83 铺铜包含性判据恒真（间距静默丢行）· #84 载流不建模铺铜/分支（承担铜时细线档降 UNKNOWN(INFO) 逐段点名）· #85 同封装焊盘对误报间距 · #86 旧库 Value 为空按货架 MPN/C 号补容值；**#88 以 5 条 `xfail(strict=True)` 记档**（铺铜弧当弦视图）· **绘图线并回 main**（merge `534d21f`：520a2–533 多岛落图）+ **535 合并暴露三层回归修复**（`2c71844`：pin-text 单模块容忍、地网降级旗标+记账、埋脚逃逸）+ **535 跟进**（`f4f3709`：143 F1 拒绝保持在 gnd 降级之前）· dsh 迁移（`docs/handoff.md`、SKILL 双副本、根 package.json shim `23b2a53`）；dsh-plugin 0.1.3 | 挖洞✓（dsh 子代理只读红队：0 实锤 / 4 存疑记档）· 实测：dsh 侧 6934 passed / **5 环境红**（3 条钩=沙箱拦 msys BaseNamedObjects、1 条 hunt=假接缝+真网络、1 条=并行竞态单跑即绿，机制均定位记档）——**0 红读数待在非沙箱终端补取**（`--basetemp=$env:TEMP\tmp_pt_rel520`）· connector 536 passed + tsc · dsh 50/1 + build；产物 exe `b0e0dce9…` / eext `E523BD6F…` / dsh `16DA3308…` | — |
| **v0.5.21**（**正式版**，2026-10-23） | **dsh 迁移暴露的测试基建三修**（发布 v0.5.20 时被沙箱环境照出的暗伤）：① `parts hunt` 的 fetch_detail 假接缝修复（`cli.py` 函数内局部 import 甩开猴子补丁 → `globals().get` 优先 + 惰性兜底；`test_520_parts_hunt` 离线密封，521/522 两处同名死补丁一并激活）· ② 钩测试 3 条加 sh 共享对象探测 skip（本机 python 子进程受限时自动 skip，非受限环境照真跑）· ③ guard probe 收集竞态根治（`--confcutdir=tests/`，churn 对拍 5/40→0/40）· 附带：epru docstring 抹除机器路径、handoff「在 dsh 里跑测试」基线节 | 挖洞✓（dsh 红队 0 实锤）· 实测✓（**dsh 与终端双边 6936 passed / 0 failed / 25 skipped / 5 xfailed 逐字一致**，互证等价；钩链另有真实 commit/push 触发旁证）· 上机：无新增 bridge/connector 行为面，闸不适用；产物 exe `93a4be1d…` / eext `55FABAA6…` / dsh `16DA3308…`（0.1.3 未变） | — |
| **v0.6.0**（正式版，2026-10-31） | 200A/B/C 报告与高速审查 + 542 反激人工锚 + CH343 示例 + 527D2/D3 + 540 平台准备 + V4 单 PCB 首批 + #89 同网测量与证据披露 | 全量 **8821 passed / 25 skipped / 0 failed**；connector 542、DSH 127/1、Rust 47+显式4；真机 doctor 9/9、evidence exit 0、P4 lint 0/0/0；三件发布件验收通过 | — |
| **v0.6.x** | **041 跨板网络**（DRAFT → 细化，040b 已落地）+ **V4 适配**（岳 2026-10-19 裁：**11 月起做**，见 `tasks/038-eprj3-tierA.md` §V4） | 0.6.0 后 | — |
| **0.6.0 后（独立方向）** | **AI 电路语义编译层**：网表 → 类型化、类 C 的可读语言，AI 读编译结果而非原始网表；调研任务 `tasks/038_v4_review_line_research.md` 只登记 V3/V4 共用语义边界，不实施编译器 | 先定义语义合同与可验证还原，再逐规则/逐视图小批接入；不与 V4 适配同批 | — |
| 远景 | **R5 SPICE**：岳 10-17 裁——等**原理图绘制过关** + **041 跨板网络**搞定后再开 | 冻结 | 两个前置 |

## 当前主攻（2026-10-31：**0.6.0 已收口，随后进入 0.6.x**）

- **0.6.0 四个功能门槛均已完成**：① `200A/200B/200C` 随 `d2130b7` 入库；
  ② 542 P0 反激整页三关、岳人眼和关闭重开验收通过；③ `527D3` 已落；
  ④ `527D2` 已落。早期诊断和失败读数保留在任务书中，不再当作当前进度。
- **本版追加内容**：540 平台准备、CH343 示例、V4 首批单 PCB 工作流，以及 #89 稳压器/FB
  同网测量与证据披露修复。V4 多 PCB、实时 PCB 位图和部分样本语义仍是公开边界。
- **本版验收已完成**：全量测试、真机、三件发布件与保密闸分别记录；服务端哈希在 Release
  上传后回读。不用旧批次的绿读数替代本版，不把 `incomplete/partial` 写成板级通过。
- **0.6.x**：绘制算法与 Rust strangler 并行；`041` 跨板网络、V4 后续样本与多 PCB 适配按任务书
  分批；`R4 stub` 仍冻结，未经岳裁不复活。算法与迁移不同批，shared/全量/真机串行。
- **非阻塞**：R6 的 `L2b`/`L2c`；`529` 去耦分类空白带；`527C2` 跨视图 note 按几何分两句。
- **存量打磨**：岳跑测试用例 → 反馈 → 修复，循环。

## 待岳拍板（不排期就不动）

### 2026-10-19 已裁（四条，落地见 `tasks/528_060_gate.md`）

- **R4 → C**：先做 `update-connector --no-reload`（528A），stub 冻结到 0.6.x 之后。
- **191D → 数值不动**：`200 / 300 / 800 / 200` mil 保持；改立 `529` 分类空白带（2.2µF/4.7µF 落 unknown）。
- **绘图线磨清楚了才能发 0.6.0**：判据取 roadmap §4 的锚 + §8 三条区域级裁定（不新造判据）。
- **527D3 + 527D2 在 0.6.0 前完成**：从 0.6.x 规划升为 0.6.0 阻塞项。

### 仍待裁

- 121 反激规划落图（10-06 暂停；绘图线 201E/进针/文字行之后才轮得到）
- R4 `stub` 是否复活（冻结到 0.6.x 之后再看；前置是**去工作电脑 `About…` 读一次宿主版本**——
  若那是 3.2.149，懒求值会让 stub 同样不生效，真该做的是升级宿主）
### 已结案（2026-10-19，527E）

- **两份过时 DRAFT 标注归档**：051 早有「已被 052 取代」横幅；088b-deltas 三条偏差已由岳 10-02 逐条裁定并随 followups 落账，本轮加归档横幅，只留作裁决原文。
- **189A1 不改**：`read_stackup.used_copper_layer_ids` 维持「文档声明口径」。改读 `effective_layer_ids` 会把通孔盘的内层带进 used 集，与 `test_125_pcb_measure.py::test_foc_main_board_used_layers` 的实读 `[1,2,16]`（岳 2026-10-07 亲裁值）冲突；裁决注释已在 `core/measure.py:321`。

## 540 平台准备与后续双主线（2026-10-31 复核）

| 工作 | 当前状态 | 证据 / 锁 |
|---|---|---|
| 540A/B 工作区与解耦 | 已落；142 模块/0 legacy、24 CLI 命令、DSH 10 工具；三入口与集成锁已建立 | `evidence/540/b-behavior-equivalence.md`；shared/CLI/bridge 改动走集成锁 |
| 540C Rust 平台 | 已落；最小 workspace、合同、fmt/clippy、显式语料与 5 case 双侧差分均已运行 | `evidence/540/c-acceptance.md`；不批量翻译、不全局安装 |
| 540 最终候选验收 | Python **8132 passed / 94 skipped / 5 xfailed / 0 failed**；其他门禁读数见证据 | **`evidence/540/candidate-regression.md`**；这是 540 历史候选读数，不替代 0.6.0 最终全量 |
| 540 真机追加验收 | 历史结论为 `conclusion=incomplete / delivery=partial`（0 器件 0 网络），不是板级通过 | `evidence/540/real-machine-instance-20261025-233933/25-final-report.md`；0.6.0 真机另验 |

- 审查线派单：`tasks/review-line.md`；绘制线派单：`tasks/draw-line.md`；shared 集成锁：
  `tasks/shared-platform.md`。两线可独立派小批，shared/全量/真机串行，算法与迁移不同批。
- 0.6.x：绘制算法与 Rust strangler 并行；新工具/引擎默认 Rust，旧工具垂直迁移。
- 0.7.0：Rust 接管全部受支持主流程，不是逐行翻译全部 Python；connector/DSH 薄适配可留 TS。

## 200 审查线收口（2026-10-31 复核）

| 项 | 当前状态 | 证据 |
|---|---|---|
| 200A 报告整合 | **已落 `d2130b7`** | `outputs/200a/report-integration-evidence.md` |
| 200B 高速 A1 | **已落 `d2130b7`** | `outputs/200b/evidence.md` |
| 200C 高速 A2/A3 | **已落 `d2130b7`** | `outputs/200c1/evidence.md`、`outputs/200c2/evidence.md` |

200 批历史集成读数 **8540 passed / 25 skipped / 2 failed** 与失败原文仍见
`outputs/200/acceptance.md`，不改写历史。当前 0.6.0 的最终全量、真机与发布件验收单独记录；
功能门槛已收口不等于发布件已经签发。
