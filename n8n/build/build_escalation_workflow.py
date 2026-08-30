"""Build the Arkon Escalation Record n8n workflow JSON.

The write path the Langflow approval gate guards. It records that a human
approved an escalation for an existing incident; it does not notify anyone and
it does not change the incident itself.
"""

import json
import pathlib

OUT = pathlib.Path(
    r"D:\-PROJECTS\--Portfolio\arkon-manufacturing-ai\n8n\escalation_record_v1.json"
)

INCIDENT_STORE = "/data/arkon/incidents.jsonl"
ESCALATION_STORE = "/data/arkon/escalations.jsonl"

VALIDATE = r"""// Arkon Escalation Record - request validation.
// The escalation is a write, so the contract is checked before the store is even
// read: a malformed request must not consume an escalation id.
const MAX_REASON = 500;
const MIN_REASON = 5;

// Parameters may arrive in the JSON body or in the query string. Both are
// supported for one reason: Langflow's API Request component can hand a model
// the URL and nothing else, so an agent-composed body is not possible. The
// method stays POST, set on the canvas rather than by the model, so the verb
// still says that this call changes something.
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

const reason = text(body.reason);
if (reason.length < MIN_REASON) {
  errors.push("reason is required and must be at least " + MIN_REASON + " characters");
} else if (reason.length > MAX_REASON) {
  errors.push("reason must be at most " + MAX_REASON + " characters");
}

const requestedBy = text(body.requested_by) || "arkon-quality-assistant";
const approvedBy = text(body.approved_by) || "human approval gate";

return [
  {
    json: {
      valid: errors.length === 0,
      errors,
      request: {
        incident_id: incidentId,
        reason: reason.slice(0, MAX_REASON),
        requested_by: requestedBy.slice(0, 120),
        approved_by: approvedBy.slice(0, 120),
      },
    },
  },
];
"""

BUILD_RECORD = r"""// Arkon Escalation Record - confirm the incident exists, then build the record.
// An escalation against an incident that is not in the store is refused: it would
// be an audit entry pointing at nothing.
const request = $("Validate Escalation").first().json.request;
const storeText = $input.first().json.store_text ?? "";

const incidents = [];
for (const line of storeText.split("\n").map((l) => l.trim()).filter(Boolean)) {
  try {
    incidents.push(JSON.parse(line));
  } catch (error) {
    // A damaged line is not an escalation failure; the status API reports the count.
  }
}

const incident = incidents.find((item) => item.incident_id === request.incident_id) ?? null;
if (!incident) {
  return [{ json: { found: false, incident_id: request.incident_id } }];
}

// Escalation ids come from workflow static data, the same mechanism the intake
// workflow uses for incident ids. Static data persists for production executions
// of a published workflow, not for editor test runs.
const state = $getWorkflowStaticData("global");
state.nextEscalationId = (state.nextEscalationId ?? 0) + 1;
const escalationId = "ARK-ESC-" + String(state.nextEscalationId).padStart(5, "0");

const record = {
  escalation_id: escalationId,
  created_at: new Date().toISOString(),
  incident_id: incident.incident_id,
  incident_priority: incident.priority,
  incident_status_at_escalation: incident.status,
  incident_summary: incident.summary,
  reason: request.reason,
  requested_by: request.requested_by,
  approved_by: request.approved_by,
  notification_channel: "none",
  context_origin: "simulated",
};

return [
  {
    json: {
      found: true,
      escalation: record,
      escalation_jsonl: JSON.stringify(record) + "\n",
    },
  },
];
"""


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


workflow = {
    "id": "arkonEscalate01",
    "name": "Arkon Escalation Record v1",
    "nodes": [
        {
            "id": "b1000000-0000-4000-8000-000000000001",
            "name": "Escalation Intake",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1328, 240],
            "webhookId": "arkon-escalation-intake",
            "parameters": {
                "httpMethod": "POST",
                "path": "arkon-escalation",
                "responseMode": "responseNode",
                "options": {},
            },
        },
        {
            "id": "b1000000-0000-4000-8000-000000000002",
            "name": "Validate Escalation",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-1104, 240],
            "parameters": {"jsCode": VALIDATE},
        },
        if_node("b1000000-0000-4000-8000-000000000003", "Valid?", [-880, 240], "={{ $json.valid }}"),
        respond(
            "b1000000-0000-4000-8000-000000000004",
            "Respond Invalid",
            [-656, 416],
            '={{ JSON.stringify({status: "rejected", errors: $json.errors}) }}',
            400,
        ),
        {
            "id": "b1000000-0000-4000-8000-000000000005",
            "name": "Read Incident Store",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [-656, 160],
            "onError": "continueErrorOutput",
            "parameters": {"operation": "read", "fileSelector": INCIDENT_STORE, "options": {}},
        },
        respond(
            "b1000000-0000-4000-8000-000000000006",
            "Respond Store Unavailable",
            [-432, -16],
            '={{ JSON.stringify({status: "unavailable", message: "The incident store could not be read, so the escalation was not recorded."}) }}',
            503,
        ),
        {
            "id": "b1000000-0000-4000-8000-000000000007",
            "name": "Extract Store Text",
            "type": "n8n-nodes-base.extractFromFile",
            "typeVersion": 1.1,
            "position": [-432, 224],
            "parameters": {
                "operation": "text",
                "binaryPropertyName": "data",
                "destinationKey": "store_text",
                "options": {},
            },
        },
        {
            "id": "b1000000-0000-4000-8000-000000000008",
            "name": "Build Escalation Record",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-208, 224],
            "parameters": {"jsCode": BUILD_RECORD},
        },
        if_node(
            "b1000000-0000-4000-8000-000000000009",
            "Incident Found?",
            [16, 224],
            "={{ $json.found }}",
        ),
        respond(
            "b1000000-0000-4000-8000-00000000000a",
            "Respond Unknown Incident",
            [240, 400],
            '={{ JSON.stringify({status: "rejected", errors: ["no incident " + $json.incident_id + " in the store, so no escalation was recorded"]}) }}',
            404,
        ),
        {
            "id": "b1000000-0000-4000-8000-00000000000b",
            "name": "Build Escalation Line",
            "type": "n8n-nodes-base.convertToFile",
            "typeVersion": 1.1,
            "position": [240, 160],
            "parameters": {"operation": "toText", "sourceProperty": "escalation_jsonl", "options": {}},
        },
        {
            "id": "b1000000-0000-4000-8000-00000000000c",
            "name": "Append Escalation Record",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [464, 160],
            "parameters": {
                "operation": "write",
                "fileName": ESCALATION_STORE,
                "options": {"append": True},
            },
        },
        respond(
            "b1000000-0000-4000-8000-00000000000d",
            "Respond Recorded",
            [688, 160],
            '={{ JSON.stringify({status: "escalation_recorded", escalation_id: $(\'Build Escalation Record\').item.json.escalation.escalation_id, incident_id: $(\'Build Escalation Record\').item.json.escalation.incident_id, recorded_at: $(\'Build Escalation Record\').item.json.escalation.created_at, notification_channel: "none"}) }}',
        ),
    ],
    "connections": {
        "Escalation Intake": {"main": [[{"node": "Validate Escalation", "type": "main", "index": 0}]]},
        "Validate Escalation": {"main": [[{"node": "Valid?", "type": "main", "index": 0}]]},
        "Valid?": {
            "main": [
                [{"node": "Read Incident Store", "type": "main", "index": 0}],
                [{"node": "Respond Invalid", "type": "main", "index": 0}],
            ]
        },
        "Read Incident Store": {
            "main": [
                [{"node": "Extract Store Text", "type": "main", "index": 0}],
                [{"node": "Respond Store Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Extract Store Text": {"main": [[{"node": "Build Escalation Record", "type": "main", "index": 0}]]},
        "Build Escalation Record": {"main": [[{"node": "Incident Found?", "type": "main", "index": 0}]]},
        "Incident Found?": {
            "main": [
                [{"node": "Build Escalation Line", "type": "main", "index": 0}],
                [{"node": "Respond Unknown Incident", "type": "main", "index": 0}],
            ]
        },
        "Build Escalation Line": {"main": [[{"node": "Append Escalation Record", "type": "main", "index": 0}]]},
        "Append Escalation Record": {"main": [[{"node": "Respond Recorded", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "binaryMode": "separate", "availableInMCP": False},
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes")
