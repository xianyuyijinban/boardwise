# 任务 010b：place_wire 在 netlist 探针后的锁窗内必败 —— connector 侧有界重试

> 执行者：DeepSeek。工作目录：`E:\boardwise`。
> 触发：010（AMS1117 手工几何）真机验收两次确定性失败 —— 10 根导线全部
> `create failed!`，器件与旗标正常。根因已用探针钉死（见下），本任务只做
> 修复与验证，**不要再调查根因**。

## 实测证据（2026-09-18，宿主 3.2.186，pro-api 0.3.18，connector 0.4.4）

1. **触发窗**：`bridge call --action sch.netlist` 返回后的数秒内，
   `sch_PrimitiveWire.create` **同步抛** "create failed!"（约 1-3ms 即拒）。
   同一参数在探针之前、之后 ~5s 都成功。窗口在 +5s 前已关闭。
2. **draw 流的暴露路径**：器件放完 → 放置校验（`sch.doc.save` +
   `sch.netlist`，见 `engines/draw.py`）→ 立刻连发 10 根 `sch.place_wire`
   （每根间隔毫秒级）→ 全部撞进窗口，全部失败。随后 `place_power` 每颗
   1.4-3.0s（`createNetFlag` 内部要取库），天然熬过窗口，成功。
3. **为什么以前没炸**：空几何块路径（场景 D）是**先旗标后短线**，
   慢速旗标把窗口磨没了；CH340 黄金回放成功记录早于放置校验的引入。
   带几何块是**先线后旗**，第一次正面撞上。
4. 审计时间线（`~/.boardwise/audit/2026-09-18.jsonl`）：
   `place_component ×3 OK → doc.save 46ms → netlist 4933ms →
   place_wire ×10 BAD (1-2ms each) → place_power ×3 OK`。
5. 已排除：参数形态（坐标对/扁平/浮点/3 点）、`net` 参数有无、
   网是否已存在、`pageUuid` 指向、全新页、器件放置后的瞬时状态 ——
   逐一探针全部成功。**唯一触发条件是 netlist 探针后的时间窗**。
6. 未隔离：`doc.save` 是否也贡献锁窗（draw 序列里 save 在 netlist 前）。
   修复时顺手各测一次（save 后放线 / netlist 后放线），把结论写进注释。

## 修复要求

**主修复（connector，`connector/src/actions.ts::schPlaceWire`）**：

- 对 `"create failed!"` 这一**确定的抛错形状**做有界重试：建议间隔
  ~500ms、总预算 ≤10s（须小于 daemon 的 `ACTION_TIMEOUT` 30s）。
- 只重试这个形状；`BAD_REQUEST` 等参数错误必须立刻抛，不得重试。
- 重试耗尽后抛 `CONNECTOR_ERROR`，消息里带**尝试次数与耗时**——
  不许只丢一句 "create failed!"。
- 注释写明实测出处（本条第 1、4 点），格式对齐文件里既有的
  "measured YYYY-MM-DD" 注释风格。

** sibling 审计（同一函数族，范围从严）**：
`schPlaceNetlabel` / `schPlaceText` / `schPlaceNetport` / `schPlacePower`
—— 真机各探一次"netlist 探针后立即调用"。失败的同样加重试；不失败的
**不加**，并在注释里记下"实测不受锁窗影响"。不做预防性重构。

**不改**：`engines/draw.py` 的调用顺序（放置校验本来就是为了在布线前
拦住漂移件，不许为了绕开窗把它挪后）；不加新的 daemon 动作。

## 验收

离线：

1. connector `npm test` 新增：假 eda 前 N 次抛 "create failed!" 第 N+1 次
   成功 ⇒ 动作成功且返回 uuid；永远抛 ⇒ `CONNECTOR_ERROR` 且消息含尝试
   次数；参数错误 ⇒ 不重试、原样抛。
2. `npm test` 与 `tsc --noEmit` 全绿；`pytest -q` 全绿（903 基线，
   本任务不应触碰 Python 侧测试）。

真机（交卷后由 Kimi 执行，你不用跑）：

3. connector 版本 0.4.4 → 0.4.5，构建 eext，`bridge update-connector --yes`
   热更（此闭环已验证过可用）。
4. `draw --spec blocklib/specs/ams1117_smoke.json` → 10 根线全部落页，
   exit 0，render 出图。

## 纪律

- 不动 git、不重启 daemon（本任务不需要 daemon 变更）。
- 代码与注释全英文。
- 变异验证：把重试条件改成"只试一次"，新增的假 eda 测试必须变红。

---

## 交付后实测补记（Kimi，2026-09-18 晚）

**sibling 审计结果**（每次调用前重打一次 `sch.netlist`，立即调用）：

| 动作 | 结果 | 处置 |
|---|---|---|
| `place_netlabel` | TIMEOUT（8s，createNetLabel 不 settle） | **不加** —— 这是已记录的独立挂起（draw 流本来就绕开它，用 text/netport），无法归因于锁窗 |
| `place_text` | 409ms 成功 | 不加 —— 实测不受锁窗影响 |
| `place_netport` | 1864ms 成功 | 不加 —— 变慢但成功 |
| `place_power` | 1137ms 成功 | 不加 —— 成功（上次靠的是慢，这次实测直接证明不受拒） |

结论：只有 `place_wire` 需要重试，与修复范围一致。

**符号 y 翻转警报（DeepSeek 在交卷时提出）——判定为误报**。真机双重探针：
P9 的 U1（真实位号 U13）上，画布 (530,420) 的探针线 → 网表 pin 1 GND；
(530,400) → pin 3 VIN 挂 +5V。与块 JSON 的文件系声明完全一致，010 布局
电气正确。渲染图上文本顺序（1/GND 在上、3/VIN 在下）与电气端点相反，
是库符号文本偏移或导出渲染器的表面现象，留作 M2 打磨期的开放问题
（需 GUI 画布对比，不属于本任务）。教训值得记下：**离线测试只按块自己
声明的 offsets 自检，符号几何与库的一致性只有真机能验**。
