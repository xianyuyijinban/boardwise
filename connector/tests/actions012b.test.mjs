/**
 * Contract tests for the 012v2 second batch: `export.fab` and `lib.recommend`.
 *
 * Same boundary as every other action test — the *production* dispatch path
 * against a fake host, so the wire contract and the failure shapes are pinned
 * where the daemon sees them. Each host here carries only what its action
 * reaches for (the manufacture API, or the library search API plus one page of
 * components); anything beyond that fails the test, which is what keeps the
 * claims about "read-only" and "the connector does not write outDir" honest
 * rather than aspirational.
 *
 * Nothing in this file needs EasyEDA: the real-host questions (does the BOM
 * accept these column names, does the gerber export come back as a zip, does
 * `searchByProperties` exist at all on a v3.2 host) are *machine* questions and
 * are parked in the task book, not asserted here.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { createFacade } from '../dist/esm/facade.mjs';
import * as connector from '../dist/esm/index.mjs';

const BANNER = {
  event: 'banner',
  data: { server: 'boardwise', protocol: '1.0', expect: 'hello' },
};

const SCH_PAGE = 'page-1';
const PCB_UUID = 'pcb-1';

/** A host `File` stand-in: the action only ever calls `arrayBuffer()`. */
function hostFile(bytes, name, type = '') {
  return {
    name,
    type,
    async arrayBuffer() {
      return Uint8Array.from(bytes).buffer;
    },
  };
}

const PNGISH = [0x1f, 0x8b, 0x08, 0x00, 0x11, 0x22];
const ZIPISH = [0x50, 0x4b, 0x03, 0x04, 0x55, 0x66];
const CSVISH = [0x4e, 0x6f, 0x2c, 0x51, 0x74, 0x79];

/**
 * What a host method returns for one option.
 *
 * Keyed by presence, not by `undefined`: an option the test *did* name but set
 * to `undefined` means "this call returns nothing" — the whole point of the
 * missing-file cases — while an absent option means "use the default". A
 * function option is called, which is how a test plants a throw or a hang.
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
    dmt_Project: {
      async getCurrentProjectInfo() {
        return { uuid: 'proj-1', name: 'proj-1-name', friendlyName: '毕设板' };
      },
    },
  };
  return host;
}

/**
 * A host with the manufacture API the fab action calls.
 *
 * Every export call is recorded with its **arguments** — the preset's whole
 * point is the argument set, so a test that only checked "three files came
 * back" would pass with the wrong units and an empty BOM column list.
 */
function hostFab(options = {}) {
  const calls = [];
  // Mutated rather than spread: the plumbing's `register` closure hands the
  // message callback to the object it was built on, so a copy would leave the
  // transport writing to an object nothing else can see.
  const host = baseHost();
  host.dmt_Pcb = {
    async getCurrentPcbInfo() {
      return pick(options, 'pcbInfo', { uuid: PCB_UUID, name: 'PCB1' });
    },
  };
  host.pcb_ManufactureData = {
    async getGerberFile(...args) {
      calls.push({ role: 'gerber', args });
      return pick(options, 'gerber', hostFile(ZIPISH, 'fab_gerber.zip', 'application/zip'));
    },
    async getPickAndPlaceFile(...args) {
      calls.push({ role: 'pick_and_place', args });
      return pick(options, 'pickAndPlace', hostFile(CSVISH, ''));
    },
    async getBomFile(...args) {
      calls.push({ role: 'bom', args });
      return pick(options, 'bom', hostFile(CSVISH, ''));
    },
  };
  host.__calls = calls;
  for (const name of options.without ?? []) delete host[name];
  return host;
}

/** A placed component as `sch_PrimitiveComponent.getAll()` hands it back. */
function placedComponent({ designator, primitiveId = `p-${designator}`, props = {} }) {
  return {
    getState_Designator: () => designator,
    getState_PrimitiveId: () => primitiveId,
    getState_OtherProperty: () => props,
  };
}

/** A library search item, in the shape the declaration describes. */
function searchItem({
  uuid,
  libraryUuid = 'lib-1',
  name = '',
  footprintName = '',
  footprint,
  symbol,
  otherProperty = {},
  supplierId,
  description,
}) {
  const item = { uuid, libraryUuid, name, footprintName, otherProperty };
  if (footprint) item.footprint = footprint;
  if (symbol) item.symbol = symbol;
  if (supplierId) item.supplierId = supplierId;
  if (description) item.description = description;
  return item;
}

/** A host with the library search surface the recommend action walks. */
function hostRecommend(options = {}) {
  const searches = [];
  const writes = [];
  // Mutated, not spread — see `hostFab` above.
  const host = baseHost();
  host.sch_PrimitiveComponent = {
    async getAll() {
      return pick(options, 'components', []);
    },
    // A recording write API: `lib.recommend` is read-only, and the way to prove
    // it is that this is never reached.
    async modify(...args) {
      writes.push(args);
      return {};
    },
  };
  host.lib_Device = {
    async searchByProperties(properties, _libraryUuid, _classification, _symbolType, itemsOfPage, page) {
      searches.push({ api: 'searchByProperties', properties, itemsOfPage, page });
      return options.searchByProperties
        ? options.searchByProperties(properties, page)
        : [];
    },
    async search(keyword, _libraryUuid, _classification, _symbolType, itemsOfPage, page) {
      searches.push({ api: 'search', keyword, itemsOfPage, page });
      return options.search ? options.search(keyword, page) : [];
    },
  };
  host.__searches = searches;
  host.__writes = writes;
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

const decode = (payload) => [...Buffer.from(payload, 'base64')];

// --------------------------------------------------------------------------
// §六 export.fab
// --------------------------------------------------------------------------

test('fab exports the three files with the vendor preset arguments', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'E:/out/fab' });
  assert.equal(frame.ok, true, JSON.stringify(frame));

  // The gerber arguments are the preset, position for position. `layers` and
  // `objects` are deliberately undefined: the declared default is the editor's
  // own one-click export set.
  assert.deepEqual(host.__calls[0], {
    role: 'gerber',
    args: [
      'fab_gerber',
      false,
      'mm',
      { integerNumber: 4, decimalNumber: 5 },
      {
        metallicDrillingInformation: true,
        nonMetallicDrillingInformation: true,
        drillTable: true,
        flyingProbeTestingFile: false,
      },
      undefined,
      undefined,
    ],
  });
  assert.deepEqual(host.__calls[1].args, ['fab_pick_and_place', 'csv', 'mm']);

  const bom = host.__calls[2].args;
  assert.equal(bom[0], 'fab_bom');
  assert.equal(bom[1], 'csv');
  assert.equal(bom[2], undefined, 'no bomTemplate was passed, so the host gets undefined');
  assert.deepEqual(bom[3], [
    { property: 'Add into BOM', includeValue: 'yes' },
    { property: 'Convert to PCB', includeValue: 'yes' },
  ]);
  assert.deepEqual(bom[4], ['No.', 'Quantity']);
  // "csv 全列": the columns the host is asked for and the `property` list it is
  // given are one list, so they cannot disagree.
  assert.equal(bom[5].length, 15);
  assert.deepEqual(bom[5], bom[6].map((column) => column.property));
  assert.ok(bom[5].includes('JLCPCB Part Class'));
  assert.ok(bom[5].includes('Supplier Part'));

  assert.deepEqual(frame.data.files.map((f) => f.role), ['gerber', 'pick_and_place', 'bom']);
  assert.equal(frame.data.encoding, 'base64');
  const gerber = frame.data.files[0];
  // The host named it, so its name wins — the editor knows whether its gerber
  // export is an archive better than a suffix guess does.
  assert.equal(gerber.name, 'fab_gerber.zip');
  assert.equal(gerber.mime, 'application/zip');
  assert.equal(gerber.bytes, ZIPISH.length);
  assert.deepEqual(decode(gerber.data), ZIPISH);
  // The two nameless files are named from the preset plus their real suffix.
  assert.equal(frame.data.files[1].name, 'fab_pick_and_place.csv');
  assert.equal(frame.data.files[2].name, 'fab_bom.csv');
  assert.deepEqual(decode(frame.data.files[2].data), CSVISH);
});

test('fab writes a manifest the caller can drop next to the files', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'E:/out/fab' });
  const manifest = frame.data.manifest;
  assert.equal(manifest.schema, 'boardwise.fab/1');
  assert.equal(manifest.vendor, 'generic');
  assert.equal(manifest.outDir, 'E:/out/fab');
  assert.equal(manifest.project.name, '毕设板');
  assert.equal(manifest.project.uuid, 'proj-1');
  assert.deepEqual(manifest.pcb, { uuid: PCB_UUID, name: 'PCB1' });
  assert.deepEqual(
    manifest.files.map((f) => [f.role, f.name, f.bytes]),
    [['gerber', 'fab_gerber.zip', ZIPISH.length],
     ['pick_and_place', 'fab_pick_and_place.csv', CSVISH.length],
     ['bom', 'fab_bom.csv', CSVISH.length]],
  );
  assert.deepEqual(manifest.failed, []);
  assert.ok(Number.isFinite(Date.parse(manifest.generatedAt)), 'generatedAt must be a timestamp');
  assert.equal(manifest.generatedAt, frame.data.generatedAt);
  // The two honest caveats travel *with the bundle*, so a directory found on
  // disk later says what was and was not verified.
  assert.match(manifest.notes.join(' '), /unverified until a real export is run/);
  assert.match(manifest.notes.join(' '), /cannot write to outDir/);
  assert.equal(frame.data.partial, false);
});

test('fab defaults to the focused PCB and reports which board it took', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'E:/out/fab' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.pcb, { uuid: PCB_UUID, name: 'PCB1' });
  assert.equal(host.__calls.length, 3);

  // …and passing the uuid that is in front is accepted, not merely tolerated.
  const explicit = await call(host, 'export.fab', { outDir: 'E:/out/fab', pcbUuid: PCB_UUID });
  assert.equal(explicit.ok, true);
});

test('fab refuses a pcbUuid that is not the focused board, before exporting', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', {
    outDir: 'E:/out/fab',
    pcbUuid: 'some-other-board',
  });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'PAGE_MISMATCH');
  assert.deepEqual(frame.error.detail, { expected: 'some-other-board', actual: PCB_UUID });
  // The guard exists so the *wrong board* is never exported — nothing ran.
  assert.deepEqual(host.__calls, []);
});

test('fab says so when no PCB is open instead of exporting something else', async (t) => {
  const host = hostFab({ pcbInfo: null });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'E:/out/fab' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /no PCB is open/);
  assert.deepEqual(host.__calls, []);
});

test('fab rejects an unknown vendor and names the reserved one', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const typo = await call(host, 'export.fab', { outDir: 'x', vendor: 'genericx' });
  assert.equal(typo.ok, false);
  assert.equal(typo.error.code, 'BAD_REQUEST');
  assert.match(typo.error.message, /generic/);

  // 捷配 is a reserved configuration slot, not a typo — the two are different
  // facts and the message must not blur them (012v2 §六).
  const pending = await call(host, 'export.fab', { outDir: 'x', vendor: 'jiepei' });
  assert.equal(pending.ok, false);
  assert.equal(pending.error.code, 'BAD_REQUEST');
  assert.match(pending.error.message, /no preset for vendor "jiepei"/);
  assert.match(pending.error.message, /sample BOM/);
  assert.deepEqual(host.__calls, []);
});

test('fab needs an outDir — the caller has to know where the bundle goes', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', {});
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'BAD_REQUEST');
  assert.match(frame.error.message, /outDir/);
  assert.deepEqual(host.__calls, []);
});

test('fab applies gerber overrides and refuses a key it does not know', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', {
    outDir: 'E:/out/fab',
    gerber: { unit: 'inch', digitalFormat: { integerNumber: 3, decimalNumber: 6 }, colorSilkscreen: true },
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  const args = host.__calls[0].args;
  assert.equal(args[1], true);
  assert.equal(args[2], 'inch');
  assert.deepEqual(args[3], { integerNumber: 3, decimalNumber: 6 });
  // Untouched fields keep the preset values.
  assert.equal(args[4].drillTable, true);
  assert.deepEqual(frame.data.manifest.preset.overrides, ['colorSilkscreen', 'digitalFormat', 'unit']);

  for (const bad of [{ bogus: 1 }, { unit: 'furlongs' }, { digitalFormat: { integerNumber: 4 } }]) {
    const rejected = await call(host, 'export.fab', { outDir: 'x', gerber: bad });
    assert.equal(rejected.ok, false, `expected ${JSON.stringify(bad)} to be refused`);
    assert.equal(rejected.error.code, 'BAD_REQUEST');
  }
});

test('fab passes a bomTemplate through as the template name', async (t) => {
  const host = hostFab();
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'x', bomTemplate: '捷配-常用' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(host.__calls[2].args[2], '捷配-常用');
  assert.equal(frame.data.manifest.preset.bom.template, '捷配-常用');
});

test('fab reports one missing file and keeps the other two', async (t) => {
  const host = hostFab({ bom: undefined });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'E:/out/fab' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.partial, true);
  assert.deepEqual(frame.data.files.map((f) => f.role), ['gerber', 'pick_and_place']);
  assert.equal(frame.data.failed.length, 1);
  assert.equal(frame.data.failed[0].role, 'bom');
  assert.match(frame.data.failed[0].reason, /returned no file/);
  assert.equal(frame.data.manifest.failed.length, 1);
});

test('fab calls an empty file a failure, not a small export', async (t) => {
  const host = hostFab({ gerber: hostFile([], 'fab_gerber.zip', 'application/zip') });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'E:/out/fab' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.failed, [{ role: 'gerber', reason: 'the editor returned an empty file' }]);
  assert.deepEqual(frame.data.files.map((f) => f.role), ['pick_and_place', 'bom']);
});

test('fab fails when the whole bundle is missing (an empty bundle is not a bundle)', async (t) => {
  const host = hostFab({
    gerber: () => { throw new Error('cannot build gerber'); },
    pickAndPlace: undefined,
    bom: undefined,
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'E:/out/fab' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /none of the three fab files came back/);
  assert.equal(frame.error.detail.failed.length, 3);
  assert.match(frame.error.detail.failed[0].reason, /cannot build gerber/);
});

test('fab fails structurally when the manufacture namespace is gone', async (t) => {
  const host = hostFab({ without: ['pcb_ManufactureData'] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'x' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
  assert.match(frame.error.message, /pcb_ManufactureData/);
});

test('fab fails structurally when one declared method is gone', async (t) => {
  // Half a bundle is a structural failure, not a partial result: a fab house
  // cannot use two of the three files, so "the API is gone" must not be dressed
  // up as "the BOM happened to be empty".
  const host = hostFab();
  delete host.pcb_ManufactureData.getBomFile;
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'x' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
  assert.match(frame.error.message, /getBomFile/);
  assert.deepEqual(host.__calls, []);
});

test('fab bounds each export so one swallow cannot hold the action', async (t) => {
  // The export.render lesson: the host drops an argument it dislikes and the
  // promise never settles. Each file has its own deadline; here all three hang
  // and the answer still comes back, per file.
  const hang = () => new Promise(() => {});
  const host = hostFab({ gerber: hang, pickAndPlace: hang, bom: hang });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'export.fab', { outDir: 'x', timeoutMs: 200 });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.deepEqual(frame.error.detail.failed.map((f) => f.role), ['gerber', 'pick_and_place', 'bom']);
  for (const failure of frame.error.detail.failed) {
    assert.match(failure.reason, /^TIMEOUT: /);
  }
});

// --------------------------------------------------------------------------
// §七 lib.recommend
// --------------------------------------------------------------------------

/** The SS34 fixture: a placed diode with MPN, LCSC code, value and footprint. */
function ss34Components() {
  return [
    placedComponent({ designator: 'R1', primitiveId: 'p-r1', props: { Value: '10k' } }),
    placedComponent({
      designator: 'D1',
      primitiveId: 'p-d1',
      props: {
        Value: 'SS34',
        'Manufacturer Part': 'SS34',
        'Supplier Part': 'C8678',
        FootprintName: 'SMA_L4.4-W2.6-LS5.0-RD',
        'Supplier Footprint': 'SMA',
      },
    }),
  ];
}

const BASIC_SS34 = searchItem({
  uuid: 'dev-basic',
  name: 'SS34',
  footprintName: 'SMA_L4.4-W2.6-LS5.0-RD',
  footprint: { uuid: 'fp-basic', libraryUuid: 'lib-1', name: 'SMA_L4.4-W2.6-LS5.0-RD' },
  symbol: { uuid: 'sym-basic', libraryUuid: 'lib-1', name: 'SS34' },
  otherProperty: {
    'Supplier Part': 'C8678',
    'Manufacturer Part': 'SS34',
    Manufacturer: 'MDD(辰达半导体)',
    'Supplier Footprint': 'SMA',
    'JLCPCB Part Class': 'Basic Part',
    Datasheet: 'https://example.invalid/ss34.pdf',
  },
});

const EXTENDED_SS34 = searchItem({
  uuid: 'dev-ext',
  name: 'SS34-E3/61T',
  footprintName: 'SMA_L4.31-W2.79-LS5.28',
  otherProperty: {
    'Supplier Part': 'C12345',
    'Manufacturer Part': 'SS34-E3/61T',
    'JLCPCB Part Class': 'Extended Part',
  },
});

test('recommend descends the ladder and reports every rung', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    // The exact rung misses, the described rung misses, the keyword rung hits —
    // the shape the ladder exists for (a part the library does not know by MPN).
    searchByProperties: () => [],
    search: (keyword) => (keyword === 'SS34' ? [EXTENDED_SS34] : []),
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.equal(frame.data.source, 'ref');
  assert.equal(frame.data.ref, 'D1');
  // The rungs are told apart by what they were handed, and each reports its own
  // hit count — including the two that found nothing.
  assert.deepEqual(frame.data.layers.map((l) => [l.layer, l.api, l.called, l.hitCount]), [
    ['exact', 'searchByProperties', true, 0],
    ['properties', 'searchByProperties', true, 0],
    ['keyword', 'search', true, 1],
  ]);
  assert.deepEqual(frame.data.layers[0].args, { partNumber: 'SS34', partCode: 'C8678' });
  assert.deepEqual(frame.data.layers[1].args, {
    value: 'SS34', footprintName: 'SMA_L4.4-W2.6-LS5.0-RD',
  });
  assert.deepEqual(frame.data.layers[2].args, { keyword: 'SS34' });
  assert.equal(frame.data.layers[0].pagesFetched, 1);
  assert.deepEqual(host.__searches.map((s) => [s.api, s.itemsOfPage, s.page]), [
    ['searchByProperties', 5, 1],
    ['searchByProperties', 5, 1],
    ['search', 5, 1],
  ]);
  // The part's own parameters, read off the page, are the provenance of the
  // search — and they are what the caller compares a candidate against.
  assert.deepEqual(frame.data.component, {
    primitiveId: 'p-d1',
    designator: 'D1',
    name: '',
    value: 'SS34',
    partNumber: 'SS34',
    partCode: 'C8678',
    footprintName: 'SMA_L4.4-W2.6-LS5.0-RD',
    supplierFootprint: 'SMA',
  });
  assert.equal(frame.data.candidates.length, 1);
  assert.equal(frame.data.candidates[0].layer, 'keyword');
});

test('recommend stops at the first rung that hits, and says so', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: (properties) => (properties.partNumber ? [BASIC_SS34] : [EXTENDED_SS34]),
    search: () => [EXTENDED_SS34],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.layers.map((l) => [l.layer, l.called, l.hitCount]), [
    ['exact', true, 1],
    ['properties', false, 0],
    ['keyword', false, 0],
  ]);
  // "not called" must never read as "found nothing".
  assert.match(frame.data.layers[1].reason, /earlier rung matched/);
  assert.equal(host.__searches.length, 1, 'a hit ends the descent');
});

test('recommend puts Basic parts first and maps the item fields', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    // Deliberately backwards: extended first, basic second.
    searchByProperties: () => [EXTENDED_SS34, BASIC_SS34],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  const [first, second] = frame.data.candidates;
  assert.equal(first.partClass, 'Basic Part');
  assert.equal(first.partClassRank, 0);
  assert.equal(second.partClass, 'Extended Part');
  assert.deepEqual(
    {
      name: first.name,
      lcsc: first.lcsc,
      mpn: first.mpn,
      footprintName: first.footprintName,
      datasheet: first.datasheet,
      deviceUuid: first.deviceUuid,
      libraryUuid: first.libraryUuid,
      symbolUuid: first.symbolUuid,
      footprintUuid: first.footprintUuid,
      layer: first.layer,
      footprintMatches: first.footprintMatches,
    },
    {
      name: 'SS34',
      lcsc: 'C8678',
      mpn: 'SS34',
      footprintName: 'SMA_L4.4-W2.6-LS5.0-RD',
      datasheet: 'https://example.invalid/ss34.pdf',
      deviceUuid: 'dev-basic',
      libraryUuid: 'lib-1',
      symbolUuid: 'sym-basic',
      footprintUuid: 'fp-basic',
      layer: 'exact',
      footprintMatches: true,
    },
  );
  // No stock, no price — the type package carries neither, so the answer labels
  // them instead of leaving a confident-looking gap.
  assert.equal(frame.data['stock/price'], '以商城实时为准');
  assert.equal(frame.data.readOnly, true);
  assert.equal(frame.data.placed, false);
  assert.deepEqual(host.__writes, [], 'lib.recommend must never write');
});

test('recommend answers an honest empty result when nothing matches', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: () => [],
    search: () => [],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.candidates, []);
  assert.equal(frame.data.returned, 0);
  assert.equal(frame.data.shown, 0);
  assert.deepEqual(frame.data.layers.map((l) => l.hitCount), [0, 0, 0]);
  assert.match(frame.data.notes.join(' '), /no library match/);
  // Every rung ran and *answered* — an empty answer is not a broken search.
  assert.equal(host.__searches.length, 3);
});

test('recommend takes a query or a ref, and exactly one of them', async (t) => {
  const host = hostRecommend({
    searchByProperties: (properties, page) => (properties.partNumber === 'SS34' && page === 1
      ? [BASIC_SS34] : []),
  });
  withEda(t, host);
  await connector.activate();

  const byQuery = await call(host, 'lib.recommend', { query: 'SS34' });
  assert.equal(byQuery.ok, true, JSON.stringify(byQuery));
  assert.equal(byQuery.data.source, 'query');
  // A bare query is used verbatim on every rung: an MPN is also the value.
  assert.deepEqual(byQuery.data.layers[0].args, { partNumber: 'SS34' });
  assert.deepEqual(byQuery.data.target.value, 'SS34');
  assert.equal(byQuery.data.candidates.length, 1);

  const neither = await call(host, 'lib.recommend', {});
  assert.equal(neither.ok, false);
  assert.equal(neither.error.code, 'BAD_REQUEST');
  assert.match(neither.error.message, /needs query, or \{pageUuid, ref\}/);

  const both = await call(host, 'lib.recommend', {
    query: 'SS34', pageUuid: SCH_PAGE, ref: 'D1',
  });
  assert.equal(both.ok, false);
  assert.equal(both.error.code, 'BAD_REQUEST');
  assert.match(both.error.message, /not both/);

  const refWithoutPage = await call(host, 'lib.recommend', { ref: 'D1' });
  assert.equal(refWithoutPage.ok, false);
  assert.equal(refWithoutPage.error.code, 'BAD_REQUEST');
  assert.match(refWithoutPage.error.message, /needs pageUuid/);
});

test('recommend reads an LCSC code as a part code, not as a value', async (t) => {
  const host = hostRecommend({ searchByProperties: () => [BASIC_SS34] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { query: 'c8678' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.layers[0].args, { partCode: 'C8678' });
  assert.deepEqual(frame.data.layers[1].args, {}, 'a C-number is not a value');
  assert.equal(frame.data.layers[1].called, false);
});

test('recommend refuses a ref on a page that is not the focused one', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: () => [BASIC_SS34],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: 'another-page', ref: 'D1' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'PAGE_MISMATCH');
  // The designator would have resolved against the wrong board's page.
  assert.deepEqual(host.__searches, []);
});

test('recommend reports a designator the page does not hold', async (t) => {
  const host = hostRecommend({ components: ss34Components() });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'U9' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_FOUND');
  assert.deepEqual(frame.error.detail.designators, ['R1', 'D1']);
  assert.deepEqual(host.__searches, []);
});

test('recommend degrades visibly when searchByProperties is absent (ADD since EDA v4)', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    without: ['lib_Device.searchByProperties'],
    search: () => [BASIC_SS34],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.layers.map((l) => [l.layer, l.called]), [
    ['exact', false],
    ['properties', false],
    ['keyword', true],
  ]);
  assert.match(frame.data.layers[0].reason, /ADD since EDA v4/);
  assert.equal(frame.data.candidates.length, 1);
  assert.match(frame.data.notes.join(' '), /searchByProperties is not available/);
  // The keyword rung is the only one asked, and it is asked correctly.
  assert.deepEqual(host.__searches, [{ api: 'search', keyword: 'SS34', itemsOfPage: 5, page: 1 }]);
});

test('recommend fails structurally when lib_Device is gone', async (t) => {
  const host = hostRecommend({ components: ss34Components(), without: ['lib_Device'] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { query: 'SS34' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
  assert.match(frame.error.message, /lib_Device/);
});

test('recommend fails structurally when no search API exists at all', async (t) => {
  const host = hostRecommend({ without: ['lib_Device.search', 'lib_Device.searchByProperties'] });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { query: 'SS34' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'NOT_IMPLEMENTED');
  assert.match(frame.error.message, /nothing can be searched/);
});

test('recommend bounds a search that never settles, per page', async (t) => {
  // A search reaches the library backend, so it is the one call here that can
  // hang rather than fail. Unbounded, a hung page would hold the action until
  // the daemon gave up and answer with nothing about which rung stalled.
  const hang = () => new Promise(() => {});
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: hang,
    search: () => [BASIC_SS34],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', {
    pageUuid: SCH_PAGE, ref: 'D1', timeoutMs: 200,
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.match(frame.data.layers[0].error, /^TIMEOUT: /);
  assert.equal(frame.data.layers[0].pagesFetched, 0);
  // The descent still happened: a hung rung is a failed rung, not the end.
  assert.equal(frame.data.layers[2].hitCount, 1);
  assert.equal(frame.data.candidates.length, 1);
});

test('recommend calls a rung that throws a failed rung, and still descends', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: () => { throw new Error('library offline'); },
    search: () => [BASIC_SS34],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.match(frame.data.layers[0].error, /library offline/);
  assert.equal(frame.data.layers[2].hitCount, 1);
  assert.match(frame.data.notes.join(' '), /a search rung failed/);
});

test('recommend fails when every rung throws — that is not an empty answer', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: () => { throw new Error('library offline'); },
    search: () => { throw new Error('library offline'); },
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1' });
  assert.equal(frame.ok, false);
  assert.equal(frame.error.code, 'CONNECTOR_ERROR');
  assert.match(frame.error.message, /every search rung failed/);
  assert.equal(frame.error.detail.errors.length, 3);
});

test('recommend pages a rung at most three times', async (t) => {
  const pages = [];
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: (properties, page) => {
      pages.push(page);
      // Every page is full, so only the cap can stop the walk.
      return [1, 2, 3, 4, 5].map((n) => searchItem({ uuid: `dev-${page}-${n}`, name: `part ${page}-${n}` }));
    },
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'D1', topN: 12 });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(pages, [1, 2, 3]);
  assert.equal(frame.data.layers[0].pagesFetched, 3);
  assert.equal(frame.data.layers[0].hitCount, 15);
  assert.equal(frame.data.shown, 12);
  assert.equal(frame.data.returned, 15);
});

test('recommend with allLayers merges the rungs and keeps one row per device', async (t) => {
  const host = hostRecommend({
    components: ss34Components(),
    searchByProperties: (properties) => (properties.partNumber ? [BASIC_SS34] : [EXTENDED_SS34]),
    search: () => [BASIC_SS34, EXTENDED_SS34],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', {
    pageUuid: SCH_PAGE, ref: 'D1', allLayers: true,
  });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.layers.map((l) => l.called), [true, true, true]);
  assert.deepEqual(frame.data.layers.map((l) => l.hitCount), [1, 1, 2]);
  // Two devices came back from three rungs; the first rung to offer a device
  // keeps it, so `layer` stays the strongest evidence of why it is here.
  assert.equal(frame.data.returned, 2);
  assert.deepEqual(frame.data.candidates.map((c) => [c.deviceUuid, c.layer]), [
    ['dev-basic', 'exact'],
    ['dev-ext', 'properties'],
  ]);
});

test('recommend resolves a ref without needing the search APIs to be perfect', async (t) => {
  // A part with only a value and a footprint (no MPN, no LCSC code): the exact
  // rung has nothing to send, so it must be reported as unsent rather than
  // called with an empty property object.
  const host = hostRecommend({
    components: [placedComponent({
      designator: 'C7',
      props: { Value: '100nF', FootprintName: 'C0805' },
    })],
    searchByProperties: () => [searchItem({ uuid: 'dev-cap', name: '100nF 0805' })],
  });
  withEda(t, host);
  await connector.activate();

  const frame = await call(host, 'lib.recommend', { pageUuid: SCH_PAGE, ref: 'C7' });
  assert.equal(frame.ok, true, JSON.stringify(frame));
  assert.deepEqual(frame.data.layers[0].args, {});
  assert.equal(frame.data.layers[0].called, false);
  assert.match(frame.data.layers[0].reason, /no partNumber \(MPN\) or partCode/);
  assert.deepEqual(frame.data.layers[1].args, { value: '100nF', footprintName: 'C0805' });
  assert.equal(frame.data.layers[1].hitCount, 1);
  assert.equal(frame.data.target.partCode, '');
});
