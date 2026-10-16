// A population guard (stage 2 re-review advisory 1, binding for stage 3): every `<input type="number">` follows the place-order pattern.
//   1. `[appDraftValue]`: the box shows its draft WITHOUT writing back what it already holds (a `[value]` binding moves the caret of a number box under fast typing, B1 / item 8);
//   2. an `(input)` handler that reads `validity.badInput`: a text the browser cannot parse arrives as `""`, which must never be read as "not overridden" or "no amount" (B1);
//   3. no other binding that writes the box's value (`[value]`, `[valueAsNumber]`, `[valueAsDate]`, `[ngModel]`, `formControl`...): a second writer is the B1 hazard again (stage 3 review R8).
// TWO HALVES, because neither instrument sees everything (stage 3 review, B-S3-2):
//   SYNTAX HALF (this file): the component templates of src/app, read by the TypeScript parser (a TS comment is not a template) and an HTML parser (an HTML comment is not an input),
//     compared to a LITERAL expected set (src/app/testing/number-boxes.ts) both ways. Its limits are real and are covered by the render half, NOT by this file:
//       - a template the HTML parser misreads is not seen. Measured: an Angular block condition with `<` (`@if (a<b) { <input type="number"> }`) is swallowed as a tag (R6);
//         Angular's `bind-type="'number'"` prefix is not a `[type]` this file recognises (R7). The old header said a bound type "fails by name": only `[type]`, `[attr.type]` and `type="{{"` do.
//       - a template that is a variable or has an interpolation, `templateUrl`, an `.html` file and `createElement('input')` in code are REPORTED (fail by name), never skipped.
//       - a component is found by the SHAPE of its decorator (a call whose object literal has `template` or `templateUrl`), so an aliased import (`@Cmp`) is still found (R5). A decorator whose argument is NOT an object literal written in place (`@Component(META)` with `const META = {...}`) is NOT read (stage 3 re-review X3, armed as the demonstrated limit): resolving a const, an import or a spread is an unbounded static analysis, so this half does not attempt it; such a component is seen by the render half when a page renders it (X4), and an UNRENDERED one with const metadata is the residual.
//   RENDER HALF (src/app/error-text.sweep.spec.ts, "every rendered number box…"): over every state the sweep reaches (each page's load, each scripted action, AND every failing run: the DOM of each failed request), every element whose live `.type` is `number` has a `data-testid` in the
//     same literal set, and every expected box is rendered somewhere. It covers R5-R7 for anything a page renders. ITS limits: it sees only boxes the sweep's pages and scripted actions
//     put on screen (a box behind a state no script drives is invisible to it: armed demonstration `RH3`), and it does not see an unrendered component; the syntax half covers those only when the decorator carries an object literal (see above).
//   A box that is found by neither half (a state nobody drives, in a template the HTML parser misreads) is not caught: that residue is stated, not claimed away.
// The analyser is armed in the first describe by sentinels that must fail, so "no problems" is only believed from an instrument that has been seen to find them.
//
// WHAT THE SYNTAX HALF CANNOT SEE (defeat list rows 4, 5, 6, 11, 12), and what covers each:
//   row 4  (shadowed in a comment or string): handled: an HTML comment, a TS comment and a string saying "badInput" are sentinels.
//   row 5  (hidden in a dead region, `if (false)`, `@if (false)`): the region is SEEN and counted (stricter); a handler whose `badInput` read sits in dead code PASSES this half. Covered by
//          behaviour: R-bad-input (place-order.spec.ts), R-replenish-bad-input (stock.spec.ts), R-payment-bad-input and R-billing-age-bad-input (billing.spec.ts).
//   row 6  (raw or triple-quoted string): `String.raw`, plain and no-substitution templates are read; a variable or interpolated template is reported. NOT covered here: HTML the parser misreads (R6), see the render half.
//   row 11 (a form the instrument does not recognise): `[type]`, `[attr.type]`, `type="{{"`, `templateUrl`, `.html` and `createElement('input')` fail by name; `bind-type` and other Angular spellings
//          are NOT recognised here (R7): the render half covers them for rendered boxes.
//   row 12 (served through a path the population never drives): a box outside src/app is outside this half; the render half sees only driven states (RH3).
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import ts from 'typescript';
import { describe, expect, it } from 'vitest';
import { EXPECTED_NUMBER_BOXES } from './testing/number-boxes';

const APP = path.resolve(import.meta.dirname);

type Sources = Record<string, string>;

export interface Member {
  /** `<relative path of the component file> | <data-testid of the box>` */
  key: string;
  problems: string[];
}

interface Analysis {
  members: Member[];
  /** Things the analyser could not read or classify: each is a failure, never a skip. */
  unreadable: string[];
}

/** The text of a component's `template`, or why it cannot be read. */
function templateOf(object: ts.ObjectLiteralExpression): { text?: string; unreadable?: string } {
  for (const property of object.properties) {
    if (!ts.isPropertyAssignment(property) || !ts.isIdentifier(property.name)) continue;
    if (property.name.text === 'templateUrl') return { unreadable: 'templateUrl: the template lives in another file the guard does not read' };
    if (property.name.text !== 'template') continue;
    let value: ts.Expression = property.initializer;
    if (ts.isTaggedTemplateExpression(value)) value = value.template;
    if (ts.isStringLiteral(value) || ts.isNoSubstitutionTemplateLiteral(value)) return { text: value.text };
    return { unreadable: `template is not a plain literal (${ts.SyntaxKind[value.kind]}): the guard cannot read it` };
  }
  return {};
}

/** Real property reads of `badInput` in a method's code (comments and strings are not code). */
function readsBadInput(method: ts.MethodDeclaration): boolean {
  let found = false;
  const visit = (node: ts.Node) => {
    if (ts.isPropertyAccessExpression(node) && node.name.text === 'badInput') found = true;
    ts.forEachChild(node, visit);
  };
  visit(method);
  return found;
}

export function analyse(sources: Sources): Analysis {
  const members: Member[] = [];
  const unreadable: string[] = [];
  for (const [rel, source] of Object.entries(sources)) {
    if (rel.endsWith('.html')) {
      unreadable.push(`${rel}: an .html template the guard does not read`);
      continue;
    }
    const file = ts.createSourceFile(rel, source, ts.ScriptTarget.Latest, true);
    const visit = (node: ts.Node) => {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'createElement' && /^['"`]input['"`]$/i.test(node.arguments[0]?.getText() ?? '')) {
        unreadable.push(`${rel}: an <input> made in code (createElement): not a template, not seen`);
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
    file.forEachChild(function walk(node) {
      if (ts.isClassDeclaration(node)) {
        // Found by the SHAPE of the decorator (a call whose first argument is an object literal with `template` or `templateUrl`), not by the name `Component`: `@Cmp` after `import { Component as Cmp }` is still a component (R5).
        const decorator = ts.getDecorators(node)?.find((d) => {
          const argument = ts.isCallExpression(d.expression) ? d.expression.arguments[0] : undefined;
          return argument !== undefined && ts.isObjectLiteralExpression(argument) && argument.properties.some((p) => ts.isPropertyAssignment(p) && ts.isIdentifier(p.name) && (p.name.text === 'template' || p.name.text === 'templateUrl'));
        });
        const argument = decorator && ts.isCallExpression(decorator.expression) ? decorator.expression.arguments[0] : undefined;
        if (argument && ts.isObjectLiteralExpression(argument)) {
          const { text, unreadable: why } = templateOf(argument);
          if (why) unreadable.push(`${rel}: ${why}`);
          if (text !== undefined) {
            const holder = document.createElement('template');
            holder.innerHTML = text;
            const methods = new Map(node.members.filter(ts.isMethodDeclaration).map((method) => [method.name.getText(), method] as const));
            for (const input of holder.content.querySelectorAll('input')) {
              const typeBound = ['[type]', '[attr.type]', 'attr.type'].some((name) => input.hasAttribute(name)) || (input.getAttribute('type') ?? '').includes('{{');
              if (typeBound) {
                unreadable.push(`${rel}: an <input> whose type is bound (${input.outerHTML.slice(0, 80)}): the guard cannot tell whether it is a number box`);
                continue;
              }
              if ((input.getAttribute('type') ?? '').toLowerCase() !== 'number') continue;
              const testId = input.getAttribute('data-testid');
              const problems: string[] = [];
              if (!testId) problems.push('has no data-testid: it cannot be named in the expected set');
              if (!input.hasAttribute('[appdraftvalue]')) problems.push('has no [appDraftValue] binding');
              if (input.hasAttribute('[value]') || input.hasAttribute('[attr.value]')) problems.push('writes its draft with [value], which moves the caret of a number box');
              const writers = input.getAttributeNames().filter((name) => name !== '[value]' && name !== '[attr.value]' && VALUE_WRITERS.has(name.replace(/^bind-|^\[\(|^\[|\)\]$|\]$/g, '').replace(/^attr\./, '').toLowerCase()));
              if (writers.length) problems.push(`has a second writer of its value: ${writers.join(', ')}`);
              const handler = input.getAttribute('(input)');
              const name = handler === null ? undefined : /^\s*([A-Za-z_$][\w$]*)\s*\(/.exec(handler)?.[1];
              const method = name === undefined ? undefined : methods.get(name);
              if (handler === null) problems.push('has no (input) handler');
              else if (!method) problems.push(`its (input) handler "${handler}" is not a method of the component`);
              else if (!readsBadInput(method)) problems.push(`its (input) handler ${name}() does not read validity.badInput`);
              members.push({ key: `${rel} | ${testId ?? input.outerHTML.slice(0, 60)}`, problems });
            }
          }
        }
      }
      ts.forEachChild(node, walk);
    });
  }
  return { members, unreadable };
}

/** Bindings (by the name Angular sees, lower-cased) that write an input's value: a second writer beside `[appDraftValue]` (stage 3 review R8). */
const VALUE_WRITERS = new Set(['valueasnumber', 'valueasdate', 'ngmodel', 'formcontrol', 'formcontrolname', 'value']);

function appSources(): Sources {
  const out: Sources = {};
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      const rel = path.relative(APP, full).split(path.sep).join('/');
      if (entry.isDirectory()) {
        if (rel !== 'testing') walk(full);
      } else if ((rel.endsWith('.ts') && !rel.endsWith('.spec.ts')) || rel.endsWith('.html')) out[rel] = readFileSync(full, 'utf8');
    }
  };
  walk(APP);
  return out;
}

const component = (template: string, body = '') => `import { Component } from '@angular/core';\n@Component({ selector: 'x', template: ${template} })\nexport default class X {\n${body}\n}\n`;
const good = `<input type="number" data-testid="a" [appDraftValue]="d()" (input)="typeA($any($event.target))" />`;
const goodMethod = `typeA(target: HTMLInputElement): void { this.bad.set(target.validity?.badInput === true); }`;
const problemsOf = (sources: Sources) => {
  const { members, unreadable } = analyse(sources);
  return { members: members.map((m) => [m.key, m.problems.length] as const), unreadable };
};

describe('the analyser is armed: each of these must be found, and the clean case must not be', () => {
  it('a clean number box has both properties and no problems', () => {
    expect(analyse({ 'x.ts': component('`' + good + '`', goodMethod) })).toEqual({ members: [{ key: 'x.ts | a', problems: [] }], unreadable: [] });
  });

  it('a BARE number box (no appDraftValue, no handler) is reported with both problems', () => {
    const { members } = analyse({ 'x.ts': component('`<input type="number" data-testid="a" />`') });
    expect(members[0]!.problems).toEqual(['has no [appDraftValue] binding', 'has no (input) handler']);
  });

  it('[value] with $event.target.value (the B1 shape) is reported', () => {
    const { members } = analyse({ 'x.ts': component('`<input type="number" data-testid="a" [value]="d()" (input)="set($any($event.target).value)" />`', 'set(v: string) {}') });
    expect(members[0]!.problems).toEqual(['has no [appDraftValue] binding', 'writes its draft with [value], which moves the caret of a number box', 'its (input) handler set() does not read validity.badInput']);
  });

  it('appDraftValue with a handler that never reads badInput is reported (delete the second property)', () => {
    const { members } = analyse({ 'x.ts': component('`' + good + '`', 'typeA(target: HTMLInputElement): void { this.d.set(target.value); }') });
    expect(members[0]!.problems).toEqual(['its (input) handler typeA() does not read validity.badInput']);
  });

  it('a badInput that is only in a comment or a string in the handler does not count (row 4)', () => {
    const { members } = analyse({ 'x.ts': component('`' + good + '`', 'typeA(target: HTMLInputElement): void { /* validity.badInput */ const s = "target.validity.badInput"; this.d.set(target.value + s); }') });
    expect(members[0]!.problems).toEqual(['its (input) handler typeA() does not read validity.badInput']);
  });

  it('an inline lambda handler is not a method and is reported', () => {
    const { members } = analyse({ 'x.ts': component('`<input type="number" data-testid="a" [appDraftValue]="d()" (input)="d.set($any($event.target).value)" />`') });
    expect(members[0]!.problems).toEqual(['its (input) handler "d.set($any($event.target).value)" is not a method of the component']);
  });

  it('an appDraftValue removed from a member that has the handler is reported (delete the first property)', () => {
    const { members } = analyse({ 'x.ts': component('`<input type="number" data-testid="a" (input)="typeA($any($event.target))" />`', goodMethod) });
    expect(members[0]!.problems).toEqual(['has no [appDraftValue] binding']);
  });

  it('a box with no data-testid is reported, so it cannot join the population unnamed', () => {
    const { members } = analyse({ 'x.ts': component('`<input type="number" [appDraftValue]="d()" (input)="typeA($any($event.target))" />`', goodMethod) });
    expect(members[0]!.problems).toEqual(['has no data-testid: it cannot be named in the expected set']);
  });

  it('a number box in an HTML comment, or in a TypeScript comment, is not a member (row 4: the shadow is not the thing)', () => {
    expect(problemsOf({ 'x.ts': component('`<!-- <input type="number" data-testid="ghost" /> -->`') }).members).toEqual([]);
    expect(problemsOf({ 'x.ts': `// <input type="number" data-testid="ghost">\n` + component('`<p>none</p>`') }).members).toEqual([]);
  });

  it('a number box in a dead @if region IS seen (row 5: stricter, never looser)', () => {
    expect(problemsOf({ 'x.ts': component('`@if (false) { <input type="number" data-testid="dead" /> }`') }).members).toEqual([['x.ts | dead', 2]]);
  });

  it('a template in a String.raw tag, a plain string and a no-substitution template are all read (row 6)', () => {
    const bare = '<input type="number" data-testid="a" />';
    for (const literal of ['String.raw`' + bare + '`', `'${bare}'`, '`' + bare + '`']) expect(problemsOf({ 'x.ts': component(literal) }).members, literal).toEqual([['x.ts | a', 2]]);
  });

  it('a template that is not a plain literal (a variable, an interpolation), a templateUrl, an .html file and an input made in code are reported, never skipped (row 11)', () => {
    expect(analyse({ 'x.ts': component('TEMPLATE') }).unreadable).toEqual(['x.ts: template is not a plain literal (Identifier): the guard cannot read it']);
    expect(analyse({ 'x.ts': component('`<p>${1}</p>`') }).unreadable).toHaveLength(1);
    expect(analyse({ 'x.ts': `import { Component } from '@angular/core';\n@Component({ selector: 'x', templateUrl: './x.html' })\nexport default class X {}\n` }).unreadable).toHaveLength(1);
    expect(analyse({ 'x.html': '<input type="number">' }).unreadable).toEqual(['x.html: an .html template the guard does not read']);
    expect(analyse({ 'x.ts': `export const make = () => document.createElement('input');\n` }).unreadable).toHaveLength(1);
  });

  it('an input whose type is BOUND is reported (it could be a number box)', () => {
    expect(analyse({ 'x.ts': component('`<input [type]="kind" data-testid="a" />`') }).unreadable).toHaveLength(1);
    expect(analyse({ 'x.ts': component('`<input [attr.type]="kind" data-testid="a" />`') }).unreadable).toHaveLength(1);
  });

  it('an aliased decorator import (@Cmp) is still a component (R5)', () => {
    const source = `import { Component as Cmp } from '@angular/core';\n@Cmp({ selector: 'x', template: \`<input type="number" data-testid="a" />\` })\nexport class X {}\n`;
    expect(problemsOf({ 'x.ts': source }).members).toEqual([['x.ts | a', 2]]);
  });

  it('a second writer of the value is reported: [valueAsNumber], [valueAsDate], [(ngModel)], bind-valueAsNumber, [formControl] (R8)', () => {
    for (const writer of ['[valueAsNumber]="+d()"', '[valueAsDate]="when()"', '[(ngModel)]="d"', 'bind-valueAsNumber="+d()"', '[formControl]="control"']) {
      const { members } = analyse({ 'x.ts': component('`<input type="number" data-testid="a" [appDraftValue]="d()" (input)="typeA($any($event.target))" ' + writer + ' />`', goodMethod) });
      expect(members[0]!.problems, writer).toHaveLength(1);
      expect(members[0]!.problems[0], writer).toContain('has a second writer of its value');
    }
  });

  it('text, checkbox and search inputs are not number boxes', () => {
    expect(problemsOf({ 'x.ts': component('`<input type="text" /><input type="checkbox" /><input />`') }).members).toEqual([]);
  });
});

describe('R-number-boxes: every type="number" input under src/app follows the place-order pattern', () => {
  const sources = appSources();
  const { members, unreadable } = analyse(sources);

  it('the population is read off the disk: it contains the component files of the pages, and the ui primitives are in it', () => {
    expect(Object.keys(sources).length, 'the walk found nothing: it is not reading src/app').toBeGreaterThan(30);
    expect(Object.keys(sources)).toEqual(expect.arrayContaining(['pages/(app)/stock/index.page.ts', 'pages/(app)/billing/index.page.ts', 'pages/(app)/orders/place.page.ts', 'ui/input/src/lib/hlm-input.ts']));
    expect(Object.keys(sources).filter((rel) => rel.startsWith('testing/'))).toEqual([]);
  });

  it('nothing is unreadable: no templateUrl, no .html, no bound type, no template that is not a literal, no <input> made in code', () => {
    expect(unreadable).toEqual([]);
  });

  it('the number boxes are exactly the reviewed ones (a new box, or a vanished one, fails by name)', () => {
    const found = members.map((member) => member.key).sort();
    const added = found.filter((key) => !EXPECTED_NUMBER_BOXES.includes(key));
    const vanished = EXPECTED_NUMBER_BOXES.filter((key) => !found.includes(key));
    if (added.length || vanished.length) expect.fail(`the number boxes differ from the reviewed set. A box the guard has not been told about (add it to EXPECTED_NUMBER_BOXES, with [appDraftValue] and a validity.badInput handler): ${JSON.stringify(added)}. A reviewed box that no template has: ${JSON.stringify(vanished)}`);
    expect(found).toEqual(EXPECTED_NUMBER_BOXES);
  });

  it.each(EXPECTED_NUMBER_BOXES)('%s: [appDraftValue] and a validity.badInput handler', (key) => {
    const member = members.find((candidate) => candidate.key === key);
    expect(member, `${key} is not in the population`).toBeDefined();
    expect(member!.problems).toEqual([]);
  });
});
