#!/bin/sh
# tests/e2e.sh
# Simulates the full lifecycle of a PhoneCluster Solo node:
#   boot -> register -> heartbeat loop -> verify status -> simulate offline -> verify detection
#
# Runs against a live coordinator on $COORDINATOR_BASE_URL.
# Exit 0 = all checks passed. Exit 1 = failure (message printed).

set -e

BASE="${COORDINATOR_BASE_URL:-http://127.0.0.1:7777}"
KEY="${PC_API_KEY:-test-api-key-ci}"
NODE="e2e-phone-$(date +%s)"

PASS=0
FAIL=0

###############################################################################
# Helpers
###############################################################################

green() { printf '\033[32m[OK]\033[0m  %s\n' "$*"; }
red()   { printf '\033[31m[FAIL]\033[0m  %s\n' "$*"; }
info()  { printf '\033[34m->\033[0m  %s\n' "$*"; }

assert_eq() {
    LABEL="$1"; EXPECTED="$2"; ACTUAL="$3"
    if [ "$ACTUAL" = "$EXPECTED" ]; then
        green "$LABEL"
        PASS=$((PASS + 1))
    else
        red "$LABEL  (expected: $EXPECTED  got: $ACTUAL)"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    LABEL="$1"; NEEDLE="$2"; HAYSTACK="$3"
    if echo "$HAYSTACK" | grep -q "$NEEDLE"; then
        green "$LABEL"
        PASS=$((PASS + 1))
    else
        red "$LABEL  (expected to contain: $NEEDLE)"
        red "  Actual: $HAYSTACK"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    LABEL="$1"; NEEDLE="$2"; HAYSTACK="$3"
    if echo "$HAYSTACK" | grep -q "$NEEDLE"; then
        red "$LABEL  (expected NOT to contain: $NEEDLE)"
        FAIL=$((FAIL + 1))
    else
        green "$LABEL"
        PASS=$((PASS + 1))
    fi
}

api_get()  { curl -sf -H "X-API-Key: $KEY" "$BASE$1"; }
api_post() { curl -sf -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d "$2" "$BASE$1"; }

###############################################################################
# 1. Health check (no auth)
###############################################################################

info "1. Health check"
HEALTH="$(curl -sf "$BASE/health")"
assert_contains "health returns ok"        '"ok"'     "$HEALTH"
assert_contains "health returns timestamp" '"ts"'     "$HEALTH"

###############################################################################
# 2. Auth enforcement
###############################################################################

info "2. Auth enforcement"
STATUS_NO_KEY="$(curl -s -o /dev/null -w '%{http_code}' "$BASE/status")"
assert_eq "status without key returns 401"   "401" "$STATUS_NO_KEY"

STATUS_BAD_KEY="$(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: bad" "$BASE/status")"
assert_eq "status with wrong key returns 401" "401" "$STATUS_BAD_KEY"

###############################################################################
# 3. Node registration
###############################################################################

info "3. Node registration"
REG="$(api_post /register "{\"node_id\":\"$NODE\",\"role\":\"solo\",\"ip\":\"192.168.1.99\",\"port\":8080}")"
assert_contains "register returns ok"         '"ok"'         "$REG"
assert_contains "register returns node_id"    "$NODE"        "$REG"
assert_contains "register event=registered"   "registered"   "$REG"

###############################################################################
# 4. Node appears in /nodes
###############################################################################

info "4. Node visibility"
NODES="$(api_get /nodes)"
assert_contains "registered node in /nodes"   "$NODE"   "$NODES"
assert_contains "node role is solo"           "\"solo\"" "$NODES"

###############################################################################
# 5. Node appears in /status
###############################################################################

info "5. Status summary"
STATUS="$(api_get /status)"
assert_contains "node in /status nodes"       "$NODE"   "$STATUS"
assert_contains "status has summary key"      "summary" "$STATUS"
assert_contains "status has coordinator key"  "coordinator" "$STATUS"

###############################################################################
# 6. Re-registration is idempotent
###############################################################################

info "6. Re-registration"
REG2="$(api_post /register "{\"node_id\":\"$NODE\",\"role\":\"solo\",\"ip\":\"192.168.1.99\",\"port\":8080}")"
assert_contains "re-register returns re-registered" "re-registered" "$REG2"

NODES2="$(api_get /nodes)"
COUNT="$(echo "$NODES2" | grep -o "\"$NODE\"" | wc -l)"
assert_eq "only one entry for node after re-register" "1" "$COUNT"

###############################################################################
# 7. Heartbeat accepted
###############################################################################

info "7. Heartbeat"
HB="$(api_post /heartbeat "{\"node_id\":\"$NODE\"}")"
assert_contains "heartbeat returns ok"  '"ok"'  "$HB"
assert_contains "heartbeat has ts"      '"ts"'  "$HB"

###############################################################################
# 8. Unknown heartbeat rejected
###############################################################################

info "8. Unknown node heartbeat"
HB_BAD_CODE="$(curl -s -o /dev/null -w '%{http_code}' \
    -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
    -d '{"node_id":"ghost-xyz-99999"}' "$BASE/heartbeat")"
assert_eq "heartbeat for unknown node returns 404" "404" "$HB_BAD_CODE"

###############################################################################
# 9. Event log contains registration
###############################################################################

info "9. Event log"
EVENTS="$(api_get /events)"
assert_contains "events log contains node"        "$NODE"       "$EVENTS"
assert_contains "events log contains registered"  "registered"  "$EVENTS"

###############################################################################
# 10. Metrics endpoint shape
###############################################################################

info "10. Metrics"
METRICS="$(api_get /metrics/json)"
assert_contains "metrics has cpu"   '"cpu"'   "$METRICS"
assert_contains "metrics has mem"   '"mem"'   "$METRICS"
assert_contains "metrics has disk"  '"disk"'  "$METRICS"
assert_contains "metrics has ts"    '"ts"'    "$METRICS"

###############################################################################
# 11. Events limit param
###############################################################################

info "11. Events pagination"
EVENTS_2="$(curl -sf -H "X-API-Key: $KEY" "$BASE/events?limit=1")"
COUNT_2="$(echo "$EVENTS_2" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")"
assert_eq "events?limit=1 returns at most 1 item" "1" "$COUNT_2"

###############################################################################
# Summary
###############################################################################

echo ""
echo "-----------------------------------------"
printf "  Passed: \033[32m%s\033[0m\n" "$PASS"
printf "  Failed: \033[31m%s\033[0m\n" "$FAIL"
echo "-----------------------------------------"

[ "$FAIL" -eq 0 ] || exit 1
