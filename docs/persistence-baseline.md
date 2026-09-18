# Persistence baseline — the real-host checklist (M0-P0d)

> Written for Kimi + 岳翔宇 to execute **on the machine**, with EasyEDA Pro
> (host build **3.2.186**) and the connector running. Nothing here was measured
> yet: this file is the procedure, and the results are what turn "we think it
> persists" into a recorded fact.
>
> Background: the upstream `easyeda-agent` issue #216 reported a write-persistence
> defect (content lost after save + reopen) in v1.4.8. Our own behaviour has
> never been measured, so every line below is a measurement to take, not a claim.

## The three states, so the words mean something

| state | what it is | who can establish it |
|---|---|---|
| `not_placed` | **no** write was acknowledged — the page was never touched | `draw` |
| `unknown` | the run stopped with writes acknowledged or unanswered, so what is on the page cannot be stated | `draw` |
| `placed` | written, and the editor's own readback agrees | `draw` (the netlist compare) |
| `saved_unverified` | the save API answered ok, nothing checked the disk | `draw` |
| `saved_verified` | content survived a close-and-reopen and compared equal | **only scenario A** |

Only `saved_verified` is "persisted". `draw` can never reach it — `doc.open` moves
the focused tab without reloading it from disk, and there is no close-project
action in the protocol (`doc.list` / `doc.open` are the whole document surface) —
so it prints its state name with the qualifier spelled out, and scenario A is how
the third state gets established.

`not_placed` and `unknown` are the pair to keep straight, because they are what a
reader acts on. `not_placed` asserts an **absence**, so it needs evidence of the
absence; `unknown` is what an interrupted run gets, and it always comes with the
list of writes that landed (scenario B).

## Before you start

```bash
cd /e/boardwise

# 1. what we are running — record these two lines in the run log
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli bridge status
#    expect: "daemon up on 127.0.0.1:61190" and "connector: connected"
#    the connector build is what issue #216 is about; write it down.

# 2. clear the test project (岳翔宇's test project) to zero drawn parts.
#    Both scenarios below count parts, so a leftover part reads as a duplicate.

# 3. note the audit file you are about to write into
#    Windows: %USERPROFILE%\.boardwise\audit\<today>.jsonl
```

Every judgement below is a **count or an exit code**, never an impression. Where
a step is read-only, it says so.

---

## Scenario A — draw, snapshot, close, reopen, compare

**What it proves:** the content reached the file (`saved_verified`), or it did not.

### A1. Draw the page

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli draw \
    --from tests/fixtures/ch340_golden.epro2 --yes --render .tmp_a1_render.png
echo "draw exit: $?"
```

Expected, in the report:

```
persistence: saved_unverified — saved_unverified (the save API answered ok; NOT
verified on disk — no reopen has compared it)
  only a close-and-reopen that compares equal makes this saved_verified; see
  docs/persistence-baseline.md for the procedure
```

Judgement: exit 0 and the diff line `no differences — designs match`.
**`saved_verified` must NOT appear** — if it does, a draw has claimed a state it
cannot establish, which is a bug worth reporting on its own.

### A2. Snapshot the page as drawn (read-only)

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli persistence \
    --out .tmp_a2_before_reopen.json
echo "snapshot exit: $?"
```

Expected: `snapshot: .tmp_a2_before_reopen.json`, exit 0.

### A3. Close the project and reopen it — **the human step**

In EasyEDA Pro: close the **project** (not just the tab) and open it again from
the start page. Wait until the page is fully drawn before continuing. This step
is the whole point of the scenario; nothing in the bridge can do it.

### A4. Compare

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli persistence \
    --baseline .tmp_a2_before_reopen.json
echo "compare exit: $?"
```

Judgement:

| outcome | meaning |
|---|---|
| exit **0** + `persistence: saved_verified — the content survived a close-and-reopen` | **pass** — this is the only pass in this file |
| exit **1** + `NOT what was drawn` | **fail** — this is issue #216's shape; keep the output and the two snapshots |
| exit **1** + `primitives differ` | **fail**, and the per-type table says which half moved |
| exit **3** + `cannot decide` | **no verdict** — one side had no netlist text or no readable geometry. Record it as undecidable; do **not** record it as a pass |

A pass also writes one line to the audit log; check it arrived:

```bash
PYTHONPATH=src ./.venv/Scripts/python -c "
import json, pathlib, os
home = pathlib.Path(os.environ['USERPROFILE']) / '.boardwise' / 'audit'
for path in sorted(home.glob('*.jsonl')):
    for line in path.read_text(encoding='utf-8').splitlines():
        rec = json.loads(line)
        if rec.get('action') in ('persistence.verified', 'draw.persistence'):
            print(rec)
"
```

Expected: a `persistence.verified` record with `"persistence": "saved_verified"`.

---

## Scenario B — the daemon dies mid-draw

**What it proves:** a dead transport is reported as unknown, and **nothing is
replayed** afterwards.

> **Measured 2026-09-18 (first run of this checklist).** `taskkill //F` on the
> daemon mid-draw left **5 parts on the P4 page** (audit log: `sch.doc.new` ×1 and
> `sch.place_component` ×5 acknowledged), and the draw report said
> `persistence: not_placed — nothing was written`. That was a **lie**, and the
> most dangerous kind this milestone can tell: a reader who believed it would
> redraw onto a page that already had the parts, ending with two sets of them on
> one sheet. Root cause and fix are in `tasks/009d-persistence-baseline.md`
> (follow-up section): a disconnect was not treated as "outcome unknown", and
> `not_placed` was inferred from "the run did not finish looking". The exit code
> in that first run was not captured (a shell artefact — the pipeline's `$?`
> reported `tail`'s status, not the draw's), so **B3 below is still to be run.**
>
> **B3 measured 2026-09-18 (second run, after the 009d2 fix).** The daemon was
> `taskkill //F`'d mid-draw again, with the exit code captured to a file — no
> pipe in between. The draw reported `persistence: unknown — the run stopped
> before the page could be read back`, listed **7 acknowledged writes** by name
> (`sch.doc.new` ×1, `sch.place_component` ×6) as "their content IS on the
> page", and **104 unanswered writes** with an explicit "do NOT assume they are
> absent, and do not redraw onto this page" warning. **Exit code: 3.** The
> first run's lie — `not_placed — nothing was written` with parts on the page —
> is gone. Verdict: **pass**.

### B1. Start a draw, then kill the daemon while it runs

```bash
# terminal 1
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli draw \
    --from tests/fixtures/ch340_golden.epro2 --yes
# record the exit code properly — no pipe between the command and $?
echo "draw exit: $?"
# terminal 2, a few seconds in — the daemon runs in its own process:
# Ctrl-C the `bridge start` process (or close its window).
```

Expected in terminal 1: failed actions reported per action with the transport
error, and the run ending **non-zero**. Judgement: the report **names the action
that died**, does not claim success, and does **not** say "nothing was written".

### B2. Look before touching anything

Note the time before the run, so the log excerpt below can be scoped to it:

```bash
export RUN_STARTED_AT=$(PYTHONPATH=src ./.venv/Scripts/python -c "import time; print(time.time())")
# ... now run B1 ...
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli bridge start   # terminal 3
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli bridge status
```

Judgement, from the audit log — the page must have been asked for exactly once:

```bash
PYTHONPATH=src ./.venv/Scripts/python -c "
import json, pathlib, os, collections
home = pathlib.Path(os.environ['USERPROFILE']) / '.boardwise' / 'audit'
counts = collections.Counter()
for path in sorted(home.glob('*.jsonl')):
    for line in path.read_text(encoding='utf-8').splitlines():
        rec = json.loads(line)
        if rec.get('ts', 0) > float(os.environ['RUN_STARTED_AT']):
            counts[rec.get('action')] += 1
print(counts['sch.doc.new'], 'x sch.doc.new', counts['sch.place_component'], 'x place_component')
"
```

Judgement: **one** `sch.doc.new` for the aborted run — a second one means
something retried a create. Then, and only then, decide by hand whether to redraw.

### B3. The report must not call the page untouched

Two lines of the report carry the verdict; read them, not the impression:

* `persistence:` must be **`unknown`**, never `not_placed`. `not_placed` asserts
  that no write was acknowledged, and the audit line above just proved otherwise;
* it must list the **acknowledged** writes ("their content IS on the page") and the
  **unanswered** ones, and warn against redrawing onto the page;
* the exit code must be **3** — unknown, not "the diff disagreed". Record it with
  `echo "draw exit: $?"` and no pipe in between, which is how the first run of
  this checklist lost the number.

---

## Scenario C — a write times out

**What it proves:** a timeout is not read as "nothing happened", and the page is
re-read before anything is concluded.

**The means, stated plainly.** The daemon's per-action deadlines are module
constants (`bridge/protocol.py`: 30 s / 60 s / 60 s) with **no flag or environment
override**, so a *daemon-side* timeout cannot be deliberately constructed — see
the gap section below. What **is** constructible is the connector's own deadline,
which is the same principle one layer down: `timeoutMs` is a per-call parameter,
clamped to 200..60000 ms.

### C1. Make the library cold, then force a 200 ms deadline

Restart EasyEDA Pro first (a warm library resolves instantly and the timeout will
not trip).

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli bridge call \
    --action sch.place_component \
    --params '{"keyword":"AMS1117","x":400,"y":600,"timeoutMs":200}'
echo "exit: $?"
```

Expected, one of:

* the connector reports a timeout **and what landed near the point** — this is
  the "timed out but it may have landed" answer, and the correct reading is
  *unknown*, not *nothing*;
* or it resolves inside 200 ms (warm library) — in which case cold the library
  again and repeat. Record which happened.

Judgement: the answer must never be a bare success/failure with no statement
about what is on the page. If it says nothing about the page, stop and report —
that is the defect this scenario exists to find.

### C2. The page after the timeout

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli persistence --out .tmp_c2_after_timeout.json
```

Judgement: read the snapshot's `geometry.components` and compare the count with
the part you asked for. Both answers ("it landed" / "it did not") are acceptable;
an **unexamined** answer is not. Then decide by hand whether to draw — do **not**
re-issue the placement blindly; a retry after a write that landed is two parts on
one spot.

### C3. The draw-side behaviour

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli draw \
    --from tests/fixtures/ch340_golden.epro2 --yes
echo "draw exit: $?"
```

Judgement: if any call times out, the report must contain a `persistence.<action>`
line whose summary says **UNKNOWN** and **nothing was retried**, and the exit code
must be **3** even when the diff matched. An exit 0 alongside a timed-out write is
the bug this scenario is for.

---

## Scenario D — the same spec drawn twice

**What it proves:** one draw creates one page, and no page ends up with two copies.

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli draw \
    --spec blocklib/specs/ams1117_smoke.json --yes
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli draw \
    --spec blocklib/specs/ams1117_smoke.json --yes
```

Then list the project's documents and count parts per page:

```bash
PYTHONPATH=src ./.venv/Scripts/python -m boardwise.cli bridge call --action doc.list
```

Judgement:

* **two** schematic pages exist, one per run (a draw always creates its own page);
* **neither** page holds two copies of the block — each page's readback shows the
  single expected part count. The replay layer's idempotence is already tested
  offline; this is the end-to-end version of it.
* a page carrying twice the parts means a write was replayed, and the audit log
  will show two `sch.doc.new` for one run.

---

## Known gap — a daemon-side timeout has no lever on this host

Say this out loud when reporting results, so nobody later reads the offline
coverage as a hardware measurement:

* the daemon's deadlines are constants with no override (`bridge/protocol.py`,
  `ACTION_TIMEOUT` / `SCREENSHOT_TIMEOUT` / `PLACEMENT_TIMEOUT`), so a timeout can
  only be *waited for*, never *constructed*, on the real host;
* the daemon-side timeout path — read the page back, report UNKNOWN, never retry,
  exit 3 — is therefore covered **offline only**, by injecting the daemon's own
  error (`BridgeError(ErrorCodes.TIMEOUT, …)`) in
  `tests/test_candidate_draw.py::test_a_timed_out_write_reads_the_page_back_and_is_never_retried`
  and its neighbours;
* scenario C covers the connector-side deadline on hardware, which is the same
  principle at a layer where a lever does exist.

If a real daemon-side timeout is ever needed, the honest way to get one is to make
the editor busy until the 30 s budget expires — record it as such rather than as a
controlled experiment.

## How the two logs differ

| question | where it is answered |
|---|---|
| what did each action do, and did it answer? | `~/.boardwise/audit/<date>.jsonl` — one line per action, `{ts, action, role, ok, ms}` |
| how far did the write get? | the same file, the `draw.persistence` line — its `persistence` field is the state name, and it is the only field to read |
| did it survive a reopen? | the `persistence.verified` line, written only by a passing scenario A |

The daemon's own records never carry the action's payload, so `saved: true` is not
in the log and never was; the persistence field is what replaces it.
