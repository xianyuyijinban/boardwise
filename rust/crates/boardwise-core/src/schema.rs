//! Rust port of `tools/contract_validate.py` — the JSON Schema 2020-12 subset the
//! 540C contracts declare.
//!
//! The Python module is the authority; this file mirrors it rather than
//! re-inventing it. Three decisions follow from that:
//!
//! * **The whole schema tree is pre-checked** (`check_schema`), including
//!   `$defs` and `properties` the instance never reaches, so an unsupported
//!   keyword, an unknown `type` name or a circular `$ref` cannot hide in an
//!   unused branch. `$ref` chains are followed without an instance and a cycle
//!   is refused instead of validating nothing; `$ref` is an applicator, so the
//!   sibling keywords still apply.
//! * **Numbers are compared exactly.** JSON has one number type, so `1` and
//!   `1.0` are equal while `true` is never `1`; an integer is compared through
//!   its decimal digits and an integer against a float through the float's exact
//!   decimal expansion (`crate::exact_decimal`), never through a lossy `f64`
//!   cast. `integer` accepts any finite number with a zero fractional part, so
//!   `1.0` is an integer.
//! * **Non-finite numbers are refused** (`ensure_finite`): `NaN`/`Infinity`
//!   tokens are already not JSON to serde, and a literal that overflows to
//!   infinity (`1e999`) is refused the way Python's strict loader refuses it.
//!
//! Two dialect notes, both from the schema-level `pattern` keyword:
//!
//! * Rust's `regex` crate is the engine. It has no backreferences or lookaround,
//!   so a pattern Python accepts but `regex` refuses is a schema error here
//!   (stricter, never looser).
//! * Python's `$` also matches immediately before a newline at the end of the
//!   string; the `regex` crate's `$` is end-of-haystack only. `pattern_matches`
//!   re-tries without that final newline, which is the same decision whenever
//!   `$` is the pattern's terminal assertion. A pattern that *consumes* a
//!   newline after a mid-pattern `$` re-tried that way would be refused here
//!   while Python accepts; no contract schema does that.

use crate::{ContractError, Result, exact_decimal};
use regex::Regex;
use serde_json::{Map, Value};
use std::cmp::Ordering;
use std::path::{Path, PathBuf};

/// Documentation keys the Python subset accepts without applying them.
const META_KEYWORDS: [&str; 5] = ["$schema", "$id", "title", "description", "$defs"];

/// The implemented keyword set; anything else fails loudly.
const SUPPORTED_KEYWORDS: [&str; 14] = [
    "$ref",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "items",
    "prefixItems",
    "enum",
    "const",
    "pattern",
    "minItems",
    "maxItems",
    "minLength",
    "minimum",
];

/// The type vocabulary of the declared subset.
const TYPE_NAMES: [&str; 7] = [
    "array", "boolean", "integer", "null", "number", "object", "string",
];

/// `kind` → schema file, the same table as `tools/differential.py:SCHEMAS`.
const SCHEMAS: [(&str, &str); 5] = [
    ("review-report-projection", "review-report-v1.schema.json"),
    ("layout-plan-geometry", "layout-plan-v1.schema.json"),
    (
        "compile-result-projection",
        "draw-compile-result-v1.schema.json",
    ),
    // The page shape is a separate contract on purpose: `pages` and `document`
    // replace `candidates`, and the subset has no `oneOf` to state both at once.
    (
        "compile-page-result-projection",
        "draw-page-compile-result-v1.schema.json",
    ),
    ("lint-result-projection", "draw-lint-result-v1.schema.json"),
];

fn validation_error(message: impl Into<String>) -> ContractError {
    ContractError::Shape(message.into())
}

fn invalid(path: &str, detail: impl std::fmt::Display) -> ContractError {
    validation_error(format!("invalid schema at {path}: {detail}"))
}

/// Validate one differential case input against the schema its kind names.
pub(crate) fn validate_for_kind(instance: &Value, kind: &str) -> Result<()> {
    let file = schema_file(kind)?;
    let schema = crate::read_json(&schema_directory().join(file))?;
    validate_document(instance, &schema)
}

fn schema_file(kind: &str) -> Result<&'static str> {
    SCHEMAS
        .iter()
        .find(|(name, _)| *name == kind)
        .map(|(_, file)| *file)
        .ok_or_else(|| ContractError::Shape(format!("unknown differential case kind {kind:?}")))
}

/// Where the Python runner reads schemas from: next to the code, never under the
/// `--root` case directory (`tools/differential.py` uses its own
/// `ROOT / "contracts" / "json"`, so a case book rooted in a temp directory still
/// validates against the repository's contracts).
fn schema_directory() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .join("contracts")
        .join("json")
}

// ------------------------------------------------------------- JSON numbers

fn is_float_syntax(text: &str) -> bool {
    text.bytes()
        .any(|byte| byte == b'.' || byte == b'e' || byte == b'E')
}

fn number_text(number: &serde_json::Number) -> String {
    // `arbitrary_precision` keeps the literal, which is what Python's parser
    // turns into an exact int or a correctly-rounded float.
    number.to_string()
}

fn finite_f64(number: &serde_json::Number) -> Option<f64> {
    number_text(number)
        .parse::<f64>()
        .ok()
        .filter(|value| value.is_finite())
}

/// A JSON number: never a boolean, never a non-finite float.
fn is_number(value: &Value) -> bool {
    match value {
        Value::Number(number) => {
            let text = number_text(number);
            !is_float_syntax(&text) || finite_f64(number).is_some()
        }
        _ => false,
    }
}

/// 2020-12 `integer`: a finite number with a zero fractional part.
fn is_integer(value: &Value) -> bool {
    match value {
        Value::Number(number) => {
            let text = number_text(number);
            if is_float_syntax(&text) {
                finite_f64(number).is_some_and(|value| value.fract() == 0.0)
            } else {
                // An integer literal is an integer however many digits it has.
                true
            }
        }
        _ => false,
    }
}

/// `(negative, magnitude digits)` for an integer literal; `None` for a float.
fn integer_digits(number: &serde_json::Number) -> Option<(bool, String)> {
    let text = number_text(number);
    if is_float_syntax(&text) {
        return None;
    }
    let magnitude = text
        .trim_start_matches('-')
        .trim_start_matches('0')
        .to_owned();
    let magnitude = if magnitude.is_empty() {
        "0".to_owned()
    } else {
        magnitude
    };
    Some((text.starts_with('-') && magnitude != "0", magnitude))
}

fn compare_magnitudes(left: &str, right: &str) -> Ordering {
    left.len().cmp(&right.len()).then_with(|| left.cmp(right))
}

fn compare_decimal_integers(
    left_negative: bool,
    left: &str,
    right_negative: bool,
    right: &str,
) -> Ordering {
    match (left_negative, right_negative) {
        (true, false) => Ordering::Less,
        (false, true) => Ordering::Greater,
        (false, false) => compare_magnitudes(left, right),
        (true, true) => compare_magnitudes(left, right).reverse(),
    }
}

/// Compare a non-zero integer magnitude with a positive finite float, exactly.
fn compare_magnitude_to_float(digits: &str, magnitude: f64) -> Ordering {
    let (float_digits, decpt) = exact_decimal(magnitude);
    let mut integer_part: Vec<u8> = Vec::new();
    if decpt > 0 {
        let width = decpt as usize;
        integer_part.extend_from_slice(&float_digits[..width.min(float_digits.len())]);
        integer_part.resize(width, 0);
    }
    let fraction_nonzero = if decpt <= 0 {
        float_digits.iter().any(|digit| *digit != 0)
    } else {
        float_digits
            .iter()
            .skip(decpt as usize)
            .any(|digit| *digit != 0)
    };
    let float_integer: String = integer_part
        .iter()
        .map(|digit| char::from(b'0' + digit))
        .collect();
    let float_integer = float_integer.trim_start_matches('0');
    match compare_magnitudes(digits, float_integer) {
        Ordering::Equal if fraction_nonzero => Ordering::Less,
        ordering => ordering,
    }
}

fn compare_integer_to_float(negative: bool, digits: &str, float: f64) -> Ordering {
    debug_assert!(float.is_finite());
    let integer_zero = digits == "0";
    if float == 0.0 {
        return if integer_zero {
            Ordering::Equal
        } else if negative {
            Ordering::Less
        } else {
            Ordering::Greater
        };
    }
    if integer_zero {
        return if float > 0.0 {
            Ordering::Less
        } else {
            Ordering::Greater
        };
    }
    let float_negative = float < 0.0;
    if negative != float_negative {
        return if negative {
            Ordering::Less
        } else {
            Ordering::Greater
        };
    }
    let magnitude = compare_magnitude_to_float(digits, float.abs());
    if negative {
        magnitude.reverse()
    } else {
        magnitude
    }
}

/// Exact ordering of two JSON numbers (`None` when either is not a number).
fn compare_numbers(left: &Value, right: &Value) -> Option<Ordering> {
    let (Value::Number(left), Value::Number(right)) = (left, right) else {
        return None;
    };
    match (integer_digits(left), integer_digits(right)) {
        (Some((left_negative, left)), Some((right_negative, right))) => Some(
            compare_decimal_integers(left_negative, &left, right_negative, &right),
        ),
        (Some((negative, digits)), None) => {
            let float = finite_f64(right)?;
            Some(compare_integer_to_float(negative, &digits, float))
        }
        (None, Some((negative, digits))) => {
            let float = finite_f64(left)?;
            Some(compare_integer_to_float(negative, &digits, float).reverse())
        }
        (None, None) => finite_f64(left)?.partial_cmp(&finite_f64(right)?),
    }
}

/// JSON value equality, recursive, with `true` and `1` kept apart.
fn json_equal(left: &Value, right: &Value) -> bool {
    match (left, right) {
        (Value::Bool(left), Value::Bool(right)) => left == right,
        (Value::Bool(_), _) | (_, Value::Bool(_)) => false,
        (Value::Number(_), Value::Number(_)) => {
            compare_numbers(left, right) == Some(Ordering::Equal)
        }
        (Value::Array(left), Value::Array(right)) => {
            left.len() == right.len()
                && left
                    .iter()
                    .zip(right)
                    .all(|(left, right)| json_equal(left, right))
        }
        (Value::Object(left), Value::Object(right)) => {
            left.len() == right.len()
                && left.iter().all(|(key, value)| {
                    right.get(key).is_some_and(|other| json_equal(value, other))
                })
        }
        _ => left == right,
    }
}

fn instance_type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(number) => {
            if is_float_syntax(&number_text(number)) {
                "float"
            } else {
                "int"
            }
        }
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

fn type_matches(value: &Value, name: &str) -> Result<bool> {
    Ok(match name {
        "object" => value.is_object(),
        "array" => value.is_array(),
        "string" => value.is_string(),
        "boolean" => value.is_boolean(),
        "integer" => is_integer(value),
        "number" => is_number(value),
        "null" => value.is_null(),
        other => {
            return Err(validation_error(format!(
                "unsupported JSON Schema type: {other:?}"
            )));
        }
    })
}

// ------------------------------------------------------------ strict loading

/// Refuse `NaN`/`Infinity` anywhere in an already-parsed JSON value.
///
/// serde cannot read bare `NaN`/`Infinity` tokens at all, so this is about
/// literals that overflow to infinity (`1e999`), which Python's strict loader
/// rejects the same way. An integer literal never overflows: it is exact.
pub fn ensure_finite(value: &Value) -> Result<()> {
    match value {
        Value::Number(number) => {
            let text = number_text(number);
            if is_float_syntax(&text) && finite_f64(number).is_none() {
                return Err(validation_error(format!(
                    "non-finite JSON number {text} is rejected: JSON numbers are finite"
                )));
            }
            Ok(())
        }
        Value::Array(items) => items.iter().try_for_each(ensure_finite),
        Value::Object(fields) => fields.values().try_for_each(ensure_finite),
        _ => Ok(()),
    }
}

// ------------------------------------------------------- pattern (`re.search`)

/// Does `text` match `pattern` the way Python's `re.search` decides it?
fn pattern_matches(pattern: &str, text: &str) -> bool {
    let Ok(regex) = Regex::new(pattern) else {
        // `check_schema` refuses an uncompilable pattern before an instance is
        // validated; reaching here means the pre-check was skipped, so refuse
        // rather than accept.
        return false;
    };
    if regex.is_match(text) {
        return true;
    }
    // Python's `$` also matches immediately before a newline at the end of the
    // string; the regex crate's `$` is end-of-haystack only.
    text.strip_suffix('\n')
        .is_some_and(|without_newline| regex.is_match(without_newline))
}

// -------------------------------------------------------------- schema check

/// Pre-check an entire schema tree (`validate` does this before any instance).
pub fn check_schema(schema: &Value) -> Result<()> {
    check_node(schema, schema, "$")
}

fn check_node(schema: &Value, root: &Value, path: &str) -> Result<()> {
    if schema.is_boolean() {
        return Ok(());
    }
    let Some(object) = schema.as_object() else {
        return Err(invalid(path, "a schema must be an object or a boolean"));
    };
    let mut unsupported: Vec<&str> = object
        .keys()
        .map(String::as_str)
        .filter(|key| {
            !SUPPORTED_KEYWORDS.contains(key)
                && !META_KEYWORDS.contains(key)
                && !key.starts_with("x-")
        })
        .collect();
    if !unsupported.is_empty() {
        unsupported.sort_unstable();
        return Err(validation_error(format!(
            "unsupported schema keyword(s) at {path}: {unsupported:?}"
        )));
    }
    check_structure(object, path)?;
    if let Some(reference) = object.get("$ref") {
        check_reference_chain(reference, root, path)?;
    }
    for (name, child) in child_schemas(object) {
        check_node(child, root, &format!("{path}/{name}"))?;
    }
    Ok(())
}

/// Every position in this node that holds a subschema (never `enum` data).
fn child_schemas(object: &Map<String, Value>) -> Vec<(String, &Value)> {
    let mut children = Vec::new();
    for name in ["$defs", "properties"] {
        if let Some(Value::Object(mapping)) = object.get(name) {
            for (key, child) in mapping {
                children.push((format!("{name}/{key}"), child));
            }
        }
    }
    for name in ["additionalProperties", "items"] {
        if let Some(child) = object.get(name) {
            children.push((name.to_owned(), child));
        }
    }
    if let Some(Value::Array(prefix)) = object.get("prefixItems") {
        for (index, child) in prefix.iter().enumerate() {
            children.push((format!("prefixItems/{index}"), child));
        }
    }
    children
}

fn check_structure(object: &Map<String, Value>, path: &str) -> Result<()> {
    for name in ["$defs", "properties"] {
        if let Some(value) = object.get(name)
            && !value.is_object()
        {
            return Err(invalid(
                path,
                format!(
                    "{name} must be an object, got {}",
                    instance_type_name(value)
                ),
            ));
        }
    }
    for name in ["additionalProperties", "items"] {
        if let Some(value) = object.get(name)
            && !value.is_object()
            && !value.is_boolean()
        {
            return Err(invalid(
                path,
                format!(
                    "{name} must be a schema object or a boolean, got {}",
                    instance_type_name(value)
                ),
            ));
        }
    }
    if let Some(value) = object.get("prefixItems")
        && !value.is_array()
    {
        return Err(invalid(path, "prefixItems must be an array of schemas"));
    }
    if let Some(expected) = object.get("type") {
        let names: Vec<&str> = match expected {
            Value::String(name) => vec![name.as_str()],
            Value::Array(items) if !items.is_empty() && items.iter().all(Value::is_string) => {
                items.iter().filter_map(Value::as_str).collect()
            }
            _ => {
                return Err(invalid(
                    path,
                    format!(
                        "type must be a string or a non-empty array of strings, got {expected}"
                    ),
                ));
            }
        };
        let mut unknown: Vec<&str> = names
            .iter()
            .copied()
            .filter(|name| !TYPE_NAMES.contains(name))
            .collect();
        unknown.sort_unstable();
        unknown.dedup();
        if !unknown.is_empty() {
            return Err(invalid(
                path,
                format!(
                    "unsupported JSON Schema type(s) {unknown:?}; the subset implements {TYPE_NAMES:?}"
                ),
            ));
        }
    }
    if let Some(required) = object.get("required") {
        let is_string_list = required
            .as_array()
            .is_some_and(|items| items.iter().all(Value::is_string));
        if !is_string_list {
            return Err(invalid(path, "required must be an array of strings"));
        }
    }
    if let Some(enumeration) = object.get("enum")
        && !enumeration.is_array()
    {
        return Err(invalid(path, "enum must be an array"));
    }
    if let Some(pattern) = object.get("pattern") {
        let Some(text) = pattern.as_str() else {
            return Err(invalid(path, "pattern must be a string"));
        };
        Regex::new(text).map_err(|error| {
            invalid(
                path,
                format!("pattern is not a regular expression: {error}"),
            )
        })?;
    }
    let zero = Value::from(0);
    for name in ["minItems", "maxItems", "minLength"] {
        if let Some(value) = object.get(name) {
            let negative = compare_numbers(value, &zero) == Some(Ordering::Less);
            if !is_integer(value) || negative {
                return Err(invalid(
                    path,
                    format!("{name} must be a non-negative integer, got {value}"),
                ));
            }
        }
    }
    if let Some(value) = object.get("minimum")
        && !is_number(value)
    {
        return Err(invalid(
            path,
            format!("minimum must be a finite number, got {value}"),
        ));
    }
    Ok(())
}

fn check_reference_chain(reference: &Value, root: &Value, path: &str) -> Result<()> {
    let mut chain: Vec<String> = Vec::new();
    let mut current = reference.clone();
    loop {
        let Some(text) = current.as_str() else {
            return Err(invalid(
                path,
                format!("$ref must be a string, got {current}"),
            ));
        };
        if chain.iter().any(|seen| seen == text) {
            return Err(circular_error(text, &chain, path));
        }
        chain.push(text.to_owned());
        let target = lookup_ref(text, root)?;
        if target.is_boolean() || target.get("$ref").is_none() {
            return Ok(());
        }
        current = target["$ref"].clone();
    }
}

fn lookup_ref<'a>(reference: &str, root: &'a Value) -> Result<&'a Value> {
    if reference == "#" {
        return Ok(root);
    }
    let Some(rest) = reference.strip_prefix("#/") else {
        return Err(validation_error(format!(
            "only local $ref is supported: {reference:?}"
        )));
    };
    let mut target = root;
    for token in rest.split('/') {
        let token = token.replace("~1", "/").replace("~0", "~");
        let Some(object) = target.as_object() else {
            return Err(validation_error(format!(
                "unresolvable $ref: {reference:?}"
            )));
        };
        let Some(found) = object.get(&token) else {
            return Err(validation_error(format!(
                "unresolvable $ref: {reference:?}"
            )));
        };
        target = found;
    }
    if target.is_object() || target.is_boolean() {
        Ok(target)
    } else {
        Err(validation_error(format!(
            "$ref does not name a schema: {reference:?}"
        )))
    }
}

fn circular_error(reference: &str, chain: &[String], path: &str) -> ContractError {
    let start = chain.iter().position(|seen| seen == reference).unwrap_or(0);
    let mut cycle: Vec<&str> = chain[start..].iter().map(String::as_str).collect();
    cycle.push(reference);
    validation_error(format!(
        "circular $ref at {path}: {}; a self-referential $ref would validate nothing, \
         so it is refused rather than passed",
        cycle.join(" -> ")
    ))
}

// -------------------------------------------------------------- validation

/// Validate one instance against a schema, pre-checking the whole tree first.
pub fn validate_document(instance: &Value, schema: &Value) -> Result<()> {
    ensure_finite(instance)?;
    ensure_finite(schema)?;
    check_schema(schema)?;
    let errors = validate_node(instance, schema, "$", schema, &[])?;
    if errors.is_empty() {
        Ok(())
    } else {
        Err(validation_error(errors.join("\n")))
    }
}

fn non_negative_count(value: &Value) -> Option<u64> {
    let Value::Number(number) = value else {
        return None;
    };
    let text = number_text(number);
    if !is_float_syntax(&text) {
        return text.parse::<u64>().ok();
    }
    let float = finite_f64(number)?;
    (float.fract() == 0.0 && float >= 0.0 && float <= u64::MAX as f64).then_some(float as u64)
}

fn validate_node(
    instance: &Value,
    schema: &Value,
    path: &str,
    root: &Value,
    ref_chain: &[String],
) -> Result<Vec<String>> {
    if let Value::Bool(accepting) = schema {
        return Ok(if *accepting {
            Vec::new()
        } else {
            vec![format!(
                "{path}: rejected by a false schema: no value is allowed here"
            )]
        });
    }
    let Some(object) = schema.as_object() else {
        return Err(invalid(path, "a schema must be an object or a boolean"));
    };

    if let Some(reference) = object.get("$ref") {
        let Some(text) = reference.as_str() else {
            return Err(invalid(path, "$ref must be a string"));
        };
        if ref_chain.iter().any(|seen| seen == text) {
            return Err(circular_error(text, ref_chain, path));
        }
        let mut next: Vec<String> = ref_chain.to_vec();
        next.push(text.to_owned());
        let mut errors = validate_node(instance, lookup_ref(text, root)?, path, root, &next)?;
        // 2020-12: `$ref` is an applicator, not a replacement.
        let siblings: Map<String, Value> = object
            .iter()
            .filter(|(key, _)| key.as_str() != "$ref")
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect();
        if !siblings.is_empty() {
            errors.extend(validate_node(
                instance,
                &Value::Object(siblings),
                path,
                root,
                ref_chain,
            )?);
        }
        return Ok(errors);
    }

    let mut errors: Vec<String> = Vec::new();
    if let Some(expected) = object.get("type") {
        let names: Vec<&str> = match expected {
            Value::String(name) => vec![name.as_str()],
            Value::Array(items) => items.iter().filter_map(Value::as_str).collect(),
            _ => Vec::new(),
        };
        let mut matched = false;
        for name in &names {
            if type_matches(instance, name)? {
                matched = true;
                break;
            }
        }
        if !matched {
            return Ok(vec![format!(
                "{path}: expected {expected}, got {}",
                instance_type_name(instance)
            )]);
        }
    }
    if let Some(constant) = object.get("const")
        && !json_equal(instance, constant)
    {
        errors.push(format!("{path}: expected const {constant}, got {instance}"));
    }
    if let Some(Value::Array(enumeration)) = object.get("enum")
        && !enumeration
            .iter()
            .any(|candidate| json_equal(instance, candidate))
    {
        errors.push(format!("{path}: {instance} is not in enum {enumeration:?}"));
    }
    if let Some(text) = instance.as_str() {
        if let Some(Value::String(pattern)) = object.get("pattern")
            && !pattern_matches(pattern, text)
        {
            errors.push(format!("{path}: {text:?} does not match {pattern:?}"));
        }
        if let Some(limit) = object.get("minLength").and_then(non_negative_count)
            && (text.chars().count() as u64) < limit
        {
            errors.push(format!("{path}: shorter than minLength {limit}"));
        }
    }
    if is_number(instance)
        && let Some(minimum) = object.get("minimum")
        && compare_numbers(instance, minimum) == Some(Ordering::Less)
    {
        errors.push(format!("{path}: {instance} is below minimum {minimum}"));
    }
    if let Some(items) = instance.as_array() {
        if let Some(limit) = object.get("minItems").and_then(non_negative_count)
            && (items.len() as u64) < limit
        {
            errors.push(format!("{path}: expected at least {limit} items"));
        }
        if let Some(limit) = object.get("maxItems").and_then(non_negative_count)
            && (items.len() as u64) > limit
        {
            errors.push(format!("{path}: expected at most {limit} items"));
        }
        let empty: Vec<Value> = Vec::new();
        let prefix = object
            .get("prefixItems")
            .and_then(Value::as_array)
            .unwrap_or(&empty);
        for (index, subschema) in prefix.iter().enumerate() {
            if let Some(item) = items.get(index) {
                errors.extend(validate_node(
                    item,
                    subschema,
                    &format!("{path}[{index}]"),
                    root,
                    &[],
                )?);
            }
        }
        if let Some(tail) = object.get("items") {
            // 2020-12: `items` applies only to the tail after `prefixItems`.
            for (index, item) in items.iter().enumerate().skip(prefix.len()) {
                errors.extend(validate_node(
                    item,
                    tail,
                    &format!("{path}[{index}]"),
                    root,
                    &[],
                )?);
            }
        }
    }
    if let Some(fields) = instance.as_object() {
        if let Some(required) = object.get("required").and_then(Value::as_array) {
            for key in required.iter().filter_map(Value::as_str) {
                if !fields.contains_key(key) {
                    errors.push(format!("{path}: required key {key:?} is missing"));
                }
            }
        }
        let properties = object.get("properties").and_then(Value::as_object);
        if let Some(properties) = properties {
            for (key, subschema) in properties {
                if let Some(value) = fields.get(key) {
                    errors.extend(validate_node(
                        value,
                        subschema,
                        &format!("{path}.{key}"),
                        root,
                        &[],
                    )?);
                }
            }
        }
        let additional = object
            .get("additionalProperties")
            .cloned()
            .unwrap_or(Value::Bool(true));
        if additional != Value::Bool(true) {
            let mut extra: Vec<&String> = fields
                .keys()
                .filter(|key| !properties.is_some_and(|properties| properties.contains_key(*key)))
                .collect();
            extra.sort();
            if additional == Value::Bool(false) {
                for key in extra {
                    errors.push(format!(
                        "{path}: additional property {key:?} is not allowed"
                    ));
                }
            } else {
                for key in extra {
                    if let Some(value) = fields.get(key) {
                        errors.extend(validate_node(
                            value,
                            &additional,
                            &format!("{path}.{key}"),
                            root,
                            &[],
                        )?);
                    }
                }
            }
        }
    }
    Ok(errors)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn repository_root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .ancestors()
            .nth(3)
            .expect("repository root")
            .to_path_buf()
    }

    fn contract_file(directory: &str, name: &str) -> Value {
        crate::read_json(&repository_root().join(directory).join(name))
            .unwrap_or_else(|error| panic!("{name}: {error}"))
    }

    fn input(name: &str) -> Value {
        contract_file("contracts/differential/inputs", name)
    }

    fn parse_json(text: &str) -> Value {
        serde_json::from_str(text).expect("test literal is JSON")
    }

    #[test]
    fn every_contract_schema_is_in_the_supported_subset() {
        for name in [
            "bridge-error-v1.schema.json",
            "draw-compile-result-v1.schema.json",
            "draw-lint-result-v1.schema.json",
            "draw-page-compile-result-v1.schema.json",
            "layout-plan-v1.schema.json",
            "review-report-v1.schema.json",
        ] {
            let schema = contract_file("contracts/json", name);
            check_schema(&schema).unwrap_or_else(|error| panic!("{name}: {error}"));
        }
    }

    #[test]
    fn repository_differential_inputs_validate() {
        let pairs = [
            ("review-report.json", "review-report-v1.schema.json"),
            ("divider-cand1.layout.json", "layout-plan-v1.schema.json"),
            (
                "divider-compile-result.json",
                "draw-compile-result-v1.schema.json",
            ),
            (
                "page-compile-result.json",
                "draw-page-compile-result-v1.schema.json",
            ),
            (
                "empty-page-lint-result.json",
                "draw-lint-result-v1.schema.json",
            ),
        ];
        for (input_name, schema_name) in pairs {
            let schema = contract_file("contracts/json", schema_name);
            validate_document(&input(input_name), &schema)
                .unwrap_or_else(|error| panic!("{input_name} against {schema_name}: {error}"));
        }
        // The kind → schema table the differential runner uses.
        for (input_name, kind) in [
            ("review-report.json", "review-report-projection"),
            ("divider-cand1.layout.json", "layout-plan-geometry"),
            ("divider-compile-result.json", "compile-result-projection"),
            ("page-compile-result.json", "compile-page-result-projection"),
            ("empty-page-lint-result.json", "lint-result-projection"),
        ] {
            validate_for_kind(&input(input_name), kind)
                .unwrap_or_else(|error| panic!("{input_name} as {kind}: {error}"));
        }
        let unknown = validate_for_kind(&json!({}), "no-such-kind").expect_err("unknown kind");
        assert!(
            unknown
                .to_string()
                .contains("unknown differential case kind")
        );
    }

    /// `pages` and `candidates` are two documents, not one renamed field: each
    /// input is refused by the other's schema, and by the other's kind.
    #[test]
    fn page_and_module_compile_documents_cannot_trade_schemas() {
        let module_schema = contract_file("contracts/json", "draw-compile-result-v1.schema.json");
        let page_schema =
            contract_file("contracts/json", "draw-page-compile-result-v1.schema.json");
        let module_input = input("divider-compile-result.json");
        let page_input = input("page-compile-result.json");

        validate_document(&page_input, &module_schema)
            .expect_err("a page document states no candidates/failureRounds");
        validate_document(&module_input, &page_schema)
            .expect_err("a module document states no pages/document");

        validate_for_kind(&page_input, "compile-result-projection")
            .expect_err("the module kind must not accept a page document");
        validate_for_kind(&module_input, "compile-page-result-projection")
            .expect_err("the page kind must not accept a module document");

        // Each document is still valid against its own contract, so the two
        // refusals above are the shape and not a broken fixture.
        validate_for_kind(&module_input, "compile-result-projection").expect("module document");
        validate_for_kind(&page_input, "compile-page-result-projection").expect("page document");
    }

    #[test]
    fn layout_plan_input_is_refused_when_the_schema_is_violated() {
        let schema = contract_file("contracts/json", "layout-plan-v1.schema.json");
        let golden = input("divider-cand1.layout.json");

        let mut extra = golden.clone();
        extra["parts"][0]["unexpected"] = json!(1);
        assert!(validate_document(&extra, &schema).is_err(), "closed object");

        let mut rotation = golden.clone();
        rotation["parts"][0]["rotation"] = json!(45);
        assert!(
            validate_document(&rotation, &schema).is_err(),
            "rotation is an enum"
        );

        let mut missing = golden.clone();
        missing["parts"][0]
            .as_object_mut()
            .expect("part")
            .remove("reference");
        assert!(
            validate_document(&missing, &schema).is_err(),
            "required key"
        );

        let mut point = golden.clone();
        point["segments"][0]["points"][0] = json!([1, 2, 3]);
        assert!(
            validate_document(&point, &schema).is_err(),
            "maxItems 2 on a point"
        );

        let mut padded = golden.clone();
        padded["source"]["circuitSha256"] = json!(format!(" {} ", "a".repeat(64)));
        assert!(validate_document(&padded, &schema).is_err(), "pattern");

        // The golden input itself is valid, so nothing above leaked into it.
        validate_document(&golden, &schema).expect("golden layout input is schema-valid");
    }

    #[test]
    fn unknown_keyword_is_refused_even_in_an_unreached_branch() {
        let schema = json!({
            "type": "object",
            "properties": {"used": {"type": "string"}},
            "additionalProperties": true,
            "$defs": {"never": {"type": "string", "oneOf": [{"type": "string"}]}},
        });
        let error = check_schema(&schema).expect_err("an unreached oneOf is unsupported");
        assert!(error.to_string().contains("unsupported schema keyword"));
        // validate_document pre-checks the tree before it looks at the instance.
        assert!(validate_document(&json!({"used": "x"}), &schema).is_err());
    }

    #[test]
    fn unknown_type_is_refused_before_a_matching_branch() {
        let union = json!({"type": ["string", "banana"]});
        assert!(check_schema(&union).is_err(), "unknown name in a union");
        assert!(
            validate_document(&json!("x"), &union).is_err(),
            "the earlier matching name must not hide the unknown one"
        );
        assert!(check_schema(&json!({"type": []})).is_err());
        assert!(check_schema(&json!({"type": "str"})).is_err());
    }

    #[test]
    fn refs_chain_keep_siblings_and_refuse_cycles() {
        let chained = json!({
            "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"type": "string"}},
            "$ref": "#/$defs/a"
        });
        assert!(validate_document(&json!("x"), &chained).is_ok());
        assert!(validate_document(&json!(1), &chained).is_err());

        let sibling = json!({
            "$defs": {"s": {"type": "string"}},
            "$ref": "#/$defs/s",
            "minLength": 5
        });
        assert!(
            validate_document(&json!("abcd"), &sibling).is_err(),
            "$ref is an applicator: the sibling constraint applies"
        );
        assert!(validate_document(&json!("abcde"), &sibling).is_ok());

        let circular = json!({
            "$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}},
            "$ref": "#/$defs/a"
        });
        let error = check_schema(&circular).expect_err("a cycle validates nothing");
        assert!(error.to_string().contains("circular $ref"));

        assert!(check_schema(&json!({"$ref": "#/$defs/missing"})).is_err());
        assert!(
            check_schema(&json!({"$ref": "https://example.com/s.json"})).is_err(),
            "only local refs"
        );
        assert!(
            check_schema(&json!({"$defs": {"n": 1}, "$ref": "#/$defs/n"})).is_err(),
            "a ref must name a schema"
        );
    }

    #[test]
    fn boolean_schemas_accept_and_reject() {
        assert!(validate_document(&json!(1), &json!(true)).is_ok());
        assert!(validate_document(&json!(1), &json!(false)).is_err());
        let array = json!({"type": "array", "items": false});
        assert!(validate_document(&json!([]), &array).is_ok());
        assert!(validate_document(&json!([1]), &array).is_err());
    }

    #[test]
    fn prefix_items_and_items_split_the_array() {
        let schema = json!({
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": {"type": "number"}
        });
        assert!(validate_document(&json!(["x", 1, 2]), &schema).is_ok());
        assert!(
            validate_document(&json!([1, 2]), &schema).is_err(),
            "prefix"
        );
        assert!(
            validate_document(&json!(["x", "y"]), &schema).is_err(),
            "tail"
        );
        assert!(
            validate_document(
                &json!([1]),
                &json!({
                    "type": "array",
                    "prefixItems": [{"type": "string"}],
                    "items": {"type": "string"}
                })
            )
            .is_err(),
            "items must not re-check a prefix position"
        );
    }

    #[test]
    fn enum_and_const_keep_booleans_apart_from_numbers() {
        let enumeration = json!({"enum": [1]});
        assert!(validate_document(&json!(1), &enumeration).is_ok());
        assert!(
            validate_document(&json!(1.0), &enumeration).is_ok(),
            "1 and 1.0 are the same JSON number"
        );
        assert!(
            validate_document(&json!(true), &enumeration).is_err(),
            "true is not 1, even in an enum"
        );
        let nested = json!({"enum": [[1, {"a": 1}]]});
        assert!(validate_document(&json!([1.0, {"a": 1.0}]), &nested).is_ok());
        assert!(validate_document(&json!([true, {"a": 1}]), &nested).is_err());
        assert!(validate_document(&json!(true), &json!({"const": 1})).is_err());
        assert!(validate_document(&json!(2), &json!({"const": 1})).is_err());

        // Exact numbers: an f64 rounded to 9007199254740992 must not equal the
        // integer 9007199254740993.
        assert!(
            validate_document(
                &json!(9_007_199_254_740_993_i64),
                &json!({"const": 9_007_199_254_740_993_i64})
            )
            .is_ok()
        );
        assert!(
            validate_document(
                &json!(9_007_199_254_740_992.0),
                &json!({"const": 9_007_199_254_740_993_i64})
            )
            .is_err()
        );
    }

    #[test]
    fn integer_accepts_one_point_zero_and_refuses_booleans() {
        let schema = json!({"type": "integer"});
        assert!(validate_document(&json!(1), &schema).is_ok());
        assert!(validate_document(&json!(1.0), &schema).is_ok());
        assert!(validate_document(&json!(1e20), &schema).is_ok());
        assert!(validate_document(&json!(1.5), &schema).is_err());
        assert!(validate_document(&json!(true), &schema).is_err());
        assert!(validate_document(&json!("1"), &schema).is_err());
    }

    #[test]
    fn non_finite_numbers_are_refused() {
        let infinity = parse_json("1e999");
        let error = validate_document(&infinity, &json!({"type": "number"}))
            .expect_err("1e999 overflows to infinity");
        assert!(error.to_string().contains("non-finite"));
        assert!(check_schema(&parse_json(r#"{"minimum": 1e999}"#)).is_err());

        // An integer literal beyond f64 is still a finite JSON number.
        let big = parse_json(
            "100000000000000000000000000000000000000000000000000000000000000000000000000000000000",
        );
        assert!(validate_document(&big, &json!({"type": "integer"})).is_ok());
        assert!(validate_document(&big, &json!({"type": "number", "minimum": 0})).is_ok());
    }

    #[test]
    fn minimum_counts_lengths_and_patterns_match_python() {
        let minimum = json!({"type": "number", "minimum": 0});
        assert!(validate_document(&json!(-1), &minimum).is_err());
        assert!(validate_document(&json!(-0.0), &minimum).is_ok());
        assert!(validate_document(&json!(1), &json!({"minimum": 1.5})).is_err());
        // Exact comparison, not an f64 cast.
        assert!(
            validate_document(
                &json!(9_007_199_254_740_992_i64),
                &json!({"minimum": 9_007_199_254_740_993_i64})
            )
            .is_err()
        );
        assert!(
            validate_document(
                &json!(9_007_199_254_740_993_i64),
                &json!({"minimum": 9_007_199_254_740_992_i64})
            )
            .is_ok()
        );

        assert!(validate_document(&json!([1, 2]), &json!({"maxItems": 2.0})).is_ok());
        assert!(validate_document(&json!([1, 2, 3]), &json!({"maxItems": 2})).is_err());
        assert!(validate_document(&json!([1]), &json!({"minItems": 2})).is_err());

        assert!(
            validate_document(&json!("\u{1f600}"), &json!({"minLength": 2})).is_err(),
            "code points, not bytes"
        );
        assert!(validate_document(&json!("\u{1f600}\u{1f600}"), &json!({"minLength": 2})).is_ok());

        let sha = json!({"type": "string", "pattern": "^[0-9a-f]{64}$"});
        let hex = "a".repeat(64);
        assert!(validate_document(&json!(hex), &sha).is_ok());
        assert!(
            validate_document(&json!(format!("{hex}\n")), &sha).is_ok(),
            "Python's `$` also matches before a final newline"
        );
        assert!(validate_document(&json!(format!("{hex} ")), &sha).is_err());
        let empty_or_sha = json!({"type": "string", "pattern": "^$|^[0-9a-f]{64}$"});
        assert!(validate_document(&json!(""), &empty_or_sha).is_ok());
        assert!(validate_document(&json!("\n"), &empty_or_sha).is_ok());
        assert!(validate_document(&json!(" "), &empty_or_sha).is_err());
    }

    #[test]
    fn additional_properties_required_and_schema_errors() {
        let closed = json!({
            "type": "object",
            "properties": {"a": {"type": "number"}},
            "additionalProperties": false,
            "required": ["a"]
        });
        assert!(validate_document(&json!({"a": 1}), &closed).is_ok());
        assert!(validate_document(&json!({"a": 1, "b": 2}), &closed).is_err());
        assert!(validate_document(&json!({}), &closed).is_err());

        let typed_extra = json!({"type": "object", "additionalProperties": {"type": "number"}});
        assert!(validate_document(&json!({"a": 1, "b": 2.5}), &typed_extra).is_ok());
        assert!(validate_document(&json!({"a": "x"}), &typed_extra).is_err());

        let open = json!({"type": "object", "additionalProperties": true});
        assert!(validate_document(&json!({"anything": [1]}), &open).is_ok());

        // Schema-level refusals: structure the subset cannot mean.
        for broken in [
            json!({"properties": []}),
            json!({"items": 1}),
            json!({"prefixItems": {}}),
            json!({"required": [1]}),
            json!({"enum": 1}),
            json!({"pattern": "("}),
            json!({"pattern": 1}),
            json!({"minItems": -1}),
            json!({"maxItems": true}),
            json!({"minLength": 1.5}),
            json!({"minimum": "1"}),
        ] {
            assert!(
                check_schema(&broken).is_err(),
                "should be refused: {broken}"
            );
        }
    }
}
