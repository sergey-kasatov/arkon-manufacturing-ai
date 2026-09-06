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

Every transition carries a timestamp, and response-time figures are computed from
those timestamps rather than estimated. The incident record itself is written once
and never rewritten: transitions are appended to a separate log, and an incident's
current state is that log applied to its record. An operator reading the raw store
therefore sees `new` on every incident; the status API is what reports the current
state, and it labels the raised state `raised_as` so the two cannot be confused.

Not every move is allowed. `closed` and `false_positive` are final, `new` cannot
be re-entered, and the one step backwards is `resolved` to `in_containment`, for a
containment that did not hold. A request the lifecycle does not permit is refused
and names what is permitted from where the incident actually is.

**The operator makes a transition on the cockpit's Steering Cell page or by
calling the endpoint; nothing does it for them.** The alert card carries no
acknowledge or close buttons, because callback handling on the alert channel
cannot be built on this deployment (the workflow's webhook address is reachable
only inside the private network); the card carries a link that opens the
incident on the cockpit instead. That is the gap to state when the system is
demonstrated. What is no longer true, and was true until 2026-09-06, is that a
lapsed window goes unnoticed: an escalation timer checks every fifteen minutes
for a P1 or P2 still unacknowledged past its window and sends the Quality
Manager one card per incident (section 8, step 6), and a daily digest at 07:05
plant time summarises the open incidents, the overdue count, the response times
and the P3 queue for the daily review. What has been true since 2026-09-03 is
that the later states are recorded, timestamped and reportable.

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
the priority levels exist to prevent. Two further cards use the same group
without diluting it: the Quality Manager's card for a P1 or P2 that nobody
acknowledged inside its window, and the daily digest at 07:05 plant time, which
carries the P3 queue so that P3 needs no push of its own.

## 8. What the operator does when an alert arrives

1. Read the card. Note the priority and the acknowledgement window it carries.
2. Acknowledge the incident. This is the step the window is measured against, and
   it is a transition like any other, so it is recorded with the time it happened
   and with who made it.
3. Open the incident record and read the evidence: the model prediction, the
   threshold it crossed, and the record identifier of the affected unit.
4. Decide whether the condition is real. The model provides evidence, not a
   verdict, and the operator may have context the model does not.
5. If real, follow the recommended action and move the incident into containment,
   then to resolved when the work is done and to closed once it has been reviewed.
   If not real, mark it false_positive with a short reason; that outcome is kept
   and is the input to threshold tuning.
6. If a P1 cannot be acknowledged within 15 minutes, or a P2 within one hour,
   escalate to the Quality Manager rather than letting the window lapse silently.
   Since 2026-09-06 the platform does not wait for the operator here: a timer
   sends the Quality Manager a card for every P1 or P2 still unacknowledged past
   its window, once per incident, so a lapsed window is never silent. The
   operator's own escalation is still theirs to record. An escalation is a
   separate record and does not move the incident: an escalated incident is
   still whatever state it was in.

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
