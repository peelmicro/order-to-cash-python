import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import { createServer } from 'node:net';
import path from 'node:path';
import { STREAM_ROUTE_ENTERED } from '../server/lib/stream-proxy';
import type { Bff } from '../server/testing/harness';
import { FakeGateway } from '../server/testing/fake-gateway';
import { SESSION_PASSWORD } from '../server/testing/gateway-script';

export const WEB_ROOT = path.resolve(import.meta.dirname, '..', '..');
export const SERVER_ENTRY = path.join(WEB_ROOT, 'dist', 'analog', 'server', 'index.mjs');

/** `vite build`, always: a stale dist/ would let a test pass against code that is no longer in src/. */
export function buildProduction(): void {
  // The test runner's own markers must not reach the build: with VITEST / NODE_ENV=test in the environment Analog's
  // Nitro plugin takes its test-mode branch and publishes the wrong directory (src/server) as the static assets,
  // so the server then answers `/` with the SOURCE index.html (`/src/main.ts`) and the app never starts in a browser.
  // Found in the live check, not by an earlier test: the build env is now explicit, and the production spec follows
  // the served page's own <script src> to prove the assets are served as JavaScript.
  const env: Record<string, string | undefined> = { ...process.env, NODE_ENV: 'production' };
  for (const name of Object.keys(env)) if (name === 'VITEST' || name.startsWith('VITEST_') || name === 'TEST') delete env[name];
  const result = spawnSync(process.execPath, ['./node_modules/vite/bin/vite.js', 'build'], { cwd: WEB_ROOT, encoding: 'utf8', timeout: 220_000, env });
  if (result.status !== 0) throw new Error(`vite build failed (exit ${result.status}):\n${result.stdout}\n${result.stderr}`);
}

/** Servers started and not yet exited. A server a test forgets would hold its port and its Gateway connection for the rest of the day (two such strays were found after earlier runs). */
const alive = new Set<ChildProcess>();
export const liveServers = (): number => alive.size;
process.once('exit', () => {
  for (const child of alive) child.kill('SIGKILL');
});

export interface RunningServer {
  baseUrl: string;
  child: ChildProcess;
  output: () => string;
  stop: () => Promise<void>;
}

/**
 * A port the OS has just handed out. Nitro treats `NITRO_PORT=0` as unset and falls back to 3000, which is often taken
 * on this machine (and was silently the port every earlier run used), so the port is asked for here and passed
 * explicitly. The window between release and the server's bind is the one race this leaves; startServer retries on it.
 */
async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port } = probe.address() as { port: number };
      probe.close(() => resolve(port));
    });
  });
}

/** Starts `node dist/analog/server/index.mjs` on a fresh port and waits for the line that names it. */
export async function startServer(env: Record<string, string>, attempt = 1): Promise<RunningServer> {
  const port = await freePort();
  try {
    return await spawnServer(env, port);
  } catch (error) {
    if (attempt < 3 && /EADDRINUSE/.test(String(error))) return startServer(env, attempt + 1);
    throw error;
  }
}

async function spawnServer(env: Record<string, string>, port: number): Promise<RunningServer> {
  const child = spawn(process.execPath, [SERVER_ENTRY], {
    cwd: WEB_ROOT,
    env: { PATH: process.env['PATH'] ?? '', NITRO_PORT: String(port), NITRO_HOST: '127.0.0.1', ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  alive.add(child);
  child.once('exit', () => alive.delete(child));
  let output = '';
  child.stdout!.on('data', (chunk: Buffer) => (output += chunk.toString()));
  child.stderr!.on('data', (chunk: Buffer) => (output += chunk.toString()));
  const baseUrl = await new Promise<string>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`the production server never announced its port:\n${output}`)), 20_000);
    const look = () => {
      const match = /Listening on (http:\/\/[^\s]+)/.exec(output);
      if (match) {
        clearTimeout(timer);
        // The line names the port the server really bound; it must be the one asked for (see freePort).
        if (!match[1]!.includes(`:${port}`)) reject(new Error(`the production server listens on ${match[1]}, not on the requested port ${port}`));
        else resolve(`http://127.0.0.1:${port}`);
      }
    };
    child.stdout!.on('data', look);
    child.on('exit', (code) => {
      clearTimeout(timer);
      reject(new Error(`the production server exited (${code}) before listening:\n${output}`));
    });
  }).catch((error: unknown) => {
    child.kill('SIGKILL'); // never leave a server behind when it failed to come up as asked
    throw error;
  });
  return {
    baseUrl,
    child,
    output: () => output,
    stop: async () => {
      if (child.exitCode !== null) return;
      child.kill('SIGTERM');
      await new Promise<void>((resolve) => {
        const timer = setTimeout(() => {
          child.kill('SIGKILL');
          resolve();
        }, 5000);
        child.on('exit', () => {
          clearTimeout(timer);
          resolve();
        });
      });
    },
  };
}

/** The production server behind a fake Gateway, shaped like the in-process harness so the same contract runs against both. */
export async function startProductionBff(extraEnv: Record<string, string> = {}): Promise<Bff & { server: RunningServer }> {
  const gateway = new FakeGateway();
  const gatewayUrl = await gateway.start();
  const server = await startServer({ GATEWAY_BASE_URL: gatewayUrl, WEB_SESSION_PASSWORD: SESSION_PASSWORD, ...extraEnv });
  return {
    baseUrl: server.baseUrl,
    gateway,
    server,
    streamRouteEntries: () => server.output().split(STREAM_ROUTE_ENTERED).length - 1,
    fetch: (pathAndQuery, init) => fetch(`${server.baseUrl}${pathAndQuery}`, { redirect: 'manual', ...init }),
    stop: async () => {
      await server.stop();
      await gateway.stop();
    },
  };
}
