"""175 item 3: `rules/pcb/focground.py`'s prose and its evidence line catch up with 171.

**What 171 changed and this file does not re-decide.** `EARTH` joined
:data:`boardwise.core.model.GROUND_NET_PREFIXES`, so two claims written into
`focground.py` (171's leftover ①) stopped being true: 「a bare `EARTH` net is not
a prefix of any `is_ground_net` word」, and the classification evidence's
hard-coded sieve list, which was printed into every R1/R1b row and named seven
words where the vocabulary now carries eight.

The fixes are a rewrite of the two prose passages and one line of the evidence
generator, which now reads the vocabulary (:data:`GROUND_NET_PREFIXES`) instead of
restating it. Nothing about which net lands in which domain changes: 171 measured
that too (no fixture carries a name only the wider list knows).
"""

from __future__ import annotations

import pathlib

from boardwise.core.model import GROUND_NET_PREFIXES, is_ground_net
from boardwise.rules.pcb import focground

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "boardwise" / "rules" / "pcb" / "focground.py").read_text(
    encoding="utf-8"
)


def _evidence(power=("PGND",), logic=("GND",), unclassified=()):
    split = focground.GroundDomainSplit(
        power=tuple(power), logic=tuple(logic), unclassified=tuple(unclassified)
    )
    return "\n".join(focground._domain_evidence(split))


def test_the_sieve_word_list_in_the_evidence_is_read_from_the_vocabulary():
    """**The fix.** The row names whatever `is_ground_net` really carries.

    Before 175 that list was a string literal in `focground.py` and had gone stale
    the moment 171 grew the vocabulary: every R1/R1b row printed seven words while
    the sieve it describes knew eight.
    """
    evidence = _evidence()
    assert " / ".join(GROUND_NET_PREFIXES) in evidence
    assert "EARTH" in evidence
    assert "GND / AGND / DGND / PGND / EGND / SGND / VSS / EARTH" in evidence


def test_the_evidence_still_says_which_words_are_the_sieve_and_which_are_the_split():
    """133c's own reading of the row, kept: the sieve and the rule's two lists."""
    evidence = _evidence()
    assert "ground-domain classification" in evidence
    assert "net-name test" in evidence
    assert "core.model.is_ground_net" in evidence
    assert all(repr(word) in evidence for word in focground.GROUND_DOMAIN_POWER_PREFIXES)
    assert all(repr(word) in evidence for word in focground.GROUND_DOMAIN_LOGIC_PREFIXES)
    assert "`_`-separated tail" in evidence, (
        "145a's suffix half of the rule is part of what the sieve is"
    )


def test_the_core_sieve_really_carries_earth_since_171():
    """The premise of the rewrite, asserted rather than assumed."""
    assert "EARTH" in GROUND_NET_PREFIXES
    assert is_ground_net("EARTH") and is_ground_net("SEC_EARTH") and is_ground_net("EARTHING")
    assert focground.domain_of("EARTH") == "power"


def test_the_union_sieve_is_now_redundant_and_kept_anyway():
    """D2's fix is not reverted just because 171 took over the name it was written for.

    Measured on this tree: after 171 every word `GROUND_DOMAIN_POWER_PREFIXES`
    claims is known to the shared vocabulary too — `PGND`/`EARTH` by its prefix
    rule, `P_GND`/`POWER_GND` by its **suffix** rule (a ground word as the last
    ``_``-separated token). So either sieve alone gives today's answer and the
    union is redundant; it stays because the sieve is not what decides a domain
    (this file's word lists are) and asking the vocabulary first is how a name got
    dropped before its own rule saw it.
    """
    assert all(is_ground_net(word) for word in focground.GROUND_DOMAIN_POWER_PREFIXES)
    assert not is_ground_net("VEE"), (
        "the vocabulary is a name test, not a proof — this is only about the words"
    )
    assert "if not side and not is_ground_net(net):" in SOURCE, "the union is kept"
    assert "**171 made the union redundant, and it is kept anyway.**" in SOURCE
    assert focground.domain_of("P_GND") == "power"


def test_the_two_refuted_claims_are_gone():
    """The sentences 171 falsified, and the ones that replaced them.

    Both were *explanations* of why a name could be dropped before its rule saw
    it; both now say what is true — the vocabulary grew, the union stays because
    the two lists are not the same set in either direction.
    """
    assert "Everything :func:`boardwise.core.model.is_ground_net` recognises" not in SOURCE
    assert "not a prefix of any ``is_ground_net`` word" not in SOURCE
    assert (
        "**171 made the union redundant, and it is kept anyway.**" in SOURCE
    ), "the passage states what 171 did instead of the falsified mechanism"
    assert "Listed rather than derived" in SOURCE
