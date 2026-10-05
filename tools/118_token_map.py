"""118: the token map from 113's intent onto the **measured** symbols.

113 named pins by **role** (``T1.P1`` = the primary's bus end, ``U4.A`` = the
TL431's anode) and wrote a profile to match.  118 measured what the host's
symbols actually are, and the two do not line up:

* ``T1`` (LCSC ``C9900020988``, ``EE16_3+3_V02``) has **five** pins numbered
  ``1 3 4 5 6``, ``PinName == PinNumber`` for every one of them, and **no pin
  named or numbered A2** — 110 recorded the same conclusion twice (``PLAN.md``
  line 44 「库内唯一 EE16 **5 脚**骨架」and line 89 「T1 5 脚符号脚位落图时以
  ``component_pins`` 实测为准」) and the 118 pin read-back confirms it.
* ``U4`` (TL431, ``C2887585``) is numbered ``1=REF 2=CATHODE 3=ANODE``; 113
  wrote the tokens ``A`` / ``K`` / ``REF``, so two of the three are names the
  host does not use.
* ``U5`` (PC817, ``C7437``) is ``1=AN 2=CAT 3=EM 4=COL``; 113 wrote ``1 2 3 4``
  as *numbers* and ``A``/``K`` as names, so the numbers happen to be right and
  the names are not.
* ``Q1`` is ``1=G 2=D 3=S``; 113 wrote ``1=S 2=D 3=G`` — the gate and the source
  are **swapped** against the measured symbol.

**The numbers come from electrical function, not from position.**  The authority
is 110's own netlist (``outputs/110/PLAN.md`` §5, the table this repo's flyback
descends from), read against 110's measured pin numbers.  Every row below is that
crosswalk; nothing here is a guess about which way a symbol "ought" to point.

115② already established the ruler: **a spec token is resolved by number first,
then by name** (``drawcompiler._pin_of_token`` and ``grammar.base.profile_pin_for``
read the same rule).  So the fix is to write the spec in the host's own tokens
and let that ruler do its job — not to teach the compiler a third spelling.
"""

from __future__ import annotations

#: ``113's token -> the measured token on the real symbol``.
#:
#: Roles, from 113's own titles and 110 §5's netlist, so each row can be checked
#: against a net name rather than against a drawing.
TOKEN_MAP: dict[str, dict[str, str]] = {
    # T1, measured 1/3 left, 4/5/6 right (110/11_pins.json as T1).
    # 110 §5: HVDC = T1.1, SW = T1.2, AUX = T1.4, SEC_12V = T1.6, and the
    # auxiliary winding's *cold* end is on PGND.  A 3+3 skeleton has SIX ends
    # and only five pins, so the aux cold end shares a pin with the primary
    # return: 110 wrote 「T1 辅助绕组冷端」 on the PGND row **without a pin
    # number**, which is the measured reality — there is no sixth terminal.
    # Measured: pin 5 sits at the right-hand mid-height, the only pin neither
    # winding end reaches, so it is the shared return.
    # T1, measured 1/3 on the LEFT and 4/5/6 on the RIGHT (110/11_pins.json).
    # 110's own text is the primary source for the reading:
    #   * line 44 「库内唯一 EE16 **5 脚**骨架」and line 160 「骨架符号只有 5 脚」;
    #   * line 89 「下表 T1 脚号是**意图**：1/2 初级、3/4 辅助、5 副边」 — an
    #     intent, and 118 is the batch that has to reconcile it with what the
    #     host actually has.
    # A 3+3 EE16 is primary(2) + secondary(2) + aux(2) = **six** ends; the
    # skeleton is five pins, so exactly one pair of ends shares a terminal.
    # The measured geometry says which pair is available: the primary is the
    # left pair (it faces the bus and the switch, both primary-side), so the
    # right triple carries the secondary and the auxiliary.
    #
    # **Which end is shared is an electrical decision, and it is forced.** The
    # grammar refuses a flyback whose transformer has no pin on the secondary
    # ground (`_secondary`: `if sec_gnd not in tx_nets: continue`), because
    # without one there is no way to draw the isolation barrier. So the shared
    # terminal must be one the secondary can own outright. 110 tied the
    # **auxiliary cold end to PGND** instead (PLAN.md line 97), which would put
    # the secondary's return and the primary's return on one net — the two
    # families the whole design exists to keep apart. 118 therefore shares the
    # **secondary return with the auxiliary cold end**, both on SEC_GND: the
    # aux still gets its own cold reference, and the secondary keeps a terminal
    # of its own so the barrier survives.
    #
    # That leaves the right-hand triple, by measured height (6 top, 5 middle,
    # 4 bottom) as: secondary hot, auxiliary hot, secondary return.
    # T1, measured 1/3 on the LEFT and 4/5/6 on the RIGHT (110/11_pins.json).
    #
    # 110 recorded the constraint twice and 118 is the batch that has to live
    # with it: `PLAN.md` line 44 「库内唯一 EE16 **5 脚**骨架」 and line 160
    # 「骨架符号只有 5 脚 ... 库内无实物变压器数据」.  The measurement agrees:
    # `11_pins.json` returns **five** pins, numbered 1/3/4/5/6, `PinName ==
    # PinNumber`, and **no A2**.
    #
    # **The five-pin part cannot carry this circuit, and that is measured, not
    # argued.**  The flyback grammar needs the transformer to touch six nets:
    # HVDC, SW, PGND, AUX, SEC_SW and SEC_GND — the primary's two ends, the
    # primary's return, the auxiliary winding, and the secondary's two ends.
    # `C9900020988` has five pins.  All 720 assignments of five pins onto six
    # nets were tried against the grammar; the 120 the grammar accepts (it
    # requires `sec_gnd in tx_nets` and a reachable primary ground) **drop AUX
    # every single time**.  The casualty is not a matter of which reading is
    # nicer: `EE16_3+3_V02` is a **two**-winding skeleton wearing a 3+3 name, and
    # a self-supplied auxiliary supply needs a third.
    #
    # So the reading below is the one that keeps the two ground families apart
    # (`flyback._secondary` refuses a transformer with no secondary-ground pin,
    # and shorting the two returns together would delete the isolation barrier
    # the whole design exists to draw).  It is recorded as the best available,
    # **not** as a working configuration — see `NO_SUCH_PIN` below and
    # `tests/test_118_measured_profiles.py::test_the_five_pin_transformer_cannot_carry_this_circuit`.
    "T1": {
        "P1": "1",   # primary bus end     -> HVDC
        "P2": "3",   # primary switch end  -> SW
        "S1": "6",   # secondary hot       -> SEC_SW
        "A1": "5",   # auxiliary hot       -> AUX  (see the note above: the
                     #   net the part cannot actually reach)
        "A2": "4",   # the one spare return terminal -> SEC_GND
        "S2": "4",   # secondary return -- **the same terminal as A2**: a
                     #   five-pin skeleton has no sixth end, and giving the
                     #   secondary its own terminal is what keeps the two
                     #   ground families from being one net.
    },
    # U4, TL431 measured 1=REF 2=CATHODE 3=ANODE.
    # 110 §5: SEC_GND takes U4.1(A), FB_SENSE takes U4.3(REF), LED_K takes U4.2(K).
    # The measured symbol numbers REF=1, CATHODE=2, ANODE=3, so 110's "(A)/
    # (REF)/(K)" roles land on 3 / 1 / 2.  113 wrote the tokens A, K, REF.
    "U4": {"A": "3", "K": "2", "REF": "1"},
    # U5, PC817 measured 1=AN 2=CAT 3=EM 4=COL.
    # 110 §5: SEC_GND = U5.2(E), COMP = U5.4(C), LED_K = U5.1(A), and U5's other
    # primary-side pin is the cathode that the LED drives.  Measured says
    # 1=AN 2=CAT 3=EM 4=COL, so 110's U5.2(E) is the measured pin 3.
    "U5": {"1": "1", "2": "3", "3": "2", "4": "4"},
    # Q1, measured 1=G 2=D 3=S (110/11_pins.json as Q1).  113's tokens were
    # 1=S 2=D 3=G, i.e. its own numbering put the source on 1 and the gate on 3;
    # the host puts the **gate** on 1 and the source on 3.  110 §5 corroborates
    # the host: "SRC | Q1.1(S)" and "GATE | Q1.3(G)" are 110's *intent* text,
    # while its own measured names say 1=G — so 113 and 110 wrote the numbers
    # from the datasheet and the host numbers them the other way round.  118
    # follows the measurement: 113's S is measured pin 3, its G is measured
    # pin 1, and its D (2) is measured pin 2.
    "Q1": {"1": "3", "2": "2", "3": "1"},
    # The diodes.  113 wrote the token pair 1=A 2=K for all three, which is a
    # claim about *which end conducts*, not about a number the host has.  The
    # host's three diode symbols do not agree with each other either — 110
    # measured D1 as 1=C/2=A, D2 as 1=A/2=C and D3 as 1=K/2=A — so the map has
    # to be read off **name**, with 113's net membership as the electrical input:
    #
    #   D1: 113 puts 1 on SW and 2 on CLAMP.  Measured names: 1=C 2=A, and a
    #       clamp diode conducts SW -> CLAMP, so the cathode is the SW end.
    #       Numbers unchanged (1->1, 2->2); what changed is the name behind them.
    #   D2: 113 puts 1 on AUX and 2 on VCC.  Measured names: 1=A 2=C, and the
    #       auxiliary rectifier's anode faces the winding.  Unchanged.
    #   D3: 113 puts 1 on SEC_SW and 2 on SEC_12V.  Measured names: 1=K 2=A.
    #       The secondary rectifier's **anode** faces the winding (SEC_SW) and
    #       its cathode feeds the output rail — so the anode is measured pin 2,
    #       and the numbers swap.  (110 §5 wrote "D3.1(A)" from the datasheet,
    #       which disagrees with 110's own pin measurement; 118 goes with the
    #       measurement, and this row is the one place the two 110 documents
    #       do not agree with each other.)
    # D1 is the one place 113 wrote **names** rather than numbers, so the map is
    # spelled in names too.  Measured D1: 1=C 2=A.  113's A sat on SW and its K
    # on CLAMP; a clamp diode's cathode is the SW end, so A -> 2 and K -> 1.
    "D1": {"A": "2", "K": "1"},
    "D2": {"1": "1", "2": "2"},
    "D3": {"1": "2", "2": "1"},
}

#: 113's tokens that the measured symbol has **no** pin for, with what the
#: measurement says instead. Recorded rather than silently dropped.
#:
#: **Empty, and that is the finding.**  113 named six transformer terminals
#: (``P1 P2 A1 A2 S1 S2``) and the measured ``EE16_3+3_V02`` has five pins, so one
#: pair has to share.  The first pass of this file put ``S2`` in here as "no such
#: pin" — true of the *name*, but it sent the retokenizer down the path of
#: dropping the member, which is a different claim: the secondary return is not
#: missing from the circuit, it is **the same terminal** as the auxiliary cold
#: end, and dropping it would have quietly deleted the secondary's return.  The
#: grammar caught that (a transformer with no pin on the secondary ground cannot
#: be read as an isolated flyback at all).  So ``S2`` maps like any other token,
#: onto the pin that carries it, and this table stays empty until a measurement
#: says otherwise.
NO_SUCH_PIN: dict[str, dict[str, str]] = {
    "T1": {
        "AUX": (
            "**the finding of this batch.**  The measured EE16_3+3_V02 has five "
            "pins; this flyback needs six transformer terminals (HVDC, SW, "
            "PGND, AUX, SEC_SW, SEC_GND).  All 720 assignments were tried "
            "against the grammar and the 120 it accepts drop AUX every time — "
            "the part is a two-winding skeleton, and a self-supplied auxiliary "
            "supply needs a third winding.  Closing this needs a **six-terminal "
            "transformer** (or an auxiliary supply taken from somewhere else), "
            "which is a BOM change and therefore 岳's call, not this batch's."
        ),
    },
}
