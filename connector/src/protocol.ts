/**
 * Wire protocol shared with the Python daemon (`src/boardwise/bridge/protocol.py`).
 *
 * Keep this file a mirror of the Python one: same envelope, same action names,
 * same error codes. The daemon rejects anything it does not have in its
 * catalogue, so a typo here shows up as UNKNOWN_ACTION rather than silence.
 */

export const PROTOCOL_VERSION = '1.0';

export const ROLE_CONNECTOR = 'connector';

/** The event the daemon sends the instant a socket opens. */
export const EVENT_BANNER = 'banner';

/**
 * One message on the wire.
 *
 * Three kinds share this type because either side may send any of them, and
 * the kind is told apart by which key is present:
 *
 * | kind     | key      |
 * |----------|----------|
 * | response | `ok`     |
 * | event    | `event`  |
 * | request  | `action` |
 *
 * `ok` wins over `event` wins over `action` — see {@link frameKind}.
 */
export type Frame = {
  id?: string;
  action?: string;
  params?: Record<string, unknown>;
  event?: string;
  ok?: boolean;
  data?: unknown;
  error?: { code: string; message: string; detail?: unknown };
  /**
   * The live context of the window that answered (023 §协议字段约定 1).
   *
   * Top level, **not** inside `data`: an action's result shape is a contract
   * with every caller, and this is bookkeeping about *which window* answered.
   * Optional everywhere — a frame without it is a frame from a connector that
   * could not read its own context, which is a fact, not an error.
   */
  context?: ResponseContext;
};

/**
 * Where a window is, as of the moment it answered.
 *
 * The daemon routes by this: with three editor windows open, "which project
 * has this action" is the question every call has to answer first, and a
 * context frozen at `hello` answers it about a document the user has since
 * closed. So the connector re-reads it for each response — see
 * `currentResponseContext` in `actions.ts`.
 *
 * Every field is optional and **omitted rather than guessed** when the window
 * cannot read it: an absent `projectUuid` means "this window did not say", a
 * wrong one means a write in the wrong project. `pageType: null` is the one
 * exception and it is a reading, not an absence: a document is in front and it
 * is neither a schematic page nor a PCB.
 */
export type ResponseContext = {
  /** The label the editor shows, e.g. `/test` — the same value `hello` sends. */
  projectName?: string;
  projectUuid?: string;
  /** The document in front, as `doc.list` / `document.current` name it. */
  pageUuid?: string;
  /**
   * Its kind, in `document.current`'s vocabulary: `sch` for a schematic
   * (schematic or page) and `pcb` for a PCB. The daemon's routing narrows two
   * windows of the same project by this, so the two sides spell it the same way.
   */
  pageType?: 'sch' | 'pcb' | null;
};

export type FrameKind = 'response' | 'event' | 'request';

/**
 * Classify a frame by the strongest key it carries, mirroring the daemon's
 * `frame_kind`. A frame holding two kinds then behaves predictably instead of
 * ambiguously.
 */
export function frameKind(frame: Frame): FrameKind {
  if ('ok' in frame) return 'response';
  if ('event' in frame) return 'event';
  return 'request';
}

export type ErrorCode =
  | 'UNAUTHENTICATED'
  | 'PROTOCOL_VIOLATION'
  | 'VERSION_MISMATCH'
  | 'BAD_REQUEST'
  | 'UNKNOWN_ACTION'
  | 'NOT_IMPLEMENTED'
  | 'NO_CONNECTOR'
  | 'CONNECTOR_ERROR'
  | 'PAGE_MISMATCH'
  | 'NOT_FOUND'
  | 'TIMEOUT'
  | 'INTERNAL';

export class ActionError extends Error {
  constructor(readonly code: ErrorCode, message: string, readonly detail?: unknown) {
    super(message);
    this.name = 'ActionError';
  }
}

/**
 * Is this one of ours? Deliberately *structural*, not `instanceof`.
 *
 * `instanceof` compares constructor identity, which only holds while exactly
 * one copy of this module is loaded. That is true of the shipped bundle, but
 * not of the test build (where several entry points may each inline a copy) or
 * of an editor that reloads the extension and keeps the old instance alive.
 * When the check fails, every typed error is silently flattened to `INTERNAL`
 * and the caller loses the code it needs to react — so duck-type instead.
 */
export function isActionError(error: unknown): error is ActionError {
  if (error instanceof ActionError) return true;
  const candidate = error as { name?: unknown; code?: unknown } | null;
  return (
    !!candidate &&
    typeof candidate === 'object' &&
    candidate.name === 'ActionError' &&
    typeof candidate.code === 'string'
  );
}

export function requestFrame(action: string, params?: Record<string, unknown>, id?: string): Frame {
  const frame: Frame = { id: id ?? newId(), action };
  if (params) frame.params = params;
  return frame;
}

export function responseFrame(id: string | undefined, data: unknown): Frame {
  return { id, ok: true, data };
}

export function errorFrame(id: string | undefined, error: ActionError): Frame {
  // Built from the fields rather than `error.toJSON()` on purpose: because
  // `isActionError` accepts *structurally* valid errors, the object handed to
  // us may come from a different copy of this module and therefore have no
  // `toJSON`. Reading the three fields always works.
  const payload: { code: string; message: string; detail?: unknown } = {
    code: error.code,
    message: error.message,
  };
  if (error.detail !== undefined) payload.detail = error.detail;
  return { id, ok: false, error: payload };
}

/**
 * Add the window's live context to a response frame (023 §协议字段约定 1).
 *
 * The wire's vocabulary is enforced **here**, at the frame, whatever the
 * reader handed over: the reader is a callback a build supplies, so a field
 * that is empty, of the wrong type, or a `pageType` outside the two words the
 * daemon routes by is turned into no field rather than into something the
 * daemon would have to disbelieve. `pageType: null` is kept — it is a reading
 * ("a document is in front and it is neither"), and the daemon's merge treats
 * it as no news rather than as a value.
 *
 * A no-op when there is nothing to add, and that is load-bearing: a build with
 * no context reader configured, or a window that could name nothing, must put
 * the *same bytes* on the wire as before this field existed. `context: {}`
 * would be a different claim on the daemon side, where the key's presence is
 * what says this connector speaks 023.
 */
export function withContext(frame: Frame, context: ResponseContext | undefined): Frame {
  const fields = contextFields(context);
  return fields ? { ...frame, context: fields } : frame;
}

/** The fields of {@link ResponseContext} that are readings, or `undefined`. */
function contextFields(context: ResponseContext | undefined): ResponseContext | undefined {
  if (!context || typeof context !== 'object') return undefined;
  const name = context.projectName;
  const uuid = context.projectUuid;
  const pageUuid = context.pageUuid;
  const pageType = context.pageType;
  const fields: ResponseContext = {
    ...(typeof name === 'string' && name ? { projectName: name } : {}),
    ...(typeof uuid === 'string' && uuid ? { projectUuid: uuid } : {}),
    ...(typeof pageUuid === 'string' && pageUuid ? { pageUuid } : {}),
    ...(pageType === 'sch' || pageType === 'pcb' || pageType === null ? { pageType } : {}),
  };
  return Object.keys(fields).length > 0 ? fields : undefined;
}

export function parseFrame(raw: string): Frame {
  let frame: unknown;
  try {
    frame = JSON.parse(raw);
  } catch {
    throw new ActionError('BAD_REQUEST', 'frame is not JSON');
  }
  // Arrays parse as `object` but are never valid frames — and an array's
  // `action` would be `undefined`, so they must be rejected here rather than
  // turned into a confusing UNKNOWN_ACTION downstream.
  if (!frame || typeof frame !== 'object' || Array.isArray(frame)) {
    throw new ActionError('BAD_REQUEST', 'frame must be a JSON object');
  }
  return frame as Frame;
}

let counter = 0;

export function newId(prefix = 'cn'): string {
  counter += 1;
  return `${prefix}-${counter.toString(36)}-${Math.random().toString(16).slice(2, 8)}`;
}
