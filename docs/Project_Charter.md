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
| Computer vision | Casting Defect, NEU Surface Defect, MVTec Component Anomaly and GC10 Defect Detection | Inspection result (casting), defect category (NEU), unlike-any-sound-part flag (MVTec) and located defects with their boxes (GC10) |
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

Additional n8n workflows are roadmap items. They are not prerequisites for the MVP. Four of the original roadmap items have since landed: RAG as the grounded assistant, NEU on 2026-09-01 as the second computer-vision module (`docs/Model_Card_NEU_Surface.md`), MVTec on 2026-09-02 as the third, four component anomaly detectors that fit on sound parts alone and train nothing (`docs/Model_Card_MVTec_Anomaly.md`), and GC10 on 2026-09-02 as the fourth and the object detection item, which is the only module that answers where a defect is rather than whether there is one (`docs/Model_Card_GC10_Detection.md`).

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

**What `evidence` may hold, and what it may not.** The four keys in the example - `record_id`, `model_version`, `prediction` and `threshold` - are required of every module and are the only ones any consumer may assume. Beyond them the object is deliberately open, because what a person needs in order to act on an event differs by module: NEU carries the whole six-way probability vector so a reader can see the runner-up, MVTec carries the category and the ceiling its threshold came from, and GC10 carries `detections`, a list of located defects with their boxes, because a detector's answer is several boxes on one frame rather than one number about it. **A list in `evidence` needed no change to this contract**, which is worth recording because it was expected to: the schema declares `evidence` with `additionalProperties: true` and the validator checks only that the four required keys are present.

The field that is closed, and therefore the one thing a new module does change, is `source_module`. It is an enum in both `events/arkon_event_schema.json` and `events/validate_event.py`, and adding a module means adding a name to both.

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

**Not in v1, 2026-08-30.** This section is the design. The deployed workflow writes an incident once, at `new`, and there is no write path for any later state: no transition is recorded, no response-time KPI is computed, and no incident has yet gone from new to closed. The lifecycle write path is scheduled with the move to a queryable store in section 7.5.

### 7.3 Ownership and assignment

Assignment happens at workflow intake, not in the model adapter. A routing table maps business_domain and priority to a role: asset_reliability to Maintenance Planner, fleet_reliability to Fleet Reliability Engineer, visual_inspection to QC Engineer, field_quality to Field Quality Analyst. P1 additionally notifies the Quality Manager. The people behind the roles come from a simulated roster file labelled `context_origin: simulated` under the section 5 rules.

### 7.4 Communication and escalation

The alert channel is a Telegram bot driven by n8n: an incident card with priority, summary, evidence reference, and for computer-vision events the defect image, plus inline acknowledge and close buttons. The channel is an adapter: a corporate deployment would swap the Telegram node for a Microsoft Teams node without changing the workflow. P1 and P2 incidents that are not acknowledged within their response window trigger a manager notification. A daily digest summarises open incidents.

**What v1 actually sends, 2026-08-30.** A text-only Telegram card for P1 and P2, carrying priority, incident id, summary, assignee, recommended action and the event id. It has **no inline acknowledge or close buttons**, and there is nothing behind them to call: acknowledgement needs the lifecycle write path of section 7.2. There is no unacknowledged-incident timer and no manager notification, and there is no daily digest. The image attachment for vision events arrives with the vision module. Read the paragraph above as the target and this one as the deployment.

### 7.5 Incident store and dashboards

The incident record of truth is one SQLite database written by the n8n workflow; its exact mount location is fixed against the NAS compose file at deployment time. **Deviation in v1, 2026-08-30:** the deployed workflow appends to a JSONL file at `/data/arkon/incidents.jsonl` on the NAS instead. The move to a queryable store is scheduled together with the lifecycle transitions of section 7.2, since both are needed by the same consumer, and now targets the n8n Data Table node rather than a separate SQLite file: it is native to the deployed platform and supports insert, get, update and upsert. A read API over the same store was added on 2026-08-30, `GET /webhook/arkon-incident-status`, so the assistant and any other consumer query incidents through one validated contract instead of reaching into the file; it moves to the queryable store with the rest. See `n8n/README.md`. Streamlit reads the store directly and serves as the live operational cockpit. Tableau reads periodic extracts and serves as the executive KPI view: open incidents by priority, response times, and trend Pareto. A live Tableau connection would require a paid Tableau Server; extract refresh is the documented portfolio boundary. **Not in v1, 2026-08-30:** neither the Streamlit cockpit nor the Tableau view is built. Both are Phase 3 items. The operational view that does exist is the conversational one, the Arkon Quality Assistant of `langflow/README.md`, which reads incidents through the status API.

### 7.6 Intake outcomes, and the two that leave no trace

Added 2026-08-31, from reading the deployed workflow's connections rather than its description. Every event that reaches the Steering Cell webhook has exactly three possible outcomes: recorded as an incident, rejected as invalid against the section 6 event contract, or suppressed as a duplicate inside the 24-hour dedup window. **Only the first one is written anywhere.**

Measured on the deployed `Arkon Quality Steering Cell v1`: the `Valid?` false branch goes to `Respond Invalid` and the `Duplicate?` true branch goes to `Respond Duplicate`, and neither reaches `Append Incident Record`. The caller receives an HTTP response naming the reason, and nothing survives it. The incident store therefore holds what got through, and there is no record at all of what did not.

Three consequences, and they are not equally harmless:

- **Suppression cannot be counted.** Dedup is a real decision made on every event, and the charter presents it as a feature, but nobody can answer how many duplicates it absorbed today or whether the 24-hour window is the right one. The evidence for tuning it is discarded by the same run that makes the decision.
- **A validation regression is indistinguishable from a quiet plant.** If a schema change starts rejecting every event, the incident store simply stops growing. There is no counter that falls, no error that accumulates, and no alert, because an alert requires an incident and no incident is created. This is the failure mode worth naming in a readiness review: the system fails silently in exactly the direction that looks like good news.
- **The assistant inherits the blind spot.** It reads the incident store through the status API, so its answer to "what is open right now" is complete and its answer to "did anything not get through" cannot exist. Nothing in the assistant is wrong; it cannot see past its source.

**Not fixed in v1, and the reason is a priority call rather than a technical one.** The fix is small in shape: the intake outcome is itself an event, and writing all three outcomes with their reason to one intake log costs one node and one file. It is not done because Phase 1 was closed on 2026-08-30 and the binding deadline belongs to a different piece of work; changing the Phase 1 workflow now buys nothing that is graded and reopens something that was deliberately closed. Recorded here so the gap is inherited knowingly rather than discovered later.

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

- **DONE 2026-08-30.** Scania APS classification, publishing the same event contract. `docs/Model_Card_Scania_APS.md`.
- **DONE 2026-08-30.** Casting Defect computer vision, publishing the same event contract. `docs/Model_Card_Casting_CV.md`.
- **DONE 2026-09-01.** NEU steel surface defect classification, publishing the same event contract. `docs/Model_Card_NEU_Surface.md`. A roadmap item rather than an original Phase 2 entry, listed here because it publishes the contract.
- **DONE 2026-09-02.** MVTec component anomaly detection, publishing the same event contract. `docs/Model_Card_MVTec_Anomaly.md`. Also a roadmap item, and the third module in the `visual_inspection` domain.
- **DONE 2026-09-02.** GC10 steel sheet defect detection, publishing the same event contract. `docs/Model_Card_GC10_Detection.md`. The roadmap's object-detection item, the fourth module in the `visual_inspection` domain, and the first whose event carries a list rather than a single measurement.
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

**Status 2026-08-30: all five are met.** The first three and the fifth were met when Phase 1 closed. The fourth was the last one open and is met by the Arkon Quality Assistant (`langflow/README.md`), a conversational operational interface that reads incidents through the status API: an operator can ask what an incident is doing and get the answer from the store rather than from the model. Two boundaries belong with that claim. The human-review step of the third criterion is the Telegram alert, and the review is not captured back, because there is no acknowledgement write path (section 7.2). And the interface is conversational only: the Streamlit cockpit and the Tableau view of section 7.5 are Phase 3 and are not built.

## 11. Status and next action

**Phase 1 closed 2026-08-30.** All four deliverables are done and verified.

The figures below were read from `docs/Model_Card_CMAPSS_RUL.md` and counted in `events/out/` on 2026-08-30. An earlier version of this block was written before the full-fleet retrain and carried that run's numbers; it is corrected here rather than left standing, because this charter is one of the documents in the assistant's knowledge base and a wrong figure in it is a wrong figure the assistant will quote and cite.

- **The CMAPSS model is reproducible and covers the full fleet:** all four subsets, 709 training and 707 test engines, six operating regimes and two fault modes. XGBoost reaches **RMSE 11.01, MAE 7.62, R2 0.932** on the benchmark task, which is one prediction per engine at its last observed cycle, n = 707. Across all 104,897 test rows it reaches **RMSE 10.05, MAE 6.13, R2 0.860**. It scores the hardest subset about as well as the easiest: FD004 11.48 against FD001 9.69. The whole gain is in the temporal features, worth 5.32 RMSE on the benchmark task against 1.67 for the cycle counter on those same 707 engines; the extra subsets are worth 0.92 on the benchmark task and 0.77 across every test row, both scored on FD001 alone because the FD001-only arm has never seen the other three subsets and that is the only test set both arms can fairly be shown. The three figures are therefore not on one basis, which the model card's table now states row by row. Full figures, the ablation and the limitations are in `docs/Model_Card_CMAPSS_RUL.md`; the training script is `notebooks/01_timeseries/cmapss_full_fleet.py`.
- **The risk-event adapter produces contract-valid events.** `events/out/cmapss_events_full_fleet.jsonl` holds **707 events**, one per test engine: 49 P1, 87 P2, 90 P3 and 481 P4 under the section 7.1 thresholds. The superseded FD001 baseline file `cmapss_events_FD001.jsonl` with its 100 events is kept beside it as the comparison point.
- **Simulated operational context is attached and labelled** per section 5.
- **The n8n Quality Steering Cell is deployed on the NAS and verified end to end:** contract violations rejected with HTTP 400, incidents created with `ARK-INC-*` ids, duplicates suppressed across production runs, incident records appended to the store, and Telegram cards delivered for P1 and P2. Deployment record and the three n8n 2.0 traps met on the way are in `n8n/README.md`.

**One Phase 3 item was brought forward and is also done.** The grounded assistant of section 9 was built on Langflow on 2026-08-30, against this documentation and the deployed workflow, and it closes the last open MVP criterion of section 10. Its precondition was the one Phase 3 states - documentation, model cards and incident records first - and that precondition was met before it was built. Two further n8n endpoints came with it: `GET /webhook/arkon-incident-status` and `POST /webhook/arkon-escalation`. See `langflow/README.md` and `n8n/README.md`.

**Five modules beyond CMAPSS publish the section 6 event contract.** Two of them are Phase 2 entries and three are roadmap items that landed early, and the distinction matters only to the plan: to the platform they are five modules on one contract. Only NHTSA text classification, the last Phase 2 entry, has nothing behind it.

**Which of them have been sent through the deployed Steering Cell, when, and with what result is the run log in `n8n/README.md`, and it is kept there rather than here deliberately.** This document is ingested into the assistant's knowledge store. A sentence about what has been run so far is false the moment anybody runs something, and correcting it here costs a snapshot, a collection drop, a rebuild and a re-measurement; `n8n/README.md` is not ingested and carries no such cost. What belongs in this charter is what the platform is and what version 1 can do, both of which the assistant has to be able to answer.

- **Scania APS classification** (`docs/Model_Card_Scania_APS.md`). Total cost 10,660 on the dataset's own metric of 10 per needless workshop check and 500 per missed failure: 416 false positives, 13 missed, recall 0.965, ROC AUC 0.995, which lands between first and second of the 2016 challenge's published top three on the same test set. It closes a gap the CMAPSS card names and does not fix, its limitation 5: RMSE punishes both error directions equally while the business does not. Here the asymmetry is the metric, and the decision threshold is worth a factor of 3.8 while every structural choice sits inside the noise of the selection: three fold seeds produced three different winners.
- **Casting Defect visual inspection** (`docs/Model_Card_Casting_CV.md`). 715 test images, 0 defects missed and 7 good parts rejected, ROC AUC 0.9999. Two qualifications from the 2026-09-01 notebook rebuild, both in the model card. The published test folder shares 64 byte-identical images with the training folder, all of them good parts, so the recall claim is clean and the false-alarm claim is measured on a partly seen set: 3.03 percent on genuinely unseen good parts against 2.67 (limitation 8). And the operating point is not reproducible - four runs from one seed span 0.0436 to 0.2203, 0 to 2 missed defects and 2 to 11 rejected good parts - so the 0 above is one draw rather than a guarantee (limitation 6). Its priority bands run the opposite way to the other two modules: banding by confidence produced 447 P1 events out of one batch, so a confident defect is P3 routine scrap and the uncertain band, where the model is a coin flip and the line actually stops, is P2.
- **NEU steel surface defect classification** (`docs/Model_Card_NEU_Surface.md`). Six defect types on hot-rolled strip, 1.0000 accuracy and macro F1 on 360 held-out images. **The number is qualified in the card and should not be quoted without its qualification**: a 1-nearest-neighbour classifier over un-finetuned ImageNet features reaches 0.9750 on the same folder, so this benchmark is close to saturated. The dataset ships no test folder, so the folder it calls `validation/` is held out and scored once, and every reported number names the folder it came from. Two structural findings: 6.8 per cent of images carry a second defect class the folder label discards, a ceiling on any single-label model; and the confidence band could not be calibrated because the model classified all 216 selection images correctly, so its band edge is declared as an Arkon assumption under section 7.1 rather than measured. It is the second module in the `visual_inspection` domain, which needed no contract change, and the first whose `risk_type` varies between its own events. 360 events published, 3 P2 and 357 P3. It is also the first module whose record identifiers carry an underscore, which turned out to matter to the alert channel rather than to the contract; `n8n/README.md` has that story.
- **MVTec component anomaly detection** (`docs/Model_Card_MVTec_Anomaly.md`). Four detectors, one per component category, and the first module here that trains nothing: a frozen ImageNet backbone, a coreset of feature vectors taken from sound parts only, and a nearest-neighbour distance. Mean image AUROC 0.9817 and mean pixel AUROC 0.9738, and **the four rows matter more than the mean**, which the card says in its own words: they span 0.0350 from 0.9650 on screw to 1.0000 on metal_nut, and the realised false-alarm rate spans 9.8 to 22.7 per cent against a declared budget of 5. It is the third module in the `visual_inspection` domain, so that field has stopped being a proxy for a module in three places rather than two. Both of its priority edges come from held-out sound parts and neither has ever seen a defect, which is the casting operating-point lesson applied rather than restated: casting searched a cost curve for an optimum that moved by a factor of five between identical runs, so this module declares a budget and reads a quantile. 309 events published from 453 test images, 262 P2 and 47 P3, with 20 defective parts never published and 20 sound parts published as a false alarm.


**What the five modules after CMAPSS cost the platform: one API projection, and then one alert defect that had been there all along.** The intake workflow has needed no change for any of them, because it validates a contract rather than a domain; the runs that establish that are in the `n8n/README.md` log. The status API needed a real fix on the second and third, and it was not the cosmetic one it had been recorded as: it projected `evidence.prediction` as `predicted_rul` for every module, so a Scania failure probability of 0.0373 was served as a remaining useful life of 0.0373 cycles and the assistant reported it as one. The projection now returns the evidence object as published, and that fix is why MVTec cost nothing: an MVTec incident keeps its own `category`, `ceiling` and `threshold_basis` without anyone touching the API.

**Then NEU's identifiers cost something real, and the platform had been carrying the fault since its first deployment.** The alert body was a Markdown template with raw event values interpolated into it, so any identifier containing an underscore made the messaging API refuse the whole card - while the incident had already been written and its id consumed, and the caller was answered HTTP 200. It survived because the branch had only ever been exercised with the one module whose identifiers happen to contain no character the markup treats as markup. Fixed by building and escaping the body in code, deployed and verified.

**The general form belongs in this charter rather than only in a README, because it is a rule about how this platform is validated and not an anecdote about one node: a path exercised solely with data that happens to be safe is an untested path, and this one reported success while failing.** The instance, its measured reach across every batch, and the deploy procedure are in `n8n/README.md`.

**And MVTec cost an identity, where the defect was in the adapter rather than in the platform.** The MVTec adapter built a part identity from the category and the image file name, and MVTec numbers its test images from `000` inside every defect-type folder, so 309 events carried 82 distinct record ids. Intake deduplicates on record id and priority together, per section 7.1, so replaying the batch would have suppressed 203 flagged parts as duplicates of parts they are not. Fixed 2026-09-02; the other four adapters were checked for the same class and each produces one record id per event. The general form is worth keeping: a deduplication key is a claim that two records describe the same thing, and it is only ever as good as the identity the publisher builds.

**Next action: NHTSA text classification** and field-quality trend detection, the last Phase 2 module, then Phase 3's Streamlit and Tableau views, which are the two operational surfaces section 7.5 describes and neither of which exists.
