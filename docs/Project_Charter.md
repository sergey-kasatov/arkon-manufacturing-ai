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

## 7. Target architecture

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

## 8. Delivery sequence

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

## 9. MVP success criteria

The MVP is complete when all of the following are true:

- At least one model is reproducible end to end with an honest held-out evaluation.
- Its output is converted to a versioned Arkon risk event.
- n8n validates, de-duplicates, records, and routes the event to a human-review step.
- The decision and event status can be seen in an operational interface.
- The repository documents data provenance, model limitations, and any simulated context.

## 10. Immediate next action

Begin Phase 1 by completing the CMAPSS baseline. The first deliverable is a saved prediction table and a documented RUL threshold that can be transformed into sample Arkon risk events. n8n begins immediately after that event output exists.
