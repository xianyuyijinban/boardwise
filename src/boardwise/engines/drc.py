"""DRC normalisation (025 batch 3): the editor's two DRC answers → report sections.

Why a separate module rather than code inside `cli.py`: this is where a claim
about *the board* is made out of a claim the *host* made, and the two DRCs
disagree about how much they say — the schematic one answers aggregate counts,
the PCB one answers a per-item tree. A mapper that is one function per section,
with the raw payloads as its only input, is testable against recorded host
answers (the shapes are in `outputs/025_probe_p4_pcb_drc.txt` and the batch-1
record) instead of only against a live editor.

Three rules this layer exists to keep:

1. **Never invent per-item detail.** `sch_Drc.check` returns
   `[{type: 'fatalError'|'error'|'warn', count}]` (measured 2026-09-22, 025 §0),
   and the array is carried through as counts. Nothing here turns a count into a
   plausible-looking finding; the per-item list in the report is the *offline
   rule engine's*, and the schematic section says so.
2. **"Not checked" is not "clean".** A host refusal, a `checked: false` answer or
   an absent PCB document produces `{checked: false, reason}` — never a section
   with zero counts, which a reader cannot tell from a board that passed.
3. **Say which path produced a sentence.** A rendered leaf records whether it was
   a format-template hit, the host's text verbatim, or a `ruleName`/net fallback,
   because those three are different amounts of evidence.
4. **Take severity from the host when the host states one.** The tree has no
   `severity` field, but a leaf's `parentId` is the editor's own path to it
   (`DRCTab|_|Errors|_|…`) and its second segment names the tab — so the split
   between `summary.errors` and `summary.warnings` follows the editor's own
   placement, and only falls back to "ERROR, and say it was assumed" when that
   path says nothing.
"""

from __future__ import annotations

import re
from typing import Any

#: Who answered, per section. These strings are the report's provenance record:
#: `host-erc` is the editor's own electrical-rule check, `host-drc` its PCB
#: design-rule check, `offline-not-available` means the command never had an
#: editor to ask (the `--file` path).
SCHEMATIC_SOURCE = "host-erc"
PCB_SOURCE = "host-drc"
OFFLINE_SOURCE = "offline-not-available"

#: The note the schematic section carries, in the task book's words (025 §3).
SCHEMATIC_NOTE = "逐条见 findings 段（规则引擎）"

#: The caveat that keeps the note above from being read as "the two agree".
#:
#: They are two different engines: the host's ERC and the boardwise rules. On the
#: test project (measured 2026-09-23, `outputs/025c_checkup_live.txt`) the host
#: answers `warn: 1` while the rules return 0 findings — so a reader must not
#: reconcile the counts against the findings list, and the report says so
#: instead of letting the two numbers imply a coverage claim neither makes.
SCHEMATIC_NOTES: tuple[str, ...] = (
    "主机只回聚合计数（025 §0 实测），逐条细节不在返回值里（在编辑器底部面板，扩展无读接口）",
    "findings 段是 boardwise 自有规则引擎的结果，与主机 ERC 不是同一套规则，两边计数不可互推",
)

#: How a PCB leaf's severity is decided.
#:
#: **Measured 2026-09-23**: the host's tree carries no severity *field*, but it
#: does carry the editor's own path to the item — `parentId` reads
#: `DRCTab|_|Errors|_|<group>|<group>`, whose second segment names the tab the
#: item appears under. That segment is used when it is readable; a leaf whose
#: `parentId` says nothing about it is treated as an ERROR with
#: `severitySource: 'assumed'`, because over-reporting a warning is the failure a
#: reviewer can see and correct, while under-reporting one is silent.
PCB_SEVERITY_BASIS = "parentId-second-segment"

#: The tab names the host's `parentId` has been seen to use, lower-cased.
_SEVERITY_SEGMENTS: dict[str, str] = {
    "error": "ERROR",
    "errors": "ERROR",
    "warning": "WARN",
    "warnings": "WARN",
    "warn": "WARN",
}


def severity_from_parent_id(parent_id: Any) -> tuple[str, str]:
    """`(severity, source)` from the host's own path to a leaf."""
    for segment in str(parent_id or "").split("|_|"):
        found = _SEVERITY_SEGMENTS.get(segment.strip().lower())
        if found:
            return found, "parentId"
    return "ERROR", "assumed"

#: `{name}` placeholders a host explanation may carry for its `param` map.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: Count kinds the schematic DRC answers, and the severity each one is.
COUNT_SEVERITY: dict[str, str] = {
    "fatalError": "ERROR",
    "error": "ERROR",
    "warn": "WARN",
}


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    """A host string, or `''` — never the string `'None'`."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


# --------------------------------------------------------------------------
# the schematic side: counts only, and it must stay that way
# --------------------------------------------------------------------------


def _counts_of(payload: dict) -> dict[str, int]:
    """`{kind: count}` from the host's count array, adding repeated kinds.

    Adding rather than overwriting because the array's contract is "one entry per
    kind" but nothing enforces it; a duplicated kind that silently overwrote its
    twin would under-report. A non-numeric `count` is reported by the caller as
    an unparsable entry — it never becomes a zero here, which is what would make
    a broken entry look like a clean one.
    """
    counts: dict[str, int] = {}
    for entry in _as_list(payload.get("counts")):
        if not isinstance(entry, dict):
            continue
        kind = _text(entry.get("type")) or "(entry without a type)"
        value = entry.get("count")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        counts[kind] = counts.get(kind, 0) + int(value)
    return counts


def _unparsable_entries(payload: dict) -> int:
    """Count-array entries whose `count` is not a number."""
    bad = 0
    for entry in _as_list(payload.get("counts")):
        if not isinstance(entry, dict):
            bad += 1
            continue
        value = entry.get("count")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            bad += 1
    return bad


def _page_reading(reading: dict) -> dict:
    """One page's DRC answer in report form, or the reason there is none."""
    page_uuid = reading.get("pageUuid")
    error = reading.get("error")
    if error:
        return {
            "pageUuid": page_uuid,
            "checked": False,
            "reason": f"{error.get('code')}: {error.get('message')}",
        }
    payload = _as_dict(reading.get("payload"))
    if not payload:
        return {"pageUuid": page_uuid, "checked": False, "reason": "no answer was recorded"}
    if payload.get("checked") is False:
        return {
            "pageUuid": page_uuid,
            "checked": False,
            "reason": payload.get("reason") or "the host reported that no check ran",
        }
    mode = _text(payload.get("mode")) or "counts"
    if mode == "counts":
        counts = _counts_of(payload)
        return {
            "pageUuid": page_uuid,
            "checked": True,
            "mode": mode,
            "counts": counts,
            "total": sum(counts.values()),
            "passed": payload.get("passed"),
            "elapsedMs": payload.get("elapsedMs"),
            **({"unparsableEntries": n} if (n := _unparsable_entries(payload)) else {}),
        }
    if mode == "boolean":
        # The host ignored `includeVerboseError: true` and said only "passed" or
        # not. That is a verdict without a count, and it is carried as exactly
        # that: `countsKnown: false`, never an empty count array.
        return {
            "pageUuid": page_uuid,
            "checked": True,
            "mode": "boolean",
            "countsKnown": False,
            "passed": payload.get("passed"),
            "elapsedMs": payload.get("elapsedMs"),
            "note": _text(payload.get("note")) or "the host answered a boolean",
        }
    return {
        "pageUuid": page_uuid,
        "checked": True,
        "mode": "unexpected",
        "countsKnown": False,
        "reason": "the host's answer is neither a count array nor a boolean",
        "elapsedMs": payload.get("elapsedMs"),
    }


def schematic_section(readings: list[dict]) -> dict:
    """The `drc.schematic` section from one reading per schematic page.

    **The top-level counts are not a sum unless the pages disagreed.** Measured
    2026-09-23: `sch_Drc.check` answers the *same* `[{type:'warn',count:1}]` for
    all four pages of the test project, so its counts are not page-scoped, and
    summing four identical readings would report four warnings where the host
    says one. The rule is therefore: readings that agree are reported once
    (`countsBasis: host-wide`, which is the ordinary case); readings that differ
    are summed and labelled `sum-of-pages`, because then per-page scoping is the
    only explanation left. Either way `pages` keeps the individual readings, so
    the reader can check the rule against the evidence.
    """
    pages = [_page_reading(reading) for reading in readings]
    checked = [page for page in pages if page.get("checked")]
    if not checked:
        reason = "no schematic page answered the ERC"
        if pages:
            reason = pages[0].get("reason") or reason
        return {
            "checked": False,
            "source": SCHEMATIC_SOURCE,
            "reason": reason,
            "pages": pages,
            "note": SCHEMATIC_NOTE,
            "notes": list(SCHEMATIC_NOTES),
        }

    counted = [page for page in checked if page.get("mode") == "counts"]
    section: dict[str, Any] = {
        "checked": True,
        "source": SCHEMATIC_SOURCE,
        "pageCount": len(pages),
        "pagesChecked": len(checked),
        "pages": pages,
        "note": SCHEMATIC_NOTE,
        "notes": list(SCHEMATIC_NOTES),
    }
    if len(checked) != len(pages):
        section["pagesUnreadable"] = len(pages) - len(checked)

    if not counted:
        # Every answer was a boolean (or something stranger): a verdict without
        # counts. Carried as an unknown count, not as zero.
        passed = all(page.get("passed") is not False for page in checked)
        section.update({
            "countsKnown": False,
            "mode": checked[0].get("mode"),
            "passed": passed,
            "totals": {},
            "countsBasis": "unavailable",
        })
        section["notes"] = [
            *section["notes"],
            "主机没有给出计数（只回了 boolean）：本段只有 passed/未通过，计数列为未知，不是 0",
        ]
        return section

    first = counted[0].get("counts", {})
    agree = all(page.get("counts", {}) == first for page in counted)
    if agree:
        basis = "host-wide"
        totals = dict(first)
    else:
        basis = "sum-of-pages"
        totals: dict[str, int] = {}
        for page in counted:
            for kind, value in page.get("counts", {}).items():
                totals[kind] = totals.get(kind, 0) + value
        section["notes"] = [
            *section["notes"],
            "各页读数不一致，故本段按页求和（countsBasis=sum-of-pages）；逐页读数见 pages",
        ]
    for kind in COUNT_SEVERITY:
        # Present only when the host stated it: an absent kind must not read as
        # an explicit zero the host never gave.
        if kind in totals:
            section[kind] = totals[kind]
    section.update({
        "totals": totals,
        "total": sum(totals.values()),
        "countsBasis": basis,
        "pageCountsAgree": agree,
        "passed": all(page.get("passed") for page in counted) if len(counted) == len(checked) else None,
    })
    if basis == "host-wide" and len(counted) > 1:
        section["notes"] = [
            *section["notes"],
            f"{len(counted)} 页读数完全相同，故按主机口径报一次，不按页累加（实测：test 工程 4 页均回 warn 1）",
        ]
    return section


# --------------------------------------------------------------------------
# the PCB side: a per-item tree, carried through with its fields intact
# --------------------------------------------------------------------------


def _render_explanation(explanation: Any, leaf: dict) -> tuple[str, str]:
    """The host's explanation as one sentence, plus *how* it was produced.

    The declaration's shape is `{str, param}` — a template and its values — and
    the measured netlist-error leaf carries `param: {}` with the sentence already
    filled in. So: fill the placeholders when every one of them has a value,
    otherwise pass the host's text through verbatim, and fall back to
    `ruleName` + net when there is no text at all. The three cases are reported
    (`rendered`) rather than normalised into one, because "the host told us this
    sentence" and "we assembled a label from two fields" are different evidence.
    """
    mapping = _as_dict(explanation)
    text = _text(mapping.get("str")) or _text(explanation)
    params = _as_dict(mapping.get("param"))
    if text:
        names = _PLACEHOLDER.findall(text)
        if names and all(name in params for name in names):
            try:
                values = {name: str(params[name]) for name in names}
                return text.format(**values), "template"
            except (KeyError, IndexError, ValueError):
                # A host template with braces we cannot fill is still the host's
                # sentence; printing it unformatted beats printing nothing.
                return text, "verbatim"
        return text, "verbatim"

    parts: list[str] = []
    rule = _text(leaf.get("ruleName")) or _text(leaf.get("ruleTypeName"))
    if rule:
        parts.append(rule)
    if net := _text(leaf.get("net")):
        parts.append(f"net {net}")
    if pos := _as_dict(leaf.get("pos")):
        x, y = pos.get("x"), pos.get("y")
        if x is not None and y is not None:
            parts.append(f"@({x}, {y})")
    if (layer := leaf.get("layer")) is not None:
        parts.append(f"layer {layer}")
    if parts:
        return " / ".join(parts), "fallback"
    return "", "none"


def _map_leaf(leaf: Any) -> dict:
    """One DRC leaf, mapped plus kept whole under `raw`."""
    raw = _as_dict(leaf)
    sentence, how = _render_explanation(raw.get("explanation"), raw)
    severity, severity_source = severity_from_parent_id(raw.get("parentId"))
    mapped: dict[str, Any] = {
        "ruleName": _text(raw.get("ruleName")),
        "ruleTypeName": _text(raw.get("ruleTypeName")),
        "errorType": _text(raw.get("errorType")),
        "errorObjType": _text(raw.get("errorObjType")),
        "net": _text(raw.get("net")),
        "severity": severity,
        "severitySource": severity_source,
        "explanation": sentence,
        "rendered": how,
        "globalIndex": _text(raw.get("globalIndex")),
        "parentId": _text(raw.get("parentId")),
        "raw": raw,
    }
    for source_key, target_key in (("pos", "pos"), ("layer", "layer"),
                                   ("obj1", "obj1"), ("obj2", "obj2"), ("objs", "objs")):
        if raw.get(source_key) is not None:
            mapped[target_key] = raw[source_key]
    return mapped


def _map_group(group: Any, index: int) -> dict:
    """One group (`group.list[].list[]` in the measured tree) and its leaves.

    A group whose `list` holds further groups is walked to its leaves; the
    intermediate node's own `name`/`title`/`count` are kept because they are what
    the editor's DRC panel shows, and a report that dropped them would be harder
    to check against the panel.
    """
    raw = _as_dict(group)
    leafs: list[dict] = []
    children: list[dict] = []
    for child in _as_list(raw.get("list")) or _as_list(raw.get("children")):
        child_dict = _as_dict(child)
        nested = _as_list(child_dict.get("list")) or _as_list(child_dict.get("children"))
        if nested:
            # A node with children is a group, not a leaf: its leafs stay under it
            # so the tree is not counted twice (the measured shape really is
            # `group.list[].list[leaf]`, 2026-09-23).
            children.append(_map_group(child, len(children)))
        else:
            leafs.append(_map_leaf(child))
    mapped: dict[str, Any] = {
        "index": index,
        "name": _text(raw.get("name")) or _text(raw.get("type")) or "(unnamed group)",
        "title": raw.get("title") if isinstance(raw.get("title"), list) else [],
        "count": raw.get("count"),
        "leafs": leafs,
    }
    if children:
        mapped["children"] = children
    if _text(raw.get("parentId")):
        mapped["parentId"] = _text(raw.get("parentId"))
    return mapped


def pcb_section(reading: dict | None, *, documents_listed: int = 0) -> dict:
    """The `drc.pcb` section from one `pcb_Drc.check` reading.

    The three "no board to check" shapes are kept together and apart from a
    clean board: the host's declared `undefined`, the throw a non-PCB page
    actually produces (measured 2026-09-23: `指定的主题消息在对应的画布内没有相关订阅`),
    and "no PCB document was listed at all". All three become
    `{checked: false, reason}` with no counts, because "we did not check" and
    "we checked and found nothing" are the two answers a reviewer must never be
    handed the same way round.
    """
    if reading is None:
        return {
            "checked": False,
            "source": PCB_SOURCE,
            "reason": "no PCB document was listed for this project",
            "documentsListed": documents_listed,
        }
    if error := reading.get("error"):
        return {
            "checked": False,
            "source": PCB_SOURCE,
            "reason": f"{error.get('code')}: {error.get('message')}",
            "documentUuid": reading.get("documentUuid"),
            "documentsListed": documents_listed,
        }
    payload = _as_dict(reading.get("payload"))
    if not payload:
        return {
            "checked": False,
            "source": PCB_SOURCE,
            "reason": "no answer was recorded",
            "documentUuid": reading.get("documentUuid"),
            "documentsListed": documents_listed,
        }
    if payload.get("checked") is False:
        return {
            "checked": False,
            "source": PCB_SOURCE,
            "reason": _text(payload.get("reason")) or "the host reported that no check ran",
            "documentUuid": reading.get("documentUuid"),
            "documentsListed": documents_listed,
        }
    mode = _text(payload.get("mode")) or "groups"
    base: dict[str, Any] = {
        "checked": True,
        "source": PCB_SOURCE,
        "documentUuid": reading.get("documentUuid"),
        "documentsListed": documents_listed,
        "mode": mode,
        "elapsedMs": payload.get("elapsedMs"),
        "severityBasis": PCB_SEVERITY_BASIS,
        "notes": [
            "叶子 severity 取自宿主自己的 parentId 第二段（实测 DRCTab|_|Errors|_|… ⇒ Errors 页）；"
            "读不出那一段时按 ERROR 记并标 severitySource='assumed'（偏严不偏松）",
        ],
    }
    if mode == "boolean":
        base.update({
            "countsKnown": False,
            "passed": payload.get("passed"),
            "groups": [],
            "totals": {},
            "note": _text(payload.get("note")) or "the host answered a boolean",
        })
        return base
    if mode == "unexpected":
        base.update({
            "countsKnown": False,
            "groups": [],
            "totals": {},
            "raw": payload.get("raw"),
            "reason": "the host's answer is not the declared group array",
        })
        return base

    groups = [_map_group(group, index) for index, group in enumerate(_as_list(payload.get("groups")))]
    host_counts = _as_dict(payload.get("counts"))
    leaf_count = sum(_count_leafs(group) for group in groups)
    totals = {
        "groups": host_counts.get("groups", len(groups)),
        "groupsReturned": host_counts.get("returnedGroups", len(groups)),
        "leafs": leaf_count,
        "hostErrors": host_counts.get("errors"),
        "hostErrorsSource": _text(host_counts.get("errorsSource")),
        "byRule": _count_leaves_by_rule(groups),
        "bySeverity": _count_leaves_by_severity(groups),
    }
    truncated = bool(payload.get("truncated")) or bool(host_counts.get("returnedGroups", len(groups))) < len(groups)
    base.update({
        "groups": groups,
        "totals": totals,
        "truncated": truncated,
    })
    dropped = None
    if isinstance(totals["groups"], int) and isinstance(totals["groupsReturned"], int):
        dropped = totals["groups"] - totals["groupsReturned"]
    if dropped:
        base["droppedGroups"] = dropped
        base["notes"] = [
            *base["notes"],
            f"连接器按 maxChars 整组丢弃了 {dropped} 组（不切半）：totals 描述整份答复，groups 只含返回的部分",
        ]
    if payload.get("notes"):
        base["connectorNotes"] = payload["notes"]
    return base


def _count_leafs(group: dict) -> int:
    total = len(_as_list(group.get("leafs")))
    for child in _as_list(group.get("children")):
        total += _count_leafs(child)
    return total


def _leaf_refs(group: dict) -> list[tuple[str, list]]:
    """Every leaf list under one group, with the path segment that reaches it.

    Returns `("", <group's own leafs>)` and `("children[i]", <that child's
    leafs>)`, one level at a time, so the summary can build a reference that a
    reader can follow without this module owning the traversal twice.
    """
    out: list[tuple[str, list]] = [("", _as_list(group.get("leafs")))]
    for index, child in enumerate(_as_list(group.get("children"))):
        for suffix, leaves in _leaf_refs(child):
            path = f"children[{index}]" + (f".{suffix}" if suffix else "")
            out.append((path, leaves))
    return out


def _count_leaves_by_severity(groups: list[dict]) -> dict[str, int]:
    """`{severity: leaf count}` over the mapped groups (see `severity_from_parent_id`)."""
    by_severity: dict[str, int] = {}

    def walk(group: dict) -> None:
        for leaf in _as_list(group.get("leafs")):
            severity = leaf.get("severity") or "ERROR"
            by_severity[severity] = by_severity.get(severity, 0) + 1
        for child in _as_list(group.get("children")):
            walk(child)

    for group in groups:
        walk(group)
    return by_severity


def _count_leaves_by_rule(groups: list[dict]) -> dict[str, int]:
    """`{ruleName-or-fallback: leaf count}` over the mapped groups."""
    by_rule: dict[str, int] = {}
    def walk(group: dict) -> None:
        for leaf in _as_list(group.get("leafs")):
            label = leaf.get("ruleName") or leaf.get("errorType") or "(no rule name)"
            by_rule[label] = by_rule.get(label, 0) + 1
        for child in _as_list(group.get("children")):
            walk(child)
    for group in groups:
        walk(group)
    return by_rule


# --------------------------------------------------------------------------
# 123: the rule set the DRC was measured against
# --------------------------------------------------------------------------

#: Who answered the rule-set read. Same provenance discipline as the two sections
#: above: the report must be able to say *where* each sentence came from.
RULESET_SOURCE = "host-drc-ruleset"

#: The reference table's file name, relative to `blocklib/`.
RULESET_REFERENCE_FILE = "drc_ruleset_reference.json"

#: What the host nests the rules under, measured 2026-10-06 on test/PCB1.
#: `{name, config}` at the top; the rules themselves live under `config`, and each
#: rule carries `unit` / `isSetDefault` plus either a `form` (scalars) or a
#: `tables` (a matrix keyed by copper thickness). `data.1` is the 1 oz row —
#: the table index is the copper thickness in ounces, so `data.1` is this board's
#: 1 oz entry and not a "first element".
RULESET_CONFIG_KEY = "config"
RULESET_THICKNESS_INDEX = "1"

#: The whole reading, verbatim, under one key. Kept whole because the host's
#: rule set is the *evidence*: a meta-review that quotes only the keys it
#: compared is a summary of the rules, not the rules, and a reader who wants to
#: check a different key has nothing to check against.
RULESET_RAW_KEY = "raw"


def _load_ruleset_reference() -> dict | None:
    """The reference table, or `None` when the file is absent or unreadable.

    A missing table is **not** a section full of violations and not a silent
    skip: the caller reports `checked: true` with `metaAudit.available: false`
    and the reason, because "we compared nothing" and "everything matched" are
    the same thing to a reader who is not told otherwise.
    """
    from .. import resources

    try:
        path = resources.drc_ruleset_reference()
    except Exception:  # noqa: BLE001 — a root that cannot be located is not a crash
        return None
    if not path.is_file():
        return None
    try:
        import json

        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _resolve_ruleset_path(reading: dict, dotted: str) -> Any:
    """One dot-joined key path into a ruleset reading, or the ``MISSING`` marker.

    The host's nesting is stable but its *key names* are editor text (`Via Size`,
    `Safe Spacing`, a space in the middle of a category name), which is why the
    reference table spells the whole path rather than walking a schema. A path
    that does not resolve returns :data:`RULESET_MISSING` — never `None`, which
    would be indistinguishable from a rule whose value genuinely is null.
    """
    node: Any = reading
    for part in str(dotted).split("."):
        if not isinstance(node, dict) or part not in node:
            return RULESET_MISSING
        node = node[part]
    return node


def _resolve_ruleset_unit(reading: dict, dotted: str) -> Any:
    """The unit a ruleset value is expressed in, read along its own path.

    The host carries ``unit`` at the rule-group level (the object that holds
    ``form``), and the same rule set is written in **whatever unit the project
    uses**: test/PCB1's capability set reads ``mm``, 毕设FOC's custom set reads
    ``mil`` — measured 2026-10-06, when the meta-audit's first real-board run
    flagged every key off-reference because 5 (mil) was compared against
    0.127 (mm). The deepest ``unit`` on the path wins, so an ounce-row that
    overrides its group is read in its own unit. Returns ``None`` when no level
    says a unit — and the caller treats that as unreadable, because a number
    without a unit is not a measurement.
    """
    node: Any = reading
    unit: Any = None
    for part in str(dotted).split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
        if isinstance(node, dict) and isinstance(node.get("unit"), str):
            unit = node["unit"]
    return unit


#: The sentinel a dotted path returns when it does not resolve. A private object
#: so it can never be produced by, or confused with, a value the host returned.
RULESET_MISSING = object()


def _compare_ruleset_key(check: dict, actual: Any, actual_unit: Any = None) -> dict:
    """One reference key against what the host answered.

    Three outcomes, kept apart on purpose:

    * ``within`` — the value is the reference value up to ``tolerance``;
    * ``outside`` — it is not, with the direction and the numbers both carried,
      because "间距比工艺下限小" and "间距比工艺下限大" are different problems;
    * ``unreadable`` — the path did not resolve, i.e. **the key was not read**.
      This never becomes a violation: an absent key is a hole in the reading, and
      filling it with the reference value would let a missing measurement pass
      as a matching one.

    Units are never converted by the engine (123d, and `test_coordinate_guards`
    makes that a hard boundary: mil↔mm factors belong to parsers +
    canvas_pin_offsets, not to engines). The reference table carries each
    expectation **per unit** (``{"mm": …, "mil": …}`` — the two numbers'
    consistency is pinned by a test, where the conversion factor is allowed to
    live); the comparison reads the value in the host's own unit. A unit the
    reference does not name, or no unit on the path at all, is ``unreadable`` —
    not a silent mm assumption. The same rule set genuinely arrives in the
    project's own unit (mm on test/PCB1, mil on 毕设FOC — the first real-board
    run flagged 5 vs 0.127 as a violation; it is 5 mil against a 0.127 mm
    reference, i.e. a perfect match).
    """
    entry = {
        "key": check.get("key"),
        "label": check.get("label"),
        "path": check.get("path"),
        "unit": check.get("unit"),
        "severity": check.get("severity"),
    }
    if actual is RULESET_MISSING:
        return {**entry, "status": "unreadable", "why": check.get("why")}
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return {
            **entry,
            "status": "unreadable",
            "actual": actual,
            "why": check.get("why"),
            "whyUnreadable": "the host answered something that is not a number",
        }
    expected = check.get("expected")
    tolerance = check.get("tolerance")
    if not isinstance(expected, dict):
        return {**entry, "status": "unreadable", "actual": actual,
                "whyUnreadable": "the reference table holds no per-unit expected values"}
    if actual_unit is None:
        return {**entry, "status": "unreadable", "actual": actual,
                "whyUnreadable": "the reading carries no unit along this path — "
                                "a number without a unit is not a measurement"}
    expected_here = expected.get(actual_unit)
    if not isinstance(expected_here, (int, float)) or isinstance(expected_here, bool):
        return {**entry, "status": "unreadable", "actual": actual,
                "actualUnit": actual_unit,
                "whyUnreadable": f"the reference table names no value in unit "
                                 f"{actual_unit!r} — not converted by guess"}
    entry["actualUnit"] = actual_unit
    value = float(actual)
    slack = abs(float(expected_here)) * float(tolerance) if isinstance(tolerance, (int, float)) else 0.0
    delta = value - float(expected_here)
    if abs(delta) <= slack:
        return {**entry, "status": "within", "actual": actual, "expected": expected_here,
                "delta": delta, "tolerance": slack}
    direction = check.get("direction")
    offending = delta < 0 if direction == "below" else delta > 0 if direction == "above" else True
    if not offending:
        # Off the reference value in the *harmless* direction. Still reported —
        # a rule set that was loosened is a fact about the board — but marked so
        # it is not read as a violation.
        return {**entry, "status": "off-reference", "actual": actual, "expected": expected_here,
                "delta": delta, "tolerance": slack,
                "why": check.get("why"),
                "note": "偏离参考值，但方向是本表标注的无害侧；报出是因为板子确实用了另一套工艺，"
                        "不是缺陷判定"}
    return {**entry, "status": "outside", "actual": actual, "expected": expected_here,
            "delta": delta, "tolerance": slack, "direction": direction, "why": check.get("why")}


def ruleset_section(reading: dict | None, *, documents_listed: int = 0) -> dict:
    """The `drc.ruleset` section: the DRC rule set, verbatim plus a meta-audit.

    A PCB DRC result is a statement **about a rule set** — the same geometry
    passes under one clearance and fails under another — so leaves without these
    are half an answer. `pcb.drc_check` got the leaves (025); this gets the
    other half.

    Two things, kept apart because they are different amounts of evidence:

    * **the reading** (`ruleset.raw`) — the host's own object, unchanged. It is
      the evidence: a meta-audit that quotes only the keys it compared is a
      summary of the rules, not the rules, and a reader who wants to check some
      other key has nothing to check against. Nothing is normalised, sorted or
      summarised away.
    * **the meta-audit** (`ruleset.metaAudit`) — each key of the reference table
      (`blocklib/drc_ruleset_reference.json`) against what was actually read.

    The meta-audit's rule is the one that keeps it from being a rubber stamp: a
    key whose path did not resolve is reported ``unreadable``, **not** ``within``.
    Substituting the reference value for a measurement that was never taken is
    how a review acquires a clean sheet it did not earn.

    The section never fails the command, and it never raises the report's
    ``exitCode`` itself: a rule set that drifted from the reference is a finding
    for the findings layer, recorded here with the numbers, not a verdict this
    function pronounces.
    """
    base: dict[str, Any] = {
        "checked": False,
        "source": RULESET_SOURCE,
        "note": "规则集是 DRC 结论的前提：同一块图在两套规则下结论不同，故 DRC 逐条要连着本段读；"
                "本段只报读数与元审查，不自己下判决",
    }
    if reading is None:
        return {**base, "reason": "no PCB document was listed for this project",
                "documentsListed": documents_listed}
    if error := reading.get("error"):
        return {**base, "reason": f"{error.get('code')}: {error.get('message')}",
                "documentUuid": reading.get("documentUuid"),
                "documentsListed": documents_listed}
    payload = _as_dict(reading.get("payload"))
    if not payload:
        return {**base, "reason": "no answer was recorded",
                "documentUuid": reading.get("documentUuid"),
                "documentsListed": documents_listed}

    ruleset = _as_dict(payload.get("ruleset"))
    current = _as_dict(ruleset.get("current"))
    checks_out: list[dict] = []
    notes: list[str] = []
    unavailable: list[str] = []
    for path in _as_list(payload.get("missing")):
        unavailable.append(f"宿主无此成员：{path}")
    for path in _as_list(payload.get("unreadable")):
        unavailable.append(f"这一项没读出来：{path}")
    notes.extend(_as_list(payload.get("notes")))
    if unavailable:
        # Which members, not just that some were — a reader who has to guess
        # which half of the reading is missing cannot act on the other half.
        notes.append("、".join(unavailable))
        notes.append(
            "有成员没读到 —— 下面标 unreadable 的键**没有**拿参考值顶替，"
            "缺读不是匹配（这是本段元审查唯一的硬纪律）"
        )

    section: dict[str, Any] = {
        **base,
        "checked": True,
        "documentUuid": reading.get("documentUuid"),
        "documentsListed": documents_listed,
        "ruleSetName": _text(ruleset.get("currentName")),
        "defaultRuleSetName": _text(ruleset.get("defaultName")),
        "realTimeDrcStatus": ruleset.get("realTimeDrcStatus"),
        "reads": _as_list(payload.get("reads")),
        "elapsedMs": payload.get("elapsedMs"),
        "ruleset": {
            RULESET_RAW_KEY: current,
            "name": _text(current.get("name")),
            "configCategories": sorted(_as_dict(current.get(RULESET_CONFIG_KEY)).keys()),
            "present": bool(current),
        },
        "notes": notes,
    }
    if not current:
        section["reason"] = (
            "the host answered the rule-set reads but held no `current` object — reported as "
            "no reading, not as a board with no rules"
        )
        return section

    reference = _load_ruleset_reference()
    if reference is None:
        section["metaAudit"] = {
            "available": False,
            "reason": f"参考表读不到（blocklib/{RULESET_REFERENCE_FILE}）—— 元审查没有跑，"
                      "不是「都匹配」",
        }
        return section

    checks = _as_list(reference.get("checks"))
    for check in checks:
        if not isinstance(check, dict):
            continue
        dotted = str(check.get("path") or "")
        checks_out.append(_compare_ruleset_key(
            check,
            _resolve_ruleset_path(current, dotted),
            _resolve_ruleset_unit(current, dotted),
        ))

    topology = _as_dict(reference.get("expectedTopology"))
    wanted_categories = [str(name) for name in _as_list(topology.get("categories"))]
    present = set(section["ruleset"]["configCategories"])
    missing_categories = [name for name in wanted_categories if name not in present]

    statuses = [entry["status"] for entry in checks_out]
    section["metaAudit"] = {
        "available": True,
        "referenceFile": f"blocklib/{RULESET_REFERENCE_FILE}",
        "referenceProvenance": reference.get("provenance"),
        "referenceSet": _as_dict(reference.get("referenceSet")),
        "expectedCategories": wanted_categories,
        "missingCategories": missing_categories,
        "keysChecked": len(checks_out),
        "within": statuses.count("within"),
        "outside": statuses.count("outside"),
        "offReference": statuses.count("off-reference"),
        "unreadable": statuses.count("unreadable"),
        "checks": checks_out,
    }
    if missing_categories:
        section["notes"] = [
            *section["notes"],
            f"规则集少了参考表预期的大类：{'、'.join(missing_categories)}—— "
            "这不是「那几个类别没有规则」，而是这份读数可能不是我们以为的那一整份",
        ]
    outside = [entry for entry in checks_out if entry["status"] == "outside"]
    if outside:
        section["notes"] = [
            *section["notes"],
            f"{len(outside)} 个键超界（{('、'.join(str(e['key']) for e in outside))}）—— "
            "逐键数字见 metaAudit.checks；本段不下判决，判不判归 findings 层",
        ]
    unreadable = [entry for entry in checks_out if entry["status"] == "unreadable"]
    if unreadable:
        # Per key, not just a count: which limit was not measured is what tells a
        # reader whether the rest of the audit can be believed.
        section["notes"] = [
            *section["notes"],
            f"{len(unreadable)} 个键没读到（{'、'.join(str(e['key']) for e in unreadable)}）—— "
            "**没有**拿参考值顶替；缺读不是匹配，这些键本段不作任何结论",
        ]
    if statuses and len(unreadable) == len(statuses):
        section["notes"] = [
            *section["notes"],
            "参考表里的键一个都没读到 —— 本段的元审查没有产生任何结论，"
            "这不是「都匹配」",
        ]
    return section


def ruleset_finding_lines(section: dict) -> list[dict]:
    """The rule-set rows that deserve a `findings[]` entry, and only those.

    ``outside`` becomes a finding; ``off-reference`` (the harmless direction) and
    ``unreadable`` (the key was never read) do not. The reason is the same one
    that governs the whole report: **a measurement that was not taken must not be
    able to produce a defect**, and a value that drifted in the direction the
    reference table marks harmless is a fact about the process, not a fault.

    Severity comes from the reference table's own `severity`, because the table
    is where the judgement was made and written down; this function does not
    invent one.
    """
    audit = _as_dict(_as_dict(section).get("metaAudit"))
    if audit.get("available") is not True:
        return []
    out: list[dict] = []
    for entry in _as_list(audit.get("checks")):
        entry = _as_dict(entry)
        if entry.get("status") != "outside":
            continue
        key = str(entry.get("key") or "")
        out.append({
            "rule_id": "pcb-drc-ruleset-out-of-reference",
            "severity": str(entry.get("severity") or "WARN").upper(),
            "message": (
                f"DRC 规则集 `{_as_dict(section).get('ruleSetName') or '(unnamed)'}` 的"
                f"「{entry.get('label')}」= {entry.get('actual')}{entry.get('unit') or ''}，"
                f"参考值 {entry.get('expected')}{entry.get('unit') or ''}"
                f"（差 {entry.get('delta')}）。{entry.get('why') or ''} 见 drc.ruleset.metaAudit"
            ),
            "refs": ["drc.ruleset"],
            "target": {
                "source": RULESET_SOURCE,
                "key": key,
                "path": entry.get("path"),
                "actual": entry.get("actual"),
                "expected": entry.get("expected"),
                "delta": entry.get("delta"),
                "direction": entry.get("direction"),
            },
        })
    return out


def offline_section(reason: str) -> dict:
    """A section for the `--file` path, where there is no editor to ask."""
    return {
        "checked": False,
        "source": OFFLINE_SOURCE,
        "reason": reason,
        "note": "离线路径不连编辑器，故没有主机 DRC；要它就给一个在线的 test/test2 工程",
    }


# --------------------------------------------------------------------------
# 分流: what a reader (and the exit code) needs from both sections + findings
# --------------------------------------------------------------------------


def summarise(*, drc: dict, findings: list[dict]) -> dict:
    """Split everything the report found into errors and warnings, with refs.

    "Counts plus references", not a second copy of the content: every entry names
    the section it came from (`drc.schematic`, `drc.pcb.groups[i].leafs[j]`,
    `findings[i]`) so a reader can go and check it, and no entry paraphrases what
    it points at. The exit code is decided here so the console line and the
    report cannot disagree about it.

    A count that is **not known** (a boolean answer, a truncated tree) is
    reported with `count: None` and marks the summary `countsIncomplete` — the
    errors are still real, they are just not enumerable, and an exit 0 would
    claim the board is clean.
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    counts_incomplete = False

    schematic = _as_dict(_as_dict(drc).get("schematic"))
    if schematic.get("checked") and schematic.get("countsKnown") is False:
        # A boolean answer: the host gave a verdict without counts. If it said
        # "passed" there is nothing to enumerate; anything else (including "it
        # did not say") leaves real errors whose count is unknown.
        if schematic.get("passed") is not True:
            counts_incomplete = True
            errors.append({
                "section": "drc.schematic",
                "source": SCHEMATIC_SOURCE,
                "severity": "ERROR",
                "count": None,
                "countsKnown": False,
                "ref": "drc.schematic",
                "detail": "主机未给计数（boolean 答复且未通过），逐条与总数都不可枚举",
            })
    elif schematic.get("checked"):
        for kind, severity in COUNT_SEVERITY.items():
            if kind not in schematic:
                continue
            bucket = errors if severity == "ERROR" else warnings
            bucket.append({
                "section": "drc.schematic",
                "source": SCHEMATIC_SOURCE,
                "severity": severity,
                "kind": kind,
                "count": schematic[kind],
                "ref": "drc.schematic",
                "detail": "主机 ERC 聚合计数；逐条不在返回值里（见 findings 段的说明）",
            })

    pcb = _as_dict(_as_dict(drc).get("pcb"))
    if pcb.get("checked"):
        if pcb.get("countsKnown") is False:
            if pcb.get("passed") is not True:
                counts_incomplete = True
                errors.append({
                    "section": "drc.pcb",
                    "source": PCB_SOURCE,
                    "severity": "ERROR",
                    "count": None,
                    "countsKnown": False,
                    "ref": "drc.pcb",
                    "detail": "主机未给逐条（boolean 或非声明形态），计数未知",
                })
        for group in _as_list(pcb.get("groups")):
            for group_ref, leaves in _leaf_refs(group):
                for leaf_index, leaf in enumerate(leaves):
                    index = group.get("index")
                    suffix = f"drc.pcb.groups[{index}]" if group_ref == "" else f"drc.pcb.groups[{index}].{group_ref}"
                    severity = leaf.get("severity") or "ERROR"
                    bucket = errors if severity == "ERROR" else warnings
                    bucket.append({
                        "section": "drc.pcb",
                        "source": PCB_SOURCE,
                        "severity": severity,
                        "severitySource": leaf.get("severitySource"),
                        "ruleName": leaf.get("ruleName") or leaf.get("errorType") or "",
                        "net": leaf.get("net") or "",
                        "count": 1,
                        "ref": f"{suffix}.leafs[{leaf_index}]",
                    })
        if pcb.get("truncated"):
            counts_incomplete = True
            errors.append({
                "section": "drc.pcb",
                "source": PCB_SOURCE,
                "severity": "ERROR",
                "count": None,
                "countsKnown": False,
                "ref": "drc.pcb.totals",
                "detail": f"主机答复被整组截断（丢 {pcb.get('droppedGroups')} 组），总数不可知",
            })

    for index, finding in enumerate(findings):
        entry = _as_dict(finding)
        severity = _text(entry.get("severity")).upper() or "INFO"
        bucket = errors if severity == "ERROR" else warnings
        if severity == "INFO":
            continue
        bucket.append({
            "section": "findings",
            "source": "rules",
            "severity": severity,
            "ruleId": _text(entry.get("rule_id")),
            "message": _text(entry.get("message")),
            "count": 1,
            "ref": f"findings[{index}]",
            "refs": _as_list(entry.get("refs")),
        })

    error_count = sum(entry["count"] for entry in errors if isinstance(entry.get("count"), int))
    warn_count = sum(entry["count"] for entry in warnings if isinstance(entry.get("count"), int))
    info_count = sum(
        1 for finding in findings
        if _text(_as_dict(finding).get("severity")).upper() == "INFO"
    )
    summary: dict[str, Any] = {
        "errorCount": error_count,
        "warnCount": warn_count,
        "infoCount": info_count,
        "errors": errors,
        "warnings": warnings,
        "countsIncomplete": counts_incomplete,
        "exitCode": 1 if errors else 0,
    }
    if counts_incomplete:
        summary["countsIncompleteReason"] = (
            "某段主机答复没有可枚举的逐条/计数（boolean 或整组截断）："
            "errors 里那条 count=null 的条目就是它，计数只多不少"
        )
    return summary
