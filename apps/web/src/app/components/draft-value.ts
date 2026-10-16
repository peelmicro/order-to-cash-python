import { Directive, effect, ElementRef, inject, input } from '@angular/core';

/**
 * Shows a draft's text in an input WITHOUT writing back what the input already holds.
 *
 * A `[value]` binding assigns `element.value` whenever its text changed since the last render. For `<input type="number">` that assignment is
 * harmful even when the string is equal: Chromium keeps the typed text ("19.") on screen while `value` reports its parse ("19"), and assigning
 * "19" replaces the screen text and moves the caret to the start, so the next keys land in front ("19.99" becomes "9919", sent as 991900).
 * The assignment happens a render AFTER the keystroke, so it races fast typing (a cold page, a catalogue arriving). Writing only when
 * `element.value !== text` leaves the typed text and caret alone, and still shows a draft changed from outside (the demo button).
 *
 * One case that test cannot see: a number box holding UNREADABLE text ("1-2") reports `value === ""`, so a draft reset to "" equals what the box reports and nothing is written,
 * and the text stays on screen under another row's heading (stage 3 review A1, live). `appDraftReset` is a counter the page bumps when it resets the draft from outside; a change
 * of the counter forces one write, which clears the screen text. Typing never bumps it, so the no-write-while-typing rule is untouched.
 */
@Directive({ selector: 'input[appDraftValue]' })
export class DraftValue {
  readonly text = input.required<string>({ alias: 'appDraftValue' });
  readonly reset = input<number>(0, { alias: 'appDraftReset' });
  private seenReset: number | undefined;
  private readonly element = inject<ElementRef<HTMLInputElement>>(ElementRef).nativeElement;

  constructor() {
    effect(() => {
      const text = this.text();
      const reset = this.reset();
      const forced = this.seenReset !== undefined && reset !== this.seenReset;
      this.seenReset = reset;
      if (forced || this.element.value !== text) this.element.value = text;
    });
  }
}
