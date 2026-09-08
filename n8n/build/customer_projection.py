"""The customer projection of an incident: what an OEM customer may know.

The plant works from the full incident record (assignee, model evidence,
priority, thresholds, other incidents). A customer asking about a quality
notice or a complaint by its `ARK-INC` reference may know eight things: the
reference, what it is, when it was received, its status in customer words,
which of five stages it is in, the next step with the date Arkon has
committed to, when it last moved, and when it was closed. Nothing else leaves
the plant through the customer status endpoint, and that is enforced here, in
the projection the endpoint serves, rather than in the prompt of the agent
that calls it.

Two workflows and two documents share this file: the customer status API
(`build_customer_status_workflow.py`) serves the projection, its checker
asserts the field list, and the customer-facing documents of the Customer
Quality Desk (the complaint handling guide and the commitments) quote the same
vocabulary and the same commitment windows. Held in one place for the reason
`lifecycle.py` is: a vocabulary copied into a document and a Code node is a
vocabulary that drifts.
"""

import json

from lifecycle import ACK_WINDOW_MINUTES, LIFECYCLE, TERMINAL_STATUSES

# The customer's view of the charter 7.2 lifecycle. Stage numbers count the
# five steps of the customer process the complaint handling guide describes;
# the two terminal outcomes are the same fifth stage with different words.
CUSTOMER_STAGES = {
    "new": {
        "customer_status": "Received",
        "stage": 1,
        "stage_name": "Received and logged",
        "next_step": "Acknowledgement by the Arkon quality team",
    },
    "acknowledged": {
        "customer_status": "Under investigation",
        "stage": 2,
        "stage_name": "Investigation opened",
        "next_step": "Containment decision",
    },
    "in_containment": {
        "customer_status": "Containment in place",
        "stage": 3,
        "stage_name": "Containment measures active",
        "next_step": "Root cause and corrective action",
    },
    "resolved": {
        "customer_status": "Corrective action implemented",
        "stage": 4,
        "stage_name": "Corrective action implemented",
        "next_step": "Effectiveness check and closure",
    },
    "closed": {
        "customer_status": "Closed",
        "stage": 5,
        "stage_name": "Closed",
        "next_step": None,
    },
    "false_positive": {
        "customer_status": "Closed, no defect confirmed",
        "stage": 5,
        "stage_name": "Closed",
        "next_step": None,
    },
}
STAGE_COUNT = 5

# Arkon's commitment for the next step, in hours from the moment the current
# stage was entered. The first one is the charter 7.1 acknowledgement window
# per priority (P1 fifteen minutes, P2 one hour), taken from lifecycle.py so the
# customer is promised exactly what the plant is measured on; P3 and P4 have no
# charter window and get the desk's one business day. The other three are the
# desk's own commitments, decided 2026-09-08 with the Customer Quality Desk and
# stated in its complaint handling guide; the charter measures none of them.
DEFAULT_ACK_HOURS = 24.0
COMMITMENT_HOURS = {
    "new": {priority: minutes / 60.0 for priority, minutes in ACK_WINDOW_MINUTES.items()},
    "acknowledged": 24.0,
    "in_containment": 240.0,
    "resolved": 120.0,
}

# The complete list of what the endpoint serves per notice. The checker asserts
# a served notice has exactly these keys, and the test asserts none of them is a
# column of the internal incident row.
SERVED_FIELDS = [
    "reference",
    "type",
    "received_at",
    "customer_status",
    "stage",
    "next_step",
    "last_update_at",
    "closed_at",
]

# Internal names that must never appear in the endpoint's answer node, so the
# workflow cannot serve them even by a later edit that forgets this file.
INTERNAL_NAMES = [
    "assigned_to",
    "assigned_role",
    "escalation_contact",
    "evidence",
    "risk_score",
    "record_id",
    "model_version",
    "priority_threshold",
    "predicted_rul",
    "recommended_action",
    "summary",
    "source_module",
    "business_domain",
    "event_id",
    "unit",
    "actor",
    "note",
]


def check_projection():
    """Raise if the vocabulary and the lifecycle disagree."""
    for status in LIFECYCLE:
        if status not in CUSTOMER_STAGES:
            raise ValueError("no customer stage for lifecycle status %s" % status)
    for status in CUSTOMER_STAGES:
        if status not in LIFECYCLE:
            raise ValueError("customer stage %s is not a lifecycle status" % status)
    for status in TERMINAL_STATUSES:
        if CUSTOMER_STAGES[status]["next_step"] is not None:
            raise ValueError("a terminal status promises a next step: %s" % status)
    for status, stage in CUSTOMER_STAGES.items():
        if stage["next_step"] is not None and status not in COMMITMENT_HOURS:
            raise ValueError("%s promises a next step without a commitment window" % status)
    if len(set(SERVED_FIELDS)) != len(SERVED_FIELDS):
        raise ValueError("a served field repeats")


def js_constants():
    """The vocabulary and the commitments as JS consts, for the Code node."""
    return "\n".join(
        [
            "const CUSTOMER_STAGES = %s;" % json.dumps(CUSTOMER_STAGES),
            "const STAGE_COUNT = %d;" % STAGE_COUNT,
            "const COMMITMENT_HOURS = %s;" % json.dumps(COMMITMENT_HOURS),
            "const DEFAULT_ACK_HOURS = %s;" % json.dumps(DEFAULT_ACK_HOURS),
            "const TERMINAL_STATUSES = %s;" % json.dumps(TERMINAL_STATUSES),
        ]
    )


# The projection itself, injected verbatim into the endpoint's answer node and
# run by the checker under node. It reads one row of the queryable store
# (`store_schema.py`, the incident row with its folded lifecycle) and returns
# the customer's eight fields and nothing else.
PROJECTION_JS = r"""
const arkonCustomerParseJson = (text, fallback) => {
  if (text === null || text === undefined || text === "") return fallback;
  try {
    return JSON.parse(text);
  } catch (error) {
    return fallback;
  }
};

// Hours Arkon has committed to for the next step of a notice in this status.
// The acknowledgement window is the charter's per priority; a priority without
// one gets the desk's default; a status without a next step gets null.
function arkonCommitmentHours(status, priority) {
  const window = COMMITMENT_HOURS[status];
  if (window === undefined) return null;
  if (typeof window === "number") return window;
  const byPriority = window[String(priority ?? "").toUpperCase()];
  return byPriority === undefined ? DEFAULT_ACK_HOURS : byPriority;
}

// One incident row of the store, seen by the customer who holds its reference.
// The current stage was entered at the last recorded transition, or at intake
// when there is none, and the commitment date counts from that moment, so a
// containment that was reopened counts from the reopening.
function arkonCustomerProjection(row, now) {
  const status = String(row.status ?? "new").toLowerCase();
  const stage = CUSTOMER_STAGES[status] ?? CUSTOMER_STAGES["new"];
  const history = arkonCustomerParseJson(row.history_json, []);
  const last = history.length ? history[history.length - 1] : null;
  const enteredAt = last && last.recorded_at ? last.recorded_at : (row.created_at ?? null);
  const entered = Date.parse(enteredAt ?? "");

  let nextStep = null;
  if (stage.next_step) {
    const hours = arkonCommitmentHours(status, row.priority);
    const due = Number.isNaN(entered) || hours === null ? null : new Date(entered + hours * 3600000);
    nextStep = {
      name: stage.next_step,
      due_at: due ? due.toISOString() : null,
      overdue: due ? now.getTime() > due.getTime() : false,
    };
  }

  const terminal = TERMINAL_STATUSES.includes(status);
  return {
    reference: row.incident_id,
    type: "quality_notice",
    received_at: row.created_at ?? null,
    customer_status: stage.customer_status,
    stage: { number: stage.stage, of: STAGE_COUNT, name: stage.stage_name },
    next_step: nextStep,
    last_update_at: enteredAt,
    closed_at: terminal ? (row.closed_at ?? enteredAt) : null,
  };
}
"""


check_projection()
