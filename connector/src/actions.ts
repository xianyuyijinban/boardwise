/**
 * Action handlers: the read-mostly surface of bridge v0.
 *
 * Everything here is a thin, defensive wrapper over the official `eda.*` API
 * (`@jlceda/pro-api-types@0.4.25`, Apache-2.0). Two habits worth keeping:
 *
 * 1. **Nothing is trusted to exist.** The API is versioned and adds methods
 *    over time, so every call is resolved at runtime and a missing one becomes
 *    a structured `NOT_IMPLEMENTED` with the name in `detail` — the manual
 *    checklist in `docs/bridge.md` turns that into a precise bug report
 *    instead of a blank failure.
 * 2. **Only scalars cross the wire.** Editor objects are method-based
 *    (`getState_X()`), not plain JSON, and may hold references. We walk the
 *    `getState_*` getters, keep the scalar results and summarise the rest, so
 *    the daemon never receives a structure it cannot serialise.
 */

import { PROBE_CHECKS, ADDED_SINCE } from './api-names';
import { ActionError, isActionError } from './protocol';
import { sysSelfUpdate } from './self-update';
import { VERSION } from './version';

/** The slice of the `eda` global this connector actually uses. */
export type Eda = Record<string, any>;

export type ActionHandler = (
  params: Record<string, unknown>,
  eda: Eda,
) => Promise<unknown>;

/** Marker colour type from the official `generateIndicatorMarkers`. */
type MarkerColor = { r: number; g: number; b: number; alpha: number };

const DEFAULT_MARKER_COLOR: MarkerColor = { r: 255, g: 0, b: 0, alpha: 255 };

// --------------------------------------------------------------------------
// small helpers
// --------------------------------------------------------------------------

/** Await a value that may or may not be a promise (the API mixes both). */
async function settle<T>(value: T | Promise<T>): Promise<T> {
  return await value;
}

/**
 * Editor objects expose `getState_*()`; call one if it exists.
 *
 * **Both** halves are guarded, and that is the whole point. The host hands out
 * *exotic* objects — Proxies whose `get` trap throws — and `obj[prop]` is a
 * trap invocation, not a safe lookup. Measured 2026-09-14: leaving the read
 * outside the `try` made `sch.geometry`, `sch.readback` and the
 * `document.current` info boxes die with
 * `TypeError: Cannot read properties of undefined (reading 'prototype')`,
 * while every path that did *not* go through `getState` (the probe's `checks`,
 * the tab list, the top-level namespace scan) kept working. A reproduce-in-Node
 * experiment pinned it: the guarded prototype walk survives a throwing Proxy,
 * a bare member read does not.
 */
async function getState(obj: any, name: string, errors?: string[]): Promise<unknown> {
  let fn: any;
  try {
    // Inside the guard on purpose: `obj?.[…]` only protects against
    // null/undefined, not against a trap that throws.
    fn = obj?.[`getState_${name}`];
  } catch (error) {
    // A trap that throws is NOT the same as "this field does not exist";
    // recording it keeps the readback from looking like an empty part.
    errors?.push(`read getState_${name}: ${String((error as Error)?.message ?? error)}`);
    return undefined;
  }
  if (typeof fn !== 'function') return undefined;
  try {
    return await settle(fn.call(obj));
  } catch {
    return undefined;
  }
}

/**
 * Read a plain property, tolerating case and separator drift.
 *
 * Not everything in the API is a `getState_*` primitive: the document info
 * objects (`IDMT_SchematicItem`, `IDMT_SchematicPageItem`, …) carry plain
 * readonly properties (`uuid`, `parentSchematicUuid`). Reading those with
 * `getState_Uuid` returns `undefined`, which made `sch.doc.new` conclude
 * "no schematic is open" on a machine where one clearly was — measured
 * 2026-09-13. This helper is the honest way to read both shapes.
 */
function plainGet(obj: any, ...names: string[]): unknown {
  if (!obj || typeof obj !== 'object') return undefined;
  const lowered = new Map<string, unknown>();
  for (const key of Object.keys(obj)) lowered.set(key.replace(/[_\s-]/g, '').toLowerCase(), obj[key]);
  for (const name of names) {
    const value = lowered.get(name.replace(/[_\s-]/g, '').toLowerCase());
    if (value !== undefined) return value;
  }
  return undefined;
}

function isScalar(value: unknown): value is string | number | boolean {
  return (
    typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
  );
}

/**
 * Read one member without letting a hostile object kill the caller.
 *
 * Same lesson as :func:`getState`: on an exotic host object a property read is
 * a *trap invocation* and may throw, and `obj?.[key]` does not catch that.
 * Returns the value, or the failure message — a caller that cannot proceed
 * must say *which* member and *why*, never swallow it.
 */
function readMember(obj: any, key: string): { value?: any; error?: string } {
  try {
    return { value: obj?.[key] };
  } catch (error) {
    return { error: String((error as Error)?.message ?? error) };
  }
}

/**
 * Where the prototype walk stops, read **once** and **guarded**.
 *
 * These used to be written inline in the loop condition
 * (`current !== Object.prototype && current !== Function.prototype`) — which
 * put a *property read* outside every `try`, and on this host that read is the
 * thing that throws: the editor hands out an exotic `Function` whose
 * `.prototype` access raises `TypeError: Cannot read properties of undefined
 * (reading 'prototype')`. Every caller of the walk therefore died —
 * `sch.geometry`, `sch.readback`, the three `document.current` info boxes and
 * the probe's enumeration — while the guard *inside* the loop never got a
 * chance to run. Pinned from the machine on 2026-09-14 by the stack captured in
 * the error's `detail`: `walkPrototypeNames` at the `while` line, column inside
 * `Function.prototype`.
 *
 * A sentinel that cannot be read is simply dropped; the walk still terminates
 * on `null`, just a level later.
 */
const PROTOTYPE_STOPS: unknown[] = (() => {
  const stops: unknown[] = [];
  const global: any = typeof globalThis !== 'undefined' ? globalThis : {};
  for (const name of ['Object', 'Function']) {
    try {
      const proto = global?.[name]?.prototype;
      if (proto !== undefined && proto !== null) stops.push(proto);
    } catch {
      // hostile global: one sentinel fewer, never a crash
    }
  }
  return stops;
})();

/**
 * Collect the property names of an object and its prototype chain, safely.
 *
 * Editor objects are class instances, so their members live on the prototype
 * (`Object.keys` on an instance returns `[]` — measured 2026-09-14) — but some
 * namespaces are plain objects whose members are *own* properties, so the walk
 * has to start at the object itself and then climb. The host also hands out
 * *exotic* objects whose `getPrototypeOf`/`getOwnPropertyNames` throw: the
 * first `sys.probe` run died with "reading 'prototype'" on every namespace
 * because one such object aborted the whole walk. So each level is guarded on
 * its own; a bad level is recorded in ``errors`` and the walk continues where
 * it can.
 *
 * One implementation, three callers (``snapshot``, ``deepDump``, ``sys.probe``)
 * — the trap is subtle enough that it must not be written three times.
 */
function walkPrototypeNames(
  object: any,
  filter: (name: string) => boolean = () => true,
  errors?: string[],
): string[] {
  const names: string[] = [];
  const seen = new Set<string>();
  let current: any = object;
  let level = 0;
  while (current !== null && current !== undefined
    && !PROTOTYPE_STOPS.includes(current)) {
    if (level > 32) {
      errors?.push('prototype chain deeper than 32 levels; stopped');
      break;
    }
    try {
      for (const name of Object.getOwnPropertyNames(current)) {
        if (seen.has(name) || !filter(name)) continue;
        seen.add(name);
        names.push(name);
      }
    } catch (error) {
      errors?.push(
        `getOwnPropertyNames at level ${level}: ${String((error as Error)?.message ?? error)}`,
      );
    }
    try {
      current = Object.getPrototypeOf(current);
    } catch (error) {
      errors?.push(
        `getPrototypeOf at level ${level}: ${String((error as Error)?.message ?? error)}`,
      );
      break;
    }
    level += 1;
  }
  return names;
}

/**
 * Walk an editor primitive's `getState_*` getters and keep the scalars.
 *
 * Dynamic on purpose: field names differ across primitive kinds and versions,
 * and a hard-coded list would silently return `{}` when the API moves. Arrays
 * and objects are reported as a count plus, for arrays, the scalar snapshot of
 * the first element — enough for a review to reason about, small enough not to
 * flood the socket.
 */
async function snapshot(obj: any, maxKeys = 40, errors?: string[]): Promise<Record<string, unknown>> {
  const out: Record<string, unknown> = {};
  if (!obj || typeof obj !== 'object') return out;
  const names = new Set<string>();
  for (const name of walkPrototypeNames(obj, (n) => n.startsWith('getState_'), errors)) {
    names.add(name.slice('getState_'.length));
  }
  for (const name of [...names].slice(0, maxKeys)) {
    const value = await getState(obj, name, errors);
    if (value === undefined) continue;
    if (isScalar(value)) {
      out[name] = value;
    } else if (Array.isArray(value)) {
      out[name] = { count: value.length };
      if (value.length > 0) {
        const first = await snapshot(value[0], 12);
        if (Object.keys(first).length > 0) out[`${name}[0]`] = first;
      }
    } else if (value && typeof value === 'object') {
      out[name] = { object: true };
    }
  }
  return out;
}

/** Require a namespace object (e.g. `dmt_EditorControl`), or fail by name. */
function namespaceOf(eda: Eda, name: string): any {
  const ns = (eda as any)?.[name];
  if (!ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `${name} is not available in this editor version`,
      { path: name },
    );
  }
  return ns;
}

/** Require a method, or fail with a message that names it. */
function requireFn(eda: Eda, path: string): (...args: any[]) => any {
  const parts = path.split('.');
  let target: any = eda;
  for (const part of parts.slice(0, -1)) target = target?.[part];
  const fn = target?.[parts[parts.length - 1]];
  if (typeof fn !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `${path}() is not available in this editor version`,
      { path },
    );
  }
  return fn.bind(target);
}

/** 8 KiB chunks keep `String.fromCharCode` away from argument-count limits. */
function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  const chunk = 0x2000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

/** Flatten the split-screen tree into a tab list. */
function flattenTabs(node: any, out: any[] = []): any[] {
  if (!node) return out;
  if (Array.isArray(node.tabs)) out.push(...node.tabs);
  if (Array.isArray(node.children)) {
    for (const child of node.children) flattenTabs(child, out);
  }
  return out;
}

/**
 * `EDMT_EditorDocumentType` values we can name, from the type package.
 *
 * Only the ones this code can act on are listed; anything else is reported as
 * the number the host gave, never guessed into a kind.
 */
const DOC_KIND_BY_TYPE: Record<number, string> = {
  1: 'page',       // SCHEMATIC_PAGE
  3: 'pcb',        // PCB
  5: 'project',    // PROJECT
  2: 'symbol',     // SYMBOL_COMPONENT
  0: 'blank',      // BLANK
  [-1]: 'home',    // HOME
};

/** Turn whatever the host called a document type into a stable kind string. */
function documentKind(value: unknown): string {
  if (typeof value === 'number' && value in DOC_KIND_BY_TYPE) {
    return DOC_KIND_BY_TYPE[value];
  }
  if (typeof value === 'string' && value) return value;
  return 'unknown';
}

/**
 * The uuid of a document-info object, in whichever of the two shapes the host
 * handed it over.
 *
 * The type declarations describe these objects as plain readonly properties
 * (`uuid`, `name`), and `getCurrentDocumentInfo` does come back that way. The
 * per-kind getters, however, answered `document.current` through
 * `getState_*()` on the prototype (`data.pcb.Name` is read that way on the real
 * editor), and `plainGet` sees no own keys on such an object — so a fallback
 * that only knew one shape would report "no document" on a page that is
 * plainly open. Read both; a uuid we failed to find is named in `problems`.
 */
async function infoUuid(info: any): Promise<string | null> {
  const direct = plainGet(info, 'uuid');
  if (typeof direct === 'string' && direct) return direct;
  for (const name of ['getState_Uuid', 'getState_uuid', 'getState_UUID']) {
    const member = readMember(info, name);
    if (typeof member.value !== 'function') continue;
    try {
      const value = await settle((member.value as () => unknown).call(info));
      if (typeof value === 'string' && value) return value;
    } catch {
      /* this spelling is not the one; try the next */
    }
  }
  return null;
}

/**
 * The **one** read of "which document is active", shared by `doc.list` and
 * `document.current`.
 *
 * Why it is shared rather than duplicated: the two used to disagree, and the
 * disagreement was expensive. Measured 2026-09-15 — with a schematic page in
 * front, `document.current` reported `type: "unknown"` and an empty project
 * while `doc.list`, using `getCurrentDocumentInfo`, named the right page every
 * time. The difference was not luck: `document.current` was deriving `type`
 * from the split-screen tab tree, and the host's tab objects carry no
 * `documentType` on this build, so the derivation could only ever answer
 * "unknown". Two readers of the same fact with different answers is worse than
 * one wrong reader, because the disagreement itself is invisible.
 *
 * `source` says which call answered, so a fallback is never mistaken for the
 * direct answer.
 */
async function activeDocument(
  eda: Eda,
  problems: string[],
): Promise<{ uuid: string; type: string; tabId?: string; source: string } | null> {
  const DIRECT = 'dmt_SelectControl.getCurrentDocumentInfo';
  try {
    const info: any = await settle(requireFn(eda, DIRECT)());
    const uuid = await infoUuid(info);
    if (uuid) {
      const tabId = plainGet(info, 'tabId');
      return {
        uuid,
        // Same vocabulary as `doc.list`'s `documents[].type`.
        type: documentKind(plainGet(info, 'documentType')),
        ...(typeof tabId === 'string' && tabId ? { tabId } : {}),
        source: DIRECT,
      };
    }
  } catch (error) {
    problems.push(`${DIRECT}: ${String((error as Error)?.message ?? error)}`);
  }
  // Per-kind getters cannot say "nothing is open" — they say which kind they
  // are about — so a null there is a legitimate empty answer, not a failure.
  const fallbacks: ReadonlyArray<readonly [string, string]> = [
    ['dmt_Schematic.getCurrentSchematicPageInfo', 'page'],
    ['dmt_Pcb.getCurrentPcbInfo', 'pcb'],
  ];
  for (const [path, type] of fallbacks) {
    try {
      const info: any = await settle(requireFn(eda, path)());
      const uuid = await infoUuid(info);
      if (uuid) {
        return { uuid, type, source: path };
      }
    } catch (error) {
      problems.push(`${path}: ${String((error as Error)?.message ?? error)}`);
    }
  }
  return null;
}

// --------------------------------------------------------------------------
// handlers
// --------------------------------------------------------------------------

/**
 * `document.current` — what the editor has open.
 *
 * The API exposes *current project*, *current PCB* and *current schematic
 * page* separately but no "which tab is focused" getter, so we report all
 * three plus the tab list and let the caller decide. A project may legitimately
 * have both a schematic and a PCB open.
 */
export const documentCurrent: ActionHandler = async (_params, eda) => {
  // Each of the three info boxes is read through the same guarded path, and a
  // failure is *named*. "All three are null" used to be indistinguishable from
  // "no project is open" — measured 2026-09-14, when the actual cause turned
  // out to be a member read that threw inside `snapshot`.
  const problems: string[] = [];
  const readInfo = async (path: string, label: string) => {
    try {
      const info = await requireFn(eda, path)();
      return info ? await snapshot(info, 40, problems) : null;
    } catch (error) {
      problems.push(`${label} (${path}): ${String((error as Error)?.message ?? error)}`);
      return null;
    }
  };
  const project = await readInfo('dmt_Project.getCurrentProjectInfo', 'project');
  const pcb = await readInfo('dmt_Pcb.getCurrentPcbInfo', 'pcb');
  const schematicPage = await readInfo('dmt_Schematic.getCurrentSchematicPageInfo', 'schematicPage');

  // The active document, from the same call `doc.list` uses. This is the fix
  // for 2026-09-15: `type` used to come from the tab tree below, whose objects
  // carry no `documentType` on this build, so a schematic page in front was
  // reported as `unknown` while `doc.list` named it correctly.
  const active = await activeDocument(eda, problems);

  let tabs: unknown[] = [];
  try {
    const tree = await requireFn(eda, 'dmt_EditorControl.getSplitScreenTree')();
    tabs = flattenTabs(tree).map((tab) => {
      // The host's tab objects do not spell the document kind `documentType`
      // on this build (measured 2026-09-14: it came back `undefined`). Try the
      // plausible spellings, and carry the object's real key names so the next
      // run can settle it instead of guessing again. **Display only** — see
      // `typeSource`.
      const documentType = tab.documentType ?? tab.documentTypeId ?? tab.type
        ?? tab.documentKind ?? tab.kind;
      return {
        tabId: tab.tabId ?? tab.id,
        title: tab.title ?? tab.name,
        documentType: documentType ?? null,
        ...(documentType === undefined ? { keys: Object.keys(tab) } : {}),
      };
    });
  } catch {
    tabs = [];
  }

  // `type` is kept for callers that already read it, and now means "the kind
  // of the active document" instead of "whatever the tab tree looked like".
  // `page` is folded into `sch` because that is what this field has always
  // said for a schematic page; `active.kind` is the precise one and uses the
  // same vocabulary as `doc.list`.
  const kind = active?.type ?? '';
  const type = active === null
    ? null
    : kind === 'pcb' ? 'pcb' : (kind === 'page' || kind === 'schematic') ? 'sch' : 'unknown';

  return {
    project, pcb, schematicPage,
    active,
    type,
    // Which read produced `type`. Anything but `getCurrentDocumentInfo` is a
    // heuristic and must not be used as a criterion: the tab tree has no
    // document type on this host, so its answer is a guess dressed as data.
    typeSource: active?.source ?? 'none',
    heuristic: active !== null && active.source !== 'dmt_SelectControl.getCurrentDocumentInfo',
    tabs,
    ...(problems.length ? { problems } : {}),
  };
};

/** Shared readback: every primitive of the current document, summarised. */
async function readback(eda: Eda, kind: 'sch' | 'pcb', params: Record<string, unknown>) {
  const api = kind === 'pcb' ? 'pcb_PrimitiveComponent' : 'sch_PrimitiveComponent';
  const label = kind === 'pcb' ? 'PCB' : 'schematic';
  const components: Array<{ primitiveId: string; [key: string]: unknown }> = [];

  let items: any[] = [];
  try {
    items = (await requireFn(eda, `${api}.getAll`)()) ?? [];
  } catch (error) {
    if (isActionError(error)) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `cannot read ${label} components: ${error.message}`,
        { kind },
      );
    }
    throw error;
  }

  const unreadable: string[] = [];
  const readErrors: string[] = [];
  for (const item of items) {
    let fields: Record<string, unknown>;
    try {
      fields = await snapshot(item, 40, readErrors);
    } catch (error) {
      // One exotic primitive must not cost the whole readback: report it as a
      // row the caller can see, the same rule the geometry dump follows.
      unreadable.push(String((error as Error)?.message ?? error));
      continue;
    }
    components.push({
      primitiveId: String(fields.PrimitiveId ?? ''),
      designator: fields.Designator ?? null,
      name: fields.Name ?? null,
      footprint: fields.Footprint ?? null,
      supplier: fields.Supplier ?? null,
      supplierId: fields.SupplierId ?? null,
      manufacturer: fields.Manufacturer ?? null,
      x: fields.X ?? null,
      y: fields.Y ?? null,
      rotation: fields.Rotation ?? null,
      ...(kind === 'sch' ? { net: fields.Net ?? null } : { layer: fields.Layer ?? null }),
      fields,
    });
  }

  // Primitives beyond components are the part of the review that needs the
  // copper/wire layer. They are opt-in because they are the expensive call.
  let primitives: unknown[] = [];
  if (params.includePrimitives) {
    primitives = await readOtherPrimitives(eda, kind);
  }

  return {
    kind, components, primitives,
    componentCount: components.length,
    ...(unreadable.length || readErrors.length
      ? {
          unreadable: unreadable.length + readErrors.length,
          reason: unreadable[0] ?? readErrors[0],
        }
      : {}),
  };
}

/**
 * Read the non-component primitives of the open document.
 *
 * Which namespaces exist differs between schematic and PCB, so each is tried
 * in turn and the ones that are missing are reported rather than thrown.
 */
async function readOtherPrimitives(eda: Eda, kind: 'sch' | 'pcb') {
  const namespaces =
    kind === 'pcb'
      ? ['pcb_PrimitivePad', 'pcb_PrimitiveLine', 'pcb_PrimitiveVia', 'pcb_PrimitiveArc',
         'pcb_PrimitiveFill', 'pcb_PrimitivePour', 'pcb_PrimitiveRegion', 'pcb_PrimitiveString']
      : ['sch_PrimitiveWire', 'sch_PrimitiveBus', 'sch_PrimitivePin', 'sch_PrimitiveNetLabel' as string,
         'sch_PrimitiveText', 'sch_PrimitiveCircle', 'sch_PrimitiveRectangle'];

  const out: unknown[] = [];
  const unavailable: string[] = [];
  for (const ns of namespaces) {
    const getAll = (eda as any)?.[ns]?.getAll;
    if (typeof getAll !== 'function') {
      unavailable.push(ns);
      continue;
    }
    let items: any[] = [];
    try {
      items = (await getAll.call((eda as any)[ns])) ?? [];
    } catch {
      unavailable.push(ns);
      continue;
    }
    for (const item of items) {
      const fields = await snapshot(item);
      out.push({ namespace: ns, primitiveId: String(fields.PrimitiveId ?? ''), fields });
    }
  }
  return [{ __meta: { unavailable, returned: out.length } }, ...out];
}

/**
 * `lib.symbol.get` — one library symbol, dumped whole (read-only).
 *
 * A recon action, and the only honest way to answer "does the *library* path
 * expose pin geometry?". Every other route was measured dead on this host
 * (2026-09-14): `sch_PrimitivePin.getAll()` is empty on a schematic page, a
 * component's `Symbol` state is `{}`, and the netlist carries no coordinates.
 * But that only rules out the *canvas* path — nobody had ever looked at the
 * library path, and "we could not find it" is not evidence that it is absent.
 *
 * So: call `lib_Symbol.get` and return whatever comes back, deep-dumped and
 * guarded. If the answer has pins in it, F3 becomes possible; if it does not,
 * we can finally say so with a measurement instead of an inference.
 */
export const libSymbolGet: ActionHandler = async (params, eda) => {
  const uuid = typeof params?.uuid === 'string' ? params.uuid.trim() : '';
  if (!uuid) {
    throw new ActionError('BAD_REQUEST', 'lib.symbol.get needs a uuid');
  }
  const libraryUuid = typeof params?.libraryUuid === 'string' && params.libraryUuid
    ? params.libraryUuid
    : undefined;

  const nsRead = readMember(eda, 'lib_Symbol');
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Symbol is not available in this editor version (${nsRead.error ?? 'absent'})`,
      { path: 'lib_Symbol' },
    );
  }
  const getRead = readMember(ns, 'get');
  const get = getRead.value;
  if (typeof get !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Symbol.get is not available (${getRead.error ?? 'not a function'})`,
      { path: 'lib_Symbol.get' },
    );
  }

  const errors: string[] = [];
  let item: any;
  try {
    item = await settle(get.call(ns, uuid, libraryUuid));
  } catch (error) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `lib_Symbol.get(${uuid}) threw: ${String((error as Error)?.message ?? error)}`,
      { uuid, libraryUuid: libraryUuid ?? null },
    );
  }
  const dumped = item === undefined || item === null
    ? null
    : await deepDump(item, 0, 6, 512, errors);
  return {
    uuid,
    libraryUuid: libraryUuid ?? null,
    found: item !== undefined && item !== null,
    item: dumped,
    ...(errors.length ? { readErrors: errors } : {}),
  };
};

/**
 * `lib.device.get` — one library device, dumped whole (read-only).
 *
 * The second half of the geometry recon: `lib_Symbol.get` needs a *library*
 * symbol uuid, and the only way to obtain one for a device is
 * `lib_Device.get(...).association.symbol` — the netlist's `Symbol` property
 * is a project-local document uuid, measured 2026-09-14 (`lib_Symbol.get` on
 * it answered `found: false` both with and without the library uuid).
 */
export const libDeviceGet: ActionHandler = async (params, eda) => {
  const uuid = typeof params?.uuid === 'string' ? params.uuid.trim() : '';
  if (!uuid) {
    throw new ActionError('BAD_REQUEST', 'lib.device.get needs a uuid');
  }
  const libraryUuid = typeof params?.libraryUuid === 'string' && params.libraryUuid
    ? params.libraryUuid
    : undefined;

  const nsRead = readMember(eda, 'lib_Device');
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Device is not available in this editor version (${nsRead.error ?? 'absent'})`,
      { path: 'lib_Device' },
    );
  }
  const getRead = readMember(ns, 'get');
  const get = getRead.value;
  if (typeof get !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Device.get is not available (${getRead.error ?? 'not a function'})`,
      { path: 'lib_Device.get' },
    );
  }

  const errors: string[] = [];
  let item: any;
  try {
    item = await settle(get.call(ns, uuid, libraryUuid));
  } catch (error) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `lib_Device.get(${uuid}) threw: ${String((error as Error)?.message ?? error)}`,
      { uuid, libraryUuid: libraryUuid ?? null },
    );
  }
  const dumped = item === undefined || item === null
    ? null
    : await deepDump(item, 0, 6, 512, errors);
  return {
    uuid,
    libraryUuid: libraryUuid ?? null,
    found: item !== undefined && item !== null,
    item: dumped,
    ...(errors.length ? { readErrors: errors } : {}),
  };
};

/**
 * `sch.component_pins` — the placed pins of one component, with geometry.
 *
 * This is the **seventh path** to a pin that the six-path table had missed,
 * and the one that decides whether F3 is implementable: the type package
 * declares `SCH_PrimitiveComponent.getAllPinsByPrimitiveId(primitiveId)`
 * returning "器件引脚图元" (`ISCH_PrimitiveComponentPin`) — x/y/pinNumber/
 * pinName/rotation/pinLength for the pins of a *placed* component, `@beta`
 * with no "ADD since v4" marker. Read-only by design: the whole point is to
 * measure the host without touching the page.
 */
export const schComponentPins: ActionHandler = async (params, eda) => {
  const primitiveId = typeof params?.primitiveId === 'string'
    ? params.primitiveId.trim()
    : '';
  if (!primitiveId) {
    throw new ActionError('BAD_REQUEST', 'sch.component_pins needs a primitiveId');
  }
  const errors: string[] = [];

  const nsRead = readMember(eda, 'sch_PrimitiveComponent');
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `sch_PrimitiveComponent is not available (${nsRead.error ?? 'absent'})`,
      { path: 'sch_PrimitiveComponent' },
    );
  }
  const fnRead = readMember(ns, 'getAllPinsByPrimitiveId');
  const getAllPins = fnRead.value;
  if (typeof getAllPins !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `sch_PrimitiveComponent.getAllPinsByPrimitiveId is not available `
        + `(${fnRead.error ?? 'not a function'})`,
      { path: 'sch_PrimitiveComponent.getAllPinsByPrimitiveId' },
    );
  }

  let pins: any;
  try {
    pins = await settle(getAllPins.call(ns, primitiveId));
  } catch (error) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `getAllPinsByPrimitiveId(${primitiveId}) threw: `
        + `${String((error as Error)?.message ?? error)}`,
      { primitiveId },
    );
  }
  const list = Array.isArray(pins) ? pins : [];
  const out: unknown[] = [];
  // The accessors the type package declares for 器件引脚图元. Read first, then
  // **called** — a plain member read only proves the method exists, it does
  // not hand over the coordinate (probes must be as strong as the conclusion).
  const ACCESSORS = [
    'getState_X', 'getState_Y', 'getState_PinNumber', 'getState_PinName',
    'getState_Rotation', 'getState_PinLength', 'getState_PrimitiveId',
    'getState_NoConnected', 'getState_PinType',
  ] as const;
  for (const pin of list) {
    const row: Record<string, unknown> = {};
    for (const accessor of ACCESSORS) {
      const member = readMember(pin, accessor);
      if (member.error !== undefined) {
        errors.push(`${accessor}: ${member.error}`);
        continue;
      }
      if (typeof member.value !== 'function') continue;
      try {
        row[accessor.replace(/^getState_/, '')] =
          await settle((member.value as () => unknown).call(pin));
      } catch (error) {
        errors.push(`call ${accessor}: ${String((error as Error)?.message ?? error)}`);
      }
    }
    out.push(row);
  }
  return {
    primitiveId,
    declared: 'SCH_PrimitiveComponent.getAllPinsByPrimitiveId',
    returned: list.length,
    pins: out,
    ...(pins === undefined ? { note: 'the host answered undefined' } : {}),
    ...(errors.length ? { readErrors: errors } : {}),
  };
};

/**
 * `lib.footprint.get` — one library footprint, dumped whole (read-only).
 *
 * The instrument §G asks for twice over: it turns the netlist's footprint
 * *uuid* back into the package name the diff needs to compare like for like,
 * and it is how R24/R27's replacement is verified — "is the placed part really
 * 0402?" is answered by reading this name, not by trusting the keyword search.
 */
export const libFootprintGet: ActionHandler = async (params, eda) => {
  const uuid = typeof params?.uuid === 'string' ? params.uuid.trim() : '';
  if (!uuid) {
    throw new ActionError('BAD_REQUEST', 'lib.footprint.get needs a uuid');
  }
  const libraryUuid = typeof params?.libraryUuid === 'string' && params.libraryUuid
    ? params.libraryUuid
    : undefined;
  const errors: string[] = [];
  const nsRead = readMember(eda, 'lib_Footprint');
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Footprint is not available (${nsRead.error ?? 'absent'})`,
      { path: 'lib_Footprint' },
    );
  }
  const getRead = readMember(ns, 'get');
  const get = getRead.value;
  if (typeof get !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Footprint.get is not available (${getRead.error ?? 'not a function'})`,
      { path: 'lib_Footprint.get' },
    );
  }
  let item: any;
  try {
    item = await settle(get.call(ns, uuid, libraryUuid));
  } catch (error) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `lib_Footprint.get(${uuid}) threw: ${String((error as Error)?.message ?? error)}`,
      { uuid },
    );
  }
  const dumped = item === undefined || item === null
    ? null
    : await deepDump(item, 0, 4, 512, errors);
  const name = dumped && typeof dumped === 'object'
    ? String((dumped as Record<string, unknown>).name ?? '')
    : '';
  return {
    uuid,
    libraryUuid: libraryUuid ?? null,
    found: item !== undefined && item !== null,
    name,
    item: dumped,
    ...(errors.length ? { readErrors: errors } : {}),
  };
};

/**
 * `sch.set_component_attribute` — write schematic attributes on a placed
 * component (`Value`, `Supplier Footprint`, …), in **one** call, then read
 * them back.
 *
 * Two measurements shape this action.
 *
 * 1. `modify`'s `otherProperty` is a **whole-map replacement, not a merge**:
 *    writing `Value` and then `Supplier Footprint` in two calls leaves only
 *    the second key alive (measured 2026-09-15 on C1 — the footprint landed,
 *    the value came back empty, and the next write wiped the footprint
 *    again). So the current map is read first, merged, and written once.
 * 2. `modify`'s return value is not evidence that anything took: the action
 *    re-reads `getState_OtherProperty()` afterwards and defines `applied` as
 *    "the read-back equals the target", key by key. Without that read-back
 *    the first defect would have stayed invisible.
 *
 * There is no schematic attribute namespace on this host (only `pcb_*`), so
 * `otherProperty` is the only channel.
 */
export const schSetComponentAttribute: ActionHandler = async (params, eda) => {
  await guardPage(eda, params.pageUuid);
  const primitiveId = typeof params?.primitiveId === 'string'
    ? params.primitiveId.trim()
    : '';
  if (!primitiveId) {
    throw new ActionError('BAD_REQUEST', 'sch.set_component_attribute needs a primitiveId');
  }
  // Accept either a map or a single key/value pair (the pair form stays for
  // one-off probes; the draw flow always sends the whole map).
  const target: Record<string, string> = {};
  const map = params?.attributes;
  if (map && typeof map === 'object' && !Array.isArray(map)) {
    for (const [key, value] of Object.entries(map as Record<string, unknown>)) {
      if (typeof value === 'string' && value) target[key] = value;
    }
  }
  const key = typeof params?.key === 'string' && params.key.trim()
    ? params.key.trim()
    : 'Value';
  if (typeof params?.value === 'string' && params.value) target[key] = params.value;
  if (Object.keys(target).length === 0) {
    throw new ActionError(
      'BAD_REQUEST',
      'sch.set_component_attribute needs attributes{}, or a non-empty key/value',
    );
  }

  const nsRead = readMember(eda, 'sch_PrimitiveComponent');
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `sch_PrimitiveComponent is not available (${nsRead.error ?? 'absent'})`,
      { path: 'sch_PrimitiveComponent' },
    );
  }
  const modify = readMember(ns, 'modify').value;
  if (typeof modify !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'sch_PrimitiveComponent.modify is not available',
      { path: 'sch_PrimitiveComponent.modify' },
    );
  }

  const readBack = async (label: string) => {
    const get = readMember(ns, 'get').value;
    if (typeof get !== 'function') return { map: null as Record<string, unknown> | null, why: `${label}: ${'sch_PrimitiveComponent.get'} is unavailable` };
    let component: any;
    try {
      component = await settle(get.call(ns, primitiveId));
    } catch (error) {
      return { map: null, why: `${label}: get threw ${String((error as Error)?.message ?? error)}` };
    }
    if (!component) return { map: null, why: `${label}: the host returned no component` };
    const member = readMember(component, 'getState_OtherProperty');
    if (typeof member.value !== 'function') {
      return { map: null, why: `${label}: getState_OtherProperty is unavailable` };
    }
    try {
      const current = await settle((member.value as () => unknown).call(component));
      return {
        map: current && typeof current === 'object'
          ? { ...(current as Record<string, unknown>) }
          : {},
        why: '',
      };
    } catch (error) {
      return { map: null, why: `${label}: read threw ${String((error as Error)?.message ?? error)}` };
    }
  };

  const before = await readBack('before');
  const merged: Record<string, unknown> = { ...(before.map ?? {}), ...target };
  let wrote = false;
  let writeError = '';
  try {
    const result: any = await settle(modify.call(ns, primitiveId, { otherProperty: merged }));
    wrote = result !== undefined && result !== null;
  } catch (error) {
    writeError = String((error as Error)?.message ?? error);
  }

  const after = await readBack('after');
  const mismatched = Object.entries(target)
    .filter(([k, v]) => after.map === null || String(after.map[k] ?? '') !== v)
    .map(([k, v]) => `${k}: wanted ${JSON.stringify(v)}, read ${JSON.stringify(after.map?.[k] ?? null)}`);
  const survived = before.map === null
    ? []
    : Object.keys(before.map).filter(
      (k) => !(k in target) && String(after.map?.[k] ?? '') !== String(before.map?.[k] ?? ''),
    );

  return {
    primitiveId,
    attributes: target,
    mergedKeys: Object.keys(merged).sort(),
    applied: wrote && mismatched.length === 0,
    wrote,
    otherPropertyBefore: before.map,
    otherPropertyAfter: after.map,
    ...(before.why ? { readBackBefore: before.why } : {}),
    ...(after.why ? { readBackAfter: after.why } : {}),
    ...(writeError ? { writeError } : {}),
    ...(mismatched.length ? { mismatched } : {}),
    ...(survived.length ? { clobberedOtherKeys: survived } : {}),
  };
};

/**
 * `lib.device.search` — keyword candidates, each dumped (read-only).
 *
 * §G requires R24/R27's replacement to be a *real* 0402 part and U3's to be
 * 2.2kΩ 0805, verified rather than assumed. A search item carries
 * `footprintName`, `footprintUuid` and `supplierId`, so "which of these hits
 * is 0402?" is answered by reading the item — the placement then goes through
 * the explicit uuid pair instead of a keyword whose first hit was wrong
 * (measured 2026-09-15: "5.1K 0402" led with TCH35P5K10JE, not a 0402).
 */
export const libDeviceSearch: ActionHandler = async (params, eda) => {
  const keyword = typeof params?.keyword === 'string' ? params.keyword.trim() : '';
  if (!keyword) {
    throw new ActionError('BAD_REQUEST', 'lib.device.search needs a keyword');
  }
  const limit = Number.isFinite(Number(params?.limit)) ? Number(params.limit) : 8;
  const errors: string[] = [];
  const nsRead = readMember(eda, 'lib_Device');
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Device is not available (${nsRead.error ?? 'absent'})`,
      { path: 'lib_Device' },
    );
  }
  const searchRead = readMember(ns, 'search');
  const search = searchRead.value;
  if (typeof search !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Device.search is not available (${searchRead.error ?? 'not a function'})`,
      { path: 'lib_Device.search' },
    );
  }
  let found: any;
  try {
    found = await settle(search.call(ns, keyword));
  } catch (error) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `lib_Device.search(${keyword}) threw: ${String((error as Error)?.message ?? error)}`,
      { keyword },
    );
  }
  const list = Array.isArray(found) ? found : [];
  const items: unknown[] = [];
  for (const item of list.slice(0, Math.max(0, limit))) {
    items.push(await deepDump(item, 0, 4, 256, errors));
  }
  return {
    keyword,
    returned: list.length,
    shown: items.length,
    items,
    ...(errors.length ? { readErrors: errors } : {}),
  };
};

export const schReadback: ActionHandler = (params, eda) => readback(eda, 'sch', params);
export const pcbReadback: ActionHandler = (params, eda) => readback(eda, 'pcb', params);

/**
 * `export.screenshot` — native canvas capture, returned as base64 PNG.
 *
 * Uses `dmt_EditorControl.getCurrentRenderedAreaImage()`, the API that returns
 * the rendered canvas as a `Blob` — exactly what a review screenshot is. The
 * document-render path lives in `export.render` (`getExportDocumentFile`);
 * this one is the *viewport*, so a backgrounded tab can hand back a stale
 * frame — diagnostic only, never evidence.
 */
export const exportScreenshot: ActionHandler = async (params, eda) => {
  const control = namespaceOf(eda, 'dmt_EditorControl');
  const capture = control.getCurrentRenderedAreaImage;
  if (typeof capture !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'dmt_EditorControl.getCurrentRenderedAreaImage() is not available',
      { path: 'dmt_EditorControl.getCurrentRenderedAreaImage' },
    );
  }
  if (params.fit) {
    const zoomToAll = control.zoomToAllPrimitives;
    if (typeof zoomToAll === 'function') {
      await settle(zoomToAll.call(control));
    }
  }
  const blob: Blob | undefined = await settle(capture.call(control));
  if (!blob) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'the editor returned no image; is a document open and focused?',
    );
  }
  const buffer = new Uint8Array(await blob.arrayBuffer());
  return {
    format: blob.type || 'image/png',
    encoding: 'base64',
    bytes: buffer.byteLength,
    data: bytesToBase64(buffer),
  };
};

/**
 * `canvas.highlight` — mark primitives on the live canvas.
 *
 * The official marker API (`generateIndicatorMarkers`) takes *shapes*, not
 * uuids, so a uuid has to be resolved to coordinates first. Component uuids
 * are resolved here; anything else is reported back in `unresolved` rather
 * than silently ignored. Marker coordinates are canvas units: mil on PCB,
 * 0.01 inch on schematic (per the API remarks).
 *
 * Field names matter and are *not* uniform across shapes: a rectangle takes
 * `left/right/top/bottom`, while `startX/startY/endX/endY` belong to lines
 * and arcs (`IDMT_IndicatorMarkerShape`). Sending line fields for a
 * rectangle is accepted silently (the call still returns `true`) but
 * renders nothing — that exact bug shipped in 0.1.2 and was only caught on
 * a real editor. Keep the test assertions on the field names.
 */
export const canvasHighlight: ActionHandler = async (params, eda) => {
  const uuids = Array.isArray(params.uuids) ? (params.uuids as string[]) : [];
  if (uuids.length === 0) {
    throw new ActionError('BAD_REQUEST', 'canvas.highlight needs params.uuids');
  }
  const control = namespaceOf(eda, 'dmt_EditorControl');

  if (params.clear) {
    const remove = control.removeIndicatorMarkers;
    if (typeof remove !== 'function') {
      throw new ActionError(
        'NOT_IMPLEMENTED',
        'dmt_EditorControl.removeIndicatorMarkers() is not available',
        { path: 'dmt_EditorControl.removeIndicatorMarkers' },
      );
    }
    const ok = await settle(remove.call(control));
    return { cleared: Boolean(ok), highlighted: 0, unresolved: [] };
  }

  const generate = control.generateIndicatorMarkers;
  if (typeof generate !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'dmt_EditorControl.generateIndicatorMarkers() is not available',
      { path: 'dmt_EditorControl.generateIndicatorMarkers' },
    );
  }

  const color = parseColor(params.color) ?? DEFAULT_MARKER_COLOR;
  const markers: Array<Record<string, unknown>> = [];
  const unresolved: string[] = [];

  for (const uuid of uuids) {
    const point = await locate(eda, uuid);
    if (!point) {
      unresolved.push(uuid);
      continue;
    }
    const size = 60; // canvas units — visible on both mil and 0.01in canvases
    markers.push({
      type: 'rectangle',
      left: point.x - size,
      right: point.x + size,
      top: point.y + size,
      bottom: point.y - size,
    });
  }

  if (markers.length === 0) {
    return { highlighted: 0, cleared: false, unresolved };
  }
  const ok = await settle(
    generate.call(control, markers, color, 2, params.zoom === true),
  );
  if (!ok) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'the canvas refused the markers (unsupported canvas or unknown tab)',
      { attempted: markers.length },
    );
  }
  return { highlighted: markers.length, cleared: false, unresolved };
};

/** Resolve a primitive uuid to a canvas coordinate, or `undefined`. */
async function locate(
  eda: Eda,
  uuid: string,
): Promise<{ x: number; y: number } | undefined> {
  const candidates = [
    'pcb_PrimitiveComponent',
    'sch_PrimitiveComponent',
    'pcb_PrimitivePad',
    'pcb_PrimitiveVia',
    'pcb_PrimitiveLine',
    'pcb_PrimitiveFill',
    'pcb_PrimitivePour',
    'sch_PrimitiveWire',
    'sch_PrimitivePin',
  ];
  for (const ns of candidates) {
    const get = (eda as any)?.[ns]?.get;
    if (typeof get !== 'function') continue;
    let item: any;
    try {
      item = await settle(get.call((eda as any)[ns], uuid));
    } catch {
      continue;
    }
    if (!item || Array.isArray(item)) continue;
    const x = await getState(item, 'X');
    const y = await getState(item, 'Y');
    if (typeof x === 'number' && typeof y === 'number') return { x, y };
    // Lines and arcs do not have X/Y; fall back to their start point.
    const sx = await getState(item, 'StartX');
    const sy = await getState(item, 'StartY');
    if (typeof sx === 'number' && typeof sy === 'number') return { x: sx, y: sy };
  }
  return undefined;
}

/** Accept `#RRGGBB`, `#RRGGBBAA` or an `{r,g,b,alpha}` object. */
function parseColor(value: unknown): MarkerColor | undefined {
  if (!value) return undefined;
  if (typeof value === 'object') {
    const candidate = value as Partial<MarkerColor>;
    if (
      typeof candidate.r === 'number' &&
      typeof candidate.g === 'number' &&
      typeof candidate.b === 'number'
    ) {
      return {
        r: candidate.r,
        g: candidate.g,
        b: candidate.b,
        alpha: candidate.alpha ?? 255,
      };
    }
    return undefined;
  }
  if (typeof value !== 'string') return undefined;
  const hex = value.replace(/^#/, '');
  if (!/^[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/.test(hex)) return undefined;
  return {
    r: parseInt(hex.slice(0, 2), 16),
    g: parseInt(hex.slice(2, 4), 16),
    b: parseInt(hex.slice(4, 6), 16),
    alpha: hex.length === 8 ? parseInt(hex.slice(6, 8), 16) : 255,
  };
}

/** A handler bound to one editor instance. */
export type BoundHandler = (params: Record<string, unknown>) => Promise<unknown>;

// --------------------------------------------------------------------------
// 006b: read-only introspection
// --------------------------------------------------------------------------

/**
 * The `checks` half of `sys.probe`: verify *named* members with a plain read.
 *
 * Enumeration is a measurement that can fail on the object it is measuring —
 * the 2026-09-14 probe died on the real editor because the host hands out
 * exotic objects that throw from `getPrototypeOf`/`getOwnPropertyNames`.
 * `typeof ns[name]` has no such failure mode: property access walks the
 * prototype chain as part of the language, so a member declared on a
 * grandparent prototype comes back as its real type and nothing has to be
 * enumerated to find it.
 *
 * The candidate names are not guessed here; they come from the offline type
 * package via `tools/api_names.py`, which makes this check *complete* for the
 * declared surface. The report deliberately uses the same three words as
 * `typeof` — `function` / `object` / `undefined` — plus `threw`, because
 * "undeclared" and "the read itself failed" must never collapse into one.
 *
 * @param checks  `{namespace: [memberName, …]}` as received from the caller.
 * @param eda     The context-global host object.
 */
function probeChecks(checks: Record<string, unknown>, eda: any): Record<string, unknown> {
  const report: Record<string, unknown> = {};
  for (const [namespace, requested] of Object.entries(checks)) {
    if (!Array.isArray(requested)) {
      report[namespace] = { error: 'expected an array of member names' };
      continue;
    }
    const ns = (() => {
      try {
        return (eda as any)?.[namespace];
      } catch (error) {
        return { __readError: String((error as Error)?.message ?? error) };
      }
    })();
    if (ns && typeof ns === 'object' && '__readError' in (ns as object)) {
      report[namespace] = {
        present: false,
        error: (ns as { __readError: string }).__readError,
      };
      continue;
    }
    const present = !!ns && (typeof ns === 'object' || typeof ns === 'function');

    const status: Record<string, string> = {};
    const notes: Record<string, string> = {};
    let missing = 0;
    for (const raw of requested) {
      const member = String(raw);
      if (!present) {
        status[member] = 'namespace-absent';
        missing += 1;
        continue;
      }
      const since = ADDED_SINCE[namespace]?.[member];
      try {
        // The whole point: a plain property read. No enumeration, no
        // `getPrototypeOf`, nothing an exotic host object can break.
        const value = ns[member];
        status[member] = typeof value;
        if (value === undefined) {
          missing += 1;
          // A declared `ADD since …` method answering `undefined` is the
          // interesting case: the claim is falsifiable, and the report should
          // carry it rather than leave the reader to cross-reference.
          if (since) notes[member] = `declared ADD since ${since} on this host`;
        }
      } catch (error) {
        status[member] = `threw: ${String((error as Error)?.message ?? error)}`;
        missing += 1;
      }
    }

    report[namespace] = {
      present,
      kind: typeof ns,
      checked: requested.length,
      missing,
      status,
      ...(Object.keys(notes).length ? { notes } : {}),
    };
  }
  return report;
}

/**
 * `sys.probe` — enumerate what the editor's API actually exposes, right now.
 *
 * This exists because "the type package declares it" and "the running editor
 * has it" turned out to be different statements. `sch_ManufactureData.getPngFile`
 * is documented as *added in EDA v3.2.183* and the host reports **3.2.186**, yet
 * the method is absent at runtime (`export.render` throws `NOT_IMPLEMENTED`).
 * A `typeof` check alone only proves *one* method is missing and cannot say
 * whether the namespace exists at all, whether a rename happened, or whether
 * the whole build is a downgrade — so this action enumerates the *real* member
 * names and returns them as data for a human to read.
 *
 * Two modes, because enumeration itself proved fragile:
 *
 * - **`checks`** (preferred): `{"checks": {"<namespace>": ["methodA", …]}}`.
 *   Each name is read with a plain property access, `typeof ns[name]`, which
 *   walks the prototype chain *by construction* — no enumeration, so no
 *   `getOwnPropertyNames`/`getPrototypeOf` call to throw on an exotic host
 *   object. The candidate names come from the offline type package
 *   (`tools/api_names.py`), so this is the *complete* set, not a sample.
 *   This is what a host that crashes the enumerator can still answer.
 * - **enumerate** (fallback): `namespace` / `namespaces` / `functionsOnly`.
 *   Kept because it can find a name nobody predicted — a capability the type
 *   package cannot provide. A throwing level costs one report line, never the
 *   whole answer.
 *
 * Purely read-only: it calls nothing. Every branch records its own outcome, so
 * an empty answer is distinguishable from a failed one.
 *
 * Params:
 * - `checks` (object, optional): `{namespace: [methodName, …]}` — the exact
 *   list to verify. Presence of this key selects the `checks` mode.
 * - `namespace` (string, optional): one namespace to enumerate (default
 *   `sch_ManufactureData`). May be given as `namespaces` (string[]) to do
 *   several at once.
 * - `functionsOnly` (boolean, optional, default `false`): keep only function
 *   members. Off by default so a renamed data field is not hidden.
 */
export const sysProbe: ActionHandler = async (params, eda) => {
  const version = (() => {
    try {
      return String((eda as any)?.sys_Environment?.getEditorCurrentVersion?.(true) ?? '');
    } catch {
      return '';
    }
  })();

  // Enumerating the top level is itself the measurement: `eda` is a *context
  // global*, not a `globalThis` property, and this list is the only direct
  // evidence of how many namespaces the host actually binds.
  const topLevel: string[] = (() => {
    try {
      const names = Object.getOwnPropertyNames(eda ?? {});
      for (const key of ['eda', 'globalThis', 'window', 'self']) {
        if (!names.includes(key)) names.push(key);
      }
      return [...new Set(names)].sort();
    } catch {
      return [];
    }
  })();

  if (params?.checks) {
    // `checks: true` (or an empty object) means "use the offline table" —
    // the names the type package declares for the namespaces the roadmap
    // depends on. An explicit object overrides it name by name.
    const requested: Record<string, unknown> =
      params.checks === true || (typeof params.checks === 'object'
        && Object.keys(params.checks).length === 0)
        ? { ...PROBE_CHECKS }
        : { ...(params.checks as Record<string, unknown>) };
    return { version, connector: VERSION, topLevel, checks: probeChecks(requested, eda) };
  }

  const namespaces: string[] = Array.isArray(params?.namespaces)
    ? (params.namespaces as unknown[]).map((v) => String(v)).filter(Boolean)
    : [String(params?.namespace ?? 'sch_ManufactureData')];
  const functionsOnly = params?.functionsOnly === true;

  const detail: Record<string, unknown> = {};
  for (const name of namespaces) {
    // Even reading the namespace is a trap invocation on this host — the same
    // reason `probeChecks` wraps it. An unguarded read here killed the *whole*
    // enumeration run on 2026-09-14 while `checks` kept working.
    const nsRead = readMember(eda, name);
    const ns = nsRead.value;
    if (nsRead.error !== undefined) {
      detail[name] = { present: false, error: `read ${name}: ${nsRead.error}` };
      continue;
    }
    const present = !!ns && typeof ns === 'object';
    const members: Record<string, string[]> = { functions: [], data: [] };
    const own: string[] = [];
    const walkErrors: string[] = [];
    if (present) {
      // Namespaces are class instances, so the members live on the prototype
      // (and possibly a prototype chain) — `Object.keys(ns)` alone returned
      // `[]` on 2026-09-14. `walkPrototypeNames` guards every level, because a
      // host *exotic* object can throw from `getPrototypeOf`: the whole first
      // probe run died with "reading 'prototype'" on every namespace, and one
      // bad level must cost one line of the report, never the whole answer.
      own.push(...walkPrototypeNames(ns, (key) => key !== 'constructor', walkErrors));
      for (const key of own) {
        let value: unknown;
        try {
          value = ns[key];
        } catch (error) {
          walkErrors.push(`read ${key}: ${String((error as Error)?.message ?? error)}`);
          continue;
        }
        if (typeof value === 'function') members.functions.push(key);
        else if (!functionsOnly) members.data.push(key);
      }
    }
    members.functions.sort();
    members.data.sort();
    detail[name] = {
      present,
      kind: typeof ns,
      ownNames: own.length,
      functions: members.functions,
      ...(functionsOnly ? {} : { data: members.data }),
      ...(walkErrors.length ? { errors: walkErrors } : {}),
    };
  }

  return { version, connector: VERSION, topLevel, namespaces: detail };
};

// --------------------------------------------------------------------------
// 006: schematic candidate-model reads
// --------------------------------------------------------------------------

/** Valid values of `ESYS_NetlistType`, from `@jlceda/pro-api-types`. */
const NETLIST_TYPES = new Set([
  'Allegro',
  'PADS',
  'Protel2',
  'JLCEDA',
  'EasyEDA',
  'DISA',
  'DSNET',
]);

/**
 * `sch.netlist` — the editor's own netlist export.
 *
 * Primary source is `sch_ManufactureData.getNetlistFile(fileName, type)`,
 * which returns a `File` whose `.text()` is the netlist. The deprecated
 * `sch_Netlist.getNetlist(type)` — which returns the string directly — is the
 * fallback, because `@deprecated` in this API has so far meant "older", not
 * "removed", and the file variant has been seen to resolve `undefined` on
 * pages with nothing placed. Whichever path answers is named in `source` so
 * the daemon-side report can say where its ground truth came from.
 */
export const schNetlist: ActionHandler = async (params, eda) => {
  const type = typeof params.type === 'string' && NETLIST_TYPES.has(params.type)
    ? params.type
    : 'EasyEDA';

  let source = 'getNetlistFile';
  let text: string | undefined;
  try {
    const file: any = await settle(
      requireFn(eda, 'sch_ManufactureData.getNetlistFile')(`boardwise-netlist-${type}`, type),
    );
    if (file && typeof file.text === 'function') {
      text = await settle(file.text());
    }
  } catch (error) {
    // Remember why the primary path failed; the fallback below may still work
    // and the report wants both facts.
    source = `getNetlistFile threw: ${error instanceof Error ? error.message : String(error)}`;
  }

  if (typeof text !== 'string') {
    try {
      text = await settle(requireFn(eda, 'sch_Netlist.getNetlist')(type));
      source = 'getNetlist (fallback)';
    } catch (error) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `both netlist exports failed; primary: ${source}; fallback: ${
          error instanceof Error ? error.message : String(error)
        }`,
        { type },
      );
    }
    if (typeof text !== 'string') {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `both netlist exports returned nothing (primary: ${source})`,
        { type },
      );
    }
  }

  return {
    type,
    source,
    size: text.length,
    text,
  };
};

/**
 * Deep, JSON-safe dump of an editor object's `getState_*` getters.
 *
 * Unlike `snapshot` above — which deliberately truncates arrays to counts for
 * the review readback — geometry *is* the payload here: a wire's polyline is
 * an array and the readback fallback cannot derive connectivity without it.
 * Depth and element limits keep a pathological primitive from flooding the
 * socket, but a real wire (≤ a few hundred numbers) passes whole.
 */
async function deepDump(
  obj: any, depth = 0, maxDepth = 4, maxArray = 512, errors?: string[],
): Promise<unknown> {
  if (obj === null || obj === undefined) return null;
  const t = typeof obj;
  if (t === 'string' || t === 'number' || t === 'boolean') return obj;
  if (t !== 'object' && t !== 'function') return null;
  if (depth >= maxDepth) return { __truncated: true };
  if (Array.isArray(obj)) {
    if (obj.length > maxArray) return { __truncated: true, length: obj.length };
    const out: unknown[] = [];
    for (const item of obj) out.push(await deepDump(item, depth + 1, maxDepth, maxArray, errors));
    return out;
  }
  // `instanceof` invokes `Get(C, "prototype")` and a `[[GetPrototypeOf]]` walk,
  // so on a host where `Blob`/`File` are not bound (or the value is exotic) it
  // throws `…(reading 'prototype')` — the same sentence as the walk bug, from
  // a different place. Guarded, because a blob check must never cost the dump.
  if (blobLike(obj)) return { __blob: (obj as Blob).size ?? null };
  const out: Record<string, unknown> = {};
  const names = new Set<string>();
  for (const name of walkPrototypeNames(obj, (n) => n.startsWith('getState_'), errors)) {
    names.add(name.slice('getState_'.length));
  }
  for (const name of names) {
    const value = await getState(obj, name, errors);
    if (value === undefined) continue;
    out[name] = await deepDump(value, depth + 1, maxDepth, maxArray, errors);
  }
  // The library item objects (`ILIB_DeviceItem`, `ILIB_SymbolItem`) carry
  // their data as **plain properties**, not `getState_*()` accessors — so the
  // walk above finds nothing and the dump reads as `{}` on an object that is
  // full. Measured 2026-09-15: `lib_Device.get` answered `found: true,
  // item: {}` for a device the editor had just placed, which read as "the
  // library path has nothing" when the truth was "our dump cannot see it".
  // Fall back to the object's own keys, every read guarded — same rule as
  // `getState`.
  if (Object.keys(out).length === 0) {
    const own = walkPrototypeNames(obj, (key) => key !== 'constructor', errors)
      .slice(0, 64);
    for (const key of own) {
      const read = readMember(obj, key);
      if (read.error !== undefined) {
        errors?.push(`read ${key}: ${read.error}`);
        continue;
      }
      if (typeof read.value === 'function') {
        // On this host the library/primitive objects keep their data behind
        // `getState_*()` accessors, and when the walk *does* surface them the
        // fallback used to skip them as "just functions" — which is how a pin
        // object full of geometry still read as `{}`. Only `getState_`-named
        // members are invoked: they are pure getters, unlike `create`/`modify`
        // on the same classes, and the fallback only runs while the dump is
        // still empty.
        if (!/^getState_/.test(key)) continue;
        let called: any;
        try {
          called = await settle(read.value.call(obj));
        } catch (error) {
          errors?.push(`call ${key}: ${String((error as Error)?.message ?? error)}`);
          continue;
        }
        if (called === undefined) continue;
        out[key] = await deepDump(called, depth + 1, maxDepth, maxArray, errors);
        continue;
      }
      out[key] = await deepDump(read.value, depth + 1, maxDepth, maxArray, errors);
    }
  }
  return out;
}

/** Is this a Blob/File, without letting a missing global or an exotic `instanceof` throw. */
function blobLike(value: any): boolean {
  try {
    if (typeof Blob !== 'undefined' && value instanceof Blob) return true;
    if (typeof File !== 'undefined' && value instanceof File) return true;
    return false;
  } catch {
    return false;
  }
}

/** One geometry namespace: every primitive, deep-dumped, with its uuid. */
async function geometryOf(eda: Eda, namespace: string) {
  // Every step here can fail on an exotic host object, and each failure must
  // be *named* — a silent `{available:false}` is what made this look like
  // "the page is empty" instead of "the read broke".
  const nsRead = readMember(eda, namespace);
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    return { available: false as const, items: [], reason: `read ${namespace}: ${nsRead.error ?? 'absent'}` };
  }
  const getAllRead = readMember(ns, 'getAll');
  const getAll = getAllRead.value;
  if (typeof getAll !== 'function') {
    return { available: false as const, items: [], reason: `read ${namespace}.getAll: ${getAllRead.error ?? 'not a function'}` };
  }
  let items: any[] = [];
  try {
    items = (await settle(getAll.call(ns))) ?? [];
  } catch (error) {
    return { available: false as const, items: [], reason: `call ${namespace}.getAll(): ${String((error as Error)?.message ?? error)}` };
  }
  const out: unknown[] = [];
  const failures: string[] = [];
  const readErrors: string[] = [];
  for (const item of items) {
    try {
      const uuid = await getState(item, 'PrimitiveId', readErrors);
      out.push({
        primitiveId: uuid == null ? null : String(uuid),
        state: await deepDump(item, 0, 4, 512, readErrors),
      });
    } catch (error) {
      // one unreadable primitive must not cost the whole dump
      failures.push(String((error as Error)?.message ?? error));
    }
  }
  const problems = [
    ...failures.map((f) => `primitive skipped: ${f}`),
    ...readErrors,
  ];
  return {
    available: true as const,
    items: out,
    ...(problems.length
      ? { reason: `${problems.length} read(s) failed; first: ${problems[0]}` }
      : {}),
  };
}

/**
 * `sch.geometry` — full geometry of the open schematic page.
 *
 * Components, wires, pins and net labels are dumped raw, plus the **measured**
 * bounding boxes of the sheet primitives (`getPrimitivesBBox` — the only way
 * to learn where the drawing frame actually is: the sheet's `getState_*`
 * fields carry an anchor, not an extent, so `Width`/`Height` would otherwise
 * have to be trusted from the file). Callers may pass `bboxIds` to measure
 * more primitives, one `getPrimitivesBBox` call each — the API returns a
 * single union box for a list, so a per-id answer costs a call per id.
 *
 * Which `getState_*` fields exist (a pin's designator linkage, a wire's
 * polyline field name) is exactly what the machine run is meant to measure —
 * the Python side consumes this tolerantly and the probe report records what
 * came back.
 */
export const schGeometry: ActionHandler = async (params, eda) => {
  const components = await geometryOf(eda, 'sch_PrimitiveComponent');
  const wires = await geometryOf(eda, 'sch_PrimitiveWire');
  const pins = await geometryOf(eda, 'sch_PrimitivePin');
  const netlabels = await geometryOf(eda, 'sch_PrimitiveNetLabel');

  const sheetIds: string[] = [];
  for (const item of components.items as Array<Record<string, unknown>>) {
    const state = (item.state ?? {}) as Record<string, unknown>;
    if (String(state.ComponentType ?? '') === 'sheet' && item.primitiveId) {
      sheetIds.push(String(item.primitiveId));
    }
  }
  const requested = Array.isArray(params?.bboxIds)
    ? (params.bboxIds as unknown[]).map((v) => String(v)).filter(Boolean)
    : [];
  const wanted = [...new Set([...sheetIds, ...requested])];
  const primitiveApi = (eda as any)?.sch_Primitive;
  const bboxFn = primitiveApi?.getPrimitivesBBox;
  const bboxes: Record<string, unknown> = {};
  let bboxAvailable = false;
  if (typeof bboxFn === 'function' && wanted.length) {
    bboxAvailable = true;
    for (const id of wanted) {
      try {
        const box: any = await settle(bboxFn.call(primitiveApi, [id]));
        if (box) {
          bboxes[id] = {
            minX: box.minX,
            minY: box.minY,
            maxX: box.maxX,
            maxY: box.maxY,
          };
        }
      } catch {
        // one unmeasurable primitive must not lose the rest of the dump
      }
    }
  }

  const reasons: Record<string, string> = {};
  for (const [label, part] of [
    ['components', components], ['wires', wires],
    ['pins', pins], ['netlabels', netlabels],
  ] as const) {
    if ((part as { reason?: string }).reason) {
      reasons[label] = (part as { reason?: string }).reason as string;
    }
  }

  return {
    components: components.items,
    wires: wires.items,
    pins: pins.items,
    netlabels: netlabels.items,
    bboxes,
    meta: {
      available: {
        components: components.available,
        wires: wires.available,
        pins: pins.available,
        netlabels: netlabels.available,
        bboxes: bboxAvailable,
      },
      sheets: sheetIds,
      // Why a namespace came back empty, when it did. Without this,
      // "the page is blank" and "the read broke" look identical.
      ...(Object.keys(reasons).length ? { reasons } : {}),
    },
  };
};

// --------------------------------------------------------------------------
// 006: schematic write actions
// --------------------------------------------------------------------------

/** Two decimals is well past the precision any schematic coordinate needs. */
function toCoord(value: unknown, label: string): number {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    throw new ActionError('BAD_REQUEST', `params.${label} must be a finite number`);
  }
  return Math.round(n * 100) / 100;
}

/**
 * Refuse to mutate unless the *focused* page is the expected one.
 *
 * The `eda.*` placement APIs anchor to whatever tab is in the foreground,
 * so a stale focus would silently draw onto the user's open design. The
 * draw flow therefore stamps every write with the `pageUuid` it created
 * (`sch.doc.new` focuses it) and each write verifies before touching
 * anything. Callers that omit `pageUuid` — interactive probes — get no
 * guard, which the docs call out as user responsibility.
 */
async function guardPage(eda: Eda, expected: unknown): Promise<void> {
  if (typeof expected !== 'string' || !expected) return;
  const current: any = await settle(
    requireFn(eda, 'dmt_Schematic.getCurrentSchematicPageInfo')(),
  );
  const uuid = plainGet(current, 'uuid');
  if (uuid !== expected) {
    throw new ActionError(
      'PAGE_MISMATCH',
      `the focused page is ${uuid == null ? '(none)' : String(uuid)}, not ${expected} — refusing to place`,
      { expected, actual: uuid == null ? null : String(uuid) },
    );
  }
}

/**
 * `sch.doc.new` — a blank schematic page in the current project.
 *
 * `dmt_Schematic.createSchematicPage(uuid)` needs the *schematic* (sheet
 * collection) uuid, which comes from the currently open schematic — a plain
 * `uuid` property, not a `getState_*` getter (measured 2026-09-13; reading
 * the getter made a real open project look empty). With no schematic open
 * at all, `createSchematic(name)` first creates the sheet, then the page
 * inside it.
 *
 * After creating the page the flow **opens it** (`openDocument`) — the
 * `eda.*` current context and the placement APIs anchor to the *focused*
 * tab, so a page that is created but not focused would leave the next
 * `sch.place_*` drawing on whatever the user had on screen.
 */
export const schDocNew: ActionHandler = async (params, eda) => {
  const name = typeof params.name === 'string' && params.name ? params.name : 'boardwise';
  let schematicUuid: string | undefined;
  try {
    const info: any = await settle(requireFn(eda, 'dmt_Schematic.getCurrentSchematicInfo')());
    schematicUuid = (plainGet(info, 'uuid') as string) || undefined;
    if (!schematicUuid) {
      const pages: any[] = (await settle(
        requireFn(eda, 'dmt_Schematic.getAllSchematicsInfo')(),
      )) ?? [];
      schematicUuid = plainGet(pages[0], 'uuid') as string | undefined;
    }
  } catch {
    schematicUuid = undefined;
  }

  if (!schematicUuid) {
    schematicUuid = await settle(
      requireFn(eda, 'dmt_Schematic.createSchematic')(name),
    ) as string | undefined;
    if (!schematicUuid) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        'createSchematic returned no uuid (is any project open?)',
      );
    }
  }

  const pageUuid = await settle(
    requireFn(eda, 'dmt_Schematic.createSchematicPage')(schematicUuid),
  ) as string | undefined;
  if (!pageUuid) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `createSchematicPage returned no uuid (schematic ${schematicUuid})`,
      { schematicUuid },
    );
  }

  let focused = false;
  try {
    await settle(requireFn(eda, 'dmt_EditorControl.openDocument')(pageUuid));
    const current: any = await settle(
      requireFn(eda, 'dmt_Schematic.getCurrentSchematicPageInfo')(),
    );
    focused = plainGet(current, 'uuid') === pageUuid;
  } catch {
    focused = false;
  }
  if (!focused) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `created page ${pageUuid} but could not focus it — refusing to draw on the wrong page`,
      { pageUuid, schematicUuid },
    );
  }
  return { schematicUuid, pageUuid, focused };
};

// --------------------------------------------------------------------------
// 006c — document management: probe / open / create / rename
// --------------------------------------------------------------------------

/** One row of `doc.list`'s document table. */
interface DocRow {
  uuid: string;
  name: string;
  type: 'page' | 'schematic' | 'pcb';
  active: boolean;
  parentUuid?: string;
  parentName?: string;
}

/**
 * Read one of the `dmt_*` enumeration calls into plain rows.
 *
 * A failed read is *named* in `problems` rather than being indistinguishable
 * from an empty project — the distinction that cost a round on 2026-09-14,
 * when `document.current` returning three nulls said nothing about which one
 * had broken.
 */
async function readDocItems(
  eda: Eda,
  path: string,
  problems: string[],
): Promise<any[]> {
  try {
    const value = await settle(requireFn(eda, path)());
    return Array.isArray(value) ? value : [];
  } catch (error) {
    problems.push(`${path}: ${String((error as Error)?.message ?? error)}`);
    return [];
  }
}

function docRow(
  item: any,
  type: DocRow['type'],
  activeUuid: string | null,
  parent?: { uuid: string; name: string },
): DocRow | null {
  const uuid = plainGet(item, 'uuid');
  if (typeof uuid !== 'string' || !uuid) return null;
  const name = plainGet(item, 'name');
  const row: DocRow = {
    uuid,
    name: typeof name === 'string' ? name : '',
    type,
    active: activeUuid === uuid,
  };
  const parentUuid = parent?.uuid ?? (plainGet(item, 'parentSchematicUuid') as string | undefined);
  const parentName = parent?.name ?? (plainGet(item, 'parentBoardName') as string | undefined);
  if (typeof parentUuid === 'string' && parentUuid) row.parentUuid = parentUuid;
  if (typeof parentName === 'string' && parentName) row.parentName = parentName;
  return row;
}

/**
 * `doc.list` — every document in the open project, and which one is active.
 *
 * Motivation (岳翔宇, 006c): the harness has been acting on "whatever page is
 * focused", and a golden/test page mix-up has already bitten us twice. This
 * makes the project's document set something a caller can *see* — and it is
 * how a uuid for `doc.open` / `doc.rename` is obtained at all.
 *
 * Each document kind has its own enumeration, so the table is assembled from
 * all of them rather than from the currently-open one, which is precisely the
 * assumption being removed.
 */
export const docList: ActionHandler = async (_params, eda) => {
  const problems: string[] = [];

  // Which document is active — the same read `document.current` uses, so the
  // two can never disagree about the same fact (see `activeDocument`).
  const active = await activeDocument(eda, problems);
  const activeUuid = active?.uuid ?? null;

  const rows: DocRow[] = [];
  const schematics = await readDocItems(eda, 'dmt_Schematic.getAllSchematicsInfo', problems);
  const schematicNames = new Map<string, string>();
  for (const schematic of schematics) {
    const uuid = plainGet(schematic, 'uuid');
    const name = plainGet(schematic, 'name');
    if (typeof uuid === 'string' && typeof name === 'string') schematicNames.set(uuid, name);
    const row = docRow(schematic, 'schematic', activeUuid);
    if (row) rows.push(row);
  }

  const pages = await readDocItems(eda, 'dmt_Schematic.getAllSchematicPagesInfo', problems);
  for (const page of pages) {
    const parentUuid = plainGet(page, 'parentSchematicUuid');
    const parent = typeof parentUuid === 'string' && schematicNames.has(parentUuid)
      ? { uuid: parentUuid, name: schematicNames.get(parentUuid) as string }
      : undefined;
    const row = docRow(page, 'page', activeUuid, parent);
    if (row) rows.push(row);
  }

  const pcbs = await readDocItems(eda, 'dmt_Pcb.getAllPcbsInfo', problems);
  for (const pcb of pcbs) {
    const row = docRow(pcb, 'pcb', activeUuid);
    if (row) rows.push(row);
  }

  return {
    documents: rows,
    active,
    schematicPages: rows.filter((row) => row.type === 'page').length,
    pcbs: rows.filter((row) => row.type === 'pcb').length,
    count: rows.length,
    ...(problems.length ? { notes: problems } : {}),
  };
};

/**
 * `doc.open` — focus a document by uuid, so later actions land where intended.
 *
 * `dmt_EditorControl.openDocument(uuid)` is the real entry (`@public`) and
 * accepts a schematic, a schematic **page** or a PCB uuid, returning the tab
 * id it opened. `activateDocument` takes that *tab id*, not a document uuid —
 * so it is the second half of the same move, not an alternative. Both are
 * @public on this build, which is why nothing here is emulated.
 */
export const docOpen: ActionHandler = async (params, eda) => {
  const uuid = typeof params.uuid === 'string' ? params.uuid.trim() : '';
  if (!uuid) {
    throw new ActionError('BAD_REQUEST', 'doc.open needs params.uuid (see doc.list)');
  }
  const tabId = await settle(
    requireFn(eda, 'dmt_EditorControl.openDocument')(uuid),
  ) as string | undefined;
  if (!tabId) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `openDocument(${uuid}) returned no tab id — the uuid may not exist in this project`,
      { uuid },
    );
  }

  // Focus is best-effort and *reported*, never assumed: openDocument opens a
  // tab, and whether that also takes input focus is the host's business.
  let activated = false;
  let activateProblem = '';
  try {
    activated = Boolean(
      await settle(requireFn(eda, 'dmt_EditorControl.activateDocument')(tabId)),
    );
  } catch (error) {
    activateProblem = String((error as Error)?.message ?? error);
  }

  // Confirm by asking the editor which document it now has, not by trusting
  // the call's own return.
  let document: unknown = null;
  try {
    const current: any = await settle(
      requireFn(eda, 'dmt_SelectControl.getCurrentDocumentInfo')(),
    );
    const activeUuid = plainGet(current, 'uuid');
    document = {
      uuid: activeUuid == null ? null : String(activeUuid),
      tabId: plainGet(current, 'tabId') ?? null,
      type: plainGet(current, 'documentType') ?? null,
      matchesRequest: activeUuid === uuid,
    };
  } catch (error) {
    document = { error: String((error as Error)?.message ?? error) };
  }

  return {
    uuid,
    tabId,
    opened: true,
    activated,
    document,
    ...(activateProblem ? { activateProblem } : {}),
  };
};

/**
 * `pcb.doc.new` — a PCB in the current project (mirrors `sch.doc.new`).
 *
 * `dmt_Pcb.createPcb(boardName?)` is `@public` and returns the new PCB uuid;
 * with no name it creates a free-standing PCB. Like `sch.doc.new` it **opens**
 * what it created and verifies the focus, because every later placement action
 * addresses the focused document.
 *
 * The daemon refuses this without `confirm: true` (006c: creating a document
 * is the one thing that must be asked for first). The connector never sees the
 * flag — it is consumed daemon-side — so there is exactly one gate rather than
 * one per caller.
 */
export const pcbDocNew: ActionHandler = async (params, eda) => {
  const boardName = typeof params.boardName === 'string' && params.boardName
    ? params.boardName
    : undefined;
  const pcbUuid = await settle(
    requireFn(eda, 'dmt_Pcb.createPcb')(boardName),
  ) as string | undefined;
  if (!pcbUuid) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'createPcb returned no uuid (is any project open?)',
      { boardName: boardName ?? null },
    );
  }

  let focused = false;
  let problem = '';
  try {
    await settle(requireFn(eda, 'dmt_EditorControl.openDocument')(pcbUuid));
    const current: any = await settle(requireFn(eda, 'dmt_Pcb.getCurrentPcbInfo')());
    focused = plainGet(current, 'uuid') === pcbUuid;
  } catch (error) {
    problem = String((error as Error)?.message ?? error);
  }
  if (!focused) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `created PCB ${pcbUuid} but could not focus it — refusing to edit the wrong document`,
      { pcbUuid, ...(problem ? { problem } : {}) },
    );
  }
  return { pcbUuid, focused };
};

/**
 * `doc.rename` — rename a schematic page, a schematic, or a PCB by uuid.
 *
 * The editor has three separate calls (`modifySchematicPageName`,
 * `modifySchematicName`, `modifyPcbName`) and no generic one, so the action
 * dispatches on the document's kind. The kind comes from `params.type` when
 * given and is otherwise **resolved by enumeration** — never guessed from the
 * uuid's shape.
 *
 * `modifyBoardName` is deliberately not used: it takes the board's *name*
 * rather than a uuid, so it cannot be addressed the way this contract says.
 * A rename is a write to existing content, not a new document.
 */
export const docRename: ActionHandler = async (params, eda) => {
  const uuid = typeof params.uuid === 'string' ? params.uuid.trim() : '';
  const name = typeof params.name === 'string' ? params.name.trim() : '';
  if (!uuid) {
    throw new ActionError('BAD_REQUEST', 'doc.rename needs params.uuid (see doc.list)');
  }
  if (!name) {
    throw new ActionError('BAD_REQUEST', 'doc.rename needs a non-empty params.name');
  }

  const CALLS: Record<string, string> = {
    page: 'dmt_Schematic.modifySchematicPageName',
    schematic: 'dmt_Schematic.modifySchematicName',
    pcb: 'dmt_Pcb.modifyPcbName',
  };
  const LISTING: Record<string, string> = {
    page: 'dmt_Schematic.getAllSchematicPagesInfo',
    schematic: 'dmt_Schematic.getAllSchematicsInfo',
    pcb: 'dmt_Pcb.getAllPcbsInfo',
  };

  let type = typeof params.type === 'string' ? params.type.trim().toLowerCase() : '';
  if (type && !(type in CALLS)) {
    throw new ActionError(
      'BAD_REQUEST',
      `doc.rename type must be one of ${Object.keys(CALLS).join('/')}, got ${type}`,
      { type },
    );
  }

  if (!type) {
    // Resolve the kind by enumeration. Pages, schematics and PCBs are distinct
    // kinds living in the same uuid space, so this is a lookup, not a guess.
    const problems: string[] = [];
    const pages = await readDocItems(eda, LISTING.page, problems);
    const pcbs = await readDocItems(eda, LISTING.pcb, problems);
    const schematics = await readDocItems(eda, LISTING.schematic, problems);
    const has = (items: any[]) => items.some((item) => plainGet(item, 'uuid') === uuid);
    if (has(pages)) type = 'page';
    else if (has(pcbs)) type = 'pcb';
    else if (has(schematics)) type = 'schematic';
    if (!type) {
      throw new ActionError(
        'BAD_REQUEST',
        `no document with uuid ${uuid} in this project — doc.list shows what exists`,
        { uuid, ...(problems.length ? { notes: problems } : {}) },
      );
    }
  }

  const renamed = Boolean(await settle(requireFn(eda, CALLS[type])(uuid, name)));

  // Verify against the editor's own table rather than the call's return value:
  // "modify returned true" and "the document now carries that name" are two
  // different statements, and only the second is what a caller asked for.
  const problems: string[] = [];
  const source = await readDocItems(eda, LISTING[type], problems);
  const entry = source.find((item) => plainGet(item, 'uuid') === uuid);
  const actualName = entry ? plainGet(entry, 'name') : undefined;
  const confirmed = actualName === name;

  if (renamed && !confirmed && entry) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `modify claimed success but the ${type} is still named ${String(actualName)}`,
      { uuid, name, type, actualName: actualName ?? null },
    );
  }

  return {
    uuid,
    name,
    type,
    renamed,
    confirmed,
    ...(problems.length ? { notes: problems } : {}),
  };
};

/**
 * `sch.doc.save` — save the project.
 *
 * Needed because `sch_ManufactureData.getNetlistFile()` returns `undefined`
 * on a project that has never been saved (measured 2026-09-13: a freshly
 * created test project failed 3/3 exports while the saved golden project
 * worked). The draw flow saves before exporting. Explicit action, not a
 * side effect of a read — saving the user's project uninvited would be
 * exactly the kind of surprise this bridge avoids.
 */
export const schDocSave: ActionHandler = async (_params, eda) => {
  const ok = await settle(requireFn(eda, 'sch_Document.save')());
  if (!ok) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'sch_Document.save() returned false — the project may need a manual save',
    );
  }
  return { saved: true };
};

/**
 * How long `sch_PrimitiveComponent.create` gets before it is declared hung.
 *
 * Generous on purpose: the *first* placement against a library that has not
 * been touched this session resolves and indexes the library, and on the
 * measured host that took longer than the old 8 s net-label bound (the probe
 * page shows a first-call timeout that still landed). 30 s is long enough for
 * a cold library and short enough that a genuinely hung call cannot occupy
 * the action slot — the daemon's own budget for this action is 60 s.
 */
const PLACE_COMPONENT_TIMEOUT_MS = 30_000;

/**
 * Components of the current page near ``(x, y)``, with their designators.
 *
 * The readback half of the "timed out but landed" defence: when `create` does
 * not settle, the *only* honest answer is "did something appear where I asked".
 * A tolerance rather than an exact match, because the editor is free to snap a
 * placement to its own lattice before storing it.
 */
async function componentsNear(
  eda: Eda, x: number, y: number, tolerance = 30,
): Promise<Array<{ primitiveId: string; designator: string }>> {
  const getAll = (eda as any)?.sch_PrimitiveComponent?.getAll;
  if (typeof getAll !== 'function') return [];
  let items: any[] = [];
  try {
    items = (await settle(getAll.call((eda as any).sch_PrimitiveComponent))) ?? [];
  } catch {
    return [];
  }
  const out: Array<{ primitiveId: string; designator: string }> = [];
  for (const item of items) {
    const cx = await getState(item, 'X');
    const cy = await getState(item, 'Y');
    if (typeof cx !== 'number' || typeof cy !== 'number') continue;
    if (Math.abs(cx - x) > tolerance || Math.abs(cy - y) > tolerance) continue;
    const id = await getState(item, 'PrimitiveId');
    const designator = await getState(item, 'Designator');
    out.push({
      primitiveId: id == null ? '' : String(id),
      designator: designator == null ? '' : String(designator),
    });
  }
  return out;
}

/**
 * `sch.place_component` — place a library device and name its designator.
 *
 * Resolution order: explicit uuid pair, LCSC part number, keyword search.
 * The search match is *reported* (`resolvedBy`, device name) rather than
 * trusted — a wrong-library hit is exactly the "replaced for library reasons"
 * the acceptance report must list. After `create`, the designator is set on
 * the returned primitive and `done()` commits it; a refused designator is an
 * error, not a warning, because a renamed placement breaks the netlist diff.
 *
 * Since 006b revision 3 the call is **timeout-bounded and self-reporting**,
 * because the measured host timed out on the *first* placement of a session
 * and placed the part anyway — which silently stacked two parts on one spot.
 * On a miss the handler reads the page back and says whether anything landed
 * near the requested point, and the error tells the caller **not to retry**
 * blindly. `timeoutMs` overrides the 30 s default (clamped 200..60000).
 */
export const schPlaceComponent: ActionHandler = async (params, eda) => {
  await guardPage(eda, params.pageUuid);
  const x = toCoord(params.x, 'x');
  const y = toCoord(params.y, 'y');
  const rotation = Number.isFinite(Number(params.rotation)) ? Number(params.rotation) : 0;
  const mirror = params.mirror === true;
  const designator = typeof params.designator === 'string' ? params.designator.trim() : '';
  const timeoutMs = Number.isFinite(Number(params.timeoutMs))
    ? Math.min(Math.max(Number(params.timeoutMs), 200), 60_000)
    : PLACE_COMPONENT_TIMEOUT_MS;

  const deviceLib = namespaceOf(eda, 'lib_Device');
  let device: { uuid: string; libraryUuid: string; name: string } | undefined;
  let resolvedBy = '';

  if (typeof params.deviceUuid === 'string' && params.deviceUuid) {
    const libraryUuid = typeof params.libraryUuid === 'string' ? params.libraryUuid : undefined;
    const item: any = await settle(
      requireFn(eda, 'lib_Device.get')(params.deviceUuid, libraryUuid),
    );
    if (item) {
      const uuid = await getState(item, 'Uuid');
      const library = await getState(item, 'LibraryUuid');
      const nm = await getState(item, 'Name');
      device = {
        uuid: String(uuid ?? params.deviceUuid),
        libraryUuid: String(library ?? libraryUuid ?? ''),
        name: String(nm ?? ''),
      };
      resolvedBy = 'uuid';
    }
    if (!device) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `device ${params.deviceUuid} not found in the library`,
        { deviceUuid: params.deviceUuid },
      );
    }
  }

  if (!device && typeof params.lcsc === 'string' && params.lcsc) {
    const matches: any[] = (await settle(
      deviceLib.getByLcscIds.call(deviceLib, [params.lcsc]),
    )) ?? [];
    const item = matches[0];
    if (item) {
      device = {
        uuid: String(item.uuid ?? ''),
        libraryUuid: String(item.libraryUuid ?? ''),
        name: String(item.name ?? ''),
      };
      resolvedBy = 'lcsc';
    } else {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `LCSC ${params.lcsc} matched no library device`,
        { lcsc: params.lcsc },
      );
    }
  }

  if (!device && typeof params.keyword === 'string' && params.keyword) {
    const matches: any[] = (await settle(
      deviceLib.search.call(deviceLib, params.keyword),
    )) ?? [];
    const item = matches[0];
    if (item) {
      device = {
        uuid: String(item.uuid ?? ''),
        libraryUuid: String(item.libraryUuid ?? ''),
        name: String(item.name ?? ''),
      };
      resolvedBy = 'keyword';
    } else {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `keyword ${JSON.stringify(params.keyword)} matched no library device`,
        { keyword: params.keyword },
      );
    }
  }

  if (!device) {
    throw new ActionError(
      'BAD_REQUEST',
      'sch.place_component needs one of lcsc / deviceUuid+libraryUuid / keyword',
    );
  }
  if (!device.uuid || !device.libraryUuid) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `resolved device is missing uuids: ${JSON.stringify(device)}`,
      { device },
    );
  }

  let created: any;
  let failure = '';
  const started = Date.now();
  try {
    created = await withTimeout(
      settle(
        requireFn(eda, 'sch_PrimitiveComponent.create')(
          { libraryType: 'Device', libraryUuid: device.libraryUuid, uuid: device.uuid },
          x,
          y,
          undefined,
          rotation,
          mirror,
          true,
          true,
        ),
      ),
      timeoutMs,
      'sch_PrimitiveComponent.create',
    );
  } catch (error) {
    failure = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  }
  const elapsedMs = Date.now() - started;

  if (!created) {
    // The measured trap: the first placement of a session resolved the library
    // for longer than the deadline *and still landed*, so a blind retry stacked
    // two parts on one spot. Read the page back and answer the only question
    // that matters — did anything appear where we asked?
    const near = await componentsNear(eda, x, y);
    const landedAnyway = near.length > 0;
    throw new ActionError(
      'TIMEOUT',
      `sch_PrimitiveComponent.create did not settle within ${timeoutMs} ms `
        + `(elapsed ${elapsedMs} ms; ${failure || 'no value returned'}); readback: `
        + (landedAnyway
          ? `${near.length} component(s) ARE present near (${x},${y}) `
            + `[${near.map((c) => c.designator || c.primitiveId).join(', ')}] — `
            + 'at least one placement landed, do NOT retry'
          : `nothing appeared near (${x},${y}) — the placement is unusable`),
      {
        device,
        x,
        y,
        elapsedMs,
        timeoutMs,
        landedAnyway,
        landedCount: near.length,
        near,
      },
    );
  }

  if (designator) {
    // The documented way to name a part is `modify(primitiveId, { designator })`.
    // The alternative — `setState_Designator` on the created object followed by
    // `done()` — was measured silently doing nothing (2026-09-13: every part on
    // a freshly drawn page kept an auto-assigned designator, verified through
    // the editor's own netlist). `modify` returns the updated primitive, and a
    // falsy result is an error: an unnamed part breaks the per-pin diff.
    const primitiveId = await getState(created, 'PrimitiveId');
    const modified: any = await settle(
      requireFn(eda, 'sch_PrimitiveComponent.modify')(
        primitiveId == null ? created : String(primitiveId),
        { designator },
      ),
    );
    if (!modified) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `modify(designator='${designator}') was refused — the part would keep an auto-assigned designator`,
        { designator, primitiveId: primitiveId == null ? null : String(primitiveId) },
      );
    }
  }

  const uuid = await getState(created, 'PrimitiveId');
  return {
    uuid: uuid == null ? null : String(uuid),
    device,
    resolvedBy,
    elapsedMs,
  };
};

/**
 * `export.render` — the document rendered to an image, as base64.
 *
 * This is the **acceptance image** (task 006b revision 4): a *document*
 * render, not a viewport capture, so it cannot come back as a cached frame.
 * The reference implementation measured `getCurrentRenderedAreaImage`
 * returning byte-identical images across different board states, and we
 * observed the same on our own host — `export.screenshot` stays available as
 * a diagnostic but is never evidence.
 *
 * The API is `sch_ManufactureData.getExportDocumentFile(fileName, fileType,
 * typeParams, object)` — ported 2026-09-18 from the reference project's
 * working export handler (`easyeda-agent_RE`, its issue #166), which verified
 * it live on this host. It replaced `getPngFile`, which the type package
 * declares (added v3.2.183) but the 3.2.186 runtime does not expose.
 *
 * ⚠️ The `object` literals below are the ones the editor ACTUALLY accepts,
 * read out of the shipped `sch-main.js` by the reference authors — the
 * `.d.ts` values (`'All Schematic' | 'Current Schematic' | 'Current
 * Schematic Page'`) are WRONG. Passing a declared-but-wrong literal does not
 * throw: an internal TypeError is never caught by the platform, so the
 * awaited promise neither resolves nor rejects and the editor shows a stuck
 * 1% progress toast forever (live-verified by the reference: two hung
 * sessions, 90 s+, only a bare `Uncaught (in promise)` in the console).
 * DO NOT "fix" these strings to match the .d.ts. The timeout guard exists
 * for exactly this failure shape.
 */
const EXPORT_RENDER_SCOPES: Record<string, string> = {
  page: 'Current Page',
  selection: 'Current Page Selected Items',
  project: 'Project',
};

const EXPORT_RENDER_FORMATS: Record<string, { fileType: string; ext: string; mime: string }> = {
  png: { fileType: 'PNG', ext: 'png', mime: 'image/png' },
  svg: { fileType: 'SVG', ext: 'svg', mime: 'image/svg+xml' },
  pdf: { fileType: 'PDF', ext: 'pdf', mime: 'application/pdf' },
};

/**
 * Upper bound for one export. A correct call answers in well under a second;
 * anything near this means the platform swallowed the request (see the trap
 * above), and the action slot must not be held hostage by a promise that
 * will never settle.
 */
const EXPORT_RENDER_TIMEOUT_MS = 30_000;

export const exportRender: ActionHandler = async (params, eda) => {
  const mfg = namespaceOf(eda, 'sch_ManufactureData');
  const getExportDocumentFile = mfg.getExportDocumentFile;
  if (typeof getExportDocumentFile !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'sch_ManufactureData.getExportDocumentFile() is not available on this editor build',
      { path: 'sch_ManufactureData.getExportDocumentFile' },
    );
  }

  const format = String(params?.format ?? 'png').toLowerCase();
  const spec = EXPORT_RENDER_FORMATS[format];
  if (!spec) {
    throw new ActionError(
      'BAD_REQUEST',
      `export.render needs params.format in ${Object.keys(EXPORT_RENDER_FORMATS).join(' | ')} (got ${JSON.stringify(params?.format)})`,
    );
  }
  const scope = String(params?.scope ?? 'page').toLowerCase();
  const objectLiteral = EXPORT_RENDER_SCOPES[scope];
  if (!objectLiteral) {
    throw new ActionError(
      'BAD_REQUEST',
      `export.render needs params.scope in ${Object.keys(EXPORT_RENDER_SCOPES).join(' | ')} (got ${JSON.stringify(params?.scope)})`,
    );
  }

  let ids: string[] = [];
  if (params?.ids !== undefined) {
    if (!Array.isArray(params.ids) || !params.ids.every((id) => typeof id === 'string')) {
      throw new ActionError('BAD_REQUEST', 'export.render params.ids must be a string[] of primitive ids');
    }
    ids = params.ids as string[];
  }
  if (scope === 'selection') {
    // A selection export with no ids would render whatever happens to be
    // selected — an empty image when nothing is, which reads as a successful
    // render of nothing. Demand the ids instead.
    if (ids.length === 0) {
      throw new ActionError(
        'BAD_REQUEST',
        'export.render with scope=selection needs params.ids (a non-empty string[] of primitive ids)',
      );
    }
    await settle(requireFn(eda, 'sch_SelectControl.doSelectPrimitives')(ids));
  }

  const fileName = typeof params?.fileName === 'string' && params.fileName
    ? params.fileName
    : `render.${spec.ext}`;
  const typeParams = { theme: 'Default', lineWidth: 'Default' };

  const file: any = await new Promise((resolve, reject) => {
    const timer = setTimeout(
      () =>
        reject(
          new ActionError(
            'TIMEOUT',
            `getExportDocumentFile did not settle within ${EXPORT_RENDER_TIMEOUT_MS / 1000} s — `
              + 'the host swallowed the request (it drops an argument it dislikes without '
              + 'rejecting). The editor may show a stuck 1% progress toast; reload the '
              + 'document to clear it.',
            { path: 'sch_ManufactureData.getExportDocumentFile', format, scope },
          ),
        ),
      EXPORT_RENDER_TIMEOUT_MS,
    );
    settle(getExportDocumentFile.call(mfg, fileName, spec.fileType, typeParams, objectLiteral)).then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
  if (!file) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'the editor returned no render; is a document open, focused and saved?',
    );
  }
  const bytes = new Uint8Array(await file.arrayBuffer());
  // A multi-document answer (scope=project) can come back as an archive; the
  // caller is told rather than silently handed a zip named `.png`.
  const isZip = bytes.length > 1 && bytes[0] === 0x50 && bytes[1] === 0x4b;
  return {
    format: isZip ? 'zip' : (file.type || spec.mime),
    encoding: 'base64',
    bytes: bytes.byteLength,
    data: bytesToBase64(bytes),
    scope,
    note: isZip
      ? 'the editor returned an archive (multi-document export), not a single image'
      : '',
  };
};

/**
 * `sch.place_wire` — one wire polyline, optionally carrying a net name.
 *
 * `points` is `[[x, y], …]` (2+). **The editor's `create` rejects the pair
 * form at runtime** ("create failed!", measured 2026-09-13 on 3.2.186) even
 * though the type declaration advertises `Array<number> | Array<Array<number>>`
 * — so the handler flattens to `[x1, y1, x2, y2, …]` before the call, which
 * is the form that works. The wire's `net` parameter is passed through; the
 * draw flow additionally names nets with net ports, so a host that ignores
 * the wire net still ends up with correctly named nets.
 */
export const schPlaceWire: ActionHandler = async (params, eda) => {
  await guardPage(eda, params.pageUuid);
  const raw = Array.isArray(params.points) ? params.points : [];
  if (raw.length < 2) {
    throw new ActionError('BAD_REQUEST', 'sch.place_wire needs params.points with 2+ [x, y] pairs');
  }
  const points: Array<[number, number]> = raw.map((p: unknown, i: number) => {
    if (Array.isArray(p) && p.length >= 2) {
      return [toCoord(p[0], `points[${i}].x`), toCoord(p[1], `points[${i}].y`)] as [number, number];
    }
    // Tolerate an already-flat list: [x1, y1, x2, y2, …]
    if (typeof p === 'number' && i % 2 === 0 && i + 1 < raw.length) {
      const y = raw[i + 1];
      if (typeof y === 'number') return [p, y] as [number, number];
    }
    throw new ActionError('BAD_REQUEST', `params.points[${i}] is not an [x, y] pair`);
  });
  const flat: number[] = [];
  for (const [x, y] of points) flat.push(x, y);
  const net = typeof params.net === 'string' && params.net ? params.net : undefined;
  const created: any = await settle(
    requireFn(eda, 'sch_PrimitiveWire.create')(flat, net),
  );
  const uuid = await getState(created, 'PrimitiveId');
  if (uuid == null) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `wire placement returned no uuid (points=${JSON.stringify(points)}, net=${net ?? ''})`,
    );
  }
  return { uuid: String(uuid), net: net ?? null, points };
};

/** How long `createNetLabel` gets before the action declares it hung. */
const NETLABEL_TIMEOUT_MS = 8000;

/** Reject after ``ms`` so a hung host call cannot occupy the action slot. */
function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${label} did not settle in ${ms} ms`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/** Did a ``NET`` attribute for ``net`` actually land near ``(x, y)``? */
async function netAttributeLanded(
  eda: Eda, net: string, x: number, y: number,
): Promise<{ landed: boolean; matches: number }> {
  const api = (eda as any)?.sch_PrimitiveAttribute;
  const getAll = api?.getAll;
  if (typeof getAll !== 'function') return { landed: false, matches: 0 };
  let items: any[] = [];
  try {
    items = (await settle(getAll.call(api))) ?? [];
  } catch {
    return { landed: false, matches: 0 };
  }
  let matches = 0;
  for (const item of items) {
    const key = await getState(item, 'Key');
    const value = await getState(item, 'Value');
    const ax = await getState(item, 'X');
    const ay = await getState(item, 'Y');
    if (
      String(key ?? '') === 'NET'
      && String(value ?? '') === net
      && Number.isFinite(Number(ax)) && Number.isFinite(Number(ay))
      && Math.abs(Number(ax) - x) < 30 && Math.abs(Number(ay) - y) < 30
    ) {
      matches += 1;
    }
  }
  return { landed: matches > 0, matches };
}

/**
 * `sch.place_netlabel` — one net label, **timeout-bounded and self-reporting**.
 *
 * The reference implementation measured the native `createNetLabel` hanging
 * on EasyEDA 3.2.186 (issue #191) while the manual UI works. Task 006b turns
 * that rumour into evidence instead of trusting it: the call races an
 * :data:`NETLABEL_TIMEOUT_MS` deadline, and when it does not settle the
 * handler **reads back** what actually landed before answering — the reference
 * lesson is that a `connector did not respond` failure may well have created
 * the marker anyway, so a blind retry would stack duplicates.
 *
 * The result or the error always carries `elapsedMs` and, on a miss,
 * `landedAnyway`, so the probe report can state which of the two happened.
 */
export const schPlaceNetlabel: ActionHandler = async (params, eda) => {
  await guardPage(eda, params.pageUuid);
  const x = toCoord(params.x, 'x');
  const y = toCoord(params.y, 'y');
  const net = typeof params.net === 'string' ? params.net.trim() : '';
  if (!net) throw new ActionError('BAD_REQUEST', 'sch.place_netlabel needs params.net');

  const started = Date.now();
  // `timeoutMs` lets a probe (or a test) shorten the deadline; it is clamped
  // so a caller cannot turn the bound off.
  const timeoutMs = Number.isFinite(Number(params.timeoutMs))
    ? Math.min(Math.max(Number(params.timeoutMs), 200), 30_000)
    : NETLABEL_TIMEOUT_MS;
  let created: any;
  let failure = '';
  try {
    created = await withTimeout(
      settle(requireFn(eda, 'sch_PrimitiveAttribute.createNetLabel')(x, y, net)),
      timeoutMs,
      'sch_PrimitiveAttribute.createNetLabel',
    );
  } catch (error) {
    failure = error instanceof Error ? `${error.name}: ${error.message}` : String(error);
  }
  const elapsedMs = Date.now() - started;

  if (created) {
    const uuid = await getState(created, 'PrimitiveId');
    return {
      uuid: uuid == null ? null : String(uuid),
      outcome: 'ok',
      elapsedMs,
      landedAnyway: true,
    };
  }

  const readback = await netAttributeLanded(eda, net, x, y);
  throw new ActionError(
    'TIMEOUT',
    `createNetLabel did not settle within ${timeoutMs} ms `
      + `(elapsed ${elapsedMs} ms; ${failure || 'no value returned'}); readback: `
      + (readback.landed
        ? `a NET attribute for ${net} IS present near (${x},${y}) — it landed, do NOT retry`
        : `nothing for ${net} appeared near (${x},${y}) — the call is unusable`),
    { net, x, y, elapsedMs, timeoutMs, landedAnyway: readback.landed, matches: readback.matches },
  );
};

/** `createNetFlag` accepts exactly these kinds. */
const NET_FLAG_KINDS = new Set(['Power', 'Ground', 'AnalogGround', 'ProtectGround']);

/**
 * `sch.place_text` — a free text primitive, **decoration only**.
 *
 * The naming-strategy decision (006b revision 3, sanctioned by 岳翔宇): the
 * only API that creates a *real* net label is `createNetLabel`, and on the
 * measured host (3.2.186) it can never settle — the type package marks it
 * *ADD since EDA v4*. The fallback that keeps a schematic **readable** is a
 * plain text primitive next to the wire: it draws the net name where a human
 * expects to read it, and it is *not* an electrical object.
 *
 * The caller must present it as what it is. It is deliberately a separate
 * action rather than a stealth mode inside `place_netlabel`, so the report can
 * say "signal names are text, not native labels" without anyone having to
 * infer it, and so nothing can quietly mistake it for a connectivity carrier.
 *
 * `alignMode` defaults to LEFT_MIDDLE (2) — the text starts at the anchor,
 * which is how a net name reads beside a wire; the anchor itself is the wire
 * point the caller computed.
 */
export const schPlaceText: ActionHandler = async (params, eda) => {
  await guardPage(eda, params.pageUuid);
  const x = toCoord(params.x, 'x');
  const y = toCoord(params.y, 'y');
  const content = typeof params.content === 'string' ? params.content : '';
  if (!content) throw new ActionError('BAD_REQUEST', 'sch.place_text needs params.content');
  const rotation = Number.isFinite(Number(params.rotation)) ? Number(params.rotation) : 0;
  const color = typeof params.color === 'string' && params.color ? params.color : null;
  const fontSize = Number.isFinite(Number(params.fontSize)) ? Number(params.fontSize) : null;

  const created: any = await settle(
    requireFn(eda, 'sch_PrimitiveText.create')(
      x,
      y,
      content,
      rotation,
      color,
      null,
      fontSize,
      false,
      false,
      false,
    ),
  );
  if (!created) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `the editor refused the text ${JSON.stringify(content)} at (${x}, ${y})`,
      { content, x, y },
    );
  }
  const uuid = await getState(created, 'PrimitiveId');
  return {
    uuid: uuid == null ? null : String(uuid),
    content,
    // Stated on every response: this object carries no connectivity. A report
    // that renders signal names this way must say so.
    decorative: true,
  };
};

/**
 * `sch.place_power` — a power / ground net flag.
 *
 * `createNetFlag` places a real library component under the hood, so the
 * result participates in the netlist exactly like the golden board's own
 * power symbols — which is why this is a first-class action rather than a
 * net label alias.
 */
export const schPlacePower: ActionHandler = async (params, eda) => {
  await guardPage(eda, params.pageUuid);
  const kind = typeof params.kind === 'string' ? params.kind : '';
  if (!NET_FLAG_KINDS.has(kind)) {
    throw new ActionError(
      'BAD_REQUEST',
      `sch.place_power needs params.kind in ${[...NET_FLAG_KINDS].join(' | ')}`,
    );
  }
  const net = typeof params.net === 'string' ? params.net.trim() : '';
  if (!net) throw new ActionError('BAD_REQUEST', 'sch.place_power needs params.net');
  const x = toCoord(params.x, 'x');
  const y = toCoord(params.y, 'y');
  const rotation = Number.isFinite(Number(params.rotation)) ? Number(params.rotation) : 0;
  const mirror = params.mirror === true;
  const created: any = await settle(
    requireFn(eda, 'sch_PrimitiveComponent.createNetFlag')(
      kind,
      net,
      x,
      y,
      rotation,
      mirror,
    ),
  );
  if (!created) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `the editor refused the ${kind} flag for net ${net} at (${x}, ${y})`,
      { kind, net },
    );
  }
  const uuid = await getState(created, 'PrimitiveId');
  return { uuid: uuid == null ? null : String(uuid) };
};

/** `createNetPort` accepts exactly these directions. */
const NET_PORT_DIRECTIONS = new Set(['IN', 'OUT', 'BI']);

/**
 * `sch.place_netport` — a net port carrying a net name.
 *
 * The naming workhorse of the draw flow: where `createNetLabel` hangs on
 * the measured host (see `schPlaceNetlabel`), a net port placed at a pin or
 * on a wire names the net through a real, supported component.
 */
export const schPlaceNetport: ActionHandler = async (params, eda) => {
  await guardPage(eda, params.pageUuid);
  const direction = typeof params.direction === 'string' ? params.direction : '';
  if (!NET_PORT_DIRECTIONS.has(direction)) {
    throw new ActionError(
      'BAD_REQUEST',
      `sch.place_netport needs params.direction in ${[...NET_PORT_DIRECTIONS].join(' | ')}`,
    );
  }
  const net = typeof params.net === 'string' ? params.net.trim() : '';
  if (!net) throw new ActionError('BAD_REQUEST', 'sch.place_netport needs params.net');
  const x = toCoord(params.x, 'x');
  const y = toCoord(params.y, 'y');
  const rotation = Number.isFinite(Number(params.rotation)) ? Number(params.rotation) : 0;
  const mirror = params.mirror === true;
  const created: any = await settle(
    requireFn(eda, 'sch_PrimitiveComponent.createNetPort')(
      direction,
      net,
      x,
      y,
      rotation,
      mirror,
    ),
  );
  if (!created) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `the editor refused the ${direction} port for net ${net} at (${x}, ${y})`,
      { direction, net },
    );
  }
  const uuid = await getState(created, 'PrimitiveId');
  return { uuid: uuid == null ? null : String(uuid) };
};
export function buildHandlers(eda: Eda): Record<string, BoundHandler> {
  const bind =
    (handler: ActionHandler): BoundHandler =>
    (params) =>
      handler(params, eda);

  return {
    'document.current': bind(documentCurrent),
    'sys.probe': bind(sysProbe),
    'sys.self_update': bind(sysSelfUpdate),
    'sch.readback': bind(schReadback),
    'lib.symbol.get': bind(libSymbolGet),
    'lib.device.get': bind(libDeviceGet),
    'sch.component_pins': bind(schComponentPins),
    'lib.footprint.get': bind(libFootprintGet),
    'lib.device.search': bind(libDeviceSearch),
    'sch.set_component_attribute': bind(schSetComponentAttribute),
    'pcb.readback': bind(pcbReadback),
    'export.screenshot': bind(exportScreenshot),
    'export.render': bind(exportRender),
    'canvas.highlight': bind(canvasHighlight),
    'sch.netlist': bind(schNetlist),
    'sch.geometry': bind(schGeometry),
    'doc.list': bind(docList),
    'doc.open': bind(docOpen),
    'pcb.doc.new': bind(pcbDocNew),
    'doc.rename': bind(docRename),
    'sch.doc.new': bind(schDocNew),
    'sch.doc.save': bind(schDocSave),
    'sch.place_component': bind(schPlaceComponent),
    'sch.place_wire': bind(schPlaceWire),
    'sch.place_netlabel': bind(schPlaceNetlabel),
    'sch.place_text': bind(schPlaceText),
    'sch.place_power': bind(schPlacePower),
    'sch.place_netport': bind(schPlaceNetport),
  };
}
