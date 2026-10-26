"""Drift guard (045 §7): the dsh plugin wraps CLI commands **by name**.

Every module under `dsh-plugin/src/` builds argv arrays whose first token is a
boardwise CLI command (`index.ts` for most tools, `review-finalize.ts` for
`review finalize`). Renaming or removing such a command breaks the plugin on
every dsh machine, silently from pytest's point of view — unless this guard is
watching. The reverse direction (a new CLI command not yet wrapped) is a
release-checklist judgment, not a failure: see `tasks/045-dsh-plugin.md` §7.

`review finalize` also gets its own pin: the top-level `review` group surviving
in cli.py says nothing about the subcommand, so the plugin's
`['review', 'finalize', …]` argv **and** the CLI dispatch to
`_cmd_review_finalize` are both asserted by name (537D3a).
"""

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "src" / "boardwise" / "cli.py"
COMMAND_SRC = REPO / "src" / "boardwise" / "commands"
PLUGIN_SRC = REPO / "dsh-plugin" / "src"
REVIEW_FINALIZE_MODULE = PLUGIN_SRC / "review-finalize.ts"
PLUGIN_PKG = REPO / "dsh-plugin" / "package.json"
PLUGIN_README = REPO / "dsh-plugin" / "README.md"

# 067: peer range and the dsh versions we actually ran, kept in lockstep with
# dsh-plugin/README.md "已验证的 dsh 版本". Widening/narrowing the range or
# leaving a stale README is a release judgment — make it a red test instead.
PEER_RANGE = ">=0.0.1-rc.1 <0.3.0 || >=0.1.7-rc.2 <0.2.0-0 || >=0.2.0-rc.1 <0.3.0-0"
VERIFIED_DSH = ("0.1.7-rc.2", "0.2.0-rc.1")

# `['review', 'finalize'` with any spacing / quote style.
REVIEW_FINALIZE_ARGV = re.compile(r"\[\s*(['\"])review\1\s*,\s*(['\"])finalize\2")
# The CLI dispatch, either spelling: `getattr(args, "file", None) == "finalize"`
# (today's code) or `args.file == "finalize"`.
REVIEW_FINALIZE_DISPATCH = re.compile(
    r'(?:getattr\(\s*args\s*,\s*(["\'])file\1\s*(?:,\s*None\s*)?\)|args\.file)'
    r'\s*==\s*(["\'])finalize\2'
)
REVIEW_FINALIZE_HANDLER = "_cmd_review_finalize("


def _cli_commands() -> set[str]:
    commands = set()
    # 540B4: registration may live in a line-owned command module, not only in
    # the assembly entry. Scan both rather than mistaking extraction for removal.
    for source in [CLI, *sorted(COMMAND_SRC.rglob("*.py"))]:
        text = source.read_text(encoding="utf-8")
        # `add_parser("name"` — the name may sit on the next line (\s spans it).
        commands.update(re.findall(r"add_parser\(\s*[\"']([\w-]+)[\"']", text))
    return commands


def _plugin_modules() -> list[Path]:
    """Every TypeScript module under dsh-plugin/src, in a stable order."""
    return sorted(PLUGIN_SRC.glob("*.ts"))


def _wrapped_commands() -> set[str]:
    commands = set()
    for module in _plugin_modules():
        text = module.read_text(encoding="utf-8")
        for argv in re.findall(r"const argv = \[([^\]]+)\]", text):
            first = argv.split(",", 1)[0].strip()
            # Only a quoted literal names a CLI command; `[...cli.prefix, …]`
            # (the spawn wrapper itself) is a spread, not a command.
            if not first.startswith(("'", '"')):
                continue
            command = first.strip("'\"")
            if command:
                commands.add(command)
    return commands


def test_every_command_the_dsh_plugin_spawns_exists_in_the_cli():
    wrapped = _wrapped_commands()
    assert wrapped, "guard vacuous: no argv arrays found under dsh-plugin/src/*.ts"
    available = _cli_commands()
    assert "draw" in available, "command discovery must include commands/draw.py"
    missing = wrapped - available
    assert not missing, (
        f"dsh-plugin wraps CLI commands that no longer exist: {sorted(missing)} — "
        "a rename in a CLI command module must be mirrored in dsh-plugin "
        "(045 §7 sync discipline)"
    )


def test_review_finalize_subcommand_is_wrapped_and_still_dispatched():
    """537D3a: the subcommand is pinned on both sides, not just its `review` group."""
    plugin = REVIEW_FINALIZE_MODULE.read_text(encoding="utf-8")
    assert REVIEW_FINALIZE_ARGV.search(plugin), (
        "dsh-plugin/src/review-finalize.ts no longer builds a `['review', 'finalize', …]` argv — "
        "a surviving top-level `review` command does not keep the finalize subcommand alive"
    )

    cli = CLI.read_text(encoding="utf-8")
    dispatch = REVIEW_FINALIZE_DISPATCH.search(cli)
    assert dispatch, (
        "src/boardwise/cli.py no longer dispatches `review finalize` on args.file == \"finalize\""
    )
    window = cli[dispatch.start(): dispatch.start() + 400]
    assert REVIEW_FINALIZE_HANDLER in window, (
        "the `review finalize` dispatch no longer calls _cmd_review_finalize — "
        "the subcommand is wired to a handler that moved or disappeared"
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
