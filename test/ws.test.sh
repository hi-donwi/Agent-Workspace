#!/usr/bin/env bash
# Tests for the ws CLI. Zero dependencies: bash, git, and coreutils.
#
# ws writes hooks into client repositories, edits .git/info/exclude, and runs
# rm -rf over skill directories. A bug here damages real repos, so the invariants
# that protect them are the ones tested first. Everything runs in a temporary
# directory against a local fake skills source; nothing touches the network or
# the developer's own workspace.
#
#   ./test/ws.test.sh            run everything
#   ./test/ws.test.sh -v         show command output from failing checks

set -uo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERBOSE=0; [ "${1:-}" = "-v" ] && VERBOSE=1
PASS=0; FAIL=0; CURRENT=""

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
dim()  { printf '\033[2m%s\033[0m\n' "$*"; }

section() { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { PASS=$((PASS+1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"
         [ -n "${2:-}" ] && printf '       %s\n' "$2"; return 0; }

# check "description" <command...>   - passes when the command succeeds
check() { local d="$1"; shift
  local out; if out="$("$@" 2>&1)"; then ok "$d"; else
    bad "$d" "exit $?"; [ "$VERBOSE" = 1 ] && printf '%s\n' "$out" | sed 's/^/       | /'; fi; }

# check_fails "description" <command...>  - passes when the command FAILS
check_fails() { local d="$1"; shift
  local out; if out="$("$@" 2>&1)"; then
    bad "$d" "expected a non-zero exit, got 0"
    [ "$VERBOSE" = 1 ] && printf '%s\n' "$out" | sed 's/^/       | /'
  else ok "$d"; fi; }

exists()     { [ -e "$1" ] && ok "$2" || bad "$2" "missing: $1"; }
not_exists() { [ ! -e "$1" ] && ok "$2" || bad "$2" "should not exist: $1"; }
contains()   { grep -qF "$2" "$1" 2>/dev/null && ok "$3" || bad "$3" "'$2' not found in $1"; }
lacks()      { grep -qF "$2" "$1" 2>/dev/null && bad "$3" "'$2' unexpectedly in $1" || ok "$3"; }
equals()     { [ "$1" = "$2" ] && ok "$3" || bad "$3" "expected '$2', got '$1'"; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
# Isolate $HOME too: ws usage falls back to ~/.agent-ops when unconfigured, and
# a real one on the machine running this suite must never leak into a test.
export HOME="$TMP/home"; mkdir -p "$HOME"
export GIT_CONFIG_GLOBAL="$TMP/gitconfig" GIT_CONFIG_SYSTEM=/dev/null
git config --global user.email "test@example.com"
git config --global user.name  "Test Runner"
git config --global init.defaultBranch main
git config --global commit.gpgsign false
export WS_USER=tester WS_AGENT=testagent
# Runtime session ids from the host agent must not leak into the suite. Neither
# may the variables `agent_id` detects the tool by: with CLAUDECODE or
# CODEX_SANDBOX set, WS_AGENT is ignored and every clock file is named after the
# agent running the suite, so three cases here failed on a developer's machine
# and passed in CI — the worst way round for a regression test to behave.
HOST_ENV="WS_SESSION_ID GROK_SESSION_ID GROK_SESSION CLAUDE_SESSION_ID CODEX_THREAD_ID
          CURSOR_TRACE_ID CLAUDECODE CODEX_SANDBOX"
unset $HOST_ENV
export -n $HOST_ENV 2>/dev/null || true

# ── a workspace built from this repository's framework files ──────────────────
WS="$TMP/workspace"
mkdir -p "$WS"
cp -R "$SRC/.agents" "$WS/.agents"
rm -rf "$WS/.agents/skills" "$WS/.agents/.cache" "$WS/.agents/skills.lock"
for f in .gitignore .ignore .gitattributes AGENTS.md workspace.conf.example; do
  cp "$SRC/$f" "$WS/$f"
done
mkdir -p "$WS/projects"; cp "$SRC/projects/README.md" "$WS/projects/README.md"
mkdir -p "$WS/.claude"; cp "$SRC/.claude/settings.json.example" "$WS/.claude/"
ws() { (cd "${RUNDIR:-$WS}" && "$WS/.agents/bin/ws" "$@"); }

git -C "$WS" init -q
git -C "$WS" remote add origin "https://example.invalid/workspace.git"

# ── a local skills source, so sync needs no network ──────────────────────────
SKILLSRC="$TMP/skills-source"
mkdir -p "$SKILLSRC/skills/alpha" "$SKILLSRC/skills/beta" "$SKILLSRC/skills/gamma"
printf -- '---\nname: alpha\ndescription: Does alpha things. Use when testing alpha.\nmetadata:\n  pack: core\n  keywords: alpha, alpha-thing, testing\n---\n# alpha\n' \
  > "$SKILLSRC/skills/alpha/SKILL.md"
printf -- '---\nname: beta\npack: core\nkeywords: beta, beta-thing, testing\ndescription: Does beta things. Use when testing beta.\n---\n# beta\n' \
  > "$SKILLSRC/skills/beta/SKILL.md"
printf -- '---\nname: gamma\npack: extra\ndescription: Does gamma things. Use when testing gamma.\n---\n# gamma\n' \
  > "$SKILLSRC/skills/gamma/SKILL.md"
cat > "$SKILLSRC/index.json" <<'JSON'
{
  "generated": "2026-01-01T00:00:00Z",
  "skills": [
    {"name": "alpha", "pack": "core", "path": "skills/alpha/SKILL.md", "references": 0, "description": "Does alpha things."},
    {"name": "beta", "pack": "core", "path": "skills/beta/SKILL.md", "references": 0, "description": "Does beta things."},
    {"name": "gamma", "pack": "extra", "path": "skills/gamma/SKILL.md", "references": 0, "description": "Does gamma things."}
  ]
}
JSON
git -C "$SKILLSRC" init -q && git -C "$SKILLSRC" add -A && git -C "$SKILLSRC" commit -qm init

# ═════════════════════════════════════════════════════════════════════════════
section "init and identity"

check "ws init writes workspace.conf" ws init --key acme
exists "$WS/workspace.conf" "workspace.conf exists"
lacks "$WS/workspace.conf" "org_name" "workspace.conf does not record an organisation name"
check "ws init is idempotent and refuses to clobber" ws init
contains "$WS/workspace.conf" "org_key        = acme" "workspace.conf keeps only a technical workspace key"

section "ws where resolves structurally"
# The breadcrumb is a fallback, not the mechanism: a workspace is recognised by
# containing AGENTS.md and .agents/standards. Regression guard for ADR-0005.
equals "$(ws where)" "$WS" "from the root"
mkdir -p "$WS/deep/nested/dir"
equals "$(RUNDIR=$WS/deep/nested/dir ws where)" "$WS" "from a nested directory"

section "context repository"
check "ws context init scaffolds and inits git" ws context init
exists "$WS/context/.git" "context is its own git repository"
exists "$WS/context/registry.tsv" "it has a registry"
exists "$WS/context/memory/projects" "it has a memory tree"
exists "$WS/context/clients" "it has a clients tree"
exists "$WS/context/.gitattributes" "it ships the union-merge rules where they take effect"

# This fixture's clients and projects are named with words the framework itself
# uses as examples, so doctor's published-tree check would flag its own test data.
# A real operator declares the names of theirs that are already public the same
# way; the check is exercised properly in the last section.
# `locked`, `strict`, and `pub` are ordinary English words this fixture happens to
# register as a key, a profile, and a folder. A real workspace with a key like that
# declares it the same way — the check cannot tell a common word from a client.
printf 'acme\nbeta\nplatform\ndonwi\ntoys\notherp\nlocked\napi2\nstrict\npub\n' \
  > "$WS/context/public-identifiers"
contains "$WS/context/.gitattributes" "merge=union" "the merge strategy is actually declared"
check_fails "a second context init refuses" ws context init
git -C "$WS" add -A >/dev/null 2>&1
equals "$(git -C "$WS" ls-files context | wc -l | tr -d ' ')" "0" "context is never tracked by the framework"
check "ws web help is available" ws web --help
check "ws context sync is a no-op without a remote" ws context sync
check_fails "ws context switch without a remote url refuses" ws context switch
OUT="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$OUT" | grep -q "private-local" \
  && ok "doctor reports a context with no remote as private-local" \
  || bad "doctor reports a context with no remote as private-local" "$OUT"
printf '%s' "$OUT" | grep -q "primary clone" \
  && ok "doctor warns that the primary clone is a shared HEAD" \
  || bad "doctor warns that the primary clone is a shared HEAD" "$OUT"
WHERE_ERR="$(ws where 2>&1 >/dev/null)"
printf '%s' "$WHERE_ERR" | grep -q "primary clone" \
  && ok "ws where notes a primary clone on stderr" \
  || bad "ws where notes a primary clone on stderr" "$WHERE_ERR"

section "context sync, switch, and bootstrap --only"
git -C "$WS/context" add -A && git -C "$WS/context" commit -qm init-context
CTXBARE="$TMP/context-a.git"
git clone -q --bare "$WS/context" "$CTXBARE"
git -C "$WS/context" remote add origin "$CTXBARE"
git -C "$WS/context" push -q -u origin main
echo "local-note" >> "$WS/context/README.md"
check "ws context sync succeeds with dirty local files" ws context sync
contains "$WS/context/README.md" "local-note" "sync restored the stashed local edit"
CTXBARE2="$TMP/context-b.git"
git init -q --bare "$CTXBARE2"
check_fails "ws context switch refuses a different remote" ws context switch "$CTXBARE2"
contains "$WS/workspace.conf" "context_remote" "switch of same-or-missing remote is the only writer" || true
check "ws context switch is a no-op for the current origin" ws context switch "$CTXBARE"
contains "$WS/workspace.conf" "$CTXBARE" "context_remote is recorded"

DOC="$(ws doctor --ci 2>&1 || true)"
echo "extra" >> "$WS/context/README.md"
DOC="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$DOC" | grep -q "local changes while a remote" \
  && ok "doctor warns when shared context is dirty" \
  || bad "doctor warns when shared context is dirty" "$DOC"
# leave the extra line; later tests tolerate dirty context

section "clients: a client may span several projects"
contains "$WS/context/registry.tsv" "client" "the registry header has a client column"
check "ws client new registers a client" ws client new acme
exists "$WS/context/clients/acme/client.md" "client.md is scaffolded"
exists "$WS/context/clients/acme/decisions.md" "decisions.md is scaffolded"
check_fails "a second client with the same key refuses" ws client new acme
check_fails "ws new refuses an unknown client" ws new orphan projects/x --client no-such-client
not_exists "$WS/context/memory/projects/orphan" "nothing was registered for the rejected project"

# Every project must belong to a client - required at creation, not just warned
# about, and enforced again by doctor for any project registered another way.
check_fails "ws new refuses to register a project with no client at all" \
  ws new clientless projects/y
not_exists "$WS/context/memory/projects/clientless" "nothing was registered without a client either"
check "ws group new registers a product group inside a client" \
  ws group new platform --client acme
contains "$WS/context/groups.tsv" "$(printf 'platform\tacme\t')" "the group records its owning client"

section "skills: take only what the manifest asks for"
cat > "$WS/.agents/skills.manifest" <<EOF
source = $SKILLSRC
ref    = main

pack core
EOF
check "ws skills sync" ws skills sync
exists "$WS/.agents/skills/alpha/SKILL.md" "a skill in the requested pack arrives"
exists "$WS/.agents/skills/beta/SKILL.md"  "so does the other one"
not_exists "$WS/.agents/skills/gamma" "a skill outside the pack does NOT arrive"
contains "$WS/.agents/skills/index.json" '"name": "alpha", "pack": "core"' \
  "metadata.pack is indexed as the skill pack"
contains "$WS/.agents/skills/index.json" '"name": "beta", "pack": "core"' \
  "top-level pack still indexes as a fallback"
exists "$WS/.agents/skills.lock" "the resolved commit is locked"
contains "$WS/.agents/skills.lock" "commit = " "the lock names a commit"

check "ws skills add pulls one more" ws skills add gamma
exists "$WS/.agents/skills/gamma/SKILL.md" "the added skill arrives"
check "ws skills remove drops it again" ws skills remove gamma
not_exists "$WS/.agents/skills/gamma" "the removed skill is deleted from disk"
exists "$WS/.agents/skills/alpha/SKILL.md" "removing one leaves the others alone"


git -C "$WS" add -A >/dev/null 2>&1
equals "$(git -C "$WS" ls-files .agents/skills | wc -l | tr -d ' ')" "0" \
  "fetched skills are never tracked"

section "product repo isolation and the commit guard"
PROD="$WS/projects/acme/api"
mkdir -p "$PROD" && git -C "$PROD" init -q
echo 'class Order {}' > "$PROD/Order.java"
git -C "$PROD" add -A && git -C "$PROD" commit -qm init
check "ws new registers the project and builds its memory" \
  ws new api projects/acme/api --client acme --group platform
exists "$WS/context/memory/projects/api/log.md" "memory is created from templates"
contains "$WS/context/registry.tsv" "api" "the registry gains a row"
contains "$WS/context/registry.tsv" "$(printf 'api\tacme\t')" "the row records its client"
contains "$WS/context/registry.tsv" "$(printf 'api\tacme\tplatform\t')" "the row records its group"

OTHER="$TMP/other-src"
mkdir -p "$OTHER" && git -C "$OTHER" init -q
echo x > "$OTHER/x" && git -C "$OTHER" add x && git -C "$OTHER" commit -qm o
OTHERBARE="$TMP/other.git"
git clone -q --bare "$OTHER" "$OTHERBARE"
check "ws client new beta" ws client new beta
check "ws new registers beta with a remote" \
  ws new otherp projects/beta/app "$OTHERBARE" --client beta
rm -rf "$WS/projects/beta/app"
check "ws bootstrap --only acme does not clone beta" ws bootstrap --only acme
[ ! -e "$WS/projects/beta/app/.git" ] && ok "beta product stayed uncloned" \
  || bad "beta product stayed uncloned"
check "ws bootstrap --only beta clones that client" ws bootstrap --only beta
exists "$WS/projects/beta/app/.git" "beta product was cloned"

# A client's own skill is discoverable by ws route the same way a framework
# skill is - it is not tied to any one of that client's projects.
mkdir -p "$WS/context/clients/acme/skills/widgets"
cat > "$WS/context/clients/acme/skills/widgets/SKILL.md" <<'SKILLEOF'
---
name: widgets
pack: domain
keywords: widget, gizmo
description: Handles widget things. Use when testing widgets.
---
# widgets
SKILLEOF
ROUTE="$(ws route --project api "widget gizmo work" 2>&1)"
printf '%s' "$ROUTE" | grep -q widgets \
  && ok "ws route finds a client's own domain skill" \
  || bad "ws route finds a client's own domain skill" "$ROUTE"

check "ws link writes the pointer" ws link api
exists "$PROD/AGENTS.md"  "pointer AGENTS.md written"
exists "$PROD/.workspace" "breadcrumb written"
contains "$PROD/.git/info/exclude" "/AGENTS.md"   "AGENTS.md is excluded"
contains "$PROD/.git/info/exclude" "/.workspace"  "the breadcrumb is excluded too"
exists "$PROD/.git/hooks/pre-commit" "the guard hook is installed"
contains "$PROD/AGENTS.md" "live in the engineering workspace" "pointer uses generic workspace wording"
lacks "$PROD/AGENTS.md" "Acme Ltd" "pointer does not expose the organisation identity"
equals "$(git -C "$PROD" status --porcelain | wc -l | tr -d ' ')" "0" \
  "the pointers are invisible to git status"

section "portable product instructions stay versionable"
cp "$PROD/AGENTS.md" "$TMP/generated-pointer.md"
printf '# Product engineering rules\n' > "$PROD/AGENTS.md"
check "link preserves new product-owned instructions" ws link api
check_fails "product-owned AGENTS.md is not ignored" git -C "$PROD" check-ignore -q AGENTS.md
contains "$PROD/AGENTS.md" "Product engineering rules" "product instructions are preserved"
contains "$PROD/.workspace-instructions.md" "GENERATED BY: ws link" "workspace gets a separate pointer"
check "product instructions can be staged normally" git -C "$PROD" add AGENTS.md
check "guard allows product instructions" git -C "$PROD" commit -qm "docs: add product rules"
check "link also preserves tracked instructions" ws link api
check_fails "tracked product instructions have no obsolete exclusion" \
  git -C "$PROD" check-ignore --no-index -q AGENTS.md
# Restore the fixture expected by the generated-pointer tests below.
git -C "$PROD" rm -q AGENTS.md
git -C "$PROD" commit -qm "test: restore generated pointer fixture"
cp "$TMP/generated-pointer.md" "$PROD/AGENTS.md"
check "generated pointer remains excluded after relinking" ws link api
check "generated AGENTS.md is ignored" git -C "$PROD" check-ignore -q AGENTS.md

section "ws scan: operator-owned policy, never the product repo"
FAKEBIN="$TMP/bin"; mkdir -p "$FAKEBIN"
printf '#!/bin/sh\nprintf "%%s\\n" "$@" > "%s/scan.args"\necho pass\nexit 0\n' "$TMP" > "$FAKEBIN/agent-secure"
chmod +x "$FAKEBIN/agent-secure"
export PATH="$FAKEBIN:$PATH"
export WS_SECURE_BIN="$FAKEBIN/agent-secure"

check_fails "ws scan unknown key refuses" ws scan nosuch
check_fails "ws scan without a policy file refuses" ws scan api

mkdir -p "$WS/.local/secure/policies"
printf '{"version":1}\n' > "$WS/.local/secure/policies/default.json"
check "ws scan uses .local/secure/policies/default.json when profile is unset" ws scan api
contains "$TMP/scan.args" "default.json" "it selected default.json"
contains "$TMP/scan.args" "scan" "it invoked scan"

printf '{"version":1}\n' > "$PROD/sneaky-policy.json"
check_fails "ws scan refuses a policy that lives inside the product repo" \
  ws scan api --policy "$PROD/sneaky-policy.json"

OUTSIDE="$TMP/operator-policy.json"
printf '{"version":1}\n' > "$OUTSIDE"
check "ws scan --policy uses an explicit operator file" ws scan api --policy "$OUTSIDE"
contains "$TMP/scan.args" "operator-policy.json" "the explicit policy path was forwarded"

mkdir -p "$WS/projects/acme/strict" && git -C "$WS/projects/acme/strict" init -q
git -C "$WS/projects/acme/strict" commit --allow-empty -qm init
check "ws new --profile strict records the label" \
  ws new locked projects/acme/strict --client acme --profile strict
contains "$WS/context/registry.tsv" "$(printf '\tstrict\t')" "the registry stores security_profile"

printf '{"version":1}\n' > "$WS/.local/secure/policies/strict.json"
check "ws scan selects the profile-named policy" ws scan locked
contains "$TMP/scan.args" "strict.json" "strict profile mapped to strict.json"

check "ws scan --doctor calls doctor not scan" ws scan api --doctor
contains "$TMP/scan.args" "doctor" "doctor subcommand was used"
lacks "$TMP/scan.args" "scan" "scan was not the subcommand"

unset WS_SECURE_BIN
mv "$FAKEBIN/agent-secure" "$FAKEBIN/agent-secure.bak"
check_fails "ws scan fails when agent-secure is not installed" ws scan api
mv "$FAKEBIN/agent-secure.bak" "$FAKEBIN/agent-secure"
export WS_SECURE_BIN="$FAKEBIN/agent-secure"

section "ws verify: operator-owned execution contract"
mkdir -p "$WS/.local/agent/contracts"
cat > "$WS/.local/agent/contracts/api.json" <<'JSON'
{
  "schema_version": 1,
  "name": "synthetic verification",
  "commands": [
    {"id": "repository-readable", "command": "git status --porcelain", "timeout_seconds": 10},
    {"id": "optional-check", "command": "exit 9", "required": false, "timeout_seconds": 10}
  ]
}
JSON
check "ws verify passes required commands" ws verify api --json
OUT="$(ws verify api --json)"
printf '%s' "$OUT" | grep -q '"status": "pass"' \
  && ok "verification report has a pass status" \
  || bad "verification report has a pass status" "$OUT"
printf '%s' "$OUT" | grep -q 'repository-readable' \
  && ok "verification report names command ids" \
  || bad "verification report names command ids" "$OUT"
RUN_OUT="$(ws run api "synthetic verification evidence")"
RUN_ID="$(printf '%s\n' "$RUN_OUT" | grep '^context/runs/api/' | cut -d/ -f4)"
check "ws verify writes evidence into the private run" ws verify api --run "$RUN_ID"
exists "$WS/context/runs/api/$RUN_ID/evidence.json" "private evidence file exists"
contains "$WS/context/runs/api/$RUN_ID/evidence.json" '"status": "pass"' "evidence records the result"
cat > "$WS/.local/agent/contracts/failing.json" <<'JSON'
{
  "schema_version": 1,
  "name": "synthetic failing verification",
  "commands": [{"id": "expected-failure", "command": "exit 7"}]
}
JSON
check_fails "ws verify returns non-zero for required findings" \
  ws verify api --contract "$WS/.local/agent/contracts/failing.json"
printf '{"schema_version":1,"commands":[]}' > "$PROD/inside-contract.json"
check_fails "ws verify rejects a product-owned contract" \
  ws verify api --contract "$PROD/inside-contract.json"
rm -f "$PROD/inside-contract.json"

section "ws policy: risk-based autonomy"
mkdir -p "$WS/.local/agent/policies"
cat > "$WS/.local/agent/policies/api.json" <<'JSON'
{
  "schema_version": 1,
  "name": "synthetic autonomy policy",
  "default": "approval-required",
  "actions": {
    "inspect": "read",
    "edit": "change",
    "deploy": "approval-required"
  }
}
JSON
check "ws policy allows read actions" ws policy check api --action inspect --json
check "ws policy allows change actions" ws policy check api --action edit
check_fails "ws policy blocks approval-required actions" ws policy check api --action deploy
POLICY_OUT="$(ws policy check api --action deploy 2>&1 || true)"
printf '%s' "$POLICY_OUT" | grep -q '"decision": "approval-required"' \
  && ok "policy reports approval-required explicitly" \
  || bad "policy reports approval-required explicitly" "$POLICY_OUT"
check_fails "ws policy defaults unknown actions to approval" ws policy check api --action unknown
printf '{"schema_version":1,"default":"read","actions":{"deploy":"read"}}' > "$PROD/inside-policy.json"
check_fails "ws policy rejects a product-owned policy" \
  ws policy check api --action deploy --policy "$PROD/inside-policy.json"
rm -f "$PROD/inside-policy.json"

section "ws eval: synthetic scenario comparison"
cat > "$WS/.local/eval-scenarios.json" <<'JSON'
{
  "schema_version": 1,
  "name": "synthetic evaluation",
  "scenarios": [
    {
      "id": "routing",
      "request": "Explain the entry points of a small synthetic application.",
      "fixture": {"files": ["README.md", "src/main.py"]},
      "expected": {
        "skills": ["codebase-onboarding"],
        "actions": ["inspect"],
        "artifacts": ["onboarding-map"]
      }
    }
  ]
}
JSON
check "ws eval validates synthetic scenarios" ws eval validate "$WS/.local/eval-scenarios.json"
cat > "$WS/.local/eval-observed.json" <<'JSON'
{
  "routing": {
    "skills": ["codebase-onboarding"],
    "actions": ["inspect"],
    "artifacts": ["onboarding-map"]
  }
}
JSON
check "ws eval compares recorded outcomes" ws eval compare "$WS/.local/eval-scenarios.json" --observed "$WS/.local/eval-observed.json"
cat > "$WS/.local/eval-incomplete.json" <<'JSON'
{}
JSON
check_fails "ws eval reports missing observations" \
  ws eval compare "$WS/.local/eval-scenarios.json" --observed "$WS/.local/eval-incomplete.json"
cat > "$WS/.local/eval-findings.json" <<'JSON'
{"routing":{"skills":[],"actions":["inspect"],"artifacts":[]}}
JSON
check_fails "ws eval reports missing expected outcomes" \
  ws eval compare "$WS/.local/eval-scenarios.json" --observed "$WS/.local/eval-findings.json"
check_fails "ws eval rejects product-owned scenario input" \
  ws eval validate "$PROD/inside-scenarios.json"

section "ws compat: pinned release metadata"
cat > "$WS/.local/compatibility.json" <<'JSON'
{
  "schema_version": 1,
  "release_channel": "stable",
  "required_checks": ["tests", "security", "compatibility"],
  "components": [
    {
      "id": "synthetic-runtime",
      "source": "https://example.invalid/synthetic-runtime.git",
      "version": "v1.2.3",
      "commit": "0123456789abcdef0123456789abcdef01234567",
      "interface": "contract-v1"
    }
  ]
}
JSON
check "ws compat validates pinned metadata" ws compat validate "$WS/.local/compatibility.json"
cat > "$WS/.local/compat-observed.json" <<'JSON'
{
  "synthetic-runtime": {
    "version": "v1.2.3",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "interface": "contract-v1"
  }
}
JSON
check "ws compat compares matching observations" \
  ws compat compare "$WS/.local/compatibility.json" --observed "$WS/.local/compat-observed.json"
cat > "$WS/.local/compat-drift.json" <<'JSON'
{
  "synthetic-runtime": {
    "version": "v1.2.4",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "interface": "contract-v1"
  }
}
JSON
check_fails "ws compat reports version drift" \
  ws compat compare "$WS/.local/compatibility.json" --observed "$WS/.local/compat-drift.json"
cat > "$WS/.local/compat-floating.json" <<'JSON'
{
  "schema_version": 1,
  "components": [{"id":"floating","source":"https://example.invalid/repo.git","version":"main","commit":"short","interface":"v1"}]
}
JSON
check_fails "ws compat rejects floating or short pins" ws compat validate "$WS/.local/compat-floating.json"
check_fails "ws compat rejects product-owned manifests" \
  ws compat validate "$PROD/inside-compatibility.json"

# The hook is the second line of defence: exclude keeps them out of sight,
# the hook stops `git add -f`.
git -C "$PROD" add -f AGENTS.md .workspace >/dev/null 2>&1
check_fails "the hook refuses a commit containing the pointers" \
  git -C "$PROD" commit -m "should be refused"
git -C "$PROD" reset -q

equals "$(RUNDIR=$PROD ws where)" "$WS" "ws where works from inside a product repo"
git -C "$WS" add -A >/dev/null 2>&1
equals "$(git -C "$WS" ls-files projects | grep -cv '^projects/README.md$')" "0" \
  "no product file reaches the workspace index"

section "search sees product code, git does not"
# /projects/* hides product code from every gitignore-aware tool; .ignore puts it
# back for search only. Regression guard for ADR-0005.
check "git ignores the product repo" git -C "$WS" check-ignore -q projects/acme/api
if command -v rg >/dev/null 2>&1; then
  found="$(cd "$WS" && rg -l 'class Order' . </dev/null 2>/dev/null | wc -l | tr -d ' ')"
  [ "$found" -ge 1 ] && ok "ripgrep still finds product code from the root" \
                     || bad "ripgrep still finds product code from the root" "no match"
else
  dim "  skip ripgrep check (rg not installed)"
fi

section "two clocks"
check "human clock in"  ws clock in api "writing the thing"
check "agent clock in"  ws agent in api "generating the thing"
check_fails "a second human clock-in is refused" ws clock in api "again"
# Rewind both starts so the durations are non-zero and overlap.
for f in "$WS"/context/works/.open-*.json; do
  ts=$(sed -n 's/.*"start_ts":\([0-9]*\).*/\1/p' "$f")
  off=1800; grep -q '"kind":"human"' "$f" && off=3600
  sed -i.bak "s/\"start_ts\":$ts/\"start_ts\":$((ts-off))/" "$f" && rm -f "$f.bak"
done
check "agent clock out" ws agent out
check "human clock out" ws clock out
exists "$WS/context/works/human/api/$(date +%Y-%m).jsonl" "human session recorded"
exists "$WS/context/works/agent/api/$(date +%Y-%m).jsonl" "agent session recorded"
lacks "$WS/context/works/human/api/$(date +%Y-%m).jsonl" '"kind":"agent"' \
  "agent sessions never land in the human file"

HOURS="$(ws hours 2>&1)"
printf '%s' "$HOURS" | grep -q 'HUMAN' && printf '%s' "$HOURS" | grep -q 'AGENT' \
  && ok "ws hours reports two columns" || bad "ws hours reports two columns"
printf '%s' "$HOURS" | grep -qE '1\.00' && ok "human hour is counted" || bad "human hour is counted" "$HOURS"
printf '%s' "$HOURS" | grep -qE '0\.50' && ok "agent half-hour is counted separately" || bad "agent half-hour is counted separately"
printf '%s' "$HOURS" | grep -qiE '^\s*combined|total across' \
  && bad "no combined total is printed" || ok "no combined total is printed"
exists "$WS/context/works/rollup/$(date +%Y-%m).json" "clocking out writes the rollup"
contains "$WS/context/works/rollup/$(date +%Y-%m).json" '"human_hours"' "rollup keeps the two apart"

section "parallel agent sessions and worktrees"
WS_SESSION_ID=alpha check "two agents can clock in with distinct WS_SESSION_ID" \
  ws agent in api "alpha session"
WS_SESSION_ID=beta check "the second session is independent" \
  ws agent in api "beta session"
exists "$WS/context/works/.open-agent-tester-testagent-alpha.json" "alpha clock file"
exists "$WS/context/works/.open-agent-tester-testagent-beta.json" "beta clock file"
WS_SESSION_ID=alpha check "alpha clocks out without closing beta" ws agent out
exists "$WS/context/works/.open-agent-tester-testagent-beta.json" "beta still open"
WS_SESSION_ID=beta check "beta clocks out" ws agent out

DOC="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$DOC" | grep -q "session id is 'default'" \
  && bad "doctor does not warn about default when no default clock is open" \
  || ok "doctor does not warn about default when no default clock is open"

check "default session clock-in still works" ws agent in api "legacy default"
DOC="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$DOC" | grep -q "session id is 'default'" \
  && ok "doctor warns when the agent session id is default" \
  || bad "doctor warns when the agent session id is default" "$DOC"
check "default session clock-out" ws agent out

WS_SESSION_ID=wt1 check "ws agent start creates a worktree" ws agent start api "isolated"
[ -e "$WS/.local/worktrees/api/wt1/.git" ] && ok "worktree path exists" || bad "worktree path exists" "missing .local/worktrees/api/wt1"
gdir="$(git -C "$PROD" rev-parse --path-format=absolute --git-common-dir)"
exists "$gdir/ws-agent-sessions/wt1.lock" "session lock is recorded"
START_OUT="$(WS_SESSION_ID=wt1 ws agent start api "reuse" 2>&1)"
printf '%s' "$START_OUT" | grep -q "reusing worktree" \
  && ok "ws agent start reuses an existing worktree" \
  || bad "ws agent start reuses an existing worktree" "$START_OUT"
WS_SESSION_ID=wt1 check "ws agent stop drops the lock and clocks out" ws agent stop
not_exists "$gdir/ws-agent-sessions/wt1.lock" "session lock is removed"
[ -e "$WS/.local/worktrees/api/wt1" ] && ok "worktree is kept after stop" \
  || bad "worktree is kept after stop"

section "session bind (attention isolation)"
# Git worktrees isolate HEAD. Session bind isolates what the agent is allowed
# to load: one project pack per WS_SESSION_ID, never a sibling client.
printf '\nSIBLING_SESSION_CANARY\n' >> "$WS/context/memory/projects/otherp/project.md"
check_fails "ws session bind unknown project refuses" ws session bind nosuch
check_fails "ws session bind --run unknown refuses" \
  env WS_SESSION_ID=attn ws session bind api --run nosuch-run

BIND_OUT="$(WS_SESSION_ID=attn ws session bind api 2>&1)"
printf '%s' "$BIND_OUT" | grep -q 'WS_PROJECT_KEY=api' \
  && ok "bind prints WS_PROJECT_KEY" || bad "bind prints WS_PROJECT_KEY" "$BIND_OUT"
printf '%s' "$BIND_OUT" | grep -q 'WS_CLIENT_KEY=acme' \
  && ok "bind prints WS_CLIENT_KEY" || bad "bind prints WS_CLIENT_KEY" "$BIND_OUT"
exists "$WS/.local/sessions/attn/bind" "bind file is per session id"
exists "$WS/.local/sessions/attn/pack.json" "pack.json is written"
exists "$WS/.local/sessions/attn/CONTEXT.md" "CONTEXT.md is written"
contains "$WS/.local/sessions/attn/bind" "project=api" "bind records the project"
contains "$WS/.local/sessions/attn/bind" "client=acme" "bind records the client"
contains "$WS/.local/sessions/attn/pack.json" '"project": "api"' "pack is for api"
lacks "$WS/.local/sessions/attn/pack.json" "SIBLING_SESSION_CANARY" \
  "api pack does not include the sibling project's memory"
lacks "$WS/.local/sessions/attn/CONTEXT.md" "SIBLING_SESSION_CANARY" \
  "CONTEXT.md does not include the sibling canary"
contains "$WS/.local/sessions/attn/CONTEXT.md" "Client: \`acme\`" "CONTEXT.md names the client"

WS_SESSION_ID=otherbind check "a second session binds independently" ws session bind otherp
contains "$WS/.local/sessions/otherbind/bind" "project=otherp" "otherbind is otherp"
contains "$WS/.local/sessions/attn/bind" "project=api" "attn bind is unchanged"
contains "$WS/.local/sessions/otherbind/pack.json" "SIBLING_SESSION_CANARY" \
  "otherp pack includes its own memory"

# Every agent that exports no session id shares one directory, so a bind there
# redirects whatever other agent is using it — without telling either of them.
# This is ADR-0011 isolation defeated by two processes and no env var.
# The suite unsets every session variable, so a bare `ws` is the default session.
check "the default session can take a first bind" ws session bind api
contains "$WS/.local/sessions/default/bind" "project=api" "default bound to api"
check "rebinding the default session to the SAME project is a refresh" \
  ws session bind api
check_fails "rebinding the default session to a DIFFERENT project is refused" \
  ws session bind otherp
contains "$WS/.local/sessions/default/bind" "project=api" \
  "the refused rebind left the other agent's bind alone"
REFUSE="$(ws session bind otherp 2>&1 || true)"
printf '%s' "$REFUSE" | grep -q 'WS_SESSION_ID' \
  && ok "the refusal names the real fix" \
  || bad "the refusal names the real fix" "$REFUSE"
check "--force takes the default session over deliberately" \
  ws session bind otherp --force
contains "$WS/.local/sessions/default/bind" "project=otherp" "--force rebound it"
# A named session was never the problem and must not acquire the restriction.
WS_SESSION_ID=attn check "a named session still rebinds freely" ws session bind otherp
WS_SESSION_ID=attn check "and back again" ws session bind api
# Leave the shared session unbound: the hook section below asserts what happens
# when there is no bind to resolve, and a leftover one silently answers for it.
check "the default session clears" ws session clear
not_exists "$WS/.local/sessions/default/bind" "default session left unbound"

STATUS="$(WS_SESSION_ID=attn ws session status 2>&1)"
printf '%s' "$STATUS" | grep -q 'project=api' \
  && ok "session status shows the bound project" \
  || bad "session status shows the bound project" "$STATUS"

WS_SESSION_ID=attn check "ws run before bind --run" ws run api "pack this run"
RUN_ID="$(ls "$WS/context/runs/api" | head -1)"
[ -n "$RUN_ID" ] && ok "run id captured for bind --run" || bad "run id captured for bind --run"
WS_SESSION_ID=attn check "bind accepts --run" ws session bind api --run "$RUN_ID"
contains "$WS/.local/sessions/attn/bind" "run=$RUN_ID" "bind records the run"
contains "$WS/.local/sessions/attn/pack.json" "runs/api/$RUN_ID/brief.md" \
  "pack includes the run brief"

WS_SESSION_ID=attn check "ws session clear drops the bind" ws session clear
not_exists "$WS/.local/sessions/attn/bind" "bind file is removed"
exists "$WS/.local/sessions/otherbind/bind" "clear does not touch another session"

UNBOUND="$(WS_SESSION_ID=attn-unbound ws doctor --ci 2>&1 || true)"
printf '%s' "$UNBOUND" | grep -q "session is not bound to a project" \
  && ok "doctor warns when a named session has no bind" \
  || bad "doctor warns when a named session has no bind" "$UNBOUND"

WS_SESSION_ID=attn check "re-bind after clear" ws session bind api
BOUND="$(WS_SESSION_ID=attn ws doctor --ci 2>&1 || true)"
printf '%s' "$BOUND" | grep -q "session bound to api" \
  && ok "doctor reports the bound project" \
  || bad "doctor reports the bound project" "$BOUND"

WS_SESSION_ID=wtbind check "ws agent start also binds the session" ws agent start api "bind-on-start"
exists "$WS/.local/sessions/wtbind/bind" "agent start wrote a bind"
contains "$WS/.local/sessions/wtbind/bind" "project=api" "agent start bound api"
WS_SESSION_ID=wtbind check "ws agent stop leaves the bind in place" ws agent stop
exists "$WS/.local/sessions/wtbind/bind" "bind survives agent stop"

section "overlap is merged, not summed"
# Two agent sessions covering the same hour are one hour of elapsed work.
M="$(date +%Y-%m)"; F="$WS/context/works/agent/overlap/$M.jsonl"; mkdir -p "${F%/*}"
BASE=$(( $(date +%s) - 86400 )); DAY=$(date -u -r $BASE +%Y-%m-%d 2>/dev/null || date -u -d @$BASE +%Y-%m-%d)
for pair in "0 3600" "1800 5400"; do
  set -- $pair
  printf '{"kind":"agent","project":"overlap","actor":"t","tool":"t","start":"%sT00:00:00+00:00","end":"x","start_ts":%s,"end_ts":%s,"minutes":60,"note":"overlap"}\n' \
    "$DAY" "$((BASE+$1))" "$((BASE+$2))" >> "$F"
done
OUT="$(ws hours --project overlap 2>&1)"
printf '%s' "$OUT" | grep -q "$DAY" && \
  { printf '%s' "$OUT" | grep "$DAY" | grep -qE '1\.50' \
      && ok "two overlapping 1h sessions count as 1.5h, not 2h" \
      || bad "two overlapping 1h sessions count as 1.5h, not 2h" "$(printf '%s' "$OUT" | grep "$DAY")"; } \
  || bad "the overlapping day appears in the report"

section "a project whose context is a repository of its own"
# When a project's memory lives in its own repo, the root context holds routing stubs.
# Packing only those hands the agent pointers plus an allowlist forbidding it to follow
# them, which is the arrangement this column exists to make workable.
PCTX="$WS/projects/acme/api-context"
mkdir -p "$PCTX/runs/2026-09-22-own-run" "$PCTX/client"
printf '# api — project\nPROJECT_CONTEXT_CANARY\n'      > "$PCTX/project.md"
printf '# api — active\nOWN_REPO_ACTIVE\n'              > "$PCTX/active.md"
printf '# api — decisions\n'                            > "$PCTX/decisions.md"
printf '# api — log\n'                                  > "$PCTX/log.md"
printf '# client\nOWN_REPO_CLIENT\n'                    > "$PCTX/client/client.md"
printf '# brief\nOWN_RUN_BRIEF\n'                       > "$PCTX/runs/2026-09-22-own-run/brief.md"
printf '# handoff\n'                                    > "$PCTX/runs/2026-09-22-own-run/handoff.md"

# reg_rows normalises a v2 file to nine columns, so the column is readable before the
# file is migrated. Migrating is what makes it editable.
check "ws context migrate-v3 adds the column" ws context migrate-v3
contains "$WS/context/registry.tsv" "context_repo" "the header carries context_repo"
exists "$WS/context/registry.tsv.bak-v2" "the v2 file is kept"
check_fails "a second migrate-v3 refuses" ws context migrate-v3
ROWS_AFTER="$(tail -n +2 "$WS/context/registry.tsv" | grep -cv '^[[:space:]]*$')"
[ "$ROWS_AFTER" -ge 2 ] && ok "migration preserved the rows" \
  || bad "migration preserved the rows" "got $ROWS_AFTER"

python3 - "$WS/context/registry.tsv" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); out = []
for line in p.read_text().split("\n"):
    c = line.split("\t")
    if c[0] == "api" and len(c) == 9:
        c[8] = "projects/acme/api-context"
        line = "\t".join(c)
    out.append(line)
p.write_text("\n".join(out))
PYEOF

WS_SESSION_ID=owncx check "bind packs a project with its own context repo" ws session bind api
contains "$WS/.local/sessions/owncx/pack.json" "OWN_REPO_ACTIVE" \
  "the pack reaches the project's own repo, not only the root stub"
contains "$WS/.local/sessions/owncx/pack.json" "OWN_REPO_CLIENT" \
  "client material inside the project repo is packed too"
contains "$WS/.local/sessions/owncx/CONTEXT.md" "projects/acme/api-context/active.md" \
  "CONTEXT.md lists the external path so the allowlist permits it"
contains "$WS/.local/sessions/owncx/pack.json" '"context_repo": "projects/acme/api-context"' \
  "the pack records where the context came from"

WS_SESSION_ID=owncx check "a run inside the project's own repo resolves" \
  ws session bind api --run 2026-09-22-own-run
contains "$WS/.local/sessions/owncx/pack.json" "OWN_RUN_BRIEF" "the external run is packed"
WS_SESSION_ID=owncx check_fails "a run in neither tree is still refused" \
  ws session bind api --run nosuch-run

# A project without the column must behave exactly as before.
WS_SESSION_ID=nocx check "a project with no context repo packs unchanged" ws session bind otherp
lacks "$WS/.local/sessions/nocx/pack.json" "OWN_REPO_ACTIVE" \
  "the other project's pack did not pick up the api context repo"
contains "$WS/.local/sessions/nocx/pack.json" '"context_repo": null' \
  "no context repo is recorded as null"

# ws link must name the same repo the pack does. Pointing a reader at the stubs is
# how a second, hand-written pointer gets added next to the generated one — which is
# exactly what happened in this workspace before the column existed.
check "ws link names the project's own context repo" ws link api
# Assert against the file ws link actually wrote, not a guess: which of the two it is
# depends on whether the product tracks its own AGENTS.md at this point in the suite.
LINKPTR="$PROD/AGENTS.md"; [ -f "$PROD/.workspace-instructions.md" ] && LINKPTR="$PROD/.workspace-instructions.md"
not_exists "$PROD/$( [ "$LINKPTR" = "$PROD/AGENTS.md" ] && echo .workspace-instructions.md || echo AGENTS.md )" \
  "only one generated pointer is left on disk"
contains "$LINKPTR" "projects/acme/api-context/" "the pointer names the external context repo"
contains "$LINKPTR" "repository of its own" "the pointer says why the root holds stubs"
contains "$PROD/.workspace" "context_repo=projects/acme/api-context" \
  "the breadcrumb records it for tools without ws on PATH"

# The cleanup above deletes a file inside a CLIENT repository. The only thing standing
# between it and a client's own AGENTS.md is owned_pointer, so that guard gets its own
# check rather than being trusted.
printf '# Product engineering rules\nCLIENT_OWNED_CANARY\n' > "$PROD/AGENTS.md"
check "ws link with a product-owned AGENTS.md" ws link api
exists "$PROD/AGENTS.md" "a client-owned AGENTS.md is never removed by the cleanup"
contains "$PROD/AGENTS.md" "CLIENT_OWNED_CANARY" "and its contents are untouched"
exists "$PROD/.workspace-instructions.md" "the generated pointer moved aside instead"
rm -f "$PROD/AGENTS.md"
check "ws link again once the product file is gone" ws link api
not_exists "$PROD/.workspace-instructions.md" "the superseded generated pointer is cleaned up"
exists "$PROD/AGENTS.md" "and the generated pointer moved back"

# A column naming a directory that is not on disk must degrade, not mislead: a pointer
# to a repo nobody has cloned is worse than a pointer to the stub that explains it.
mv "$PCTX" "$TMP/api-context-parked"
LINKOUT="$(ws link api 2>&1)"
printf '%s' "$LINKOUT" | grep -q 'not on disk' \
  && ok "link warns when context_repo is not cloned" \
  || bad "link warns when context_repo is not cloned" "$LINKOUT"
contains "$LINKPTR" "context/memory/projects/api/" "it falls back to the root context"
mv "$TMP/api-context-parked" "$PCTX"
check "link recovers once the context repo is back" ws link api

# The column names a path inside the workspace; anything else escapes the boundary.
python3 - "$WS/context/registry.tsv" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); out = []
for line in p.read_text().split("\n"):
    c = line.split("\t")
    if c[0] == "api" and len(c) == 9:
        c[8] = "../../etc"
        line = "\t".join(c)
    out.append(line)
p.write_text("\n".join(out))
PYEOF
WS_SESSION_ID=owncx check_fails "a context_repo escaping the workspace is refused" \
  ws session bind api
# Put it back: later sections bind `api` and a poisoned column would fail them for a
# reason that has nothing to do with what they test.
python3 - "$WS/context/registry.tsv" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); out = []
for line in p.read_text().split("\n"):
    c = line.split("\t")
    if c[0] == "api" and len(c) == 9:
        c[8] = "-"
        line = "\t".join(c)
    out.append(line)
p.write_text("\n".join(out))
PYEOF
WS_SESSION_ID=owncx check "binding works again once the column is cleared" ws session bind api

section "abandoned clocks"
# A session killed by a quota limit, a crash, or a closed terminal never clocks
# out. Closing that clock with `now` would bill every hour since - and because
# hours merges overlaps within a column, one such interval swallows every real
# session that month. So recovery is evidence-bound, and says that it is.
OPEN="$WS/context/works/.open-agent-tester-testagent-default.json"

# Backdate an open clock by N seconds. The mtime moves with the start unless a
# second argument says otherwise, because sed rewrites the file and would
# otherwise leave a fresh mtime - i.e. evidence of activity that never happened.
backdate_open() {
  local f="$1" back="$2" beat="${3:-start}"
  local ts; ts=$(sed -n 's/.*"start_ts":\([0-9]*\).*/\1/p' "$f")
  sed -i.bak "s/\"start_ts\":$ts/\"start_ts\":$((ts-back))/" "$f" && rm -f "$f.bak"
  [ "$beat" = start ] && python3 -c "import os,sys; t=int(sys.argv[2]); os.utime(sys.argv[1],(t,t))" \
    "$f" "$((ts-back))"
  return 0
}

check "agent clock in for the abandon case" ws agent in api "will be abandoned"
exists "$OPEN" "the open clock file exists"
# Backdate the start well past the 8h cap, with no later evidence of activity.
backdate_open "$OPEN" 500000

OUT="$(ws doctor 2>&1)"
printf '%s' "$OUT" | grep -q 'abandoned clock' \
  && ok "doctor names an abandoned clock instead of counting it as open" \
  || bad "doctor names an abandoned clock instead of counting it as open" "$OUT"

OUT="$(ws agent recover --dry-run 2>&1)"
printf '%s' "$OUT" | grep -q 'would recover' && ok "recover --dry-run reports the clock" \
  || bad "recover --dry-run reports the clock" "$OUT"
exists "$OPEN" "recover --dry-run writes nothing"

OUT="$(ws agent recover 2>&1)"
not_exists "$OPEN" "recover closes the clock"
M="$(date +%Y-%m)"
contains "$WS/context/works/agent/api/$M.jsonl" '"recovered":true' \
  "the recovered session is marked as an estimate"
# The start is 139h back and nothing touched the file, so the only honest end is
# the start itself - never `now`, and never the 8h cap either.
contains "$WS/context/works/agent/api/$M.jsonl" '"recovered_basis":"start"' \
  "with no later evidence the end falls back to the start"
RECOVERED="$(grep -c '"recovered":true' "$WS/context/works/agent/api/$M.jsonl")"
[ "$RECOVERED" = 1 ] && ok "a 139h abandoned clock with no evidence writes one record" \
  || bad "a 139h abandoned clock with no evidence writes one record" "got $RECOVERED"
MINUTES="$(grep '"recovered":true' "$WS/context/works/agent/api/$M.jsonl" | sed -n 's/.*"minutes":\([0-9]*\).*/\1/p')"
[ "$MINUTES" = 0 ] && ok "no evidence means no hours invented" \
  || bad "no evidence means no hours invented" "got $MINUTES minutes"

# The other path: the session did keep touching the workspace, but for far longer
# than the cap. The cap is what stops a clock left from Monday billing to Friday.
check "clock in for the cap case" ws agent in api "ran long, died late"
backdate_open "$OPEN" 500000 now
check "recover closes the long-running clock" ws agent recover
contains "$WS/context/works/agent/api/$M.jsonl" '"recovered_basis":"cap"' \
  "a late heartbeat past the cap is recorded as capped"
CAPPED="$(grep '"recovered_basis":"cap"' "$WS/context/works/agent/api/$M.jsonl" \
          | sed -n 's/.*"minutes":\([0-9]*\).*/\1/p' | awk '{s+=$1} END{print s}')"
# 478-480, not exactly 480: minutes are floored per day segment, so a window
# that crosses midnight loses up to a minute to rounding.
[ "$CAPPED" -ge 478 ] && [ "$CAPPED" -le 480 ] \
  && ok "139h of wall clock is recorded as the 8h cap, not 139h" \
  || bad "139h of wall clock is recorded as the 8h cap, not 139h" "got $CAPPED minutes"

check "recover is a no-op when nothing is open" ws agent recover
OUT="$(ws agent recover 2>&1)"; printf '%s' "$OUT" | grep -q 'no open agent clock' \
  && ok "recover says so plainly when there is nothing to do" \
  || bad "recover says so plainly when there is nothing to do" "$OUT"

# A clock inside the cap is a session that may still be running. Recovery must
# leave it alone unless asked, and a second clock-in must still be refused.
check "agent clock in, still fresh" ws agent in api "running now"
check_fails "a second clock-in is still refused while the clock is fresh" ws agent in api "again"
OUT="$(ws agent recover 2>&1)"
printf '%s' "$OUT" | grep -q 'under the' && ok "recover skips a clock inside the cap" \
  || bad "recover skips a clock inside the cap" "$OUT"
exists "$OPEN" "a fresh clock survives recover"
check "--all recovers a fresh clock when explicitly asked" ws agent recover --all
not_exists "$OPEN" "--all closed it"

# The failure that started all this: an agent could not clock in at all, because
# a clock its dead predecessor left behind refused every new session.
check "clock in, to be abandoned again" ws agent in api "abandoned again"
backdate_open "$OPEN" 500000
OUT="$(ws agent in api "the next session" 2>&1)"
printf '%s' "$OUT" | grep -q 'treating it as abandoned' \
  && ok "clock-in recovers an abandoned clock instead of refusing" \
  || bad "clock-in recovers an abandoned clock instead of refusing" "$OUT"
contains "$OPEN" '"note":"the next session"' "the new session is the one now open"

OUT="$(ws hours --project api 2>&1)"
printf '%s' "$OUT" | grep -q 'Estimated, not measured' \
  && ok "ws hours flags that recovered time is an estimate" \
  || bad "ws hours flags that recovered time is an estimate" "$OUT"
check "clock out after the recovery" ws agent out

# --end states a real end the person knows; it must still be bounded by the start
# and by now, or recovery becomes a way to write any number into the record.
check "clock in for the --end case" ws agent in api "ended at a known time"
TS=$(sed -n 's/.*"start_ts":\([0-9]*\).*/\1/p' "$OPEN")
backdate_open "$OPEN" 500000
check_fails "--end in the future is refused" ws agent recover --end "2999-01-01T00:00:00+00:00"
check_fails "--end before the session start is refused" ws agent recover --end "1999-01-01T00:00:00+00:00"
check_fails "--end cannot be combined with --all" ws agent recover --all --end "2020-01-01T00:00:00+00:00"
exists "$OPEN" "a refused --end leaves the clock open"
END=$(date -u -r $((TS-400000)) +%Y-%m-%dT%H:%M:%S+00:00 2>/dev/null \
      || date -u -d @$((TS-400000)) +%Y-%m-%dT%H:%M:%S+00:00)
check "recover accepts a stated end inside the session" ws agent recover --end "$END"
not_exists "$OPEN" "the stated end closed the clock"

section "hooks and automatic agent clocking"
# A hook runs unattended inside someone's editor session: it must never fail, and
# it must never guess which project an hour belongs to.
check "ws hooks status works before installing" ws hooks status
check "ws hooks install"                        ws hooks install
exists "$WS/.claude/settings.json" "settings.json is written"
contains "$WS/.claude/settings.json" "ws agent auto" "it wires the auto clock"

check "auto out is a no-op when nothing is running" ws agent auto out
check "auto in from the root records nothing without a default" ws agent auto in
STATUS="$(ws agent status 2>&1)"
printf '%s' "$STATUS" | grep -q 'no open session' \
  && ok "no session was invented for an unknown project" \
  || bad "no session was invented for an unknown project" "$STATUS"

check "auto in from inside a product repo" env -u RUNDIR sh -c 'cd "$1" && "$2" agent auto in' _ "$PROD" "$WS/.agents/bin/ws"
STATUS="$(ws agent status 2>&1)"
printf '%s' "$STATUS" | grep -q 'api' \
  && ok "the project is resolved from the working directory" \
  || bad "the project is resolved from the working directory" "$STATUS"
check "auto out closes it" ws agent auto out

# Everyone is told to open the editor at the workspace root, where the directory
# walk resolves nothing. A session that has said which project it is on is the
# only signal left, so the hook has to use it or record nothing all day.
WS_SESSION_ID=clockbind check "a session binds from the root" ws session bind api
WS_SESSION_ID=clockbind check "auto in from the root uses the bind" ws agent auto in
STATUS="$(WS_SESSION_ID=clockbind ws agent status 2>&1)"
printf '%s' "$STATUS" | grep -q 'api' \
  && ok "the bound project is clocked, not nothing" \
  || bad "the bound project is clocked, not nothing" "$STATUS"
WS_SESSION_ID=clockbind check "auto out closes the bound session" ws agent auto out
WS_SESSION_ID=clockbind check "session clear" ws session clear

check "ws hooks remove" ws hooks remove
not_exists "$WS/.claude/settings.json" "the hooks are removed again"

section "log and route"
# Preserve an existing Current focus so parallel agents cannot stomp it.
sed -i.bak 's/^- \*\*Current focus:\*\*.*/- **Current focus:** keep this line/' \
  "$WS/context/memory/projects/api/active.md" && rm -f "$WS/context/memory/projects/api/active.md.bak"
check "ws run creates a run directory" ws run api "do the isolated thing"
contains "$WS/context/memory/projects/api/active.md" "keep this line" \
  "ws run does not overwrite Current focus"
contains "$WS/context/memory/projects/api/active.md" "do-the-isolated-thing" \
  "ws run appends the new run to the Active runs table"

check "ws log appends a milestone" ws log api "did a thing"
ws log api "check reported destination" > "$TMP/log-output"
contains "$TMP/log-output" "context/memory/projects/api/log.md" "log reports the real context destination"
lacks "$TMP/log-output" ".agents/memory" "log does not report a forbidden framework path"
contains "$WS/context/memory/projects/api/log.md" "did a thing" "the milestone is in the log"
contains "$WS/context/memory/projects/api/log.md" "tester" "it is attributed to a person"
ROUTE="$(ws route "testing alpha things" 2>&1)"
printf '%s' "$ROUTE" | grep -q 'alpha' && ok "ws route finds a matching skill" \
  || bad "ws route finds a matching skill" "$ROUTE"

# Regression: any skill lacking a `keywords:` line makes the scoring pipeline's
# `grep -v` exit 1 on empty input. Under pipefail + errexit that used to kill
# `ws route` outright the moment it reached such a skill - which was every call,
# since the very first framework skill alphabetically has no keywords line.
mkdir -p "$WS/.agents/skills/no-keywords"
cat > "$WS/.agents/skills/no-keywords/SKILL.md" <<'SKILLEOF'
---
name: no-keywords
pack: core
description: Has no keywords line at all.
---
# no-keywords
SKILLEOF
check "ws route survives a skill with no keywords: line" ws route "testing alpha things"
rm -rf "$WS/.agents/skills/no-keywords"

section "hours by client"
check "human clock in on the api project" ws clock in api "billable acme work"
for f in "$WS"/context/works/.open-*.json; do
  ts=$(sed -n 's/.*"start_ts":\([0-9]*\).*/\1/p' "$f")
  sed -i.bak "s/\"start_ts\":$ts/\"start_ts\":$((ts-3600))/" "$f" && rm -f "$f.bak"
done
check "human clock out" ws clock out
OUT="$(ws hours --client acme 2>&1)"
printf '%s' "$OUT" | grep -q 'client acme' && ok "ws hours --client scopes to that client's projects" \
  || bad "ws hours --client scopes to that client's projects" "$OUT"
printf '%s' "$OUT" | grep -qE '1\.0[0-9]' && ok "the hour is counted under the client" \
  || bad "the hour is counted under the client" "$OUT"
check_fails "ws hours refuses an unknown client" ws hours --client no-such-client
check_fails "ws hours refuses --project and --client together" ws hours --project api --client acme
check "ws hours --rollup" ws hours --rollup
contains "$WS/context/works/rollup/$(date +%Y-%m).json" '"by_client"' "the rollup breaks hours down by client"
contains "$WS/context/works/rollup/$(date +%Y-%m).json" '"acme"' "acme appears in the client breakdown"

# Regression: `cat` exits nonzero the moment ANY argument file is missing. A
# client with two projects, only one of which has hours this month, hits this
# on every call - one of "api"'s siblings below has never been clocked into.
# Under pipefail + errexit that used to kill ws hours outright from inside the
# a=$(...) / h=$(...) assignment in hours_net.
check "ws new registers a second acme project with no hours yet" \
  ws new api2 projects/acme/api2 --client acme
check "ws hours --client survives a sibling project with no session file" \
  ws hours --client acme

section "ws usage: reading a separate, optional tool's data - never merging it in"
check_fails "ws usage fails cleanly with no source configured" ws usage
USRC="$TMP/fake-agent-ops"
mkdir -p "$USRC/ops/usage"
M="$(date +%Y-%m)"
cat > "$USRC/ops/usage/$M.jsonl" <<EOF
{"id":"a","tool":"claude-code","projectRoot":"$PROD","start":"$(date +%Y-%m-%d)T01:00:00Z","end":"$(date +%Y-%m-%d)T02:00:00Z","tokens":{"input":100,"output":200}}
{"id":"b","tool":"cursor","projectRoot":"$WS/projects/acme/api2","start":"$(date +%Y-%m-%d)T01:00:00Z","end":"$(date +%Y-%m-%d)T02:00:00Z","tokens":{"input":10,"output":20}}
{"id":"c","tool":"opencode","projectRoot":"/somewhere/unrelated","start":"$(date +%Y-%m-%d)T01:00:00Z","end":"$(date +%Y-%m-%d)T02:00:00Z","tokens":{"input":999,"output":999}}
{"id":"d","tool":"cursor","projectRoot":null,"start":"$(date +%Y-%m-%d)T01:00:00Z","end":"$(date +%Y-%m-%d)T02:00:00Z","tokens":{"input":999,"output":999}}
EOF
echo "usage_source = $USRC" >> "$WS/workspace.conf"

check "ws usage with no filter reads the configured source" ws usage
OUT="$(ws usage --project api 2>&1)"
printf '%s' "$OUT" | grep -q '\b100\b' && ok "ws usage --project matches only that project's records" \
  || bad "ws usage --project matches only that project's records" "$OUT"
printf '%s' "$OUT" | grep -q '\b999\b' && bad "unrelated projectRoot leaked into the filtered total" "$OUT" \
  || ok "a record with an unrelated projectRoot is excluded"

OUT="$(ws usage --client acme 2>&1)"
printf '%s' "$OUT" | grep -qE '^TOTAL +2 ' && ok "ws usage --client sums across every one of that client's projects" \
  || bad "ws usage --client sums across every one of that client's projects" "$OUT"

check "a record with projectRoot: null never crashes the filter" ws usage --project api
check_fails "ws usage refuses --project and --client together" ws usage --project api --client acme

section "doctor on a bare clone"
# Three bugs have now shipped that only appear before anything has been created:
# check-ignore not matching a directory that does not exist, and `find` on a
# missing directory returning 1 into pipefail. A bare checkout — no skills
# materialised, no context, no product repos — is the state every new machine and
# every CI run starts in, so it gets its own case.
BARE="$TMP/bare"
mkdir -p "$BARE"
cp -R "$SRC/.agents" "$BARE/.agents"
rm -rf "$BARE/.agents/skills" "$BARE/.agents/.cache"
for f in .gitignore .ignore .gitattributes AGENTS.md workspace.conf.example; do
  cp "$SRC/$f" "$BARE/$f"
done
mkdir -p "$BARE/projects"; cp "$SRC/projects/README.md" "$BARE/projects/README.md"
cp "$SRC/test/ws.test.sh" "$BARE/ws.test.sh" 2>/dev/null || true
cp "$BARE/workspace.conf.example" "$BARE/workspace.conf"
git -C "$BARE" init -q
git -C "$BARE" remote add origin "https://example.invalid/bare.git"
git -C "$BARE" add -A >/dev/null 2>&1
git -C "$BARE" commit -qm bare >/dev/null 2>&1
not_exists "$BARE/.agents/skills" "no skills are materialised yet"
not_exists "$BARE/context" "no context repo yet"
check "doctor survives a bare clone" sh -c 'cd "$1" && "$1/.agents/bin/ws" doctor --ci' _ "$BARE"

section "doctor: healthy, then each failure it must catch"
git -C "$WS" add -A >/dev/null 2>&1
git -C "$WS" commit -qm "test workspace" >/dev/null 2>&1
check "doctor passes on a healthy workspace" ws doctor --ci

# A pin can name a commit the source no longer has, after an upstream history
# rewrite. `ws skills sync` reports success anyway - it materialises from the
# local cache - so the workspace that synced looks healthy while every fresh
# clone fails at bootstrap. Doctor is what has to notice.
# The lock is edited in place rather than re-synced: sync is silent about this
# only when the cache still holds the lost commit, which is true on the machine
# that synced before the rewrite and false in a fixture.
LOCKED="$(sed -n 's/^commit[[:space:]]*=[[:space:]]*//p' "$WS/.agents/skills.lock")"
sed -i.bak 's/^commit[[:space:]]*=.*/commit = 0000000000000000000000000000000000000000/' \
  "$WS/.agents/skills.lock" && rm -f "$WS/.agents/skills.lock.bak"
check_fails "doctor fails on a pin the source no longer has" ws doctor --ci
DOC="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$DOC" | grep -q 'ws skills update' \
  && ok "doctor names the re-pin as the fix" \
  || bad "doctor names the re-pin as the fix" "$DOC"
sed -i.bak "s|^commit[[:space:]]*=.*|commit = $LOCKED|" "$WS/.agents/skills.lock" \
  && rm -f "$WS/.agents/skills.lock.bak"
check "doctor passes once the pin is real again" ws doctor --ci

# Every one of these has damaged something real, or would have.
cp "$WS/context/registry.tsv" "$TMP/reg.bak"
printf 'api\tprojects/other\t-\tduplicate key\n' >> "$WS/context/registry.tsv"
check_fails "doctor fails on a duplicate registry key" ws doctor --ci
cp "$TMP/reg.bak" "$WS/context/registry.tsv"

cp "$WS/context/registry.tsv" "$TMP/reg2.bak"
printf 'orphan\tno-such-client\tprojects/orphan\t-\tno client dir\n' >> "$WS/context/registry.tsv"
check_fails "doctor fails when a project's client does not exist" ws doctor --ci
cp "$TMP/reg2.bak" "$WS/context/registry.tsv"

cp "$WS/context/registry.tsv" "$TMP/reg3.bak"
printf 'clientless\t-\tprojects/clientless\t-\tno client at all\n' >> "$WS/context/registry.tsv"
check_fails "doctor fails when a project names no client at all" ws doctor --ci
cp "$TMP/reg3.bak" "$WS/context/registry.tsv"

cp "$WS/context/registry.tsv" "$TMP/reg4.bak"
mkdir -p "$WS/context/clients/other"
printf 'badgroup\tother\tplatform\tprojects/other/badgroup\t-\tclient\t-\tgroup owned by acme\n' >> "$WS/context/registry.tsv"
check_fails "doctor fails when a project uses another client's group" ws doctor --ci
cp "$TMP/reg4.bak" "$WS/context/registry.tsv"
rm -rf "$WS/context/clients/other"

# Assembled from pieces on purpose: a literal machine path here would trip the
# very check this case exists to test, and fail doctor on this file in CI.
BADPATH="/$(printf 'Users')/someone/workspace"
echo "- root: $BADPATH" >> "$WS/AGENTS.md"
git -C "$WS" add AGENTS.md >/dev/null 2>&1
check_fails "doctor fails on a machine path in a tracked file" ws doctor --ci
# the bad line was staged, so the index holds it too - restore from the commit
git -C "$WS" reset -q HEAD AGENTS.md 2>/dev/null || true
git -C "$WS" checkout -- AGENTS.md 2>/dev/null || true

git -C "$PROD" add -f AGENTS.md >/dev/null 2>&1
check_fails "doctor fails when a pointer is tracked in a client repo" ws doctor --ci
git -C "$PROD" reset -q

cp "$WS/workspace.conf" "$TMP/conf.bak"
awk 'BEGIN{d=0} /^[[:space:]]*packs[[:space:]]*=/{print "packs = core, nosuchpack"; d=1; next} {print} END{if(!d) print "packs = core, nosuchpack"}' \
  "$TMP/conf.bak" > "$WS/workspace.conf"
check_fails "doctor fails on a standards pack that does not exist" ws doctor --ci
cp "$TMP/conf.bak" "$WS/workspace.conf"

awk 'BEGIN{d=0} /^[[:space:]]*packs[[:space:]]*=/{print "packs = core"; d=1; next} {print} END{if(!d) print "packs = core"}' \
  "$TMP/conf.bak" > "$WS/workspace.conf"
ws doctor >"$TMP/doctor-core-only.txt" 2>&1 || true
contains "$TMP/doctor-core-only.txt" "Java not required" "doctor does not require Java when the java pack is off"
cp "$TMP/conf.bak" "$WS/workspace.conf"

mv "$WS/.gitignore" "$TMP/gitignore.bak"
printf '/projects/*\n!/projects/README.md\n' > "$WS/.gitignore"
check_fails "doctor fails when context is no longer ignored" ws doctor --ci
mv "$TMP/gitignore.bak" "$WS/.gitignore"

git -C "$WS" add -A >/dev/null 2>&1
check "doctor passes again once each fault is undone" ws doctor --ci

section "git clean -ff guard and ADR-0010 context split"
SHIM="$SRC/.agents/bin/git"
check_fails "git shim refuses clean -ff at the workspace root" \
  "$SHIM" -C "$WS" clean -ffxd
check "git shim still lists status" "$SHIM" -C "$WS" status -sb
mkdir -p "$TMP/not-a-workspace"
git -C "$TMP/not-a-workspace" init -q
check "git shim allows clean -ff outside a workspace root" \
  "$SHIM" -C "$TMP/not-a-workspace" clean -ffxd

echo "personal_clients = donwi" >> "$WS/workspace.conf"
# Earlier switch tests attach a context remote. Mixed+remote is a failure;
# detach so the operator-local warning is what we assert here.
git -C "$WS/context" remote remove origin 2>/dev/null || true
check "ws client new donwi" ws client new donwi
mkdir -p "$WS/projects/donwi/pub" && git -C "$WS/projects/donwi/pub" init -q
git -C "$WS/projects/donwi/pub" commit --allow-empty -qm init
check "ws new registers a personal project" \
  ws new toys projects/donwi/pub --client donwi
if ws doctor --ci >"$TMP/doctor-mixed.txt" 2>&1; then
  ok "mixed operator-local context still passes doctor --ci"
else
  bad "mixed operator-local context still passes doctor --ci" "$(head -80 "$TMP/doctor-mixed.txt")"
fi
contains "$TMP/doctor-mixed.txt" "mixes personal_clients" \
  "doctor warns when personal and paying-client rows share one context"

check_fails "ws context switch refuses to publish mixed history" \
  ws context switch git@gitlab.example/mixed.git --force

check "ws context split writes audience copies" \
  ws context split --personal donwi
exists "$WS/.local/contexts/donwi/registry.tsv" "personal copy has a registry"
exists "$WS/.local/contexts/org/registry.tsv" "org copy has a registry"
contains "$WS/.local/contexts/donwi/registry.tsv" "toys" "personal copy has the donwi project"
lacks "$WS/.local/contexts/donwi/registry.tsv" "api" "personal copy has no paying-client project"
contains "$WS/.local/contexts/org/registry.tsv" "api" "org copy keeps the paying-client project"
lacks "$WS/.local/contexts/org/registry.tsv" "toys" "org copy has no donwi project"
exists "$WS/.local/archives" "mixed history was archived locally"

git -C "$WS/context" remote add origin "https://example.invalid/mixed-context.git"
check_fails "doctor fails when a mixed context has a remote" ws doctor --ci
git -C "$WS/context" remote remove origin

section "no private identifier reaches the published tree"
# The framework repo is public. The previous guard was a two-name regex living in
# three tracked files, so it published the very client name it was scrubbing and
# knew nothing about the other seven clients. The list now comes from the context
# repo, which only someone able to push this repo has.
ALLOW='acme\nbeta\nplatform\ndonwi\ntoys\notherp\nlocked\napi2\nstrict\npub\n'
printf "$ALLOW" > "$WS/context/public-identifiers"
check "doctor passes when every derived name is declared public" ws doctor --ci

# Put the undeclared client key in a tracked framework file explicitly. This keeps
# the assertion independent of local workspace identity settings.
printf '# acme belongs to a client\n' >> "$WS/AGENTS.md"
git -C "$WS" add AGENTS.md >/dev/null 2>&1
printf "$ALLOW" | grep -v '^acme$' > "$WS/context/public-identifiers"
check_fails "an undeclared client key in a tracked file fails doctor" ws doctor --ci
OUT="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$OUT" | grep -q 'public-identifiers' \
  && ok "doctor names the allowlist as the fix" \
  || bad "doctor names the allowlist as the fix" "$OUT"
git -C "$WS" reset -q HEAD AGENTS.md 2>/dev/null || true
git -C "$WS" checkout -- AGENTS.md 2>/dev/null || true

# `.agents/` and `test/` were excluded from the old scan, which is where two of
# the three real leaks were sitting.
printf "$ALLOW" > "$WS/context/public-identifiers"
printf '# acme2 belongs to a client\n' >> "$WS/.agents/standards/core/git-workflow.md"
git -C "$WS" add .agents/standards/core/git-workflow.md >/dev/null 2>&1
ws client new acme2 >/dev/null 2>&1
check_fails "a client name inside .agents/ is caught too" ws doctor --ci
git -C "$WS" checkout -- .agents/standards/core/git-workflow.md 2>/dev/null || true
rm -f "$WS/context/public-identifiers"

section "public CI governance stays deterministic"
GOVERNANCE="$SRC/.github/workflows/agentic-governance.yml"
exists "$GOVERNANCE" "agentic governance workflow exists"
contains "$GOVERNANCE" 'permissions:' "governance workflow declares permissions"
contains "$GOVERNANCE" 'contents: read' "governance workflow is read-only"
contains "$GOVERNANCE" 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1' \
  "governance checkout is pinned"
contains "$GOVERNANCE" 'ws_eval.py validate' "governance validates evaluation template"
contains "$GOVERNANCE" 'ws_compat.py validate' "governance validates compatibility template"
lacks "$GOVERNANCE" 'git clone' "governance does not clone private repositories"

# ═════════════════════════════════════════════════════════════════════════════
printf '\n'
if [ "$FAIL" -eq 0 ]; then grn "$PASS passed, 0 failed"; exit 0
else red "$PASS passed, $FAIL FAILED"; exit 1; fi
