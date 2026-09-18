# Block-spec validation (task 008c, item 4; 009-M0 P0)

A board spec is a claim: *these* blocks, *these* numbers, *these* connections.
`src/boardwise/engines/validate_spec.py` is what makes the claim answerable
without a model in the loop, and without looking at the answer.

The gates come in two families, because "a user is drawing a new board" and
"we are grading a generation run" are different questions:

* **product gates** — always run: sources, pin budget, levels, power tree;
* **benchmark gate** — the closed book, run only with `--benchmark`: nothing
  generation-side may trace to the target board, and every field must cite a
  declared input. A user drawing a new board owes sound electricity, not a
  bibliography, so the product run reports the closed book as *skipped* with
  the reason rather than demanding a golden board to grade against.

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli validate \
    --spec blocklib/specs/ch340g_usb_uart.json

# grading a generation run adds the closed book:
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli validate \
    --spec blocklib/specs/ch340g_usb_uart.json \
    --benchmark --target tests/fixtures/ch340_golden.epro2
```

`draw --spec …` runs the product gates before assembling anything; a refused
spec draws nothing (exit 2, and the bridge is never opened). Nothing is cached:
every run re-reads the file, and the report's first line carries
`spec sha256:<12 hex>` so a verdict names the exact bytes it belongs to.

Exit **0** nothing blocks / **1** something blocks / **2** bad input.

## The gates, in the order they run

| gate | family | asks | blocks when |
|---|---|---|---|
| **closed-book** | benchmark only | did this page come from somewhere other than the board it will be graded against, and can every field say where it came from? | a template traces to the target board; the spec text names it; a block / value / connection cites nothing, or cites something never declared |
| **sources** | product | is every declared input real? | a declared file is not there; a cited part is not on the shelf; a part citation with no library supplied is undecidable |
| **pin-budget** | product | do the firmware's pins and the schematic's MCU agree, and fit? | a pin the symbol does not have; more ports used than the part exposes |
| **levels** | product | do the ports on one signal net speak one IO domain? | two domains on a net with no declared shifter on it |
| **power-tree** | product | does every rail have exactly one source feeding what the sinks ask for? | zero sources, two sources, or a sink asking for another voltage |

Every gate runs even when an earlier one failed: a page that is both copied and
mis-wired wants both facts said at once.

## Two statuses that are not "pass"

* **undecidable** — something blocks and cannot be judged, usually because a
  port says nothing. It **blocks exactly like a violation**. A green report
  nobody re-reads is worth less than a stop.
* **skipped** — the gate's input was never supplied (no pin table ⇒ no MCU to
  budget), or it is the closed book outside `--benchmark`. Skipped does **not**
  block, because a board with no MCU firmware is real and a new board has no
  target, but it prints *why nothing was checked* so nobody mistakes it for
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

## Evidence: every field cites a declared input (benchmark mode)

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
note; missing or undeclared evidence is a violation **of the closed book**,
which runs under `--benchmark`. The product half of the same discipline is the
**sources** gate: whatever a spec *does* declare must be real.

`--target` (benchmark mode) may be given more than once. Give **every alias of
the board** being generated — the export *and* the local project — because one
board is often one design under two names, and "we re-exported it" must not be a
loophole. The dated suffix is stripped, so `ProPrj_box_2026-09-17.epro2` and
`ProPrj_box` are the same board; `ch340x` is never condemned for being named
like `ch340`.

## Files

| path | what |
|---|---|
| `src/boardwise/engines/validate_spec.py` | the gates and the report |
| `src/boardwise/core/portmeta.py` | the port-metadata sidecar |
| `blocklib/blocks.portmeta.json` | the CH340 four: every port declared, with provenance |
| `tests/test_validate_spec.py` | 72 tests: each gate asked the question it exists for, then asked it in the shape that must be refused |
| `tests/test_spec_cli.py` | the CLI decisions: validation precedes assembly and any bridge call; `--benchmark` splits the families |
