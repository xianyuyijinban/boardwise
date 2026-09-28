"""Drift guard (045 §7): the dsh plugin wraps CLI commands **by name**.

`dsh-plugin/src/index.ts` builds argv arrays whose first token is a boardwise
CLI command. Renaming or removing such a command breaks the plugin on every dsh
machine, silently from pytest's point of view — unless this guard is watching.
The reverse direction (a new CLI command not yet wrapped) is a release-checklist
judgment, not a failure: see `tasks/045-dsh-plugin.md` §7.
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "src" / "boardwise" / "cli.py"
PLUGIN = REPO / "dsh-plugin" / "src" / "index.ts"
PLUGIN_PKG = REPO / "dsh-plugin" / "package.json"
PLUGIN_README = REPO / "dsh-plugin" / "README.md"

# 067: peer range and the dsh versions we actually ran, kept in lockstep with
# dsh-plugin/README.md "已验证的 dsh 版本". Widening/narrowing the range or
# leaving a stale README is a release judgment — make it a red test instead.
PEER_RANGE = ">=0.0.1-rc.1 <0.3.0 || >=0.1.7-rc.2 <0.2.0-0 || >=0.2.0-rc.1 <0.3.0-0"
VERIFIED_DSH = ("0.1.7-rc.2", "0.2.0-rc.1")


def _cli_commands() -> set[str]:
    text = CLI.read_text(encoding="utf-8")
    # `add_parser("name"` — the name may sit on the next line (\s spans it).
    return set(re.findall(r"add_parser\(\s*[\"']([\w-]+)[\"']", text))


def _wrapped_commands() -> set[str]:
    text = PLUGIN.read_text(encoding="utf-8")
    commands = set()
    for argv in re.findall(r"const argv = \[([^\]]+)\]", text):
        first = argv.split(",", 1)[0].strip().strip("'\"")
        if first:
            commands.add(first)
    return commands


def test_every_command_the_dsh_plugin_spawns_exists_in_the_cli():
    wrapped = _wrapped_commands()
    assert wrapped, "guard vacuous: no argv arrays found in dsh-plugin/src/index.ts"
    missing = wrapped - _cli_commands()
    assert not missing, (
        f"dsh-plugin wraps CLI commands that no longer exist: {sorted(missing)} — "
        "a rename in cli.py must be mirrored in dsh-plugin (045 §7 sync discipline)"
    )


def _plugin_package() -> dict:
    return json.loads(PLUGIN_PKG.read_text(encoding="utf-8"))


def test_peer_range_is_the_one_we_tested():
    """`<0.2.0` hard-fails `npm install` against dsh-tools 0.2.x (066 §2b)."""
    peers = _plugin_package()["peerDependencies"]
    assert peers["@deepseek-ai/dsh-tools"] == PEER_RANGE, (
        f"dsh-tools peer range drifted: {peers['@deepseek-ai/dsh-tools']!r} != "
        f"{PEER_RANGE!r} — if the range moved deliberately, re-run the dsh matrix "
        "(outputs/066_dsh_matrix/) and update README 已验证的 dsh 版本 together"
    )


def test_readme_lists_the_verified_dsh_versions():
    readme = PLUGIN_README.read_text(encoding="utf-8")
    missing = [v for v in VERIFIED_DSH if v not in readme]
    assert not missing, (
        f"dsh-plugin/README.md lost the verified dsh versions: {missing} — "
        "the 已验证的 dsh 版本 table is the only place we record what was actually run"
    )


def test_readme_install_snippet_matches_the_packed_version():
    readme = PLUGIN_README.read_text(encoding="utf-8")
    version = _plugin_package()["version"]
    assert f"boardwise-dsh-{version}.tgz" in readme, (
        f"dsh-plugin/README.md install snippet does not name boardwise-dsh-{version}.tgz "
        "(a version bump must carry the README tarball path along)"
    )
