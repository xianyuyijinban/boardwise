"""537D1a2a: ``review-read --section netlist`` — the live capture's netlist, sorted.

Why this section exists. 537D1a made the report's four prose/ledger questions
readable as one structured envelope; the live netlist was still answered by
hand-written one-off parsers over ``live-evidence.json`` and the captured
``netlist_raw.json``. Those scripts had the same failure direction 537D exists to
stop: an absent capture read as 「没有网表」, a directory listing read as 「这就
是本次实时网表」, and ``report.model`` (the archive summary) promoted to a live
netlist.

The contract this file pins:

* ``status: "ok"`` requires **both** the parsed live model and the artifact that
  proved the file. Everything else — no ``evidence.liveCapture``, identity not
  verified, ``liveSchematic`` not ``ok``, no netlist artifact, a file that fails
  bytes/sha256/UTF-8/parse — is either a concrete ``missing`` reason or exit 2,
  never an empty list dressed up as an answer;
* the directory listing is never evidence: a perfectly valid
  ``netlist_raw.json`` beside a report whose capture does not cite it is not
  read, and a stray ``report.model`` stays a summary;
* components are sorted by designator and keep the model's own pin order; nets
  are sorted by name, members are de-duplicated and sorted by designator +
  **numeric** pin (``R1.2`` before ``R1.11``); ``pinName`` is read from the same
  live component's exact pin number, ``""`` for a real empty name and ``None``
  for a member the current component/pin map cannot resolve (a repeated
  designator keeps only its last placement) with that ``REF.pin`` disclosed in
  ``unresolvedPins``;
* the projection never mutates the report and never aliases it, the artifact or
  the machine fields; the CLI still writes nothing, the envelope is the same,
  and the other four sections behave exactly as before;
* the CLI's evidence gate is where the file read happens: identity false and
  ``liveSchematic`` failed must **not** open a bad netlist (exit 0 + missing),
  several matching artifacts are exit 2, and a cited file that fails its proof is
  exit 2 rather than a downgrade to ``missing``.

Everything here is anonymous and synthetic — no editor, daemon, project file,
real report or real netlist.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.candidate import candidate_from_netlist
from boardwise.engines.reviewread import (
    REVIEW_READ_SCHEMA,
    REVIEW_READ_SECTIONS,
    review_read_section,
)

PROJECT = "proj-synthetic-netlist"
OTHER_SECTIONS = ("verdict", "findings", "crossView", "coverage")
PROTECTED = (
    "report.json",
    "report.md",
    "board-report.md",
    "review-summary.md",
    "live-evidence.json",
)
REPORT_MD_SENTINEL = "# synthetic report.md — review-read 不得改写\n"
BOARD_MD_SENTINEL = "# synthetic board-report.md — review-read 不得改写\n"
SUMMARY_SENTINEL = (
    "# synthetic review-summary\n\n"
    "| 位置 | 结论（人写的） | 证据 |\n"
    "| --- | --- | --- |\n"
    "| CTRL/U9.33 | 人工分析，只读命令不得覆盖 | 目测 |\n"
)
LIVE_EVIDENCE_SENTINEL = '{"schema": "boardwise.live-evidence/1", "sentinel": true}\n'

#: The live netlist's own shape (a parsed EasyEDA JSON document). R1.11 exists to
#: prove numeric member sorting (a plain string sort puts it before R1.2).
LIVE_DOC = {
    "version": "2.0.0",
    "components": {
        "g-u9": {
            "props": {
                "Unique ID": "g-u9",
                "Designator": "U9",
                "Value": "MCU",
                "Supplier Footprint": "LQFP-64",
                "Manufacturer Part": "STM32F103",
            },
            "pinInfoMap": {
                "11": {"name": "PA1", "number": "11", "net": "OTHER"},
                # 537C3b3's measured mismatch: FOC_EN's live member is U9.33/PB11.
                "33": {"name": "PB11", "number": "33", "net": "FOC_EN"},
                "34": {"name": "PB12", "number": "34", "net": ""},
            },
        },
        "g-r1": {
            "props": {"Designator": "R1", "Value": "1k", "Supplier Footprint": "0603"},
            "pinInfoMap": {
                "2": {"name": "2", "number": "2", "net": "FOC_EN"},
                "1": {"name": "1", "number": "1", "net": "FOC_EN"},
                "11": {"name": "11", "number": "11", "net": "FOC_EN"},
            },
        },
        "g-r10": {
            "props": {"Designator": "R10", "Value": ""},
            "pinInfoMap": {"1": {"name": "1", "number": "1", "net": "VCC/2"}},
        },
    },
}

#: Two placements answer to one designator. The candidate parser keeps the last
#: placement as the component, so U1.5 is a net member with no current pin: its
#: name is unknown (``None``), not empty (``""``).
DUPLICATE_DOC = {
    "version": "2.0.0",
    "components": {
        "g-u1a": {
            "props": {"Designator": "U1"},
            "pinInfoMap": {"5": {"name": "PA5", "number": "5", "net": "SIG"}},
        },
        "g-u1b": {
            "props": {"Designator": "U1"},
            "pinInfoMap": {"6": {"name": "PA6", "number": "6", "net": "SIG"}},
        },
    },
}

#: A pin that really exists with an empty name: ``""`` is a known empty name and
#: must not be conflated with the unresolved ``None`` above.
EMPTY_NAME_DOC = {
    "version": "2.0.0",
    "components": {
        "g-j1": {
            "props": {"Designator": "J1"},
            "pinInfoMap": {"1": {"name": "", "number": "1", "net": "SIG"}},
        },
        "g-r2": {
            "props": {"Designator": "R2"},
            "pinInfoMap": {"1": {"name": "1", "number": "1", "net": "SIG"}},
        },
    },
}

#: The report's own archive summary: present, readable, and never the live rows.
ARCHIVE_MODEL = {
    "source": "archive",
    "components": [{"designator": "ARCH1", "value": "archive-only"}],
    "nets": [{"name": "ARCH_NET", "members": ["ARCH1.1"]}],
}


def live_text(doc: dict | None = None) -> str:
    return json.dumps(doc if doc is not None else LIVE_DOC, ensure_ascii=False)


def live_model(doc: dict | None = None):
    return candidate_from_netlist(live_text(doc))


def parsed_bytes(text: str | None = None) -> bytes:
    return (text if text is not None else live_text()).encode("utf-8")


def netlist_artifact(data: bytes | None = None, **overrides) -> dict:
    payload = parsed_bytes() if data is None else data
    row = {
        "kind": "netlist",
        "channel": "liveSchematic",
        "file": "netlist_raw.json",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "netlistType": "EasyEDA",
    }
    row.update(overrides)
    return row


def capture(
    *,
    verified: bool = True,
    live_status: str = "ok",
    artifacts: list[dict] | None = None,
) -> dict:
    return {
        "schema": "boardwise.live-evidence/1",
        "ok": verified and live_status == "ok",
        "identity": {
            "expectedProjectUuid": PROJECT,
            "verifiedAgainstReport": verified,
            "ok": verified,
        },
        "channels": {
            "liveSchematic": {"status": live_status, "source": "liveSchematic"},
            "archivePcb": {"status": "ok", "source": "archivePcb"},
        },
        "artifacts": list(artifacts or []),
        "focusRestore": {"status": "restored", "originalUuid": "page-1"},
    }


def report_with_capture(
    capture_row: dict | None = None,
    *,
    model: dict | None = None,
) -> dict:
    """A report shaped like ``merge_live_capture`` writes it (C3b2a contract).

    The capture's ``channels`` are **merged into** ``evidence.channels``; the
    stored ``liveCapture`` is metadata only (identity, artifacts, focusRestore,
    …) and carries no ``channels`` key. The fixture reproduces that split so a
    projection that reads the channel from the wrong place is red, not green.
    """
    evidence: dict = {
        "channels": {
            "liveSchematic": {"status": "missing"},
            "archivePcb": {"status": "ok"},
        },
        "delivery": {"status": "partial"},
    }
    if capture_row is not None:
        live_capture = copy.deepcopy(capture_row)
        channels = live_capture.pop("channels", {})
        assert "channels" not in live_capture, "liveCapture 不得再携带 channels"
        live = channels.get("liveSchematic") if isinstance(channels, dict) else None
        if isinstance(live, dict):
            evidence["channels"]["liveSchematic"] = live
        evidence["liveCapture"] = live_capture
    report = {
        "schema": "boardwise.checkup/7",
        "source": {"project": {"projectUuid": PROJECT, "name": "SYNTH"}},
        "conclusion": {"verdict": "incomplete", "mayClaimPassed": False},
        "findings": [],
        "warning_triage": [],
        "environment": {"limitations": []},
        "evidence": evidence,
    }
    if model is not None:
        report["model"] = model
    return report


def ok_report(*, doc: dict | None = None, model: dict | None = None) -> tuple[dict, dict]:
    data = parsed_bytes(live_text(doc))
    artifact_row = netlist_artifact(data)
    report = report_with_capture(
        capture(artifacts=[artifact_row]), model=model or ARCHIVE_MODEL
    )
    return report, artifact_row


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def run_cli(*argv: str) -> int:
    return cli.main(["review-read", *argv])


def write_out(
    tmp_path: Path,
    report: dict,
    *,
    netlist_bytes: bytes | None = None,
    netlist_name: str = "netlist_raw.json",
) -> Path:
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "report.md").write_text(REPORT_MD_SENTINEL, encoding="utf-8")
    (out / "board-report.md").write_text(BOARD_MD_SENTINEL, encoding="utf-8")
    (out / "review-summary.md").write_text(SUMMARY_SENTINEL, encoding="utf-8")
    (out / "live-evidence.json").write_text(LIVE_EVIDENCE_SENTINEL, encoding="utf-8")
    if netlist_bytes is not None:
        (out / netlist_name).write_bytes(netlist_bytes)
    return out


def hashes(out: Path) -> dict[str, str]:
    return {
        name: hashlib.sha256((out / name).read_bytes()).hexdigest()
        for name in PROTECTED
        if (out / name).exists()
    }


def read_stdout_json(capsys) -> dict:
    captured = capsys.readouterr()
    assert captured.err == "", captured.err
    assert captured.out.endswith("\n")
    return json.loads(captured.out)


def cli_report_for_broken_artifact(
    *, verified: bool = True, live_status: str = "ok"
) -> tuple[dict, bytes]:
    """A capture that cites a netlist whose recorded bytes/hash are both wrong.

    The file on disk is the valid live text, so a command that opens it despite
    the failed identity/channel gate would exit 2 — which is exactly what the
    identity/channel tests must not see.
    """
    data = parsed_bytes()
    broken = netlist_artifact(data, bytes=1, sha256="0" * 64)
    report = report_with_capture(
        capture(verified=verified, live_status=live_status, artifacts=[broken]),
        model=ARCHIVE_MODEL,
    )
    return report, data


# ---------------------------------------------------------------------------
# 1) the pure netlist projection
# ---------------------------------------------------------------------------


def test_netlist_ok_projects_sorted_components_nets_and_numeric_pin_order():
    report, artifact_row = ok_report()

    payload = review_read_section(
        report,
        "netlist",
        live_model=live_model(),
        netlist_artifact=artifact_row,
    )

    assert payload["status"] == "ok"
    assert payload["reason"] == ""

    # The archive summary travels as a copy, never as the live rows.
    assert payload["model"] == ARCHIVE_MODEL
    assert payload["model"] is not report["model"]
    assert "ARCH1" not in [row["designator"] for row in payload["components"]]

    # Machine fields are copied from the capture verbatim.
    assert payload["identity"] == report["evidence"]["liveCapture"]["identity"]
    assert payload["liveSchematic"] == {
        "status": "ok",
        "source": "liveSchematic",
    }
    assert payload["artifact"] == artifact_row
    assert payload["artifact"] is not artifact_row

    # Components by designator; the model's own pin order is preserved.
    assert [row["designator"] for row in payload["components"]] == ["R1", "R10", "U9"]
    u9 = payload["components"][2]
    assert u9 == {
        "uid": "g-u9",
        "designator": "U9",
        "value": "MCU",
        "footprint": "LQFP-64",
        "mpn": "STM32F103",
        "pins": [
            {"number": "11", "name": "PA1", "net": "OTHER"},
            {"number": "33", "name": "PB11", "net": "FOC_EN"},
            {"number": "34", "name": "PB12", "net": None},
        ],
    }
    r1 = payload["components"][0]
    assert [pin["number"] for pin in r1["pins"]] == ["2", "1", "11"]

    # Nets by name; members de-duplicated and sorted by designator + NUMERIC pin
    # (R1.2 before R1.11), names from the same component's exact pin number.
    assert [row["name"] for row in payload["nets"]] == ["FOC_EN", "OTHER", "VCC/2"]
    foc = payload["nets"][0]
    assert foc["members"] == [
        {"pin": "R1.1", "pinName": "1"},
        {"pin": "R1.2", "pinName": "2"},
        {"pin": "R1.11", "pinName": "11"},
        {"pin": "U9.33", "pinName": "PB11"},
    ]
    assert payload["unresolvedPins"] == []
    assert payload["repeatedDesignators"] == []


def test_netlist_pin_name_uses_the_exact_pin_number_not_a_prefix():
    """U9.3 must not borrow U9.33's name; a missing pin is unresolved, not ``""``."""
    report, artifact_row = ok_report()

    model = live_model()
    payload = review_read_section(
        report, "netlist", live_model=model, netlist_artifact=artifact_row
    )
    u9_names = {
        member["pin"]: member["pinName"]
        for net in payload["nets"]
        for member in net["members"]
    }
    assert u9_names["U9.33"] == "PB11"
    assert u9_names["U9.11"] == "PA1"


def test_netlist_repeated_designator_discloses_unresolved_member_with_null_name():
    data = parsed_bytes(live_text(DUPLICATE_DOC))
    report = report_with_capture(capture(artifacts=[netlist_artifact(data)]))
    model = live_model(DUPLICATE_DOC)

    payload = review_read_section(
        report,
        "netlist",
        live_model=model,
        netlist_artifact=netlist_artifact(data),
    )

    assert payload["status"] == "ok"  # the live evidence was read; the ambiguity is disclosed
    assert payload["repeatedDesignators"] == ["U1"]
    assert payload["unresolvedPins"] == ["U1.5"]
    members = payload["nets"][0]["members"]
    # Both members survive — nothing is silently dropped.
    assert members == [
        {"pin": "U1.5", "pinName": None},
        {"pin": "U1.6", "pinName": "PA6"},
    ]


def test_netlist_real_empty_pin_name_stays_an_empty_string():
    data = parsed_bytes(live_text(EMPTY_NAME_DOC))
    report = report_with_capture(capture(artifacts=[netlist_artifact(data)]))

    payload = review_read_section(
        report,
        "netlist",
        live_model=live_model(EMPTY_NAME_DOC),
        netlist_artifact=netlist_artifact(data),
    )

    assert payload["unresolvedPins"] == []
    assert payload["nets"][0]["members"] == [
        {"pin": "J1.1", "pinName": ""},
        {"pin": "R2.1", "pinName": "1"},
    ]


@pytest.mark.parametrize(
    ("report", "artifact", "expected"),
    [
        pytest.param(
            report_with_capture(None, model=ARCHIVE_MODEL),
            None,
            "liveCapture",
            id="no-live-capture",
        ),
        pytest.param(
            report_with_capture(
                capture(verified=False, artifacts=[netlist_artifact()]),
                model=ARCHIVE_MODEL,
            ),
            None,
            "verifiedAgainstReport",
            id="identity-not-verified",
        ),
        pytest.param(
            report_with_capture(
                capture(live_status="failed", artifacts=[netlist_artifact()]),
                model=ARCHIVE_MODEL,
            ),
            None,
            "liveSchematic",
            id="live-schematic-failed",
        ),
        pytest.param(
            report_with_capture(capture(artifacts=[]), model=ARCHIVE_MODEL),
            None,
            "记录",
            id="no-netlist-artifact",
        ),
        pytest.param(
            report_with_capture(
                capture(artifacts=[netlist_artifact()]), model=ARCHIVE_MODEL
            ),
            netlist_artifact(),
            "live_model",
            id="artifact-without-parsed-model",
        ),
    ],
)
def test_netlist_missing_states_a_concrete_reason_and_never_promotes_the_archive(
    report, artifact, expected
):
    payload = review_read_section(
        report, "netlist", live_model=None, netlist_artifact=artifact
    )

    assert payload["status"] == "missing"
    assert expected in payload["reason"]
    assert payload["components"] == []
    assert payload["nets"] == []
    assert payload["repeatedDesignators"] == []
    assert payload["unresolvedPins"] == []
    # The summary is still readable, but it is named as a summary.
    assert payload["model"] == ARCHIVE_MODEL
    assert "ARCH1" not in json.dumps(payload["components"])


def test_netlist_old_report_with_only_report_model_is_a_summary_not_a_netlist():
    report = report_with_capture(None, model=ARCHIVE_MODEL)
    report.pop("evidence")  # pre-537C report: no evidence section at all

    payload = review_read_section(report, "netlist")

    assert payload["status"] == "missing"
    assert payload["components"] == []
    assert payload["nets"] == []
    assert payload["liveSchematic"] is None
    assert payload["identity"] is None
    assert payload["artifact"] is None
    assert payload["model"] == ARCHIVE_MODEL
    assert payload["model"] is not report["model"]


def test_netlist_projection_does_not_mutate_or_alias_any_input():
    report, artifact_row = ok_report()
    report_before = copy.deepcopy(report)
    artifact_before = copy.deepcopy(artifact_row)
    model = live_model()
    model_components_before = copy.deepcopy(model.components)

    payload = review_read_section(
        report, "netlist", live_model=model, netlist_artifact=artifact_row
    )
    assert report == report_before

    payload["status"] = "tampered"
    payload["model"]["components"].append({"designator": "INJECTED"})
    payload["artifact"]["sha256"] = "f" * 64
    payload["identity"]["verifiedAgainstReport"] = False
    payload["liveSchematic"]["status"] = "failed"
    payload["components"][0]["pins"].append({"number": "99", "name": "X", "net": None})
    payload["nets"][0]["members"].append({"pin": "X.1", "pinName": "X"})
    payload["repeatedDesignators"].append("INJECTED")
    payload["unresolvedPins"].append("INJECTED.1")

    assert report == report_before
    assert artifact_row == artifact_before
    assert model.components == model_components_before


def test_netlist_needs_a_model_the_projection_can_read():
    report = report_with_capture(capture(artifacts=[netlist_artifact()]))

    with pytest.raises(ValueError):
        review_read_section(
            report,
            "netlist",
            live_model=object(),
            netlist_artifact=netlist_artifact(),
        )


def test_netlist_is_in_the_section_table_and_unknown_names_still_fail():
    assert "netlist" in REVIEW_READ_SECTIONS
    assert REVIEW_READ_SECTIONS[-1] == "netlist"

    payload = review_read_section(report_with_capture(None), "netlist")
    assert payload["status"] == "missing"

    with pytest.raises(ValueError):
        review_read_section(report_with_capture(None), "netlist-raw")


# ---------------------------------------------------------------------------
# 2) the CLI: evidence gate, file proof, envelope, exit codes
# ---------------------------------------------------------------------------


def test_cli_netlist_ok_projects_the_live_model_and_matches_stdout_bytes(tmp_path, capsys):
    report, artifact_row = ok_report()
    out = write_out(tmp_path, report, netlist_bytes=parsed_bytes())

    assert run_cli("--out", str(out), "--section", "netlist") == 0
    envelope = read_stdout_json(capsys)

    assert set(envelope) == {"schema", "section", "report", "payload"}
    assert envelope["schema"] == REVIEW_READ_SCHEMA
    assert envelope["section"] == "netlist"
    assert Path(envelope["report"]["path"]) == (out / "report.json").resolve()
    assert envelope["payload"] == review_read_section(
        report,
        "netlist",
        live_model=live_model(),
        netlist_artifact=artifact_row,
    )
    assert envelope["payload"]["status"] == "ok"
    assert envelope["payload"]["unresolvedPins"] == []
    assert "ok" not in envelope

    # The file form is the same bytes as stdout, and repeatable.
    target = tmp_path / "netlist-read.json"
    assert run_cli(
        "--out", str(out), "--section", "netlist", "--json", str(target)
    ) == 0
    assert capsys.readouterr().out == ""
    assert run_cli("--out", str(out), "--section", "netlist") == 0
    assert capsys.readouterr().out.encode("utf-8") == target.read_bytes()


def test_cli_netlist_identity_false_never_opens_the_cited_file(tmp_path, capsys):
    report, data = cli_report_for_broken_artifact(verified=False)
    out = write_out(tmp_path, report, netlist_bytes=data)

    # A command that read the file would exit 2 (its bytes/hash are deliberately
    # wrong); the evidence gate must stop before the open.
    assert run_cli("--out", str(out), "--section", "netlist") == 0
    payload = read_stdout_json(capsys)["payload"]
    assert payload["status"] == "missing"
    assert "verifiedAgainstReport" in payload["reason"]
    assert payload["components"] == []


def test_cli_netlist_live_schematic_failed_never_opens_the_cited_file(tmp_path, capsys):
    report, data = cli_report_for_broken_artifact(live_status="failed")
    out = write_out(tmp_path, report, netlist_bytes=data)

    assert run_cli("--out", str(out), "--section", "netlist") == 0
    payload = read_stdout_json(capsys)["payload"]
    assert payload["status"] == "missing"
    assert "liveSchematic" in payload["reason"]


def test_cli_netlist_without_an_artifact_citation_is_missing_not_an_error(tmp_path, capsys):
    report = report_with_capture(capture(artifacts=[]), model=ARCHIVE_MODEL)
    out = write_out(tmp_path, report, netlist_bytes=parsed_bytes())

    assert run_cli("--out", str(out), "--section", "netlist") == 0
    payload = read_stdout_json(capsys)["payload"]
    assert payload["status"] == "missing"
    assert "记录" in payload["reason"]
    assert payload["components"] == []


def test_cli_netlist_never_guesses_from_a_file_in_the_directory(tmp_path, capsys):
    report = report_with_capture(None, model=ARCHIVE_MODEL)
    out = write_out(tmp_path, report, netlist_bytes=parsed_bytes())

    assert run_cli("--out", str(out), "--section", "netlist") == 0
    payload = read_stdout_json(capsys)["payload"]
    assert payload["status"] == "missing"
    assert "liveCapture" in payload["reason"]
    assert payload["components"] == []
    assert payload["nets"] == []


def test_cli_netlist_multiple_artifacts_are_contradictory_evidence_exit_two(
    tmp_path, capsys
):
    data = parsed_bytes()
    second = netlist_artifact(data, file="netlist_raw_2.json")
    report = report_with_capture(capture(artifacts=[netlist_artifact(data), second]))
    out = write_out(tmp_path, report, netlist_bytes=data)
    before = hashes(out)

    assert run_cli("--out", str(out), "--section", "netlist") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "恰好一条" in captured.err
    assert hashes(out) == before


@pytest.mark.parametrize(
    ("overrides", "needle"),
    [
        pytest.param({"sha256": "0" * 64}, "sha256", id="hash-mismatch"),
        pytest.param({"bytes": 1}, "字节数", id="byte-count-mismatch"),
        pytest.param({"file": "../escape.json"}, "单文件名", id="path-escape"),
        pytest.param({"bytes": None}, "bytes", id="missing-bytes"),
        pytest.param({"sha256": None}, "sha256", id="missing-hash"),
    ],
)
def test_cli_netlist_artifact_that_fails_its_proof_is_exit_two(
    overrides, needle, tmp_path, capsys
):
    data = parsed_bytes()
    report = report_with_capture(capture(artifacts=[netlist_artifact(data, **overrides)]))
    out = write_out(tmp_path, report, netlist_bytes=data)
    before = hashes(out)
    target = tmp_path / "should-not-exist.json"

    assert run_cli(
        "--out", str(out), "--section", "netlist", "--json", str(target)
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert needle in captured.err
    assert not target.exists()
    assert hashes(out) == before


def test_cli_netlist_non_utf8_is_exit_two(tmp_path, capsys):
    data = b"\xff\xfe\x00not-utf8"
    report = report_with_capture(capture(artifacts=[netlist_artifact(data)]))
    out = write_out(tmp_path, report, netlist_bytes=data)
    before = hashes(out)

    assert run_cli("--out", str(out), "--section", "netlist") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "UTF-8" in captured.err
    assert hashes(out) == before


def test_cli_netlist_parse_failure_is_exit_two_not_missing(tmp_path, capsys):
    data = b'{"version": "2.0.0"}'
    report = report_with_capture(capture(artifacts=[netlist_artifact(data)]))
    out = write_out(tmp_path, report, netlist_bytes=data)
    before = hashes(out)

    assert run_cli("--out", str(out), "--section", "netlist") == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "解析" in captured.err
    assert hashes(out) == before


def test_cli_netlist_read_is_side_effect_free_and_keeps_the_sentinels(
    tmp_path, capsys
):
    report, _ = ok_report()
    out = write_out(tmp_path, report, netlist_bytes=parsed_bytes())
    before = hashes(out)
    netlist_before = (out / "netlist_raw.json").read_bytes()

    assert run_cli("--out", str(out), "--section", "netlist") == 0
    capsys.readouterr()

    assert hashes(out) == before
    assert (out / "netlist_raw.json").read_bytes() == netlist_before
    assert (out / "review-summary.md").read_text(encoding="utf-8") == SUMMARY_SENTINEL


def test_cli_netlist_unresolved_pin_reaches_the_envelope(tmp_path, capsys):
    data = parsed_bytes(live_text(DUPLICATE_DOC))
    report = report_with_capture(capture(artifacts=[netlist_artifact(data)]))
    out = write_out(tmp_path, report, netlist_bytes=data)

    assert run_cli("--out", str(out), "--section", "netlist") == 0
    payload = read_stdout_json(capsys)["payload"]

    assert payload["status"] == "ok"
    assert payload["repeatedDesignators"] == ["U1"]
    assert payload["unresolvedPins"] == ["U1.5"]
    assert payload["nets"][0]["members"][0] == {"pin": "U1.5", "pinName": None}


# ---------------------------------------------------------------------------
# 3) regression: the four earlier sections and the envelope are untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("section", OTHER_SECTIONS)
def test_old_sections_project_exactly_as_before(
    section, tmp_path, capsys
):
    report, _ = ok_report()
    out = write_out(tmp_path, report, netlist_bytes=parsed_bytes())
    before = hashes(out)

    assert run_cli("--out", str(out), "--section", section) == 0
    envelope = read_stdout_json(capsys)

    assert envelope["section"] == section
    assert envelope["payload"] == review_read_section(report, section)
    assert "netlist" not in envelope["payload"]
    assert hashes(out) == before


def test_envelope_schema_and_section_vocabulary_are_stable():
    assert REVIEW_READ_SCHEMA == "boardwise.review-read/1"
    assert tuple(REVIEW_READ_SECTIONS)[:4] == OTHER_SECTIONS
    # 537D1a2b inserts `artifacts` between the four earlier sections and
    # `netlist`; neither of those moved or changed shape.
    assert tuple(REVIEW_READ_SECTIONS) == OTHER_SECTIONS + ("artifacts", "netlist")


def test_fixture_matches_the_live_merge_contract():
    """The report shape this suite uses is ``merge_live_capture``'s own.

    A capture-shaped fixture (channels inside ``liveCapture``) made the first
    implementation green while a real enhanced report returned ``missing``. This
    guards the fixture, not the projection: the merged report has the channel row
    at ``evidence.channels.liveSchematic`` and no ``channels`` in the metadata.
    """
    report, _ = ok_report()

    assert "channels" not in report["evidence"]["liveCapture"]
    assert report["evidence"]["channels"]["liveSchematic"] == {
        "status": "ok",
        "source": "liveSchematic",
    }
    assert report["evidence"]["liveCapture"]["identity"]["verifiedAgainstReport"] is True
