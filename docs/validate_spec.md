# Block-spec validation — the four gates (task 008c, item 4)

A board spec is a claim: *these* blocks, *these* numbers, *these* connections.
`src/boardwise/engines/validate_spec.py` is what makes the claim answerable
without a model in the loop, and without looking at the answer.

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli validate \
    --spec blocklib/specs/ch340g_usb_uart.json \
    --target tests/fixtures/ch340_golden.epro2 \
    --library blocklib/parts.json \
    --root .
```

Exit **0** nothing blocks / **1** something blocks / **2** bad input.

## The four gates, in the order they run

| gate | asks | blocks when |
|---|---|---|
| **closed-book** | did this page come from somewhere other than the board it will be graded against, and can every field say where it came from? | a template traces to the target board; a block / value / connection cites nothing, or cites something never declared |
| **pin-budget** | do the firmware's pins and the schematic's MCU agree, and fit? | a pin the symbol does not have; more ports used than the part exposes |
| **levels** | do the ports on one signal net speak one IO domain? | two domains on a net with no declared shifter on it |
| **power-tree** | does every rail have exactly one source feeding what the sinks ask for? | zero sources, two sources, or a sink asking for another voltage |

Every gate runs even when an earlier one failed: a page that is both copied and
mis-wired wants both facts said at once.

## Two statuses that are not "pass"

* **undecidable** — something blocks and cannot be judged, usually because a
  port says nothing. It **blocks exactly like a violation**. A green report
  nobody re-reads is worth less than a stop.
* **skipped** — the gate's input was never supplied (no pin table ⇒ no MCU to
  budget). Skipped does **not** block, because a board with no MCU firmware is
  real, but it prints *"nothing was checked"* so nobody mistakes it for
  agreement.

## Where the port metadata lives

Three optional fields (schema version stays 1; templates written before this
still load byte-for-byte):

| field | allowed on | says |
|---|---|---|
| `direction` | power, gnd | `source` or `sink` — the one thing the tree needs in order to count |
| `voltage` | power | the rail's nominal value, written as the design writes it (`"3V3"`, `"5V"`) |
| `level` | signal | the IO domain it speaks (`"3V3"`, `"5V"`, `"USB"`) |

One knob per job: `direction` or `voltage` on a signal port, and `level` on a
power or ground port, are refused at load time — otherwise the power tree and
the level gate could disagree about one port without either being wrong.

**Board-extract blocks keep them in a sidecar**, `blocklib/blocks.portmeta.json`,
applied at load time:

```python
spec = load_board_spec(path, port_meta=load_port_meta("blocklib/blocks.portmeta.json"))
```

The reason is the one this project has hit twice already (006b golden overrides,
008b part corrections): `tests/test_cut.py` holds every committed `ch340_*`
block to be byte-for-byte what re-running the cut produces, and a declaration is
not something the board's geometry says. The consequence is deliberate and
visible — **reading the same block without the sidecar answers "cannot tell",
which blocks.** Hand-authored blocks (datasheet / textbook) may carry these
fields in the file itself; nothing about them is reproduced from a board.

Each entry also carries `provenance`, which is appended in square brackets to
the notes it contributes, so every voltage in the file names its authority.

## Evidence: every field cites a declared input

```jsonc
"references": [
  {"id": "intent", "kind": "intent", "path": "inputs/smart_pillbox/intent.md"},
  {"id": "pins",   "kind": "pintable", "path": "inputs/smart_pillbox/pintable.json"},
  {"id": "ldo",    "kind": "datasheet", "path": "inputs/.../AMS1117-3.3.pdf", "note": "p.5"},
  {"id": "rt9013", "kind": "part", "ref": "ic.rt9013_33gb"},
  {"id": "shifter","kind": "textbook", "note": "bidirectional mos level shifter"}
]
```

The vocabulary is **closed** (`intent` / `pintable` / `datasheet` / `part` /
`textbook`) for the same reason the pin table's functions are: an invented kind
would let "some unspecified source" through a gate that exists precisely to
forbid that. Each kind says where its identity lives — a file for the first
three, a shelf key for a part, and nothing but a name for a textbook.

Blocks take `"evidence": [id, ...]`; values go in the parallel map
`param_evidence` (`"power.u3_value": ["ldo"]`) so existing `params` need no
rewriting; connections take `"evidence"` too. A declared input nobody cites is a
note; missing or undeclared evidence is a violation.

`--target` may be given more than once. Give **every alias of the board** being
generated — the export *and* the local project — because one board is often one
design under two names, and "we re-exported it" must not be a loophole. The
dated suffix is stripped, so `ProPrj_box_2026-09-17.epro2` and `ProPrj_box` are
the same board; `ch340x` is never condemned for being named like `ch340`.

## Files

| path | what |
|---|---|
| `src/boardwise/engines/validate_spec.py` | the four gates and the report |
| `src/boardwise/core/portmeta.py` | the port-metadata sidecar |
| `blocklib/blocks.portmeta.json` | the CH340 four: every port declared, with provenance |
| `tests/test_validate_spec.py` | 68 tests: each gate asked the question it exists for, then asked it in the shape that must be refused |
