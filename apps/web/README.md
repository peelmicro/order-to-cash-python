# apps/web

The web app of Order To Cash (assessment #9): an [Analog](https://analogjs.org) (Angular 22) app with its own Nitro server, a backend-for-frontend. The browser talks only to that server; it holds the Gateway's JWT in a sealed httpOnly cookie and forwards every call to the Gateway.

The full guide, with the `.env` keys, the sign-in account and the pages, is the root README's section [Running the web app](../../README.md#running-the-web-app). The commands below run from the repository root; pnpm is pinned to 12.8.1 by `packageManager` in `package.json`, so use `npx`, not a global pnpm.

```bash
npx --yes pnpm@12.8.1 -C apps/web install --frozen-lockfile
npx --yes pnpm@12.8.1 -C apps/web dev          # http://localhost:3010, the port is WEB_PORT
npx --yes pnpm@12.8.1 -C apps/web build        # apps/web/dist
npx --yes pnpm@12.8.1 -C apps/web start        # serves the build on WEB_PORT
npx --yes pnpm@12.8.1 -C apps/web types:check  # src/generated/openapi.ts matches specs/shared/openapi.yaml
npx --yes pnpm@12.8.1 -C apps/web types:generate
npx --yes pnpm@12.8.1 -C apps/web test:ci      # Vitest, once
```

Where things are:

- `src/server/` is the BFF: Nitro routes under `routes/api`, the session, CSRF and Gateway relay under `lib` and `middleware`.
- `src/app/` is the Angular app: `pages/` is the file router, `api/api-client.ts` is the only place a request or an event stream is opened, `ui/` is the generated spartan components.
- `src/generated/openapi.ts` is generated from `specs/shared/openapi.yaml`; never edit it by hand.
- `src/app/error-text.sweep.spec.ts` renders every page, fails every request it makes with every status its operation declares, and requires the problem's own text on screen.
