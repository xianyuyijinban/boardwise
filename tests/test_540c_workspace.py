"""540C: executable pins for the minimal Rust workspace and build dispatch docs."""

from __future__ import annotations

import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
RUST = ROOT / "rust"


def test_workspace_has_only_the_two_contract_crates_and_minimal_dependencies() -> None:
    workspace = tomllib.loads((RUST / "Cargo.toml").read_text(encoding="utf-8"))
    assert workspace["workspace"]["members"] == [
        "crates/boardwise-core", "crates/boardwise-cli",
    ]
    assert set(workspace["workspace"]["dependencies"]) == {
        "serde", "serde_json", "sha2", "regex",
    }
    for crate in ("boardwise-core", "boardwise-cli"):
        manifest = tomllib.loads(
            (RUST / "crates" / crate / "Cargo.toml").read_text(encoding="utf-8")
        )
        package = manifest["package"]
        assert package["name"] == crate
        assert package.get("edition") == "2024" or package.get("edition", {}).get("workspace") is True
    cli = (RUST / "crates" / "boardwise-cli" / "Cargo.toml").read_text(encoding="utf-8")
    core = (RUST / "crates" / "boardwise-core" / "Cargo.toml").read_text(encoding="utf-8")
    for forbidden in ("pyo3", "wasm", "node-addon", "napi"):
        assert forbidden not in (cli + core).lower()


def test_regex_serves_only_the_versioned_schema_pattern() -> None:
    """`regex` exists for one reason, and this pins that reason.

    The contract schemas express `pattern` in Python `re` (`re.search`), so the
    Rust side needs an engine with the same semantics for that keyword; a
    hand-rolled matcher would be a compatibility risk. The dependency is allowed
    — but only inside `schema.rs` (the 540C input validator), never in the CLI or
    in a business module.
    """
    users = sorted(
        path.relative_to(RUST).as_posix()
        for path in (RUST / "crates").rglob("*.rs")
        if "regex::" in path.read_text(encoding="utf-8")
    )
    assert users == ["crates/boardwise-core/src/schema.rs"], users
    schema = (
        RUST / "crates" / "boardwise-core" / "src" / "schema.rs"
    ).read_text(encoding="utf-8")
    # It names the authority it mirrors and the keyword it serves.
    assert "tools/contract_validate.py" in schema
    assert '"pattern"' in schema
    cli = tomllib.loads(
        (RUST / "crates" / "boardwise-cli" / "Cargo.toml").read_text(encoding="utf-8")
    )
    assert "regex" not in cli["dependencies"]


def test_lockfile_and_contract_inputs_exist_without_real_project_additions() -> None:
    assert (RUST / "Cargo.lock").is_file()
    book = json.loads((ROOT / "contracts" / "differential" / "cases.json").read_text(encoding="utf-8"))
    assert len(book["cases"]) == 5
    for case in book["cases"]:
        path = ROOT / case["input"]
        assert path.is_file()
        assert path.suffix == ".json"
        assert path.is_relative_to(ROOT / "contracts" / "differential" / "inputs")


def test_build_and_dispatch_docs_name_the_executable_commands_and_integration_lock() -> None:
    document = (ROOT / "docs" / "rust-platform.md").read_text(encoding="utf-8")
    for command in ("cargo fmt --check", "cargo clippy -- -D warnings", "cargo test"):
        assert command in document
    for token in (
        "tools.differential", "tools.differential_compare", "tools.build_differential_fixtures",
        "tasks/shared-platform.md", "tasks/review-line.md", "tasks/draw-line.md",
        "PyO3", "WASM", "Node native addon",
    ):
        assert token in document
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "cargo fmt --check" in agents
    assert "cargo clippy -- -D warnings" in agents
    assert "cargo test" in agents


def test_cargo_target_is_a_ignored_rebuild_artifact() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "rust/target/" in ignored


def test_contract_json_is_pinned_to_lf_in_git_attributes() -> None:
    """The manifest hashes golden bytes, so a checkout must not rewrite `\\n`."""
    rules = [
        line.strip()
        for line in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "/contracts/**/*.json text eol=lf" in rules
