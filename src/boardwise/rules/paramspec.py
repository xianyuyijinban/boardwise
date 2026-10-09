"""选型判据（issue #64）：货架 MPN/params 里的**规格**与板上的**轨**对拍。

#64 的实测：``blocklib/parts.json`` 里 ``diode.smcj28ca`` / ``smcj40ca`` /
``smcj64ca`` 的 MPN 数字就是击穿电压档位，``ic.tplp2981_30dbvr`` 的 ``30``
就是 3.0 V 固定输出，``ic.stm32h743vit6`` 带着 10 项规格——**躺着**，没有一条
规则消费它们。#63 是"没看"，这条是"看了没用上"。

本模块只做两类，理由是 2026-10-07 的货架实测（见类文档）：

* ``sel-tvs-standoff-rail`` —— TVS 的**反向关断电压**对它所挂的那条轨；
* ``sel-ldo-fixed-output`` —— 固定输出 LDO 的**输出档**对它输出的那条轨。

其余带规格的类别（电容耐压、电解电容耐压、MOS 的 Vds/Id、电感 Isat、LED 的
Vf、开关的额定电压）**留给以后**，理由各自写在类文档里；已经有一条
``pwr-cap-voltage-rating`` 在消费电容耐压的那一类，本模块不重复它。

**与 ``rules/railratings.py`` 的关系：对齐，不复制。** 那两条规则
（``pwr-cap-voltage-rating`` / ``path-ldo-dissipation``）立下的纪律本模块逐条
沿用，因为它们和这里要问的是同一个问题——"一个数 vs 另一条文档说的数"：

* **测量永远报（INFO）**，因为没人报出来的数字在报告里读起来像"已定级"；
* **只有本 build 能说出的限值才是 WARN**：``Vrwm < 轨压`` 与 ``固定输出 ≠
  轨压``，都是两个数之间的关系，不是口味；
* **读不出就是 UNKNOWN，并点名缺哪个事实**，绝不猜；
* **不发明降额标准。** 这里比的是 ``Vrwm >= rail`` 和 ``declared == rail``，
  两个数都在消息里，本工具不给它们套任何系数——092 §二 那句话在这里同样是
  纪律而不是修辞。裕度以**比值**的形式报出来（``28 V / 24 V = 1.17x``），
  要不要按自己的规矩留 20 % 由读报告的人决定，本工具替他决定不了；
* **合同（design intent）压过图纸自己的推断**：轨压先取
  ``requirements.rails[net=…].targetVoltage``（那是需求），再取图纸自己的
  读数。合同因此是本模块两条规则的 ``intent=`` 承载体，它们进
  :data:`boardwise.engines.review.INTENT_RULES`；没有合同的读法，两条规则照样
  跑（图纸自己的轨压仍然是证据），只是不用合同——这与
  ``pwr-cap-voltage-rating`` 的差别是那条规则**以合同的轨为主语**，没有合同
  就无主语可言，本模块的主语是**板上的器件**，合同只是它读轨压时的第一顺位
  证据。

**自指纪律（本模块独有的一条，也是唯一一处不得不新写的东西）**：一条轨的电压
可能**正是从被审的这颗 LDO 自己推出来的**——:func:`boardwise.core.power_domains.infer_net_domains`
会把 LDO 输出脚的电压加进候选，来源串形如 ``U8 AMS1117-3.3 output, decoded
from the MPN suffix``。拿这样的轨压去对拍"AMS1117 的固定输出是不是 3.3 V"，
是把零件自己的名字读一遍再宣布它通过了。因此只有**独立**的轨压才配下判语：
合同声明的、轨名自己写着的（``+5V``）、或者**别的** LDO 的输出脚推出来的
（本工具读得出 `U8 != U9`，来源串因此足够，见
:func:`sel_rail_voltage` 的自指判定）；否则一律 UNKNOWN，点名"这条轨的电压
是从 U8 自己推出来的，写进合同 ``requirements.rails[net=VCC].targetVoltage``
才能判"。
"""

from __future__ import annotations

from ..core.designintent import INTENT_MISSING, IntentSource, write_path
from ..core.model import Component, DesignModel, is_ground_net
from ..core.parts import PartEntry, designator_category, find_facts
from ..core.power_domains import (
    domain_of,
    infer_net_domains,
    ldo_output_pin,
    ldo_output_voltage,
    ldo_output_voltage_facts,
    voltage_from_net_name,
)
from ..core.values import parse_voltage_volts
from .base import Finding, Outcome
from .facts import FactsRule
from .railratings import rail_voltage
from .unproven import unproven_nets, unproven_outcome

LEVEL = "L2-facts"


# --------------------------------------------------------------------------
# 规格读数：货架条目的命名字段
# --------------------------------------------------------------------------

#: A TVS's **reverse stand-off voltage** — the highest continuous voltage it
#: carries without conducting, and therefore the number a bus voltage is
#: compared against. The catalog is a **named-field** store (it writes
#: ``"Reverse Stand-Off Voltage (Vrwm)": "28V"`` verbatim, in whichever
#: spelling the listing used), so the reader asks for the field by name and the
#: spellings are listed here rather than mined out of the description — the same
#: discipline :func:`boardwise.rules.railratings.cap_voltage_rating` keeps for a
#: capacitor's rating. A field that is present but unreadable falls through to
#: the next spelling; nothing here guesses.
_TVS_STANDOFF_KEYS: tuple[str, ...] = (
    "Reverse Stand-Off Voltage (Vrwm)",
    "Reverse Standoff Voltage",
    "Stand-Off Voltage",
    "Vrwm",
    "VRWM",
    "反向截止电压(Vrwm)",
    "反向关断电压",
)

#: The **breakdown** voltage (where the device starts to conduct) and the
#: **clamping** voltage (what it holds the surge down to). Both are reported as
#: measurements on the OK/VIOLATION rows — they are the other two thirds of a
#: TVS selection and this rule deliberately does *not* judge on them (a
#: clamping voltage is a datasheet number under a stated test condition, and
#: what a design may clamp to is the architecture's question, not the shelf's).
_TVS_BREAKDOWN_KEYS: tuple[str, ...] = (
    "Voltage - Breakdown",
    "Voltage Breakdown",
    "Breakdown Voltage",
    "击穿电压",
)
_TVS_CLAMPING_KEYS: tuple[str, ...] = (
    "Clamping Voltage",
    "Peak Clamping Voltage",
    "钳位电压",
)

#: What makes a shelf entry a **TVS**. Same reason as the category question in
#: ``facts.py``: ``diode`` alone would sweep in rectifiers and Schottkys, and a
#: rectifier has no stand-off voltage to compare at all. An entry that names no
#: type is NOT "not a TVS" — it is *unknown*, and the row says so.
_TVS_TYPE_KEYS: tuple[str, ...] = ("Type", "器件类型", "类型")
_TVS_TYPE_TOKENS: tuple[str, ...] = ("TVS", "tvs", "瞬态抑制", "瞬态抑制二极管")

#: A **fixed**-output regulator's declared output voltage, and the field that
#: says whether it is fixed at all (``固定`` / ``Fixed``). A part whose type says
#: adjustable is NOT_APPLICABLE — its output is a divider's job
#: (``param-divider-output``'s subject), and there is no档位 to compare.
_LDO_OUTPUT_KEYS: tuple[str, ...] = ("Output Voltage", "输出电压")
_LDO_TYPE_KEYS: tuple[str, ...] = ("Output Type", "输出类型")
_FIXED_TOKENS: tuple[str, ...] = ("固定", "fixed", "Fixed", "FIXED")
_ADJUSTABLE_TOKENS: tuple[str, ...] = (
    "可调", "adjustable", "Adjustable", "ADJUSTABLE",
)


def _params_of(entry: PartEntry | None) -> dict[str, str]:
    return dict((entry.params if entry is not None else {}) or {})


def _named(params: dict[str, str], keys: tuple[str, ...]) -> tuple[str, str]:
    """The first ``keys`` spelling present in ``params``, with the key it used.

    ``("", "")`` for none. A key that is present with an **empty or placeholder**
    value counts as present-but-unreadable: the caller then reports UNKNOWN
    naming that field, rather than reading the next spelling and pretending the
    first one said nothing. ``"-"`` is this catalog's placeholder for "not
    stated", and treating it as absent is how a "TVS with no Vrwm" would silently
    become a "TVS rated at something else".
    """
    for key in keys:
        if key in params:
            return key, (params[key] or "").strip()
    return "", ""


def _read_volts(raw: str) -> float | None:
    """One catalog voltage field as a number — the shared reader.

    :func:`boardwise.core.values.parse_voltage_volts` is the reader the whole
    codebase uses for a stated voltage (``28V``, ``3.3``, ``3V3``), and a field
    whose value it refuses (``-``, ``3V3~5V`` — a *range*, not one rating) is a
    field this rule has no reading for: UNKNOWN, not a guess at the lower end.
    """
    volts = parse_voltage_volts(raw)
    if volts is None or volts <= 0:
        return None
    return volts


def _identity(comp: Component, entry: PartEntry | None) -> str:
    bits = [f"value {comp.value!r}"]
    if comp.mpn:
        bits.append(f"料号 {comp.mpn!r}")
    if entry is not None and entry.lcsc:
        bits.append(f"货架条目 {entry.lcsc}")
    return "，".join(bits)


# --------------------------------------------------------------------------
# 轨压的读取顺序（合同 → 轨名 → 别的 LDO → 这颗 LDO 自己）
# --------------------------------------------------------------------------


def independent_rail_price(
    model: DesignModel, library, net: str | None, *, subject: str
) -> tuple[float | None, str]:
    """A rail's voltage from **another** part's shelf spec — ``(volts, source)``.

    :func:`boardwise.core.power_domains.infer_net_domains` prices an LDO's
    output rail from the part's **MPN suffix** or a curated
    ``ldo.fixed_output`` fact — never from the catalog's own ``Output Voltage``
    field. That is #64's complaint one layer down: the field every LDO entry on
    this shelf actually carries is not a source the domain inference reads, so a
    board whose regulator is a plain `AMS1117-3.3` ends up with a rail priced
    by a *guess* about its own name, and every rule that needs that rail is
    left with an UNKNOWN.

    So this reader asks the question the domain inference will not: **does some
    other regulator on this board, sitting on ``net``'s own output pin, state
    its output voltage in the catalog field?** That answer is independent
    evidence for a rule judging ``subject`` — a different part's datasheet, not
    the subject's own name — and it is exactly what the self-reference refusal
    below is looking for as its escape.

    Only ``ic.ldo`` entries are read, and only through
    :func:`boardwise.core.power_domains.ldo_output_pin`, so "another regulator's
    output pin" is a fact rather than a guess. Every part found is reported in
    the source string, and a **disagreement** between them is a CONFLICT this
    reader refuses rather than resolves — picking one of two regulators' claims
    about the same net is the architecture's question, and
    ``arch-rail-voltage-clash`` is where that is owned.
    """
    if not net or library is None:
        return None, ""
    found: dict[float, list[str]] = {}
    for designator in sorted(model.components):
        if designator == subject:
            continue
        comp = model.components[designator]
        entry = None
        if comp.mpn:
            entry = find_facts(library, mpn=comp.mpn)
        if entry is None and comp.lcsc_part:
            entry = find_facts(library, lcsc=comp.lcsc_part)
        if entry is None or entry.category != "ic.ldo":
            continue
        out_pin = ldo_output_pin(entry)
        if not out_pin:
            continue
        on_net = [p for p in comp.pins if p.net == net]
        if not any(p.number == out_pin for p in on_net):
            continue
        key, raw = _named(_params_of(entry), _LDO_OUTPUT_KEYS)
        volts = _read_volts(raw)
        if volts is None:
            continue
        found.setdefault(volts, []).append(
            f"{designator} 的 {key} = {raw!r}（货架条目 {entry.key}）"
        )
    if len(found) != 1:
        # No neighbour speaks, or two of them disagree — see the docstring.
        return None, ""
    volts, sources = next(iter(found.items()))
    return volts, (
        "货架上另一颗稳压器对该轨输出脚自己声明的输出电压："
        + "；".join(sources)
    )


def sel_rail_voltage(
    intent: IntentSource | None,
    guesses: dict,
    net: str | None,
    *,
    subject: str = "",
    model: DesignModel | None = None,
    library=None,
) -> tuple[float | None, str, str]:
    """``(volts, source, why_not)`` for the rail one part hangs on.

    The order is :func:`boardwise.rules.railratings.rail_voltage`'s — the
    contract's ``targetVoltage`` first (the requirement), the net name second,
    the drawing's own inference third — with two additions this module needs and
    that rule does not: **the subject's own MPN decode is not evidence about
    itself**, and **a neighbour regulator's shelf field is** (see
    :func:`independent_rail_price`).

    :func:`boardwise.core.power_domains.infer_net_domains` prices a net from an
    LDO's output pin, naming the source ``U8 AMS1117-3.3 output, decoded from
    the MPN suffix``. When the part being judged *is* that ``U8``, that reading
    would make ``sel-ldo-fixed-output`` compare AMS1117-3.3's fixed output
    against a number derived from AMS1117-3.3's name — a verdict the rule
    manufactures from the very string it is auditing. So the last step refuses
    that, and says which designator the offending inference came from, because
    "nobody states this rail's voltage" and "the only statement is the part under
    audit" are two different work orders.

    A **net name that states its voltage** (``+5V``) is independent of every
    part, so it is asked before the inference and is never self-referential.

    The refusal above keys on the subject's designator appearing in the source
    string, and that string carries **every** candidate that voted on the net
    (:func:`boardwise.core.power_domains.infer_net_domains` joins them with
    ``"; "``). So a rail that some *other* regulator also prices would be
    refused even though the neighbour's reading is independent evidence. When
    the subject's vote is not the only one, the reading stands and the row
    quotes the whole source — including the subject's own vote — so the reader
    sees that one of the prices came from the part under audit. Only a rail
    priced by nothing but the subject is refused, which is the measured shape
    of all three boards below.
    """
    if intent is not None:
        volts, source, why = rail_voltage(intent, guesses, net)
        if volts is not None:
            return volts, source, ""
        if not net:
            return None, "", why
        # The contract answered nothing for this net; the drawing still may.
    named = voltage_from_net_name(net)
    if named is not None:
        return named[0], named[1], ""
    # Before the inference's own answer, the field the inference does not read
    # (see `independent_rail_price`). A neighbour's declaration is independent
    # evidence about the subject, so it is asked first and settles the question
    # even when the subject votes on the same net.
    neighbour, neighbour_source = independent_rail_price(
        model, library, net, subject=subject
    )
    if neighbour is not None:
        return neighbour, neighbour_source, ""
    volts, source, why = domain_of(guesses, net)
    if volts is not None:
        # One entry per voting source; the subject's own vote is the one that
        # cannot serve as evidence about the subject.
        votes = [v for v in source.split("; ") if v.strip()]
        mine = [v for v in votes if v.startswith(f"{subject} ")] if subject else []
        others = [v for v in votes if not v.startswith(f"{subject} ")]
        if mine and not others:
            return None, "", (
                f"这条轨 {net!r} 的电压只从被审的 {subject} 自己推出来"
                f"（{source}），拿它对拍 {subject} 的规格等于拿零件自己的名字"
                f"验零件自己；{INTENT_MISSING}: 写进合同 "
                f"{write_path('rails', net, 'targetVoltage')}，或让轨名自己写着电压"
            )
        return volts, source, ""
    missing = why or f"no source names the voltage of net {net!r}"
    if intent is not None:
        missing = (
            f"{missing}；{INTENT_MISSING}: 合同也没声明 "
            f"{write_path('rails', net or '?', 'targetVoltage')}"
        )
    return None, "", missing


# --------------------------------------------------------------------------
# 1: TVS 的关断电压 vs 它所挂的轨
# --------------------------------------------------------------------------


class TvsStandoffRail(FactsRule):
    """SEL-1: a TVS's reverse stand-off voltage against the rail it hangs on.

    **The comparison and its direction.** A TVS diode is specified for the
    highest *continuous* reverse voltage it holds off without conducting — the
    shelf's own ``Reverse Stand-Off Voltage (Vrwm)``. That number and the bus
    voltage it sits on must satisfy

    ``Vrwm >= rail``

    and the two failures are not symmetric, which is why one inequality is
    enough:

    * ``Vrwm < rail`` — **VIOLATION (WARN)**. The device conducts on the rail's
      *normal* operating voltage, not on a surge: it becomes a permanent load on
      the bus, the bus no longer sits at its rated voltage, and it heats. This is
      a relation between two stated numbers, not a matter of taste — no margin
      policy is needed to say it, and the same is true of ``pwr-cap-voltage-rating``'s
      over-voltage;
    * ``Vrwm >= rail`` — **OK (INFO)**, and the **margin is reported as a ratio**
      (``28 V / 24 V = 1.17x``). A TVS is normally chosen with real standoff
      margin above the bus (transients ride above the nominal), and this build
      states no coefficient for that: 092 §二's "不发明降额标准" applies to
      voltage margins exactly as it does to derating, so the ratio travels in the
      message and a reviewer applies their own house number. What the rule
      refuses to do is decide *their* margin for them — a threshold invented
      here would be a verdict wearing a measurement's clothes.

    The other two thirds of a TVS selection — the **breakdown** voltage and the
    **clamping** voltage — are read and quoted on the same rows, and
    deliberately not judged: a clamping voltage is a datasheet figure under a
    stated test condition (``Ipp = 33.1A @ 10/1000µs``), and what a design may
    clamp to is the architecture's question.

    **The rail is the TVS's own non-ground net.** A two-lead TVS has exactly one;
    if the part sits on more than one non-ground net, or on none, the row is
    UNKNOWN naming that — "which rail does it protect" is a question this rule
    has no right to answer for a three-channel array.

    **The subject is a part whose shelf entry declares it a TVS** (``Type:
    TVS``). ``diode`` alone would sweep in rectifiers, which have no stand-off
    voltage to compare; and an entry that names no type is **UNKNOWN**, not
    "not a TVS" — the same three-way answer ``facts.py``'s ``_category_state``
    gives (explicitly-not / explicitly-is / cannot-tell), for the same reason.

    Every rail read here is a net read, so issue #19's welded-name refusal
    applies verbatim: the rule joins :data:`boardwise.rules.unproven.NET_MEMBERSHIP_RULES`
    and an unproven net is UNKNOWN, never an OK.
    """

    id = "sel-tvs-standoff-rail"
    title = "A TVS's stand-off voltage clears the rail it protects"
    level = LEVEL
    source = (
        "the shelf entry's own Reverse Stand-Off Voltage (Vrwm) field against the "
        "rail's voltage, read from the design intent's requirements.rails[]."
        "targetVoltage first and the drawing's own inference second; no margin or "
        "derating coefficient is applied (issue #64)"
    )

    def __init__(self, library=None, intent: IntentSource | None = None) -> None:
        super().__init__(library)
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity)
            for outcome, severity in self._rows(model)
            if severity is not None
        ]

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for comp in model.components.values():
            row = self._row(model, comp, guesses)
            if row is not None:
                rows.append(row)
        return rows

    def _row(
        self, model: DesignModel, comp: Component, guesses: dict
    ) -> tuple[Outcome, str | None] | None:
        ref = comp.designator
        evidence = [f"{ref} pin{pin.number} @ {pin.net}" for pin in comp.pins]
        entry = self.entry_for(comp)
        if entry is None:
            # Which part this is, is another rule's report (PWR/CONN-2); a
            # diode-designator part with no shelf entry has no spec to read, and
            # one row per unlisted diode on every board would drown the real
            # ones. `path-ldo-dropout` skips the same way.
            return None
        is_diode = (
            entry.category == "diode" or designator_category(ref) == "diode"
        )
        if not is_diode:
            return None
        params = _params_of(entry)
        type_key, type_raw = _named(params, _TVS_TYPE_KEYS)
        if not type_key:
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}（{_identity(comp, entry)}）是货架上的二极管条目，"
                        f"但条目没有 Type 字段说它是不是 TVS，所以它的关断电压"
                        f"无从读出（Type 候选：{', '.join(_TVS_TYPE_KEYS)}）"
                    ),
                    evidence=evidence,
                    missing_fact=(
                        f"{ref} 的器件类型（货架条目 {entry.key} 的 Type 字段："
                        f"TVS 还是整流/肖特基）"
                    ),
                ),
                "INFO",
            )
        if not any(token in type_raw for token in _TVS_TYPE_TOKENS):
            return (
                Outcome(
                    rule_id=self.id,
                    state="NOT_APPLICABLE",
                    subject=ref,
                    message=(
                        f"{ref}: 货架条目 {type_key} = {type_raw!r}，不是 TVS"
                        f"（本规则只判 TVS 的关断电压）"
                    ),
                ),
                None,
            )
        # 2026-10-07 measured: every diode entry in the shelf is uncategorised
        # (task 039 never reached them), so the *type field* is the only thing
        # that says "this is a TVS" and the gate is not a fact gate here —
        # `params` is catalog text, which 039 does not hold back.
        if not entry.facts_verified:
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}: 货架条目是候选件（facts_verified=false），其 params "
                        f"里的规格在复核之前不驱动任何规则"
                    ),
                    evidence=evidence,
                    missing_fact=f"复核货架条目 {entry.key}（facts_verified 的翻转）",
                ),
                "INFO",
            )
        standoff_key, standoff_raw = _named(params, _TVS_STANDOFF_KEYS)
        rails = sorted(
            {
                pin.net
                for pin in comp.pins
                if pin.net and not is_ground_net(pin.net)
            }
        )
        if len(rails) != 1:
            where = "、".join(rails) if rails else "无（两个脚都在地上或悬空）"
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}: 它挂在 {len(rails)} 条非地网络（{where}），"
                        f"所以「它保护哪条轨」这个事实读不出来"
                    ),
                    evidence=evidence,
                    missing_fact=f"{ref} 保护的是哪一条轨（非地网络：{where}）",
                ),
                "INFO",
            )
        rail_net = rails[0]
        welded = unproven_nets(model, (rail_net,))
        if welded:
            return (
                unproven_outcome(
                    self.id,
                    ref,
                    welded,
                    what=(
                        f"{ref} 挂的轨 {rail_net!r} 的电压，以及它与 "
                        f"{ref} 关断电压的关系"
                    ),
                    evidence=evidence,
                ),
                "INFO",
            )
        volts, volts_source, volts_why = sel_rail_voltage(
            self.intent,
            guesses,
            rail_net,
            subject=ref,
            model=model,
            library=self.library,
        )
        standoff = _read_volts(standoff_raw)
        rail_label = f"所挂轨 {rail_net}" + (
            f" = {volts:g} V" if volts is not None else ""
        )
        if standoff is None or volts is None:
            # An absent field and an unreadable one are two different work
            # orders, so the message says which: "no such field" names the
            # spellings to write one of, while "there is a field and its value
            # is not a voltage this build reads" quotes what it actually said.
            field_note = (
                f"字段 {standoff_key} = {standoff_raw!r}，不是本工具能读量的写法，"
                f"如 `28V`"
                if standoff_key
                else f"货架条目没有关断电压字段（候选：{'、'.join(_TVS_STANDOFF_KEYS)}）"
            )
            if standoff is None and volts is None:
                missing = (
                    f"{ref} 的关断电压（{rail_label}）与 {rail_net} 的轨压，两样都缺"
                )
                why = f"关断电压读不出（{field_note}），且轨压读不出"
            elif standoff is None:
                missing = f"{ref} 的反向关断电压 Vrwm（{rail_label}）"
                why = f"关断电压读不出（{field_note}）"
            else:
                missing = f"{rail_net} 的轨压（{ref} 的 Vrwm {standoff:g} V 已知）"
                why = volts_why
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}（{_identity(comp, entry)}）：{why}，所以对拍无从做起"
                    ),
                    evidence=evidence,
                    missing_fact=missing,
                ),
                "INFO",
            )
        extras = self._extra_voltages(params)
        ratio = standoff / volts
        measured = "".join(
            f"；{label} {value:g} V（{key}）" for label, value, key in extras
        )
        common = [
            f"{ref} Vrwm {standoff:g} V —— 来源：货架条目 {entry.key} 的 "
            f"{standoff_key} = {standoff_raw!r}",
            f"{rail_net} 轨压 {volts:g} V —— 来源：{volts_source}",
        ]
        if standoff < volts:
            return (
                Outcome(
                    rule_id=self.id,
                    state="VIOLATION",
                    subject=ref,
                    message=(
                        f"{ref}: 关断电压 {standoff:g} V < {rail_label}，比值 "
                        f"{ratio:.2f}x —— 确定的越限：这条轨的正常工作电压已经在"
                        f"关断电压之上，TVS 会在常态下导通（不是过压口味：两个数"
                        f"都在这里——{standoff_key} 与 {volts_source}）。换一颗"
                        f"Vrwm 高于该轨的件，或把该轨的声明改对"
                    ),
                    evidence=common,
                ),
                "WARN",
            )
        return (
            Outcome(
                rule_id=self.id,
                state="OK",
                subject=ref,
                message=(
                    f"{ref}: 关断电压 {standoff:g} V ≥ {rail_label}，比值 "
                    f"{ratio:.2f}x{measured} —— 这是测量行：本工具不发明裕度"
                    f"系数（要按自家规矩留多少余量，请拿这个比值自己判）"
                ),
                evidence=common,
            ),
            "INFO",
        )

    def _extra_voltages(self, params: dict[str, str]) -> list[tuple[str, float, str]]:
        """``(label, volts, key)`` for breakdown / clamping — quoted, not judged."""
        found: list[tuple[str, float, str]] = []
        for label, keys in (
            ("击穿电压", _TVS_BREAKDOWN_KEYS),
            ("钳位电压", _TVS_CLAMPING_KEYS),
        ):
            key, raw = _named(params, keys)
            volts = _read_volts(raw)
            if key and volts is not None:
                found.append((label, volts, key))
        return found


# --------------------------------------------------------------------------
# 2: 固定输出 LDO 的输出档 vs 它输出那条轨的电压
# --------------------------------------------------------------------------


class LdoFixedOutput(FactsRule):
    """SEL-2: a fixed-output LDO's output voltage against the rail it feeds.

    **The comparison and its direction.** A fixed regulator is one档位 — the
    shelf says so in the entry's own ``Output Voltage`` field (``3.3V`` for
    ``AMS1117-3.3``, ``3V`` for ``TPLP2981-30DBVR``, which is exactly #64's
    "``30`` = 3.0 V 躺着睡大觉"). It has no feedback divider to be re-scaled, so
    the rail behind its output pin must satisfy

    ``declared == rail``

    and any difference is a contradiction between two documents:

    * different — **VIOLATION (WARN)**. Either the part is the wrong档位 for the
      rail, or the rail's own name/contract is stating the wrong voltage, and
      which of the two is wrong is a design decision (052 §2.1's ruling, kept
      here for the same question): the row names both candidates and repairs
      neither;
    * equal — **OK (INFO)**, both numbers and both sources quoted.

    **No tolerance band is invented.** A regulator's output is nominal and the
    rail a board declares is nominal too; this rule compares the two stated
    numbers for equality and reports the difference. Coining an "LDO tolerance
    is ±2 % so 3.0 V passes a 3.05 V rail" band would be the same fabricated
    standard 092 §二 refuses — and 3.0 V against a 3.3 V rail is not a question
    of a band either way.

    **Which rail.** The one on the part's **output pin**, taken from
    :func:`boardwise.core.power_domains.ldo_output_pin` — the same reader
    ``path-ldo-dropout`` and ``path-ldo-dissipation`` use. An entry whose facts
    do not name exactly one output pin yields UNKNOWN naming that gap rather than
    a guess: measured, ``ic.tplp2981_30dbvr`` carries no ``facts`` at all, so its
    output pin is exactly the fact that is missing.

    **The self-reference refusal** is this module's own addition and is
    documented at :func:`sel_rail_voltage`: the rail's voltage is frequently
    inferred from this very LDO's MPN suffix, and comparing a part's declared
    output against a number decoded from its own name proves nothing.

    **Which档位 to compare, in reading order** — strongest evidence first, the
    same order :func:`boardwise.core.parts.PartEntry.resistance` uses:

    1. ``facts.ldo.fixed_output.volts`` with its datasheet page (issue #17's
       curated fact; no shelf entry declares one today);
    2. the entry's own ``Output Voltage`` field — the catalog's declaration, the
       field #64 is about;
    3. :func:`boardwise.core.power_domains.ldo_output_voltage`'s MPN-suffix
       decode — a guess, reported as one. It reads an *explicit delimited*
       suffix: ``AMS1117-3.3`` and ``RT9013-33GB`` both land on 3.3 V even
       though their stems are in issue #17's adjustable-by-default guard list,
       because the ``-3.3``/``-33GB`` tail is exactly the shape that guard
       allows. A part with no such tail (``LM317``, and the measured
       ``TPLP2981-30DBVR``, whose ``30`` this decoder will not read — it wants
       ``-30``) answers ``None`` and falls back to step 2, which is where all
       four measured LDO entries are actually decided.

    Delete step 2 (the acceptance anchor's UNKNOWN path) and both the measured
    boards lose their verdict rather than gaining a fabricated one.

    Every rail read here is a net read, so this rule is in
    :data:`boardwise.rules.unproven.NET_MEMBERSHIP_RULES` and refuses on an
    unproven net exactly as SEL-1 does.
    """

    id = "sel-ldo-fixed-output"
    title = "A fixed-output LDO's voltage step matches the rail it feeds"
    level = LEVEL
    source = (
        "the shelf entry's own Output Voltage field (or its ldo.fixed_output fact, "
        "or a guarded MPN-suffix decode) against the output rail's voltage, read "
        "from the design intent's requirements.rails[].targetVoltage first and the "
        "drawing's own inference second; the part's own decode of that rail is "
        "refused as evidence about itself, and no tolerance band is invented "
        "(issue #64)"
    )

    def __init__(self, library=None, intent: IntentSource | None = None) -> None:
        super().__init__(library)
        self.intent = intent

    def outcomes(self, model: DesignModel) -> list[Outcome]:
        return [row[0] for row in self._rows(model)]

    def check(self, model: DesignModel) -> list[Finding]:
        return [
            self.finding_from_row(outcome, severity)
            for outcome, severity in self._rows(model)
            if severity is not None
        ]

    def _rows(self, model: DesignModel) -> list[tuple[Outcome, str | None]]:
        guesses = infer_net_domains(model, self.library)
        rows: list[tuple[Outcome, str | None]] = []
        for comp in self.ics(model):
            row = self._row(model, comp, guesses)
            if row is not None:
                rows.append(row)
        return rows

    def _row(
        self, model: DesignModel, comp: Component, guesses: dict
    ) -> tuple[Outcome, str | None] | None:
        ref = comp.designator
        entry = self.entry_for(comp)
        if entry is None:
            return None
        if entry.category != "ic.ldo":
            # "Is this part an LDO at all" is `path-ldo-dropout`'s conclusion,
            # and it states it for every IC whose shelf entry cannot tell
            # (`_category_state`'s three-way answer) — `path-ldo-dissipation`
            # skips those the same way and says why in its own docstring. A
            # second copy of that row in this rule's wording is how two rules
            # start disagreeing about the same gap.
            return None
        params = _params_of(entry)
        type_key, type_raw = _named(params, _LDO_TYPE_KEYS)
        if any(token in type_raw for token in _ADJUSTABLE_TOKENS):
            return (
                Outcome(
                    rule_id=self.id,
                    state="NOT_APPLICABLE",
                    subject=ref,
                    message=(
                        f"{ref}: 货架条目 {type_key} = {type_raw!r}，是可调输出"
                        f"（输出档位由分压决定，`{type_key}` 那类字段不适用）"
                    ),
                ),
                None,
            )
        declared, declared_source = self._declared_output(comp, entry, params)
        if declared is None:
            read_through = "、".join(_LDO_OUTPUT_KEYS)
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}（{_identity(comp, entry)}）的固定输出电压读不出："
                        f"三个取值口都没读到——ldo.fixed_output 事实、货架条目的 "
                        f"Output Voltage 字段（{read_through}）、受保护料号后缀的"
                        f"解码（{entry.mpn or '板上没写料号'}）。"
                        f"needs_datasheet 同族点名："
                        f"{ref} 的固定输出电压"
                    ),
                    missing_fact=f"{ref} 的固定输出电压（固定/可调、Output Voltage）",
                ),
                "INFO",
            )
        out_pin = ldo_output_pin(entry)
        if out_pin is None:
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref}（{_identity(comp, entry)}）的固定输出是 "
                        f"{declared:g} V（{declared_source}），但货架事实没有指明"
                        f"它的输出脚（supply_pins 与 required_caps 合起来指不出唯一"
                        f"一个非供电脚），所以它输出的是哪条轨读不出来"
                    ),
                    missing_fact=(
                        f"{ref} 的输出脚（货架条目 {entry.key} 的 ldo 事实："
                        f"supply_pins / required_caps）"
                    ),
                ),
                "INFO",
            )
        out_net = next(
            (pin.net for pin in comp.pins if pin.number == out_pin), None
        )
        evidence = [
            f"{ref} pin{out_pin} @ {out_net}",
            f"{ref} 固定输出 {declared:g} V —— 来源：{declared_source}",
        ]
        welded = unproven_nets(model, (out_net,))
        if welded:
            return (
                unproven_outcome(
                    self.id,
                    ref,
                    welded,
                    what=f"{ref} 输出轨 {out_net!r} 的电压与其固定输出档位是否一致",
                    evidence=evidence,
                ),
                "INFO",
            )
        volts, volts_source, volts_why = sel_rail_voltage(
            self.intent, guesses, out_net, subject=ref, model=model,
            library=self.library,
        )
        if volts is None:
            return (
                Outcome(
                    rule_id=self.id,
                    state="UNKNOWN",
                    subject=ref,
                    message=(
                        f"{ref} 的固定输出是 {declared:g} V（{declared_source}），"
                        f"但它输出轨 {out_net} 的轨压读不出，所以对拍无从做起："
                        f"{volts_why}"
                    ),
                    evidence=evidence,
                    missing_fact=f"{out_net} 的轨压（{ref} 输出的那条轨）",
                ),
                "INFO",
            )
        evidence.append(f"{out_net} 轨压 {volts:g} V —— 来源：{volts_source}")
        if abs(declared - volts) < 1e-9:
            return (
                Outcome(
                    rule_id=self.id,
                    state="OK",
                    subject=ref,
                    message=(
                        f"{ref}: 固定输出 {declared:g} V = 输出轨 {out_net} = "
                        f"{volts:g} V（档位对得上；档位来源 {declared_source}，"
                        f"轨压来源 {volts_source}）"
                    ),
                    evidence=evidence,
                ),
                "INFO",
            )
        return (
            Outcome(
                rule_id=self.id,
                state="VIOLATION",
                subject=ref,
                message=(
                    f"{ref}: 固定输出 {declared:g} V ≠ 输出轨 {out_net} = {volts:g} V，"
                    f"差 {declared - volts:+g} V —— 两份文档互相矛盾：换一颗档位"
                    f"等于该轨的件，或把轨名/合同里的电压改对（哪一边错是设计决定，"
                    f"本工具不替它选；档位来源 {declared_source}，轨压来源 "
                    f"{volts_source}）"
                ),
                evidence=evidence,
            ),
            "WARN",
        )

    def _declared_output(
        self, comp: Component, entry: PartEntry, params: dict[str, str]
    ) -> tuple[float | None, str]:
        """``(volts, where it came from)`` — the shelf's档位, strongest first."""
        cited = ldo_output_voltage_facts(entry)
        if cited is not None:
            volts, provenance = cited
            return volts, f"货架条目的 ldo.fixed_output 事实（{provenance}）"
        key, raw = _named(params, _LDO_OUTPUT_KEYS)
        volts = _read_volts(raw)
        if key and volts is not None:
            return volts, f"货架条目 {entry.key} 的 {key} = {raw!r}"
        mpn = entry.mpn or comp.mpn
        decoded = ldo_output_voltage(mpn) if mpn else None
        if decoded is not None:
            return decoded, (
                f"从料号 {mpn!r} 的受保护后缀解码——一个猜测：没有数据手册事实"
                f"声明它"
            )
        return None, ""