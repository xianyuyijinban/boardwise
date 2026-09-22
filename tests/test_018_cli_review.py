"""`boardwise review` 的 beta 体验（任务 018 §C）——四条，全离线、全 mock：

1. `--latest [<目录>]`：扫目录（含一层子目录）取最新 `.epro2`，自报选了哪个
   （路径 + mtime），与位置参数 `file` 互斥，空目录 / 非目录报错；
2. `--md` 报告顶部的中文摘要：规则中文名 + 位号 + 关键数值，**英文消息本体不动**；
3. `review --json` 的 schema 一个字节不变（评测 harness 只读它）；
4. `edit apply` 连不上 daemon → 退出码 **3**（页状态不可陈述），不是 2。

没有 socket、没有编辑器、没有真机动作：唯一被替换的是 `_open_cli` 返回的 client
类，它连 `open()` 都不成功。摘要的期望值写死在断言里，不用"跑一遍再抄"的方式
生成——否则改坏了实现，测试会跟着一起改。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from boardwise import cli
from boardwise.bridge.protocol import BridgeError
from boardwise.cli import (
    LATEST_DEFAULT_DIRS,
    _cmd_edit_apply,
    _cmd_edit_plan,
    _latest_scan_dirs,
    _newest_project_backup,
    build_parser,
)
from boardwise.engines.review import BUILTIN_RULES
from boardwise.rules.base import Finding, FindingTarget
from boardwise.rules.connectivity import DecouplingPerIC
from boardwise.rules.i18n import (
    KEY_VALUE_LIMIT,
    RULE_NAMES_ZH,
    finding_line,
    key_values,
    rule_name_zh,
    severity_zh,
    summary_section,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
#: 50 components, 27 INFO (`param-rc-cutoff` only) — the summary's crowded case.
ENET = FIXTURES / "board24v.enet"
#: 47 components, a clean board — the summary's empty case.
EPRO2 = FIXTURES / "llc_board.epro2"
#: 17 components, 2 WARN including one repairable finding (U3 carries a target).
MISMATCH = ROOT / "reviewsets" / "injected" / "value-mpn-mismatch.epro2"


def _backup(directory: Path, name: str, mtime: float, data: bytes = b"x") -> Path:
    """A candidate export with a chosen mtime — selection reads nothing else."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))
    return path


# --------------------------------------------------------------------------
# 1. `--latest`: which export is meant
# --------------------------------------------------------------------------


def test_latest_takes_the_newest_backup_one_level_down(tmp_path):
    root = tmp_path / "lc"
    oldest = _backup(root, "old.epro2", 1_000_000)
    middle = _backup(root / "sub", "middle.epro2", 2_000_000)
    newest = _backup(root / "sub", "new.epro2", 3_000_000)
    picked = _newest_project_backup([root])
    assert picked == newest
    assert picked not in (oldest, middle)


def test_latest_does_not_go_below_the_first_level(tmp_path):
    root = tmp_path / "lc"
    top = _backup(root, "top.epro2", 1_000_000)
    # Two levels down and the newest mtime in the tree: a recursive walk would
    # pick it, "one level of subdirectories" must not.
    _backup(root / "a" / "b", "deep.epro2", 9_000_000)
    assert _newest_project_backup([root]) == top


def test_latest_matches_the_suffix_case_insensitively(tmp_path):
    root = tmp_path / "lc"
    _backup(root, "old.epro2", 1_000_000)
    upper = _backup(root, "NEW.EPRO2", 2_000_000)
    assert _newest_project_backup([root]) == upper


def test_latest_ignores_everything_that_is_not_a_backup(tmp_path):
    root = tmp_path / "lc"
    for name in ("notes.txt", "board.enet", "board.epro2.tmp", "ProPrj.eprj2"):
        _backup(root, name, 9_000_000)
    assert _newest_project_backup([root]) is None


def test_latest_over_several_directories_takes_the_newest_anywhere(tmp_path):
    first = tmp_path / "one"
    second = tmp_path / "two"
    _backup(first, "a.epro2", 1_000_000)
    pick = _backup(second / "inner", "b.epro2", 5_000_000)
    _backup(second / "inner", "c.epro2", 4_000_000)
    assert _newest_project_backup([first, second]) == pick


def test_latest_skips_a_directory_that_does_not_exist(tmp_path):
    existing = tmp_path / "there"
    pick = _backup(existing, "a.epro2", 1_000_000)
    assert _newest_project_backup([tmp_path / "nope", existing]) == pick


def test_the_default_directories_are_the_three_named_places():
    # §C.1 names them; a test that only counted them would pass on a swap.
    assert LATEST_DEFAULT_DIRS == ("~/Downloads", "~/Desktop", "E:/LC Project")


def test_only_the_default_directories_that_exist_are_scanned(monkeypatch, tmp_path):
    there = tmp_path / "Downloads"
    there.mkdir(parents=True)
    monkeypatch.setattr(
        cli,
        "LATEST_DEFAULT_DIRS",
        (str(there), str(tmp_path / "Desktop"), str(tmp_path / "LC Project")),
    )
    assert _latest_scan_dirs("") == [there], "a missing default dir is skipped, not an error"


def test_an_explicit_directory_is_used_exactly_as_given(tmp_path):
    given = tmp_path / "given"
    assert _latest_scan_dirs(str(given)) == [given]


def test_latest_refuses_an_empty_directory(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code = cli.main(["review", "--latest", str(empty)])
    captured = capsys.readouterr()
    assert code == 2
    assert "没有 .epro2" in captured.err and str(empty) in captured.err


def test_latest_refuses_a_path_that_is_not_a_directory(tmp_path, capsys):
    code = cli.main(["review", "--latest", str(tmp_path / "nope")])
    captured = capsys.readouterr()
    assert code == 2
    assert "不是一个目录" in captured.err


def test_latest_and_a_file_are_mutually_exclusive(capsys):
    code = cli.main(["review", str(ENET), "--latest", str(ENET.parent)])
    captured = capsys.readouterr()
    assert code == 2
    assert "not both" in captured.err
    assert captured.out == "", "a refused invocation reviews nothing"


def test_review_with_neither_a_file_nor_latest_says_what_to_give(capsys):
    code = cli.main(["review"])
    captured = capsys.readouterr()
    assert code == 2
    assert "give a file" in captured.err


def test_latest_reviews_the_newest_export_end_to_end(tmp_path, capsys):
    root = tmp_path / "lc"
    # Both candidates parse, so a wrong pick cannot hide behind a parse error.
    older = _backup(root, "old.epro2", 1_000_000, EPRO2.read_bytes())
    picked = _backup(root / "backup", "newest.epro2", 3_000_000, EPRO2.read_bytes())
    md = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    code = cli.main(
        ["review", "--latest", str(root), "--md", str(md), "--json", str(json_path)]
    )
    captured = capsys.readouterr()

    assert code == 0, captured.err
    assert "选中" in captured.out and picked.name in captured.out
    assert re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", captured.out), captured.out
    assert str(older) not in captured.out
    assert "(47 components, 25 nets)" in captured.out
    assert f"Source: {picked}" in md.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 2. the Chinese summary in the --md report
# --------------------------------------------------------------------------


def test_the_md_report_keeps_its_opening_and_gains_a_chinese_summary(tmp_path, capsys):
    md = tmp_path / "r.md"
    assert cli.main(["review", str(ENET), "--md", str(md)]) == 0
    capsys.readouterr()
    text = md.read_text(encoding="utf-8")

    # The opening is what tests/test_cli.py pins, byte for byte.
    assert text.startswith("# boardwise review report")
    assert (
        "- [提示] RC 截止频率（param-rc-cutoff）：位号 R34/C116；"
        "关键数值 10Ω、330uF、48 Hz、-3 dB" in text
    )
    assert "共 27 条发现：0 错误 / 0 警告 / 27 提示" in text

    summary_at = text.index("## 中文摘要")
    assert summary_at < text.index("## INFO (27)")
    assert summary_at < text.index("`param-rc-cutoff`")
    # The English finding line is still there, untranslated, in its own place.
    assert "- `param-rc-cutoff` [L2-facts] RC R34(10Ω) + C116(330uF) on 'VM'" in text


def test_the_summary_names_the_rule_the_part_and_the_numbers(tmp_path, capsys):
    md = tmp_path / "r.md"
    assert cli.main(["review", str(MISMATCH), "--view", "schematic", "--md", str(md)]) == 0
    capsys.readouterr()
    text = md.read_text(encoding="utf-8")

    assert "共 2 条发现：0 错误 / 2 警告 / 0 提示" in text
    assert (
        "- [警告] LED 限流电阻（param-led-current）："
        "位号 LED1/U3/U5；关键数值 4700Ω、3.3 V" in text
    )
    assert (
        "- [警告] 位号值与 MPN 是否一致（param-value-mpn-match）："
        "位号 U3；关键数值 4700 Ω、1000 Ω、4.70x、3x" in text
    )
    # `RT9013` is part of U5's part number ("per U5 RT9013-33GB"), which the
    # designator reader reads as an `RT` designator; the board has no RT9013,
    # so the summary must not name it.
    assert "RT9013" not in text.split("## WARN")[0]
    assert "contradicts its MPN" in text, "the English message body is not translated"


def test_a_clean_board_says_so_in_chinese_too(tmp_path, capsys):
    md = tmp_path / "r.md"
    assert cli.main(["review", str(EPRO2), "--md", str(md)]) == 0
    capsys.readouterr()
    text = md.read_text(encoding="utf-8")
    assert "共 0 条发现：0 错误 / 0 警告 / 0 提示" in text
    assert "- 没有发现问题。" in text
    assert "No findings." in text, "the English report body is not replaced"


def test_the_summary_line_is_built_from_name_id_part_and_numbers():
    line = finding_line(
        severity="WARN",
        rule_id="param-value-mpn-match",
        message="U3: board value 4700 Ω contradicts its MPN (1000 Ω) -- 4.70x apart",
        refs=["U3"],
    )
    assert line == (
        "- [警告] 位号值与 MPN 是否一致（param-value-mpn-match）："
        "位号 U3；关键数值 4700 Ω、1000 Ω、4.70x"
    )


def test_an_unregistered_rule_id_falls_back_to_the_id():
    # A new rule must show up as the id it is, not vanish from the summary.
    assert rule_name_zh("brand-new-rule") == "brand-new-rule"
    assert finding_line(severity="ERROR", rule_id="brand-new-rule", message="") == (
        "- [错误] brand-new-rule"
    )
    # …and the id is not printed twice when it *is* the name.
    assert finding_line(severity="INFO", rule_id="xtal-load-caps", message="") == (
        "- [提示] 晶振负载电容（xtal-load-caps）"
    )


def test_an_unregistered_severity_falls_back_too():
    assert severity_zh("WARN") == "警告"
    assert severity_zh("FATAL") == "FATAL"


def test_every_rule_id_in_this_build_has_a_chinese_name():
    ids = {rule.id for rule in BUILTIN_RULES} | {DecouplingPerIC.id}
    assert ids - set(RULE_NAMES_ZH) == set(), "a rule with no Chinese name"
    assert set(RULE_NAMES_ZH) - ids == set(), "a name for a rule that does not exist"


def test_key_values_keeps_only_numbers_carrying_a_unit():
    message = (
        "U1 pin16 on net '3V3': 4.7kΩ against MPN 1000 Ω, 2.13x apart at 3.3 V; "
        "revision 2.0.0 stands"
    )
    assert key_values(message) == ["4.7kΩ", "1000 Ω", "2.13x", "3.3 V"]


def test_key_values_are_capped_and_deduplicated():
    message = " ".join(f"{n} V" for n in range(1, 8)) + " 2 V"
    values = key_values(message)
    assert values == [f"{n} V" for n in range(1, KEY_VALUE_LIMIT + 1)]


def test_the_summary_section_carries_the_counts_and_the_lines():
    text = summary_section(["- 行一", "- 行二"], {"ERROR": 1, "WARN": 2, "INFO": 3})
    assert text.split("\n")[:6] == [
        "## 中文摘要",
        "",
        "共 6 条发现：1 错误 / 2 警告 / 3 提示",
        "",
        "- 行一",
        "- 行二",
    ]
    assert text.endswith("\n"), "the section ends with a blank separator line"


def test_the_summary_reads_the_designator_from_the_plan_target_when_prose_has_none():
    finding = Finding(
        rule_id="param-value-mpn-match",
        severity="WARN",
        message="no designator in this prose at all",
        level="L2-facts",
        evidence=[],
        target=FindingTarget(
            component_ref="U9", expected_before="4.7kΩ", suggested_after="1k"
        ),
    )
    assert cli._finding_refs_for_summary(finding, {"U9", "U3"}) == ["U9"]
    # A designator the board does not have is dropped, not reported as a fact.
    assert cli._finding_refs_for_summary(finding, {"U3"}) == []
    assert finding_line(
        severity=finding.severity,
        rule_id=finding.rule_id,
        message=finding.message,
        refs=[],
    ).endswith("param-value-mpn-match）")


def test_a_report_with_an_unexpected_header_is_left_alone():
    report = "# something else\n\nbody\n"
    assert cli._with_chinese_summary(report, "## 中文摘要\n\n- x\n") == report


# --------------------------------------------------------------------------
# 3. `--json` is the harness's contract: untouched
# --------------------------------------------------------------------------


def test_the_json_report_is_byte_identical_with_and_without_the_markdown(
    tmp_path, capsys
):
    plain = tmp_path / "plain.json"
    both = tmp_path / "both.json"
    assert cli.main(["review", str(ENET), "--json", str(plain)]) == 0
    assert (
        cli.main(
            ["review", str(ENET), "--json", str(both), "--md", str(tmp_path / "r.md")]
        )
        == 0
    )
    capsys.readouterr()
    assert plain.read_bytes() == both.read_bytes()


def test_the_json_schema_is_the_one_the_harness_reads(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert (
        cli.main(["review", str(ENET), "--json", str(out), "--md", str(tmp_path / "r.md")])
        == 0
    )
    capsys.readouterr()
    raw = out.read_text(encoding="utf-8")
    payload = json.loads(raw)

    assert set(payload) == {"summary", "findings"}
    assert payload["summary"] == {"ERROR": 0, "WARN": 0, "INFO": 27}
    keys = {"rule_id", "severity", "message", "level", "evidence", "target", "refs"}
    assert payload["findings"], "the fixture must produce findings or this pins nothing"
    for finding in payload["findings"]:
        assert set(finding) == keys
        assert isinstance(finding["refs"], list)
    assert "中文摘要" not in raw, "the Chinese summary belongs to --md only"


# --------------------------------------------------------------------------
# 4. `edit apply` with no daemon: exit 3, not 2
# --------------------------------------------------------------------------


def _plan_file(tmp_path: Path) -> Path:
    """`edit plan` output for the injected board's U3 — offline, no daemon."""
    out = tmp_path / "plan.json"
    args = build_parser().parse_args(
        [
            "edit", "plan",
            "--file", str(MISMATCH),
            "--rule", "param-value-mpn-match",
            "--designator", "U3",
            "-o", str(out),
        ]
    )
    assert _cmd_edit_plan(args) == 0
    return out


def test_edit_apply_exits_3_when_the_daemon_is_unreachable(monkeypatch, tmp_path, capsys):
    plan = _plan_file(tmp_path)

    class Unreachable:
        @classmethod
        async def open(cls, uri, token, role, client=""):
            raise OSError("Connection refused")

    monkeypatch.setattr(
        "boardwise.cli._open_cli",
        lambda args: (Unreachable, BridgeError, 61190, "token"),
    )
    code = _cmd_edit_apply(build_parser().parse_args(["edit", "apply", str(plan)]))
    captured = capsys.readouterr()
    # 3 = "the page's state cannot be stated". With no connection there is no
    # read-back, so nothing about the page is known — that is not the 2 the
    # contract reserves for "the promised effect is not there" (016 scenario 5).
    assert code == 3, captured
    assert "daemon not reachable" in captured.err


def test_edit_apply_still_exits_5_on_an_unusable_plan(tmp_path, capsys):
    broken = tmp_path / "broken.json"
    broken.write_text("{ not a plan", encoding="utf-8")
    code = _cmd_edit_apply(build_parser().parse_args(["edit", "apply", str(broken)]))
    captured = capsys.readouterr()
    assert code == 5, captured
    assert "boardwise edit apply" in captured.err
