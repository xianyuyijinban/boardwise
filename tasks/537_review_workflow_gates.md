# 537 · 审查流程环境 / 证据 / 权限 / 交付硬闸

> 来源：岳 2026-10-24 提供的《审查流程分析与优化建议》及原会话复盘材料
> （真实会话只在临时区核实，不入库）。本批先逐条核实，再修工具与流程；
> 不把复盘里的每个建议都当成正确实现方案。
>
> 红线：真实工程只读；本批不操作画布、不写任何工程、不做 git 写操作；真实会话与网表只进
> `.tmp_537_review/` 临时核实区，不进入公开夹具。回归使用匿名化合成数据。

## 1. 核实结论

| 项 | 原会话与代码证据 | 判定 / 处置 |
|---|---|---|
| DSH skill / doctor | 原 seq 35 为 7/10，Kimi/Claude 异版 + connector 0.5.18 vs 0.5.21；当前会话已成功加载 `.agents` skill，但 doctor 仍只查 Kimi/Claude | “DSH 无 skill”已被现状覆盖；doctor 的 harness 识别仍是真缺口，修 |
| connector 环境 | checkup `source.connectorVersion` 已记版本，但没有期望版本、能力限制或交付披露 | 修：环境限制进入结构化报告与 finalize |
| crossView 过度确认 | seq 133/146 实时 SCH 给出 U1.44/43/42、U1.33、U1.35/36/37；seq 192 只有归档两侧差异；seq 162/176 live PCB 失败，seq 237/299 PCB 图失败 | `crossView` 已声明“不判哪侧正确”，算法不重写；补机器可读 `suspected` 状态和候选映射，防止模型手工拼错 |
| 覆盖缺口 | live SCH 成功、archive PCB 成功、live PCB 失败、PCB 图缺失，最终未独立披露 | 修：分通道覆盖账 + 独立实时证据采集 + partial 交付语义 |
| 警告分诊 | seq 320 将无逐条文本的 host ERC 标“有害”，seq 435 pending=0；当前 pending 只看 verdict 非空 | 修：`needs-manual` 仍占 pending；命令与手改侧车都不能绕闸 |
| 数据手册证据 | seq 258 web_search 404，seq 442 仍出现“已与 LQFP-64 手册核对”和具体手册参数 | 修：无手册证据时相关措辞/结论不能过 finalize；资料缺口保持 pending |
| 采样偏置 | 实时网表确有 R17/R18 → VCC/2；当前源码能识别分压中点，但下午归档的 R10/R16 `Value` 为空，后续 L0 却能从 MPN 恢复 1k，导致规则把“有但无效的偏置”写成“没有偏置” | 不重写算法；补唯一 MPN 阻值恢复并共享给存在性与 Thévenin 算术，恢复来源进 evidence。间距工艺也不凭“电气不敏感”关闭 |
| DSH 写权限 | 插件文案要求只读，但 `boardwise_bridge` 原样转发全部 action；daemon 只有风险分级，没有真实工程只读策略 | 修：CLI 只读模式 + 插件强制；checkup 返回 writeAllowed=false 与允许的下一步 |
| finalize / present | seq 404 校验异常被后续命令 exit 0 掩盖；seq 431 同一步发检查与 present；DSH present 只 stat 文件 | 修：finalize 先验证并签发与文件哈希绑定的运行时收据；present 的硬阻断单独核 DSH 扩展点，不用提示词冒充硬闸 |
| Windows / shell | seq 77 中文乱码，seq 339 长 heredoc SyntaxError，seq 304/421 `rm -f` | 当前插件有 UTF-8 解码，当前 harness 已有长脚本/read/grep/回收站纪律；补必要测试，不用新 shell 脚本重造流程 |
| PCB 恢复 | seq 299 焦点成功后仍未得到 PCB 图，readback/render 由手写 shell 串联，错误被 exit 0 掩盖 | 修：高层采集逐步记录 ok/failed/error，render 不阻断 readback，finally 恢复原焦点 |

## 2. 串行小批

### 537A · 环境与只读

- DSH 下 doctor 检查工作区 `.agents/skills/boardwise/SKILL.md`，不再要求无关的 Kimi/Claude 安装；非 DSH 行为不变。
- checkup 结构化记录运行/期望 connector 版本与环境限制。
- `bridge call --read-only` 在转发前按 action catalogue 的 risk 硬拒非 read；DSH 插件强制使用。
- checkup 报告与 stdout 给出 `writeAllowed=false` 和离线 plan / 工程师手动 / 明确授权测试工程的下一步。

### 537A3 · daemon 设计写工程白名单

- A2 只管住插件逃生口；普通 `bridge call` / `edit apply` 仍可绕到真实工程，本棒关闭整条 daemon 路径。
- action catalogue 增加明确的 designWrite 分类：导航 `doc.focus/doc.open` 与连接器自更新不等于设计写；删改器件/导线/属性、建删页、打标、保存、覆盖源文本才是设计写。
- daemon 默认只放行 `test` / `test2` 的设计写；真实工程或工程身份未知在转发前拒绝，read 与导航不变。操作员显式 `BOARDWISE_WRITE_PROJECTS` 可放行指定工程，`*` 仅作 legacy 兼容开关。
- 不用真实工程做写测试；以 fake window 证明未转发。

### 537B · 分诊硬闸

- 保留 `TRIAGE_VERDICTS` 三词兼容；新增并列 `needs-manual`。
- 无逐条文本的槽位不得用三词关闭；`needs-manual` 必须有理由、仍计 pending，并单列 needsManual 计数。
- 侧车非法判决不并入，报告 notes 点名；控制台、report.md、completion 同源。
- 不把 open-items 的既有退出码契约改成新错误。

### 537C · 证据与覆盖

- crossView 差异只标 `suspected`；从同一 net 名的原理图成员自动生成候选映射，包含同位号候选脚，证据来源分开。
- `cross_view_lonely_pins` 的原始行形状、空结果与 `checked:false` 保持兼容；`candidateMappings` / 状态只在有差异时加性写入，不给“无差异”凭空增加 confirmed 结论。
- 新增 `liveSchematic / archivePcb / livePcb / schematicImage / pcbImage / datasheets` 覆盖账；未采集与失败不同。
- 高层实时证据采集独立记录每一步 stdout/stderr/exit/error，readback 与 render 不互相阻断，finally 恢复焦点。
- 缺 live PCB 或 PCB 图像时是 partial delivery，不得只用笼统 verdict 掩盖。
- 执行拆棒：C1 crossView；C2 环境/权限；C3a 六通道证据账与现有报告接入；C3b1 独立实时采集器；
  C3b2 `review-evidence` 命令与报告合并；C3b3 用实时 netlist 为候选补引脚名（archive/live 来源分开）。
  状态词汇保持 `ok / failed / missing / unavailable / not-applicable`：未采集与失败不合并，
  无 PCB 文档与未读 PCB 不合并。`partial` 只描述证据/交付覆盖，不等于板子通过或不通过。
  `liveSchematic` 不得由 project-file/per-page 归档冒充：只有直接实时网表/几何（或 C3b 的直接
  readback/netlist）才可记 ok；归档先记 missing。`archivePcb` 与 `livePcb` 也是两条不同证据路径。
  datasheets 只把 `accepted_unknown.state == "accepted"` 的当前接受未审计为缺口；stale / stale-elsewhere /
  not-unreviewed 不单独把当前板降为 unavailable，但仍走既有 completion 披露。
  C3b 的 identity/focusRestore 放在 channels 外；identity 未核实保持 partial，focus 恢复失败阻止 finalize。
  这些额外 disclosure 在 need-datasheet 派生刷新时也必须保留，不得被重算抹掉；人工 summary 不被采集覆盖。
  C3b3 可加性写 `liveSchematicCandidates`（含 pin name）与 `liveCandidateEvidence`，不把 archive 候选改掉；
  原会话实读证明归档差异脚与实时同网脚可有不同 pin number，因此必须按实时同名网的实际成员生成 live 候选，
  不是只给旧 archive ref 补名字；工程级网表遇重复位号/身份歧义时保持待核，不任选一份。
  仅 `verifiedAgainstReport=true`、liveSchematic 可用且 netlist artifact 哈希吻合时才写 live 候选；
  身份未核实的完整采集仍只作 partial 披露，不把可能属于另一工程的候选并入报告。
  即使实时证据成功，crossView 仍 suspected，除非未来另有逐脚对拍，绝不自动 confirmed。

### 537D · 结构化读取与 finalize

- 提供高层结构化读取，常规审查不再手写一次性 JSON 解析脚本。DSH `runBoardwise` stdout 会截断，
  插件不得解析半截 JSON；review-read 工具经 `--json` 落盘后读取完整结果并检查退出码/文件。
- `review finalize` 校验 Markdown 表格/转义、占位符、行集与 location_chains、结论一致性、needs-manual、覆盖与环境披露、无手册证据的禁用措辞。
- finalize 成功签发与文件内容哈希绑定的运行时收据；失败、异常或文件变动均不可交付。
- DSH present 只消费当前会话中真实 finalize 工具产生的 `plugin:boardwise-dsh/review-finalized` 记录，不直接信任模型可手写的 `finalize.json`；present 重新计算哈希，并行 finalize/present 因尚无记录而拒绝。
- `present` 的新校验默认关闭，只由 boardwise 插件 patch 对审查文件开启；普通图片/Office 交付不变。`review-summary.md` 是审查目录标记，避免把任意目录下的普通 `report.md` 误纳管。
- 同一输入重复 finalize 应幂等；checkup 重跑或文件内容改变后旧收据必须失效。没有扩展点就明确保留缺口，不伪称已硬阻断。
- 执行拆棒：D1a `review-read` 的结构化读取；D1b 实时证据/批量分诊的工具面；D2 `review finalize`
  校验器；D3 插件真实 Session 收据与 DSH `present` 复核。每棒独立验收，不把 CLI 的 ok 当成 Session 收据，
  也不把收据当成板级通过。DSH `snapshotEvents` 已标 deprecated，新代码优先用 Session projection。
  DSH 源码/组成核查（尚未改运行进程）：实际 preset 把 present 放在 `agent-preset.config.plugins`，不是
  `applyEntryPatches` 会递归的 loader group；主探针按根层 `id: present` patch 得到 `entry present not found`，
  所以不得声称根 patch 可配置嵌套行。D3 改用 boardwise 根插件的 `tools/pre-execute` listener：在 present
  正文前对审查交付 deny/allow，并自行经 ctx.fs 重算哈希；插件不存在即默认无闸，普通文件直接 next，
  不改 present config / maxFiles / DSH-core present 源码。该路径仍须以真实 listener + Session 测试验收。
  自定义 `plugin:boardwise-dsh/review-finalized` 要走 `appendPluginRecord`（带 ignorable 记录 envelope），
  不是给 typed SessionEvent 用的 `session.append`；闸只读当前 Session 的 projection，不读手写文件或全量事件快照。
  finalize 不得盲信旧报告保存的 completion：先用当前分诊/覆盖规则重算并同步，再计算哈希；
  缺新 environment/evidence 的旧报告必须重跑采集，不能补猜后签发。`finalize.ok` 仅表示交付校验通过。
  板级结论仍以 `report.conclusion` 为唯一权威；evidence/finalize 的 partial/complete 是另一层交付覆盖，
  不得从 summary 文案另造通过结论。重算后必须经现有写口同步 board_report/conclusion。

### 537E · 文档与回归

- SOP 改成结构化读取 → 分诊 → 覆盖补全 → finalize → 顺序交付；模型记忆不等于手册，archive 不等于 live。
- 聚焦测试 + 旧 triage/checkup/doctor/bridge/plugin 回归；按仓库纪律跑交付线。
- 完成后才进入下一批“子岛独立编译与局部回滚”。

### 537F · 空 Value 的阻值恢复（已复现的 P2 规则输入缺口）

- 同一拓扑只把 R10/R16 的 `Value` 置空，当前规则即从“有偏置”退化为“没有偏置”；MPN `0603WAF1001T5E` 可唯一恢复 1k。
- 只恢复空白字段；非空但不可读、MPN 多候选、货架明确声明非电阻均不猜。
- 存在性判断与 Thévenin 算术共用同一读数；恢复来源进 evidence。区分“无偏置”与“有但无效的偏置”，不重写算法。

### 537G · Windows 子进程 UTF-8

- 原始 Python 子进程在 DSH shell 下已复现中文/µ 乱码；`PYTHONUTF8=1` 可消除。
- 在 DSH 的 bash/pwsh 本地执行器环境默认值中补 `PYTHONUTF8=1` 与 `PYTHONIOENCODING=utf-8`，调用方显式 env 仍可覆盖；不改 boardwise 既有 CLI 解码。

## 3. 非目标

- 不重画、不同步、不修改原会话所涉工程或任何真实工程。
- 不把 crossView 的两种可能原因压成唯一结论；不把 live PCB 成功自动等同于归档差异已确认，除非另有逐脚对拍。
- 不重写 `path-sampling-bias`、间距工艺规则，不增加审查规则条数。
- 不复制真实工程、完整会话、网表或图像进 tests/fixtures / 公开文档。
- 不做 git add / commit / checkout / restore / push，不发布版本。

## 4. 验收证据

- **537A1（主代理复审通过）**：代理 TDD red `10 failed, 57 passed`；green `67 passed`。
  主代理用新 basetemp 合并复跑 `test_537a_doctor_dsh / test_doctor / test_069c_guided_doctor /
  test_skill_install / test_doc_claims`：**132 passed / 3 skipped**。DSH 仅 `skill-dsh`、9 项；
  legacy 仍 Kimi/Claude 两项、10 项。
- **537A2（主代理复审通过）**：Python red `10 failed, 2 passed`；TS red `2 failed`。
  主代理独立复跑 `test_537a_bridge_readonly / test_bridge_cli / test_dsh_plugin_sync`：
  **63 passed**；`dsh-plugin` typecheck + test（**52 passed / 1 skipped**）+ build 全绿。
  非 read action 在 `_open_cli` 前 exit 2，旧的不带 `--read-only` 路径不变。
- **537B（主代理复审通过）**：结构性 red（`TRIAGE_UNJUDGEABLE` 不存在）与行为 red（命令/侧车均可把无文本 ERC 误判关闭）；修后首轮 **89 passed**，相邻两组 **86 / 81 passed**。
  主代理复审另发现“整键删除 text 可绕闸”，退回窄修；最终独立复跑 537b/063/039c/070/075 **92 passed**，缺键复现 `admissible=False / closed=False`，非空文本仍可判。
- **537A3（主代理复审通过）**：代理先红 `26 failed, 9 passed`（真实工程与未知身份均被转发），修后新测
  **37 passed**，指定聚焦 **195 passed**；三个变异分别打掉 8 / 1 / 3 条测试，恢复后 hash 与备份一致。
  主代理检查 `design_write` 位于 dataclass 尾部、无变异残留，独立复跑指定五组及 confirmation-gate：
  **235 passed**。生产默认仍为 test/test2；legacy 测试只在构造处显式注入 `write_projects={"*"}`。
  本批只验证源码，运行中的 daemon 尚未重启，不能声称新策略已在当前进程生效。
- **537C1（主代理复审通过）**：代理先红 `10 failed, 5 passed`，绿为新增 15 + 旧 18 = **33 passed**；
  两个变异分别红 5 / 3，cp 恢复后 hash 一致。主代理用新 basetemp 独立复跑新增、189A2、537B、192A
  共 **52 passed**。仅在 lonely 非空时增加 `status=suspected` 与逐行 `candidateMappings`；原始行、空结果、
  checked:false 形状不变。候选只取归档原理图同名网的真实成员并标注 archivePcb/archiveSchematic；
  候选网本身 unproven 时仍只是待核候选，不构成连接结论。原报告归档的同名控制网包含预期候选脚；
  具体真实引脚只留在临时核实区，没有把这次源码测试说成原工程实时复核。
- **537C2（主代理复审通过）**：代理先红 `15 failed, 2 passed`，三个变异分别红 4 / 4 / 2 并恢复；
  主复审另发现 console 硬编码 writeAllowed，窄修先红 `1 failed, 17 passed`，修后新增 **18 passed**。
  主代理独立合并复跑环境、checkup、025d、插件同步及 069a/154/185/187b：**160 passed**；
  diff --check 干净。原报告只读判定为 expected 0.5.21 / running 0.5.18 / mismatch，
  limitation=`connector-version-mismatch`，writeAllowed=false。离线 file 的 expected 保留仓库版本，
  status=not-applicable；离线不是 mismatch。四处渲染同源，completion/exit/schema 未改。
- **537C3a（主代理复审通过）**：代理先红 `23 failed, 1 passed`，新增 **27 passed**；三个变异分别红
  5 / 5 / 1 并恢复。主代理独立复跑指定五组及 090/092/126d/131c/154/185/189b：**310 passed**；
  diff --check 与 MUTANT 扫描干净。原报告投影为 liveSchematic=missing（不归档冒充实时）、archivePcb=ok、
  livePcb=missing、schematicImage=ok、pcbImage=missing、datasheets=unavailable，delivery=partial；
  旧报告没有补造直接采集史。`state=accepted` 才算当前接受未审，stale 不降级；SVG 回退保留 pngError。
- **537C3b1（主代理复审通过）**：独立采集器与匿名 fake-client 套件只新增 `engines/liveevidence.py` 及其测试；
  逐步记录 readback/netlist/geometry/render，独立核 `document.current.active.uuid`，并在 finally 恢复、复核原焦点。
  代理最终新增 **41 passed**；另对焦点、listing、PNG 守卫做变异并 cp/hash 恢复。主代理复审退回四类残余缺口后，
  最终树补成：无效 `doc.list` 四通道 `missing` 且零导航、PNG 必须具真实 8 字节签名、readback `kind` 必须匹配
  sch/pcb、geometry 必须有完整 meta/count。主探针分别得到 `RENDER_NOT_IMAGE`（零 artifact）、
  `READBACK_KIND_MISMATCH`、`GEOMETRY_NO_META`、`GEOMETRY_INCOMPLETE`，坏 listing 只调用 `doc.list`；
  主代理用独立 basetemp 合并复跑 C3b1+C3a：**68 passed**。最终源码 sha256
  `2e8def1a30fcdc239119164119297c4a9e41decee2d351b2eb6ca4b8b036e259`，diff/MUTANT 检查干净。
  本棒只验收 fake client，没有连接 daemon/编辑器，也没有声称真实 PCB 已补读或出图。
- **537C3b2a（主代理复审通过）**：纯 `merge_live_capture` 只替换四个 live 通道，archive/datasheets 原样保留；
  identity/focusRestore 作为 channels 外的 liveCapture 元数据进入 delivery，未核实身份与焦点恢复失败各有固定 disclosure，
  need-datasheet 刷新及 Markdown/console fallback 均不丢。代理首轮 11 新测，三个变异后恢复；主代理用真实 collector
  返回形状做集成探针，证明 `capture.ok=true + verifiedAgainstReport=false` 仍为 partial。主复审另查出空 liveCapture
  被误当无采集的边界，退回窄修为“仅 None 表示旧报告无采集，空/损坏记录 fail closed”。
  最终主探针得到：unverified=partial（identity 码）、verified=complete、empty/broken liveCapture=partial
  （identity+focus 两码）、刷新保留 capture、坏输入拒绝、输入未被改。主代理独立复跑新增/证据/采集/相邻报告：
  **152 passed**；最终 evidence.py sha256 `0c5aec23557074179d57dcf58dda6e55f5f994cfa0805c7063e5277494c8d560`。
  本棒仍是纯函数与渲染，不含 CLI、落盘、finalize 或真机验收。
- **537C3b2b（主代理复审通过）**：`review-evidence` 从 report.source.project.projectUuid 取身份，
  经同一 collector 写 `live-evidence.json`（稳定字节 + bytes/sha256），合并四通道并经既有写口重建
  report.json/report.md/board-report.md；review-summary 人工内容在成功、采集失败、doc.list 失败路径均不变。
  退出码 0/1/2/3 只描述采集：未核实身份即使 capture.ok=true 也为 1，缺报告/桥或 doc.list 不可读为 3。
  代理 24 新测、三类变异恢复；主复审另以探针确认缺通道/非法 status 在连接前为 2，并查出 `_open_cli`
  准备异常原为 traceback，窄修后为 3、SystemExit 安装提示保持。最终主探针得到 2/2/3 且报告未变，
  主代理独立复跑七组：**180 passed**。最终 cli.py sha256
  `dde022aad2e378e8a68c2385c658a701250a6572b8fc8ab826808a2a4f47cc18`，diff/MUTANT 干净。
  全部使用匿名 fake client；未连接 daemon/编辑器，未声称真实 PCB 已补读、出图或完成视觉验收。
- **537C3b3a（主代理复审通过）**：纯 `enrich_cross_view_live_candidates` 先剥离旧 live 字段，身份未核实即停止；
  仅按实时同名网真实成员生成 `liveSchematicCandidates[{pin,pinName}]` 与 `liveCandidateEvidence`，
  archive 五字段及 suspected 不动；缺网为 missing，重复位号/不可解析脚为 unavailable 且不给部分列表。
  candidate parser 只增加重复位号 consumer 披露，components/nets 读数不变。代理 41 新测、四个变异恢复；
  主代理独立复跑五组 **119 passed**。另用临时区保留的实时网表读数做离线探针（不是重新采集），
  七组同网候选与引脚名映射均命中预期；repeatedDesignators=[]，archive 保留、无 confirmed。
  具体网名、位号与引脚只留临时核实区，不进入本任务书或公开夹具。
  最终 pcbreview/candidate hash 分别为 `4f4e4700b34e8ee478e1bb62d0de9a48a709343ee0c2a25dc5061c9ea8db858a` /
  `c267cb004124d60c313709c7f24eddc8fcc083381831ab5a9781120504a47f09`；真实数据未进公开夹具。
  本棒未接 CLI、未改板级结论、未做 finalize 或真机验收。
- **537C3b3b（主代理复审通过）**：review-evidence 在 capture/merge 后、三份 writer 前接入实时候选；
  仅 verified + liveSchematic=ok + 有 mappings 才读取 netlist，核验单文件名、bytes、sha256、UTF-8 与 parser；
  失败 exit2 且原始 capture 留档、四份报告不动。identity/live 不可用走同一纯函数剥旧 live 字段，不读网表；
  evidence 只在候选成功后写入，内存与磁盘都不半改；无 mappings 不强制解析，console 不虚构身份原因。
  代理 40 个 CLI 测试、三个变异恢复；主代理独立复跑八组 **237 passed**。另以原报告副本 + 原 raw netlist
  跑 fake-client 集成：exit0、七组实时候选落盘、summary 保留；故意把 artifact sha 改为全零后 exit2，
  四份文件逐字节不变、capture 保留。最终 cli.py sha256
  `75e14741a9b6209984cac81d6f9caba0ad66941d0846649e8c9af01b40743cec`。
  全部为离线/fake 验证；未连接 daemon/编辑器，未声称真实板已补读、出图、视觉通过或 crossView confirmed。
- **537D1a1（主代理复审通过）**：新增 `review-read` 与纯投影模块，覆盖 verdict/findings/crossView/coverage；
  envelope 不含易误解的 ok，verdict 只认 report.conclusion，needs-manual 计数复用 checkup predicates，
  缺 environment/evidence/completion 明示 missing。`--json` 以 bytes 输出保持 stdout/文件一致，五个审查输入
  及其路径别名禁止作为输出。代理 58 新测、三个变异恢复；主代理独立复跑聚焦与相邻组 **315 passed**。
  原报告只读探针：verdict 与原 conclusion 完全一致；旧 completion.warningsPendingTriage=0 经当前规则
  读为 pending=1、needsManual=0（无文本的普通“有害”不再关闭）；crossView lonely=7；
  coverage.missingSections=[environment,evidence]；源文件逐字节不变。最终 reviewread.py hash
  `997b59d85a74988f72148d18e9d24decbfefa2c926fedd91c833a57f0d39eb35`。未做 netlist/artifacts、分诊写入、插件或 finalize。
- **537D1a2a（主代理复审通过）**：`review-read --section netlist` 只在 identity verified + liveSchematic=ok
  且恰一条 artifact 时读取实际文件并复用 bytes/hash/UTF-8/parser 校验；无 capture/identity 未核/通道失败/无 artifact
  均为 missing 且不读文件，不从目录文件名猜 live。规范化 components/nets/pinName，保留 repeatedDesignators 与
  unresolvedPins（未解析 pinName=null，真实空名=""）。代理 33 新测后，主原探针发现其把 channels 错放在
  liveCapture：真实结构是 evidence.channels.liveSchematic、liveCapture 只存元数据。夹具先改真 → 旧实现 14 红，
  随后 engine+CLI 同步窄修，新增真实结构钉；三个变异恢复。最终主代理复跑 **339 passed**。
  原旧报告 status=missing、不读 netlist_raw；增强报告 status=ok，七组 pin 映射全中，repeated/unresolved 均空，
  两个源文件未变。最终 reviewread.py/cli.py hash 分别为
  `83a7057c2eae18f7bb30473c4046b42f90d570f15526096099ffb4cf5275434b` /
  `8ed61c41be323ab4b172b739ee9b2caed49a9fc91332de37ce400fca2235e7fd`。
  未做 artifacts、分诊写入、插件、finalize 或真机。
- **537D1a2b（主代理复审通过）**：`review-read --section artifacts` 只按报告机器字段列出
  canvas、channels、liveCapture/captureFile 与五个标准输出，不从目录 promotion 未引用文件；
  逐行给 source/channel/artifact/path/exists/bytesOnDisk/bytesMatch/sha256Matches/error，
  越界在目标 resolve/stat/open 前拒绝，内部文件分块重算 hash，missingOutputs 只记缺席标准输出。
  首轮后主探针退回三类边界：archivePcb 的 `{title,components,copperLayers}` 是非文件读数，
  同来源同文件但冲突 hash 不得被去重吞掉，目标 resolve 失败不得 fallback 后继续 stat；窄修均有合成钉。
  主代理独立复跑 537C/D **327 passed**；主边界探针为冲突两行/unavailable、resolve 零读取、archive 元数据零文件行。
  原旧报告 canvas bytes/sha 均吻合、live-evidence 仅列 missingOutputs；增强报告在新临时 stage 补齐既有 canvas 引用后，
  capture/netlist bytes/sha 均吻合且 status=ok，两个源报告逐字节不变。最终 reviewread.py/cli.py hash 分别为
  `b1ee09fb83c84e23ed91e6f59f3b61e6e4585a589c4e537107758580bf92e8ba` /
  `d989e1990611e5d66e2082d670aa62129870ac054ed52a8240b30e942e65d9f7`。
  未做批量分诊、插件、finalize、视觉或真机验收。
- **537D1b1（主代理复审通过）**：新增 `triage-batch --out --input [--json]`，严格
  `boardwise.triage-batch/1` 输入；整批预检与内存合并后才调用现有 sidecar/report/report.md/board-report
  写口，任一非法行零写入，review-summary 不动。输入重复 key 拒绝；报告重复 key 全更新并披露；
  needs-manual 复用同一 predicate，仍 pending 且进 manualReviewRequired。JSON 不造板级 ok，
  stdout/file 为同 UTF-8 bytes，受保护输出在任何 writer 前拒绝。主复审另退回非字符串 key/reason
  被 str 强转、坏 warning_triage traceback 两边界；窄修后类型与 report/re-gate 结构错误均写前 exit2。
  主代理独立复跑 537D+063/070/537B **210 passed**；主边界探针为非字符串/坏结构 exit2 且零写入。
  原报告临时副本：合法首行+未知次行零写入；host ERC 改 needs-manual 后 pending=1、needsManual=1，
  重跑字节一致，原目录不变。最终 cli.py hash
  `c30ba73ba0b8702ff793944ec6445feb8987a547c06b729428039bce3a55b717`。未做插件或 finalize。
- **537D1b2（主代理复审通过）**：dsh-plugin 新增 boardwise_review_read / review_evidence /
  triage_batch。review_read 与 triage_batch 只经 `--json PATH` 读完整文件并做 transport 校验，
  非零/缺文件/坏 JSON/schema 或 section 不符均抛错，绝不 fallback 到截断 stdout；TS 不重算
  verdict/pending/needs-manual。review_evidence 保留采集 exit0/1/2/3 文本语义与四份 artifact notes。
  主代理独立复跑 typecheck/test/build：插件 **75 passed / 1 skipped**；test_dsh_plugin_sync **4 passed**。
  真实 Node + Python 离线集成：findings render **59864 bytes**，完整返回 34 findings/7 triage；
  非法批抛错且零写入，合法批 pending=1、needsManual=1，原目录不变。三轮变异分别抓 stdout 解析、
  缺文件 fallback、忽略 exit code。最终 src/index.ts hash
  `b1ace05fe0edd12dd198fc53373b5727b08d60c9d7f78ec23e644bfae57f2c9c`；lib 由 build 生成。
  pnpm 必须带 `--config.verify-deps-before-run=false`，避免自动 install 改动 npm 布局。
  未做真实 daemon/画布、finalize/Session receipt/present gate、版本与全量回归。
- **537D2a1（主代理复审通过）**：新增纯 `reviewfinalize.validate_review_summary`，七组校验
  Markdown/转义与行集、人工占位、权威 conclusion、分诊、环境/覆盖、手册禁用措辞、crossView suspected；
  不读文件、不 import cli、不改输入，pending/needs-manual/partial 在披露一致时允许。
  首轮后主探针退回七类 fail-open：分隔列数、无关否定、focus 披露即豁免、manualReviewRequired 缺/错 key、
  非 dict 槽位与无量词人工计数；窄修为七列分隔、最近子句+连接语闭集、focus 无条件阻断、
  人工清单逐 key 对拍。合法“据此认定/据此声称”否定仍放行。主代理独立复跑 **293 passed**；
  真实 checkup 正例 pending=3/delivery=partial 得 `issues=[]`；十个 fail-open 全报对应 code，
  两个合法连接语反例仍 `[]`。原旧/增强报告稳定给 11/13 个明确 issue，源文件不变。
  最终 reviewfinalize.py hash `4370f657a78dfdbff26f67bbb2e47c42a353976e6bf7a77de9dbc1c156622747`。
  未做 CLI、机器摘要、收据或插件。
- **537D2a2（主代理复审通过）**：`review finalize --out` 在内存合并侧车、重算 completion/summary、
  刷新 datasheets、派生 board_report/conclusion，再调用 D2a1 校验器与 artifacts 文件核验；任何 1/2/3
  均在 writer 前结束，成功只经既有写口同步 report.json/report.md/board-report.md，人工 summary 与侧车不改。
  代理 TDD 首轮 34 个测试全红，最终本文件 43 + 校验器 74 passed；主代理独立合并复跑八组 **255 passed**。
  主审另抓到非 list renderErrors 与空字符串 --json/--md 三类 fail-open，窄修后分别 exit1/exit2 且零写入，
  两个变异各被 5/2 个测试捕获并 cp+hash 恢复。真实 checkup 正例 pending=3/delivery=partial 连续两次 exit0、
  重复字节一致、summary 不变；原旧/增强报告分别 exit1（9/11 行 issue）、暂存副本零写入、原始来源不变。
  最终 cli.py / 测试 hash 为 `ea3b991ff83197296714547e1460acffa724e858e4547d94be5ea353bf650eec` /
  `0ed848bbeaa2a15194a13b919881b1e54a0091a93599cfad41e911849bbb0af2`。本棒不创建 finalize.json，
  尚未做机器管理段落同步、CLI 收据或 DSH Session/present 闸。
- **537D2b1（主代理复审通过）**：finalize 只用权威 renderer 同步 summary 的 environment/evidence
  两个机器段，段外人工内容与 CRLF 保留，缺标题/缺披露不补造，失败时内存同步不落盘。
  入口另按当前 CHECKUP/EVIDENCE/LIVE_EVIDENCE schema 拒绝未知版本（exit2）；通道 status 必须在
  固定词表，通道与 liveCapture 的 artifacts/errors/steps/captureFile 坏容器不得被当成空证据（exit1）。
  派生 delivery 的正常重算、缺省可选字段、archivePcb 无文件元数据保持兼容。
  代理最终两文件 **161 passed**；主代理独立复跑八组 **299 passed**。主黑盒探针覆盖
  CRLF/段外字节、三个 foreign schema、非法 status、六类坏容器、坏 environment/liveCapture：
  均按预期 exit0/1/2 且失败零写入；合法 pending=3/partial 仍两次 exit0、重复字节一致、未创建收据。
  原旧/增强报告保持 exit1（9/11 行 issue）与零写入，原始来源不变。
  最终 cli.py / reviewfinalize.py hash 为 `da02827751b91817ba7f904baaed36baffde953d641cd1b3da2d5891930dfd85` /
  `5a1b96baa441a72ba06acd4aeed3fce9576f273bdea7640b12b96eef477d496f`；两份测试 hash 为
  `d1dc9b1a5bc93cc75acd6df3ce7be411511083d0dcc059e13ba66dbf90677419` /
  `5b5d1c0f376c9688a8a8ab639e011bd003a9bd7a4feeb09652b192d81ad6942f`。
  本棒仍未创建 finalize.json，未做 CLI 收据或 DSH Session/present 闸。
- **537D2b2（主代理复审通过）**：成功 finalize 在四份输出落盘后重读最终 report.json，再次复用
  artifacts 投影与文件核验，签 `boardwise.review-finalize/1`（`ok=true` 仅 `delivery-content`，
  板级权威仍 `report.conclusion`）。receipt 以 resolved path 去重、相对 POSIX 排序，覆盖必需四件、
  存在的 live-evidence/sidecar/architecture/design-intent 与所有引用证据；bytes/sha256 从最终文件分块重算，
  排除自身，不含时间戳/随机值/绝对路径。sibling tmp + os.replace 原子写入；writer、写后复核、hash、
  rename 失败均 exit2 且不产生新收据，pre-gate 1/2/3 零写入不变。
  代理本文件 75 / 八组 **311 passed**；主代理加入 doc-claims 与插件同步后独立复跑 **332 passed**。
  主黑盒：8 个跟踪文件（含相对/绝对同文件去重）全部 bytes/hash 吻合，重复整目录字节一致；
  markdown/summary writer 与 rename 三类异常均 exit2、无收据、无 traceback。真实 checkup 正例
  pending=3/partial 可签且重复稳定；原旧/增强报告仍 exit1、零写入、无新收据，原始来源不变。
  最终 cli.py / 测试 hash 为 `d793675cedc8572c907d5065d28797e287e9f72ca1f1a9e613507420c4301265` /
  `03219627d66530469ca58e5d1421c1c199431f0c3fde9ba7d0d86fe90a052199`。
  这只是 CLI delivery receipt；手写文件没有 Session 特权，DSH 当前 Session 记录与 present 硬闸尚未做。
- **537D3a（主代理复审通过）**：dsh-plugin 追加第八工具 `boardwise_review_finalize`，exit0 后从文件
  完整读取并校验 receipt（不解析截断 stdout），再以 `appendPluginRecord` 写
  `plugin:boardwise-dsh/review-finalized`；host-only `boardwiseReviewFinalized` projection 保存完整
  post-change receipts，同目录替换、异目录保留，坏 record/无关事件不授权。缺 projection 或当前 Session
  在 spawn 前失败；非零/缺/坏 receipt 均无记录。共享 transport 移入独立模块，旧七工具语义不变；
  新增三个 peer 声明，不改依赖布局或插件版本。同步守卫覆盖全部 `src/*.ts` 并单独钉住 review finalize 子命令。
  主代理独立 typecheck/test/build：**92 passed / 1 skipped**；Python 同步 **5 passed**。
  真实 Python CLI + 构建插件 + detached Session/projection 集成：4 个文件进入 ignorable record，
  完整状态可读，Session 隔离，后续非法 finalize 无 append，本棒无 pre-execute listener。
  最终 src/index/transport/review-finalize hash 分别为 `8e8a10aed0d02b24b27ebe067ab007fe00f27413c72ffe3196fb7f8224ddb93a` /
  `bbd5d3441c05794ae7ea967a83dca34beaf544c0d975e2b64cd57b69bd9b0806` /
  `417526fa886ee81210a5bb5fe9f0d41ac9313baa7acdd3a1451615c542ef0d26`；lib/review-finalize.js
  `c1e6212c7d9681f68415567f0ad9e6cb4aadf0141f46aa2be289922e333640ec`，同步测试
  `5ef81abb0b79058636a272ddc9cb60567119c2e3fd74cbaa9985ed053a7e6778`。
  未做 present 闸、真实 Session 持久化、pack/bump 或运行进程重启；当前 DSH 尚未因此获得新工具。
- **537D3b（主代理复审通过）**：boardwise 根插件注册 `tools/pre-execute`，仅拦截 present；
  以最近 review-summary.md 或当前 Session receipt root 识别审查目录，普通图片/Office/无关 report.md 直接 next。
  只消费当前 Session 的 `boardwiseReviewFinalized`，不读手写 finalize.json 当授权；无 record 的并行 present、
  其他 Session、坏 receipt、untracked（含 finalize.json 自身）均 deny。命中后对全部 tracked 文件经 ctx.fs
  复核 regular file/bytes，并以 ≤1MiB 窗口重算 SHA-256；任何一项变化、删除、读错或越界都拒绝。
  `review-finalize.ts` 仅把同一 receipt 校验函数导出复用，判定不变；inject 增 fs/workingDirectory，不改 DSH core。
  主代理独立 typecheck/test/build：**113 passed / 1 skipped**（delivery-gate 21），Python 同步 **5 passed**。
  无 record 放行变异红 5 条；补 presented 同尺寸用例后，跳过 SHA-256 恰好红 presented/non-presented 两条，
  cp+sha256 恢复。真实 CLI + listener + 文件集成：普通文件放行，手写/他 Session/untracked 拒绝，
  改未展示文件与 presented 等长改写均拒绝，重新 finalize/逐字节恢复后放行，marker 移走仍拒绝、恢复后放行。
  最终 src/index/review-finalize/review-delivery hash 为 `5ce13d6d865b4d491b43c2fecef29361ead1d2aa00a632505046a1bec64c5119` /
  `1da890b26a77193db43e03f6379489d214c71e13475fc7e65ca28caf8387c90a` /
  `238ee8108db1eeff2dfb047cd95ab59fd0f70deb8d8a2839b57e8a164056d5cd`；lib/review-delivery.js
  `50e26fe69c7e5e0d72a643ed5b4aa080a3666edbec005f8d5a65c79f90fc7b02`，测试
  `c2306c7b14592e72b39e687b208f2d86c44682464bfd2a8265374f7ab9cdc945`。
  未重启当前 DSH 或做真实 Session 持久化，故只证明源码与独立进程闸，不声称当前 GUI 已 enforcement。
- **537F（主代理复审通过）**：首棒超时后由主线冻结并审查；共享 `ResistanceReading(ohms, display, provenance)`
  只在 Value 空白且 MPN 候选唯一时恢复，非空不可读、多候选、货架已核验非电阻均不猜，未放宽全局
  `_resistor_like`。主审首跑 `test_094_sense_bias.py` **40 passed**，相邻采样/判型/ARCH/CONN/解码 **236 passed**；
  原始 `probe_bias.py` 从「没有偏置」恢复为识别分压的 INFO，闭包仍为 `R_th=10500Ω`、`V_err≈15.7µV`，
  evidence 点名 `0603WAF1001T5E`、`1001 (numeric-exponent field)` 与值码锚。主审另以零欧探针发现
  非空 `0Ω` 被新读数误排除；窄修新增测试先红 `1 failed / 40 deselected`，再把正值要求留在算术腿收集层。
  最终主线独立复跑 **41 passed**，零欧探针确认存在性保留且 arithmetic legs 为空，原始探针再次通过。
  最终 facts/archclosure/sensebias/test_094 hash 分别为
  `e52fb2d72e48a03f967f9eb26cf4bb58a1bcfadd996d7490579cc161a2a08149` /
  `9e7ebabcb7958656d6b558b43dacf7c57745fc79e828c4b4d52f7a7c30b1b697` /
  `761741632fe1c66b777dc333ebd50c543b5f33bf8fddc815506b978dded6e976` /
  `981ba52785a87f487a8baa5bd1e0c5bf09dc8ffd0d46ae12ff77e73a398e4b75`。
  未改公式、阈值、真实工程或公开夹具；全量回归留到 537E。
- **537G（主代理复审通过）**：独立 `probe_dsh_python_utf8.mjs` 修前分别证明 bash/pwsh 的
  `PYTHONUTF8` 与 `PYTHONIOENCODING` 都是 `undefined`；两个本地执行器只在其 `ENV_OVERRIDES`
  尾部增加 `PYTHONUTF8="1"`、`PYTHONIOENCODING="utf-8"`，既有合并序
  `ENV_OVERRIDES < env < dshEnv` 与 pwsh preamble 未动。主线独立 `node --check` 两个文件并复跑探针，
  两边均输出 defaults and caller precedence OK；最终 bash/pwsh hash 为
  `6e88d6d952bddb1475dee728c327b7b5b927b5d0896800f60cdb5dc93f9f3403` /
  `30346754ec370029fd807bf176a268598c03085cbe2c4d29d1526c4b0a1cb6ad`。
  未改 boardwise CLI 解码、未重启 DSH；仅证明新源码与独立 spawnSpec，不声称当前 GUI 已加载新默认值。
- **537E（主代理复审通过）**：SOP 收尾改为结构化读取 → 分诊 → environment/evidence 覆盖 →
  人工总结 → finalize → 顺序交付；明确 partial 只描述覆盖、`finalize.ok` 只校验 delivery-content、
  `report.conclusion` 是板级唯一权威，DSH present 只等当前 Session 的真实 finalize 记录。
  两份 SKILL 原位压缩并保持 320 行、逐字节一致；文档测试新增四条小节级钉。代理与主线文档/
  安装回归均 **59 passed**，两条文档变异分别红 1 / 2 并 cp+hash 还原。主线另发现写盘阶段
  「一律零写入」文案过度承诺，已改成部分同步可能存在但无新收据、不得交付。
  第一轮全量为 **7648 passed / 2 failed / 19 skipped / 5 xfailed**：旧收尾标题锚被改、
  537F 规则体指纹未记。窄修保留旧 test_069d，恢复标题并移动分段；指纹按实量记为 direct
  `cda23a06`、recursive `83d0e91c`，原因与 41 条行为锚写入 test_126a。受影响三组主线复跑
  **45 passed**；第二轮完整 Python **7650 passed / 19 skipped / 5 xfailed**（477.76s）。
  connector **536 passed** + typecheck；dsh-plugin **113 passed / 1 skipped** + typecheck + build；
  构建后 src/lib hash 与 D3 验收一致。最终 docs/review-sop.md / test_126a hash 为
  `f40faa550d7aa40a7ab30e2a2aeebf573c52d31511c4345c446998932f8027e7` /
  `32d4cf0daf747308a0e1d1a23d4c55aa78e44e161b730d93aa2d93afc442a95a`。
  过程偏差：文档代理自述在一个临时重复备份上误用一次 `rm -f`，未涉及仓库文件或用户数据；
  已如实披露，后续仍禁止直删。未重启当前 DSH/daemon，未做真机、画布或 git 写操作。
- DSH present 硬闸的实现层与限制：由 boardwise 根插件 `tools/pre-execute` 提供，不改 DSH core/present config；
  只对 review-summary.md 或当前 Session receipt root 标记的目录启用，普通交付不受影响。收据只来自真实
  finalize 工具写入的当前 Session projection，手写 finalize.json 无效；present 重算全部 tracked 哈希，
  无 record 的并行调用或任何内容变化均拒绝。当前仅源码与独立进程验收，运行中的 DSH 未重启，尚不能声称
  当前 GUI 已执行新闸；真实 Session 持久化也未在本批验证。
- 下一批入口：537 的授权项与四线回归已关闭。538 只做**独立子岛编译与局部回滚**；
  核心+卫星组内装配、岛群页级 pack、跨群连接、CH343/534 迁移、真机/画布与视觉验收仍须另批授权。
