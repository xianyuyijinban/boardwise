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
