"""Build the Arkon Incident Status API n8n workflow JSON.

The workflow is written from a script rather than by hand so the two Code-node
bodies stay readable and quoting stays under control.
"""

import json
import pathlib

from lifecycle import FOLD_JS, js_constants

OUT = pathlib.Path(__file__).resolve().parent.parent / "incident_status_api_v1.json"

STORE_PATH = "/data/arkon/incidents.jsonl"
TRANSITION_STORE = "/data/arkon/incident_transitions.jsonl"

PARSE_QUERY = (
    r"""// Arkon Incident Status API - request parsing and validation.
// Every query parameter is optional; the contract is documented in n8n/README.md.
// Invalid input is rejected here so the agent gets a precise reason instead of
// an empty result it might read as "no incident exists".
"""
    + js_constants()
    + r"""
const PRIORITIES = ["P1", "P2", "P3", "P4"];
const MAX_LIMIT = 50;
const DEFAULT_LIMIT = 5;

const params = $input.first().json.query ?? {};
const errors = [];

const raw = (key) => {
  const value = params[key];
  if (value === undefined || value === null) return null;
  const text = String(Array.isArray(value) ? value[0] : value).trim();
  return text === "" ? null : text;
};

// incident_id: accepts ARK-INC-00014, ark-inc-14, or a bare number
let incidentId = raw("incident_id");
if (incidentId !== null) {
  const digits = incidentId.replace(/[^0-9]/g, "");
  if (!/^(ARK-INC-)?[0-9]+$/i.test(incidentId) || digits === "") {
    errors.push("incident_id must look like ARK-INC-00014 or be a plain number");
    incidentId = null;
  } else {
    incidentId = "ARK-INC-" + digits.padStart(5, "0");
  }
}

// unit: CMAPSS only. Matched against the unit token of a record id shaped like
// FD001-Unit-092. Take the last hyphen-separated token first: a full record id
// carries digits in its subset prefix too, and reading them all would turn
// FD001-Unit-092 into 1092. A module whose record ids are not engine units is
// filtered with record_id instead, and a unit query never matches one.
let unit = raw("unit");
if (unit !== null) {
  const token = unit.split("-").pop().trim();
  const digits = token.replace(/[^0-9]/g, "");
  unit = digits === "" ? token.toUpperCase() : String(parseInt(digits, 10));
}

// record_id, source_module, business_domain: contract fields every module has,
// so these three work whatever produced the incident.
const recordId = raw("record_id");
const sourceModule = raw("source_module");
const businessDomain = raw("business_domain");

// priority: one or more of P1..P4, comma separated
let priority = [];
const priorityRaw = raw("priority");
if (priorityRaw !== null) {
  priority = priorityRaw.split(",").map((p) => p.trim().toUpperCase()).filter(Boolean);
  const unknown = priority.filter((p) => !PRIORITIES.includes(p));
  if (unknown.length) {
    errors.push("priority must be one of " + PRIORITIES.join(", ") + "; got " + unknown.join(", "));
    priority = [];
  }
}

// status: a value from the charter 7.2 incident lifecycle
let status = raw("status");
if (status !== null) {
  status = status.toLowerCase();
  if (!LIFECYCLE.includes(status)) {
    errors.push("status must be one of " + LIFECYCLE.join(", "));
    status = null;
  }
}

let limit = DEFAULT_LIMIT;
const limitRaw = raw("limit");
if (limitRaw !== null) {
  if (!/^[0-9]+$/.test(limitRaw)) {
    errors.push("limit must be a whole number");
  } else {
    limit = parseInt(limitRaw, 10);
    if (limit < 1 || limit > MAX_LIMIT) {
      errors.push("limit must be between 1 and " + MAX_LIMIT);
      limit = DEFAULT_LIMIT;
    }
  }
}

// Test affordance only: lets the agent's failure path be demonstrated on demand
// without unpublishing the workflow. A production deployment removes it or puts
// it behind an operator role.
const simulateFailure = ["1", "true", "yes"].includes((raw("simulate_failure") ?? "").toLowerCase());

return [
  {
    json: {
      valid: errors.length === 0,
      errors,
      simulate_failure: simulateFailure,
      query: { incident_id: incidentId, unit, record_id: recordId, source_module: sourceModule, business_domain: businessDomain, priority, status, limit },
    },
  },
];
"""
)

FILTER_INCIDENTS = (
    r"""// Arkon Incident Status API - answer the query from the JSONL incident store.
// Response times come from charter 7.1, the status vocabulary from charter 7.2.
//
// The incident line is written once, at new, and never rewritten, so a status
// read off it is the status the incident was raised with. Every status below is
// the fold of the transition log onto that line: current state, the three
// milestone timestamps, and the response times computed from them.
"""
    + js_constants()
    + FOLD_JS
    + r"""
const request = $("Parse Query").first().json;
const filters = request.query;
const storeText = $("Extract Store Text").first().json.store_text ?? "";
const transitionsText = $("Extract Transitions Text").first().json.transitions_text ?? "";
const now = new Date();

const lines = storeText.split("\n").map((line) => line.trim()).filter(Boolean);
const incidents = [];
let unreadableLines = 0;
for (const line of lines) {
  try {
    incidents.push(JSON.parse(line));
  } catch (error) {
    unreadableLines += 1;
  }
}

// Fold once per incident, keyed by the parsed object rather than by id, so two
// store lines carrying the same id cannot share one answer.
const transitions = arkonTransitionsById(transitionsText);
const folded = new Map();
for (const incident of incidents) {
  folded.set(incident, arkonFold(incident, transitions.byId));
}
const lifecycleOf = (incident) => folded.get(incident);
const statusOf = (incident) => lifecycleOf(incident).status;

const recordIdOf = (incident) => String(incident.event?.evidence?.record_id ?? "");

// A CMAPSS record id is FD<digits>-Unit-<token>. The prefix is the module
// marker; the token after it is the unit and is not always numeric, because the
// attribution test wrote FD001-Unit-ATTRTEST. Only these carry an engine unit;
// SCANIA-APS-000056 is a service record and has none, and reporting its last
// token as a "unit" is how a field that reads fine comes to mean nothing.
const CMAPSS_RECORD = /^FD\d+-Unit-.+$/i;
const unitToken = (incident) => {
  const recordId = recordIdOf(incident);
  return CMAPSS_RECORD.test(recordId) ? recordId.split("-").pop() : null;
};

const ageMinutes = (incident) => {
  const created = Date.parse(incident.created_at ?? "");
  return Number.isNaN(created) ? null : Math.round((now.getTime() - created) / 60000);
};

// Overdue means still unacknowledged past the charter 7.1 window. Before the
// transition log existed every incident read new for ever, so this counted the
// whole store and meant nothing; it is a real measurement now.
const isOverdue = (incident) => {
  const window = ACK_WINDOW_MINUTES[String(incident.priority ?? "").toUpperCase()];
  if (window === undefined) return false;
  if (statusOf(incident) !== "new") return false;
  const age = ageMinutes(incident);
  return age !== null && age > window;
};

const matches = (incident) => {
  if (filters.incident_id && incident.incident_id !== filters.incident_id) return false;
  if (filters.status && statusOf(incident) !== filters.status) return false;
  if (filters.priority.length && !filters.priority.includes(String(incident.priority ?? "").toUpperCase())) {
    return false;
  }
  if (filters.record_id
      && recordIdOf(incident).toUpperCase() !== String(filters.record_id).toUpperCase()) {
    return false;
  }
  if (filters.source_module
      && String(incident.source_module ?? "").toLowerCase() !== String(filters.source_module).toLowerCase()) {
    return false;
  }
  if (filters.business_domain
      && String(incident.business_domain ?? "").toLowerCase() !== String(filters.business_domain).toLowerCase()) {
    return false;
  }
  if (filters.unit) {
    const token = unitToken(incident);
    if (token === null) return false;
    const tokenDigits = token.replace(/[^0-9]/g, "");
    const filterDigits = String(filters.unit).replace(/[^0-9]/g, "");
    if (tokenDigits !== "" && filterDigits !== "") {
      if (parseInt(tokenDigits, 10) !== parseInt(filterDigits, 10)) return false;
    } else if (token.toUpperCase() !== String(filters.unit).toUpperCase()) {
      return false;
    }
  }
  return true;
};

const project = (incident) => ({
  incident_id: incident.incident_id,
  created_at: incident.created_at,
  age_minutes: ageMinutes(incident),
  // The folded status, not the one on the store line. raised_as is the store
  // line's own value and is always new; it is returned so a reader who opens the
  // JSONL and sees a different word knows the two are not in conflict.
  status: statusOf(incident),
  raised_as: lifecycleOf(incident).stored_status,
  lifecycle: {
    transition_count: lifecycleOf(incident).transition_count,
    is_terminal: lifecycleOf(incident).is_terminal,
    acknowledged_at: lifecycleOf(incident).acknowledged_at,
    resolved_at: lifecycleOf(incident).resolved_at,
    closed_at: lifecycleOf(incident).closed_at,
    minutes_to_acknowledge: lifecycleOf(incident).minutes_to_acknowledge,
    minutes_to_resolve: lifecycleOf(incident).minutes_to_resolve,
    minutes_to_close: lifecycleOf(incident).minutes_to_close,
    history: lifecycleOf(incident).history,
  },
  priority: incident.priority,
  unit: unitToken(incident),
  record_id: recordIdOf(incident) || null,
  summary: incident.summary,
  recommended_action: incident.recommended_action,
  acknowledge_due_minutes: ACK_WINDOW_MINUTES[String(incident.priority ?? "").toUpperCase()] ?? null,
  overdue: isOverdue(incident),
  source_module: incident.source_module,
  business_domain: incident.business_domain,
  assigned_to: incident.assigned_to,
  assigned_role: incident.assigned_role,
  escalation_contact: incident.escalation_contact,
  event_id: incident.event?.event_id ?? null,
  risk_score: incident.event?.risk_score ?? null,
  // The evidence object as the module published it. Every module fills this and
  // no consumer has to know which one did.
  evidence: incident.event?.evidence ?? null,
  // predicted_rul is a CMAPSS word and only a CMAPSS record has one. It used to
  // be filled from evidence.prediction whatever the module was, so a Scania
  // failure probability of 0.0373 was served as a remaining useful life of
  // 0.0373 cycles, and the assistant read it out as one. Nothing failed.
  predicted_rul: CMAPSS_RECORD.test(recordIdOf(incident))
    ? (incident.event?.evidence?.prediction ?? null)
    : null,
  priority_threshold: CMAPSS_RECORD.test(recordIdOf(incident))
    ? (incident.event?.evidence?.threshold ?? null)
    : null,
  model_version: incident.event?.evidence?.model_version ?? null,
  data_origin: incident.event?.context_origin ?? null,
  operational_context_origin: incident.event?.operational_context?.context_origin ?? null,
});

const byPriority = {};
const byStatus = {};
for (const incident of incidents) {
  const key = String(incident.priority ?? "unknown").toUpperCase();
  byPriority[key] = (byPriority[key] ?? 0) + 1;
  const state = statusOf(incident);
  byStatus[state] = (byStatus[state] ?? 0) + 1;
}

// Response-time KPIs, charter 7.2. The median rather than the mean, because one
// incident acknowledged the next morning would otherwise move the number more
// than every incident acknowledged on time.
const median = (values) => {
  const sorted = values.filter((v) => v !== null && v !== undefined).sort((a, b) => a - b);
  if (!sorted.length) return null;
  const middle = Math.floor(sorted.length / 2);
  const value = sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return Math.round(value * 10) / 10;
};

const ackMinutes = [];
const closeMinutes = [];
let acknowledgedInWindow = 0;
let acknowledgedLate = 0;
for (const incident of incidents) {
  const life = lifecycleOf(incident);
  if (life.minutes_to_acknowledge !== null) {
    ackMinutes.push(life.minutes_to_acknowledge);
    const window = ACK_WINDOW_MINUTES[String(incident.priority ?? "").toUpperCase()];
    if (window !== undefined) {
      if (life.minutes_to_acknowledge <= window) acknowledgedInWindow += 1;
      else acknowledgedLate += 1;
    }
  }
  if (life.minutes_to_close !== null) closeMinutes.push(life.minutes_to_close);
}

const hits = incidents
  .filter(matches)
  .sort((a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? "")));
const page = hits.slice(0, filters.limit).map(project);

return [
  {
    json: {
      status: hits.length ? "ok" : "no_match",
      message: hits.length
        ? hits.length + " incident(s) match the query, " + page.length + " returned."
        : "No incident in the store matches the query.",
      as_of: now.toISOString(),
      query: filters,
      store: {
        path: "__STORE_PATH__",
        total_incidents: incidents.length,
        unreadable_lines: unreadableLines,
        incidents_by_priority: byPriority,
        incidents_by_status: byStatus,
        open_incidents: incidents.filter((i) => OPEN_STATUSES.includes(statusOf(i))).length,
        overdue_incidents: incidents.filter(isOverdue).length,
      },
      transitions: {
        path: "__TRANSITION_STORE__",
        total_transitions: Object.values(transitions.byId).reduce((sum, list) => sum + list.length, 0),
        incidents_with_transitions: Object.keys(transitions.byId).length,
        unreadable_lines: transitions.unreadable,
      },
      response_times: {
        acknowledged_incidents: ackMinutes.length,
        median_minutes_to_acknowledge: median(ackMinutes),
        acknowledged_within_window: acknowledgedInWindow,
        acknowledged_late: acknowledgedLate,
        closed_incidents: closeMinutes.length,
        median_minutes_to_close: median(closeMinutes),
      },
      match_count: hits.length,
      returned: page.length,
      incidents: page,
    },
  },
];
"""
).replace("__STORE_PATH__", STORE_PATH).replace("__TRANSITION_STORE__", TRANSITION_STORE)


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


workflow = {
    "id": "arkonStatusApi1",
    "name": "Arkon Incident Status API v1",
    "nodes": [
        {
            "id": "a1000000-0000-4000-8000-000000000001",
            "name": "Status Request",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1328, 240],
            "webhookId": "arkon-incident-status",
            "parameters": {
                "httpMethod": "GET",
                "path": "arkon-incident-status",
                "responseMode": "responseNode",
                "options": {},
            },
        },
        {
            "id": "a1000000-0000-4000-8000-000000000002",
            "name": "Parse Query",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-1104, 240],
            "parameters": {"jsCode": PARSE_QUERY},
        },
        if_node(
            "a1000000-0000-4000-8000-000000000003",
            "Valid Request?",
            [-880, 240],
            "={{ $json.valid }}",
        ),
        respond_node(
            "a1000000-0000-4000-8000-000000000004",
            "Respond Bad Request",
            [-656, 416],
            '={{ JSON.stringify({status: "rejected", errors: $json.errors}) }}',
            400,
        ),
        if_node(
            "a1000000-0000-4000-8000-000000000005",
            "Simulated Failure?",
            [-656, 160],
            "={{ $json.simulate_failure }}",
        ),
        respond_node(
            "a1000000-0000-4000-8000-000000000006",
            "Respond Unavailable",
            [-432, -16],
            '={{ JSON.stringify({status: "unavailable", message: "Incident store lookup failed (simulated failure requested by the caller)."}) }}',
            503,
        ),
        {
            "id": "a1000000-0000-4000-8000-000000000007",
            "name": "Read Incident Store",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [-432, 224],
            "onError": "continueErrorOutput",
            "parameters": {
                "operation": "read",
                "fileSelector": STORE_PATH,
                "options": {},
            },
        },
        respond_node(
            "a1000000-0000-4000-8000-000000000008",
            "Respond Store Unavailable",
            [-208, 416],
            '={{ JSON.stringify({status: "unavailable", message: "The incident store could not be read."}) }}',
            503,
        ),
        {
            "id": "a1000000-0000-4000-8000-000000000009",
            "name": "Extract Store Text",
            "type": "n8n-nodes-base.extractFromFile",
            "typeVersion": 1.1,
            "position": [-208, 224],
            "parameters": {
                "operation": "text",
                "binaryPropertyName": "data",
                "destinationKey": "store_text",
                "options": {},
            },
        },
        {
            "id": "a1000000-0000-4000-8000-00000000000c",
            "name": "Read Transition Store",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [16, 224],
            "onError": "continueErrorOutput",
            "parameters": {
                "operation": "read",
                "fileSelector": TRANSITION_STORE,
                "options": {},
            },
        },
        # An unreadable transition log is a 503, not an empty log. Reading it as
        # empty would report every incident as new with a 200, and a wrong status
        # served confidently is the one answer this endpoint exists to prevent.
        respond_node(
            "a1000000-0000-4000-8000-00000000000d",
            "Respond Transition Log Unavailable",
            [240, 416],
            '={{ JSON.stringify({status: "unavailable", message: "The incident transition log could not be read, so no incident status could be determined."}) }}',
            503,
        ),
        {
            "id": "a1000000-0000-4000-8000-00000000000e",
            "name": "Extract Transitions Text",
            "type": "n8n-nodes-base.extractFromFile",
            "typeVersion": 1.1,
            "position": [240, 224],
            "parameters": {
                "operation": "text",
                "binaryPropertyName": "data",
                "destinationKey": "transitions_text",
                "options": {},
            },
        },
        {
            "id": "a1000000-0000-4000-8000-00000000000a",
            "name": "Filter Incidents",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [464, 224],
            "parameters": {"jsCode": FILTER_INCIDENTS},
        },
        respond_node(
            "a1000000-0000-4000-8000-00000000000b",
            "Respond Status",
            [688, 224],
            "={{ JSON.stringify($json) }}",
        ),
    ],
    "connections": {
        "Status Request": {"main": [[{"node": "Parse Query", "type": "main", "index": 0}]]},
        "Parse Query": {"main": [[{"node": "Valid Request?", "type": "main", "index": 0}]]},
        "Valid Request?": {
            "main": [
                [{"node": "Simulated Failure?", "type": "main", "index": 0}],
                [{"node": "Respond Bad Request", "type": "main", "index": 0}],
            ]
        },
        "Simulated Failure?": {
            "main": [
                [{"node": "Respond Unavailable", "type": "main", "index": 0}],
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
        "Extract Transitions Text": {"main": [[{"node": "Filter Incidents", "type": "main", "index": 0}]]},
        "Filter Incidents": {"main": [[{"node": "Respond Status", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1", "binaryMode": "separate", "availableInMCP": False},
    "pinData": {},
}

OUT.write_text(json.dumps(workflow, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print("written", OUT, OUT.stat().st_size, "bytes")
