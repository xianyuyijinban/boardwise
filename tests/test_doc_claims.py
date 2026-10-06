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
#: 命令面抽取：README/SKILL 提到的命令必须与 cli.py 的注册表对拍（issue #60 的
#: 「contract-drift 同一把尺子对准自己」）。只数**首词是真命令**的序列——散文里的
#: 「boardwise daemon」不是命令提及；真命令的第二个词必须是它注册过的子命令。
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


def _mentioned_commands(document: str) -> set[str]:
    """文档提到的 boardwise 命令集。

    按**行**提取（行内反引号段 + 代码块里的裸命令行），不靠全局反引号配对
    （全文 2106 个反引号，一处失配全文档翻转——实测过）。三段判定：
    首词必须是注册的顶层命令（散文「boardwise daemon 常驻」不是命令提及）；
    第二词是注册的子命令才算双词命令；第二词紧跟 `.` 的是文件名参数
    （`review-mark report.json`），不是子命令。
    """
    tops, tree = _cli_commands()
    commands: set[str] = set()
    pattern = re.compile(
        r"boardwise\s+([a-z][a-z0-9-]*)(?:\s+([a-z][a-z0-9-]*)(\.?))?"
    )
    for line in document.splitlines():
        pieces = re.findall(r"`([^`]+)`", line) or [line]
        for piece in pieces:
            for match in pattern.finditer(piece):
                first, second, dot = match.groups()
                if first not in tops:
                    continue
                if second is None or dot:
                    commands.add(first)
                else:
                    commands.add(f"{first} {second}")
    return commands


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
    """护 #60 主治法：SKILL.md 提到的命令必须是 cli.py 注册表里的真命令（单向 set-diff：
    SKILL ⊆ CLI——SKILL 是 SOP 不是命令参考，不反向要求 74 条全覆盖）。"""
    skill = (REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    tops, tree = _cli_commands()
    known = set(tops)
    for parent, subs in tree.items():
        known.update(f"{parent} {sub}" for sub in subs)
    mentioned = _mentioned_commands(skill)
    stale = sorted(m for m in mentioned if m not in known)
    assert stale == [], (
        "SKILL.md names commands the CLI no longer has: " + ", ".join(stale)
    )


def test_skill_md_covers_the_load_bearing_commands():
    """护 #60 的另一半：承重命令（画图链的机器闸与提案器）不许再 0 次提及。"""
    skill = (REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    mentioned = _mentioned_commands(skill)
    for command in ("draw lint", "draw propose"):
        assert command in mentioned, (
            f"SKILL.md no longer mentions `{command}` — the draw pipeline's "
            "acceptance gate/proposer must stay discoverable in the SOP"
        )


def test_skill_md_protocol_line_refs_resolve():
    """护 #60 的次级实测：坑表里 `protocol.py:NNN` 的出处行号必须对得上——
    同一行里提到的大写常量，至少有一个真的定义在那一行（坑 2 曾引 :120，
    DELETE_TIMEOUT 真身在 :152）。"""
    skill_path = REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md"
    protocol_lines = (
        REPO / "src" / "boardwise" / "bridge" / "protocol.py"
    ).read_text(encoding="utf-8").splitlines()
    bad: list[str] = []
    for lineno, line in enumerate(skill_path.read_text(encoding="utf-8").splitlines(), 1):
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
                bad.append(f"SKILL.md:{lineno} -> protocol.py:{target}")
    assert bad == [], "stale protocol.py line refs: " + ", ".join(bad)
