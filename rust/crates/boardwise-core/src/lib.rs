//! Business-free cross-language contracts for the 540C Rust skeleton.
//! No review rule, parser, layout algorithm or editor transport lives here.

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::cmp::Ordering;
use std::collections::BTreeMap;
use std::error::Error;
use std::fmt::{Display, Formatter};
use std::fs;
use std::path::{Path, PathBuf};

pub const CLI_RESULT_SCHEMA: &str = "boardwise.cli-result/1";
pub const DIFFERENTIAL_REPORT_SCHEMA: &str = "boardwise.differential-report/1";
pub const DIFFERENTIAL_CASES_SCHEMA: &str = "boardwise.differential-cases/1";

pub mod schema;

#[derive(Debug)]
pub enum ContractError {
    Io(String),
    Json(String),
    Shape(String),
}

impl Display for ContractError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(message) => write!(formatter, "I/O error: {message}"),
            Self::Json(message) => write!(formatter, "JSON error: {message}"),
            Self::Shape(message) => write!(formatter, "contract shape error: {message}"),
        }
    }
}

impl Error for ContractError {}

impl From<std::io::Error> for ContractError {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.to_string())
    }
}

impl From<serde_json::Error> for ContractError {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error.to_string())
    }
}

pub type Result<T> = std::result::Result<T, ContractError>;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ErrorObject {
    pub code: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CliResult {
    pub schema: String,
    pub command: String,
    #[serde(rename = "exitCode")]
    pub exit_code: i32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payload: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<ErrorObject>,
}

impl CliResult {
    pub fn success(command: impl Into<String>) -> Self {
        Self {
            schema: CLI_RESULT_SCHEMA.to_owned(),
            command: command.into(),
            exit_code: 0,
            payload: Some(json!({"businessLogic": false})),
            error: None,
        }
    }

    pub fn failure(command: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            schema: CLI_RESULT_SCHEMA.to_owned(),
            command: command.into(),
            exit_code: 2,
            payload: None,
            error: Some(ErrorObject {
                code: "BAD_REQUEST".to_owned(),
                message: message.into(),
                detail: None,
            }),
        }
    }
}

#[derive(Debug, Deserialize)]
struct CaseBook {
    schema: String,
    cases: Vec<Case>,
}

#[derive(Debug, Deserialize)]
struct Case {
    id: String,
    kind: String,
    input: PathBuf,
    expected: Value,
}

#[derive(Debug, Serialize)]
pub struct CaseResult {
    pub id: String,
    pub ok: bool,
    pub actual: Value,
    pub expected: Value,
}

#[derive(Debug, Serialize)]
pub struct DifferentialReport {
    pub schema: String,
    pub runner: String,
    pub ok: bool,
    pub cases: Vec<CaseResult>,
}

pub(crate) fn read_json(path: &Path) -> Result<Value> {
    let text = fs::read_to_string(path)
        .map_err(|error| ContractError::Io(format!("{}: {error}", path.display())))?;
    let value: Value = serde_json::from_str(&text)
        .map_err(|error| ContractError::Json(format!("{}: {error}", path.display())))?;
    // One gate for both the case book and every case input: `1e999` parses to
    // infinity, and a book that carries one is not a document either side can
    // claim to have read. Python's strict loader refuses it at the same place.
    schema::ensure_finite(&value)
        .map_err(|error| ContractError::Shape(format!("{}: {error}", path.display())))?;
    Ok(value)
}

fn field<'a>(value: &'a Value, key: &str) -> Result<&'a Value> {
    value
        .get(key)
        .ok_or_else(|| ContractError::Shape(format!("missing key {key:?}")))
}

fn object<'a>(value: &'a Value, key: &str) -> Result<&'a Value> {
    let found = field(value, key)?;
    if found.is_object() {
        Ok(found)
    } else {
        Err(ContractError::Shape(format!("{key} must be an object")))
    }
}

fn array<'a>(value: &'a Value, key: &str) -> Result<&'a Vec<Value>> {
    field(value, key)?
        .as_array()
        .ok_or_else(|| ContractError::Shape(format!("{key} must be an array")))
}

fn text<'a>(value: &'a Value, key: &str) -> Result<&'a str> {
    field(value, key)?
        .as_str()
        .ok_or_else(|| ContractError::Shape(format!("{key} must be a string")))
}

fn integer(value: &Value, key: &str) -> Result<i64> {
    field(value, key)?
        .as_i64()
        .ok_or_else(|| ContractError::Shape(format!("{key} must be an integer")))
}

fn boolean(value: &Value, key: &str) -> Result<bool> {
    field(value, key)?
        .as_bool()
        .ok_or_else(|| ContractError::Shape(format!("{key} must be a boolean")))
}

// ---------------------------------------------------------------- canonical
//
// The Python side is the authority for what a document *means*: every geometry
// number goes through `LayoutPlan._number` (`float()`), every geometry *text*
// through `_text` (`str.strip()`), and the two source digests plus each
// `symbolHash` through `_digest`, which matches the raw string against
// `\A[0-9a-f]{64}\Z` and never trims it (a padded digest is refused, not
// cleaned up). The digest itself is
// `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
// hashed as UTF-8 (052 sec.4). Canonical JSON therefore has four rules this
// module has to reproduce byte for byte:
//
// 1. object keys sorted (Python sorts by code point; UTF-8 byte order is the
//    same order), arrays in document order;
// 2. `ensure_ascii=False` escaping (only `"`, `\`, the short control escapes and
//    `\u00XX` for the remaining control characters);
// 3. numbers spelled by `float.__repr__` — shortest round-trip digits, fixed
//    notation while `-4 < decpt <= 16`, exponent otherwise, `.0` on integral
//    values, and `-0.0` keeping its sign;
// 4. no whitespace anywhere.
//
// `python_float_repr` is the third rule on its own. Rust's `{:e}` supplies
// shortest round-trip digits but breaks exact halfway ties the other way from
// CPython's dtoa (measured: `1000000000000000.25` is `1000000000000000.2` in
// Python, `...3` in Rust), so an ambiguous candidate is recomputed from the
// value's exact decimal expansion, rounding half to even like dtoa does.

/// One JSON value, numbered by its Python spelling.
#[derive(Debug, Clone)]
enum Canon {
    Null,
    Bool(bool),
    PosInt(u64),
    NegInt(i64),
    /// An integer literal beyond `u64::MAX`: Python keeps every digit.
    Integer(String),
    Float(f64),
    Text(String),
    Array(Vec<Canon>),
    Object(BTreeMap<String, Canon>),
}

impl Canon {
    fn write(&self, out: &mut String) {
        match self {
            Self::Null => out.push_str("null"),
            Self::Bool(true) => out.push_str("true"),
            Self::Bool(false) => out.push_str("false"),
            Self::PosInt(value) => out.push_str(&value.to_string()),
            Self::NegInt(value) => out.push_str(&value.to_string()),
            Self::Integer(value) => out.push_str(value),
            Self::Float(value) => out.push_str(&python_float_repr(*value)),
            Self::Text(value) => write_json_string(value, out),
            Self::Array(items) => {
                out.push('[');
                for (index, item) in items.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    item.write(out);
                }
                out.push(']');
            }
            Self::Object(fields) => {
                out.push('{');
                for (index, (key, value)) in fields.iter().enumerate() {
                    if index > 0 {
                        out.push(',');
                    }
                    write_json_string(key, out);
                    out.push(':');
                    value.write(out);
                }
                out.push('}');
            }
        }
    }
}

fn canonical_text(value: &Canon) -> String {
    let mut out = String::new();
    value.write(&mut out);
    out
}

/// `json.dumps(..., ensure_ascii=False)` string escaping, and nothing else.
fn write_json_string(value: &str, out: &mut String) {
    out.push('"');
    for character in value.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if (control as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", control as u32));
            }
            other => out.push(other),
        }
    }
    out.push('"');
}

/// The canonical spelling of a document (see the module comment above).
fn canonical_of(value: &Value) -> Canon {
    match value {
        Value::Null => Canon::Null,
        Value::Bool(flag) => Canon::Bool(*flag),
        Value::Number(number) => {
            let spelling = number.to_string();
            if number.is_f64() {
                Canon::Float(number_as_f64(number).unwrap_or(f64::NAN))
            } else if let Some(unsigned) = number.as_u64() {
                Canon::PosInt(unsigned)
            } else if let Some(signed) = number.as_i64() {
                Canon::NegInt(signed)
            } else if spelling
                .bytes()
                .any(|byte| byte == b'.' || byte == b'e' || byte == b'E')
            {
                // A float literal outside f64's range: Python reads `1e400` as
                // infinity and writes that token.
                Canon::Float(spelling.parse::<f64>().unwrap_or(f64::NAN))
            } else {
                Canon::Integer(spelling)
            }
        }
        Value::String(value) => Canon::Text(value.clone()),
        Value::Array(items) => Canon::Array(items.iter().map(canonical_of).collect()),
        Value::Object(fields) => Canon::Object(
            fields
                .iter()
                .map(|(key, value)| (key.clone(), canonical_of(value)))
                .collect(),
        ),
    }
}

/// Two documents are the same value only when their canonical bytes are: the
/// rule the Python runner applies, so `true`/`1` and `95`/`95.0` stay distinct.
fn documents_match(left: &Value, right: &Value) -> bool {
    canonical_text(&canonical_of(left)) == canonical_text(&canonical_of(right))
}

// ------------------------------------------------------------- float digits

/// A decimal significand: `value = 0.d1d2… * 10^decpt`, digits are `0..=9`.
#[derive(Debug, Clone)]
struct DecimalDigits {
    digits: Vec<u8>,
    decpt: i32,
}

impl DecimalDigits {
    /// Does this decimal, read back as a double, give exactly `value`?
    fn round_trips(&self, value: f64) -> bool {
        self.format(false)
            .parse::<f64>()
            .is_ok_and(|parsed| parsed.to_bits() == value.to_bits())
    }

    /// One unit in the last digit up or down — the neighbouring candidate.
    fn neighbour(&self, delta: i32) -> Self {
        let mut digits = self.digits.clone();
        let mut decpt = self.decpt;
        if delta > 0 {
            let mut carry = true;
            for index in (0..digits.len()).rev() {
                if !carry {
                    break;
                }
                if digits[index] == 9 {
                    digits[index] = 0;
                } else {
                    digits[index] += 1;
                    carry = false;
                }
            }
            if carry {
                digits.insert(0, 1);
                decpt += 1;
            }
        } else {
            let mut borrow = true;
            for index in (0..digits.len()).rev() {
                if !borrow {
                    break;
                }
                if digits[index] == 0 {
                    digits[index] = 9;
                } else {
                    digits[index] -= 1;
                    borrow = false;
                }
            }
            if borrow {
                return Self {
                    digits: vec![0],
                    decpt: 1,
                };
            }
            while digits.len() > 1 && digits[0] == 0 {
                digits.remove(0);
                decpt -= 1;
            }
        }
        Self { digits, decpt }
    }

    /// Python's `repr(float)` layout for these digits and this sign.
    fn format(&self, negative: bool) -> String {
        let mut out = String::new();
        if negative {
            out.push('-');
        }
        if self.digits == [0] {
            out.push_str("0.0");
            return out;
        }
        let length = self.digits.len() as i32;
        let decpt = self.decpt;
        if decpt <= -4 || decpt > 16 {
            out.push(digit_character(self.digits[0]));
            if self.digits.len() > 1 {
                out.push('.');
                for digit in &self.digits[1..] {
                    out.push(digit_character(*digit));
                }
            }
            let exponent = decpt - 1;
            out.push('e');
            out.push(if exponent < 0 { '-' } else { '+' });
            let magnitude = exponent.abs();
            if magnitude < 10 {
                out.push('0');
            }
            out.push_str(&magnitude.to_string());
        } else if decpt <= 0 {
            out.push_str("0.");
            for _ in 0..(-decpt) {
                out.push('0');
            }
            for digit in &self.digits {
                out.push(digit_character(*digit));
            }
        } else if decpt >= length {
            for digit in &self.digits {
                out.push(digit_character(*digit));
            }
            for _ in 0..(decpt - length) {
                out.push('0');
            }
            out.push_str(".0");
        } else {
            let split = decpt as usize;
            for digit in &self.digits[..split] {
                out.push(digit_character(*digit));
            }
            out.push('.');
            for digit in &self.digits[split..] {
                out.push(digit_character(*digit));
            }
        }
        out
    }
}

fn digit_character(digit: u8) -> char {
    char::from(b'0' + digit)
}

/// Shortest round-trip digits as Rust's `LowerExp` spells them.
fn shortest_decimal(value: f64) -> DecimalDigits {
    let scientific = format!("{value:e}");
    let (mantissa, exponent_text) = scientific
        .split_once('e')
        .expect("LowerExp always writes an exponent");
    let exponent: i32 = exponent_text
        .parse()
        .expect("LowerExp writes an integer exponent");
    let mantissa = mantissa.strip_prefix('-').unwrap_or(mantissa);
    let digits = mantissa
        .bytes()
        .filter(|byte| *byte != b'.')
        .map(|byte| byte - b'0')
        .collect();
    DecimalDigits {
        digits,
        decpt: exponent + 1,
    }
}

/// `repr(value)` for a positive finite double, digits chosen like CPython's dtoa.
pub fn python_float_repr(value: f64) -> String {
    if value.is_nan() {
        return "NaN".to_owned();
    }
    if value.is_infinite() {
        return if value.is_sign_negative() {
            "-Infinity"
        } else {
            "Infinity"
        }
        .to_owned();
    }
    let negative = value.is_sign_negative();
    if value == 0.0 {
        return if negative { "-0.0" } else { "0.0" }.to_owned();
    }
    let magnitude = value.abs();
    let mut decimal = shortest_decimal(magnitude);
    if !decimal_is_unambiguous(&decimal, magnitude) {
        decimal = exact_shortest(magnitude);
    }
    decimal.format(negative)
}

/// Is this the only candidate of its length that reads back as `value`?
fn decimal_is_unambiguous(decimal: &DecimalDigits, magnitude: f64) -> bool {
    !decimal.neighbour(1).round_trips(magnitude) && !decimal.neighbour(-1).round_trips(magnitude)
}

/// The shortest decimal that reads back as `value`, ties rounded to even — the
/// choice CPython's dtoa makes when Rust's digits land on a halfway boundary.
fn exact_shortest(magnitude: f64) -> DecimalDigits {
    let (digits, decpt) = exact_decimal(magnitude);
    let limit = digits.len().min(17);
    for count in 1..=limit {
        let head = DecimalDigits {
            digits: digits[..count].to_vec(),
            decpt,
        };
        let up = head.neighbour(1);
        let head_ok = head.round_trips(magnitude);
        let up_ok = up.round_trips(magnitude);
        if !head_ok && !up_ok {
            continue;
        }
        let choose_up = if head_ok && up_ok {
            if digits.len() == count {
                false
            } else {
                match remainder_against_half(&digits[count..]) {
                    Ordering::Less => false,
                    Ordering::Greater => true,
                    Ordering::Equal => digits[count - 1] % 2 == 1,
                }
            }
        } else {
            up_ok
        };
        return if choose_up { up } else { head };
    }
    shortest_decimal(magnitude)
}

/// Is the dropped tail below, above, or exactly one half of the last digit?
fn remainder_against_half(remainder: &[u8]) -> Ordering {
    match remainder.first() {
        None => Ordering::Equal,
        Some(first) => match first.cmp(&5) {
            Ordering::Equal => {
                if remainder[1..].iter().any(|digit| *digit != 0) {
                    Ordering::Greater
                } else {
                    Ordering::Equal
                }
            }
            other => other,
        },
    }
}

/// The exact decimal expansion of a positive finite double:
/// `value = 0.<digits> * 10^decpt`, no rounding anywhere.
pub(crate) fn exact_decimal(magnitude: f64) -> (Vec<u8>, i32) {
    let bits = magnitude.to_bits();
    let stored_exponent = ((bits >> 52) & 0x7ff) as i32;
    let fraction = bits & ((1_u64 << 52) - 1);
    let (mantissa, exponent) = if stored_exponent == 0 {
        (fraction, -1074)
    } else {
        (fraction | (1_u64 << 52), stored_exponent - 1075)
    };
    let mut limbs = decimal_limbs(mantissa);
    let text = if exponent >= 0 {
        for _ in 0..exponent {
            decimal_limbs_mul(&mut limbs, 2);
        }
        limbs_to_decimal(&limbs)
    } else {
        for _ in 0..-exponent {
            decimal_limbs_mul(&mut limbs, 5);
        }
        limbs_to_decimal(&limbs)
    };
    let decpt = if exponent >= 0 {
        text.len() as i32
    } else {
        text.len() as i32 + exponent
    };
    (text.bytes().map(|byte| byte - b'0').collect(), decpt)
}

const LIMB_BASE: u64 = 1_000_000_000;

fn decimal_limbs(value: u64) -> Vec<u32> {
    let mut limbs = Vec::new();
    let mut rest = value;
    while rest > 0 {
        limbs.push((rest % LIMB_BASE) as u32);
        rest /= LIMB_BASE;
    }
    if limbs.is_empty() {
        limbs.push(0);
    }
    limbs
}

fn decimal_limbs_mul(limbs: &mut Vec<u32>, factor: u32) {
    let mut carry: u64 = 0;
    for limb in limbs.iter_mut() {
        let product = u64::from(*limb) * u64::from(factor) + carry;
        *limb = (product % LIMB_BASE) as u32;
        carry = product / LIMB_BASE;
    }
    while carry > 0 {
        limbs.push((carry % LIMB_BASE) as u32);
        carry /= LIMB_BASE;
    }
}

fn limbs_to_decimal(limbs: &[u32]) -> String {
    let mut text = limbs.last().map_or_else(|| "0".to_owned(), u32::to_string);
    for limb in limbs.iter().rev().skip(1) {
        text.push_str(&format!("{limb:09}"));
    }
    text
}

// ------------------------------------------------------- layout-plan readers

fn value_object<'a>(value: &'a Value, where_: &str) -> Result<&'a Map<String, Value>> {
    value
        .as_object()
        .ok_or_else(|| ContractError::Shape(format!("{where_} must be a JSON object")))
}

/// `LayoutPlan._list`: a missing or null list reads as empty.
fn layout_list<'a>(map: &'a Map<String, Value>, key: &str) -> Result<&'a [Value]> {
    match map.get(key) {
        None | Some(Value::Null) => Ok(&[]),
        Some(Value::Array(items)) => Ok(items.as_slice()),
        Some(_) => Err(ContractError::Shape(format!("{key} must be a list"))),
    }
}

/// Python's `str.isspace()`: Unicode whitespace plus U+001C..U+001F, which
/// `char::is_whitespace` does not consider whitespace.
fn python_whitespace(character: char) -> bool {
    character.is_whitespace() || matches!(character, '\u{1c}'..='\u{1f}')
}

/// `LayoutPlan._text`: absent/null is `""` (or a refusal when required), a
/// string is stripped, anything else is refused.
fn text_field(map: &Map<String, Value>, key: &str, required: bool, where_: &str) -> Result<String> {
    match map.get(key) {
        None | Some(Value::Null) => {
            if required {
                Err(ContractError::Shape(format!("{where_} is required")))
            } else {
                Ok(String::new())
            }
        }
        Some(Value::String(text)) => {
            let stripped = text.trim_matches(python_whitespace).to_owned();
            if required && stripped.is_empty() {
                Err(ContractError::Shape(format!("{where_} is empty")))
            } else {
                Ok(stripped)
            }
        }
        Some(_) => Err(ContractError::Shape(format!("{where_} must be a string"))),
    }
}

/// `LayoutPlan._digest`: a 64-character lowercase hex string, read **verbatim**.
///
/// `_digest` runs `\A[0-9a-f]{64}\Z` against the raw value and never strips, so
/// a digest with surrounding whitespace is refused rather than cleaned up —
/// unlike `_text` fields, which the reader does strip. Sharing `text_field`
/// here would silently accept `" <sha256> "` and produce a document Python
/// refuses.
fn digest_field(map: &Map<String, Value>, key: &str, where_: &str) -> Result<String> {
    let value = match map.get(key) {
        Some(Value::String(text)) => text,
        _ => {
            return Err(ContractError::Shape(format!(
                "{where_} must be 64 hex characters (a sha256)"
            )));
        }
    };
    let is_digest = value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte));
    if is_digest {
        Ok(value.clone())
    } else {
        Err(ContractError::Shape(format!(
            "{where_} must be 64 hex characters (a sha256), got {value:?}"
        )))
    }
}

/// `LayoutPlan._number`: a JSON number becomes a double; booleans and strings
/// are refused.
fn number_of(value: &Value, where_: &str) -> Result<f64> {
    match value {
        Value::Number(number) => number_as_f64(number).ok_or_else(|| {
            ContractError::Shape(format!("{where_} must be a number in canvas units"))
        }),
        _ => Err(ContractError::Shape(format!(
            "{where_} must be a number in canvas units"
        ))),
    }
}

/// The double a JSON number literal denotes, read with Rust's correctly-rounded
/// parser (`Number` keeps the literal because of `arbitrary_precision`). This is
/// the same conversion as Python's `float()`: an integer literal goes through
/// the exact integer, not through a lossy f64 accumulator.
fn number_as_f64(number: &serde_json::Number) -> Option<f64> {
    number.to_string().parse::<f64>().ok()
}

fn number_field(map: &Map<String, Value>, key: &str, where_: &str) -> Result<f64> {
    match map.get(key) {
        Some(value) => number_of(value, where_),
        None => Err(ContractError::Shape(format!("{where_} is required"))),
    }
}

/// A reader default: `body.get(key, default)` — but an explicit `null` is still
/// a refusal, exactly like Python's `_number(None)`.
fn number_default(map: &Map<String, Value>, key: &str, default: f64, where_: &str) -> Result<f64> {
    match map.get(key) {
        None => Ok(default),
        Some(value) => number_of(value, where_),
    }
}

fn boolean_default(
    map: &Map<String, Value>,
    key: &str,
    default: bool,
    where_: &str,
) -> Result<bool> {
    match map.get(key) {
        None => Ok(default),
        Some(Value::Bool(flag)) => Ok(*flag),
        Some(_) => Err(ContractError::Shape(format!("{where_} must be a boolean"))),
    }
}

/// `check_box`: exactly four numbers, `[minX, minY, maxX, maxY]`.
fn box_field(map: &Map<String, Value>, key: &str, where_: &str) -> Result<Vec<Canon>> {
    let items = match map.get(key) {
        Some(Value::Array(items)) => items,
        _ => {
            return Err(ContractError::Shape(format!(
                "{where_} must be [minX, minY, maxX, maxY] in canvas units"
            )));
        }
    };
    if items.len() != 4 {
        return Err(ContractError::Shape(format!(
            "{where_} must be [minX, minY, maxX, maxY] in canvas units"
        )));
    }
    items
        .iter()
        .enumerate()
        .map(|(index, item)| number_of(item, &format!("{where_}[{index}]")).map(Canon::Float))
        .collect()
}

fn point_of(value: &Value, where_: &str) -> Result<Canon> {
    let pair = value
        .as_array()
        .ok_or_else(|| ContractError::Shape(format!("{where_} must be [x, y] in canvas units")))?;
    if pair.len() < 2 {
        return Err(ContractError::Shape(format!(
            "{where_} must be [x, y] in canvas units"
        )));
    }
    let x = number_of(&pair[0], where_)?;
    let y = number_of(&pair[1], where_)?;
    Ok(Canon::Array(vec![Canon::Float(x), Canon::Float(y)]))
}

fn object_of(fields: BTreeMap<String, Canon>) -> Canon {
    Canon::Object(fields)
}

fn geometry_parts(root: &Map<String, Value>) -> Result<Vec<Canon>> {
    let items = layout_list(root, "parts")?;
    if items.is_empty() {
        return Err(ContractError::Shape(
            "parts is empty — a plan describes a drawing".to_owned(),
        ));
    }
    let mut parts = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let spot = format!("parts[{index}]");
        let body = value_object(item, &spot)?;
        let mut fields = BTreeMap::new();
        fields.insert(
            "partId".to_owned(),
            Canon::Text(text_field(body, "partId", true, &format!("{spot}.partId"))?),
        );
        fields.insert(
            "reference".to_owned(),
            Canon::Text(text_field(
                body,
                "reference",
                false,
                &format!("{spot}.reference"),
            )?),
        );
        fields.insert(
            "symbolRef".to_owned(),
            Canon::Text(text_field(
                body,
                "symbolRef",
                true,
                &format!("{spot}.symbolRef"),
            )?),
        );
        fields.insert(
            "symbolHash".to_owned(),
            Canon::Text(digest_field(
                body,
                "symbolHash",
                &format!("{spot}.symbolHash"),
            )?),
        );
        fields.insert(
            "x".to_owned(),
            Canon::Float(number_field(body, "x", &format!("{spot}.x"))?),
        );
        fields.insert(
            "y".to_owned(),
            Canon::Float(number_field(body, "y", &format!("{spot}.y"))?),
        );
        fields.insert(
            "rotation".to_owned(),
            Canon::Float(number_default(
                body,
                "rotation",
                0.0,
                &format!("{spot}.rotation"),
            )?),
        );
        fields.insert(
            "mirror".to_owned(),
            Canon::Bool(boolean_default(
                body,
                "mirror",
                false,
                &format!("{spot}.mirror"),
            )?),
        );
        if !boolean_default(body, "valueVisible", true, &format!("{spot}.valueVisible"))? {
            fields.insert("valueVisible".to_owned(), Canon::Bool(false));
        }
        for key in ["group", "island"] {
            let value = text_field(body, key, false, &format!("{spot}.{key}"))?;
            if !value.is_empty() {
                fields.insert(key.to_owned(), Canon::Text(value));
            }
        }
        parts.push(object_of(fields));
    }
    Ok(parts)
}

fn geometry_segments(root: &Map<String, Value>) -> Result<Vec<Canon>> {
    let items = layout_list(root, "segments")?;
    let mut segments = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let spot = format!("segments[{index}]");
        let body = value_object(item, &spot)?;
        let mut fields = BTreeMap::new();
        fields.insert(
            "net".to_owned(),
            Canon::Text(text_field(body, "net", true, &format!("{spot}.net"))?),
        );
        let points = layout_list(body, "points")?
            .iter()
            .enumerate()
            .map(|(point_index, pair)| point_of(pair, &format!("{spot}.points[{point_index}]")))
            .collect::<Result<Vec<_>>>()?;
        fields.insert("points".to_owned(), Canon::Array(points));
        segments.push(object_of(fields));
    }
    Ok(segments)
}

fn geometry_junctions(root: &Map<String, Value>) -> Result<Vec<Canon>> {
    let items = layout_list(root, "junctions")?;
    let mut junctions = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let spot = format!("junctions[{index}]");
        let body = value_object(item, &spot)?;
        let mut fields = BTreeMap::new();
        fields.insert(
            "net".to_owned(),
            Canon::Text(text_field(body, "net", true, &format!("{spot}.net"))?),
        );
        fields.insert(
            "x".to_owned(),
            Canon::Float(number_field(body, "x", &format!("{spot}.x"))?),
        );
        fields.insert(
            "y".to_owned(),
            Canon::Float(number_field(body, "y", &format!("{spot}.y"))?),
        );
        junctions.push(object_of(fields));
    }
    Ok(junctions)
}

fn geometry_labels(root: &Map<String, Value>) -> Result<Vec<Canon>> {
    let items = layout_list(root, "labels")?;
    let mut labels = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let spot = format!("labels[{index}]");
        let body = value_object(item, &spot)?;
        let mut fields = BTreeMap::new();
        fields.insert(
            "net".to_owned(),
            Canon::Text(text_field(body, "net", true, &format!("{spot}.net"))?),
        );
        fields.insert(
            "text".to_owned(),
            Canon::Text(text_field(body, "text", true, &format!("{spot}.text"))?),
        );
        fields.insert(
            "x".to_owned(),
            Canon::Float(number_field(body, "x", &format!("{spot}.x"))?),
        );
        fields.insert(
            "y".to_owned(),
            Canon::Float(number_field(body, "y", &format!("{spot}.y"))?),
        );
        fields.insert(
            "rotation".to_owned(),
            Canon::Float(number_default(
                body,
                "rotation",
                0.0,
                &format!("{spot}.rotation"),
            )?),
        );
        fields.insert(
            "bbox".to_owned(),
            Canon::Array(box_field(body, "bbox", &format!("{spot}.bbox"))?),
        );
        labels.push(object_of(fields));
    }
    Ok(labels)
}

fn geometry_power_symbols(root: &Map<String, Value>) -> Result<Vec<Canon>> {
    let items = layout_list(root, "powerSymbols")?;
    let mut symbols = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let spot = format!("powerSymbols[{index}]");
        let body = value_object(item, &spot)?;
        let mut fields = BTreeMap::new();
        fields.insert(
            "symbolRef".to_owned(),
            Canon::Text(text_field(
                body,
                "symbolRef",
                true,
                &format!("{spot}.symbolRef"),
            )?),
        );
        fields.insert(
            "symbolHash".to_owned(),
            Canon::Text(digest_field(
                body,
                "symbolHash",
                &format!("{spot}.symbolHash"),
            )?),
        );
        fields.insert(
            "net".to_owned(),
            Canon::Text(text_field(body, "net", true, &format!("{spot}.net"))?),
        );
        fields.insert(
            "x".to_owned(),
            Canon::Float(number_field(body, "x", &format!("{spot}.x"))?),
        );
        fields.insert(
            "y".to_owned(),
            Canon::Float(number_field(body, "y", &format!("{spot}.y"))?),
        );
        fields.insert(
            "rotation".to_owned(),
            Canon::Float(number_default(
                body,
                "rotation",
                0.0,
                &format!("{spot}.rotation"),
            )?),
        );
        symbols.push(object_of(fields));
    }
    Ok(symbols)
}

fn geometry_texts(root: &Map<String, Value>) -> Result<Vec<Canon>> {
    let items = layout_list(root, "texts")?;
    let mut texts = Vec::with_capacity(items.len());
    for (index, item) in items.iter().enumerate() {
        let spot = format!("texts[{index}]");
        let body = value_object(item, &spot)?;
        let mut fields = BTreeMap::new();
        fields.insert(
            "kind".to_owned(),
            Canon::Text(text_field(body, "kind", true, &format!("{spot}.kind"))?),
        );
        fields.insert(
            "text".to_owned(),
            Canon::Text(text_field(body, "text", true, &format!("{spot}.text"))?),
        );
        fields.insert(
            "partId".to_owned(),
            Canon::Text(text_field(
                body,
                "partId",
                false,
                &format!("{spot}.partId"),
            )?),
        );
        // A text placed without a point carries `null`, not a zero (the field is
        // optional in the reader, and `None` is what the document states).
        for key in ["x", "y"] {
            let value = match body.get(key) {
                None | Some(Value::Null) => Canon::Null,
                Some(number) => Canon::Float(number_of(number, &format!("{spot}.{key}"))?),
            };
            fields.insert(key.to_owned(), value);
        }
        fields.insert(
            "rotation".to_owned(),
            Canon::Float(number_default(
                body,
                "rotation",
                0.0,
                &format!("{spot}.rotation"),
            )?),
        );
        fields.insert(
            "bbox".to_owned(),
            Canon::Array(box_field(body, "bbox", &format!("{spot}.bbox"))?),
        );
        texts.push(object_of(fields));
    }
    Ok(texts)
}

/// `LayoutPlan._geometry_payload()`: everything that *is* the layout, in the
/// canonical JSON the digest binds a preview to.
fn layout_geometry(payload: &Value) -> Result<Canon> {
    let root = value_object(payload, "$")?;
    let source = value_object(field(payload, "source")?, "source")?;
    let mut source_fields = BTreeMap::new();
    source_fields.insert(
        "circuitSha256".to_owned(),
        Canon::Text(digest_field(
            source,
            "circuitSha256",
            "source.circuitSha256",
        )?),
    );
    source_fields.insert(
        "presentationSha256".to_owned(),
        Canon::Text(digest_field(
            source,
            "presentationSha256",
            "source.presentationSha256",
        )?),
    );
    let mut geometry = BTreeMap::new();
    geometry.insert("source".to_owned(), object_of(source_fields));
    geometry.insert("parts".to_owned(), Canon::Array(geometry_parts(root)?));
    geometry.insert(
        "segments".to_owned(),
        Canon::Array(geometry_segments(root)?),
    );
    geometry.insert(
        "junctions".to_owned(),
        Canon::Array(geometry_junctions(root)?),
    );
    geometry.insert("labels".to_owned(), Canon::Array(geometry_labels(root)?));
    geometry.insert(
        "powerSymbols".to_owned(),
        Canon::Array(geometry_power_symbols(root)?),
    );
    geometry.insert("texts".to_owned(), Canon::Array(geometry_texts(root)?));
    Ok(object_of(geometry))
}

/// Canonical compact JSON of the geometry, byte-identical to Python's.
pub fn geometry_json(payload: &Value) -> Result<String> {
    layout_geometry(payload).map(|geometry| canonical_text(&geometry))
}

/// The plan's identity as a picture — the same digest Python's
/// `LayoutPlan.geometry_sha256` produces for the same document.
pub fn geometry_sha256(payload: &Value) -> Result<String> {
    let canonical = geometry_json(payload)?;
    Ok(format!("{:x}", Sha256::digest(canonical.as_bytes())))
}

// ------------------------------------------------------- compile projections

/// A preview's basename: the text after the last `/` **or** backslash, on any
/// host. Python's `_preview_names` replaces a backslash with `/` and splits on
/// `/`, which is the same rule.
fn preview_names(payload: &Value) -> Result<Vec<String>> {
    array(payload, "previews")?
        .iter()
        .map(|item| {
            let path = item
                .as_str()
                .ok_or_else(|| ContractError::Shape("preview paths must be strings".to_owned()))?;
            Ok(path.rsplit(['/', '\\']).next().unwrap_or(path).to_owned())
        })
        .collect()
}

/// The array a compile document counts: the module shape counts `candidates`,
/// the page shape counts `pages`. There is no shared name to fall back on — a
/// page document never states candidates.
#[derive(Debug, Clone, Copy)]
enum CompileCount {
    Candidates,
    Pages,
}

impl CompileCount {
    fn source(self) -> &'static str {
        match self {
            Self::Candidates => "candidates",
            Self::Pages => "pages",
        }
    }

    fn field(self) -> &'static str {
        match self {
            Self::Candidates => "candidateCount",
            Self::Pages => "pageCount",
        }
    }
}

/// The half both compile projections state: `command`, `ok`, `failureCount` and
/// the preview basenames. Read once, here, so the two shapes cannot drift in the
/// fields they have in common; only the count field names their own array.
fn compile_projection(payload: &Value, count: CompileCount) -> Result<Value> {
    let mut fields = Map::new();
    fields.insert(
        "command".to_owned(),
        Value::String(text(payload, "command")?.to_owned()),
    );
    fields.insert("ok".to_owned(), Value::Bool(boolean(payload, "ok")?));
    fields.insert(
        count.field().to_owned(),
        Value::from(array(payload, count.source())?.len()),
    );
    fields.insert(
        "failureCount".to_owned(),
        Value::from(array(payload, "failures")?.len()),
    );
    fields.insert(
        "previewNames".to_owned(),
        Value::from(preview_names(payload)?),
    );
    Ok(Value::Object(fields))
}

// ------------------------------------------------------------------ cases

fn project_case(case: &Case, root: &Path) -> Result<Value> {
    let payload = read_json(&root.join(&case.input))?;
    // 540C: the input contract is checked before it is projected, against the
    // same `contracts/json` schemas the Python runner loads.
    schema::validate_for_kind(&payload, &case.kind)?;
    match case.kind.as_str() {
        "review-report-projection" => {
            let summary = object(&payload, "summary")?;
            let completion = object(&payload, "completion")?;
            let evidence = object(&payload, "evidence")?;
            let delivery = object(evidence, "delivery")?;
            Ok(json!({
                "schema": text(&payload, "schema")?,
                "completionVerdict": text(completion, "verdict")?,
                "summaryExitCode": integer(summary, "exitCode")?,
                "findingCount": array(&payload, "findings")?.len(),
                "errorCount": integer(summary, "errorCount")?,
                "warnCount": integer(summary, "warnCount")?,
                "infoCount": integer(summary, "infoCount")?,
                "evidenceDelivery": text(delivery, "status")?,
            }))
        }
        "layout-plan-geometry" => {
            let digest = geometry_sha256(&payload)?;
            let plan = value_object(&payload, "$")?;
            Ok(json!({
                "geometrySha256": digest,
                "partCount": layout_list(plan, "parts")?.len(),
                "segmentCount": layout_list(plan, "segments")?.len(),
                "junctionCount": layout_list(plan, "junctions")?.len(),
                "labelCount": layout_list(plan, "labels")?.len(),
                "powerSymbolCount": layout_list(plan, "powerSymbols")?.len(),
                "textCount": layout_list(plan, "texts")?.len(),
            }))
        }
        "compile-result-projection" => compile_projection(&payload, CompileCount::Candidates),
        // A page document states `pages`. Counting them into `candidateCount`
        // would report a field the producer never wrote.
        "compile-page-result-projection" => compile_projection(&payload, CompileCount::Pages),
        "lint-result-projection" => {
            let counts = object(&payload, "counts")?;
            Ok(json!({
                "source": text(&payload, "source")?,
                "exitCode": integer(&payload, "exitCode")?,
                "errorCount": integer(counts, "ERROR")?,
                "findingCount": array(&payload, "findings")?.len(),
                "textReadable": boolean(&payload, "textReadable")?,
            }))
        }
        other => Err(ContractError::Shape(format!(
            "unknown differential case kind {other:?}"
        ))),
    }
}

pub fn run_cases(cases_path: &Path, root: &Path) -> Result<DifferentialReport> {
    let book: CaseBook = serde_json::from_value(read_json(cases_path)?)?;
    if book.schema != DIFFERENTIAL_CASES_SCHEMA {
        return Err(ContractError::Shape(format!(
            "unsupported case-book schema {:?}",
            book.schema
        )));
    }
    let mut rows = Vec::with_capacity(book.cases.len());
    for case in &book.cases {
        let actual = project_case(case, root)?;
        rows.push(CaseResult {
            id: case.id.clone(),
            // Type-strict on purpose: the verdict is canonical bytes, so a
            // golden that spells `true` as `1`, or `95.0` as `95`, fails here
            // exactly as it fails on the Python runner.
            ok: documents_match(&actual, &case.expected),
            actual,
            expected: case.expected.clone(),
        });
    }
    Ok(DifferentialReport {
        schema: DIFFERENTIAL_REPORT_SCHEMA.to_owned(),
        runner: "rust".to_owned(),
        ok: rows.iter().all(|row| row.ok),
        cases: rows,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repository_root() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .ancestors()
            .nth(3)
            .expect("repository root")
            .to_path_buf()
    }

    fn golden_layout() -> Value {
        read_json(
            &repository_root().join("contracts/differential/inputs/divider-cand1.layout.json"),
        )
        .expect("golden layout input is readable")
    }

    fn parse_json(literal: &str) -> Value {
        serde_json::from_str(literal).expect("test literal is JSON")
    }

    fn minimal_payload() -> Value {
        let digest = "0".repeat(64);
        json!({
            "source": {
                "circuitSha256": digest,
                "presentationSha256": digest,
            },
            "parts": [{
                "partId": "p1",
                "symbolRef": "synthetic-symbol",
                "symbolHash": "1".repeat(64),
                "x": 10,
                "y": 20,
            }],
        })
    }

    /// Rewrite every integral float as an integer literal (the spelling a plan
    /// that was hand-edited would use). `-0.0` stays a float: it is a different
    /// value from `0` after Python's `float()`.
    fn integer_spelling(value: &Value) -> Value {
        match value {
            Value::Number(number) if number.is_f64() => {
                let float = number.as_f64().expect("float number");
                let integral = float.fract() == 0.0
                    && float.abs() <= 9_007_199_254_740_992.0
                    && !(float == 0.0 && float.is_sign_negative());
                if integral {
                    Value::from(float as i64)
                } else {
                    value.clone()
                }
            }
            Value::Array(items) => Value::Array(items.iter().map(integer_spelling).collect()),
            Value::Object(fields) => Value::Object(
                fields
                    .iter()
                    .map(|(key, item)| (key.clone(), integer_spelling(item)))
                    .collect(),
            ),
            other => other.clone(),
        }
    }

    #[test]
    fn repository_differential_cases_pass() {
        let root = repository_root();
        let report = run_cases(&root.join("contracts/differential/cases.json"), &root)
            .expect("differential cases run");
        assert!(report.ok, "Rust differential failed: {report:#?}");
        assert_eq!(report.cases.len(), 5);
        assert_eq!(report.runner, "rust");
    }

    fn repository_case<'a>(report: &'a DifferentialReport, id: &str) -> &'a CaseResult {
        report
            .cases
            .iter()
            .find(|case| case.id == id)
            .unwrap_or_else(|| panic!("{id} is in the repository case book"))
    }

    /// The page document counts pages. It must not inherit the module shape's
    /// `candidateCount`, which this producer never writes.
    #[test]
    fn page_compile_projection_counts_pages_and_never_candidates() {
        let root = repository_root();
        let report = run_cases(&root.join("contracts/differential/cases.json"), &root)
            .expect("differential cases run");

        let page = repository_case(&report, "compile-page-result-projection");
        assert!(page.ok, "page projection must match its golden: {page:#?}");
        assert_eq!(page.actual["pageCount"], 8);
        assert_eq!(
            page.actual["previewNames"].as_array().map(Vec::len),
            Some(16)
        );
        assert_eq!(page.actual["failureCount"], 0);
        assert!(
            page.actual.get("candidateCount").is_none(),
            "a page document states no candidates: {}",
            page.actual
        );
        // Both separators end a preview name; this fixture's names are the
        // basenames of `<OUT>/compile-page/candN.{svg,page.json}`.
        assert_eq!(page.actual["previewNames"][0], "cand1.svg");
        assert_eq!(page.actual["previewNames"][1], "cand1.page.json");

        // The module shape keeps its own count and states no pages.
        let module = repository_case(&report, "compile-result-projection");
        assert!(module.ok);
        assert_eq!(module.actual["candidateCount"], 3);
        assert_eq!(module.actual["failureCount"], 0);
        assert!(module.actual.get("pageCount").is_none());
    }

    /// Both compile shapes read the common half through one function, so a
    /// change to (say) the preview basename rule lands on both.
    #[test]
    fn compile_shapes_share_the_common_half_of_the_projection() {
        let document = |count_key: &str, count: Value| {
            let mut payload = json!({
                "command": "compile",
                "ok": true,
                "failures": [{"category": "layout-unsat", "detail": "d", "action": "a"}],
                "previews": ["<OUT>/cand1.svg", "<OUT>/nested\\cand2.page.json"],
            });
            payload[count_key] = count;
            payload
        };
        let module = compile_projection(
            &document("candidates", json!([{}, {}, {}])),
            CompileCount::Candidates,
        )
        .expect("module projection");
        let page = compile_projection(&document("pages", json!([{}, {}])), CompileCount::Pages)
            .expect("page projection");

        for key in ["command", "ok", "failureCount", "previewNames"] {
            assert_eq!(module[key], page[key], "{key} must not depend on the shape");
        }
        assert_eq!(module["candidateCount"], 3);
        assert!(module.get("pageCount").is_none());
        assert_eq!(page["pageCount"], 2);
        assert!(page.get("candidateCount").is_none());
        assert_eq!(
            page["previewNames"],
            json!(["cand1.svg", "cand2.page.json"]),
            "a backslash ends a preview name like a slash does"
        );
    }

    #[test]
    fn golden_geometry_digest_matches_python() {
        // The digest Python's LayoutPlan.geometry_sha256 gives this document,
        // pinned in contracts/differential/cases.json. Changing it is changing
        // the contract, not fixing a test.
        assert_eq!(
            geometry_sha256(&golden_layout()).expect("golden layout hashes"),
            "62a272b1968a1d037a6854f38299223f8597ab4acd06fed25f11d7476ca056b1"
        );
    }

    #[test]
    fn integer_and_float_spellings_of_one_picture_share_a_digest() {
        let golden = golden_layout();
        let integer_spelled = integer_spelling(&golden);
        assert_ne!(golden, integer_spelled, "the fixture still spells 95.0");
        assert_eq!(
            geometry_json(&golden).expect("float spelling hashes"),
            geometry_json(&integer_spelled).expect("integer spelling hashes"),
            "the same geometry must not hash differently by number spelling"
        );
        assert_eq!(
            geometry_sha256(&integer_spelled).expect("integer spelling hashes"),
            geometry_sha256(&golden).expect("float spelling hashes")
        );
    }

    #[test]
    fn float_spelling_follows_pythons_repr() {
        // Every row measured against Python's repr() on this machine.
        let rows: &[(f64, &str)] = &[
            (95.0, "95.0"),
            (-130.0, "-130.0"),
            (0.0, "0.0"),
            (-0.0, "-0.0"),
            (0.1, "0.1"),
            (1.0 / 3.0, "0.3333333333333333"),
            (1e-4, "0.0001"),
            (1e-5, "1e-05"),
            (1e-7, "1e-07"),
            (2.5e-7, "2.5e-07"),
            (1e-300, "1e-300"),
            (1e15, "1000000000000000.0"),
            (1e16, "1e+16"),
            (1e17, "1e+17"),
            (1e300, "1e+300"),
            (1234567890123456.0, "1234567890123456.0"),
            (9007199254740992.0, "9007199254740992.0"),
            (1.2345678901234568e17, "1.2345678901234568e+17"),
            (5e-324, "5e-324"),
            (2.2250738585072014e-308, "2.2250738585072014e-308"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
            // Exact halfway ties: CPython's dtoa rounds to even, Rust's `{:e}`
            // does not — the case the exact-decimal fallback exists for. The
            // bits are spelled out because the decimal tie has no short form.
            (f64::from_bits(0x430c_6bf5_2634_0002), "1000000000000000.2"),
            (f64::from_bits(0xc31a_cd24_2c8d_7601), "-1885976161115520.2"),
            (f64::from_bits(0x4312_cb29_1ac0_c8d9), "1322481745932854.2"),
        ];
        for (value, expected) in rows {
            assert_eq!(
                python_float_repr(*value),
                *expected,
                "repr({value:?}) must follow Python"
            );
        }
    }

    #[test]
    fn text_fields_are_stripped_like_python() {
        let mut spaced = minimal_payload();
        spaced["parts"][0]["reference"] = json!(" R1 ");
        spaced["parts"][0]["symbolRef"] = json!(" R0402 ");
        spaced["parts"][0]["group"] = json!("\tmodule A ");
        spaced["parts"][0]["island"] = json!("\u{3000}island 2 ");
        spaced["labels"] = json!([{
            "net": " VIN ",
            "text": " VIN ",
            "x": 1,
            "y": 2,
            "bbox": [0, 0, 3, 4],
        }]);
        spaced["texts"] = json!([{
            "kind": " reference ",
            "text": " R1 ",
            "partId": " p1 ",
            "bbox": [0, 0, 3, 4],
        }]);
        let mut stripped = spaced.clone();
        stripped["parts"][0]["reference"] = json!("R1");
        stripped["parts"][0]["symbolRef"] = json!("R0402");
        stripped["parts"][0]["group"] = json!("module A");
        stripped["parts"][0]["island"] = json!("island 2");
        stripped["labels"][0]["net"] = json!("VIN");
        stripped["labels"][0]["text"] = json!("VIN");
        stripped["texts"][0]["kind"] = json!("reference");
        stripped["texts"][0]["text"] = json!("R1");
        stripped["texts"][0]["partId"] = json!("p1");

        let canonical = geometry_json(&spaced).expect("spaced payload hashes");
        assert_eq!(
            canonical,
            geometry_json(&stripped).expect("stripped payload hashes")
        );
        assert!(canonical.contains(r#""reference":"R1""#));
        assert!(canonical.contains(r#""island":"island 2""#));
        assert!(!canonical.contains(r#""reference":" R1 ""#));
    }

    #[test]
    fn optional_fields_follow_pythons_presence_rules() {
        let mut payload = minimal_payload();
        payload["parts"][0]["valueVisible"] = json!(false);
        payload["parts"][0]["group"] = json!("g1");
        // Empty is "not stated": the reader treats "" as no island at all.
        payload["parts"][0]["island"] = json!("");
        payload["texts"] = json!([{
            "kind": "value",
            "text": "10k",
            "bbox": [0, 0, 3, 4],
        }]);
        let expected = r#"{"junctions":[],"labels":[],"parts":[{"group":"g1","mirror":false,"partId":"p1","reference":"","rotation":0.0,"symbolHash":"<SYMBOL>","symbolRef":"synthetic-symbol","valueVisible":false,"x":10.0,"y":20.0}],"powerSymbols":[],"segments":[],"source":{"circuitSha256":"<SOURCE>","presentationSha256":"<SOURCE>"},"texts":[{"bbox":[0.0,0.0,3.0,4.0],"kind":"value","partId":"","rotation":0.0,"text":"10k","x":null,"y":null}]}"#
            .replace("<SYMBOL>", &"1".repeat(64))
            .replace("<SOURCE>", &"0".repeat(64));
        let canonical = geometry_json(&payload).expect("payload hashes");
        assert_eq!(canonical, expected);
        assert!(!canonical.contains("island"));

        let mut without_island = payload.clone();
        without_island["parts"][0]
            .as_object_mut()
            .expect("part object")
            .remove("island");
        assert_eq!(
            geometry_json(&without_island).expect("payload hashes"),
            canonical
        );

        // Stated ownership is part of the picture; a printed value is not stated.
        let mut stated = minimal_payload();
        stated["parts"][0]["island"] = json!("i1");
        let canonical = geometry_json(&stated).expect("payload hashes");
        assert!(canonical.contains(r#""island":"i1""#));
        assert!(!canonical.contains("valueVisible"));
    }

    #[test]
    fn expected_comparison_is_type_strict() {
        assert!(documents_match(&json!({"a": 1}), &json!({"a": 1})));
        assert!(documents_match(
            &json!({"a": [1, "x", true]}),
            &json!({"a": [1, "x", true]})
        ));
        assert!(documents_match(
            &json!({"a": 1, "b": 2}),
            &json!({"b": 2, "a": 1})
        ));

        // The F14 class: a golden that spells a boolean as 1, or a float as an
        // integer, must fail on this side exactly like on the Python side.
        assert!(!documents_match(&json!(true), &json!(1)));
        assert!(!documents_match(&json!({"ok": true}), &json!({"ok": 1})));
        assert!(!documents_match(&json!(1), &json!(1.0)));
        assert!(!documents_match(&json!(95.0), &json!(95)));
        assert!(!documents_match(&json!(0.0), &json!(-0.0)));
        assert!(!documents_match(&json!([1]), &json!([1.0])));
        assert!(!documents_match(&json!({"a": 1}), &json!({"a": "1"})));
        assert!(!documents_match(&json!({"a": 1}), &json!({"a": 1, "b": 2})));

        // An integer beyond u64::MAX is still an integer to Python (it keeps
        // every digit), so it must not equal the float spelling of the same
        // magnitude.
        let big = parse_json("100000000000000000000");
        assert!(documents_match(&big, &parse_json("100000000000000000000")));
        assert!(!documents_match(&big, &parse_json("1e20")));
        assert!(!documents_match(&big, &parse_json("100000000000000000001")));
    }

    #[test]
    fn canonical_json_escapes_only_what_python_escapes() {
        let mut payload = minimal_payload();
        payload["texts"] = json!([{
            "kind": "value",
            "text": "a\u{1}b\"c\\d\ne\tf \u{e9} \u{1f600}",
            "bbox": [0, 0, 1, 1],
        }]);
        let canonical = geometry_json(&payload).expect("payload hashes");
        assert!(
            canonical.contains("\\u0001"),
            "control char escape: {canonical}"
        );
        assert!(canonical.contains("\\\""), "quote escape: {canonical}");
        assert!(canonical.contains("\\\\"), "backslash escape: {canonical}");
        assert!(canonical.contains("\\n"), "newline escape: {canonical}");
        assert!(canonical.contains("\\t"), "tab escape: {canonical}");
        assert!(canonical.contains('\u{e9}'), "non-ASCII stays raw");
        assert!(canonical.contains('\u{1f600}'), "emoji stays raw");
        assert!(!canonical.contains("\\u00e9"), "no ensure_ascii escaping");
    }

    #[test]
    fn geometry_number_spelling_is_independent_of_the_input_spelling() {
        let spell = |value: Value| {
            let mut payload = minimal_payload();
            payload["junctions"] = json!([{"net": "N", "x": value, "y": 0}]);
            geometry_json(&payload).expect("payload hashes")
        };
        // 1e-7, 0.0000001 and 1.0e-7 are one number; Python writes 1e-07.
        assert_eq!(spell(json!(1e-7)), spell(parse_json("0.0000001")));
        assert_eq!(spell(json!(1e-7)), spell(parse_json("1.0e-7")));
        assert!(spell(json!(1e-7)).contains(r#""x":1e-07"#));
        // A big magnitude crosses into exponent form at decpt 17.
        assert!(spell(json!(1e16)).contains(r#""x":1e+16"#));
        assert!(spell(json!(1e15)).contains(r#""x":1000000000000000.0"#));
        // -0.0 is a different picture from 0.0, as it is in Python.
        assert_ne!(spell(json!(-0.0)), spell(json!(0.0)));
        assert!(spell(json!(-0.0)).contains(r#""x":-0.0"#));
    }

    #[test]
    fn geometry_refuses_numbers_the_reader_refuses() {
        let mut payload = minimal_payload();
        payload["parts"][0]["x"] = json!(true);
        assert!(
            geometry_json(&payload).is_err(),
            "a boolean is not a number"
        );

        let mut missing = minimal_payload();
        missing["parts"][0]
            .as_object_mut()
            .expect("part")
            .remove("y");
        assert!(geometry_json(&missing).is_err(), "x and y are required");

        let mut blank = minimal_payload();
        blank["parts"][0]["partId"] = json!("  ");
        assert!(geometry_json(&blank).is_err(), "a blank partId is refused");
    }

    #[test]
    fn digests_are_read_verbatim_not_stripped() {
        let digest = "2a".repeat(32);

        // Positive: exactly 64 lowercase hex characters are read as written.
        let mut good = minimal_payload();
        good["source"]["circuitSha256"] = json!(digest);
        good["parts"][0]["symbolHash"] = json!(digest);
        let canonical = geometry_json(&good).expect("a real digest is accepted");
        assert!(canonical.contains(&format!(r#""circuitSha256":"{digest}""#)));
        assert!(canonical.contains(&format!(r#""symbolHash":"{digest}""#)));

        // Negative: `_digest` matches the raw string, so padding is a refusal —
        // not something to trim away. Python refuses all of these.
        for padded in [
            format!(" {digest}"),
            format!("{digest} "),
            format!("\t{digest}\n"),
        ] {
            let mut bad_source = minimal_payload();
            bad_source["source"]["circuitSha256"] = json!(padded.as_str());
            assert!(
                geometry_json(&bad_source).is_err(),
                "padded source digest {padded:?} must be refused"
            );

            let mut bad_symbol = minimal_payload();
            bad_symbol["parts"][0]["symbolHash"] = json!(padded.as_str());
            assert!(
                geometry_json(&bad_symbol).is_err(),
                "padded symbolHash {padded:?} must be refused"
            );
        }

        // Uppercase hex is not a Python digest either (`[0-9a-f]` only).
        let mut uppercase = minimal_payload();
        uppercase["parts"][0]["symbolHash"] = json!(digest.to_uppercase());
        assert!(
            geometry_json(&uppercase).is_err(),
            "uppercase hex is refused"
        );

        // Every `_text` field still strips: the same padding is accepted there.
        let mut spaced_text = minimal_payload();
        spaced_text["parts"][0]["reference"] = json!(" R1 ");
        let canonical = geometry_json(&spaced_text).expect("text fields still strip");
        assert!(canonical.contains(r#""reference":"R1""#));
    }

    #[test]
    fn cli_envelope_round_trip_preserves_success_and_error_shapes() {
        let success = CliResult::success("smoke");
        let encoded = serde_json::to_value(&success).expect("success serializes");
        assert_eq!(encoded["schema"], CLI_RESULT_SCHEMA);
        assert_eq!(encoded["exitCode"], 0);
        assert_eq!(encoded["payload"]["businessLogic"], false);
        assert!(encoded.get("error").is_none());

        let failure = CliResult::failure("smoke", "bad smoke input");
        let encoded = serde_json::to_value(&failure).expect("failure serializes");
        assert_eq!(encoded["exitCode"], 2);
        assert_eq!(encoded["error"]["code"], "BAD_REQUEST");
        assert_eq!(encoded["error"]["message"], "bad smoke input");
        assert!(encoded.get("payload").is_none());
        let decoded: CliResult = serde_json::from_value(encoded).expect("failure round-trips");
        assert_eq!(decoded, failure);
    }
}
