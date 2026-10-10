"""145c：C13 的符号几何不符 —— 宿主把两颗「0603」解析成两颗不同的符号。

============================ 145c 的触发 ============================

145b 把 145a 的 plan 往 test/P1 上落，在**拉线之前的引脚回读**这个守门上硬停（exit 3）：
`C13.1 reads back at (400, 660) but the plan expects (405, 660)`。同批 C10（`C100040`）、
C6（`C14858`）同用 `symbolRef=C0603`，回读正好 ±15、通过；只有 C13（`C14663`）被本机
解析成半宽 20 的符号。

145c 在真机上量了一遍，结论不是「档案错」而是「**0603 是一个封装，不是一个符号几何**」：

| 料号 | 用途 | 宿主符号 | 脚尖 |
|---|---|---|---|
| `C100040` | C10（118 量 C0603 profile 的基准） | `6837e352…` | **±15** |
| `C14858` | C6 | `c52f6dce…` | **±15** |
| `C14663` | **C13** | `aaaf5070dfb7f1f1` | **±20** |

实测原始读数 = `outputs/145c/probe_145c_C14663.json`（三件实物放在 `test` 的一张临时页上，
读完删净：`sch.doc.new` / `sch.place_component` / `sch.component_pins` / `sch.geometry` /
`sch.delete_primitives` / `doc.delete_page` 的逐条回复都在 `outputs/145c/probe_0*.json`）。

============================ 本文件钉的四件事 ============================

1. **C13 换的是 symbolRef，不是料号**：`C13.lcsc` 仍然 `C14663`、值仍然 `100nF 0603`——
   改的是「这颗料在本机的符号是哪一颗」这条断言，不是 BOM。
2. **新 profile `C0603W` 的脚尖是 ±20**，与探针文件逐脚相符（读文件，不信 profile 自己的注）。
3. **`C0603` 一个字没改**：仍是 ±15（`C100040`/`C14858` 的回读是精确的）。
   把 `C0603` 改成 ±20 是这条测试要拒的那个修法——它会让 C10/C6 凭空多 10 单位，
   且与它们的实测回读相矛盾。
4. **两颗 profile 是两颗符号**：`geometry_hash()` 必须不同（同 hash 就意味着「两个名字一张几何」，
   而它们的脚尖本来就不同）。
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPECS = ROOT / "blocklib" / "specs"
PROBE = ROOT / "outputs" / "145c" / "probe_145c_C14663.json"

#: 145c 的实测：C14663 的宿主符号（`sch.place_component` 的 `device.uuid`）与
#: 它解析出的符号 uuid（`sch.geometry` 的 `Component.uuid`）。写下来是为了让
#: 「哪一颗符号被量了」这件事可核，而不是只说「量过了」。
C14663_DEVICE_UUID = "96b39256cc3f4d80bd3b503deb4f3328"
C14663_SYMBOL_UUID = "aaaf5070dfb7f1f1"

WIDE_REF = "C0603W"
NARROW_REF = "C0603"


def _library() -> dict:
    return json.loads((SPECS / "flyback_uc3845.library.json").read_text(encoding="utf-8"))


def _profile(book: dict, ref: str) -> dict:
    for entry in book["profiles"]:
        if entry["symbolRef"] == ref:
            return entry
    raise AssertionError(f"the library carries no profile {ref!r}")


def _tips(entry: dict) -> dict[str, tuple[float, float]]:
    return {
        pin["number"]: (round(float(pin["tip"][0]), 4), round(float(pin["tip"][1]), 4))
        for pin in entry["pins"]
    }


def _probe_tips() -> dict[str, tuple[float, float]]:
    payload = json.loads(PROBE.read_text(encoding="utf-8"))
    placement = payload["placement"]
    assert placement["rotation"] == 0 and not placement["mirror"], (
        f"{PROBE.relative_to(ROOT).as_posix()} placed the part at {placement!r}; this "
        "reader subtracts the origin only, so a rotated placement reads wrong"
    )
    ox, oy = placement["x"], placement["y"]
    return {
        str(pin["number"]): (round(pin["x"] - ox, 4), round(pin["y"] - oy, 4))
        for pin in payload["pinsAbsolute"]
    }


def test_c13_keeps_its_part_and_changes_only_its_symbol():
    """**换的是符号，不是料号。** C13 还是 `C14663`、还是 `100nF 0603`。

    这条是 145c 的边界：它修的是「这颗料在本机的符号几何是哪一颗」，
    不是换料、不是改值。BOM 一个字都不该动——动了 BOM 就是另一个决定，得岳点头。
    """
    circuit = json.loads((SPECS / "flyback_uc3845.circuit.json").read_text(encoding="utf-8"))
    by_id = {part["id"]: part for part in circuit["parts"]}
    assert by_id["C13"]["symbolRef"] == WIDE_REF, (
        f"C13 is on {by_id['C13']['symbolRef']!r}; 145c measured that the host resolves "
        f"C14663 to a ±20 symbol, so it needs its own profile ({WIDE_REF!r})"
    )
    assert by_id["C13"]["lcsc"] == "C14663", (
        f"C13's LCSC is {by_id['C13']['lcsc']!r} — 145c changed the symbol reference, "
        "never the part"
    )
    assert by_id["C13"]["value"] == "100nF 0603", (
        f"C13's value is {by_id['C13']['value']!r}; 145c did not touch it"
    )
    # And the two parts whose ±15 read-back is exact stay on the narrow profile.
    for designator in ("C10", "C6"):
        assert by_id[designator]["symbolRef"] == NARROW_REF, (
            f"{designator} moved to {by_id[designator]['symbolRef']!r}; its measured "
            f"read-back is ±15, which is the {NARROW_REF!r} profile — moving it would "
            "be claiming a geometry the host did not draw"
        )


def test_the_wide_profile_carries_the_measured_tips():
    """**新 profile 的脚尖等于探针读数**（读文件，不信 profile 自己的注）。"""
    book = _library()
    entry = _profile(book, WIDE_REF)
    measured = _probe_tips()
    assert _tips(entry) == measured, (
        f"{WIDE_REF} declares {_tips(entry)}, "
        f"{PROBE.relative_to(ROOT).as_posix()} measured {measured}"
    )
    assert entry["body"] == [-10.0, 0.0, 10.0, 0.0], (
        f"{WIDE_REF}'s body is {entry['body']}; the two pins' inner ends for ±20 tips "
        "of length 10 are ±10 — the same body convention C0603/C0805 state"
    )
    # The probe must be the part it claims to be: one device uuid, one symbol uuid.
    payload = json.loads(PROBE.read_text(encoding="utf-8"))
    assert payload["part"]["deviceUuid"] == C14663_DEVICE_UUID
    assert payload["part"]["symbolUuid"] == C14663_SYMBOL_UUID
    assert payload["part"]["lcsc"] == "C14663"


def test_the_narrow_profile_is_untouched_by_the_wide_one():
    """**不许把 `C0603` 改成 ±20** —— C10/C6 的回读证明它是准的。

    这是 145c 最容易被做错的一步：把档案里的标准 0603 改宽，让 C13 一类通过，
    同时悄悄把 C10/C6 的支路撑宽 10 单位。两个名字、两张几何，是这条要钉的形状。
    """
    book = _library()
    narrow, wide = _profile(book, NARROW_REF), _profile(book, WIDE_REF)
    assert _tips(narrow) == {"1": (-15.0, -0.0), "2": (15.0, 0.0)}, (
        f"{NARROW_REF}'s tips are {_tips(narrow)}; 118 measured ±15 from C100040 and "
        "145c's probe re-measured the same ±15 on C100040 and C14858"
    )
    assert narrow["body"] == [-5.0, 0.0, 5.0, 0.0]
    assert _tips(narrow) != _tips(wide), (
        "the two profiles carry one geometry — but the host draws two different "
        "symbols, which is the whole reason 145c exists"
    )


def test_the_two_profiles_are_two_symbols_not_one_name():
    """**几何哈希必须不同** —— 同 hash = 两个名字一张图。

    `geometry_hash()` 正是 apply 的库几何守门（C6）读写的那把尺子：一颗 profile
    换了数字，plan 里的 `profiles` 表就与新的库对不上，apply 在**写之前**就拒
    （145b 因为没传 `--profiles` 才让 C13 落到了引脚回读那一步）。
    """
    from boardwise.engines import drawapply

    book = drawapply.load_library(SPECS / "flyback_uc3845.library.json")
    assert book[WIDE_REF].geometry_hash() != book[NARROW_REF].geometry_hash()
    table = dict(drawapply.profile_table(book))
    assert table[WIDE_REF] == book[WIDE_REF].geometry_hash()
    assert table[NARROW_REF] == book[NARROW_REF].geometry_hash()
