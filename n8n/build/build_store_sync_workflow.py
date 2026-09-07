"""Build the Arkon Store Sync n8n workflow JSON: the queryable incident store of
charter 7.5, kept as three n8n data tables.

What it is and what it is not. The record of truth stays the two append-only
JSONL logs on the NAS: `incidents.jsonl`, written once per incident at `new`, and
`incident_transitions.jsonl`, appended by every lifecycle move. Nothing about
the write paths changes. What this workflow adds is a projection of both logs
into n8n's own data tables (`store_schema.py`): one row per incident carrying
the folded lifecycle, one row per transition, and one summary row with the
store-wide numbers the status API used to recompute on every request. The API
then reads rows instead of parsing both logs whole, which was charter 7.5's
reason for the move: the per-request fold was linear in the size of both files.

Four decisions.

- **The sync runs after every write, not on a clock.** The Steering Cell and the
  transition endpoint call this workflow through an Execute Sub-workflow node
  without waiting for it, so the projection is current seconds after a line is
  appended and no request path ever waits for a fold. A webhook exists for a
  person or a script (`POST /webhook/arkon-store-sync`, `{"rebuild": true}` to
  start from empty tables), and `n8n execute --id=arkonStoreSync1` starts it
  from the command line, because that command starts from an Execute Workflow
  Trigger and from nothing else.
- **Every run folds the whole store and writes only what changed.** The fold
  is `lifecycle.py`, injected verbatim, so the sync, the transition endpoint and
  the escalation record cannot disagree about a status. The summary row is
  recomputed from that full fold every time, so it can never drift from the
  logs; the row writes are limited to new incident lines and to incidents a new
  transition line touched, using the two line counters the summary row carries.
  Reading both files whole per sync is the linear cost that remains, and it is
  named as the boundary: the file node has no offset read.
- **A rebuild is the same run from empty tables.** `rebuild: true` deletes every
  row first; the fold and the writes are identical. The projection is therefore
  always derivable from the logs by one call, which is what makes it a
  projection rather than a second record of truth. A plant reset that archives
  the logs is followed by one rebuild.
- **Successful runs are not stored as executions.** A run carries both logs as
  text, and the status API's executions had grown n8n's database to 3.6 GB in
  eight days for exactly that reason. The sync writes its own one-line record to
  `/data/arkon/store_sync.jsonl` instead, with the summary numbers and the row
  counts; failed executions are kept.

    py n8n/build/build_store_sync_workflow.py
    py n8n/build/check_store_sync_js.py
"""

import json
import pathlib

from lifecycle import FOLD_JS, js_constants
from store_schema import (
    INCIDENTS_TABLE, PROJECT_JS, SUMMARY_KEY, SUMMARY_TABLE, TABLES, TRANSITIONS_TABLE,
    js_column_lists,
)

OUT = pathlib.Path(__file__).resolve().parent.parent / "store_sync_v1.json"

WORKFLOW_ID = "arkonStoreSync1"
STORE_PATH = "/data/arkon/incidents.jsonl"
TRANSITION_STORE = "/data/arkon/incident_transitions.jsonl"
SYNC_LOG = "/data/arkon/store_sync.jsonl"

READ_REQUEST = r"""// Arkon Store Sync - what kind of run this is.
// Three ways in: a caller workflow (the Steering Cell after it appended an
// incident, the transition endpoint after it appended a move), the webhook for a
// person or a script, and the command line. Only the webhook can ask for a
// rebuild, and the source is recorded on the sync line.
const first = $input.first().json ?? {};
const isWebhook = first.headers !== undefined && (first.body !== undefined || first.query !== undefined);
const body = isWebhook ? (first.body && typeof first.body === "object" ? first.body : {}) : first;
const rebuild = ["1", "true", "yes"].includes(String(body.rebuild ?? "").toLowerCase());
const source = isWebhook ? "webhook" : String(first.source ?? "").trim() || "command_line";
return [{ json: { rebuild, source } }];
"""

FOLD_STORE = (
    r"""// Arkon Store Sync - fold both logs, then decide which rows to write.
// The incident line is written once, at new, and never rewritten; the current
// status of an incident is the fold of the transition log onto that line
// (charter 7.2). This node folds every incident, computes the store summary
// from all of them, and emits rows only for what the last sync had not seen:
// new incident lines, and every incident a new transition line touched. On a
// rebuild, or when no summary row exists yet, everything is a row.
"""
    + js_constants()
    + FOLD_JS
    + PROJECT_JS
    + js_column_lists()
    + r"""
const request = $("Read Request").first().json;
const storeText = $("Extract Store Text").first().json.store_text ?? "";
const transitionsText = $("Extract Transitions Text").first().json.transitions_text ?? "";
const summaryRows = $("Get Summary").all().map((item) => item.json).filter((row) => row && row.key === "__SUMMARY_KEY__");
const previous = request.rebuild || !summaryRows.length ? null : summaryRows[0];
const started = Date.now();
const now = new Date();
const syncedAt = now.toISOString();

// Every non-empty line gets an ordinal, readable or not: the summary records how
// many lines the sync had seen, and the next sync starts after that many.
const incidents = [];
let incidentLines = 0;
let incidentsUnreadable = 0;
for (const raw of storeText.split("\n")) {
  const line = raw.trim();
  if (!line) continue;
  incidentLines += 1;
  try {
    const incident = JSON.parse(line);
    if (!incident || typeof incident !== "object" || !incident.incident_id) {
      incidentsUnreadable += 1;
      continue;
    }
    incidents.push({ incident, line: incidentLines });
  } catch (error) {
    incidentsUnreadable += 1;
  }
}

// The same parse for transitions, grouped by incident for the fold and kept in
// log order for the rows. The rule for a damaged line is the fold's own: count
// it, never throw, because one bad line must not take the lifecycle out.
const transitionsById = {};
const transitionRecords = [];
let transitionLines = 0;
let transitionsUnreadable = 0;
for (const raw of transitionsText.split("\n")) {
  const line = raw.trim();
  if (!line) continue;
  transitionLines += 1;
  try {
    const record = JSON.parse(line);
    const id = String(record?.incident_id ?? "");
    if (!id) {
      transitionsUnreadable += 1;
      continue;
    }
    (transitionsById[id] = transitionsById[id] ?? []).push(record);
    transitionRecords.push({ record, line: transitionLines });
  } catch (error) {
    transitionsUnreadable += 1;
  }
}

const folded = incidents.map((entry) => ({ ...entry, life: arkonFold(entry.incident, transitionsById) }));
const statusOf = (entry) => entry.life.status;

// What to write. Without a previous summary every row is new.
const prevIncidentLines = previous ? Number(previous.incidents_lines ?? 0) : 0;
const prevTransitionLines = previous ? Number(previous.transitions_lines ?? 0) : 0;
const touched = new Set();
for (const { record, line } of transitionRecords) {
  if (line > prevTransitionLines) touched.add(String(record.incident_id));
}
const changed = folded.filter(
  (entry) => !previous || entry.line > prevIncidentLines || touched.has(String(entry.incident.incident_id))
);
const newTransitions = transitionRecords.filter((entry) => !previous || entry.line > prevTransitionLines);

// A data table row holds strings, numbers, booleans and nulls. Anything nested
// travels as JSON text and is decoded again by the status API.
const flat = (value) => {
  if (value === null || value === undefined) return null;
  if (typeof value === "object") return JSON.stringify(value);
  return value;
};

const incidentRow = ({ incident, line, life }) => {
  const projected = arkonProject(incident, life);
  const row = {};
  for (const column of INCIDENT_COLUMNS) {
    if (column === "evidence_json") row[column] = projected.evidence === null ? null : JSON.stringify(projected.evidence);
    else if (column === "history_json") row[column] = JSON.stringify(projected.history ?? []);
    else if (column === "store_line") row[column] = line;
    else if (column === "synced_at") row[column] = syncedAt;
    else row[column] = flat(projected[column]);
  }
  return row;
};

const transitionRow = ({ record, line }) => {
  const row = {};
  for (const column of TRANSITION_COLUMNS) {
    if (column === "log_line") row[column] = line;
    else if (column === "synced_at") row[column] = syncedAt;
    else row[column] = flat(record[column]);
  }
  return row;
};

// The store summary, computed over every incident exactly as the status API
// computed it before the move, so the numbers a consumer sees do not change
// with the storage.
const byPriority = {};
const byStatus = {};
for (const entry of folded) {
  const key = String(entry.incident.priority ?? "unknown").toUpperCase();
  byPriority[key] = (byPriority[key] ?? 0) + 1;
  const state = statusOf(entry);
  byStatus[state] = (byStatus[state] ?? 0) + 1;
}

const ageMinutes = (incident) => {
  const created = Date.parse(incident.created_at ?? "");
  return Number.isNaN(created) ? null : Math.round((now.getTime() - created) / 60000);
};
const isOverdue = (entry) => {
  const window = ACK_WINDOW_MINUTES[String(entry.incident.priority ?? "").toUpperCase()];
  if (window === undefined) return false;
  if (statusOf(entry) !== "new") return false;
  const age = ageMinutes(entry.incident);
  return age !== null && age > window;
};

// The median rather than the mean, because one incident acknowledged the next
// morning would otherwise move the number more than every one acknowledged on
// time (charter 7.2).
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
for (const entry of folded) {
  const life = entry.life;
  if (life.minutes_to_acknowledge !== null) {
    ackMinutes.push(life.minutes_to_acknowledge);
    const window = ACK_WINDOW_MINUTES[String(entry.incident.priority ?? "").toUpperCase()];
    if (window !== undefined) {
      if (life.minutes_to_acknowledge <= window) acknowledgedInWindow += 1;
      else acknowledgedLate += 1;
    }
  }
  if (life.minutes_to_close !== null) closeMinutes.push(life.minutes_to_close);
}

const highest = (values) => values.reduce((best, value) => (best === null || String(value) > best ? String(value) : best), null);

const summaryRow = {
  key: "__SUMMARY_KEY__",
  synced_at: syncedAt,
  sync_mode: request.rebuild ? "rebuild" : previous ? "incremental" : "initial",
  sync_source: request.source,
  duration_ms: Date.now() - started,
  incidents_lines: incidentLines,
  transitions_lines: transitionLines,
  incidents_unreadable: incidentsUnreadable,
  transitions_unreadable: transitionsUnreadable,
  total_incidents: folded.length,
  open_incidents: folded.filter((entry) => OPEN_STATUSES.includes(statusOf(entry))).length,
  overdue_incidents: folded.filter(isOverdue).length,
  incidents_by_priority_json: JSON.stringify(byPriority),
  incidents_by_status_json: JSON.stringify(byStatus),
  total_transitions: transitionRecords.length,
  incidents_with_transitions: Object.keys(transitionsById).length,
  response_times_json: JSON.stringify({
    acknowledged_incidents: ackMinutes.length,
    median_minutes_to_acknowledge: median(ackMinutes),
    acknowledged_within_window: acknowledgedInWindow,
    acknowledged_late: acknowledgedLate,
    closed_incidents: closeMinutes.length,
    median_minutes_to_close: median(closeMinutes),
  }),
  incident_rows_written: changed.length,
  transition_rows_written: newTransitions.length,
  highest_incident_id: highest(folded.map((entry) => entry.incident.incident_id)),
  highest_transition_id: highest(transitionRecords.map((entry) => entry.record.transition_id ?? "")),
};
for (const column of SUMMARY_COLUMNS) {
  if (!(column in summaryRow)) summaryRow[column] = null;
}

return [
  {
    json: {
      request,
      summary_row: summaryRow,
      incident_rows: changed.map(incidentRow),
      transition_rows: newTransitions.map(transitionRow),
    },
  },
];
""".replace("__SUMMARY_KEY__", SUMMARY_KEY)
)

INCIDENT_ROWS = r"""// One item per incident row the fold decided to write; none is a valid answer.
return $("Fold Store").first().json.incident_rows.map((row) => ({ json: row }));
"""

TRANSITION_ROWS = r"""// One item per new transition line; none is a valid answer.
return $("Fold Store").first().json.transition_rows.map((row) => ({ json: row }));
"""

SUMMARY_ROW = r"""// The one summary row, rewritten by every sync. Always exactly one item, which
// is why this branch carries the sync line and the webhook's answer.
return [{ json: $("Fold Store").first().json.summary_row }];
"""

SYNC_LINE = r"""// The sync's own record, one line per run: the summary numbers and the row
// counts. Successful executions are not stored (workflow settings), so this
// line is the evidence that a sync happened and what it found.
const summary = $("Fold Store").first().json.summary_row;
return [{ json: { ...summary, sync_jsonl: JSON.stringify(summary) + "\n" } }];
"""

SYNC_DONE = r"""// The last node: its output is the webhook's answer (response mode "last node").
return [{ json: $("Fold Store").first().json.summary_row }];
"""


def node_id(n):
    return "d1000000-0000-4000-8000-%012x" % n


def code(n, name, position, js, execute_once=False):
    node = {
        "id": node_id(n),
        "name": name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": position,
        "parameters": {"jsCode": js},
    }
    if execute_once:
        node["executeOnce"] = True
    return node


def table_ref(name):
    return {"__rl": True, "mode": "name", "value": name}


def create_table(n, name, position, table):
    return {
        "id": node_id(n),
        "name": name,
        "type": "n8n-nodes-base.dataTable",
        "typeVersion": 1.1,
        "position": position,
        "parameters": {
            "resource": "table",
            "operation": "create",
            "tableName": table,
            "columns": {"column": [{"name": col, "type": kind} for col, kind in TABLES[table]]},
            "options": {"createIfNotExists": True},
        },
    }


def wipe_table(n, name, position, table, key_column):
    # Delete needs at least one condition; "the key is not empty" is every row.
    return {
        "id": node_id(n),
        "name": name,
        "type": "n8n-nodes-base.dataTable",
        "typeVersion": 1.1,
        "position": position,
        "alwaysOutputData": True,
        "parameters": {
            "resource": "row",
            "operation": "deleteRows",
            "dataTableId": table_ref(table),
            "matchType": "allConditions",
            "filters": {"conditions": [{"keyName": key_column, "condition": "isNotEmpty", "keyValue": ""}]},
            "options": {},
        },
    }


def get_summary(n, name, position):
    return {
        "id": node_id(n),
        "name": name,
        "type": "n8n-nodes-base.dataTable",
        "typeVersion": 1.1,
        "position": position,
        "alwaysOutputData": True,
        "parameters": {
            "resource": "row",
            "operation": "get",
            "dataTableId": table_ref(SUMMARY_TABLE),
            "matchType": "allConditions",
            "filters": {"conditions": [{"keyName": "key", "condition": "eq", "keyValue": SUMMARY_KEY}]},
            "returnAll": False,
            "limit": 1,
        },
    }


def upsert(n, name, position, table, key_column, key_expression):
    return {
        "id": node_id(n),
        "name": name,
        "type": "n8n-nodes-base.dataTable",
        "typeVersion": 1.1,
        "position": position,
        "parameters": {
            "resource": "row",
            "operation": "upsert",
            "dataTableId": table_ref(table),
            "matchType": "allConditions",
            "filters": {"conditions": [{"keyName": key_column, "condition": "eq", "keyValue": key_expression}]},
            "columns": {
                "mappingMode": "autoMapInputData",
                "value": {},
                "matchingColumns": [],
                "schema": [],
                "attemptToConvertTypes": False,
                "convertFieldsToString": False,
            },
            "options": {},
        },
    }


def if_node(n, name, position, left_value):
    return {
        "id": node_id(n),
        "name": name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": position,
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 1},
                "conditions": [
                    {
                        "id": node_id(n),
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


def read_file(n, name, position, path):
    return {
        "id": node_id(n),
        "name": name,
        "type": "n8n-nodes-base.readWriteFile",
        "typeVersion": 1.1,
        "position": position,
        "parameters": {"operation": "read", "fileSelector": path, "options": {}},
    }


def extract_text(n, name, position, destination_key):
    return {
        "id": node_id(n),
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


def chain(*names):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


workflow = {
    "id": WORKFLOW_ID,
    "name": "Arkon Store Sync v1",
    "nodes": [
        {
            "id": node_id(1),
            "name": "Sync Request",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-1552, 160],
            "webhookId": "arkon-store-sync",
            "parameters": {
                "httpMethod": "POST",
                "path": "arkon-store-sync",
                "responseMode": "lastNode",
                "options": {},
            },
        },
        {
            "id": node_id(2),
            "name": "When Executed by Another Workflow",
            "type": "n8n-nodes-base.executeWorkflowTrigger",
            "typeVersion": 1.2,
            "position": [-1552, 400],
            "parameters": {
                "inputSource": "workflowInputs",
                "workflowInputs": {
                    "values": [{"name": "source", "type": "string"}, {"name": "rebuild", "type": "boolean"}]
                },
            },
        },
        code(3, "Read Request", [-1328, 280], READ_REQUEST),
        create_table(4, "Create Incidents Table", [-1104, 280], INCIDENTS_TABLE),
        create_table(5, "Create Transitions Table", [-880, 280], TRANSITIONS_TABLE),
        create_table(6, "Create Summary Table", [-656, 280], SUMMARY_TABLE),
        if_node(7, "Rebuild?", [-432, 280], "={{ $('Read Request').first().json.rebuild }}"),
        wipe_table(8, "Wipe Incidents", [-208, 80], INCIDENTS_TABLE, "incident_id"),
        wipe_table(9, "Wipe Transitions", [16, 80], TRANSITIONS_TABLE, "transition_id"),
        wipe_table(10, "Wipe Summary", [240, 80], SUMMARY_TABLE, "key"),
        read_file(11, "Read Incident Store", [464, 280], STORE_PATH),
        extract_text(12, "Extract Store Text", [688, 280], "store_text"),
        read_file(13, "Read Transition Store", [912, 280], TRANSITION_STORE),
        extract_text(14, "Extract Transitions Text", [1136, 280], "transitions_text"),
        get_summary(15, "Get Summary", [1360, 280]),
        code(16, "Fold Store", [1584, 280], FOLD_STORE),
        # Three branches. n8n's v1 execution order runs them top to bottom by
        # position, so the rows land before the summary that records them: a run
        # that dies half way leaves counters that make the next run redo the rows.
        code(17, "Incident Rows", [1808, 40], INCIDENT_ROWS),
        upsert(18, "Upsert Incidents", [2032, 40], INCIDENTS_TABLE, "incident_id", "={{ $json.incident_id }}"),
        code(19, "Transition Rows", [1808, 280], TRANSITION_ROWS),
        upsert(20, "Upsert Transitions", [2032, 280], TRANSITIONS_TABLE, "transition_id", "={{ $json.transition_id }}"),
        code(21, "Summary Row", [1808, 520], SUMMARY_ROW),
        upsert(22, "Upsert Summary", [2032, 520], SUMMARY_TABLE, "key", SUMMARY_KEY),
        code(23, "Sync Line", [2256, 520], SYNC_LINE, execute_once=True),
        {
            "id": node_id(24),
            "name": "Build Sync Line",
            "type": "n8n-nodes-base.convertToFile",
            "typeVersion": 1.1,
            "position": [2480, 520],
            "parameters": {"operation": "toText", "sourceProperty": "sync_jsonl", "options": {}},
        },
        {
            "id": node_id(25),
            "name": "Append Sync Log",
            "type": "n8n-nodes-base.readWriteFile",
            "typeVersion": 1.1,
            "position": [2704, 520],
            "parameters": {"operation": "write", "fileName": SYNC_LOG, "options": {"append": True}},
        },
        code(26, "Sync Done", [2928, 520], SYNC_DONE, execute_once=True),
    ],
    "connections": {
        "Sync Request": {"main": [[{"node": "Read Request", "type": "main", "index": 0}]]},
        "When Executed by Another Workflow": {"main": [[{"node": "Read Request", "type": "main", "index": 0}]]},
        **chain("Read Request", "Create Incidents Table", "Create Transitions Table", "Create Summary Table", "Rebuild?"),
        "Rebuild?": {
            "main": [
                [{"node": "Wipe Incidents", "type": "main", "index": 0}],
                [{"node": "Read Incident Store", "type": "main", "index": 0}],
            ]
        },
        **chain("Wipe Incidents", "Wipe Transitions", "Wipe Summary", "Read Incident Store"),
        **chain("Read Incident Store", "Extract Store Text", "Read Transition Store", "Extract Transitions Text",
                "Get Summary", "Fold Store"),
        "Fold Store": {
            "main": [
                [
                    {"node": "Incident Rows", "type": "main", "index": 0},
                    {"node": "Transition Rows", "type": "main", "index": 0},
                    {"node": "Summary Row", "type": "main", "index": 0},
                ]
            ]
        },
        **chain("Incident Rows", "Upsert Incidents"),
        **chain("Transition Rows", "Upsert Transitions"),
        **chain("Summary Row", "Upsert Summary", "Sync Line", "Build Sync Line", "Append Sync Log", "Sync Done"),
    },
    # Successful runs carry both logs as text and are not worth an execution
    # record each; the sync line is the record. Failures are kept.
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
