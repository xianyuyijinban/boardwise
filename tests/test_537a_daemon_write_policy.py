"""537A3: the daemon's design-write project whitelist.

537A2 closed the *escape hatch* — `bridge call --read-only` and the DSH plugin
refuse non-read actions before the CLI opens a socket. A plain `bridge call` or
`edit apply` still reached the daemon, and the daemon only graded `risk`: a
`write` went straight into whichever project the routed window had open. So the
last chance to say "not into *this* project" is the daemon's dispatch, and that
is where this gate lives — a choke point, not a prompt.

The policy frozen for this task:

* the catalogue gains `design_write` with a **safe default** (``True``): a new
  non-read action is a design write unless somebody deliberately says otherwise,
  so forgetting to register it cannot open the hole again. Only navigation
  (``doc.focus`` / ``doc.open``) and the connector's self-replacement
  (``sys.self_update``) are ``False`` — they change which document actions land
  on, or swap the connector, but not the project's bytes. Their ``risk`` is
  **unchanged** (``doc.focus``/``doc.open`` stay ``write``, ``self_update``
  stays ``dangerous``), so 537A2's read-only gate behaves exactly as it did;
* the daemon allows design writes only into ``test`` / ``test2`` by default.
  A real project — or a window whose identity cannot be read at all — is refused
  **after routing and before anything is forwarded**, with
  ``WRITE_PROJECT_FORBIDDEN``, the action, the actual project and the allowed
  set in the message;
* ``BOARDWISE_WRITE_PROJECTS`` (comma-separated names / uuids) lets an operator
  name the projects they mean; ``*`` is the legacy full-allow switch, and an
  **explicitly empty** value denies every project (it is not "use the default");
* an injected ``write_projects`` wins over the environment, so tests can pin a
  policy without touching the process environment — and the legacy suite pins
  ``{"*"}`` explicitly instead of relying on the production default.

Nothing here opens a socket, starts a daemon or touches an editor: a fake window
whose socket records what was sent is the whole editor, and the spy on
``_forward`` is the question "did this reach the editor at all?".
"""

from __future__ import annotations

import asyncio

import pytest
from websockets.protocol import State

from boardwise.bridge.daemon import BridgeDaemon, WindowConnection
from boardwise.bridge.protocol import ACTIONS, BridgeError, ErrorCodes, action_spec

TOKEN = "test-token-not-a-real-secret"

#: A project the daemon must never write without being told to. Synthetic on
#: purpose — no real board's name or uuid belongs in a test.
REAL_NAME = "我的真实工程"
REAL_UUID = "uuid-real-0001"

#: The three catalogue entries that are **not** design writes, and nothing else.
#: Pinned as a set so adding a fourth is a review decision, not an accident.
NOT_DESIGN_WRITES = frozenset({"doc.open", "doc.focus", "sys.self_update"})


# --------------------------------------------------------------------------
# The fake editor: one window, one socket that records what reached it
# --------------------------------------------------------------------------


class FakeSocket:
    """A connector socket that only records; nothing is ever written to a peer."""

    def __init__(self, state: State = State.OPEN) -> None:
        self.state = state
        self.sent: list = []

    async def send(self, raw) -> None:
        self.sent.append(raw)

    async def close(self) -> None:
        self.state = State.CLOSED


def _window(
    key: str = "w1",
    *,
    name: str = "",
    uuid: str = "",
    socket: FakeSocket | None = None,
) -> WindowConnection:
    return WindowConnection(
        websocket=socket or FakeSocket(),
        key=key,
        instance_id=key,
        project_name=name,
        project_uuid=uuid,
    )


def _daemon(tmp_path, monkeypatch, *, env: str | None = None, **kwargs):
    """A daemon plus the forward-spy, with the environment pinned per test.

    ``env=None`` removes ``BOARDWISE_WRITE_PROJECTS`` so the **production
    default** is what runs; every other value sets it verbatim (``""`` included,
    which is a policy, not an absent variable). ``kwargs`` go to the
    constructor, which is how an injected ``write_projects`` is exercised.
    """
    if env is None:
        monkeypatch.delenv("BOARDWISE_WRITE_PROJECTS", raising=False)
    else:
        monkeypatch.setenv("BOARDWISE_WRITE_PROJECTS", env)

    daemon = BridgeDaemon(token=TOKEN, home=tmp_path, **kwargs)

    forwarded: list[tuple[str, dict, str]] = []

    async def fake_forward(action, params, role, window):
        forwarded.append((action, dict(params), window.key))
        return {"spy": action}

    monkeypatch.setattr(daemon, "_forward", fake_forward)
    return daemon, forwarded


def _attach(daemon: BridgeDaemon, window: WindowConnection) -> WindowConnection:
    daemon.windows[window.key] = window
    return window


def _call(daemon: BridgeDaemon, action: str, *, params=None, routed=None,
          target_project: str = ""):
    return asyncio.run(daemon.handle_request(
        action, params or {}, "cli", target_project, routed,
    ))


def _refusal(daemon: BridgeDaemon, action: str, **kwargs) -> BridgeError:
    with pytest.raises(BridgeError) as raised:
        _call(daemon, action, **kwargs)
    return raised.value


# --------------------------------------------------------------------------
# 1. The default policy: test / test2, and nothing else
# --------------------------------------------------------------------------


def test_the_production_default_is_test_and_test2(tmp_path, monkeypatch):
    """No environment, no injection: exactly the two scratch projects."""
    daemon, _forwarded = _daemon(tmp_path, monkeypatch)

    assert daemon.write_projects == frozenset({"test", "test2"})


def test_a_write_into_a_real_project_is_refused_before_it_is_forwarded(
    tmp_path, monkeypatch
):
    """The hole this task closes, at the choke point.

    Four facts travel with the refusal: the action, the project actually
    selected, the allowed set, and that the editor never saw the call. The
    out-parameter stays **unmarked** too: a caller that later writes an audit
    line must not be told this request was routed to a window when nothing was
    sent to it.
    """
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    window = _attach(daemon, _window(name=REAL_NAME, uuid=REAL_UUID))
    routed: dict = {}

    error = _refusal(
        daemon, "sch.place_component", params={"designator": "R1"}, routed=routed
    )

    assert error.code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert "sch.place_component" in error.message
    assert REAL_NAME in error.message or REAL_UUID in error.message
    assert "test" in error.message and "test2" in error.message
    assert "allowed" in error.message
    assert "Nothing was forwarded" in error.message
    # The spy is the proof: not a message claim.
    assert forwarded == []
    assert window.websocket.sent == []
    assert routed == {}, "a refused call must not be marked as routed"
    assert error.detail["action"] == "sch.place_component"
    assert error.detail["allowed"]


def test_a_window_whose_project_cannot_be_read_is_refused(tmp_path, monkeypatch):
    """Unknown identity is not a licence: it is exactly what must be refused.

    A window that named no project (an old connector, or a read that failed)
    would otherwise be the cheapest way to write into a real board by simply not
    saying which one it is.
    """
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    window = _attach(daemon, _window(name="", uuid=""))
    routed: dict = {}

    error = _refusal(daemon, "sch.doc.save", routed=routed)

    assert error.code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert "unknown" in error.message.lower() or "unnamed" in error.message.lower()
    assert "Nothing was forwarded" in error.message
    assert forwarded == []
    assert window.websocket.sent == []
    assert routed == {}


@pytest.mark.parametrize("name", ["test", "/test", "TEST", "Test2", "test2", "/test2"])
def test_writes_into_test_and_test2_are_allowed(tmp_path, monkeypatch, name):
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    _attach(daemon, _window(name=name, uuid=f"uuid-{name.strip('/').lower()}"))

    result = _call(daemon, "sch.place_component", params={"designator": "R1"})

    assert result == {"spy": "sch.place_component"}
    assert [entry[0] for entry in forwarded] == ["sch.place_component"]


# --------------------------------------------------------------------------
# 2. What the gate must NOT touch: reads, navigation, self-update
# --------------------------------------------------------------------------


def test_a_read_on_a_real_project_is_untouched(tmp_path, monkeypatch):
    """Reads were never the problem, and a read-only review must keep working."""
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    _attach(daemon, _window(name=REAL_NAME, uuid=REAL_UUID))

    assert _call(daemon, "doc.list") == {"spy": "doc.list"}
    assert forwarded == [("doc.list", {}, "w1")]


@pytest.mark.parametrize("action", ["doc.focus", "doc.open"])
def test_navigation_is_not_a_design_write(tmp_path, monkeypatch, action):
    """Navigation moves what the next call lands on; it writes no project byte.

    Their ``risk`` stays ``write`` (537A2's read-only gate must keep refusing
    them), which is exactly why the daemon cannot use ``risk`` alone here.
    """
    spec = action_spec(action)
    assert spec is not None and spec.risk == "write" and spec.design_write is False

    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    _attach(daemon, _window(name=REAL_NAME, uuid=REAL_UUID))
    routed: dict = {}

    result = _call(daemon, action, params={"uuid": "page-1"}, routed=routed)

    assert result == {"spy": action}
    assert forwarded == [(action, {"uuid": "page-1"}, "w1")]
    assert routed == {"windowKey": "w1"}


def test_self_update_still_answers_with_the_confirmation_gate(tmp_path, monkeypatch):
    """The dangerous tier's own choke point runs first, and stays the answer.

    A caller that forgot ``confirm`` must learn *that*, not "wrong project" —
    and confirming must not be blocked by a project policy, because replacing
    the connector is not a design write.
    """
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    _attach(daemon, _window(name=REAL_NAME, uuid=REAL_UUID))

    error = _refusal(daemon, "sys.self_update", params={"bundleB64": "AA=="})
    assert error.code == ErrorCodes.CONFIRMATION_REQUIRED
    assert forwarded == []

    _call(daemon, "sys.self_update", params={"bundleB64": "AA==", "confirm": True})
    assert [entry[0] for entry in forwarded] == ["sys.self_update"]


def test_overwriting_a_documents_source_is_still_a_design_write(tmp_path, monkeypatch):
    """`sys.set_document_source` overwrites the project's own text.

    It is `dangerous` (so confirmation is demanded first) **and** a design
    write: the two gates compose, and a confirmed call into a real project is
    still refused here.
    """
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    _attach(daemon, _window(name=REAL_NAME, uuid=REAL_UUID))

    error = _refusal(
        daemon, "sys.set_document_source",
        params={"source": "x", "uuid": "doc-1", "confirm": True},
    )

    assert error.code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert forwarded == []


# --------------------------------------------------------------------------
# 3. The operator's override, and the difference between "empty" and "absent"
# --------------------------------------------------------------------------


def test_an_explicitly_empty_environment_denies_every_project(tmp_path, monkeypatch):
    """``""`` is a policy ("write nowhere"), not a missing value.

    Treating it as absent would silently restore the default — the one reading
    that turns an operator's "nothing" into "test and test2", which is the
    direction that writes when the operator said not to.
    """
    daemon, forwarded = _daemon(tmp_path, monkeypatch, env="")
    _attach(daemon, _window(name="test", uuid="uuid-test"))

    assert daemon.write_projects == frozenset()
    error = _refusal(daemon, "sch.place_wire", params={"points": [[0, 0], [1, 0]]})
    assert error.code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert "Nothing was forwarded" in error.message
    assert forwarded == []


def test_an_injected_empty_set_also_denies_everything(tmp_path, monkeypatch):
    daemon, forwarded = _daemon(tmp_path, monkeypatch, write_projects=set())
    _attach(daemon, _window(name="test", uuid="uuid-test"))

    assert daemon.write_projects == frozenset()
    assert _refusal(daemon, "sch.doc.save").code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert forwarded == []


def test_the_environment_can_allow_named_projects(tmp_path, monkeypatch):
    """Comma-separated names / uuids; the comparison folds case and `/`."""
    daemon, forwarded = _daemon(tmp_path, monkeypatch, env="alpha, /Beta ,uuid-gamma")
    assert daemon.write_projects == frozenset({"alpha", "beta", "uuid-gamma"})

    _attach(daemon, _window(name="/Alpha", uuid="uuid-alpha"))
    _call(daemon, "sch.doc.save")
    assert forwarded == [("sch.doc.save", {}, "w1")]


def test_an_allowed_uuid_lets_a_differently_named_project_through(tmp_path, monkeypatch):
    """The uuid is a name too: an operator who knows the uuid should not have
    to know the friendly name."""
    daemon, _forwarded = _daemon(tmp_path, monkeypatch, write_projects={"uuid-my-board"})
    _attach(daemon, _window(name="whatever-the-editor-calls-it", uuid="uuid-my-board"))

    assert _call(daemon, "sch.doc.save") == {"spy": "sch.doc.save"}


def test_an_operator_allowlist_does_not_keep_test_enabled(tmp_path, monkeypatch):
    """The override replaces the default rather than widening it."""
    daemon, forwarded = _daemon(tmp_path, monkeypatch, env="alpha")
    _attach(daemon, _window(name="test", uuid="uuid-test"))

    assert _refusal(daemon, "sch.doc.save").code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert forwarded == []


@pytest.mark.parametrize(
    ("name", "uuid"),
    ((REAL_NAME, REAL_UUID), ("test", "uuid-test"), ("", "")),
)
def test_the_star_is_the_legacy_full_allow_switch(tmp_path, monkeypatch, name, uuid):
    """``*`` is for old callers/tests: every project, including unknown ones."""
    daemon, forwarded = _daemon(tmp_path, monkeypatch, env="*")
    assert "*" in daemon.write_projects

    window = _attach(daemon, _window(name=name, uuid=uuid))
    routed: dict = {}
    _call(daemon, "sch.place_component", routed=routed)

    assert forwarded == [("sch.place_component", {}, window.key)]
    assert routed == {"windowKey": window.key}


def test_an_injected_policy_wins_over_the_environment(tmp_path, monkeypatch):
    """Testing isolation: the constructor argument is the final word."""
    daemon, forwarded = _daemon(
        tmp_path, monkeypatch, env="alpha", write_projects={"test"}
    )
    assert daemon.write_projects == frozenset({"test"})

    _attach(daemon, _window(name="test", uuid="uuid-test"))
    _call(daemon, "sch.doc.save")
    assert forwarded == [("sch.doc.save", {}, "w1")]

    forwarded.clear()
    _attach(daemon, _window(key="w2", name="alpha", uuid="uuid-alpha"))
    assert _refusal(
        daemon, "sch.doc.save", target_project="alpha",
    ).code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert forwarded == []


# --------------------------------------------------------------------------
# 4. The catalogue half: default-safe classification, pinned exceptions
# --------------------------------------------------------------------------


def test_only_navigation_and_self_update_are_not_design_writes():
    """The exceptions are a reviewed list, not whatever was convenient."""
    actual = {action.name for action in ACTIONS if not action.design_write}
    assert actual == set(NOT_DESIGN_WRITES), (
        "the non-design-write set drifted from the reviewed one: "
        f"unexpected {sorted(actual - NOT_DESIGN_WRITES)}, "
        f"missing {sorted(NOT_DESIGN_WRITES - actual)}"
    )


def test_every_other_action_is_a_design_write_including_new_ones():
    """A forgotten registration must fail **closed**.

    `design_write` defaults to `True`, so this asserts two things at once: the
    field exists on every entry, and nothing but the pinned trio opted out.
    """
    for action in ACTIONS:
        assert isinstance(action.design_write, bool), action.name
        if action.name not in NOT_DESIGN_WRITES:
            assert action.design_write is True, (
                f"{action.name} is not a design write — pin the exception in "
                "this test before changing the catalogue"
            )


@pytest.mark.parametrize(
    "action",
    [
        "sch.place_component",
        "sch.place_wire",
        "sch.delete_primitives",
        "sch.set_component_attribute",
        "sch.doc.new",
        "pcb.doc.new",
        "doc.delete_page",
        "sch.doc.save",
        "sys.set_document_source",
    ],
)
def test_the_write_surface_is_classified_as_design_writes(action):
    spec = action_spec(action)
    assert spec is not None
    assert spec.design_write is True


def test_the_risk_field_is_unchanged_by_this_task():
    """537A2 keys the CLI's read-only gate on `risk`; this task must not move it.

    In particular navigation stays `write` (and therefore stays refused by
    `--read-only`), while `self_update` stays in the dangerous tier.
    """
    assert action_spec("doc.focus").risk == "write"
    assert action_spec("doc.open").risk == "write"
    assert action_spec("sys.self_update").risk == "dangerous"


# --------------------------------------------------------------------------
# 5. The old catalogue rules still answer first
# --------------------------------------------------------------------------


def test_an_unknown_action_is_still_unknown_action(tmp_path, monkeypatch):
    """The policy must not become the answer to a name that does not exist."""
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    _attach(daemon, _window(name=REAL_NAME, uuid=REAL_UUID))

    error = _refusal(daemon, "board.explode")

    assert error.code == ErrorCodes.UNKNOWN_ACTION
    assert error.code != ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert forwarded == []


def test_a_create_action_still_asks_for_confirmation_first(tmp_path, monkeypatch):
    """Same order as `self_update`: the confirmation gate, then the project."""
    daemon, forwarded = _daemon(tmp_path, monkeypatch)
    _attach(daemon, _window(name=REAL_NAME, uuid=REAL_UUID))

    error = _refusal(daemon, "sch.doc.new", params={"name": "scratch"})
    assert error.code == ErrorCodes.CONFIRMATION_REQUIRED
    assert forwarded == []

    error = _refusal(daemon, "sch.doc.new", params={"name": "scratch", "confirm": True})
    assert error.code == ErrorCodes.WRITE_PROJECT_FORBIDDEN
    assert forwarded == []
