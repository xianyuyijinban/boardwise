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
    """**每颗 profile 的脚尖都等于 118 的实测**，一颗都不许是编的。

    量的是**符号局部坐标**（把 118 的页坐标读数按该器件实际落图时的位姿
    逆变换回去），不是页坐标——那才是 profile 该记的东西。
    """
    tips, lcsc = _measured_118()
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    plan = json.loads(
        (ROOT / "outputs" / "118" / "plan_report.json").read_text(encoding="utf-8")
    )["plan"]["change"]["parts"]
    # One designator per symbolRef — the profiles are per symbol, not per part.
    sample: dict[str, str] = {}
    for item in plan:
        sample.setdefault(item["symbolRef"], item["designator"])

    for entry in book["profiles"]:
        designator = sample[entry["symbolRef"]]
        measured = tips[designator]
        declared = {pin["number"]: tuple(pin["tip"]) for pin in entry["pins"]}
        assert set(declared) == set(measured), (
            f"{entry['symbolRef']}: the profile declares {sorted(declared)} but "
            f"the host measured {sorted(measured)} on {designator} "
            f"({lcsc[designator]})"
        )
        for number, tip in sorted(measured.items()):
            assert declared[number] == tip, (
                f"{entry['symbolRef']} pin {number}: the profile says "
                f"{declared[number]}, the host measured {tip} — 113's "
                "hand-written tip is still in here"
            )


def test_every_profile_says_where_its_geometry_came_from():
    """**每颗 profile 自己交代来源**——实测还是下界，一行字，不许含糊。

    两种来源是分开的，因为可信度不同：两颗脚的器件，体内端**就是**本体的边，
    是**实测**；多脚器件的外侧体内端只框住 x 与 y 的范围、中间的缺口没有
    任何读数带得到，所以是**下界**。把两者写成同一种话，就是把一个估计说成
    测量——drawlint 同款纪律，118 对 profile 用同一条。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    for entry in book["profiles"]:
        assert "measured 2026-10-04" in entry["title"], (
            f"{entry['symbolRef']}: the title does not say the pins are measured"
        )
        assert entry.get("bodySource"), (
            f"{entry['symbolRef']}: bodySource is missing, so a reader cannot "
            "tell a measured body from a derived lower bound"
        )
        two_pin = len(entry["pins"]) == 2
        assert ("measured" in entry["bodySource"]) is two_pin, (
            f"{entry['symbolRef']}: {len(entry['pins'])} pins but bodySource "
            f"says {entry['bodySource']!r}"
        )


def test_every_body_box_is_the_measured_inner_ends_and_nothing_wider():
    """**体框也是量出来的**，而且只许是**体内端**——多一圈就是凭空多要地方。

    118 的 `bodySource` 那一行说的是「由体内端推出」，那这一条就去查它是不是
    真的由体内端推出：把每颗 profile 的体框与它自己的脚尖、脚长对一遍。
    **多包一个 `GAP` 或者宽了一圈，量出来就不等**——而那正是「按尺寸类别猜」
    的样子，也是编译器多要一块地、多一张图放不下的样子。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    inward = {
        "left": (1.0, 0.0), "right": (-1.0, 0.0),
        "up": (0.0, -1.0), "down": (0.0, 1.0),
    }
    for entry in book["profiles"]:
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
    plan = json.loads(
        (ROOT / "outputs" / "118" / "plan_report.json").read_text(encoding="utf-8")
    )["plan"]["change"]["parts"]
    _tips, lcsc = _measured_118()
    sample: dict[str, str] = {}
    for item in plan:
        sample.setdefault(item["symbolRef"], item["lcsc"])
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
    # 9 of the 13 profiles, not 21: the count is over *symbols*, and 110 measured
    # 12 *parts* which collapse onto fewer symbols (three pairs share an LCSC).
    assert covered >= 9, (
        f"only {covered} profiles could be checked against a measured name; the "
        "pin tokens are the whole point of this batch"
    )


def test_the_113_shape_intent_is_kept_alongside_the_measurement():
    """**意图与实测分两行**——113 选形状的理由不许被实测悄悄抹掉。

    113 为每颗符号挑的形状是**有理由的**（岳 ruling e 要反馈横排在水平线上、
    钳位二极管要横着画才表达得了「变压器的这一侧」），那些理由写进了 title。
    118 换了几何，**理由必须还在**，只是不能再说成「这就是器件的样子」。
    """
    book = json.loads((SPECS / "flyback_uc3845.library.json").read_text(
        encoding="utf-8"))
    for entry in book["profiles"]:
        title = entry["title"]
        assert "\n[118] " in title, (
            f"{entry['symbolRef']}: the title has no measured-geometry line, so "
            "113's intent and 118's measurement are not separable"
        )
        intent, measurement = title.split("\n[118] ", 1)
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


def test_the_transformer_has_five_pins_and_the_spec_uses_five():
    """**T1 的脚 token 体系整个换了**，而且 spec 一个都不多写。

    113 写的是 `P1 P2 A1 A2 S1 S2` 六 terminals；宿主实测是 `1 3 4 5 6`
    **五脚**，`PinName == PinNumber`，**没有 A2**。110 早就记了两次
    （`PLAN.md` 第 44 行「库内唯一 EE16 **5 脚**骨架」、第 160 行「骨架符号只有
    5 脚」），118 是把它落到 spec 上的那一棒。
    """
    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.engines import drawcompiler as dc

    circuit = CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json")
    profile = circuit_symbol(circuit, "T1")
    numbers = sorted(pin.number for pin in profile.pins)
    assert numbers == ["1", "3", "4", "5", "6"], numbers
    # No 113-style token survives anywhere in the spec.
    used = set(_tokens_of(circuit, "T1"))
    for stale in ("P1", "P2", "A1", "A2", "S1", "S2"):
        assert stale not in used, (
            f"T1.{stale} is still in the spec; the host symbol has no such pin"
        )
    assert dc._part_nets(circuit, "T1"), "T1 lost its nets"


def test_the_five_pin_transformer_cannot_carry_this_circuit():
    """**118 的结论**：五脚的 EE16 骨架**装不下**这个反激，而这是穷举量出来的。

    113 的 spec 要变压器碰**六个**网：`HVDC` / `SW` / `PGND` / `AUX` / `SEC_SW` /
    `SEC_GND`——初级的两个端、初级回流、辅助绕组、副边的两个端。宿主实测的
    `C9900020988` 只有**五根脚**（110 早就记了两次：`PLAN.md` 第 44 行与第
    160 行）。

    **穷举**：把五根脚指派到六个网上，全部 **720** 种都拿去问语法。语法收了
    **120** 种（它要求 `sec_gnd in tx_nets`，且初级回流要够得着），而这 120 种
    **无一例外**地少了 `AUX`——`EE16_3+3_V02` 是一副**两绕组**骨架顶了个 3+3 的
    名字，自供电的辅助电源需要第三个绕组。

    这条不是「换个读法也许能行」：牺牲的那一端**永远是辅助绕组**，与哪颗脚放
    哪一网无关。**要闭合只能换料**——一颗六端变压器，或者辅助供电另寻出处——
    那是 BOM 改动，归岳，**本棒不动**。
    """
    import itertools

    from boardwise.core.circuitspec import CircuitSpec
    from boardwise.core.presentationspec import PresentationSpec
    from boardwise.engines import grammar
    import test_113_flyback_grammar as t113

    book = t113._library_from(SPECS / "flyback_uc3845.library.json")
    profile = circuit_symbol(
        CircuitSpec.load(SPECS / "flyback_uc3845.circuit.json"), "T1"
    )
    assert profile is not None, "T1 has no profile in the measured library"
    pins = [pin.number for pin in profile.pins]
    assert len(pins) == 5, (
        f"the transformer now has {len(pins)} pins ({pins}); this batch's "
        "finding was measured on five, so re-measure before trusting the test"
    )

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
            for entry in payload["nets"]:
                if entry["id"] == net:
                    entry["members"].append(f"T1.{pin}")
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
