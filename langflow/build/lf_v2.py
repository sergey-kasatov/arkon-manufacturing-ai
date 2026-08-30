"""Run a Langflow flow through the v2 workflows API, which can pause and resume.

A flow containing a Human Input node cannot be executed through /api/v1/run at
all - not even on branches that never reach the gate - so every scripted test of
the Sprint 3 canvas goes through here.

Usage (on the NAS, beside lf_api.py):
    python3 lf_v2.py run <flow-name-or-id> <message> [session_id] [decision]
    python3 lf_v2.py session <flow-name-or-id> <turns.json> <session_id> [decision]

`decision` is the label to send if the run pauses for approval, e.g. Approve or
Reject. Without it a paused run is reported and left pending.
"""

import json
import sys
import time
import urllib.error
import urllib.request

import lf_api

POLL_SECONDS = 2
POLL_LIMIT = 150


def post(path, payload):
    request = urllib.request.Request(
        lf_api.BASE + path,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"x-api-key": lf_api.api_key(), "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            body = response.read()
            if body[:2] == lf_api.GZIP_MAGIC:
                body = lf_api.gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read()
        if detail[:2] == lf_api.GZIP_MAGIC:
            detail = lf_api.gzip.decompress(detail)
        sys.exit("HTTP %s on POST %s\n%s" % (err.code, path, detail.decode("utf-8", "replace")[:3000]))


def get(path):
    request = urllib.request.Request(
        lf_api.BASE + path, headers={"x-api-key": lf_api.api_key()}
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = response.read()
            if body[:2] == lf_api.GZIP_MAGIC:
                body = lf_api.gzip.decompress(body)
            return json.loads(body.decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read()
        if detail[:2] == lf_api.GZIP_MAGIC:
            detail = lf_api.gzip.decompress(detail)
        sys.exit("HTTP %s on GET %s\n%s" % (err.code, path, detail.decode("utf-8", "replace")[:3000]))


def resolve_flow_id(target):
    if len(target) == 36 and target.count("-") == 4:
        return target
    for flow in lf_api.api("GET", "/api/v1/flows/?get_all=true&header_flows=true"):
        if target in (flow.get("endpoint_name"), flow.get("name")):
            return flow["id"]
    sys.exit("no flow named or endpointed %r" % target)


def texts(state):
    """Return (branch display name, answer) for every chat output that produced one.

    Naming the branch is the point: the whole demo narration is which node
    classified and which specialist answered.
    """
    answers = []
    for node_id, output in (state.get("outputs") or {}).items():
        content = output.get("content")
        if isinstance(content, str) and content.strip():
            answers.append((output.get("display_name") or node_id, content))
    if not answers:
        single = (state.get("output") or {}).get("text")
        if isinstance(single, str) and single.strip():
            answers.append((state.get("output", {}).get("source", "output"), single))
    return answers


def pending_for(job_id, flow_id):
    listing = get("/api/v2/workflows/pending?flow_id=%s" % flow_id)
    items = listing if isinstance(listing, list) else listing.get("pending", listing.get("items", []))
    return [item for item in items if str(item.get("job_id")) == str(job_id)]


def run_once(flow_id, message, session_id, decision=None):
    payload = {"flow_id": flow_id, "input_value": message, "mode": "background"}
    if session_id:
        payload["session_id"] = session_id
    started = post("/api/v2/workflows", payload)
    job_id = started.get("job_id") or started.get("id")
    if not job_id:
        print(json.dumps(started)[:2000])
        return
    resumed = False
    for _ in range(POLL_LIMIT):
        state = get("/api/v2/workflows?job_id=%s" % job_id)
        status = str(state.get("status", "")).lower()
        if status in ("completed", "success", "finished", "failed", "error", "cancelled"):
            answers = texts(state)
            print("[status %s]" % status)
            for branch, answer in answers:
                print("[%s]" % branch)
                print(answer)
            if not answers:
                print(json.dumps(state)[:3000])
            return
        waiting = pending_for(job_id, flow_id)
        if waiting and not resumed:
            request = waiting[0]
            print("[paused for approval] request_id=%s options=%s"
                  % (request.get("request_id"), [o.get("label") for o in request.get("options", [])]))
            if not decision:
                print("[left pending: no decision given]")
                return
            print("[answering: %s]" % decision)
            post("/api/v2/workflows/%s/resume" % job_id,
                 {"request_id": request.get("request_id"),
                  "decision": {"action_id": str(decision).strip().lower().replace(" ", "_")}})
            resumed = True
        time.sleep(POLL_SECONDS)
    print("[timed out waiting for job %s]" % job_id)


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    command, target = sys.argv[1], sys.argv[2]
    flow_id = resolve_flow_id(target)
    if command == "run":
        run_once(flow_id, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None,
                 sys.argv[5] if len(sys.argv) > 5 else None)
    elif command == "session":
        with open(sys.argv[3], encoding="utf-8") as handle:
            turns = json.load(handle)
        session_id = sys.argv[4] if len(sys.argv) > 4 else None
        decision = sys.argv[5] if len(sys.argv) > 5 else None
        for index, turn in enumerate(turns, start=1):
            message = turn["message"] if isinstance(turn, dict) else turn
            turn_decision = turn.get("decision", decision) if isinstance(turn, dict) else decision
            print("=" * 78)
            print("TURN %d  >>> %s" % (index, message))
            print("-" * 78)
            run_once(flow_id, message, session_id, turn_decision)
            print()
    else:
        sys.exit(__doc__)


main()
