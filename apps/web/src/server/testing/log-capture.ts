import { format, inspect } from 'node:util';

/**
 * One captured console call as text, the way a log line would carry it. `String(arg)` turns an object into
 * `[object Object]` and hides what a structured log call (`console.error('call', { headers: { Authorization } })`)
 * prints, so every argument is rendered with `util.inspect` at UNLIMITED depth (console itself prints nested objects
 * only to depth 2; a deeper token is still written by structured loggers), and the call is also rendered by
 * `util.format` exactly as console formats it.
 */
export function renderLogCall(args: readonly unknown[]): string {
  const deep = args.map((arg) => (typeof arg === 'string' ? arg : inspect(arg, { depth: Infinity, maxArrayLength: null, maxStringLength: null, breakLength: Infinity, showHidden: false })));
  return [format(...args), ...deep].join('\n');
}

/** Every call captured by the given console spies, rendered and joined. */
export function renderLogCalls(spies: ReadonlyArray<{ mock: { calls: ReadonlyArray<ReadonlyArray<unknown>> } }>): string {
  return spies.flatMap((spy) => spy.mock.calls.map((args) => renderLogCall(args))).join('\n');
}
