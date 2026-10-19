"""527D2: the machine-verified class's evidence lands on the shelf.

527D's known edge #1, closed: `parts classify --from/--page/--quote` printed the
citation to the terminal and the `--json` report and then dropped it, so a
`machine_verified` class could not be traced to its quote afterwards — the one
521 rule (every fact carries its source) applied to facts but not to the
conclusion. The fix is a third class key, `category_provenance`, written
verbatim on the entry and read back by `parts show` / `parts show --json`.

The rules the batch is held to, each with its test:

* the evidence rides **with the tier** — written on the machine run, taken back
  off when a human re-signs;
* a hand-signed class (and every entry written before the field existed) keeps
  its exact bytes — absent means absent, never a written null or `None`;
* the loader validates the shape on the way in, 522's ruling applied to this
  field: null, a missing member, a bad source or a bad page is an error, never
  a silent default;
* `category_trust` is not touched by the write — the evidence proves the
  *machine* run, it does not upgrade it to a human signature.

527D2's second pass (the red team's findings), also each with its test:

* **the citation names the document the quote was really checked on.** The
  `http(s)` leg read the cache by the entry's *identity* and never looked at
  `--from`, so any invented URL landed on the shelf as a `machine_verified`
  citation; the URL is now matched against the cache's own `.meta.json` record,
  and a cache with no url record is refused rather than guessed at;
* **`--from` has to be an address**, not just a scheme — `http://` and `file:`
  name no document (`core.parts.citation_source_defect`, applied at the door and
  in the loader);
* **a new classification's evidence replaces the old one** — a second run with a
  different `--from/--page/--quote` used to be able to keep the previous run's
  citation (the `setdefault` failure mode this repo has hit before);
* **the display end tells the two directions apart** — the citation block prints
  for a machine-signed class only, a machine class with none says so, and the
  `--json` report gains `categoryProvenanceExpected` beside the raw key.

Zero network: the `file:` leg reads a dump from disk, as in 527D's own tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.parts import (
    FACTS_TRUST_MACHINE,
    FACTS_TRUST_VERIFIED,
    PartError,
    entry_from_json,
    entry_to_json,
    load_parts,
)

ROOT = Path(__file__).resolve().parents[1]
#: The real shelf, copied per test — the 109 untouched entries are the point of
#: test ④, so a fixture shelf of hand-built entries would not prove them.
REAL_SHELF = ROOT / "blocklib" / "parts.json"

TARGET_KEY = "ic.lm5164ddar"
TARGET_MPN = "LM5164DDAR"

DUMP = (
    "<<<page 1>>>\n"
    "ACME9 Cover page\n"
    "<<<page 2>>>\n"
    "LM5164 is a 100 V step-down buck converter.\n"
)
QUOTE = "LM5164 is a 100 V step-down buck converter."
SOURCE = "https://www.ti.com.cn/lit/ds/symlink/lm5164.pdf"
TARGET_LCSC = "C477928"
#: The page dump stage one cached for the target entry — what the `http(s)` leg
#: of `--from` reads, and (527D2) what the citation is matched against.
CACHE_PAGES = [
    "ACME9 Cover page",
    "LM5164 is a 100 V step-down buck converter.",
]


def shelf_without_category(tmp_path: Path, *, key: str = TARGET_KEY) -> Path:
    """The real shelf, copied, with one entry's class taken back off."""
    raw = json.loads(REAL_SHELF.read_text(encoding="utf-8"))
    for item in raw["parts"]:
        if item["key"] == key:
            item.pop("category", None)
            item.pop("category_trust", None)
            item.pop("category_provenance", None)
    shelf = tmp_path / "parts.json"
    shelf.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return shelf


def write_cache(
    tmp_path: Path, *, pages: list[str] | None = None, url: str | None = SOURCE
) -> Path:
    """A stage-one cache entry for the target: `<cache>/<C码>/<C码>.*`.

    `parts fetch` / `parts hunt` leave the four files; the `.meta.json` records
    where the bytes came from. 527D2 makes that record load-bearing (the citation
    must name the document the quote was checked on), so `url=None` builds the
    "dump but no source record" case the refusal also has to cover.
    """
    root = tmp_path / "cache"
    directory = root / TARGET_LCSC
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{TARGET_LCSC}.pages.json").write_text(
        json.dumps(pages if pages is not None else CACHE_PAGES, ensure_ascii=False),
        encoding="utf-8",
    )
    if url is not None:
        (directory / f"{TARGET_LCSC}.meta.json").write_text(
            json.dumps(
                {"url": url, "channel": "detail-api", "bytes": 123},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return root


def page_dump(tmp_path: Path) -> Path:
    path = tmp_path / "lm5164.txt"
    path.write_text(DUMP, encoding="utf-8")
    return path


def classify_machine(shelf: Path, tmp_path: Path, *extra: str) -> int:
    return cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", f"file:{page_dump(tmp_path)}", "--page", "2", "--quote", QUOTE,
        "--library", str(shelf), *extra,
    ])


def target_of(shelf: Path) -> dict:
    raw = json.loads(shelf.read_text(encoding="utf-8"))
    return next(item for item in raw["parts"] if item["key"] == TARGET_KEY)


def round_tripped(shelf: Path) -> bytes:
    """The shelf's bytes after one load→save cycle (the round-trip test's probe)."""
    from boardwise.core.parts import save_parts

    elsewhere = shelf.with_name("rt.json")
    save_parts(load_parts(shelf), elsewhere)
    return elsewhere.read_bytes()


# --------------------------------------------------------------------------
# ① the machine run writes the evidence, and the shelf can answer "where from"
# --------------------------------------------------------------------------


def test_machine_run_writes_the_evidence_and_the_shelf_reads_it_back(
    tmp_path, capsys
):
    shelf = shelf_without_category(tmp_path)
    assert classify_machine(shelf, tmp_path) == 0
    capsys.readouterr()
    written = target_of(shelf)["category_provenance"]
    # All three flags, verbatim — not a summary, not a page number alone.
    assert written["source"] == f"file:{page_dump(tmp_path)}"
    assert written["page"] == 2
    assert written["quote"] == QUOTE
    # The read-back route the doc names: `parts show`, terminal and `--json`.
    dump = tmp_path / "show.json"
    assert cli.main([
        "parts", "show", TARGET_MPN, "--library", str(shelf), "--json", str(dump),
    ]) == 0
    out = capsys.readouterr().out
    assert "category provenance:" in out and "第 2 页" in out
    assert QUOTE in out
    entry_dump = json.loads(dump.read_text(encoding="utf-8"))["entry"]
    assert entry_dump["categoryProvenance"]["source"] == f"file:{page_dump(tmp_path)}"
    assert entry_dump["categoryProvenance"]["page"] == 2
    assert entry_dump["categoryProvenance"]["quote"] == QUOTE


# --------------------------------------------------------------------------
# ② the human run (and every legacy entry) writes nothing
# --------------------------------------------------------------------------


def test_human_run_writes_no_evidence_key(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    assert cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck", "--library", str(shelf),
    ]) == 0
    capsys.readouterr()
    # Direct JSON: the key is not there at all — not null, not an empty dict.
    assert "category_provenance" not in target_of(shelf)
    # …and `parts show --json` reports it as absent, the human tier's shape.
    dump = tmp_path / "show.json"
    assert cli.main([
        "parts", "show", TARGET_MPN, "--library", str(shelf), "--json", str(dump),
    ]) == 0
    capsys.readouterr()
    entry_dump = json.loads(dump.read_text(encoding="utf-8"))["entry"]
    assert entry_dump["categoryProvenance"] is None
    # The terminal does not print a provenance block for a hand signature.
    assert cli.main(["parts", "show", TARGET_MPN, "--library", str(shelf)]) == 0
    assert "category provenance" not in capsys.readouterr().out


# --------------------------------------------------------------------------
# ③ the loader refuses a malformed citation — 522's rule, this field
# --------------------------------------------------------------------------


def test_loader_refuses_null_and_malformed_category_provenance(tmp_path):
    base = {
        "key": "ic.acme9", "lcsc": "C9900000001",
        "deviceUuid": "dev-1", "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
        "category": "ic.ldo",
    }
    # A present-but-null key is an error, not "absent": `raw.get` cannot tell
    # `{"category_provenance": null}` from `{}`, and the difference is exactly
    # the one 522 measured on `facts_trust`.
    with pytest.raises(PartError, match="category_provenance"):
        entry_from_json({**base, "category_provenance": None})
    with pytest.raises(PartError, match="expected an object"):
        entry_from_json({**base, "category_provenance": "file:ds.pdf p.2"})
    # Missing members: the evidence is all three fields or none.
    for partial in (
        {"source": SOURCE, "page": 2},
        {"source": SOURCE, "quote": QUOTE},
        {"page": 2, "quote": QUOTE},
    ):
        with pytest.raises(PartError, match="missing"):
            entry_from_json({**base, "category_provenance": partial})
    with pytest.raises(PartError, match="unknown key"):
        entry_from_json({**base, "category_provenance": {"url": SOURCE}})
    # A source that is neither http(s) nor file: — the 保密口径, one field over.
    with pytest.raises(PartError, match="neither a http\\(s\\) URL"):
        entry_from_json({**base, "category_provenance": {"source": "C:/ds.pdf", "page": 2, "quote": QUOTE}})
    # A page that is not a positive integer (bool included — it is an int).
    with pytest.raises(PartError, match="page"):
        entry_from_json({**base, "category_provenance": {"source": SOURCE, "page": 0, "quote": QUOTE}})
    with pytest.raises(PartError, match="page"):
        entry_from_json({**base, "category_provenance": {"source": SOURCE, "page": "2", "quote": QUOTE}})
    with pytest.raises(PartError, match="page"):
        entry_from_json({**base, "category_provenance": {"source": SOURCE, "page": True, "quote": QUOTE}})
    # An empty quote is a citation with no sentence in it.
    with pytest.raises(PartError, match="quote"):
        entry_from_json({**base, "category_provenance": {"source": SOURCE, "page": 2, "quote": ""}})
    # …and a well-formed one round-trips exactly.
    good = {"source": SOURCE, "page": 2, "quote": QUOTE}
    loaded = entry_from_json({**base, "category_provenance": dict(good)})
    assert loaded.category_provenance == good
    assert entry_to_json(loaded)["category_provenance"] == good


# --------------------------------------------------------------------------
# ④ the 109 legacy entries round-trip byte-identically
# --------------------------------------------------------------------------


def test_legacy_entries_round_trip_byte_identically(tmp_path):
    """A field nobody wrote must not appear on the next save — measured, not
    assumed: the real shelf (all 109 entries, none carrying the field) through
    one load→save cycle, byte for byte."""
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    assert b"category_provenance" not in before
    assert round_tripped(shelf) == before
    # …and the loader never invents the field on a legacy entry either.
    legacy = entry_from_json({
        "key": "ic.acme9", "lcsc": "C9900000001",
        "deviceUuid": "dev-1", "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
    })
    assert legacy.category_provenance is None
    assert "category_provenance" not in entry_to_json(legacy)


# --------------------------------------------------------------------------
# ⑤ the tier is not touched by the evidence
# --------------------------------------------------------------------------


def test_evidence_does_not_upgrade_the_tier(tmp_path):
    shelf = shelf_without_category(tmp_path)
    assert classify_machine(shelf, tmp_path) == 0
    raw = target_of(shelf)
    # Machine stays machine: the citation proves *how* it was checked, never
    # *who signed it* — that would be the exact upgrade 522/527D exist to stop.
    assert raw["category_trust"] == FACTS_TRUST_MACHINE
    assert load_parts(shelf).get(TARGET_KEY).category_trust == FACTS_TRUST_MACHINE
    assert load_parts(shelf).get(TARGET_KEY).category_provenance is not None
    # …and the write also cannot *demote* a class that was already machine.
    assert classify_machine(shelf, tmp_path) == 0
    assert target_of(shelf)["category_trust"] == FACTS_TRUST_MACHINE
    # A hand re-sign takes both back off together (the downgrade path).
    assert cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck", "--library", str(shelf),
    ]) == 0
    raw = target_of(shelf)
    assert "category_trust" not in raw
    assert "category_provenance" not in raw


# --------------------------------------------------------------------------
# ⑥ the opened constraint, pinned: only the class's own keys move
# --------------------------------------------------------------------------


def test_only_the_classs_own_keys_move(tmp_path):
    """「只改两个键」opened by 527D2, restated and pinned: a machine-tier write
    moves exactly `category`, `category_trust` and `category_provenance` of the
    one entry — the citation belongs to the class, so it moves with it; every
    other byte of the entry and of the shelf stays where it was."""
    shelf = shelf_without_category(tmp_path)
    raw_before = json.loads(shelf.read_text(encoding="utf-8"))
    assert classify_machine(shelf, tmp_path) == 0
    raw_after = json.loads(shelf.read_text(encoding="utf-8"))
    before_target = next(
        item for item in raw_before["parts"] if item["key"] == TARGET_KEY
    )
    after_target = next(
        item for item in raw_after["parts"] if item["key"] == TARGET_KEY
    )
    changed = {
        name
        for name in set(before_target) | set(after_target)
        if before_target.get(name) != after_target.get(name)
    }
    assert changed == {"category", "category_trust", "category_provenance"}
    # The other 108 entries: byte-identical.
    others_before = json.dumps(
        [item for item in raw_before["parts"] if item["key"] != TARGET_KEY],
        ensure_ascii=False, indent=2,
    )
    others_after = json.dumps(
        [item for item in raw_after["parts"] if item["key"] != TARGET_KEY],
        ensure_ascii=False, indent=2,
    )
    assert others_before == others_after


# --------------------------------------------------------------------------
# ⑦ the citation names the document the quote was checked on (red team, hole 1)
# --------------------------------------------------------------------------


def test_an_http_source_is_matched_against_the_cached_document(tmp_path, capsys):
    """`--from` must be the url the cache recorded for this entry.

    Measured hole: the `http(s)` leg read `<cache>/<C码>/*.pages.json` and never
    compared it to `evidence["source"]`, so **any** URL was accepted and written
    onto the shelf as the citation of a quote checked against a different
    document — with the terminal still saying 「引文逐字对上」. That is the one
    thing this field exists to prevent: a citation nobody can re-check.
    """
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    cache = write_cache(tmp_path)
    code = cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", "https://totally-unrelated.example/not-the-datasheet.pdf",
        "--page", "2", "--quote", QUOTE,
        "--cache", str(cache), "--library", str(shelf),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "不是缓存里那份文档" in captured.err
    assert SOURCE in captured.err, "the refusal must name the url the cache holds"
    # Zero write: no citation, no key, and no backup left behind either.
    assert shelf.read_bytes() == before
    assert "category_provenance" not in target_of(shelf)
    assert not (tmp_path / "parts.json.tmp").exists()


def test_an_http_source_with_no_url_record_is_refused_rather_than_guessed(
    tmp_path, capsys
):
    """A cache with a page dump but no `.meta.json` cannot corroborate anything.

    Reachable from a hand-cleaned cache directory, and "the tool cannot say which
    document this is" must not become "so any document will do".
    """
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    cache = write_cache(tmp_path, url=None)
    code = cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", SOURCE, "--page", "2", "--quote", QUOTE,
        "--cache", str(cache), "--library", str(shelf),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "来源记录" in captured.err
    assert shelf.read_bytes() == before


def test_the_matching_url_is_written_verbatim_and_the_output_names_it(
    tmp_path, capsys
):
    """The accepted leg: `--from` == the cache's url → the citation is that url,
    and the output says which document the quote was checked on."""
    shelf = shelf_without_category(tmp_path)
    cache = write_cache(tmp_path)
    report = tmp_path / "classify.json"
    code = cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", SOURCE, "--page", "2", "--quote", QUOTE,
        "--cache", str(cache), "--library", str(shelf), "--json", str(report),
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert target_of(shelf)["category_provenance"] == {
        "source": SOURCE, "page": 2, "quote": QUOTE,
    }
    # 「引文逐字对上」 now names its document, terminal and `--json` alike.
    assert f"checked document: {SOURCE}" in out
    assert json.loads(report.read_text(encoding="utf-8"))["checkedSource"] == SOURCE


@pytest.mark.parametrize(
    "source", ["http://", "https://", "HTTP://", "file:", "file:   ", "file://"]
)
def test_a_source_with_a_scheme_and_no_address_is_refused(tmp_path, capsys, source):
    """`http://` / `file:` pass a prefix test and name nothing.

    Both ends of the door are pinned here: the command refuses at
    `_classify_evidence` (before any cache read) and the loader refuses the same
    string in `entry_from_json`, so a hand-edited shelf cannot smuggle one in
    either (`test_loader_refuses_a_scheme_with_no_address` below).
    """
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", source, "--page", "2", "--quote", QUOTE,
        "--cache", str(write_cache(tmp_path)), "--library", str(shelf),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "只收 http(s) URL 或 file: 路径" in captured.err or (
        "没有主机名" in captured.err or "没有路径" in captured.err
    )
    assert shelf.read_bytes() == before
    assert not (tmp_path / "parts.json.tmp").exists()


def test_loader_refuses_a_scheme_with_no_address():
    """The loader's half: a shelf holding `"http://"` as a citation is refused
    rather than loaded as an address nobody can open."""
    base = {
        "key": "ic.acme9", "lcsc": "C9900000001",
        "deviceUuid": "dev-1", "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
        "category": "ic.ldo",
    }
    with pytest.raises(PartError, match="no host"):
        entry_from_json({**base, "category_provenance": {
            "source": "http://", "page": 2, "quote": QUOTE}})
    with pytest.raises(PartError, match="no path"):
        entry_from_json({**base, "category_provenance": {
            "source": "file:", "page": 2, "quote": QUOTE}})
    with pytest.raises(PartError, match="neither a http\\(s\\) URL"):
        entry_from_json({**base, "category_provenance": {
            "source": "note.txt", "page": 2, "quote": QUOTE}})


# --------------------------------------------------------------------------
# ⑧ a new run's evidence replaces the previous one (red team, hole 3)
# --------------------------------------------------------------------------


def test_a_second_run_with_different_evidence_replaces_the_citation(
    tmp_path, capsys
):
    """The write **overwrites**; it does not `setdefault`.

    Measured hole: every test in the batch classified the same entry with the
    same `--from/--page/--quote`, so flipping the assignment to "keep what is
    already there" left the suite green — and a real two-run sequence then landed
    `category: ic.ldo` beside the **first** run's buck quote, a citation for a
    claim nobody made. The old evidence is a machine signature too, so keeping it
    is exactly as bad as keeping a stale tier.
    """
    shelf = shelf_without_category(tmp_path)
    first = tmp_path / "first.txt"
    first.write_text(
        "<<<page 1>>>\nACME9 cover\n"
        "<<<page 2>>>\nLM5164 is a 100 V step-down buck converter.\n",
        encoding="utf-8",
    )
    second = tmp_path / "second.txt"
    second.write_text(
        "<<<page 1>>>\nACME9 cover, second edition\n"
        "<<<page 2>>>\nLM5164 can also serve as a step-up controller.\n",
        encoding="utf-8",
    )
    assert cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", f"file:{first}", "--page", "2", "--quote", QUOTE,
        "--library", str(shelf),
    ]) == 0
    capsys.readouterr()
    assert target_of(shelf)["category_provenance"] == {
        "source": f"file:{first}", "page": 2, "quote": QUOTE,
    }
    second_quote = "LM5164 can also serve as a step-up controller."
    assert cli.main([
        "parts", "classify", TARGET_MPN, "ic.ldo",
        "--from", f"file:{second}", "--page", "2", "--quote", second_quote,
        "--library", str(shelf),
    ]) == 0
    capsys.readouterr()
    # All three fields moved, together — source, page and quote.
    assert target_of(shelf)["category_provenance"] == {
        "source": f"file:{second}", "page": 2, "quote": second_quote,
    }
    assert target_of(shelf)["category"] == "ic.ldo"
    assert load_parts(shelf).get(TARGET_KEY).category_provenance["quote"] == second_quote


def test_a_second_run_that_only_moves_the_page_replaces_the_page(
    tmp_path, capsys
):
    """`--page` is part of the citation: the same document, the same sentence
    length, a different page — the shelf must say the new one."""
    shelf = shelf_without_category(tmp_path)
    dump = tmp_path / "paged.txt"
    dump.write_text(
        "<<<page 1>>>\nLM5164 is a 100 V step-down buck converter.\n"
        "<<<page 2>>>\nLM5164 is a 100 V step-down buck converter.\n"
        "<<<page 3>>>\nLM5164 is a 100 V step-down buck converter.\n",
        encoding="utf-8",
    )
    for page in (1, 3):
        assert cli.main([
            "parts", "classify", TARGET_MPN, "ic.buck",
            "--from", f"file:{dump}", "--page", str(page), "--quote", QUOTE,
            "--library", str(shelf),
        ]) == 0
        capsys.readouterr()
        assert target_of(shelf)["category_provenance"]["page"] == page


# --------------------------------------------------------------------------
# ⑨ the display end: which tier the citation belongs to (red team, hole 4)
# --------------------------------------------------------------------------


def show(shelf: Path, tmp_path: Path, capsys) -> tuple[str, dict]:
    """`parts show` on one shelf: ``(terminal output, the --json entry)``."""
    dump = tmp_path / "show.json"
    assert cli.main([
        "parts", "show", TARGET_MPN, "--library", str(shelf), "--json", str(dump),
    ]) == 0
    out = capsys.readouterr().out
    return out, json.loads(dump.read_text(encoding="utf-8"))["entry"]


def shelf_with(shelf: Path, **fields) -> Path:
    """The copied shelf with `fields` stamped onto the target entry (``None``
    removes the key), i.e. the hand-edited/sidecar shapes the loader loads."""
    raw = json.loads(shelf.read_text(encoding="utf-8"))
    for item in raw["parts"]:
        if item["key"] == TARGET_KEY:
            for name, value in fields.items():
                if value is None:
                    item.pop(name, None)
                else:
                    item[name] = value
    shelf.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return shelf


def test_show_prints_the_citation_for_a_machine_class_and_marks_it_expected(
    tmp_path, capsys
):
    """machine + citation: printed, and `categoryProvenanceExpected` is true."""
    shelf = shelf_with(
        shelf_without_category(tmp_path),
        category="ic.buck",
        category_trust=FACTS_TRUST_MACHINE,
        category_provenance={"source": SOURCE, "page": 2, "quote": QUOTE},
    )
    out, entry = show(shelf, tmp_path, capsys)
    assert f"category provenance: {SOURCE} 第 2 页" in out
    assert f"quote: {QUOTE}" in out
    assert entry["categoryProvenance"] == {
        "source": SOURCE, "page": 2, "quote": QUOTE,
    }
    assert entry["categoryProvenanceExpected"] is True


def test_show_says_a_machine_class_has_no_recorded_source(tmp_path, capsys):
    """machine + no citation: the state 0.5.18's `parts classify` could write
    (it set the tier, not the evidence). Silence would read as "checked, nothing
    to cite", so it is said out loud."""
    shelf = shelf_with(
        shelf_without_category(tmp_path),
        category="ic.buck",
        category_trust=FACTS_TRUST_MACHINE,
        category_provenance=None,
    )
    out, entry = show(shelf, tmp_path, capsys)
    assert "未记录出处" in out
    assert "第 2 页" not in out
    # The raw key stays null, and the new boolean is what tells a script that
    # this null is the *missing* one rather than a human tier's normal shape.
    assert entry["categoryProvenance"] is None
    assert entry["categoryProvenanceExpected"] is True


def test_show_does_not_print_a_citation_for_a_hand_signed_class(tmp_path, capsys):
    """human + citation (a hand edit, or a sidecar's `curated.fields`): the
    loader loads it — one entry must not fail the whole shelf — and `parts show`
    says the citation decides nothing, rather than printing it under a verified
    class as if a machine had checked it."""
    shelf = shelf_with(
        shelf_without_category(tmp_path),
        category="ic.buck",
        category_trust=None,
        category_provenance={"source": SOURCE, "page": 2, "quote": QUOTE},
    )
    out, entry = show(shelf, tmp_path, capsys)
    assert "这条分类是人签的，落盘的引文不参与判定" in out
    assert f"quote: {QUOTE}" not in out
    assert "第 2 页" not in out
    # `--json` keeps the raw data (it is in the file) and answers "is it
    # expected" with false — the pair a script needs.
    assert entry["categoryProvenance"] == {
        "source": SOURCE, "page": 2, "quote": QUOTE,
    }
    assert entry["categoryProvenanceExpected"] is False
