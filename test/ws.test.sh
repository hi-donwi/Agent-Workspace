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
HOST_ENV="WS_SESSION_ID GROK_SESSION_ID GROK_SESSION CLAUDE_SESSION_ID CLAUDE_CODE_SESSION_ID
          CODEX_THREAD_ID CURSOR_TRACE_ID CLAUDECODE CODEX_SANDBOX GEMINI_CLI"
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
contains "$WS/workspace.conf" "context_publish = manual" "context publication defaults to manual"
check "ws init is idempotent and refuses to clobber" ws init
contains "$WS/workspace.conf" "org_key        = acme" "workspace.conf keeps only a technical workspace key"

section "ws launcher for agent shells"
LAUNCHBIN="$TMP/ws-bin"
check "ws install writes a user launcher" ws install --bin-dir "$LAUNCHBIN"
exists "$LAUNCHBIN/ws" "the launcher exists"
contains "$LAUNCHBIN/ws" "generated by ws install" "the launcher is marked as managed"
check "ws install is idempotent" ws install --bin-dir "$LAUNCHBIN"
equals "$(env HOME="$HOME" PATH="$LAUNCHBIN:/usr/bin:/bin" sh -c 'cd "$1" && ws where' _ "$WS")" "$WS" \
  "bare ws resolves from the workspace root without .agents/bin on PATH"
mkdir -p "$WS/agent-cwd/nested"
equals "$(env HOME="$HOME" PATH="$LAUNCHBIN:/usr/bin:/bin" sh -c 'cd "$1" && ws where' _ "$WS/agent-cwd/nested")" "$WS" \
  "bare ws resolves from a nested agent working directory"
CONFLICTBIN="$TMP/conflict-bin"
mkdir -p "$CONFLICTBIN"
printf '# user-owned launcher\n' > "$CONFLICTBIN/ws"
check_fails "ws install does not overwrite an unowned launcher" ws install --bin-dir "$CONFLICTBIN"
contains "$CONFLICTBIN/ws" "user-owned launcher" "the unowned launcher is unchanged"

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
check_fails "ws web refuses" ws web
check "ws context sync is a no-op without a remote" ws context sync
check_fails "ws context switch without a remote url refuses" ws context switch
OUT="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$OUT" | grep -q "private-local" \
  && ok "doctor reports a context with no remote as private-local" \
  || bad "doctor reports a context with no remote as private-local" "$OUT"
printf '%s' "$OUT" | grep -q "primary clone" \
  && ok "doctor warns that the primary clone is a shared HEAD" \
  || bad "doctor warns that the primary clone is a shared HEAD" "$OUT"
printf '%s' "$OUT" | grep -q "GB free" \
  && bad "doctor --ci skips the local disk check" "$OUT" \
  || ok "doctor --ci skips the local disk check"
# A full disk stops agents mid-run (no swap, failed installs), so doctor says so
# before it happens. The threshold is per machine: min_free_disk_gb.
cp "$WS/workspace.conf" "$TMP/workspace.conf.keep"
printf 'min_free_disk_gb = 999999999\n' >> "$WS/workspace.conf"
DISK_OUT="$(ws doctor 2>&1 || true)"
printf '%s' "$DISK_OUT" | grep -q "below min_free_disk_gb" \
  && ok "doctor warns when free disk is below min_free_disk_gb" \
  || bad "doctor warns when free disk is below min_free_disk_gb" "$DISK_OUT"
printf 'min_free_disk_gb = 0\n' > "$TMP/disk.conf"
cat "$TMP/workspace.conf.keep" "$TMP/disk.conf" > "$WS/workspace.conf"
DISK_OUT="$(ws doctor 2>&1 || true)"
printf '%s' "$DISK_OUT" | grep -q "ok .* GB free on the workspace volume" \
  && ok "doctor reports free disk above the threshold" \
  || bad "doctor reports free disk above the threshold" "$DISK_OUT"
cp "$TMP/workspace.conf.keep" "$WS/workspace.conf"
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
check "ws context switch records the publish origin" ws context switch "$CTXBARE"
check_fails "context publish refuses dirty files" ws context publish
git -C "$WS/context" add README.md && git -C "$WS/context" commit -qm "docs: publish context fixture"
check "ws context publish pushes the context repository" ws context publish
equals "$(git -C "$CTXBARE" rev-parse main)" "$(git -C "$WS/context" rev-parse HEAD)" \
  "context publish updates only the context remote"
check_fails "context publish refuses a force option" ws context publish --force
CTXPEER="$TMP/context-peer"
git clone -q "$CTXBARE" "$CTXPEER"
printf 'peer update\n' >> "$CTXPEER/README.md"
git -C "$CTXPEER" add README.md && git -C "$CTXPEER" commit -qm "docs: peer context update"
git -C "$CTXPEER" push -q origin main
check_fails "context publish refuses a remote branch that moved ahead" ws context publish
check "context sync recovers from the remote update" ws context sync
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
exists "$WS/context/clients/acme/contacts.md" "contacts.md is scaffolded, restricted"
exists "$WS/context/clients/acme/commercial.md" "commercial.md is scaffolded, restricted"
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

# Establish a clean, published baseline before testing automatic publication. This is a
# disposable fixture repository, so committing the setup is intentional.
git -C "$WS/context" add -A && git -C "$WS/context" commit -qm "test: prepare context publish baseline"
git -C "$WS/context" push -q origin main
sed -i.bak -E 's/^[[:space:]]*context_publish[[:space:]]*=.*/context_publish = auto/' "$WS/workspace.conf"
rm -f "$WS/workspace.conf.bak"
contains "$WS/workspace.conf" "context_publish = auto" "auto context publication is enabled"
NO_PUBLISH_REMOTE="$(git -C "$CTXBARE" rev-parse main)"
check "ws run creates a no-publish override fixture" ws run api "no publish context checkpoint"
NO_PUBLISH_RUN="$(ls "$WS/context/runs/api")"
printf '\nno publish checkpoint\n' >> "$WS/context/runs/api/$NO_PUBLISH_RUN/plan.md"
check "checkpoint no-publish override stays local" ws checkpoint api --no-publish
equals "$(git -C "$CTXBARE" rev-parse main)" "$NO_PUBLISH_REMOTE" \
  "no-publish override leaves the context remote unchanged"
check "explicit publish shares the no-publish checkpoint" ws context publish
check "ws run creates an auto-publish fixture" ws run api "auto context checkpoint"
AUTO_RUN=""
for run_path in "$WS/context/runs/api"/*; do AUTO_RUN="${run_path##*/}"; done
printf '\nauto publish checkpoint\n' >> "$WS/context/runs/api/$AUTO_RUN/plan.md"
AUTO_OUT="$(ws checkpoint api -m "checkpoint auto publish" 2>&1)"
if printf '%s' "$AUTO_OUT" | grep -q 'context published'; then
  ok "auto context publication pushes the session checkpoint"
else
  bad "auto context publication pushes the session checkpoint" "$AUTO_OUT"
fi
equals "$(git -C "$CTXBARE" rev-parse main)" "$(git -C "$WS/context" rev-parse HEAD)" \
  "auto publication reaches the configured context remote"
sed -i.bak -E 's/^[[:space:]]*context_publish[[:space:]]*=.*/context_publish = manual/' "$WS/workspace.conf"
rm -f "$WS/workspace.conf.bak"

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

# An agent's worktree is verified where the agent's change is, not in the primary checkout.
VT="$WS/.local/worktrees/api/vt1"
git -C "$PROD" worktree add -q -b ws-verify-vt1 "$VT"
: > "$VT/only-in-worktree.txt"
cat > "$WS/.local/agent/contracts/worktree.json" <<'JSON'
{
  "schema_version": 1,
  "name": "runs where the change is",
  "commands": [{"id": "sees-the-worktree", "command": "test -f only-in-worktree.txt", "timeout_seconds": 10}]
}
JSON
check "ws verify --worktree runs the contract in the agent worktree" \
  ws verify api --worktree "$VT" --contract "$WS/.local/agent/contracts/worktree.json" --json
check_fails "the same contract fails in the primary checkout" \
  ws verify api --contract "$WS/.local/agent/contracts/worktree.json"
check_fails "ws verify --worktree refuses the primary checkout" \
  ws verify api --worktree "$PROD" --contract "$WS/.local/agent/contracts/worktree.json"
mkdir -p "$WS/.local/worktrees/api/plain"
check_fails "ws verify --worktree refuses a folder that is not a worktree of the project" \
  ws verify api --worktree "$WS/.local/worktrees/api/plain" --contract "$WS/.local/agent/contracts/worktree.json"
mkdir -p "$WS/.local/worktrees/other"
git init -q "$WS/.local/worktrees/api/foreign"
check_fails "ws verify --worktree refuses another repository under the project's worktrees" \
  ws verify api --worktree "$WS/.local/worktrees/api/foreign" --contract "$WS/.local/agent/contracts/worktree.json"
check_fails "ws verify --worktree refuses a path that climbs out of the project's worktrees" \
  ws verify api --worktree "$WS/.local/worktrees/api/../other" --contract "$WS/.local/agent/contracts/worktree.json"
printf '{"schema_version":1,"commands":[{"id":"x","command":"true"}]}' > "$VT/inside-contract.json"
check_fails "ws verify --worktree rejects a contract inside the worktree" \
  ws verify api --worktree "$VT" --contract "$VT/inside-contract.json"
for case in "$PROD|lives under .local/worktrees/api/" \
            "$WS/.local/worktrees/api/foreign|not a worktree of api" \
            "$WS/.local/worktrees/api/../other|lives under .local/worktrees/api/" \
            "$VT|contract must not live inside"; do
  target="${case%%|*}"; reason="${case#*|}"
  contract="$WS/.local/agent/contracts/worktree.json"
  [ "$target" = "$VT" ] && contract="$VT/inside-contract.json"
  OUT="$(ws verify api --worktree "$target" --contract "$contract" 2>&1 || true)"
  printf '%s' "$OUT" | grep -q -- "$reason" \
    && ok "ws verify --worktree says why: $reason" \
    || bad "ws verify --worktree says why: $reason" "$OUT"
done
git -C "$PROD" worktree remove --force "$VT"
git -C "$PROD" branch -q -D ws-verify-vt1
rm -rf "$WS/.local/worktrees/api/plain" "$WS/.local/worktrees/api/foreign" "$WS/.local/worktrees/other"

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

section "ws learn: harvest run learnings into a candidate skill"
mkdir -p "$WS/context/runs/api/run-mock"
cat > "$WS/context/runs/api/run-mock/brief.md" <<'MD'
# Mock Feature
## Goal
Implement mock endpoint.
MD
cat > "$WS/context/runs/api/run-mock/decisions.md" <<'MD'
## D-01: Mock Decision
Always use record DTOs.
MD
check "ws learn extracts run and generates valid draft" ws learn api --run run-mock --name mock-skill
exists "$WS/.local/skills-draft/mock-skill/SKILL.md" "draft SKILL.md written"
# The default used to install into a machine-wide skills folder that every later
# session loads, whatever client it works for: one client's decisions in every other
# client's prompt (ADR-0011). A draft stays in .local/ until someone picks a scope.
not_exists "$HOME/.gemini/config/skills/mock-skill" "the default installs nothing machine-wide"
check_fails "a client project's run cannot be installed machine-wide" \
  ws learn api --run run-mock --name client-skill --user
not_exists "$HOME/.gemini/config/skills/client-skill" "the refused install wrote nothing"
mkdir -p "$WS/context/runs/workspace/run-fw"
printf '# Framework lesson\n## Goal\nKeep the CLI dependency-free.\n' \
  > "$WS/context/runs/workspace/run-fw/brief.md"
check "the framework's own run may be installed machine-wide" \
  ws learn workspace --run run-fw --name fw-skill --user
exists "$HOME/.gemini/config/skills/fw-skill/SKILL.md" "the framework skill is installed"
check_fails "a skill name cannot climb out of the drafts folder" \
  ws learn api --run run-mock --name ../../escaped
not_exists "$WS/escaped" "nothing was written outside .local/skills-draft"
check_fails "a run id cannot climb out of the project's runs" ws learn api --run ../workspace/run-fw
WS_SESSION_ID=learnbind ws session bind api >/dev/null 2>&1
WS_SESSION_ID=learnbind check "ws learn defaults to the bound project" \
  ws learn --run run-mock --name bound-skill
exists "$WS/.local/skills-draft/bound-skill/SKILL.md" "the bound project's run was harvested"
WS_SESSION_ID=learnbind ws session clear >/dev/null 2>&1

section "ws compact: memory and output auto-compaction"
# Compaction rewrites shared memory files, so what it keeps matters more than what it
# saves. ws run inserts the newest run at the TOP of the table; State is a column, and
# "opencode" in an owner is not the word "open".
CM="$WS/context/memory/projects/compactdemo"; mkdir -p "$CM"
cat > "$CM/active.md" <<'MD'
# compactdemo - active

- **Current focus:** COMPACT_FOCUS_CANARY

## Active runs

| Run | Owner | State |
|---|---|---|
| `2026-09-09-090000-a-x-new` | a (claude-code) | open |
| `2026-09-08-090000-a-x-review` | a (claude-code) | ready for review |
| `2026-09-07-090000-a-x-progress` | a (claude-code) | in progress |
| `2026-09-06-090000-a-x-blocked` | a (claude-code) | blocked |
| `2026-09-05-090000-a-x-d5` | a (claude-code) | done |
| `2026-09-04-090000-a-x-d4` | a (claude-code) | done |
| `2026-09-03-090000-a-x-d3` | a (claude-code) | done |
| `2026-09-02-090000-a-x-d2` | a (claude-code) | done |
| `2026-09-01-090000-a-opencode-d1` | a (opencode) | done |

## Next up

- COMPACT_NEXT_CANARY
MD
{ printf '# compactdemo - log\n\n| Date | Milestone |\n|---|---|\n'
  for d in 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20; do
    printf '| 2026-09-%s | milestone %s |\n' "$d" "$d"
  done
  printf '\nCOMPACT_FOOTER_CANARY\n'; } > "$CM/log.md"
cp "$CM/active.md" "$TMP/compact-active.before"; cp "$CM/log.md" "$TMP/compact-log.before"
check "ws compact memory without --apply is a dry run" ws compact memory compactdemo
cmp -s "$CM/active.md" "$TMP/compact-active.before" && cmp -s "$CM/log.md" "$TMP/compact-log.before" \
  && ok "the dry run changed nothing" || bad "the dry run changed nothing"
check "ws compact memory --apply compacts" ws compact memory compactdemo --apply
for live in x-new x-review x-progress x-blocked; do
  contains "$CM/active.md" "$live" "a live run is kept ($live)"
done
contains "$CM/active.md" "x-d5" "the newest done runs are kept"
contains "$CM/active.md" "x-d3" "up to the limit of three"
lacks "$CM/active.md" "x-d2" "older done runs are dropped"
lacks "$CM/active.md" "opencode-d1" "an owner named opencode is not mistaken for an open run"
contains "$CM/active.md" "COMPACT_FOCUS_CANARY" "text above the runs table is kept"
contains "$CM/active.md" "COMPACT_NEXT_CANARY" "sections after the runs table are kept"
contains "$CM/log.md" "| 2026-09-20 |" "the newest milestones stay in log.md"
lacks "$CM/log.md" "| 2026-09-05 |" "older milestones leave log.md"
contains "$CM/log-archive.md" "| 2026-09-05 |" "and are archived, not deleted"
contains "$CM/log.md" "COMPACT_FOOTER_CANARY" "text after the log table is kept"
check_fails "ws compact refuses something that is not a project key" ws compact memory ../api
rm -rf "$CM"
check "ws compact exec runs command with condensation" ws compact exec -- echo "compact-ok"

# A line-count limit alone does nothing against one line that is itself huge -
# a single-line JSON dump or minified bundle never trips "too many lines".
HUGE_OUT="$(ws compact exec -- python3 -c 'print("A" * 5000)')"
printf '%s' "$HUGE_OUT" | grep -q "more chars on this line" \
  && ok "ws compact exec truncates a single oversized line" \
  || bad "ws compact exec truncates a single oversized line" "$HUGE_OUT"
LOGGED="$(/usr/bin/grep -l "AAAAA" "$WS/.local/logs"/python3-*.log 2>/dev/null | tail -1)"
[ -n "$LOGGED" ] && [ "$(wc -c < "$LOGGED")" -gt 5000 ] \
  && ok "the full, untruncated line is still saved to .local/logs/" \
  || bad "the full, untruncated line is still saved to .local/logs/" "$LOGGED"

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

# Stopped sessions leave their worktrees behind, each with its own dependencies and
# build output. `ws agent clean` removes only the ones git itself calls clean, and
# never one a live session, uncommitted work, or a branchless commit still needs.
WT="$WS/.local/worktrees/api"
CLEAN_OUT="$(ws agent clean 2>&1)"
printf '%s' "$CLEAN_OUT" | grep -q "api/wt1 (used 0h ago)" \
  && ok "ws agent clean keeps a worktree used inside the idle window" \
  || bad "ws agent clean keeps a worktree used inside the idle window" "$CLEAN_OUT"
CLEAN_OUT="$(ws agent clean --idle-hours 0 2>&1)"
printf '%s' "$CLEAN_OUT" | grep -q "clean .local/worktrees/api/wt1" \
  && ok "ws agent clean lists an idle clean worktree" \
  || bad "ws agent clean lists an idle clean worktree" "$CLEAN_OUT"
exists "$WT/wt1/.git" "ws agent clean without --apply removes nothing"
WS_SESSION_ID=wt2 ws agent start api "dirty" >/dev/null 2>&1
printf 'draft\n' > "$WT/wt2/scratch.txt"
WS_SESSION_ID=wt2 ws agent stop >/dev/null 2>&1
WS_SESSION_ID=wt3 ws agent start api "live" >/dev/null 2>&1
WS_SESSION_ID=wt4 ws agent start api "branchless" >/dev/null 2>&1
git -C "$WT/wt4" checkout -q --detach
git -C "$WT/wt4" commit -q --allow-empty -m "commit on no branch"
WS_SESSION_ID=wt4 ws agent stop >/dev/null 2>&1
check "ws agent clean --apply removes idle clean worktrees" \
  ws agent clean --apply --idle-hours 0
not_exists "$WT/wt1" "the idle clean worktree is removed"
[ -n "$(git -C "$PROD" branch --list 'agent-wt1-*')" ] && ok "its branch survives the worktree" \
  || bad "its branch survives the worktree"
exists "$WT/wt2/scratch.txt" "a worktree with untracked work is kept"
exists "$WT/wt3/.git" "a worktree with a live session lock is kept"
exists "$WT/wt4/.git" "a worktree whose HEAD is on no branch is kept"
check_fails "ws agent clean refuses a non-numeric idle window" \
  ws agent clean --idle-hours soon
WS_SESSION_ID=wt3 ws agent stop >/dev/null 2>&1

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

section "SessionStart(compact) reminder (PreCompact pairing)"
# Compaction erases the transcript, including whatever told the agent which
# project's allowlist is still in force. ws session compact-reminder is what
# the installed SessionStart(compact) hook calls to hand that back.
REMINDER="$(WS_SESSION_ID=attn ws session compact-reminder)"
printf '%s' "$REMINDER" | grep -q '"hookSpecificOutput"' \
  && printf '%s' "$REMINDER" | grep -q 'project `api`' \
  && ok "compact-reminder names the bound project" \
  || bad "compact-reminder names the bound project" "$REMINDER"
printf '%s' "$REMINDER" | grep -q "sessions/attn/CONTEXT.md" \
  && ok "compact-reminder points at this session's pack" \
  || bad "compact-reminder points at this session's pack" "$REMINDER"

UNBOUND_REMINDER="$(WS_SESSION_ID=attn-unbound ws session compact-reminder)"
[ -z "$UNBOUND_REMINDER" ] \
  && ok "compact-reminder is silent with no bind" \
  || bad "compact-reminder is silent with no bind" "$UNBOUND_REMINDER"

WS_SESSION_ID=wtbind check "ws agent start also binds the session" ws agent start api "bind-on-start"
exists "$WS/.local/sessions/wtbind/bind" "agent start wrote a bind"
contains "$WS/.local/sessions/wtbind/bind" "project=api" "agent start bound api"
WS_SESSION_ID=wtbind check "ws agent stop leaves the bind in place" ws agent stop
exists "$WS/.local/sessions/wtbind/bind" "bind survives agent stop"

section "workspace-local user preferences reach CONTEXT.md"
# session_dir() is $ROOT/.local/sessions/<id>: two .parent hops land on $ROOT/.local
# already, so appending another ".local" looked for $ROOT/.local/.local/rules/ - a path
# that never exists. The workspace's own preferences file was silently never read.
mkdir -p "$WS/.local/rules"
printf 'PREFERS_TABS_CANARY
' > "$WS/.local/rules/user-preferences.md"
WS_SESSION_ID=prefs check "bind succeeds with a workspace-local preferences file"   ws session bind api
contains "$WS/.local/sessions/prefs/CONTEXT.md" "PREFERS_TABS_CANARY"   "the workspace-local preferences file reaches CONTEXT.md"
rm -rf "$WS/.local/rules"
WS_SESSION_ID=prefs check "bind still succeeds with neither preferences file"   ws session bind api
lacks "$WS/.local/sessions/prefs/CONTEXT.md" "## User preferences"   "no preferences section is added when neither file exists"

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

section "one checkout, two keys (a monorepo subproject)"
# A registry row whose folder sits inside another row's checkout, with the same remote:
# an API and its mobile app in one repository, registered as two projects. Every
# command that clones, inits or links into a project's folder must leave this one
# alone — it is a subdirectory of a tracked tree.
MONO="$WS/projects/beta/app"
mkdir -p "$MONO/mobile" && echo 'void main() {}' > "$MONO/mobile/main.dart"
git -C "$MONO" add -A && git -C "$MONO" commit -qm "add mobile app"
git -C "$MONO" push -q origin HEAD

check "ws new registers a subproject inside a monorepo" \
  ws new otherp-mobile projects/beta/app/mobile "$OTHERBARE" --client beta
not_exists "$MONO/mobile/.git" "no repository is nested inside the parent's tree"
ROWCOLS="$(grep '^otherp-mobile' "$WS/context/registry.tsv" | awk -F'\t' '{print NF}')"
[ "$ROWCOLS" = 9 ] && ok "ws new writes nine columns on a v3 registry" \
  || bad "ws new writes nine columns on a v3 registry" "got $ROWCOLS"

OUT="$(ws doctor 2>&1 || true)"
printf '%s' "$OUT" | grep -q "otherp-mobile lives inside otherp's repo" \
  && ok "doctor recognises the subproject" || bad "doctor recognises the subproject" "$OUT"
printf '%s' "$OUT" | grep -q 'x otherp-mobile' \
  && bad "doctor does not fail a subproject for having no .git" "$OUT" \
  || ok "doctor does not fail a subproject for having no .git"

check "ws link on a subproject succeeds without writing" ws link otherp-mobile
not_exists "$MONO/mobile/AGENTS.md" "no pointer inside a subdirectory of a tracked tree"
not_exists "$MONO/mobile/.workspace" "nor a breadcrumb"
equals "$(git -C "$MONO" status --porcelain | wc -l | tr -d ' ')" "0" \
  "the parent's working tree stays clean"

# The case that actually broke: a fresh machine. The parent's clone creates the
# subproject's folder, and the old code then tried to clone the whole monorepo into it.
rm -rf "$MONO"
check "a fresh bootstrap clones the monorepo once" ws bootstrap --only beta
exists "$MONO/mobile/main.dart" "the subproject arrived with its parent"
not_exists "$MONO/mobile/.git" "the monorepo was not cloned into its own subdirectory"

# Hours from inside the subproject belong to it, not to whichever row came first.
RUNDIR="$MONO/mobile" check "the hook clocks in from inside the subproject" ws agent auto in
contains "$WS/context/works/.open-agent-tester-testagent-default.json" '"project":"otherp-mobile"' \
  "the most specific folder wins, so the hours are the subproject's"
check "and clocks out" ws agent auto out

# The rule is narrow on purpose: a folder inside another project with a DIFFERENT remote
# is a separate repository and must still be one.
mkdir -p "$MONO/vendored"
printf 'otherp-vendored\tbeta\t-\tprojects/beta/app/vendored\thttps://example.invalid/vendored.git\tclient\t-\tvendored\t-\n' \
  >> "$WS/context/registry.tsv"
mkdir -p "$WS/context/memory/projects/otherp-vendored"
OUT="$(ws doctor 2>&1 || true)"
printf '%s' "$OUT" | grep -q 'x otherp-vendored exists but is not a git repo' \
  && ok "a nested folder with a different remote must still be its own repo" \
  || bad "a nested folder with a different remote must still be its own repo" "$OUT"

# Leave the registry as the later sections expect it.
python3 - "$WS/context/registry.tsv" <<'PYEOF'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
keep = [l for l in p.read_text().split("\n") if not l.startswith(("otherp-mobile\t", "otherp-vendored\t"))]
p.write_text("\n".join(keep))
PYEOF
rm -rf "$MONO/vendored" "$WS/context/memory/projects/otherp-vendored" "$WS/context/memory/projects/otherp-mobile"

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
# A recovered record is dated by the backdated start, 500000s (~6 days) ago - in the
# first days of a month that is last month's file. Read every month, and ask
# `ws hours` for the start's month, or this block fails the first six days of a month.
RM_TS=$(( $(date +%s) - 500000 ))
RM="$(date -r "$RM_TS" +%Y-%m 2>/dev/null || date -d "@$RM_TS" +%Y-%m)"
RECS="$TMP/agent-api-records.jsonl"
cat "$WS"/context/works/agent/api/*.jsonl > "$RECS"
contains "$RECS" '"recovered":true' \
  "the recovered session is marked as an estimate"
# The start is 139h back and nothing touched the file, so the only honest end is
# the start itself - never `now`, and never the 8h cap either.
contains "$RECS" '"recovered_basis":"start"' \
  "with no later evidence the end falls back to the start"
RECOVERED="$(grep -c '"recovered":true' "$RECS")"
[ "$RECOVERED" = 1 ] && ok "a 139h abandoned clock with no evidence writes one record" \
  || bad "a 139h abandoned clock with no evidence writes one record" "got $RECOVERED"
MINUTES="$(grep '"recovered":true' "$RECS" | sed -n 's/.*"minutes":\([0-9]*\).*/\1/p')"
[ "$MINUTES" = 0 ] && ok "no evidence means no hours invented" \
  || bad "no evidence means no hours invented" "got $MINUTES minutes"

# The other path: the session did keep touching the workspace, but for far longer
# than the cap. The cap is what stops a clock left from Monday billing to Friday.
check "clock in for the cap case" ws agent in api "ran long, died late"
backdate_open "$OPEN" 500000 now
check "recover closes the long-running clock" ws agent recover
cat "$WS"/context/works/agent/api/*.jsonl > "$RECS"
contains "$RECS" '"recovered_basis":"cap"' \
  "a late heartbeat past the cap is recorded as capped"
CAPPED="$(grep '"recovered_basis":"cap"' "$RECS" \
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

OUT="$(ws hours --project api --month "$RM" 2>&1)"
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
contains "$WS/.claude/settings.json" "checkpoint --no-publish" "compaction checkpoint never publishes"
contains "$WS/.claude/settings.json" "ws checkpoint || true" "stop checkpoint uses the publication policy"
# Every turn ends with `auto out` on Stop, so the clock must open on every prompt, not
# once per session - or every turn after the first goes unrecorded. Session start is
# not a turn: the time until the first prompt is spent waiting for a person.
hook_has() { python3 - "$WS/.claude/settings.json" "$1" "$2" <<'PY'
import json, sys
settings, event, needle = sys.argv[1:]
groups = json.load(open(settings)).get("hooks", {}).get(event, [])
sys.exit(0 if any(needle in h.get("command", "") for g in groups for h in g.get("hooks", [])) else 1)
PY
}
check "each prompt clocks in" hook_has UserPromptSubmit "ws agent auto in"
check "each turn clocks out" hook_has Stop "ws agent auto out"
check "the session end clocks out" hook_has SessionEnd "ws agent auto out"
check_fails "session start does not clock in" hook_has SessionStart "ws agent auto in"

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

# settings.json also holds the operator's own permissions and hooks. An install used
# to copy the example over it and throw those away; it must merge, and so must remove.
SET="$WS/.claude/settings.json"
printf '{"permissions":{"allow":["Bash(echo hi)"]},"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo mine"}]}]}}\n' > "$SET"
check "install merges into an existing settings file" ws hooks install
contains "$SET" "Bash(echo hi)" "install keeps the operator's permissions"
contains "$SET" "echo mine" "install keeps the operator's own hooks"
contains "$SET" "ws_activity.py hook" "install wires the activity hook"
check "a second install refreshes" ws hooks install
equals "$(grep -o 'ws agent auto in' "$SET" | wc -l | tr -d ' ')" "1" "a refresh does not duplicate our hooks"
STATUS="$(ws hooks status 2>&1)"
printf '%s' "$STATUS" | grep -q 'agent activity hooks: installed' \
  && ok "status reports the activity hooks" || bad "status reports the activity hooks" "$STATUS"
check "remove takes only ours out" ws hooks remove
exists "$SET" "the file stays while it holds the operator's settings"
lacks "$SET" "ws agent auto" "remove takes the clock hooks out"
lacks "$SET" "ws_activity.py" "remove takes the activity hooks out"
contains "$SET" "Bash(echo hi)" "remove keeps the permissions"
contains "$SET" "echo mine" "remove keeps the operator's own hooks"
rm -f "$SET"

section "agent activity for the desk"
# The desk shows what each agent is doing from one small record per session. It holds
# names only, and a hook that cannot use an event must exit 0 and write nothing.
ACT="$WS/.local/agent/activity"
check_fails "activity without a project is refused" env WS_SESSION_ID=actnone "$WS/.agents/bin/ws" agent activity reading
WS_SESSION_ID=actsess check "a session binds for activity" ws session bind api
WS_SESSION_ID=actsess check "ws agent activity records a state" ws agent activity reading Read
exists "$ACT/actsess.json" "one record per session"
contains "$ACT/actsess.json" '"state": "reading"' "the record holds the state"
contains "$ACT/actsess.json" '"project": "api"' "the record holds the bound project"
WS_SESSION_ID=actsess check_fails "an unknown state is refused" ws agent activity dancing
WS_SESSION_ID=actsess check "ws agent activity off" ws agent activity off
not_exists "$ACT/actsess.json" "off removes the record"

hook() { (cd "$WS" && printf '%s' "$2" | env CLAUDE_CODE_SESSION_ID="$1" python3 "$WS/.agents/bin/ws_activity.py" hook .); }
WS_SESSION_ID=hooksess check "a hook session binds" ws session bind api
check "a tool call is a pose" hook hooksess '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"new_string":"SECRET-INPUT"}}'
contains "$ACT/hooksess.json" '"state": "typing"' "Edit is typing"
contains "$ACT/hooksess.json" '"detail": "Edit"' "the detail is the tool name"
lacks "$ACT/hooksess.json" "SECRET-INPUT" "a tool's input never reaches the record"
check "a notification raises a hand" hook hooksess '{"hook_event_name":"Notification","message":"Claude needs your permission to use Bash"}'
contains "$ACT/hooksess.json" '"state": "waiting"' "a notification is waiting"
check "a prompt is thinking" hook hooksess '{"hook_event_name":"UserPromptSubmit","prompt":"PRIVATE-PROMPT"}'
lacks "$ACT/hooksess.json" "PRIVATE-PROMPT" "a prompt never reaches the record"
check "malformed input is ignored, not an error" hook hooksess 'not json'
contains "$ACT/hooksess.json" '"state": "thinking"' "malformed input leaves the record alone"
check "session end" hook hooksess '{"hook_event_name":"SessionEnd"}'
not_exists "$ACT/hooksess.json" "session end removes the record"
check "an unbound session at the root" hook loosesess '{"hook_event_name":"PreToolUse","tool_name":"Read"}'
not_exists "$ACT/loosesess.json" "no project, no record"
check "an unbound session inside a product repo" hook cwdsess "{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Read\",\"cwd\":\"$PROD\"}"
contains "$ACT/cwdsess.json" '"project": "api"' "the project comes from the registry folder"
WS_SESSION_ID=actsess ws session clear >/dev/null 2>&1; WS_SESSION_ID=hooksess ws session clear >/dev/null 2>&1

section "notes"
# A note is the one thing the desk writes first, so its file name, its content, and its
# refusals are fixed here; the desk only ever calls this command.
NOTES="$WS/context/memory/projects/api/notes"
TODAY="$(date +%F)"
OUT="$(ws note api "First idea" "Try a CSV first." 2>&1)"
exists "$NOTES/$TODAY-first-idea.md" "ws note writes notes/<date>-<slug>.md"
printf '%s' "$OUT" | grep -q "^note context/memory/projects/api/notes/$TODAY-first-idea.md$" \
  && ok "it prints the note's path" || bad "it prints the note's path" "$OUT"
contains "$NOTES/$TODAY-first-idea.md" "# First idea" "the title is the heading"
contains "$NOTES/$TODAY-first-idea.md" "Try a CSV first." "the body follows"
contains "$NOTES/$TODAY-first-idea.md" "<!-- ws note " "who and when stay out of the rendered note"
check "the same title again" ws note api "First idea" "second"
exists "$NOTES/$TODAY-first-idea-2.md" "a second note never overwrites the first"
check "a body from stdin" sh -c 'printf "line one\nline two\n" | "$1" note api "Multi line" -' _ "$WS/.agents/bin/ws"
contains "$NOTES/$TODAY-multi-line.md" "line two" "stdin keeps every line"
check "a title is one line" ws note api "$(printf 'Split\ntitle')"
contains "$NOTES/$TODAY-split-title.md" "# Split title" "line breaks in a title become spaces"
check_fails "an unknown project is refused" ws note nosuch "x"
check_fails "an invalid key is refused" ws note "../api" "x"
check_fails "an empty title is refused" ws note api "   "
check_fails "a fourth argument is refused" ws note api "t" "b" "extra"

section "operator tasks"
# The desk's second write. A task is the operator's, not a run's: a run's plan rows stay
# with its owner. A status change carries the revision the desk read, so two editors
# cannot silently overwrite each other.
TASKS="$WS/context/tasks/api"
OUT="$(ws task add api "Write the export" --priority high 2>&1)"
printf '%s' "$OUT" | grep -q '^task task_write_the_export backlog mtime:' \
  && ok "ws task add prints the id, status, and revision" || bad "ws task add prints the id, status, and revision" "$OUT"
exists "$TASKS/task_write_the_export.md" "the task is a file under tasks/<key>/"
contains "$TASKS/task_write_the_export.md" "priority: high" "the priority is kept"
contains "$TASKS/task_write_the_export.md" "status: backlog" "a new task starts in backlog"
check "the same title again" ws task add api "Write the export"
exists "$TASKS/task_write_the_export_2.md" "a second task never overwrites the first"
check "a body from stdin" sh -c 'printf "Details here\n" | "$1" task add api "With body" -' _ "$WS/.agents/bin/ws"
contains "$TASKS/task_with_body.md" "Details here" "stdin becomes the body"
LIST="$(ws task list api 2>&1)"
printf '%s' "$LIST" | grep -q "task_write_the_export	backlog	high	Write the export" \
  && ok "ws task list shows id, status, priority, title" || bad "ws task list shows id, status, priority, title" "$LIST"
REV="$(printf '%s' "$OUT" | awk '{print $4}')"
check "a status change with the revision it read" ws task status api task_write_the_export in_progress --revision "$REV"
contains "$TASKS/task_write_the_export.md" "status: in_progress" "the status changed"
check_fails "a stale revision is refused" ws task status api task_write_the_export done --revision "$REV"
contains "$TASKS/task_write_the_export.md" "status: in_progress" "a refused change leaves the task alone"
check "a status change without a revision" ws task status api task_write_the_export done
check_fails "an unknown status is refused" ws task status api task_write_the_export finished
check_fails "an unknown task is refused" ws task status api task_nope done
check_fails "an unknown priority is refused" ws task add api "x" --priority extreme
check_fails "an unknown project is refused" ws task add nosuch "x"
check_fails "an empty title is refused" ws task add api "   "
# A blocker is part of the task, with its reason, so the desk can show what holds what.
check_fails "blocking without a reason is refused" ws task block api task_write_the_export "  "
check "a task is blocked with a reason" ws task block api task_write_the_export "waits on the vendor API"
contains "$TASKS/task_write_the_export.md" "blocked: true" "the task is marked blocked"
contains "$TASKS/task_write_the_export.md" 'blocked_reason: "waits on the vendor API"' "the reason is kept"
LIST="$(ws task list api 2>&1)"
printf '%s' "$LIST" | grep -q "task_write_the_export.*\[blocked\] waits on the vendor API" \
  && ok "ws task list shows the blocker" || bad "ws task list shows the blocker" "$LIST"
check_fails "a stale revision cannot unblock" ws task unblock api task_write_the_export --revision "mtime:1:size:1"
check "unblocking" ws task unblock api task_write_the_export
contains "$TASKS/task_write_the_export.md" "blocked: false" "the task is free again"

# Project management fields (ADR-0024): written as schema 2, every change in the activity.
contains "$TASKS/task_write_the_export.md" "schema_version: 2" "a changed task is written as schema 2"
contains "$TASKS/task_write_the_export.md" "status in_progress -> done" "the status change is in the activity"
check "a milestone with a due date" ws task add api "Release one" --kind milestone --due 2026-11-30
check "a task with a due date, an assignee, labels, and a parent" \
  ws task add api "Ship the importer" --due 2026-11-20 --assignee agent:claude --label import --label data --parent task_release_one
contains "$TASKS/task_ship_the_importer.md" "assignee: agent:claude" "the assignee is kept"
contains "$TASKS/task_ship_the_importer.md" "parent: task_release_one" "the parent is kept"
check_fails "a parent that does not exist is refused" ws task add api "Orphan" --parent task_nope
check_fails "an invalid due date is refused" ws task add api "Bad date" --due 2026-02-30
check "an edit sets fields and adds checklist items" \
  ws task edit api task_ship_the_importer --priority urgent --due none --check-add "Parse rows" --check-add "Report errors"
contains "$TASKS/task_ship_the_importer.md" "[ ] Report errors" "checklist items are in the body"
check "a checklist item is checked by number" ws task check api task_ship_the_importer 2
contains "$TASKS/task_ship_the_importer.md" "[x] Report errors" "the item is checked"
check_fails "a checklist number past the end is refused" ws task check api task_ship_the_importer 9
check "a comment" ws task comment api task_ship_the_importer "Rows arrive in batches"
contains "$TASKS/task_ship_the_importer.md" "Rows arrive in batches" "the comment is in the activity"
check_fails "an edit that changes nothing is refused" ws task edit api task_ship_the_importer --priority urgent
SHOW="$(ws task show api task_ship_the_importer --json 2>&1)"
printf '%s' "$SHOW" | grep -q '"priority": "urgent"' && printf '%s' "$SHOW" | grep -q '"text": "Rows arrive in batches"' \
  && ok "ws task show --json carries fields and activity" || bad "ws task show --json carries fields and activity" "$SHOW"
ALL="$(ws task list --all --label import --json 2>&1)"
printf '%s' "$ALL" | grep -q '"id": "task_ship_the_importer"' && ! printf '%s' "$ALL" | grep -q '"id": "task_with_body"' \
  && ok "ws task list --all filters across projects" || bad "ws task list --all filters across projects" "$ALL"
# Work that belongs to a client, reminders, and recurring work (ADR-0024).
check "a client's own task" ws task add @acme "Send the monthly report" --due 2026-10-31 --recur monthly
exists "$WS/context/clients/acme/tasks/task_send_the_monthly_report.md" "it lives with the client"
check_fails "an unknown client is refused" ws task add @nosuch "x"
OUT="$(ws task status @acme task_send_the_monthly_report done 2>&1)"
printf '%s' "$OUT" | grep -q '^next task_send_the_monthly_report_2 backlog' \
  && ok "finishing recurring work prints its next occurrence" || bad "finishing recurring work prints its next occurrence" "$OUT"
contains "$WS/context/clients/acme/tasks/task_send_the_monthly_report_2.md" "due: 2026-11-30" "the next one is due a month later"
check "a reminder" ws remind api "Call about phase 2" --at "2026-10-20 14:00"
contains "$TASKS/task_call_about_phase_2.md" "kind: reminder" "a reminder is a task of kind reminder"
contains "$TASKS/task_call_about_phase_2.md" "remind_at: 2026-10-20T14:00" "it keeps its time"
check_fails "a reminder without a time is refused" ws remind api "No time"
ACME="$(ws task list --all --client acme --json 2>&1)"
printf '%s' "$ACME" | grep -q '"scope": "@acme"' && printf '%s' "$ACME" | grep -q '"scope": "api"' \
  && ! printf '%s' "$ACME" | grep -q '"scope": "otherp"' \
  && ok "--client keeps the client's tasks and its projects' tasks" || bad "--client keeps the client's tasks and its projects' tasks" "$ACME"
# Today and alerts are computed from the same records (ADR-0024).
check "a task that is late" ws task add api "Late report" --due 2020-01-02
TODAY="$(ws today --json 2>&1)"
printf '%s' "$TODAY" | grep -q '"id": "overdue:api:task_late_report"' \
  && ok "ws today lists overdue work" || bad "ws today lists overdue work" "$TODAY"
check "ws today prints a summary" ws today
check "an alert is snoozed" ws alerts snooze overdue:api:task_late_report --for 1d
exists "$WS/.local/pm/snoozes.json" "snoozes stay on this machine, in .local/"
ALERTS="$(ws alerts --json 2>&1)"
! printf '%s' "$ALERTS" | grep -q 'overdue:api:task_late_report' \
  && ok "a snoozed alert is hidden" || bad "a snoozed alert is hidden" "$ALERTS"
ws alerts --all --json 2>&1 | grep -q 'overdue:api:task_late_report' \
  && ok "--all shows snoozed alerts" || bad "--all shows snoozed alerts" "$(ws alerts --all --json 2>&1)"
check_fails "a malformed alert id is refused" ws alerts snooze "not an id" --for 1d
check_fails "a snooze needs a length or --off" ws alerts snooze overdue:api:task_late_report
# A client's dossier, and records that never reach an agent (ADR-0024).
check "an interaction is logged" ws client log acme "Call: agreed the phase 2 scope"
contains "$WS/context/clients/acme/log.md" "agreed the phase 2 scope" "the log is the client's"
check_fails "an interaction for an unknown client is refused" ws client log nosuch "x"
printf 'RESTRICTED_CONTACT_CANARY\n' >> "$WS/context/clients/acme/contacts.md"
printf 'RESTRICTED_RATE_CANARY\n' >> "$WS/context/clients/acme/commercial.md"
DOSSIER="$(ws client show acme --json 2>&1)"
printf '%s' "$DOSSIER" | grep -q '"contacts": true' && printf '%s' "$DOSSIER" | grep -q 'agreed the phase 2 scope' \
  && ok "ws client show carries the log and says which restricted records exist" || bad "ws client show carries the log and says which restricted records exist" "$DOSSIER"
! printf '%s' "$DOSSIER$(ws client show acme 2>&1)" | grep -q 'CANARY' \
  && ok "ws client show never prints a restricted record" || bad "ws client show never prints a restricted record" "$DOSSIER"
WS_SESSION_ID=restricted ws session bind api >/dev/null 2>&1
lacks "$WS/.local/sessions/restricted/pack.json" "clients/acme/contacts.md" "the session pack never lists contacts.md"
lacks "$WS/.local/sessions/restricted/pack.json" "clients/acme/commercial.md" "the session pack never lists commercial.md"
lacks "$WS/.local/sessions/restricted/pack.json" "CANARY" "the session pack carries no restricted record"
lacks "$WS/.local/sessions/restricted/CONTEXT.md" "CANARY" "CONTEXT.md carries no restricted record"

section "run plans"
# A plan row changes only through its run's owner - or the person that owner is, at the
# desk, with --operator - and the run rules hold: one row in progress, a reason for a
# blocked or dropped row, and a refused change when the plan moved since it was read.
RUNP="$(ws run api "plan edits" 2>&1 | grep -o 'context/runs/api/[^ ]*' | head -1)"
PRUN="$(basename "$RUNP")"
PLANF="$WS/$RUNP/plan.md"
printf '# Plan\n\n| # | Task | Status | Notes |\n|---|---|---|---|\n| 1 | Write the parser | `pending` | |\n| 2 | Wire the route | `pending` | |\n' > "$PLANF"
check "the owner starts a row" ws plan status api "$PRUN" 1 in_progress
contains "$PLANF" '| 1 | Write the parser | `in_progress` |' "the row shows its new status"
check_fails "a second row in progress is refused" ws plan status api "$PRUN" 2 in_progress
check_fails "blocked without a reason is refused" ws plan status api "$PRUN" 2 blocked
check "blocked with a reason" ws plan status api "$PRUN" 2 blocked --notes "waits on the API"
contains "$PLANF" '| 2 | Wire the route | `blocked` | waits on the API |' "the reason is in Notes"
OUT="$(ws plan status api "$PRUN" 1 done 2>&1)"
REV="$(printf '%s' "$OUT" | awk '{print $5}')"
printf '%s' "$OUT" | grep -q "^plan $PRUN 1 done mtime:" \
  && ok "ws plan status prints run, row, status, and revision" || bad "ws plan status prints run, row, status, and revision" "$OUT"
check_fails "a stale revision is refused" ws plan status api "$PRUN" 1 pending --revision "mtime:1:size:1"
check "the revision just read is accepted" ws plan status api "$PRUN" 1 pending --revision "$REV"
check_fails "another tool of the same person is refused" env WS_AGENT=othertool "$WS/.agents/bin/ws" plan status api "$PRUN" 1 done
check "the same person as operator" env WS_AGENT=othertool "$WS/.agents/bin/ws" plan status api "$PRUN" 1 done --operator
check_fails "another person, even as operator" env WS_USER=someone "$WS/.agents/bin/ws" plan status api "$PRUN" 1 pending --operator
check_fails "an unknown row is refused" ws plan status api "$PRUN" 9 done
check_fails "an unknown status is refused" ws plan status api "$PRUN" 1 finished
check_fails "an invalid run id is refused" ws plan status api "../x" 1 done
SHOW="$(ws plan show api "$PRUN" 2>&1)"
printf '%s' "$SHOW" | grep -q "^1	done	Write the parser" \
  && ok "ws plan show lists row, status, task" || bad "ws plan show lists row, status, task" "$SHOW"

section "ws chat starts the desk and its Agent-Brain gateway"
# One command for the desk: rebuild when the UI changed, start the gateway the brain
# endpoint names when it is down, and stop that gateway when the desk stops.
FAKEHOST="$TMP/fake-agent-control"
mkdir -p "$FAKEHOST/node_modules" "$FAKEHOST/dist" "$FAKEHOST/src"
# The host runs for a moment, like a real server: the gateway it outlives must get going first.
printf '{"name":"fake-host","private":true,"scripts":{"start":"sleep 1 && echo HOST_STARTED","build":"echo HOST_BUILT && touch dist/index.html"}}\n' > "$FAKEHOST/package.json"
touch "$FAKEHOST/index.html" "$FAKEHOST/src/app.tsx"
sleep 1; touch "$FAKEHOST/dist/index.html"
FAKEBIN="$TMP/fake-brain-bin"; mkdir -p "$FAKEBIN"
printf '#!/bin/sh\necho "$@" > "$BRAIN_ARGS"\necho $$ > "$BRAIN_PID"\nexec sleep 30\n' > "$FAKEBIN/brain"; chmod +x "$FAKEBIN/brain"
mkdir -p "$WS/.local/agent"
printf '{"endpoints":{"brain":{"protocol":"openai-chat","baseUrl":"http://127.0.0.1:59871/v1","models":["m"]}}}\n' > "$WS/.local/agent/endpoints.json"
chat() { (cd "$WS" && WS_AGENT_CONTROL_DIR="$FAKEHOST" BRAIN_ARGS="$TMP/brain.args" BRAIN_PID="$TMP/brain.pid" PATH="$FAKEBIN:$PATH" "$WS/.agents/bin/ws" chat "$@" 2>&1); }
if command -v node >/dev/null && command -v npm >/dev/null; then
  OUT="$(chat)"
  printf '%s' "$OUT" | grep -q HOST_STARTED && ok "ws chat starts the agent host" || bad "ws chat starts the agent host" "$OUT"
  printf '%s' "$OUT" | grep -q HOST_BUILT && bad "a current build is not rebuilt" "$OUT" || ok "a current build is not rebuilt"
  contains "$TMP/brain.args" "serve --cloud-only --port 59871" "the gateway starts on the brain endpoint's port"
  sleep 1
  kill -0 "$(cat "$TMP/brain.pid")" 2>/dev/null && bad "the gateway stops with the desk" || ok "the gateway stops with the desk"
  rm -f "$TMP/brain.args"
  OUT="$(chat --no-brain)"
  not_exists "$TMP/brain.args" "--no-brain leaves the gateway alone"
  sleep 1; touch "$FAKEHOST/src/app.tsx"
  OUT="$(chat --no-brain)"
  printf '%s' "$OUT" | grep -q HOST_BUILT && ok "a changed UI source triggers a rebuild" || bad "a changed UI source triggers a rebuild" "$OUT"
else
  ok "ws chat cases skipped: node and npm are not installed"
fi
rm -f "$WS/.local/agent/endpoints.json"

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
check "ws route accepts the framework key" ws route --project workspace "debugging the workspace CLI"
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
M="$(date +%Y-%m)"
# The agent host writes its own records under .local/agent/usage/ (ADR-0021): the
# workspace's own data, read with or without an external tool's source.
AGU="$WS/.local/agent/usage"; mkdir -p "$AGU"
agent_usage() {
  printf '{"tool":"agent-control","endpoint":"mock","model":"echo","projectRoot":"%s","end":"%sT03:00:00Z","tokens":{"input":7,"output":8,"cacheRead":0,"cacheWrite":0}}\n' \
    "$PROD" "$(date +%Y-%m-%d)" > "$AGU/$M.jsonl"
}
agent_usage
OUT="$(ws usage --project api 2>&1)"
printf '%s' "$OUT" | grep -q 'agent-control=1' \
  && ok "ws usage reads the agent host's records with no external source" \
  || bad "ws usage reads the agent host's records with no external source" "$OUT"
rm -f "$AGU/$M.jsonl"
USRC="$TMP/fake-agent-ops"
mkdir -p "$USRC/ops/usage"
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
agent_usage
OUT="$(ws usage --project api 2>&1)"
printf '%s' "$OUT" | grep -qE '^TOTAL +2 +107 ' \
  && ok "agent host records add to the external source's, not replace them" \
  || bad "agent host records add to the external source's, not replace them" "$OUT"
rm -f "$AGU/$M.jsonl"

section "ws usage: cache hit rate and the heaviest sessions"
# api2's own root (record "b" above) gets three more records, clean enough to
# check exact arithmetic rather than tolerate float rounding: a 900/90/10 split
# across cacheRead gives every total and every percentage a single right answer.
cat >> "$USRC/ops/usage/$M.jsonl" <<EOF
{"id":"hvy-big","tool":"claude-code","projectRoot":"$WS/projects/acme/api2","end":"$(date +%Y-%m-%d)T03:00:00Z","tokens":{"input":100,"output":10,"cacheRead":900,"cacheWrite":0}}
{"id":"hvy-mid","tool":"claude-code","projectRoot":"$WS/projects/acme/api2","end":"$(date +%Y-%m-%d)T03:00:00Z","tokens":{"input":10,"output":5,"cacheRead":90,"cacheWrite":0}}
{"id":"hvy-low","tool":"codex","projectRoot":"$WS/projects/acme/api2","end":"$(date +%Y-%m-%d)T03:00:00Z","tokens":{"input":90,"output":5,"cacheRead":10,"cacheWrite":0}}
EOF
OUT="$(ws usage --project api2 2>&1)"
printf '%s' "$OUT" | grep -q 'cache hit: 83% (cacheRead=1000 cacheWrite=0)' \
  && ok "ws usage reports the scope's overall cache-hit rate" \
  || bad "ws usage reports the scope's overall cache-hit rate" "$OUT"
printf '%s' "$OUT" | grep -qE '^claude-code *2 *110 *990 *0 *15 *90%' \
  && ok "per-tool breakdown sums cache read/write and its own hit rate" \
  || bad "per-tool breakdown sums cache read/write and its own hit rate" "$OUT"
printf '%s' "$OUT" | grep -qE '^codex *1 *90 *10 *0 *5 *10%' \
  && ok "a second tool in the same scope gets its own row, not merged with the first" \
  || bad "a second tool in the same scope gets its own row, not merged with the first" "$OUT"
BIG_LINE="$(printf '%s' "$OUT" | grep -n 'hvy-big' | cut -d: -f1)"
MID_LINE="$(printf '%s' "$OUT" | grep -n 'hvy-mid' | cut -d: -f1)"
LOW_LINE="$(printf '%s' "$OUT" | grep -n 'hvy-low' | cut -d: -f1)"
[ -n "$BIG_LINE" ] && [ -n "$MID_LINE" ] && [ -n "$LOW_LINE" ] \
  && [ "$BIG_LINE" -lt "$MID_LINE" ] && [ "$MID_LINE" -lt "$LOW_LINE" ] \
  && ok "heaviest sessions are listed biggest cache-read first" \
  || bad "heaviest sessions are listed biggest cache-read first" "$OUT"

OUT="$(ws usage --project api 2>&1)"
printf '%s' "$OUT" | grep -q 'hvy-big' \
  && bad "another project's heavy session leaked into this scope" "$OUT" \
  || ok "the heaviest-sessions list is scoped like everything else"

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

# context-pack (ws_state.py) refuses any single file over 32 KiB; doctor should
# say so before ws session bind does, and only warn, not fail, on the way there.
cp "$WS/context/memory/projects/api/active.md" "$TMP/active.bak"
python3 -c "print('x' * 20000)" > "$WS/context/memory/projects/api/active.md"
DOC="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$DOC" | grep -q "past half the 32 KiB pack limit" \
  && ok "doctor warns when a project's memory file nears the pack limit" \
  || bad "doctor warns when a project's memory file nears the pack limit" "$DOC"
check "a near-limit memory file is a warning, not a doctor failure" ws doctor --ci

python3 -c "print('x' * 40000)" > "$WS/context/memory/projects/api/active.md"
check_fails "doctor fails once a memory file is over the 32 KiB pack limit" ws doctor --ci
DOC="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$DOC" | grep -q "over the 32 KiB pack limit.*ws session bind api will fail" \
  && ok "doctor says bind will fail, and names ws compact memory as the fix" \
  || bad "doctor says bind will fail, and names ws compact memory as the fix" "$DOC"
cp "$TMP/active.bak" "$WS/context/memory/projects/api/active.md"

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
# Unstage as well: checkout alone restores the file from the index, which still
# holds the planted line, and every later commit in this workspace would carry it.
git -C "$WS" reset -q HEAD -- .agents/standards/core/git-workflow.md 2>/dev/null || true
git -C "$WS" checkout -- .agents/standards/core/git-workflow.md 2>/dev/null || true
rm -f "$WS/context/public-identifiers"

section "agent identity and run keys"
# A tool started from another agent's terminal inherits that agent's markers;
# only an explicit WS_AGENT says which tool is actually running.
OUT="$(CLAUDECODE=1 WS_AGENT=kilo ws run api "explicit agent wins" 2>&1)"
printf '%s' "$OUT" | grep -q -- '-kilo-explicit-agent-wins' \
  && ok "WS_AGENT wins over an inherited tool marker" \
  || bad "WS_AGENT wins over an inherited tool marker" "$OUT"
OUT="$(cd "$WS" && unset WS_AGENT && GEMINI_CLI=1 ./.agents/bin/ws run api "gemini detected" 2>&1)"
printf '%s' "$OUT" | grep -q -- '-gemini-gemini-detected' \
  && ok "Gemini CLI is recognised by the variable it documents" \
  || bad "Gemini CLI is recognised by the variable it documents" "$OUT"
OUT="$(cd "$WS" && unset WS_AGENT && ./.agents/bin/ws run api "who am i" 2>&1)"
printf '%s' "$OUT" | grep -q 'WS_AGENT' \
  && ok "an unidentified agent is told which variable to set" \
  || bad "an unidentified agent is told which variable to set" "$OUT"
# Claude Code exports CLAUDE_CODE_SESSION_ID; reading only CLAUDE_SESSION_ID put
# every Claude session on the shared `default` clock.
(cd "$WS" && CLAUDE_CODE_SESSION_ID=Code-Session-1 ./.agents/bin/ws session bind api >/dev/null 2>&1)
exists "$WS/.local/sessions/code-session-1/bind" "Claude Code's own session id names the session"
(cd "$WS" && CLAUDE_CODE_SESSION_ID=Code-Session-1 ./.agents/bin/ws session clear >/dev/null 2>&1) || true
# A hand-made memory folder used to be enough for a run under any key.
mkdir -p "$WS/context/memory/projects/acme"
check_fails "ws run refuses a client key, even with a memory folder" ws run acme "keyed by client"
check_fails "ws run refuses a group key" ws run platform "keyed by group"
not_exists "$WS/context/runs/acme" "no run folder is left under a client key"
rmdir "$WS/context/memory/projects/acme"
check "ws run accepts the framework key" ws run workspace "framework work"

section "the framework key binds like a project"
# Framework work is keyed `workspace` and has no registry row. ws run accepted it, but
# a bind died with "unknown project" - and ws agent start died with it, after the
# worktree, lock, and clock already existed.
printf '# workspace - active\n\nFRAMEWORK_MEMORY_CANARY\n' \
  > "$WS/context/memory/projects/workspace/active.md"
WS_SESSION_ID=fwbind check "ws session bind accepts the framework key" ws session bind workspace
contains "$WS/.local/sessions/fwbind/bind" "project=workspace" "the bind records the framework key"
contains "$WS/.local/sessions/fwbind/bind" "scope=framework" "the bind scope says framework"
contains "$WS/.local/sessions/fwbind/pack.json" "FRAMEWORK_MEMORY_CANARY" \
  "the framework pack holds the framework's own memory"
lacks "$WS/.local/sessions/fwbind/pack.json" "clients/" "the framework pack holds no client material"
lacks "$WS/.local/sessions/fwbind/pack.json" "SIBLING_SESSION_CANARY" \
  "the framework pack holds no project's memory"
check "ws context pack accepts the framework key" ws context pack workspace
FW_RUN="$(ls "$WS/context/runs/workspace" | head -1)"
WS_SESSION_ID=fwbind check "the framework key binds with --run" ws session bind workspace --run "$FW_RUN"
contains "$WS/.local/sessions/fwbind/pack.json" "runs/workspace/$FW_RUN/brief.md" \
  "the framework pack includes its run brief"
WS_SESSION_ID=fwstart check "ws agent start completes for the framework key" \
  ws agent start workspace "framework"
exists "$WS/.local/sessions/fwstart/bind" "ws agent start bound the framework key"
exists "$WS/.local/worktrees/workspace/fwstart/.git" "the framework worktree exists"
WS_SESSION_ID=fwstart check "ws agent stop closes the framework session" ws agent stop

section "checkpoint commits only this agent's context work"
(cd "$WS" && WS_AGENT=otheragent ./.agents/bin/ws run otherp "someone elses run" >/dev/null 2>&1)
ws run otherp "my own run" >/dev/null 2>&1
printf 'unrelated\n' > "$WS/context/memory/projects/api/unrelated.md"
git -C "$WS/context" add memory/projects/api/unrelated.md
check "ws checkpoint commits the caller's work" ws checkpoint otherp -m "checkpoint test"
CP="$(git -C "$WS/context" show --name-only --format= HEAD)"
printf '%s' "$CP" | grep -q -- '-tester-testagent-my-own-run/' \
  && ok "the checkpoint holds the caller's run" || bad "the checkpoint holds the caller's run" "$CP"
printf '%s' "$CP" | grep -q -- 'otheragent' \
  && bad "another agent's run stays out of the checkpoint" "$CP" || ok "another agent's run stays out of the checkpoint"
printf '%s' "$CP" | grep -q 'unrelated.md' \
  && bad "another project's staged file stays out" "$CP" || ok "another project's staged file stays out"
git -C "$WS/context" diff --cached --name-only | grep -q 'unrelated.md' \
  && ok "and it is still staged afterwards" || bad "and it is still staged afterwards"
OUT="$(ws checkpoint otherp 2>&1)"
printf '%s' "$OUT" | grep -q 'nothing changed' \
  && ok "a checkpoint with nothing new is a no-op" || bad "a checkpoint with nothing new is a no-op" "$OUT"
git -C "$WS/context" reset -q HEAD memory/projects/api/unrelated.md
rm -f "$WS/context/memory/projects/api/unrelated.md"

# The owner pattern is human + tool, so it also matched every other session of the
# same tool: two sessions of one agent checkpointed each other's runs.
WS_SESSION_ID=cpa ws run otherp "session a run" >/dev/null 2>&1
WS_SESSION_ID=cpb ws run otherp "session b run" >/dev/null 2>&1
WS_SESSION_ID=cpa check "a named session checkpoints" ws checkpoint otherp -m "session a"
CP="$(git -C "$WS/context" show --name-only --format= HEAD)"
printf '%s' "$CP" | grep -q -- '-session-a-run/' \
  && ok "the checkpoint holds this session's run" || bad "the checkpoint holds this session's run" "$CP"
printf '%s' "$CP" | grep -q -- '-session-b-run/' \
  && bad "another session of the same tool keeps its run" "$CP" \
  || ok "another session of the same tool keeps its run"
# Shared memory files: another agent clocked in on the project may be half-way through
# an edit, and a checkpoint would publish it under this agent's name.
RA="$(ls "$WS/context/runs/otherp" | grep -- '-session-a-run$')"
WS_SESSION_ID=cpb ws agent in otherp "editing memory" >/dev/null 2>&1
printf '\nCPB_HALF_WRITTEN\n' >> "$WS/context/memory/projects/otherp/active.md"
printf 'more\n' >> "$WS/context/runs/otherp/$RA/plan.md"
OUT="$(WS_SESSION_ID=cpa ws checkpoint otherp -m 'while b works' 2>&1)"
CP="$(git -C "$WS/context" show --name-only --format= HEAD)"
printf '%s' "$CP" | grep -q "runs/otherp/$RA/plan.md" \
  && ok "this session's run is still checkpointed" || bad "this session's run is still checkpointed" "$CP"
printf '%s' "$CP" | grep -q 'memory/projects/otherp/active.md' \
  && bad "memory another agent may be editing stays out" "$CP" \
  || ok "memory another agent may be editing stays out"
printf '%s' "$OUT" | grep -q 'another agent' \
  && ok "the checkpoint says why memory was left" || bad "the checkpoint says why memory was left" "$OUT"
WS_SESSION_ID=cpb ws agent out >/dev/null 2>&1
WS_SESSION_ID=cpa check "with no other agent on the project, memory is checkpointed" \
  ws checkpoint otherp -m "memory"
CP="$(git -C "$WS/context" show --name-only --format= HEAD)"
printf '%s' "$CP" | grep -q 'memory/projects/otherp/active.md' \
  && ok "the memory file is in that checkpoint" || bad "the memory file is in that checkpoint" "$CP"
# One session can hold two clocks - one from `ws agent start` under its tool name, one
# from the editor hook under the editor's - and it is still one agent.
WS_SESSION_ID=cpa WS_AGENT=editorhook ws agent in otherp "hook clock" >/dev/null 2>&1
printf '\nSAME_SESSION_EDIT\n' >> "$WS/context/memory/projects/otherp/active.md"
WS_SESSION_ID=cpa check "a checkpoint with a second clock of the same session" ws checkpoint otherp -m "same session"
CP="$(git -C "$WS/context" show --name-only --format= HEAD)"
printf '%s' "$CP" | grep -q 'memory/projects/otherp/active.md' \
  && ok "this session's own second clock does not hold memory back" || bad "this session's own second clock does not hold memory back" "$CP"
WS_SESSION_ID=cpa WS_AGENT=editorhook ws agent out >/dev/null 2>&1
# Operator tasks are the project's like its memory, so they are checkpointed with it.
WS_SESSION_ID=cpa ws task add otherp "Checkpoint me" >/dev/null 2>&1
WS_SESSION_ID=cpa check "a checkpoint after adding a task" ws checkpoint otherp -m "tasks"
CP="$(git -C "$WS/context" show --name-only --format= HEAD)"
printf '%s' "$CP" | grep -q 'tasks/otherp/task_checkpoint_me.md' \
  && ok "operator tasks are in the checkpoint" || bad "operator tasks are in the checkpoint" "$CP"
WS_SESSION_ID=cpa ws task add @beta "Client follow-up" >/dev/null 2>&1
WS_SESSION_ID=cpa check "a checkpoint after adding a client task" ws checkpoint otherp -m "client tasks"
CP="$(git -C "$WS/context" show --name-only --format= HEAD)"
printf '%s' "$CP" | grep -q 'clients/beta/tasks/task_client_follow_up.md' \
  && ok "the client's own tasks are checkpointed with its project" || bad "the client's own tasks are checkpointed with its project" "$CP"

section "hard rules reach every agent"
# One block, repeated in every tool's entry file: a copy that drifts is a rule
# some agent never sees. Checked against this repository itself.
CANON="$(sed -n '/<!-- hard-rules:begin -->/,/<!-- hard-rules:end -->/p' "$SRC/.agents/rules/00-hard-rules.md")"
for f in AGENTS.md GEMINI.md .github/copilot-instructions.md .cursor/rules/00-workspace.mdc; do
  [ -n "$CANON" ] && [ "$(sed -n '/<!-- hard-rules:begin -->/,/<!-- hard-rules:end -->/p' "$SRC/$f")" = "$CANON" ] \
    && ok "hard rules identical in $f" || bad "hard rules identical in $f"
done
# Antigravity silently discards an .agents/rules file without a trigger.
contains "$SRC/.agents/rules/00-hard-rules.md" "trigger: always_on" "the rules file is always on for Antigravity"
# Antigravity truncates a rule file at 24 KB; stay well under it.
SIZE="$(wc -c < "$SRC/AGENTS.md" | tr -d ' ')"
[ "$SIZE" -lt 20000 ] && ok "AGENTS.md fits every tool's rule budget ($SIZE bytes)" \
  || bad "AGENTS.md fits every tool's rule budget" "$SIZE bytes"
printf "$ALLOW" > "$WS/context/public-identifiers"
check "doctor passes with the hard rules in sync" ws doctor --ci
sed -i.bak 's/This framework repository is public/This framework repository is private/' "$WS/AGENTS.md"
check_fails "doctor fails when an entry file's hard rules drift" ws doctor --ci
mv "$WS/AGENTS.md.bak" "$WS/AGENTS.md"

section "framework guard: nothing naming a client leaves the machine"
printf "$ALLOW" | grep -v '^acme$' > "$WS/context/public-identifiers"
check "ws guard install" ws guard install
for h in pre-commit commit-msg pre-push; do
  contains "$WS/.git/hooks/$h" "ws-framework-guard" "the guard installs $h"
done
check "ws guard status reports it installed" ws guard status

printf 'generic text\n' > "$WS/guard-ok.md"; git -C "$WS" add guard-ok.md
check "a commit naming no client passes" git -C "$WS" commit -qm "docs: generic note"
printf 'plan for acme\n' > "$WS/guard-bad.md"; git -C "$WS" add guard-bad.md
check_fails "a commit whose content names a client is refused" git -C "$WS" commit -qm "docs: plan"
OUT="$(git -C "$WS" commit -qm "docs: plan" 2>&1 || true)"
printf '%s' "$OUT" | grep -q -- '--no-verify' \
  && ok "the refusal says not to bypass it" || bad "the refusal says not to bypass it" "$OUT"
git -C "$WS" rm -q --cached guard-bad.md; rm -f "$WS/guard-bad.md"
printf 'x\n' > "$WS/acme-notes.md"; git -C "$WS" add acme-notes.md
check_fails "a file whose name names a client is refused" git -C "$WS" commit -qm "docs: notes"
git -C "$WS" rm -q --cached acme-notes.md; rm -f "$WS/acme-notes.md"
printf 'generic\n' > "$WS/guard-two.md"; git -C "$WS" add guard-two.md
check_fails "a commit message naming a client is refused" git -C "$WS" commit -qm "docs: notes for acme"
check "the same change with a clean message passes" git -C "$WS" commit -qm "docs: notes"

# The push is the last line: it also catches what --no-verify let through, and
# history the tip no longer shows.
PUB="$TMP/public.git"; git init -q --bare "$PUB"; git -C "$WS" remote add pub "$PUB"
check "a clean push passes" git -C "$WS" push -q pub HEAD:refs/heads/main
printf 'acme leaked\n' > "$WS/guard-three.md"; git -C "$WS" add guard-three.md
git -C "$WS" commit -q --no-verify -m "docs: bypassed"
check_fails "a push carrying a client name is refused, even after --no-verify" \
  git -C "$WS" push -q pub HEAD:refs/heads/main
git -C "$WS" rm -q guard-three.md; git -C "$WS" commit -q --no-verify -m "docs: remove it again"
check_fails "a name added and removed before the push is still refused" \
  git -C "$WS" push -q pub HEAD:refs/heads/main
git -C "$WS" reset -q --hard refs/remotes/pub/main
check_fails "a branch whose name names a client is refused" git -C "$WS" push -q pub HEAD:refs/heads/acme-fix

# A framework worktree has no context/ of its own; the guard borrows the primary's.
WT="$WS/.local/worktrees/workspace/guard"
git -C "$WS" worktree add -q -b guard-wt "$WT" HEAD 2>/dev/null
printf 'acme in a worktree\n' > "$WT/wt-bad.md"; git -C "$WT" add wt-bad.md
check_fails "the guard in a framework worktree still knows every client" git -C "$WT" commit -qm "docs: wt"
# A hook run inside the worktree can leave an empty context/ there; it must not hide the
# primary's registry from the guard.
mkdir -p "$WT/context/works"
check_fails "an empty context folder in a worktree does not switch the guard off" git -C "$WT" commit -qm "docs: wt again"
git -C "$WS" worktree remove --force "$WT"; git -C "$WS" branch -q -D guard-wt

# Doctor reports what the guard cannot see from inside git.
git -C "$WS" worktree add -q --detach "$WS/.tool-wt" HEAD 2>/dev/null
mkdir -p "$WS/context/runs/acme/hand-made-run"
OUT="$(ws doctor 2>&1 || true)"
printf '%s' "$OUT" | grep -q 'framework guard hooks installed' \
  && ok "doctor sees the guard installed" || bad "doctor sees the guard installed" "$OUT"
printf '%s' "$OUT" | grep -q '\.tool-wt' \
  && ok "doctor names a framework worktree outside .local/worktrees" \
  || bad "doctor names a framework worktree outside .local/worktrees" "$OUT"
printf '%s' "$OUT" | grep -q 'other than a project: acme' \
  && ok "doctor names a run keyed by a client" || bad "doctor names a run keyed by a client" "$OUT"
printf '%s' "$OUT" | grep -q 'acme/hand-made-run' \
  && ok "doctor names a run folder not made by ws run" || bad "doctor names a run folder not made by ws run" "$OUT"
git -C "$WS" worktree remove --force "$WS/.tool-wt"; rm -rf "$WS/context/runs/acme"

# A project's identifiers also include its remote's own owner/org segment, and
# a client's legal/brand name from client.md - not just key/client/group/folder.
cp "$WS/context/registry.tsv" "$TMP/reg-remote.bak"
printf 'acme-upstream\tacme\t-\tprojects/acme/upstream\tgit@gitlab.com:acme-upstream-org/widget.git\tclient\t-\tfixture\t-\n' \
  >> "$WS/context/registry.tsv"
cp "$WS/context/clients/acme/client.md" "$TMP/acme-client.bak"
printf '# acme\n\n- **Full name:** Acme Widgets Corp (brand: Widgetronic)\n' > "$WS/context/clients/acme/client.md"
cp "$WS/context/clients/donwi/client.md" "$TMP/donwi-client.bak"
printf '# donwi\n\n- **Full name:** Some Operator (brand: Operatronic)\n' > "$WS/context/clients/donwi/client.md"
IDS="$(ws identifiers 2>&1)"
printf '%s' "$IDS" | grep -qx 'acme-upstream-org' \
  && ok "a project's remote owner/org becomes a guarded identifier" \
  || bad "a project's remote owner/org becomes a guarded identifier" "$IDS"
printf '%s' "$IDS" | grep -qx 'widgetronic' \
  && ok "a word from client.md's Full name becomes a guarded identifier" \
  || bad "a word from client.md's Full name becomes a guarded identifier" "$IDS"
printf '%s' "$IDS" | grep -qx 'operatronic' \
  && bad "donwi's own client.md leaked into the guarded list" "$IDS" \
  || ok "donwi's own Full name is excluded - the operator, not a protected client"

printf 'widgetronic leaked\n' > "$WS/guard-brand.md"; git -C "$WS" add guard-brand.md
check_fails "a brand word from client.md's Full name is refused" git -C "$WS" commit -qm "docs: brand"
git -C "$WS" rm -q --cached guard-brand.md; rm -f "$WS/guard-brand.md"

cp "$TMP/reg-remote.bak" "$WS/context/registry.tsv"
cp "$TMP/acme-client.bak" "$WS/context/clients/acme/client.md"
cp "$TMP/donwi-client.bak" "$WS/context/clients/donwi/client.md"

# Someone else's hook is never overwritten, and remove takes only ours.
check "ws guard remove" ws guard remove
not_exists "$WS/.git/hooks/pre-push" "remove takes the guard hooks out"
OUT="$(ws doctor 2>&1 || true)"
printf '%s' "$OUT" | grep -q 'ws guard install' \
  && ok "doctor names ws guard install when the guard is missing" \
  || bad "doctor names ws guard install when the guard is missing" "$OUT"
printf '#!/bin/sh\nexit 0\n' > "$WS/.git/hooks/pre-commit"; chmod +x "$WS/.git/hooks/pre-commit"
ws guard install >/dev/null 2>&1
lacks "$WS/.git/hooks/pre-commit" "ws-framework-guard" "a pre-commit hook that is not ours is left untouched"
rm -f "$WS/.git/hooks/pre-commit"; ws guard remove >/dev/null 2>&1
git -C "$WS" remote remove pub
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
