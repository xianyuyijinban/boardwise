"""188a — 电容尾从「NT 这一家的包装码」改成那个字段的**结构** + 量不是电阻的前缀。

两块，都来自 184 面的挖洞报告（v0.5.13 发布闸 swarm agent-342 中-1/中-2/中-3）：

* **尾是结构，不是包装码**（中-1）。184 的读法本身是结构性的（容差字母前那个三元
  组是值码），触发它的却是一个字面串 ``NT``：同一个字段换一家包装就整 token 拒读
  （``FCC0603B103K500CT`` 与 ``0603B103K500NT`` 是同一字段，一个 None 一个 103）。
  货架自己 11 颗电容属于这一类，两块在库夹具板上另有 7 个电容位号（``Value`` 空）
  因「值不可知」上榜。放宽是**有代价**的：裸放宽（``NT`` → ``[A-Z]{2,4}``）在全库
  136,893 个 MPN 形 token 上新增命中 29 个，其中 6 个是误命；守卫把它们分成两档处理
  （见 :data:`FRAGMENT_FALSE_HITS` / :data:`RESTORED_BY_RULING`）。
* **新 reader 缺封装码豁免**（中-2）。``_cap_voltage_tail_code`` 只 ``search``，不
  查 group1 的整段数字是不是**封装尺寸码的尾段**——旧的 ``_voltage_rating_tail``
  正是靠这条豁免让 ``X0402K500NT`` 走老路。结果是新 reader 把老读数顶掉
  （``500`` → ``402``）。本批复用同一条 ``_digit_run`` 判法。
* **FB/RV 不是电阻**（中-3）。``_value_decodable`` 的 MPN 兜底把磁珠/压敏的数交给
  电阻 candidates 读，与仓库自己的 ``rules/facts.py::_resistor_like``（"a ferrite's
  600 is not a resistor"）两把尺；``mpn_resistance_candidates`` 的 docstring 自己写
  了「只有已经知道这是电阻的调用方才能问它」。``RT`` 同一条（B 常数不是电阻），
  ``RP``（排阻）保留（它的声明值**就是**电阻）。

守卫的**最终形态**（岳 2026-10-16 裁点 1）：两分支，读与不读都出一条理由——

1. **group1 是整段数字**（``_digit_run`` 返的就是它）→ 读。这是自成一个字段的数
   （``FS32X106K101EGG``→106、``TAJB107K006RNJ``→107、``CGA0603X7R104K500JT``→104）；
2. 否则 **token 自己报了封装尺寸**、且 group1 不落在 ``_PACKAGE_TAILS`` 里 → 读。
   这是货架 华新科/风华 那一族：介质码的末位数字粘在值码前面
   （``HGC0603R``**5**``106M250``、``HHV1206R``**7**``475K101``），而 token 的
   ``0603``/``1206`` 就是 071 §1 C 的 ``ANCHOR_PACKAGE_CONTEXT``。

两分支都不满足即拒读。裁点 1 之前的第一版只留了分支 2（「必须报尺寸」），把
``FS32X106K101EGG``（fixture 板上 C4，板上 Value 空）和 ``TAJB107K006RNJ`` 一起拒了；
只留「整段数字」分支则会拒掉货架自己的 4 颗（值码被介质码粘住）——所以两条都要。

本文件只钉源码读数与闸门；实板/全库的测量在 ``outputs/188a/evidence.md``。板框细长
环的披露在 ``tests/test_188a_slender_outline.py``。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise.core.model import Component, DesignModel
from boardwise.core.values import (
    ANCHOR_PACKAGE_CONTEXT,
    _cap_voltage_tail_code,
    _non_eia_notation,
    decode_eia_3digit,
    mpn_resistance_candidates,
    mpn_value_code,
    mpn_value_code_anchor,
    parse_capacitance_farads,
)
from boardwise.engines.checkup import (
    UNKNOWN_REASON_UNDECODABLE,
    _value_decodable,
    unknown_parts,
)

ROOT = Path(__file__).resolve().parents[1]
SHELF = ROOT / "blocklib" / "parts.json"
_CAP_BASE = 1e-12

#: 裸放宽实测的 6 处误命（agent-342 的清单）里，**本批仍然拒读的 4 处**。三元组 =
#: （token，**裸**放宽会答出的读数，本批的读数）：前两个是「顶读」——``805`` 会把
#: 既有的正确读数顶掉，所以本批回到既有读数；后两个整条拒读。四处都是**同一个理由**：
#: group1 只是更长一串数字的尾巴（``0805`` 的尾段 / ``6206`` 的尾段 / 电感尺寸
#: ``252012`` 的尾段），而 token 里没有任何封装尺寸码可以说明它是什么。
FRAGMENT_FALSE_HITS = (
    ("FRC0805J471TSD", "805", "471"),   # FRC 电阻：805 是它的尺寸 0805 的尾段
    ("KRMV0805G350NXT", "805", "350"),  # 同上
    ("XC6206P332MR", "206", None),      # 一颗稳压器：206 是 6206 的尾段，token 无尺寸码
    ("FTC252012S100MBCA", "012", None),  # 货架自己的 10 µH 电感（ind.ftc252012s100mbca）
)

#: 同一个清单里**被裁点 1 救回来的 2 处**：它们的 group1 本身就是一整段数字，读出来
#: 的值也对（``FS32X…`` 是 fixture 板 `ProPrj_高速电机控制器` 的 C4、板上 Value 空，
#: 10 µF；``TAJB107K006RNJ`` 是 100 µF 钽电容）。第一版守卫（「必须报尺寸」）把它们
#: 一起拒了，岳 2026-10-16 裁定改为两分支守卫。
RESTORED_BY_RULING = (
    ("FS32X106K101EGG", "106", 1e-5),      # 10 µF
    ("TAJB107K006RNJ", "107", 1e-4),       # 100 µF
)

#: 184 抢读的见证：pre-184 读 ``500``（token 里没有值码，那是老读数的老毛病），
#: 184 换成封装尺寸码的尾段 ``402``/``206``/``603``/``210``。本批回到 pre-184。
PREEMPTED = ("X0402K500NT", "CC1206K500NT", "GRM0603K500NT")

#: 015 的拒读见证，一条都不许复活：电解（案例尺寸/电压前缀）、TDK 的厚度尾料号
#: （``C1608X5R1V225KT000E``，尾后只有 1 个字母，根本不成这个字段）、聚合物 µF 系列。
#: 与尾的包装码无关——它们不是那个字段。
#:
#: ``C1608X7R1H104K080AB`` **不在**名单里（188a 裁点 1 后它读 ``104``）：TDK 那条
#: 「尾三数字是厚度不是耐压」的拒读是 :func:`mpn_voltage_rating` 的事（#72，一行未动），
#: 而**值码** 104 本来就是它的值（100 nF）——读出来是对的，只是无锚（token 里没有
#: 封装尺寸码）。下面单列一条把这件事钉住，免得有人把两者混为一谈。
REFUSALS_015 = (
    "PA50V330M10x15",
    "C1608X5R1V225KT000E",
    "SPZ1HM100E07O00RAXXX",
)

#: 值读得出、但**无锚**的 token（裁点 1 的代价之一）：TDK 的厚度尾料号（值码 104 是
#: 对的，三数字厚度尾是**耐压** reader 的拒读对象）、两颗被裁点 1 救回来的料号，
#: 以及没有尺寸的裸尾。
UNANCHORED_TAIL_READINGS = (
    "C1608X7R1H104K080AB",
    "FS32X106K101EGG",
    "TAJB107K006RNJ",
    "225K250NT",
)


def component(designator: str, *, value: str = "", mpn: str = "", supplier: str = "C1") -> Component:
    return Component(
        uid=f"u-{designator}", designator=designator, value=value, footprint="",
        mpn=mpn, lcsc_part=supplier, props={},
    )


def gate(prefix: str, mpn: str, value: str = "") -> bool:
    """``_value_decodable`` for one synthetic part."""
    return _value_decodable(prefix, component(f"{prefix}1", value=value, mpn=mpn))


def shelf_entries():
    raw = json.loads(SHELF.read_text(encoding="utf-8"))
    return raw["parts"] if isinstance(raw, dict) else raw


# ---------------------------------------------------------------------------
# 中-1：尾是那个字段的结构，不是一家包装码
# ---------------------------------------------------------------------------


def test_the_structural_tail_reads_the_shelves_own_capacitors():
    """货架 11 颗电容：这个**字段**读出值码，且与货架自己声明的 value 同值。

    两个独立读数必须同值——这是放宽的**实测出处**，也是 184 那条货架对拍的电容
    半边（电阻半边在 ``tests/test_184_value_decode_coverage.py``）。11 是实测数，
    不是白名单：货架 30 颗电容里 11 颗用这个字段印值码，其余用别家的拼法
    （``CL05B104KB54PNC``、``CC0603KRX7R9BB104`` …，它们由白名单那条路读，不属
    本批的字段——所以这里按 :func:`_cap_voltage_tail_code` 过滤，而不是按
    ``mpn_value_code``）。
    """
    checked = 0
    for entry in shelf_entries():
        key = entry.get("key", "")
        if not key.startswith("cap."):
            continue
        token = entry.get("mpn") or ""
        if _cap_voltage_tail_code(token) is None:
            continue
        code = mpn_value_code(token)
        declared = parse_capacitance_farads((entry.get("value") or "").strip())
        assert code is not None and declared is not None, (key, token, entry.get("value"))
        assert decode_eia_3digit(code, _CAP_BASE) == pytest.approx(declared), (
            key, token, entry.get("value"), code
        )
        checked += 1
    assert checked == 11, checked


def test_the_fragment_false_hits_are_still_refused():
    """裸放宽的 6 处误命里，group1 只是**更长数字的尾巴**的 4 处：仍然全挡。

    每一处都记着裸放宽会答什么、本批答什么（见 :data:`FRAGMENT_FALSE_HITS`）。
    它们被拦的理由是同一条：``0805``/``6206``/``252012`` 这些更长的数字串，group1 只是
    它的尾段——而 token 里又没有封装尺寸码能说明那串是什么。``FTC252012S100MBCA``
    顺手给出一条**货架自己**的反例：它是 ``ind.ftc252012s100mbca``，声明 10 µH——
    ``012`` 那个读数与货架自身的声明矛盾，所以这里拒读不是保守，是唯一正确的答案。
    """
    for token, bare_reading, expected in FRAGMENT_FALSE_HITS:
        assert _cap_voltage_tail_code(token) is None, (token, bare_reading)
        assert mpn_value_code(token) == expected, (
            token, bare_reading, expected, mpn_value_code(token)
        )
    # 货架自己的那条横证：这颗料是电感，不是电容。
    shelf = {entry["key"]: entry for entry in shelf_entries()}
    assert shelf["ind.ftc252012s100mbca"]["mpn"] == "FTC252012S100MBCA"
    assert shelf["ind.ftc252012s100mbca"]["value"] == "10uH"


def test_the_tail_reader_reads_by_two_branches_and_says_which():
    """守卫的**最终形态**（岳 2026-10-16 裁点 1）：两个分支，各有各的理由。

    分支 1「group1 是整段数字」= 自成一个字段的数；分支 2「token 报了封装尺寸、
    group1 又不是尺寸码的尾段」= 货架 华新科/风华 那一族（值码被介质码的末位数字
    粘住：``R``**5**``106``、``R``**7**``475``），而 token 的尺寸就是 071 §1 C 的
    ``ANCHOR_PACKAGE_CONTEXT``。两分支都不满足 → 拒读（下一节那 4 处）。

    这条测试把**两个分支各自的见证**都钉住，免得下一批只留一条又把另一半弄丢
    （裁点 1 前就是这样：只留分支 2 拒了 ``FS32X106K101EGG``/``TAJB107K006RNJ``，
    只留分支 1 拒了货架 4 颗）。
    """
    # 分支 1：整段数字（token 里没有尺寸码也读）。
    for token, code, farads in RESTORED_BY_RULING:
        assert _digit_run_of_value(token) == code, token
        assert mpn_value_code(token) == code, token
        assert decode_eia_3digit(code, _CAP_BASE) == pytest.approx(farads), token
    # 分支 2：值码被介质码粘住，但 token 报了尺寸。
    for token, code in (
        ("HGC0603R5106M250NTHJ", "106"),   # R5 + 106
        ("HHV1206R7475K101NSPJ", "475"),   # R7 + 475
        ("HHV0805R7225K101NSLJ", "225"),
    ):
        assert _digit_run_of_value(token) != code, (token, "这一族的值码不是整段数字")
        assert mpn_value_code(token) == code, token
    # 两分支的**共同**代价：没报尺寸、值码又不是整段数字的，一律不读
    # （``R5106K500NSPJ`` 是文档里被截断的 HHV 料号）。
    assert mpn_value_code("R5106K500NSPJ") is None
    assert mpn_value_code("R7475K101NSPJ") is None


def _digit_run_of_value(token: str) -> str:
    """The digit run the tail's value group sits in (test-side helper)."""
    from boardwise.core.values import _CAP_VOLTAGE_TAIL_RE, _digit_run

    match = _CAP_VOLTAGE_TAIL_RE.search(token)
    assert match is not None, token
    return _digit_run(token, match.start())


def test_an_unanchored_tail_reading_is_the_price_of_the_ruling():
    """锚：报尺寸的尾读数带锚，其余不带——071 §1 C 让它们只能无声地对不上板。

    裁点 1 之前，本 batch 的第一版把 ``has_package_context`` 当成尾 reader 的**前置
    条件**，「这个 reader 读出来的都带锚」由此成为构造性不变量；放宽成两分支后不再
    成立：``FS32X106K101EGG``/``TAJB107K006RNJ``/``225K250NT`` 的读数**无锚**。
    这条测试把代价写进机器可读的断言里，免得它变成一句记忆。
    """
    for token in ("CGA0603X7R104K500JT", "HGC0603R5106M250NTHJ", "0603S226M6R3CT"):
        code, anchor = mpn_value_code_anchor(token)
        assert code is not None and anchor == ANCHOR_PACKAGE_CONTEXT, token
    for token in ("FS32X106K101EGG", "TAJB107K006RNJ", "225K250NT"):
        code, anchor = mpn_value_code_anchor(token)
        assert code is not None and anchor == "", token
    # 无锚读数仍由白名单那条路给出，本批没有动它（防「顺手收紧白名单」）。
    assert mpn_value_code_anchor("CL10B104KB8NNNC") == ("104", "")


def test_the_tdk_thickness_tail_reads_its_value_but_not_its_rating():
    """TDK 的 ``C1608X7R1H104K080AB``：**值**读得出（104），**耐压**仍拒读（#72）。

    两者是不同的读者、不同的问题：``104`` 是这颗料的 EIA 值码（100 nF，读对了），
    而尾上的 ``080`` 是厚度（0.8 mm）——把它当 8 V 会假报一颗 50 V 的料超压，所以
    :func:`mpn_voltage_rating` 那条路照旧拒读（072，本批一行未动）。188a 裁点 1 之前
    这条值读数是顺带被「必须报尺寸」的守卫挡掉的；现在它在，且**无锚**（token 里没有
    封装尺寸码 ``C1608`` 是 TDK 的尺寸拼法，不在本仓的尺寸表里）。
    """
    from boardwise.core.values import mpn_voltage_rating

    assert mpn_value_code("C1608X7R1H104K080AB") == "104"
    assert decode_eia_3digit("104", _CAP_BASE) == pytest.approx(1e-7)
    assert mpn_voltage_rating("C1608X7R1H104K080AB") is None, "厚度不是耐压（#72）"
    assert mpn_value_code_anchor("C1608X7R1H104K080AB") == ("104", "")


def test_the_6r3_rating_and_the_ct_packaging_name_their_value():
    """worker 核实过的两颗真料号：Walsin 的 ``CT`` 包装与 ``6R3`` 耐压档。

    ``6R3`` 是 6.3 V（``R`` 是小数点），所以耐压那一组不是「三个数字」——
    :data:`_CAP_VOLTAGE_TAIL_RE` 的第二组两条路都收。
    """
    assert mpn_value_code("0603S226M6R3CT") == "226"
    assert decode_eia_3digit("226", _CAP_BASE) == pytest.approx(2.2e-5)
    assert mpn_value_code("0603B104K500CT") == "104"
    assert decode_eia_3digit("104", _CAP_BASE) == pytest.approx(1e-7)


def test_a_package_size_fragment_is_never_taken_for_a_value():
    """中-2：group1 是封装尺寸码的尾段时豁免（复用 ``_voltage_rating_tail`` 判法）。

    这三个 token 里没有值码，pre-184 答 ``500``（老白名单的老毛病），184 答
    ``402``/``206``/``603``（新 reader 抢读）。本批把抢读关掉，读数回到 pre-184 的
    ``500``——「新 reader 只加读、不改旧读」这条不变式恢复。
    """
    for token in PREEMPTED:
        assert mpn_value_code(token) == "500", token
    # 带尺寸头的兄弟形态同样不读（184 曾答 402/210）。
    for token in ("CGA0603X7R0402K500NT", "CGA0603X7R1210K500NT"):
        assert mpn_value_code(token) is None, token


def test_the_015_electrolytic_and_tdk_witnesses_keep_their_refusal():
    """015/046/072 的见证仍 None——放宽只碰那个字段，不碰拒读本身。

    ``_non_eia_notation`` 一行未改：它对这些 token 仍然是 True（拒读），变化的只是
    ``mpn_value_code`` 在问它之前先问了电容尾 reader，而尾 reader 现在只在**这个
    字段**上答话。
    """
    for token in REFUSALS_015:
        assert mpn_value_code(token) is None, token
    # 拒读行为本身在：同一批 token，两条路都问一遍。
    assert _non_eia_notation("PA50V330M10x15") is True
    assert _non_eia_notation("C1608X5R1V225KT000E") is True
    # 而尾 reader 抢读的那一族，拒读**依然在**——只是被更窄的读数先答了。
    assert _non_eia_notation("HGC1206R5106K500NSPJ") is True
    assert mpn_value_code("HGC1206R5106K500NSPJ") == "106"


# ---------------------------------------------------------------------------
# 中-3：量不是电阻的前缀，不走电阻 candidates
# ---------------------------------------------------------------------------


def test_a_ferrite_bead_is_not_asked_for_a_resistance():
    """``FB``：磁珠的量是 100 MHz 阻抗，不是电阻。

    这些 MPN 在 candidates 侧都有一处中缀形状，184 的闸门因此判「值已知」——读数
    是编出来的（``BRC2016T101K`` 的 ``101`` 是 100 Ω@100MHz，被读成 1 kΩ/101 kΩ）。
    EIA code 那一路照旧（``BLM15HD102SN1D`` 的 ``102`` 仍是读数）；**板上 Value**
    那一路也照旧（磁珠板上写 ``600Ω`` 时闸门照样放行——本批只改 MPN 侧）。
    """
    for token in (
        "BRC2016T101K", "NLCV32T-100K-PF", "Y-3.2X2.5MM", "UPZ2012E102-2R0TF",
    ):
        assert mpn_resistance_candidates(token), token  # 读数还在（reader 未动）
        assert gate("FB", token) is False, token
    # 同一个 MPN 落在电阻位号上仍然放行——两把尺的差别就在位号说这颗料是什么。
    assert gate("R", "BRC2016T101K") is True
    # EIA code 与板上 Value 两条路都还在。
    assert gate("FB", "BLM15HD102SN1D") is True
    assert gate("FB", "BRC2016T101K", "600Ω") is True


def test_a_varistors_gate_no_longer_rests_on_the_resistance_candidates():
    """``RV``：压敏的量是电压。闸门的答案 === ``mpn_value_code`` 的答案。

    14D471K 类的 candidates 给出 1 kΩ/71 kΩ/471 kΩ 三个读数——都是把压敏电压码当
    电阻读；184 的闸门靠它放行。现在两个读数都只剩 EIA code 那一路（``471`` 本身
    是这颗料的电压码，读数没错），等式就是这条规则的钉子。
    """
    for token in ("7D471K", "14D471K", "10D471K", "S07K300", "V275LA20AP"):
        assert gate("RV", token) is (mpn_value_code(token) is not None), token
    # candidates 只读得出电阻的那类 MPN：R 位号放行、RV 位号不放行。
    assert gate("R", "RC0603FR-071KL") is True
    assert gate("RV", "RC0603FR-071KL") is False
    assert mpn_resistance_candidates("RC0603FR-071KL"), "reader untouched"


def test_a_thermistors_b_constant_is_not_a_resistance():
    """``RT``：热敏的 MPN 给的是 R25 与 **B 常数**，不是电阻。

    ``MF52-103/3435`` 的 ``3435`` 按 E-96 形状读成 34.3 MΩ——184 的闸门就此把一颗
    板上没有 Value 的热敏判成「值已知」。reader 不动（那个读数仍在），闸门不再问它。
    板上写了 ``10kΩ`` 的热敏照旧放行（第一档分支）。
    """
    readings = {ohms for ohms, _text, _anchor in mpn_resistance_candidates("MF52-103/3435")}
    assert readings == {34_300_000.0}
    assert gate("RT", "MF52-103/3435") is False
    assert gate("RT", "MF52-103/3435", "10kΩ") is True
    # EIA code 那一路仍放行：``NTCG103JF103FT1`` 的 ``103`` 就是它的 R25。
    assert gate("RT", "NTCG103JF103FT1") is True


def test_a_resistor_array_keeps_the_resistance_ruler():
    """``RP``（排阻）：声明值**就是**电阻，candidates 保留——写明的取舍。

    ``FB``/``RV``/``RT`` 被移出是因为它们的量不是欧姆；排阻的每一路都是，货架/板上
    也按欧姆写。这条测试把「保留」也钉住，免得下一批顺手一起删掉。
    """
    assert gate("RP", "RC0603FR-071KL") is True
    assert mpn_value_code("EXB38V103JV") is None  # 没有值码，只能靠 candidates
    assert gate("RP", "EXB38V103JV") is False


def test_the_gate_lists_a_part_whose_value_is_really_unknowable():
    """收尾：闸门的两个方向都还在（184 的意义不能被上面几条改没了）。

    一颗磁珠 MPN 读不出、板上值也读不出 → UNDECODABLE；同一条料号板上写了值 →
    不在清单上。
    """
    parts = unknown_parts(DesignModel(components={
        "FB1": component("FB1", mpn="BRC2016T101K"),
        "FB2": component("FB2", mpn="BRC2016T101K", value="600Ω"),
        "RT1": component("RT1", mpn="MF52-103/3435"),
    }, nets={}))
    by_ref = {part["designator"]: part for part in parts}
    assert set(by_ref) == {"FB1", "RT1"}
    assert all(
        UNKNOWN_REASON_UNDECODABLE in part["reasons"] for part in parts
    ), [part["reasons"] for part in parts]
