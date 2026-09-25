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
| `facts` | datasheet claims (039's vocabulary: `supply_pins` / `required_caps` / `nc_pins` / `must_connect` / `pull_required` / `ldo` / `led`), each with its own page-cited provenance |
| `facts_verified` | the gate: written **only when false**, and absent means true. A candidate (`false`) records a claim nobody has reviewed; no rule acts on it until a human flips the flag in review |
| `provenance` | `kind` (`board-extract` / `catalog-select` / `manual-curation`), `source`, and `designators` — the accumulating track record |
| `notes` | anything a reader must know: a corrected footprint spelling, an unrecognised part class, a disambiguated key |

Two properties are deliberately *tri-state* (`true` / `false` / `null`). "No
evidence" and "no" are different answers, and a library whose `basic: false`
means "we never looked" is worse than one that says `null`.

## The fact intake: `missing` → `add` → curation → the gate (039)

The rules cannot decide anything about a part the shelf knows no facts for, and
until 039 nothing said *which* facts were owed. Three offline commands close that
loop; none of them touches the bridge.

```bash
boardwise parts missing --file board.epro2          # what the shelf owes this board
boardwise parts missing --file board.eprj3 --json report.json
boardwise parts show CH340N                         # one entry, in full
boardwise parts show ic.ch340n --json entry.json
boardwise parts add TPL2981-30DBVR --lcsc C9900000001
```

* **`missing`** lists every `U`-prefixed part of a project with the fact keys the
  shelf has not recorded for it, in vocabulary order, and the identity the rules
  will look up (MPN first, then the C-number — `find_facts`' exact-match order, so
  the list and the verdicts can never disagree). **Exit 0 always**: a non-empty
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
python tools/harvest_parts.py --sources blocklib/sources/*.eprj2 \
    --out blocklib/parts.json          # offline; no network, no editor
python tools/harvest_parts.py --sources ... --check    # re-harvest and diff
python tools/harvest_parts.py --sources ... --verify   # also ask the library
```

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

Measured on the four boards, in the formats they arrived in: `smart_pillbox`
→ 13 entries, `thesis_FOC_board` → 41, `ProPrj_高速电机控制器` (`.epro2`) → 47,
`ProPrj_ROBOT ctrl FOC` (`.epro2`) → 15; shared parts merge, so the shelf holds
**85 entries**. The two edit-log-only `.eprj2` files are still passed to the tool
and are still skipped with that reason — the same boards, harvested and refused,
side by side in one report. `CH340N` (C2977777) is on **all four**, which is the
strongest provenance in the file.

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
python tools/harvest_parts.py --sources ... --verify        # writes the library
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
| `tools/harvest_parts.py` | the harvesting CLI (`--check`, `--verify`, `--rehome`) |
| `tools/backfill_datasheets.py` | the datasheet-link CLI (network, per C-number, resumable) |
| `blocklib/parts.json` | the library |
| `blocklib/parts.corrections.json` | the sidecar the library is harvested with |
| `tests/test_parts_library.py` | schema + the value gate + the vocabulary table |
| `tests/test_harvest.py` | counts, idempotence, reconcile, conflicts, verification |
| `tests/test_harvest_verify.py` | the verify chain, stubbed (including its three failures) |
| `tests/test_rehome.py` | identity re-anchoring, the sidecar, and the command |
| `tests/test_datasheet_backfill.py` | the product reader and the backfill loop, recorded responses |
| `tests/test_select.py` | offline selection, the #202 negatives, exit codes, `--resolve` |
| `tests/test_catalog.py` | the mocked online path and the resolver |
| `tests/test_board_source.py` | both readers, cross-validated against the proven parser |
