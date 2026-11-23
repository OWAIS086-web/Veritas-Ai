#!/usr/bin/env bash
# VERITAS AI smoke test against the running stack (through Nginx).
# Usage: scripts/smoke.sh [base_url]   (needs curl and python3)
set -uo pipefail
BASE="${1:-http://localhost:8080}"
API="$BASE/api/v1"
FAILURES=0

pass() { printf '\033[32mPASS\033[0m  %s\n' "$1"; }
fail() { printf '\033[31mFAIL\033[0m  %s: %s\n' "$1" "$2"; FAILURES=$((FAILURES + 1)); }
json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

curl -fsS "$BASE/healthz" >/dev/null && pass "nginx /healthz" || fail "nginx /healthz" "unreachable"
status=$(curl -fsS "$API/system/health" | json "d['status']") || status=error
[ "$status" = "ok" ] && pass "api health" || fail "api health" "status=$status"

SUFFIX=$(python3 -c "import uuid; print(uuid.uuid4().hex[:10])")
EMAIL="smoke-$SUFFIX@example.com"
PASSWORD="smoke-password-$SUFFIX"

reg=$(curl -fsS -X POST "$API/auth/register" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"full_name\":\"Smoke Test\",\"organization_name\":\"Smoke Org $SUFFIX\"}") \
  && pass "register" || fail "register" "request failed"
login=$(curl -fsS -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}") && pass "login" || fail "login" "request failed"
TOKEN=$(echo "$login" | json "d['access_token']")
AUTH="Authorization: Bearer $TOKEN"

role=$(curl -fsS "$API/auth/me" -H "$AUTH" | json "d['role']")
[ "$role" = "org_admin" ] && pass "auth/me" || fail "auth/me" "role=$role"

code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"wrong-password-1\"}")
[ "$code" = "401" ] && pass "wrong password is 401" || fail "wrong password is 401" "got $code"

JOB=$(curl -fsS -X POST "$API/system/ping-job" -H "$AUTH" | json "d['id']")
jstatus=queued
for _ in $(seq 1 30); do
  sleep 0.5
  jstatus=$(curl -fsS "$API/jobs/$JOB" -H "$AUTH" | json "d['status']")
  [ "$jstatus" = "succeeded" ] || [ "$jstatus" = "failed" ] && break
done
[ "$jstatus" = "succeeded" ] && pass "worker processes a real job" || fail "worker job" "status=$jstatus"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CASE=$(curl -fsS -X POST "$API/cases" -H "$AUTH" -H 'Content-Type: application/json' \
  -d "{\"title\":\"Smoke case $SUFFIX\",\"objective\":\"Smoke test\"}" | json "d['id']")
DOC=$(curl -fsS -X POST "$API/cases/$CASE/documents" -H "$AUTH" \
  -F "files=@$ROOT/sample-data/shipment-case/02_commercial_invoice.pdf" | json "d['results'][0]['document_id']")
dstatus=uploaded
for _ in $(seq 1 240); do
  sleep 1
  dstatus=$(curl -fsS "$API/documents/$DOC" -H "$AUTH" | json "d['status']")
  [ "$dstatus" = "completed" ] || [ "$dstatus" = "failed" ] && break
done
amount=$(curl -fsS "$API/documents/$DOC/extractions" -H "$AUTH" | \
  json "next(f['normalized_value']['amount'] for f in d['fields'] if f['name']=='total_amount' and f['bbox'])")
[ "$dstatus" = "completed" ] && [ "$amount" = "48000.00" ] && pass "document pipeline (USD $amount)" \
  || fail "document pipeline" "status=$dstatus amount=$amount"

JOB=$(curl -fsS -X POST "$API/cases/$CASE/documents" -H "$AUTH" \
  -F "files=@$ROOT/sample-data/shipment-case/03_customs_declaration.pdf" | json "d['job_id']")
cstatus=queued
for _ in $(seq 1 240); do
  sleep 1
  cstatus=$(curl -fsS "$API/jobs/$JOB" -H "$AUTH" | json "d['status']")
  [ "$cstatus" = "succeeded" ] || [ "$cstatus" = "failed" ] && break
done
found=$(curl -fsS "$API/cases/$CASE/findings" -H "$AUTH" | \
  json "[(f['difference'], f['evidence_count']) for f in d if f['type']=='financial_discrepancy']")
[ "$cstatus" = "succeeded" ] && [ "$found" = "[('20000.00', 2)]" ] && pass "cross-document comparison (USD 20000.00)" \
  || fail "cross-document comparison" "status=$cstatus findings=$found"

gsource=postgres
for _ in $(seq 1 90); do
  gsource=$(curl -fsS "$API/cases/$CASE/graph" -H "$AUTH" | json "d['source']")
  [ "$gsource" = "neo4j" ] && break
  sleep 1
done
contradicts=$(curl -fsS "$API/cases/$CASE/graph" -H "$AUTH" | \
  json "sum(1 for e in d['edges'] if e['type']=='CONTRADICTS' and e['finding_id'] and e['evidence_ids'])")
[ "$gsource" = "neo4j" ] && [ "$contradicts" = "1" ] && pass "evidence graph (Neo4j, 1 contradiction)" \
  || fail "evidence graph" "source=$gsource contradicts=$contradicts"

forensic=$(curl -fsS "$API/cases/$CASE/forensics" -H "$AUTH" | json "' '.join(r['document_id'] + ':' + str(r['status']) for r in d)")
fbad=0; fcount=0
for row in $forensic; do
  fcount=$((fcount + 1)); doc="${row%%:*}"
  [ "${row#*:}" = "succeeded" ] || fbad=1
  lim=$(curl -fsS "$API/documents/$doc/forensics" -H "$AUTH" | \
    json "any('does not establish document alteration' in l for l in d['limitations'])")
  [ "$lim" = "True" ] || fbad=1
done
[ "$fcount" = "2" ] && [ "$fbad" = "0" ] && pass "document forensics (2 runs with limitations)" \
  || fail "document forensics" "documents=$fcount problems=$fbad"

actions=$(curl -fsS "$API/audit-logs" -H "$AUTH" | json "' '.join(i['action'] for i in d['items'])")
case "$actions" in *auth.register*auth.login*|*auth.login*auth.register*) pass "audit log recorded the session";;
  *) fail "audit log" "$actions";; esac

if [ "$FAILURES" -gt 0 ]; then echo "$FAILURES smoke check(s) failed"; exit 1; fi
echo "All smoke checks passed"
