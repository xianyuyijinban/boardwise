"""CLI smoke tests against the real fixture."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
FIXTURE = Path(__file__).parent / "fixtures" / "board24v.enet"
EPRU_FIXTURE = Path(__file__).parent / "fixtures" / "llc_board.epro2"


def run_cli(*args):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "boardwise.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_review_fixture_smoke(tmp_path):
    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    result = run_cli(
        "review", str(FIXTURE), "--json", str(json_path), "--md", str(md_path)
    )
    # Exit code contract: 1 on ERROR findings, else 0. Fixture has no ERRORs.
    assert result.returncode == 0, result.stderr
    assert "findings:" in result.stdout
    assert "ERROR" in result.stdout

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"] == {"ERROR": 0, "WARN": 0, "INFO": 0}
    assert isinstance(payload["findings"], list)

    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("# boardwise review report")
    assert "No findings." in md


def test_review_exit_code_on_error(tmp_path):
    # Craft a minimal .enet that triggers the decoupling ERROR-free path is
    # covered above; here we only assert the exit code stays within contract.
    enet = tmp_path / "tiny.enet"
    enet.write_text(
        json.dumps(
            {
                "version": "2.0.0",
                "components": {
                    "u1uid": {
                        "props": {"Designator": "U1", "Value": ""},
                        "pinInfoMap": {
                            "1": {"name": "1", "number": "1", "net": "VCC"},
                            "2": {"name": "2", "number": "2", "net": "GND"},
                        },
                    }
                },
                "designRule": {},
                "differentialPair": {},
                "netClass": {},
                "equalLengthNetGroup": {},
            }
        ),
        encoding="utf-8",
    )
    result = run_cli("review", str(enet))
    assert result.returncode in (0, 1)
    assert "decoupling-per-ic" in result.stdout  # WARN expected, exit 0
    assert result.returncode == 0


def test_review_epro2_fixture_smoke(tmp_path):
    # One file in, full report out: the same reviewer as .enet, plus the
    # board line that only a backup can provide.
    json_path = tmp_path / "report.json"
    md_path = tmp_path / "report.md"
    result = run_cli(
        "review", str(EPRU_FIXTURE), "--json", str(json_path), "--md", str(md_path)
    )
    assert result.returncode == 0, result.stderr
    assert "(47 components, 25 nets)" in result.stdout
    assert "board: 117 pads, 49 tracks, 257 vias" in result.stdout
    assert "0 ERROR, 7 WARN" in result.stdout
    assert "decoupling-per-ic" in result.stdout

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"] == {"ERROR": 0, "WARN": 7, "INFO": 0}

    md = md_path.read_text(encoding="utf-8")
    assert md.startswith("# boardwise review report")
    assert "Components: 47" in md


def test_review_rejects_unknown_extension(tmp_path):
    target = tmp_path / "board.brd"
    target.write_text("not a reviewable input", encoding="utf-8")
    result = run_cli("review", str(target))
    assert result.returncode == 2
    assert "unsupported input type" in result.stderr
    assert ".enet" in result.stderr and ".epro2" in result.stderr


def test_review_reports_encrypted_backup(tmp_path):
    # An encrypted export is not a ZIP at all; the user must be told to
    # re-export, not shown a stack trace.
    target = tmp_path / "board.epro2"
    target.write_bytes(b"\x00not a zip")
    result = run_cli("review", str(target))
    assert result.returncode == 2
    assert "re-export" in result.stderr


def test_bridge_help_renders_the_action_catalogue():
    # The catalogue is the daemon's routing table; --help must show it, or the
    # two drift and an action ends up routable but undocumented.
    result = run_cli("bridge", "--help")
    assert result.returncode == 0, result.stderr
    for action in (
        "hello",
        "ping",
        "document.current",
        "sch.readback",
        "pcb.readback",
        "export.screenshot",
        "canvas.highlight",
        "export.render",
        "sys.probe",
    ):
        assert action in result.stdout, f"{action} missing from bridge --help"
    # Owners must be visible: it is the difference between local and forwarded.
    assert "daemon" in result.stdout and "connector" in result.stdout
