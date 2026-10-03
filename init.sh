#!/usr/bin/env bash
# init.sh — Environment and state coherence check.
#
# Run this at the START of every session, and again before declaring any
# feature `done`. If it fails, the session must not advance.
#
# Exit codes: 0 = healthy, 1 = at least one [FAIL].

set -u

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { printf "${GREEN}[OK]${NC}    %s\n" "$1"; }
warn() { printf "${YELLOW}[WARN]${NC}  %s\n" "$1"; }
fail() { printf "${RED}[FAIL]${NC}  %s\n" "$1"; EXIT_CODE=1; }
section() { printf "\n${BLUE}── %s ${NC}\n" "$1"; }

EXIT_CODE=0
cd "$(dirname "$0")" || exit 1

# ─────────────────────────────────────────────────────────────
section "1. Environment"

# Python is the backend toolchain, managed by uv. .python-version pins the
# interpreter; uv resolves it on every `uv run`, so the check below asks uv
# what it actually runs rather than reading the pin back to itself — a check
# that only re-reads the pin would pass with no interpreter installed at all.
if command -v uv >/dev/null 2>&1; then
  ok "uv $(uv --version | awk '{print $2}')"
  if [ -f .python-version ]; then
    PY_WANTED="$(tr -d ' \n\r' < .python-version)"
    if PY_ACTUAL="$(uv run --no-project python -c 'import platform; print(platform.python_version())' 2>/dev/null)"; then
      case "$PY_ACTUAL" in
        "$PY_WANTED"|"$PY_WANTED".*) ok "python $PY_ACTUAL satisfies .python-version ($PY_WANTED)" ;;
        *) fail "uv runs python $PY_ACTUAL but .python-version pins $PY_WANTED — run 'uv python install $PY_WANTED'" ;;
      esac
    else
      fail "uv cannot run the interpreter pinned in .python-version ($PY_WANTED) — run 'uv python install $PY_WANTED'"
    fi
  else
    fail ".python-version is missing — the interpreter is unpinned"
  fi
  if [ -f uv.lock ]; then
    if uv lock --check >/dev/null 2>&1; then ok "uv.lock is up to date with pyproject.toml"; else fail "uv.lock is stale against pyproject.toml — run 'uv lock' and review the diff"; fi
  else
    warn "no uv.lock yet (the workspace arrives in phase 5)"
  fi
else
  fail "uv is not installed"
fi

# Node and pnpm exist for apps/web only; the backend has no Node dependency.
# (The backlog validator below is also Node — #7's proven script, kept
# byte-identical through #8 and #9 rather than rewritten in Python: a rewrite
# would add effort to the benchmark while changing nothing.)
if command -v node >/dev/null 2>&1; then
  NODE_ACTUAL="$(node -v | sed 's/^v//')"
  if [ -f .nvmrc ]; then
    NODE_WANTED="$(tr -d ' \n\r' < .nvmrc)"
    if [ "$NODE_ACTUAL" = "$NODE_WANTED" ]; then
      ok "node $NODE_ACTUAL matches .nvmrc"
    else
      warn "node $NODE_ACTUAL does not match .nvmrc ($NODE_WANTED) — run 'nvm use'"
    fi
  else
    ok "node $NODE_ACTUAL (no .nvmrc)"
  fi
else
  fail "node is not installed"
fi

# The global pnpm may differ from the one apps/web pins in `packageManager`;
# pnpm switches to the pinned version itself, so only presence is checked here.
if command -v pnpm >/dev/null 2>&1; then ok "pnpm $(pnpm -v) (global; apps/web pins its own from phase 5)"; else fail "pnpm is not installed"; fi

if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then ok "docker daemon reachable"; else warn "docker installed but daemon not reachable"; fi
else
  warn "docker not installed (required from phase 4 onwards)"
fi

# ─────────────────────────────────────────────────────────────
section "2. Harness files"

for f in AGENTS.md CLAUDE.md CHECKPOINTS.md feature_list.json progress/current.md progress/history.md; do
  [ -f "$f" ] && ok "$f present" || fail "$f is missing"
done

AGENT_COUNT=$(find .claude/agents -maxdepth 1 -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
if [ "$AGENT_COUNT" -ge 7 ]; then ok ".claude/agents/ has $AGENT_COUNT agent definitions"; else fail ".claude/agents/ has only $AGENT_COUNT definitions (expected >= 7)"; fi

# Every agent must declare its model explicitly, or say it deliberately inherits.
for f in .claude/agents/*.md; do
  [ -e "$f" ] || continue
  if grep -q '^model:' "$f"; then
    ok "$(basename "$f") pins model: $(grep '^model:' "$f" | head -1 | cut -d' ' -f2)"
  elif grep -qi 'inherit' "$f"; then
    ok "$(basename "$f") deliberately unpinned (documented)"
  else
    fail "$(basename "$f") neither pins a model nor documents inheriting one"
  fi
done

# ─────────────────────────────────────────────────────────────
section "3. Backlog coherence"

if [ -f feature_list.json ] && command -v node >/dev/null 2>&1; then
  node - <<'NODE'
const fs = require('fs');
let d;
try { d = JSON.parse(fs.readFileSync('feature_list.json', 'utf8')); }
catch (e) { console.log(`\x1b[0;31m[FAIL]\x1b[0m  feature_list.json is not valid JSON: ${e.message}`); process.exit(1); }

const ok   = m => console.log(`\x1b[0;32m[OK]\x1b[0m    ${m}`);
const fail = m => { console.log(`\x1b[0;31m[FAIL]\x1b[0m  ${m}`); process.exitCode = 1; };
const warn = m => console.log(`\x1b[0;33m[WARN]\x1b[0m  ${m}`);

const valid = d.rules.valid_status;
ok(`feature_list.json parsed — ${d.features.length} features`);

const bad = d.features.filter(f => !valid.includes(f.status));
bad.length ? fail(`invalid status on: ${bad.map(f => `${f.name}=${f.status}`).join(', ')}`)
           : ok('every status is in the valid set');

const inProgress = d.features.filter(f => f.status === 'in_progress');
if (inProgress.length > 1) fail(`${inProgress.length} features in_progress (max 1): ${inProgress.map(f => f.name).join(', ')}`);
else if (inProgress.length === 1) ok(`1 feature in_progress: ${inProgress[0].name}`);
else ok('no feature in_progress');

const ids = d.features.map(f => f.id);
new Set(ids).size === ids.length ? ok('feature ids are unique') : fail('duplicate feature ids');

const blocked = d.features.filter(f => f.status === 'blocked');
if (blocked.length) warn(`${blocked.length} blocked: ${blocked.map(f => f.name).join(', ')}`);

// SDD coherence: a sdd:true feature past `pending` needs its triple-doc.
const needsSpec = d.features.filter(f => f.sdd && ['spec_ready','in_progress','in_review','done'].includes(f.status));
let missing = 0;
for (const f of needsSpec) {
  for (const doc of ['requirements.md','design.md','tasks.md']) {
    if (!fs.existsSync(`specs/${f.name}/${doc}`)) { fail(`specs/${f.name}/${doc} missing (feature is ${f.status})`); missing++; }
  }
}
if (!missing) ok(`SDD coherence: ${needsSpec.length} sdd feature(s) past pending have their triple-doc`);

const done = d.features.filter(f => f.status === 'done').length;
ok(`progress: ${done}/${d.features.length} features done`);
NODE
  [ $? -ne 0 ] && EXIT_CODE=1
else
  fail "cannot validate feature_list.json (missing file or node)"
fi

# ─────────────────────────────────────────────────────────────
section "4. Session file in lockstep"

# CHECKPOINTS.md C2's fourth box: progress/current.md describes the ACTIVE
# session, never leftovers. It has been re-opened and hand-closed every feature
# — three reviews in a row here, and three times in #7 before that. A checkpoint
# that is broken and repaired by hand every single feature is not a discipline,
# it is a chore with a good excuse; its persistence across six reviews is what
# makes it a check rather than a seventh advisory.
if [ -f progress/current.md ] && [ -f feature_list.json ] && command -v node >/dev/null 2>&1; then
  LOCKSTEP="$(node -e '
    const fs = require("fs");
    const d = JSON.parse(fs.readFileSync("feature_list.json", "utf8"));
    const cur = fs.readFileSync("progress/current.md", "utf8");
    const line = (cur.match(/^\*\*Feature:\*\*.*$/m) || [""])[0];
    // A feature is ACTIVE while it is in_progress OR in_review: during a
    // review pass current.md should still name it, not claim idleness. The
    // first version of this check omitted in_review and so failed on correct
    // state during every review — a guard firing on something that is not
    // wrong, which trains its reader to ignore it. Found by review D7.
    const active = d.features.filter(f => f.status === "in_progress" || f.status === "in_review");
    if (active.length >= 1) {
      const named = active.some(f => line.includes(f.name));
      process.stdout.write(named ? "" : `names none of the active feature(s) [${active.map(f => `${f.name}=${f.status}`).join(", ")}]: "${line.trim()}"`);
    } else {
      const idle = /none|idle|awaiting/i.test(line);
      process.stdout.write(idle ? "" : `claims a feature while none is active: "${line.trim()}"`);
    }
  ' 2>/dev/null)"
  if [ -z "$LOCKSTEP" ]; then ok "progress/current.md's **Feature:** line names the active feature (this check reads that line ONLY — a stale Goal/Decisions/Notes body below it is invisible here; feature 23's review found exactly that)"
  else fail "progress/current.md $LOCKSTEP"; fi
else
  warn "cannot check progress/current.md lockstep"
fi

# ─────────────────────────────────────────────────────────────
section "5. Superseded rules"

# An amendment is not finished when the canonical file is edited — only when
# nothing anywhere still asserts the old rule. Found the hard way in Phase 8:
# .claude/agents/reviewer.md kept a superseded non-negotiable and would have had
# the next reviewer reject correct code, from disk, exactly as instructed.
if [ -f .superseded-rules ]; then
  SUPERSEDED_HITS=0
  while IFS= read -r rule; do
    case "$rule" in ''|'#'*) continue ;; esac
    # Options BEFORE `--`: after it grep reads every argument as a path, so the
    # original `-- "$rule" --include=...` silently dropped every --include and
    # scanned all file types — including apps/web/node_modules (600+ MB), which
    # its `^\./node_modules/` post-filter never matched.
    #
    # Every TEXT file is scanned (-I skips binaries), not an extension list: the
    # first fix used one, and it went blind to extension-less tracked files such
    # as scripts/git-hooks/commit-msg — a narrowing found by review, not by the
    # author. Build output, dependencies, logs and history are excluded at the
    # source, never by post-filtering the output.
    HITS="$(grep -rlIF \
              --exclude-dir=node_modules --exclude-dir=.nitro --exclude-dir=.output \
              --exclude-dir=.angular --exclude-dir=dist --exclude-dir=.venv \
              --exclude-dir=__pycache__ --exclude-dir=.mypy_cache --exclude-dir=.ruff_cache \
              --exclude-dir=.pytest_cache --exclude-dir=htmlcov --exclude-dir=.git \
              --exclude-dir=logs --exclude-dir=progress \
              -- "$rule" . 2>/dev/null \
              | grep -vE '^\./\.superseded-rules$' || true)"
    if [ -n "$HITS" ]; then
      fail "superseded rule text still present: \"$(printf '%.60s' "$rule")...\""
      printf '%s\n' "$HITS" | sed 's/^/          /'
      SUPERSEDED_HITS=$((SUPERSEDED_HITS+1))
    fi
  done < .superseded-rules
  [ "$SUPERSEDED_HITS" -eq 0 ] && ok "no superseded rule text outside progress/"
else
  warn ".superseded-rules not present — amendments are unswept"
fi

# ─────────────────────────────────────────────────────────────
section "5b. Backlog tripwire"

# A feature id that VANISHES, or a `done` that reverts, is the one backlog
# corruption every other check is blind to: section 3 validates SHAPE, and a
# backlog with a feature missing is still perfectly shaped. Twice in Phase 8 an
# agent mangled feature_list.json with a whole-file rewrite and reverted with
# `git checkout --`, silently discarding uncommitted entries — once losing a
# backlog item added minutes earlier, which nothing caught. Prose did not stop
# the second occurrence, and the rule was in the offending agent's context both
# times, so this is the mechanical form.
#
# The snapshot is refreshed by THIS script on every clean run, so it needs no
# discipline to maintain. It is deliberately untracked: it is a within-session
# tripwire, not a shared artifact.
BACKLOG_SNAPSHOT=".backlog-snapshot"
CURRENT_BACKLOG="$(node -e '
  const d = require("./feature_list.json");
  console.log(d.features.map(f => f.id + ":" + f.status).sort((a,b) => Number(a.split(":")[0]) - Number(b.split(":")[0])).join("\n"));
' 2>/dev/null || true)"

if [ -z "$CURRENT_BACKLOG" ]; then
  warn "backlog tripwire skipped — feature_list.json could not be read"
elif [ -f "$BACKLOG_SNAPSHOT" ]; then
  TRIPWIRE_FAILED=0
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    OLD_ID="${line%%:*}"; OLD_STATUS="${line#*:}"
    NEW_LINE="$(printf '%s\n' "$CURRENT_BACKLOG" | grep -E "^${OLD_ID}:" || true)"
    if [ -z "$NEW_LINE" ]; then
      fail "backlog tripwire: feature id ${OLD_ID} has DISAPPEARED since the last clean init.sh run"
      TRIPWIRE_FAILED=1
    else
      NEW_STATUS="${NEW_LINE#*:}"
      if [ "$OLD_STATUS" = "done" ] && [ "$NEW_STATUS" != "done" ]; then
        fail "backlog tripwire: feature id ${OLD_ID} reverted from done to ${NEW_STATUS}"
        TRIPWIRE_FAILED=1
      fi
    fi
  done < "$BACKLOG_SNAPSHOT"
  if [ "$TRIPWIRE_FAILED" -eq 0 ]; then
    ok "backlog tripwire: no feature lost, no done reverted"
  else
    printf '          %s\n' "Recover from git or from the session record — do NOT run 'git checkout -- feature_list.json'."
  fi
else
  ok "backlog tripwire: no snapshot yet — baseline created by this run"
fi

# ─────────────────────────────────────────────────────────────
section "5c. Commit-message hook"

# Git hooks are NOT tracked, so a fresh clone — or a .git/hooks wiped by any
# tool — silently loses this one. The hook refuses a commit subject that makes
# an unverified quantity claim, after the coordinator wrote a false count into a
# subject twice. A guard that can vanish without anyone noticing is the shape
# this repository exists to catch, so its presence is checked here and it is
# reinstalled from the tracked copy when missing.
HOOK_SRC="scripts/git-hooks/commit-msg"
HOOK_DST=".git/hooks/commit-msg"
if [ ! -f "$HOOK_SRC" ]; then
  fail "scripts/git-hooks/commit-msg is missing — the tracked copy of the commit-message guard"
elif [ ! -x "$HOOK_DST" ] || ! cmp -s "$HOOK_SRC" "$HOOK_DST"; then
  cp "$HOOK_SRC" "$HOOK_DST" && chmod +x "$HOOK_DST"
  warn "commit-msg hook was missing or stale — reinstalled from $HOOK_SRC"
else
  ok "commit-msg hook installed and matches the tracked copy"
fi

# ─────────────────────────────────────────────────────────────
section "5d. Shared-spec parity with #8 and #7"

# THE CLAIM THIS WHOLE REPOSITORY RESTS ON. `specs/shared/` is copied from #8
# (whose copy is byte-identical to #7's through SA-1..SA-5), not written, and
# the benchmark is only honest if it STAYS copied: a silent edit here turns "we
# reused the spec" into "we forked it and did not notice". #8 added this check
# in its phase 13, after two amendments had been applied by hand with nothing
# to say whether they had been applied correctly.
#
# #9 checks against BOTH siblings: an SA-n must land in all three repositories
# in the same session, and a two-way check would pass while the third had
# drifted.
#
# And #9 refuses to pass on an empty population. #8's version counted the files
# it compared and reported OK either way, so before the spec is copied it would
# have said "byte-identical across 0 file(s)" — a green that means nothing, the
# exact shape #8 recorded as "a comparison guard is not proven until it has had
# two things to compare". Zero files is reported as what it is.
#
# test-matrix.md is EXEMPT by design: it carries each assessment's own
# per-requirement Status column, so it is the one file that MUST diverge.
SPEC_FILES="$(find specs/shared -maxdepth 1 -type f ! -name test-matrix.md 2>/dev/null | sort)"
if [ -z "$SPEC_FILES" ]; then
  warn "specs/shared/ holds no comparable files yet — shared-spec parity NOT checked (the spec is copied in phase 3)"
else
  for SIBLING in "${OTC_SIBLING_DOTNET:-../order-to-cash-dotnet}" "${OTC_SIBLING_NESTJS:-../order-to-cash-nestjs}"; do
    if [ ! -d "$SIBLING/specs/shared" ]; then
      warn "sibling checkout not found at $SIBLING — parity against it unchecked (set OTC_SIBLING_DOTNET / OTC_SIBLING_NESTJS)"
      continue
    fi
    PARITY_DIFF=0
    PARITY_SEEN=0
    for f in $SPEC_FILES; do
      b=$(basename "$f")
      PARITY_SEEN=$((PARITY_SEEN + 1))
      if [ ! -f "$SIBLING/specs/shared/$b" ]; then
        fail "specs/shared/$b has no counterpart in $SIBLING — the shared spec has forked"
        PARITY_DIFF=$((PARITY_DIFF + 1))
      elif ! cmp -s "$f" "$SIBLING/specs/shared/$b"; then
        fail "specs/shared/$b DIFFERS from $SIBLING — a spec amendment must be applied to all three repos in the same session, with an SA-n id"
        PARITY_DIFF=$((PARITY_DIFF + 1))
      fi
    done
    # The reverse direction: a file the sibling has and this repo lost.
    for g in "$SIBLING"/specs/shared/*; do
      b=$(basename "$g"); [ "$b" = "test-matrix.md" ] && continue
      if [ ! -f "specs/shared/$b" ]; then
        fail "specs/shared/$b exists in $SIBLING but not here"
        PARITY_DIFF=$((PARITY_DIFF + 1))
      fi
    done
    [ "$PARITY_DIFF" -eq 0 ] && ok "shared spec byte-identical to $SIBLING across $PARITY_SEEN file(s); test-matrix.md exempt (per-assessment Status column)"
  done
fi

# ─────────────────────────────────────────────────────────────
section "6. Repository state"

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  ok "git repo on branch '$(git rev-parse --abbrev-ref HEAD)'"
  DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
  [ "$DIRTY" -eq 0 ] && ok "working tree clean" || warn "$DIRTY uncommitted change(s) — expected mid-session"
  git config --local --get user.email >/dev/null 2>&1 \
    && ok "repo-local git identity: $(git config --local --get user.name) <$(git config --local --get user.email)>" \
    || warn "no repo-local git identity set"
else
  fail "not inside a git repository"
fi

# ─────────────────────────────────────────────────────────────
section "7. Tests"

if [ -f pyproject.toml ]; then
  warn "uv workspace present — run './quality.sh' before closing a feature (not run here to keep init.sh fast)"
else
  warn "no pyproject.toml yet (the uv workspace arrives in phase 5)"
fi

if [ -f apps/web/package.json ]; then
  warn "apps/web present — run 'pnpm -C apps/web test' before closing a web feature"
fi

# ─────────────────────────────────────────────────────────────
printf "\n"
if [ "$EXIT_CODE" -eq 0 ]; then
  # Refresh the tripwire baseline ONLY on a clean run, so a damaged backlog is
  # never blessed as the new normal by the very script that flagged it.
  [ -n "${CURRENT_BACKLOG:-}" ] && printf '%s\n' "$CURRENT_BACKLOG" > "${BACKLOG_SNAPSHOT:-.backlog-snapshot}"
  printf "${GREEN}══ init.sh: environment and state are coherent ══${NC}\n"
else
  printf "${RED}══ init.sh: FAILURES above — do not advance the session ══${NC}\n"
fi
exit $EXIT_CODE
