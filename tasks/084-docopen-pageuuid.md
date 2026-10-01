# 084 — #44：doc.open 分类对齐 + 三个放置动作目录补 pageUuid

来源：GitHub issue #44（084 重写版正文即规格，分析结论全部核实过，直接照做）。
纯 Python 批：**不碰 connector TS、不碰 dsh-plugin**。

## 改动（全部在 `src/boardwise/bridge/protocol.py`，另加测试）

1. **`doc.open` risk read→write**：:979 附近 `risk="read"` → `risk="write"`（只改 doc.open 这一条 Action）。
2. **三个 Action 的 params 补 `"pageUuid"`，params_schema 补一句**（措辞对齐同文件 :699-700 `sch.place_netlabel` 的写法："pageUuid: refuse to write unless the focused page matches"）：
   - :683 `sch.place_wire`：`params=("points", "net")` → `("points", "net", "pageUuid")`；params_schema 现有句子后追加 pageUuid 说明。
   - :723 `sch.place_power`：`("kind","net","x","y","rotation","mirror")` → 追加 `"pageUuid"`；params_schema 同理。
   - :735 `sch.place_netport`：`("direction","net","x","y","rotation","mirror")` → 追加 `"pageUuid"`；params_schema 同理。
3. **注释对齐**：:202-205 的 risk 字段注释——`read` 定义里现把 `doc.open` 当范例（"so does ``doc.open``, which changes the editor's active document but not a single byte of what the project contains"）。重写这段：read 保留「不能改变工程内容」的判据；**write 定义补一句**：焦点变更（doc.open / doc.focus）决定放置动作的落点页，归入 write。:300 附近（sys.identity summary 里提到 doc.open 的历史叙事）不动。
4. **测试**：`tests/test_action_catalogue.py` 增补（风格跟随文件内 :122-125 一带的 ACTIONS 遍历断言）：
   - `sch.place_wire` / `sch.place_power` / `sch.place_netport` 三个动作的 params 都含 `"pageUuid"`；
   - `doc.open` 的 risk == `"write"`；
   - `doc.open` 与 `doc.focus` 的 risk 相同。

## 验收

- 跑：`cd E:/boardwise && .venv/Scripts/python.exe -m pytest tests/test_action_catalogue.py -q --basetemp=.tmp_pt_home_agent084`（**必须用这个 basetemp**，`.tmp_pt_home` 是主代理全量专用的，撞车会互相清目录）。全绿。
- `git status` 只应见：protocol.py、test_action_catalogue.py、tasks/084-docopen-pageuuid.md。
- **不 commit、不 push、不写 PROGRESS.md**（主代理收口）。

## 边界（不做）

- guardPage 缺省静默放行是有意设计（actions.ts:2259-2264 注释），不改 TS。
- cli.py 条件传参（:15950 / :15984）与前置守卫（:15732-15746）保持现状。
- daemon.py 锁逻辑与 `_gate_confirmation` 不动（已核实确认闸只对 risk=="create" 生效，本次 flip 不触发）。
- 若发现 test_action_catalogue.py 里有别的断言因 params/risk 变化而红（例如对 params 清单做快照的测试），先读懂该断言的意图再对齐，不许为绿而删断言。
