#!/usr/bin/env bash
# Walk one dataset case through the running API with curl: login -> upload -> watch -> review -> audit -> report.
# Usage: scripts/demo_api.sh [cluster, default C_002]   (start the API first:  make api)
set -euo pipefail
API=${API:-http://localhost:8000}
CLUSTER=${1:-C_002}
DS=data/official/dataset

login() { curl -sf "$API/auth/login" -H 'content-type: application/json' -d "{\"username\":\"$1\",\"password\":\"$1-demo\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'; }
SUB=$(login submitter); REV=$(login reviewer); SEN=$(login senior); AUD=$(login auditor)
H() { echo "Authorization: Bearer $1"; }

FILES=()
for f in $(python3 - "$CLUSTER" <<'PY'
import json,sys
m=json.load(open("data/official/dataset/metadata.json"))
print(" ".join("data/official/dataset/"+x["file_path"] for x in m if x["case_cluster_id"]==sys.argv[1]))
PY
); do FILES+=(-F "files=@$f"); done

echo "== upload $(( ${#FILES[@]} / 2 )) documents of $CLUSTER"
CASE=$(curl -sf "$API/cases" -H "$(H "$SUB")" -H "Idempotency-Key: demo-$CLUSTER-$(date +%s)" "${FILES[@]}" | tee /dev/stderr | python3 -c 'import sys,json;print(json.load(sys.stdin)["case_id"])')
echo; echo "== live events (SSE) for $CASE"
curl -sN "$API/cases/$CASE/stream?token=$SUB" | python3 -c '
import sys,json
for line in sys.stdin:
    if line.startswith("data: "):
        m=json.loads(line[6:])
        print("  ", m.get("node",m["type"]), m.get("status",""), m.get("doc_id") or "")
        if m["type"]!="event": break'
echo; echo "== decision"
curl -sf "$API/cases/$CASE" -H "$(H "$SUB")" | python3 -c '
import sys,json
c=json.load(sys.stdin)
print("  status:",c["status"],"| AI decision:",c["ai_decision"],"| confidence:",c["confidence"],"| amount: $%.2f"%c["total_amount"])
for d in c["decision"]["documents"]: print("   %-24s %-9s %s"%(d["doc_id"],d["decision"],d["rule_id"]))
print("  justification:",c["decision"]["justification"])'
STATUS=$(curl -sf "$API/cases/$CASE" -H "$(H "$SUB")" | python3 -c 'import sys,json;print(json.load(sys.stdin)["status"])')
if [ "$STATUS" = "IN_REVIEW" ]; then
  echo; echo "== reviewer overrides (high-value cases wait for a second approver)"
  OV=$(curl -sf "$API/cases/$CASE/override" -H "$(H "$REV")" -H 'content-type: application/json' \
       -d '{"decision":"APPROVE","reason_code":"ADDITIONAL_INFORMATION","note":"demo"}')
  echo "  $OV"
  ID=$(echo "$OV" | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
  if echo "$OV" | grep -q PENDING_APPROVAL; then
    echo "== senior reviewer approves"; curl -sf -X POST "$API/cases/$CASE/overrides/$ID/approve" -H "$(H "$SEN")"; echo
  fi
fi
echo; echo "== audit chain"; curl -sf "$API/audit/verify" -H "$(H "$AUD")"; echo
curl -sf "$API/cases/$CASE/report.pdf" -H "$(H "$REV")" -o "/tmp/$CASE-report.pdf" && echo "report saved: /tmp/$CASE-report.pdf"
