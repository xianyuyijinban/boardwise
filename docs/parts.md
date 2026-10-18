# The curated part library and selection (task 008b)

008c will have a model propose blocks; for that to be more than a suggestion it
needs a **deterministic shelf** to pick from. This file documents the shelf, the
tool that fills it, and the picker — including the two rules that make a lookup
trustworthy enough to place a part with.

## What is on the shelf

`blocklib/parts.json` — one entry per **verified real part**:

| Field | Meaning |
|---|---|
| `key` | `<shelf>.<slug>` — `res.5k1_0402`, `ic.stm32g431rbt6`. Unique; ambiguous slugs get the C-number appended |
| `value` | the schematic value (`470Ω`, `100nF`), verbatim |
| `mpn`, `lcsc`, `manufacturer` | the identity: manufacturer part number, LCSC C-number, maker |
| `deviceUuid` + `libraryUuid` | the pair `lib.device.get` / `sch.place_component` need. **The library's** device uuid, not the project-local one (006b measured that a project-local uuid answers `found:false`) |
| `footprint_name` | the **library** footprint name (`R0402`) — never the human label (`0603`) |
| `footprint_name_verified` | `true` only after the bridge confirmed it, `false` if it could not be read, `null` if nobody has asked |
| `params` | the electrical/mechanical parameters **verbatim, units kept** (`"Resistance": "5.1kΩ ±1%"`). No normalisation |
| `datasheetUrl`, `datasheetPdfUrl` | declared by the source; the PDF URL is empty when the source has none, rather than guessed |
| `basic` | JLC basic-part flag: `true`/`false` **with evidence**, `null` without |
| `category` | the electrical class from the vocabulary — absent means "not classified", which a rule reports as UNKNOWN rather than guessing from the designator |
| `facts` | datasheet claims (039's vocabulary: `supply_pins` / `required_caps` / `nc_pins` / `must_connect` / `pull_required` / `ldo` / `led`), each with its own page-cited provenance. Since issue #17 an `ldo` record may also carry the optional `fixed_output` (`{"volts": 3.3, "provenance": "…, p.3 …"}`): the domain inference then quotes that page instead of decoding the part number, and labels an entry that has none as the **guess** it is |
| `facts_verified` | the gate: written **only when false**, and absent means true. A candidate (`false`) records a claim nobody has reviewed; no rule acts on it until a human flips the flag in review |
| `provenance` | `kind` (`board-extract` / `catalog-select` / `manual-curation`), `source`, and `designators` — the accumulating track record |
| `notes` | anything a reader must know: a corrected footprint spelling, an unrecognised part class, a disambiguated key |

Two properties are deliberately *tri-state* (`true` / `false` / `null`). "No
evidence" and "no" are different answers, and a library whose `basic: false`
means "we never looked" is worse than one that says `null`.

### Two shelves, one reading (191B)

A frozen exe has **two** shelves: the copy it carries
(`resources/blocklib/parts.json`, inside the PyInstaller extraction directory —
read-only, and dead when the process exits) and the user's own
`~/.boardwise/parts.json` (`BOARDWISE_HOME` wins over `~`), which is what
`parts add` / `parts fetch` write. 186-H2 made the first write copy the bundled
file there and made the read side prefer it — which fixed "the curation went to
a file no rule opens" and left the next hole: the user's file is a **snapshot**
of the bundled shelf, so every entry a later **upgrade** adds to the exe's copy
was shadowed by the whole shelf.

191B closes it by merging, not by choosing:

* the **read** is the pair — the user's shelf first, the bundled one underneath
  (`rules.facts.default_library_paths()` → `read_default_library()`);
* the **write** target stays one file, the user's
  (`default_library_path()`), because that is the path `report.json` quotes back
  in its clearing instruction;
* the merge key is the **part**, not the file: shelf key, MPN or C-number. The
  user's entry wins for the same part; everything else on the exe's shelf stays
  visible. An explicit `--library` names **one** shelf and is never merged;
* `parts list` shows what the merge did — one row per entry, with `user`,
  `builtin` or `user-overrides-builtin` in the last column (`-` from a checkout,
  where there is one shelf and a label would invent a second). `--json` carries
  the same labels under `entries[].source`, plus `shelfPaths` / `originCounts`.

```bash
boardwise parts list                    # the shelf this install reads, labelled
boardwise parts list --query CH340N     # one part, either shelf
boardwise parts list --category ic --json
```

## The fact intake: `missing` → `add` → curation → the gate (039)

The rules cannot decide anything about a part the shelf knows no facts for, and
until 039 nothing said *which* facts were owed. Three offline commands close that
loop; none of them touches the bridge.

```bash
boardwise parts missing --file board.epro2          # what the shelf owes this board
boardwise parts missing --file board.eprj3 --json report.json
boardwise parts show CH340N                         # one entry, in full
boardwise parts show ic.ch340n --json entry.json
boardwise parts list                               # every entry + which shelf it came from (191B)
boardwise parts add TPL2981-30DBVR --lcsc C9900000001
```

* **`missing`** lists every `U`-prefixed part of a project with the fact keys the
  shelf has not recorded for it, in vocabulary order, and the identity the rules
  will look up (MPN first, then the C-number, then the **device name** —
  `resolve_facts`' exact-match order, so the list and the verdicts can never
  disagree; a name hit is labelled `matchedBy: name`, because it is weaker
  evidence than an MPN or a C-number and must not read the same). **Exit 0
  always**: a non-empty
  list is "the shelf owes work", not a failure. Exit 2 is reserved for an input
  that cannot be read. A part is owed until it records *every* key, which is the
  strict reading — an entry with three of seven keys still lists four. A gated
  candidate's *claim* counts toward the recorded side (the claim is real work
  already done); what the gate withholds is trust, and the row says so with
  `unverified`.
* **`show`** dumps one entry: identity, every fact in full, each provenance line,
  and the gate. Lookup is exact key → exact MPN → case-insensitive either; a miss
  is exit 2 **with** up to five substring neighbours, because "no such part" with
  no "did you mean" is a dead end.
* **`fetch`** (039 批②) gets a datasheet and turns it into a **candidate** entry:
  the engineer's channel is `--file <local PDF>`; otherwise the entry's own LCSC
  links are downloaded (`datasheetPdfUrl` first, then the product page) into
  `.tmp_datasheets/` (gitignored). Either way the PDF's text is dumped page by
  page beside it (`<MPN>.txt`, `<<<page N>>>` markers so a fact can cite its
  page), a narrow extractor proposes `supply_pins` / `required_caps` / `nc_pins`
  records that quote their own line — and the entry is written with
  `facts_verified: false`. Two deliberate limits: an entry whose facts already
  drive rules is never overwritten without `--force` (an unverified guess does
  not replace something a human vouched for), and when the extractor proposes
  nothing the library is not touched at all (there is no claim, so the gate stays
  open). The third channel — the vendor's own site — is the AI's, via WebSearch;
  the failure output hands over the queries to start from.
* **`add`** appends a candidate: identity only, `category` empty, no facts,
  `facts_verified: false`, `provenance.kind: manual-curation`. A duplicate MPN or
  C-number is refused (exit 2) pointing at `parts show`. The write is a
  **JSON-document** edit — a library-wide re-serialisation would reorder keys
  inside existing entries — so it backs the file up to a `.tmp` sibling, re-parses
  the result with the real validator, and rolls back if the validator refuses.
  `--json` is written **before** the shelf is touched (188B): a json path that
  cannot be opened (a directory, a missing parent, a read-only volume) exits 2 with
  the shelf byte-identical, instead of leaving a moved shelf behind a failed run.

### The manual facts path: `parts add --facts … --verified` (186)

039 built the gate; 186 built the **route through it**. An AI that reads a
datasheet had no first-class way to put what it found into the shelf, so the only
way to close a part's gate was to edit the JSON by hand — and the field reading of
"feed it a PDF" (which only writes a candidate, §above) was that the gate could
not be closed at all.

```bash
# one record at a time …
boardwise parts add ACME-PWR-1000 --lcsc C9900000001 --category ic.ldo \
  --fact 'nc_pins={"pins":["2"],"provenance":"file:acme.pdf p.4"}'
# … or the whole object, which is what an AI writes after reading the PDF —
# with the uuid pair resolved by the bridge in the same command (187c)
boardwise parts add ACME-PWR-1000 --lcsc C9900000001 --category ic.ldo \
  --facts facts.json --verified --resolve
# the pair may still be given by hand instead (a machine with no bridge)
boardwise parts add ACME-PWR-1000 --lcsc C9900000001 --category ic.ldo \
  --facts facts.json --verified \
  --device-uuid <32 hex> --library-uuid <32 hex>
```

* `--facts <file.json>` takes the facts object; `parts fetch`'s
  `<stem>.candidate.json` (`{"label","url","facts"}`) is accepted **as it stands**,
  so what an extractor proposed can be handed straight back in. `--fact KEY=JSON`
  is the same thing one record at a time; the value is JSON because every fact
  kind is a record, not a scalar.
* The facts go through `entry_from_json` — the same validator every entry in the
  file passes — so a fact with no page-cited provenance is refused wherever it
  came from, and a refused entry leaves no bytes behind.
* **`--verified` is the declaration**, and it is never implied: without it the
  facts are a candidate's claim and drive nothing. With it, the entry starts
  driving rules. It needs facts (verifying nothing is not a statement) and, per
  039's schema rule, the uuid pair — the entry must be placeable, so `add` prints
  where those ids come from (`--resolve` on this command, `parts select
  --resolve`, or the entry already on the shelf).
* Facts given for an identity **already on the shelf** update that entry: the
  candidate `parts fetch` left behind is the case this exists for. Identity is not
  touched by that path (a differing C-number is refused), and an entry whose facts
  already drive rules is not overwritten without `--force` — the same guard
  `fetch` applies.
* The duplicate check reads the **merged** shelf, not only the file the write
  lands in (192C). A part the exe's own shelf already carries is a duplicate too,
  and gets the same refusal: without `--force`, a hit on the *bundled* shelf is
  never shadowed, because a candidate keyed on the same MPN / C-number wins the
  merge (191B) and takes the curated entry's verified facts with it. `--force`
  writes your entry into the user's shelf, and the output names the bundled entry
  it overrides.

The same flow is what the report's 未审器件 section points at: **给 PDF ≠ 清闸**.

### Bulk addressing: `parts hunt` (520)

`fetch` answers one part at a time, which does not scale to a board with forty.
`hunt` is the same pipeline over a whole board, split so that the deterministic
half stays here and the half that needs a search engine becomes a **work order**
rather than a guess.

```bash
# stage one: classify every part, fetch what the catalog can give, write the work order
boardwise parts hunt --file board.epro2 --out .tmp_hunt

# CI / a board whose identity may not leave the machine: zero calls, work order only
# (C-number parts come back `deferred-online` — the tool could fetch them itself)
boardwise parts hunt --file board.epro2 --out .tmp_hunt --offline

# stage two: hand the found URLs back in — same download / extract / land path
boardwise parts hunt --file board.epro2 --out .tmp_hunt --apply answers.json

# stage three: hand the facts **you read out of the .txt** back in. Every quote
# must appear verbatim on the page it cites, or the claim is refused outright.
boardwise parts hunt --file board.epro2 --out .tmp_hunt \
    --offline --cache ~/.boardwise/datasheets --apply-facts facts.json

# land the extracted candidates on a shelf (never the default: a batch run must
# not quietly edit a curated file)
boardwise parts hunt --file board.epro2 --out .tmp_hunt --shelf ~/.boardwise/parts.json
```

**The three channels.** Every component is classified by its *own identity field*
(`c-number` / `mpn-only` / `no-identity`). The C-number is matched by shape
(`^C\d{4,}$`), never trusted: measured on `tests/fixtures/llc_board.epro2`, 4 of
its 27 non-empty `lcsc_part` values hold an **MPN**. Those fall through to the
search channel — asking the product endpoint about a part number would spend a
request to learn that the catalog has never heard of it, and the report would
blame the part.

**The work order.** `hunt-plan.json` holds only `{designator, mpn, query}` per
part that still needs a PDF, with `query` always the template
`"<mpn>" datasheet pdf`. A part with no MPN is **not** on the list even though it
also needs a datasheet: there is nothing to search for, and an empty query is a
work item that looks like coverage and is not. Those are counted separately and
named as the engineer's own job.

**Outcomes** (closed set — every one is a different next step):

| outcome | meaning |
|---|---|
| `extracted` | PDF downloaded, and the narrow extractor proposed facts |
| `cached` | an earlier run already downloaded and extracted this identity |
| `pdf-unavailable` | the service answered and the part has no PDF |
| `service-unknown` | the service answered `result: null` — the catalog does not hold this C-number |
| `no-pdf-url` | the answer carries no usable `pdfUrl` (no field, or no `result` object) |
| `download-failed` | what came back was not a PDF (landing page / 404), never handed to the extractor |
| `no-facts` | the PDF **was** read (page count and `.txt` are real) and the narrow extractor found nothing it recognises |
| `parse-failed` | the text reader itself failed on this document (a broken file, or a machine without `pypdf`) |
| `deferred-online` | the tool can obtain this one itself — this run was `--offline`; not a work-order row |
| `needs-search` | an MPN and no PDF, and no address the tool can get: a row in `hunt-plan.json` |
| `no-identity` | neither a valid C-number nor an MPN: only an engineer can supply one |
| `unknown-designator` | an `--apply` record named a designator this board does not have |

`no-facts` and `parse-failed` are split because they answer two different
questions and send a reader two different places. Measured on
`tests/fixtures/级联多电平-驱动模块_2026-09-27.epro2` (46 parts, 24 unique
C-numbers, 41 s cold): **45 `no-facts`, 0 `extracted`** — including
`UCC21520DWR`'s 52-page TI datasheet, whose text reads perfectly and whose supply
rails are spelled `VDDA`/`VDDB`/`VCCI`, none of which the extractor's vocabulary
carries. Calling those rows "unparseable" would have sent the reader hunting for
a better PDF that does not exist. The narrow vocabulary is a **known limit of the
extractor**, not a property of the datasheet, and closing it is a separate task.
Note that a missing `pypdf` is *not* reported per part at all: `parts hunt`
probes the reader **once, before the batch**, and exits 2 with an install line
rather than downloading forty PDFs to produce forty rows that blame the files.

`deferred-online` exists because `--offline` used to file every C-number part
under `needs-search`, which put 45 parts the tool can fetch itself onto a work
order read as "go run a search". A work order is advice; advice a re-run answers
for free is wrong advice, and it is worst in the one mode chosen by an operator
who is being careful.

`pdf-unavailable`, `service-unknown` and `no-pdf-url` are deliberately three
values: "the vendor publishes no datasheet", "the number is wrong" and "the
service did not answer" are one line apart in a report and three different phone
calls in a review. Collapsing them is how a tool sends an engineer to search for
a part it never asked about.

**Why a download is checked before it is read.** Both vendors answer a 404 or a
throttled request with a landing page and a 200 status. A text dump of that page
extracts to nothing, and "extracted nothing" cannot be told apart from "this
datasheet is outside the narrow extractor's reach" — so the bytes are checked for
the PDF magic (and `text/*` refused outright) *before* the extractor sees them.
`--apply`'s answers take the same path, for the same reason: a second
implementation of "fetch and extract" would be a second set of failure modes
nobody tests.

**Privacy: only a C-number or an MPN leaves the machine.** The one request the
detail channel can make is `productCode=<C-number>`; the one query text the tool
can *generate* is the template above, and `assert_query_is_safe` refuses anything
that is not that template with the MPN substituted (a designator, a board title, a
net name, a value — each contributes a character outside the allowed set, and a
reordering is refused too, because one template is what produced every query).
Every outbound call lands a line in `hunt-audit.jsonl`
(`{ts, channel, request, http, bytes, sha256}`) whose `request` must be the
C-number or the MPN **verbatim** — never a URL, never a redacted form, because
this file is the only artefact that can prove what was sent. `--offline` makes
both outbound seams unreachable, and a warm cache still answers (a cache is a
local file; the flag forbids the network, not the disk).

**Cache.** `--cache <dir>` (default `~/.boardwise/datasheets`) is keyed by the
part's identity — the C-number first, since one C-number is one part by
definition, while two MPNs differing in case or in a vendor's suffix are not
certainly the same part. Each key is a directory: the PDF, the `<key>.txt` page
dump a curator reads, the per-page JSON, and a small meta file recording the URL
so a cached row can still name where it came from. `--no-cache` moves the store
inside `--out`: this run's downloads travel with its report and the next run
starts from nothing.

**Artefacts in `--out`.** `hunt-report.json` (every part, its channel, identity,
outcome, notes, facts and PDF), `hunt-plan.json` (the work order),
`hunt-report.md` (one page: counts by outcome, then what is left for a human) and
`hunt-audit.jsonl`. Extracted facts also land as `<designator>.candidate.json`
sidecars under `candidates/`, in the same `{label, url, facts}` shape `parts
fetch` writes — so they can be handed straight back to
`parts add --facts`.

**给 PDF ≠ 清闸；hunt 只产出 candidate 条目，规则仍然不认它。** Every entry this
writes carries `facts_verified: false`, and an entry whose facts already drive
rules is never overwritten by a candidate. A hunt run shortens the shelf's work;
it never closes a part's gate — that still needs a human reading the pages and
flipping the flag.

### Stage three: the reading is handed over, `--apply-facts` (521)

**Why the extractor is not the answer.** Measured on
`tests/fixtures/级联多电平-驱动模块_2026-09-27.epro2` (46 parts, 24 unique
C-numbers, 15 PDFs obtained): **0 `extracted`, 45 `no-facts`** — `UCC21520DWR`'s
52-page TI datasheet included, and that text reads perfectly. Widening the
extractor's supply-name vocabulary from 11 names to 39 moved it from **0/15 to
0/15**, not one part. The root cause is layout, not vocabulary: a real
recommended-operating-conditions table is in **columns** (`VCCI VCCI Input supply
voltage 3 18 V` — the two numbers separated by nothing but space) while `_RANGE`
only understands an explicit `to`/`-`, and a pin name may sit on a line of its own
(`VDDA,`). **This channel's output is a PDF plus a page-marked `.txt`; the facts
are produced by an AI reading the `.txt`, and the tool's job is to check the
quotes.**

So `--apply-facts <file>` is the third stage, alongside `--apply`'s URL replay.
The answer file is closed:

```jsonc
[
  {
    "designator": "U2",              // or lcsc / mpn — designator > lcsc > mpn
    "facts": {                        // the `PartEntry.facts` schema
      "supply_pins": [
        {
          "pins": ["3", "8"],
          "name": "VCCI",
          "mode": "operating",
          "v_operating": [3, 18],
          // A `provenance` must point back at its source: an `http(s)` URL, or a
          // `file:` path for a datasheet handed over by hand. Writing
          // `C601651.txt, p.4` is refused by the schema gate — measured here, it
          // was the first thing this batch's own example answer got wrong.
          "provenance": "file:C601651.pdf, p.4"
        }
      ]
    },
    "quotes": [                      // evidence, one per cited page
      {"page": 4, "text": "VCCI 3 P Primary-side supply voltage."},
      {"page": 5, "text": "VCCI VCCI Input supply voltage 3 18 V"}
    ]
  }
]
```

Measured end to end on the real board (`--offline`, zero outbound): those quotes
came back `facts-accepted 1` and landed one candidate sidecar; changing the last
quote to `3 19 V` came back `facts-rejected 1` with `refusal: quote-not-found`,
`facts: {}`, and **no `candidates/` directory at all** — not an empty file, not a
written-then-deleted one.

An unknown key anywhere in that file is a **file** error (exit 2), not a
per-record refusal: a misspelt `quote` that was ignored would turn a
well-evidenced claim into a refused one for a reason its author cannot see.

**Four gates, and what each one is for.** In the order they are checked:

1. **Schema** — `core/parts.py`'s own `_facts_from_json`, not a second copy, so
   nothing is accepted here that the shelf would then refuse to load. Checked
   first because a claim the loader cannot represent has no pins to look for.
2. **Page numbers** — `page` must be within `1..len(pages)`. A citation past the
   end of the document points at evidence that is not there; clamping it would
   be inventing a citation.
3. **Quotes verbatim** — every `quotes[].text` must appear on the page it cites,
   compared after stripping the ends and folding runs of whitespace into one
   space. **Folding is the only relaxation**: a text layer wraps an 80-character
   cell across two lines, and a quote crossing the wrap is still that sentence;
   but case, digits, units and order are compared exactly, because those are the
   characters a hallucinated table gets wrong while looking right. This is the
   one mechanism that stops "an AI writes a plausible-looking pin table", so it
   has a test that proves **one changed character is refused**, and that test is
   mutation-verified (turn the comparison off and it goes red).
4. **Pins printed somewhere** — each pin a fact names must occur in the document
   as a standalone token. **Occurrence only, never semantics**: the tool does not
   check that pin 16 is really VDDA, because that is a reading of the circuit and
   a tool pretending to it is the confident-garbage generator this stage exists
   to avoid. What it does catch is the cheap failure — pins invented for a pin
   count the package does not have.

Outcomes, and what lands:

| outcome | meaning |
|---|---|
| `facts-accepted` | every quote was found verbatim on its page; the facts land as a **candidate** |
| `facts-rejected` | a gate said no; **nothing** lands — no shelf entry, no sidecar |

A refusal names its gate in the report's `refusals` field and in the markdown:
`quote-not-found`, `page-out-of-range`, `pin-not-in-document`, `schema`,
`no-document` (stage one never got this part's PDF, so there is nothing to check
the claim against — not a judgement on the quote), `duplicate-claim` (one part,
two claims in the same file; the second would silently win).

**`--offline` is the point of this stage, not a limitation.** Everything the gate
needs is a UTF-8 page dump already on disk, so `--offline --apply-facts` works and
makes **zero** outbound calls — which is what makes this route usable on a board
whose identity may not leave the machine. There is a test for exactly that, and
its seams raise if called.

**Accepted is not verified.** The gate checks the *evidence*, not the
*conclusion*: "this sentence is on page 5" is a claim a machine can settle,
"VDDA supplies driver A" is not. So `facts-accepted` entries still land as
`facts_verified: false` with provenance kind `hunt-read` (distinct from
`hunt-extract`, so a reader can tell whose reading it was), and a refused claim
writes no `candidates/<designator>.candidate.json` — the sidecar is the artefact
someone hands to `parts add --facts`, and a file that exists for a refused claim
would walk past the gate it just failed. Trust tiers for accepted-vs-verified are
522's subject; this batch deliberately does not add a `machine_verified` field.


### The uuid pair, in the same command: `parts add --resolve` (187c)

The 186 flow still had one step in it that needed the bridge by hand: the uuid
pair 039's schema demands of an entry a rule acts on. `--resolve` asks the
library for it **while writing the entry**, so the whole intake is one command:

```bash
boardwise parts add ACME-PWR-1000 --lcsc C9900000001 \
  --facts facts.json --verified --resolve
```

* The search is `lib.device.search`, keyed on the **C-number first** (an exact
  key: 013 F4 measured `supplierId` as the only property this host indexes) and
  on the **MPN** when that finds nothing. Exactly one item must carry the term —
  zero hits and several hits are both refusals, and the refusal **lists what the
  search returned** (fields as the items spell them) rather than saying "no such
  part". An item that carries only half the pair is refused too: the schema wants
  both, and a half-pair written now is a refusal moved later with the reason lost.
* **Offline is a refusal, never a guess** (exit 2, and the manual flags are named
  in the message). An invented uuid passes the schema and fails on the board,
  which is the one outcome nobody can debug from the shelf.
* An explicitly given `--device-uuid` / `--library-uuid` **wins per field** — so
  `--resolve` fills only the half that is missing, and with both given the bridge
  is not asked at all (nothing to fill, so no reason to need a network). On an
  entry that already carries the pair, the resolved ids write over it exactly as
  the two flags would: the pair is the placement ids, not the identity, and
  "identity is not touched by a facts write" is about key/MPN/C-number.
* The same lookup is what `parts select <query> --resolve` does for an online
  pick; the difference is the destination: `select --write` appends a
  `catalog-select` entry, `add --resolve` writes the entry the AI is curating.
  `select --write` **without** `--library` resolves the destination the same way
  `add` does — the repository's `blocklib/parts.json` from a checkout, the user's
  own `~/.boardwise/parts.json` when frozen (188B, 187B 遗留4: the write used to
  be handed a literal `None` there, i.e. a `TypeError` in the middle of the
  flow), so the entry always lands in the shelf the review reads back.

### The gate

`facts_verified: false` means *a claim nobody has vouched for*. The gate is
enforced where the object is built (`PartEntry.__post_init__`), not only in the
loader: such an entry reads `facts is None` to every consumer, so no rule needs
to know the field exists, and the claim itself is kept in `candidate_facts` so
`parts show` can print what there is to review. Flipping the flag — a line in the
git diff — *is* the review; that is what "verified" physically means here.

Two consequences worth knowing:

* The rules name the difference. "Its shelf entry has no facts" (a curation task)
  and "it claims facts nobody has verified" (a **review**) are different work
  orders, and the UNKNOWN row says which one it is; the `missing_fact` line asks
  for the flip.
* A candidate is **unclassified** as well as unusable: `_category_state` answers
  UNKNOWN for it whatever `category` says, so there is no partial trust and no
  rule has to remember the gate.
* A candidate may omit `deviceUuid`/`libraryUuid` — `add` is offline and the pair
  only comes from the bridge. `Verified ⟹ resolvable` still holds: the exemption
  is exactly the shut gate, and anything else must carry the pair.

### The other way out of the gate: `parts accept-unknown` (191A)

The gate above has two honest exits, and 186 could only *describe* the second
one: judge the part (verified facts), or **state that it need not be judged**.
`boardwise parts accept-unknown` is the second one, and it is a *design-intent*
answer — not a shelf change — so it is written into the DesignIntent contract
(`core/designintent.py`), the file `checkup` and the rules already read.

```bash
boardwise parts accept-unknown <MPN|位号> --reason "<为什么接受>" \
    [--board <板名>] [--file <工程.epro2|工程目录>] [--intent <合同>] [--who <谁>]
boardwise parts accept-unknown <MPN|位号> --revoke [--board <板名>] --intent <合同>
```

* **`--reason` is mandatory** for an acceptance (a `--revoke` needs none): a
  skipped judgement with no stated reason is the silent green light the channel
  exists to prevent, so an empty one is exit 2 and **no byte is written**.
* **`--file` is the project, and it is read-only**: it resolves the *same*
  default contract `checkup` reads (by the project's `projectUuid`), and checks
  the token really is on that board — a token that is not is a *note*, not a
  refusal, because an acceptance may legitimately precede the drawing. `--intent`
  names the contract path explicitly and wins over `--file`.
* **`--board` scopes the acceptance**: the key is `(part, board)`, so one token
  on two boards has two entries. Repeating an acceptance for the same key is an
  **update** (reason/who/when), never a second row.
* **`--revoke` takes one back.** A revoke that matches nothing is exit 2 and
  says **"nothing was changed"** — 目标缺失就停下来问, never read as "already
  cleanly revoked" (R3). The key is `(part, board)`, so a `--revoke` for one
  board leaves another board's acceptance in place; the command names what is
  still there rather than leaving the reader to guess.

The contract gains a top-level `acceptedUnknown[]` (`part` / `reason` / `who` /
`when` / `board` / `provenance` / `stale`), written **only when the list is
non-empty** — every contract written before this batch keeps its exact bytes and
digest, which is what lets the rules that pin a contract `sha256` keep pinning
it. It is deliberately **not** one of the contract's `ENTRY_SECTIONS`: it is not
a requirement *about the board*, it is an accounting of which judgements a
review may skip, so it must not enter the document's provenance / draft
arithmetic.

What the next `checkup` does with it: the accepted part **leaves**
`unreviewed_parts` (so the datasheet gate no longer owes it) and **appears** in
the report's own `accepted_unknown[]`, where the reason and the who/when stay
readable. Nothing is dropped silently — a contract entry that matched no
placement still comes back as a row, marked `stale`.

**It is not a pass, and the verdict says so.** Accepting a part caps
`completion.verdict` at `complete-with-open-items`, never `complete`: a part
nobody judged is an *open item*, not a closed one. `mayQuotePassed` stays false,
and the quotable conclusion always carries 「另有 N 颗工程师接受未审」. (Whether
`verdict` actually leaves `incomplete` depends on the rest of the board — another
open item can still hold it there, and the section prints this run's own verdict
rather than asserting one.)

**An AI never accepts on the engineer's behalf.** The channel exists because a
human decided this unknown is acceptable; an acceptance with no human behind it
is exactly the silent pass this whole section is built to prevent. See
`docs/review-sop.md` §3.1 for where it sits in the review loop.

### Wave 1 (039), and the two rule behaviours it measured

Five ICs the boards actually place were curated: **CH340N** (`ic.usb-uart`),
**SN65HVD230DR** (`ic.transceiver`), **TLV9062IDR** (`ic.opamp`),
**REF2033AIDDCR** (`ic.reference`), **MPU-6050** (`ic.sensor`). The last four
classes were added to `CATEGORY_VOCABULARY` for them: the rules' subject test is
"category starts with `ic`", so a curated IC with no word for its class would have
read as *unclassified* — the opposite of what the entry is.

Every fact cites its own page, and each entry records only what its source states.
Notably **not** recorded: CH340N pin 4 (unlisted in the manual's SOP-8 column, and
"unused pins may float" is not a declaration), MPU-6050's CLKIN/FSYNC ("connect to
GND **if unused**" — a rule cannot see whether it is used), and SN65HVD230's RS
mode select (a choice, not an obligation).

REF2033AIDDCR came through curation **gated** for one round: its facts were
complete and cited, but the VIN bypass requirement made `decap-required-caps`
report "no grounded capacitor found" on 毕设FOC驱动板, where C34 sits between VIN
and AGND with an undeclared value. Both behaviours behind that report were
pre-existing rule defects, and both are now fixed in `rules/decap.py`
(039 批①b), which is why the entry is verified and driving:

* a capacitor with **no readable value** is now a candidate whose value cannot be
  established (`unreadable` → UNKNOWN, naming the capacitor), instead of not
  being a candidate at all and reading as "there is no capacitor here";
* a capacitor whose **both terminals are on the same net** no longer counts as a
  grounded candidate — a candidate must *bridge* the net to a different ground
  net — and such a capacitor gets its own WARN saying it bridges nothing;
* and when the protected pin's **own net is a ground net** (the thesis board's
  U5 pin5 on AGND) the rule decides nothing: UNKNOWN, naming the fact. It used to
  answer OK there, because a ground net is full of "grounded" capacitors.

## Where the identity comes from

Two formats can carry a board's part identity, and they carry it in different
places. `parsers/board_source.py` reads both and picks by suffix; the harvest
never has to know which it was handed.

| | `.eprj2` (local project) | `.epro2` (export) |
|---|---|---|
| containers | SQLite: `documents` / `components` / `devices` / `attributes` | ZIP: one `.epru` record stream |
| document payload | `"base64" + base64(gzip(array records))` | `{envelope}||{body}|` lines |
| library devices | `devices` rows + the `attributes` table | `DEVICE` documents' `META.attributes` |
| the library's ids | `devices.source` = `"<libraryDocUuid>|<libraryUuid>"` | `META.source`, the same form |
| footprint name | `components.title` (**case-folded**) | `FOOTPRINT` `META.title` (**as the library spells it**) |
| placements | the schematic document's array records | the `SCH_PAGE` document, via `_split_page` |

**A local project is not one shape**, and that is the measurement that made this
task possible:

| table | edit-log-only project | locally-saved project |
|---|---|---|
| `documents`, `components`, `devices` | 0 rows — state is in the encrypted edit log | populated |
| `attributes` | 0 rows | **the library metadata**: `Supplier Part` (the C-number), `Manufacturer Part`, `Datasheet`, the electrical parameters |

So 004's reconnaissance ("a local project does not carry library metadata") was
true of *that* file and is not a property of the format. Where the attributes
live is the finding that matters, and it decides what a board can contribute:

* **locally-saved** → full identity → harvestable;
* **edit-log-only** → no LCSC, no MPN, no footprint → **cannot seed a library**.
  The fix is "re-save it locally, or export `.epro2`", not "decrypt harder" —
  the encrypted stream is not where the attributes would have been.

That advice was followed on 2026-09-16: the two boards that could not be read as
local projects came back as `.epro2` exports, and the same boards then yielded
**47 and 15 entries**. The measurement is in
`tests/test_board_source.py::test_the_same_board_is_unharvestable_as_an_edit_log_and_fine_as_an_export`.

Two traps the readers document rather than work around:

* a **body-less record** ends an attribute run, as does any element that is not
  `ELE_PLACEHOLDER` or `LINE` — the `.epro2` reader does not re-derive this, it
  calls the proven `_split_page`. A hand-rolled version found "85 placements"
  that were a *different* 85;
* the local-project reader parses only fields whose position is confirmed on the
  real files (`["ATTR", id, parentId, key, value, …]`). Guessing an array index
  is how a wrong answer arrives looking like a right one.

## Harvesting

```bash
python tools/harvest_parts.py \
    --out blocklib/parts.json          # offline; no network, no editor
python tools/harvest_parts.py --check                 # re-harvest and diff
python tools/harvest_parts.py --verify                # also ask the library
```

The boards come from `blocklib/harvest.sources.json` — a JSON array of
repository-relative paths — unless `--sources` names them. That file is the
single source the tests read too, so the shipped command, the shelf and the
suite cannot name three different sets of boards. Naming `--sources` yourself
still works; private source boards (e.g. a local `blocklib/sources/` directory,
**never committed** — real project containers stay off the repo) are picked up
the same way.

Rules the tool keeps:

* **Walk the components.** Only devices the schematic *places* are harvested; an
  unused library device has no designator and so no provenance.
* **An abstract device is not a part.** `Res_0603` / `CAP_0402` carry a `Value`
  and a `Supplier Footprint` but no C-number — they are the shape that caused
  006b's "library swap". They are **reported** (so the gap is visible) and never
  curated.
* **Merge by C-number, keep the history.** The same part on two boards is one
  entry, and `provenance.designators` accumulates `U10@smart_pillbox` and
  `U8@thesis_FOC_board` — that track record is the confidence signal. Merging is
  what makes re-running the tool idempotent.
* **A conflict is recorded, not resolved.** Two boards disagreeing about a field
  keeps the first (deterministic) value and gains a note naming both.
* **`--verify` is the only thing that may mark a name verified**, and it starts
  from the **device**: `lib.device.get(device uuid, library uuid)` →
  `item.association.footprintUuid` → `lib.footprint.get(that, library uuid)` →
  the name. One chain per distinct device, not per placement. Asking
  `lib.footprint.get` with the footprint uuid the *project* holds fails on the
  live library — the same fact 006b measured for project-local symbol uuids — and
  that was the first version's bug, so the failing shortcut is written down here
  rather than merely removed. The library's spelling is adopted because that is
  the vocabulary a consumer must use; a difference is recorded.

Measured 2026-09-30 by `python tools/harvest_parts.py --check` with no
`--sources`, over the six boards in `blocklib/harvest.sources.json`, in the
formats they arrived in: `smart_pillbox` → 13 entries, `thesis_FOC_board` → 41,
`ProPrj_高速电机控制器_2026-09-16` (`.epro2`) → 60,
`ProPrj_ROBOT ctrl FOC_2026-09-16` (`.epro2`) → 19,
`ProPrj_智能药箱_2026-09-17` (`.epro2`) → 13,
`ProPrj_毕设FOC驱动板_2026-09-17` (`.epro2`) → 35; shared parts merge, so the
shelf holds **109 entries**. The two edit-log-only `.eprj2` files are still
passed to the tool and are still skipped with that reason — the same boards,
harvested and refused, side by side in one report. `CH340N` (C2977777) is on
**all six**, which is the strongest provenance in the file.

**The glob this section used to print cannot rebuild the shelf.** It matched
four `.eprj2` files, two of which are the edit-log-only ones, so it harvested
`smart_pillbox` + `thesis_FOC_board` alone: measured 2026-09-30, **52** entries
against the shelf's 109 — 57 short — and it did not even get that far, because
`C369933` (AMS1117-3.3) is on no glob source and the sidecar's `curated` record
for it is a field overlay rather than a whole entry, so the run died at
`harvest_parts: curated[C369933]: 'key' is required and must not be empty`
(exit 2, nothing written). Both facts are the reason the source list is a
committed file now.

**A case-only spelling difference is not a conflict.** The same footprint arrives
as `R0603` from an export and `r0603` from a local project (the editor case-folds
document titles). The case-preserving spelling is kept, because the library's own
spelling is the mixed-case one — 006b read `R0402` straight out of
`lib.footprint.get`. An entry whose *only* source is a local project keeps the
folded spelling and gains a note: nothing is upper-cased without a second
spelling to compare against, which is the same rule that refuses to guess a
footprint name in the first place.

Provenance records the source **relative to the repository**, so the committed
file does not embed anyone's home directory. A `provenance.source` that names
several boards is a **sorted set of labels**, not a log: the order the operator
lists `--sources` in must not change the artifact, and a provenance list has no
meaningful order to preserve.

## The corrections sidecar

```bash
python tools/harvest_parts.py --rehome                     # needs the bridge
python tools/backfill_datasheets.py                        # needs the network
python tools/harvest_parts.py --verify                  # writes the library
```

Two facts about a part are **not in any board**, and both are kept in
`blocklib/parts.corrections.json` rather than edited into the library — the same
rule as the golden fixture's overrides: `blocklib/parts.json` stays a
deterministic function of *sources + corrections*, so an offline `--check` still
means something.

| Section | What it holds | Why it cannot come from a board |
|---|---|---|
| `identity` | the device/library uuid pair of the two entries whose stored library uuid is a library **name** (`"FOC"`, a personal library) | `lib.device.get` rejects that pair (`found:false`, measured), so nothing can be resolved from it. Re-anchored by C-number through `lib.device.search`, which accepts an item only on an **exact, unique** match |
| `datasheets` | the datasheet **PDF** link per C-number | a board declares a datasheet *web page*; the file link exists only on the product page |

Measured 2026-09-17 against the live endpoints:

* `--rehome` candidates: exactly two entries, `ic.drv8350srtvr` (C2861195) and
  `ic.hb04n090s` (C49423996). The candidate rule is local and checkable (the
  library uuid is not 32 hex characters), so "which entries need re-anchoring" is
  reproducible without the bridge. `--rehome` writes the sidecar **and nothing
  else**; the library is refreshed by the next `--verify` run, which applies the
  sidecar *before* asking the bridge — asking about the board's original pair
  would answer `found:false` for exactly the entries the correction exists for.
* `--backfill-datasheets` (the tool is `backfill_datasheets.py`):
  `GET wmsc.lcsc.com/ftps/wm/product/detail?productCode=<C>` → `result.pdfUrl`.
  **82 of 85 filled.** Three answers are not links, and all three are reported
  rather than papered over: `C160183` exists with no `pdfUrl`; `C22369707` and
  `C9900097986` answer `{"code":200,"result":null}` — the catalog does not know
  those C-numbers. The last one is worth a second look upstream: it is a
  **ten-digit** C-number on `conn.mx1_25_lt_3` (an MX1.25 connector harvested
  from the ROBOT/高速 boards), which is not a shape the catalog issues.

`Verified ⟹ resolvable` is enforced by the schema, not by convention: an entry
claiming `footprint_name_verified: true` with a library uuid that cannot be a key
is rejected at load (`core/parts.py::entry_from_json`), because the only route to
that answer runs through a pair the library accepts.

## Selecting

```bash
boardwise parts select "100nF 0805"          # offline, blocklib/parts.json
boardwise parts select "5mΩ 2512" --json
boardwise parts select "330mΩ 0805" --online # explicit opt-in: JLC SMT catalog
boardwise parts select "CH340N" --resolve    # then resolve the C-number via the bridge
boardwise parts select "CH340N" --resolve --write   # ...and add it to the library
```

### The value gate (#202)

An explicit `Ω`/`ohm` query is a **quantity**, not a substring:

* the SI prefix is **case-sensitive** — `mΩ` is milli, `MΩ` is mega, nine
  decades apart. `330mΩ` equals `0.33Ω` and is nothing like `33Ω`;
* the value must come from a **named field** (a catalog `Resistance` attribute,
  or the curated `value`). `0805W8F330LT5E`, `C52548` and prose numbers can never
  supply one — that is the regression the discipline exists for;
* a field is read whole. `5.1kΩ ±1%` is unambiguous and accepted; `1/2Ω` (a unit
  with no quantity), `0.33Ω~1Ω` (two values) and `1,000Ω` (a separator, not a
  quantity) all **fail closed**;
* **no exact candidate ⇒ exit code 1**, and no fuzzy recommendation. A query
  without a unit (`10k`) is a fuzzy search, and an empty fuzzy result is not an
  error — writing `10kΩ` is how you ask for the *verified* one.

### The footprint vocabulary table

`0402` is a size; `R0402` is a library name. 006b measured what conflating them
costs, so the only mapping allowed is the explicit table in
`core/parts.py::FOOTPRINT_ALIASES` (`0402 → {R0402, C0402, L0402, LED0402}`,
narrowed by a category word: `cap 0402 → C0402`). A size-shaped word that is not
in the table is **reported as unmapped** and applies no constraint — an
unmapped `9999` must not silently become "match nothing", nor silently become a
guess.

### Online: explicit, and never from the connector

`--online` compares against the JLC SMT catalog (`selectSmtComponentList`,
queried twice — `base` and general — and merged by C-number, because basic parts
only surface with `componentLibraryType: 'base'`). Ranking is the task's order:
spec match → buildable (`stock ≥ qty`) → basic → preferred → cheapest, so a
basic part with too little stock yields to an in-stock one.

The call is made **Python-side**: the EasyEDA webview cannot make cross-origin
fetches. In code it sits behind a one-method seam (`catalog.Fetcher`), which is
what lets the tests exercise the whole path without a network — one test
replaces `urllib.request.urlopen` with something that raises.

An online pick's identity is then resolved **deterministically**: `lib.device.search`
is called with the C-number itself, and an item is accepted only if one of its
fields equals it exactly. Zero matches, more than one, or a match without a
device uuid is a refusal. The field that carried the C-number is reported
(`matched_key`), and a pick whose C-number is already curated **from a board** is
not overwritten — a `board-extract` entry is the stronger claim, and rewriting it
from a catalog row would silently downgrade the provenance.

## Honest boundaries

* **The `.epro2` path is exercised on real exports** (four of them, including
  the two supplied on 2026-09-16); the `.eprj2` path on two. Nothing about the
  harvest is a guess.
* **The live catalog and the product endpoint have both been called for real, by
  a person holding the network** (2026-09-17: the product endpoint on 85
  C-numbers). The JLC SMT *search* endpoint — the one `parts select --online`
  uses — is still recorded-shape only: its request/response keys come from the
  reference implementation's 2026-09 notes, and the client is written so a
  different shape produces empty fields plus a note rather than a silent empty
  list.
* **`--verify` has run against a live editor** (2026-09-16, on the machine:
  83 of 85 names upgraded, 48 folded spellings corrected). `--resolve` is
  implemented and stub-tested, and its item shape is pinned by the connector's
  documentation (`supplierId`, `footprintName`, `footprintUuid`) — which the
  same live run confirmed.
* **`parts add --resolve` (187c) is offline-tested only.** Its C-number rung is
  the same `lib.device.search` call `select --resolve` makes, and its MPN rung
  reads `name` — the field 180 measured the host naming a *device* by (it found
  `Ground-<net>` that way). Which fields a hit carries is **not** verified on
  this host, so nothing is assumed: the field that matched is reported
  (`matched_by` + `matched_key`), a refusal quotes every item's fields verbatim,
  and half a uuid pair is refused rather than completed.
* **`--rehome` has never run against a live editor.** It is implemented,
  stub-tested (including the three refusals: ambiguous hit, non-uuid answer,
  transport failure), and its two candidates are measured from the artifact. The
  live run is Kimi's step, and it is a two-command sequence:
  `--rehome` then `--verify`.
* **`C22369707` and `C9900097986` remain unresolved** at the source: the catalog
  does not know them, so their entries keep the boards' identity and no PDF link.
  Nothing is invented for them.

## Files

| Path | Role |
|---|---|
| `src/boardwise/core/parts.py` | the entry/library schema, the value gate, the vocabulary table, the corrections sidecar |
| `src/boardwise/parsers/board_source.py` | board reader for both formats: documents, library identity, placements |
| `src/boardwise/engines/harvest.py` | board → entries; merging; the verifier seam; applying corrections |
| `src/boardwise/engines/catalog.py` | the JLC SMT client and the product-detail reader, each behind a fetcher seam |
| `src/boardwise/engines/select.py` | offline/online ranking, and C-number resolution |
| `src/boardwise/engines/hunt.py` | 520: batch channel decision, the guarded search query, the fetch path, the cache, the audit log, the report shapes; 521: the `--apply-facts` quote gate (`check_claim`) |
| `tools/harvest_parts.py` | the harvesting CLI (`--check`, `--verify`, `--rehome`) |
| `tools/backfill_datasheets.py` | the datasheet-link CLI (network, per C-number, resumable) |
| `blocklib/parts.json` | the library |
| `blocklib/parts.corrections.json` | the sidecar the library is harvested with |
| `blocklib/harvest.sources.json` | the six boards the library is harvested from (the `--sources` default) |
| `tests/test_parts_library.py` | schema + the value gate + the vocabulary table |
| `tests/test_harvest.py` | counts, idempotence, reconcile, conflicts, verification |
| `tests/test_harvest_verify.py` | the verify chain, stubbed (including its three failures) |
| `tests/test_rehome.py` | identity re-anchoring, the sidecar, and the command |
| `tests/test_datasheet_backfill.py` | the product reader and the backfill loop, recorded responses |
| `tests/test_select.py` | offline selection, the #202 negatives, exit codes, `--resolve` |
| `tests/test_catalog.py` | the mocked online path and the resolver |
| `tests/test_board_source.py` | both readers, cross-validated against the proven parser |
