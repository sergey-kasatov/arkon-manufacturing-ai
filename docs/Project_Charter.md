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

Additional n8n workflows are roadmap items. They are not prerequisites for the MVP. Four of the original roadmap items have since landed: RAG as the grounded assistant, NEU on 2026-09-01 as the second computer-vision module (`docs/Model_Card_NEU_Surface.md`), MVTec on 2026-09-02 as the third, four component anomaly detectors that fit on sound parts alone and train nothing (`docs/Model_Card_MVTec_Anomaly.md`), GC10 on 2026-09-02 as the fourth and the object detection item, which is the only module that answers where a defect is rather than whether there is one (`docs/Model_Card_GC10_Detection.md`), and NHTSA on 2026-09-03 as the NLP field-quality module, which is the MVP entry above rather than a roadmap item and the last Phase 2 module to be built (`docs/Model_Card_NHTSA_Field_Quality.md`).

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

and NHTSA carries the manufacturer, the component, the month and the counts behind a trend, because its answer is about a rate rather than about a thing it inspected.

**A caution that arrived with the seventh module.** `evidence.prediction` and `evidence.threshold` are required of every module, and until NHTSA they were always a model output and a decision boundary on it. NHTSA publishes two counts there instead: the complaints observed in a cell and the number the cell's own history predicted. That is inside this contract, which constrains neither key beyond requiring it, and it means a consumer comparing `threshold` across modules is comparing two different kinds of number. Read `source_module` first.

The field that is closed, and therefore the one thing a new module usually does change, is `source_module`. It is an enum in both `events/arkon_event_schema.json` and `events/validate_event.py`, and adding a module means adding a name to both. **NHTSA is the exception and the only one so far: it needed no change to this contract at all**, because `nhtsa_nlp` was written into that enum and `field_quality` into `business_domain` when the platform was designed, and the role behind the domain was already in `roster.json`.

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

A reviewed incident may instead be marked false_positive; that outcome is kept and feeds threshold tuning. Every transition is timestamped, and response-time KPIs are computed from these timestamps. The demo must show at least one full path from new to closed.

**Built 2026-09-03.** `POST /webhook/arkon-incident-transition` records the later states. The paragraph above is now the deployment rather than the design, with three qualifications that belong with it.

**Transitions are appended to a log, not written into the incident record.** The incident line is written once at `new` and never rewritten, and the current status of an incident is the fold of `/data/arkon/incident_transitions.jsonl` onto that line. Three reasons, in order of weight: the incident store is append-only and every write path keeps it that way; a read-modify-write of the whole store would race the intake workflow, which appends to the same file with no lock; and a response-time KPI needs both timestamps, where an overwritten record keeps one. Every consumer that reports a status performs the fold, so the same code decides the answer in all three of them; it lives in `n8n/build/lifecycle.py`. The cost is that a consumer reading only the incident store sees `new` for ever, which is why the status API returns `raised_as` on every record.

**The machine refuses moves as well as making them.** `closed` and `false_positive` are terminal, `new` can never be re-entered, and `resolved -> in_containment` is the one backward edge, for a containment that did not hold. A request the lifecycle does not allow is refused with HTTP 409 naming the current status and the allowed next states, which is a different answer from a malformed request: a caller has to be able to tell "you asked wrong" from "you are too late". Because of the backward edge, every KPI is computed from the **first** time a milestone is reached.

**What this unblocked.** `overdue_incidents` always meant "still unacknowledged past the 7.1 window" and, with nothing able to stop being unacknowledged, counted the whole store; it is a measurement now. The `status` filter on the read API was a filter over a constant. And the Phase 4 criterion in section 9 could not be met at all. Detail, the deployment record and the boundaries are in `n8n/README.md`. What is still not built is the callback path of section 7.4: nothing calls this endpoint automatically and the alert card still has no buttons.

### 7.3 Ownership and assignment

Assignment happens at workflow intake, not in the model adapter. A routing table maps business_domain and priority to a role: asset_reliability to Maintenance Planner, fleet_reliability to Fleet Reliability Engineer, visual_inspection to QC Engineer, field_quality to Field Quality Analyst. P1 additionally notifies the Quality Manager. The people behind the roles come from a simulated roster file labelled `context_origin: simulated` under the section 5 rules.

### 7.4 Communication and escalation

The alert channel is a Telegram bot driven by n8n: an incident card with priority, summary, evidence reference, and for computer-vision events the defect image, plus inline acknowledge and close buttons. The channel is an adapter: a corporate deployment would swap the Telegram node for a Microsoft Teams node without changing the workflow. P1 and P2 incidents that are not acknowledged within their response window trigger a manager notification. A daily digest summarises open incidents.

**What v1 actually sends, 2026-08-30, corrected 2026-09-03 and 2026-09-06.** A text-only Telegram card for P1 and P2, carrying priority, incident id, summary, assignee, recommended action and the event id, and since 2026-09-05 a link that opens that incident on the cockpit's Steering Cell page, where the transition form is. It has **no inline acknowledge or close buttons**, and on this deployment it cannot have them: callback handling needs a Telegram Trigger node with an address that Telegram can reach, and the workflow's webhook address on this NAS is a private network name, so a button would have nothing reachable to call. Opening one path to the internet is possible and is a decision rather than a task; for v1 the buttons are closed, and the lifecycle write path of section 7.2 is deployed, so what a button would call exists. **The manager notification and the daily digest are deployed since 2026-09-06**, both as scheduled n8n workflows that read the status API and decide nothing it already decides. The overdue escalation (`n8n/overdue_escalation_v1.json`) checks every fifteen minutes for a P1 or P2 still unacknowledged past its section 7.1 window and puts one card per incident, once, in front of the Quality Manager in the alert group, longest wait first and at most three per run. The daily digest (`n8n/daily_digest_v1.json`) sends one card at 07:05 plant time with the open incidents by priority and lifecycle state, the overdue count, the response-time medians and the P3 queue for the daily review. Every card of either kind is recorded in `/data/arkon/incident_notifications.jsonl` with Telegram's own message id, so that log is evidence of delivery rather than of intent. The image attachment for vision events arrives with the vision module. Read the first paragraph as the target and this one as the deployment.

### 7.5 Incident store and dashboards

The incident record of truth is one SQLite database written by the n8n workflow; its exact mount location is fixed against the NAS compose file at deployment time. **Deviation in v1, 2026-08-30:** the deployed workflow appends to a JSONL file at `/data/arkon/incidents.jsonl` on the NAS instead. A read API over the same store was added on 2026-08-30, `GET /webhook/arkon-incident-status`, so the assistant and any other consumer query incidents through one validated contract instead of reaching into the file. See `n8n/README.md`. Streamlit reads the store directly and serves as the live operational cockpit. Tableau reads periodic extracts and serves as the executive KPI view: open incidents by priority, response times, and trend Pareto. A live Tableau connection would require a paid Tableau Server; extract refresh is the documented portfolio boundary. **The Streamlit cockpit was built 2026-09-04** and is deployed on the NAS at `http://AK2101:8303` (`app/README.md`). It reads incidents through the status API rather than opening the store, which is not a detail: the store holds the state an incident was raised in and holds it for ever, so a cockpit reading the file directly would show every incident as `new` and never anything else. It shows the counts by priority and lifecycle state, the response-time KPIs, and any incident with the full history of who moved it when; it also carries a page per module, built from the tracked metrics files, and the assistant with its approval gate. **The Tableau extract layer was built 2026-09-04** (`tableau/README.md`): four tidy fact tables refreshed from the same status API by one command, which verify their own completeness and exit non-zero if the API's page cap (500 since 2026-09-06) ever truncates a lifecycle state. **The workbook was built 2026-09-05 and published on Tableau Public on 2026-09-06** (`tableau/README.md`): generated as XML by `tableau/build_workbook.py` from the extracts, an Executive view with no controls and an Explore view with filters, and a refresh loop that rebuilds the extracts and the workbook on a timer while the publish click stays a person's. A note here once claimed the installed Tableau Public could save only to the public cloud; reading the application on 2026-09-05 refuted that, and the authored `.twb` needed no local save at all. With it the Phase 3 list of section 9 is complete; what remains from this section is the queryable store below. The conversational view of `langflow/README.md` continues to exist alongside the cockpit and reads the same API.

**The queryable store and the lifecycle were scheduled together, and were separated on 2026-09-03.** The reasoning here used to be that both were needed by the same consumer, so both would land at once. That turned out to be wrong in the useful direction: the lifecycle needed no queryable store at all, because transitions append to a second log rather than rewriting an incident line, and appending is what the current store already does well. So the lifecycle shipped on JSONL and the store move did not have to be dragged in with it. Two files are now read on every status call, `incidents.jsonl` and `incident_transitions.jsonl`, and the fold across them is what makes the move worth doing eventually: it is linear in the size of both files on every request, which is right at demo scale and wrong at plant scale. The target remains the n8n Data Table node rather than a separate SQLite file, because it is native to the deployed platform and supports insert, get, update and upsert. It is now paced by the Streamlit cockpit rather than by the lifecycle.

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
- **DONE 2026-09-03.** NHTSA consumer-complaint text classification and field-quality trend detection, publishing the same event contract. `docs/Model_Card_NHTSA_Field_Quality.md`. The last Phase 2 entry, the only module in the `field_quality` domain, the first over free text, and the first that needed no contract change at all.

**Phase 2 is closed.**

### Phase 3: Product integration

- **DONE 2026-09-04.** Streamlit views for module results and incident status, deployed as one cockpit. `app/README.md`. The events themselves are visible through the incidents they raised rather than as a separate view, which is the shape the platform actually has: an event that was suppressed as a duplicate or rejected as invalid leaves no trace to show, per section 7.6.
- **DONE 2026-09-05, published 2026-09-06.** Tableau views for aggregated risk, response time, and quality trends: `tableau/Arkon_Executive_View.twb`, generated from four extract tables refreshed off the status API (`tableau/README.md`). The response times it needs exist since 2026-09-03.
- Add a grounded RAG assistant only after documentation, model cards, and incident records exist. **DONE 2026-08-30**, brought forward once its stated precondition was met. `langflow/README.md`.
- **DONE 2026-09-03.** The incident lifecycle write path of section 7.2, which is not itself a Phase 3 item but which both remaining ones need: a cockpit and a KPI view over a store where nothing ever moves have nothing to show. `n8n/README.md`.

### Phase 4: Portfolio completion

- Produce model cards, data cards, architecture diagrams, and a demo script.
- Demonstrate one complete incident path from model output to human-reviewed closure. **DONE 2026-09-03**, and it was the last criterion in this document that could not be met at all rather than merely being unbuilt. `ARK-INC-00013`, a P1 raised from a real CMAPSS prediction of 8 remaining cycles on engine unit 82, went `new -> acknowledged -> in_containment -> resolved -> closed` as `ARK-TRN-00001` to `00004`. Two more paths were recorded the same day and each shows something the first does not: `ARK-INC-00016` was marked `false_positive` in one step, which is the other outcome this section's lifecycle names, and it was the right call on its merits because that incident is the attribution test record rather than a real engine; and `ARK-INC-00032` was driven through the reopen edge, `resolved -> in_containment -> resolved -> closed`, which is what proves the response times come from the first time a milestone is reached rather than the last. **The response times are honest rather than flattering**: both acknowledgements are outside their charter 7.1 window by days, because the incidents were raised on 2026-08-30 and nobody was watching a demo store. That is what the KPI is for.
- Document limitations, false-positive trade-offs, and simulated-data boundaries.

## 10. MVP success criteria

The MVP is complete when all of the following are true:

- At least one model is reproducible end to end with an honest held-out evaluation.
- Its output is converted to a versioned Arkon risk event.
- n8n validates, de-duplicates, records, and routes the event to a human-review step.
- The decision and event status can be seen in an operational interface.
- The repository documents data provenance, model limitations, and any simulated context.

**Status 2026-08-30: all five are met.** The first three and the fifth were met when Phase 1 closed. The fourth was the last one open and is met by the Arkon Quality Assistant (`langflow/README.md`), a conversational operational interface that reads incidents through the status API: an operator can ask what an incident is doing and get the answer from the store rather than from the model. Two boundaries belonged with that claim, and **one of them was removed on 2026-09-03**. The human-review step of the third criterion is the Telegram alert, and the review used to be lost: an operator who acted on a card left no trace in the system, because there was no acknowledgement write path. Section 7.2 is now deployed, so a review is captured, timestamped and reportable, and the assistant reads it back through the same status API it already used. What is still true is that the card has no buttons (section 7.4); since 2026-09-05 it carries a link to the cockpit page where the operator makes the move, and since 2026-09-06 a lapsed window is escalated and summarised by the platform rather than left to be noticed. The second boundary fell with Phase 3: the Streamlit cockpit (2026-09-04) and the Tableau view (2026-09-05, published 2026-09-06) of section 7.5 are built, so the conversational interface is one of three operational views rather than the only one.

## 11. Status and next action

**Phase 1 closed 2026-08-30.** All four deliverables are done and verified.

The figures below were read from `docs/Model_Card_CMAPSS_RUL.md` and counted in `events/out/` on 2026-08-30. An earlier version of this block was written before the full-fleet retrain and carried that run's numbers; it is corrected here rather than left standing, because this charter is one of the documents in the assistant's knowledge base and a wrong figure in it is a wrong figure the assistant will quote and cite.

- **The CMAPSS model is reproducible and covers the full fleet:** all four subsets, 709 training and 707 test engines, six operating regimes and two fault modes. XGBoost reaches **RMSE 11.01, MAE 7.62, R2 0.932** on the benchmark task, which is one prediction per engine at its last observed cycle, n = 707. Across all 104,897 test rows it reaches **RMSE 10.05, MAE 6.13, R2 0.860**. It scores the hardest subset about as well as the easiest: FD004 11.48 against FD001 9.69. The whole gain is in the temporal features, worth 5.32 RMSE on the benchmark task against 1.67 for the cycle counter on those same 707 engines; the extra subsets are worth 0.92 on the benchmark task and 0.77 across every test row, both scored on FD001 alone because the FD001-only arm has never seen the other three subsets and that is the only test set both arms can fairly be shown. The three figures are therefore not on one basis, which the model card's table now states row by row. Full figures, the ablation and the limitations are in `docs/Model_Card_CMAPSS_RUL.md`; the training script is `notebooks/01_timeseries/cmapss_full_fleet.py`.
- **The risk-event adapter produces contract-valid events.** `events/out/cmapss_events_full_fleet.jsonl` holds **707 events**, one per test engine: 49 P1, 87 P2, 90 P3 and 481 P4 under the section 7.1 thresholds. The superseded FD001 baseline file `cmapss_events_FD001.jsonl` with its 100 events is kept beside it as the comparison point.
- **Simulated operational context is attached and labelled** per section 5.
- **The n8n Quality Steering Cell is deployed on the NAS and verified end to end:** contract violations rejected with HTTP 400, incidents created with `ARK-INC-*` ids, duplicates suppressed across production runs, incident records appended to the store, and Telegram cards delivered for P1 and P2. Deployment record and the three n8n 2.0 traps met on the way are in `n8n/README.md`.

**One Phase 3 item was brought forward and is also done.** The grounded assistant of section 9 was built on Langflow on 2026-08-30, against this documentation and the deployed workflow, and it closes the last open MVP criterion of section 10. Its precondition was the one Phase 3 states - documentation, model cards and incident records first - and that precondition was met before it was built. Two further n8n endpoints came with it: `GET /webhook/arkon-incident-status` and `POST /webhook/arkon-escalation`. See `langflow/README.md` and `n8n/README.md`.

**Six modules beyond CMAPSS publish the section 6 event contract, and Phase 2 is closed.** Three of them are Phase 2 entries and three are roadmap items that landed early, and the distinction matters only to the plan: to the platform they are six modules on one contract. Nothing in Phase 2 is now unbuilt.

**Which of them have been sent through the deployed Steering Cell, when, and with what result is the run log in `n8n/README.md`, and it is kept there rather than here deliberately.** This document is ingested into the assistant's knowledge store. A sentence about what has been run so far is false the moment anybody runs something, and correcting it here costs a snapshot, a collection drop, a rebuild and a re-measurement; `n8n/README.md` is not ingested and carries no such cost. What belongs in this charter is what the platform is and what version 1 can do, both of which the assistant has to be able to answer.

- **Scania APS classification** (`docs/Model_Card_Scania_APS.md`). Total cost 10,660 on the dataset's own metric of 10 per needless workshop check and 500 per missed failure: 416 false positives, 13 missed, recall 0.965, ROC AUC 0.995, which lands between first and second of the 2016 challenge's published top three on the same test set. It closes a gap the CMAPSS card names and does not fix, its limitation 5: RMSE punishes both error directions equally while the business does not. Here the asymmetry is the metric, and the decision threshold is worth a factor of 3.8 while every structural choice sits inside the noise of the selection: three fold seeds produced three different winners.
- **Casting Defect visual inspection** (`docs/Model_Card_Casting_CV.md`). 715 test images, 0 defects missed and 7 good parts rejected, ROC AUC 0.9999. Two qualifications from the 2026-09-01 notebook rebuild, both in the model card. The published test folder shares 64 byte-identical images with the training folder, all of them good parts, so the recall claim is clean and the false-alarm claim is measured on a partly seen set: 3.03 percent on genuinely unseen good parts against 2.67 (limitation 8). And the operating point is not reproducible - four runs from one seed span 0.0436 to 0.2203, 0 to 2 missed defects and 2 to 11 rejected good parts - so the 0 above is one draw rather than a guarantee (limitation 6). Its priority bands run the opposite way to the other two modules: banding by confidence produced 447 P1 events out of one batch, so a confident defect is P3 routine scrap and the uncertain band, where the model is a coin flip and the line actually stops, is P2.
- **NEU steel surface defect classification** (`docs/Model_Card_NEU_Surface.md`). Six defect types on hot-rolled strip, 1.0000 accuracy and macro F1 on 360 held-out images. **The number is qualified in the card and should not be quoted without its qualification**: a 1-nearest-neighbour classifier over un-finetuned ImageNet features reaches 0.9750 on the same folder, so this benchmark is close to saturated. The dataset ships no test folder, so the folder it calls `validation/` is held out and scored once, and every reported number names the folder it came from. Two structural findings: 6.8 per cent of images carry a second defect class the folder label discards, a ceiling on any single-label model; and the confidence band could not be calibrated because the model classified all 216 selection images correctly, so its band edge is declared as an Arkon assumption under section 7.1 rather than measured. It is the second module in the `visual_inspection` domain, which needed no contract change, and the first whose `risk_type` varies between its own events. 360 events published, 3 P2 and 357 P3. It is also the first module whose record identifiers carry an underscore, which turned out to matter to the alert channel rather than to the contract; `n8n/README.md` has that story.
- **MVTec component anomaly detection** (`docs/Model_Card_MVTec_Anomaly.md`). Four detectors, one per component category, and the first module here that trains nothing: a frozen ImageNet backbone, a coreset of feature vectors taken from sound parts only, and a nearest-neighbour distance. Mean image AUROC 0.9817 and mean pixel AUROC 0.9738, and **the four rows matter more than the mean**, which the card says in its own words: they span 0.0350 from 0.9650 on screw to 1.0000 on metal_nut, and the realised false-alarm rate spans 9.8 to 22.7 per cent against a declared budget of 5. It is the third module in the `visual_inspection` domain, so that field has stopped being a proxy for a module in three places rather than two. Both of its priority edges come from held-out sound parts and neither has ever seen a defect, which is the casting operating-point lesson applied rather than restated: casting searched a cost curve for an optimum that moved by a factor of five between identical runs, so this module declares a budget and reads a quantile. 309 events published from 453 test images, 262 P2 and 47 P3, with 20 defective parts never published and 20 sound parts published as a false alarm.
- **GC10 steel sheet defect detection** (`docs/Model_Card_GC10_Detection.md`). Ten defect classes located with bounding boxes, and **the only module that answers where**: the other four return one answer for a whole frame, which is the gap the NEU card names in its own limitation 3. mAP@0.5 0.6260 on 339 held-out sheets, 350 of 544 annotated boxes located and 231 claimed that are not there. **Three qualifications belong with that number and the card leads with them.** It **does not reproduce**: refitting from the same seed moved test mAP 0.6260 to 0.6462 and the detection threshold 0.60 to 0.60, so the shipped model is the worse of two draws and a refit changes who is asked to look at a coil, which is the casting instability on a different architecture. **It cannot pass a sheet**: this dataset contains none anyone certified clean, so the module was fitted and scored only on sheets carrying a defect and its silence on 29 of 339 test sheets is a failure to find rather than a pass. And **the per-class spread is not the sample sizes**, which the run refuted: silk spot has the most boxes of any class, 167, and scores 0.2676. Two operating points where every other module has one, the box threshold calibrated at 0.60 and the priority band edge declared at 0.90 because that rule returned nothing, which is NEU's rule degenerating again from the opposite end. It is the fourth module in `visual_inspection` and the first whose `evidence` carries a list, which needed no contract change. 310 events published from 339 test sheets, 63 P2 and 247 P3.
- **NHTSA consumer-complaint field quality** (`docs/Model_Card_NHTSA_Field_Quality.md`). The only module in the `field_quality` domain, the last Phase 2 entry, and **the first whose input is not a measurement**: it reads what a member of the public wrote about their own vehicle rather than something the platform inspected, which is why nothing it publishes may be read as evidence that a part failed. Multi-label component classification over 60,039 complaints received in 2024, 24 classes, **micro F1 0.6867 and macro F1 0.6306** from the narrative text alone; 93% of complaints get at least one component right and 41% the exact set. **Three findings belong with that number.** The component column is **two labellings joined on 2020-11-04**, the day an intake form changed, so the window starts there and 50,170 complaints are discarded - the GC10 lesson that the label is whatever the file holds, in a new costume. It is **the first Arkon module that reproduces exactly**, a refit moving no predicted probability at all, over 1,440,936 of them. And its events are about a signal rather than a part: 3,080 manufacturer-component-month cells were tested against their own trailing baselines and **25 published**, 9 P2 and 16 P3, because 60,039 events would bury the incident store. **What that batch is worth is measured, which no other module here can do**: run the identical trend over the held-out labels and the module's flags score precision 0.520 and recall 0.684, so about half of what it publishes is not confirmed. The priority band is **declared, not calibrated, for the third module running and the third distinct reason** - it needed 30 calibration cells and got 5 - and the run then measured whether the band means anything at all: correlation between the risk score and confirmation is -0.056 and the ordering inverts at the top, so **the band says how large a movement is and never how certain**.


**What the six modules after CMAPSS cost the platform: one API projection, and then one alert defect that had been there all along.** The intake workflow has needed no change for any of them, because it validates a contract rather than a domain; the runs that establish that are in the `n8n/README.md` log. The status API needed a real fix on the second and third, and it was not the cosmetic one it had been recorded as: it projected `evidence.prediction` as `predicted_rul` for every module, so a Scania failure probability of 0.0373 was served as a remaining useful life of 0.0373 cycles and the assistant reported it as one. The projection now returns the evidence object as published, and that fix is why MVTec cost nothing: an MVTec incident keeps its own `category`, `ceiling` and `threshold_basis` without anyone touching the API.

**Then NEU's identifiers cost something real, and the platform had been carrying the fault since its first deployment.** The alert body was a Markdown template with raw event values interpolated into it, so any identifier containing an underscore made the messaging API refuse the whole card - while the incident had already been written and its id consumed, and the caller was answered HTTP 200. It survived because the branch had only ever been exercised with the one module whose identifiers happen to contain no character the markup treats as markup. Fixed by building and escaping the body in code, deployed and verified.

**The general form belongs in this charter rather than only in a README, because it is a rule about how this platform is validated and not an anecdote about one node: a path exercised solely with data that happens to be safe is an untested path, and this one reported success while failing.** The instance, its measured reach across every batch, and the deploy procedure are in `n8n/README.md`.

**And MVTec cost an identity, where the defect was in the adapter rather than in the platform.** The MVTec adapter built a part identity from the category and the image file name, and MVTec numbers its test images from `000` inside every defect-type folder, so 309 events carried 82 distinct record ids. Intake deduplicates on record id and priority together, per section 7.1, so replaying the batch would have suppressed 203 flagged parts as duplicates of parts they are not. Fixed 2026-09-02; the other four adapters were checked for the same class and each produces one record id per event. The general form is worth keeping: a deduplication key is a claim that two records describe the same thing, and it is only ever as good as the identity the publisher builds.

**Next action: Phase 3.** Phase 2 closed on 2026-09-03 with the NHTSA module. What remains is the Streamlit cockpit and the Tableau view of section 7.5, the two operational surfaces that document describes and neither of which exists, plus the lifecycle write path of section 7.2 that both of them need.
