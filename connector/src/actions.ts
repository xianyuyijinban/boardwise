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
import { ActionError, isActionError, type ResponseContext } from './protocol';
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
 * One identifying field of a project, in whichever of the two shapes the host
 * handed the info object over: plain property first, `getState_*` second.
 *
 * Same lesson as {@link infoUuid}, for the project box: the type declarations
 * describe `dmt_Project.getCurrentProjectInfo` as `IDMT_ProjectInfo` with plain
 * readonly properties (`uuid`, `name`, `friendlyName`), and that is what the
 * real host answers (measured 2026-09-21) — while a mock or an older build may
 * answer through `getState_*` on the prototype. A reader that knew only one
 * shape reported "no project" on a project it was handed.
 */
async function identityField(info: any, plain: string, state: string): Promise<string | undefined> {
  const direct = plainGet(info, plain);
  if (typeof direct === 'string' && direct) return direct;
  const fallback = await getState(info, state);
  return typeof fallback === 'string' && fallback ? fallback : undefined;
}

/**
 * The identity of a project, spelled the way `doc.list`'s `projects[]` row
 * spells it (`projectUuid` / `name` / `friendlyName`).
 *
 * Why one shared read rather than a field read per caller: `doc.list` and
 * `document.current` ask the host for the *same* project and used to disagree
 * about it. Measured 2026-09-21 on editor 3.2.186 — `projects[]` named the
 * focused project (`/test`, `test`, `ea80fff6…`) while `document.current`
 * answered `project: {}`, because that box was built with `snapshot()`, which
 * walks `getState_*` prototype members only and this host's project info
 * carries plain properties. The disagreement was invisible for as long as it
 * lasted: `document.current`'s pcb and schematic-page boxes *are* read through
 * `getState_*` on that build, so only the project box came back empty, and an
 * empty box reads like "nothing is open". Both readers go through here now.
 */
async function projectIdentity(info: any): Promise<Record<string, string>> {
  const [uuid, name, friendlyName] = await Promise.all([
    identityField(info, 'uuid', 'Uuid'),
    identityField(info, 'name', 'Name'),
    identityField(info, 'friendlyName', 'FriendlyName'),
  ]);
  return {
    ...(uuid ? { projectUuid: uuid } : {}),
    ...(name ? { name } : {}),
    ...(friendlyName ? { friendlyName } : {}),
  };
}

/**
 * The focused project of *this window*, in the shape `hello` carries it
 * (021 §2.3).
 *
 * The one channel that can answer "which projects does the user have open?".
 * `eda` is window-scoped and there is no cross-window member on the host (021
 * §A4, measured 2026-09-22: `dmt_Project` has 12 members and none of them lists
 * the open projects), but every window runs its own connector — so each one
 * saying which project it holds makes the set visible on the daemon side, where
 * the refused instances are exactly the other windows (021 §实测记录 A1).
 *
 * **Never throws, and never guesses.** An empty object means "this window could
 * not name its project" — an absent capability or a failed read, not a project
 * called nothing. The daemon records that absence instead of a name, because
 * this is the field a caller would use to decide where a write goes.
 *
 * `projectName` prefers `friendlyName` (`/test`) over `name` (`test`): it is
 * the label the editor itself shows for the project, so the name printed by
 * `bridge status` is one the user can match against their own window.
 */
export async function currentProjectIdentity(
  eda: Eda,
): Promise<{ projectName?: string; projectUuid?: string }> {
  try {
    const getCurrent = requireFn(eda, 'dmt_Project.getCurrentProjectInfo');
    const info = await settle(getCurrent());
    const identity = await projectIdentity(info);
    const name = identity.friendlyName || identity.name;
    return {
      ...(identity.projectUuid ? { projectUuid: identity.projectUuid } : {}),
      ...(name ? { projectName: name } : {}),
    };
  } catch {
    return {};
  }
}

/**
 * The `pageType` vocabulary of a response frame's context (023 §协议字段约定 1).
 *
 * Two words, and they are `document.current`'s own: `sch` for a schematic or
 * one of its pages, `pcb` for a PCB. `null` is the third answer, and it is a
 * *reading* — a document is in front and it is neither (a symbol editor, the
 * home tab). A window that could read no document at all omits the key
 * instead, because "no document" and "a document of another kind" are
 * different facts and the daemon routes on the difference.
 */
function responsePageType(kind: string): 'sch' | 'pcb' | null {
  if (kind === 'pcb') return 'pcb';
  if (kind === 'page' || kind === 'schematic') return 'sch';
  return null;
}

/**
 * This window's live context, read for each response frame (023 §协议字段约定 1).
 *
 * Why it is per response rather than per connection: with three editor windows
 * open, the daemon has to answer "which project is this action about?" before
 * every call, and a context frozen at `hello` answers it about the document the
 * user had open when the connector connected. The response the daemon is
 * already waiting for is the freshest thing on the wire, so the answer rides on
 * it.
 *
 * Both reads are the *shared* ones — `currentProjectIdentity`, which is what
 * `hello` announces, and `activeDocument`, which is what `doc.list` and
 * `document.current` use — so this can never disagree with the actions a caller
 * would use to check it. The empty `problems` array is deliberate: those
 * findings belong to the actions that report them, and a context frame carries
 * four short fields, not a diagnosis.
 *
 * **Never throws, never invents, never waits.** Whatever could not be read is
 * left out of the object — an absent `pageUuid` means "this window did not
 * say", and the transport puts the whole read on a deadline so a host call that
 * never settles costs a decoration rather than the answer.
 */
export async function currentResponseContext(eda: Eda): Promise<ResponseContext> {
  const context: ResponseContext = {};
  try {
    Object.assign(context, await currentProjectIdentity(eda));
  } catch {
    // `currentProjectIdentity` answers `{}` instead of throwing; this is the
    // shell for a host that gets past its own guards.
  }
  try {
    const active = await activeDocument(eda, []);
    if (active) {
      context.pageUuid = active.uuid;
      context.pageType = responsePageType(active.type);
    }
  } catch {
    // A document read that failed leaves both keys out — never the previous
    // window's reading, which would name a page this window does not have.
  }
  return context;
}

/**
 * Uuids the host uses as a *placeholder* for "no document is focused".
 *
 * Measured on the machine 2026-09-21: with more than one editor window open and
 * none of them focused, `getCurrentDocumentInfo` still answers — with
 * `uuid: "0"`, a uuid no document in any project has. Reporting that as fact is
 * worse than reporting nothing, because `active` is what every caller uses to
 * decide *where* it is working, and a name that matches no document quietly
 * defeats that check while looking like an answer.
 */
const PLACEHOLDER_DOC_UUIDS = new Set(['0']);

/**
 * What the shared "which document is active" read answers.
 *
 * `projectUuid` / `libraryUuid` come from `IDMT_EditorDocumentItem`'s
 * `parentProjectUuid` / `parentLibraryUuid` — the type package's own answer to
 * "which project is this document in", and the only field that can tell two
 * layers of editor focus apart when they disagree (the case `sys.identity`
 * exists for; see `docs/bridge.md` §4). They are optional because only the
 * direct `getCurrentDocumentInfo` read carries them, and only some host builds
 * fill them in.
 */
type ActiveDocumentReading = {
  uuid: string;
  type: string;
  tabId?: string;
  projectUuid?: string;
  libraryUuid?: string;
  source: string;
};

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
 *
 * It is also where the host's placeholder uuid is turned into "no active
 * document" (see {@link PLACEHOLDER_DOC_UUIDS}): the answer is dropped, and the
 * raw reading goes into `problems` — which `doc.list` surfaces as `notes` —
 * so the caller can tell "nothing is focused" from "the host said `0`".
 */
async function activeDocument(
  eda: Eda,
  problems: string[],
): Promise<ActiveDocumentReading | null> {
  const DIRECT = 'dmt_SelectControl.getCurrentDocumentInfo';
  // A placeholder is a *reading*, not a failure, so it is named where every
  // other "we asked and the answer was unusable" is named — the caller gets
  // `null` (no active document) plus the evidence, never a uuid it might act
  // on. Both readers share this, so the two can never disagree about it.
  const noActive = (uuid: string, source: string): null => {
    problems.push(
      `${source}: reported uuid "${uuid}" for the active document — the host's `
        + 'placeholder for "nothing is focused"; reported as no active document',
    );
    return null;
  };
  try {
    const info: any = await settle(requireFn(eda, DIRECT)());
    const uuid = await infoUuid(info);
    if (uuid) {
      if (PLACEHOLDER_DOC_UUIDS.has(uuid)) return noActive(uuid, DIRECT);
      const tabId = plainGet(info, 'tabId');
      const parentProjectUuid = plainGet(info, 'parentProjectUuid');
      const parentLibraryUuid = plainGet(info, 'parentLibraryUuid');
      return {
        uuid,
        // Same vocabulary as `doc.list`'s `documents[].type`.
        type: documentKind(plainGet(info, 'documentType')),
        ...(typeof tabId === 'string' && tabId ? { tabId } : {}),
        // Carried through unchanged when the host offers them, omitted when it
        // does not — "the host did not say" is a different fact from "no
        // project", and only the caller knows which of the two it can act on.
        ...(typeof parentProjectUuid === 'string' && parentProjectUuid
          ? { projectUuid: parentProjectUuid }
          : {}),
        ...(typeof parentLibraryUuid === 'string' && parentLibraryUuid
          ? { libraryUuid: parentLibraryUuid }
          : {}),
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
        if (PLACEHOLDER_DOC_UUIDS.has(uuid)) return noActive(uuid, path);
        return { uuid, type, source: path };
      }
    } catch (error) {
      problems.push(`${path}: ${String((error as Error)?.message ?? error)}`);
    }
  }
  return null;
}

// --------------------------------------------------------------------------
// project identity readers shared by the new diagnostics (018 §B)
// --------------------------------------------------------------------------

/** One project, in the spelling `doc.list`'s `projects[]` rows use. */
type ProjectName = { projectUuid: string; name?: string; friendlyName?: string };

/** A project plus the read that named it — never merged into one anonymous fact. */
type ProjectOwner = ProjectName & { source: string };

/** `name (uuid)`, or the bare uuid when the project could not be named. */
function projectLabel(project: ProjectName | null): string {
  if (!project?.projectUuid) return 'unknown';
  const name = project.name || project.friendlyName;
  return name ? `"${name}" (${project.projectUuid})` : project.projectUuid;
}

/** Build a {@link ProjectName} from an identity record, keeping only real fields. */
function namedProject(projectUuid: string, identity: Record<string, string>): ProjectName {
  const name = typeof identity.name === 'string' && identity.name ? identity.name : undefined;
  const friendlyName = typeof identity.friendlyName === 'string' && identity.friendlyName
    ? identity.friendlyName
    : undefined;
  return {
    projectUuid,
    ...(name ? { name } : {}),
    ...(friendlyName ? { friendlyName } : {}),
  };
}

/**
 * The focused project — the one `doc.list` marks `focused: true`.
 *
 * Read through the same `projectIdentity` the `doc.list` and `document.current`
 * project boxes use, so the three cannot disagree about the same project. It is
 * a separate reader from `projectRows` on purpose: that one treats a missing
 * `dmt_Project` as an absent capability and stays out of `notes`, while a
 * *diagnostic* caller has to be told that it could not ask (018 §B: "both
 * absent and different are reported honestly").
 */
async function focusedProject(eda: Eda, notes: string[]): Promise<ProjectName | null> {
  let info: any;
  try {
    info = await settle(requireFn(eda, 'dmt_Project.getCurrentProjectInfo')());
  } catch (error) {
    notes.push(
      `focused project (dmt_Project.getCurrentProjectInfo): ${String((error as Error)?.message ?? error)}`,
    );
    return null;
  }
  if (!info) return null;
  const identity = await projectIdentity(info);
  const uuid = identity.projectUuid;
  if (typeof uuid !== 'string' || !uuid) return null;
  return namedProject(uuid, identity);
}

/**
 * Every project the editor has open, by uuid, with whatever name it will give.
 *
 * `getAllProjectsUuid` answers for the workspace, and `getProjectInfo(uuid)` is
 * the type package's **brief** per-project read — uuid / friendlyName / team,
 * explicitly documented as carrying no document tree. That is the honest limit
 * of this index and the reason it can name a project but never list what is in
 * one; a caller that needs the documents of a non-focused project has to focus
 * it first (`doc.list`'s `projects[]` says the same with `documents: "brief"`).
 */
async function openProjectIndex(eda: Eda, notes: string[]): Promise<Map<string, ProjectName>> {
  const index = new Map<string, ProjectName>();
  let uuids: unknown;
  try {
    uuids = await settle(requireFn(eda, 'dmt_Project.getAllProjectsUuid')());
  } catch (error) {
    notes.push(`open projects: ${String((error as Error)?.message ?? error)}`);
    return index;
  }
  if (!Array.isArray(uuids)) {
    notes.push(`open projects: getAllProjectsUuid returned ${typeof uuids}, not an array`);
    return index;
  }
  for (const raw of uuids) {
    const uuid = String(raw ?? '');
    if (!uuid) continue;
    let entry: ProjectName = { projectUuid: uuid };
    try {
      const info: any = await settle(requireFn(eda, 'dmt_Project.getProjectInfo')(uuid));
      if (info) entry = namedProject(uuid, await projectIdentity(info));
    } catch (error) {
      notes.push(
        `open projects: getProjectInfo(${uuid}): ${String((error as Error)?.message ?? error)}`,
      );
    }
    index.set(uuid, entry);
  }
  return index;
}

/** Fill in a project's names from the open-project index when it has none. */
function withNames(project: ProjectName | null, index: Map<string, ProjectName>): ProjectName | null {
  if (!project?.projectUuid) return null;
  const known = index.get(project.projectUuid);
  const name = project.name ?? known?.name;
  const friendlyName = project.friendlyName ?? known?.friendlyName;
  return {
    projectUuid: project.projectUuid,
    ...(name ? { name } : {}),
    ...(friendlyName ? { friendlyName } : {}),
  };
}

/**
 * Which project a document uuid belongs to, asked of the document itself.
 *
 * This is the channel `document.current` was missing: when the editor's two
 * layers of focus disagree, `doc.list` and `document.current` both describe the
 * **focused project**, while the active document may belong to another one —
 * and only the document's own info object says which. The type package carries
 * the answer for every kind we can address: `IDMT_SchematicItem.parentProjectUuid`
 * and `IDMT_PcbItem.parentProjectUuid` (`所属工程 UUID`). A schematic *page*
 * uuid is resolved through its schematic, because a page item carries
 * `parentSchematicUuid` and no project.
 *
 * The reads are per-kind and documented as operating "inside the currently open
 * project", so on a real host a **foreign** uuid may legitimately answer
 * nothing. That is a limit of the channel, and it is reported as `null` with
 * the failure named in `notes` rather than guessed at.
 */
async function documentOwnerProject(
  eda: Eda,
  uuid: string,
  notes: string[],
): Promise<ProjectOwner | null> {
  const check = (path: string, info: any): ProjectOwner | null => {
    const projectUuid = plainGet(info, 'parentProjectUuid');
    return typeof projectUuid === 'string' && projectUuid ? { projectUuid, source: path } : null;
  };

  const direct = ['dmt_Pcb.getPcbInfo', 'dmt_Schematic.getSchematicInfo'];
  for (const path of direct) {
    try {
      const info = await settle(requireFn(eda, path)(uuid));
      const found = info ? check(path, info) : null;
      if (found) return found;
    } catch (error) {
      notes.push(`${path}(${uuid}): ${String((error as Error)?.message ?? error)}`);
    }
  }

  // A schematic *page*: page → parent schematic → project.
  const pagePath = 'dmt_Schematic.getSchematicPageInfo';
  try {
    const page: any = await settle(requireFn(eda, pagePath)(uuid));
    const schematicUuid = plainGet(page, 'parentSchematicUuid');
    if (typeof schematicUuid === 'string' && schematicUuid) {
      const schematic: any = await settle(
        requireFn(eda, 'dmt_Schematic.getSchematicInfo')(schematicUuid),
      );
      // The project uuid comes from the *schematic*, and the source says so:
      // naming the page read here would credit the wrong call with the answer.
      const found = schematic
        ? check(`${pagePath} → dmt_Schematic.getSchematicInfo`, schematic)
        : null;
      if (found) return found;
    }
  } catch (error) {
    notes.push(`${pagePath}(${uuid}): ${String((error as Error)?.message ?? error)}`);
  }
  return null;
}

// --------------------------------------------------------------------------
// handlers
// --------------------------------------------------------------------------

/**
 * The `project` box of `document.current`: the `snapshot()` view of the info
 * object **plus** the identity `doc.list` reports for the same project.
 *
 * Both halves are kept. `snapshot` is the only reader that can carry whatever
 * else a host build puts on the box, and the identity keys are what a caller
 * compares against `doc.list`'s `projects[]` row — the two used to disagree
 * exactly here, because `snapshot` cannot see plain properties (see
 * {@link projectIdentity}).
 */
async function readProject(eda: Eda, problems: string[]): Promise<Record<string, unknown> | null> {
  try {
    const info = await requireFn(eda, 'dmt_Project.getCurrentProjectInfo')();
    if (!info) return null;
    return { ...(await snapshot(info, 40, problems)), ...(await projectIdentity(info)) };
  } catch (error) {
    problems.push(
      `project (dmt_Project.getCurrentProjectInfo): ${String((error as Error)?.message ?? error)}`,
    );
    return null;
  }
}

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
  // The project box is the one that is *not* only a `snapshot`: this host
  // answers it with plain properties, so a snapshot-only box came back empty
  // on a project `doc.list` could name (measured 2026-09-21). See `readProject`.
  const project = await readProject(eda, problems);
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
 * Every member that reads back as a function also gets an `arity` entry
 * (`fn.length`), so "declared with six arguments" and "declared with two" are
 * distinguishable without a second action — see the `arity` comment below.
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
    // `fn.length` — the member's *declared* arity, reported beside the typeof it
    // belongs to. F4 (2026-09-21) needed exactly this: `searchByProperties`
    // reads back `function` on a host that answers nothing, and a 2-argument
    // implementation under a 6-argument declaration would explain it. A hint,
    // not a verdict — a proxy or a wrapper loses the real arity, so it is
    // reported and never judged on (same footing as "typeof only proves the
    // member is there").
    const arity: Record<string, number> = {};
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
        if (typeof value === 'function') {
          try {
            arity[member] = value.length;
          } catch {
            // A member whose arity read throws stays a `function` in `status`:
            // the read the caller asked for succeeded, and the arity simply did
            // not — which is readable as "a function with no arity entry".
          }
        }
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
      // Always present, and empty when no member read back as a function: an
      // absent member has no arity, and "no entry" is that fact.
      arity,
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
 *   The member's declared arity (`fn.length`) is reported alongside, which is
 *   how "present but answering nothing" gets a shape to test.
 *   This is what a host that crashes the enumerator can still answer.
 * - **enumerate** (fallback): `namespace` / `namespaces` / `functionsOnly`.
 *   Kept because it can find a name nobody predicted — a capability the type
 *   package cannot provide. A throwing level costs one report line, never the
 *   whole answer.
 * - **`call`** (025): `{"call": {"action": "…", "params": {…}}}` runs one
 *   registered *read-only* action and returns its own answer under `call`. This
 *   is not an enumeration: it exists because the daemon's catalogue is a
 *   load-time constant, so an action registered after the daemon started cannot
 *   be reached by `bridge call --action <name>` until that daemon restarts. The
 *   allowlist is closed and read-only (see {@link PROBE_CALL_ACTIONS}) so this
 *   channel cannot bypass the daemon's `create` gate.
 *
 * Purely read-only: it calls nothing. Every branch records its own outcome, so
 * an empty answer is distinguishable from a failed one. (The `call` mode is the
 * one exception, and it only reaches actions that are themselves read-only.)
 *
 * Params:
 * - `checks` (object, optional): `{namespace: [methodName, …]}` — the exact
 *   list to verify. Presence of this key selects the `checks` mode.
 * - `namespace` (string, optional): one namespace to enumerate (default
 *   `sch_ManufactureData`). May be given as `namespaces` (string[]) to do
 *   several at once.
 * - `functionsOnly` (boolean, optional, default `false`): keep only function
 *   members. Off by default so a renamed data field is not hidden.
 * - `call` (object, optional): `{action, params?}` — dispatch one allowlisted
 *   read-only action. Checked before `checks`, so the key cannot be shadowed.
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

  // `call` mode (025): dispatch one registered **read-only** action by name.
  // Exists because the daemon's catalogue is a load-time constant, so a freshly
  // registered action is unreachable until the daemon is restarted — see
  // `PROBE_CALL_ACTIONS` for the rule and the reasoning. The handler is invoked
  // exactly as `buildHandlers` would invoke it, so the answer is the registered
  // action's own answer, not a re-implementation of it.
  if (params?.call !== undefined) {
    const request = params.call;
    if (!request || typeof request !== 'object' || Array.isArray(request)) {
      throw new ActionError(
        'BAD_REQUEST',
        'sys.probe params.call must be an object {action, params?}',
      );
    }
    const name = String((request as Record<string, unknown>).action ?? '');
    const handler = PROBE_CALL_ACTIONS[name];
    if (!handler) {
      throw new ActionError(
        'BAD_REQUEST',
        `sys.probe call mode only dispatches ${Object.keys(PROBE_CALL_ACTIONS).join(' | ')} `
          + `(asked for ${JSON.stringify(name)}) — the list is closed to read-only actions so `
          + "this channel can never bypass the daemon's create gate",
        { action: name, allowed: Object.keys(PROBE_CALL_ACTIONS) },
      );
    }
    const inner = (request as Record<string, unknown>).params;
    if (inner !== undefined && (!inner || typeof inner !== 'object' || Array.isArray(inner))) {
      throw new ActionError('BAD_REQUEST', 'sys.probe params.call.params must be an object');
    }
    const forwarded = (inner ?? {}) as Record<string, unknown>;
    const result = await handler(forwarded, eda);
    return {
      version,
      connector: VERSION,
      topLevel,
      call: { action: name, params: forwarded, result },
    };
  }

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
 * Every document the editor's open project lists, in `doc.list`'s row shape.
 *
 * One builder for two readers — `doc.list` itself and `doc.open`'s failure
 * diagnosis (018 §B1), which has to ask "is this uuid in the project at all?"
 * of exactly the set `doc.list` shows. Two copies of this would be two answers
 * to that question.
 *
 * `activeUuid` only marks rows; a caller with no interest in the marker passes
 * `null`, and a caller that needs to know whether the listing is *complete*
 * watches `problems` (the enumerations record their own failures there).
 */
async function collectDocumentRows(
  eda: Eda,
  problems: string[],
  activeUuid: string | null,
): Promise<DocRow[]> {
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
  return rows;
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

  const rows = await collectDocumentRows(eda, problems, activeUuid);

  // 012 §五: the multi-project view rides along on the same report — the
  // existing fields are untouched (187 tests guard them), `projects` is new.
  const projects = await projectRows(eda, problems, rows);

  return {
    documents: rows,
    projects,
    active,
    schematicPages: rows.filter((row) => row.type === 'page').length,
    pcbs: rows.filter((row) => row.type === 'pcb').length,
    count: rows.length,
    ...(problems.length ? { notes: problems } : {}),
  };
};

/**
 * The multi-project half of `doc.list` (012 §五): every project the editor
 * has open, with the focused one marked.
 *
 * The type package's per-project read is `getProjectInfo(uuid)` — a *brief*
 * item (uuid / friendlyName / team), explicitly documented as lacking the
 * document tree; only `getCurrentProjectInfo()` carries the full tree, and
 * there is exactly one current project. So the honest shape is: the focused
 * project lists its schematics/pcbs, every other entry reports `documents:
 * "brief"` with an empty pair, and the caller focuses another project with
 * `doc.focus` / `doc.open` before enumerating its pages. `opened` is
 * `"unknown"` for the non-focused entries on purpose: `getAllProjectsUuid()`
 * answers for the whole workspace, not for "what is open in tabs", and the
 * tab tree carries project names only inside tab titles — claiming an open
 * set from that would be guessing.
 */
async function projectRows(eda: Eda, problems: string[], docRows: DocRow[]): Promise<Array<Record<string, unknown>>> {
  const rows: Array<Record<string, unknown>> = [];
  let current: any;
  try {
    const getCurrent = requireFn(eda, 'dmt_Project.getCurrentProjectInfo');
    current = await settle(getCurrent());
  } catch {
    // A host without dmt_Project gets the legacy doc.list fields with an
    // empty project view — an *absent capability*, not a broken read, so it
    // stays out of `notes` (those name reads that actually failed).
    return rows;
  }
  // The identity of the focused project comes from the read `document.current`
  // uses for its `project` box, so the two cannot spell the same project
  // differently (`projectIdentity`).
  const currentIdentity = await projectIdentity(current);

  const push = (
    uuid: unknown,
    friendly: unknown,
    name: unknown,
    focused: boolean,
    schematics: unknown[] = [],
    pcbs: unknown[] = [],
  ): void => {
    if (typeof uuid !== 'string' || !uuid) return;
    rows.push({
      projectUuid: uuid,
      name: typeof name === 'string' && name ? name : friendly,
      friendlyName: typeof friendly === 'string' ? friendly : '',
      focused,
      opened: focused ? 'yes' : 'unknown',
      schematics,
      pcbs,
      documents: focused ? 'full' : 'brief',
    });
  };

  // The focused project first, from the full-info read. Its document list
  // reuses the rows already enumerated above (getAllSchematicsInfo & co. —
  // measured APIs), not the type package's `data[]` whose itemType values
  // the host fills differently (measured 2026-09-21: my Schematic/PCB guess
  // matched nothing, 0 schematics on a project with four).
  const focusSchematics = docRows
    .filter((row) => row.type === 'schematic' || row.type === 'page')
    .map((row) => ({ uuid: row.uuid, name: row.name, type: row.type }));
  const focusPcbs = docRows
    .filter((row) => row.type === 'pcb')
    .map((row) => ({ uuid: row.uuid, name: row.name, type: row.type }));
  push(currentIdentity.projectUuid, currentIdentity.friendlyName, currentIdentity.name,
    true, focusSchematics, focusPcbs);

  const getAllUuids = requireFn(eda, 'dmt_Project.getAllProjectsUuid');
  let uuids: unknown;
  try {
    uuids = await settle(getAllUuids());
  } catch (error) {
    problems.push(
      `projects: getAllProjectsUuid failed — ${String((error as Error)?.message ?? error)}`,
    );
    return rows;
  }
  if (!Array.isArray(uuids)) {
    problems.push(`projects: getAllProjectsUuid returned ${typeof uuids}, not an array`);
    return rows;
  }
  const getProjectInfo = requireFn(eda, 'dmt_Project.getProjectInfo');
  for (const raw of uuids) {
    const uuid = String(raw ?? '');
    if (!uuid || uuid === currentIdentity.projectUuid) continue;
    try {
      const info: any = await settle(getProjectInfo(uuid));
      const identity = await projectIdentity(info);
      push(uuid, identity.friendlyName, identity.name, false);
    } catch (error) {
      problems.push(
        `projects: getProjectInfo(${uuid}) failed — ${String((error as Error)?.message ?? error)}`,
      );
    }
  }
  return rows;
}

/**
 * `doc.focus` — put an already-open document on top (012 §五).
 *
 * `activateDocument` takes a **tab id**, and the tab tree is the only place
 * to resolve one from a page uuid: ids in the tree are `"<docUuid>@<hash>"`,
 * so the caller may pass either the full tabId or the document uuid and the
 * match is a prefix test against what the host actually reports. Focusing a
 * document that has no tab is a caller bug — `doc.open` is the one that
 * opens tabs — and is refused rather than silently opened.
 */
export const docFocus: ActionHandler = async (params, eda) => {
  const tabId = typeof params.tabId === 'string' ? params.tabId.trim() : '';
  const uuid = typeof params.pageUuid === 'string' ? params.pageUuid.trim() : '';
  if (!tabId && !uuid) {
    throw new ActionError('BAD_REQUEST', 'doc.focus needs params.tabId or params.pageUuid');
  }
  const tree: any = await settle(requireFn(eda, 'dmt_EditorControl.getSplitScreenTree')());
  const tabs: Array<{ title: string; tabId: string; documentType: unknown }> = [];
  const walk = (item: any): void => {
    if (!item || typeof item !== 'object') return;
    const own = plainGet(item, 'tabs');
    if (Array.isArray(own)) {
      for (const tab of own) {
        tabs.push({
          title: String(plainGet(tab, 'title') ?? ''),
          tabId: String(plainGet(tab, 'tabId') ?? ''),
          documentType: plainGet(tab, 'documentType'),
        });
      }
    }
    const children = plainGet(item, 'children');
    if (Array.isArray(children)) for (const child of children) walk(child);
  };
  walk(tree);
  if (!tabs.length) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'doc.focus: getSplitScreenTree returned no tabs — is any document open?',
    );
  }

  const wanted = tabId || uuid;
  const match = tabs.find((t) => t.tabId === wanted) ??
    tabs.find((t) => t.tabId.startsWith(`${wanted}@`)) ??
    (tabId ? undefined : tabs.find((t) => t.title === wanted));
  if (!match) {
    throw new ActionError(
      'NOT_FOUND',
      `doc.focus: no open tab matches ${wanted} — open it first with doc.open`,
      { wanted, openTabs: tabs.map((t) => t.tabId) },
    );
  }
  const activated = await settle(
    requireFn(eda, 'dmt_EditorControl.activateDocument')(match.tabId),
  );
  return {
    activated: activated === true,
    tabId: match.tabId,
    title: match.title,
    documentType: match.documentType ?? null,
  };
};

/**
 * Carry a project's names through from the open-project index, keeping the read
 * that named it.
 */
function namedOwner(owner: ProjectOwner | null, index: Map<string, ProjectName>): ProjectOwner | null {
  if (!owner?.projectUuid) return null;
  const named = withNames(owner, index) ?? { projectUuid: owner.projectUuid };
  return { ...named, source: owner.source };
}

/**
 * The project the **active document** belongs to (018 §B2 ②).
 *
 * Preferred channel: `getCurrentDocumentInfo().parentProjectUuid`, because it
 * belongs to the very read that names the active document, so the two cannot
 * disagree — and disagreeing is the failure this whole action is about. When
 * the host does not fill that field in, the document's own per-kind read is
 * asked instead ({@link documentOwnerProject}).
 *
 * `null` means neither answered. That is reported as "cannot be determined",
 * never as "no project": a caller deciding whether it is safe to write needs to
 * tell those apart.
 */
async function activeDocumentProject(
  eda: Eda,
  active: ActiveDocumentReading | null,
  index: Map<string, ProjectName>,
  notes: string[],
): Promise<ProjectOwner | null> {
  if (!active) return null;
  if (active.projectUuid) {
    const named = withNames({ projectUuid: active.projectUuid }, index);
    if (named) {
      return {
        ...named,
        source: 'dmt_SelectControl.getCurrentDocumentInfo (parentProjectUuid)',
      };
    }
  }
  const owner = namedOwner(await documentOwnerProject(eda, active.uuid, notes), index);
  if (!owner) {
    notes.push(
      `active document ${active.uuid}: neither getCurrentDocumentInfo.parentProjectUuid `
        + 'nor a per-kind info read named its project',
    );
  }
  return owner;
}

/** Everything that could be established about a uuid the editor would not open. */
type UuidLocation = {
  focused: ProjectName | null;
  active: ActiveDocumentReading | null;
  /** Which project the active document belongs to, when a read can say. */
  activeProject: ProjectName | null;
  owner: ProjectOwner | null;
  /** Is it among the documents `doc.list` lists? `null` when the listing broke. */
  inFocusedListing: boolean | null;
  listingCount: number;
  listingComplete: boolean;
  /** Open tabs whose tab id carries this uuid (`<docUuid>@<hash>`). */
  openTabs: Array<{ tabId: string; title: string }>;
  otherProjects: ProjectName[];
  notes: string[];
};

/**
 * Work out where a uuid `openDocument` refused to open actually lives (018 §B1).
 *
 * The two-layer focus problem (measured 2026-09-21): `doc.list` reported the
 * focused project as one thing while the document in the editor's canvas
 * belonged to another, and `doc.open` — which addresses the pages of the
 * project the editor has open — refused a uuid that plainly existed. The bare
 * "returned no tab id" told the caller nothing it could act on.
 *
 * Every read here is best-effort and guarded: this runs *inside* an error path,
 * so it must never be the thing that replaces a diagnosis with a second
 * failure. Anything it could not establish stays `null` and is named in
 * `notes`.
 */
async function locateUuid(eda: Eda, uuid: string): Promise<UuidLocation> {
  const notes: string[] = [];
  const index = await openProjectIndex(eda, notes);
  const focused = withNames(await focusedProject(eda, notes), index);
  const active = await activeDocument(eda, notes);
  const activeProject = await activeDocumentProject(eda, active, index, notes);
  const owner = namedOwner(await documentOwnerProject(eda, uuid, notes), index);

  // The same listing `doc.list` shows. A read that failed while building it is
  // recorded by `collectDocumentRows` itself, which is what separates "this
  // project has no such document" from "we could not list them".
  const listingProblems: string[] = [];
  const rows = await collectDocumentRows(eda, listingProblems, null);
  notes.push(...listingProblems);
  const hit = rows.find((row) => row.uuid === uuid) ?? null;

  let openTabs: Array<{ tabId: string; title: string }> = [];
  try {
    const tree: any = await settle(requireFn(eda, 'dmt_EditorControl.getSplitScreenTree')());
    openTabs = flattenTabs(tree)
      .map((tab) => ({
        tabId: String(plainGet(tab, 'tabId') ?? ''),
        title: String(plainGet(tab, 'title') ?? ''),
      }))
      // A tab id is `"<documentUuid>@<hash>"` (measured 006c), so a prefix test
      // is what matches a document uuid against the tabs it is open in.
      .filter((tab) => tab.tabId === uuid || tab.tabId.startsWith(`${uuid}@`));
  } catch (error) {
    notes.push(
      `tabs (dmt_EditorControl.getSplitScreenTree): ${String((error as Error)?.message ?? error)}`,
    );
  }

  return {
    focused,
    active,
    activeProject,
    owner,
    inFocusedListing: listingProblems.length ? null : hit !== null,
    listingCount: rows.length,
    listingComplete: listingProblems.length === 0,
    openTabs,
    otherProjects: [...index.values()]
      .filter((project) => project.projectUuid !== focused?.projectUuid),
    notes,
  };
}

/**
 * The sentence the caller needs, built from what {@link locateUuid} established.
 *
 * Every branch states what is *known* and what to do next; none of them
 * pretends to have searched a project whose document tree the API cannot read
 * (`getProjectInfo` is a brief read — see {@link openProjectIndex}), which is
 * why the "nothing found" branch says which projects it was able to search and
 * which it was not.
 */
function describeUuidLocation(uuid: string, location: UuidLocation): string {
  const focusedLabel = projectLabel(location.focused);
  const activeClause = describeActiveDocument(location);
  const owner = location.owner;

  if (owner?.projectUuid) {
    const ownerLabel = projectLabel(owner);
    if (location.focused?.projectUuid === owner.projectUuid) {
      return `it belongs to the focused project ${ownerLabel} (${owner.source}), yet the editor `
        + 'opened no tab — re-read doc.list, and use doc.focus if the document is already open';
    }
    return `this uuid belongs to project ${ownerLabel} (${owner.source}), which is not the project `
      + `the editor has open (focused project: ${focusedLabel}; ${activeClause}); switch the editor `
      + 'to that project first, then retry';
  }

  if (location.openTabs.length > 0) {
    const titles = location.openTabs.map((tab) => `"${tab.title}"`).join(', ');
    return `it is the uuid of an already-open tab (${titles}), so the document exists but the `
      + 'editor did not open a tab for it — try doc.focus with this uuid';
  }

  if (location.inFocusedListing === true) {
    return `it is one of the documents the open project ${focusedLabel} lists, but the editor opened `
      + 'no tab — re-read doc.list before acting on this uuid';
  }

  if (location.listingComplete) {
    const searched = `the focused project ${focusedLabel} lists ${location.listingCount} `
      + 'document(s) and none of them is this uuid';
    const others = location.otherProjects.length
      ? `; the other open projects (${location.otherProjects.map(projectLabel).join(', ')}) cannot be `
        + 'searched, because their document trees are not readable on this API (getProjectInfo is a '
        + 'brief read) — focus one to enumerate it'
      : '';
    return `no document of the project the editor has open is ${uuid} (${searched})${others} `
      + `— ${activeClause}; take the uuid from doc.list`;
  }

  return 'the open project\'s document list could not be read, so it is not possible to say whether '
    + `${uuid} exists — re-read doc.list, and check the connector log for the failed enumeration`;
}

/**
 * One clause naming the active document and the project it belongs to.
 *
 * Both halves come from the `document.current` channel — the active document
 * from `getCurrentDocumentInfo`, its project from that read's
 * `parentProjectUuid` (or the document's own per-kind read). Kept apart from
 * the focused project on purpose: a message that named only the focused project
 * would state the very thing that is in doubt.
 */
function describeActiveDocument(location: UuidLocation): string {
  const active = location.active;
  if (!active) return 'no document is focused in the editor';
  const where = location.activeProject ? ` (project ${projectLabel(location.activeProject)})` : '';
  return `the active document is ${active.uuid}${where}`;
}

/**
 * `doc.open` — focus a document by uuid, so later actions land where intended.
 *
 * `dmt_EditorControl.openDocument(uuid)` is the real entry (`@public`) and
 * accepts a schematic, a schematic **page** or a PCB uuid, returning the tab
 * id it opened. `activateDocument` takes that *tab id*, not a document uuid —
 * so it is the second half of the same move, not an alternative. Both are
 * @public on this build, which is why nothing here is emulated.
 *
 * The failure path is not a bare "no tab id" (018 §B1). `openDocument` is
 * scoped to the project the editor has open, so the question "why is my uuid
 * not here?" almost always has an answer that can be read off the editor: the
 * uuid belongs to a *different* project, or it is already open in a tab, or the
 * listing does not have it at all. The error carries that diagnosis, and the
 * raw readings in `detail`, so a caller can act instead of guessing.
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
    // The diagnosis must never turn a clear error into an unclear one: if it
    // throws for any reason, the original message stands.
    let location: UuidLocation | null = null;
    try {
      location = await locateUuid(eda, uuid);
    } catch {
      // The diagnosis failed. That is not the caller's problem to solve, and
      // the original failure — the one that is certainly true — is reported.
      location = null;
    }
    const why = location ? describeUuidLocation(uuid, location) : 'the reason could not be read';
    throw new ActionError(
      'CONNECTOR_ERROR',
      `openDocument(${uuid}) returned no tab id — ${why}`,
      location
        ? {
            uuid,
            focusedProject: location.focused,
            activeDocument: location.active,
            uuidBelongsTo: location.owner,
            inFocusedProjectListing: location.inFocusedListing,
            listingCount: location.listingCount,
            openTabs: location.openTabs,
            otherProjects: location.otherProjects,
            ...(location.notes.length ? { notes: location.notes } : {}),
          }
        : { uuid, diagnosisError: true },
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
 * `sys.identity` — the editor's two identity layers, and whether they agree
 * (018 §B2).
 *
 * Why a separate read-only action rather than a note on `document.current`: the
 * question being answered is not "what is open" but "**is what is open the
 * thing I think I am writing to?**". Two layers exist, and they are not the
 * same thing:
 *
 * - **`doc.list`'s `focused` project** — `dmt_Project.getCurrentProjectInfo`,
 *   which the type package documents as the project of the schematic / PCB /
 *   panel that holds the last *input* focus;
 * - **the active document** — `dmt_SelectControl.getCurrentDocumentInfo`, plus
 *   its `parentProjectUuid`, which says which project that document is in.
 *
 * Measured 2026-09-21 they disagreed: `doc.list` named one project as focused
 * while the document in front belonged to another, and `doc.open` — scoped to
 * the project the editor has open — then refused a uuid that existed. A caller
 * about to write therefore has to be able to ask this before acting, and get a
 * third value — `consistent` — that is `null` rather than `true` when the
 * comparison cannot be made at all. "The check passed" and "the check could not
 * run" must never look alike here.
 *
 * Read-only in the strict sense: nothing is opened, focused or written; the
 * parameters are ignored.
 */
export const sysIdentity: ActionHandler = async (_params, eda) => {
  const notes: string[] = [];
  const index = await openProjectIndex(eda, notes);
  const focused = withNames(await focusedProject(eda, notes), index);
  const active = await activeDocument(eda, notes);
  const activeProject = await activeDocumentProject(eda, active, index, notes);

  // The comparison itself, and *how* it was made. Three bases, because they are
  // worth different amounts of confidence: two project uuids that were both
  // read (strong), the focused project's own document listing (weaker — it can
  // only confirm membership), or nothing at all.
  let consistent: boolean | null = null;
  let consistentBasis = 'unavailable';
  if (active === null) {
    consistentBasis = 'no-active-document';
  } else if (activeProject?.projectUuid && focused?.projectUuid) {
    consistent = activeProject.projectUuid === focused.projectUuid;
    consistentBasis = 'project-uuid';
  } else if (focused?.projectUuid) {
    // The document did not name its project. The one listing that can be read
    // is the focused project's, and it is only worth an answer when all three
    // of its enumerations succeeded — a partial listing would report "not in
    // this project" for a document that simply was not listed.
    const listingProblems: string[] = [];
    const rows = await collectDocumentRows(eda, listingProblems, active.uuid);
    notes.push(...listingProblems);
    if (listingProblems.length === 0) {
      consistent = rows.some((row) => row.uuid === active.uuid);
      consistentBasis = 'focused-project-listing';
    } else {
      notes.push(
        'the active document did not name its project and the focused project\'s listing was '
          + 'incomplete, so the two layers cannot be compared',
      );
    }
  }

  return {
    focusedProject: focused,
    activeDocument: active
      ? { ...active, project: activeProject }
      : null,
    consistent,
    consistentBasis,
    pageUuid: active?.uuid ?? null,
    readOnly: true,
    ...(notes.length ? { notes } : {}),
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
 * `sch.place_wire`'s retry budget — and why it is these two numbers.
 *
 * The editor rejects `sch_PrimitiveWire.create` **synchronously** while a
 * post-netlist lock window is open (measured 2026-09-18, host 3.2.186, pro-api
 * 0.3.18, connector 0.4.4): inside the window `create` throws `create failed!`
 * in 1-3 ms, while the *same* call with the *same* arguments succeeds before
 * the probe and again about five seconds after it. The audit timeline of the
 * run that found it (`~/.boardwise/audit/2026-09-18.jsonl`) reads
 * `place_component x3 OK -> doc.save 46ms -> netlist 4933ms -> place_wire x10
 * BAD (1-2ms each) -> place_power x3 OK`. The draw flow validates the page
 * *before* it wires, so every wire of a 10-run block met the window head-on;
 * the flags survived the same window by accident, each one spending 1.4-3.0 s
 * resolving a library glyph.
 *
 * A retry is the right answer for *this* failure because it is a rejection,
 * not a write that half-landed: the same arguments land a clean wire moments
 * later. Contrast `sch.place_netlabel` below, where the call can hang **and**
 * land, so a blind retry there would stack duplicate markers.
 *
 * The budget sits above the window the probe measured (closed before +5 s) and
 * well under the daemon's 30 s `ACTION_TIMEOUT`, so the connector's own answer
 * — not a daemon-side hang-up — is what reaches the caller.
 *
 * Only `sch.place_wire` is retried. Its siblings in the same family
 * (`place_netlabel` / `place_text` / `place_netport` / `place_power`) have
 * **not** been probed against the window, and a retry is only added to a write
 * that was *measured* to fail inside it — so they keep their current behaviour
 * until that audit is run. `place_power` is the one that survived the measured
 * run, but it did so by taking 1.4-3.0 s per flag, which is luck rather than
 * evidence.
 */
const WIRE_CREATE_RETRY_DELAY_MS = 500;
const WIRE_CREATE_RETRY_BUDGET_MS = 10_000;

/** The text a thrown value carries, whether it is an `Error` or a bare value. */
function errorText(error: unknown): string {
  if (error && typeof error === 'object' && 'message' in error) {
    return String((error as { message: unknown }).message);
  }
  return String(error);
}

/**
 * Is this the editor's synchronous `create failed!` rejection?
 *
 * Structural, on the message: the host throws a bare `Error` and its text is
 * the only thing it carries, so there is no `code` to test. The match is on the
 * *whole* message (trimmed, case-insensitive) — exactly the shape the probe
 * pinned — so a different failure that merely mentions the phrase is not
 * retried by accident; anything unrecognised reaches the caller unchanged.
 */
function isCreateRejection(error: unknown): boolean {
  return errorText(error).trim().toLowerCase() === 'create failed!';
}

/**
 * Call `attempt` until it survives {@link isCreateRejection}, or the budget runs out.
 *
 * Only that rejection is retried. A `BAD_REQUEST` about the parameters, or a
 * `NOT_IMPLEMENTED` for an API this editor version does not expose, is thrown
 * on the spot because no amount of waiting fixes it — which is also why the
 * caller resolves `requireFn` *outside* the loop: the point is to retry the
 * window, not the wiring.
 *
 * No attempt starts at or after the budget (`BUDGET - DELAY` is the last start
 * time), so one wire action occupies the daemon's action slot for ~10 s at
 * worst, and the total wall time stays under it plus a single host call. On
 * exhaustion the error carries the attempt count and the elapsed time, because
 * the bare `create failed!` it replaces says neither.
 */
async function withCreateRetry<T>(label: string, attempt: () => T | Promise<T>): Promise<T> {
  const startedAt = Date.now();
  let attempts = 0;
  for (;;) {
    attempts += 1;
    try {
      return await settle(attempt());
    } catch (error) {
      if (!isCreateRejection(error)) throw error;
      const elapsedMs = Date.now() - startedAt;
      if (elapsedMs + WIRE_CREATE_RETRY_DELAY_MS >= WIRE_CREATE_RETRY_BUDGET_MS) {
        throw new ActionError(
          'CONNECTOR_ERROR',
          `${label}: the editor rejected create ${attempts} time(s) over ${elapsedMs} ms `
            + `(retry every ${WIRE_CREATE_RETRY_DELAY_MS} ms, budget `
            + `${WIRE_CREATE_RETRY_BUDGET_MS} ms); last rejection: ${errorText(error)}`,
          {
            attempts,
            elapsedMs,
            retryDelayMs: WIRE_CREATE_RETRY_DELAY_MS,
            budgetMs: WIRE_CREATE_RETRY_BUDGET_MS,
          },
        );
      }
      await new Promise((resolve) => setTimeout(resolve, WIRE_CREATE_RETRY_DELAY_MS));
    }
  }
}

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
 *
 * That same text is also what the post-netlist lock window produces, and by the
 * time the call is made the parameters are already flat, so a rejection here is
 * the window (see {@link WIRE_CREATE_RETRY_DELAY_MS}); the call is therefore
 * retried on that shape alone.
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
  // `requireFn` outside the retry: a missing API cannot start existing, and
  // retrying it would only delay the structured NOT_IMPLEMENTED.
  const create = requireFn(eda, 'sch_PrimitiveWire.create');
  const created: any = await withCreateRetry('sch.place_wire', () => create(flat, net));
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

/**
 * Pose-editing classes, per the offline type package (2026-09-20 read).
 *
 * Each entry maps a class to the pose keys its `modify` property object
 * actually accepts — `SCH_PrimitiveWire.modify` takes a `line`, not a pose,
 * and `PCB_PrimitivePour.modify` has no position at all, so a request naming
 * a primitive of those classes is a structural refusal, not a best effort.
 * `mirror` exists only where the type package declares it (schematic
 * components); passing it elsewhere would be silently dropped or rejected,
 * so it is filtered out per class here. Attribute primitives are absent from
 * both tables (see `SCH_DELETE_CLASSES`): a class the delete flow cannot
 * address must not be movable either, or the two verbs disagree about what
 * exists.
 */
const POSE_CLASSES: Record<string, string[]> = {
  sch_PrimitiveComponent: ['x', 'y', 'rotation', 'mirror'],
  sch_PrimitiveText: ['x', 'y', 'rotation'],
  sch_PrimitivePin: ['x', 'y', 'rotation'],
  pcb_PrimitiveComponent: ['x', 'y', 'rotation'],
  pcb_PrimitiveVia: ['x', 'y'],
  pcb_PrimitivePad: ['x', 'y', 'rotation'],
};

/**
 * Classes the delete actions dispatch to. `sch_PrimitiveAttribute` is
 * **excluded on purpose**: its type-package `delete()` takes no primitive id
 * (`delete(): boolean` — it deletes whatever the editor has selected), so it
 * cannot be addressed the way this contract requires; a probe of it is a
 * measurement of a different operation. Everything else here declares
 * `delete(primitiveIds: string | string[])`.
 */
const SCH_DELETE_CLASSES = [
  'sch_PrimitiveComponent',
  'sch_PrimitiveWire',
  'sch_PrimitiveText',
  'sch_PrimitivePin',
];
const PCB_DELETE_CLASSES = [
  'pcb_PrimitiveComponent',
  'pcb_PrimitiveLine',
  'pcb_PrimitiveVia',
  'pcb_PrimitivePad',
  'pcb_PrimitivePour',
];

/**
 * One `getAllPrimitiveId()` per class, joined into an id -> class index.
 *
 * The enumeration is the *authority* on what a page holds: an id absent from
 * the index is `notFound` in the caller's report, and a class whose namespace
 * or `getAllPrimitiveId` is missing fails the whole action structurally —
 * a half-built index would dress "the API is gone" up as "the id was wrong".
 */
async function buildIdIndex(
  eda: Eda,
  classes: string[],
  action: string,
): Promise<Map<string, string>> {
  const index = new Map<string, string>();
  for (const ns of classes) {
    const getAllIds = requireFn(eda, `${ns}.getAllPrimitiveId`);
    let ids: unknown;
    try {
      ids = await settle(getAllIds());
    } catch (error) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `${action}: enumerating ${ns}.getAllPrimitiveId failed — ${String(
          (error as Error)?.message ?? error,
        )}`,
        { namespace: ns },
      );
    }
    if (!Array.isArray(ids)) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `${action}: ${ns}.getAllPrimitiveId returned ${typeof ids}, not an array`,
        { namespace: ns },
      );
    }
    for (const id of ids) {
      const key = String(id);
      // First class to claim an id wins: a collision would mean the host
      // handed the same id out twice, which is its bug to confess — and
      // deleting either way hits the same primitive.
      if (!index.has(key)) index.set(key, ns);
    }
  }
  return index;
}

/** PCB-side page guard: same contract as `guardPage`, different document. */
async function guardPcb(eda: Eda, expected: unknown): Promise<void> {
  if (typeof expected !== 'string' || !expected) return;
  const current: any = await settle(
    requireFn(eda, 'dmt_Pcb.getCurrentPcbInfo')(),
  );
  const uuid = plainGet(current, 'uuid');
  if (uuid !== expected) {
    throw new ActionError(
      'PAGE_MISMATCH',
      `the focused PCB is ${uuid == null ? '(none)' : String(uuid)}, not ${expected} — refusing to edit`,
      { expected, actual: uuid == null ? null : String(uuid) },
    );
  }
}

/**
 * Read a primitive's pose off the object `get()` hands back, for the
 * before/after report. Every field is independent: a host that hides one
 * getter yields `null` for that field, not a failed modification.
 */
function readPose(obj: any): { x: unknown; y: unknown; rotation: unknown; mirror: unknown } {
  const read = (name: string): unknown => {
    const viaState = obj ? `getState_${name}` : '';
    if (viaState && typeof obj[viaState] === 'function') {
      try {
        return obj[viaState]();
      } catch {
        return null;
      }
    }
    const plain = plainGet(obj, name);
    return plain === undefined ? null : plain;
  };
  return { x: read('X'), y: read('Y'), rotation: read('Rotation'), mirror: read('Mirror') };
}

/**
 * `sch.delete_primitives` / `pcb.delete_primitives` — delete by id, honestly.
 *
 * `params.pageUuid` is the focused-document guard (a mismatch is a
 * PAGE_MISMATCH refusal); `params.primitiveIds` is a list of primitive ids.
 * The handler builds the page's id index across the dispatch classes, then
 * deletes **one id per host call** — the type package's array form returns a
 * single `boolean` for the whole batch, which cannot report a partial
 * failure, and this contract prefers honest per-id results over batch speed.
 *
 * Returns `{deleted, notFound, failed}`: `deleted` are the ids the host
 * confirmed, `notFound` are ids the page's index never held (including ids
 * of classes the type package cannot address — e.g. schematic attributes,
 * see `SCH_DELETE_CLASSES`), and `failed` carries per-id host refusals. A
 * partial result is a *successful* action; only a broken enumeration or a
 * missing page guard target throws.
 */
function makeDeletePrimitives(classes: string[], label: string): ActionHandler {
  return async (params, eda) => {
    const guard = classes[0].startsWith('sch_') ? guardPage : guardPcb;
    await guard(eda, params.pageUuid);
    const raw = params.primitiveIds;
    if (raw !== undefined && !Array.isArray(raw)) {
      throw new ActionError(
        'BAD_REQUEST',
        `${label} needs params.primitiveIds as an array of primitive ids`,
      );
    }
    const ids = (raw ?? []).map((v) => String(v ?? '')).filter(Boolean);
    if (!ids.length) return { deleted: [], notFound: [], failed: [] };
    const index = await buildIdIndex(eda, classes, label);
    const deleted: string[] = [];
    const notFound: string[] = [];
    const failed: Array<{ id: string; reason: string }> = [];
    for (const id of ids) {
      const ns = index.get(id);
      if (!ns) {
        notFound.push(id);
        continue;
      }
      const del = requireFn(eda, `${ns}.delete`);
      try {
        const ok = await settle(del(id));
        if (ok === true) deleted.push(id);
        else failed.push({ id, reason: `delete returned ${String(ok)}` });
      } catch (error) {
        failed.push({
          id,
          reason: String((error as Error)?.message ?? error),
        });
      }
    }
    return { deleted, notFound, failed };
  };
}

export const schDeletePrimitives = makeDeletePrimitives(
  SCH_DELETE_CLASSES,
  'sch.delete_primitives',
);
export const pcbDeletePrimitives = makeDeletePrimitives(
  PCB_DELETE_CLASSES,
  'pcb.delete_primitives',
);

const POSE_KEYS = ['x', 'y', 'rotation', 'mirror'] as const;

/**
 * Collect the pose fields the caller actually supplied, restricted to what
 * the target class accepts. Returns `null` when nothing applicable was
 * requested — "move it nowhere" is a caller bug, not an edit.
 */
function poseProperty(
  ns: string,
  params: Record<string, unknown>,
): Record<string, unknown> | null {
  const allowed = POSE_CLASSES[ns];
  const out: Record<string, unknown> = {};
  for (const key of POSE_KEYS) {
    if (params[key] === undefined) continue;
    if (!allowed.includes(key)) {
      throw new ActionError(
        'BAD_REQUEST',
        `${ns} has no ${key} in its modify property — its pose is ${allowed.join(', ')}`,
        { namespace: ns, key },
      );
    }
    if (key === 'mirror') out.mirror = params.mirror === true;
    else if (key === 'rotation') {
      const rotation = Number(params.rotation);
      if (!Number.isFinite(rotation)) {
        throw new ActionError('BAD_REQUEST', `rotation must be a number, got ${String(params.rotation)}`);
      }
      out.rotation = rotation;
    } else {
      const coord = Number(params[key]);
      if (!Number.isFinite(coord)) {
        throw new ActionError('BAD_REQUEST', `${key} must be a number, got ${String(params[key])}`);
      }
      out[key] = coord;
    }
  }
  return Object.keys(out).length ? out : null;
}

/**
 * `sch.modify_primitive` / `pcb.modify_primitive` — move / rotate / mirror by
 * id, nothing else.
 *
 * Only pose is exposed on purpose: value/designator edits have
 * `sch.set_component_attribute`, and folding them here would duplicate that
 * gate. The class comes from the page's id index (never guessed), the
 * property keys are filtered through `POSE_CLASSES` — a wire, for instance,
 * has no pose in the type package (`modify` takes a `line`) and naming one
 * is a structural refusal. The action reads the pose before and after the
 * host call and returns both, so the caller can verify what moved without a
 * second read.
 */
function makeModifyPrimitive(label: string, schematic: boolean): ActionHandler {
  return async (params, eda) => {
    if (schematic) await guardPage(eda, params.pageUuid);
    else await guardPcb(eda, params.pageUuid);
    const id = typeof params.primitiveId === 'string' ? params.primitiveId : '';
    if (!id) {
      throw new ActionError('BAD_REQUEST', `${label} needs params.primitiveId`);
    }
    // The index walks the *deletable* classes too, on purpose: a wire exists
    // on the page even though it has no pose, and the honest answer to "move
    // this wire" is "that class cannot be moved", not "no such primitive".
    const deletable = schematic ? SCH_DELETE_CLASSES : PCB_DELETE_CLASSES;
    const classes = [...new Set([...deletable, ...Object.keys(POSE_CLASSES).filter((ns) =>
      schematic ? ns.startsWith('sch_') : ns.startsWith('pcb_'),
    )])];
    const index = await buildIdIndex(eda, classes, label);
    const ns = index.get(id);
    if (!ns) {
      throw new ActionError(
        'NOT_FOUND',
        `${label}: no primitive ${id} on the guarded page`,
        { primitiveId: id },
      );
    }
    if (!POSE_CLASSES[ns]) {
      throw new ActionError(
        'BAD_REQUEST',
        `${label}: ${ns} has no pose semantics in the type package — modify is not a move`,
        { namespace: ns, primitiveId: id },
      );
    }
    const property = poseProperty(ns, params);
    if (!property) {
      throw new ActionError(
        'BAD_REQUEST',
        `${label} needs at least one of x / y / rotation / mirror`,
      );
    }
    const mod = requireFn(eda, `${ns}.modify`);
    const beforeObj: any = await settle(requireFn(eda, `${ns}.get`)(id));
    if (!beforeObj) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `${label}: ${ns}.get(${id}) returned nothing before the modify`,
        { namespace: ns, primitiveId: id },
      );
    }
    const before = readPose(beforeObj);
    const afterObj: any = await settle(mod(id, property));
    if (!afterObj) {
      throw new ActionError(
        'CONNECTOR_ERROR',
        `${label}: the editor refused the modify (${ns} ${JSON.stringify(property)})`,
        { namespace: ns, property },
      );
    }
    const after = readPose(afterObj);
    return { before, after };
  };
}

export const schModifyPrimitive = makeModifyPrimitive('sch.modify_primitive', true);
export const pcbModifyPrimitive = makeModifyPrimitive('pcb.modify_primitive', false);

/**
 * `doc.delete_page` — remove a schematic page by uuid (012 S4).
 *
 * The cleanup half of the scratch-page flow: `sch.doc.new` creates one, work
 * happens on it, and the page itself has to go when the work is done. The
 * uuid must be one the project actually lists — an unknown uuid is NOT_FOUND,
 * never a silent no-op — and the host's own `deleteSchematicPage` decides the
 * rest (it refuses the last page of a schematic, measured behaviour).
 */
export const docDeletePage: ActionHandler = async (params, eda) => {
  const uuid = typeof params.pageUuid === 'string' ? params.pageUuid.trim() : '';
  if (!uuid) {
    throw new ActionError('BAD_REQUEST', 'doc.delete_page needs params.pageUuid');
  }
  const pages = await readDocItems(eda, 'dmt_Schematic.getAllSchematicPagesInfo', []);
  const page = pages.find((item) => plainGet(item, 'uuid') === uuid);
  if (!page) {
    throw new ActionError(
      'NOT_FOUND',
      `doc.delete_page: ${uuid} is not a page of the current project`,
      { pageUuid: uuid, knownPages: pages.map((item) => plainGet(item, 'uuid')) },
    );
  }
  const name = plainGet(page, 'name');
  const deleted = await settle(
    requireFn(eda, 'dmt_Schematic.deleteSchematicPage')(uuid),
  );
  if (deleted !== true) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `the editor refused to delete page ${name ?? uuid}`,
      { pageUuid: uuid },
    );
  }
  return { deleted: true, pageUuid: uuid, name: typeof name === 'string' ? name : '' };
};

// --------------------------------------------------------------------------
// 012 §六: `export.fab` — the fab bundle (Gerber + pick-and-place + BOM)
// --------------------------------------------------------------------------

/**
 * One vendor's gerber arguments, named after the declaration.
 *
 * `getGerberFile(fileName, colorSilkscreen, unit, digitalFormat, other, layers,
 * objects)` is positional, so this object is spread into the call at exactly
 * one place instead of being unpacked by position in several. `unit` stays a
 * plain string because `ESYS_Unit` is a string enum (`MILLIMETER = 'mm'`), so
 * the wire value and the enum value are the same bytes.
 */
type FabGerberArgs = {
  fileName: string;
  colorSilkscreen: boolean;
  unit: string;
  digitalFormat: { integerNumber: number; decimalNumber: number };
  other: {
    metallicDrillingInformation: boolean;
    nonMetallicDrillingInformation: boolean;
    drillTable: boolean;
    flyingProbeTestingFile: boolean;
  };
  layers?: Array<{ layerId: string; isMirror: boolean }>;
  objects?: string[];
};

/** One row of the BOM's column spec (`IPCB_BomPropertiesTableColumns`). */
type FabBomColumn = {
  property: string;
  title: string;
  sort: null | 'asc' | 'desc';
  group: null | 'Yes' | 'No';
  orderWeight: number;
};

type FabVendorPreset = {
  summary: string;
  gerber: FabGerberArgs;
  pickAndPlace: { fileName: string; fileType: 'csv' | 'xlsx'; unit: string };
  bom: {
    fileName: string;
    fileType: 'csv' | 'xlsx';
    filterOptions: Array<{ property: string; includeValue: boolean | string }>;
    statistics: string[];
    columns: FabBomColumn[];
  };
};

/**
 * The BOM's column set — every column a fab house or a buyer reads.
 *
 * **One list**, and both of `getBomFile`'s column arguments are derived from it:
 * the two counting columns become `statistics` and every other column becomes
 * `property`, so the host is told about exactly the columns that are asked for
 * and about none of them twice. Heavier `orderWeight` sorts left, which is the
 * documented meaning. See {@link FAB_BOM_STATISTICS} for why the split is not
 * cosmetic.
 *
 * The names are the component properties *this host* reports (measured in the
 * netlist export, 2026-09-15: `Supplier Part` carries the LCSC code,
 * `Manufacturer Part` the MPN, `JLCPCB Part Class` Basic/Extended), plus the
 * two the type package's own example uses for the counting columns (`No.`,
 * `Quantity`). Whether the host accepts every one of them is a **machine**
 * question — see the manifest note this action attaches; the point of keeping
 * them in one list is that the answer changes one place.
 */
const FAB_BOM_COLUMNS: FabBomColumn[] = [
  { property: 'No.', title: '序号', sort: 'asc', group: null, orderWeight: 100 },
  { property: 'Designator', title: '位号', sort: 'asc', group: 'No', orderWeight: 90 },
  { property: 'Quantity', title: '数量', sort: 'desc', group: 'Yes', orderWeight: 80 },
  { property: 'Value', title: '值', sort: 'asc', group: 'Yes', orderWeight: 70 },
  { property: 'Name', title: '器件名称', sort: 'asc', group: 'Yes', orderWeight: 60 },
  { property: 'Device', title: '器件', sort: null, group: 'Yes', orderWeight: 55 },
  { property: 'Footprint', title: '封装', sort: null, group: 'Yes', orderWeight: 50 },
  { property: 'Manufacturer Part', title: '制造商料号', sort: null, group: 'Yes', orderWeight: 40 },
  { property: 'Manufacturer', title: '制造商', sort: null, group: 'Yes', orderWeight: 35 },
  { property: 'Supplier Part', title: '立创编号', sort: null, group: 'Yes', orderWeight: 30 },
  { property: 'Supplier', title: '供应商', sort: null, group: 'Yes', orderWeight: 25 },
  { property: 'Supplier Footprint', title: '供应商封装', sort: null, group: 'Yes', orderWeight: 20 },
  { property: 'JLCPCB Part Class', title: 'JLC 类别', sort: null, group: 'Yes', orderWeight: 15 },
  { property: 'Datasheet', title: '数据手册', sort: null, group: 'Yes', orderWeight: 10 },
  { property: 'Description', title: '描述', sort: null, group: 'Yes', orderWeight: 5 },
];

/**
 * The columns the BOM API takes as **statistics** rather than as attributes.
 *
 * The declaration has two arguments for one column set, and the host's
 * implementation is why the two are not interchangeable: `statistics` entries go
 * through `hne`, which rewrites `'No.'` into the `'Number'` column the BOM
 * engine numbers, while a `property` entry keeps the literal `'No.'`. The host
 * then builds the table from `statistics + property` and does **not**
 * deduplicate (`api.js` `getBomFile`) — so sending the counting columns in both
 * arguments produced a **17-column header for a 15-column preset** (measured
 * 2026-09-21): `序号`/`Number` and `数量`/`Quantity` each arrived twice.
 *
 * Dropping `statistics` instead would be worse than untidy: the column pass
 * refuses the whole call when a column's property is in neither list
 * (`p.includes(m.property) … else return`), and `'No.'` only becomes `'Number'`
 * — the value that pass looks for — on this path. No `statistics`, no BOM file
 * at all.
 */
const FAB_BOM_STATISTICS = ['No.', 'Quantity'];

/**
 * The `property` argument: the columns that are attributes, in column order.
 *
 * Derived from {@link FAB_BOM_COLUMNS} rather than written out, and kept
 * **disjoint** from {@link FAB_BOM_STATISTICS}: the union of the two is exactly
 * the columns the preset asks for, which is the check the host runs for every
 * column it is handed, and neither list repeats an entry of the other.
 */
const FAB_BOM_PROPERTY = FAB_BOM_COLUMNS
  .map((column) => column.property)
  .filter((property) => !FAB_BOM_STATISTICS.includes(property));

/**
 * Vendor presets, keyed by the `vendor` parameter.
 *
 * `generic` is the only one with a preset (012v2 §六): metric 4:5 gerber with
 * the drill table on, a CSV pick-and-place in millimetres, and a CSV BOM with
 * every column. **`colorSilkscreen: false`** because the coloured silkscreen
 * file is a JLC-specific extra ("嘉立创专用文件" in the declaration) that other
 * fab houses do not want in the zip.
 *
 * `layers`/`objects` are deliberately **absent** from the gerber preset: their
 * declared default is the editor's own one-click export set (the layers the
 * board really uses, plus the drill layers), which is what a fab house expects.
 * Pinning an explicit layer list here without a machine run would be a guess
 * dressed as a decision; `params.gerber.layers` overrides it when a vendor
 * wants an exact list.
 */
const FAB_VENDORS: Record<string, FabVendorPreset> = {
  generic: {
    summary: 'generic fab house: metric 4:5 gerber (drill table on), CSV P&P in mm, CSV BOM with every column',
    gerber: {
      // The name carries its own suffix because the host echoes this string
      // back as the file's name (`api.js`: `new File([data], t || c.fileName)`)
      // — a bare `fab_gerber` reached disk with no extension at all (measured
      // 2026-09-21).
      fileName: 'fab_gerber.zip',
      colorSilkscreen: false,
      unit: 'mm',
      digitalFormat: { integerNumber: 4, decimalNumber: 5 },
      other: {
        metallicDrillingInformation: true,
        nonMetallicDrillingInformation: true,
        drillTable: true,
        flyingProbeTestingFile: false,
      },
    },
    // Same echo as the gerber name — `new File([blobData], r)` — so the suffix
    // has to be here too.
    pickAndPlace: { fileName: 'fab_pick_and_place.csv', fileType: 'csv', unit: 'mm' },
    bom: {
      // No suffix here, unlike the other two: this is the one name the host
      // makes itself (`new File([data], fileName + '.' + fileType)`), so
      // `fab_bom` lands as `fab_bom.csv`. Putting `.csv` here would produce
      // `fab_bom.csv.csv` (measured 2026-09-21).
      fileName: 'fab_bom',
      fileType: 'csv',
      // `includeValue` is the value the host filters **against** — the rule
      // leaves a row *out* when the part's property matches it. That is the
      // opposite of what the parameter's name suggests, and the type package's
      // own example (`includeValue: 'yes'`) therefore drops every part that is
      // in the BOM: with it, the 122-component board came back as a
      // header-only CSV (measured on 2026-09-21). `'no'` is the editor's own
      // default for this rule and keeps them.
      //
      // Evidence, all from the host's own code shipped in D:/lceda-pro: the
      // wrapper maps our entries onto `filterRules`
      // (`api.js` `mne`/`gne`, which also coerces any value but `'yes'` to
      // `'no'`), and the BOM builder drops a row whenever the rule matches
      // (`pro-sch` `attrsGroup2` → `verify`, `if (... n.test(e[t])) return
      // false`). `api.js` starts from `[{attr:'Add into BOM', rule:'no',
      // checked:true}, {attr:'Convert to PCB', rule:'no', checked:false}]`.
      //
      // One rule, not two: "Convert to PCB" is left unchecked by the host's own
      // default, because on a PCB-side BOM every part is on the board by
      // construction — the row it would drop is not the row a fab house reads.
      filterOptions: [{ property: 'Add into BOM', includeValue: 'no' }],
      // The counting columns go here and nowhere else, and every other column
      // goes in the `property` argument derived from `FAB_BOM_COLUMNS` — sending
      // one column in both is what doubled the header (see
      // {@link FAB_BOM_STATISTICS}).
      statistics: FAB_BOM_STATISTICS,
      columns: FAB_BOM_COLUMNS,
    },
  },
};

/**
 * Vendors the catalogue reserves a slot for but has no preset for yet.
 *
 * Kept apart from the preset table so a caller asking for one gets "the slot
 * exists, the preset does not" instead of "unknown vendor" — the two are
 * different facts and the second one would be a lie (012v2 §六: 捷配留配置位).
 */
const FAB_PENDING_VENDORS: Record<string, string> = {
  jiepei: 'the 捷配 preset is a reserved slot: it needs a sample BOM/template from 岳 before its columns can be written (012v2 open question)',
};

/** `ESYS_Unit`'s declared members, for validating a `unit` override. */
const FAB_UNITS = ['mm', 'cm', 'dm', 'm', 'inch', 'in', 'mil'];

/** Keys `params.gerber` may override — anything else is a typo, not a setting. */
const FAB_GERBER_OVERRIDE_KEYS = [
  'fileName', 'colorSilkscreen', 'unit', 'digitalFormat', 'other', 'layers', 'objects',
];

/**
 * Keys `params.bom` may override, under the same allowlist discipline.
 *
 * One key wide, and for a measured reason: `filterOptions` is the argument whose
 * meaning the declaration gets wrong (see the preset's comment), so a caller
 * with a different BOM rule — or one measuring this host — needs a way to say
 * so without a rebuild. `null` is the third value and means "send nothing at
 * all", which is not the same as `[]`: the host then keeps its own default
 * rules rather than being handed an empty list that happens to look the same.
 * The list grows when a caller has a reason; it does not grow to be symmetric
 * with `params.gerber`.
 */
const FAB_BOM_OVERRIDE_KEYS = ['filterOptions'];

/**
 * Per-file deadline for the three export calls.
 *
 * Same lesson as `export.render`: the host **drops an argument it dislikes
 * without rejecting**, so the awaited promise never settles and the action slot
 * is held forever. Each of the three calls therefore races its own deadline and
 * reports a per-file `TIMEOUT`; the other two files still come back. 60 s is
 * the editor's own "export manufacture data" order of magnitude for a small
 * board, and the daemon's `FAB_TIMEOUT` (240 s) sits above 3 × this.
 */
const FAB_CALL_TIMEOUT_MS = 60_000;

/** The payload for one fab file, as the wire carries it. */
type FabFilePayload = {
  role: string;
  name: string;
  mime: string;
  bytes: number;
  data: string;
  sourceName: string;
};

/**
 * Race one host call against a deadline, failing with a typed TIMEOUT.
 *
 * Used by every host call in this section, because they share the failure the
 * `export.render` probe found: an argument the host dislikes is *dropped*, not
 * rejected, so the promise never settles and the action slot is held until the
 * daemon gives up — an answer nobody can act on, instead of a named failure.
 * `hint` carries what the caller should do about it.
 */
function raceHostCall<T>(call: Promise<T>, label: string, ms: number, hint = ''): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(
      () =>
        reject(
          new ActionError(
            'TIMEOUT',
            `${label} did not settle within ${ms} ms — the host swallowed the request `
              + `instead of rejecting it${hint ? `; ${hint}` : ''}`,
            { call: label, timeoutMs: ms },
          ),
        ),
      ms,
    );
    call.then(
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

/**
 * `base` with `ext`, unless it already ends in it.
 *
 * The three files are not named the same way (measured 2026-09-21): gerber and
 * pick-and-place echo back the name they were handed, while the BOM's is the
 * host's own `fileName + '.' + fileType`. The preset names therefore carry their
 * suffixes, and this guard is what keeps a host that ever appends on its own
 * from producing `fab_bom.csv.csv`.
 */
function withSuffix(base: string, ext: string): string {
  return base.toLowerCase().endsWith(ext.toLowerCase()) ? base : `${base}${ext}`;
}

/**
 * A host `File` as base64 + metadata, or a thrown reason.
 *
 * A zero-byte file is a *failure*, not a small file: the editor answers with an
 * empty File when there is nothing to export, and handing that to a fab house
 * as a successful export is exactly the shape of error this project keeps
 * paying for. The bytes are also sniffed for the zip magic so a gerber export
 * that came back as an archive is named `.zip` instead of `.png`-style lies.
 */
async function readFabFile(
  file: any, role: string, base: string, ext: string, fallbackMime: string,
): Promise<FabFilePayload> {
  const arrayBuffer = readMember(file, 'arrayBuffer').value;
  if (typeof arrayBuffer !== 'function') {
    throw new Error('the returned file has no arrayBuffer() — its bytes cannot be read');
  }
  const bytes = new Uint8Array(await arrayBuffer.call(file));
  if (bytes.byteLength === 0) throw new Error('the editor returned an empty file');
  const zip = bytes.length > 1 && bytes[0] === 0x50 && bytes[1] === 0x4b;
  const given = readMember(file, 'name').value;
  // Path separators are stripped: this name becomes a path on the writing side,
  // and a host-provided name must never be able to climb out of `outDir`.
  const sourceName = typeof given === 'string' ? given.replace(/[\\/]+/g, '_').trim() : '';
  const type = readMember(file, 'type').value;
  return {
    role,
    name: sourceName || withSuffix(base, zip ? '.zip' : ext),
    mime: typeof type === 'string' && type ? type : fallbackMime,
    bytes: bytes.byteLength,
    data: bytesToBase64(bytes),
    sourceName,
  };
}

/**
 * `export.fab` — Gerber + pick-and-place + BOM in one call, plus the manifest.
 *
 * Why one action and not three: the three files are only useful together (a fab
 * house rejects a submission with a mismatched or missing piece), and one call
 * means one guard, one project/pcb stamp and one manifest for the set.
 *
 * **The connector does not write to `outDir`, and that is a measured limit, not
 * a shortcut.** The declaration offers `sys_FileSystem.saveFile(fileData,
 * fileName?)` — no directory argument; it goes through the browser download /
 * Electron save dialog, so it cannot honour a path. The reliable path is the
 * one `export.render` already uses: hand the bytes back as base64 and let the
 * caller (the daemon-side CLI) write them. `outDir` is therefore carried in the
 * parameters and recorded in the manifest, and the CLI is what creates it.
 *
 * Honest partial results: a file the host refuses, returns empty, or hangs on
 * is reported in `failed` while the others still come back (`partial: true`).
 * Only a *structural* absence throws — the namespace or one of the three
 * declared methods missing — and so does "all three failed", because an empty
 * bundle is not a bundle.
 *
 * **What the host actually does with the preset, measured 2026-09-21 on
 * 3.2.186** — this is why `params.bom` exists at all: the BOM's `filterOptions`
 * are *exclusion* rules (`includeValue` is the value that leaves a row out, so
 * the type package's own `'yes'` example exports an empty BOM — see the preset),
 * and the three names are not chosen the same way (gerber and P&P echo the name
 * they are handed, the BOM's is the host's own `fileName + '.' + fileType`).
 */
export const exportFab: ActionHandler = async (params, eda) => {
  const vendor = String(params?.vendor ?? 'generic').trim().toLowerCase();
  const preset = FAB_VENDORS[vendor];
  if (!preset) {
    const pending = FAB_PENDING_VENDORS[vendor];
    throw new ActionError(
      'BAD_REQUEST',
      pending
        ? `export.fab has no preset for vendor ${JSON.stringify(vendor)} yet — ${pending}`
        : `export.fab needs params.vendor to be one of ${Object.keys(FAB_VENDORS).join(' | ')} `
          + `(known-but-unimplemented: ${Object.keys(FAB_PENDING_VENDORS).join(', ') || 'none'}; `
          + `got ${JSON.stringify(params?.vendor)})`,
      { vendor, known: Object.keys(FAB_VENDORS), pending: Object.keys(FAB_PENDING_VENDORS) },
    );
  }
  const outDir = typeof params?.outDir === 'string' ? params.outDir.trim() : '';
  if (!outDir) {
    throw new ActionError(
      'BAD_REQUEST',
      'export.fab needs params.outDir — the directory the caller writes the bundle into. '
        + 'The connector only *records* it: no declared API takes a destination directory '
        + '(SYS_FileSystem.saveFile(fileData, fileName?) has none), so the daemon-side CLI does the write.',
    );
  }
  const timeoutMs = Number.isFinite(Number(params?.timeoutMs))
    ? Math.min(Math.max(Number(params?.timeoutMs), 200), 600_000)
    : FAB_CALL_TIMEOUT_MS;

  // --- params.gerber: an allowlist, so a typo fails instead of being ignored.
  const overrides: Record<string, unknown> = {};
  if (params?.gerber !== undefined) {
    if (!params.gerber || typeof params.gerber !== 'object' || Array.isArray(params.gerber)) {
      throw new ActionError('BAD_REQUEST', 'export.fab params.gerber must be an object of gerber overrides');
    }
    for (const [key, value] of Object.entries(params.gerber as Record<string, unknown>)) {
      if (!FAB_GERBER_OVERRIDE_KEYS.includes(key)) {
        throw new ActionError(
          'BAD_REQUEST',
          `export.fab params.gerber has an unknown key ${JSON.stringify(key)} — `
            + `allowed: ${FAB_GERBER_OVERRIDE_KEYS.join(', ')}`,
          { key, allowed: FAB_GERBER_OVERRIDE_KEYS },
        );
      }
      overrides[key] = value;
    }
    if (overrides.unit !== undefined
      && !(typeof overrides.unit === 'string' && FAB_UNITS.includes(overrides.unit))) {
      throw new ActionError(
        'BAD_REQUEST',
        `export.fab params.gerber.unit must be one of ${FAB_UNITS.join(' | ')} `
          + `(got ${JSON.stringify(overrides.unit)})`,
      );
    }
    const format = overrides.digitalFormat;
    if (format !== undefined && !(
      format && typeof format === 'object' && !Array.isArray(format)
      && Number.isFinite(Number((format as Record<string, unknown>).integerNumber))
      && Number.isFinite(Number((format as Record<string, unknown>).decimalNumber))
    )) {
      throw new ActionError(
        'BAD_REQUEST',
        'export.fab params.gerber.digitalFormat must be {integerNumber, decimalNumber} '
          + `(got ${JSON.stringify(format)})`,
      );
    }
    if (overrides.colorSilkscreen !== undefined && typeof overrides.colorSilkscreen !== 'boolean') {
      throw new ActionError('BAD_REQUEST', 'export.fab params.gerber.colorSilkscreen must be a boolean');
    }
    for (const key of ['other', 'layers', 'objects']) {
      if (overrides[key] === undefined || overrides[key] === null) continue;
      const shape = key === 'other' ? 'an object' : 'an array';
      if (typeof overrides[key] !== 'object' || Array.isArray(overrides[key]) !== (key !== 'other')) {
        throw new ActionError(
          'BAD_REQUEST', `export.fab params.gerber.${key} must be ${shape}`,
        );
      }
    }
  }
  // --- params.bom: same allowlist. `filterOptions: null` means "send nothing",
  // which leaves the host on its own default rules.
  let bomFilters: FabVendorPreset['bom']['filterOptions'] | undefined = preset.bom.filterOptions;
  const bomOverrides: Record<string, unknown> = {};
  if (params?.bom !== undefined) {
    if (!params.bom || typeof params.bom !== 'object' || Array.isArray(params.bom)) {
      throw new ActionError('BAD_REQUEST', 'export.fab params.bom must be an object of BOM overrides');
    }
    for (const [key, value] of Object.entries(params.bom as Record<string, unknown>)) {
      if (!FAB_BOM_OVERRIDE_KEYS.includes(key)) {
        throw new ActionError(
          'BAD_REQUEST',
          `export.fab params.bom has an unknown key ${JSON.stringify(key)} — `
            + `allowed: ${FAB_BOM_OVERRIDE_KEYS.join(', ')}`,
          { key, allowed: FAB_BOM_OVERRIDE_KEYS },
        );
      }
      bomOverrides[key] = value;
    }
    if ('filterOptions' in bomOverrides) {
      const filters = bomOverrides.filterOptions;
      if (filters === null) {
        bomFilters = undefined;
      } else if (Array.isArray(filters) && filters.every((entry) => (
        entry && typeof entry === 'object' && !Array.isArray(entry)
        && typeof (entry as Record<string, unknown>).property === 'string'
        && ((entry as Record<string, unknown>).property as string).trim() !== ''
        && ['string', 'boolean'].includes(typeof (entry as Record<string, unknown>).includeValue)
      ))) {
        bomFilters = filters as FabVendorPreset['bom']['filterOptions'];
      } else {
        throw new ActionError(
          'BAD_REQUEST',
          'export.fab params.bom.filterOptions must be null (send none — the host keeps its own '
            + 'default rules), or an array of {property: string, includeValue: string | boolean} '
            + `(got ${JSON.stringify(filters)})`,
        );
      }
    }
  }
  const gerberArgs: FabGerberArgs = { ...preset.gerber, ...(overrides as Partial<FabGerberArgs>) };
  const bomTemplate = typeof params?.bomTemplate === 'string' && params.bomTemplate.trim()
    ? params.bomTemplate.trim()
    : undefined;

  // --- the host surface, checked before anything is called.
  const mfg = namespaceOf(eda, 'pcb_ManufactureData');
  const calls = ['getGerberFile', 'getPickAndPlaceFile', 'getBomFile'] as const;
  for (const name of calls) {
    if (typeof readMember(mfg, name).value !== 'function') {
      throw new ActionError(
        'NOT_IMPLEMENTED',
        `pcb_ManufactureData.${name} is not available on this editor build`,
        { path: `pcb_ManufactureData.${name}` },
      );
    }
  }

  // --- which board: the guard is the same one the writes use, because
  // "which PCB is in front" decides which board is exported.
  const pcbInfo: any = await settle(requireFn(eda, 'dmt_Pcb.getCurrentPcbInfo')());
  const focusedUuid = (await infoUuid(pcbInfo)) ?? '';
  const requested = typeof params?.pcbUuid === 'string' ? params.pcbUuid.trim() : '';
  if (requested && focusedUuid !== requested) {
    throw new ActionError(
      'PAGE_MISMATCH',
      `the focused PCB is ${focusedUuid || '(none)'}, not ${requested} — refusing to export. `
        + 'The manufacture APIs export the board that is in front; open it first (doc.open).',
      { expected: requested, actual: focusedUuid || null },
    );
  }
  if (!focusedUuid) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      'no PCB is open in the focused project — export.fab exports the focused board '
        + '(open it with doc.open, or pass pcbUuid once it is in front)',
      { requested: requested || null },
    );
  }
  const pcbName = pcbInfo ? String(plainGet(pcbInfo, 'name') ?? plainGet(pcbInfo, 'friendlyName') ?? '') : '';

  // --- the manifest's project stamp. A missing project read is recorded, not
  // fatal: the files themselves are what the caller came for.
  let project: { uuid: string; name: string } = { uuid: '', name: '' };
  const notes: string[] = [];
  try {
    const info: any = await settle(requireFn(eda, 'dmt_Project.getCurrentProjectInfo')());
    project = {
      uuid: (await infoUuid(info)) ?? '',
      name: String(plainGet(info, 'friendlyName') ?? plainGet(info, 'name') ?? ''),
    };
  } catch (error) {
    notes.push(`project info unreadable: ${String((error as Error)?.message ?? error)}`);
  }

  const files: FabFilePayload[] = [];
  const failed: Array<{ role: string; reason: string }> = [];
  const record = async (
    role: string, base: string, ext: string, mime: string, call: () => Promise<any>,
  ): Promise<void> => {
    let file: any;
    try {
      file = await raceHostCall(
        settle(call()),
        `${role} export`,
        timeoutMs,
        'the editor may show a stuck export progress toast — reload the document to clear it',
      );
    } catch (error) {
      failed.push({
        role,
        reason: isActionError(error)
          ? `${error.code}: ${error.message}`
          : String((error as Error)?.message ?? error),
      });
      return;
    }
    if (!file) {
      failed.push({
        role,
        reason: 'the editor returned no file — is the exported board the one that is open, and does it have content?',
      });
      return;
    }
    try {
      files.push(await readFabFile(file, role, base, ext, mime));
    } catch (error) {
      failed.push({ role, reason: String((error as Error)?.message ?? error) });
    }
  };

  await record('gerber', preset.gerber.fileName, '.zip', 'application/zip', () =>
    mfg.getGerberFile.call(
      mfg,
      gerberArgs.fileName,
      gerberArgs.colorSilkscreen,
      gerberArgs.unit,
      gerberArgs.digitalFormat,
      gerberArgs.other,
      gerberArgs.layers,
      gerberArgs.objects,
    ));
  await record('pick_and_place', preset.pickAndPlace.fileName, `.${preset.pickAndPlace.fileType}`,
    'text/csv', () =>
      mfg.getPickAndPlaceFile.call(
        mfg,
        preset.pickAndPlace.fileName,
        preset.pickAndPlace.fileType,
        preset.pickAndPlace.unit,
      ));
  await record('bom', preset.bom.fileName, `.${preset.bom.fileType}`, 'text/csv', () =>
    mfg.getBomFile.call(
      mfg,
      preset.bom.fileName,
      preset.bom.fileType,
      bomTemplate,
      bomFilters,
      preset.bom.statistics,
      FAB_BOM_PROPERTY,
      preset.bom.columns,
    ));

  if (files.length === 0) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `none of the three fab files came back (${failed.map((f) => `${f.role}: ${f.reason}`).join('; ')})`,
      { failed, pcbUuid: focusedUuid, timeoutMs },
    );
  }

  const builtAt = new Date().toISOString();
  const manifest = {
    schema: 'boardwise.fab/1',
    generatedAt: builtAt,
    vendor,
    vendorSummary: preset.summary,
    project,
    pcb: { uuid: focusedUuid, name: pcbName },
    outDir,
    preset: {
      gerber: gerberArgs,
      pickAndPlace: preset.pickAndPlace,
      bom: {
        ...preset.bom,
        // The filters that were actually sent (`null` = none: the host kept its
        // own default rules), not the preset's, so a bundle found on disk later
        // says what produced it.
        filterOptions: bomFilters ?? null,
        template: bomTemplate ?? null,
        // The `property` argument as sent — `statistics` (spread from the preset
        // above) and this list are disjoint, and their union is `columns`.
        property: FAB_BOM_PROPERTY,
      },
      overrides: [
        ...Object.keys(overrides),
        // A `bom` key is prefixed: both groups have a `filterOptions`-shaped
        // future, and two bare names would be indistinguishable in a manifest.
        ...Object.keys(bomOverrides).map((key) => `bom.${key}`),
      ].sort(),
    },
    files: files.map((file) => ({
      role: file.role, name: file.name, mime: file.mime, bytes: file.bytes,
    })),
    failed,
    notes: [
      ...notes,
      'measured 2026-09-21 on 3.2.186: exactly the 15 BOM column names come back in the header, '
      + 'the two counting columns travelling as `statistics` and the other 13 as `property` '
      + '(sending them in both produced a 17-column header — see the preset), the BOM filter rule '
      + 'is an *exclusion* one — `includeValue` is the value that leaves a row out, not the one it '
      + 'keeps — and this host names the BOM file itself (`fileName + "." + fileType`) while '
      + 'gerber/P&P echo the name they are handed',
      'the connector cannot write to outDir: no declared API takes a directory (SYS_FileSystem.saveFile has no such argument), so the caller writes these base64 payloads',
    ],
  };

  return {
    vendor,
    project,
    pcb: { uuid: focusedUuid, name: pcbName },
    outDir,
    generatedAt: builtAt,
    encoding: 'base64',
    files,
    manifest,
    failed,
    partial: failed.length > 0,
    note: 'write files[].data (base64) into outDir under files[].name, and manifest.json from manifest{} — '
      + 'the connector cannot write a path itself; `boardwise bridge export-fab` does both.',
  };
};

// --------------------------------------------------------------------------
// 012 §七: `lib.recommend` — read-only part recommendations
// --------------------------------------------------------------------------

/** How many candidates reach the answer unless the caller asks for more. */
const RECOMMEND_TOP_N = 5;

/** "每层 Top5" — one page of a layer holds this many, as the task words it. */
const RECOMMEND_PAGE_SIZE = 5;

/** "分页上限 3 页" — a layer stops here even when the host keeps returning full pages. */
const RECOMMEND_MAX_PAGES = 3;

/**
 * Per-page deadline for one library search.
 *
 * A search reaches the editor's own library backend, so it is the one call in
 * this action that can *hang* rather than fail — and a hung call would hold the
 * action slot until the daemon gave up, answering the caller with a bare
 * `TIMEOUT` and no idea which rung stalled. 20 s per page, with up to nine
 * pages, fits inside the daemon's `RECOMMEND_TIMEOUT` (90 s) only because a
 * hung page is reported and the descent continues instead of retrying.
 */
const RECOMMEND_CALL_TIMEOUT_MS = 20_000;

/**
 * How many `probes` one call may carry.
 *
 * A probe is a raw host call the connector does not understand, so the list is
 * capped: without a bound, `probes` would be an open channel into the editor's
 * library, one call per entry, and the action's own deadline (and the daemon's
 * 90 s) would decide how far it got rather than the caller.
 */
const RECOMMEND_MAX_PROBES = 10;

/** `searchByProperties`' arguments after the first, in declaration order. */
const PROBE_ARGUMENTS = ['libraryUuid', 'classification', 'symbolType', 'itemsOfPage', 'page'] as const;

/**
 * The read-only claim `lib.recommend` makes, in one place.
 *
 * The ladder's answer and the probes answer both carry it, and a claim written
 * twice is a claim that drifts once.
 */
const RECOMMEND_READONLY_NOTE = 'read-only: nothing was placed or modified. Put a candidate on '
  + 'the page with sch.place_component (deviceUuid + libraryUuid), or write the chosen LCSC code '
  + '/ MPN onto the part already on the page with sch.set_component_attribute.';

/** What the recommendation is *for*: the parameters the old part carried. */
type RecommendTarget = {
  value: string;
  partNumber: string;
  partCode: string;
  footprintName: string;
  supplierFootprint: string;
  name: string;
};

const EMPTY_TARGET: RecommendTarget = {
  value: '', partNumber: '', partCode: '', footprintName: '', supplierFootprint: '', name: '',
};

/** Normalise a property key so `JLCPCB Part Class` and `jlcpcb_part_class` agree. */
function normalizedKey(key: string): string {
  return key.replace(/[\s_-]/g, '').toLowerCase();
}

/** `Object.keys` of a possibly-exotic host object; a throwing trap means none. */
function ownKeys(obj: any): string[] {
  try {
    return Object.keys(obj ?? {});
  } catch {
    return [];
  }
}

/**
 * One string field out of a plain property map, tolerating key spelling.
 *
 * The library items and the component `otherProperty` maps are plain objects
 * whose key *spelling* is not guaranteed (`JLCPCB Part Class` was measured, and
 * a variant that writes `JLCPCBP artClass` — or `Supplier_Part` — must still be
 * found). Keys are compared with spaces/underscores/case removed, and every
 * read is guarded because on this host a property read may be a trap.
 */
function stringField(obj: any, ...names: string[]): string {
  if (!obj || typeof obj !== 'object') return '';
  const wanted = names.map(normalizedKey);
  for (const key of ownKeys(obj)) {
    if (!wanted.includes(normalizedKey(key))) continue;
    const read = readMember(obj, key);
    if (read.error !== undefined) continue;
    const value = read.value;
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

/**
 * One field of a library item: plain property first, `getState_*` second.
 *
 * Measured 2026-09-15: the library item objects carry their data as **plain
 * properties** (`item.uuid`, `item.footprintName`) while the editor's own
 * primitives use `getState_*()` accessors — the same split that made
 * `lib.device.get` answer `{}` for a device the editor had just placed. Both
 * shapes are therefore read, and neither is assumed.
 */
async function libraryField(item: any, ...names: string[]): Promise<string> {
  const direct = stringField(item, ...names);
  if (direct) return direct;
  for (const name of names) {
    const value = await getState(item, name);
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text) return text;
  }
  return '';
}

/**
 * JLCPCB's part class as a sort key: **Basic first**.
 *
 * The class decides whether SMT assembly charges an extended-part fee, which is
 * the whole reason 012v2 §七 asks for it in the output. `Preferred Extended` is
 * checked before `Extended` because the longer string contains the shorter one.
 */
function partClassRank(partClass: string): number {
  const text = partClass.toLowerCase();
  if (!text) return 3;
  if (text.includes('basic')) return 0;
  if (text.includes('preferred')) return 1;
  if (text.includes('extended')) return 2;
  return 3;
}

/** Does a candidate's package match what the old part used? */
function footprintMatches(
  footprintName: string, supplierFootprint: string, target: RecommendTarget,
): boolean {
  const wanted = [target.footprintName, target.supplierFootprint]
    .map((s) => s.toLowerCase()).filter(Boolean);
  if (!wanted.length) return false;
  return [footprintName, supplierFootprint]
    .map((s) => s.toLowerCase()).filter(Boolean)
    .some((have) => wanted.includes(have));
}

/** One search hit, reduced to the fields a chooser needs. */
async function recommendCandidate(
  item: any, layer: string, layerIndex: number, target: RecommendTarget,
): Promise<Record<string, unknown>> {
  const props = readMember(item, 'otherProperty').value;
  const footprint = readMember(item, 'footprint').value;
  const symbol = readMember(item, 'symbol').value;
  const footprintName = await libraryField(item, 'footprintName')
    || await libraryField(footprint, 'name');
  const supplierFootprint = stringField(props, 'Supplier Footprint');
  const partClass = stringField(props, 'JLCPCB Part Class', 'Part Class', 'LCSC Part Class');
  return {
    name: await libraryField(item, 'name'),
    // The LCSC code has lived under `Supplier Part` in every map measured so
    // far; `supplierId` is the search item's own spelling of the same fact.
    lcsc: stringField(props, 'Supplier Part', 'LCSC Part', 'partCode')
      || await libraryField(item, 'supplierId'),
    mpn: stringField(props, 'Manufacturer Part', 'ManufacturerPart', 'partNumber'),
    manufacturer: stringField(props, 'Manufacturer'),
    footprintName,
    supplierFootprint,
    partClass: partClass || 'unknown',
    partClassRank: partClassRank(partClass),
    datasheet: stringField(props, 'Datasheet', 'Datasheet URL'),
    description: await libraryField(item, 'description'),
    deviceUuid: await libraryField(item, 'uuid'),
    libraryUuid: await libraryField(item, 'libraryUuid'),
    symbolUuid: await libraryField(symbol, 'uuid') || await libraryField(item, 'symbolUuid'),
    footprintUuid: await libraryField(footprint, 'uuid') || await libraryField(item, 'footprintUuid'),
    layer,
    layerIndex,
    footprintMatches: footprintMatches(footprintName, supplierFootprint, target),
  };
}

/** Ranking: Basic first, then the package that fits, then the earlier layer. */
function compareCandidates(a: Record<string, unknown>, b: Record<string, unknown>): number {
  const byClass = Number(a.partClassRank) - Number(b.partClassRank);
  if (byClass !== 0) return byClass;
  const byFootprint = Number(b.footprintMatches) - Number(a.footprintMatches);
  if (byFootprint !== 0) return byFootprint;
  const byLayer = Number(a.layerIndex) - Number(b.layerIndex);
  if (byLayer !== 0) return byLayer;
  return String(a.name).localeCompare(String(b.name));
}

/** One layer of the ladder, and what it was handed. */
type RecommendLayer = {
  layer: string;
  api: 'searchByProperties' | 'search';
  args: Record<string, unknown>;
  /** Absent when the layer cannot run; `why` says which reason applies. */
  call: ((page: number) => Promise<any>) | null;
  why: string;
};

/**
 * Run one layer: page 1..`RECOMMEND_MAX_PAGES`, stopping on a short page.
 *
 * A short page means the host has nothing more for this query, so asking again
 * is a wasted round trip; `topN` is the other stop — once the pool can fill the
 * answer, more pages only add candidates nobody will see.
 */
async function runRecommendLayer(
  layer: RecommendLayer, topN: number, timeoutMs: number,
): Promise<{ items: any[]; pagesFetched: number; error: string }> {
  const items: any[] = [];
  let pagesFetched = 0;
  for (let page = 1; page <= RECOMMEND_MAX_PAGES; page += 1) {
    let found: any;
    try {
      found = await raceHostCall(
        settle(layer.call!(page)),
        `${layer.api} page ${page}`,
        timeoutMs,
        'the library search is not answering',
      );
    } catch (error) {
      return {
        items,
        pagesFetched,
        error: isActionError(error)
          ? `${error.code}: ${error.message}`
          : `${layer.api} page ${page} threw: ${String((error as Error)?.message ?? error)}`,
      };
    }
    pagesFetched += 1;
    const list = Array.isArray(found) ? found : [];
    items.push(...list);
    if (!Array.isArray(found)) {
      return {
        items,
        pagesFetched,
        error: `${layer.api} returned ${typeof found}, not an array`,
      };
    }
    if (list.length < RECOMMEND_PAGE_SIZE) break;
    if (items.length >= topN) break;
  }
  return { items, pagesFetched, error: '' };
}

/**
 * The placed component a `ref` names, with the parameters it carries.
 *
 * Read-only, and **focus-guarded**: `sch_PrimitiveComponent.getAll()` is the
 * focused page's list, so resolving "U1" against a page the caller did not mean
 * would answer with a different board's part. There is no cross-page lookup to
 * use instead, which is why the guard is the honest option rather than a
 * convenience.
 */
async function componentByRef(
  eda: Eda, ref: string,
): Promise<{ component: Record<string, string> | null; designators: string[] }> {
  const ns = namespaceOf(eda, 'sch_PrimitiveComponent');
  const getAll = readMember(ns, 'getAll').value;
  if (typeof getAll !== 'function') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'sch_PrimitiveComponent.getAll is not available — a designator cannot be resolved to a part',
      { path: 'sch_PrimitiveComponent.getAll' },
    );
  }
  const items: any[] = (await settle(getAll.call(ns))) ?? [];
  const wanted = ref.trim().toLowerCase();
  const designators: string[] = [];
  let component: Record<string, string> | null = null;
  for (const item of items) {
    const propsState = await getState(item, 'OtherProperty');
    const props = propsState && typeof propsState === 'object'
      ? propsState
      : readMember(item, 'otherProperty').value;
    const fromState = await getState(item, 'Designator');
    const designator = (fromState == null ? '' : String(fromState).trim())
      || stringField(props, 'Designator')
      || stringField(item, 'Designator', 'designator');
    if (designator) designators.push(designator);
    if (!designator || designator.toLowerCase() !== wanted || component) continue;
    const primitiveId = await getState(item, 'PrimitiveId');
    component = {
      primitiveId: primitiveId == null ? '' : String(primitiveId),
      designator,
      name: stringField(props, 'Name'),
      value: stringField(props, 'Value'),
      partNumber: stringField(props, 'Manufacturer Part', 'ManufacturerPart'),
      partCode: stringField(props, 'Supplier Part', 'LCSC Part'),
      footprintName: stringField(props, 'FootprintName'),
      supplierFootprint: stringField(props, 'Supplier Footprint'),
    };
  }
  return { component, designators };
}

/** One entry of `probes`, resolved into the exact call the caller asked for. */
type RecommendProbe = {
  /** The argument list for `Function.prototype.apply` — position for position. */
  args: unknown[];
  /** The page size the caller *asked for*; `null` when they did not ask. */
  pageSize: number | null;
};

/**
 * Read the optional `probes` parameter — or `null` when there are none.
 *
 * F4 (2026-09-21) needs to ask the *host* why `searchByProperties` answers
 * nothing while `search` hits on the same string, and the two remaining
 * explanations — "the host ignores these keys" and "the call shape matters" —
 * are only distinguishable by varying one argument at a time. So the caller
 * hands over the argument list itself and the connector sends it **verbatim**:
 * an argument the caller did not give is not sent at all, which is what keeps
 * `arguments.length` the caller's own (a `{properties, libraryUuid}` probe must
 * reach the host as *two* arguments, not as six with four `undefined`s — the
 * difference is the thing being measured).
 *
 * The shape is closed and small on purpose: every key that reaches a probe is a
 * declared `searchByProperties` parameter, so a probe can never invent an
 * argument the type package does not document. Absent (or explicitly `null`)
 * means "no probes", in which case the action's own path is untouched.
 */
function recommendProbes(raw: unknown): RecommendProbe[] | null {
  if (raw === undefined || raw === null) return null;
  if (!Array.isArray(raw)) {
    throw new ActionError(
      'BAD_REQUEST',
      'lib.recommend probes must be an array of {properties, libraryUuid?, classification?, '
        + 'symbolType?, itemsOfPage?, page?}',
    );
  }
  if (raw.length > RECOMMEND_MAX_PROBES) {
    throw new ActionError(
      'BAD_REQUEST',
      `lib.recommend takes at most ${RECOMMEND_MAX_PROBES} probes, got ${raw.length}`,
    );
  }
  return raw.map((entry, index) => {
    const probe = entry && typeof entry === 'object' && !Array.isArray(entry)
      ? (entry as Record<string, unknown>)
      : null;
    if (!probe) {
      throw new ActionError('BAD_REQUEST', `lib.recommend probes[${index}] must be an object`);
    }
    const properties = probe.properties;
    if (!properties || typeof properties !== 'object' || Array.isArray(properties)) {
      throw new ActionError(
        'BAD_REQUEST',
        `lib.recommend probes[${index}].properties must be an object — it is the one argument `
          + 'searchByProperties requires',
      );
    }
    const args: unknown[] = [properties];
    for (const name of PROBE_ARGUMENTS) {
      if (!Object.prototype.hasOwnProperty.call(probe, name)) continue;
      // A gap before a given argument is filled with `undefined`: the *position*
      // is what the host reads, so dropping it would renumber the call.
      while (args.length <= PROBE_ARGUMENTS.indexOf(name)) args.push(undefined);
      args.push(probe[name]);
    }
    const asked = probe.itemsOfPage;
    return {
      args,
      pageSize: typeof asked === 'number' && Number.isFinite(asked) ? asked : null,
    };
  });
}

/**
 * Run one probe — exactly one `searchByProperties` call, reported as it went.
 *
 * One call, not the ladder's page walk: the point is the host's answer to a
 * *specific* argument list, and a second page would muddy which call produced
 * which count. `hitCount` is therefore the size of the page that came back, and
 * `firstKeys` the first item's own key names, so a caller can see what a hit
 * actually contains without a second round trip.
 *
 * Nothing here is fatal. A probe that throws, hangs or finds nothing becomes
 * that entry's `error`/counts — the caller asked for a matrix, and one bad row
 * must not cost them the rest. Only `lib_Device` missing is structural, and
 * that check lives in the action.
 */
async function runRecommendProbe(
  probe: RecommendProbe,
  index: number,
  ns: any,
  searchByProperties: unknown,
  timeoutMs: number,
): Promise<Record<string, unknown>> {
  const label = `searchByProperties probe ${index + 1}`;
  if (typeof searchByProperties !== 'function') {
    return {
      args: probe.args,
      called: false,
      hitCount: 0,
      pageSize: probe.pageSize,
      firstKeys: [],
      error: 'lib_Device.searchByProperties is not available on this editor build '
        + '(the type package marks it "ADD since EDA v4")',
    };
  }
  let found: any;
  try {
    // `apply` with the caller's own list — the same deadline a ladder page gets,
    // for the same reason: this call reaches the library backend and can hang
    // rather than fail.
    found = await raceHostCall(
      settle((searchByProperties as (...rest: unknown[]) => unknown).apply(ns, probe.args)),
      label,
      timeoutMs,
      'the library search is not answering',
    );
  } catch (error) {
    return {
      args: probe.args,
      called: true,
      hitCount: 0,
      pageSize: probe.pageSize,
      firstKeys: [],
      error: isActionError(error)
        ? `${error.code}: ${error.message}`
        : `${label} threw: ${String((error as Error)?.message ?? error)}`,
    };
  }
  if (!Array.isArray(found)) {
    return {
      args: probe.args,
      called: true,
      hitCount: 0,
      pageSize: probe.pageSize,
      firstKeys: [],
      error: `${label} returned ${typeof found}, not an array`,
    };
  }
  return {
    args: probe.args,
    called: true,
    hitCount: found.length,
    pageSize: probe.pageSize,
    firstKeys: found.length ? ownKeys(found[0]) : [],
  };
}

/**
 * `lib.recommend` — read-only candidates for a part, and never a placement.
 *
 * Two entry points, exactly one of which must be given: `query` (a bare string
 * — an MPN, a value, or an LCSC code) or `{pageUuid, ref}` (a placed part, whose
 * own parameters are read off the page first).
 *
 * The ladder is the task's, and each rung reports its own hit count:
 *
 * 1. `exact` — `searchByProperties({supplierId})`: the LCSC code, addressed by
 *    the one properties key this host actually indexes (measured 2026-09-21 on
 *    3.2.186: `supplierId` = "C8678" → exactly that device, a bogus C-number →
 *    none; `partNumber` / `partCode` / `value` are applied and match nothing;
 *    `name` / `footprintName` are ignored — they answer with the library's
 *    default page of ten. See `docs/bridge.md` §12);
 * 2. `properties` — `searchByProperties({value, footprintName})`: the same part
 *    described the way a schematic holds it — which on that same host is a rung
 *    that **cannot hit**, and says so in `notes` rather than leaving a zero for
 *    the caller to misread;
 * 3. `keyword` — `search(text)`: the broadest, and the only rung that exists on
 *    an editor older than the `searchByProperties` declaration (which is marked
 *    **ADD since EDA v4**).
 *
 * The ladder **descends**: a rung that hits ends the search, and the rungs below
 * it are reported as not called rather than silently missing. `allLayers: true`
 * runs every rung and merges the pool, for a caller who wants the widest choice
 * rather than the most precise one.
 *
 * `searchByProperties` missing is a *degradation*, not an error — the keyword
 * rung still answers and the response says which rungs were unavailable. Only
 * `lib_Device` itself missing, or every rung failing, is structural.
 *
 * `probes` (optional, F4 2026-09-21) replaces the ladder with a raw channel onto
 * `searchByProperties`: each entry is **one** call, sent with exactly the
 * arguments the caller listed (see `recommendProbes`), and the answer carries
 * `probes: [{args, called, hitCount, pageSize, firstKeys, error?}]` with
 * `probesOnly: true`, an empty ladder and empty `candidates`. It was added to
 * ask the *host* why the exact rung answered nothing on 3.2.186, and it
 * answered: the call shape was never the problem, the **keys** were — which is
 * why rung 1 sends `supplierId` today. With no `probes` in the params nothing
 * about this action changes, which is the point: the ladder's answer is pinned
 * byte for byte in `tests/actions012b.test.mjs`.
 *
 * **Read-only, stated as an output field**: nothing here places, edits or drops
 * a part. Placement stays a decision the oracle makes, then executed through
 * `sch.place_component` / `sch.set_component_attribute`.
 */
export const libRecommend: ActionHandler = async (params, eda) => {
  const query = typeof params?.query === 'string' ? params.query.trim() : '';
  const ref = typeof params?.ref === 'string' ? params.ref.trim() : '';
  // A probes-only call is not a search of its own, so the query/ref contract
  // below does not apply to it: there is no ladder whose input has to be
  // unambiguous. Everything else — the structural `lib_Device` check, the
  // per-call deadline, the read-only answer fields — still does.
  const probes = recommendProbes(params?.probes);
  if (!probes) {
    if (query && ref) {
      throw new ActionError('BAD_REQUEST', 'lib.recommend takes either query or {pageUuid, ref} — not both');
    }
    if (!query && !ref) {
      throw new ActionError('BAD_REQUEST', 'lib.recommend needs query, or {pageUuid, ref}');
    }
  }
  const topN = Number.isFinite(Number(params?.topN))
    ? Math.min(Math.max(Math.trunc(Number(params.topN)), 1), 20)
    : RECOMMEND_TOP_N;
  const allLayers = params?.allLayers === true;
  const callTimeoutMs = Number.isFinite(Number(params?.timeoutMs))
    ? Math.min(Math.max(Number(params.timeoutMs), 200), 120_000)
    : RECOMMEND_CALL_TIMEOUT_MS;

  const target: RecommendTarget = { ...EMPTY_TARGET };
  let pageUuid = '';
  let component: Record<string, string> | null = null;
  if (probes) {
    // Nothing to resolve: a probe reads no page, so neither the focus-guarded
    // designator lookup nor the query derivation runs, and `target` /
    // `component` stay empty in the answer instead of looking like a part the
    // caller asked about.
  } else if (ref) {
    pageUuid = typeof params?.pageUuid === 'string' ? params.pageUuid.trim() : '';
    if (!pageUuid) {
      throw new ActionError(
        'BAD_REQUEST',
        'lib.recommend with ref needs pageUuid: the ref is resolved on the focused page, '
          + 'and the page uuid is what proves it is the page the caller meant',
      );
    }
    await guardPage(eda, pageUuid);
    const found = await componentByRef(eda, ref);
    if (!found.component) {
      throw new ActionError(
        'NOT_FOUND',
        `no component with designator ${JSON.stringify(ref)} on the focused page `
          + `(${found.designators.length} component(s): ${found.designators.slice(0, 20).join(', ') || 'none'})`,
        { ref, designators: found.designators.slice(0, 50) },
      );
    }
    component = found.component;
    target.value = component.value;
    target.partNumber = component.partNumber;
    target.partCode = component.partCode;
    target.footprintName = component.footprintName;
    target.supplierFootprint = component.supplierFootprint;
    target.name = component.name;
  } else {
    // A bare query is used verbatim on every rung: the same string is the MPN
    // and the value for a real part number like "SS34", and a caller who knows
    // which field their string is can use the ref path instead. An LCSC code
    // (`C` + digits) is *not* a value, so it only takes the partCode rung.
    const looksLikeLcsc = /^c\d{2,}$/i.test(query);
    target.value = looksLikeLcsc ? '' : query;
    target.partNumber = looksLikeLcsc ? '' : query;
    target.partCode = looksLikeLcsc ? query.toUpperCase() : '';
  }

  const nsRead = readMember(eda, 'lib_Device');
  const ns = nsRead.value;
  if (nsRead.error !== undefined || !ns || typeof ns !== 'object') {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      `lib_Device is not available in this editor version (${nsRead.error ?? 'absent'})`,
      { path: 'lib_Device' },
    );
  }
  const searchByProperties = readMember(ns, 'searchByProperties').value;
  const search = readMember(ns, 'search').value;
  const hasProperties = typeof searchByProperties === 'function';
  const hasSearch = typeof search === 'function';
  if (!hasProperties && !hasSearch) {
    throw new ActionError(
      'NOT_IMPLEMENTED',
      'neither lib_Device.searchByProperties nor lib_Device.search is available — nothing can be searched',
      { path: 'lib_Device.search' },
    );
  }

  if (probes) {
    // Probes only: the descent is not walked, so `layers` is empty and
    // `candidates` is empty *by construction* rather than because nothing
    // matched — which is what `probesOnly` is for. A probe that fails is that
    // entry's `error`, never a reason to lose the other rows: the caller asked
    // for a matrix and a matrix is the answer.
    const answered: Array<Record<string, unknown>> = [];
    // Sequentially, never in parallel: one editor, one library backend, and a
    // matrix is read against the order the calls went out in.
    for (let index = 0; index < probes.length; index += 1) {
      answered.push(
        await runRecommendProbe(probes[index], index, ns, searchByProperties, callTimeoutMs),
      );
    }
    return {
      source: 'probes',
      query: query || null,
      pageUuid: null,
      ref: ref || null,
      component,
      target,
      topN,
      layers: [],
      probes: answered,
      probesOnly: true,
      returned: 0,
      shown: 0,
      candidates: [],
      'stock/price': '以商城实时为准',
      readOnly: true,
      placed: false,
      note: RECOMMEND_READONLY_NOTE,
      notes: ['probes only: the search ladder was not run — layers[] and candidates[] are empty '
        + 'by construction, and probes[] holds the raw searchByProperties calls'],
    };
  }

  const callProperties = (properties: Record<string, unknown>) =>
    (page: number) =>
      searchByProperties.call(ns, properties, undefined, undefined, undefined, RECOMMEND_PAGE_SIZE, page);
  const callSearch = (keyword: string) =>
    (page: number) =>
      search.call(ns, keyword, undefined, undefined, undefined, RECOMMEND_PAGE_SIZE, page);

  // The exact rung describes the part by its **LCSC code**, and the key it sends
  // is `supplierId` rather than the declared `partCode`. Measured 2026-09-21 on
  // 3.2.186 with the `probes` channel (`outputs/013_f4_probes_real.json`):
  // `{supplierId:"C8678"}` returns exactly that one device and a bogus C-number
  // returns none — the key is genuinely filtered on — while `{partCode:"C8678"}`
  // and `{partNumber:"SS34"}` are applied and match nothing, and `name` /
  // `footprintName` are ignored outright (they answer with the library's default
  // page of 10). So the same fact, addressed by the key this host indexes.
  const exact: Record<string, unknown> = {};
  if (target.partCode) exact.supplierId = target.partCode;
  const described: Record<string, unknown> = {};
  if (target.value) described.value = target.value;
  if (target.footprintName) described.footprintName = target.footprintName;
  const keyword = query || target.value || target.partNumber || target.name;

  const layers: RecommendLayer[] = [
    {
      layer: 'exact',
      api: 'searchByProperties',
      args: exact,
      call: hasProperties && Object.keys(exact).length ? callProperties(exact) : null,
      why: !hasProperties
        ? 'lib_Device.searchByProperties is not available on this editor build (the type package marks it "ADD since EDA v4")'
        : 'no partCode (LCSC code) is known for this part — and supplierId, the key this '
          + 'host indexes, has nothing to carry (measured 2026-09-21)',
    },
    {
      // Kept as the declared reading of "the same part as a schematic holds it",
      // and reported honestly: on 3.2.186 this rung cannot hit — `value` is
      // applied but has no index and `footprintName` is ignored (both measured
      // 2026-09-21), which is why a run that reaches it says so in `notes`
      // instead of leaving a zero to be read as "this part is not in the
      // library".
      layer: 'properties',
      api: 'searchByProperties',
      args: described,
      call: hasProperties && Object.keys(described).length ? callProperties(described) : null,
      why: !hasProperties
        ? 'lib_Device.searchByProperties is not available on this editor build'
        : 'neither a value nor a footprint name is known for this part',
    },
    {
      layer: 'keyword',
      api: 'search',
      args: { keyword },
      call: hasSearch && keyword ? callSearch(keyword) : null,
      why: hasSearch
        ? 'there is no text to search for'
        : 'lib_Device.search is not available on this editor build',
    },
  ];

  const report: Array<Record<string, unknown>> = [];
  const collected: Array<Record<string, unknown>> = [];
  const errors: string[] = [];
  // Rungs that could not run at all, told apart from rungs an earlier hit made
  // unnecessary: the first is something the caller has to know about the host,
  // the second is the ladder working as designed.
  const unavailable: string[] = [];
  // Rungs that ran, answered zero, and *cannot* answer otherwise on this host:
  // told apart from "this part is not in the library" because a caller reading
  // three zeros would draw exactly the wrong conclusion (2026-09-21).
  const deadRungs: string[] = [];
  let succeeded = 0;
  for (let index = 0; index < layers.length; index += 1) {
    const layer = layers[index];
    if (!layer.call) {
      unavailable.push(`${layer.layer}: ${layer.why}`);
      report.push({
        layer: layer.layer, api: layer.api, called: false, args: layer.args,
        hitCount: 0, reason: layer.why,
      });
      continue;
    }
    if (collected.length && !allLayers) {
      report.push({
        layer: layer.layer, api: layer.api, called: false, args: layer.args,
        hitCount: 0,
        reason: 'an earlier rung matched — pass allLayers: true to run every rung',
      });
      continue;
    }
    const outcome = await runRecommendLayer(layer, topN, callTimeoutMs);
    if (outcome.error) errors.push(outcome.error);
    else succeeded += 1;
    report.push({
      layer: layer.layer,
      api: layer.api,
      called: true,
      args: layer.args,
      hitCount: outcome.items.length,
      pagesFetched: outcome.pagesFetched,
      ...(outcome.error ? { error: outcome.error } : {}),
    });
    for (const item of outcome.items) {
      collected.push(await recommendCandidate(item, layer.layer, index, target));
    }
    if (layer.layer === 'properties' && !outcome.error && !outcome.items.length) {
      deadRungs.push(
        'properties: searchByProperties(value / footprintName) cannot match on this host — '
          + 'measured 2026-09-21 on 3.2.186: value is applied but has no index and '
          + 'footprintName is ignored outright, so those two keys never select anything '
          + '(the LCSC code does: see the exact rung)',
      );
    }
  }

  if (succeeded === 0) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `every search rung failed: ${errors.join('; ') || 'no rung could run'}`,
      { errors, layers: report },
    );
  }

  // One device can come back from more than one rung; the first rung to offer
  // it keeps it, so `layer` stays the strongest evidence of why it is here.
  const unique = new Map<string, Record<string, unknown>>();
  for (const candidate of collected) {
    const key = `${String(candidate.deviceUuid)}|${String(candidate.libraryUuid)}`;
    if (unique.has(key)) continue;
    unique.set(key, candidate);
  }
  const ranked = [...unique.values()].sort(compareCandidates);
  const shown = ranked.slice(0, topN);
  const notes: string[] = [];
  if (!shown.length) {
    notes.push(
      'no library match — try the LCSC code directly (lib.device.get / getByLcscIds), '
        + 'or a plainer query',
    );
  }
  notes.push(
    ...errors.map((error) => `a search rung failed: ${error}`),
    ...unavailable,
    ...deadRungs,
  );

  return {
    source: ref ? 'ref' : 'query',
    query: query || null,
    pageUuid: pageUuid || null,
    ref: ref || null,
    component,
    target,
    topN,
    layers: report,
    returned: ranked.length,
    shown: shown.length,
    candidates: shown,
    // The type package's search item carries no stock or price field, so the
    // recommendation cannot answer either — said with a fixed label rather
    // than left for the caller to notice the absence.
    'stock/price': '以商城实时为准',
    readOnly: true,
    placed: false,
    note: RECOMMEND_READONLY_NOTE,
    ...(notes.length ? { notes } : {}),
  };
};

// --------------------------------------------------------------------------
// 012 §八: review.mark — draw a review pass back onto the page
// --------------------------------------------------------------------------

/** Half-width of a review marker, in canvas units — same size as `canvas.highlight`. */
const REVIEW_MARK_SIZE = 60;

/** Margin added to the focus box, so the part is not flush against the viewport edge. */
const REVIEW_MARK_PAD = 20;

/** One finding as the caller normalised it — what a mark needs, and nothing else. */
type ReviewMark = {
  /** 1-based position in `marks`, which is the order the caller sent (see `focus`). */
  position: number;
  ref: string;
  ruleId: string;
  severity: string;
  /** The one-line summary, as the rule wrote it. */
  text: string;
};

/** Trim anything that arrives as a string-ish field; never invent a value. */
function markTextField(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (value == null) return '';
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return '';
}

function reviewMarks(raw: unknown[]): ReviewMark[] {
  return raw.map((entry, index) => {
    const item = (entry && typeof entry === 'object' ? entry : {}) as Record<string, unknown>;
    return {
      position: index + 1,
      ref: markTextField(item.ref),
      ruleId: markTextField(item.ruleId),
      severity: markTextField(item.severity).toUpperCase(),
      text: markTextField(item.text),
    };
  });
}

type ComponentPosition = { primitiveId: string; designator: string; x: number; y: number };

/**
 * Where each component sits on the focused page, keyed by upper-cased designator.
 *
 * The position comes from `sch.geometry`'s own dump (`getState_X/Y`), not from a
 * fresh `locate()` lookup per ref: the caller is marking a whole review pass, and
 * the marker API takes *shapes*, so every position is needed anyway. A component
 * without a designator or without numeric coordinates is counted in
 * `withoutPosition` rather than dropped in silence.
 *
 * A page that cannot be read at all is **structural**: with no components there
 * is no position for any ref, so the action fails by name instead of returning a
 * jump list that is empty for a reason nobody can see.
 */
async function componentPositions(eda: Eda): Promise<{
  positions: Map<string, ComponentPosition>;
  components: number;
  withoutPosition: number;
}> {
  const page = await geometryOf(eda, 'sch_PrimitiveComponent');
  if (!page.available) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `the schematic page's components could not be read (${page.reason ?? 'unknown reason'}) — `
        + 'no ref can be resolved to a position',
      { reason: page.reason ?? null },
    );
  }
  const positions = new Map<string, ComponentPosition>();
  let withoutPosition = 0;
  for (const entry of page.items as Array<{ primitiveId?: unknown; state?: unknown }>) {
    const state = (entry.state && typeof entry.state === 'object' ? entry.state : {}) as Record<string, unknown>;
    const other = state.OtherProperty && typeof state.OtherProperty === 'object'
      ? (state.OtherProperty as Record<string, unknown>)
      : {};
    const designator = markTextField(state.Designator) || markTextField(other.Designator);
    const x = Number(state.X);
    const y = Number(state.Y);
    if (!designator || !Number.isFinite(x) || !Number.isFinite(y)) {
      withoutPosition += 1;
      continue;
    }
    // A sheet symbol has no designator, so a duplicate key here would be two
    // primitives sharing one — first one wins and the count above still adds up.
    const key = designator.toUpperCase();
    if (!positions.has(key)) {
      positions.set(key, {
        primitiveId: entry.primitiveId == null ? '' : String(entry.primitiveId),
        designator,
        x,
        y,
      });
    } else {
      withoutPosition += 1;
    }
  }
  return { positions, components: (page.items as unknown[]).length, withoutPosition };
}

/**
 * `review.mark` — take a `boardwise review` pass and put it on the canvas.
 *
 * The task's shape: findings in (each carrying a ref), markers out. The
 * official API (`dmt_EditorControl.generateIndicatorMarkers`) takes *shapes*,
 * not ids and not text, so a ref is resolved to a coordinate first and the
 * marker is a rectangle around it. **The text the task asks for — rule id,
 * severity, one line — cannot be drawn by this API.** It travels in the result
 * instead: `marked[k]` is marker `k` (1-based, in the order drawn), so the
 * caller's table *is* the legend, and the numbers on screen mean something.
 *
 * Three honest degradations, none of which lose the finding list:
 *
 * 1. `markers: false` — the caller asked for the jump list (ref + coordinates)
 *    only; nothing is drawn.
 * 2. `generateIndicatorMarkers` absent, or the canvas refuses it (returns
 *    `false` for an unsupported canvas / unknown tab) — the answer becomes
 *    `mode: 'list'` with the reason. A missing marker API must not cost the
 *    caller the coordinates it can still use.
 * 3. A ref that is not on the page, or has no position, is reported per mark in
 *    `unresolved` — the rest are still drawn.
 *
 * Refusals, by contrast, are structural and thrown: a `pageUuid` that is not the
 * focused page (`PAGE_MISMATCH`), a focused document that is not a schematic
 * page, a page whose components cannot be read, `focus` outside `marks`, and no
 * `marks` at all. `clear: true` calls `removeIndicatorMarkers` and needs the API
 * to exist — there is no jump-list fallback for "remove the overlays".
 *
 * `clear: true` is also the one path with **no page guard**, and that is
 * deliberate: it removes the overlays on whatever canvas is in front, which is
 * what "clear the markers" means (measured 2026-09-21: it cleared a page in a
 * different project than the one the caller had in mind). With **no** active
 * document there is no canvas to clear, and the answer is `cleared: true` with
 * the note "no active canvas — nothing to remove": the host refuses such a call
 * (`removeIndicatorMarkers` answers `false`), but calling that a refusal would
 * be wrong twice — nothing was there to remove, and the removal is idempotent.
 *
 * Read-only in the strict sense the catalogue uses: markers are an overlay, no
 * primitive is created, moved or modified.
 */
export const reviewMark: ActionHandler = async (params, eda) => {
  const control = namespaceOf(eda, 'dmt_EditorControl');

  if (params?.clear === true) {
    const remove = control.removeIndicatorMarkers;
    if (typeof remove !== 'function') {
      throw new ActionError(
        'NOT_IMPLEMENTED',
        'dmt_EditorControl.removeIndicatorMarkers() is not available — the markers cannot be cleared',
        { path: 'dmt_EditorControl.removeIndicatorMarkers' },
      );
    }
    // Which canvas, if any, is in front — the same read `doc.list` uses, so the
    // two can never disagree about "nothing is focused". `cleared: true` here is
    // idempotent semantics, not optimism: with no canvas, the markers the caller
    // asked to be gone are gone, and reporting the host's `false` as "the canvas
    // refused the removal" would send the caller hunting a canvas that is not
    // open.
    const clearProblems: string[] = [];
    const clearActive = await activeDocument(eda, clearProblems);
    if (clearActive === null) {
      return {
        mode: 'markers' as const,
        cleared: true,
        count: 0,
        marked: [],
        unresolved: [],
        readOnly: true,
        note: 'no active canvas — nothing to remove'
          + (clearProblems.length ? ` (${clearProblems[0]})` : ''),
      };
    }
    const ok = await settle(remove.call(control));
    return {
      mode: 'markers' as const,
      cleared: Boolean(ok),
      count: 0,
      marked: [],
      unresolved: [],
      readOnly: true,
      note: ok
        ? 'every indicator marker on the focused canvas was removed'
        : 'the canvas refused the removal — an unsupported canvas or an unknown tab',
    };
  }

  const raw = Array.isArray(params?.marks) ? (params.marks as unknown[]) : [];
  if (raw.length === 0) {
    throw new ActionError(
      'BAD_REQUEST',
      'review.mark needs params.marks (one entry per finding), or {clear: true} to remove the markers',
    );
  }
  const marks = reviewMarks(raw);

  const focus = params?.focus == null ? null : Number(params.focus);
  if (focus !== null && (!Number.isInteger(focus) || focus < 1 || focus > marks.length)) {
    throw new ActionError(
      'BAD_REQUEST',
      `params.focus is a 1-based position in marks (1..${marks.length}), got ${JSON.stringify(params?.focus)}`,
      { focus: params?.focus ?? null, count: marks.length },
    );
  }

  // The guard first: a uuid that does not match the focused page refuses before
  // any position is read, so a wrong tab cannot produce markers.
  await guardPage(eda, params?.pageUuid);

  const problems: string[] = [];
  const active = await activeDocument(eda, problems);
  if (active && active.type !== 'page' && active.type !== 'schematic') {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `the focused document is a ${active.type}, not a schematic page — markers would land on the `
        + 'wrong canvas. Focus the schematic page the findings are about.',
      { active },
    );
  }

  const page = await componentPositions(eda);
  const marked: Array<Record<string, unknown>> = [];
  const unresolved: Array<Record<string, unknown>> = [];
  for (const mark of marks) {
    const label = {
      position: mark.position,
      ref: mark.ref,
      ruleId: mark.ruleId,
      severity: mark.severity,
      text: mark.text,
    };
    if (!mark.ref) {
      unresolved.push({ ...label, reason: 'the finding names no ref — there is nothing to point at' });
      continue;
    }
    const hit = page.positions.get(mark.ref.toUpperCase());
    if (!hit) {
      unresolved.push({
        ...label,
        reason: `no component with this designator on the focused page (${page.positions.size} `
          + `designator(s) in ${page.components} component(s))`,
      });
      continue;
    }
    marked.push({
      ...label,
      marker: marked.length + 1,
      primitiveId: hit.primitiveId,
      designator: hit.designator,
      x: hit.x,
      y: hit.y,
    });
  }

  const boxes = marked.map((entry) => {
    const x = entry.x as number;
    const y = entry.y as number;
    return {
      type: 'rectangle',
      left: x - REVIEW_MARK_SIZE,
      right: x + REVIEW_MARK_SIZE,
      top: y + REVIEW_MARK_SIZE,
      bottom: y - REVIEW_MARK_SIZE,
    };
  });

  // One call for the whole pass: the colour and the line width belong to the
  // call, not to a marker, so severities cannot be coloured differently without
  // splitting the pass into one call per severity — a decision the oracle has
  // not made, so it is not taken here.
  const wantMarkers = params?.markers !== false;
  const generate = control.generateIndicatorMarkers;
  let mode: 'markers' | 'list' = 'markers';
  let attempted = 0;
  let accepted = 0;
  let markerReason = '';
  if (!wantMarkers) {
    mode = 'list';
    markerReason = 'markers: false — the jump list was asked for, so nothing was drawn';
  } else if (boxes.length === 0) {
    markerReason = 'no ref resolved to a position on this page, so there was nothing to draw';
  } else if (typeof generate !== 'function') {
    mode = 'list';
    markerReason = 'dmt_EditorControl.generateIndicatorMarkers() is not available on this editor — '
      + 'degraded to the jump list (ref + coordinates); nothing was drawn';
  } else {
    attempted = boxes.length;
    const color = parseColor(params?.color) ?? DEFAULT_MARKER_COLOR;
    // `focus` wins the zoom: zooming to all markers and then to one of them
    // would make which rectangle is in view depend on call ordering.
    const zoom = params?.zoom === true && focus === null;
    const ok = await settle(generate.call(control, boxes, color, 2, zoom));
    if (ok) {
      accepted = boxes.length;
    } else {
      mode = 'list';
      markerReason = 'the canvas refused the markers (unsupported canvas or unknown tab) — '
        + 'degraded to the jump list';
    }
  }

  let focused: Record<string, unknown> | null = null;
  if (focus !== null) {
    const target = marks[focus - 1];
    const base = {
      position: target.position,
      ref: target.ref,
      ruleId: target.ruleId,
      severity: target.severity,
    };
    const landed = marked.find((entry) => entry.position === target.position);
    const zoomToRegion = control.zoomToRegion;
    if (!landed) {
      focused = { ...base, zoomed: false, reason: 'this finding has no position on this page, so there is nothing to zoom to' };
    } else if (typeof zoomToRegion !== 'function') {
      focused = { ...base, zoomed: false, reason: 'dmt_EditorControl.zoomToRegion() is not available on this editor' };
    } else {
      const x = landed.x as number;
      const y = landed.y as number;
      const pad = REVIEW_MARK_SIZE + REVIEW_MARK_PAD;
      try {
        const ok = await settle(zoomToRegion.call(control, x - pad, x + pad, y + pad, y - pad));
        focused = {
          ...base, x, y, zoomed: Boolean(ok),
          ...(ok ? {} : { reason: 'the canvas refused the zoom (unsupported canvas or unknown tab)' }),
        };
      } catch (error) {
        focused = { ...base, x, y, zoomed: false, reason: `zoomToRegion threw: ${String((error as Error)?.message ?? error)}` };
      }
    }
  }

  const notes: string[] = [];
  if (page.withoutPosition) {
    notes.push(`${page.withoutPosition} primitive(s) on the page carry no designator or no numeric position and cannot be pointed at`);
  }
  if (active === null) {
    notes.push('the editor reported no active document — the markers land on whichever canvas was focused last'
      + (problems.length ? ` (${problems[0]})` : ''));
  }
  if (!params?.pageUuid) {
    notes.push('no pageUuid was given, so the page was not verified against a uuid; pass one to make a wrong tab a refusal');
  }
  if (unresolved.length) {
    notes.push(`${unresolved.length} finding(s) could not be pointed at on this page and were not drawn`);
  }
  if (problems.length) {
    notes.push(...problems.map((problem) => `a read failed: ${problem}`));
  }

  return {
    mode,
    cleared: false,
    page: {
      components: page.components,
      designators: page.positions.size,
      withoutPosition: page.withoutPosition,
      active: active ? { uuid: active.uuid, type: active.type, source: active.source } : null,
    },
    count: marks.length,
    marked,
    unresolved,
    markers: { attempted, accepted, ...(markerReason ? { reason: markerReason } : {}) },
    ...(focused ? { focused } : {}),
    readOnly: true,
    note: 'markers are geometric: generateIndicatorMarkers takes shapes, not text. marked[k-1] is '
      + 'marker k (1-based, in the order drawn) — `position` is the caller\'s own finding order, and '
      + '`marker` is the drawn order. The API has no per-marker text, so the rule id, the severity '
      + 'and the one-line summary travel in this table.',
    ...(notes.length ? { notes } : {}),
  };
};

// --------------------------------------------------------------------------
// 025: the document file / document source reads, and the two DRC checks
// --------------------------------------------------------------------------

/**
 * The permission gates the type package documents on `sys_FileManager`.
 *
 * Reported in every refusal's `detail` instead of being asserted as the cause.
 * The connector observes a `throw`; it cannot see the extension's grants, so
 * "you lack a permission" is a claim it has no way to check. What it *can* hand
 * back is the host's own words plus the gates the declaration names — which is
 * the difference between an actionable refusal and a blank one.
 */
const FILE_READ_GATES: readonly string[] = [
  '工程设计图 > 文件导出 — getDocumentFile / getSchematicFile',
  '工程管理 > 下载工程 — getProjectFile',
];

/**
 * One budget for both `sys_FileManager` reads, and the daemon's is what binds.
 *
 * The daemon gives a newly registered action the default `ACTION_TIMEOUT` of
 * 30 s (`protocol.timeout_for` does not name these yet). A connector deadline
 * *longer* than the daemon's can never be observed — the caller gets the
 * daemon's TIMEOUT and this action's honest verdict never arrives — so the two
 * are deliberately equal rather than merely compatible.
 */
const DOCUMENT_READ_TIMEOUT_MS = 30_000;

/**
 * A host error as `name: message`, with the name said only once.
 *
 * The host's own `Error.message` sometimes already begins with its name
 * (`"Error: 指定的主题消息在对应的画布内没有相关订阅"` — measured 2026-09-23), so a
 * caller that always prefixes reports `threw Error: Error: …`. The prefix is
 * therefore added only when the message does not already carry it, and the parts
 * travel separately in `detail` either way.
 */
function hostErrorText(error: unknown): { name: string; message: string; text: string } {
  const host = error as { name?: unknown; message?: unknown } | null;
  const name = typeof host?.name === 'string' && host.name ? host.name : typeof error;
  const message = String(host?.message ?? error);
  return {
    name,
    message,
    text: message.startsWith(`${name}:`) ? message : `${name}: ${message}`,
  };
}

/**
 * The refusal of one `sys_FileManager` read, as an error that names what happened.
 *
 * `getDocumentFile` and `getDocumentSource` are both documented to `throw` when
 * the extension lacks a grant ("没有权限调用将始终 throw Error"), and this side
 * has no way to read the extension's grants. So the host's message is carried
 * through verbatim, the gates above are listed as the possibilities the package
 * names, and `detail.thrown` separates a refusal from a *missing method* — a
 * distinction that stayed invisible for as long as nothing wrote it down.
 */
function fileReadFailure(path: string, error: unknown): ActionError {
  if (isActionError(error)) return error;
  const host = hostErrorText(error);
  return new ActionError(
    'CONNECTOR_ERROR',
    `${path} threw ${host.text}. The connector cannot read this `
      + "extension's grants, so whether a permission is missing is not knowable from "
      + `here; the type package documents these gates: ${FILE_READ_GATES.join('; ')}`,
    {
      path,
      thrown: true,
      errorName: host.name,
      errorMessage: host.message,
      permissions: FILE_READ_GATES,
    },
  );
}

/** A host `File` as base64 plus the metadata a caller needs to write it out. */
async function hostFilePayload(
  file: any,
  path: string,
): Promise<{ name: string; mime: string; bytes: number; data: string; isZip: boolean }> {
  const member = readMember(file, 'arrayBuffer');
  if (typeof member.value !== 'function') {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `${path} returned an object with no arrayBuffer() — its bytes cannot be read`,
      { path, observed: member.error ?? typeof file },
    );
  }
  const buffer = new Uint8Array(await settle(member.value.call(file)));
  if (buffer.byteLength === 0) {
    // The rule `export.fab` learned, applied before it can bite: an empty file is
    // a *failure*, not a small one. Zero bytes fed to the offline pipeline would
    // read as "a project with nothing in it" and the report would be wrong in the
    // reassuring direction.
    throw new ActionError(
      'CONNECTOR_ERROR',
      `${path} returned a zero-byte file — an empty export is not a small one`,
      { path, bytes: 0 },
    );
  }
  const given = readMember(file, 'name').value;
  const type = readMember(file, 'type').value;
  return {
    // A host-provided name becomes a path on the writing side, so separators are
    // stripped before it can climb out of the caller's output directory.
    name: typeof given === 'string' && given ? given.replace(/[\\/]+/g, '_').trim() : '',
    mime: typeof type === 'string' && type ? type : 'application/octet-stream',
    bytes: buffer.byteLength,
    data: bytesToBase64(buffer),
    isZip: buffer.length > 1 && buffer[0] === 0x50 && buffer[1] === 0x4b,
  };
}

/**
 * `sys.get_document_file` — the open document as an `.epro`/`.epro2` archive.
 *
 * This is the online half of the offline pipeline: the bytes it returns are the
 * same kind of archive `boardwise review` already reads, so a live project can go
 * through `load_epru_text → build_schematic_model` with **no rule changes** —
 * provided the host actually hands the file over. The declaration marks the call
 * as gated on 工程设计图 > 文件导出 and says a missing grant throws every time, so
 * "it worked" is a fact about this editor's grants, not about the API's shape;
 * the probe record in `outputs/025_probe_p1_document_file.txt` is where that was
 * measured, and `detail.permissions` travels with every refusal so a caller knows
 * what to ask the user to enable.
 *
 * `isZip` is reported rather than assumed: an `.epro2` is a ZIP archive, so a
 * payload whose first two bytes are not `PK` will not parse downstream, and
 * saying so here is cheaper than a parser failure one layer away.
 */
export const sysGetDocumentFile: ActionHandler = async (params, eda) => {
  const PATH = 'sys_FileManager.getDocumentFile';
  const requested = params?.fileType === undefined ? 'epro2' : String(params.fileType);
  if (requested !== 'epro2' && requested !== 'epro') {
    throw new ActionError(
      'BAD_REQUEST',
      `sys.get_document_file needs params.fileType to be epro2 or epro `
        + `(got ${JSON.stringify(params?.fileType)})`,
    );
  }
  const fileName = typeof params?.fileName === 'string' ? params.fileName.trim() : '';
  const password = typeof params?.password === 'string' ? params.password : '';
  const timeoutMs = Number.isFinite(Number(params?.timeoutMs))
    ? Math.min(Math.max(Number(params?.timeoutMs), 200), 600_000)
    : DOCUMENT_READ_TIMEOUT_MS;
  const call = requireFn(eda, PATH);

  let file: any;
  try {
    file = await raceHostCall(
      settle(call(fileName || undefined, password || undefined, requested)),
      PATH,
      timeoutMs,
      'the host drops an argument it dislikes rather than rejecting it, and this '
        + 'call is gated on a grant the connector cannot see',
    );
  } catch (error) {
    throw fileReadFailure(PATH, error);
  }
  if (!file) {
    throw new ActionError(
      'CONNECTOR_ERROR',
      `${PATH} returned ${file === null ? 'null' : 'undefined'} — the declaration says `
        + 'that means no document is open or the read failed; nothing was exported',
      { path: PATH, fileType: requested, empty: true },
    );
  }

  const payload = await hostFilePayload(file, PATH);
  return {
    fileType: requested,
    source: PATH,
    encoding: 'base64',
    ...payload,
    ...(payload.isZip
      ? {}
      : {
          note: 'the first bytes are not the ZIP magic "PK" — an .epro2 is a ZIP '
            + 'archive, so these bytes will not parse through the offline pipeline',
        }),
  };
};

/** Default and ceiling for `sys.get_document_source`'s `maxChars`. */
const SOURCE_DEFAULT_MAX_CHARS = 65_536;
const SOURCE_MAX_MAX_CHARS = 4_000_000;
/** How much of a truncated source is echoed from the end, to recognise its shape. */
const SOURCE_TAIL_CHARS = 1_024;

/**
 * `sys.get_document_source` — the focused document's source text.
 *
 * The declaration is one line (`Promise<string | undefined>`, `@beta`) and says
 * nothing about the format, so this action's job is to hand the string back
 * **unjudged** and let a probe decide what it is. Whether it equals the `.epru`
 * record stream inside an `.epro2` is exactly the question `outputs/025_probe_p2_document_source.txt`
 * answers; the action itself only reports length and, when it truncates, both
 * ends of the text.
 *
 * Both ends, not just the head: a record stream's head is a `DOCHEAD` line and
 * its tail is the last record of the last document, and a reader who sees one
 * without the other cannot tell a truncated dump from a different format.
 */
export const sysGetDocumentSource: ActionHandler = async (params, eda) => {
  const PATH = 'sys_FileManager.getDocumentSource';
  let maxChars = SOURCE_DEFAULT_MAX_CHARS;
  if (params?.maxChars !== undefined) {
    const wanted = Number(params.maxChars);
    if (!Number.isFinite(wanted) || wanted < 256 || wanted > SOURCE_MAX_MAX_CHARS) {
      throw new ActionError(
        'BAD_REQUEST',
        `sys.get_document_source params.maxChars must be a number between 256 and `
          + `${SOURCE_MAX_MAX_CHARS} (got ${JSON.stringify(params.maxChars)})`,
      );
    }
    maxChars = Math.floor(wanted);
  }
  const call = requireFn(eda, PATH);

  let source: unknown;
  try {
    source = await raceHostCall(
      settle(call()),
      PATH,
      DOCUMENT_READ_TIMEOUT_MS,
      'this read takes no arguments, so a hang means the host never answered',
    );
  } catch (error) {
    throw fileReadFailure(PATH, error);
  }
  if (typeof source !== 'string') {
    // `undefined` is documented ("当前未打开文档或数据获取失败") and null is not,
    // but both mean the same thing to a caller: there is no text. Reported as a
    // failure with the observed kind rather than as an empty string, because an
    // empty string is a *value* an equivalence check would happily compare.
    throw new ActionError(
      'CONNECTOR_ERROR',
      `${PATH} returned ${source === undefined ? 'undefined' : source === null ? 'null' : typeof source} `
        + '— the declaration says undefined means no document is open or the read failed',
      { path: PATH, kind: source === undefined ? 'undefined' : typeof source },
    );
  }
  const chars = source.length;
  const truncated = chars > maxChars;
  const data = truncated ? source.slice(0, maxChars) : source;
  return {
    source: PATH,
    chars,
    maxChars,
    truncated,
    data,
    headLines: (data.match(/\n/g) ?? []).length,
    ...(truncated
      ? {
          tail: source.slice(-SOURCE_TAIL_CHARS),
          note: `truncated to the first ${maxChars} characters; \`tail\` echoes the last `
            + `${SOURCE_TAIL_CHARS}, so both ends of the stream are inspectable`,
        }
      : {}),
    ...(chars === 0 ? { note: 'the host returned an empty string' } : {}),
  };
};

/** The three arguments both DRC checks take, with this project's defaults. */
function drcArgs(params: Record<string, unknown>): {
  strict: boolean;
  userInterface: boolean;
  includeVerboseError: boolean;
} {
  return {
    // The declaration says the schematic check is "统一为严格检查模式" anyway, and
    // the PCB one likewise; the default matches what the editor itself does.
    strict: params?.strict !== false,
    // Never a default: the editor pops its bottom DRC panel when this is true,
    // and an unattended check that rearranges the user's screen is a side effect
    // nobody asked for. A caller that wants to *watch* it passes true.
    userInterface: params?.userInterface === true,
    includeVerboseError: params?.includeVerboseError !== false,
  };
}

/** Which document a check ran against, plus why that read could not be made. */
async function drcTarget(eda: Eda, problems: string[]): Promise<Record<string, unknown>> {
  const active = await activeDocument(eda, problems);
  return active ? { uuid: active.uuid, type: active.type } : { uuid: null, type: 'unknown' };
}

/** `uuid (type)` for an error message, or the fact that nothing is focused. */
function describeDocument(page: Record<string, unknown>): string {
  const uuid = page?.uuid;
  return typeof uuid === 'string' && uuid
    ? `${uuid} (${String(page.type ?? 'unknown')})`
    : 'no document (the host reported none as focused)';
}

/**
 * `sch.drc_check` — the schematic DRC counts, read without touching the editor UI.
 *
 * What the type package promises and what the host does are different here, and
 * both are reported: the declaration overloads `includeVerboseError: true` to
 * resolve an array and `false` to resolve a boolean, but the machine measurement
 * behind 025 §0 found the array holds **aggregate counts only**
 * (`[{type: 'fatalError'|'error'|'warn', count}]`) while the per-item detail goes
 * to the bottom panel, which has no read interface for an extension. So the array
 * is returned **verbatim** under `counts` — no reshaping that would make an
 * aggregate look like a list of findings — and `total` / `byType` are summed from
 * the entries' own fields, with any entry that carries no numeric `count` counted
 * separately in `unparsed` rather than folded in as zero.
 *
 * A boolean answer despite `includeVerboseError: true` is reported as mode
 * `boolean`, not as an empty result: this build said only "passed".
 */
export const schDrcCheck: ActionHandler = async (params, eda) => {
  const PATH = 'sch_Drc.check';
  const args = drcArgs(params);
  const problems: string[] = [];
  const page = await drcTarget(eda, problems);
  const call = requireFn(eda, PATH);

  const started = Date.now();
  let result: unknown;
  try {
    result = await raceHostCall(
      settle(call(args.strict, args.userInterface, args.includeVerboseError)),
      PATH,
      DOCUMENT_READ_TIMEOUT_MS,
      'the host drops an argument it dislikes rather than rejecting it',
    );
  } catch (error) {
    if (isActionError(error)) throw error;
    const host = hostErrorText(error);
    throw new ActionError(
      'CONNECTOR_ERROR',
      `${PATH} threw ${host.text}. This call is only meaningful on a `
        + `schematic page — the focused document here is ${describeDocument(page)} — and `
        + 'the type package marks the whole namespace @beta',
      {
        path: PATH,
        args,
        focused: page,
        thrown: true,
        errorName: host.name,
        errorMessage: host.message,
        elapsedMs: Date.now() - started,
      },
    );
  }
  const elapsedMs = Date.now() - started;
  const base = {
    source: PATH,
    checked: true,
    elapsedMs,
    args,
    page,
    uiRequested: args.userInterface,
    ...(problems.length ? { notes: problems } : {}),
  };

  if (Array.isArray(result)) {
    const byType: Record<string, number> = {};
    let total = 0;
    let unparsed = 0;
    for (const entry of result) {
      const type = plainGet(entry, 'type');
      const count = Number(plainGet(entry, 'count'));
      const label = typeof type === 'string' && type ? type : '(entry without a type field)';
      if (Number.isFinite(count)) {
        byType[label] = (byType[label] ?? 0) + count;
        total += count;
      } else {
        unparsed += 1;
        byType[label] = byType[label] ?? 0;
      }
    }
    return {
      ...base,
      mode: 'counts',
      counts: result,
      entries: result.length,
      total,
      byType,
      passed: total === 0,
      ...(unparsed ? { unparsed } : {}),
    };
  }
  if (typeof result === 'boolean') {
    return {
      ...base,
      mode: 'boolean',
      counts: null,
      passed: result,
      note: 'the host answered a boolean even though includeVerboseError was true: this '
        + 'build does not hand back per-kind counts, so "passed" is everything it said',
    };
  }
  const rendered = safeJson(result);
  return {
    ...base,
    mode: 'unexpected',
    counts: null,
    passed: null,
    ...(rendered.error ? { unrenderable: rendered.error } : { raw: result }),
    note: 'the answer is neither the declared count array nor a boolean; reported whole '
      + 'rather than reshaped',
  };
};

/** Default and ceiling for `pcb.drc_check`'s inline tree. */
const DRC_TREE_DEFAULT_MAX_CHARS = 200_000;
const DRC_TREE_MAX_MAX_CHARS = 4_000_000;

/** `JSON.stringify` that cannot throw on a cyclic or hostile host object. */
function safeJson(value: unknown): { text: string; error?: string } {
  try {
    return { text: JSON.stringify(value) ?? '' };
  } catch (error) {
    return { text: '', error: String((error as Error)?.message ?? error) };
  }
}

/**
 * The keys a DRC node uses to hold its children.
 *
 * A closed list rather than "any array-valued field", and the difference is not
 * theoretical: measured on the machine 2026-09-23, a real leaf carries
 * `objs: ['err0']` and its containers carry `title: [name, '(1)']`, so a walk
 * that followed *every* array would treat each error as a branch and report
 * **0 items beside a group whose own `count` says 1** — a summary that lies in
 * the reassuring direction, which is the one direction that must not happen
 * (`outputs/025_probe_p4_pcb_drc.txt`).
 */
const DRC_CHILD_KEYS = ['list', 'children', 'errors', 'items', 'groups'] as const;

/** The array-valued children of a DRC node, from {@link DRC_CHILD_KEYS} only. */
function drcChildArrays(node: Record<string, unknown>): unknown[] {
  const out: unknown[] = [];
  for (const key of DRC_CHILD_KEYS) {
    const value = node[key];
    if (Array.isArray(value)) out.push(value);
  }
  return out;
}

/**
 * A DRC node's own `count`, when it states one.
 *
 * The editor puts the number of errors *under* a node on the node itself, which
 * makes it better evidence than anything a walk can derive — it is the host's
 * own answer to "how many?". Read defensively: a node without it returns
 * `null`, never 0, so "did not say" cannot pass for "none".
 */
function drcNodeCount(node: unknown): number | null {
  if (!node || typeof node !== 'object' || Array.isArray(node)) return null;
  const count = Number(plainGet(node, 'count'));
  return Number.isFinite(count) ? count : null;
}

/** The label a DRC leaf carries, from whichever of its own fields exists. */
function drcLeafLabel(item: unknown): string {
  for (const key of ['ruleName', 'errorType', 'type', 'name', 'kind']) {
    const value = plainGet(item, key);
    if (typeof value === 'string' && value) return value;
  }
  return '(leaf without a name field)';
}

/**
 * Count a DRC answer's leaf items, grouped by the label each leaf carries.
 *
 * A count and not an interpretation: which field a leaf uses for its rule name
 * differs per group, so the walk looks for the spellings the type package and
 * the host use, and reports every node that has none of them under one honest
 * label instead of dropping it. `seen` guards against a host object that points
 * back at itself — the walk must never be the thing that hangs.
 */
function countDrcLeaves(
  node: unknown,
  byLabel: Record<string, number>,
  seen: Set<unknown>,
): number {
  if (Array.isArray(node)) {
    let total = 0;
    for (const child of node) total += countDrcLeaves(child, byLabel, seen);
    return total;
  }
  if (!node || typeof node !== 'object') return 0;
  if (seen.has(node)) return 0;
  seen.add(node);
  const children = drcChildArrays(node as Record<string, unknown>);
  if (children.length === 0) {
    const label = drcLeafLabel(node);
    byLabel[label] = (byLabel[label] ?? 0) + 1;
    return 1;
  }
  let total = 0;
  for (const child of children) total += countDrcLeaves(child, byLabel, seen);
  return total;
}

/**
 * Keep whole groups while the rendered text stays inside the budget.
 *
 * Whole groups rather than a byte cut: half a group's JSON is not a DRC finding,
 * and a caller that receives one cannot tell it from a finding about a truncated
 * object. The first group is always kept — if it alone exceeds the budget the
 * note says so, which is more useful than an empty tree.
 */
function budgetDrcGroups(
  groups: unknown[],
  maxChars: number,
): { kept: unknown[]; dropped: number; jsonChars: number; oversizedFirst: boolean } {
  const kept: unknown[] = [];
  let used = 2; // the brackets of the array
  let dropped = 0;
  let oversizedFirst = false;
  for (const group of groups) {
    const size = safeJson(group).text.length + 1;
    if (kept.length === 0) {
      oversizedFirst = size > maxChars;
      kept.push(group);
      used += size;
      continue;
    }
    if (used + size > maxChars) {
      dropped = groups.length - kept.length;
      break;
    }
    kept.push(group);
    used += size;
  }
  return { kept, dropped, jsonChars: used, oversizedFirst };
}

/**
 * `pcb.drc_check` — the PCB DRC result, per item, as the host structured it.
 *
 * This is the one DRC that does carry item-level detail (025 §0): the answer is
 * an array of groups, each with a sub-group level and leaves carrying
 * `ruleName` / `errorType` / `explanation` / `obj1` / `obj2` / `globalIndex` /
 * `parentId`. **Measured on the machine 2026-09-23** (see
 * `outputs/025_probe_p4_pcb_drc.txt`) the tree is `group.list[].list[]`, each
 * node states its own `count`, and a leaf is told from a container by which of
 * the keys the tree really uses (`list`/`children`/…) is an array — a leaf's own
 * `objs: ['err0']` is *not* a child list, and treating it as one is how a tally
 * ends up reporting 0 items beside a group whose `count` says 1.
 *
 * The groups therefore come back **verbatim** — a mapping layer can read the
 * shape the editor really produces instead of the one this file guessed — and
 * the counts beside them only describe what was returned.
 *
 * Two answers are kept distinguishable from "a clean board":
 *
 * - `undefined`: the declared answer for "the editor is not on a PCB". Measured
 *   2026-09-23, the host instead **throws** `指定的主题消息在对应的画布内没有相关订阅`
 *   (the check publishes to the PCB canvas topic and there is no subscriber on a
 *   schematic page), so the throw is caught and reported with the focused
 *   document named. Both shapes are handled because a declaration is not a
 *   behaviour.
 * - a tree with no leaves: the *empty test PCB* answered one group, "Netlist
 *   Error / Import Changes" — the schematic has parts and the PCB does not. So
 *   "0 items" here is a real verdict about a board, not an absence of checking.
 */
export const pcbDrcCheck: ActionHandler = async (params, eda) => {
  const PATH = 'pcb_Drc.check';
  const args = drcArgs(params);
  let maxChars = DRC_TREE_DEFAULT_MAX_CHARS;
  if (params?.maxChars !== undefined) {
    const wanted = Number(params.maxChars);
    if (!Number.isFinite(wanted) || wanted < 1_000 || wanted > DRC_TREE_MAX_MAX_CHARS) {
      throw new ActionError(
        'BAD_REQUEST',
        `pcb.drc_check params.maxChars must be a number between 1000 and `
          + `${DRC_TREE_MAX_MAX_CHARS} (got ${JSON.stringify(params.maxChars)})`,
      );
    }
    maxChars = Math.floor(wanted);
  }
  const problems: string[] = [];
  const page = await drcTarget(eda, problems);
  const call = requireFn(eda, PATH);

  const started = Date.now();
  let result: unknown;
  try {
    result = await raceHostCall(
      settle(call(args.strict, args.userInterface, args.includeVerboseError)),
      PATH,
      DOCUMENT_READ_TIMEOUT_MS,
      'the host drops an argument it dislikes rather than rejecting it',
    );
  } catch (error) {
    if (isActionError(error)) throw error;
    const host = hostErrorText(error);
    throw new ActionError(
      'CONNECTOR_ERROR',
      `${PATH} threw ${host.text}. The declaration says the call reports `
        + `nothing at all when no PCB is focused; the focused document here is `
        + `${describeDocument(page)}`,
      {
        path: PATH,
        args,
        focused: page,
        thrown: true,
        errorName: host.name,
        errorMessage: host.message,
        elapsedMs: Date.now() - started,
      },
    );
  }
  const elapsedMs = Date.now() - started;
  const base = {
    source: PATH,
    elapsedMs,
    args,
    page,
    uiRequested: args.userInterface,
    ...(problems.length ? { notes: problems } : {}),
  };

  if (result === undefined || result === null) {
    return {
      ...base,
      checked: false,
      available: false,
      groups: null,
      counts: null,
      reason:
        `the host returned ${result === null ? 'null' : 'undefined'}, its declared answer for `
        + `"there is no PCB document to check" — the focused document here is `
        + `${describeDocument(page)}. No check ran: this is not a board with zero errors`,
    };
  }
  if (typeof result === 'boolean') {
    return {
      ...base,
      checked: true,
      available: true,
      mode: 'boolean',
      groups: null,
      counts: null,
      passed: result,
      note: 'the host answered a boolean even though includeVerboseError was true: this '
        + 'build does not hand back per-item errors, so "passed" is everything it said',
    };
  }
  if (!Array.isArray(result)) {
    const rendered = safeJson(result);
    return {
      ...base,
      checked: true,
      available: true,
      mode: 'unexpected',
      groups: null,
      counts: null,
      ...(rendered.error ? { unrenderable: rendered.error } : { raw: result }),
      note: 'the answer is not the declared group array; reported whole rather than reshaped',
    };
  }

  const byLabel: Record<string, number> = {};
  const items = countDrcLeaves(result, byLabel, new Set<unknown>());
  // The host states the number of errors under each group on the group itself,
  // which beats anything a walk can derive. Preferred when *every* top-level
  // group states one; otherwise the walked count is used and `errorsSource`
  // says so, because a total silently assembled from two sources is not a fact.
  let stated = 0;
  let fromHost = 0;
  for (const group of result) {
    const count = drcNodeCount(group);
    if (count !== null) {
      stated += 1;
      fromHost += count;
    }
  }
  const hostCountsAll = result.length > 0 && stated === result.length;
  const budget = budgetDrcGroups(result, maxChars);
  const notes: string[] = [...(problems.length ? problems : [])];
  if (budget.dropped) {
    notes.push(
      `${budget.dropped} group(s) were dropped to keep the answer inside maxChars `
        + `(${maxChars}); the counts describe the whole answer, the returned groups do not`,
    );
  }
  if (budget.oversizedFirst) {
    notes.push(
      'the first group alone exceeds maxChars, so it is returned whole and this answer is '
        + 'larger than the budget asks for',
    );
  }
  return {
    ...base,
    checked: true,
    available: true,
    mode: 'groups',
    groups: budget.kept,
    counts: {
      groups: result.length,
      returnedGroups: budget.kept.length,
      errors: hostCountsAll ? fromHost : items,
      errorsSource: hostCountsAll ? 'group-count' : 'walked-leaves',
      items,
      byLabel,
      jsonChars: budget.jsonChars,
    },
    truncated: budget.dropped > 0,
    ...(notes.length ? { notes } : {}),
  };
};

/**
 * The actions `sys.probe`'s `call` mode may dispatch to, and why the list is short.
 *
 * The daemon's action catalogue is a **load-time constant**: an action registered
 * here *after* the daemon started is unreachable through `bridge call --action
 * <name>` — the daemon answers `UNKNOWN_ACTION` before the frame is forwarded
 * (SKILL.md §6 pitfall 8, third recurrence). Restarting the daemon is the normal
 * fix, and it is the operator's call to make. This channel exists so a read-only
 * probe can still measure a freshly registered action against a daemon that has
 * not been restarted yet, which is what 025 batch 1 needed.
 *
 * It is a closed list of **read-only** actions on purpose. The `create` gate
 * (`CONFIRMATION_REQUIRED`) lives in the daemon, so anything routed through here
 * would bypass it — and a bypass that can bring a document into existence is
 * exactly the hole the gate was built to close. Reads have no gate to bypass.
 */
const PROBE_CALL_ACTIONS: Record<string, ActionHandler> = {
  'sys.get_document_file': sysGetDocumentFile,
  'sys.get_document_source': sysGetDocumentSource,
  'sch.drc_check': schDrcCheck,
  'pcb.drc_check': pcbDrcCheck,
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
    'sys.identity': bind(sysIdentity),
    // 025: the online half of the review pipeline — a whole document as an
    // archive the offline parsers already read, the document's own source text,
    // and the two DRC checks. All four are reads.
    'sys.get_document_file': bind(sysGetDocumentFile),
    'sys.get_document_source': bind(sysGetDocumentSource),
    'sch.drc_check': bind(schDrcCheck),
    'pcb.drc_check': bind(pcbDrcCheck),
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
    'sch.delete_primitives': bind(schDeletePrimitives),
    'pcb.delete_primitives': bind(pcbDeletePrimitives),
    'sch.modify_primitive': bind(schModifyPrimitive),
    'pcb.modify_primitive': bind(pcbModifyPrimitive),
    'doc.focus': bind(docFocus),
    'doc.delete_page': bind(docDeletePage),
    'export.fab': bind(exportFab),
    'lib.recommend': bind(libRecommend),
    'review.mark': bind(reviewMark),
  };
}
