# Lessons — the incident record behind CLAUDE.md's rules

> **Archive, not instructions.** This is the full text of `CLAUDE.md` as it stood on 2026-09-17, before it was cut from 81 KB to about 12 KB. The cut was made at the maintainer's request after phase 16 used 24% of a weekly allowance in under a day: the file rides along in every agent's context on every turn. The rules themselves live in `CLAUDE.md`. This file keeps the evidence, the incidents and the reasoning behind each rule. Read the relevant section **only** when you need to know why a rule exists or how a failure looked. Do not load it by default.

---

# (archived) CLAUDE.md — Leader role and project conventions

> Loaded automatically at the start of every session. Read `AGENTS.md` for the repository map, this file for *how we build things here*.

## Project

**Order To Cash** — an order lifecycle backbone for a B2B EDI / e-invoicing platform, built as event-driven microservices with an orchestrated saga. Assessment **#8 of a trilogy** (#7 = NestJS, completed; #9 = FastAPI) that implements the same specification three times.

**This is the reuse run, and it changes what "good" means here.** `specs/shared/`, this harness, the n8n workflows and the stack-agnostic infra configs were **copied from `peelmicro/order-to-cash-nestjs`, not written**. Two consequences bind every decision below:

1. **`specs/shared/` is read-only.** A change to it is a **spec amendment** — explicit, human-gated, committed on its own, and back-ported to #7. Never a silent fork. A #8 that quietly "improved" the spec has destroyed both things this repository exists to produce: the parity claim and the benchmark.
2. **Per-feature effort is recorded** in `progress/history.md` (sessions + wall-clock) against #7's baseline. The features that were **not** faster are the interesting ones — record them with the same care as the wins.

---

## Mandatory role: leader

In this repository you act **always** as the `leader` subagent defined in `.claude/agents/leader.md`. Your job is to **decompose and coordinate**, not to implement.

### Hard rules

- ❌ **Do not edit** files under `src/`, `tests/` or `apps/web/` directly (not with Edit, Write, or Bash). Launch `implementer`.
- ❌ **Do not mark** features `done` in `feature_list.json` — the `reviewer` does.
- ❌ **Do not skip the spec phase** for any `"sdd": true` feature.
- ❌ **Do not skip the human approval gate** between `spec_ready` and `in_progress`.
- ✅ For any code task, launch the right subagent via the `Agent` tool:
  - `spec_author` → writes `specs/<name>/{requirements,design,tasks}.md`
  - `implementer` → writes code + tests for **one** approved feature
  - `reviewer` → validates traceability and completeness before closing
  - `test_maintainer` → mechanical test updates after a landed change
  - For research first, launch 2–3 `Explore` agents in parallel with narrow questions.

### When this role does not apply

- Conceptual questions or repo exploration (pure reading) → answer directly.
- Changes outside `src/`, `tests/` and `apps/web/` (docs, compose, `infra/`, `progress/`, `n8n/`, root config) → you may edit those yourself.

### Briefing subagents economically

A subagent's cost is dominated by exploratory reading, so a brief that names its inputs is cheaper *and* more accurate than one that makes it hunt:

- **Name the files.** List the exact paths to read and in what order. "Read the spec" costs an order of magnitude more than "read `specs/x/tasks.md`, then `design.md` §4, then `apps/orders/src/domain/order.ts`".
- **State what already exists** so it does not rediscover it — the conventions in force, the reference implementation to copy, the decisions already taken at the gate.
- **Bound the scope explicitly.** Say which files it may touch and which it must not; "do not re-touch anything else" prevents whole categories of exploration.
- **Route mechanical test work to `test_maintainer`** (haiku) rather than the implementer: retitles, assertion updates after a landed change, timeout budgets, config guards. It is cheaper by a tier and constitutionally unable to edit source.
- **Never forbid in a brief what the approved `tasks.md` mandates.** A gate-approved spec outranks the brief that dispatched the work — that is already the ruling here — so a brief that contradicts it does not constrain the subagent, it just manufactures a false finding for the reviewer to spend a round on. Found in feature 16, where the brief said "you MUST NOT edit `feature_list.json`" while task M5 of the approved task list said "set `order_saga_orchestrator` to `in_review` in `feature_list.json` and stop". The implementer correctly followed the spec and the review had to adjudicate a conflict that should never have existed. **Before writing a scope bound, read the whole task list** — not just its bookkeeping tasks — and phrase every bound around what it already mandates: "make no change to `feature_list.json` beyond the transition `tasks.md` itself asks for", "touch no service other than the ones `tasks.md` names".

  **This rule was then broken again, one phase later, by the leader who wrote it** — a brief for `fulfillment_stock` said "do not touch `src/Orders/`" while task group A of the approved spec required exactly three files there, for a cross-service change the feature genuinely needed. The first version of this rule said *read the task list's own bookkeeping tasks*, so it was read for bookkeeping and not for source. **The bound must be derived from the task list, never written from an assumption about which directories a feature ought to need** — a feature that composes with another service will say so in its tasks, and a coordinator who has not read them is guessing.
- **Never supply, in a brief, the answer to a question a rule says must be researched.** A brief that says *"the correct answer is almost certainly X"* converts a research task into a transcription task, and the subagent will write X down — with the leader's authority behind it. Found in phase 14, Slice A. `CLAUDE.md` requires a ledger row's *"#7 relied on X"* half to be read out of #7's checkout with a file and line; the leader's fix-round brief instead told the implementer the answer was *"almost certainly none owed — this is #8-only harness work"*. It was wrong on both halves: #7 has four `apps/*/drizzle.config.ts` design-time configs reading the same five roles including the sibling key `MYSQL_DB_BILLING` (`apps/billing/drizzle.config.ts:21`), guarded by nothing; and its `main.ts` is not importable in five of six services (`apps/billing/src/main.ts:13,48`), the one exception documenting itself at `apps/orders/src/main.ts:125-135`. **The implementer wrote it down, the reviewer's own round-1 paragraph had said the same thing, and it took a third pass to catch** — three independent assertions of one unresearched premise, because the first one came from the brief.

  The distinction is not "say less". *State what already exists* is still right, and cheap: facts the leader has **verified**, with citations, save real exploration. What may never be supplied is a **conclusion to the question the task is about** — especially prefixed with "almost certainly", which reads as permission to skip the check. Phrase it as the question plus where to look: *"determine whether a row is owed, citing #7's checkout either way"*, not *"no row is owed"*.

- **Run `premise_checker` over a brief before dispatching it, and over any recommendation before the human acts on it.** Adopted at the human gate on 2026-09-13, after the maintainer asked what the apparatus is for if the coordinator's own suggestions are wrong. It was the right question: **every mechanism here checks something that executes** — arming checks guards, review checks implementations, enumeration checks sweeps — and **nothing reads the leader's prose.** A brief and a recommendation are the only artefacts in this project that no instrument touches, which is precisely why they are where the errors survive: nothing compiles them, so a false premise lives until someone spends an implementation cycle discovering it.

  The bright line that sorts the failures, applied when writing rather than remembered afterwards: **did I produce this fact with a command, in this session?** If yes, state it and carry the command. If no, it is a question for the subagent, never an assertion. On phase 14's record that line is exact in both directions — every claim the leader got right came from a command it ran (a counted population, a schema read, a site verified line by line); every claim it got wrong was copied from prose or inferred (*"neither repository has X"* when one did, the wrong test harness recommended, a 24-file feature sized as a "small alignment").

  Being a rule, that line will fail exactly when attention is elsewhere, like every other memory-enforced rule in this file. `premise_checker` is the part that does not depend on the leader remembering: read-only, sonnet, one line per claim, VERIFIED / FALSE / UNVERIFIABLE with the command quoted. The economics remove the judgement call — a wrong brief costs an implementer cycle, measured at **140k–370k tokens** in phase 14; the check costs a fraction of one. Run it; do not deliberate about whether this brief is worth it.

- **Name the unit in every criterion a brief sets — and never let a sample stand in for the population.** Adopted at the human gate during phase 14's wrap-up, after four briefs written by the leader in two features each checked the wrong unit, and each cost a round. `CLAUDE.md` already said *"classify the unit the claim is about"* — but only for sweeps an agent runs. All four failures were in **criteria the leader wrote into a brief**; the agent then applied them faithfully, so the defect entered at the brief and every downstream check inherited it.

  | Brief | Unit it used | Unit the claim was about | What escaped |
  |---|---|---|---|
  | Feature 27, Group N re-arm criterion | the **group** that touched a file | the **arm** it made stale | 13 of 27 ledger rows touched after their arm, including a real regression (an unbounded in-flight health call) |
  | Feature 27, review-round-1 fix, §11 walk | the **class** name | the **test case** | five row groups marked "Exists" with no case |
  | Feature 27, review-round-2 fix, §11 walk | the **reviewer's sample** (19 groups) | the **table** (41 groups) | about 22 groups never walked; caught only because the leader counted the table before re-review |
  | Leader's verification of the L21 arms | "the arm is deterministic" | **which artefact** holds the determinism — test or mutation | a delay inserted into the **mutation** while both tests never overlapped; the plain defect passed 3/3 |

  So:
  - **Name the unit** of every acceptance criterion a brief sets: arm, case, row, site, copy, branch, ordering, invocation path.
  - **When a sample exists** — a reviewer's probe set, a previous round's table — state that it is evidence and **not the population**, and give the command that counts the population.
  - **Before dispatching a re-review, count the population yourself** and compare it with the record's.
  - **A verification step a brief prescribes must be able to fail.** The same phase found a brief telling an implementer that `dotnet build` would catch broken doc-comment `cref`s while `GenerateDocumentationFile=false` guaranteed it could not — backlog id 78.
- **Route long, noisy command runs to `suite_runner`** (haiku) when the output would otherwise flood context — it returns exit code, counts and verbatim failure blocks, and interprets nothing. Do not use it for anything requiring judgement, and never let it replace probing evidence yourself.
- **`reviewer`: probe the claims, do not re-run the world.** Re-running a suite the implementer just ran is duplicated cost; the value is in the independent mutation probes, the traceability walk and the specific claims under test. Re-run in full only when the claim *is* about the full suite.

### `feature_list.json` is a single-writer file

Never run two subagents concurrently when both may write the backlog. They will not conflict on source — different features touch different directories — but a `reviewer` closing one feature and anything else transitioning another are both read-modify-write on the same JSON, and the later write silently reverts the earlier one.

The reason this is worth a rule rather than care: **`init.sh` cannot catch it.** A status reverted from `spec_ready` to `pending` is still a *valid* status, still has at most one `in_progress`, and still satisfies SDD coherence — so the coherence check passes while the state is wrong. That is the guard-that-does-not-guard shape once more, and the only defence is not to create the race. Found in Phase 8, where a review and a spec revision were launched in parallel and a `spec_ready` transition was lost.

**And no agent may run `git checkout --` on `feature_list.json`, ever.** Found in feature 16, where a reviewer reformatted the file, thought better of it, and reverted with `git checkout --` — which restored the *last committed* version and silently destroyed the leader's uncommitted backlog entry for a defect found in already-closed work. The file is almost always dirty: it carries the current feature's transitions and anything anyone has added since the last commit, so reverting it to HEAD discards other writers' work by construction, not by accident.

**It happened a second time, one feature after the rule was written, and the second occurrence names the real trigger.** An implementer rewrote the file with a JSON round-trip that lacked `ensure_ascii=False`, re-escaping every non-ASCII character in the file, and reached for `git checkout --` to undo the mess. Both incidents began the same way: **a whole-file rewrite went wrong, and reverting looked like the only way back.** So the rule as written — *to undo an edit, re-edit it* — is sound advice that arrives too late, because by then there is a whole mangled file to re-edit rather than one line.

The actionable form is therefore upstream of the revert: **do not rewrite this file to change one value.** Edit the single line. If you do parse and re-serialise it, `json.dumps(..., indent=2, ensure_ascii=False)` reproduces this file's formatting exactly, and `git diff` showing **only the lines you meant to change** is the check that it did — run that check *before* moving on, while the mistake is still one command from being fixed by hand. Not a line count: a legitimate edit that adds a backlog entry is a dozen lines or more, so counting insertions would cry wolf. Read the diff.

**The rule is about the dirty tree, not about one command — and naming one command is why it failed.** Phase 14, id 72's fix round 4: an implementer wanted to read `specs/shared/test-matrix.md` as it exists at HEAD, to compare a whole-file column hash. It ran **`git stash`, then `git stash pop`** — against a working tree carrying **153 uncommitted changes across four features**. It was lossless, and it was found only because an unrelated check classified files by modification time and returned ~120 source files rewritten at one instant. The signature is worth knowing: `.git/ORIG_HEAD` written, the reflog entry `reset: moving to HEAD` (stash's default push hard-resets the tree internally), an **empty** `git stash list`, and two dangling commits — `WIP on main: <sha>` and `index on main: <sha>` — that `git fsck --unreachable` will show.

So: **no agent may run any git command that writes the index or the working tree — `stash`, `reset`, `restore`, `clean`, `checkout` — on this repository, for any reason.** Reading history is always safe and is almost always what was actually wanted: **`git show HEAD:<path>`** prints a file as committed without touching anything, and `git diff`, `git log`, `git status`, `git fsck` are read-only. In this incident the implementer had *already* run `git show HEAD:specs/shared/test-matrix.md | … | md5sum` correctly, six times, in the same block — then reached for a repo-wide operation to ask the same question once more. If you want one file at HEAD, `git show` is the whole answer.

Three reasons this is worse than the `checkout --` case it generalises, not milder:
- **It fails silently.** `git checkout --` on an untracked path errors out and restores nothing, so the mistake announces itself. A stash cycle succeeds, and the tree afterwards looks untouched except for timestamps.
- **A conflicting pop strands everything at once.** Not one file — the entire uncommitted state of every in-flight feature, in a dangling commit recoverable only by someone who thinks to run `git fsck --unreachable`. With 153 dirty files and no other copy, that is the whole session's work.
- **`-u` would have taken the record too.** Default `stash` leaves untracked files alone, which is the only reason this one was harmless: the 26 untracked files included that feature's two new test files and every `progress/impl_*.md` and `review_*.md`. `git stash -u` would have moved them, so a failed pop would have destroyed the evidence that the work happened along with the work.

And the leader's own lesson from tracing it: **a subagent's self-reported wall-clock range is not evidence of when it ran.** The first attribution went to the wrong agent because its record said *"≈12:35 → 12:55"* and the timestamp fell inside that window; the filesystem — transcript and log mtimes — placed a different agent across the event. Ask git and the filesystem, then ask the agent.

The reason this needs saying separately from the arming protocol's own no-`git checkout` rule is that the arming rule is justified by files being **untracked** — and `feature_list.json` is tracked, so a reader who has internalised that rule will conclude it does not apply. It applies more. And **`init.sh` cannot catch it**: a backlog with a feature missing is still a valid backlog, still has at most one `in_progress`, still satisfies SDD coherence. That is now the third disguise of the guard-that-does-not-guard in this file — a check that fires on nothing, a check run against the wrong artefact, and a check whose invariants are all satisfied by an incorrect state. To undo an edit to this file, re-edit it.

Parallelism across subagents is still worth having — just never with the backlog in two writers' hands at once. Sequence the one that writes it, or have only one of them own it.

### The injected copy of this file is a cache — check the disk

This repository amends its own conventions at human gates, mid-project, on purpose: the wire-shape non-negotiable changed in Phase 5, and the arming protocol gained two clauses in Phases 5 and 6. Any copy of this file injected into an agent's context was taken when that session started and **is expected to go stale**.

So: before enforcing or quoting a rule from here — in a brief, in a review, in a report — `grep` the file on disk. A reviewer that rejects work against a superseded rule is a guard firing on something no longer true, which is the guard-that-does-not-guard inverted and just as expensive. Found in Phase 7, where it produced one spurious advisory against correct code.

### The ported-idiom ledger — the one defect class nothing else here can see

**Every feature that ports a #7 mechanism carries a ledger: a short section listing, one line per ported idiom, *"#7 relied on X; in #8 that property is supplied by Y."* Where the property was supplied by #7's engine, language or library and must be hand-built here, a guard test is required and named.** Adopted at the human gate closing Phase 8; **bound to the port rather than to the document at the human gate opening Phase 13.**

**Where the ledger lives depends on the feature, and this is the part that was wrong for four phases.** For an `sdd: true` feature it belongs in `design.md`, with its guards named in `tasks.md`. For an **`sdd: false` feature it belongs in `progress/impl_<feature>.md`**, beside the arming table the implementer already writes there, with its guards named in the same place — no new document and no extra ceremony.

**The original rule said `design.md`, and an `sdd: false` feature has none — so the rule silently exempted exactly the features most likely to need it.** Phase 10 found the consequence and recommended the fix: feature 22 ported #7's payment handler wholesale, had no `design.md`, carried no ledger, and its one finding of substance was a textbook ledger miss — *#7 relied on a `markPaid` that returns its event id; in #8 that property is supplied by nothing.* Traceability could not see it (the requirement was satisfied), arming could not see it (nine mutations, eight kills, none nearby), and it took a reviewer reading #7's source for an unrelated question.

**The recommendation then sat unactioned for two phases while three ported services shipped**, which is its own finding: a recommendation inside a closing assessment is read once, by whoever writes the next brief, and then only if they go looking. Phase 13 is where it finally bit hard enough to act on — every one of its six features is `sdd: false`, and its central feature ports #7's gateway wholesale. **#7's own record is the argument**: its `gateway_rest_auth` was rejected twice, and the first rejection was, in its historian's words, *the first defect no test in the repository could have caught, because both sides of the seam were tested only against the wire each preferred.* A NATS wire mismatch between a client and the responders it calls, each side green against its own assumption. That is a ported-idiom defect in its purest form, and under the old rule the #8 feature that inherits it would have owed no ledger at all.

The evidence is three defects, and what makes them one class is not the mechanism but the way they hid:

| Property | #7 got it from | #8's rendering | How it surfaced |
|---|---|---|---|
| Payload key order on the wire | MySQL's `json` column normalisation, leaking through the relay | Treated as a byte-exact parity requirement | Captured twelve real envelopes and looked |
| Money never truncates | JavaScript numbers have no narrowing conversion | `int` columns with a narrowing cast, justified as "spec parity" | The human asked whether it was a mistake |
| The counter row seeds atomically | `INSERT … ON DUPLICATE KEY UPDATE`, unconditional | `IF NOT EXISTS (SELECT …) INSERT` — check-then-act | A review of a *later* feature read the SQL |

**All three satisfied their requirement text exactly.** So `R<n>` → test traceability cannot see them: the requirement was met. And **arming cannot see them either**, because the behaviour was present and correct on the path the test took — the lost property only shows under a condition the test never created (a second writer, a value above `int.MaxValue`, a different storage engine). Two of this repository's three strongest guards are structurally blind to this class, which is why it needs its own line rather than more of either.

None of the three was found by the process. One was found by capturing real bytes, one by the human asking a question, one by a reviewer reading SQL for an unrelated feature. That is a 0-for-3 detection record on a class that has cost real rework every time, and phases 9–13 port five more services from the same source.

**A ledger row's Guard column is itself a countable claim, and a countable claim is not done until it has been seen to fail.** Adopted after feature 19, where a row correctly identified a property #7 got from its database driver, the code that supplied it was correct, and the row's named guard **could not fail**: the test re-implemented the conversion instead of reading through the mapper, so the task list's own prescribed mutation left the suite green. The enumeration worked and the guard was decorative — which is the ledger's own version of the failure it exists to catch, one level up. Naming a guard in `tasks.md` creates the obligation to arm it; it does not discharge it.

**An engine claim probed in one direction is a claim about that direction only.** A ledger row asserting how a database, driver or broker behaves is a **countable claim about a symmetric situation**, and running the probe one way answers half of it. Found twice on the same row, in consecutive rounds of feature 24: the row first claimed two index filters would conflict (they do not), and its correction then explained the right answer with the wrong mechanism — that the server normalises a type alias *when storing* it. It does not; it normalises when *comparing*. Creating with the alias first stores the alias, which the reverse-order probe showed immediately and the forward-order probe could never have shown.

**Where a row's claim involves two parties — two writers, two orderings, two creation sequences — the probe runs both ways or the row states which way it was run.** The second occurrence is the one that makes this a rule rather than a note: the wrong mechanism had reached a **test name**, and a test name is how the next assessment reads a question as settled. A ledger exists to carry properties across stacks; a confidently wrong row in it is worse than an absent one, because it will be inherited rather than re-derived.

**A ledger row has two halves, and the *"#7 relied on X"* half is a claim about #7's source code — so it is read out of #7's checkout, with a file and line, never inferred from what the framework would plausibly have done.** Found on the very first feature to carry a ledger under the port-bound rule, in phase 13. The row said #7 got one-instance reuse from *"module-scoped provider singletons … declaratively, with nothing to configure wrong."* #7's `app.module.ts:123-137` does the opposite: an explicit `useExisting` alias between two distinct tokens, carrying its own warning comment about why it is not a second factory. The row's **guard** half was real and had teeth; its **history** half was written from an assumption about NestJS.

**And *"none owed"* is a claim about #7 exactly like any other, needing the same citation.** Phase 14's Slice A guarded 20 design-time `IDesignTimeDbContextFactory` env reads and recorded *"no ledger row owed — #8-only harness work"*. Three people asserted it: the implementer wrote it, the reviewer's first-round paragraph agreed, and the leader's brief had supplied it. All three were wrong. #7 has the identical mechanism — four `apps/*/drizzle.config.ts` files reading host, port, user, password and a **sibling-family** database key (`MYSQL_DB_BILLING`/`_FULFILLMENT`/`_NOTIFICATIONS`/`_ORDERS`) — and guarded it with nothing, so a row was owed recording a **strengthening**, which is one of the more valuable rows a ledger can carry for #9.

A negative ledger verdict is the easiest place in this harness for an unchecked premise to settle, because it produces no row to review: absence looks like completion. **So "none owed" is written only after the same search that would have produced a row** — name the #7 path you looked in and what you found there, in one line. Where the mechanism exists in #7 and is *unguarded*, that is not "nothing to port": it is the row worth writing.

That asymmetry is why this needs its own rule rather than more care. A wrong guard fails loudly the moment it is armed. **A wrong history half cannot fail at all** — nothing executes it, the guard beside it still passes, and it is precisely the half #9 inherits and has no reason to re-derive. The ledger exists to carry *what made the original correct*; a row that misdescribes that has kept the ceremony and thrown away the cargo.

It also costs almost nothing to get right: #7's checkout is on disk, and the difference between *"NestJS singletons make this automatic"* and *"#7 aliased two tokens with `useExisting` and left a comment explaining why"* is one `grep`. Cite the file and line in the row, the way any other claim about another repository is cited here.

**Both halves of a row are claims, and tightening one displaces attention onto it.** Two consecutive phase-13 features were rejected with **the citation half correct and the guard half hollow** — the second one naming a guard whose own *"in #8"* column already explained that the test does not call the code the row is about. The rule requiring a file-and-line citation into #7 was added between those two features, and it worked: the citations became accurate. It also moved where the care went.

That is worth stating because it is the general shape of every fix in this file: **a rule that hardens one half of a two-part claim does not harden the other, and will quietly borrow attention from it.** When you write a row, the last thing to check is not the sentence you just tightened — it is the one you did not. For a ledger row that means reading the named guard and asking *does this test execute the code this row is about?*, which is a different question from *does this test pass?* and from *does deleting the behaviour break it?*

**Writing the line is most of the value.** The failure in all three cases was not analytical difficulty — it was that nobody asked *"what made this correct over there, and does that thing exist here?"* at the moment of translating. A one-line ledger forces the question at spec time, when the translation is being thought about anyway and the answer is nearly free.

### When you port a mechanism, port its guards — enumerate #7's tests, not only its source

**Both phase-13 rejections were the same shape: a guard #7 wrote, dropped in translation, found by review rather than by us.** Feature 40 lost #7's `includeDisabled` controller assertion, so forcing that flag to a constant left the whole suite green. Feature 41 lost #7's compensation-reason assertion, so transposing the two arms of the reason branch left 337 unit and 6 container tests green — and that one mattered, because a mislabelled reason makes `Order.Cancel` throw and strands the order mid-compensation.

Neither was hard to prevent. **Both guards existed, in a checkout on this machine, in files named after the thing being ported.** The ledger already forces reading #7's *source* to answer *"what supplied this property there"*; nothing forced reading #7's *tests* to answer **"what did they check about it, and does an equivalent exist here?"**

So, when porting: **enumerate #7's test files for the mechanism and classify each assertion — ported, deliberately not ported (with the reason), or not applicable.** It is a search result, not a reading: the command, its complete output, one line per hit.

This is narrower than it sounds, and that is the point. It does not ask for #7's tests to be reproduced — #8's suites are structured differently and frequently assert more. It asks that a guard which existed and stopped existing be **noticed**, because the alternative is what happened twice in one phase: shipping a branch whose behaviour nothing checks, in code whose predecessor checked it.

### When the work targets a defect CLASS, enumerate the class repository-wide before fixing any instance

Five backlog entries were grouped into one loop because they shared a cause — *a guard whose assertion cannot detect the defect it names*. The grouping was right, and its own blocking defect proved it: a prose completeness claim where a search result was required, caught only because the control that exposed it — the same mutation on a sibling service that **has** the missing row — was already in that session's context. Run separately, the likeliest outcome is a green suite recorded as a pass.

**What the grouping did not buy is the thing that then escaped.** Each entry was fixed at the sites it named, and nobody enumerated the class across the repository — so the retired shape survived in **three more files**, two of them in the same assembly, under the **same test name**. Measured, not suspected: an undeclared property left one suite 362/362 green and another 124/124 green.

So: **when a loop's theme is a defect class rather than a defect, its first task is one repository-wide enumeration of that class — as a search result, before any fix.** The instances named in the backlog are where the class was *noticed*, never where it *ends*, and an entry filed from one sighting will otherwise be closed while the class is still live. This is the same lesson as *a fix prescribed at a line closes a line; a fix prescribed at a class closes a class* — arrived at from the other direction, and it has now cost a rejection each way.

### An audit phase needs a stopping rule, written before it starts

**Phase 14 found defects faster than it closed them, and nothing in this harness noticed.** It closed nine features and filed ten new entries; the backlog grew from 77 to 89 while the work itself went well. Every entry filed was real — that was never in question, and several were production defects (a saga fast path that stalled every order behind one dead responder; a deadlock victim escaping the outbox relay; an architecture rule blind to the dominant shape of two services' business logic). The phase ended only because the maintainer stopped it, and eleven entries were then **dispositioned with documented evidence rather than worked**.

The failure is not that the audit found things. It is that **"is this defect real?" and "is this defect worth the budget?" are different questions, and only the first was ever being asked.** An entry that passes the first test gets filed, briefed, implemented, reviewed and closed — and at this project's measured rate that is **200k–800k tokens each** (one entry cost 432k). Fifteen open entries is therefore a multi-million-token commitment that nobody ever decided to make, arrived at one reasonable filing at a time.

So, for any phase whose theme is auditing rather than building:

- **Write the stopping rule at the start, in the phase's own plan**: how many entries it may open, or what class of finding closes it, or a budget. Any of the three works; having none does not.
- **Give every filed entry a disposition, not just a status.** *Fix*, or *accept with evidence*, or *re-open only if X*. "Pending" is not a disposition — it is a decision deferred, and deferred decisions accumulate silently because each one looks free.
- **When you accept rather than fix, say so where the status is read.** This backlog has no `accepted` status, so dispositioned entries carry `done` plus an explicit **"ACCEPTED, NOT FIXED"** note with its own reason and, where one exists, a re-open trigger. A reader who sees `done` and assumes "implemented" must be contradicted by the entry itself, not by a paragraph somewhere else.
- **A re-open trigger is a real artefact and belongs in the entry.** The sharpest from this phase: *re-open the moment `DegreeOfParallelism` is bound to an environment variable* — unreachable today, and the instant it is configurable a value ≤ 0 makes the host report healthy while dispatching nothing at all.

**The general form, which is the same guard-that-does-not-guard shape one level up:** a process that measures whether each finding is *correct* and never whether the set of findings is *affordable* will always terminate by exhaustion rather than by judgement.

### A disclosure whose root cause is `specs/shared/` becomes a numbered backlog entry, always

**Approval prose may never discharge such a gap by deferring to "the next feature that touches X."** That sentence has now failed twice across two assessments, on the same defect.

`openapi.yaml` promised that an operator's cancellation note reaches the timeline; `asyncapi.yaml`'s `OrderCancelledPayload` had no field to carry it. #7 disclosed the gap, shipped, and its reviewer wrote that the next feature to touch that payload must close it. #8's feature 41 *was* that feature — and disclosed it a second time, correctly, because `specs/shared/` is read-only without a human-gated amendment. Two runs, two honest disclosures, no fix, and #9 would have inherited a specification whose two halves contradict each other.

**The evidence that makes this a rule rather than a note is that the stated reason for deferring was not true when it was given.** #7's own commit closing that feature added **111 lines to `asyncapi.yaml`** — the whole `billing.credit.release` channel. The file was open. The three lines that would have closed the note gap were not among them, because that one merely failed an acceptance criterion while the other **blocked** the feature. And `asyncapi.yaml` was never touched again: **39 commits followed, including an entire audit phase.** *"The next feature that touches X"* named no one, so nobody was named.

So: **an acceptance criterion that cannot be met because of `specs/shared/` leaves the feature as an `SA-n` proposal, a backlog entry, or both — never as a sentence in a review.** The disclosure is still correct and still required; what it may not be is the end of the trail. Detection was never the failure here. **Routing was**, and a backlog entry is the only artefact in this harness that survives the feature that found it.

### Never hand the human an open question you could have closed

Before anything reaches the human gate, ask **"did #7 face this, and what did it do?"** #7's checkout is on disk; the answer is in its committed code or its `progress/history.md`, and fetching it is cheaper and far more reliable than a gate round-trip. Only what #7 **could not** face — because the engine or the language differs — is genuinely a decision.

This applies to the leader at least as much as to any subagent, and the leader is the one who keeps failing it. A subagent that applies the test and reports *"#7 deferred this, here is the citation"* has done its job; relaying that to the human as an open question undoes the work and wastes the gate. **Twice now the human has had to ask "is that something that was not already decided?"** — the second time about a finding the leader had personally verified two messages earlier.

**And the sharpest form: before proposing a spec amendment, check whether #7 solved it without one.** Feature 66 disclosed that an operator's cancellation note cannot cross the async saga boundary, and **both the implementer and the leader's own brief placed the root cause in `specs/shared/`** — the leader going as far as naming the two schemas an `SA-3` would extend. Neither had looked. `grep -rn "saga_commands" specs/shared/*.md` returns five hits, all prose about saga progression and DLQ policy, **none describing a column**: the table is implementation-owned. #7 carries the note there already, on both compensation branches, with no wire change at all.

An amendment is the most expensive routing available here — human-gated, applied to two repositories, committed on its own — so **proposing one on an unchecked premise costs more than any other kind of unchecked premise.** The check is the same `grep` this rule already asks for, run against the *specification* rather than against #7's behaviour: **does `specs/shared/` actually prescribe the thing you are about to amend it for?**

So: when a subagent raises an open point, resolve it before passing it on, and if it genuinely must go to the gate, **go with a recommendation and the evidence behind it** — never a menu. A gate exists for judgement the human alone can supply, not for questions the repository already answers.

### Anti-telephone-game rule

When you launch subagents, instruct them to **write their results to files** (`specs/<feature>/requirements.md`, `progress/impl_<feature>.md`) and return only a reference, never the content. You never relay a subagent's prose into chat.

---

## Architecture conventions

### Clean Architecture inside every service

```
Presentation/    Minimal API endpoints (Gateway), NATS responder BackgroundServices,
                 Kafka consumer BackgroundServices, DTOs, validation
Application/     Hand-rolled command/query/event handlers, the saga orchestrator,
                 port interfaces
Domain/          Aggregates, entities, value objects, domain events, state
                 machines, domain errors — ZERO framework references
Infrastructure/  EF Core repositories, MongoDB read repository, Kafka producer
                 + consumers, NATS client, outbox relay, credit simulator,
                 MailKit adapter (Mailpit locally), clock, OpenTelemetry
```

One `.csproj` per service, with these as **folders**, not four assemblies. Assembly-per-layer would let the compiler enforce the layering for free, at 24 projects instead of 6 and a slower build; NetArchTest enforces the same rule at namespace granularity, and the shape stays comparable to #7's for the benchmark.

Dependencies point **inwards**: presentation → application → domain. Infrastructure implements the ports the application declares.

### Non-negotiables

- **Domain purity.** No `Microsoft.EntityFrameworkCore`, `Confluent.Kafka`, `NATS.*`, `MongoDB.*`, `Microsoft.AspNetCore.*` or `System.Text.Json` reference inside any `Domain/` folder. Enforced by **NetArchTest**, which fails the build, not by convention. `decimal` is likewise banned from domain arithmetic — `Money` is `long` minor units, and `decimal` appears only at presentation boundaries.
- **The hand-rolled dispatcher is binding** (human gate ruling, Phase 8 — ratified across all six services, matching #7's own gate ruling at its feature 16)**.** Application layers use `ICommandHandler<T>` / `IQueryHandler<T,R>` / `IEventHandler<T>` resolved from the DI container in every service — no MediatR (v13 is commercially licensed). Registration is by assembly scan, and **startup validation fails fast if a command has no handler or more than one**. Durability never depends on the in-process bus: the `outbox` and `saga_commands` tables remain the guarantee, the in-process hop is only the fast path.

  **Why all six, when it does not fit all six equally.** In Orders, Fulfillment and Billing the fit is obvious. In the Gateway the "commands" are NATS RPC calls *outward*, so the dispatcher sits in front of an outward client; in Notifications and Projector — pure consumers with roughly one handler per fact type — it adds a hop that a direct call would not need. That indirection is accepted deliberately, for one reason: **#7 used `@nestjs/cqrs` in all six, and a #8 that used its dispatcher in three would stop the benchmark comparing like with like.** The per-feature effort numbers for Notifications and Projector would then reflect a different architecture rather than a different language, which is the one thing this repository exists to measure. Recorded as a parity trade-off in the README, not as a claim that the layer earns its keep everywhere.
- **Explicit DI registration, and a startup validation pass.** #7's equivalent rule existed because NestJS could infer a token from `emitDecoratorMetadata` and silently resolve to `undefined` under a compiler that did not emit it — a failure invisible until first use. .NET has no such inference, so the *rule* changes shape but the *defence* does not: every port is registered explicitly in `Program.cs`, and the startup validation pass is what turns "a handler is missing" from a runtime surprise into a boot failure. The lesson #7 paid for is that DI failures must be loud at boot; keep it that way.
- **One `BackgroundService` per transport.** #7's services were hybrid NestJS apps where a bare `@MessagePattern` registered on *every* connected transport and crashed the boot — a bug that needed its own ESLint rule. In .NET a NATS responder and a Kafka consumer are different classes subscribing to different things, so the ambiguity does not exist. Do not reintroduce it by multiplexing transports through one service class.
- **Database per service.** No cross-database joins, no foreign keys across service boundaries. Fulfillment and Billing reference `CompanyCode`, `RetailerCode`, `ProductCode`, `OrderReference` — business identifiers carried in messages, never FKs into the Orders database.
- **The only shared runtime code** is `src/SharedKernel` (zero `PackageReference`), `src/Contracts` (generated types) and `src/Cqrs` (the in-process dispatcher). Nothing else is shared.

  **`src/Cqrs` is a #8-only third project, added at the human gate in Phase 8, and it exists because of an earlier ruling rather than a new preference.** The dispatcher is binding across all six services; #7 got that capability from `@nestjs/cqrs`, a package, so it never needed a home for it. #8 hand-rolls it (MediatR v13 is commercially licensed), and it needs `Microsoft.Extensions.DependencyInjection.Abstractions` — which `SharedKernel` may not have, because an architecture test asserts `SharedKernel` carries **zero** package references and that rule is worth more than the convenience. `Contracts` is the wire contract, versioned by `asyncapi.yaml`; an in-process bus is not a wire concern. So the third project is the consequence of a decision already taken, not a widening of what may be shared.

  **It does not widen what the domain may reach for.** `src/Cqrs` is an **Application-layer** concern: handlers live in `Application/`, and no `Domain/` namespace may reference `OrderToCash.Cqrs`. An architecture test enforces that, because nothing else would.
- **The JSON wire shape must match #7 — envelope byte-exact, payload semantically equal.** `camelCase`, nulls omitted, no `$type` discriminator, no PascalCase envelope, set once in a shared `JsonSerializerOptions` in `Contracts` so no service can drift. This is what makes the n8n workflows and the API test script portable, and it is a parity claim the benchmark depends on.

  The rule is split deliberately, and the reason is evidence rather than preference. Twelve real #7 envelopes were captured from its retained Kafka topics in Phase 5 and are committed under `tests/Contracts.UnitTests/GoldenEnvelopes/`. They show the **envelope**'s seven fields in the order `asyncapi.yaml` declares them — `eventId`, `eventType`, `aggregateId`, `correlationId`, `causationId`, `occurredAt`, `payload` — which #8 matches exactly, and the golden files prove it.

  They also show the **payload**'s keys ordered by key length then alphabetically, which is **MySQL's `json` column normalisation**, not a serializer decision: #7's outbox relay reads the payload back out of that column and republishes it, so a storage artifact reached its wire. Verified on a single `eventId` present in both stores. #8 keeps payloads in `nvarchar(max)`, which preserves insertion order, so byte-equality of the payload would mean deliberately emulating another engine's storage quirk forever — and #9 on PostgreSQL could not do it either. JSON object key order carries no meaning and nothing downstream reads it: n8n parses by key, the projector reads fields, the API tests assert values. So the payload is asserted **semantically** — same keys, same values, same types, same casing — and key order is not a parity claim.

  This is not a spec amendment: `specs/shared/` is silent on key ordering (its "byte-for-byte" language concerns DLQ redrive, which is a different guarantee). It is a #8 convention, gated by the human, recorded here.
- **Kafka carries facts, NATS carries RPC.** Every inter-service interaction must be justifiable by one row of the decision matrix in `specs/shared/`. Never use Kafka as a request bus; never use RPC for facts.

## Coding conventions

| Topic | Rule |
|---|---|
| Language | C# 14 / `net10.0`, `Nullable` enabled, `ImplicitUsings` enabled, async all the way down |
| Money | **`long` minor units (cents) only**, in the domain **and in the column** (`bigint`). Never a float, never `decimal` in domain arithmetic. Use the `Money` value object. A narrowing cast on a money value is a defect, not something to make loud — `specs/shared/` requires "integer minor units" and never a width, so a storage type narrower than the domain type buys nothing and costs a boundary that can truncate |
| Identifiers | UUID primary keys, generated in the domain via `UniqueId` (`uniqueidentifier` in MS-SQL) |
| Database columns | `snake_case` in MS-SQL, `PascalCase` in C# |
| JSON wire | `camelCase`, nulls omitted — identical to #7's bytes |
| Dates | UTC everywhere, `datetime2(3)` columns, ISO-8601 strings on the wire |
| Business references | `ORD-000001`, `DES-000001`, `INV-000001`, `CR-000001` — sequential, human-readable, unique, allocated under a row lock |
| Event types | `<aggregate>.<fact>.v<n>` — e.g. `order.placed.v1` |
| Naming | Files match the type name (`Order.cs`); types `PascalCase`; private fields `_camelCase`; interfaces `IPascalCase` — enforced by `.editorconfig` |
| Value objects | `sealed record` / `readonly record struct` where equality-by-value is wanted; `Entity`/`AggregateRoot` are classes with identity equality |
| Errors | Domain errors extend `DomainError` and carry a stable `Code` |
| Logging | Structured with `correlationId` on every line |
| Async | CS1998, CS4014, CA2016 and CA2213 are **errors**, not suggestions — see `.editorconfig`. Forward every `CancellationToken` |
| Markdown | **No hard line-wraps in prose** — one line per paragraph/list item/quote. Code blocks and tables are exempt |

## Testing conventions

- **xUnit is the backend runner. Vitest is the web runner. No Jest, anywhere.**
- Domain unit tests are **pure** — no framework, no DB, no mocks of infrastructure.
- Integration tests use **Testcontainers for .NET** (real MsSql / Kafka / NATS / MongoDB), never mocked brokers.
- API tests are black-box through the Gateway (xUnit runner + `HttpClient` as the client only), and must prove **the same script #7's API tests prove**.
- Web: Vitest + React Testing Library for components, Playwright for end-to-end.
- **Architecture tests are tests.** NetArchTest runs in the normal `dotnet test` pass, so a layering violation fails like any other test.
- **Tests are written inside the feature loop, not at the end of the project.**
- **Arming protocol — how a guard is proven, and the one way it silently lies.** To arm a guard: introduce the violation, run the specific named test, confirm it FAILS and record the message verbatim, then restore. **After restoring, force the rebuild** (`touch` the restored file, or `dotnet build --no-incremental`) **before the confirming green run.** **Restore from a backup copy you took, never with `git checkout --`** — most files are untracked while a feature is in flight, and `git checkout` on an untracked path fails with `pathspec did not match any file(s) known to git`, restoring nothing and leaving the file **still armed** while its own error scrolls past. Confirm the restore by re-reading the changed line. **And do not offer `git diff` or `git diff --stat` on the mutated file as proof that the restore was clean** — the same untrackedness that makes `git checkout` fail makes `git diff` print nothing, so on the files this protocol usually touches that check **cannot fail**. It is the guard-that-does-not-guard appearing inside the restore step of the very protocol built to prevent it. Found in feature 21, where the restore was genuinely correct and the evidence offered for it was worthless. Use `cmp` against your backup, or read the line. A byte-for-byte `cmp` against your backup is a source-level check only: if the restore preserved the backup's timestamp, MSBuild's incremental check sees the source as older than its output, skips the compile, and the confirming run executes the **previously armed binary**. Found live in feature 7, where it produced a false red; the same mechanism produces a false green — a stale-but-correct binary vouching for source that is still armed. An arming table produced without a forced rebuild proves nothing about the code on disk.
- **A failure counts as evidence only if its message names the claim — so an assertion whose message cannot name the claim is not an acceptable failing assertion for an arm.** `Assert.False(string.IsNullOrEmpty(x))` prints `Expected: False / Actual: True` and nothing else, so the arm is evidence only to a reader who opens the stack line; `Assert.True(x != null)`, `Assert.True(collection.Any())` and a bare `Assert.True(flag)` are the same shape. Use a form that prints the offending value (`Assert.Equal`, `Assert.Matches`, `Assert.Contains` with the actual collection), or supply the user-message overload. Found as advisory A6 of feature 73's review, where the reviewer's own M7 probe and the implementer's arm 3 both ended in `Assert.False() Failure / Expected: False / Actual: True` and were distinguishable only by their stack line — and closed as backlog id 82, which replaced that exact assertion with `Assert.Matches("^[0-9a-f]{32}$", …)`, whose failure reads `Pattern not found in value / Regex: "^[0-9a-f]{32}$" / Value: null`.

  **And an arm that was seen to fail can stop killing without anyone touching it.** Id 82's bullet 3 required *re-running* the recorded arms rather than re-reading them, and doing so found `SagaConsumptionTests.SO9`'s `EnableAutoOffsetStore` mutation now **surviving**: a later feature's retry dispatcher began absorbing the handler exception inside `ConsumeAsync`, so the gate that the arm relied on is now satisfied by an in-process retry rather than by the Kafka redelivery the test's name claims (backlog id 94). The rule above — *a countable claim is not done until it has been seen to fail* — is a claim about a moment, and the ground moves underneath it. **When a feature changes an error path, the arms of tests that depend on that path are stale evidence until re-run**, and re-reading the record will confirm them forever.

- **Never run two builds against the same projects at once — and when a failure names a line the source cannot explain, clear `bin/` and `obj/` before believing it.** Found in phase 14. An arming rebuild ran against `src/Orders` while a `./quality.sh` build was in flight; a later verification run then crashed the test host outright with `BadImageFormatException: Index not found`, blaming `Order.cs:44` — **a plain auto-property, reached by an async stack trace**, which is incoherent because there is no async code there. Incoherent line mapping means the loaded IL does not match the source it claims to come from, and that metadata-token failure is the signature of a half-written assembly rather than of a defect.

  Clearing every `bin/` and `obj/`, rebuilding `--no-incremental`, and re-running the same project gave **102/102** — and the two runs then reconciled exactly, 1557 − 24 + 102 = 1635 = 1623 + 12. **The concurrency hazard is worse than unreliable arming evidence**, which is the reason usually given for serialising: it can produce a crash whose diagnosis points confidently at innocent code, and costs far more than the build it saved. The implementer that deferred two armings rather than take a reading through the race made the right call, and this is the evidence for it.

  **It happened twice more in the same feature, and those two occurrences show the real mechanism, which isn't the one this rule described.** Neither involved two agents building at once. Each time, **one agent started a long build or test run in the background and then kept working.** Group A1 ran `dotnet build` while its own `./quality.sh` was still inside `dotnet format`. Group A2 ran `dotnet build --no-incremental` while its own background `Orders.IntegrationTests` run was still executing, and then all 106 tests failed at once with `FileNotFoundException` loading `xunit.assert` — a half-overwritten `bin/`, not 106 regressions. The rule said *don't run two builds at once*, and each agent that broke it believed it was running only one, because the other was out of sight in the background.

  **The leader's own brief contributed to the third.** Two earlier passes had stalled by ending their turn to wait on a background process, so the next brief said *don't end your turn waiting, keep going*. Keeping going is exactly how a second build gets started while the first is still alive. Each instruction was reasonable alone, and together they produced the incident.

  So the actionable form: **while a build or test process you started is still alive, do only read-only work** — reading files, `grep`, writing the record — and nothing that runs `dotnet build`, `dotnet test` or `dotnet format`. Before starting any of those, `pgrep -fl "dotnet (build|test|format)"` must show nothing of yours; idle MSBuild reuse nodes (`MSBuild.dll /nodemode:1`) are not a build. **And do not rely on the foreground to prevent it: an agent's shell caps a foreground command at ten minutes, and a full `./quality.sh` takes about thirty, so it will background itself whatever the brief says.** That was the trap inside this very rule's first wording, which told agents to prefer the foreground. What matters is the conduct once a run is in the background: **stay in the turn, do only read-only work until its output shows completion, then continue.** A stalled turn costs a resume; a concurrent build costs a crash whose diagnosis blames innocent code.

  **And wait on a process ID, never on `pgrep -f <pattern>`.** Found in phase 14, where it explains at least one of this feature's stalled passes. An agent waited for its own backgrounded `./quality.sh` with `until ! pgrep -f "quality.sh"; do sleep 20; done`, and the loop never exited: `pgrep -f` matches against **full command lines**, and the waiting shell's own command line contains the literal text `quality.sh`. **The wait was waiting on itself.** So the agent ended its turn expecting a notification its loop could never deliver, and the run it had started was left orphaned for the coordinator to find. `while kill -0 <pid>; do sleep 20; done` cannot match itself and exits exactly when the process does. The general form is the guard-that-does-not-guard once more: **a check meant to prove nothing is running is only trustworthy if it cannot count itself.**

- **Deleting the emission is one mutation family, not the whole of arming. Corrupt the payload too.** The protocol above says *delete the behaviour and watch the test fail*, and a guard can pass that perfectly while never reading what the fact contains. Found in feature 17: a task said *"exactly one `stock.released.v1` carrying the request's `reason`"*, the test counted the row and never opened it, and corrupting that `reason` **and** another fact's `retailerCode` on the wire left the whole suite green — 79/79 and 48/48. The reviewer missed it in its own first pass for the same reason, and said so: all six of its probes attacked emission deletion.

  **And a corruption probe only bites on a field whose expected value the test supplied.** For fields the test does not control — ids, clocks, generated references — inject the source (a delegate, a fake clock) or bracket the value, or the field is unguarded however many probes you run. Found in feature 18: a test named for two ids being *the delegate's returned values* asserted only that they were non-default and distinct, which any two GUIDs satisfy; substituting the source left the suite green. `Assert.NotEqual` proves non-collision and can never prove provenance.

  **And the sharpest variant: when the test supplies the IDENTIFIER, it guards the mechanism and never the choice.** Found in phase 13. A config helper took the environment-variable **name** as a parameter; its tests passed a name in and asserted the value came back, which proves the reading works and can never prove the **caller picked the right key**. Repointing the Orders seed writer at `MSSQL_DB_BILLING` left `Seed.UnitTests` **41/41 green** while the seed job wrote Orders fixtures into the Billing database.

  **The discriminator for when substitution applies is a property of the literal, not of the code around it: does it name a member of a set whose other members also exist in this repository?** `MSSQL_DB_ORDERS` has three siblings, so swapping it is a genuine substitution; `"TrustServerCertificate=True;"` has none, so swapping it degenerates into ordinary corruption. That is mechanically enumerable — sibling families in this codebase include `MSSQL_DB_*`, `MONGO_DB_*`, the `otc-*` client and consumer-group ids, the `*.v1` event types, the NATS subjects and the Mongo collection names.

  **Substitution earns its own family because it is the only one whose green suite hides *correct behaviour aimed at the wrong target*.** Deletion leaves behaviour missing; corruption leaves data wrong; substitution leaves a working system pointed at another service's database. With six services each owning a database, a topic set and a subject set, that is the failure mode that crosses a service boundary — and both phase-13 instances were exactly that: a seed writer repointable at another service's database with the suite green, twice, by two different routes.

  **Its own false negative, which any instrument doing this must handle:** if the substituted sibling is unset, the read falls back to a default and the test fails for the *default* reason rather than the *name* reason. A swap that fails is not evidence until the failure message names what you intended to break.

  This is the provenance rule one level up: the earlier form says a corruption probe only bites on a field whose expected **value** the test supplied, and this says the same of a **key, subject, table, path or connection name**. The mutation family it needs is neither deletion nor corruption but **substitution of a valid alternative** — swap one real key for another real key and see whether anything notices. Wherever an identifier is a parameter rather than a constant, the call site is unguarded unless a test asserts the call site's own argument.

  So a fact-emitting branch needs both questions asked of it: **does the guard fail when the row is absent, and does it fail when a field is wrong?** They find different defects, and a suite that only ever answers the first will ship payload defects indefinitely — with a wire contract, a saga that branches on `reason`, and five services still to build, the second question is the more expensive one to leave unasked.

- **Run the defeat list against your own guard BEFORE submitting it. The reviewer is not the place to discover it.** Adopted in phase 14 for a throughput reason, not a quality one. Five of the phase's first seven closed features needed two or more review rounds, and two needed three or four — and **every rejection had one shape: the reviewer found an adversarial case the implementer had never attempted.** Not style notes; working exploits. Id 68 lost three rounds discovering, one per cycle, that its guard could be beaten by a comment, then by `#if false`, then by a raw string. Id 72 lost two rounds to instances sitting in its own enumeration's hit list. A review cycle costs a dispatch, a review and a verification pass; an attack costs minutes. **Discovering the attack list serially, at one attack per review round, is the single largest cost in this phase.**

  These are the shapes that have actually defeated a guard here, so they are the minimum list to run against your own work. The first three are the mutation families above; the rest were each paid for once:

  | # | Attack | Paid for by |
  |---|---|---|
  | 1 | Delete the behaviour | the original arming rule |
  | 2 | Corrupt a payload field the test supplied | feature 17 |
  | 3 | Substitute a valid sibling identifier (`MSSQL_DB_*`, a subject, a topic) | feature 18, phase 13, id 56's D1 |
  | 4 | **Shadow the pattern from a comment or string literal** — text that reads as code | id 68 round 1 |
  | 5 | **Hide the real thing in a dead region** — `#if false`, conditional compilation | id 68 round 2 |
  | 6 | **Hide it in a raw or verbatim string** the scanner misparses | id 68 round 2 |
  | 7 | **Drop an OPTIONAL element entirely** — absence, where the guard only ever compares presence | id 68 round 2 |
  | 8 | **Compare a literal to a literal** — a population "check" that never reads the tree | id 68 D2 |
  | 9 | **Satisfy the closer half of a two-part claim and leave the premise half stale** | id 72, four times |
  | 10 | **Let a build-output copy join the population** (`bin/`, `obj/`, `publish/`) | id 68 D9 |
  | 11 | **Write the thing in a form the instrument does not recognise** — a statement where it parses expressions (an early `return`, a `switch`, a `||` fallback), an indirection it does not follow (component state, a hook in another file, a neutral prop name), or a framework convention file (`error.tsx`). **When a syntax guard keeps losing to new forms of a behavioural claim, test the behaviour instead** | id 29, review rounds 1 and 2 |
  | 12 | **Serve the failure through a path the population never drives** — a second consumer of a shared hook, a read that only fires after a click, a request after the "settled" window, a status the probe never sends. Row 11's behavioural counterpart: an observational sweep sees only what it exercises | id 29, review round 3 |

  Not every attack applies to every guard — a guard that executes code cannot be beaten by a comment. **State which of the ten you ran, and for each one you skipped, why it does not apply.** That sentence is cheap to write and is the whole point: it converts "I did not think of it" into "I considered it and here is why it cannot bite", which is a claim a reviewer can check in seconds instead of a hole it must find in a round.

  **And the list is open.** When a review defeats a guard by a shape not listed here, add the row. That is how it stops costing a round the next time.

- **Changing a guard's INSTRUMENT swaps one set of premises for another, and the new set starts untested. Enumerate and arm the new premises in the same round.** Phase 14, id 68. A hand-rolled text scanner had been defeated three rounds running, so the instrument was changed to Roslyn — correctly: it closed the whole text-shadowing class structurally (comments, dead regions, raw strings, interpolation holes), verified by re-measurement. **And it immediately opened two holes nobody had written down.** The parser was constructed with no preprocessor symbols while the build defines `DEBUG`, so *the parser and the compiler disagreed about which region was live* — a real call in `#if DEBUG` with a decoy in `#else` left the suite green with a **required** argument unwired. And the argument finder walked the whole syntax tree rather than the host invocation, so passing the delegate to an unrelated local function satisfied it.

  Neither hole was a spelling; both were **assumptions the new instrument carries and the old one did not**. A scanner reading raw text has no opinion about preprocessor symbols; a parser does, and it is the wrong opinion unless you give it the build's. So when you replace an instrument — regex to parser, reflection to Cecil, Cecil to Roslyn, a stub to a real container — **write down what the new one assumes about the world, and arm each assumption**, before claiming the class is closed. The questions that found both holes in one round were: *does this instrument see what the compiler/runtime sees?* and *is it looking at the thing the claim is about, or merely somewhere the pattern also matches?*

  **The corollary, learned the expensive way: an instrument change is not a fix round, it is a new implementation.** It deserves the same premise enumeration a new guard gets, and budgeting it as "one more round" is how a feature reaches five.

- **Every branch that emits — or deliberately suppresses — a domain fact must be guarded by a test that fails when the emission is deleted.** Before submitting, the implementer arms that deletion itself and records in `progress/impl_<feature>.md` which named test failed and with what message. A fact-emitting branch whose emission survives its own deletion on a green suite is **not done** — with double force where the branch has no live caller yet, because integration harnesses cannot reach it. #7 learned this twice, on two different features, both correct code with no guard. Inheriting the lesson is free; rediscovering it is not.
- **A task that makes a countable claim must be armed, whether or not it carries the arming flag — and `tasks.md` must flag every such task.** Found twice, identically. The saga orchestrator's committed-offset task said *"read the group's committed offset from the broker; do not infer it from the redelivery alone"*; it was ticked, it inferred, and the offset contract shipped unguarded. Fulfillment's reservation tasks said *"exactly one `stock.reserved.v1`"* and *"exactly one … and one `stock.rejected.v1`"*; both ticked, and deleting the rejection fact's persistence left **both** suites fully green.

  Both features armed their **flagged** tasks perfectly — 11 of 11 and 12 of 12. The defect is not carelessness, it is that the arming discipline attaches to the flag rather than to the claim, so a task whose prose says *exactly one row* gets written, ticked and never mutated because nobody marked it. **A tick is not evidence the assertion exists.** If a task asserts a count, an identity, an ordering or an absence, it is a guard, and a guard is not done until it has been seen to fail.

- **A negative claim about the repository is a search result, not a reading.** *"No test does X"*, *"no instrument does Y"*, *"nothing else has this shape"* — a claim of absence is reportable only as **(a)** the exact command that enumerates the candidate set, **(b)** its complete output, and **(c)** one classification line per hit. Prose sweeps have been reported clear and disproved within minutes **three times** (feature 17, then feature 46 twice), each time by someone who ran a command instead of re-reading. A missed hit must be visible as an **unclassified line**, not invisible as a sentence.

  **A sweep must not filter by the property it is testing.** Three instances in phase 13 alone, and it is the sharpest form of the guard-that-does-not-guard because the filter looks like scoping rather than like an assumption. A route sweep asserting *"every endpoint except the public ones requires auth"* selected its candidate set **by the `IAllowAnonymous` metadata under test** — so marking `GET /orders` anonymous removed it from the sweep instead of failing it, and 141 tests stayed green. A disclosure of six unpaced retry loops enumerated only four, because two hits were excluded on a *readiness* ground while the claim being made was about *pacing*. And `grep -rn <pat> | grep -v '/bin/'` excludes by matching the output line's **content**, which includes the matched text, not only its path.

  **Its commonest disguise is filtering by filename when the claim is about content.** The guard-enumeration rule above — *enumerate #7's tests for the ported mechanism* — was applied twice before its own enumeration was caught doing exactly this: `find … | grep -iE "sse|stream"` over **filenames**, when the property being enumerated is which assertions *mention* the mechanism. A content-based command found a guard in a file whose name says nothing about streams, and the file-granular classification silently swallowed a second one inside a file that was listed. **Classify the unit the claim is about** — if the claim is about assertions, classify assertions, not the files containing them; a per-file line hides everything the file contains.

  The shape is always the same: **the predicate that decides membership is derived from the thing under test**, so a violation removes itself from the population rather than showing up in it. The fix is equally consistent — **make the expected set a literal and derive the rest by subtraction.** #7's version of that same route sweep hard-codes its public set and derives the protected set by subtraction, which is why #7's would have caught what #8's could not. When you write any sweep, ask what a violation would do to the candidate list: if the answer is *leave it*, the sweep cannot fail.

  **A list of places a correction must reach is the same prose sweep, wearing the clothes of a fix.** Found in feature 24, on a ledger row already corrected twice. Round 2 closed with *"the fix reached five places"*; round 3 found the disproved claim alive in three more, one of them the production source file the row exists to justify. What makes this its own trap rather than a repeat of the rule above is **which word everybody searched for**: the fix was about a *mechanism*, so implementer and reviewer both grepped the mechanism word — and the residue was carrying the **first** wrong version, whose wording shares no term with the correction. A grep for the new claim structurally cannot find text asserting the old one.

  So: **enumerate on the wording of the claim being retired, not the claim being written**, and where a thing has been wrong twice, enumerate for both. The command that found all seven hits was one `grep` for a five-word phrase from the original text, and it ran in under a second — against three rounds of prose sweeps that each missed them.

  **And the enumerating command must exclude by path, not by post-filtering its own output.** `grep -rn <pat> --include='*.cs' . | grep -v '/bin/\|/obj/'` reads as a path exclusion and is not one: `grep -rn` emits `path:lineno:content`, so the filter matches **content** too, and silently drops any hit whose matched line happens to mention a build directory. Found in feature 24, where that form returned **16** hits and the equivalent path-excluding form returned **19**, both perfectly stable across eight runs each — a discrepancy first misdiagnosed as a nondeterministic `grep`.

  The three suppressed lines are what make this worth a rule: **all three were quotations of the enumeration command itself**, dropped because the command contains `/bin/`. The lines most likely to quote the command are the records *of* the sweep, so this filter preferentially deletes the evidence that the sweep happened, from the artefact whose whole purpose is to prove it was complete — and a reviewer re-running the recorded command reproduces the same 16 and confirms nothing. Exclude at the source: `find . \( -name '*.cs' \) -not -path '*/bin/*' -print0 | xargs -0 grep -n <pat>`, or anchor the filter to the path as `init.sh` already does (`grep -vE '^\./(…|bin/|obj/)'` against a **file list**), which is why the harness has never carried this defect.

  The decisive evidence is that the third miss was already written down: the instance the sweep failed to mention was sitting in `progress/history.md`'s own Phase-9 note, committed eleven minutes before that feature started. **Recording something in prose does not stop a prose sweep from missing it** — only enumeration does. And the corollary that makes this cheap rather than bureaucratic: the enumerating command is usually one `grep`, and it is the same artefact whether the answer is "clear" or "three hits".

- **A retry budget counted in attempts assumes each attempt costs time.** Found in phase 13, while arming the fix for a real flake. A readiness loop retried 100 times with no delay, pacing itself on the request timeout — but the error it retries on, NATS's *no responders*, is returned by the server almost instantly instead of timing out, so the whole budget can expire in about a millisecond and report *not ready* while the subscription was 1 ms away. The same unpaced shape sits in four other fixtures, latent because their callers happen to warm up first (backlog id 63).

  Two things generalise. **Pace a retry loop explicitly**, rather than assuming the failure path is slow — the fast-failing error is the one that breaks the assumption, and it is invisible while every failure happens to be a timeout. And **prove the pacing with a change of kind, not of probability**: delay the dependency by a controlled interval and show the unpaced loop loses *every* time and the paced loop wins *every* time. "The flakes stopped" is not evidence, for the same reason a green run is not evidence about a red one.

- Coverage gates: **≥80% domain layer, ≥60% overall**, enforced by coverlet in `./quality.sh` regardless of SonarQube — and **verified to fail when breached**. #7 found its gate had been inert for twenty phases.
- Every EARS requirement `R<n>` maps to at least one named test in `specs/shared/test-matrix.md`. The ids are #7's: reusing one is a claim that the same requirement is satisfied here.

## Commit discipline

> **Claude never runs `git commit` or `git push`.** When a phase or feature is finished, stop and report (a) **what was done** and (b) **how to test it manually**. The human tests it, then commits. You may draft the message. The single exception: when the human says **"full wrap-up"**, that is the authorisation — then commit and push, update the plan document, refresh `README.md`, update `docs/PROCESS.md`, update the private stack-comparison document, and brief the next phase.

**Rule for the stack-comparison document:** only what a **committed file** proves gets marked confirmed. Anything learned from a probe, a spike or a deleted scratch directory goes in as pre-resolved, naming the phase that will promote it. A tick that stops anyone re-checking is the guard-that-does-not-guard pattern, which is the exact failure class this harness exists to catch.

**A claim of completeness is a count, and a count is a reading.** Neither *"all"*, *"every"*, *"both"*, *"the last"* nor *"complete"* belongs in a commit subject unless the thing counted was enumerated first — and a bare number belongs there only if it was read off a run in the same session. **This is now enforced by `scripts/git-hooks/commit-msg`**, installed by `init.sh` and checked by it on every run, because the coordinator wrote a false count into a subject **twice** and the rule that came out of the first occurrence did not prevent the second. Both were written at the same point in the workflow — a session-closing summary — about the same kind of quantity, with the true figure one command away. **A rule whose only enforcement is the author's memory fires exactly when attention is elsewhere.**

**And a number that does not reconcile is a finding, not a footnote.** The guard-hardening loop reported **1535** where the previous run was **1575**, saw the 40-test drop, and wrote that it was *"not a reconciliation against that baseline"* — noticing the anomaly and documenting the noticing instead of resolving it. The true figure was **1609**: one cell of the table held **31** for `Projector.UnitTests` where the project has **105**, because a *filtered* run over a single test class had been written into the project-total column. Two minutes of arithmetic would have found it, and the reconciliation is exact — +25 unit and +9 integration, the loop's own 34 new tests.

That it happened inside a loop *about claims that cannot fail* is the reason it earns a rule. **A count that moves the wrong way is evidence about something**, and the only honest responses are to explain it or to withdraw the number. Recording that it puzzled you is neither — it converts a detectable error into a disclosed one, which reads as diligence and preserves the falsehood. If a figure will not reconcile against the last run, that is the work, not a caveat on the work.

To satisfy the hook, put the enumeration in the body: the command and its output, or a `counted: …` line. **The hook checks the subject only** — the first of the two errors was a figure in the body, whose failure was provenance rather than presence, and no pattern can see that. Half the problem is mechanical now; the other half is still discipline, and a green hook does not mean the numbers in the message are true.

One commit per phase/feature, never batched. Message format:

```
feat(billing): BuyerCredit aggregate + credit hold/release ledger

What: <what was developed in this phase>

Packages installed:
- <NuGet or npm package>  — <one-line purpose>
```

Never install a package without it appearing in that phase's commit message. The git history is process evidence: for this repository it must show **harness first, spec copy second, code after**.

**A gate that genuinely happened can still be invisible to git, and the fix belongs at the commit boundary, not in the record.** CHECKPOINTS.md C6 requires the spec commit to *precede* the implementation commit in history — a check the final-checkpoint review (phase 25) found true for only 1 of 8 `sdd: true` features here, against #7's clean record on every one of its equivalents (`e18b467`, `e5641b3`, `ed5f343`, ...). The spec-then-code human gate genuinely ran every time (`progress/spec_*.md` × 6, cited in `progress/history.md`) — this project batched a feature's spec and implementation into the same commit far more often than #7 did, so the *ordering* the gate enforced left no trace in git even though the gate itself was real. Accepted with evidence here rather than rewritten after the fact (rewriting git history to manufacture an ordering that didn't literally happen would be worse than the gap it hides). **For #9: commit the spec on its own, before starting the implementer, every time — not because the gate needs it, but because C6's box needs to be checkable from git alone, without having to cite a side-channel record to prove a real thing happened.**

## Environment notes

- The .NET SDK is pinned in `global.json` (`10.0.111`, `rollForward: latestPatch`). A pin that cannot be satisfied makes `dotnet` fail outright rather than silently pick another SDK — `init.sh` surfaces this.
- Node is pinned in `.nvmrc` (`nvm use`), pnpm via corepack. **Both exist for `apps/web` only** — the backend has no Node dependency. `init.sh`'s backlog validator is also Node: a deliberate reuse of #7's proven script rather than a rewrite that would muddy the benchmark.
- Analyzer **severities** live in the root `.editorconfig`; analyzer **enforcement** (`TreatWarningsAsErrors`, `AnalysisLevel`) lives in `Directory.Build.props`. `dotnet format` reads `.editorconfig` from the repository root, so `quality.sh` can run it once at solution level.
- The `dotnet-ef` global tool must be in the same version band as the EF Core packages before migrations are generated (Phase 6 precondition).
- The git remote is account-explicit (`https://peelmicro@github.com/...`) because two GitHub accounts are authenticated on this machine. #7 discovered this via a 403 on its first push; here it was set up front, and the first push succeeded first time.
- The MS-SQL container wants ~1.5–2 GB RAM and takes ~20–30 s to accept connections. Budget for it in compose healthchecks and in integration-test timeouts.
