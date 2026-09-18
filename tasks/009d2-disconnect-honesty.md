# 任务 009d2（M0-P0d follow-up）：断连路径的 persistence 谎报

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 前置阅读：`tasks/009d-persistence-baseline.md`（审计记录节）、
> `docs/persistence-baseline.md`（场景 B）。
> 来源：2026-09-18 真机四场景执行，场景 B 实证抓出。

## 现象（真机实证，非推测）

场景 B：CH340 draw 中途 `taskkill //F` 杀 daemon。结果：

- audit log 实证：`sch.doc.new` ×1、`sch.place_component` ×5 成功返回
  （daemon 死前已落 5 件到 P4 页）
- draw 报告却写：`persistence: not_placed — nothing was written — the flow
  stopped before it placed anything`

**"nothing was written" 是谎报**——5 件就在页面上。用户若信了这个报告
去重画，就是同一页两套件。这正是 P0d 要防的最危险误导。

## 根因方向（先核实再动手）

`_call_write` 只把 `timed_out` 当"状态未知"。daemon 被杀走的是**连接断开**
异常路径（`BridgeError` 非 TIMEOUT，或 transport 层的连接错误），没有被
同等对待；末端 persistence 汇总把"流程没走完"等同成"什么都没写"。

另外记录：场景 B 的退出码当时因测量伪影（管道 `$?` 抓到 tail 的码）
未取得，修复后由 Kimi 真机重测，预期非零（3 或 1，按语义定）。

## 裁决（照做，不自行改道）

1. **写入动作的连接断开 = 状态未知**，与超时同等对待：尝试读回（连接
   断了读回会失败——如实记"could not look"，不许读成"是空的"）；
   persistence 报 unknown 类（措辞照 P0d 三态的诚实风格，例如
   `unknown — N write(s) were acknowledged before the transport died`），
   **绝不许**在有任何写动作成功过之后说 `not_placed / nothing was
   written`。
2. `not_placed` 只许在**确证零写入**时使用（零个写动作被确认）。
3. 退出码：断连中断的 draw 必须非零；用语义上正确的那一个（3 =
   状态未知），并在 cli 的退出码文档处同步。
4. 该场景离线可测：mock client 在第 N 个写动作后抛连接错误，断言
   persistence 措辞含 unknown、不含 "nothing was written"、退出码 3。

## 交卷标准

- pytest（866+N）/ connector 183 / tsc 三线全绿，既有测试语义不动
  （例外逐条列出）
- 变异验证 ≥2（例：把断连路径重新映射回 not_placed → 必须咬红）
- `docs/persistence-baseline.md` 场景 B 节补一句实测记录（2026-09-18：
  5 件落页但报 not_placed，本任务修复）
- 纪律照旧：不动 git、不碰真机、全英文注释、Windows 坑、最小改动

交卷报告：根因（文件:行号）、修法、测试清单、变异记录。
