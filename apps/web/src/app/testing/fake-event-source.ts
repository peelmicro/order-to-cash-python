import type { EventSourceLike } from '../lib/order-stream-client';

const CONNECTING = 0;
const OPEN = 1;
const CLOSED = 2;

type Listener = (event: { data?: unknown }) => void;

/**
 * A server-sent-event transport a test controls: it records that it was opened and closed, and the test pushes frames, a transient drop (the browser
 * keeps retrying: `readyState` goes back to CONNECTING) or a refusal (the browser gives up: CLOSED). Deterministic: nothing happens unless the test says so.
 */
export class FakeEventSource implements EventSourceLike {
  readyState = CONNECTING;
  closed = false;
  private readonly listeners = new Map<string, Listener[]>();

  constructor(readonly url: string) {}

  addEventListener(type: string, listener: Listener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close(): void {
    this.closed = true;
    this.readyState = CLOSED;
  }

  /** Delivers one frame (`data` is the JSON text, or an object to serialise). */
  emit(type: string, data: unknown): void {
    if (this.closed) return;
    this.readyState = OPEN;
    for (const listener of this.listeners.get(type) ?? []) listener({ data: typeof data === 'string' ? data : JSON.stringify(data) });
  }

  /** The connection dropped; the browser will reconnect by itself. */
  drop(): void {
    if (this.closed) return;
    this.readyState = CONNECTING;
    for (const listener of this.listeners.get('error') ?? []) listener({});
  }

  /** The server refused the connection (a non-200, a wrong content type, an expired session): the browser does not retry. */
  refuse(): void {
    if (this.closed) return;
    this.readyState = CLOSED;
    for (const listener of this.listeners.get('error') ?? []) listener({});
  }
}
