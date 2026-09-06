"""Clients for the two live services, and one rule they share.

The status API distinguishes four situations on purpose: incidents found,
nothing matched, request rejected, lookup failed. Collapsing the last two into
an empty result is what makes a consumer invent a status, so every call here
returns which of the four it got and the pages render them differently. A cockpit
that shows an empty table when the store is unreachable is worse than one that
shows nothing at all.

Stdlib only, like the probes in n8n/, so the app has one less thing to install.
"""

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from utils import config

TIMEOUT = 30

# Langflow gzips its answers whether or not one is asked for, and n8n does not.
# Sniffing the two magic bytes covers both without a per-service branch, and it
# is what `langflow/build/lf_api.py` does for the same reason.
GZIP_MAGIC = bytes([31, 139])


# Transport

def _text(payload):
    if payload[:2] == GZIP_MAGIC:
        payload = gzip.decompress(payload)
    return payload.decode("utf-8", errors="replace")


def _request(url, method="GET", body=None, headers=None, timeout=TIMEOUT):
    """Return (http_status, parsed_body). A transport failure comes back as 0."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = _text(response.read())
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as err:
        raw = _text(err.read())
        try:
            return err.code, json.loads(raw)
        except json.JSONDecodeError:
            return err.code, {"status": "unavailable", "message": raw[:300]}
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        # No answer at all is not an empty answer. It is reported as unavailable
        # with the reason, so the page can say the lookup failed.
        return 0, {"status": "unavailable", "message": "no answer from %s (%s)" % (url, err)}


# Incident status API, the read path

def incidents(**filters):
    """Query the status API. Empty and None filters are dropped, not sent."""
    query = {k: v for k, v in filters.items() if v not in (None, "", [], ())}
    for key, value in list(query.items()):
        if isinstance(value, (list, tuple)):
            query[key] = ",".join(str(v) for v in value)
    url = config.STATUS_API + ("?" + urllib.parse.urlencode(query) if query else "")
    status, body = _request(url)
    body.setdefault("status", "unavailable")
    body["http_status"] = status
    return body


def reachable(body):
    """True when the answer describes the store rather than a failure to read it."""
    return body.get("status") in ("ok", "no_match")


# Incident transition API, the lifecycle write path

def transition(incident_id, to_status, actor, note=""):
    """Record one lifecycle transition. Returns the parsed answer with its code."""
    query = urllib.parse.urlencode(
        {"incident_id": incident_id, "to_status": to_status, "actor": actor, "note": note}
    )
    status, body = _request(config.TRANSITION_API + "?" + query, method="POST")
    body["http_status"] = status
    return body


# Langflow, the assistant

class AssistantError(RuntimeError):
    pass


def _langflow(path, method="GET", body=None, timeout=TIMEOUT):
    if not config.LANGFLOW_API_KEY:
        raise AssistantError(
            "No Langflow API key. Set ARKON_LANGFLOW_API_KEY for this app; on the NAS it "
            "belongs in the compose file, never in the repository."
        )
    status, parsed = _request(
        config.LANGFLOW_URL + path, method=method, body=body,
        headers={"x-api-key": config.LANGFLOW_API_KEY, "Accept": "application/json"},
        timeout=timeout,
    )
    if status not in (200, 201, 202):
        raise AssistantError("HTTP %s on %s %s: %s" % (status, method, path, json.dumps(parsed)[:300]))
    return parsed


def flow_id(name=None):
    """Resolve the assistant's endpoint name to a flow id."""
    name = name or config.ASSISTANT_FLOW
    if len(name) == 36 and name.count("-") == 4:
        return name
    for flow in _langflow("/api/v1/flows/?get_all=true&header_flows=true") or []:
        if name in (flow.get("endpoint_name"), flow.get("name")):
            return flow["id"]
    raise AssistantError("no Langflow flow named or endpointed %r" % name)


def start_turn(flow, message, session_id):
    """Start one turn in the background and return its job id.

    The canvas holds a Human Input node, so it cannot be run through the v1 API
    at all, on any branch. Everything goes through v2 workflows, which can pause.
    """
    started = _langflow(
        "/api/v2/workflows", method="POST",
        body={"flow_id": flow, "input_value": message, "mode": "background", "session_id": session_id},
    )
    job = started.get("job_id") or started.get("id")
    if not job:
        raise AssistantError("no job id in the answer: " + json.dumps(started)[:300])
    return job


def poll_turn(flow, job_id, seconds=2.0):
    """Wait one step and report where the turn is: running, paused or done.

    Returns a dict with `state` in {running, paused, done} plus, when paused, the
    approval request, and when done, the answers as (branch name, text) pairs.
    """
    state = _langflow("/api/v2/workflows?job_id=%s" % job_id)
    status = str(state.get("status", "")).lower()
    if status in ("completed", "success", "finished", "failed", "error", "cancelled"):
        return {"state": "done", "status": status, "answers": answers(state)}

    listing = _langflow("/api/v2/workflows/pending?flow_id=%s" % flow)
    items = listing if isinstance(listing, list) else listing.get("pending", listing.get("items", []))
    waiting = [item for item in items if str(item.get("job_id")) == str(job_id)]
    if waiting:
        return {"state": "paused", "request": waiting[0]}
    time.sleep(seconds)
    return {"state": "running"}


def resume_turn(job_id, request_id, decision):
    """Answer an approval request. The action id is the label, lowercased."""
    return _langflow(
        "/api/v2/workflows/%s/resume" % job_id, method="POST",
        body={"request_id": request_id,
              "decision": {"action_id": str(decision).strip().lower().replace(" ", "_")}},
    )


def history(session_id):
    """Every turn Langflow has stored under this session, oldest first.

    Langflow persists each message in its own table keyed by session id, so a
    conversation survives the page that produced it. The cockpit used to mint a
    fresh uuid on every load and never read this back, which threw away the key to
    a conversation that was still on disk: the history was not lost, only
    unreachable. Returns [] rather than raising when the lookup fails, because a
    conversation that cannot be reloaded is a worse page, not a broken one.
    """
    try:
        rows = _langflow(
            "/api/v1/monitor/messages?session_id=" + urllib.parse.quote(session_id)
        ) or []
    except AssistantError:
        return []
    turns = []
    for row in rows:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        turns.append({
            "role": "user" if (row.get("sender") or "").lower() == "user" else "assistant",
            "branch": row.get("sender_name") if (row.get("sender") or "").lower() != "user" else None,
            "text": text,
            "at": row.get("timestamp"),
        })
    return turns


def answers(state):
    """Every chat output that produced text, with the branch that produced it.

    Naming the branch is the point rather than decoration: which specialist
    answered is the execution trace, and it is what the operator is owed.
    """
    found = []
    for node_id, output in (state.get("outputs") or {}).items():
        content = output.get("content")
        if isinstance(content, str) and content.strip():
            found.append((output.get("display_name") or node_id, content))
    if not found:
        single = (state.get("output") or {}).get("text")
        if isinstance(single, str) and single.strip():
            found.append((state.get("output", {}).get("source", "output"), single))
    return found
