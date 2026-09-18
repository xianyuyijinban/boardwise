# 006b — 信号网命名路径：实测结论与待裁决项

**日期**：2026-09-14
**宿主**：EasyEDA Pro `3.2.186.b52e3e87`（`user_agent` 实测，见 `~/.boardwise/audit/2026-09-14.jsonl`）
**证据来源**：`boardwise` 自有栈（`bridge call` → daemon → connector 0.3.4），不使用参考 CLI
**探针落点**：焦点在 `Start Page`（编辑器当前前台标签），故本报告只测 API 行为，不涉及图元

---

## 1. 结论摘要

| # | 待测项 | 结论 | 强度 |
|---|--------|------|------|
| 1 | `sch_PrimitiveAttribute.createNetLabel` 是否挂起 | **挂起；且什么都没落地** | 实测（带超时界） |
| 2 | 类型包内是否存在替代的信号网命名路径 | **没有** | 穷举类型包 |
| 3 | `sch_ManufactureData.getPngFile` 是否可用 | **不可用**（`NOT_IMPLEMENTED`） | 实测 |
| 4 | 编辑器版本与两个 API 的声明门槛是否自洽 | **不自洽，待 `sys.probe` 定案** | 推断 |

---

## 2. 逐项证据

### 2.1 `createNetLabel` 挂起（已证实）

调用：`sch.place_netlabel {x:100, y:100, net:"PROBE_NET", timeoutMs:6000}`

返回：

```json
{
  "code": "TIMEOUT",
  "message": "createNetLabel did not settle within 6000 ms (elapsed 6963 ms; Error: sch_PrimitiveAttribute.createNetLabel did not settle in 6000 ms); readback: nothing for PROBE_NET appeared near (100,100) — the call is unusable",
  "detail": {
    "net": "PROBE_NET",
    "x": 100,
    "y": 100,
    "elapsedMs": 6963,
    "timeoutMs": 6000,
    "landedAnyway": false,
    "matches": 0
  }
}
```

**三个要点，缺一不可**：

1. **挂起被证实**：`elapsedMs` 6963 > 6000。`Promise.race` 截断了它，**动作槽没有被吊死**——这是 006b 里 `withTimeout` 存在的全部理由。
2. **落地被证伪**：`landedAnyway: false` / `matches: 0`。排除了"超时但其实成功了"这个**更坏**的情况。参考栈的教训是"超时的调用可能已经生效，盲目重试会堆重复项"，所以只测超时是不够的，必须读回。
3. **净副作用为 0**：readback 在 (100,100) 附近找不到 `PROBE_NET`，探针没留下垃圾。

### 2.2 类型包已穷举，无替代路径

`@jlceda/pro-api-types` 里全部与网络命名相关的公开方法：

| 方法 | 声明 | 能否用于信号网 |
|------|------|----------------|
| `sch_PrimitiveAttribute.createNetLabel(x, y, net)` | **ADD since EDA v4** | 是信号网的唯一入口，**在 3.2.186 上挂起** |
| `sch_PrimitiveComponent.createNetFlag(identification, net, x, y, …)` | 已存在 | **不能**：`identification` 只有 `Power / Ground / AnalogGround / ProtectGround` 四个值 |
| `sch_PrimitiveNetLabel.*` | **命名空间不存在** | —（004 侦察已记录；`sch.geometry` 的 `meta.available.netlabels` 实测 `false`） |

**`createNetLabel` 的文档门槛是 "ADD since EDA v4"，宿主是 v3.2 线。** 所以它在 3.2.186 上不是"有时挂起"，而是**根本在被调用的那一刻就注定失败**——而且失败形态是挂起，不是干净报错。`sch.place_netlabel` 的超时保护把这个坑变成了可报告的失败，这是它唯一正确的行为。

### 2.3 `getPngFile` 不可用（已证实）

调用：`export.render {width:200, height:200}`

```json
{ "code": "NOT_IMPLEMENTED",
  "message": "sch_ManufactureData.getPngFile() is not available on this editor build",
  "detail": { "path": "sch_ManufactureData.getPngFile" } }
```

`detail.path` 是 `sch_ManufactureData.getPngFile`（带方法名），说明是 **`exportRender` 自己的 "method missing" 分支**抛的，不是 `namespaceOf` 的 "namespace missing" 分支 —— 即：**命名空间拿得到，方法不在**。

对照：`export.screenshot`（旧 API，走 `getCurrentRenderedAreaImage`）**可用**，返回 80820 B 的 PNG。

`getPngFile` 的文档门槛是 **ADD since EDA v3.2.183**，宿主 3.2.186 **应当包含**。这一条与 2.2 的机制**不一致**，需要 `sys.probe` 的成员枚举才能定案（可能：该 build 的分支号落后于官宣；或方法名有差异）。

---

## 3. 待岳翔宇裁决（任务书要求：不静默降级）

任务书原文：

> **net-label path with evidence first** … **if confirmed no path, come back with evidence for 岳翔宇 to rule — never silently fall back to ports**

现状：**信号网命名在本宿主上无可用 API 路径**（2.1 挂起 + 2.2 无替代），所以到了必须裁决的点。可选方向：

| 方案 | 含义 | 代价 |
|------|------|------|
| **A. 接受无信号网名** | 回放黄金几何，但信号网**不命名**（导线画出，无 label）。连通性仍由 `connectivity` 验证（靠几何接触），但**读图的人看不出网名** | 可读性受损；违反"信号网用 net 标签"这条规则的字面要求 |
| **B. 用端口（违令）** | 退回 `sch.place_netport` | **违反岳翔宇的最高优先级规则**，除非他本人改口 |
| **C. 等 v4 宿主** | 本任务只做可做部分，命名留到编辑器升到 v4 | 006b 的"可读"闸门无法完整达成 |
| **D. 逐网裁决** | 关键网（如 USB D+/D-、晶振）特事特办 | 需要他指定哪些网必须有名 |

**我的建议是 A + D 的组合**，但这是他的决定。

---

## 4. 后续动作（等 daemon 重启 + 0.3.5 侧载）

`sys.probe` 是本次新增的**只读**诊断动作（`connector/src/actions.ts` → `sysProbe`），用途是把上表第 4 行的"不自洽"彻底定案：

```
boardwise bridge call --action sys.probe --params '{"namespaces":["sch_ManufactureData","sch_PrimitiveAttribute","sch_PrimitiveNetLabel"]}'
```

它会返回：
- 编辑器版本（`sys_Environment.getEditorCurrentVersion(true)`）；
- `eda` 顶层绑定的命名空间全名单；
- 每个请求命名空间的**真实成员名**（走原型链枚举，`Object.keys` 在类实例上返回空）。

拿到 `sch_ManufactureData` 的成员表，就能回答：`getPngFile` 是**不存在**还是**改名了**，以及 `getSvgFile` 在不在（它俩是同一批 3.2.183 加的，一起看能判断是不是整批缺失）。
