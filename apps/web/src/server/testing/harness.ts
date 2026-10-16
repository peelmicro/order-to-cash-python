/// <reference types="vite/client" />
import { readdirSync } from 'node:fs';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { createApp, createRouter, toNodeListener, type EventHandler, type RouterMethod } from 'h3';
import { STREAM_ROUTE_ENTERED } from '../lib/stream-proxy';
import { FakeGateway } from './fake-gateway';

/**
 * The BFF as Nitro assembles it, rebuilt in-process over a real socket: middleware first, then every
 * route file under src/server/routes, mapped to a method and path by Nitro's file-name convention.
 * The mapping is re-implemented here (Nitro does it at build time), so the PRODUCTION build is
 * tested too (src/build/production-bff.spec.ts) and a mapping drift between the two fails there.
 */
export const SERVER_ROOT = path.resolve(import.meta.dirname, '..');
export const ROUTES_DIR = path.join(SERVER_ROOT, 'routes');
export const MIDDLEWARE_DIR = path.join(SERVER_ROOT, 'middleware');

const ROUTE_GLOB = import.meta.glob<{ default: EventHandler }>('/src/server/routes/**/*.ts');
const MIDDLEWARE_GLOB = import.meta.glob<{ default: EventHandler }>('/src/server/middleware/*.ts');

export interface RouteFile {
  /** Relative to src/server/routes, e.g. `api/orders/[id].get.ts`. */
  rel: string;
  /** `undefined`: the file has no `.get`/`.post` suffix and answers every method (Nitro's convention). */
  method: RouterMethod | undefined;
  /** The h3 router path, e.g. `/api/orders/:id`. */
  path: string;
  /** The path as a reader names it, e.g. `/api/orders/{id}`. */
  name: string;
  load: () => Promise<{ default: EventHandler }>;
}

export function parseRouteFile(rel: string): { method: RouterMethod | undefined; path: string; name: string } {
  const match = /^(.*?)(?:\.(get|post|put|patch|delete))?\.ts$/.exec(rel);
  if (!match) throw new Error(`not a route file: ${rel}`);
  const segments = match[1]!.split('/').filter((segment) => segment !== 'index');
  const method = match[2] as RouterMethod | undefined;
  return {
    method,
    path: `/${segments.map((segment) => (segment.startsWith('[...') ? '**' : segment.replace(/^\[(.+)\]$/, ':$1'))).join('/')}`,
    name: `/${segments.map((segment) => (segment.startsWith('[...') ? '**' : segment.replace(/^\[(.+)\]$/, '{$1}'))).join('/')}`,
  };
}

export const ROUTE_FILES: RouteFile[] = Object.entries(ROUTE_GLOB)
  .map(([key, load]) => {
    const rel = key.replace(/^\/src\/server\/routes\//, '');
    return { rel, ...parseRouteFile(rel), load };
  })
  .sort((a, b) => a.rel.localeCompare(b.rel));

/** The same population read straight off the disk, to check the glob against. */
export function routeFilesOnDisk(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else out.push(path.relative(ROUTES_DIR, full).split(path.sep).join('/'));
    }
  };
  walk(ROUTES_DIR);
  return out.sort();
}

export function middlewareOnDisk(): string[] {
  return readdirSync(MIDDLEWARE_DIR).sort();
}

export interface Bff {
  baseUrl: string;
  gateway: FakeGateway;
  /** A fetch against the BFF with the Origin a same-site browser would send. */
  fetch: (pathAndQuery: string, init?: RequestInit) => Promise<Response>;
  /** How many requests have reached the stream route so far (it logs STREAM_ROUTE_ENTERED once the session is accepted, so a refused cookie does not count): the premise of the same-tick case. */
  streamRouteEntries: () => number;
  stop: () => Promise<void>;
}

/** Starts a fake Gateway and the in-process BFF in front of it. Sets GATEWAY_BASE_URL in process.env (restore it with `vi.unstubAllEnvs`). */
export async function startBff(setEnv: (name: string, value: string) => void): Promise<Bff> {
  const gateway = new FakeGateway();
  const gatewayUrl = await gateway.start();
  setEnv('GATEWAY_BASE_URL', gatewayUrl);
  let streamEntries = 0;
  const realDebug = console.debug;
  console.debug = (...args: unknown[]) => {
    if (args[0] === STREAM_ROUTE_ENTERED) streamEntries += 1;
    else realDebug(...args);
  };

  const app = createApp();
  for (const load of Object.values(MIDDLEWARE_GLOB)) app.use((await load()).default);
  const router = createRouter();
  for (const file of ROUTE_FILES) router.add(file.path, (await file.load()).default, file.method);
  app.use(router);

  const server: Server = createServer(toNodeListener(app));
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  return {
    baseUrl,
    gateway,
    fetch: (pathAndQuery, init) => fetch(`${baseUrl}${pathAndQuery}`, { redirect: 'manual', ...init }),
    streamRouteEntries: () => streamEntries,
    stop: async () => {
      console.debug = realDebug;
      server.closeAllConnections();
      await new Promise<void>((resolve) => server.close(() => resolve()));
      await gateway.stop();
    },
  };
}
