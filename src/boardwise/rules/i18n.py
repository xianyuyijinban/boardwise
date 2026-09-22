"""中文渲染：`boardwise review --md` 报告顶部的中文摘要（任务 018 §C.3）。

这份文件只做一件事——把报告里的**规则、位号、数值**换成中文说法，让不读英文
的人一眼看到"哪条规则、哪颗料、差多少"。它是发现的一条**附加读法**，不是新论断：

* 规则消息本体（英文）一字不改，仍在各自的原行里，评测配对不受影响；
* `review --json` 完全不经过这里（评测 harness 只读它认识的键）；
* 只给本 build 里真实存在的规则 id 起中文名（:data:`RULE_NAMES_ZH`），id 没有
  条目时**回退成 id 原文**，新规则不会因为漏登记而从摘要里消失。

中文文案都在这一层，包括 019 的空读提示（:data:`EMPTY_PCB_VIEW_HINT`）——但它
**什么时候出现**由 CLI 判断，本模块不认触发条件。

放在 `rules/` 层而不是 `cli.py`：中文名是规则的名称，与规则同层。本模块只用
标准库，不 import 任何上层模块（层规则见 `docs/architecture.md`，由
`tests/test_layer_rules.py` 检查）。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

#: 规则 id → 中文名。**只登记本 build 里存在的 rule id**（清单由
#: `tests/test_018_cli_review.py` 从规则类反推核对，多一个幽灵 id 或漏一个真实
#: id 都会红）。名字是"这条规则管什么"的短语，与 `Rule.title` 的英文同义，不是
#: 消息的翻译：消息本体不翻译。
#:
#: `decoupling-per-ic` 已从 `BUILTIN_RULES` 退役（任务 015 §2），但规则类仍在
#: （退役不是删除，重新加回列表即可再跑），所以它的 id 仍登记在这里。
RULE_NAMES_ZH: dict[str, str] = {
    "decoupling-per-ic": "IC 去耦电容",
    "conn-duplicate-designators": "位号重复",
    "xtal-load-caps": "晶振负载电容",
    "shunt-sense-link": "采样电阻检测连路",
    "decap-required-caps": "去耦电容是否齐备",
    "conn-nc-and-must-connect": "NC 与必连引脚",
    "conn-library-pins": "库符号引脚一致性",
    "pwr-supply-on-known-domain": "供电引脚电压未知",
    "pwr-domain-vs-range": "供电电压与工作范围",
    "path-ldo-dropout": "LDO 压差余量",
    "conn-usb-cc-pulldown": "USB CC 下拉电阻",
    "param-value-mpn-match": "位号值与 MPN 是否一致",
    "param-led-current": "LED 限流电阻",
    "param-divider-output": "分压输出",
    "param-rc-cutoff": "RC 截止频率",
}

#: 严重度 → 中文。三个词与 `severity_counts` 的键一一对应。
SEVERITY_NAMES_ZH: dict[str, str] = {
    "ERROR": "错误",
    "WARN": "警告",
    "INFO": "提示",
}

#: `.epro2` 的 pcb 视图什么都没读到时的中文提示（任务 019 §2）。
#:
#: 触发条件不在这里——那是 CLI 的判断（`cli._pcb_view_read_nothing`：`.epro2`
#: + pcb 视图 + 器件/网络/焊盘/走线/过孔全空）。本模块只管**怎么说**：文案归
#: i18n，是否触发出 CLI 决定，和 :data:`RULE_NAMES_ZH` 的分工一样。
#:
#: 为什么要有这句话：缺省 view 是 pcb，只画了原理图的导出会如实报"0 器件 0 网络"，
#: 读的人无从知道该加 `--view schematic`——工程里真的有内容，报告却说没有。
EMPTY_PCB_VIEW_HINT = (
    "提示：PCB 视图没有读到任何内容。"
    "如果你要审查的是原理图，请加 `--view schematic` 重新运行。"
)

#: 摘要里每条 finding 最多列几个关键数值：够看清"差多少"，又不至于把一行撑成
#: 一段话（消息本体就在下一行，英文原文一字不少）。
KEY_VALUE_LIMIT = 4

#: 关键数值：**带单位**的数（`12 pF`、`4.7kΩ`、`3.3 V`、`48 Hz`、`4.70x`）。
#: 只取带单位的：裸数字（位号里的 3、版本号 2.0.0、引脚号 pin16）不算——摘要要的
#: 是"差多少"，不是把消息里的每个数字都复读一遍。单位表按可能的最长匹配排列，
#: `mV`/`kHz`/`mΩ` 这类两段单位不会被拆成前面的单字母单位；单位后面必须是边界
#: （`(?![A-Za-z0-9])`），否则网名 `3V3` 会被读成数值 `3V`。
_KEY_VALUE = re.compile(
    r"[-+]?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:[pnumµ]?(?:F|H|Ω)|kΩ|MΩ|mΩ|ohms?|mV|kV|V|mA|A|mW|kW|W|"
    r"GHz|MHz|kHz|Hz|x|%|dB)(?![A-Za-z0-9])"
)


def rule_name_zh(rule_id: str) -> str:
    """规则 id 的中文名；没有登记时回退成 id 原文。"""
    return RULE_NAMES_ZH.get(rule_id, rule_id)


def severity_zh(severity: str) -> str:
    """严重度的中文名；未知严重度回退原文（不猜、不吞）。"""
    return SEVERITY_NAMES_ZH.get(severity, severity)


def key_values(message: str) -> list[str]:
    """消息里带单位的关键数值，首次出现顺序、去重、最多 :data:`KEY_VALUE_LIMIT` 个。"""
    found: list[str] = []
    for match in _KEY_VALUE.finditer(message or ""):
        token = match.group(0)
        if token not in found:
            found.append(token)
        if len(found) >= KEY_VALUE_LIMIT:
            break
    return found


def finding_line(
    *,
    severity: str,
    rule_id: str,
    message: str,
    refs: Sequence[str] = (),
) -> str:
    """一条发现的中文行：严重度 + 规则中文名 + (id) + 位号 + 关键数值。

    `位号值与 MPN 是否一致（param-value-mpn-match）：位号 U3；关键数值 4700 Ω、1000 Ω、4.70x`

    `refs` 由调用方给：位号的读法只有一处（`engines.review.finding_refs`，规则层
    不许 import 引擎层），而且调用方还要把结果按"这块板真的有没有这个位号"过滤
    ——见 `cli._finding_refs_for_summary`。两条都没有时就只报规则名：不编位号，
    也不编数值。
    """
    name = rule_name_zh(rule_id)
    head = f"- [{severity_zh(severity)}] {name}"
    if name != rule_id:
        head += f"（{rule_id}）"
    parts: list[str] = []
    if refs:
        parts.append("位号 " + "/".join(refs))
    values = key_values(message)
    if values:
        parts.append("关键数值 " + "、".join(values))
    if not parts:
        return head
    return head + "：" + "；".join(parts)


def summary_section(
    lines: Sequence[str], counts: Mapping[str, int], *, hint: str = ""
) -> str:
    """整节中文摘要（含标题、计数、逐条行），末尾是一个空行（与下一节分隔）。

    计数读的就是 :func:`engines.review.severity_counts` 的字典，缺键按 0 ——
    摘要说自己数字的时候不去猜。

    `hint` 非空时作为独立一段追加在末尾（任务 019 §2，空读提示）。放在**发现
    行之后**：它解释的是"为什么一条都没有"，紧跟结论读起来才对；单独成段
    （前后各一空行）而不是接着列表写，否则 markdown 会把它并进上一个列表项。
    缺省空串＝与 018 的输出逐字节一致。
    """
    error = counts.get("ERROR", 0)
    warn = counts.get("WARN", 0)
    info = counts.get("INFO", 0)
    block = [
        "## 中文摘要",
        "",
        f"共 {error + warn + info} 条发现：{error} 错误 / {warn} 警告 / {info} 提示",
        "",
    ]
    if lines:
        block.extend(lines)
    else:
        block.append("- 没有发现问题。")
    if hint:
        block.extend(["", hint])
    block.append("")
    return "\n".join(block)
