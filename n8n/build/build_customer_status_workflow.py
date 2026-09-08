"""Build the Arkon Customer Status API n8n workflow JSON.

The read endpoint of the Customer Quality Desk (2026-09-08): a customer's
quality engineer, or the agent answering them, asks about one quality notice
or complaint by its `ARK-INC` reference and gets the customer projection of
`customer_projection.py` back. It reads the same queryable store the plant
works from (charter 7.5) and serves eight fields of it; the assignee, the
evidence, the priority and every other incident stay behind the endpoint,
which is what makes the desk's output restriction an infrastructure fact
rather than a prompt instruction.

Same shape as the incident status API (`build_status_workflow.py`): one
required parameter instead of seven optional ones, the same four answers so
the agent can tell them apart, the same store reads, the same failure
affordance. Written from a script for the same reason: the Code-node bodies
stay readable and quoting stays under control.
"""

import json
import pathlib

from customer_projection import PROJECTION_JS, js_constants
from store_schema import INCIDENTS_TABLE, SUMMARY_KEY, SUMMARY_TABLE

OUT = pathlib.Path(__file__).resolve().parent.parent / "customer_status_api_v1.json"

WORKFLOW_ID = "arkonCustDesk01"
WEBHOOK_PATH = "arkon-customer-status"

PARSE_REFERENCE = r"""// Arkon Customer Status API - request parsing.
// One parameter is required: the customer's reference, which is the plant's
// incident id. Every other parameter is ignored, so a caller cannot reach an
// internal filter (priority, module, assignee) through this endpoint.
const params = $input.first().json.query ?? {};
const errors = [];

const raw = (key) => {
  const value = params[key];
  if (value === undefined || value === null) return null;
  const text = String(Array.isArray(value) ? value[0] : value).trim();
  return text === "" ? null : text;
};

// reference: accepts ARK-INC-00348, ark-inc-348, or a bare number, and is
// normalised to the padded form the store holds.
let reference = raw("reference");
if (reference === null) {
  errors.push("reference is required, for example ARK-INC-00348");
} else {
  const digits = reference.replace(/[^0-9]/g, "");
  if (!/^(ARK-INC-)?[0-9]+$/i.test(reference) || digits === "") {
    errors.push("reference must look like ARK-INC-00348");
    reference = null;
  } else {
    reference = "ARK-INC-" + digits.padStart(5, "0");
  }
}

// Test affordance only, the same one the incident status API carries: lets the
// agent's failure path be demonstrated on demand without unpublishing the
// workflow. A production deployment removes it or puts it behind an operator role.
const simulateFailure = ["1", "true", "yes"].includes((raw("simulate_failure") ?? "").toLowerCase());

return [
  {
    json: {
      valid: errors.length === 0,
      errors,
      simulate_failure: simulateFailure,
      reference,
    },
  },
];
"""

PROJECT_FOR_CUSTOMER = (
    r"""// Arkon Customer Status API - answer one reference for a customer.
// The row is the store sync's projection of the incident line with its
// transition log folded on (charter 7.2 and 7.5). What leaves this node is the
// customer projection and nothing else: nothing about the people working the
// notice, what the models saw, how urgent the plant rates it, or any other
// notice. The vocabulary and the commitment windows come from
// customer_projection.py, shared with the desk's customer documents.
"""
    + js_constants()
    + PROJECTION_JS
    + r"""
const request = $("Parse Reference").first().json;
const now = new Date();

const isRow = (json) => json && typeof json === "object" && typeof json.incident_id === "string";
const rows = $("Get Reference")
  .all()
  .map((item) => item.json)
  .filter(isRow)
  .filter((row) => row.incident_id === request.reference);

if (!rows.length) {
  return [
    {
      json: {
        status: "no_match",
        message: "No quality notice or complaint with reference " + request.reference + " is on record.",
        as_of: now.toISOString(),
        reference: request.reference,
        notice: null,
      },
    },
  ];
}

return [
  {
    json: {
      status: "ok",
      message: "Reference " + request.reference + " found.",
      as_of: now.toISOString(),
      reference: request.reference,
      notice: arkonCustomerProjection(rows[0], now),
    },
  },
];
"""
)


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
                        "operator": {
                            "type": "boolean",
                            "operation": "true",
                            "singleValue": True,
                        },
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
    }


def respond_node(node_id, name, position, body_expression, response_code=None):
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


def table_ref(name):
    return {"__rl": True, "mode": "name", "value": name}


def get_rows(node_id, name, position, table, conditions, return_all, limit=None, execute_once=False):
    # A read that finds nothing still emits one empty item, so the chain reaches
    # the answer node and answers no_match instead of leaving the caller waiting.
    node = {
        "id": node_id,
        "name": name,
        "type": "n8n-nodes-base.dataTable",
        "typeVersion": 1.1,
        "position": position,
        "alwaysOutputData": True,
        "onError": "continueErrorOutput",
        "parameters": {
            "resource": "row",
            "operation": "get",
            "dataTableId": table_ref(table),
            "matchType": "allConditions",
            "filters": {"conditions": conditions},
            "returnAll": return_all,
        },
    }
    if limit is not None:
        node["parameters"]["limit"] = limit
    if execute_once:
        node["executeOnce"] = True
    return node


def unavailable(message):
    return '={{ JSON.stringify({status: "unavailable", message: "' + message + '"}) }}'


workflow = {
    "id": WORKFLOW_ID,
    "name": "Arkon Customer Status API v1",
    "nodes": [
        {
            "id": "c1000000-0000-4000-8000-000000000001",
            "name": "Customer Status Request",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1328, 240],
            "webhookId": WEBHOOK_PATH,
            "parameters": {
                "httpMethod": "GET",
                "path": WEBHOOK_PATH,
                "responseMode": "responseNode",
                "options": {},
            },
        },
        {
            "id": "c1000000-0000-4000-8000-000000000002",
            "name": "Parse Reference",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-1104, 240],
            "parameters": {"jsCode": PARSE_REFERENCE},
        },
        if_node(
            "c1000000-0000-4000-8000-000000000003",
            "Valid Request?",
            [-880, 240],
            "={{ $json.valid }}",
        ),
        respond_node(
            "c1000000-0000-4000-8000-000000000004",
            "Respond Bad Request",
            [-656, 416],
            '={{ JSON.stringify({status: "rejected", errors: $json.errors}) }}',
            400,
        ),
        if_node(
            "c1000000-0000-4000-8000-000000000005",
            "Simulated Failure?",
            [-656, 160],
            "={{ $json.simulate_failure }}",
        ),
        respond_node(
            "c1000000-0000-4000-8000-000000000006",
            "Respond Unavailable",
            [-432, -16],
            unavailable("Reference lookup failed (simulated failure requested by the caller)."),
            503,
        ),
        # The one summary row: a store that cannot be read, or that has never been
        # synced, is a 503, never a "no such reference". A customer told that
        # their complaint is not on record because a table did not answer is the
        # one thing this endpoint must never do.
        get_rows(
            "c1000000-0000-4000-8000-000000000007",
            "Get Summary",
            [-432, 224],
            SUMMARY_TABLE,
            [{"keyName": "key", "condition": "eq", "keyValue": SUMMARY_KEY}],
            return_all=False,
            limit=1,
        ),
        respond_node(
            "c1000000-0000-4000-8000-000000000008",
            "Respond Store Unavailable",
            [-208, 416],
            unavailable("The reference lookup is temporarily unavailable (the incident store did not answer)."),
            503,
        ),
        if_node(
            "c1000000-0000-4000-8000-000000000009",
            "Store Synced?",
            [-208, 224],
            '={{ $json.key === "' + SUMMARY_KEY + '" }}',
        ),
        respond_node(
            "c1000000-0000-4000-8000-00000000000a",
            "Respond Store Not Synced",
            [16, 416],
            unavailable("The reference lookup is temporarily unavailable (the incident store has not been synced yet)."),
            503,
        ),
        # The one row the reference names. Nothing else is read.
        get_rows(
            "c1000000-0000-4000-8000-00000000000b",
            "Get Reference",
            [16, 224],
            INCIDENTS_TABLE,
            [
                {
                    "keyName": "incident_id",
                    "condition": "eq",
                    "keyValue": "={{ $('Parse Reference').first().json.reference }}",
                }
            ],
            return_all=True,
            execute_once=True,
        ),
        respond_node(
            "c1000000-0000-4000-8000-00000000000c",
            "Respond Rows Unavailable",
            [240, 416],
            unavailable("The reference lookup is temporarily unavailable (the incidents table did not answer)."),
            503,
        ),
        {
            "id": "c1000000-0000-4000-8000-00000000000d",
            "name": "Project For Customer",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [240, 224],
            "parameters": {"jsCode": PROJECT_FOR_CUSTOMER},
        },
        respond_node(
            "c1000000-0000-4000-8000-00000000000e",
            "Respond Customer Status",
            [464, 224],
            "={{ JSON.stringify($json) }}",
        ),
    ],
    "connections": {
        "Customer Status Request": {"main": [[{"node": "Parse Reference", "type": "main", "index": 0}]]},
        "Parse Reference": {"main": [[{"node": "Valid Request?", "type": "main", "index": 0}]]},
        "Valid Request?": {
            "main": [
                [{"node": "Simulated Failure?", "type": "main", "index": 0}],
                [{"node": "Respond Bad Request", "type": "main", "index": 0}],
            ]
        },
        "Simulated Failure?": {
            "main": [
                [{"node": "Respond Unavailable", "type": "main", "index": 0}],
                [{"node": "Get Summary", "type": "main", "index": 0}],
            ]
        },
        "Get Summary": {
            "main": [
                [{"node": "Store Synced?", "type": "main", "index": 0}],
                [{"node": "Respond Store Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Store Synced?": {
            "main": [
                [{"node": "Get Reference", "type": "main", "index": 0}],
                [{"node": "Respond Store Not Synced", "type": "main", "index": 0}],
            ]
        },
        "Get Reference": {
            "main": [
                [{"node": "Project For Customer", "type": "main", "index": 0}],
                [{"node": "Respond Rows Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Project For Customer": {"main": [[{"node": "Respond Customer Status", "type": "main", "index": 0}]]},
    },
    # A read endpoint the desk calls on every status question is not worth an
    # execution record per successful call (the status API's records had grown
    # n8n's database to 3.6 GB in eight days). Failures are kept.
    "settings": {
        "executionOrder": "v1",
        "binaryMode": "separate",
        "availableInMCP": False,
        "saveDataSuccessExecution": "none",
        "saveDataErrorExecution": "all",
        "saveManualExecutions": True,
    },
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes")
