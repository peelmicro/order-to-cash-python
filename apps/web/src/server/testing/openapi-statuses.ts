import { readFileSync } from 'node:fs';
import path from 'node:path';
import ts from 'typescript';

/**
 * The response statuses `specs/shared/openapi.yaml` declares for each operation, read from the
 * GENERATED types (`src/generated/openapi.ts`, which `pnpm run types:check` keeps in step with the
 * spec) with the TypeScript parser, because types are erased at run time. Ported from #8
 * (apps/web/src/test/openapi-statuses.ts), extended to read the `default` response: since SA-9 every
 * operation declares one, meaning "any other status answers a problem document".
 */
export const GENERATED = path.resolve(import.meta.dirname, '..', '..', 'generated', 'openapi.ts');

/** The status the sweep serves for an operation's `default` response (no number is declared for it). */
export const DEFAULT_RESPONSE_STATUS = 500;

export interface DeclaredOperation {
  method: string;
  /** Gateway path template, e.g. `/orders/{id}`. */
  template: string;
  operationId: string;
  /** Numeric statuses declared, plus {@link DEFAULT_RESPONSE_STATUS} when the operation declares `default` and not that status. */
  statuses: number[];
}

function interfaceNamed(file: ts.SourceFile, name: string): ts.InterfaceDeclaration {
  const found = file.statements.find((s): s is ts.InterfaceDeclaration => ts.isInterfaceDeclaration(s) && s.name.text === name);
  if (!found) throw new Error(`openapi.ts has no interface ${name}`);
  return found;
}

const memberName = (member: ts.TypeElement): string | undefined => (member.name && (ts.isIdentifier(member.name) || ts.isStringLiteral(member.name) || ts.isNumericLiteral(member.name)) ? member.name.text : undefined);

export function declaredOperations(file: string = GENERATED): DeclaredOperation[] {
  const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
  const statuses = new Map<string, number[]>();
  for (const op of interfaceNamed(source, 'operations').members) {
    const id = memberName(op);
    if (!id || !ts.isPropertySignature(op) || !op.type || !ts.isTypeLiteralNode(op.type)) continue;
    const responses = op.type.members.find((m) => memberName(m) === 'responses');
    if (!responses || !ts.isPropertySignature(responses) || !responses.type || !ts.isTypeLiteralNode(responses.type)) continue;
    const names = responses.type.members.map(memberName).filter((n): n is string => n !== undefined);
    const numeric = names.filter((n) => /^\d{3}$/.test(n)).map(Number);
    if (names.includes('default') && !numeric.includes(DEFAULT_RESPONSE_STATUS)) numeric.push(DEFAULT_RESPONSE_STATUS);
    statuses.set(id, numeric);
  }
  const out: DeclaredOperation[] = [];
  for (const entry of interfaceNamed(source, 'paths').members) {
    const template = memberName(entry);
    if (!template || !ts.isPropertySignature(entry) || !entry.type || !ts.isTypeLiteralNode(entry.type)) continue;
    for (const method of entry.type.members) {
      const name = memberName(method);
      if (!name || !ts.isPropertySignature(method) || !method.type) continue;
      const type = method.type; // `post: operations["login"]`
      if (!ts.isIndexedAccessTypeNode(type) || !ts.isLiteralTypeNode(type.indexType) || !ts.isStringLiteral(type.indexType.literal)) continue;
      const operationId = type.indexType.literal.text;
      out.push({ method: name.toUpperCase(), template, operationId, statuses: statuses.get(operationId) ?? [] });
    }
  }
  return out;
}

/** The declared operation a Gateway request (`METHOD /path`, query ignored) is an instance of. */
export function operationFor(method: string, gatewayPath: string, operations: DeclaredOperation[] = declaredOperations()): DeclaredOperation | undefined {
  const pathOnly = gatewayPath.split('?')[0]!;
  return operations.find((op) => op.method === method.toUpperCase() && new RegExp(`^${op.template.replace(/[.*+?^$()|[\]\\]/g, '\\$&').replace(/\\?\{[^}]+\\?\}|\{[^}]+\}/g, '[^/]+')}$`).test(pathOnly));
}
