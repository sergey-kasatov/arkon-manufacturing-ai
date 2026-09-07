"""Build the Arkon Incident Transition n8n workflow JSON.

The incident lifecycle write path of charter 7.2. Version 1 wrote an incident
once, at new, and nothing could ever move it, so no response-time KPI could be
computed and no incident could reach closure. This endpoint records the later
states.

It appends to a transition log rather than rewriting the incident line. Three
reasons, in order of weight: the incident store is append-only and both existing
write paths keep it that way; a read-modify-write of the whole store would race
the intake workflow, which appends to the same file with no lock; and a log of
transitions is what a response-time KPI actually needs, because a KPI needs two
timestamps and an overwritten record keeps one. The current status of an incident
is therefore a fold, and every consumer that reports a status performs it.

Since 2026-09-07 the endpoint also starts the store sync of charter 7.5 after
every append (`add_store_sync.py`), so the queryable projection the status API
reads is level with the log seconds after a move. The sync is not waited for and
cannot fail a transition.
"""

import json
import pathlib

from add_store_sync import sync_node
from lifecycle import FOLD_JS, js_constants

OUT = pathlib.Path(__file__).resolve().parent.parent / "incident_transition_v1.json"

INCIDENT_STORE = "/data/arkon/incidents.jsonl"
TRANSITION_STORE = "/data/arkon/incident_transitions.jsonl"

VALIDATE = (
    r"""// Arkon Incident Transition - request validation.
// A transition is a write, so the contract is checked before any store is opened:
// a malformed request must not consume a transition id.
"""
    + js_constants()
    + r"""
const MAX_NOTE = 500;

// Parameters may arrive in the JSON body or in the query string, for the same
// reason the escalation endpoint accepts both: Langflow's API Request component
// can hand a model the URL and nothing else, so an agent-composed body is not
// possible. The method stays POST, set on the canvas rather than by the model,
// so the verb still says that this call changes something.
const incoming = $input.first().json;
const body = { ...(incoming.query ?? {}), ...(incoming.body ?? {}) };
const errors = [];

const text = (value) => (value === undefined || value === null ? "" : String(value).trim());

let incidentId = text(body.incident_id);
if (!incidentId) {
  errors.push("incident_id is required");
} else {
  const digits = incidentId.replace(/[^0-9]/g, "");
  if (!/^(ARK-INC-)?[0-9]+$/i.test(incidentId) || digits === "") {
    errors.push("incident_id must look like ARK-INC-00014 or be a plain number");
  } else {
    incidentId = "ARK-INC-" + digits.padStart(5, "0");
  }
}

// to_status names the state being entered. "new" gets its own reason rather than
// the generic list: it is the intake state, written once by the Steering Cell,
// and a caller asking for it has misread the endpoint rather than mistyped.
let toStatus = text(body.to_status).toLowerCase();
if (!toStatus) {
  errors.push("to_status is required and must be one of " + REQUESTABLE_STATUSES.join(", "));
} else if (toStatus === "new") {
  errors.push("to_status new is the intake state, written by the Steering Cell and never by a transition");
  toStatus = "";
} else if (!REQUESTABLE_STATUSES.includes(toStatus)) {
  errors.push("to_status must be one of " + REQUESTABLE_STATUSES.join(", ") + "; got " + toStatus);
  toStatus = "";
}

const actor = text(body.actor) || "human operator";
const note = text(body.note);
if (note.length > MAX_NOTE) {
  errors.push("note must be at most " + MAX_NOTE + " characters");
}

// The same test affordance, the same three spellings, as the status API and the
// escalation record. Read after validation and before anything is opened, so a
// malformed request still gets its 400 and no transition id is consumed. A
// production deployment removes it or puts it behind an operator role.
const simulateFailure = ["1", "true", "yes"].includes(text(body.simulate_failure).toLowerCase());

return [
  {
    json: {
      valid: errors.length === 0,
      errors,
      simulate_failure: simulateFailure,
      request: {
        incident_id: incidentId,
        to_status: toStatus,
        actor: actor.slice(0, 120),
        note: note.slice(0, MAX_NOTE),
      },
    },
  },
];
"""
)

BUILD_RECORD = (
    r"""// Arkon Incident Transition - fold the log onto the incident, then decide.
// Two refusals live here and neither writes anything: an incident that is not in
// the store, and a transition the lifecycle does not allow from where the
// incident actually is. The second one needs the fold, because the incident line
// says "new" for the whole life of the incident.
"""
    + js_constants()
    + FOLD_JS
    + r"""
const request = $("Validate Transition").first().json.request;
const storeText = $("Extract Store Text").first().json.store_text ?? "";
const transitionsText = $("Extract Transitions Text").first().json.transitions_text ?? "";

const incidents = [];
for (const line of storeText.split("\n").map((l) => l.trim()).filter(Boolean)) {
  try {
    incidents.push(JSON.parse(line));
  } catch (error) {
    // A damaged line is not a transition failure; the status API reports the count.
  }
}

const incident = incidents.find((item) => item.incident_id === request.incident_id) ?? null;
if (!incident) {
  return [{ json: { found: false, allowed: false, incident_id: request.incident_id } }];
}

const folded = arkonFold(incident, arkonTransitionsById(transitionsText).byId);
const from = folded.status;
const allowedNext = ALLOWED_TRANSITIONS[from] ?? [];

if (!allowedNext.includes(request.to_status)) {
  return [
    {
      json: {
        found: true,
        allowed: false,
        incident_id: incident.incident_id,
        current_status: from,
        requested_status: request.to_status,
        allowed_next: allowedNext,
        reason: allowedNext.length
          ? incident.incident_id + " is " + from + ", and from there the lifecycle allows only " + allowedNext.join(", ")
          : incident.incident_id + " is " + from + ", which is a terminal state; no further transition is possible",
      },
    },
  ];
}

// Transition ids come from workflow static data, the same mechanism the intake
// and escalation workflows use for their ids, and one is consumed only once both
// refusals above are past. Static data persists for production executions of a
// published workflow, not for editor test runs.
const state = $getWorkflowStaticData("global");
state.nextTransitionId = (state.nextTransitionId ?? 0) + 1;
const transitionId = "ARK-TRN-" + String(state.nextTransitionId).padStart(5, "0");

const recordedAt = new Date();
const minutesBetween = (fromMs, toMs) =>
  Number.isNaN(fromMs) || Number.isNaN(toMs) ? null : Math.round(((toMs - fromMs) / 60000) * 10) / 10;

const minutesSinceCreated = minutesBetween(Date.parse(incident.created_at ?? ""), recordedAt.getTime());
const previous = folded.history.length ? folded.history[folded.history.length - 1] : null;
const minutesSincePrevious = previous
  ? minutesBetween(Date.parse(previous.recorded_at ?? ""), recordedAt.getTime())
  : null;

// The acknowledgement window of charter 7.1, evaluated only on the transition it
// describes and null on every other one. The timestamps are the record of truth;
// these two numbers are derived at write time so a consumer reading this file
// alone, a Tableau extract for instance, still has the KPI without the fold.
const ackWindow = ACK_WINDOW_MINUTES[String(incident.priority ?? "").toUpperCase()] ?? null;
const acknowledgedWithinWindow =
  request.to_status === "acknowledged" && ackWindow !== null && minutesSinceCreated !== null
    ? minutesSinceCreated <= ackWindow
    : null;

const record = {
  transition_id: transitionId,
  recorded_at: recordedAt.toISOString(),
  incident_id: incident.incident_id,
  incident_priority: incident.priority ?? null,
  incident_created_at: incident.created_at ?? null,
  from_status: from,
  to_status: request.to_status,
  actor: request.actor,
  note: request.note,
  minutes_since_created: minutesSinceCreated,
  minutes_since_previous_transition: minutesSincePrevious,
  acknowledge_window_minutes: ackWindow,
  acknowledged_within_window: acknowledgedWithinWindow,
  // The actor is a simulated role holder, the same boundary the escalation
  // record draws. The timestamps and the state machine are real.
  context_origin: "simulated",
};

return [
  {
    json: {
      found: true,
      allowed: true,
      transition: record,
      transition_jsonl: JSON.stringify(record) + "\n",
    },
  },
];
"""
)


def respond(node_id, name, position, body_expression, response_code=None):
    options = {} if response_code is None else {"responseCode": response_code}
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.respondToWebhook",
        "typeVersion": 1.1,
        "position": position,
        "parameters": {
            "respondWith": "json",
            "responseBody": body_expression,
            "options": options,
        },
    }


def if_node(node_id, name, position, left_value):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": position,
        "parameters": {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "strict",
                    "version": 1,
                },
                "conditions": [
                    {
                        "id": node_id,
                        "leftValue": left_value,
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    }


def read_file(node_id, name, position, path):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.readWriteFile",
        "typeVersion": 1.1,
        "position": position,
        "onError": "continueErrorOutput",
        "parameters": {"operation": "read", "fileSelector": path, "options": {}},
    }


def extract_text(node_id, name, position, destination_key):
    return {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.extractFromFile",
        "typeVersion": 1.1,
        "position": position,
        "parameters": {
            "operation": "text",
            "binaryPropertyName": "data",
            "destinationKey": destination_key,
            "options": {},
        },
    }


RECORDED_BODY = (
    "={{ JSON.stringify({"
    'status: "transition_recorded", '
    "transition_id: $('Build Transition Record').item.json.transition.transition_id, "
    "incident_id: $('Build Transition Record').item.json.transition.incident_id, "
    "from_status: $('Build Transition Record').item.json.transition.from_status, "
    "to_status: $('Build Transition Record').item.json.transition.to_status, "
    "recorded_at: $('Build Transition Record').item.json.transition.recorded_at, "
    "minutes_since_created: $('Build Transition Record').item.json.transition.minutes_since_created, "
    "acknowledged_within_window: $('Build Transition Record').item.json.transition.acknowledged_within_window"
    "}) }}"
)

workflow = {
    "id": "arkonTransit01",
    "name": "Arkon Incident Transition v1",
    "nodes": [
        {
            "id": "c1000000-0000-4000-8000-000000000001",
            "name": "Transition Intake",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1552, 240],
            "webhookId": "arkon-incident-transition-intake",
            "parameters": {
                "httpMethod": "POST",
                "path": "arkon-incident-transition",
                "responseMode": "responseNode",
                "options": {},
            },
        },
        {
            "id": "c1000000-0000-4000-8000-000000000002",
            "name": "Validate Transition",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-1328, 240],
            "parameters": {"jsCode": VALIDATE},
        },
        if_node("c1000000-0000-4000-8000-000000000003", "Valid?", [-1104, 240], "={{ $json.valid }}"),
        respond(
            "c1000000-0000-4000-8000-000000000004",
            "Respond Invalid",
            [-880, 416],
            '={{ JSON.stringify({status: "rejected", errors: $json.errors}) }}',
            400,
        ),
        if_node(
            "c1000000-0000-4000-8000-000000000005",
            "Simulated Failure?",
            [-880, 160],
            "={{ $json.simulate_failure }}",
        ),
        respond(
            "c1000000-0000-4000-8000-000000000006",
            "Respond Simulated Unavailable",
            [-656, -160],
            '={{ JSON.stringify({status: "unavailable", message: "The transition was not recorded (simulated failure requested by the caller)."}) }}',
            503,
        ),
        read_file("c1000000-0000-4000-8000-000000000007", "Read Incident Store", [-656, 160], INCIDENT_STORE),
        respond(
            "c1000000-0000-4000-8000-000000000008",
            "Respond Store Unavailable",
            [-432, -16],
            '={{ JSON.stringify({status: "unavailable", message: "The incident store could not be read, so the transition was not recorded."}) }}',
            503,
        ),
        extract_text("c1000000-0000-4000-8000-000000000009", "Extract Store Text", [-432, 224], "store_text"),
        read_file(
            "c1000000-0000-4000-8000-00000000000a",
            "Read Transition Store",
            [-208, 224],
            TRANSITION_STORE,
        ),
        # An unreadable transition log is a 503 rather than an empty log, and the
        # difference is the whole point of having one. Treating it as empty would
        # report every incident as new, which is a wrong status served with a 200
        # - exactly the answer the status API refuses to give when its own store
        # cannot be read.
        respond(
            "c1000000-0000-4000-8000-00000000000b",
            "Respond Transition Log Unavailable",
            [16, 32],
            '={{ JSON.stringify({status: "unavailable", message: "The transition log could not be read, so the incident\'s current status is unknown and nothing was recorded."}) }}',
            503,
        ),
        extract_text(
            "c1000000-0000-4000-8000-00000000000c",
            "Extract Transitions Text",
            [16, 288],
            "transitions_text",
        ),
        {
            "id": "c1000000-0000-4000-8000-00000000000d",
            "name": "Build Transition Record",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [240, 288],
            "parameters": {"jsCode": BUILD_RECORD},
        },
        if_node("c1000000-0000-4000-8000-00000000000e", "Incident Found?", [464, 288], "={{ $json.found }}"),
        respond(
            "c1000000-0000-4000-8000-00000000000f",
            "Respond Unknown Incident",
            [688, 464],
            '={{ JSON.stringify({status: "rejected", errors: ["no incident " + $json.incident_id + " in the store, so no transition was recorded"]}) }}',
            404,
        ),
        if_node("c1000000-0000-4000-8000-000000000010", "Transition Allowed?", [688, 224], "={{ $json.allowed }}"),
        # 409 rather than 400: the request is well formed and the incident exists,
        # but the incident has moved on. A caller has to be able to tell "you
        # asked wrong" from "you are too late", the same separation the status API
        # draws between no_match and unavailable.
        respond(
            "c1000000-0000-4000-8000-000000000011",
            "Respond Illegal Transition",
            [912, 400],
            "={{ JSON.stringify({status: \"rejected\", errors: [$json.reason], incident_id: $json.incident_id, current_status: $json.current_status, requested_status: $json.requested_status, allowed_next: $json.allowed_next}) }}",
            409,
        ),
        {
            "id": "c1000000-0000-4000-8000-000000000012",
            "name": "Build Transition Line",
            "type": "n8n-nodes-base.convertToFile",
            "typeVersion": 1.1,
            "position": [912, 160],
            "parameters": {"operation": "toText", "sourceProperty": "transition_jsonl", "options": {}},
        },
        {
            "id": "c1000000-0000-4000-8000-000000000013",
            "name": "Append Transition Record",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [1136, 160],
            "parameters": {
                "operation": "write",
                "fileName": TRANSITION_STORE,
                "options": {"append": True},
            },
        },
        respond(
            "c1000000-0000-4000-8000-000000000014",
            "Respond Recorded",
            [1360, 160],
            RECORDED_BODY,
        ),
        # Charter 7.5: every appended transition is followed by a store sync,
        # started without waiting and never able to fail the write.
        sync_node("transition", [1360, -16]),
    ],
    "connections": {
        "Transition Intake": {"main": [[{"node": "Validate Transition", "type": "main", "index": 0}]]},
        "Validate Transition": {"main": [[{"node": "Valid?", "type": "main", "index": 0}]]},
        "Valid?": {
            "main": [
                [{"node": "Simulated Failure?", "type": "main", "index": 0}],
                [{"node": "Respond Invalid", "type": "main", "index": 0}],
            ]
        },
        "Simulated Failure?": {
            "main": [
                [{"node": "Respond Simulated Unavailable", "type": "main", "index": 0}],
                [{"node": "Read Incident Store", "type": "main", "index": 0}],
            ]
        },
        "Read Incident Store": {
            "main": [
                [{"node": "Extract Store Text", "type": "main", "index": 0}],
                [{"node": "Respond Store Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Extract Store Text": {"main": [[{"node": "Read Transition Store", "type": "main", "index": 0}]]},
        "Read Transition Store": {
            "main": [
                [{"node": "Extract Transitions Text", "type": "main", "index": 0}],
                [{"node": "Respond Transition Log Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Extract Transitions Text": {
            "main": [[{"node": "Build Transition Record", "type": "main", "index": 0}]]
        },
        "Build Transition Record": {"main": [[{"node": "Incident Found?", "type": "main", "index": 0}]]},
        "Incident Found?": {
            "main": [
                [{"node": "Transition Allowed?", "type": "main", "index": 0}],
                [{"node": "Respond Unknown Incident", "type": "main", "index": 0}],
            ]
        },
        "Transition Allowed?": {
            "main": [
                [{"node": "Build Transition Line", "type": "main", "index": 0}],
                [{"node": "Respond Illegal Transition", "type": "main", "index": 0}],
            ]
        },
        "Build Transition Line": {"main": [[{"node": "Append Transition Record", "type": "main", "index": 0}]]},
        "Append Transition Record": {
            "main": [
                [
                    {"node": "Respond Recorded", "type": "main", "index": 0},
                    {"node": "Sync Store", "type": "main", "index": 0},
                ]
            ]
        },
    },
    "settings": {"executionOrder": "v1", "binaryMode": "separate", "availableInMCP": False},
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes")
