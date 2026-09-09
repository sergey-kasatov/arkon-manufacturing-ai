"""Contract test for the Arkon Incident Status API.

Checks the read endpoint the way the assistant will use it: parameter forms an
LLM is likely to produce, the rejection cases, and the designed failure path.
Assertions are invariants rather than snapshots of the store, so the suite stays
valid as incidents are added. Stdlib only.

Usage:
    python n8n/incident_status_probe.py
    python n8n/incident_status_probe.py http://AK2101:5678/webhook/arkon-incident-status
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://AK2101:5678/webhook/arkon-incident-status"
LIFECYCLE = ["new", "acknowledged", "in_containment", "resolved", "closed", "false_positive"]


# Call the endpoint and return (http status, parsed body)
def call(base, params):
    url = base + ("?" + urllib.parse.urlencode(params) if params else "")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"raw": raw[:200]}


# Invariants every successful answer must satisfy
def check_ok(body, params):
    problems = []
    if body.get("status") not in ("ok", "no_match"):
        problems.append("status is " + repr(body.get("status")))
    returned, matched = body.get("returned"), body.get("match_count")
    limit = body.get("query", {}).get("limit")
    if returned is None or matched is None or limit is None:
        return problems + ["response is missing returned/match_count/query.limit"]
    if returned > limit:
        problems.append(f"returned {returned} exceeds limit {limit}")
    if returned > matched:
        problems.append(f"returned {returned} exceeds match_count {matched}")
    if returned != len(body.get("incidents", [])):
        problems.append("returned does not equal the number of incident objects")
    if (matched > 0) != (body.get("status") == "ok"):
        problems.append("status does not agree with match_count")
    for incident in body.get("incidents", []):
        if "priority" in params and incident["priority"].upper() not in [
            p.strip().upper() for p in str(params["priority"]).split(",")
        ]:
            problems.append(f"{incident['incident_id']} violates the priority filter")
        # Read the status filter off the echoed query, not off the parameter: one
        # accepted value, `open`, stands for three states and the server says which.
        wanted_states = body.get("query", {}).get("status_set") or []
        if "status" in params and wanted_states and incident["status"].lower() not in wanted_states:
            problems.append(f"{incident['incident_id']} violates the status filter")
        asked_for = params.get("assigned_to") or params.get("assignee")
        if asked_for:
            held = " ".join(str(incident.get("assigned_to") or "").lower().split())
            wanted = " ".join(str(asked_for).lower().split())
            if held != wanted and wanted not in held.split(" "):
                problems.append(f"{incident['incident_id']} violates the assignee filter")
        if incident.get("operational_context_origin") != "simulated":
            problems.append(f"{incident['incident_id']} lost its simulated-context label")
    # A filtered read describes its own set; a newest-page read must not pretend to.
    summary = body.get("match_summary")
    if summary is not None and summary.get("total") != matched:
        problems.append("match_summary.total disagrees with match_count")
    return problems


# Case list: (label, params, expected http code, expected top-level status)
CASES = [
    ("no filters", {}, 200, None),
    ("incident_id full", {"incident_id": "ARK-INC-00014"}, 200, None),
    ("incident_id bare number", {"incident_id": "14"}, 200, None),
    ("incident_id lowercase", {"incident_id": "ark-inc-00014"}, 200, None),
    ("unit plain", {"unit": "92"}, 200, None),
    ("unit zero padded", {"unit": "092"}, 200, None),
    ("unit full record id", {"unit": "FD001-Unit-092"}, 200, None),
    ("priority single", {"priority": "P1"}, 200, None),
    ("priority list", {"priority": "P1,P2"}, 200, None),
    ("priority lowercase", {"priority": "p1"}, 200, None),
    ("status filter", {"status": "new", "limit": "2"}, 200, None),
    ("status with no members", {"status": "closed"}, 200, None),
    ("status open expands", {"status": "open", "limit": "3"}, 200, None),
    ("assignee full name", {"assigned_to": "A. Novak", "limit": "3"}, 200, None),
    ("assignee by surname", {"assignee": "Novak", "limit": "3"}, 200, None),
    ("assignee and open", {"assigned_to": "A. Novak", "status": "open", "limit": "3"}, 200, None),
    ("a name fragment matches nobody", {"assigned_to": "ova"}, 200, "no_match"),
    ("unknown incident", {"incident_id": "ARK-INC-99999"}, 200, "no_match"),
    ("limit honoured", {"limit": "2"}, 200, None),
    ("combined filters", {"priority": "P2", "unit": "100"}, 200, None),
    ("unknown parameter ignored", {"colour": "blue"}, 200, None),
    ("bad priority", {"priority": "P9"}, 400, "rejected"),
    ("bad status", {"status": "exploded"}, 400, "rejected"),
    ("bad limit word", {"limit": "many"}, 400, "rejected"),
    ("limit at the cap", {"limit": "500"}, 200, None),
    ("limit out of range", {"limit": "501"}, 400, "rejected"),
    ("bad incident_id", {"incident_id": "not-an-id"}, 400, "rejected"),
    ("two errors at once", {"priority": "P9", "limit": "0"}, 400, "rejected"),
    ("simulated failure", {"simulate_failure": "true"}, 503, "unavailable"),
]


# Run the suite
base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
print(f"probing {base}\n")
failures = 0
for label, params, expected_code, expected_status in CASES:
    code, body = call(base, params)
    problems = []
    if code != expected_code:
        problems.append(f"expected HTTP {expected_code}, got {code}")
    if expected_status and body.get("status") != expected_status:
        problems.append(f"expected status {expected_status!r}, got {body.get('status')!r}")
    if code == 200 and not problems:
        problems += check_ok(body, params)
    if code == 400 and not body.get("errors"):
        problems.append("rejection carries no errors list")
    verdict = "PASS" if not problems else "FAIL"
    failures += bool(problems)
    detail = body.get("message") or "; ".join(body.get("errors", [])) or ""
    print(f"{verdict}  {label:<26} HTTP {code}  {detail[:70]}")
    for problem in problems:
        print(f"      -> {problem}")

# The lifecycle vocabulary must stay in step with charter 7.2
code, body = call(base, {"status": "bogus"})
if code == 400 and not all(name in " ".join(body.get("errors", [])) for name in LIFECYCLE):
    failures += 1
    print("FAIL  lifecycle vocabulary       the rejection message does not list charter 7.2 statuses")
else:
    print(f"PASS  lifecycle vocabulary       HTTP {code}")

print(f"\n{len(CASES) + 1 - failures}/{len(CASES) + 1} passed")
sys.exit(1 if failures else 0)
