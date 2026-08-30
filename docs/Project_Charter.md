# Arkon Manufacturing AI: Project Charter

## 1. Project purpose

Arkon Manufacturing AI is a portfolio-scale, fictional industrial manufacturing group that demonstrates how different AI capabilities can support one quality operating model.

The project does not claim that its public datasets come from one factory or can be joined at raw-record level. Each dataset represents a department with a different decision problem. Their outputs are standardised as Arkon risk events and handled through a common Quality Steering Cell workflow.

## 2. Portfolio story

Arkon operates a closed-loop quality system:

1. Production assets generate condition and quality signals.
2. Models detect maintenance, defect, or operational risk.
3. The Quality Steering Cell prioritises the risk and assigns containment work.
4. Field-quality complaint trends provide post-market feedback.
5. Resolved incidents create evidence for corrective and preventive action.

This structure demonstrates that AI models are decision-support components, not isolated notebooks.

## 3. Learning and business objectives

The project demonstrates the following capabilities in one coherent system:

| Capability | Arkon module | Decision supported |
|---|---|---|
| Time series machine learning | NASA CMAPSS | Remaining useful life and maintenance priority |
| Tabular machine learning | Scania APS | Probability of a component-related service issue |
| Computer vision | Casting Defect or NEU Surface Defect | Inspection result and defect category |
| NLP and LLM | NHTSA Consumer Complaints | Field-quality component trend and complaint triage |
| Automation | n8n | Incident routing, alerting, approval, and audit trail |
| Decision communication | Streamlit and Tableau | Operational cockpit and executive quality view |

## 4. Scope and MVP boundary

The initial MVP uses one working model from each core capability:

- CMAPSS for the time series module.
- Scania APS for the tabular classification module.
- Casting Defect as the first computer-vision module.
- NHTSA Consumer Complaints 2020-2024 as the NLP field-quality module.
- One n8n workflow that receives a validated Arkon risk event and creates an incident with an alert.

MVTec, NEU, GC10, advanced detection models, RAG, and additional n8n workflows are roadmap items. They are not prerequisites for the MVP.

## 5. Data boundaries and integrity

All primary model training and evaluation uses real public data only.

- Keep raw source data immutable.
- Preserve dataset identifiers and source provenance.
- Report metrics only from real held-out data.
- Do not claim raw-record joins across independent datasets.
- Treat NHTSA complaints as a public field-quality proxy, not proof of manufacturing root cause.

Synthetic operational context may be added only after a model produces real outputs. It may provide demonstration fields such as shift, line, station, incident owner, containment action, and status. Every generated field must be labelled `context_origin: simulated`, created with documented rules and a fixed seed, and kept separate from model metrics.

## 6. Shared event contract

Every model publishes a common event after its own validation step. This makes the components interoperable without pretending that their raw data is connected.

```json
{
  "event_id": "arkon-2026-000001",
  "event_time": "2026-07-23T10:30:00Z",
  "source_module": "cmapss_rul",
  "business_domain": "asset_reliability",
  "risk_type": "maintenance",
  "risk_score": 0.91,
  "priority": "P2",
  "summary": "Engine unit is predicted to reach the RUL threshold within 15 cycles.",
  "evidence": {
    "record_id": "FD001-Unit-42",
    "model_version": "baseline-v1",
    "prediction": 14.8,
    "threshold": 20
  },
  "context_origin": "real",
  "recommended_action": "Schedule inspection before the next operating window.",
  "status": "new"
}
```

The exact priority thresholds will be defined per module and documented with the model. A risk score is not automatically a production stop decision.

## 7. Quality Steering Cell operating rules

Decided 2026-08-10. These rules govern what happens after an event is published.

### 7.1 Priority levels

P1 is the highest severity.

| Priority | Meaning | Response expectation (demo scale) |
|---|---|---|
| P1 | Critical: imminent failure or safety-relevant defect risk | Immediate alert; acknowledge within 15 minutes or escalate to the Quality Manager |
| P2 | High: threshold breach requiring same-shift action | Alert; acknowledge within 1 hour |
| P3 | Medium: degradation trend for planned work | Queued; reviewed daily, no push alert |
| P4 | Low or informational: recorded for trend analysis | Dashboard only |

Each module documents its own risk_score-to-priority thresholds next to the model. CMAPSS mapping on predicted RUL in cycles: RUL <= 10 is P1, RUL <= 25 is P2, RUL <= 50 is P3, above 50 is P4. The thresholds were set against the FD001 baseline and kept unchanged when the model moved to the full fleet on 2026-08-30, because the model scores the four subsets evenly; they are recorded here as a tuning input rather than a validated optimum.

### 7.2 Incident lifecycle

new -> acknowledged -> in_containment -> resolved -> closed

A reviewed incident may instead be marked false_positive; that outcome is kept and feeds threshold tuning. Every transition is timestamped in the incident record, and response-time KPIs are computed from these timestamps. The demo must show at least one full path from new to closed.

### 7.3 Ownership and assignment

Assignment happens at workflow intake, not in the model adapter. A routing table maps business_domain and priority to a role: asset_reliability to Maintenance Planner, fleet_reliability to Fleet Reliability Engineer, visual_inspection to QC Engineer, field_quality to Field Quality Analyst. P1 additionally notifies the Quality Manager. The people behind the roles come from a simulated roster file labelled `context_origin: simulated` under the section 5 rules.

### 7.4 Communication and escalation

The alert channel is a Telegram bot driven by n8n: an incident card with priority, summary, evidence reference, and for computer-vision events the defect image, plus inline acknowledge and close buttons. The channel is an adapter: a corporate deployment would swap the Telegram node for a Microsoft Teams node without changing the workflow. P1 and P2 incidents that are not acknowledged within their response window trigger a manager notification. A daily digest summarises open incidents.

### 7.5 Incident store and dashboards

The incident record of truth is one SQLite database written by the n8n workflow; its exact mount location is fixed against the NAS compose file at deployment time. **Deviation in v1, 2026-08-30:** the deployed workflow appends to a JSONL file at `/data/arkon/incidents.jsonl` on the NAS instead. The move to a queryable store is scheduled together with the lifecycle transitions of section 7.2, since both are needed by the same consumer, and now targets the n8n Data Table node rather than a separate SQLite file: it is native to the deployed platform and supports insert, get, update and upsert. See `n8n/README.md`. Streamlit reads the store directly and serves as the live operational cockpit. Tableau reads periodic extracts and serves as the executive KPI view: open incidents by priority, response times, and trend Pareto. A live Tableau connection would require a paid Tableau Server; extract refresh is the documented portfolio boundary.

## 8. Target architecture

```text
Public datasets
      |
      v
Reproducible module pipelines
      |
      v
Validated model outputs
      |
      v
Arkon risk-event adapters
      |
      v
n8n Quality Steering Cell workflow
      |
      +--> Incident record and audit trail
      +--> Priority-based alert
      +--> Human review and containment decision
      |
      v
Streamlit operational cockpit and Tableau executive view
```

n8n orchestrates operational work. It does not train or host machine-learning models. The workflow receives an event through a webhook, API call, or controlled file input, validates it, prevents duplicate alerts, assigns a priority route, records the incident, requests human approval where required, and stores closure feedback.

## 9. Delivery sequence

### Phase 0: Foundation

- Maintain this charter and dataset provenance.
- Define the shared event schema and a small event validator.
- Establish a consistent folder, environment, and experiment-tracking convention.

### Phase 1: First vertical slice, CMAPSS

- Complete a reproducible CMAPSS baseline and evaluate RUL predictions.
- Create CMAPSS risk-event adapter output.
- Add limited simulated operational context only if required for the workflow demonstration.
- Build the first n8n workflow from event intake to incident and alert.

### Phase 2: Additional model modules

- Implement Scania APS classification and publish the same event contract.
- Implement Casting Defect computer vision and publish the same event contract.
- Implement NHTSA text classification and field-quality trend detection, then publish the same event contract.

### Phase 3: Product integration

- Add Streamlit views for module results, events, and incident status.
- Add Tableau views for aggregated risk, response time, and quality trends.
- Add a grounded RAG assistant only after documentation, model cards, and incident records exist.

### Phase 4: Portfolio completion

- Produce model cards, data cards, architecture diagrams, and a demo script.
- Demonstrate one complete incident path from model output to human-reviewed closure.
- Document limitations, false-positive trade-offs, and simulated-data boundaries.

## 10. MVP success criteria

The MVP is complete when all of the following are true:

- At least one model is reproducible end to end with an honest held-out evaluation.
- Its output is converted to a versioned Arkon risk event.
- n8n validates, de-duplicates, records, and routes the event to a human-review step.
- The decision and event status can be seen in an operational interface.
- The repository documents data provenance, model limitations, and any simulated context.

## 11. Immediate next action

**Phase 1 closed 2026-08-30.** All four deliverables are done and verified:

- The CMAPSS model is reproducible and now covers the full fleet, all four subsets, 709 engines, six operating regimes and two fault modes. XGBoost reaches RMSE 16.95 on the benchmark task, one prediction per engine at its last observed cycle, and scores the hardest subset about as well as the easiest. Full figures, the FD001 comparison and the limitations are in `docs/Model_Card_CMAPSS_RUL.md`; the training script is `notebooks/01_timeseries/cmapss_full_fleet.py`.
- The risk-event adapter produces contract-valid events; 100 exist in `events/out/`.
- Simulated operational context is attached and labelled per section 5.
- The n8n Quality Steering Cell is deployed on the NAS and verified end to end: contract violations rejected with HTTP 400, incidents created with `ARK-INC-*` ids, duplicates suppressed across production runs, incident records appended to the store, and Telegram cards delivered for P1 and P2. Deployment record and the three n8n 2.0 traps met on the way are in `n8n/README.md`.

Next action: Phase 3 brings the grounded assistant forward, built on Langflow against this documentation and the deployed workflow. Phase 2 model modules follow.
