"""515C: a draw plan on a multi-board project must not die in the designator pool.

The measured defect (live Board1+Board2 project, 2026-10-17): `draw plan` exits 1
with a traceback —

    designator_pool -> model.components -> single_board()
    MultiBoardProjectError: this project has 2 boards (Board1, Board2)

`ProjectModel.components` is 040b's single-board façade and **raises** on more than
one board by design (first-board-wins is the silent loss that batch removed),
and `getattr(model, "components", None)` does not catch it because the property
raises `ValueError`, not `AttributeError`. `designator_pool` now asks the
board-aware `designators()` first, which answers for every board — and that is
also the more conservative pool: a number used anywhere in the project is
avoided, so the host cannot rename a requested designator mid-run (036b).
"""

from __future__ import annotations

from boardwise.core.model import MultiBoardProjectError
from boardwise.engines import addcomponent


class _FakeMultiBoard:
    """The shape a real ProjectModel has: board-aware `designators`, raising façade."""

    def __init__(self, names: list[str]) -> None:
        self._names = names

    def designators(self) -> list[str]:
        return sorted(self._names)

    @property
    def components(self):  # noqa: ANN201 - the façade is what must not be touched
        raise MultiBoardProjectError(
            "this project has 2 boards (Board1, Board2) — ask for a board model "
            "instead of reading the project as one"
        )


def _geometry(names: list[str]) -> dict:
    """A page carrying exactly `names` (the shape `component_origins` reads)."""
    components = []
    for index, name in enumerate(names):
        components.append({
            "state": {
                "ComponentType": "part",
                "Designator": name,
                "X": 100.0 + index * 10.0,
                "Y": 200.0 + index * 10.0,
            }
        })
    return {"components": components}


def test_a_multi_board_project_answers_with_every_board_designator():
    model = _FakeMultiBoard(["C1", "R2", "U3"])
    names = addcomponent.designator_pool(_geometry(["R9"]), model)
    assert "R9" in names, "the page's own designators stay first"
    for wanted in ("C1", "R2", "U3"):
        assert wanted in names, (
            f"every board's designator belongs to the pool (036b: the host renames "
            f"a collision mid-run when another page uses the number), missing {wanted}"
        )


def test_the_pool_does_not_duplicate_a_name_on_both_sides():
    model = _FakeMultiBoard(["R9", "C1"])
    names = addcomponent.designator_pool(_geometry(["R9"]), model)
    assert names.count("R9") == 1


def test_a_single_board_facade_still_reads_through_components():
    """The pre-040b shape (a model with `components`, no `designators`) is unchanged."""

    class _SingleBoard:
        components = {"R1": object(), "C2": object()}

    names = addcomponent.designator_pool(_geometry(["R7"]), _SingleBoard())
    assert names[0] == "R7"
    assert {"R1", "C2"} <= set(names)


def test_no_model_degrades_to_the_page_alone():
    names = addcomponent.designator_pool(_geometry(["R3", "R4"]), None)
    assert names == ["R3", "R4"]
