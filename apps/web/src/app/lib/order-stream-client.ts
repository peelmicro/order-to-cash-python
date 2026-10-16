import type { Schemas } from '../../shared/api-types';

export type StreamConnectionStatus = 'connecting' | 'connected' | 'reconnecting' | 'gave-up';

/** The part of `EventSource` this client uses: the browser's own and the `eventsource` npm package (used in tests over a real local HTTP server) both satisfy it. */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: { data?: unknown }) => void): void;
  close(): void;
  readonly readyState: number;
}

export type EventSourceFactory = (url: string) => EventSourceLike;

export interface OrderStreamCallbacks {
  onOrderUpdated: (update: Schemas['OrderStreamUpdate']) => void;
  onTimelineAppended: (entry: Schemas['TimelineStreamEntry']) => void;
  /** `stream.ready` answered `resumed: false`: the replay buffer could not resume this client (a fresh connection always gets this), so the page re-reads (openapi.yaml "Reconnection" 1). */
  onResync: () => void;
  onStatusChange: (status: StreamConnectionStatus) => void;
}

const READY_STATE_CLOSED = 2;
export const DEFAULT_GIVE_UP_AFTER_CONSECUTIVE_ERRORS = 6;

/**
 * The client half of `GET /orders/stream` (R55): applies `order.updated` and `timeline.appended` frames exactly once each (R51:
 * delivery is at-least-once) and reacts to the two outcomes of a connection. A transient drop is the `EventSource`'s own business,
 * including the `Last-Event-ID` header that makes the reconnect a RESUME; this class only reports it.
 *
 * DE-DUPLICATION IS PER FRAME TYPE. The projector gives the two frames of one applied fact the SAME `eventId`
 * (`OrderStreamUpdate.eventId` is "the fact that caused the update"; `TimelineStreamEntry.eventId` is that fact). One set shared by both types
 * treats whichever frame arrives second as a redelivery of the first and drops it: #7 shipped exactly that and its timeline stuck (#7 review pass 3,
 * finding 1). A redelivery is the SAME type with the same `eventId`; only that is dropped.
 */
export class OrderStreamClient {
  private source: EventSourceLike | null = null;
  private consecutiveErrors = 0;
  private readonly seenOrderUpdateIds = new Set<string>();
  private readonly seenTimelineEntryIds = new Set<string>();

  constructor(
    private readonly url: string,
    private readonly callbacks: OrderStreamCallbacks,
    private readonly factory: EventSourceFactory,
    private readonly giveUpAfterConsecutiveErrors: number = DEFAULT_GIVE_UP_AFTER_CONSECUTIVE_ERRORS,
  ) {}

  /**
   * Marks the facts a FETCHED snapshot already contains as seen, for both frame types: the snapshot's header and its timeline both reflect them, so a
   * replayed frame of either type for one of them is a redelivery. Called with a server snapshot only, never with the cache after a live patch (a patch
   * by one frame type does not mean the other type was applied, and seeding from it would drop that second frame).
   */
  seedSeenEventIds(eventIds: Iterable<string>): void {
    for (const id of eventIds) {
      this.seenOrderUpdateIds.add(id);
      this.seenTimelineEntryIds.add(id);
    }
  }

  connect(): void {
    this.disconnect();
    this.consecutiveErrors = 0;
    this.callbacks.onStatusChange('connecting');

    const source = this.factory(this.url);
    this.source = source;

    source.addEventListener('stream.ready', (event) => {
      const data = parse<Schemas['StreamReady']>(event);
      if (!data || this.source !== source) return;
      this.markAlive();
      if (!data.resumed) this.callbacks.onResync();
    });

    source.addEventListener('order.updated', (event) => {
      const data = parse<Schemas['OrderStreamUpdate']>(event);
      if (!data || this.source !== source) return;
      this.markAlive();
      if (this.seenOrderUpdateIds.has(data.eventId)) return;
      this.seenOrderUpdateIds.add(data.eventId);
      this.callbacks.onOrderUpdated(data);
    });

    source.addEventListener('timeline.appended', (event) => {
      const data = parse<Schemas['TimelineStreamEntry']>(event);
      if (!data || this.source !== source) return;
      this.markAlive();
      if (this.seenTimelineEntryIds.has(data.eventId)) return;
      this.seenTimelineEntryIds.add(data.eventId);
      this.callbacks.onTimelineAppended(data);
    });

    // `ping` carries no id (openapi.yaml "Frame format") and no content: it only proves the connection is alive.
    source.addEventListener('ping', () => {
      if (this.source === source) this.markAlive();
    });

    source.addEventListener('error', () => {
      if (this.source !== source) return;
      this.consecutiveErrors += 1;
      if (source.readyState === READY_STATE_CLOSED || this.consecutiveErrors >= this.giveUpAfterConsecutiveErrors) {
        this.disconnect();
        this.callbacks.onStatusChange('gave-up');
        return;
      }
      this.callbacks.onStatusChange('reconnecting');
    });
  }

  disconnect(): void {
    this.source?.close();
    this.source = null;
  }

  private markAlive(): void {
    this.consecutiveErrors = 0;
    this.callbacks.onStatusChange('connected');
  }
}

function parse<T>(event: { data?: unknown }): T | undefined {
  if (typeof event.data !== 'string') return undefined;
  try {
    return JSON.parse(event.data) as T;
  } catch {
    return undefined;
  }
}
