"""分阶段交付与可中断审查 —— SOP 3.0a 与它依赖的三条只读路径。

这批测试是 **TDD 钉**，不是对已写文档的转述。它钉两件事：

1. **文档**：`docs/review-sop.md` 里的 `### 3.0a 分阶段交付与可中断审查`（截至
   `### 3.1 审板子`）必须把岳 2026-10-26 那条裁决写成可执行的文字——一次 checkup
   之后先交付 initial/partial 首轮检查点、再深挖；每批有 finding/假设/需要的证据/
   停止条件、最多 3 条 finding、约 15 分钟、约 30 分钟必交付、续查另批或用户同意、
   禁止「再查最后一个」；run 冻结输入归档与 SHA256/引擎版本/intent/活动页/证据通道/
   模型计数，输入或通道一变就开新 run 做语义比较而不混 findings；同输入哈希+引擎+
   intent 的普通统计走复读报告/结构化产物/缓存，重算要新具体证据，DRC 复核最多 2 次，
   只用公开接口；文件大小/哈希变化只能用 Markdown 表格里的 `archive-bytes-changed`
   表达、`user-modified-design` 禁止；中止/402/超时/预算耗尽只读已有产物出 partial
   并分四档，缺手册/intent/证据落 `needs-manual`/`open-item`，缺 finalize 不是耗时
   根因、无收据不冒称正式 finalize；末尾明确「未形成硬约束」的四条，并链接
   `tasks/review-stage-runtime-gates.md`。

   3.0a 的正文只住在 SOP 里（SKILL 有 320 行预算）。两份 SKILL.md（`.agents/` 与
   `.kimi-code/`）只须**路由**到它：「审板子」那一段要提到 3.0a、首轮检查点、
   initial/partial、先交付或 SOP 路径，且两份路由段与整文件都逐字节相同。

   其中「同基准无新证据的重复 checkup/run_pcb_review」「第三次 DRC 稳定性复核」和
   「输入或证据通道变化」三行，必须落在一张匿名策略表（场景 / 同基准？ / 新证据 /
   动作）里，动作为 `reject-use-existing` / `reject-needs-new-evidence` /
   `new-run-semantic-diff`。**这张表是策略钉，不是运行时闸**：仓库里没有任何代码会
   拦截第二次 checkup，表只规定 AI 该怎么做。测试同时断言这一点，免得后来的人把
   「SOP 写了」读成「机器拦住了」。

2. **生产只读路径**：审查在首轮检查点之后被中止（402/超时/预算耗尽）时，剩下的
   裁决只允许从**已经在盘上的产物**读出。`review-read` 的四节和 `review finalize`
   都必须在这种状态上工作，且都不得回头调用 `cli._cmd_checkup`、`run_pcb_review`
   或 `cli._open_cli`——一次新的 checkup 或一次新的编辑器会话会花掉用户正在被耗尽
   的那份预算，而 partial 交付的全部价值就是「不再花」。

全部夹具匿名合成：没有编辑器、daemon、工程文件、网表或图片，也没有真报告。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

import test_537d_finalize_cli as finalize_fx
import test_537d_finalize_validation as fx

from boardwise import cli
from boardwise.engines import pcbreview

# ---------------------------------------------------------------------------
# 1) the SOP section, extracted by its own headings
# ---------------------------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
SOP_PATH = REPO / "docs" / "review-sop.md"
AGENTS_SKILL = REPO / ".agents" / "skills" / "boardwise" / "SKILL.md"
KIMI_SKILL = REPO / ".kimi-code" / "skills" / "boardwise" / "SKILL.md"

START = "### 3.0a 分阶段交付与可中断审查"
END = "### 3.1 审板子"

#: SKILL 只承载**路由**，不复制 3.0a 正文：审板子那一行到「缺手册」之前的一段。
ROUTE_START = "- **审板子**"
ROUTE_END = "- **缺手册"

#: 「约 15 分钟」与「约 30 分钟必交付」是**停止线**，不是目标值：写了就要能照做，
#: 所以测试只认数字与「必交付」，不认形容词。
FIFTEEN = re.compile(r"15\s*分钟")
THIRTY = re.compile(r"30\s*分钟")
NEGATIONS = ("禁止", "不得", "不许", "不准", "不要", "别", "不", "禁", "无")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _section(path: Path) -> str:
    """The bytes of 3.0a in ``docs/review-sop.md``, heading up to (not incl.) 3.1.

    The section is read from the SOP, which is its only home: the SKILL files
    carry a route, not a copy, so this helper is never aimed at them.
    """
    text = _read(path)
    start = text.find(START)
    assert start >= 0, f"{path} 里没有 `{START}` 小节——3.0a 还没写"
    end = text.find(END, start + len(START))
    assert end >= 0, f"{path} 的 `{START}` 没有以 `{END}` 收尾（边界不清就不算小节）"
    return text[start:end]


def _route(path: Path) -> str:
    """The「审板子」route of one SKILL copy, up to the next bullet.

    SKILL has a 320-line budget, so 3.0a's body lives in the SOP; what the copy
    must carry is a pointer to it. Extracted by the two bullets around it, so a
    copy that only mentions ``3.0a`` elsewhere does not satisfy this.
    """
    text = _read(path)
    start = text.find(ROUTE_START)
    assert start >= 0, f"{path} 里没有 `{ROUTE_START}` 这条路由"
    end = text.find(ROUTE_END, start + len(ROUTE_START))
    assert end >= 0, f"{path} 的「审板子」路由没有以 `{ROUTE_END}` 收尾"
    return text[start:end]


@pytest.fixture(scope="module")
def sop() -> str:
    """3.0a as the SOP carries it: one string, one copy, one home."""
    return _section(SOP_PATH)


def _squash(text: str) -> str:
    """Whitespace-free text, so a phrase wrapped across lines still matches."""
    return re.sub(r"\s+", "", text)


def _near(text: str, needle: str, *others: str, window: int = 80) -> bool:
    """Whether every one of ``others`` sits within ``window`` chars of ``needle``."""
    for match in re.finditer(re.escape(needle), text):
        chunk = text[max(0, match.start() - window): match.end() + window]
        if all(other in chunk for other in others):
            return True
    return False


def _forbidden_near(text: str, needle: str, *, window: int = 80) -> bool:
    """Whether **any** negation sits near ``needle``.

    A ban sentence uses one negation word, not all of them: requiring every
    member of :data:`NEGATIONS` in the same window would fail a correct SOP.
    """
    for match in re.finditer(re.escape(needle), text):
        chunk = text[max(0, match.start() - window): match.end() + window]
        if any(word in chunk for word in NEGATIONS):
            return True
    return False


def _table_rows(text: str) -> list[list[str]]:
    """Every GFM data row of every table in the section, cells stripped."""
    rows: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue  # the separator row
        rows.append(cells)
    return rows


# ---------------------------------------------------------------------------
# 2) what the section must say (one pin per numbered claim in the ruling)
# ---------------------------------------------------------------------------


def test_both_skill_copies_route_to_3_0a_byte_for_byte():
    """3.0a 的正文只住在 SOP；两份 SKILL 只须**路由**到它，且两份是同一份字节。

    SKILL 有 320 行预算，正文复制进去迟早被压缩掉——所以这里不要求标题、也不要求
    整节，只要求「审板子」那一段指向 3.0a。sop 不参与这段断言：它是 SOP 的文本。
    """
    agents = _route(AGENTS_SKILL)
    kimi = _route(KIMI_SKILL)
    assert agents == kimi, "两份 SKILL.md 的「审板子」路由不一致（逐字节）"
    # 两份文件整体也是同一份文件放在两个地方——路由相同但整体漂移同样是失败。
    assert AGENTS_SKILL.read_bytes() == KIMI_SKILL.read_bytes()

    route = _squash(agents)
    assert "3.0a" in route
    assert "首轮检查点" in route
    assert "initial" in route and "partial" in route
    assert "先交付" in route or "docs/review-sop.md" in route, (
        "路由段既没说「先交付」，也没指向 docs/review-sop.md"
    )


def test_first_checkpoint_comes_after_one_checkup_and_before_digging(sop):
    """一次 checkup 之后**先交付** initial/partial 首轮检查点，再深挖。

    Ordering is the pin: 「先」和「再」反了，这条裁决就变成「查完再汇报」——正是
    用户被烧掉预算时最不想要的那种。
    """
    squashed = _squash(sop)
    for token in ("一次checkup", "首轮检查点", "initial", "partial", "环境", "身份"):
        assert token in squashed, f"3.0a 没写 `{token}`"
    # 环境/身份确认是 checkup 的前置，不是首轮检查点里可选的一项。
    assert _near(squashed, "一次checkup", "环境", "身份"), (
        "3.0a 没有把「完成环境/身份确认 + 一次 checkup」写成首轮检查点的前提"
    )
    assert _forbidden_near(squashed, "自由探索"), "3.0a 没有禁止一上来就自由探索"
    deliver = squashed.find("先交付")
    dig = squashed.find("深挖")
    assert deliver >= 0 and dig >= 0, "3.0a 没写「先交付…再深挖」"
    assert deliver < dig, "3.0a 的「先交付」必须排在「深挖」之前"

    # 首轮检查点的五个字段：缺一个，用户拿到的就是无法验收的一句话。
    for field in ("连接与版本", "report.conclusion", "宿主DRC", "待确认项", "产物位置"):
        assert field in squashed, f"首轮检查点缺少字段 `{field}`"
    assert "ERROR" in squashed


def test_batch_template_has_a_stop_condition_and_a_finding_cap(sop):
    """每批四件套 + 最多 3 条 finding + 15/30 分钟 + 续查另批 + 禁「再查最后一个」。"""
    squashed = _squash(sop)
    for token in ("finding", "假设", "需要的证据", "停止条件", "更新阶段报告"):
        assert token in squashed, f"批次模板缺少 `{token}`"
    assert re.search(r"最多\s*3\s*(条|个|项)?\s*finding", squashed) or re.search(
        r"最多3(条|个|项)?finding", squashed
    ), "3.0a 没有「最多 3 条 finding」的上限"
    assert FIFTEEN.search(squashed), "3.0a 没有约 15 分钟的批次预算"
    assert THIRTY.search(squashed), "3.0a 没有约 30 分钟必交付的停止线"
    # 30 分钟从首轮检查点之后累计，不是从开跑算。
    assert _near(squashed, "30分钟", "首轮检查点"), (
        "30 分钟没有写明从首轮检查点之后累计"
    )
    assert "必交付" in squashed
    assert "用户同意" in squashed
    assert re.search(r"另(开)?(一)?批|续查另批", squashed), "续查没有「另起一批」的出口"

    # 「再查最后一个」必须是禁句，而不是一句可选的建议。
    banned = "再查最后一个"
    assert banned in squashed, "3.0a 没有点名禁止「再查最后一个」"
    assert _forbidden_near(squashed, banned), "「再查最后一个」没有被写成禁止"


def test_a_run_freezes_its_inputs_and_a_change_opens_a_new_run(sop):
    """冻结什么、什么时候开新 run、什么时候允许复读、DRC 复核几次、允许调什么。"""
    squashed = _squash(sop)
    for token in (
        "归档", "SHA256", "引擎版本", "intent", "活动页", "证据通道", "模型计数",
    ):
        assert token in squashed, f"run 冻结清单缺少 `{token}`"
    # 输入/通道一变：新 run + 语义比较 + 不混 findings，三件事必须同时在场。
    assert re.search(r"新\s*run|开新run|另开run", squashed), "变化后没有「开新 run」"
    assert "语义比较" in squashed
    assert _near(squashed, "findings", "不混") or _near(
        squashed, "新run", "不混"
    ), "新 run 没有写「不混 findings」"
    # 同基准：复读即可，且复读的对象是这三样。
    assert "复读" in squashed
    for target in ("报告", "结构化产物", "缓存"):
        assert target in squashed, f"复读对象缺少 `{target}`"
    assert "重算" in squashed and _near(squashed, "重算", "证据")
    assert "具体证据" in squashed, "重算没有要求「新具体证据」"
    # intent 是 DesignIntent 合同的路径 + 内容哈希，不是一句人写的问题描述。
    assert "DesignIntent" in squashed, "intent 没有绑到 DesignIntent 合同"
    assert "合同" in squashed
    assert _near(squashed, "DesignIntent", "SHA256"), "DesignIntent 没有要求内容 SHA256"
    assert "这次审查要回答" not in squashed, "intent 仍写成「这次审查要回答…」的旧语义"
    assert "板级结论随之降级" not in squashed, "缺合同不得由流程 SOP 新造 verdict 降级"
    assert re.search(r"(最多|至多|不超过)\s*2\s*次", squashed), "DRC 复核没有「最多 2 次」"
    assert "公开接口" in squashed
    assert "私有API" in squashed, "run 冻结清单没有写「只用公开接口、不猜私有 API」"


def test_file_size_or_hash_movement_is_only_archive_bytes_changed(sop):
    """严格 Markdown 表格：允许什么、禁止什么、以及它**不能**证明什么。"""
    cells = [cell for row in _table_rows(sop) for cell in row]
    assert cells, "3.0a 没有 Markdown 表格——证据变化只能用表格表达"

    changed = [row for row in _table_rows(sop) if any(
        "archive-bytes-changed" in cell for cell in row
    )]
    assert changed, "表格里没有 `archive-bytes-changed` 这一行"
    assert any(
        any(marker in cell for cell in row for marker in ("允许", "只允许"))
        for row in changed
    ), "`archive-bytes-changed` 没有被写成允许的那一个"

    forbidden = [row for row in _table_rows(sop) if any(
        "user-modified-design" in cell for cell in row
    )]
    assert forbidden, "表格里没有 `user-modified-design` 这一行（禁止项必须点名）"
    assert any(
        any(marker in cell for cell in row for marker in ("禁止", "不得", "不许"))
        for row in forbidden
    ), "`user-modified-design` 没有被写成禁止"

    squashed = _squash(sop)
    assert "用户改设计" in squashed or "用户改的设计" in squashed
    assert _near(squashed, "用户改设计", "单独") or _near(
        squashed, "用户改设计", "不得"
    ), "3.0a 没有写「文件变化不得单独证明用户改设计」"


def test_an_aborted_run_reads_what_is_already_on_disk_and_says_partial(sop):
    """中止/402/超时/预算耗尽：只读、partial、四档、needs-manual/open-item。"""
    squashed = _squash(sop)
    for token in ("中止", "402", "超时", "预算"):
        assert token in squashed, f"3.0a 没有覆盖 `{token}`"
    assert "partial" in squashed
    # 只读已有产物，不再发起任何一次新的采集。
    assert "已有产物" in squashed
    for engine in ("checkup", "run_pcb_review", "DRC", "采集"):
        assert engine in squashed, f"3.0a 没有点名 `{engine}`"
        assert _near(squashed, engine, "不", window=40) or _near(
            squashed, engine, "无", window=40
        ), f"中止后仍然可能跑 `{engine}`——没有写「不新跑」"
    # 四档：证据的强弱必须分得开。
    for verdict in ("已确认", "疑似", "未验证", "未覆盖"):
        assert verdict in squashed, f"partial 交付缺少 `{verdict}` 档"
    assert "needs-manual" in squashed
    assert "open-item" in squashed
    # 其他板/记忆/网名只是线索，不是证据。
    for token in ("其他板", "历史记忆", "网名", "线索"):
        assert token in squashed, f"partial 交付没有写 `{token}` 只作线索"
    # 缺 finalize 不是耗时根因；没有收据就不许冒称正式 finalize。
    assert _near(squashed, "finalize", "根因", "不是"), "没有写「缺 finalize 不是耗时根因」"
    assert "收据" in squashed
    assert _near(squashed, "收据", "正式") or _near(squashed, "收据", "冒称")


def test_the_dedupe_policy_table_is_a_policy_pin_not_a_runtime_gate(sop):
    """三行策略表 + 「这是策略钉、不是运行时闸」+ 「未形成硬约束」四条 + 出处链接。

    这张表容易被后人误读成「机器会拦住重复 checkup」。仓库里没有任何这样的闸，
    所以测试把这句话一并钉住：SOP 规定的是 AI 的动作，不是运行时行为。
    """
    rows = _table_rows(sop)
    header = next(
        (row for row in rows if any("场景" in cell for cell in row)), None
    )
    assert header is not None, "策略表没有 `场景` 列"
    for column in ("同基准", "新证据", "动作"):
        assert any(column in cell for cell in header), f"策略表缺少 `{column}` 列"

    def find(*needles: str) -> list[str]:
        return [
            " | ".join(row)
            for row in rows
            if all(any(needle in cell for cell in row) for needle in needles)
        ]

    repeated = find("checkup")
    assert repeated, "策略表没有「重复 checkup」这一行"
    assert any("run_pcb_review" in row for row in repeated), "重复 run_pcb_review 没有同行"
    assert any("reject-use-existing" in row for row in repeated), (
        "同基准无新证据的重复 checkup/run_pcb_review 动作不是 `reject-use-existing`"
    )

    drc = find("DRC")
    assert drc, "策略表没有「DRC 复核」这一行"
    assert any("reject-needs-new-evidence" in row for row in drc), (
        "第三次 DRC 稳定性复核无新证据的动作不是 `reject-needs-new-evidence`"
    )
    assert any(
        marker in row
        for row in drc
        for marker in ("第三次", "第3次", "3 次", "3次", "三次")
    ), "DRC 那行没有点名「第三次」"

    changed = find("变化")
    assert changed, "策略表没有「输入或证据通道变化」这一行"
    assert any("new-run-semantic-diff" in row for row in changed), (
        "输入/通道变化的动作不是 `new-run-semantic-diff`"
    )

    squashed = _squash(sop)
    assert "策略" in squashed
    assert _near(squashed, "策略", "运行时闸") or _near(squashed, "表", "运行时闸"), (
        "3.0a 没有声明这张表是策略钉、不是运行时闸"
    )
    assert "不是运行时闸" in squashed or "非运行时闸" in squashed or "不构成运行时闸" in squashed

    # 同一件事的另一半：3.0a 必须自己点名它**没有**形成哪些硬约束。表里写了
    # 「reject-use-existing」，不等于仓库里有一道闸；这句话是给下一个人看的边界。
    assert "未形成硬约束" in squashed, "3.0a 末尾没有「未形成硬约束」"
    assert "harness" in squashed and "顺序" in squashed, "没有写 harness 顺序不受约束"
    assert "墙钟" in squashed, "没有写墙钟/预算停止只是策略"
    assert "全局" in squashed and "checkup" in squashed, "没有写全局重复 checkup 不被阻止"
    assert "DRC" in squashed, "没有写全局 DRC 阻止不存在"
    assert "私有API" in squashed
    assert _near(squashed, "私有", "阻止") or _near(squashed, "私有", "拦")

    assert "review-read" in squashed
    assert "全局去重" in squashed, "没有点名「全局去重」"
    assert _near(squashed, "全局去重", "不等于") or _near(squashed, "全局去重", "不="), (
        "没有写「review-read 可复读 ≠ 全局去重」"
    )
    assert "tasks/review-stage-runtime-gates.md" in sop, "没有链接 runtime-gates 说明"


# ---------------------------------------------------------------------------
# 3) the production read-only paths an interrupted run may still use
# ---------------------------------------------------------------------------

#: 中止之后一个审查再花不起的东西：一次 checkup、一次 PCB 复核、一次编辑器会话。
#: `cli.run_pcb_review` 是模块级 tripwire；引擎里的同名函数才是真的被 import 的那个
#: （`cli` 在调用点做局部 import），两处都钉住，否则「禁调用」只是看起来禁了。
FORBIDDEN_ENTRY_POINTS = ("_cmd_checkup", "run_pcb_review", "_open_cli")


def _forbid_live_work(monkeypatch) -> None:
    def refuse(*args, **kwargs):  # pragma: no cover - only on the wrong path
        raise AssertionError(
            "中止后的只读路径调用了新工作入口 "
            f"({', '.join(FORBIDDEN_ENTRY_POINTS)})——partial 交付不得再花预算"
        )

    monkeypatch.setattr(cli, "_cmd_checkup", refuse, raising=True)
    monkeypatch.setattr(cli, "_open_cli", refuse, raising=True)
    monkeypatch.setattr(cli, "run_pcb_review", refuse, raising=False)
    monkeypatch.setattr(pcbreview, "run_pcb_review", refuse, raising=True)


def _dir_hashes(out: Path) -> dict[str, str]:
    """Every file under the review directory, by name, as sha256."""
    return {
        str(path.relative_to(out)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(out.rglob("*"))
        if path.is_file()
    }


def _review_read(out: Path, section: str) -> int:
    return cli.main(["review-read", "--out", str(out), "--section", section])


def test_after_first_checkup_interruption_review_read_serves_four_sections(
    tmp_path, capsys, monkeypatch
):
    """首轮检查点之后被中止：四节全部从盘上的 report.json 读出，不再发起一次调用。

    ``delivery`` 必须是 ``partial``——这不是失败，而是这份证据覆盖的诚实读数；
    「partial 读不出来」才是失败。
    """
    out, written = finalize_fx._make_review(tmp_path)
    before = _dir_hashes(out)
    _forbid_live_work(monkeypatch)

    assert _review_read(out, "verdict") == 0
    verdict = json.loads(capsys.readouterr().out)["payload"]
    assert verdict["status"] == "ok"
    assert verdict["conclusion"]["mayQuotePassed"] is False
    assert verdict["delivery"]["status"] == "partial"
    assert verdict["summaryExitCode"] == written["summary"]["exitCode"]

    assert _review_read(out, "findings") == 0
    findings = json.loads(capsys.readouterr().out)["payload"]
    assert len(findings["findings"]) == len(written["findings"])
    assert findings["warningsPendingTriage"] == written["completion"]["warningsPendingTriage"]
    assert findings["warningsNeedsManual"] == written["completion"]["warningsNeedsManual"]

    assert _review_read(out, "coverage") == 0
    coverage = json.loads(capsys.readouterr().out)["payload"]
    assert coverage["missingSections"] == []
    assert coverage["verdict"] == written["completion"]["verdict"]
    assert coverage["environment"] == written["environment"]

    assert _review_read(out, "artifacts") == 0
    artifacts = json.loads(capsys.readouterr().out)["payload"]
    assert artifacts["status"] == "ok"
    assert set(artifacts["missingOutputs"]) == {
        "report.md", "board-report.md", "live-evidence.json"
    }
    assert any(row["exists"] is True for row in artifacts["artifacts"])

    # 只读：一个字节都不动，也不产生交付收据。
    assert _dir_hashes(out) == before
    assert not (out / "finalize.json").exists()


def test_after_first_checkup_interruption_a_second_verdict_read_is_byte_identical(
    tmp_path, capsys, monkeypatch
):
    """同一份 report.json 读两次，stdout 逐字节相同。

    这**不证明全局去重**：两次都 exit 0，运行时并没有拦住第二次读。它只证明投影是
    稳定的（同一个 hash 有意义，插件可以比对）。「不要在同一个基准上重复 checkup」
    是 3.0a 的策略钉（`reject-use-existing`），不是这条命令的闸——把两件事混在一起，
    就会有人写出一个真的去拦重复审查的运行时闸。
    """
    out, _written = finalize_fx._make_review(tmp_path)
    _forbid_live_work(monkeypatch)

    assert _review_read(out, "verdict") == 0
    first = capsys.readouterr().out
    assert _review_read(out, "verdict") == 0
    second = capsys.readouterr().out

    assert first != ""
    assert first == second
    # 复读被允许，正是「运行时没有全局去重」的证据；去重只存在于 SOP 的策略表里。
    assert json.loads(first) == json.loads(second)


def test_after_first_checkup_interruption_finalize_validates_partial_delivery(
    tmp_path, capsys, monkeypatch
):
    """收尾也走真实 ``review finalize``：partial 交付可以验证，且不回头重新采集。

    允许既有的内存 re-gate（``_completion_from_report`` 等）——那是校验，不是采集；
    禁的是另外三个会花预算的入口。
    """
    out, written = finalize_fx._make_review(tmp_path)
    assert written["evidence"]["delivery"]["status"] == "partial"
    assert written["conclusion"]["mayQuotePassed"] is False
    _forbid_live_work(monkeypatch)

    assert finalize_fx._run(out) == 0
    text = capsys.readouterr().out
    assert "Traceback" not in text
    assert "delivery partial" in text
    assert "不是板级通过" in text

    after = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert after["evidence"]["delivery"]["status"] == "partial"
    assert after["conclusion"]["mayQuotePassed"] is False
