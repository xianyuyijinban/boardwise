"""issue #69 条 3: `doctor` is a guided install, not a checklist of FAILs.

The complaint: 「exe + connector 导入 + skill 安装三步手工，坑在 connector 导入与版本匹配」
and the issue's own diagnosis of the fix — 「检查器不过时，文档会过时」. So the thing
worth pinning is not that a check goes red (that has been pinned since 012), it is
that a **first-time user can act on the output without reading a manual** — and that
the guidance and `docs/getting-started.md` cannot drift apart, because the checker is
the thing that stays true.

Three properties, each a way the guided output could be useless:

1. **grouping by cause** — with nothing running, six lines go red and five of them
   carry the same 「先让扩展连上」. Six steps saying one sentence is not a walkthrough;
   the red lines that could not judge themselves fold into the one step that will
   unblock them, and the fold is *announced* so a reader counting red lines and
   steps does not think a check was dropped;
2. **install order, not severity** — a `.eext` cannot be imported into an editor too
   old to have the menu, so the steps come out in the manual's numbering. Sorting by
   how bad the failure looks would send the reader to the wrong step first;
3. **each step points at the written step** — and the step number is a *table*, not a
   second copy of the manual's text. That is the whole anti-drift mechanism: the
   checker says what is wrong, the document says how, and a table is the one thing
   that can be wrong in only one place.

The all-green path is asserted too, and it is a real requirement rather than a
formality: a section that only appears on failure must not appear on success, or
every healthy run ends with a walkthrough nobody reads.
"""

from __future__ import annotations

import json

import pytest

from boardwise import __version__, skill_install
from boardwise.cli import (
    DOCTOR_STEP_HINTS,
    DOCTOR_ROOT_ACTION,
    DoctorProbe,
    _guided_groups,
    _guided_step,
    run_doctor,
)
# The healthy-machine probe and the real `doctor` argument builder are test_doctor's,
# and duplicating them here would mean this file's fixtures could drift from the
# ones the rest of the suite judges doctor by — the same argument every other
# cross-import in this directory makes.
import test_doctor as base


def _doctor_args(json_path=None, extra=()):
    return base._doctor_args(json_path=json_path, extra=extra)


ALL_PRESENT = base.ALL_PRESENT
check = base.check
healthy_probe = base.healthy_probe
skill_states = base.skill_states


# --------------------------------------------------------------------------
# 1. grouping: one step per cause, not one per red line
# --------------------------------------------------------------------------


def test_six_red_lines_with_one_cause_become_two_steps():
    """The measured no-daemon case, and the reason grouping exists.

    Everything that could not be judged says `未验证` and carries the same fix. The
    guided block must collapse those into the one action that unblocks them —
    otherwise the block is the old output with numbers in front of it.
    """
    checks = run_doctor(healthy_probe(
        ping=None, ping_error="connection refused",
        skill_statuses=(), probe=None, probe_error="[NO_CONNECTOR] none",
        documents=None, documents_error="[NO_CONNECTOR] none",
        connector_version="", editor_version="",
    ))
    failed = [entry for entry in checks if not entry.ok]
    groups = _guided_groups(failed)

    assert len(failed) >= 6, "the fixture must reproduce the many-red-lines shape"
    assert len(groups) == 2, [group[0].name for group in groups]
    roots = {group[0].name for group in groups}
    assert roots == {"connector", "daemon"}
    # Nothing was dropped: every red line is in exactly one group.
    assert sorted(entry.name for group in groups for entry in group) == sorted(
        entry.name for entry in failed
    )


def test_a_line_that_failed_on_its_own_evidence_keeps_its_own_step():
    """The grouping is by **cause**, not by name.

    `connector-version` is in the connector's fold group, but only when it says
    「未验证」. A connector that is attached and simply running an **old build** has
    its own instruction (`update-connector`), and folding it into 「connect the
    extension」 would send the reader to a step that is already done — the exact
    mistake issue #6 was about.
    """
    checks = run_doctor(healthy_probe(connector_version="0.4.4"))
    entry = check(checks, "connector-version")
    assert entry.ok is False
    assert "未验证" not in entry.detail, "it failed on its own comparison"
    groups = _guided_groups([entry])
    assert len(groups) == 1 and groups[0][0].name == "connector-version"
    assert "update-connector" in groups[0][0].fix


def test_the_offline_editor_line_is_never_folded():
    """`editor-install` is judgeable with nothing connected, so nothing upstream of
    it can be its cause — it is the first step of the install and must stay one."""
    checks = run_doctor(DoctorProbe(
        port=61190,
        offline_editor_path=r"D:\lceda-pro", offline_editor_version="3.2.148.88089769",
    ))
    install = check(checks, "editor-install")
    assert install.ok is False
    assert "editor-install" not in DOCTOR_ROOT_ACTION
    groups = _guided_groups([install])
    assert len(groups) == 1 and groups[0][0].name == "editor-install"


def test_the_steps_come_out_in_install_order_not_in_check_order():
    """Editor → connector → daemon → project, which is the manual's numbering.

    `run_doctor` builds its lines editor-first then daemon before connector, so the
    sort has to be deliberate: without it a reader with no daemon is told to start
    the daemon and then — one step later — to import the connector, i.e. the
    reverse of 第 2 步 / 第 3 步.
    """
    checks = run_doctor(healthy_probe(
        ping=None, ping_error="connection refused",
        skill_statuses=(), probe=None, probe_error="[NO_CONNECTOR] none",
        documents=None, documents_error="[NO_CONNECTOR] none",
        connector_version="", editor_version="",
    ))
    failed = [entry for entry in checks if not entry.ok]
    roots = [group[0].name for group in _guided_groups(failed)]
    assert roots.index("connector") < roots.index("daemon")
    # And the numbers the sort uses are the manual's own.
    hints = [DOCTOR_STEP_HINTS[name] for name in roots]
    assert hints == sorted(hints), (roots, hints)


def test_a_check_with_no_manual_step_prints_its_fix_without_a_pointer():
    """Unknown is not a wrong pointer.

    A check the table has no entry for (a future one) still gets a step; it just
    does not claim a section of the manual that may not be about it.
    """
    checks = run_doctor(healthy_probe(connector_version="0.4.4"))
    entry = check(checks, "connector-version")
    assert DOCTOR_STEP_HINTS["connector-version"] == 2
    assert "docs/getting-started.md 第 2 步" in _guided_step(entry, 1)


# --------------------------------------------------------------------------
# 2. the printed block
# --------------------------------------------------------------------------


@pytest.fixture
def guided(monkeypatch, tmp_path):
    """Run the real `_cmd_doctor` against a stub daemon, and return its output."""
    from boardwise import resources
    from boardwise.bridge import protocol
    from boardwise.cli import _cmd_doctor

    class _Client:
        @classmethod
        async def open(cls, uri, token, role, client=""):
            raise OSError("connection refused")

    monkeypatch.setattr(
        "boardwise.cli._open_cli",
        lambda args: (_Client, protocol.BridgeError, 61190, "token"),
    )
    # Isolate the two offline inputs, or the line counts below become a property of
    # whichever machine runs them (the same reason test_doctor pins both).
    monkeypatch.setenv("EDITOR_INSTALL_ENV", str(tmp_path / "no-editor"))
    for harness in skill_install.HARNESSES:
        monkeypatch.delenv(skill_install.SKILL_HOME_ENVS[harness], raising=False)

    import io
    import contextlib

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = _cmd_doctor(_doctor_args(json_path=tmp_path / "doctor.json"))
    return code, buffer.getvalue(), json.loads((tmp_path / "doctor.json").read_text(
        encoding="utf-8"
    ))


def test_the_block_appears_only_when_something_is_red(guided):
    """The all-green path is asserted through the pure function, because a stub
    daemon that answers everything is a second fixture; what matters here is that
    the block's *gate* is the failed list, not the check count."""
    code, out, _payload = guided
    assert code == 1, out
    assert "按这个顺序做" in out


def test_the_fold_is_announced_so_no_check_looks_dropped(guided):
    """The count mismatch has to be explained on the spot.

    Seven red lines, two steps, and no sentence saying why: the reader counts,
    finds five checks unaccounted for, and stops trusting the output. So the header
    names both numbers and says where the folded ones went.
    """
    _code, out, payload = guided
    failed = [entry for entry in payload["checks"] if not entry["ok"]]
    header = next(line for line in out.splitlines() if "按这个顺序做" in line)
    assert f"{len(failed)} 个红项归成" in header, header
    assert "归并的红项列在它那一步下面" in header, header
    # …and they really are, named, under their step.
    for folded in ("sys.probe 关键方法在位", "编辑器版本 ≥ 3.2.149", "当前工程焦点可读"):
        assert f"（这一步会同时解决：{folded}）" in out, folded


def test_every_step_carries_the_action_not_just_the_label(guided):
    """A step that only names the check is the old output again.

    Each step prints the check's own `fix` — the sentence the engine built and
    already tested — followed by the doc pointer, so the two cannot disagree.
    """
    _code, out, _payload = guided
    steps = [line for line in out.splitlines() if line.strip().startswith("第 ")]
    assert len(steps) >= 2, steps
    for step in steps:
        assert "·" in step and "boardwise" not in step, step
    actions = [line for line in out.splitlines() if "docs/getting-started.md 第" in line]
    assert len(actions) == len(steps)
    assert any("boardwise bridge start" in line for line in actions)
    assert any("立创 EDA Pro" in line for line in actions)


def test_the_step_numbers_point_at_sections_getting_started_actually_has(guided):
    """The anti-drift check, and the reason the pointers are a table.

    Every `docs/getting-started.md` step number doctor may emit must be a section
    that document really has. This is the pin that makes 「检查器不过时，文档会过时」
    mechanically caught: renumber the manual and doctor goes red, rather than
    sending a reader to a step that no longer says what they need.
    """
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "docs" / "getting-started.md").read_text(
        encoding="utf-8"
    )
    steps = {int(part) for part in DOCTOR_STEP_HINTS.values() if part}
    assert steps, "at least one check must point at a written step"
    for number in steps:
        assert f"## 第 {number} 步" in doc, (
            f"doctor points at docs/getting-started.md 第 {number} 步, "
            "which that document does not have"
        )
    # 0 is the sentinel for "no numbered section" (the skill lines: `install-skill`
    # is printed from the exe with no Python, which the manual writes as 第 0 步).
    # It must never be rendered as 「第 0 步」 by `_guided_step` — the pin is on the
    # renderer's behaviour, since that is where the wrong pointer would appear.
    assert 0 in set(DOCTOR_STEP_HINTS.values())
    entry = run_doctor(healthy_probe(skill_statuses=skill_states(claude="missing")))[1]
    assert DOCTOR_STEP_HINTS[entry.name] == 0
    assert "第 0 步" not in _guided_step(entry, 1)


def test_the_json_carries_the_walkthrough_already_grouped_and_ordered(guided):
    """`guidedSteps` is the machine half of the walkthrough.

    The printout is for a person reading a terminal; a colleague who wraps doctor
    in a script needs the same ordering and grouping without parsing Chinese prose,
    and — the reason this is a key of its own rather than a derivation — it cannot
    come out with a different grouping than the human-readable one. Each step names
    its cause first and the red lines it unblocks after, exactly as the block does.
    """
    _code, out, payload = guided
    steps = payload["guidedSteps"]
    assert len(steps) == 2, steps
    assert [entry["step"] for entry in steps] == [1, 2]
    assert [entry["cause"] for entry in steps] == ["connector", "daemon"]
    # Every red check is accounted for exactly once, across all steps.
    red = {entry["name"] for entry in payload["checks"] if not entry["ok"]}
    assert sorted(
        name for step in steps for name in step["checks"]
    ) == sorted(red)
    # The step numbers go with the manual's own order, not the check order.
    assert [entry["stepHint"] for entry in steps] == sorted(
        entry["stepHint"] for entry in steps
    ), steps
    # The printed block and the JSON say the same thing, in the same order.
    printed = [
        line.strip() for line in out.splitlines()
        if line.strip().startswith("第 ") and "步 ·" in line
    ]
    assert len(printed) == len(steps)
    for line, step in zip(printed, steps):
        assert step["label"] in line, (line, step)
        assert step["fix"].split("（详见")[0] in out


def test_an_all_green_run_grows_no_walkthrough(monkeypatch, tmp_path, capsys):
    """The requirement that makes the block tolerable: it is absent when green.

    A working install's `doctor` output is read far more often than a broken one's
    (it is the last line of the install and the first line of every "is it still
    fine?" check), so a permanent section would be noise on every run. Asserted on
    both halves — the printout and the JSON — because the JSON is what a script
    reads, and an empty `guidedSteps: []` there would be a different contract from
    an absent one (039's own 「缺席而非空」 rule).
    """
    from boardwise.bridge import protocol
    from boardwise.cli import _cmd_doctor, _repo_connector_version

    class _Client:
        @classmethod
        async def open(cls, uri, token, role, client=""):
            return _Daemon()

    class _Daemon:
        async def call(self, action, params=None, *, target_project=None, target_instance=None):
            if action == "ping":
                return {"pong": True, "version": __version__, "connector": True,
                        "pairedFingerprint": "ab12cd34"}
            if action == "sys.probe":
                return {"version": "3.2.186", "connector": _repo_connector_version(),
                        "checks": ALL_PRESENT}
            if action == "doc.list":
                return {"projects": [{"projectUuid": "p", "friendlyName": "板", "focused": True,
                                      "schematics": [], "pcbs": []}],
                        "active": {"uuid": "page-1", "type": "page"}}
            raise AssertionError(action)

        async def close(self):
            return None

    monkeypatch.setattr(
        "boardwise.cli._open_cli",
        lambda args: (_Client, protocol.BridgeError, 61190, "token"),
    )
    monkeypatch.setenv("EDITOR_INSTALL_ENV", str(tmp_path / "no-editor"))
    for harness in skill_install.HARNESSES:
        monkeypatch.delenv(skill_install.SKILL_HOME_ENVS[harness], raising=False)

    assert _cmd_doctor(_doctor_args(json_path=tmp_path / "d.json")) == 0
    out = capsys.readouterr().out
    assert "按这个顺序做" not in out
    assert "先修第一项" not in out
    assert "PASS" in out
    payload = json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))
    assert "guidedSteps" not in payload


# --------------------------------------------------------------------------
# 3. the four things doctor is asked to check, named as the issue names them
# --------------------------------------------------------------------------


def test_the_four_install_questions_the_issue_names_all_have_a_step():
    """daemon 在不在听 / connector 连没连 / connector 版本与 exe 内嵌 bundle 对不对 /
    skill 装了没 — the issue's own list, mapped to the lines that answer them.

    Pinned as a *set* rather than as behaviour because the issue is about coverage:
    a step hint added for two of the four would leave the other two undocumented,
    and nothing else in the file would notice.
    """
    for name in ("daemon", "connector", "connector-version"):
        assert DOCTOR_STEP_HINTS.get(name), name
    # `install-skill` is printed from the exe with no Python: that is 第 0 步 in the
    # manual, which is why its two hints are 0 (the sentinel for "no numbered
    # section" is 0 too, so they are pinned by name instead).
    for name in ("skill-kimi", "skill-claude"):
        assert name in DOCTOR_STEP_HINTS, name


def test_a_missing_skill_gets_a_step_of_its_own():
    """The install's third manual step, and the one people forget.

    `install-skill` is offline, so it can be red while everything else is green —
    which means it cannot fold into a connector step (there is no connector problem
    to fold into) and must reach the reader on its own.
    """
    checks = run_doctor(healthy_probe(skill_statuses=skill_states(claude="missing")))
    entry = check(checks, "skill-claude")
    assert entry.ok is False
    assert entry.fix == "boardwise install-skill"
    groups = _guided_groups([entry])
    assert len(groups) == 1 and groups[0][0].name == "skill-claude"
    assert "install-skill" in _guided_step(entry, 1)
