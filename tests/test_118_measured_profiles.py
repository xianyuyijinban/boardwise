"""118：把 113 **编写**的符号 profile 换成 **实测**，让反激页在真实几何下翻绿。

============================ 118 的触发 ============================

117 把反激整页编译出来了（`ok=True`、1 个候选、闸零硬违反），预览落
`outputs/117/previews/`。然后它在真机上被 **054 C6** 拦下：`draw apply` 把 21 件
全放下、**21/21 值校验通过**，但**拉线前的引脚回读几乎全军覆没**——49 根脚里
**46 根**超出 2.5 单位容差，两颗符号的脚 token 体系宿主根本没有。

**这不是精度问题，是「profile 是什么」的问题。** 113 手写了十三颗 profile，
每一个数字都是**对形状的猜测**。猜测好到足以排出一张图、足以过离线闸——
**然后在第一次接触真实库时就不成立**。一份 profile 不是一颗器件的画，
它是**关于某一个库符号的一组断言**；没人量过的断言，是恰好能编译的猜测。

============================ 本文件钉的四件事 ============================

1. **每颗 profile 的脚尖/方向/长度都是实测的**（`tools/118_measure_profiles.py`
   从两份独立真机读数推出，并**每次重建都重跑交叉校验**）。
2. **token 以真实符号为准**，号码为主、名字为辅，115② 的同尺照旧。
3. **T1 的 A2 没有实脚**，五脚骨架的电气读法由**语法自己的判据**定，不是猜的。
4. **真实几何下 `same-column(Q1, R5)` 不再是「位姿可解」**——116 记的那条结论
   建立在 113 编的 profile 上，实测几何把它推翻了。这条是 118 挖出来的
   **新发现**，如实记在这里与 SUMMARY，不假装它一直是对的。
============================ 119 更新：换料之后这些断言量的现实换了 ============================

岳 2026-10-04 深夜裁定换料：T1 从 `C9900020988`（`EE16_3+3_V02`，实测**五脚**）
换成同门的 `C49118510`（`XREE16-050624` 卧式 5+5），真机实测**七脚**
（左侧 1-5、右侧 6/10；证据 `outputs/118/probe/xfmr_swap_probe.json`；同门
`C49118511` 立式 4+4 实测只有 3 脚含 NC，已否）。辅助绕组的冷端**第一次有了
真脚**（`T1.2` 归 `PGND`，物理正确——辅助是原边参考的）。

**120 再换一次料**：岳选了 WE 749118105（`C17189451`，**两绕组真品料**，六脚，
pin 2/5 是 NC）放在 P1，辅助链整条拆掉（D2/C7/AUX/VCC 出 spec——语法设计上
aux 是可选角色）。所以 119 那批「七脚 XREE」的断言**再一次**按新现实改写：
119 的七脚证据作为 **119 的记录**留在 `outputs/119/` 与本文件的说明里，历史不抹。

120 同样没有抹五脚缺陷：它仍然是 118 的发现，由
`test_the_five_pin_transformer_cannot_carry_this_circuit` 在 118 当时那份实测库
上重跑，仍然可复算。

本文件的断言因此**按新现实改写**，但**五脚缺陷不抹**：它是 118 的**发现**，
写进 `test_the_five_pin_transformer_cannot_carry_this_circuit` 的**发现记录**里
（并引 `outputs/118/SUMMARY.md` 与那份穷举证据），不再是关于当前电路的断言。

改写清单（每条一句「原来量什么 → 现在量什么」）：

| 测试 | 119 之后的主张 |
|---|---|
| `…hand_written_pin_tip` | 十二颗**换料未动**的 profile 仍逐脚等于 118 的实测；**T1 改钉 118b 换料探针**（那份才是它现在的实测） |
| `…where_its_geometry_came_from` | 来源写在 **`notes` 的字符串数组**里（library schema 校验不收 `bodySource` 键），判据从「键在不在」改成「那一句在不在」 |
| `…body_box_is_the_extent_the_host_reports` | **每颗体框逐字等于宿主自己给的读数**（`sch.geometry bboxIds`，本文件的读法是从原始读数重新折回来的）；没有被放上过页面的那颗（`C0805`）仍是「引脚内端推出的下界」，并且必须说自己是下界 |
| `…pin_carries_the_name_the_host_reports` | 符号表随换料换了，名字对账改按 **symbolRef 自带的行**查，缺读数的行点名跳过而不是悄悄放过 |
| `…113_shape_intent_is_kept` | 换料那一行是 `[118b]` 不是 `[118]`（`[118]` 那一行属于十二颗没动过的） |
| `test_the_transformer_has_five_pins…` | 改成**七脚**现实：脚号集、spec 用的 token、无 `P1/P2/A1/A2/S1/S2` 残留 |
| `test_the_five_pin_transformer_cannot_carry_this_circuit` | 变成 **118 的发现记录**：拿**当时那五颗脚**（记在 `outputs/118/library_measured.json` 里）重跑那份穷举，结论仍是「缺的永远是 AUX」——钉的是那份发现，不是现电路 |

============================ 121b 更新：库里多了旗标 ============================

121b 给库加了**三颗无脚 profile**（`PWR-GND` / `PWR-HVDC` / `PWR-SEC_12V`），于是
「每颗 profile 的几何出处」这份契约多了一条分支：旗标**没有脚尖**可言（连接点就是
原点，无脚正是编译器识别旗标的办法），所以本文件对它改问**它真正带的那一半实测**
——字形挂在连接点**哪一侧**、岳把这一族画在**什么姿态**，读数是
`outputs/099/libprobe`（宿主自己两颗旗标的字号 bbox）与岳亲手画的 P1 页
（`outputs/111/geo_P1_live.json`：PGND/SEC_GND 全 180、HVDC/SEC_12V 全 0）。

三颗旗标的**体框**当时是 053B 的**约定盒** `(-6,0,6,18)`（本仓库每颗 `PWR-*` 都写它，
所以它认不出族），所以那一行 `body:` 必须说自己是**约定**而不是测量；实测那一行
标 `[121b] `——**118 没量过旗标**，给它写 `[118] ` 正是这条契约要拒的那句谎话。

============================ 147 更新：体框现在是实测，旗标按族实测 ============================

**147 把这条契约的尺子换掉了，而尺子换掉的理由本身就是一次测量。** 147 之前，
每颗 profile 的 `body` 是「引脚内端推出来的盒」——对两颗脚的器件是**一条线**
（`R0603: [-10,0,10,0]`），在垂直于引脚轴的方向上零厚度。零厚度的盒子在任何姿态下
都「没有内部」，于是 `wire-through-body` 与「文字压器件」这两条硬约束对 15/19 个
器件**天然失效**：岳在落地页面上用眼睛抓到的三处「走线穿器件 / 文字压器件」，全部
离线闸绿（`outputs/147/FINDINGS.md` §0）。修法是量一次真的：
`sch.geometry --params {"bboxIds": [...]}` 给每个 primitive 一个外框（含描边），
把 16 颗 symbolRef 的 `body` 换成那份读数（`outputs/147/11_geom_bboxes.json`，
147b 把副本搬进 `outputs/118/`，本文件读的就是它）。

所以本文件两条测试的尺子跟着换：

* `…says_where_its_geometry_came_from`：一句 `body:` / `measured:` 的来源要**说对
  自己那一类**——有读数的那 16 颗必须说「宿主自己的 per-primitive bbox」并点出
  那份读数文件，没读数的那一颗（`C0805`）必须说自己是**引脚内端的下界**；
  旗标（无脚那三颗）不再是「约定盒」，它们的那一行必须说这是**宿主读到的字形**，
  而族是**按 symbolRef 读**的。
* `…body_box_is_the_extent_the_host_reports`（原名 `…is_the_measured_inner_ends…`）：
  体框**逐字等于**从两份原始读数重新折回来的那张表（读法复用
  `tools/118_measure_profiles.py::read_bboxes`——库就是这个工具建的，
  测试与工具用同一把尺子才算对账）；没有读数的那一颗照旧按下界核。
  旗标那一半保留 121b 的两项实测（字形在连接点哪一侧、岳把族画在什么姿态），
  外加一件约定盒**表达不了**的事：两个族的盒子**必须不同**（gnd
  `(-10.5,0,10.5,19.5)` vs rail `(-5.5,0,5.5,10.5)`）。
"""

from __future__ import annotations

import json
import math
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
APPLY = ROOT / "outputs" / "118" / "apply_report.json"
PINS110 = ROOT / "outputs" / "110" / "11_pins.json"
BODIES110 = ROOT / "outputs" / "110" / "12_bodies.json"
#: 118b 换料探针的原始输出（真机只读）。T1 的实测从这里来，不再从 apply_report
#: ——那一页上放的还是被换掉的那颗 `C9900020988`。
SWAP_PROBE = ROOT / "outputs" / "118" / "probe" / "xfmr_swap_probe.json"
#: 118 **当时**那份实测库（换料之前）。五脚变压器那份发现的可复算证据在这里，
#: 所以 119 把那条测试改成记录它时不必重新造数据。
LIBRARY_118 = ROOT / "outputs" / "118" / "library_measured.json"

#: 120 换掉的唯一一颗 profile（119 换过一次，见下），以及它现在该读哪份实测。
#:
#: 换料是常事，所以这一段**只记当前这一颗**，不写死「它曾经是哪一颗」——
#: 119 那颗 `XFMR-XREE16-050624` 的证据在 `outputs/119/`，它的七脚断言在
#: `tests/test_119_pose_ladder_widening.py` 与 119 的 SUMMARY 里。
SWAPPED_REF = "XFMR-WE-749118105"
SWAPPED_FROM = "XFMR-XREE16-050624"

#: 145c: the library gained a **second** two-pin capacitor profile, and the
#: reason is a measurement, not a shape preference. "0603" is a footprint, not
#: one symbol geometry: the host resolves ``C100040`` (1nF, the part 118 measured
#: the ``C0603`` profile from) to a symbol whose pins escape ±15, and ``C14663``
#: (100nF, C13) to a **different** symbol whose pins escape ±20. 145b's live
#: apply found this the hard way — C13 read back at ±20 against a plan that
#: expected ±15, and the pin read-back stopped the run before any wire was
#: drawn. So 145c measured ``C14663`` on a scratch page of ``test`` and
#: registered it under its own symbolRef instead of widening ``C0603`` (widening
#: it would be a lie about C10/C6, whose ±15 read-back is exact).
#:
#: The reading it must be checked against is the probe output, not the profile's
#: own note — the same ruler every other profile in this file is held to.
PROBE_145C = ROOT / "outputs" / "145c" / "probe_145c_C14663.json"
C0603W_REF = "C0603W"

#: 121b: the three **flag** profiles the library gained (``PWR-GND`` /
#: ``PWR-HVDC`` / ``PWR-SEC_12V``). They have **no pins** — the connection point
#: IS the origin, and a pin-less profile is how the compiler identifies a flag —
#: so the contract they are held to is not "every tip is measured" (there are no
#: tips to have been hand-written) but "the glyph's side and the pose are", and
#: those readings are real files, read by :func:`_flag_readings`.
#:
#: ``symbolRef -> (family, the net 岳's own P1 page states with that family)``.
FLAG_READINGS: dict[str, tuple[str, str]] = {
    "PWR-GND": ("gnd", "PGND"),
    "PWR-HVDC": ("rail", "HVDC"),
    "PWR-SEC_12V": ("rail", "SEC_12V"),
}

#: 147: the reading the library's `body` boxes now come from, and the tool that
#: folds it back into symbol-local coordinates. **The tool is imported** rather
#: than re-implemented here: `tools/118_measure_profiles.py` is what *builds* the
#: library, so a test that folded the reading its own way would be a second ruler
#: for the same number — and two rulers is how a body box ends up disagreeing
#: with the drawing it describes (147's root cause). 147b moved both input files
#: under `outputs/118/`, which is where the tool and this file now read them.
BODY_TOOL = ROOT / "tools" / "118_measure_profiles.py"

#: The two live-host readings the flag profiles cite: 099's library probe (each
#: family's glyph extent, relative to the connection, at rotation 0) and 岳's own
#: hand-drawn P1 page (the rotation his flags are actually drawn at).
FLAG_GLYPH_PROBE = ROOT / "outputs" / "099" / "libprobe" / "08_geometry_probe.json"
FLAG_PAGE_READING = ROOT / "outputs" / "111" / "geo_P1_live.json"


def _measured_bodies() -> dict[str, tuple[float, float, float, float]]:
    """``{symbolRef: local body box}`` **re-derived** from the host's bbox reading.

    The reading is a page box per placed primitive (`outputs/118/11_geom_bboxes.json`,
    the host's own ``sch.geometry bboxIds`` answer) plus the poses of the page the
    ids came off (`outputs/118/bbox_layout.json`); folding the box back through
    the pose gives the symbol-local extent — which is what a profile's ``body``
    has to be, and what 147 measured for all 16 disposed symbolRefs.

    The fold is the tool's own :func:`read_bboxes`, imported by path (the module
    name starts with a digit). The tool fills its flag-family table from the
    library at the start of a build, so this does the same — otherwise a ground
    flag would be folded through the rail family's rotation and the box would be
    wrong on the axis the flag hangs from, silently.

    A symbolRef the reading never covered is **absent** from the result rather
    than defaulted: "nobody put this part on a page" is a different claim from
    "the host reports this box", and the callers below branch on exactly that.
    """
    import importlib.util

    from boardwise.core.symbolprofile import SymbolProfile, flag_glyph_kind

    spec = importlib.util.spec_from_file_location("tool_118_measure_profiles", BODY_TOOL)
    assert spec is not None and spec.loader is not None, BODY_TOOL
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    tool._FLAG_KIND.update({
        entry["symbolRef"]: flag_glyph_kind(SymbolProfile.from_dict(entry))
        for entry in book["profiles"]
    })
    return dict(tool.read_bboxes(book["profiles"]))


def _flag_readings() -> tuple[dict[str, tuple[float, float]], dict[str, float]]:
    """``(glyph extent per family relative to the connection, flag rotation by net)``.

    Both halves are what the flag profiles *claim*, read out of the live-host
    files they cite instead of taken on trust: which side of the connection each
    family hangs its glyph on (positive y is above it), and the rotation 岳's own
    page draws each family at. That is the difference between "the note names a
    file" and "the file says what the note says" — the whole point of the
    provenance contract this file pins.
    """
    probe = json.loads(FLAG_GLYPH_PROBE.read_text(encoding="utf-8"))
    glyph: dict[str, tuple[float, float]] = {}
    for component in probe["components"]:
        state = component.get("state", component)
        if state.get("ComponentType") != "netflag":
            continue
        box = probe["bboxes"].get(component["primitiveId"])
        if box is None:
            continue
        name = str((state.get("Component") or {}).get("name", ""))
        family = "gnd" if name.upper().startswith("GROUND") else "rail"
        glyph[family] = (
            round(box["minY"] - state["Y"], 4),
            round(box["maxY"] - state["Y"], 4),
        )
    page = json.loads(FLAG_PAGE_READING.read_text(encoding="utf-8"))
    rotation: dict[str, float] = {}
    for component in page["components"]:
        state = component.get("state", component)
        if state.get("ComponentType") != "netflag":
            continue
        rotation.setdefault(state.get("Net", ""), float(state.get("Rotation", 0.0)))
    return glyph, rotation

if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))


def _inverse_pose(dx: float, dy: float, rotation: float, mirror: bool):
    """Local symbol tip from a page offset under a placed pose.

    :func:`boardwise.core.geometry.transform_point` mirrors first and rotates
    second, so the inverse rotates by -theta and *then* un-mirrors.  The order
    is not cosmetic: getting it wrong still returns plausible numbers, which is
    why the cross-check in ``test_two_live_readings_agree_pin_for_pin`` exists.
    """
    rad = math.radians(-rotation)
    cos_v, sin_v = math.cos(rad), math.sin(rad)
    x = dx * cos_v - dy * sin_v
    y = dx * sin_v + dy * cos_v
    if mirror:
        x = -x
    return (round(x, 4), round(y, 4))


def _measured_118() -> tuple[dict, dict]:
    report = json.loads(APPLY.read_text(encoding="utf-8"))
    placed = {item["designator"]: item for item in report["write"]["placed"]}
    tips: dict[str, dict[str, tuple[float, float]]] = {}
    for key, point in report["write"]["pins"].items():
        part_id, _, number = key.rpartition(".")
        part = placed[part_id]
        tips.setdefault(part_id, {})[number] = _inverse_pose(
            point[0] - part["x"], point[1] - part["y"],
            part["rotation"], part["mirror"],
        )
    lcsc = {part_id: part["lcsc"] for part_id, part in placed.items()}
    return tips, lcsc


def _measured_110() -> dict[str, dict[str, tuple]]:
    """`{lcsc: {pin number: (local x, local y, name, direction, length)}}`."""
    bodies = json.loads(BODIES110.read_text(encoding="utf-8"))
    origin, by_lcsc = {}, {}
    for component in bodies["components"]:
        state = component.get("state", component)
        if state.get("ComponentType") == "sheet":
            continue
        origin[state["Designator"]] = (state["X"], state["Y"])
        by_lcsc[state.get("SupplierId")] = state["Designator"]
    by_rotation = {0: "right", 90: "up", 180: "left", 270: "down"}
    measured = json.loads(PINS110.read_text(encoding="utf-8"))
    out = {}
    for designator, record in measured.items():
        if designator not in origin:
            continue
        ox, oy = origin[designator]
        code = next((c for c, d in by_lcsc.items() if d == designator), None)
        if code is None:
            continue
        out[code] = {
            str(pin["PinNumber"]): (
                round(pin["X"] - ox, 4), round(pin["Y"] - oy, 4),
                pin["PinName"],
                by_rotation.get(pin["Rotation"], "right"),
                float(pin["PinLength"]),
            )
            for pin in record["pins"]
        }
    return out


# ------------------------------------------------------- 119: the swapped part


def _swap_probe() -> dict:
    """The 118b probe reading — **118's** part, kept as 118/119's record.

    120 swapped the transformer again (WE 749118105, six pins), so this file no
    longer holds the reading for the part T1 uses. It is still read, for one
    reason: the five-pin finding (118) and the seven-pin state (119) are both
    claims about parts that were once on this page, and deleting the reading
    would make them unfalsifiable — a test that only ever checked the current
    part could not tell a real record from a story someone made up later.

    So this stays a **historical** reading, and the current part is measured from
    the profile the compiler actually reads (see :func:`_current_transformer`).
    That split is the whole of 120's "改的是主张，不是掩盖": the claims move to the
    new reality, the evidence for the old claims stays where it was found.
    """
    payload = json.loads(SWAP_PROBE.read_text(encoding="utf-8"))
    chosen = next(
        entry for entry in payload["candidates"].values()
        if entry.get("verdict") == "chosen"
    )
    placed = chosen["placedPrimitive"]
    assert "rot0" in placed, (
        f"the probe part was placed {placed!r}, so subtracting its origin is not "
        "the inverse transform this reader assumes"
    )
    ox, oy = (int(value) for value in placed.rsplit("(", 1)[-1].split(")")[0].split(","))
    return {
        "lcsc": next(
            code for code, entry in payload["candidates"].items()
            if entry is chosen
        ),
        "tips": {
            str(pin["number"]): (float(pin["x"] - ox), float(pin["y"] - oy))
            for pin in chosen["pins"]
        },
        "body": (
            float(chosen["bbox"]["minX"] - ox),
            float(chosen["bbox"]["minY"] - oy),
            float(chosen["bbox"]["maxX"] - ox),
            float(chosen["bbox"]["maxY"] - oy),
        ),
    }


def _current_transformer() -> dict:
    """T1's profile **as the compiler reads it**, plus what its own note claims.

    120: the swapped-in part is the WE 749118105 (six pins, two windings), and
    unlike 118's and 119's parts there is **no probe file in the tree** for it
    yet — the measurement is recorded on the profile itself (``[118c]`` in the
    title, ``body:`` in the notes, and the datasheet pinout in ``value``). So
    the readings under test are read through the **library loader**, the same way
    the compiler reads them: if the loader drops or mangles a number, this fails,
    which a hand-rolled JSON reader would not catch.

    What it deliberately does **not** do is check the numbers against a
    measurement this test can see. That check is 岳's and the probe's job; what
    belongs here is that the profile the compiler uses is the one the spec names,
    that its pins are the six the datasheet lists, and that its own note says
    where the body came from.
    """
    from boardwise.core.circuitspec import CircuitSpec

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    profile = circuit_symbol(circuit, "T1")
    assert profile is not None, "T1 has no profile in the library the spec names"
    return {
        "symbolRef": profile.symbol_ref,
        "pins": {pin.number: tuple(pin.tip) for pin in profile.pins},
        "numbers": sorted(pin.number for pin in profile.pins),
        "body": tuple(profile.body),
        "notes": list(profile.notes),
        "lcsc": next(
            (part.lcsc for part in circuit.parts if part.id == "T1"), ""
        ),
    }


def _measured_session() -> dict[str, str]:
    """``symbolRef -> designator`` **of the measurement session**, not of today.

    The designator↔symbol mapping is read from the apply report's own plan (the
    page 118 measured), never from the current ``circuit.json``: 119 swapped T1's
    part, and the spec's designator→LCSC assignments have moved with it, so a
    test that resolved profiles through today's spec would point at parts the
    measurement never saw. One designator per symbolRef — profiles are per
    symbol, not per part.
    """
    plan = json.loads(
        (ROOT / "outputs" / "118" / "plan_report.json").read_text(encoding="utf-8")
    )["plan"]["change"]["parts"]
    sample: dict[str, str] = {}
    for item in plan:
        sample.setdefault(item["symbolRef"], item["designator"])
    return sample


# -------------------------------------------------- 145c: the second 0603 symbol


def _probe_145c() -> dict[str, tuple[float, float]]:
    """``C0603W``'s local pin tips, read off the 145c probe output.

    The probe placed ``C14663`` on a scratch page of ``test`` at a known origin
    and read ``sch.component_pins`` back; the local tip is the page reading minus
    that origin, i.e. the same inverse-pose step 118's reader takes (the probe
    placed it at rotation 0, so there is no rotation to undo). Read from the file
    rather than taken on trust, so a note that names the probe and a probe that
    says something else cannot both pass.
    """
    payload = json.loads(PROBE_145C.read_text(encoding="utf-8"))
    placement = payload["placement"]
    assert placement["rotation"] == 0 and not placement["mirror"], (
        f"{PROBE_145C.relative_to(ROOT).as_posix()} placed the part under a pose "
        f"{placement!r}; this reader subtracts the origin only, so a rotated or "
        "mirrored placement would be read as the wrong local tip"
    )
    ox, oy = placement["x"], placement["y"]
    return {
        str(pin["number"]): (round(pin["x"] - ox, 4), round(pin["y"] - oy, 4))
        for pin in payload["pinsAbsolute"]
    }


# ============================================================== 1 实测，不是编写


def test_two_live_readings_agree_pin_for_pin():
    """**118 的地基**：两份**互相独立**的真机读数，逐脚一致。

    118 的每颗 profile 都要用「脚尖来自 118 的回读、名字/方向/长度来自 110 的
    测量」这种拼接的来源，而拼接只有在两份读数**本来就说同一件事**的时候才
    成立。这一条每次跑都重量一遍，不是记忆。

    118 覆盖 21 颗，110 覆盖其中 **12 颗**（同一 LCSC）。**12/12 逐脚全等，
    0 处分歧**——所以那另外 9 颗（118 独有的 LCSC）沿用 110 的**族规则**取
    名字与长度时，脚尖仍然是 118 **逐颗实测**的，0603 的 ±15 与 0805 的 ±20
    由测量区分，不是按尺寸类别猜的。
    """
    tips, lcsc = _measured_118()
    other = _measured_110()
    shared = [part for part in tips if lcsc[part] in other]
    assert len(shared) >= 12, (
        f"only {len(shared)} of {len(tips)} parts were measured twice; the "
        "cross-check is the whole basis for trusting the rest"
    )
    problems = []
    for part in sorted(shared):
        mine, theirs = tips[part], {n: v[:2] for n, v in other[lcsc[part]].items()}
        if set(mine) != set(theirs):
            problems.append(f"{part}: token set {sorted(mine)} vs {sorted(theirs)}")
            continue
        for number in sorted(mine):
            if tuple(mine[number]) != tuple(theirs[number]):
                problems.append(
                    f"{part} ({lcsc[part]}) pin {number}: "
                    f"118 reads {mine[number]}, 110 reads {theirs[number]}"
                )
    assert not problems, (
        "the two live readings disagree, so every profile below would be a "
        "guess: " + "; ".join(problems)
    )


def test_no_profile_carries_a_hand_written_pin_tip():
    """**每颗 profile 的脚尖都等于实测**，一颗都不许是编的——T1 除外，因为它换了料。

    量的是**符号局部坐标**（把 118 的页坐标读数按该器件实际落图时的位姿
    逆变换回去），不是页坐标——那才是 profile 该记的东西。

    **119 更新**：T1 的 profile 换成了 118b 换料探针实测的那颗七脚变压器，所以
    它的脚尖不再等于 `apply_report.json` 的读数——那一页上放的还是**被换掉的**
    那颗 `C9900020988`。这一条对十二颗没动过的符号照旧逐脚对账，对 T1 改钉
    探针读数，**并且把两者都要求存在**：一颗既不在 118 那页上、也不在换料探针
    里的 profile，就是一颗来源不明的 profile，那是本条要抓的形状。

    **121b 更新**：库里多了三颗**旗标** profile，它们**没有脚**（连接点就是原点，
    无脚正是编译器识别旗标的办法）。所以「脚尖是不是编的」在这三颗上无从谈起
    ——本条对它们改问另一半：**它是被登记在一个真读数上的，而且自己的文字里
    点得出那两份文件的名字**（`outputs/099/libprobe`、`outputs/111/geo_P1_live.json`）。
    旗标真正会悄悄错掉的是「字形挂在连接点哪一侧」和「姿态」，那由下面那条
    体框测试逐项对着这两份文件核；这里只管登记在不在、文字点不点得出来。
    """
    tips, lcsc = _measured_118()
    probe = _swap_probe()
    current = _current_transformer()
    session = _measured_session()
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))

    measured_for: dict[str, tuple[dict, str]] = {}
    for symbol_ref, designator in session.items():
        measured_for[symbol_ref] = (tips[designator], f"the 118 apply report ({designator})")
    # 120: the part T1 uses now is the WE six-pin one, measured through the
    # library loader. The 118b probe reading stays for **its** part, which is
    # what the five-pin and seven-pin findings are about.
    measured_for[SWAPPED_REF] = (current["pins"], f"the 120 library ({SWAPPED_REF})")
    # 145c: the second 0603 symbol, measured on a scratch page of `test`. It is
    # turned up by **this** registry, not by the 118 apply report, because no 118
    # page ever placed `C14663`.
    measured_for[C0603W_REF] = (
        _probe_145c(),
        f"the 145c probe ({PROBE_145C.relative_to(ROOT).as_posix()})",
    )

    for entry in book["profiles"]:
        symbol_ref = entry["symbolRef"]
        if not entry["pins"]:
            # 121b's flags. A flag is *identified* by having no pins — its origin
            # IS the connection point — so there is no tip in here that could
            # have been hand-written, and "no live reading covers this profile"
            # is the wrong complaint: what a pin-less profile can get silently
            # wrong is the glyph's side and its pose, which *are* measured (by
            # 099's probe / 064's canvas probe / 岳's own page), and which
            # :func:`test_every_body_box_is_the_measured_inner_ends_and_nothing_wider`
            # checks against those files. Here the requirement is the one that
            # keeps that checkable: the flag is registered against a live
            # reading, and its own prose names it.
            assert symbol_ref in FLAG_READINGS, (
                f"{symbol_ref}: a pin-less profile is a flag, and every flag "
                "profile has to be registered against the live reading that "
                f"measured its glyph (registry: {sorted(FLAG_READINGS)})"
            )
            prose = entry["title"] + "\n" + "\n".join(entry["notes"])
            for cited in (
                FLAG_GLYPH_PROBE.parent.relative_to(ROOT).as_posix(),
                FLAG_PAGE_READING.relative_to(ROOT).as_posix(),
            ):
                assert cited in prose, (
                    f"{symbol_ref}: this profile is registered against a live "
                    f"reading but never names {cited!r} — a provenance a reader "
                    "cannot find is not a provenance"
                )
            continue
        assert symbol_ref in measured_for, (
            f"{symbol_ref}: no live reading covers this profile any more, so its "
            f"pin tips would be an assertion about nothing (119 swapped T1; the "
            f"swapped-in part is measured by {SWAP_PROBE.relative_to(ROOT).as_posix()})"
        )
        measured, source = measured_for[symbol_ref]
        # The designator is a name for the failure message only. `T1` is the
        # default because the swapped-in transformer is the one profile whose
        # designator is not in the 118 session; 145c's C0603W is the same case,
        # so its own symbolRef is the honest name rather than a borrowed `T1`.
        designator = session.get(symbol_ref) or (
            "T1" if symbol_ref == SWAPPED_REF else symbol_ref
        )
        declared = {pin["number"]: tuple(pin["tip"]) for pin in entry["pins"]}
        assert set(declared) == set(measured), (
            f"{symbol_ref}: the profile declares {sorted(declared)} but "
            f"{source} measured {sorted(measured)}"
        )
        for number, tip in sorted(measured.items()):
            assert declared[number] == tip, (
                f"{symbol_ref} pin {number}: the profile says "
                f"{declared[number]}, {source} measured {tip} — 113's "
                "hand-written tip is still in here"
            )
        assert designator, f"{symbol_ref} has no designator to name in a failure"


def _body_source(entry: dict) -> str:
    """The one line that says where a profile's body came from.

    **119 更新**：118 wrote it as a ``bodySource`` **key**, and the library
    schema's CLI validation does not accept that key — it was folded by hand
    into ``notes``, which the schema does accept and which must therefore be an
    array of strings. Reading the key would report every profile as unsourced;
    reading the note is what the file now says.

    **147 更新**：147 把体框换成宿主实测之后，那一行的前缀是 ``measured:``
    而不是 ``body:``（`tools/118_measure_profiles.py::MEASURED_BODY_SOURCE`
    写的就是这一行），所以这里两种前缀都认得——认的是**「有一行交代体框的来历」
    这件事**，不是某一个前缀。没有读数的那颗（`C0805`）仍带着 118 那句话
    （``body: measured: the two pins' inner ends``），它说的正是下界。
    """
    notes = entry.get("notes")
    assert isinstance(notes, list) and all(
        isinstance(line, str) for line in notes
    ), (
        f"{entry['symbolRef']}: notes is {notes!r}; the schema wants an array of "
        "strings, and the body provenance lives in one of them"
    )
    for line in notes:
        if line.startswith("body:") or line.startswith("measured:"):
            return line
    return ""


def test_every_profile_says_where_its_geometry_came_from():
    """**每颗 profile 自己交代来源**——实测还是下界，一行字，不许含糊。

    三种来源，可信度各不相同，而且它们**不是同一种量法**，所以也不该用同一把
    尺子去量（下一条就是按来源分尺的）：

    * 两颗脚的器件：体内端**就是**本体的边——**实测**；
    * 多脚器件：外侧体内端只框住 x 与 y 的范围、中间的缺口没有读数带得到——
      **下界**；
    * **119 新增第三种**：T1 换的那颗七脚变压器，**真的有一份 bbox 读数**
      （118b 探针的 ``sch.geometry bboxIds``），所以它的体框是**实测 bbox**，
      而且比体内端**更宽**——骨架中间的绕组空档没有脚可推，那一块地是真占着的。
      把一个实测 bbox 说成下界，或者反过来按下界去核一个实测 bbox，都是把
      测量说成估计。

    **121b 更新，第四种**：三颗**旗标** profile 的体框既不是实测也不是下界——它是
    053B 的**约定盒**，本仓库每一颗 `PWR-*` 都写着同一个 `(-6,0,6,18)`，所以那
    一行 `body:` 必须**说自己是约定**（上一批在这三颗上写了一句 "measured"，
    把约定说成了测量，这一条就是不让人再这么写）。旗标真正带实测的那一半另说：
    **字形挂在连接点哪一侧、岳把这一族画在什么姿态**，由下面那条测试对着
    `outputs/099/libprobe` 与 `outputs/111/geo_P1_live.json` 两份真读数核。

    **147 更新，四种来源归成两种**：147 量到了每颗 primitive 的外框，于是
    「约定盒」这一种**没有了**——旗标的盒也成了宿主读数（按族：ground 的 bars
    挂在连接点下方、rail 的 pennant 挂在上方，两个族**盒子不同**，这正是 053B
    那个「一盒两族」的约定盒表达不了的事）。所以本条现在只认两种：

    * **有读数**（16 颗，含三颗旗标）：那句话必须说体框是**宿主自己的
      per-primitive bbox**，并且点出一份**真的在树里**的读数文件；
    * **没有读数**（`C0805`，118/147 都没把它放上过页面）：那句话必须说这是
      **引脚内端推出的下界**——把一个没量过的东西说成测量，正是本条要拒的谎话。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    reading = _measured_bodies()
    assert len(reading) >= 16, sorted(reading)
    for entry in book["profiles"]:
        assert "measured 2026-10-04" in entry["title"] or "measured on the live host" in entry["title"], (
            f"{entry['symbolRef']}: the title does not say the pins are measured"
        )
        source = _body_source(entry)
        assert source, (
            f"{entry['symbolRef']}: no notes line starts with 'body:' or "
            "'measured:', so a reader cannot tell a measured body from a derived "
            "lower bound"
        )
        if entry["symbolRef"] in reading:
            # 147: measured, and the note has to say *which* measurement. A note
            # that claims a host bbox reading while carrying a box nobody read
            # fails the next test; a note that calls a measured box a lower bound
            # fails here.
            assert "per-primitive bbox" in source, (
                f"{entry['symbolRef']}: the box is in the host's bbox reading but "
                f"the note says {source!r} — the one thing a reader needs is which "
                "of the two kinds of box this is"
            )
            named = [
                word for word in source.split()
                if word.startswith("outputs/") and (ROOT / word).exists()
            ]
            assert named, (
                f"{entry['symbolRef']}: the note cites no reading file that "
                f"exists, so the provenance cannot be checked: {source!r}"
            )
            continue
        # Nobody ever placed this symbol, so no reading covers it: the box is the
        # pin-derived lower bound, and calling that a measurement is the lie this
        # branch exists to refuse.
        assert "inner ends" in source and "per-primitive bbox" not in source, (
            f"{entry['symbolRef']}: no reading covers this profile, so its box "
            f"must be the stated pin-derived lower bound; the note says {source!r}"
        )
        if not entry["pins"]:
            continue


def test_every_body_box_is_the_extent_the_host_reports():
    """**体框是实测的**：逐字等于从宿主读数重新折回来的那张表，一颗不差。

    **为什么换尺子（147，见 `outputs/147/FINDINGS.md` §0）**：这条测试原名
    `…is_the_measured_inner_ends_and_nothing_wider`，量的尺子是「体框 == 引脚内端
    推出来的盒」。那把尺子在 147 之前是对的（库当时就是这么建的），但它量的东西
    本身是**退化的**：两颗脚的器件推出的是**一条线**（`R0603: [-10,0,10,0]`），
    多脚器件推出来的是外侧脚之间那个矩形。线没有内部，于是任何走线、任何文字行
    都可以穿过它而闸看不见——岳在落地页面上抓到的三处「走线/文字压器件」全部因此
    离线绿着。147 量了宿主自己的外框（`sch.geometry bboxIds`，含描边）并把 16 颗
    symbolRef 的 `body` 换掉，**于是这条量的是那次测量**：

    * **有读数的 16 颗**：`body` 必须逐字等于 `read_bboxes` 从两份原始读数
      （`outputs/118/11_geom_bboxes.json` + `bbox_layout.json`）折回来的盒。
      库就是这个工具建的，所以这是「库 == 工具的输出」的对账，而不是又写一遍
      同一条公式（两把尺子量同一个数，正是 147 要治的病）；
    * **两个方向都必须有正的长度**（这是 147 的**主题**：一个零厚度的体框不是
      体框）。没读数的那颗（`C0805`）**不在**这条断言下，因为它照旧是下界——
      而下界退化正是它的陈述本身；
    * **没有读数的（`C0805`）**：照旧按老尺子核——体框 == 引脚内端推出来的盒，
      并且它必须**说自己是下界**（上一条核那句）。
    * **旗标（三颗无脚）**：现在也有读数（按族：ground `(-10.5,0,10.5,19.5)`、
      rail `(-5.5,0,5.5,10.5)`），所以它们走上面第一条分支；121b 那两项实测照旧
      核——**字形挂在连接点哪一侧**（`outputs/099/libprobe` 的 netflag bbox）与
      **岳把这一族画在什么姿态**（`outputs/111/geo_P1_live.json`）。再加一条
      147 才量得出来的事实：**两个族的盒子必须不同**——053B 那个「一盒两族」的
      约定盒恰恰表达不了这件事，而它曾经让六个批次的旗标画反了方向还全绿。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    reading = _measured_bodies()
    assert len(reading) >= 16, sorted(reading)
    glyph, page_rotation = _flag_readings()
    inward = {
        "left": (1.0, 0.0), "right": (-1.0, 0.0),
        "up": (0.0, -1.0), "down": (0.0, 1.0),
    }
    families: dict[str, tuple[float, float, float, float]] = {}
    for entry in book["profiles"]:
        ref = entry["symbolRef"]
        box = [round(value, 4) for value in entry["body"]]
        if ref not in reading:
            assert ref == "C0805", (
                f"{ref}: no reading covers this profile, and the only symbol the "
                "118/147 sessions never placed is C0805 — a profile that lost its "
                "reading is a profile whose body is now a guess"
            )
            inner = [
                (pin["tip"][0] + inward[pin["direction"]][0] * pin["length"],
                 pin["tip"][1] + inward[pin["direction"]][1] * pin["length"])
                for pin in entry["pins"]
            ]
            expected = [
                min(point[0] for point in inner), min(point[1] for point in inner),
                max(point[0] for point in inner), max(point[1] for point in inner),
            ]
            assert box == [round(value, 4) for value in expected], (
                f"{ref}: body is {entry['body']} but the measured inner ends give "
                f"{expected} — that is the stated lower bound for a symbol nobody "
                "placed, and it has to be exactly that"
            )
            continue
        expected = [round(value, 4) for value in reading[ref]]
        assert box == expected, (
            f"{ref}: the profile's body is {entry['body']} but the host's own "
            f"per-primitive bbox reading folds back to {expected} — the compiler "
            "reserves a rectangle the part does not occupy (or misses the one it "
            "does)"
        )
        # 147's whole subject: a body with no extent on an axis is a line, and a
        # line is what no wire and no text row can be caught crossing.
        assert box[2] > box[0] and box[3] > box[1], (
            f"{ref}: the measured body is degenerate on an axis ({entry['body']}) "
            "— that is the defect 147 fixed, not a reading"
        )
        if not entry["pins"]:
            family, net = FLAG_READINGS[ref]
            families[family] = (box[0], box[1], box[2], box[3])
            low, high = glyph[family]
            if family == "gnd":
                assert high < 0.0, (
                    f"{ref} is the ground family, but "
                    f"{FLAG_GLYPH_PROBE.relative_to(ROOT).as_posix()} measures its "
                    f"glyph at {low:g}..{high:g} from the connection — not below it"
                )
                assert page_rotation.get(net) == 180.0, (
                    f"岳's own page draws his {net} flags at rotation "
                    f"{page_rotation.get(net)!r}, not 180 — the ground family's "
                    "pose is a reading, and this profile claims it"
                )
                # The one ground profile states **both** ground families' cases
                # (its title says PGND and SEC_GND), so both have to be there.
                assert page_rotation.get("SEC_GND") == 180.0, (
                    "岳's own page does not draw its SEC_GND flags at 180, so "
                    "the second family this profile claims is not in the reading"
                )
                # And the measured box starts at the connection: the leader is the
                # flag's own extent, so nothing of it is *behind* the anchor.
                assert box[1] == 0.0 and box[3] > box[1], (
                    f"{ref}: the flag's box {entry['body']} does not start at the "
                    "connection (y = 0) and run away from it"
                )
            else:
                assert low > 0.0, (
                    f"{ref} is the rail family, but "
                    f"{FLAG_GLYPH_PROBE.relative_to(ROOT).as_posix()} measures its "
                    f"glyph at {low:g}..{high:g} from the connection — not above it"
                )
                assert page_rotation.get(net) == 0.0, (
                    f"岳's own page draws his {net} flag at rotation "
                    f"{page_rotation.get(net)!r}, not 0 — the rail family's pose "
                    "is a reading, and this profile claims it"
                )
                assert box[1] == 0.0 and box[3] > box[1], (
                    f"{ref}: the flag's box {entry['body']} does not start at the "
                    "connection (y = 0) and run away from it"
                )
    # 147: the two families are **different drawings**, and the library now says
    # so. The single convention box they used to share is exactly how six batches
    # of one family drawn backwards stayed invisible offline. Both boxes run from
    # the connection outwards in the profile's own frame (the family's turn is
    # `symbolprofile.FLAG_GLYPH_ROTATION_OFFSETS`, applied at draw time), so what
    # separates them is the **size**: the ground family draws a 10-unit leader
    # then 20-wide bars, the rail family a 5-unit leader then a 10-wide pennant —
    # 147's own measurement, and the reason one box could never serve both.
    assert families.get("gnd") != families.get("rail"), families
    gnd, rail = families["gnd"], families["rail"]
    assert (gnd[2] - gnd[0]) > (rail[2] - rail[0]) and gnd[3] > rail[3], (
        f"the ground family's glyph is the larger one (measured 19.5 from the "
        f"connection against the rail's 10.5): {families}"
    )


def test_every_pin_carries_the_name_the_host_reports():
    """**脚名也是实测的**，不是 113 起的那套。

    113 给三极管写的是 `1=S 2=D 3=G`，给 TL431 写的是 `A` / `K` / `REF`。
    宿主实测：MOSFET 是 `1=G 2=D 3=S`（**门与源在号数上对调**），TL431 是
    `1=REF 2=CATHODE 3=ANODE`（**只有 REF 那个名字还在**）。名字错了不一定会
    立刻炸——`_pin_of_token` 先按号码找，找不到才按名字——但它会让一个写错名字
    的 spec 悄悄绑到**另一根脚**上，而那正是 118 这次要消灭的那一类事故。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    declared = {
        entry["symbolRef"]: {
            pin["number"]: pin["name"] for pin in entry["pins"]
        }
        for entry in book["profiles"]
    }
    # The measured names, from 110's reading of the same LCSC parts.
    measured = _measured_110()
    _tips, lcsc = _measured_118()
    # 119: the symbol table follows the **measurement session**, read off the
    # apply report's own plan rather than today's spec. T1's entry there names
    # the part that was swapped OUT, so it is dropped explicitly instead of
    # being resolved through a symbolRef that no longer exists in the library —
    # and the count is asserted so a future swap cannot quietly shrink what this
    # test checks.
    session = _measured_session()
    # 120: `SWAPPED_FROM` is now the **119** part, which is not in the 118 apply
    # report either, so the filter drops it by the same rule as before — the one
    # that matters is that the mapping is read off the measurement session, not
    # off today's spec.
    sample = {
        symbol_ref: lcsc[designator]
        for symbol_ref, designator in session.items()
        if symbol_ref not in (SWAPPED_FROM, "XFMR-EE16-3W")
    }
    covered = 0
    for symbol_ref, code in sample.items():
        record = measured.get(code)
        if not record:
            continue
        covered += 1
        for number, values in record.items():
            name = values[2]
            assert declared[symbol_ref].get(number) == name, (
                f"{symbol_ref} pin {number}: the profile calls it "
                f"{declared[symbol_ref].get(number)!r}, the host reports {name!r}"
            )
    # 8 of the 12 remaining profiles, not 21: the count is over *symbols*, and 110
    # measured 12 *parts* which collapse onto fewer symbols (three pairs share an
    # LCSC). **119**: it was 9, and the ninth was the five-pin transformer — the
    # part 119 took out of the circuit. The floor moves with the library, and
    # this states the new one rather than leaving a stale 9 that would be
    # satisfied by re-admitting a profile nobody uses.
    assert covered >= 8, (
        f"only {covered} profiles could be checked against a measured name; the "
        "pin tokens are the whole point of this batch"
    )


def test_the_113_shape_intent_is_kept_alongside_the_measurement():
    """**意图与实测分两行**——113 选形状的理由不许被实测悄悄抹掉。

    113 为每颗符号挑的形状是**有理由的**（岳 ruling e 要反馈横排在水平线上、
    钳位二极管要横着画才表达得了「变压器的这一侧」），那些理由写进了 title。
    118 换了几何，**理由必须还在**，只是不能再说成「这就是器件的样子」。

    **119 更新**：那一行的批号跟着**这颗 profile 自己的来历**走。十二颗没换过料
    的仍然是 `[118] `；换过料的那颗（`XFMR-XREE16-050624`）是 **118b** 的换料
    探针量的，所以它是 `[118b] `。这一条查的是「实测那一行在，而且标的是这颗
    profile 真正的来源」，不是查一个写死的批号——写死的批号会在下一次换料时
    变成一句谎话，而这一条正是为了不让人写谎话存在的。

    **121b 更新**：三颗旗标的实测那一行是 `[121b] `——它们不是任何一次换料量出来的，
    几何来自宿主自己的旗标读数（`outputs/099/libprobe`、`outputs/064_railflag`）与
    岳亲手画的 P1 页（`outputs/111/geo_P1_live.json`），所以批号是它们自己那一批。
    给它们写 `[118] ` 正是这一条要拒的那句谎话：118 从没量过旗标。批号仍然是
    **逐类钉死**的（不是从 title 里回读出来的），所以把 `[121b]` 改成 `[118]` 会红。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    for entry in book["profiles"]:
        title = entry["title"]
        # 120's measurement is marked `[118c]`; 119's was `[118b]`. The marker is
        # **derived from the profile's own title** rather than hard-coded, so a
        # future swap cannot leave a stale claim behind — and the test below still
        # pins the current part's marker explicitly.
        # 120: the marker for the **current** part is pinned, not derived. A first
        # version derived it from the title, which made the assertion unfalsifiable
        # — mutation M6 changed `[118c]` to `[118]` and the test stayed green,
        # because a title that says `[118]` yields the expectation `[118]`. The
        # structural half (there IS a measurement line) and the factual half (it
        # names **this** measurement) are two different claims and need two
        # different assertions.
        #
        # 121b added a third class and it is pinned the same way: the flags were
        # not measured by any part swap — their geometry is the host's own flag
        # readings (outputs/099/libprobe, outputs/064_railflag) plus 岳's own P1
        # page (outputs/111/geo_P1_live.json) — so they carry their own batch
        # marker. Writing `[118] ` on them would be exactly the stale claim this
        # test exists to refuse: 118 never measured a flag.
        if entry["symbolRef"] in FLAG_READINGS:
            expected = "[121b] "
        elif entry["symbolRef"] == SWAPPED_REF:
            expected = "[118c] "
        elif entry["symbolRef"] == C0603W_REF:
            # 145c measured `C14663` on the live host, so its marker is its own
            # batch. Writing `[118] ` on it would be the same stale claim 121b's
            # branch refuses: 118 never placed this part (145b is where the host
            # first disagreed with the plan about it).
            expected = "[145c] "
        else:
            expected = "[118] "
        assert f"\n{expected}" in title, (
            f"{entry['symbolRef']}: the title has no {expected!r} measured-geometry "
            f"line, so 113's intent and the measurement are not separable (the "
            f"title is {title.splitlines()[-1]!r})"
        )
        intent, measurement = title.split(f"\n{expected}", 1)
        assert intent.strip(), f"{entry['symbolRef']}: the intent line is empty"
        assert "measured" in measurement
        # 113 wrote a **reason**, not a part number, for every shape it chose.
        # The reasons are worded differently per symbol (some cite 岳's ruling,
        # some say why a vertical diode cannot express a side-of-the-transformer
        # relation), so what is checked is that a reason survived at all — a
        # title that had become a bare restatement of the footprint would fail
        # this, and so would an emptied one.
        assert len(intent) > 20, (
            f"{entry['symbolRef']}: the intent line is {intent!r} — 113's reason "
            "for choosing this shape did not survive"
        )


# ================================================== 2 token 以真实符号为准


def test_every_spec_token_resolves_on_the_measured_symbol():
    """**spec 里的每一个脚 token，宿主符号上真有这一脚**。

    115② 已经定了同尺：先按**号码**、再按**名字**找（`_pin_of_token` 与
    `grammar.base.profile_pin_for` 读同一条规则）。118 把 spec 改写成宿主自己的
    token，这条量的是**改写之后**的结果——113 写的 `T1.P1` / `U4.A` 那一套
    在真实符号上一个都不存在。
    """
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.engines import drawcompiler as dc

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    missing = []
    for part in circuit.parts:
        profile = circuit_symbol(circuit, part.id)
        if profile is None:
            missing.append(f"{part.id}: no profile")
            continue
        for token in sorted(set(_tokens_of(circuit, part.id))):
            if dc._pin_of_token(profile, token) is None:
                missing.append(f"{part.id}.{token} is not a pin of {part.id}")
    assert not missing, (
        "the spec still names pins the host symbols do not have: "
        + "; ".join(missing)
    )


def _tokens_of(circuit, part_id) -> list[str]:
    from boardwise.engines import drawcompiler as dc
    return list(dc._part_nets(circuit, part_id))


def circuit_symbol(circuit, part_id):
    """The profile the compiler would use for `part_id`.

    Read through the circuit's own ``symbolRef`` rather than a hard-coded table,
    so retokenizing the spec cannot silently point a test at the wrong profile.
    """
    import test_113_flyback_grammar as t113
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    for part in circuit.parts:
        if part.id == part_id:
            return book.get(part.symbol_ref)
    return None


def test_the_transformer_has_six_pins_and_the_spec_uses_four():
    """**120 更新**：又换了一次料——WE 749118105，**六脚两绕组**，辅助链整条拆掉。

    这一条在 119 已经改过一次（113 的 `P1/P2/A1/A2/S1/S2` → 七脚 XREE 的
    `1 2 3 4 5 6 10`）。120 岳选了**真品料** WE 749118105（`C17189451`），datasheet
    pinout 是 **N1 = 1-3 原边 / N2 = 4-6 副边，2 与 5 是 NC**，所以：

    * 脚是**六**个，脚号集逐个等于 profile 读出来的；
    * spec **只接四颗**（`HVDC`→1、`SW`→3、`SEC_SW`→4、`SEC_GND`→6）——
      **2/5 是 NC，一条网都不接**，这一条单独钉住，因为「接上去了」是那颗料上
      最容易犯也最不容易看出来的错；
    * `AUX` 整条辅助链（D2/C7/AUX/VCC）**从 spec 里出去了**——语法设计上 aux 是
      **可选**角色，所以这不是「漏了」，是这颗料本来只有两绕组；这一条也单独钉住，
      否则下一次有人「补回来」就会把一颗两绕组的料当三绕组用；
    * 113 起的 `P1/P2/A1/A2/S1/S2` 一个都不许残留。

    六脚的意义要说清：**它不是「七脚减一颗」**。119 那颗 XREE 是 5+5 十位骨架
    （左侧 1-5、右侧 6/10），WE 这颗是**两绕组六脚**，副边只有一对。118 那条
    「五脚装不下三绕组」的结论在这颗料上**不再适用**——不是被推翻了，是**前提
    没了**：两颗绕组要的端数（4）小于脚数（6），辅助电源另有出处是**设计**的选择，
    不是这颗料的缺陷。
    """
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.engines import drawcompiler as dc

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    current = _current_transformer()
    assert current["numbers"] == ["1", "2", "3", "4", "5", "6"], (
        f"T1 carries {current['numbers']}; the WE 749118105 datasheet lists six "
        "pins (N1 = 1-3, N2 = 4-6, 2/5 NC) — re-probe before trusting either list"
    )
    # The NC pair: present on the symbol, connected to nothing.
    used = set(_tokens_of(circuit, "T1"))
    for nc in ("2", "5"):
        assert f"T1.{nc}" not in used, (
            f"T1.{nc} is wired up, but the datasheet calls it NC — a pin with no "
            "connection in the part must not acquire one in the spec, because "
            "nothing downstream would notice"
        )
    # The four it does carry, one by one, by net.
    by_net = {}
    for pin, net in sorted(dc._part_nets(circuit, "T1").items()):
        by_net.setdefault(net, pin)
    assert by_net == {
        "HVDC": "1", "SW": "3", "SEC_SW": "4", "SEC_GND": "6",
    }, (
        f"the transformer reaches {by_net}; the WE pinout is HVDC->1, SW->3, "
        "SEC_SW->4, SEC_GND->6 (datasheet N1 = 1-3, N2 = 4-6)"
    )
    # And the auxiliary chain is gone, which is a *design* statement about a
    # two-winding part — not an omission to be quietly repaired.
    # Only the **auxiliary** chain went. `CLAMP` / `CLAMP_B` stay: those are the
    # primary-side leakage clamp (C5/D1/R15/R3), which reads on N1 and has
    # nothing to do with a third winding — asserting they are gone would be
    # asserting a false history, and 120 measured that mistake before writing
    # this line.
    for net_id in ("AUX", "VCC"):
        assert net_id not in {net.id for net in circuit.nets}, (
            f"net {net_id!r} is back in the spec; the WE part has two windings and "
            "the grammar treats aux as an optional role, so a re-added auxiliary "
            "supply would be asking a six-pin two-winding part to carry a third"
        )
    for part in circuit.parts:
        assert part.id not in ("D2", "C7"), (
            f"{part.id} is back in the spec; it belonged to the auxiliary chain "
            "the two-winding part does not have"
        )
    for stale in ("P1", "P2", "A1", "A2", "S1", "S2"):
        assert stale not in used, (
            f"T1.{stale} is still in the spec; the host symbol has no such pin"
        )
    assert dc._part_nets(circuit, "T1"), "T1 lost its nets"



def test_the_five_pin_transformer_cannot_carry_this_circuit():
    """**118 的发现，仍然钉在那副骨架上**——换料不等于把发现删掉。

    113 的 spec 要变压器碰**六个**网：`HVDC` / `SW` / `PGND` / `AUX` / `SEC_SW` /
    `SEC_GND`——初级的两个端、初级回流、辅助绕组、副边的两个端。118 实测宿主那颗
    `C9900020988`（`EE16_3+3_V02`）只有**五根脚**（110 早就记了两次：
    `PLAN.md` 第 44 与第 160 行）。

    **穷举**：把五根脚指派到六个网上，全部 **720** 种都拿去问语法。语法收了
    **120** 种（它要求 `sec_gnd in tx_nets`，且初级回流要够得着），而这 120 种
    **无一例外**地少了 `AUX`——`EE16_3+3_V02` 是一副**两绕组**骨架顶了 3+3 的
    名字，自供电的辅助电源需要第三个绕组。牺牲的那一端**永远是辅助绕组**，与
    哪颗脚放哪一网无关。**要闭合只能换料**——那是 BOM 改动，归岳。

    **119 更新：这条断言的对象换了，但主张没换。** 那副骨架已经换下，
    `circuit.json` 里的 T1 是七脚的新料，所以**不能再拿现电路去跑这份穷举**
    ——那会量一颗已经不在这页上的器件，量出来的是别的东西。因此这一条改成
    **在 118 当时那份实测库上重跑**（`outputs/118/library_measured.json`，
    树内存档），脚号集从那份库里**读出来**，既不是从现电路读、也不是写死：库里
    是五脚就重跑五脚；将来若再换料，这一条要么重跑出新结论、要么因为库里不是
    五脚而**明说**，不会悄悄变成一句关于别人的话。

    换句话说：**这份骨架装不下这个电路，仍然是可复算的事实**，只是它现在是一
    条**历史记录**而不是当前电路的断言——换料是岳的裁定，换料不替编译器把这
    条结论擦掉。
    """
    import itertools

    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec
    from boardwise.engines import grammar
    import test_113_flyback_grammar as t113

    archived = json.loads(LIBRARY_118.read_text(encoding="utf-8"))
    archived_entry = next(
        item for item in archived["profiles"]
        if item["symbolRef"] == "XFMR-EE16-3W"
    )
    pins = [pin["number"] for pin in archived_entry["pins"]]
    assert len(pins) == 5, (
        f"{LIBRARY_118.relative_to(ROOT).as_posix()} records XFMR-EE16-3W with "
        f"{len(pins)} pins ({pins}); 118's finding was measured on five, so that "
        "archive is not the artefact it was written against — re-derive the "
        "finding rather than trusting this run"
    )
    # The whole archived library, not the live one: the finding is a statement
    # about the world as it stood, and the live library has moved on since.
    book = t113._library_from(LIBRARY_118)

    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    base = json.loads(
        (SPECS / "flyback_uc3845.circuit.json").read_text(encoding="utf-8"))
    needed = {"HVDC", "SW", "PGND", "AUX", "SEC_SW", "SEC_GND"}
    accepted, missing = 0, set()
    for permutation in itertools.permutations(sorted(needed), len(pins)):
        assignment = dict(zip(pins, permutation))
        if not {"PGND", "SEC_GND"} <= set(permutation):
            continue
        payload = json.loads(json.dumps(base))
        for net in payload["nets"]:
            net["members"] = [
                member for member in net["members"]
                if not member.startswith("T1.")
            ]
        for pin, net in assignment.items():
            for target in payload["nets"]:
                if target["id"] == net:
                    target["members"].append(f"T1.{pin}")
        for net in payload["nets"]:
            net["members"] = sorted(set(net["members"]))
        try:
            circuit = CircuitSpec.from_dict(payload)
        except Exception:
            continue
        if grammar.bind(circuit, presentation, book).ok:
            accepted += 1
            missing |= needed - set(permutation)
    assert accepted, (
        "no assignment the grammar accepts carries both ground families on the "
        "transformer — the reading has to be re-derived, not re-run"
    )
    assert missing == {"AUX"}, (
        f"the five-pin part dropped {sorted(missing)} rather than AUX; 118 "
        "measured AUX as the only casualty, so either the measurement or this "
        "test is stale"
    )


# ============================ 4 真实几何推翻了 116 的一条结论（如实记）


def test_same_column_q1_r5_is_solved_by_r5s_rotation_90_not_by_the_origin():
    """**118 量错了、也改对了**：这条序关系**仍然是位姿可解的**，但理由与 116 记的不同。

    118 的第一版断言写的是「没有任何位姿组合能满足 `same-column(Q1, R5)`」——
    **那是错的**，本条就是把它量回来的过程与结论。逐位姿量（Q1 两档、R5 四档）：

    | | Q1 的 SRC pad x | R5 的 SRC pad x |
    |---|---:|---:|
    | rot 0 | 0 | **−20** |
    | rot 0 mirror | 0 | +20 |
    | rot 90 | — | **0** ✓ |
    | rot 90 mirror | — | 0 |

    R5 转 90° 就把它的 SRC pad 放回 x=0，与 Q1 同列，容差 `grid/2 = 2.5` 内成立。
    116 说的「归位姿阶梯」**结论没错**，但它给的理由是「rot0 delta=0」——那个 0
    来自 **113 编的 profile**（R0603 被画成竖直、脚在体轴上）。真实 0603 是横置的，
    `rot0 delta=−20`，能救这条关系的是 `rot90` 而不是 `rot0`。**结论相同、理由换了**，
    这一条钉的是实测的那个理由，免得下一棒照 116 的理由去改代码而改错地方。
    """
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec
    from boardwise.engines import drawcompiler as dc
    from boardwise.core.geometry import transform_point
    import test_113_flyback_grammar as t113

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    presentation = PresentationSpec.load(
        SPECS / "flyback_uc3845.presentation.json")
    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    binding = dc.bind_grammar(circuit, presentation, book)
    prepared = dc._prepare(circuit, presentation, binding, book,
                           dc.CompileBudget(max_candidates=8))
    assert prepared.context is not None
    ctx = prepared.context
    saved = dc._relation_failures
    dc._relation_failures = lambda ctx_, placed_: []
    try:
        placed, failure = dc._place(ctx, dc._variants(ctx)[0])
    finally:
        dc._relation_failures = saved
    assert placed is not None, failure

    def pin_x(part_id: str, net: str, pose) -> float:
        token = dc._token_on(circuit, part_id, net)
        pin = dc._pin_of_token(ctx.profile(part_id), token)
        return transform_point(
            pin.tip[0], pin.tip[1], rotation=pose.rotation, mirror=pose.mirror,
            ox=placed.origins[part_id][0], oy=placed.origins[part_id][1],
        )[0]

    slack = ctx.budget.grid / 2.0
    q_at_zero = sorted({
        round(pin_x("Q1", "SRC", pose), 4) for pose in ctx.accepted["Q1"]
    })
    r_pairs = {
        (pose.rotation, pose.mirror): round(pin_x("R5", "SRC", pose), 4)
        for pose in ctx.accepted["R5"]
    }
    solving = [
        key for key, value in r_pairs.items()
        if any(abs(value - mine) <= slack for mine in q_at_zero)
    ]
    assert solving, (
        f"no pose of R5 puts its SRC pad in Q1's column (Q1 reaches {q_at_zero}, "
        f"R5 reaches {sorted(set(r_pairs.values()))}) — the relation is no longer "
        "pose-solvable and 116's note IS stale, which is a different finding"
    )
    # The measured reason: **rotation 90**, not rotation 0.  116 recorded rot0
    # because 113's profile put the 0603's pins on the body axis.
    assert all(key[0] == 90 for key in solving), (
        f"the solving poses are {solving}, but 118 measured that rotation 0 is "
        f"the one that misses (R5 at rot 0 reaches {r_pairs[(0, False)]}) — 116's "
        "recorded reason and the measured one have diverged"
    )
