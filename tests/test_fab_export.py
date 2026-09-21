"""The writing half of `export.fab` (012v2 §六).

The connector can hand back base64 fab files but cannot write them: the declared
`SYS_FileSystem.saveFile(fileData, fileName?)` takes no destination directory. So
the daemon-side CLI is the writer, and this file tests that writer — the part
that can put bytes in the wrong place — without a daemon, an editor or a socket.

`boardwise bridge export-fab` itself is covered at the two ends that do not need
EasyEDA: the argument/exit-code wiring (against a port nothing listens on) and
the catalogue registration (params, risk, timeout).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["BOARDWISE_HOME"] = str(tmp_path)
    env["BOARDWISE_PORT"] = str(_free_port())
    return subprocess.run(
        [sys.executable, "-m", "boardwise.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


def _file(name: str, blob: bytes, role: str = "gerber") -> dict:
    return {
        "role": role,
        "name": name,
        "mime": "application/octet-stream",
        "bytes": len(blob),
        "data": base64.b64encode(blob).decode("ascii"),
        "sourceName": name,
    }


def _payload(*files: dict, manifest: dict | None = None, failed: list | None = None) -> dict:
    return {
        "vendor": "generic",
        "files": list(files),
        "manifest": manifest if manifest is not None else {
            "schema": "boardwise.fab/1",
            "generatedAt": "2026-09-21T12:00:00.000Z",
            "vendor": "generic",
            "project": {"uuid": "proj-1", "name": "毕设板"},
            "pcb": {"uuid": "pcb-1", "name": "PCB1"},
            "outDir": "E:/somewhere/else",
            "files": [{"role": f["role"], "name": f["name"], "bytes": f["bytes"]} for f in files],
        },
        "failed": failed or [],
        "partial": bool(failed),
    }


def test_the_bundle_lands_and_the_manifest_says_what_arrived(tmp_path):
    from boardwise.cli import _write_fab_bundle

    out = tmp_path / "fab"
    payload = _payload(
        _file("fab_gerber.zip", b"PK\x03\x04gerber-bytes"),
        _file("fab_pick_and_place.csv", b"Ref,X,Y\nD1,1,2\n", "pick_and_place"),
        _file("fab_bom.csv", b"No.,Quantity\n1,2\n", "bom"),
    )
    result = _write_fab_bundle(payload, out)

    assert result["outDir"] == str(out)
    assert (out / "fab_gerber.zip").read_bytes() == b"PK\x03\x04gerber-bytes"
    assert (out / "fab_bom.csv").read_bytes() == b"No.,Quantity\n1,2\n"
    assert [entry["name"] for entry in result["written"]] == [
        "fab_gerber.zip", "fab_pick_and_place.csv", "fab_bom.csv",
    ]
    # The size is the one `stat` reports, not the connector's claim: the write
    # is the thing being verified.
    assert all(entry["bytes"] == entry["declaredBytes"] for entry in result["written"])
    assert result["mismatched"] == []

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    # The connector's manifest is kept, and enriched with what only the writer
    # knows: where the bundle actually went, and what landed there.
    assert manifest["schema"] == "boardwise.fab/1"
    assert manifest["project"]["name"] == "毕设板"
    assert manifest["outDir"] == str(out)
    assert [entry["name"] for entry in manifest["written"]] == [
        "fab_gerber.zip", "fab_pick_and_place.csv", "fab_bom.csv",
    ]
    assert [entry["bytes"] for entry in manifest["written"]] == [
        len(b"PK\x03\x04gerber-bytes"), len(b"Ref,X,Y\nD1,1,2\n"), len(b"No.,Quantity\n1,2\n"),
    ]


def test_the_bundle_directory_is_created_when_it_does_not_exist(tmp_path):
    from boardwise.cli import _write_fab_bundle

    out = tmp_path / "deep" / "not" / "there"
    _write_fab_bundle(_payload(_file("fab_bom.csv", b"x", "bom")), out)
    assert (out / "fab_bom.csv").exists()
    assert (out / "manifest.json").exists()


@pytest.mark.parametrize("name", ["../escape.csv", "sub/escape.csv", "..", "."])
def test_a_file_name_must_be_one_path_segment(tmp_path, name):
    """The name can come from the editor, so it must not be able to leave `outDir`."""
    from boardwise.cli import FabWriteError, _write_fab_bundle

    out = tmp_path / "fab"
    with pytest.raises(FabWriteError, match="single"):
        _write_fab_bundle(_payload(_file(name, b"nope")), out)
    # Refused, not sanitised: nothing was written anywhere, and in particular
    # nothing appeared next to the directory.
    assert not (tmp_path / "escape.csv").exists()
    assert not (out / "escape.csv").exists()


def test_a_payload_without_files_is_refused_with_the_reason(tmp_path):
    from boardwise.cli import FabWriteError, _write_fab_bundle

    payload = _payload()
    payload["files"] = []
    payload["failed"] = [{"role": "gerber", "reason": "the editor returned an empty file"}]
    with pytest.raises(FabWriteError, match="no files to write") as caught:
        _write_fab_bundle(payload, tmp_path / "fab")
    # The failure reason travels into the error, so a caller is not left with
    # "nothing was written" and no idea why.
    assert "empty file" in str(caught.value)


def test_data_that_is_not_base64_is_refused(tmp_path):
    from boardwise.cli import FabWriteError, _write_fab_bundle

    entry = _file("fab_bom.csv", b"x", "bom")
    entry["data"] = "not base64!!"
    with pytest.raises(FabWriteError, match="not base64"):
        _write_fab_bundle(_payload(entry), tmp_path / "fab")


def test_an_empty_blob_is_refused_as_no_data(tmp_path):
    # An empty file is not a small file: the connector already refuses to call
    # one a success, and the writer refuses to create it either.
    from boardwise.cli import FabWriteError, _write_fab_bundle

    entry = _file("fab_bom.csv", b"", "bom")
    entry["bytes"] = 0
    with pytest.raises(FabWriteError, match="sent no data"):
        _write_fab_bundle(_payload(entry), tmp_path / "fab")


def test_a_byte_count_disagreement_is_reported_not_swallowed(tmp_path):
    from boardwise.cli import _write_fab_bundle

    entry = _file("fab_bom.csv", b"twelve bytes", "bom")
    entry["bytes"] = 999_999  # the connector's claim, wrong on purpose
    result = _write_fab_bundle(_payload(entry), tmp_path / "fab")

    assert result["mismatched"] == ["fab_bom.csv"]
    assert result["written"][0]["bytes"] == len(b"twelve bytes")
    manifest = json.loads((tmp_path / "fab" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["byteCountMismatch"] == ["fab_bom.csv"]


def test_a_payload_that_is_not_an_object_is_refused(tmp_path):
    from boardwise.cli import FabWriteError, _write_fab_bundle

    with pytest.raises(FabWriteError, match="not a payload"):
        _write_fab_bundle(["nope"], tmp_path / "fab")


def test_export_fab_says_so_when_the_daemon_is_not_running(tmp_path):
    result = _run_cli(tmp_path, "bridge", "export-fab", "--out", str(tmp_path / "fab"))
    assert result.returncode == 2
    assert "daemon not reachable" in result.stderr
    # Nothing was created for a bundle that never arrived.
    assert not (tmp_path / "fab").exists()


def test_export_fab_rejects_gerber_overrides_that_are_not_json(tmp_path):
    result = _run_cli(
        tmp_path, "bridge", "export-fab", "--out", str(tmp_path / "fab"), "--gerber", "{oops",
    )
    assert result.returncode == 2
    assert "--gerber is not JSON" in result.stderr


def test_export_fab_is_a_read_action_with_its_own_timeouts():
    """The daemon-side half of the contract, which no connector test can see."""
    from boardwise.bridge.protocol import (
        FAB_TIMEOUT,
        RECOMMEND_TIMEOUT,
        action_spec,
        timeout_for,
    )

    fab = action_spec("export.fab")
    assert fab is not None
    assert fab.risk == "read", "an export writes files, not project content"
    assert fab.owner == "connector"
    assert set(fab.params) >= {"pcbUuid", "outDir", "vendor", "gerber", "bomTemplate"}
    # Three exports at up to 60 s each have to fit inside the daemon's patience,
    # or the connector's per-file answer never reaches the caller.
    assert timeout_for("export.fab") == FAB_TIMEOUT >= 3 * 60

    recommend = action_spec("lib.recommend")
    assert recommend is not None
    assert recommend.risk == "read"
    assert recommend.owner == "connector"
    assert set(recommend.params) >= {"query", "pageUuid", "ref", "topN"}
    assert timeout_for("lib.recommend") == RECOMMEND_TIMEOUT > 30

    # Both are plain `domain.verb` names, so neither needed a new naming family.
    for action in (fab, recommend):
        assert action.name.count(".") == 1
