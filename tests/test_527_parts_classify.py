"""527D (TASKMAP 523): `parts classify` — the first-class route to a `category`.

The gap this batch closes is measured, not theoretical: `parts hunt
--apply-facts` can write facts through 521's six gates and land them
`facts_trust: machine_verified`, but nothing could set the **class** those facts
are judged against — `rules.facts._category_state` answers UNKNOWN for an entry
whose `category` is empty, whatever else is on it — so the only route was editing
`blocklib/parts.json` by hand.

Two things are therefore under test, and they are the same ruling seen twice:

* the **command** — one word from the shelf's own table, three evidence flags
  taken as a set, and exactly the class's own keys of exactly one entry moving
  (`category`, `category_trust`, and — since 527D2 — the machine tier's
  `category_provenance` citation);
* the **reach** of what it writes — a category is a *conclusion* ("this is an
  LDO"), so 522's dividing line applies: `category_trust: machine_verified`
  unlocks the calculation rules and no conclusion rule, while an entry with no
  `category_trust` at all (every entry written before this field existed) keeps
  behaving exactly as it did.

Zero network, like 521/522: the `file:` leg reads a dump from disk, and the
`http(s)` leg reads the page dump stage one already cached. A test that needed a
socket would be asserting something this batch cannot promise.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from boardwise import cli
from boardwise.core.parts import (
    CATEGORY_VOCABULARY,
    FACTS_TRUST_CANDIDATE,
    FACTS_TRUST_MACHINE,
    FACTS_TRUST_VERIFIED,
    PartEntry,
    PartError,
    PartProvenance,
    category_families,
    entry_from_json,
    entry_to_json,
    load_parts,
)
from boardwise.rules.facts import _category_absent_reason, _category_state

ROOT = Path(__file__).resolve().parents[1]
#: The real shelf, copied by the tests below. A fixture with two hand-built
#: entries would not exercise the property that matters most here — that the
#: other 108 entries keep their exact bytes.
REAL_SHELF = ROOT / "blocklib" / "parts.json"

#: The entry the end-to-end runs re-classify: LM5164 is the `ic.buck` 128 added,
#: and its `category` is taken back off in the fixture below so a write has
#: something to do.
TARGET_KEY = "ic.lm5164ddar"
TARGET_MPN = "LM5164DDAR"
TARGET_LCSC = "C477928"

DUMP = (
    "<<<page 1>>>\n"
    "ACME9 Cover page\n"
    "<<<page 2>>>\n"
    "LM5164 is a 100 V step-down buck converter.\n"
)
QUOTE = "LM5164 is a 100 V step-down buck converter."
#: 527D2: the url `parts fetch`/`hunt` record in the cache's `.meta.json` when the
#: bytes arrive. The `http(s)` leg of `--from` is now matched against it.
CACHED_URL = "https://www.ti.com/cn/lit/gpn/lm5164"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def shelf_without_category(tmp_path: Path, *, key: str = TARGET_KEY) -> Path:
    """The real shelf, copied, with one entry's category taken back off."""
    raw = json.loads(REAL_SHELF.read_text(encoding="utf-8"))
    for item in raw["parts"]:
        if item["key"] == key:
            item.pop("category", None)
            item.pop("category_trust", None)
    shelf = tmp_path / "parts.json"
    shelf.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return shelf


def page_dump(tmp_path: Path, text: str = DUMP) -> Path:
    path = tmp_path / "lm5164.txt"
    path.write_text(text, encoding="utf-8")
    return path


def write_cache(
    root: Path, *, lcsc: str = TARGET_LCSC, pages: list[str], url: str | None = CACHED_URL
) -> Path:
    """A stage-one cache entry: `<root>/<C码>/<C码>.{pages.json,txt,pdf,meta.json}`.

    The shape 521's own tests build, because this is the same file `--apply-facts`
    reads and the "`http(s)` --from" leg is exactly that read. 527D2 adds the
    `.meta.json` (what `parts fetch` writes when the bytes arrive) and makes it
    optional, so the "cache has a dump but no url record" case can be built too.
    """
    directory = root / lcsc
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{lcsc}.pages.json").write_text(
        json.dumps(pages, ensure_ascii=False), encoding="utf-8"
    )
    (directory / f"{lcsc}.txt").write_text(
        "\n".join(f"<<<page {index}>>>\n{page}" for index, page in enumerate(pages, 1)),
        encoding="utf-8",
    )
    (directory / f"{lcsc}.pdf").write_bytes(b"%PDF-1.4 stub")
    if url is not None:
        (directory / f"{lcsc}.meta.json").write_text(
            json.dumps(
                {"url": url, "channel": "detail-api", "bytes": 123},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return root


def classify(shelf: Path, *argv: str) -> int:
    return cli.main(["parts", "classify", *argv, "--library", str(shelf)])


def target_of(shelf: Path) -> dict:
    raw = json.loads(shelf.read_text(encoding="utf-8"))
    return next(item for item in raw["parts"] if item["key"] == TARGET_KEY)


def others_of(raw: dict) -> str:
    """Every entry but the target, serialised — a byte comparison of the rest."""
    return json.dumps(
        [item for item in raw["parts"] if item["key"] != TARGET_KEY],
        ensure_ascii=False,
        indent=2,
    )


# --------------------------------------------------------------------------
# 1/2: the door — the word, and the entry
# --------------------------------------------------------------------------


def test_a_word_outside_the_vocabulary_is_refused_and_the_families_are_listed(
    tmp_path, capsys
):
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = classify(shelf, TARGET_MPN, "transistor")
    captured = capsys.readouterr()
    assert code == 2
    assert "不在货架的分类词表里" in captured.err
    # Every legal top-level family, and the sub-words of the one family that has
    # them: a refusal that said only "no" would leave the reader guessing at the
    # 20 words the table actually holds.
    families = category_families()
    for family in families:
        assert family in captured.err
    assert "ic.buck" in captured.err and "ic.ldo" in captured.err
    assert shelf.read_bytes() == before, "a refused word must not touch the shelf"
    assert not (tmp_path / "parts.json.tmp").exists()


def test_an_entry_the_shelf_does_not_have_is_refused_and_nothing_is_created(
    tmp_path, capsys
):
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = classify(shelf, "NOSUCH-MPN-9", "ic.ldo")
    captured = capsys.readouterr()
    assert code == 2
    assert "里没有" in captured.err and "不新建" in captured.err
    assert shelf.read_bytes() == before, "this command never creates an entry"
    assert not (tmp_path / "parts.json.tmp").exists()
    assert load_parts(shelf).get("NOSUCH-MPN-9") is None


# --------------------------------------------------------------------------
# 3/4: the two tiers
# --------------------------------------------------------------------------


def test_evidence_writes_the_machine_tier_and_moves_only_the_two_keys(
    tmp_path, capsys
):
    shelf = shelf_without_category(tmp_path)
    raw_before = json.loads(shelf.read_text(encoding="utf-8"))
    code = classify(
        shelf,
        TARGET_MPN,
        "ic.buck",
        "--from",
        f"file:{page_dump(tmp_path)}",
        "--page",
        "2",
        "--quote",
        QUOTE,
    )
    out = capsys.readouterr().out
    assert code == 0
    entry = load_parts(shelf).get(TARGET_KEY)
    assert entry.category == "ic.buck"
    assert entry.category_trust == FACTS_TRUST_MACHINE
    # The tier is spelled out in the file (a machine granted it, so a reader has
    # to see it without opening the tool — 522's rule for `facts_trust`).
    raw_after = json.loads(shelf.read_text(encoding="utf-8"))
    assert target_of(shelf)["category_trust"] == FACTS_TRUST_MACHINE

    # …and nothing else moved: every other entry keeps its exact bytes, and the
    # target's other keys are untouched.
    assert others_of(raw_before) == others_of(raw_after)
    before_target = next(
        item for item in raw_before["parts"] if item["key"] == TARGET_KEY
    )
    after_target = target_of(shelf)
    changed = {
        name
        for name in set(before_target) | set(after_target)
        if before_target.get(name) != after_target.get(name)
    }
    # 527D2: the class's own keys are `category`, `category_trust` **and** the
    # evidence the machine run writes (`category_provenance`) — the citation
    # belongs to the class, so it moves with it; nothing else does.
    assert changed == {"category", "category_trust", "category_provenance"}
    assert "机器核验档" in out


def test_no_evidence_writes_the_human_tier_and_says_there_is_no_quote(
    tmp_path, capsys
):
    shelf = shelf_without_category(tmp_path)
    code = classify(shelf, TARGET_MPN, "ic.buck")
    out = capsys.readouterr().out
    assert code == 0
    assert "无引文，按人工签署记账" in out
    entry = load_parts(shelf).get(TARGET_KEY)
    assert entry.category == "ic.buck"
    assert entry.category_trust == FACTS_TRUST_VERIFIED
    # `verified` writes **no key** (039/522's spelling), so an entry a human
    # signed looks exactly like the 109 that predate the field.
    assert "category_trust" not in target_of(shelf)


def test_a_second_run_without_evidence_takes_the_machine_signature_back(
    tmp_path, capsys
):
    shelf = shelf_without_category(tmp_path)
    dump = page_dump(tmp_path)
    assert (
        classify(
            shelf, TARGET_MPN, "ic.buck",
            "--from", f"file:{dump}", "--page", "2", "--quote", QUOTE,
        )
        == 0
    )
    assert target_of(shelf)["category_trust"] == FACTS_TRUST_MACHINE
    capsys.readouterr()
    # Re-signing by hand must not leave the machine tier sitting in the file: the
    # file would then claim a machine granted a class a human just took over.
    assert classify(shelf, TARGET_MPN, "ic.buck") == 0
    assert "无引文，按人工签署记账" in capsys.readouterr().out
    assert "category_trust" not in target_of(shelf)
    assert load_parts(shelf).get(TARGET_KEY).category_trust == FACTS_TRUST_VERIFIED


# --------------------------------------------------------------------------
# 5/6: the evidence gates
# --------------------------------------------------------------------------


def test_a_quote_below_521s_floor_is_refused(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = classify(
        shelf, TARGET_MPN, "ic.buck",
        "--from", f"file:{page_dump(tmp_path)}", "--page", "2", "--quote", "3 V",
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "引文太短" in captured.err
    assert shelf.read_bytes() == before


def test_a_quote_that_is_not_on_the_page_it_cites_is_refused(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = classify(
        shelf, TARGET_MPN, "ic.buck",
        "--from", f"file:{page_dump(tmp_path)}", "--page", "2",
        "--quote", "LM5164 is a 12 V boost controller.",
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "找不到引文" in captured.err
    assert shelf.read_bytes() == before


def test_a_page_past_the_end_of_the_document_is_refused(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = classify(
        shelf, TARGET_MPN, "ic.buck",
        "--from", f"file:{page_dump(tmp_path)}", "--page", "9", "--quote", QUOTE,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "不在 1..2 里" in captured.err
    assert shelf.read_bytes() == before


@pytest.mark.parametrize("source", ["ftp://example.com/x.pdf", "note.txt", "C:/tmp/x.pdf"])
def test_a_source_that_is_neither_http_nor_file_is_refused(tmp_path, capsys, source):
    """522/524's 保密口径: a bare path would have the tool read a file the caller
    never named as a datasheet."""
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = classify(
        shelf, TARGET_MPN, "ic.buck",
        "--from", source, "--page", "2", "--quote", QUOTE,
    )
    captured = capsys.readouterr()
    assert code == 2
    assert "只收 http(s) URL 或 file: 路径" in captured.err
    assert shelf.read_bytes() == before


@pytest.mark.parametrize(
    "argv",
    [
        ("--from", "file:dump.txt"),
        ("--page", "2"),
        ("--quote", "some sentence that is long enough"),
        ("--from", "file:dump.txt", "--page", "2"),
    ],
)
def test_half_the_evidence_is_refused_rather_than_guessed(tmp_path, capsys, argv):
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = classify(shelf, TARGET_MPN, "ic.buck", *argv)
    captured = capsys.readouterr()
    assert code == 2
    assert "三条齐全" in captured.err
    assert shelf.read_bytes() == before


def test_an_http_source_reads_the_dump_stage_one_cached(tmp_path, capsys):
    """The `http(s)` leg is `--apply-facts`'s own read — the cache under
    `<cache>/<C码>/`, never a socket. 527D2: `--from` must be the url the cache
    recorded for that entry, which is what makes the citation name the document
    the quote was actually checked on."""
    shelf = shelf_without_category(tmp_path)
    cache = write_cache(
        tmp_path / "cache",
        pages=[
            "ACME9 Cover page",
            "LM5164 is a 100 V step-down buck converter.",
        ],
    )
    code = cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", CACHED_URL,
        "--page", "2", "--quote", QUOTE,
        "--cache", str(cache), "--library", str(shelf),
    ])
    capsys.readouterr()
    assert code == 0
    assert load_parts(shelf).get(TARGET_KEY).category_trust == FACTS_TRUST_MACHINE


def test_a_file_source_accepts_the_browser_spelling_of_a_local_path(tmp_path, capsys):
    """`file:///C:/…` is the same file as `file:C:/…` — and the same gate.

    Not a nicety: the URL form is what a reader copies out of a browser or a
    terminal, and refusing it would send them looking for a `file:` spelling the
    tool never asked for by name.
    """
    shelf = shelf_without_category(tmp_path)
    dump = page_dump(tmp_path)
    code = classify(
        shelf, TARGET_MPN, "ic.buck",
        "--from", "file:///" + str(dump).replace("\\", "/"),
        "--page", "2", "--quote", QUOTE,
    )
    capsys.readouterr()
    assert code == 0
    assert load_parts(shelf).get(TARGET_KEY).category_trust == FACTS_TRUST_MACHINE


def test_an_http_source_with_no_cached_dump_is_refused(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    before = shelf.read_bytes()
    code = cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", CACHED_URL,
        "--page", "2", "--quote", QUOTE,
        "--cache", str(tmp_path / "empty"), "--library", str(shelf),
    ])
    captured = capsys.readouterr()
    assert code == 2
    assert "没有" in captured.err and "本命令不外呼" in captured.err
    assert shelf.read_bytes() == before


# --------------------------------------------------------------------------
# 7/8: what the tier reaches
# --------------------------------------------------------------------------


def test_a_machine_verified_category_needs_a_human_where_facts_do():
    """527D's core ruling: a category is a **conclusion**, so the machine tier
    unlocks the number rules only — exactly what `facts_trust` already does."""
    entry = PartEntry(
        key="ic.acme9", mpn="ACME9", lcsc="C9900000001",
        category="ic.buck", category_trust=FACTS_TRUST_MACHINE,
    )
    assert _category_state(entry, allow_machine=False) == "unknown"
    reason = _category_absent_reason(entry, allow_machine=False)
    assert "机器核验" in reason
    # The same entry to a calculation rule: classified, as it is for `verified`.
    assert _category_state(entry, allow_machine=True) == "ic"
    # …and "not an IC" is not a hole either: a machine-granted non-IC class is
    # just as invisible to a conclusion rule.
    passive = PartEntry(
        key="res.acme", lcsc="C9900000002",
        category="resistor", category_trust=FACTS_TRUST_MACHINE,
    )
    assert _category_state(passive, allow_machine=False) == "unknown"
    assert _category_state(passive, allow_machine=True) == "non-ic"


def test_a_category_a_human_signed_is_not_gated_at_all():
    entry = PartEntry(key="ic.acme9", lcsc="C9900000001", category="ic.ldo")
    assert entry.category_trust == FACTS_TRUST_VERIFIED
    for allow_machine in (True, False):
        assert _category_state(entry, allow_machine=allow_machine) == "ic"


def test_a_legacy_entry_without_the_field_behaves_exactly_as_before():
    """The 109 entries written before `category_trust` existed must not move."""
    legacy = entry_from_json({
        "key": "ic.acme9", "lcsc": "C9900000001", "category": "ic.ldo",
        "deviceUuid": "dev-1", "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
    })
    assert legacy.category_trust == FACTS_TRUST_VERIFIED
    for allow_machine in (True, False):
        assert _category_state(legacy, allow_machine=allow_machine) == "ic"
    # Round-trip: a hand-signed class writes no key, so its bytes do not move.
    assert "category_trust" not in entry_to_json(legacy)
    # The two existing unknowns are untouched: no category, and a closed gate.
    blank = entry_from_json({
        "key": "ic.acme9", "lcsc": "C9900000001",
        "deviceUuid": "dev-1", "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
    })
    assert _category_state(blank, allow_machine=False) == "unknown"
    assert "no category" in _category_absent_reason(blank, allow_machine=False)
    candidate = entry_from_json({
        "key": "ic.acme9", "lcsc": "C9900000001", "category": "ic.ldo",
        "facts_trust": FACTS_TRUST_CANDIDATE,
    })
    for allow_machine in (True, False):
        assert _category_state(candidate, allow_machine=allow_machine) == "unknown"
        assert "unverified" in _category_absent_reason(
            candidate, allow_machine=allow_machine
        )


def test_the_loader_refuses_a_typo_tier_and_round_trips_the_machine_one():
    """One vocabulary for both fields, and a tier nobody typed is an error."""
    with pytest.raises(PartError):
        entry_from_json({"key": "ic.a", "lcsc": "C1", "category_trust": "machin_verified"})
    with pytest.raises(PartError):
        entry_from_json({"key": "ic.a", "lcsc": "C1", "category_trust": None})
    with pytest.raises(PartError):
        PartEntry(key="ic.a", category_trust="verified_ish")
    body = entry_to_json(PartEntry(
        key="ic.a", lcsc="C1", category="ic.ldo",
        category_trust=FACTS_TRUST_MACHINE, facts_trust=FACTS_TRUST_MACHINE,
    ))
    assert body["category_trust"] == FACTS_TRUST_MACHINE
    assert entry_from_json(body).category_trust == FACTS_TRUST_MACHINE


# --------------------------------------------------------------------------
# the operator's windows: `parts show` and `--json`
# --------------------------------------------------------------------------


def test_the_command_can_be_pointed_at_a_c_number(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    assert classify(shelf, TARGET_LCSC, "ic.buck") == 0
    out = capsys.readouterr().out
    assert "按 lcsc 对上" in out
    assert load_parts(shelf).get(TARGET_KEY).category == "ic.buck"


def test_parts_show_prints_who_signed_the_category(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    dump = page_dump(tmp_path)
    assert (
        classify(
            shelf, TARGET_MPN, "ic.buck",
            "--from", f"file:{dump}", "--page", "2", "--quote", QUOTE,
        )
        == 0
    )
    capsys.readouterr()
    code = cli.main(["parts", "show", TARGET_MPN, "--library", str(shelf)])
    out = capsys.readouterr().out
    assert code == 0
    assert "category: ic.buck" in out
    assert "category trust: machine_verified" in out
    assert "要人签字" in out


def test_the_json_report_carries_the_evidence_and_the_tier(tmp_path, capsys):
    shelf = shelf_without_category(tmp_path)
    dump = page_dump(tmp_path)
    report = tmp_path / "classify.json"
    code = cli.main([
        "parts", "classify", TARGET_MPN, "ic.buck",
        "--from", f"file:{dump}", "--page", "2", "--quote", QUOTE,
        "--library", str(shelf), "--json", str(report),
    ])
    capsys.readouterr()
    assert code == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["command"] == "parts-classify"
    assert payload["category"] == "ic.buck"
    assert payload["categoryTrust"] == FACTS_TRUST_MACHINE
    assert payload["evidence"]["page"] == 2
    assert payload["evidence"]["quote"] == QUOTE
    assert payload["entry"] == TARGET_KEY
    # `parts show --json` reports the same tier beside the same category.
    dump_path = tmp_path / "show.json"
    assert cli.main([
        "parts", "show", TARGET_MPN, "--library", str(shelf),
        "--json", str(dump_path),
    ]) == 0
    capsys.readouterr()
    entry_dump = json.loads(dump_path.read_text(encoding="utf-8"))["entry"]
    assert entry_dump["category"] == "ic.buck"
    assert entry_dump["categoryTrust"] == FACTS_TRUST_MACHINE


def test_the_vocabulary_is_still_the_single_source_of_truth():
    """The command's list and the shelf's table are one table (527D)."""
    assert "ic.buck" in CATEGORY_VOCABULARY
    families = category_families()
    assert set(families) == {word.split(".", 1)[0] for word in CATEGORY_VOCABULARY}
    flat = sorted(word for words in families.values() for word in words)
    assert flat == sorted(CATEGORY_VOCABULARY)


def test_shelf_declaration_asks_the_category_its_own_tier():
    """The reach of the class's tier, at the **other** gate (527D follow-up).

    `_category_state` is the facts-rule gate; `core.partkind.shelf_declaration`
    is the *judging* gate every 判型 path goes through (190/192B — `distance`,
    `sensebias`, `archclosure` and `classify_part` all read the shelf through
    it). The first cut of this batch asked only `facts_trust` there, so
    `parts classify --from … --quote …` on an entry whose facts a person had
    already signed — exactly the state the command produces — handed a
    machine-granted class to every conclusion rule as if a signature were on it.
    Two tiers, two questions.
    """
    from boardwise.core.partkind import shelf_declaration

    machine_class = PartEntry(
        key="ic.acme9", mpn="ACME9", lcsc="C9900000001",
        category="ic.buck", category_trust=FACTS_TRUST_MACHINE,
        facts_trust=FACTS_TRUST_VERIFIED,
    )
    assert shelf_declaration(machine_class) == "", (
        "a machine-granted class must not declare itself to a conclusion rule"
    )

    # The number rules still get it, through `_category_state(allow_machine=True)`
    # — that is the half the tier is FOR.
    assert _category_state(machine_class, allow_machine=True) == "ic"

    # A human-signed class, and an entry written before the field existed, are
    # unchanged: the shelf declares both.
    human = PartEntry(key="ic.acme8", lcsc="C9900000003", category="ic.ldo")
    assert shelf_declaration(human) == "ic.ldo"
    # A `verified` entry must be resolvable (039), so the uuid pair is part of
    # what "written before this field existed" looks like.
    legacy = entry_from_json({
        "key": "ic.acme7", "lcsc": "C9900000004", "category": "ic.ldo",
        "facts_trust": "verified",
        "deviceUuid": "dev-2", "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
    })
    assert shelf_declaration(legacy) == "ic.ldo"


def test_the_hunt_rebuild_inherits_every_field():
    """527D's sweep, H1: a rebuild that forgets a field **resets** it.

    `_hunt_write_shelf` does not mutate the shelf entry — it constructs a new
    `PartEntry` and inherits the old one's fields by hand, one keyword at a time.
    That is what made 522's hole possible once and what made this batch's
    possible again: `parts classify --from … --quote …` writes
    `category_trust: machine_verified`, and a later `parts hunt --apply-facts`
    reconstructed the entry without that keyword, so the class came back
    `verified` — **a machine-granted conclusion silently upgraded into a human
    signature**, the one direction the whole tier exists to prevent.

    Pinned structurally rather than by one fixture, because the next field added
    to `PartEntry` has the same trap: read the rebuild's own `PartEntry(...)`
    call and require a keyword for every field the dataclass declares. Read
    through the **AST**, not the source text: a comment that happens to spell a
    field name is not an inheritance, and the first cut's text search could not
    tell the difference.

    527D2 measured the hole in the first cut of this test: the filter was
    `field.name.endswith("_trust")`, so `category_provenance` — the field this
    batch added, and the one whose loss resurrects exactly the same
    "machine granted it, evidence erased" shape one field over — was **not
    covered**. Deleting the three inheritance lines from the rebuild left both
    test files at 36 passed. The judgement is therefore the whole dataclass, and
    the exemptions are named one by one rather than implied by a name pattern.
    """
    import ast
    import dataclasses
    import inspect

    from boardwise import cli

    tree = ast.parse(inspect.getsource(cli._hunt_write_shelf))
    builds = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "PartEntry"
    ]
    assert len(builds) == 1, (
        "expected exactly one `PartEntry(...)` construction in the rebuild, found "
        f"{len(builds)} — this test judges that call"
    )
    passed = {keyword.arg for keyword in builds[0].keywords}
    #: Fields the rebuild does **not** pass, with the reason each is exempt:
    #:
    #: * `candidate_facts` — **derived**, not stored: `PartEntry.__post_init__`
    #:   computes it from `facts` (the gate-shut view), so it cannot be lost by
    #:   the rebuild and must not be passed in (the constructor would be saying
    #:   two things about the same claim).
    #:
    #: A field added to `PartEntry` later lands here by default — this dict is
    #: the whole exemption list, so forgetting to inherit a new field is red.
    derived = {
        "candidate_facts": "__post_init__ derives it from `facts`",
    }
    fields = [field.name for field in dataclasses.fields(PartEntry)]
    assert "candidate_facts" in fields, (
        "the exemption list is stale — `candidate_facts` is no longer a field, "
        "so the whitelist is hiding something"
    )
    for name in fields:
        if name in derived:
            continue
        assert name in passed, (
            f"`_hunt_write_shelf` rebuilds the entry without inheriting {name!r} "
            "— the rebuilt entry would silently take the default "
            f"(527D2: this is how `category_trust` was reset once and how "
            "`category_provenance` would be erased). Exempt it in `derived` "
            "with the reason, or inherit it."
        )
    # The exemption list itself must not grow into a hole: every entry has a
    # non-empty reason, names a real field, and is a field the call really does
    # not pass (an exemption for something that is passed hides nothing, but it
    # does mean the list has drifted).
    assert all(
        reason.strip() and name in fields and name not in passed
        for name, reason in derived.items()
    ), f"the exemption list is stale: {derived} vs passed {sorted(passed)}"


def test_the_hunt_rebuild_keeps_a_machine_classs_citation(tmp_path):
    """The structural test's behavioural half (527D2): the rebuild really does
    put the citation back on the entry it rewrites.

    A `category_provenance=` keyword in the source is not the same claim as "the
    citation survives the rebuild" — the field could be read from the wrong
    place, or dropped by `entry_to_json` afterwards. So an entry that carries a
    machine-granted class **and** its citation goes through a real
    `_hunt_write_shelf` run, beside a fresh facts claim for the same identity —
    which is exactly what `parts hunt --apply-facts` does to a part a previous
    `parts classify --from … --quote …` had already classified.
    """
    proven = {"source": "https://www.ti.com/cn/lit/gpn/lm5164", "page": 2, "quote": QUOTE}
    shelf = tmp_path / "parts.json"
    shelf.write_text(
        json.dumps(
            {
                "kind": "boardwise-part-library",
                "version": 2,
                "sources": [],
                "notes": [],
                "parts": [
                    {
                        "key": "ic.lm5164ddar",
                        "mpn": "LM5164DDAR",
                        "lcsc": TARGET_LCSC,
                        # A `verified` entry must be resolvable (039), which is
                        # what the shelf holds until the rebuild lands facts on it.
                        "deviceUuid": "aef6a3b388cc4d0fac09a8cb1dea8191",
                        "libraryUuid": "0819f05c4eef4c71ace90d822a990e87",
                        "category": "ic.buck",
                        "category_trust": FACTS_TRUST_MACHINE,
                        "category_provenance": dict(proven),
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    class Outcome:
        # The five attributes `_hunt_write_shelf` reads off a claim outcome
        # (`engines.hunt.claim_outcome`'s shape, without running an extractor).
        identity = {"lcsc": TARGET_LCSC, "mpn": "LM5164DDAR"}
        outcome = "facts-read"
        facts = {
            "supply_pins": [
                {"name": "VIN", "pins": ["1"], "provenance": "file:C477928.txt, p.2"},
            ]
        }
        url = "https://www.ti.com/cn/lit/gpn/lm5164"
        read_by_someone = True
        designator = "U1"

    said = cli._hunt_write_shelf(str(shelf), [Outcome()])
    assert "更新 1 条" in said, said
    entry = load_parts(shelf).get("ic.lm5164ddar")
    assert entry.category == "ic.buck"
    assert entry.category_trust == FACTS_TRUST_MACHINE, (
        "the rebuild downgraded a machine-granted class to a human signature"
    )
    assert entry.category_provenance == proven, (
        "the rebuild kept the machine-granted class but erased the citation that "
        "lets anyone re-check it"
    )
    # …and it survived as far as the written document, not only the object.
    raw = json.loads(shelf.read_text(encoding="utf-8"))
    written = next(item for item in raw["parts"] if item["key"] == "ic.lm5164ddar")
    assert written["category_provenance"] == proven


def test_a_machine_category_finding_says_so():
    """527D's sweep, H2: the caveat has to reach the finding, not just the rules.

    522's physical guarantee is that a report cannot paint a machine-checked
    number green: every finding driven by `machine_verified` carries
    `machine_trust_note`. That sentence was generated from `facts_trust` alone,
    so a finding driven by a machine-granted **class** on an entry whose facts a
    person had signed arrived with no caveat at all — which is exactly the state
    `parts classify --from … --quote …` produces.
    """
    from boardwise.core.parts import machine_trust_note

    signed_facts = {
        "supply_pins": [
            {"pin": "1", "provenance": "file:C123.txt, p.2", "verified": True},
        ],
    }
    machine_class = PartEntry(
        key="ic.acme9", mpn="ACME9", lcsc="C9900000001",
        category="ic.ldo", category_trust=FACTS_TRUST_MACHINE,
        facts=signed_facts, facts_trust=FACTS_TRUST_VERIFIED,
        deviceUuid="dev-1", libraryUuid="0819f05c4eef4c71ace90d822a990e87",
        provenance=PartProvenance(kind="hunt-read", source="file:C123.txt"),
    )
    note = machine_trust_note(machine_class)
    assert "机器核验" in note and "未人工确认" in note
    assert "分类" in note, "the sentence must name which half is unsigned"

    both = PartEntry(
        key="ic.acme8", lcsc="C9900000002",
        category="ic.ldo", category_trust=FACTS_TRUST_MACHINE,
        facts=signed_facts, facts_trust=FACTS_TRUST_MACHINE,
        provenance=PartProvenance(kind="hunt-read", source="file:C123.txt"),
    )
    both_note = machine_trust_note(both)
    assert "参数与分类" in both_note

    human = PartEntry(key="ic.acme7", lcsc="C9900000003", category="ic.ldo")
    assert machine_trust_note(human) == "", (
        "a human-signed entry's row must stay byte-identical"
    )


def test_a_machine_granted_class_cannot_close_a_review_item():
    """527D's sweep, H4: `shelf_can_drive_rules` answers 「can the review stop here」.

    It asked the facts' tier and the category's *presence*, so a part whose class
    a machine granted on top of signed facts moved out of `unreviewed_parts` into
    `reviewed_by_shelf` — while the rules were meanwhile answering UNKNOWN about
    that same part. Two readers, two answers, no disagreement surfaced.
    """
    from boardwise.engines.checkup import shelf_can_drive_rules

    signed_facts = {
        "supply_pins": [
            {"pin": "1", "provenance": "file:C123.txt, p.2", "verified": True},
        ],
    }
    machine_class = PartEntry(
        key="ic.acme9", lcsc="C9900000001",
        category="ic.ldo", category_trust=FACTS_TRUST_MACHINE,
        facts=signed_facts, facts_trust=FACTS_TRUST_VERIFIED,
        deviceUuid="dev-1", libraryUuid="0819f05c4eef4c71ace90d822a990e87",
    )
    assert shelf_can_drive_rules(machine_class) is False

    human = PartEntry(
        key="ic.acme8", lcsc="C9900000002", category="ic.ldo",
        facts=signed_facts, facts_trust=FACTS_TRUST_VERIFIED,
        deviceUuid="dev-2", libraryUuid="0819f05c4eef4c71ace90d822a990e87",
    )
    assert shelf_can_drive_rules(human) is True
