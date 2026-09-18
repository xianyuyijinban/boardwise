# `.eprj2` reconnaissance (2026-09-12)

Throwaway scripts that reverse-engineered EasyEDA Pro's **local project
database** (`.eprj2`), kept because the findings drive later tasks. Nothing
here is imported by the `boardwise` package — this directory is a lab notebook,
not library code.

Source project: `C:\Users\xiangyu\Desktop\CH340G.eprj2` (CH340 USB-UART board).
All scripts open it **read-only** (`mode=ro`).

## What `.eprj2` is

A SQLite database, **not** a ZIP like `.epro2`. It holds no current-state
snapshot: `devices`, `components`, `documents`, `boards`, `schematics` … are
all **0 rows**. Everything lives in an encrypted edit log:

| table | rows | role |
|---|---|---|
| `history_data` | 57 | `dataStr` = one base64 AES-GCM blob, a chunk of the record stream |
| `project_history_<hash>` | 18 | one row per history node: `uuid` (used as IV), `key` (the AES key), `id` (ordering) |
| `project_structures` | 28 | document inventory (matches the 28 `DOCHEAD`s) |
| `projects` / `users` / `project_members` | 1 / 1 / 1 | project metadata |

Full census in `schema.txt`.

## Decryption (confirmed, 57/57 blobs)

```
algorithm : aes-128-gcm
key       : bytes.fromhex(project_history_<h>.key)      # 32 hex chars -> 16 bytes
iv/nonce  : bytes.fromhex(history_data.history_uuid)    # 32 hex chars -> 16 bytes
blob      : base64.b64decode(dataStr)
ciphertext: blob[:-16]      tag: blob[-16:]
plaintext : gzip.decompress(...)   -> .epru record text (UTF-8)
```

The scheme was not guessed: it was read out of the installed client,
`D:\lceda-pro\resources\app\app.js` (`algorithm="aes-128-gcm"`,
`key.length !== 16` guard, `gzipSync` before `createCipheriv`, tag appended).
`try_decrypt.py` is the failed brute-force over ECB/CBC/CTR/CFB/OFB that
predates finding `app.js` — kept to show what does *not* work.

## Rebuilding a usable document stream

Records are an **edit log**, not a snapshot:

1. Concatenating the 57 decrypted chunks in any order does **not** work —
   documents are interleaved across history nodes.
2. Correct order: sort by `(project_history.id, history_data.id)`.
3. For each `(type, id)` key, **the last record wins**.
4. **An empty body means deletion** — the element is dropped.
5. Each non-`DOCHEAD` record is emitted under the `DOCHEAD` that was current
   when it was first seen, which restores document grouping.
6. `EDIT_HEAD` records are skipped.

`rebuild.py` does exactly this. Result: 1,440 records / 472 KB, 0 malformed.

### Document census of the rebuild

```
CONFIG 1, BOARD 1, SCH 1, SCH_PAGE 1, PCB 1, SYMBOL 29, DEVICE 28, BLOB 1, FOOTPRINT 18
PCB 374 records | SCH_PAGE 683 | FOOTPRINT 142 | SYMBOL 204
```

## Finding: where library metadata lives (corrected 2026-09-16)

This is the reason the rebuild is **not** usable as a golden fixture — but the
*reason* was refined in 008b, and the original wording was too broad:

- In **this** file (a locally-cached cloud project) the DEVICE documents contain
  only `DOCHEAD` — no `META` — so no `Value`, `Supplier Part`, `Manufacturer`,
  `Datasheet`, and the FOOTPRINT documents have no title either. The PCB `ATTR`
  is complete (`Designator` 17, `Device` 17, `Footprint` 17), so a `.eprj2`-derived
  model has correct designators, nets and geometry but **empty `value` /
  `footprint` / `lcsc_part`**.
- **But that is a property of the file's shape, not of `.eprj2`.** In a project
  saved locally (文件 → 另存为本地), the same tables are populated:
  `documents` / `components` / `devices` hold the state, and the library
  metadata lives in **`attributes`** (key/value per `devices.uuid`:
  `Supplier Part`, `Manufacturer Part`, `Datasheet`, `Supplier Footprint`, and
  the electrical parameters). Measured on the four boards 岳翔宇 supplied for
  008b: two are locally-saved (full identity, harvestable) and two are
  edit-log-only like this one (0 rows everywhere, nothing to harvest).
- So the actionable statement is: **an edit-log-only `.eprj2` cannot seed a part
  library; re-save it locally or export `.epro2`.** It is not that the format
  lacks the data — it is that this particular save mode never stored it, and no
  amount of decryption would recover what was never there.

See `docs/parts.md` for the harvest that depends on this, and
`src/boardwise/parsers/eprj2.py` for the reader.

### Document bodies are not encrypted

Unlike the edit-log blobs (`history_data`, aes-128-gcm), a materialised
document's `dataStr` is `"base64" + base64(gzip(record text))` — plain gzip, so
reading it needs **no** `pycryptodome`. (`pycryptodome` is only needed for the
edit-log path below.) The record text is a positional array form
(`["ATTR","e69","e67","Designator","U1",…]`), not the `.epru` envelope form that
`rebuild.py` writes.

Second caveat: `PAD_NET` carries edit residue — 68 records for 43 real pads,
so the rebuilt netlist has 51 pins against 43 physical pads.

## Scripts

| file | what it does | needs |
|---|---|---|
| `try_decrypt.py` | brute-forces AES modes; **all fail** (kept as evidence) | pycryptodome |
| `decrypt_test.py` | first successful single-blob decrypt | pycryptodome |
| `decrypt_probe.py` | decrypts all 57, censuses `docType` per chunk, dumps the largest PCB chunk → `ch340g_decrypted.epru` | pycryptodome |
| `merge_probe.py` | naive concatenation → `ch340g_merged.epru`; shows why it fails | pycryptodome |
| `rebuild.py` | **the one that works**: edit-log replay → `ch340g_final.epru` | pycryptodome |

`pycryptodome` is the only non-stdlib dependency and is **not** a dependency of
`boardwise` — install it in a scratch venv if these ever need re-running.

## Outputs

| file | what it is |
|---|---|
| `ch340g_final.epru` | 473 KB, replayed final document state — the usable one |
| `ch340g_merged.epru` | 1.2 MB, naive concatenation (superseded, kept for diffing) |
| `ch340g_decrypted.epru` | 205 KB, single largest PCB chunk (superseded) |
