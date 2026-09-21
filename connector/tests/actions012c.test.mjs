/**
 * Contract tests for the 012v2 third batch: `review.mark` (§八).
 *
 * Same boundary as every other action test — the *production* dispatch path
 * against a fake host, so the wire contract and the failure shapes are pinned
 * where the daemon sees them. The host here carries the page (`getAll`), the
 * marker API and the focus readings, and nothing else.
 *
 * The two claims this file exists to keep honest:
 *
 * 1. **A mark is a rectangle at the component's coordinates**, drawn in *one*
 *    call, with the field names a rectangle takes (`left/right/top/bottom` —
 *    a line's `startX/endX` is accepted silently by the host and renders
 *    nothing; that bug shipped once).
 * 2. **Nothing about the finding list is lost when the drawing fails.** The
 *    marker API missing, refusing, or being switched off degrades to
 *    `mode: 'list'` with the coordinates still in the answer, and a ref that is
 *    not on the page is reported per mark — the rest are still drawn.
 *
 * The real-host questions (does `generateIndicatorMarkers` accept these shapes
 * on 3.2.186, do the markers actually render, do canvas units mean what the API
 * remarks say) are *machine* questions and are parked in the task book.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

const SCH_PAGE = 'page-1';

/**
 * What a host method returns for one option.
 *
 * Keyed by presence, not by `undefined`: an option the test *did* name but set
 * to `undefined` means "this call returns nothing", while an absent option means
 * "use the default". A function option is called, which is how a test plants a
 * throw.
 */
async function pick(options, key, fallback) {
  if (!(key in options)) return fallback;
  const value = options[key];
  return typeof value === 'function' ? await value() : value;
}

/** The plumbing every action handler needs to be reachable at all. */
function baseHost() {
  const host = {
    sys_WebSocket: {
      register(_id, _uri, onMessage) {
        host.__onMessage = onMessage;
      },
      send(_id, data) {
        host.__sent = host.__sent ?? [];
        host.__sent.push(JSON.parse(data));
      },
      close() {},
    },
    sys_Log: { add() {} },
    sys_Message: { showToastMessage() {} },
    sys_Environment: { getEditorCurrentVersion: () => '3.2.186' },
    sys_Storage: {
      getExtensionUserConfig: () => undefined,
      setExtensionUserConfig: async () => true,
    },
    sys_Dialog: { showInformationMessage() {} },
    dmt_Schematic: {
      async getCurrentSchematicPageInfo() {
        return { uuid: SCH_PAGE };
      },
    },
    // The focus reading `activeDocument` prefers. `documentType: 1` is
    // SCHEMATIC_PAGE; the PCB case is planted by a test that changes it.
    dmt_SelectControl: {
      async getCurrentDocumentInfo() {
        return { uuid: SCH_PAGE, documentType: 1, tabId: 'tab-1' };
      },
    },
  };
  return host;
}

/** A placed component as `sch_PrimitiveComponent.getAll()` hands it back. */
function component({ designator, primitiveId = `p-${designator}`, x = 0, y = 0 }) {
  return {
    getState_PrimitiveId: () => primitiveId,
    getState_Designator: () => designator,
    getState_X: () => x,
    getState_Y: () => y,
  };
}

/**
 * A host with the page, the marker API and the focus readings.
 *
 * Every marker / zoom / remove call is recorded **with its arguments**: the
 * rectangle's field names and the zoom box's four coordinates are the whole
 * contract here, and a test that only counted the calls would pass with a box
 * drawn in the wrong shape.
 */
function hostReviewMark(options = {}) {
  const markers = [];
  const zooms = [];
  let removed = 0;
  // Mutated rather than spread: the plumbing's `register` closure hands the
  // message callback to the object it was built on, so a copy would leave the
  // transport writing to an object nothing else can see.
  const host = baseHost();
  host.sch_PrimitiveComponent = {
    async getAll() {
      return pick(options, 'components', []);
    },
    // A recording write API: `review.mark` draws an overlay and touches no
    // primitive, and the way to prove it is that this is never reached.
    async modify(...args) {
      host.__writes = host.__writes ?? [];
      host.__writes.push(args);
      return {};
    },
  };
  host.dmt_EditorControl = {
    async generateIndicatorMarkers(...args) {
      markers.push(args);
      return pick(options, 'generate', true);
    },
    async zoomToRegion(...args) {
      zooms.push(args);
      return pick(options, 'zoom', true);
    },
    async removeIndicatorMarkers() {
      removed += 1;
      return pick(options, 'remove', true);
    },
  };
  host.__markers = markers;
  host.__zooms = zooms;
  host.__removed = () => removed;
  for (const name of options.without ?? []) {
    if (name.includes('.')) {
      const [ns, member] = name.split('.');
      delete host[ns][member];
    } else {
      delete host[name];
    }
  }
  return host;
}

function withEda(t, host) {
  connector.__setFacadeForTests(createFacade(host));
  t.after(() => {
    connector.deactivate();
    connector.__setFacadeForTests(undefined);
  });
}

async function waitFor(predicate, timeoutMs = 2000) {
  const deadline = Date.now() + timeoutMs;
  while (!predicate()) {
    if (Date.now() > deadline) return false;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  return true;
}

async function call(host, action, params = {}) {
  const id = `req-${Math.random().toString(36).slice(2, 8)}`;
  void host.__onMessage({ data: JSON.stringify({ id, action, params }) });
  assert.ok(
    await waitFor(() => (host.__sent ?? []).some((f) => f.id === id)),
    `no response frame for ${action}`,
  );
  return (host.__sent ?? []).find((f) => f.id === id);
}

const MARK = { ref: 'C116', ruleId: 'decoupling-per-ic', severity: 'WARN', text: 'U1 缺少去耦电容' };

// --------------------------------------------------------------------------
// §八 review.mark — the drawing
// --------------------------------------------------------------------------

test('review.mark draws one rectangle per resolved ref, in a single call', async (t) => {
  const host = hostReviewMark({
    components: [
      component({ designator: 'C116', primitiveId: 'c-116', x: 100, y: 200 }),
      component({ designator: 'U1', primitiveId: 'u-1', x: -30, y: 40 }),
    ],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', {
    marks: [MARK, { ref: 'U1', ruleId: 'decoupling-per-ic', severity: 'ERROR', text: 'U1 无去耦' }],
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));

  // One call for the whole pass: the colour and the line width belong to the
  // call, so splitting it would be a decision, not an optimisation.
  assert.equal(host.__markers.length, 1);
  const [boxes, color, lineWidth, zoom] = host.__markers[0];
  // Rectangle field names, in canvas units, centred on the component.
  assert.deepEqual(boxes, [
    { type: 'rectangle', left: 40, right: 160, top: 260, bottom: 140 },
    { type: 'rectangle', left: -90, right: 30, top: 100, bottom: -20 },
  ]);
  assert.deepEqual(color, { r: 255, g: 0, b: 0, alpha: 255 });
  assert.equal(lineWidth, 2);
  assert.equal(zoom, false, 'the caller did not ask for a zoom');

  assert.equal(frame.data.mode, 'markers');
  assert.equal(frame.data.markers.attempted, 2);
  assert.equal(frame.data.markers.accepted, 2);
  assert.deepEqual(
    frame.data.marked.map((m) => [m.marker, m.position, m.ref, m.severity, m.x, m.y, m.primitiveId]),
    [
      [1, 1, 'C116', 'WARN', 100, 200, 'c-116'],
      [2, 2, 'U1', 'ERROR', -30, 40, 'u-1'],
    ],
  );
  // The task's mark content — rule id, severity, one line — is carried in the
  // answer, because the marker API cannot draw text.
  assert.equal(frame.data.marked[0].ruleId, 'decoupling-per-ic');
  assert.equal(frame.data.marked[0].text, 'U1 缺少去耦电容');
  assert.equal(frame.data.readOnly, true);
  assert.equal(host.__writes, undefined, 'nothing may be modified');
});

test('review.mark resolves a ref to the page spelling, case-insensitively', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'R5', x: 1, y: 2 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [{ ref: ' r5 ' }] });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.marked.length, 1);
  assert.equal(frame.data.marked[0].designator, 'R5', 'the page\'s spelling is reported back');
  assert.equal(frame.data.marked[0].ref, 'r5', 'and the caller\'s own text is kept verbatim');
});

test('a ref that is not on the page is reported, and the others are still drawn', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 10, y: 20 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', {
    marks: [MARK, { ref: 'U9', ruleId: 'decoupling-per-ic', severity: 'WARN', text: 'U9 缺电容' }],
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.mode, 'markers');
  assert.equal(frame.data.marked.length, 1);
  assert.equal(host.__markers[0][0].length, 1, 'only the resolved mark was drawn');
  assert.equal(frame.data.unresolved.length, 1);
  assert.equal(frame.data.unresolved[0].ref, 'U9');
  assert.equal(frame.data.unresolved[0].position, 2);
  assert.match(frame.data.unresolved[0].reason, /no component with this designator/);
});

test('a mark with no ref is reported instead of being pointed at something', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 10, y: 20 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', {
    marks: [{ ruleId: 'value-mpn-match', severity: 'INFO', text: '无法定位的发现' }, MARK],
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.count, 2);
  assert.equal(frame.data.marked.length, 1);
  assert.equal(frame.data.marked[0].position, 2, 'positions are the caller\'s order, not a renumbering');
  assert.equal(frame.data.marked[0].marker, 1, 'and the drawn order is its own field');
  assert.match(frame.data.unresolved[0].reason, /names no ref/);
});

test('a component without a numeric position is counted, not silently dropped', async (t) => {
  const host = hostReviewMark({
    components: [
      component({ designator: 'C116', x: 10, y: 20 }),
      { getState_PrimitiveId: () => 'sheet-1', getState_ComponentType: () => 'sheet' },
      component({ designator: 'U1', x: 'east', y: 3 }),
    ],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK] });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.page.components, 3);
  assert.equal(frame.data.page.designators, 1);
  assert.equal(frame.data.page.withoutPosition, 2);
  assert.ok(
    frame.data.notes.some((note) => /no designator or no numeric position/.test(note)),
    JSON.stringify(frame.data.notes),
  );
});

// --------------------------------------------------------------------------
// §八 review.mark — the degradations (task book: markers unusable ⇒ jump list)
// --------------------------------------------------------------------------

test('markers: false yields the jump list and draws nothing', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 10, y: 20 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], markers: false });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.mode, 'list');
  assert.equal(host.__markers.length, 0, 'nothing may be drawn when the caller asked for the list');
  assert.match(frame.data.markers.reason, /markers: false/);
  // The coordinates — the whole point of the fallback — are still there.
  assert.deepEqual(
    frame.data.marked.map((m) => [m.ref, m.x, m.y]),
    [['C116', 10, 20]],
  );
});

test('a host without generateIndicatorMarkers degrades to the jump list', async (t) => {
  const host = hostReviewMark({
    components: [component({ designator: 'C116', x: 10, y: 20 })],
    without: ['dmt_EditorControl.generateIndicatorMarkers'],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK] });
  assert.equal(frame.ok, true, 'a missing marker API must not cost the caller the coordinates');
  assert.equal(frame.data.mode, 'list');
  assert.match(frame.data.markers.reason, /generateIndicatorMarkers\(\) is not available/);
  assert.equal(frame.data.marked.length, 1);
});

test('a canvas that refuses the markers degrades to the jump list', async (t) => {
  const host = hostReviewMark({
    components: [component({ designator: 'C116', x: 10, y: 20 })],
    generate: false,
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK] });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.mode, 'list');
  assert.equal(frame.data.markers.attempted, 1);
  assert.equal(frame.data.markers.accepted, 0);
  assert.match(frame.data.markers.reason, /refused the markers/);
});

test('a page with nothing resolvable says so, and calls no marker API', async (t) => {
  const host = hostReviewMark({ components: [] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK] });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.mode, 'markers');
  assert.equal(host.__markers.length, 0);
  assert.equal(frame.data.markers.attempted, 0);
  assert.match(frame.data.markers.reason, /nothing to draw/);
});

// --------------------------------------------------------------------------
// §八 review.mark — the refusals (structural, and thrown)
// --------------------------------------------------------------------------

test('review.mark refuses a pageUuid that is not the focused page', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116' })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], pageUuid: 'page-other' });
  assert.equal(frame.ok, false, JSON.stringify(frame));
  assert.equal(frame.error.code, 'PAGE_MISMATCH');
  assert.equal(host.__markers.length, 0, 'the guard fires before anything is drawn');
});

test('review.mark passes the guard when the pageUuid matches', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 0, y: 0 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], pageUuid: SCH_PAGE });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(host.__markers.length, 1);
});

test('review.mark refuses a focused document that is not a schematic page', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116' })] });
  host.dmt_SelectControl.getCurrentDocumentInfo = async () => ({ uuid: 'pcb-1', documentType: 3 });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK] });
  assert.equal(frame.ok, false, JSON.stringify(frame));
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /focused document is a pcb/);
  assert.equal(host.__markers.length, 0);
});

test('an unreadable page is structural, not an empty jump list', async (t) => {
  const host = hostReviewMark({ without: ['sch_PrimitiveComponent'] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK] });
  assert.equal(frame.ok, false, JSON.stringify(frame));
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /could not be read/);
});

test('review.mark needs marks, and says what to send instead', async (t) => {
  const host = hostReviewMark();
  withEda(t, host);
  await connector.activate();

  for (const params of [{}, { marks: [] }, { markers: false }]) {
    const frame = await call(host, 'review.mark', params);
    assert.equal(frame.ok, false, JSON.stringify(frame));
    assert.equal(frame.error.code, 'BAD_REQUEST');
    assert.match(frame.error.message, /params\.marks/);
  }
  assert.equal(host.__markers.length, 0);
});

// --------------------------------------------------------------------------
// §八 review.mark — clear
// --------------------------------------------------------------------------

test('clear removes the markers and ignores the marks list', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 1, y: 1 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { clear: true, marks: [MARK] });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.cleared, true);
  assert.equal(frame.data.count, 0);
  assert.deepEqual(frame.data.marked, []);
  assert.equal(host.__removed(), 1);
  assert.equal(host.__markers.length, 0, 'clear does not draw');
});

test('clear reports a canvas that refuses the removal', async (t) => {
  const host = hostReviewMark({ remove: false });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { clear: true });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.cleared, false);
  assert.match(frame.data.note, /refused the removal/);
});

test('clear with no active document is already done, not refused', async (t) => {
  // Measured 2026-09-21: with nothing focused, the host answers `false` to
  // removeIndicatorMarkers — and that answer used to come back as "the canvas
  // refused the removal", which sends the caller looking for a canvas that is
  // not open. There is no canvas, so there is nothing to remove, and the clear
  // is idempotent.
  const host = hostReviewMark();
  host.dmt_SelectControl = { async getCurrentDocumentInfo() { return { uuid: '0' }; } };
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { clear: true });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.cleared, true);
  assert.match(frame.data.note, /no active canvas — nothing to remove/);
  // The host's own placeholder reading travels with the note, the way it does on
  // the drawing path.
  assert.match(frame.data.note, /placeholder/);
  assert.equal(host.__removed(), 0, 'there is no canvas, so nothing is asked of the host');
});

test('clear without removeIndicatorMarkers is structural', async (t) => {
  const host = hostReviewMark({ without: ['dmt_EditorControl.removeIndicatorMarkers'] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { clear: true });
  assert.equal(frame.ok, false, JSON.stringify(frame));
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
  assert.match(frame.error.message, /removeIndicatorMarkers/);
});

// --------------------------------------------------------------------------
// §八 review.mark — --focus N
// --------------------------------------------------------------------------

test('focus N zooms to the Nth mark, with the box in the declared order', async (t) => {
  const host = hostReviewMark({
    components: [
      component({ designator: 'C116', x: 100, y: 200 }),
      component({ designator: 'U1', x: -30, y: 40 }),
    ],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', {
    marks: [MARK, { ref: 'U1', ruleId: 'decoupling-per-ic', severity: 'ERROR', text: 'U1 无去耦' }],
    focus: 2,
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  // `zoomToRegion(left, right, top, bottom)` — the marker box plus a margin.
  assert.deepEqual(host.__zooms, [[-110, 50, 120, -40]]);
  assert.equal(frame.data.focused.position, 2);
  assert.equal(frame.data.focused.ref, 'U1');
  assert.equal(frame.data.focused.zoomed, true);
  assert.equal(
    host.__markers[0][3], false,
    'focus wins the zoom: the marker call must not zoom to all markers as well',
  );
});

test('focus out of range is refused before anything is drawn', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116' })] });
  withEda(t, host);
  await connector.activate();

  for (const focus of [0, 3, 1.5, 'first']) {
    const frame = await call(host, 'review.mark', { marks: [MARK], focus });
    assert.equal(frame.ok, false, JSON.stringify(frame));
    assert.equal(frame.error.code, 'BAD_REQUEST');
    assert.match(frame.error.message, /1-based position in marks/);
  }
  assert.equal(host.__markers.length, 0);
  assert.equal(host.__zooms.length, 0);
});

test('focus on an unresolved finding reports why it could not zoom', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 1, y: 1 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK, { ref: 'U9' }], focus: 2 });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(host.__zooms.length, 0);
  assert.equal(frame.data.focused.zoomed, false);
  assert.match(frame.data.focused.reason, /no position on this page/);
});

test('focus survives a host without zoomToRegion, and says so', async (t) => {
  const host = hostReviewMark({
    components: [component({ designator: 'C116', x: 100, y: 200 })],
    without: ['dmt_EditorControl.zoomToRegion'],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], focus: 1 });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.focused.zoomed, false);
  assert.match(frame.data.focused.reason, /zoomToRegion\(\) is not available/);
  assert.equal(frame.data.marked.length, 1, 'the marks are unaffected by a missing zoom');
});

test('focus reports a canvas that refuses the zoom', async (t) => {
  const host = hostReviewMark({
    components: [component({ designator: 'C116', x: 5, y: 5 })],
    zoom: false,
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], focus: 1 });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.focused.zoomed, false);
  assert.match(frame.data.focused.reason, /refused the zoom/);
});

test('a throwing zoomToRegion is reported, not raised', async (t) => {
  const host = hostReviewMark({
    components: [component({ designator: 'C116', x: 5, y: 5 })],
    zoom: () => {
      throw new TypeError('canvas is gone');
    },
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], focus: 1, zoom: true });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.match(frame.data.focused.reason, /zoomToRegion threw: canvas is gone/);
});

test('zoom: true is passed through to the marker call when there is no focus', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 1, y: 1 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], zoom: true });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(host.__markers[0][3], true);
});

test('a custom colour reaches the marker call', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 1, y: 1 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK], color: '#00FF007F' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(host.__markers[0][1], { r: 0, g: 255, b: 0, alpha: 127 });
});

test('review.mark without a pageUuid says the page was not verified', async (t) => {
  const host = hostReviewMark({ components: [component({ designator: 'C116', x: 1, y: 1 })] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'review.mark', { marks: [MARK] });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.page.active.uuid, SCH_PAGE);
  assert.ok(
    frame.data.notes.some((note) => /no pageUuid was given/.test(note)),
    JSON.stringify(frame.data.notes),
  );
});
