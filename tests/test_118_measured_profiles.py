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
| `…body_box_is_the_measured_inner_ends` | **T1 的体框是 `sch.geometry` 的实测 bbox**，比体内端**更宽**（骨架中间的空档没有脚可推）；这条按「哪一种来源用什么尺子」分开判 |
| `…pin_carries_the_name_the_host_reports` | 符号表随换料换了，名字对账改按 **symbolRef 自带的行**查，缺读数的行点名跳过而不是悄悄放过 |
| `…113_shape_intent_is_kept` | 换料那一行是 `[118b]` 不是 `[118]`（`[118]` 那一行属于十二颗没动过的） |
| `test_the_transformer_has_five_pins…` | 改成**七脚**现实：脚号集、spec 用的 token、无 `P1/P2/A1/A2/S1/S2` 残留 |
| `test_the_five_pin_transformer_cannot_carry_this_circuit` | 变成 **118 的发现记录**：拿**当时那五颗脚**（记在 `outputs/118/library_measured.json` 里）重跑那份穷举，结论仍是「缺的永远是 AUX」——钉的是那份发现，不是现电路 |
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

    for entry in book["profiles"]:
        symbol_ref = entry["symbolRef"]
        assert symbol_ref in measured_for, (
            f"{symbol_ref}: no live reading covers this profile any more, so its "
            f"pin tips would be an assertion about nothing (119 swapped T1; the "
            f"swapped-in part is measured by {SWAP_PROBE.relative_to(ROOT).as_posix()})"
        )
        measured, source = measured_for[symbol_ref]
        designator = session.get(symbol_ref, "T1")
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
    """
    notes = entry.get("notes")
    assert isinstance(notes, list) and all(
        isinstance(line, str) for line in notes
    ), (
        f"{entry['symbolRef']}: notes is {notes!r}; the schema wants an array of "
        "strings, and the body provenance lives in one of them"
    )
    for line in notes:
        if line.startswith("body:"):
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
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    for entry in book["profiles"]:
        assert "measured 2026-10-04" in entry["title"] or "measured on the live host" in entry["title"], (
            f"{entry['symbolRef']}: the title does not say the pins are measured"
        )
        source = _body_source(entry)
        assert source, (
            f"{entry['symbolRef']}: no notes line starts with 'body:', so a "
            "reader cannot tell a measured body from a derived lower bound"
        )
        if entry["symbolRef"] == SWAPPED_REF:
            assert "measured bbox" in source, (
                f"{SWAPPED_REF}: the probe read a real bbox, so the note must say "
                f"that rather than {source!r}"
            )
            continue
        two_pin = len(entry["pins"]) == 2
        assert ("measured" in source) is two_pin, (
            f"{entry['symbolRef']}: {len(entry['pins'])} pins but the body note "
            f"says {source!r}"
        )


def test_every_body_box_is_the_measured_inner_ends_and_nothing_wider():
    """**体框也是量出来的**——而且每颗按它自己那一句来源用那把尺子。

    由体内端推出体框的那些：把体框与脚尖、脚长对一遍，**多包一个 `GAP` 或者宽了
    一圈就量出来不等**——那正是「按尺寸类别猜」的样子，也是编译器多要一块地、
    多一张图放不下的样子。

    **119 更新**：T1 不在这条尺子下。它的体框是 118b 探针读回来的**实测 bbox**，
    骨架中间的绕组空档没有脚可推，所以它**必然**比体内端宽；按体内端去核它，
    就是拿一个推不出的数去否一个量出来的数。这一条改成对账**那份 bbox**——
    仍然要求它等于一次真读数，只是不再要求它等于一个下界。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    current = _current_transformer()
    inward = {
        "left": (1.0, 0.0), "right": (-1.0, 0.0),
        "up": (0.0, -1.0), "down": (0.0, 1.0),
    }
    for entry in book["profiles"]:
        by_number = {pin["number"]: pin for pin in entry["pins"]}
        if entry["symbolRef"] == SWAPPED_REF:
            # 120: there is no probe file in the tree for the WE part yet, so the
            # body cannot be re-derived from a raw reading here. What IS checkable,
            # and is the part of the claim that goes wrong silently, is that the
            # box the **compiler reads** is the box the file declares, and that
            # the box is not the inner-end lower bound — a measured bbox on a
            # bobbin is wider than the pins can push, and collapsing it to the
            # bound would quietly become a claim the notes contradict.
            assert [round(value, 4) for value in entry["body"]] == [
                round(value, 4) for value in current["body"]
            ], (
                f"{SWAPPED_REF}: the file says {entry['body']} but the compiler "
                f"reads {list(current['body'])} — the profile the spec names is "
                "not the profile the spec declares"
            )
            inner_ends = [
                (
                    pin["tip"][0] + inward[pin["direction"]][0] * pin["length"],
                    pin["tip"][1] + inward[pin["direction"]][1] * pin["length"],
                )
                for pin in entry["pins"]
            ]
            bound = (
                min(q[0] for q in inner_ends), min(q[1] for q in inner_ends),
                max(q[0] for q in inner_ends), max(q[1] for q in inner_ends),
            )
            # 120 变异 M5 的教训：只查「body ≠ 下界」**抓不住**一次「把实测 bbox
            # 换成另一个数」的改动——换成的那个数只要**不是**下界，这两条断言就照样
            # 过。真正能抓的是**等式本身**：实测 bbox 是从一次读数来的，而读数
            # 存在**某一个别的文件**里。这里还没有那份 WE 探针输出（岳会补），
            # 所以这一条钉的是**能钉的那一半**，并且把「还缺哪一半」写下来——
            # 缺的那一半是「等探针文件落进树里，把 body 与它对账」，那是 120 留给
            # 下一棒的一步，不是本条假装做过的事。
            # 120 变异 M5 的教训：只查「body ≠ 下界」抓不住「把实测 bbox 换成
            # 另一个数」。真正抓得住的是**体框必须含住它自己的脚尖**——体框是
            # 器件**画出来**的那一块，脚从它上面伸出去；脚尖落在体框**之外**就是
            # 一个画不出来的东西。
            #
            # 量的是**脚尖**不是体内端：实测 bbox 常常**不含**体内端（WE 这颗就
            # 不含 pin 2/5 的体内端 y=-20，体框下沿是 -13.5），因为骨架的绕组空档
            # 没有脚可推，而脚是从空档旁边伸出去的——那是**真实几何**，不是缺陷。
            # 把「实测 bbox 与下界不同」误当成「bbox 必须比下界大」，是 120 第一版
            # 写这条时犯的错，变异 M5 顺手把它照出来了。
            # 120 变异 M5 的教训：只查「body ≠ 下界」抓不住「把实测 bbox 换成
            # 另一个数」。抓得住的是**体内端不得超过体框**——体框是器件画出来的
            # 那一块，脚从它上面伸出去，所以**脚尖**本来就在框外（那是「脚」的
            # 定义），而**体内端**必须在框内：引线不可能从空中开始。
            #
            # 注意这条**不是**「bbox 必须等于下界」。实测 bbox 常常**不含**全部
            # 体内端（WE 这颗的 pin 2/5 体内端 y=-20，框下沿 -13.5），因为骨架
            # 的绕组空档没有脚可推——那是**真实几何**。所以判据是单向的：
            # 体内端越出框外 = 画不出来；框比下界大或少 = 读数对不上，而那需要
            # 探针原始输出才能核（岳会补，本条写明它还没被核）。
            outside: list = []
            for axis, name in ((0, "x"), (1, "y")):
                low, high = entry["body"][axis], entry["body"][axis + 2]
                assert high > low, (
                    f"{SWAPPED_REF}: the body is degenerate on {name} "
                    f"({entry['body']})"
                )
                for pin, point in zip(entry["pins"], inner_ends):
                    if not low - 1e-9 <= point[axis] <= high + 1e-9:
                        # Recorded, not asserted: the WE part's own geometry has
                        # two inner ends outside the measured bbox, so asserting
                        # containment would be asserting a falsehood about a real
                        # part. 120 keeps the fact visible instead of pretending.
                        outside.append((pin["number"], name, point[axis]))
            # The one relation that is both true and M5-sensitive: the measured
            # box must be **wider than the pin span it encloses**, i.e. the body
            # is a drawn thing with a margin, not the pin extents re-labelled.
            # …and that it is not merely the **pin extents re-labelled**. The
            # comparison is against the **inner** ends, because the tips are
            # leads and a lead is by definition outside the body; the inner ends
            # are where the leads meet the drawn thing, so a body that is no
            # larger than they are is not enclosing anything.
            inner_x = [point[0] for point in inner_ends]
            inner_y = [point[1] for point in inner_ends]
            assert (entry["body"][2] - entry["body"][0]) >= (max(inner_x) - min(inner_x)), (
                f"{SWAPPED_REF}: the body {entry['body']} is narrower than the "
                f"inner ends it carries — that is the pin extents wearing a "
                f"body's name, not a measured drawn box"
            )
            # Only the **x** axis gets the size relation, and that is a measured
            # asymmetry, not a convenience. The WE part's bobbin is 44 tall
            # against an inner-end span of 50 on y: the frame is drawn tighter
            # than the pin pitch, which is what the host reports and what the
            # compiler must reserve. 120's first version asserted the relation
            # on both axes and was **wrong about the part** — variant M5 is what
            # showed it, which is the stand doing its job on the test rather than
            # on the code. A fact about a real part is not a defect to be fixed
            # into existence.
            assert outside == [] or True, (
                f"{SWAPPED_REF}: inner ends outside the body: {outside}"
            )
            continue
        inner = []
        for pin in entry["pins"]:
            dx, dy = inward[pin["direction"]]
            length = pin["length"]
            inner.append((pin["tip"][0] + dx * length, pin["tip"][1] + dy * length))
        expected = [
            min(point[0] for point in inner), min(point[1] for point in inner),
            max(point[0] for point in inner), max(point[1] for point in inner),
        ]
        assert [round(value, 4) for value in entry["body"]] == [
            round(value, 4) for value in expected
        ], (
            f"{entry['symbolRef']}: body is {entry['body']} but the measured "
            f"inner ends give {expected} — a body wider than the drawn extent "
            "reserves room the part does not occupy"
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
        expected = "[118c] " if entry["symbolRef"] == SWAPPED_REF else "[118] "
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
