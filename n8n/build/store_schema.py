"""The queryable incident store of charter 7.5: three n8n data tables, one schema.

The record of truth stays the two append-only JSONL logs on the NAS; what this
module describes is the projection of them that the store sync workflow keeps in
n8n's own data tables so a status query reads rows instead of parsing both logs
whole. Three workflows share this file: the sync writes the rows, the status API
reads them, and the offline checkers assert that both use the same column names.
Held in one place for the reason `lifecycle.py` is: a schema copied into two
generated JS bodies is a schema that drifts.

Column values are flat by construction. The data table node refuses arrays and
objects in a row, so the nested parts of an incident (the evidence, the history)
travel as JSON strings and are decoded again on the way out.
"""

import json
import re

INCIDENTS_TABLE = "arkon_incidents"
TRANSITIONS_TABLE = "arkon_transitions"
SUMMARY_TABLE = "arkon_store_summary"

# The one row of the summary table is found by this key.
SUMMARY_KEY = "store"

# One row per incident: the flat projection the status API serves, plus the
# folded lifecycle. `status` here is the fold at sync time, never the stored
# `new` of the JSONL line, which lives on in `raised_as`.
INCIDENT_COLUMNS = [
    ("incident_id", "string"),
    ("created_at", "string"),
    ("priority", "string"),
    ("status", "string"),
    ("raised_as", "string"),
    ("is_terminal", "boolean"),
    ("transition_count", "number"),
    ("acknowledged_at", "string"),
    ("resolved_at", "string"),
    ("closed_at", "string"),
    ("minutes_to_acknowledge", "number"),
    ("minutes_to_resolve", "number"),
    ("minutes_to_close", "number"),
    ("acknowledge_due_minutes", "number"),
    ("unit", "string"),
    ("record_id", "string"),
    ("summary", "string"),
    ("recommended_action", "string"),
    ("source_module", "string"),
    ("business_domain", "string"),
    ("assigned_to", "string"),
    ("assigned_role", "string"),
    ("escalation_contact", "string"),
    ("event_id", "string"),
    ("risk_score", "number"),
    ("evidence_json", "string"),
    ("predicted_rul", "number"),
    ("priority_threshold", "number"),
    ("model_version", "string"),
    ("data_origin", "string"),
    ("operational_context_origin", "string"),
    ("history_json", "string"),
    ("store_line", "number"),
    ("synced_at", "string"),
]

# One row per transition, the record as the transition endpoint wrote it.
TRANSITION_COLUMNS = [
    ("transition_id", "string"),
    ("recorded_at", "string"),
    ("incident_id", "string"),
    ("incident_priority", "string"),
    ("incident_created_at", "string"),
    ("from_status", "string"),
    ("to_status", "string"),
    ("actor", "string"),
    ("note", "string"),
    ("minutes_since_created", "number"),
    ("minutes_since_previous_transition", "number"),
    ("acknowledge_window_minutes", "number"),
    ("acknowledged_within_window", "boolean"),
    ("context_origin", "string"),
    ("log_line", "number"),
    ("synced_at", "string"),
]

# One row, rewritten by every sync: the store-wide numbers the status API used
# to compute on every request, and the two line counters that make the next
# sync incremental on the database side.
SUMMARY_COLUMNS = [
    ("key", "string"),
    ("synced_at", "string"),
    ("sync_mode", "string"),
    ("sync_source", "string"),
    ("duration_ms", "number"),
    ("incidents_lines", "number"),
    ("transitions_lines", "number"),
    ("incidents_unreadable", "number"),
    ("transitions_unreadable", "number"),
    ("total_incidents", "number"),
    ("open_incidents", "number"),
    ("overdue_incidents", "number"),
    ("incidents_by_priority_json", "string"),
    ("incidents_by_status_json", "string"),
    ("total_transitions", "number"),
    ("incidents_with_transitions", "number"),
    ("response_times_json", "string"),
    ("incident_rows_written", "number"),
    ("transition_rows_written", "number"),
    ("highest_incident_id", "string"),
    ("highest_transition_id", "string"),
]

TABLES = {
    INCIDENTS_TABLE: INCIDENT_COLUMNS,
    TRANSITIONS_TABLE: TRANSITION_COLUMNS,
    SUMMARY_TABLE: SUMMARY_COLUMNS,
}

# n8n keeps these on every row itself; a user column may not reuse the names.
SYSTEM_COLUMNS = ("id", "createdAt", "updatedAt")
COLUMN_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


def check_schema():
    """Raise if a table definition could not be created or would collide."""
    for table, columns in TABLES.items():
        names = [name for name, _ in columns]
        if len(names) != len(set(names)):
            raise ValueError("%s repeats a column" % table)
        for name, kind in columns:
            if not COLUMN_NAME.match(name):
                raise ValueError("%s.%s is not a safe column name" % (table, name))
            if name in SYSTEM_COLUMNS:
                raise ValueError("%s.%s shadows a system column" % (table, name))
            if kind not in ("string", "number", "boolean", "date"):
                raise ValueError("%s.%s has an unknown type %s" % (table, name, kind))
    for a in TABLES:
        for b in TABLES:
            if a != b and a in b:
                raise ValueError("%s is a substring of %s; the node resolves a table by name match" % (a, b))


def column_names(table):
    return [name for name, _ in TABLES[table]]


def js_column_lists():
    """The three column-name lists as JS consts, for the sync's row builder."""
    return "\n".join(
        "const %s_COLUMNS = %s;" % (label, json.dumps(column_names(table)))
        for label, table in (("INCIDENT", INCIDENTS_TABLE), ("TRANSITION", TRANSITIONS_TABLE), ("SUMMARY", SUMMARY_TABLE))
    )


# The projection of one folded incident, shared by the sync (which writes it as a
# row) and the status API (which serves it). `age_minutes` and `overdue` are not
# here on purpose: both depend on the clock and are computed at read time.
PROJECT_JS = r"""
// A CMAPSS record id is FD<digits>-Unit-<token>. Only these carry an engine unit;
// SCANIA-APS-000056 is a service record and has none, and reporting its last
// token as a "unit" is how a field that reads fine comes to mean nothing.
const CMAPSS_RECORD = /^FD\d+-Unit-.+$/i;
const arkonRecordId = (incident) => String(incident.event?.evidence?.record_id ?? "");
const arkonUnitToken = (incident) => {
  const recordId = arkonRecordId(incident);
  return CMAPSS_RECORD.test(recordId) ? recordId.split("-").pop() : null;
};

// The flat projection of one incident line with its fold applied. Every field the
// status API serves per incident except the two clock-dependent ones.
function arkonProject(incident, life) {
  const recordId = arkonRecordId(incident);
  const isCmapss = CMAPSS_RECORD.test(recordId);
  return {
    incident_id: incident.incident_id,
    created_at: incident.created_at ?? null,
    priority: incident.priority ?? null,
    status: life.status,
    raised_as: life.stored_status,
    is_terminal: life.is_terminal,
    transition_count: life.transition_count,
    acknowledged_at: life.acknowledged_at,
    resolved_at: life.resolved_at,
    closed_at: life.closed_at,
    minutes_to_acknowledge: life.minutes_to_acknowledge,
    minutes_to_resolve: life.minutes_to_resolve,
    minutes_to_close: life.minutes_to_close,
    acknowledge_due_minutes: ACK_WINDOW_MINUTES[String(incident.priority ?? "").toUpperCase()] ?? null,
    unit: arkonUnitToken(incident),
    record_id: recordId || null,
    summary: incident.summary ?? null,
    recommended_action: incident.recommended_action ?? null,
    source_module: incident.source_module ?? null,
    business_domain: incident.business_domain ?? null,
    assigned_to: incident.assigned_to ?? null,
    assigned_role: incident.assigned_role ?? null,
    escalation_contact: incident.escalation_contact ?? null,
    event_id: incident.event?.event_id ?? null,
    risk_score: incident.event?.risk_score ?? null,
    evidence: incident.event?.evidence ?? null,
    // predicted_rul is a CMAPSS word and only a CMAPSS record has one; served
    // from evidence.prediction for every module it once turned a Scania failure
    // probability into a remaining useful life of 0.0373 cycles.
    predicted_rul: isCmapss ? (incident.event?.evidence?.prediction ?? null) : null,
    priority_threshold: isCmapss ? (incident.event?.evidence?.threshold ?? null) : null,
    model_version: incident.event?.evidence?.model_version ?? null,
    data_origin: incident.event?.context_origin ?? null,
    operational_context_origin: incident.event?.operational_context?.context_origin ?? null,
    history: life.history,
  };
}
"""

# Turning a row back into the object the API serves: the two JSON columns are
# decoded, the clock-dependent fields are computed now, and the lifecycle block
# takes the shape the v1 contract promised.
ROW_TO_API_JS = r"""
const arkonParseJson = (text, fallback) => {
  if (text === null || text === undefined || text === "") return fallback;
  try {
    return JSON.parse(text);
  } catch (error) {
    return fallback;
  }
};

function arkonRowToIncident(row, now) {
  const created = Date.parse(row.created_at ?? "");
  const ageMinutes = Number.isNaN(created) ? null : Math.round((now.getTime() - created) / 60000);
  const window = ACK_WINDOW_MINUTES[String(row.priority ?? "").toUpperCase()];
  // Overdue means still unacknowledged past the charter 7.1 window. The status
  // is the sync's fold and the age is the clock, so this is live on every read.
  const overdue = window !== undefined && row.status === "new" && ageMinutes !== null && ageMinutes > window;
  const number = (value) => (value === null || value === undefined || value === "" ? null : Number(value));
  return {
    incident_id: row.incident_id,
    created_at: row.created_at ?? null,
    age_minutes: ageMinutes,
    status: row.status,
    raised_as: row.raised_as,
    lifecycle: {
      transition_count: number(row.transition_count) ?? 0,
      is_terminal: row.is_terminal === true,
      acknowledged_at: row.acknowledged_at ?? null,
      resolved_at: row.resolved_at ?? null,
      closed_at: row.closed_at ?? null,
      minutes_to_acknowledge: number(row.minutes_to_acknowledge),
      minutes_to_resolve: number(row.minutes_to_resolve),
      minutes_to_close: number(row.minutes_to_close),
      history: arkonParseJson(row.history_json, []),
    },
    priority: row.priority ?? null,
    unit: row.unit ?? null,
    record_id: row.record_id ?? null,
    summary: row.summary ?? null,
    recommended_action: row.recommended_action ?? null,
    acknowledge_due_minutes: number(row.acknowledge_due_minutes),
    overdue,
    source_module: row.source_module ?? null,
    business_domain: row.business_domain ?? null,
    assigned_to: row.assigned_to ?? null,
    assigned_role: row.assigned_role ?? null,
    escalation_contact: row.escalation_contact ?? null,
    event_id: row.event_id ?? null,
    risk_score: number(row.risk_score),
    evidence: arkonParseJson(row.evidence_json, null),
    predicted_rul: number(row.predicted_rul),
    priority_threshold: number(row.priority_threshold),
    model_version: row.model_version ?? null,
    data_origin: row.data_origin ?? null,
    operational_context_origin: row.operational_context_origin ?? null,
  };
}
"""


check_schema()
