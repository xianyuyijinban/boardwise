# 180 地旗按符号放置（178b 裁决的正面回应）+ 173C 收尾

任务编号 180。类型：两阶段（侦察门 → 实施）。178b 已裁决：`sch.place_power` 按 kind 选符号
（Ground→恒 `Ground-GND`），net 只进属性——**画布字形级的地族隔离必须走「按符号放置」**。

## 阶段一：侦察（不过门不进阶段二，结果落证据就停）

回答一个问题：repo/connector 现有哪条动作能**按库符号放置**一颗地旗 device（如
`Ground-PGND`，device uuid 在 `outputs/178/live/device_pgnd.json`），使它落在画布上是
**旗**（netflag，Global Net Name = 符号自己的地网名）而不是普通元件实例？

1. 读 `src/boardwise/bridge/protocol.py` 的 ACTIONS 找放置类动作（place_component /
   place_device / …），看 drawapply 放普通元件走哪条（`src/boardwise/engines/drawapply.py`
   的放置调用点）。
2. 真机只读先行：libprobe 确认 `Ground-PGND` device 的 uuid/symbol uuid 还在
   （`--project test` 路由）。
3. 真机写探针（test 工程 scratch 页，178b 手法：建→验→清场→删页，终态逐字节复原）：
   用该动作放一颗 `Ground-PGND`，读回（文档源/sch.geometry）确认：它是 netflag 形态、
   net 是 PGND、没有变成带位号的普通元件。
4. 如果现有动作做不到（比如只接受元件库类目、或放出来是元件），明确报告「需要新动作」
   并给出最小动作定义——**停下来等主代理裁决**，不要自己加动作。

## 阶段二：实施（阶段一过了门才做）

1. **draw 侧**：地旗放置从 `place_power(kind+net)` 改为「宿主库有 `Ground-<net>` 就按符号
   放，没有才回落 `place_power`」。每 net 的符号查询结果要缓存（一探一缓存，别每旗一探）。
   回落时必须进 `plan.notes`（观察通道，168 的规矩：不拦，但要看得见）。
2. **173C 收尾**：`engines/grammar/flyback.py:2470-2501` 的义务散文已失效（还在说
   「`gnd_flag` 让每网同 ref、画不出两族不同」）——按 178+本批的现实改写。
3. **CLI 两族检查**（主代理已裁：plan.notes 观察通道，**不上 findings 面**）：一页 ≥2
   地族而实际挂的旗同形（共享 symbolRef 或共享宿主字形）时，plan.notes 记一条
   「两族同形」观察（点名两族与回落原因），不拒、不改严重度。

## 红线

- 先读 AGENTS.md。禁 git；禁 rm（回收站通道，`.ps1` 文件法——inline 变量会被 harness
  吃掉，主代理实测）；pytest 带 `--basetemp=.tmp_pt_180`；真机写只限 test 工程 scratch 页。
- 绝不伪造 symbolHash；新放置路径的旗在计划里 symbolRef/哈希照实。
- 场景哈希变动按申报制；变异验证 ≥2（cp 备份 + sha256 还原）。
- 指纹规矩：动 `rules/**` 才重钉（本批按设计不动）。

## 验收

- 阶段一探针结论（uuid 级证据）；阶段二：PGND/SEC_GND 在 golden 页/真机 scratch 页上
  各挂各的宿主字形（Ground-PGND vs Ground-GND 可读回区分），回落路径有 notes。
- 受影响测试全绿 + 全量一次（基线 5407+23 并行 / 5408+22 串行）。
- 证据 `outputs/180/evidence.md`（append + grep -c），真机读数 `outputs/180/live/`。

## 交卷

阶段一结论（过/不过门 + 证据）/ 阶段二改动清单 / 测试计数 / 哈希申报 / 变异记录 / 遗留。
