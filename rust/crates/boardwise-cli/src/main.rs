//! Minimal Rust CLI process boundary for 540C contract smoke and differential
//! runs.
//!
//! `differential` mirrors the Python `tools.differential` surface where a script
//! can observe it: both `--flag PATH` and `--flag=PATH`, a repeated flag takes
//! its last value, no `--cases`/`--root` means "the repository's own case book"
//! and "the repository root" (never the current directory), `-h`/`--help` prints
//! help on stdout and exits 0, and a usage error is plain usage text on stderr
//! with exit 2. Only a *request* the runner cannot carry out — an unreadable
//! book, a schema refusal, an unknown case kind, an unwritable `--output` —
//! becomes the one `boardwise.cli-result/1` envelope on stderr with exit 2.
//! A completed run still prints the report on stdout and exits 0 (every golden
//! agrees) or 1 (a golden differs).
//!
//! `smoke` keeps the shape it always had: its refusal is the structured
//! envelope (see `tests/smoke.rs`), because it is the contract smoke surface and
//! not the differential compatibility surface.

use boardwise_core::{CliResult, ContractError, run_cases};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

const DIFFERENTIAL_USAGE: &str =
    "usage: boardwise-cli differential [--cases PATH] [--root DIR] [--output PATH]";

const DIFFERENTIAL_HELP: &str = "\
usage: boardwise-cli differential [--cases PATH] [--root DIR] [--output PATH]

Run one 540C differential case book and print the language-neutral report.

options:
  -h, --help     show this help and exit
  --cases PATH   case book (default: <repository>/contracts/differential/cases.json)
  --root DIR     case input root (default: <repository>)
  --output PATH  also write the report as JSON; stdout still carries the report

Both `--flag PATH` and `--flag=PATH` are accepted, and a repeated flag takes its
last value, the same as the Python `argparse` surface.

Exit codes: 0 every golden agrees, 1 a golden differs, 2 the request failed (one
boardwise.cli-result/1 envelope on stderr; usage errors keep plain usage text).
";

struct Output {
    value: Value,
    exit_code: i32,
    stderr: bool,
}

enum Run {
    Report(Output),
    Help(&'static str),
}

/// Why the process is about to fail, and which surface states it.
enum Failure {
    /// A flag syntax problem: usage text on stderr, exit 2, never the envelope.
    Usage(String),
    /// A request the runner could not carry out: one cluster of JSON, exit 2.
    Domain(ContractError),
}

impl From<ContractError> for Failure {
    fn from(error: ContractError) -> Self {
        Self::Domain(error)
    }
}

impl From<std::io::Error> for Failure {
    fn from(error: std::io::Error) -> Self {
        Self::Domain(error.into())
    }
}

impl From<serde_json::Error> for Failure {
    fn from(error: serde_json::Error) -> Self {
        Self::Domain(error.into())
    }
}

fn usage(detail: impl std::fmt::Display) -> Failure {
    Failure::Usage(format!(
        "{DIFFERENTIAL_USAGE}\nboardwise-cli differential: error: {detail}\n"
    ))
}

/// The repository this binary was built in — the Python runner's `ROOT`
/// (`Path(__file__).resolve().parents[1]`), not the current directory.
fn repository_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .expect("repository root")
        .to_path_buf()
}

fn required_value(
    arguments: &mut impl Iterator<Item = String>,
    flag: &str,
) -> Result<String, Failure> {
    match arguments.next() {
        Some(value) if !value.starts_with('-') => Ok(value),
        Some(value) => Err(usage(format!(
            "{flag}: expected one argument, got {value:?}"
        ))),
        None => Err(usage(format!("{flag}: expected one argument"))),
    }
}

fn flag_value(
    arguments: &mut impl Iterator<Item = String>,
    flag: &str,
    attached: Option<&str>,
) -> Result<String, Failure> {
    match attached {
        Some(value) => Ok(value.to_owned()),
        None => required_value(arguments, flag),
    }
}

fn differential(rest: &mut impl Iterator<Item = String>) -> Result<Run, Failure> {
    let mut cases: Option<String> = None;
    let mut root: Option<String> = None;
    let mut output: Option<String> = None;
    while let Some(argument) = rest.next() {
        let (flag, attached) = match argument.split_once('=') {
            Some((flag, value)) => (flag, Some(value)),
            None => (argument.as_str(), None),
        };
        match flag {
            "-h" | "--help" if attached.is_none() => return Ok(Run::Help(DIFFERENTIAL_HELP)),
            "--cases" | "--root" | "--output" => {
                let value = flag_value(rest, flag, attached)?;
                match flag {
                    "--cases" => cases = Some(value),
                    "--root" => root = Some(value),
                    _ => output = Some(value),
                }
            }
            other => return Err(usage(format!("unrecognized argument {other:?}"))),
        }
    }
    // Python's defaults are the repository itself, independent of `--root`:
    // `--root DIR` alone still reads the repository's case book.
    let root = root.map_or_else(repository_root, PathBuf::from);
    let cases = cases.map_or_else(
        || repository_root().join("contracts/differential/cases.json"),
        PathBuf::from,
    );
    let report = run_cases(&cases, &root)?;
    let value = serde_json::to_value(&report)?;
    // Write before printing: a failed write must leave stdout empty, so nobody
    // reading stdout sees a report that contradicts the exit code.
    if let Some(path) = output.filter(|path| !path.is_empty()) {
        fs::write(path, serde_json::to_string_pretty(&value)? + "\n")?;
    }
    Ok(Run::Report(Output {
        value,
        exit_code: i32::from(!report.ok),
        stderr: false,
    }))
}

fn smoke(rest: &mut impl Iterator<Item = String>) -> Result<Run, Failure> {
    let mut command_name = None::<String>;
    let mut fail = false;
    while let Some(argument) = rest.next() {
        match argument.as_str() {
            "--command" => {
                if command_name.is_some() {
                    return Err(ContractError::Shape(
                        "--command may be given only once".to_owned(),
                    )
                    .into());
                }
                command_name = Some(next_value(rest, "--command")?);
            }
            "--fail" => fail = true,
            other => {
                return Err(
                    ContractError::Shape(format!("unknown smoke argument {other:?}")).into(),
                );
            }
        }
    }
    let command_name = command_name
        .ok_or_else(|| ContractError::Shape("smoke requires --command NAME".to_owned()))?;
    if command_name.trim().is_empty() {
        return Err(ContractError::Shape("smoke --command must not be empty".to_owned()).into());
    }
    let result = if fail {
        CliResult::failure(command_name, "business-free smoke refusal")
    } else {
        CliResult::success(command_name)
    };
    let exit_code = result.exit_code;
    Ok(Run::Report(Output {
        value: serde_json::to_value(result)?,
        exit_code,
        stderr: fail,
    }))
}

/// `smoke` keeps the parameter reading it always had (a missing value is its
/// structured refusal), which is why it does not share `required_value`.
fn next_value(
    arguments: &mut impl Iterator<Item = String>,
    flag: &str,
) -> Result<String, ContractError> {
    arguments
        .next()
        .ok_or_else(|| ContractError::Shape(format!("{flag} requires a value")))
}

fn run(arguments: Vec<String>) -> Result<Run, Failure> {
    let Some(command) = arguments.first().cloned() else {
        return Err(ContractError::Shape(
            "usage: boardwise-cli differential [--cases PATH] [--root DIR] [--output PATH] \
             | boardwise-cli smoke --command NAME [--fail]"
                .to_owned(),
        )
        .into());
    };
    let mut rest = arguments.into_iter().skip(1);
    match command.as_str() {
        "differential" => differential(&mut rest),
        "smoke" => smoke(&mut rest),
        other => Err(ContractError::Shape(format!(
            "unknown command {other:?}; expected differential or smoke"
        ))
        .into()),
    }
}

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let command = arguments
        .first()
        .cloned()
        .unwrap_or_else(|| "cli".to_owned());
    match run(arguments) {
        Ok(Run::Report(output)) => {
            let text = serde_json::to_string_pretty(&output.value)
                .expect("a structured CLI result always serializes")
                + "\n";
            if output.stderr {
                eprint!("{text}");
            } else {
                print!("{text}");
            }
            std::process::exit(output.exit_code);
        }
        Ok(Run::Help(text)) => {
            print!("{text}");
            std::process::exit(0);
        }
        Err(Failure::Usage(message)) => {
            eprint!("{message}");
            std::process::exit(2);
        }
        Err(Failure::Domain(error)) => {
            let result = CliResult::failure(command, error.to_string());
            let text = serde_json::to_string_pretty(&result)
                .expect("a structured error always serializes")
                + "\n";
            eprint!("{text}");
            std::process::exit(2);
        }
    }
}
