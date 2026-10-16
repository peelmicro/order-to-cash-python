/**
 * Which assessment this web app belongs to (#8 backlog id 99, inherited as acceptance item 6). #7, #8 and
 * #9 share a page structure and all default to port 3010, so every place a user looks (the signed-in
 * header, the sign-in page and the browser tab) names the stack.
 *
 * This is the ONLY definition: the shell, the login page and the tab title all read it from here, and
 * src/app/stack-label.spec.ts fails if the text is written anywhere else in the app's source.
 */
export const STACK_LABEL = '#9 · Python / Angular';

/** The browser-tab title. */
export const APP_TITLE = `Order-To-Cash · ${STACK_LABEL}`;
