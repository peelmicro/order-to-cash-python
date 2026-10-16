import type { Schemas } from '../../shared/api-types';

type OrderDetail = Schemas['OrderDetail'];
type OrderStatus = Schemas['OrderStatus'];
type ProjectionPending = Schemas['ProjectionPending'];
type TimelineEntry = Schemas['TimelineEntry'];

/** What `GET /api/orders/{id}` answered: a projected document, or the R55 "projection pending" (202) answer with the Gateway's suggested retry delay. */
export type OrderDetailResult = { kind: 'ready'; detail: OrderDetail } | { kind: 'pending'; pending: ProjectionPending; retryAfterMs: number };

export const DEFAULT_PENDING_RETRY_MS = 2000;
export const MIN_PENDING_RETRY_MS = 250;

/** The Gateway's retry hint for a 202: the `Retry-After` header (delta-seconds) first, then the body's `retryAfterMs`, then a default. Never below a floor, so a hint of `0` cannot become a tight loop. */
export function pendingRetryDelayMs(retryAfterSeconds: number | undefined, pending: Partial<ProjectionPending> | undefined): number {
  if (retryAfterSeconds !== undefined && Number.isSafeInteger(retryAfterSeconds)) return Math.max(MIN_PENDING_RETRY_MS, retryAfterSeconds * 1000);
  if (typeof pending?.retryAfterMs === 'number' && Number.isSafeInteger(pending.retryAfterMs)) return Math.max(MIN_PENDING_RETRY_MS, pending.retryAfterMs);
  return DEFAULT_PENDING_RETRY_MS;
}

const TERMINAL: ReadonlySet<OrderStatus> = new Set<OrderStatus>(['completed', 'cancelled']);

/** `completed` and `cancelled` are the only statuses an order never leaves (openapi.yaml `OrderStatus`). */
export function isTerminalStatus(status: OrderStatus): boolean {
  return TERMINAL.has(status);
}

function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/**
 * The timeline order openapi.yaml `TimelineEntry` prescribes: `occurredAt` ascending (R50); within one identical `occurredAt`, a fact follows the
 * fact that caused it (`causationId` = the other's `eventId`); where no recorded edge exists, `eventId` ascending (amendment A1). Applied to
 * live-appended entries so a page that received them over the stream shows the order a reload would.
 */
export function orderTimeline(entries: readonly TimelineEntry[]): TimelineEntry[] {
  const byInstant = new Map<string, TimelineEntry[]>();
  for (const entry of entries) {
    const group = byInstant.get(entry.occurredAt);
    if (group) group.push(entry);
    else byInstant.set(entry.occurredAt, [entry]);
  }
  const instants = [...byInstant.keys()].sort((a, b) => Date.parse(a) - Date.parse(b) || compareText(a, b));
  return instants.flatMap((instant) => orderTieGroup(byInstant.get(instant) ?? []));
}

function orderTieGroup(group: TimelineEntry[]): TimelineEntry[] {
  if (group.length < 2) return [...group];
  const ids = new Set(group.map((entry) => entry.eventId));
  const remaining = [...group].sort((a, b) => compareText(a.eventId, b.eventId));
  const placed = new Set<string>();
  const out: TimelineEntry[] = [];
  while (remaining.length > 0) {
    // The lowest eventId whose in-group cause (if any) is already placed; a cycle falls back to the lowest eventId.
    let index = remaining.findIndex((entry) => !entry.causationId || !ids.has(entry.causationId) || placed.has(entry.causationId));
    if (index < 0) index = 0;
    const [next] = remaining.splice(index, 1);
    if (!next) break;
    out.push(next);
    placed.add(next.eventId);
  }
  return out;
}

/** Applies a live `order.updated` frame to a projected document. A pending answer has nothing to patch. */
export function applyOrderUpdate(current: OrderDetailResult | undefined, update: Schemas['OrderStreamUpdate']): OrderDetailResult | undefined {
  if (!current || current.kind !== 'ready') return current;
  return {
    kind: 'ready',
    detail: {
      ...current.detail,
      status: update.status,
      cancellationReason: update.cancellationReason !== undefined ? update.cancellationReason : current.detail.cancellationReason,
      references: update.references ? { ...current.detail.references, ...update.references } : current.detail.references,
      totals: update.totals ?? current.detail.totals,
      orderReference: update.orderReference ?? current.detail.orderReference,
      updatedAt: update.occurredAt,
    },
  };
}

/** Appends a live `timeline.appended` frame. An entry whose `eventId` is already in the timeline is a redelivery and changes nothing (R51): the second de-duplication layer, independent of the stream client's own. */
export function applyTimelineAppended(current: OrderDetailResult | undefined, entry: Schemas['TimelineStreamEntry']): OrderDetailResult | undefined {
  if (!current || current.kind !== 'ready') return current;
  if (current.detail.events.some((existing) => existing.eventId === entry.eventId)) return current;
  const appended: TimelineEntry = { eventId: entry.eventId, eventType: entry.eventType, occurredAt: entry.occurredAt, summary: entry.summary };
  if (entry.causationId) appended.causationId = entry.causationId;
  return { kind: 'ready', detail: { ...current.detail, events: orderTimeline([...current.detail.events, appended]) } };
}

/**
 * The entry a timeline entry's `causationId` names, within THIS order's timeline, or nothing. Nothing is the right answer in two cases: no
 * `causationId` (an entry projected before the field existed), and an id that names a COMMAND (SA-6: a fact produced by an RPC responder cites the command
 * that requested it, which is never a timeline entry). #7 (`app/pages/orders/[id].vue:114`) and #8 (`src/lib/order-detail.ts:101`) both render no
 * "caused by" at all then; so does this: a link to nowhere, or a "caused by <id>" that names no visible entry, would claim a cause the page cannot show.
 */
export function causingEntry(entry: TimelineEntry, events: readonly TimelineEntry[]): TimelineEntry | undefined {
  if (!entry.causationId) return undefined;
  return events.find((candidate) => candidate.eventId === entry.causationId);
}

/**
 * When the order page re-reads `GET /orders/{id}` on its own (the TanStack `refetchInterval`), as a plain object so it can be tested without a clock:
 * - a `202 ProjectionPending` answer: at the Gateway's own suggested interval (R55);
 * - a live document that is not terminal: on a slow backstop, because a frame lost outright (no resend, no `resumed: false`) would otherwise leave a stale
 *   status on screen forever under a badge that says "Live";
 * - a terminal document the page watched BECOME terminal: ONE more read, so a sibling fact of the same burst still lands (#7 review D2/D7, ported by #8);
 * - a terminal document the page opened already terminal: never.
 * `interval` may be evaluated any number of times per update, so it only makes IDEMPOTENT notes.
 */
export const STALE_STATUS_BACKSTOP_MS = 5_000;

export class RefetchPlan {
  private completedReads = 0;
  private observedNonTerminal = false;
  private terminalSeenAfterReads: number | undefined;

  constructor(private readonly backstopMs: number = STALE_STATUS_BACKSTOP_MS) {}

  /** Call once per completed read of the order. */
  noteRead(): void {
    this.completedReads += 1;
  }

  reset(): void {
    this.completedReads = 0;
    this.observedNonTerminal = false;
    this.terminalSeenAfterReads = undefined;
  }

  interval(data: OrderDetailResult | undefined): number | false {
    if (!data) return false;
    if (data.kind === 'pending') return data.retryAfterMs;
    if (!isTerminalStatus(data.detail.status)) {
      this.observedNonTerminal = true;
      return this.backstopMs;
    }
    if (!this.observedNonTerminal) return false;
    this.terminalSeenAfterReads ??= this.completedReads;
    return this.completedReads === this.terminalSeenAfterReads ? this.backstopMs : false;
  }
}
