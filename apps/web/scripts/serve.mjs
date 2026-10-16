// Starts the web app on WEB_PORT (default 3010), the one port setting for `dev` and `preview`.
//
//   node --env-file-if-exists=../../.env scripts/serve.mjs <dev|preview>
//
// Why a script and not `vite --port ${WEB_PORT:-3010}` in package.json: the shell expands that
// BEFORE node loads the repository `.env`, so a WEB_PORT that lives only in `.env` would be
// ignored (#8 L1: a leader-side `.env.example` value defeated the documented override). Here
// process.env already holds both sources when this runs: a variable exported in the shell wins over
// the `.env` file (node never overrides an existing variable), and 3010 applies only when neither
// sets it. The default is 3010 because the usual dev port is often taken on this machine (CLAUDE.md, Environment notes).
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const DEFAULT_WEB_PORT = 3010;

export function webPort(env = process.env) {
  const raw = env.WEB_PORT?.trim();
  if (!raw) return DEFAULT_WEB_PORT;
  const port = Number(raw);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error(`WEB_PORT must be an integer between 1 and 65535, got "${raw}"`);
  }
  return port;
}

/** The command line and environment for a mode. Pure, so the test can read it without starting a server. */
export function commandFor(mode, env = process.env) {
  const port = webPort(env);
  if (mode === 'dev') {
    return { command: process.execPath, args: ['./node_modules/vite/bin/vite.js', '--port', String(port), '--strictPort'], env: { ...env } };
  }
  if (mode === 'preview') {
    // Nitro's node-server preset listens on NITRO_PORT, else PORT.
    return { command: process.execPath, args: ['dist/analog/server/index.mjs'], env: { ...env, NITRO_PORT: String(port), PORT: String(port) } };
  }
  throw new Error(`usage: serve.mjs <dev|preview>, got "${mode}"`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const { command, args, env } = commandFor(process.argv[2] ?? '');
  const child = spawn(command, args, { stdio: 'inherit', env, cwd: path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..') });
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
  child.on('exit', (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
}
