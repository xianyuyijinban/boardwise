//! #87④: the Rust schema reader accepts the same additive identity contract.

use boardwise_core::schema::validate_document;
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf()
}

fn load(path: PathBuf) -> Value {
    serde_json::from_str(&fs::read_to_string(path).expect("JSON is readable")).expect("JSON parses")
}

fn measurement() -> Value {
    json!({
        "kind": "clearance", "value": 1.0, "unit": "mil",
        "element_a": "old label A", "element_b": "old label B",
        "component_a": "U1", "component_b": "", "within_one_footprint": false,
        "element_a_detail": {"kind": "pad", "component": "U1", "pin": "2", "layers": [1, 2]},
        "element_b_detail": {"kind": "track", "component": "", "pin": "", "layers": [1]},
        "shared_layer_ids": [1]
    })
}

#[test]
fn additive_identity_and_old_reports_follow_the_python_contract() {
    let base = root();
    let schema = load(base.join("contracts/json/review-report-v1.schema.json"));
    let old = load(base.join("contracts/differential/inputs/review-report.json"));
    assert_eq!(
        schema["properties"]["schema"]["const"],
        "boardwise.checkup/7"
    );
    assert!(validate_document(&old, &schema).is_ok());

    let mut report = old.clone();
    report["findings"][0]["target"]["measurement"] = measurement();
    assert!(validate_document(&report, &schema).is_ok());

    for key in ["element_a_detail", "element_b_detail", "shared_layer_ids"] {
        report["findings"][0]["target"]["measurement"]
            .as_object_mut()
            .unwrap()
            .remove(key);
        assert!(validate_document(&report, &schema).is_ok());
    }
}

#[test]
fn partial_identity_and_layer_sentinel_are_rejected() {
    let base = root();
    let schema = load(base.join("contracts/json/review-report-v1.schema.json"));
    let mut report = load(base.join("contracts/differential/inputs/review-report.json"));
    report["findings"][0]["target"]["measurement"] = measurement();
    report["findings"][0]["target"]["measurement"]["element_a_detail"]
        .as_object_mut()
        .unwrap()
        .remove("pin");
    assert!(validate_document(&report, &schema).is_err());
    let detail = report["findings"][0]["target"]["measurement"]["element_a_detail"]
        .as_object_mut()
        .unwrap();
    detail.insert("pin".to_owned(), json!("2"));
    detail.insert("layers".to_owned(), json!([-1]));
    assert!(validate_document(&report, &schema).is_err());
}
