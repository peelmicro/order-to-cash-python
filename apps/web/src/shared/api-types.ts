// The ONE module that imports the generated OpenAPI types (src/generated/openapi.ts, produced from
// specs/shared/openapi.yaml by `pnpm run types:generate`; `pnpm run types:check` fails on drift).
// The browser client (src/app/api/api-client.ts) and the BFF (src/server/**) both take wire shapes
// from here; src/shared/generated-types.spec.ts fails if any other source file imports the generated file.
import type { components, operations, paths } from '../generated/openapi';

export type { components, operations, paths };
export type Schemas = components['schemas'];

export type Problem = Schemas['Problem'];
export type LoginRequest = Schemas['LoginRequest'];
export type LoginResponse = Schemas['LoginResponse'];
export type CurrentUser = Schemas['CurrentUser'];

/**
 * What the BFF tells the browser about its own session: identity, NEVER the token. This shape
 * belongs to the BFF (it has no row in openapi.yaml), so it is declared here, once, for both sides.
 */
export interface SessionInfo {
  authenticated: boolean;
  username?: string;
  displayName?: string;
  roles?: string[];
}
