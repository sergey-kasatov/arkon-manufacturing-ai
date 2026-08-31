"""Contract test for the Arkon Escalation Record API, the one endpoint that writes.

Every case here is a case that must NOT reach the store: the simulated failure,
the malformed requests, and an escalation against an incident that does not
exist. That is deliberate and it is the whole design of this probe. The endpoint
appends an audit record and consumes an escalation id, so a suite that exercised
the success path would grow the store a little every time it ran, and a test that
changes the thing it measures is not a test worth keeping.

The success path is therefore left to a human at the approval gate, which is also
the only way it is reached in normal use.

This suite exists because the 503 branch could not be exercised at all until the
`simulate_failure` parameter was added on 2026-08-31. Before that it needed the
incident store to be moved aside on the NAS, so nobody exercised it, and a
sentence copied into the wrong branch survived there for as long as the branch
went unread. See DEFECT-7 in the project notes.

Stdlib only.

Usage:
    python n8n/escalation_probe.py
    python n8n/escalation_probe.py http://AK2101:5678/webhook/arkon-escalation
"""

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "http://AK2101:5678/webhook/arkon-escalation"

# An id far outside the range the demo store uses. Every case that would
# otherwise be valid points at this, so a passing suite writes nothing even if
# the endpoint were to lose its existence check.
ABSENT_INCIDENT = "ARK-INC-00099"


def call(base, params):
    """POST the parameters as a query string, the way the agent's tool does."""
    url = base + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"raw": raw[:200]}


VALID = {
    "incident_id": ABSENT_INCIDENT,
    "reason": "contract probe, never intended to be recorded",
    "requested_by": "escalation-probe",
    "approved_by": "escalation-probe",
}


def case(name, params, expect_code, expect_status, must_contain=None):
    return (name, params, expect_code, expect_status, must_contain)


CASES = [
    # The designed failure path, and the reason this file exists.
    case("simulated failure", dict(VALID, simulate_failure="1"), 503, "unavailable",
         "simulated failure requested by the caller"),
    case("simulated failure, true", dict(VALID, simulate_failure="true"), 503, "unavailable", None),
    case("simulated failure, yes", dict(VALID, simulate_failure="yes"), 503, "unavailable", None),
    case("simulate off is not on", dict(VALID, simulate_failure="0"), 404, "rejected", None),
    case("simulate absent is off", VALID, 404, "rejected", None),

    # Validation runs first, so a malformed request cannot ride the simulated
    # failure past the contract, and cannot consume an escalation id either.
    case("validation beats simulate", dict(VALID, reason="x", simulate_failure="1"), 400, "rejected",
         "reason is required"),
    case("reason too short", dict(VALID, reason="x"), 400, "rejected", "at least 5 characters"),
    case("reason missing", {k: v for k, v in VALID.items() if k != "reason"}, 400, "rejected",
         "reason is required"),
    case("incident_id missing", {k: v for k, v in VALID.items() if k != "incident_id"}, 400, "rejected",
         "incident_id is required"),
    case("incident_id malformed", dict(VALID, incident_id="engine 92"), 400, "rejected",
         "must look like ARK-INC-00014"),

    # A plain number and a short id both normalise to the padded form, and the
    # rejection names the normalised id back. Pointed at the absent incident so
    # normalisation is checked without writing.
    case("plain number normalises", dict(VALID, incident_id="99"), 404, "rejected", ABSENT_INCIDENT),
    case("short id normalises", dict(VALID, incident_id="ARK-INC-99"), 404, "rejected", ABSENT_INCIDENT),

    # An audit entry pointing at nothing is refused, and says so.
    case("unknown incident", VALID, 404, "rejected", "no escalation was recorded"),
]


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    passed = 0

    for name, params, expect_code, expect_status, must_contain in CASES:
        code, body = call(base, params)
        text = json.dumps(body)
        problems = []
        if code != expect_code:
            problems.append("HTTP %s, expected %s" % (code, expect_code))
        if body.get("status") != expect_status:
            problems.append("status %r, expected %r" % (body.get("status"), expect_status))
        if must_contain and must_contain not in text:
            problems.append("answer does not mention %r" % must_contain)
        # No case in this suite may ever record anything.
        if "escalation_id" in text:
            problems.append("THE STORE WAS WRITTEN: " + text[:160])

        if problems:
            print("FAIL  %-26s %s" % (name, "; ".join(problems)))
        else:
            passed += 1
            message = body.get("message") or "; ".join(body.get("errors", []))
            print("PASS  %-26s HTTP %s  %s" % (name, code, message[:78]))

    print("\n%d/%d passed" % (passed, len(CASES)))
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
