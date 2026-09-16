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

check "ws init writes workspace.conf" \
  ws init --org "Acme Ltd" --key acme --group "git@example.invalid:acme"
exists "$WS/workspace.conf" "workspace.conf exists"
contains "$WS/workspace.conf" "org_name  = Acme Ltd" "it records the organisation"
check "ws init is idempotent and refuses to clobber" ws init --org Other --key other --group x
contains "$WS/workspace.conf" "Acme Ltd" "a second init leaves the first alone"

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
contains "$WS/context/.gitattributes" "merge=union" "the merge strategy is actually declared"
check_fails "a second context init refuses" ws context init
git -C "$WS" add -A >/dev/null 2>&1
equals "$(git -C "$WS" ls-files context | wc -l | tr -d ' ')" "0" "context is never tracked by the framework"
check "ws web help is available" ws web --help
check "ws context sync is a no-op without a remote" ws context sync
OUT="$(ws doctor --ci 2>&1 || true)"
printf '%s' "$OUT" | grep -q "private-local" \
  && ok "doctor reports a context with no remote as private-local" \
  || bad "doctor reports a context with no remote as private-local" "$OUT"

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
equals "$(git -C "$PROD" status --porcelain | wc -l | tr -d ' ')" "0" \
  "the pointers are invisible to git status"

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
check "ws hooks remove" ws hooks remove
not_exists "$WS/.claude/settings.json" "the hooks are removed again"

section "log and route"
check "ws log appends a milestone" ws log api "did a thing"
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
printf '%s' "$OUT" | grep -qE '1\.00' && ok "the hour is counted under the client" \
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
sed -i.bak 's/^packs = .*/packs = core, nosuchpack/' "$WS/workspace.conf" && rm -f "$WS/workspace.conf.bak"
check_fails "doctor fails on a standards pack that does not exist" ws doctor --ci
cp "$TMP/conf.bak" "$WS/workspace.conf"

sed -i.bak 's/^packs = .*/packs = core/' "$WS/workspace.conf" && rm -f "$WS/workspace.conf.bak"
ws doctor >"$TMP/doctor-core-only.txt" 2>&1 || true
contains "$TMP/doctor-core-only.txt" "Java not required" "doctor does not require Java when the java pack is off"
cp "$TMP/conf.bak" "$WS/workspace.conf"

mv "$WS/.gitignore" "$TMP/gitignore.bak"
printf '/projects/*\n!/projects/README.md\n' > "$WS/.gitignore"
check_fails "doctor fails when context is no longer ignored" ws doctor --ci
mv "$TMP/gitignore.bak" "$WS/.gitignore"

git -C "$WS" add -A >/dev/null 2>&1
check "doctor passes again once each fault is undone" ws doctor --ci

# ═════════════════════════════════════════════════════════════════════════════
printf '\n'
if [ "$FAIL" -eq 0 ]; then grn "$PASS passed, 0 failed"; exit 0
else red "$PASS passed, $FAIL FAILED"; exit 1; fi
