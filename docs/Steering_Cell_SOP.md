# Standard Operating Procedure: Arkon Quality Steering Cell

Operating instructions for the on-shift Quality Steering Cell operator. Derived
from the operating rules in `Project_Charter.md` section 7; where this document
and the charter disagree, the charter is the authority.

Version 1, 2026-08-30. Covers the deployed workflow: event intake, validation,
duplicate suppression, incident record, and the priority-routed alert.

---

## 1. What the Quality Steering Cell is

The Quality Steering Cell is the operational layer of the Arkon platform. It
receives risk events published by the model modules, decides whether each event
becomes an incident, and puts the incident in front of a human. The Steering
Cell does not train models and does not make engineering decisions. It routes
attention.

The Steering Cell exists because a model output is not an instruction. A
predicted remaining life of eight cycles is evidence; the decision to stop a
test, order an inspection, or wait is made by a person who can see context the
model cannot.

## 2. What arrives, and what is rejected

An event reaches the Steering Cell as an HTTP POST to the intake webhook. Every
event must satisfy the Arkon event contract, defined in
`events/arkon_event_schema.json`. Twelve fields are mandatory: event_id,
event_time, source_module, business_domain, risk_type, risk_score, priority,
summary, evidence, context_origin, recommended_action and status.

An event that violates the contract is rejected immediately with HTTP 400 and a
list of the specific violations. It creates no incident and raises no alert. A
rejected event means a publishing module is broken, not that a machine is
healthy, and the module owner must be told.

The Steering Cell also rejects any event whose operational context is present but
not labelled as simulated. This is deliberate: simulated staffing and shift data
must never be mistaken for a real roster.

## 3. Priority levels and what each one obliges

Priority is assigned by the publishing module, not by the Steering Cell. P1 is
the highest severity.

**P1 means critical**: imminent failure or a safety-relevant defect risk. A P1
incident raises an immediate alert. The operator must acknowledge a P1 within 15
minutes; an unacknowledged P1 escalates to the Quality Manager.

**P2 means high**: a threshold breach requiring action within the same shift. A
P2 incident raises an alert. The operator must acknowledge a P2 within one hour.

**P3 means medium**: a degradation trend for planned work. A P3 incident is
recorded and queued for daily review. It raises no push alert, by design, so that
the alert channel keeps its meaning.

**P4 means low or informational**: recorded for trend analysis only, visible on
the dashboard. A P4 incident raises no alert.

For the CMAPSS engine module, priority is derived from the predicted remaining
useful life in cycles: 10 or fewer is P1, 25 or fewer is P2, 50 or fewer is P3,
and above 50 is P4. Each module documents its own thresholds next to its model.

## 4. Duplicate suppression

The Steering Cell suppresses duplicates on the combination of the evidence record
identifier and the priority, within a 24 hour window. The same engine crossing
the same threshold repeatedly produces one incident, not one per prediction run.

A suppressed duplicate is answered with `duplicate_suppressed` and creates no
second incident and no second alert. This is not an error and does not need
investigation. Repeated suppression on the same record is itself information: it
means the condition persists and was already raised.

Duplicate suppression is keyed on record identifier and priority together, so an
engine that deteriorates from P2 to P1 does raise a new incident. An escalation
in severity is always a new incident.

## 5. Incident lifecycle

An incident moves through: new, acknowledged, in_containment, resolved, closed.

A reviewed incident may instead be marked false_positive. That outcome is kept
rather than deleted, because false positives are the input to threshold tuning. A
false positive rate that is never recorded cannot be improved.

Every transition carries a timestamp in the incident record, and response-time
figures are computed from those timestamps rather than estimated.

**In version 1 only the `new` state is written automatically.** Acknowledge and
close actions, the escalation timer, and the daily digest are the next iteration;
they need callback handling on the alert channel. An operator working with
version 1 therefore tracks the later states outside the system, and this gap must
be stated whenever the system is demonstrated.

## 6. Ownership and assignment

Assignment happens at workflow intake, not inside the model. The routing table
maps the business domain to a role: asset_reliability goes to the Maintenance
Planner, fleet_reliability to the Fleet Reliability Engineer, visual_inspection
to the QC Engineer, and field_quality to the Field Quality Analyst. A P1
incident additionally notifies the Quality Manager.

The people named behind these roles come from a simulated roster and are labelled
as simulated in every event. No real person is named anywhere in the system.

## 7. The alert channel

Alerts are delivered as incident cards to a Telegram group, sent by the n8n
workflow. A card carries the priority, the incident identifier, the summary, the
assigned role and person, the recommended action, and the source event
identifier.

The alert channel is an adapter, not an architectural commitment. A corporate
deployment would replace the Telegram node with a Microsoft Teams node without
changing anything else in the workflow.

Alerts are sent for P1 and P2 only. If every priority alerted, the channel would
become noise and the operator would stop reading it, which is the failure mode
the priority levels exist to prevent.

## 8. What the operator does when an alert arrives

1. Read the card. Note the priority and the acknowledgement window it carries.
2. Open the incident record and read the evidence: the model prediction, the
   threshold it crossed, and the record identifier of the affected unit.
3. Decide whether the condition is real. The model provides evidence, not a
   verdict, and the operator may have context the model does not.
4. If real, follow the recommended action and move the incident into
   containment. If not real, mark it false_positive with a short reason.
5. If a P1 cannot be acknowledged within 15 minutes, or a P2 within one hour,
   escalate to the Quality Manager rather than letting the window lapse silently.

## 9. Boundaries the operator must know

The Steering Cell does not stop production. It does not order maintenance. It
does not approve or reject a part. It records a risk, routes it to a named role,
and keeps the audit trail. Every consequential action stays with a person.

The model outputs a single number with no uncertainty attached, and its errors
are symmetric while the real cost is not: predicting more remaining life than an
engine has is the expensive direction. An operator should treat a prediction near
a threshold as a prompt to look, not as a measurement.

All data in the current system is simulated. The engine measurements come from
the NASA CMAPSS simulation, and the operational context around them is
fabricated. No decision taken in this system affects any real equipment.
