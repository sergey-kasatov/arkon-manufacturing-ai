"""The incident lifecycle of charter 7.2, in one place.

Three workflows need this state machine: the transition endpoint enforces it,
the status API folds transitions onto incidents with it, and the escalation
record uses it to report the status an incident actually had when it was
escalated. Written once here because a state machine copied into three
generated JS bodies is a state machine that drifts.

Injected into the Code nodes as JSON by the build scripts, so the deployed
workflows and this file cannot disagree.
"""

import json

# Charter 7.2, in order. The status API rejection message lists this verbatim.
LIFECYCLE = [
    "new",
    "acknowledged",
    "in_containment",
    "resolved",
    "closed",
    "false_positive",
]

# What "open" counts as in the store summary. resolved is deliberately not open:
# the work is done and only the closure review is outstanding.
OPEN_STATUSES = ["new", "acknowledged", "in_containment"]

# Nothing leaves these two.
TERMINAL_STATUSES = ["closed", "false_positive"]

# new is the intake state and is written by the Steering Cell, never requested.
REQUESTABLE_STATUSES = [s for s in LIFECYCLE if s != "new"]

# The machine itself. resolved -> in_containment is the reopen path, for a
# containment that did not hold; it is the only edge that goes backwards, and it
# is why every KPI below is computed from the FIRST time a milestone is reached.
ALLOWED_TRANSITIONS = {
    "new": ["acknowledged", "false_positive"],
    "acknowledged": ["in_containment", "resolved", "false_positive"],
    "in_containment": ["resolved", "false_positive"],
    "resolved": ["closed", "in_containment", "false_positive"],
    "closed": [],
    "false_positive": [],
}

# Charter 7.1 acknowledgement windows, in minutes. P3 and P4 have none.
ACK_WINDOW_MINUTES = {"P1": 15, "P2": 60}


def js_constants(prefix=""):
    """Return the machine as JS const declarations for injection into a Code node."""
    lines = [
        "const %sLIFECYCLE = %s;" % (prefix, json.dumps(LIFECYCLE)),
        "const %sOPEN_STATUSES = %s;" % (prefix, json.dumps(OPEN_STATUSES)),
        "const %sTERMINAL_STATUSES = %s;" % (prefix, json.dumps(TERMINAL_STATUSES)),
        "const %sREQUESTABLE_STATUSES = %s;" % (prefix, json.dumps(REQUESTABLE_STATUSES)),
        "const %sALLOWED_TRANSITIONS = %s;" % (prefix, json.dumps(ALLOWED_TRANSITIONS)),
        "const %sACK_WINDOW_MINUTES = %s;" % (prefix, json.dumps(ACK_WINDOW_MINUTES)),
    ]
    return "\n".join(lines)


# The fold. Every consumer that reads a status has to apply the transition log to
# the incident line, because the incident line only ever holds "new". Emitted as
# a JS function so the status API, the escalation record and the transition
# endpoint itself all fold identically.
FOLD_JS = r"""
// Apply the transition log to one incident. The incident line in the store is
// written once, at new, and never rewritten; the current status is therefore the
// last transition recorded against it, and the KPI timestamps are the first time
// each milestone was reached. Charter 7.2.
function arkonFold(incident, transitionsById) {
  const list = (transitionsById[incident.incident_id] ?? [])
    .slice()
    .sort((a, b) => String(a.recorded_at ?? "").localeCompare(String(b.recorded_at ?? "")));

  const stored = String(incident.status ?? "new").toLowerCase();
  const current = list.length ? String(list[list.length - 1].to_status).toLowerCase() : stored;

  const firstAt = (status) => {
    const hit = list.find((t) => String(t.to_status).toLowerCase() === status);
    return hit ? hit.recorded_at : null;
  };

  const created = Date.parse(incident.created_at ?? "");
  const minutesFromCreated = (iso) => {
    if (!iso || Number.isNaN(created)) return null;
    const at = Date.parse(iso);
    return Number.isNaN(at) ? null : Math.round(((at - created) / 60000) * 10) / 10;
  };

  const acknowledgedAt = firstAt("acknowledged");
  const resolvedAt = firstAt("resolved");
  // A false_positive is a closing outcome: the incident is finished with, and a
  // response time that counted only "closed" would silently drop those cases.
  const closedAt = firstAt("closed") ?? firstAt("false_positive");

  return {
    status: current,
    stored_status: stored,
    transition_count: list.length,
    is_terminal: TERMINAL_STATUSES.includes(current),
    acknowledged_at: acknowledgedAt,
    resolved_at: resolvedAt,
    closed_at: closedAt,
    minutes_to_acknowledge: minutesFromCreated(acknowledgedAt),
    minutes_to_resolve: minutesFromCreated(resolvedAt),
    minutes_to_close: minutesFromCreated(closedAt),
    history: list.map((t) => ({
      transition_id: t.transition_id ?? null,
      recorded_at: t.recorded_at ?? null,
      from_status: t.from_status ?? null,
      to_status: t.to_status ?? null,
      actor: t.actor ?? null,
      note: t.note ?? null,
    })),
  };
}

// Parse a JSONL store into transitions grouped by incident id. Damaged lines are
// counted rather than thrown: one bad line must not take the whole lifecycle out.
function arkonTransitionsById(text) {
  const byId = {};
  let unreadable = 0;
  for (const line of String(text ?? "").split("\n").map((l) => l.trim()).filter(Boolean)) {
    try {
      const record = JSON.parse(line);
      const id = String(record.incident_id ?? "");
      if (!id) {
        unreadable += 1;
        continue;
      }
      (byId[id] = byId[id] ?? []).push(record);
    } catch (error) {
      unreadable += 1;
    }
  }
  return { byId, unreadable };
}
"""
