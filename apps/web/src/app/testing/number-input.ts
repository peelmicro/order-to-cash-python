import { fireEvent } from '@testing-library/dom';

/** What Chromium does with "1-2" in a `type="number"` box: the text stays on screen, `value` is "" and `validity.badInput` is true. jsdom sanitises the value the same way but has no such validity, so it is defined here. */
export function typeUnparseable(input: HTMLInputElement): void {
  Object.defineProperty(input, 'validity', { configurable: true, value: { badInput: true } });
  fireEvent.input(input, { target: { value: '' } });
}

/** A parseable keystroke into a number box: the browser reports `badInput: false` and the text. */
export function typeParseable(input: HTMLInputElement, value: string): void {
  Object.defineProperty(input, 'validity', { configurable: true, value: { badInput: false } });
  fireEvent.input(input, { target: { value } });
}

/**
 * Records EVERY assignment the page makes to `input.value` while the operator types (stage 2 re-review advisory 4: not only the assignments of the text the input already holds).
 * In Chromium an assignment to an `<input type="number">` replaces the typed text ("19." on screen, "19" as `value`) and moves the caret to the start (measured:
 * `.arm/web29s2f1/live/bare.mjs`, and "19.99" became "9919" / 991900 under render lag, `live/lag.out`). jsdom has no divergence between the screen text and `value`, so it cannot show
 * the caret move; it CAN show the cause, which is what this records: while typing, the page must never write to the box at all (the box already holds what was typed; the
 * keystroke itself is the browser's write and does not pass through this setter).
 */
export function writesWhileTyping(input: HTMLInputElement): string[] {
  const accessor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!;
  const writes: string[] = [];
  Object.defineProperty(input, 'value', {
    configurable: true,
    get(this: HTMLInputElement) { return accessor.get!.call(this) as string; },
    set(this: HTMLInputElement, text: string) {
      writes.push(String(text));
      accessor.set!.call(this, text);
    },
  });
  // The other two ways a page can write a number box's value (stage 3 review R8): `valueAsNumber` and `valueAsDate`. Recorded as `name=text`.
  for (const name of ['valueAsNumber', 'valueAsDate'] as const) {
    const other = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, name);
    if (!other?.set) continue;
    Object.defineProperty(input, name, {
      configurable: true,
      get(this: HTMLInputElement) { return other.get!.call(this) as unknown; },
      set(this: HTMLInputElement, v: unknown) {
        writes.push(`${name}=${String(v)}`);
        other.set!.call(this, v);
      },
    });
  }
  return writes;
}
