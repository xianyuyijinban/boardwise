"""文档声明钉（doc-claims audit）：让重要声明没法再悄悄过期（issue #57  finding #7，
岳 2026-10-03 裁「病在文案」）。

仓库没有 CI，"实时更新文案"的实现方式就是这组测试：**load-bearing 的声明配机器可验的
钉子，谁让声明失效，谁的测试当场红**。v1 家族 = README 的评审纪律段 vs 规则常量引用
的取证板与评审集分堆。往这个文件里加新声明钉的规矩：

1. 声明必须是**机器可验**的（能量化的、能对拍的、能 grep 判真伪的）；验不了的散文
   不许写成断言式口号——要么改写，要么补一个能验的机制。
2. 钉子读**源头**（代码常量/评审集记录/argparse 定义），不读二手转述。
3. 每条钉子注释里写明它护的是哪句话、失效时的样子。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_readme_raw = (REPO / "README.md").read_text(encoding="utf-8")
#: 声明钉按整句找——README 的换行是排版不是语义，先把空白归一再对拍。
README = re.sub(r"\s+", " ", _readme_raw)
#: 审查 SOP 的正文（139 收口的两条声明钉读这里：§3.1 的「按网找协同器件的 N 条规则」
#: 与 §3.1b 的 set-rail 双写）。同样先归空白再对拍。
SOP = (REPO / "docs" / "review-sop.md").read_text(encoding="utf-8")

#: 旧的绝对化口号（#7 的病灶原文，中英两版）：README 曾经断言验收集「从不参与调参」，
#: 而 params 的两条常量恰恰是在 holdout 板的证据上定出来的。
ABSOLUTE_CLAIMS = ("never used for tuning", "不许参与规则调试")
#: 替代它的诚实形态（README 现在的措辞钉）：机制无法泄漏 + 早期常量如实披露。
DISCLOSURE_TOKENS = (
    "predate the split discipline",
    "cannot leak",
    "先于分堆制度诞生",
)
DENOMINATOR_TOKEN = "holdout records enter no denominator"

_CONSTANT_RE = re.compile(r"^([A-Z][A-Z0-9_]{3,}) = ", re.MULTILINE)
_DESIGNATOR_RE = re.compile(r"\b[URCLDJQ]\d+\b")
_EVIDENCE_VERBS = re.compile(r"实测|measured|witness|oracle|见证|ruling|signed", re.IGNORECASE)
_EVIDENCE_BOARDS_RE = re.compile(r"^#: evidence-boards:\s*(.+)$", re.MULTILINE)


def _rules_comment_blocks() -> list[tuple[str, str, Path]]:
    """Every (constant name, the `#:` comment block directly above it, file)."""
    out: list[tuple[str, str, Path]] = []
    for path in sorted((REPO / "src" / "boardwise" / "rules").glob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            match = re.match(r"^([A-Z][A-Z0-9_]{3,}) = ", line)
            if not match:
                continue
            block: list[str] = []
            cursor = index - 1
            while cursor >= 0 and lines[cursor].startswith("#:"):
                block.append(lines[cursor])
                cursor -= 1
            out.append((match.group(1), "\n".join(reversed(block)), path))
    return out


def _constants_citing_board_evidence() -> list[tuple[str, str, Path, list[str]]]:
    """Tuning constants whose comment cites designator evidence, with boards declared."""
    found = []
    for name, block, path in _rules_comment_blocks():
        if not (_DESIGNATOR_RE.search(block) and _EVIDENCE_VERBS.search(block)):
            continue
        declaration = _EVIDENCE_BOARDS_RE.search(block)
        boards = []
        if declaration:
            boards = [item.strip() for item in declaration.group(1).split(",") if item.strip()]
        found.append((name, block, path, boards))
    return found


def _reviewset_splits() -> dict[str, str]:
    """``board name -> split_default`` for every annotation record that says one."""
    splits: dict[str, str] = {}
    for record in sorted((REPO / "reviewsets").glob("*.json")):
        try:
            payload = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        board = str(payload.get("board") or record.stem)
        split = str(payload.get("split_default") or "")
        if split:
            splits[board] = split
    return splits


def _resolve_board(fragment: str, splits: dict[str, str]) -> str | None:
    """The split of the one reviewset board this fragment names, or ``None``."""
    matches = [split for board, split in splits.items() if fragment in board]
    return matches[0] if len(matches) == 1 else None


def test_every_evidence_citing_constant_declares_its_boards():
    """引用取证板的常量必须声明是哪些板——否则下一条常量又会悄悄在 holdout 上定出来。"""
    missing = [
        f"{name} ({path.name})"
        for name, _block, path, boards in _constants_citing_board_evidence()
        if not boards
    ]
    assert missing == [], (
        "these constants cite board evidence but declare no `evidence-boards:` line: "
        + ", ".join(missing)
    )


def test_every_declared_board_resolves_to_one_reviewset_record():
    """声明的板必须能唯一解析到评审集记录——写个模糊名字等于没声明。"""
    splits = _reviewset_splits()
    bad: list[str] = []
    for name, _block, path, boards in _constants_citing_board_evidence():
        for fragment in boards:
            if _resolve_board(fragment, splits) is None:
                bad.append(f"{name} ({path.name}): {fragment!r}")
    assert bad == [], "evidence-boards fragments that resolve to no single record: " + ", ".join(bad)


def test_readme_never_resurrects_the_absolute_claim():
    """旧口号一个字都不许回来——它曾经是真话的对立面（#7），中英两版同查。"""
    for claim in ABSOLUTE_CLAIMS:
        assert claim not in README


def test_readme_states_the_mechanism_and_the_disclosure():
    """替代形态的两半都在：harness 结构上无法泄漏 + 早期常量如实披露。"""
    for token in (*DISCLOSURE_TOKENS, DENOMINATOR_TOKEN):
        assert token in README, f"README's eval paragraph lost {token!r}"


def test_holdout_evidence_and_the_readme_stay_consistent():
    """核心不变量：只要还有常量的取证板是 holdout，README 就必须带着那句披露。

    反过来：哪天常量全部改在 dev 堆上标定（evidence-boards 里不再有 holdout），
    这条测试允许 README 换成无前缀的强声明——但那是另一次有意的文案决定，
    不是悄悄发生的。
    """
    splits = _reviewset_splits()
    holdout_citing: list[str] = []
    for name, _block, _path, boards in _constants_citing_board_evidence():
        for fragment in boards:
            if _resolve_board(fragment, splits) == "holdout":
                holdout_citing.append(f"{name} ← {fragment}")
    if holdout_citing:
        assert "predate the split discipline" in README, (
            "constants tuned on holdout evidence exist ("
            + ", ".join(holdout_citing)
            + ") but README dropped the disclosure — the claim outran the data again"
        )


def test_the_harness_default_stays_leak_proof():
    """审计确认过的机制钉死：`--split` 默认 `dev`（holdout 不显式给就进不了分母）。"""
    source = (REPO / "src" / "boardwise" / "cli.py").read_text(encoding="utf-8")
    split_block = re.search(
        r'add_argument\(\s*"--split",.*?default="(?P<default>[a-z]+)"', source, re.DOTALL
    )
    assert split_block is not None, "the --split argument definition was not found"
    assert split_block.group("default") == "dev", (
        "--split's default moved off dev — the harness's leak-proof claim in README "
        "is only true while holdout is opt-in, never the default"
    )


# ============================================================ issue #58-#60
#: 命令面抽取：README/SKILL 提到的命令必须与 cli.py 的注册表**双向**对拍（issue #60
#: 的「contract-drift 同一把尺子对准自己」+ issue #62 的反向那一半）。只数**首词是真
#: 命令**的序列——散文里的「boardwise daemon」不是命令提及（:data:`PROSE_AFTER_BOARDWISE`
#: 逐个声明）；真命令的第二个词必须是它注册过的子命令。
def _cli_commands() -> tuple[set[str], dict[str, set[str]]]:
    """（顶层命令集, 顶层 -> 子命令集），全部从 cli.py 的 argparse 注册处直读。"""
    source = (REPO / "src" / "boardwise" / "cli.py").read_text(encoding="utf-8")
    tops = dict(re.findall(r'(\w+)\s*=\s*sub\.add_parser\(\s*"([^"]+)"', source))
    subparsers = dict(re.findall(r'(\w+)_sub\s*=\s*(\w+)\.add_subparsers', source))
    tree: dict[str, set[str]] = {name: set() for name in tops.values()}
    for match in re.finditer(r'(\w+)_sub\.add_parser\(\s*"([^"]+)"', source):
        sub_var, name = match.groups()
        parent = tops.get(subparsers.get(sub_var, ""), "")
        if parent:
            tree.setdefault(parent, set()).add(name)
    return set(tree), tree


#: `boardwise <词>` 后面跟的词里，**不是命令**的那些——散文（issue #62）。
#:
#: 写成表而不是隐式跳过：「哪些词是散文」是一个要有人负责的声明，写出来才能审。
#: 反向断言（未知顶层词）比正向断言更依赖这张表，所以它必须小而显式：这里每个词都是
#: 一次人工判读的结果，不是「跑出来啥是啥」。实测 SKILL.md 正文全集只有 ``connector``
#: 一个（`boardwise connector —— …` 指的是那个 npm 包，不是子命令）。
PROSE_AFTER_BOARDWISE: frozenset[str] = frozenset({"connector", "daemon"})


def _mentioned_commands(document: str) -> tuple[set[str], set[str]]:
    """文档提到的 boardwise 命令集，以及提到的**未知顶层词**集。

    返回 ``(commands, unknown_tops)``——issue #62 把这个 helper 从单向改成双向：
    原实现对未知首词 `continue`，于是「顶层命令被删/改名」这件事连同整条提及一起被丢掉，
    `checkup` 改名后 SKILL.md 十几处引用**不会让任何测试红**（实测 `review-mark` /
    `persistence` / `triage` / `checkup` 四个删掉都是 `stale=[]` 静默通过）。

    按**行**提取（行内反引号段 + 代码块里的裸命令行），不靠全局反引号配对
    （全文 2100+ 个反引号，一处失配全文档翻转——实测过）。三段判定：
    首词必须是注册的顶层命令（散文「boardwise daemon 常驻」不是命令提及）；
    第二词是注册的子命令才算双词命令；第二词紧跟 `.` 的是文件名参数
    （`review-mark report.json`），不是子命令。
    未知首词则进第二个返回值——由 :data:`PROSE_AFTER_BOARDWISE` 豁免散文，
    其余每一个都是「文档指向一个不存在的命令」。
    """
    tops, tree = _cli_commands()
    commands: set[str] = set()
    unknown_tops: set[str] = set()
    pattern = re.compile(
        r"boardwise\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*)(\.?))?"
    )
    for line in document.splitlines():
        pieces = re.findall(r"`([^`]+)`", line) or [line]
        for piece in pieces:
            for match in pattern.finditer(piece):
                first, second, dot = match.groups()
                if first not in tops:
                    if first not in PROSE_AFTER_BOARDWISE:
                        unknown_tops.add(first)
                    continue
                if second is None or dot:
                    commands.add(first)
                else:
                    commands.add(f"{first} {second}")
    return commands, unknown_tops


def test_readme_rule_count_matches_builtin_rules():
    """护 #58：README 的规则数必须 == len(BUILTIN_RULES)，谁加规则谁更新 README。"""
    from boardwise.engines.review import BUILTIN_RULES

    count = len(BUILTIN_RULES)
    assert f"{count} design rules" in README, (
        f"README's English rule count drifted from BUILTIN_RULES ({count})"
    )
    assert f"{count} 条设计规则" in README, (
        f"README 中文段的规则数与 BUILTIN_RULES（{count}）漂移"
    )


def test_readme_export_sentence_tells_the_truth():
    """护 #59：「各一条命令」从未成立——export-fab 一条同时出三样，网表没有导出命令。"""
    assert "one command each" not in README
    assert "各一条命令" not in README
    assert "export-fab" in README, "README 的导出句丢了 export-fab 这个真身"


def test_skill_md_mentions_only_real_commands():
    """护 #60 主治法 + #62 的反向那一半：SKILL.md 提到的命令必须双向对拍。

    正向（#60）：SKILL ⊆ CLI——SKILL 是 SOP 不是命令参考，不反向要求 74 条全覆盖。
    反向（#62）：未知顶层词——SKILL 里 `boardwise <词>` 的首词若是 CLI 从未注册过的，
    就是 SOP 指向一个不存在的命令。旧实现对未知首词 `continue`，把整条提及丢掉，
    于是顶层命令被删/改名时这条钉子静默通过（实测把 `cli.py` 里 `review-mark` 注册名
    改成 `mark`：单向 11 passed 静默通过，双向 CAUGHT）。散文由
    :data:`PROSE_AFTER_BOARDWISE` 豁免——「哪些词不是命令」是有人负责的声明。
    """
    skill = (REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    tops, tree = _cli_commands()
    known = set(tops)
    for parent, subs in tree.items():
        known.update(f"{parent} {sub}" for sub in subs)
    mentioned, unknown_tops = _mentioned_commands(skill)
    stale = sorted(m for m in mentioned if m not in known)
    assert stale == [], (
        "SKILL.md names commands the CLI no longer has: " + ", ".join(stale)
    )
    # 反向：SKILL.md 提到的、CLI 没有的顶层命令（不是子命令）。
    phantom = sorted(unknown_tops)
    assert phantom == [], (
        "SKILL.md mentions `boardwise <word>` for top-level commands the CLI "
        "never registered (or dropped): " + ", ".join(phantom)
        + " — either the command was removed/renamed, or PROSE_AFTER_BOARDWISE "
        "needs the word declared as prose"
    )


def test_skill_md_covers_the_load_bearing_commands():
    """护 #60 的另一半：承重命令（画图链的机器闸与提案器）不许再 0 次提及。"""
    skill = (REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    mentioned, _unknown = _mentioned_commands(skill)
    for command in ("draw lint", "draw propose"):
        assert command in mentioned, (
            f"SKILL.md no longer mentions `{command}` — the draw pipeline's "
            "acceptance gate/proposer must stay discoverable in the SOP"
        )


def test_skill_md_protocol_line_refs_resolve():
    """护 #60 的次级实测：坑表里 `protocol.py:NNN` 的出处行号必须对得上——
    同一行里提到的大写常量，至少有一个真的定义在那一行（坑 2 曾引 :120，
    DELETE_TIMEOUT 真身在 :152）。124 减重后全表在 docs/pits.md，两处同查。"""
    protocol_lines = (
        REPO / "src" / "boardwise" / "bridge" / "protocol.py"
    ).read_text(encoding="utf-8").splitlines()
    bad: list[str] = []
    for doc in (
        REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md",
        REPO / "docs" / "pits.md",
    ):
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            for ref in re.finditer(r"protocol\.py:(\d+)", line):
                target = int(ref.group(1))
                constants = re.findall(r"\b[A-Z][A-Z0-9_]{3,}\b", line)
                resolved = (
                    1 <= target <= len(protocol_lines)
                    and any(
                        re.match(rf"{re.escape(name)}\s*=", protocol_lines[target - 1])
                        for name in constants
                    )
                )
                if not resolved:
                    bad.append(f"{doc.name}:{lineno} -> protocol.py:{target}")
    assert bad == [], "stale protocol.py line refs: " + ", ".join(bad)


# ============================================================ 124 减重预算闸
SKILL_BUDGET_LINES = 320


def test_skill_md_stays_within_its_line_budget():
    """护 124 的战果：SKILL.md 是运行时必读路由层，不是知识库（岳 2026-10-06：
    「skill 是对方的 5、6 倍」——峰值 686 行，拆层后 279）。预算 320 行：
    撞线的人先去压实或外置，不许再把 SKILL 当仓库写。"""
    skill_lines = (
        REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md"
    ).read_text(encoding="utf-8").splitlines()
    assert len(skill_lines) <= SKILL_BUDGET_LINES, (
        f"SKILL.md is {len(skill_lines)} lines (budget {SKILL_BUDGET_LINES}) — "
        "深水区内容外置到 docs/，别在路由层续写"
    )


def test_skill_md_doc_pointers_resolve():
    """路由层的存在理由是指针，指针烂掉路由层就死了：SKILL.md 提到的每个
    `docs/*.md` / `tasks/*.md` 都必须真的在仓库里。"""
    skill = (REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    missing: list[str] = []
    for ref in sorted(set(re.findall(r"(?:docs|tasks)/[A-Za-z0-9._-]+\.md", skill))):
        if not (REPO / ref).is_file():
            missing.append(ref)
    assert missing == [], "SKILL.md points at files that do not exist: " + ", ".join(missing)


def test_skill_md_referenced_docs_are_shipped_not_pointed_at_air():
    """护 124b（外部审计「路由层指向空气」）：SKILL.md 引用的 docs/*.md 必须同时
    在 **spec 的 DATAS**（exe 打包清单）与 **resources 的引用清单**（install-skill
    拷到 references/ 的清单）里——读者有两类（仓库内 AI / 装了 exe 的朋友），
    指针只对一类解析就是只对一类成立。"""
    from boardwise import resources

    skill = (REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    mentioned = set(re.findall(r"docs/[A-Za-z0-9._-]+\.md", skill))

    spec_body = (REPO / "packaging" / "boardwise.spec").read_text(encoding="utf-8")
    in_spec = {m for m in mentioned if all(p in spec_body for p in m.split("/"))}
    shipped = {f"docs/{path.name}" for path in resources.skill_reference_paths()}
    missing_spec = sorted(mentioned - in_spec)
    missing_ship = sorted(mentioned - shipped)
    assert not missing_spec and not missing_ship, (
        f"SKILL.md references docs the install cannot resolve — "
        f"not in spec DATAS: {missing_spec}; not in resources.skill_reference_paths(): "
        f"{missing_ship}"
    )


# ================================================ 139 收口：轨电压的两个键与那份清单
#: §3.1 的那句清单：``协同器件的 N 条规则（`id` / `id` …）``。
_SOP_TIER_CLAIM_RE = re.compile(r"协同器件的\s*(\d+)\s*条规则（([^）]*)）")
#: 清单里的规则 id——反引号段里全小写带连字符的那些。
_SOP_RULE_ID_RE = re.compile(r"`([a-z][a-z0-9-]+)`")


def test_the_sop_rule_list_in_the_per_page_tier_matches_the_registry():
    """护 064/139：SOP 说的「按网找协同器件的 N 条规则」必须与真实清单对拍。

    失效时的样子（本钉就是为此写的）：064 把 `sel-tvs-standoff-rail` /
    `sel-ldo-fixed-output` 加进 `NET_MEMBERSHIP_RULES`，而 SOP 仍写着「9 条」并列着
    老的九个——读 SOP 的人以为少两条规则不下结论，per-page 档的诚实度就少两块。

    钉子读**源头**：条数 == 清单里真有几个 id，成员 ⊆ `BUILTIN_RULES` 的 id
    （注册表）**且** ⊆ `NET_MEMBERSHIP_RULES`（这段话真正的断言是「它们对出现在多于
    一个页的网名不下结论」，只有后者能担保）。数字与清单本身必须是同一个数。
    """
    from boardwise.engines.review import BUILTIN_RULES
    from boardwise.rules.unproven import NET_MEMBERSHIP_RULES

    match = _SOP_TIER_CLAIM_RE.search(re.sub(r"\s+", " ", SOP))
    assert match is not None, (
        "docs/review-sop.md §3.1 lost its per-page rule list — the sentence that says "
        "which rules refuse on a welded net"
    )
    stated, listing = int(match.group(1)), _SOP_RULE_ID_RE.findall(match.group(2))
    assert len(listing) == stated, (
        f"the SOP says {stated} rules and lists {len(listing)}: {listing}"
    )
    builtin = {rule.id for rule in BUILTIN_RULES}
    assert set(listing) <= builtin, (
        "the SOP names rules that are not in BUILTIN_RULES: "
        + str(sorted(set(listing) - builtin))
    )
    assert set(listing) <= set(NET_MEMBERSHIP_RULES), (
        "the SOP lists rules that do not refuse on a welded net: "
        + str(sorted(set(listing) - set(NET_MEMBERSHIP_RULES)))
    )


def test_the_sop_and_the_writer_agree_that_one_answer_fills_both_voltage_keys():
    """护 139 收口：SOP 的 set-rail 段必须写明**双写**并点名两个键，且代码真的一次
    写两份——「答一次就不问」这句话两半都要成立。

    失效时的样子（139 之前）：文档写着「`intent set-rail` 写 `voltage`；要那两条规则
    也算答过，就在同一份合同里补 `targetVoltage`」——把缝留给工程师手工补，于是
    `pwr-cap-voltage-rating` / `path-ldo-dissipation` 对一条已经答过的轨继续报
    `intent-missing`（`evidence/064/intent_slot_gap.txt`）。

    文档那一半（「双写」二字与两个键名）与代码那一半（`set_rail_voltage` 真落两键，
    键名与 `RAIL_VOLTAGE_SLOTS` 逐字一致）分开断言：只写文档不改代码，或反过来，
    这条测试都会红。
    """
    from boardwise.core.designintent import SECTION_RAILS, DesignIntent
    from boardwise.core.railquery import RAIL_VOLTAGE_SLOTS, set_rail_voltage

    assert "双写" in SOP, "the SOP stopped explaining why one answer goes into two keys"
    updated, _ = set_rail_voltage(DesignIntent(), "VCCA", "3.3V")
    entry = updated.entry(SECTION_RAILS, "VCCA")
    for slot in RAIL_VOLTAGE_SLOTS:
        assert entry.value(slot) == "3.3V", f"set_rail_voltage stopped writing {slot}"
        assert f"`{slot}`" in SOP, f"the SOP no longer names the {slot} key"
    assert RAIL_VOLTAGE_SLOTS == ("voltage", "targetVoltage"), (
        "the pair moved — update docs/review-sop.md §3.1b in the same breath, and this "
        "pin with it"
    )
