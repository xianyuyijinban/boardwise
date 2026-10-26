//! CLI process contracts.
//!
//! `smoke` keeps its original shape: a refusal is the structured envelope, and
//! these tests pin that. `smoke` is **not** the differential compatibility
//! surface — the `differential_*` tests below (and
//! `tests/test_540c_cross_language.py`) cover the surface that mirrors
//! `tools.differential`: defaults, `--flag=value`, repeated flags, help, usage
//! text and the runner-error envelope.

use serde_json::{Value, json};
use std::fs;
use std::path::Path;
use std::process::{Command, Output};

fn run(arguments: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_boardwise-cli"))
        .args(arguments)
        .output()
        .expect("Rust CLI process runs")
}

fn run_in(directory: &Path, arguments: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_boardwise-cli"))
        .args(arguments)
        .current_dir(directory)
        .output()
        .expect("Rust CLI process runs")
}

fn stdout(output: &Output) -> Value {
    serde_json::from_slice(&output.stdout).expect("stdout is one JSON object")
}

fn stderr(output: &Output) -> Value {
    serde_json::from_slice(&output.stderr).expect("stderr is one JSON object")
}

fn repository_root() -> std::path::PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf()
}

/// A per-checkout directory cargo keeps for integration-test scratch files.
fn target_tmp() -> &'static Path {
    Path::new(env!("CARGO_TARGET_TMPDIR"))
}

fn write_json(path: &Path, value: &Value) {
    fs::write(
        path,
        serde_json::to_string_pretty(value).expect("test JSON serializes") + "\n",
    )
    .expect("test JSON is writable");
}

fn assert_cli_result(value: &Value) {
    assert_eq!(value["schema"], "boardwise.cli-result/1");
    assert_eq!(value["command"], "differential");
    assert_eq!(value["exitCode"], 2);
    assert_eq!(value["error"]["code"], "BAD_REQUEST");
    assert!(value.get("payload").is_none());
}

#[test]
fn smoke_success_has_structured_envelope_and_exit_zero() {
    let output = run(&["smoke", "--command", "contract-smoke"]);
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stderr.is_empty());
    let value = stdout(&output);
    assert_eq!(value["schema"], "boardwise.cli-result/1");
    assert_eq!(value["command"], "contract-smoke");
    assert_eq!(value["exitCode"], 0);
    assert_eq!(value["payload"]["businessLogic"], false);
    assert!(value.get("error").is_none());
}

#[test]
fn smoke_refusal_has_structured_error_and_exit_two() {
    let output = run(&["smoke", "--command", "contract-smoke", "--fail"]);
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    let value = stderr(&output);
    assert_eq!(value["schema"], "boardwise.cli-result/1");
    assert_eq!(value["command"], "contract-smoke");
    assert_eq!(value["exitCode"], 2);
    assert_eq!(value["error"]["code"], "BAD_REQUEST");
    assert_eq!(value["error"]["message"], "business-free smoke refusal");
    assert!(value.get("payload").is_none());
}

#[test]
fn invalid_arguments_have_the_same_error_shape() {
    let output = run(&[]);
    assert_eq!(output.status.code(), Some(2));
    let value = stderr(&output);
    assert_eq!(value["schema"], "boardwise.cli-result/1");
    assert_eq!(value["exitCode"], 2);
    assert_eq!(value["error"]["code"], "BAD_REQUEST");
    assert!(
        value["error"]["message"]
            .as_str()
            .unwrap()
            .contains("usage:")
    );
}

#[test]
fn differential_command_executes_the_repository_case_book() {
    let root = repository_root();
    let cases = root.join("contracts/differential/cases.json");
    let output = Command::new(env!("CARGO_BIN_EXE_boardwise-cli"))
        .arg("differential")
        .arg("--cases")
        .arg(&cases)
        .arg("--root")
        .arg(&root)
        .output()
        .expect("differential process runs");
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let value = stdout(&output);
    assert_eq!(value["schema"], "boardwise.differential-report/1");
    assert_eq!(value["runner"], "rust");
    assert_eq!(value["ok"], true);
    assert_eq!(value["cases"].as_array().unwrap().len(), 5);
}

#[test]
fn differential_without_flags_uses_the_repository_not_the_current_directory() {
    // The Python runner's defaults are its own repository, so running from an
    // unrelated directory must still find the case book.
    let elsewhere = std::env::temp_dir();
    let output = run_in(&elsewhere, &["differential"]);
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let value = stdout(&output);
    assert_eq!(value["schema"], "boardwise.differential-report/1");
    assert_eq!(value["ok"], true);
    assert_eq!(value["cases"].as_array().expect("cases").len(), 5);
}

#[test]
fn differential_help_is_plain_text_with_exit_zero() {
    for flag in ["-h", "--help"] {
        let output = run(&["differential", flag]);
        assert_eq!(output.status.code(), Some(0), "{flag}");
        assert!(output.stderr.is_empty(), "{flag}: stderr must stay empty");
        let text = String::from_utf8_lossy(&output.stdout);
        assert!(text.contains("usage:"), "{flag}: {text}");
        assert!(text.contains("--cases"));
        assert!(
            !text.trim_start().starts_with('{'),
            "help is text, not the structured envelope"
        );
    }
}

#[test]
fn differential_usage_errors_are_plain_text_with_exit_two() {
    for arguments in [
        vec!["differential", "--bogus"],
        vec!["differential", "--cases"],
        vec!["differential", "--root"],
        vec!["differential", "--output"],
    ] {
        let output = run(&arguments);
        assert_eq!(output.status.code(), Some(2), "{arguments:?}");
        assert!(output.stdout.is_empty(), "{arguments:?}");
        let text = String::from_utf8_lossy(&output.stderr);
        assert!(text.contains("usage:"), "{arguments:?}: {text}");
        assert!(
            !text.contains("boardwise.cli-result/1"),
            "{arguments:?}: a usage error is not the domain envelope"
        );
    }
}

#[test]
fn differential_accepts_equals_forms_last_repeated_value_and_output() {
    let root = repository_root();
    let cases = root.join("contracts/differential/cases.json");
    let missing = target_tmp().join("540c-absent-book.json");
    let report = target_tmp().join("540c-rust-differential.json");
    let output = Command::new(env!("CARGO_BIN_EXE_boardwise-cli"))
        .arg("differential")
        // A repeated flag takes its last value, like argparse: the first book
        // does not exist, the second does.
        .arg(format!("--cases={}", missing.display()))
        .arg(format!("--cases={}", cases.display()))
        .arg("--root")
        .arg("/definitely-not-a-repository")
        .arg(format!("--root={}", root.display()))
        .arg(format!("--output={}", report.display()))
        .output()
        .expect("differential process runs");
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stderr.is_empty());
    let value = stdout(&output);
    assert_eq!(value["ok"], true);
    let written = serde_json::from_str::<Value>(
        &fs::read_to_string(&report).expect("--output file was written"),
    )
    .expect("--output file is JSON");
    assert_eq!(written["schema"], "boardwise.differential-report/1");
    assert_eq!(written["ok"], true);
}

#[test]
fn differential_runner_failures_are_structured_envelopes() {
    let directory = target_tmp();
    let input = directory.join("540c-bad.layout.json");
    fs::write(&input, "{}\n").expect("bad input is writable");
    let schema_invalid = directory.join("540c-schema-invalid-cases.json");
    write_json(
        &schema_invalid,
        &json!({
            "schema": "boardwise.differential-cases/1",
            "cases": [{
                "id": "schema-invalid",
                "kind": "layout-plan-geometry",
                "input": "540c-bad.layout.json",
                "expected": {},
            }],
        }),
    );
    let unknown_kind = directory.join("540c-unknown-kind-cases.json");
    write_json(
        &unknown_kind,
        &json!({
            "schema": "boardwise.differential-cases/1",
            "cases": [{
                "id": "unknown-kind",
                "kind": "not-a-kind",
                "input": "540c-bad.layout.json",
                "expected": {},
            }],
        }),
    );
    for book in [&schema_invalid, &unknown_kind] {
        let output = Command::new(env!("CARGO_BIN_EXE_boardwise-cli"))
            .arg("differential")
            .arg("--cases")
            .arg(book)
            .arg("--root")
            .arg(directory)
            .output()
            .expect("differential process runs");
        assert_eq!(output.status.code(), Some(2), "{}", book.display());
        assert!(output.stdout.is_empty(), "a refusal states no report");
        assert_cli_result(&stderr(&output));
    }
}

#[test]
fn differential_output_parent_missing_is_a_structured_refusal() {
    let report = target_tmp()
        .join("540c-no-such-directory")
        .join("report.json");
    let output = Command::new(env!("CARGO_BIN_EXE_boardwise-cli"))
        .arg("differential")
        .arg("--output")
        .arg(&report)
        .output()
        .expect("differential process runs");
    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    assert_cli_result(&stderr(&output));
}

#[test]
fn differential_golden_mismatch_exits_one_with_the_report_on_stdout() {
    let book = target_tmp().join("540c-mismatch-cases.json");
    write_json(
        &book,
        &json!({
            "schema": "boardwise.differential-cases/1",
            "cases": [{
                "id": "mismatch",
                "kind": "layout-plan-geometry",
                "input": "contracts/differential/inputs/divider-cand1.layout.json",
                "expected": {"geometrySha256": "0".repeat(64)},
            }],
        }),
    );
    let output = Command::new(env!("CARGO_BIN_EXE_boardwise-cli"))
        .arg("differential")
        .arg("--cases")
        .arg(&book)
        .arg("--root")
        .arg(repository_root())
        .output()
        .expect("differential process runs");
    assert_eq!(output.status.code(), Some(1));
    assert!(
        output.stderr.is_empty(),
        "a differing golden is not a request failure"
    );
    let value = stdout(&output);
    assert_eq!(value["schema"], "boardwise.differential-report/1");
    assert_eq!(value["ok"], false);
    assert_eq!(value["cases"][0]["ok"], false);
}
