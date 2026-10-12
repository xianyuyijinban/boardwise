"""任务 174：桥接 ``pcb.geometry`` 只读动作 —— 三段接通（connector / protocol / cli）。

背景：172 把丝印字宽的「宿主实测优先」管线全接好了，缺的就是**桥上的动作本体**。
172 当时只能借原理图侧的 ``sch.geometry``（挂在 ``sch_Primitive`` 上）去量 PCB 的
位号 ATTR id，那是个凑合：宿主里真正对口的 API 是
``eda.pcb_Primitive.getPrimitivesBBox``（easyeda-agent 的 ``pcbSilkAlign`` 就是用它
量每条位号 ATTR 的），没人包。本批把它包成 ``pcb.geometry``：

* **connector 段**（``connector/src/actions.ts``）——只读实现，一个 id 一次调用
  （宿主对一串 id 只答**并集**盒），量不到的 id 进 ``meta.unreadable`` 并带原因；
  测试在 ``connector/tests/pcb-geometry.test.mjs``（假 eda，离线）；
* **protocol 段**（``src/boardwise/bridge/protocol.py``）——动作表登记，
  ``risk="read"``、``owner="connector"``，返回形状与 ``sch.geometry`` 的 ``bboxes``
  同构；daemon 不需要改路由（read 动作照常转发，不加写锁）；
* **接线段**（``src/boardwise/cli.py``）——``SILK_BBOX_ACTION`` 由 ``sch.geometry``
  换成 ``pcb.geometry``，172 钉的那条链路（``doc.list`` → 档里 ATTR id → bbox 动作）
  从此量的是**这条板上真的位号文字盒**。

本文件只管 Python 侧可离线证的那部分：动作表的形状、daemon 真的把它转发出去、
cli 与它的 join 形状。真机探针在最后，窗口不在就 skip。
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from boardwise import cli as cli_module
from boardwise.bridge.protocol import (
    ACTION_NAMES,
    ACTIONS,
    ErrorCodes,
    action_spec,
    describe_actions,
)
from boardwise.bridge.protocol import decode_frame, request_frame

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
FOC_100 = FIXTURES / "ProPrj_毕设FOC驱动板_v1.0.0_2026-10-07.epro2"

#: 岳 2026-10-12 给的 test 工程（任务书点名）。真机探针只碰这一个，只读。
#: 按**工程名**路由（`--project`），不硬编码窗口 instance id：任何一次
#: 热更/reload 后 instance id 都会变（2026-10-12 实测 0.4.29→0.4.30 后
#: inst-110614866-3i116ex4 已不存在），硬编码只会让探针假 skip。test 工程
#: 只有一个窗口开着，按名路由无歧义。
TEST_PROJECT = "test"


# ---------------------------------------------------------------------------
# 1. 动作表：形状与 sch.geometry 的 bbox 半边同构
# ---------------------------------------------------------------------------


def test_the_action_is_registered_as_a_connector_owned_read():
    spec = action_spec("pcb.geometry")
    assert spec is not None, "pcb.geometry 不在动作表里 —— 172 的接线就无从谈起"
    assert spec.risk == "read", "量一个包围盒不改任何字节，read 是它唯一诚实的档"
    assert spec.owner == "connector", "只有编辑器里有 eda.pcb_Primitive"
    assert list(spec.params) == ["bboxIds"]
    assert "pcb.geometry" in ACTION_NAMES


def test_the_return_contract_is_isomorphic_with_sch_geometrys_bbox_half():
    """两边的 ``bboxes`` 键必须是**同一个形状**：调用方（172）读的就是它。

    ``pcb.geometry`` 存在的理由就是替换 172 借用 ``sch.geometry`` 的那一段，所以
    「同一个键、同一个四元组」不是审美问题——172 的 join 代码只有一套。
    """
    sch = action_spec("sch.geometry")
    pcb = action_spec("pcb.geometry")
    for spec in (sch, pcb):
        assert "bboxes: {primitiveId: {minX,minY,maxX,maxY}}" in spec.returns, spec.name


def test_the_rendered_table_shows_it_once_with_its_risk():
    rendered = describe_actions()
    assert "pcb.geometry" in rendered
    assert rendered.count("pcb.geometry") == 1


def test_a_read_action_declares_no_confirm():
    assert "confirm" not in action_spec("pcb.geometry").params
    assert ErrorCodes.CONFIRMATION_REQUIRED  # 确认闸对 read 根本不适用


def test_every_catalogue_entry_still_has_a_name_the_daemon_can_route():
    """登记进来的动作必须是「daemon 认得、connector 有」的那种名字。

    ``connector/tests/contract-drift.test.mjs`` 管两侧集合相等；这一条只管本次
    新增的这一个确实落在两侧共同的命名域里（``domain.verb``）。
    """
    names = {action.name for action in ACTIONS}
    assert "pcb.geometry" in names
    assert "sch.geometry" in names


# ---------------------------------------------------------------------------
# 2. daemon：read 动作照常转发，加的是新名字，不是新路径
# ---------------------------------------------------------------------------

# `test_bridge` 的 daemon 夹具（真 WebSocket + 假 connector）。跨文件复用是刻意的：
# 再写一套假 daemon 就会有两套「转发」语义，其中一套迟早和真 daemon 不一致。
from test_bridge import (  # noqa: E402
    FakeConnector,
    WINDOW_A,
    _daemon,
    _hello,
    _start,
    run,
)


def test_the_daemon_forwards_pcb_geometry_to_the_window_untouched(tmp_path):
    """动作表登记之后，daemon 就把它当普通 read 转发——参数原样、答案原样。

    「daemon 路由要不要改」这个问题的答案就在这里：不要。它按 ``spec.risk`` 分叉，
    read 不加写锁、直接 ``_forward``；所以新增只读动作的全部 daemon 侧工作就是
    在动作表里写一行，而这一条钉的是那一行真的接通了。
    """
    box = {"bboxes": {"attr-1": {"minX": 1, "minY": 2, "maxX": 3, "maxY": 4}},
           "meta": {"available": {"bboxes": True}, "requested": 1, "measured": 1}}

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test")
            fake = FakeConnector(a_ws, responses={"pcb.geometry": box})
            task = asyncio.create_task(fake.serve())
            try:
                cli, _ = await _hello(port, "cli")
                await cli.send(request_frame(
                    "pcb.geometry", {"bboxIds": ["attr-1"]}, id="r",
                    target_project="/test",
                ))
                reply = decode_frame(await asyncio.wait_for(cli.recv(), timeout=3))
                assert reply["ok"] is True and reply["data"] == box
                # The connector saw the action and the params verbatim: the CLI's
                # shape (`{"bboxIds": [...]}`) is the connector handler's contract,
                # and a daemon that rewrote it would break 172's join silently.
                assert fake.received[-1]["action"] == "pcb.geometry"
                assert fake.received[-1]["params"] == {"bboxIds": ["attr-1"]}
                await cli.close()
            finally:
                task.cancel()
                await a_ws.close()

    run(scenario())


def test_the_daemon_refuses_a_pcb_geometry_nobody_declared(tmp_path):
    """正控：同一个 socket 上，没登记的名字必须被 daemon 直接拒。

    没有这一条，「转发成功」也可以读成「daemon 什么都转发」。
    """

    async def scenario():
        daemon = _daemon(tmp_path)
        server, port = await _start(daemon)
        async with server:
            a_ws, _ = await _hello(port, "connector", token="t", instanceId=WINDOW_A,
                                   projectName="/test")
            fake = FakeConnector(a_ws, responses={})
            task = asyncio.create_task(fake.serve())
            try:
                cli, _ = await _hello(port, "cli")
                await cli.send(request_frame(
                    "pcb.geometry_gone", {}, id="r", target_project="/test",
                ))
                reply = decode_frame(await asyncio.wait_for(cli.recv(), timeout=3))
                assert reply["ok"] is False
                assert reply["error"]["code"] == ErrorCodes.UNKNOWN_ACTION
                assert fake.received == [], "nothing may reach the editor"
                await cli.close()
            finally:
                task.cancel()
                await a_ws.close()

    run(scenario())


# ---------------------------------------------------------------------------
# 3. cli 接线：SILK_BBOX_ACTION 换真值，join 形状不变
# ---------------------------------------------------------------------------


def test_the_silk_wiring_now_asks_the_pcb_action():
    assert cli_module.SILK_BBOX_ACTION == "pcb.geometry"
    assert cli_module.SILK_BBOX_ACTION in ACTION_NAMES, "接线指向的动作必须在动作表里"


def _fake_host(answers: dict, seen: list):
    async def call(action, params):
        seen.append((action, params))
        key = (action, json.dumps(params, sort_keys=True))
        if key in answers:
            value = answers[key]
            if isinstance(value, Exception):
                raise value
            return value
        raise AssertionError(f"the test host was not given an answer for {key}")

    return call


def _focused_pcb_of(archive: Path):
    from boardwise.parsers.epru import load_epro2_source

    source = load_epro2_source(archive)
    document = source.documents_of_type("PCB")[0]
    attr = next(
        record for record in document.records
        if record.type == "ATTR" and (record.body or {}).get("key") == "Designator"
    )
    return document, attr


def _doc_list_payload(uuid: str, name: str) -> dict:
    return {
        "active": {"uuid": uuid, "type": "pcb"},
        "documents": [
            {"uuid": "sch-1", "name": "schematic1", "type": "schematic"},
            {"uuid": uuid, "name": name, "type": "pcb"},
        ],
        "pcbs": 1,
    }


def _designator_ids(document) -> list[str]:
    return sorted(
        str(r.id) for r in document.records
        if r.type == "ATTR" and (r.body or {}).get("key") == "Designator" and r.id
    )


def test_the_pcb_answer_is_joined_by_primitive_id_and_becomes_a_measurement():
    document, attr = _focused_pcb_of(FOC_100)
    designator = str(attr.body["value"])
    seen: list = []
    host = _fake_host(
        {
            ("doc.list", "{}"): _doc_list_payload(document.uuid, "PCB1"),
            ("pcb.geometry", json.dumps(
                {"bboxIds": _designator_ids(document)}, sort_keys=True
            )): {
                "bboxes": {str(attr.id): {"minX": 10, "minY": 20, "maxX": 40, "maxY": 60}},
                "meta": {"available": {"bboxes": True}, "requested": 1, "measured": 1},
            },
        },
        seen,
    )
    notes: list[str] = []
    measured = asyncio.run(cli_module._measure_silk_boxes(host, FOC_100, notes))
    assert measured == {("PCB1", designator): (10.0, 20.0, 40.0, 60.0)}
    assert [action for action, _ in seen] == ["doc.list", "pcb.geometry"]


def test_an_unreadable_id_in_the_answer_does_not_lose_the_readable_ones():
    """``meta.unreadable`` 是背景说明，不是「整条读数作废」。

    量到一条就是一条实测——这正是 172 要的两态分明：报告里那句「宿主实测 N 条」
    必须数的是真量到的数。
    """
    document, attr = _focused_pcb_of(FOC_100)
    designator = str(attr.body["value"])
    host = _fake_host(
        {
            ("doc.list", "{}"): _doc_list_payload(document.uuid, "PCB1"),
            ("pcb.geometry", json.dumps(
                {"bboxIds": _designator_ids(document)}, sort_keys=True
            )): {
                "bboxes": {str(attr.id): {"minX": 1, "minY": 1, "maxX": 2, "maxY": 2}},
                "meta": {
                    "available": {"bboxes": True},
                    "requested": 2,
                    "measured": 1,
                    "unreadable": ["attr-nowhere: the host returned no box for this id"],
                },
            },
        },
        [],
    )
    notes: list[str] = []
    measured = asyncio.run(cli_module._measure_silk_boxes(host, FOC_100, notes))
    assert measured == {("PCB1", designator): (1.0, 1.0, 2.0, 2.0)}
    assert any("宿主实测" in note and "1 条位号文字盒" in note for note in notes)


def test_an_action_that_is_not_on_this_daemon_degrades_and_names_the_action():
    """旧 daemon（动作表是加载期常量）→ UNKNOWN_ACTION，降级照旧、且点名动作。

    这是 174 换常量之后真实存在的失败模式：动作没生效时，172 的降级路径必须仍然
    说得清楚**是谁**没给出读数。
    """
    from boardwise.bridge.protocol import BridgeError

    document, _attr = _focused_pcb_of(FOC_100)

    async def call(action, params):
        if action == "doc.list":
            return _doc_list_payload(document.uuid, "PCB1")
        raise BridgeError(ErrorCodes.UNKNOWN_ACTION, "unknown action 'pcb.geometry'")

    notes: list[str] = []
    assert asyncio.run(cli_module._measure_silk_boxes(call, FOC_100, notes)) == {}
    assert any(
        "丝印字宽降级" in note and "pcb.geometry" in note and "估算值" in note
        for note in notes
    ), notes


def test_a_payload_without_a_bbox_map_degrades_instead_of_faking_a_table():
    """宿主答了、但 ``bboxes`` 不是表 → 空表 + 降级句（绝不出半个读数）。"""
    document, _attr = _focused_pcb_of(FOC_100)

    async def call(action, params):
        if action == "doc.list":
            return _doc_list_payload(document.uuid, "PCB1")
        return {"meta": {"available": {"bboxes": False}}}

    notes: list[str] = []
    assert asyncio.run(cli_module._measure_silk_boxes(call, FOC_100, notes)) == {}
    assert any("丝印字宽降级" in note and "估算值" in note for note in notes)


def test_a_box_with_missing_corners_is_not_a_reading():
    """四元组缺角（或不是数）的盒子不许进表——它会让叠加深度算成假的。"""
    document, attr = _focused_pcb_of(FOC_100)
    host = _fake_host(
        {
            ("doc.list", "{}"): _doc_list_payload(document.uuid, "PCB1"),
            ("pcb.geometry", json.dumps(
                {"bboxIds": _designator_ids(document)}, sort_keys=True
            )): {"bboxes": {str(attr.id): {"minX": 1, "minY": 2}}},
        },
        [],
    )
    notes: list[str] = []
    assert asyncio.run(cli_module._measure_silk_boxes(host, FOC_100, notes)) == {}
    assert any("丝印字宽降级" in note for note in notes)


# ---------------------------------------------------------------------------
# 4. 真机 —— 只读；窗口不在 / 焦点不对就 skip，绝不写
# ---------------------------------------------------------------------------


def _bridge_call(action: str, params: dict, *, timeout: int = 60):
    """真机只读调用（子进程走 CLI，和人在终端敲的是同一条路）。"""
    env = dict(os.environ)
    env.pop("BOARDWISE_NO_AUTO_DAEMON", None)
    proc = subprocess.run(
        [
            sys.executable, "-m", "boardwise.cli", "bridge", "call",
            "--action", action, "--project", TEST_PROJECT,
            "--params", json.dumps(params),
        ],
        cwd=REPO, capture_output=True, timeout=timeout, env=env,
        # UTF-8 explicitly: the CLI prints its payload with `ensure_ascii=False`,
        # so a host message in Chinese (measured: `sch.geometry`'s reasons carry
        # 「获取所有器件失败」) is UTF-8 on the pipe while this process's locale
        # is GBK — decoding by locale loses the whole frame to a reader-thread
        # exception and turns a good read into `stdout is None`.
        encoding="utf-8", errors="replace",
    )
    if proc.returncode == 0:
        return json.loads(proc.stdout), ""
    return None, (proc.stdout + proc.stderr).strip()


def _live_window():
    """R1 身份：任务书点名的窗口 + 焦点工程逐字对得上，否则 skip。"""
    listing, why = _bridge_call("doc.list", {})
    if listing is None:
        pytest.skip(f"test 工程窗口不在线（`bridge call doc.list` 失败：{why[:200]}）")
    focused = next(
        (p for p in (listing.get("projects") or [])
         if isinstance(p, dict) and p.get("focused")),
        None,
    )
    name = str((focused or {}).get("friendlyName") or (focused or {}).get("name") or "")
    name = name.lstrip("/")
    if name != TEST_PROJECT:
        pytest.skip(
            f"焦点工程是 {name!r}，不是任务书点名的 {TEST_PROJECT!r} —— "
            f"不动它（R1：身份不符就停）"
        )
    return listing


def test_live_pcb_geometry_answers_emptily_or_with_a_legal_refusal():
    """真机只读（窗口不在/焦点不对就 skip）：``pcb.geometry`` 不许崩。

    2026-10-12 实测：daemon 重启后认得这个动作（动作表是加载期常量），但它被转发
    到编辑器里跑的 connector 包时，0.4.29 那个 bundle 里**没有**本批新加的 handler，
    于是回来的是一条 ``UNKNOWN_ACTION``（``connector has no handler for
    pcb.geometry``）——合法的拒绝，不是崩。探针同时接受两种结局：

    * 运行中的 connector 已带 174 的 handler → 空板 ``PCB1`` 上量不到位号，回
      ``{bboxes: {}, meta: {…}}``（本批真机这一态只能这样，板上一片元件都没有）；
    * 还是旧 bundle → 结构化错误帧（合法拒绝），CLI 退出 1、无栈回溯。

    两条都钉「回答是一个帧」这件事：读一个不存在的 id 不许把 daemon 或 connector
    弄翻。**不写**：这条探针一个写动作都不发。
    """
    _live_window()
    payload, why = _bridge_call("pcb.geometry", {"bboxIds": ["174-no-such-primitive"]})
    if payload is None:
        # 合法拒绝：CLI 把 code 打在人读的那一行上
        assert "[UNKNOWN_ACTION]" in why or "[CONNECTOR_ERROR]" in why or "[NOT_IMPLEMENTED]" in why, why
        assert "Traceback" not in why, why
        return
    assert isinstance(payload.get("bboxes"), dict), payload
    assert payload["bboxes"] == {}, "空板上没有可量的图元：表必须是空的，不许编"
    meta = payload.get("meta") or {}
    assert meta.get("available", {}).get("bboxes") is True, meta
    assert meta.get("requested") == 1
    assert meta.get("measured") == 0
    # 量不到的那个 id 必须被点名，而不是悄悄少一行
    assert any("174-no-such-primitive" in line for line in (meta.get("unreadable") or [])), meta


def test_live_sch_geometry_still_answers_the_bbox_half():
    """回归：``sch.geometry`` 那条 bbox 链路（172 借用的那段）没有被本批碰坏。

    2026-10-12 实测：``test`` 窗口的焦点是 ``PCB1``（pcb 文档），原理图命名空间在
    PCB 画布上本来就不可用，所以 ``bboxes`` 为空、``meta.available`` 逐项写明理由
    ——这正是「读不到≠没有」的那个形状。要点是**动作活着、帧形状没变**。
    """
    listing = _live_window()
    payload, why = _bridge_call("sch.geometry", {})
    if payload is None:
        pytest.skip(f"sch.geometry 在 test 窗口上没答上来（{why[:200]}）")
    for key in ("components", "wires", "pins", "netlabels", "bboxes", "meta"):
        assert key in payload, f"sch.geometry 的帧形状变了：缺 {key}"
    assert isinstance(payload["bboxes"], dict)
    # 焦点若是 pcb，理由必须逐条写明，而不是一个空 meta
    active = listing.get("active") or {}
    if str(active.get("type") or "") == "pcb":
        available = (payload.get("meta") or {}).get("available") or {}
        assert available.get("bboxes") is False, "PCB 画布上没有 sch 图元可量"
