"""Build the Arkon Incident Status API n8n workflow JSON.

The workflow is written from a script rather than by hand so the Code-node
bodies stay readable and quoting stays under control.

Since 2026-09-07 it answers from the queryable store of charter 7.5: the three
n8n data tables the store sync keeps level with the two JSONL logs
(`build_store_sync_workflow.py`, `store_schema.py`). The contract is the one of
2026-08-30 unchanged - the same parameters, the same four answers, the same
per-incident projection and the same store summary - and what changed is the
cost: a request reads the rows its filter names plus the one summary row,
instead of parsing both logs whole and folding every incident on every call.
The two clock-dependent fields, `age_minutes` and `overdue`, are still computed
at read time, so an incident going overdue between two writes is reported as
overdue without any sync.

Since 2026-09-09 the contract has one more filter and one more convenience, and
both exist for the same reason: the assistant could not answer "how many
incidents do I have", so it answered for the whole plant instead. `assigned_to`
(`assignee` is the same parameter) filters by the person an incident is assigned
to, and `status=open` expands to the three non-terminal states rather than
forcing three calls. `match_summary` describes the matched set the way `store`
describes the plant, so a count does not require paging every hit to the caller,
and `sort=priority` returns the page in the order the work is done, because a
model asked to sort the page itself put three P3 incidents above six P2 ones and
called the result ordered.
"""

import json
import pathlib

from lifecycle import js_constants
from store_schema import INCIDENTS_TABLE, ROW_TO_API_JS, SUMMARY_KEY, SUMMARY_TABLE

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
const MAX_LIMIT = 500;
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

// assigned_to: the person an incident is assigned to, as the roster writes it
// ("A. Novak"). `assignee` is accepted as the same parameter, because that is
// the word an operator and an agent reach for. Inner whitespace is collapsed so
// the contains match on the row stays a superset of the exact rule applied later.
let assignedTo = raw("assigned_to") ?? raw("assignee");
if (assignedTo !== null) assignedTo = assignedTo.replace(/\s+/g, " ");

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

// status: a value from the charter 7.2 incident lifecycle, or the word `open`
// for the three states an incident can still move out of. `open` is not a stored
// value and never was: it is expanded here, so "what is still open" is one call
// instead of three, and the store summary's own definition of open is the one
// used. statusSet is what the answer node tests; status is what the query echoes.
let status = raw("status");
let statusSet = [];
if (status !== null) {
  status = status.toLowerCase();
  if (status === "open") {
    statusSet = OPEN_STATUSES.slice();
  } else if (!LIFECYCLE.includes(status)) {
    errors.push("status must be one of " + LIFECYCLE.join(", ") + ", or open");
    status = null;
  } else {
    statusSet = [status];
  }
}

// sort: `recent` is the contract's original order, newest first. `priority` is
// the order an operator works a list in, P1 first and the oldest of a priority
// first, and it is computed here because a model asked to sort a page of
// incidents itself gets it wrong while still calling the result ordered.
let sort = (raw("sort") ?? "recent").toLowerCase();
if (!["recent", "priority"].includes(sort)) {
  errors.push("sort must be recent or priority");
  sort = "recent";
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

// The one condition the data table answers, the most selective filter first;
// every other filter is applied to the rows it returns. A contains match (ilike)
// is a superset that the answer node narrows to the exact rule, so the row read
// stays one condition wide. Without any filter the table returns the newest
// `limit` rows and the summary row supplies the count.
let dbFilter;
if (incidentId) dbFilter = { column: "incident_id", condition: "eq", value: incidentId, return_all: true };
else if (statusSet.length === 1) dbFilter = { column: "status", condition: "eq", value: statusSet[0], return_all: true };
else if (assignedTo) dbFilter = { column: "assigned_to", condition: "ilike", value: assignedTo, return_all: true };
else if (priority.length === 1) dbFilter = { column: "priority", condition: "eq", value: priority[0], return_all: true };
else if (sourceModule) dbFilter = { column: "source_module", condition: "ilike", value: sourceModule, return_all: true };
else if (businessDomain) dbFilter = { column: "business_domain", condition: "ilike", value: businessDomain, return_all: true };
else if (recordId) dbFilter = { column: "record_id", condition: "ilike", value: recordId, return_all: true };
else if (unit) dbFilter = { column: "unit", condition: "ilike", value: unit, return_all: true };
else if (priority.length > 1 || statusSet.length > 1 || sort === "priority") dbFilter = { column: "incident_id", condition: "isNotEmpty", value: "", return_all: true };
else dbFilter = { column: "incident_id", condition: "isNotEmpty", value: "", return_all: false };
dbFilter.limit = limit;

return [
  {
    json: {
      valid: errors.length === 0,
      errors,
      simulate_failure: simulateFailure,
      query: { incident_id: incidentId, unit, record_id: recordId, source_module: sourceModule, business_domain: businessDomain, assigned_to: assignedTo, priority, status, status_set: statusSet, sort, limit },
      db_filter: dbFilter,
    },
  },
];
"""
)

ANSWER_QUERY = (
    r"""// Arkon Incident Status API - answer the query from the queryable store.
// Response times come from charter 7.1, the status vocabulary from charter 7.2.
//
// The rows are the store sync's projection of the two JSONL logs: the incident
// line with the transition log folded onto it (charter 7.2), written by the
// sync after every append. `status` on a row is that fold; `raised_as` is what
// the incident line itself says, which is always new. The two fields that
// depend on the clock, age and overdue, are computed here on every read.
"""
    + js_constants()
    + ROW_TO_API_JS
    + r"""
const request = $("Parse Query").first().json;
const filters = request.query;
const now = new Date();

const isRow = (json) => json && typeof json === "object" && typeof json.incident_id === "string";
const summary = $("Get Summary").all().map((item) => item.json).find((row) => row && row.key === "__SUMMARY_KEY__") ?? {};
const matchRows = $("Get Matches").all().map((item) => item.json).filter(isRow);
const openRows = $("Get Open").all().map((item) => item.json).filter(isRow);

const parse = (text, fallback) => {
  if (text === null || text === undefined || text === "") return fallback;
  try {
    return JSON.parse(text);
  } catch (error) {
    return fallback;
  }
};
const number = (value) => (value === null || value === undefined || value === "" ? null : Number(value));

const incidents = matchRows.map((row) => arkonRowToIncident(row, now));

// A roster name is "A. Novak". Compare it whole, or by one of its own tokens, so
// that "Novak" finds the same person and "ova" finds nobody: a person filter that
// matched any substring would quietly answer for the wrong operator.
const nameKey = (value) => String(value ?? "").toLowerCase().replace(/\s+/g, " ").trim();

// The exact rules of the contract, over the superset the one table condition
// returned. Same rules as before the move, so a filter answers the same way.
const matches = (incident) => {
  if (filters.incident_id && incident.incident_id !== filters.incident_id) return false;
  if (filters.status_set && filters.status_set.length && !filters.status_set.includes(incident.status)) return false;
  if (filters.assigned_to) {
    const held = nameKey(incident.assigned_to);
    const wanted = nameKey(filters.assigned_to);
    if (held !== wanted && !held.split(" ").includes(wanted)) return false;
  }
  if (filters.priority.length && !filters.priority.includes(String(incident.priority ?? "").toUpperCase())) {
    return false;
  }
  if (filters.record_id
      && String(incident.record_id ?? "").toUpperCase() !== String(filters.record_id).toUpperCase()) {
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
    const token = incident.unit;
    if (token === null || token === undefined) return false;
    const tokenDigits = String(token).replace(/[^0-9]/g, "");
    const filterDigits = String(filters.unit).replace(/[^0-9]/g, "");
    if (tokenDigits !== "" && filterDigits !== "") {
      if (parseInt(tokenDigits, 10) !== parseInt(filterDigits, 10)) return false;
    } else if (String(token).toUpperCase() !== String(filters.unit).toUpperCase()) {
      return false;
    }
  }
  return true;
};

// Newest first, or the order the work is done in: P1 before P2, and inside a
// priority the oldest first, so the head of the page is the head of the list.
const newestFirst = (a, b) => String(b.created_at ?? "").localeCompare(String(a.created_at ?? ""));
const rank = { P1: 1, P2: 2, P3: 3, P4: 4 };
const byPriority = (a, b) => {
  const left = rank[String(a.priority ?? "").toUpperCase()] ?? 9;
  const right = rank[String(b.priority ?? "").toUpperCase()] ?? 9;
  return left !== right ? left - right : String(a.created_at ?? "").localeCompare(String(b.created_at ?? ""));
};
const hits = incidents.filter(matches).sort(filters.sort === "priority" ? byPriority : newestFirst);
const page = hits.slice(0, filters.limit);

// Without a filter the table returned only the newest page, and the count of
// everything is the summary's, which the sync computed over every incident.
const matchCount = request.db_filter.return_all ? hits.length : (number(summary.total_incidents) ?? hits.length);

// The store summary is the whole plant and stays that way, whatever was asked.
// This one describes the matched set instead, so a caller that filtered - by
// assignee above all - can report counts without paging every hit into its own
// context. Null when the read was the newest page rather than every match,
// because counting a page and calling it a total is the defect it exists to stop.
const tally = (values) => values.reduce((counts, value) => {
  const key = value === null || value === undefined || value === "" ? "unknown" : String(value);
  counts[key] = (counts[key] ?? 0) + 1;
  return counts;
}, {});
const matchSummary = request.db_filter.return_all
  ? {
      total: hits.length,
      open: hits.filter((incident) => OPEN_STATUSES.includes(incident.status)).length,
      overdue: hits.filter((incident) => incident.overdue).length,
      by_status: tally(hits.map((incident) => incident.status)),
      by_priority: tally(hits.map((incident) => incident.priority)),
    }
  : null;

// Overdue is live: the new incidents past their window right now, not at the
// last sync. Everything else in the summary changes only when a line is written,
// and every written line is followed by a sync.
const overdueNow = openRows.map((row) => arkonRowToIncident(row, now)).filter((incident) => incident.overdue).length;
const syncedAt = Date.parse(summary.synced_at ?? "");
const syncLagSeconds = Number.isNaN(syncedAt) ? null : Math.max(0, Math.round((now.getTime() - syncedAt) / 1000));

return [
  {
    json: {
      status: matchCount ? "ok" : "no_match",
      message: matchCount
        ? matchCount + " incident(s) match the query, " + page.length + " returned."
        : "No incident in the store matches the query.",
      as_of: now.toISOString(),
      query: filters,
      store: {
        path: "__STORE_PATH__",
        total_incidents: number(summary.total_incidents) ?? 0,
        unreadable_lines: number(summary.incidents_unreadable) ?? 0,
        incidents_by_priority: parse(summary.incidents_by_priority_json, {}),
        incidents_by_status: parse(summary.incidents_by_status_json, {}),
        open_incidents: number(summary.open_incidents) ?? 0,
        overdue_incidents: overdueNow,
        projection: "n8n data tables __INCIDENTS_TABLE__, arkon_transitions, __SUMMARY_TABLE__",
        synced_at: summary.synced_at ?? null,
        sync_mode: summary.sync_mode ?? null,
        sync_lag_seconds: syncLagSeconds,
      },
      transitions: {
        path: "__TRANSITION_STORE__",
        total_transitions: number(summary.total_transitions) ?? 0,
        incidents_with_transitions: number(summary.incidents_with_transitions) ?? 0,
        unreadable_lines: number(summary.transitions_unreadable) ?? 0,
      },
      response_times: parse(summary.response_times_json, {}),
      match_count: matchCount,
      match_summary: matchSummary,
      returned: page.length,
      incidents: page,
    },
  },
];
"""
).replace("__STORE_PATH__", STORE_PATH).replace("__TRANSITION_STORE__", TRANSITION_STORE) \
    .replace("__SUMMARY_KEY__", SUMMARY_KEY).replace("__INCIDENTS_TABLE__", INCIDENTS_TABLE) \
    .replace("__SUMMARY_TABLE__", SUMMARY_TABLE)


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


def get_rows(node_id, name, position, table, conditions, return_all, limit=None, order_by=False, execute_once=False):
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
    if order_by:
        node["parameters"]["orderBy"] = True
        node["parameters"]["orderByColumn"] = "created_at"
        node["parameters"]["orderByDirection"] = "DESC"
    if execute_once:
        node["executeOnce"] = True
    return node


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
        # The one summary row. A table that cannot be read is a 503, the same
        # answer an unreadable file used to get: nothing about incident state may
        # be inferred from a lookup that failed.
        get_rows(
            "a1000000-0000-4000-8000-000000000007",
            "Get Summary",
            [-432, 224],
            SUMMARY_TABLE,
            [{"keyName": "key", "condition": "eq", "keyValue": SUMMARY_KEY}],
            return_all=False,
            limit=1,
        ),
        respond_node(
            "a1000000-0000-4000-8000-000000000008",
            "Respond Store Unavailable",
            [-208, 416],
            '={{ JSON.stringify({status: "unavailable", message: "The incident store could not be read (the store data tables did not answer)."}) }}',
            503,
        ),
        # No summary row means no sync has run since the tables were created: a
        # store that exists but has never been filled must not answer "empty".
        if_node(
            "a1000000-0000-4000-8000-000000000009",
            "Store Synced?",
            [-208, 224],
            '={{ $json.key === "' + SUMMARY_KEY + '" }}',
        ),
        respond_node(
            "a1000000-0000-4000-8000-00000000000c",
            "Respond Store Not Synced",
            [16, 416],
            '={{ JSON.stringify({status: "unavailable", message: "The incident store has not been synced yet (no summary row), so no incident status could be determined. Run the store sync."}) }}',
            503,
        ),
        # The new incidents, for the live overdue count. Bounded by what the crew
        # has not yet acknowledged, whatever the size of the store.
        get_rows(
            "a1000000-0000-4000-8000-00000000000d",
            "Get Open",
            [16, 224],
            INCIDENTS_TABLE,
            [{"keyName": "status", "condition": "eq", "keyValue": "new"}],
            return_all=True,
            execute_once=True,
        ),
        respond_node(
            "a1000000-0000-4000-8000-00000000000e",
            "Respond Rows Unavailable",
            [240, 416],
            '={{ JSON.stringify({status: "unavailable", message: "The incident store could not be read (the incidents table did not answer)."}) }}',
            503,
        ),
        # The rows the query names, one condition wide, newest first. Without a
        # filter, only the newest page.
        get_rows(
            "a1000000-0000-4000-8000-00000000000f",
            "Get Matches",
            [240, 224],
            INCIDENTS_TABLE,
            [
                {
                    "keyName": "={{ $('Parse Query').first().json.db_filter.column }}",
                    "condition": "={{ $('Parse Query').first().json.db_filter.condition }}",
                    "keyValue": "={{ $('Parse Query').first().json.db_filter.value }}",
                }
            ],
            return_all="={{ $('Parse Query').first().json.db_filter.return_all }}",
            limit="={{ $('Parse Query').first().json.db_filter.limit }}",
            order_by=True,
            execute_once=True,
        ),
        {
            "id": "a1000000-0000-4000-8000-00000000000a",
            "name": "Answer Query",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [464, 224],
            "parameters": {"jsCode": ANSWER_QUERY},
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
                [{"node": "Get Open", "type": "main", "index": 0}],
                [{"node": "Respond Store Not Synced", "type": "main", "index": 0}],
            ]
        },
        "Get Open": {
            "main": [
                [{"node": "Get Matches", "type": "main", "index": 0}],
                [{"node": "Respond Rows Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Get Matches": {
            "main": [
                [{"node": "Answer Query", "type": "main", "index": 0}],
                [{"node": "Respond Rows Unavailable", "type": "main", "index": 0}],
            ]
        },
        "Answer Query": {"main": [[{"node": "Respond Status", "type": "main", "index": 0}]]},
    },
    # A read endpoint called every few seconds by the cockpit, the plant and the
    # timers is not worth an execution record per successful call; those records
    # had grown n8n's database to 3.6 GB in eight days. Failures are kept.
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
