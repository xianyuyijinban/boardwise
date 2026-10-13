"""R1（v0.5.12）桥能力补齐：Python 侧可离线证的那部分。

两件动作改在 connector 里（``connector/src/actions.ts``），行为由
``connector/tests/pcb-place-component.test.mjs`` 与
``connector/tests/source-identity.test.mjs`` 钉；这里只管 daemon 这一侧：

* **R1-1 ``pcb.place_component``**——动作表登记（connector 所有、``write`` 档、
  ``pageUuid`` 必填写进 schema）、daemon 的超时预算与 ``sch.place_component``
  同档（connector 自己 30 s 截断 + 读回，daemon 必须等得过它）、daemon 在窗口写锁
  下原样转发参数与答案；
* **R1-2 ``sys.get_document_source``**——返回契约里多了 ``uuid`` / ``name`` /
  ``type``（纯增量，既有键一个不少）。

真机三件套（放→读→删）与 R1-3 / R1-4 两个侦察**不在 pytest 里**：写动作不许
因为有人碰巧开着编辑器跑全量就落到画布上。步骤在 ``outputs/R1/runbook.md``。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from boardwise.bridge.protocol import (
    ACTION_NAMES,
    ACTION_TIMEOUT,
    PLACEMENT_TIMEOUT,
    action_spec,
    decode_frame,
    describe_actions,
    request_frame,
    timeout_for,
)

REPO = Path(__file__).resolve().parents[1]
BRIDGE_DOC = REPO / "docs" / "bridge.md"


# ---------------------------------------------------------------------------
# R1-1: 动作表
# ---------------------------------------------------------------------------


def test_pcb_place_component_is_a_connector_owned_write():
    spec = action_spec("pcb.place_component")
    assert spec is not None, "pcb.place_component 不在动作表里：daemon 会在转发前回 UNKNOWN_ACTION"
    assert spec.owner == "connector", "只有编辑器里有 eda.pcb_PrimitiveComponent"
    assert spec.risk == "write", "往板上放件是写；不是 create（不新建文档），所以不走确认闸"
    assert "confirm" not in spec.params
    assert "pcb.place_component" in ACTION_NAMES
    assert describe_actions().count("pcb.place_component") == 1


def test_the_guard_and_the_resolution_ladder_are_in_the_contract():
    spec = action_spec("pcb.place_component")
    # 页防串：PCB 写动作与 pcb.delete_primitives / pcb.modify_primitive 用同一个
    # 参数名、同一个守卫（focused PCB uuid），且这一个是**必填**。
    assert spec.params[0] == "pageUuid"
    assert "required" in spec.params_schema and "pageUuid" in spec.params_schema
    # 解析梯子与 sch.place_component 同一套（connector 里是同一个函数）。
    sch = action_spec("sch.place_component")
    for key in ("lcsc", "deviceUuid", "libraryUuid", "keyword", "x", "y", "rotation", "timeoutMs"):
        assert key in spec.params, key
        assert key in sch.params, key
    assert "layer" in spec.params and "'top'" in spec.params_schema and "'bottom'" in spec.params_schema
    # 未落地时的读回是板级 id 差分，契约里必须看得见。
    assert "appeared" in spec.returns and "requested" in spec.returns and "placed" in spec.returns


def test_the_daemon_waits_out_the_connectors_own_deadline():
    """connector 截在 30 s、再读一次板；daemon 先挂断，读回就永远到不了调用方。"""
    assert timeout_for("pcb.place_component") == PLACEMENT_TIMEOUT
    assert timeout_for("pcb.place_component") == timeout_for("sch.place_component")
    assert PLACEMENT_TIMEOUT > 30.0 and PLACEMENT_TIMEOUT > ACTION_TIMEOUT


def test_the_documentation_row_says_the_guard_is_required():
    text = BRIDGE_DOC.read_text(encoding="utf-8")
    rows = [line for line in text.splitlines() if line.startswith("| `pcb.place_component` |")]
    assert len(rows) == 1, "docs/bridge.md §4 必须恰好有一行"
    row = rows[0]
    assert "| write |" in row
    assert "**required**" in row and "pageUuid" in row
    assert "landedAnyway" in row and "appeared" in row


# ---------------------------------------------------------------------------
# R1-1: daemon 转发（真 WebSocket + 假 connector，夹具与 test_174 同源）
# ---------------------------------------------------------------------------

from test_bridge import (  # noqa: E402
    FakeConnector,
    WINDOW_A,
    _daemon,
    _hello,
    _start,
    run,
)


def test_the_daemon_forwards_a_pcb_placement_verbatim(tmp_path):
    """写动作原样转发——参数不改一个字，答案不改一个字。

    daemon 按 ``spec.risk`` 分叉：非 read 走窗口写锁再 ``_forward``，非 create
    不过确认闸。这一条钉的是动作表那一行真的把这条写路接通了。
    """
    params = {
        "pageUuid": "pcb-1", "lcsc": "C25804", "x": 1000, "y": -250,
        "rotation": 90, "layer": "top",
    }
    answer = {
        "uuid": "cmp-1",
        "device": {"uuid": "dev", "libraryUuid": "lib", "name": "0603"},
        "resolvedBy": "lcsc",
        "requested": {"x": 1000, "y": -250, "rotation": 90, "layer": "top"},
        "placed": {"x": 1000, "y": -250, "rotation": 90, "layer": 1, "designator": "R1"},
        "appeared": ["cmp-1"],
        "elapsedMs": 12,
    }
    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test")
            fake = FakeConnector(a_ws, responses={"pcb.place_component": answer})
            task = asyncio.create_task(fake.serve())
            try:
                cli, _ = await _hello(port, "cli")
                await cli.send(request_frame(
                    "pcb.place_component", params, id="r", target_project="/test",
                ))
                reply = decode_frame(await asyncio.wait_for(cli.recv(), timeout=3))
                assert reply["ok"] is True, reply
                assert reply["data"] == answer
                assert fake.received[-1]["action"] == "pcb.place_component"
                assert fake.received[-1]["params"] == params
                await cli.close()
            finally:
                task.cancel()
                await a_ws.close()

    run(scenario())


# ---------------------------------------------------------------------------
# R1-2: sys.get_document_source 的返回契约
# ---------------------------------------------------------------------------


def test_the_source_read_answers_with_the_documents_identity():
    spec = action_spec("sys.get_document_source")
    returns = spec.returns.replace(" ", "")
    assert returns.startswith("{source,uuid,name,type,"), spec.returns
    # 纯增量：179 以前的键一个不少。
    for key in ("chars", "maxChars", "truncated", "data", "headLines", "tail?", "note?"):
        assert key in returns, key
    assert "notes?" in returns
    assert spec.risk == "read"
    text = BRIDGE_DOC.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| `sys.get_document_source` |"))
    assert "{source, uuid, name, type," in row
    assert "R1-2" in row
