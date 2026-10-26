//! The preview-path contract and the strict book/input read, on the Rust side.
//!
//! The shapes that made the two runners disagree on a basename (the empty string,
//! a path ending in a separator, a path whose final segment is exactly `.` or
//! `..`) are refused by `contracts/json/draw-compile-result-v1.schema.json`
//! itself, and by the page contract, which states the same rule. Both sides
//! therefore reach the same verdict before any projection. The loops here run in
//! a plain `cargo test`; nothing is env-gated.

use boardwise_core::run_cases;
use boardwise_core::schema::{ensure_finite, validate_document};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};

fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf()
}

fn read_schema(name: &str) -> Value {
    let text = fs::read_to_string(repo_root().join("contracts/json").join(name))
        .unwrap_or_else(|error| panic!("{name} is readable: {error}"));
    serde_json::from_str(&text).unwrap_or_else(|error| panic!("{name} is JSON: {error}"))
}

fn module_payload(previews: Value) -> Value {
    json!({
        "command": "compile",
        "ok": true,
        "labelFallbacks": [],
        "candidates": [],
        "failures": [],
        "failureRounds": [],
        "categories": [],
        "rejected": [],
        "notes": [],
        "previews": previews,
    })
}

fn page_payload(previews: Value) -> Value {
    json!({
        "command": "compile",
        "document": "page",
        "ok": true,
        "pages": [],
        "failures": [],
        "categories": [],
        "rejected": [],
        "moduleFailureRounds": {},
        "notes": [],
        "previews": previews,
    })
}

/// The same previews judged by both compile contracts: a basename verdict is
/// only worth stating when the module and page documents agree on it.
fn both_compile_documents(previews: Value) -> [(&'static str, Value); 2] {
    [
        (
            "draw-compile-result-v1.schema.json",
            module_payload(previews.clone()),
        ),
        (
            "draw-page-compile-result-v1.schema.json",
            page_payload(previews),
        ),
    ]
}

#[test]
fn preview_paths_that_do_not_name_a_file_are_refused() {
    for bad in [
        "",
        ".",
        "..",
        "out/dir/",
        "out/dir\\",
        "/",
        "\\",
        "a/",
        "a\\",
        "cand1.svg/",
        // A final `.`/`..` segment: the two runners split these differently
        // (`Path("a/.").name` is "a", the rsplit basename is "."), so the
        // contract refuses the shape instead of picking a winner.
        "a/.",
        "./.",
        "a/./.",
        "../.",
        "a/..",
        "out/dir/..",
        "a\\..",
        "a\\.",
    ] {
        for (name, instance) in both_compile_documents(json!([bad])) {
            let schema = read_schema(name);
            assert!(
                validate_document(&instance, &schema).is_err(),
                "{name} accepted {bad:?}, which does not name a file"
            );
        }
    }
}

#[test]
fn preview_paths_that_name_a_file_are_accepted() {
    for good in [
        "cand1.svg",
        "out/dir/cand1.svg",
        "C:\\proj\\out\\cand1.svg",
        "/abs/cand1.svg",
        "..\\up\\c.svg",
        "C:/abs/x.svg",
        ".hidden",
        "a",
        // A middle `./` is ordinary path text, and a name that merely starts
        // with dots is a file both runners name the same way.
        "a/./b.svg",
        "..x",
        "...",
        ".a",
    ] {
        for (name, instance) in both_compile_documents(json!([good])) {
            let schema = read_schema(name);
            assert!(
                validate_document(&instance, &schema).is_ok(),
                "{name} refused {good:?}, which does name a file"
            );
        }
    }
}

#[test]
fn the_committed_golden_compile_results_still_validate() {
    for (schema_name, input_name, preview_count) in [
        (
            "draw-compile-result-v1.schema.json",
            "divider-compile-result.json",
            6,
        ),
        (
            "draw-page-compile-result-v1.schema.json",
            "page-compile-result.json",
            16,
        ),
    ] {
        let schema = read_schema(schema_name);
        let text = fs::read_to_string(
            repo_root()
                .join("contracts/differential/inputs")
                .join(input_name),
        )
        .unwrap_or_else(|error| panic!("{input_name} is readable: {error}"));
        let instance: Value = serde_json::from_str(&text).expect("the golden is JSON");
        validate_document(&instance, &schema).expect("the committed golden must stay valid");
        let previews = instance["previews"].as_array().expect("previews");
        assert_eq!(previews.len(), preview_count);
        for name in previews {
            let name = name.as_str().expect("a preview is a string");
            assert!(!name.is_empty() && name != "." && !name.ends_with(['/', '\\']));
        }
    }
}

#[test]
fn serde_overflow_is_not_a_finite_number() {
    let value: Value = serde_json::from_str("1e999").expect("serde keeps the literal");
    assert!(ensure_finite(&value).is_err());
    let value: Value = serde_json::from_str("1.5").expect("a normal number");
    assert!(ensure_finite(&value).is_ok());
}

fn target_tmp(name: &str) -> PathBuf {
    let dir = PathBuf::from(env!("CARGO_TARGET_TMPDIR"));
    fs::create_dir_all(&dir).expect("target tmp dir");
    dir.join(name)
}

#[test]
fn a_case_book_with_an_overflowing_number_is_refused() {
    let book = target_tmp("book-1e999.json");
    fs::write(
        &book,
        "{\"schema\":\"boardwise.differential-cases/1\",\"cases\":[],\"probe\":1e999}",
    )
    .expect("write the poisoned book");
    let error = run_cases(&book, &repo_root()).expect_err("1e999 in the book must be refused");
    assert!(
        error.to_string().contains("non-finite"),
        "the refusal must name the cause: {error}"
    );
}

#[test]
fn a_case_input_with_an_overflowing_number_is_refused() {
    // Two gates see this one — the strict read in `read_json` and, for an input, the
    // schema gate's own `ensure_finite` — and either refusing is the wanted answer.
    // The *book* case above is the one only `read_json` can catch.
    let input = target_tmp("input-1e999.json");
    fs::write(&input, "{\"probe\": 1e999}").expect("write the poisoned input");
    let case = json!({
        "id": "overflow",
        "kind": "review-report-projection",
        "input": input.to_string_lossy(),
        "expected": {},
    });
    let book = target_tmp("book-input-1e999.json");
    fs::write(
        &book,
        serde_json::to_string(&json!({
            "schema": "boardwise.differential-cases/1",
            "cases": [case],
        }))
        .expect("serialize the book"),
    )
    .expect("write the book");
    let error = run_cases(&book, &repo_root()).expect_err("1e999 in an input must be refused");
    assert!(
        error.to_string().contains("non-finite"),
        "the refusal must name the cause: {error}"
    );
}
