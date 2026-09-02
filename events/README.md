# Arkon Risk Events

Shared event layer between the model modules and the n8n Quality Steering
Cell. Contract owner: `docs/Project_Charter.md` sections 6 and 7.

| File | Purpose |
|---|---|
| `arkon_event_schema.json` | Formal JSON Schema of the event contract |
| `validate_event.py` | Stdlib validator implementing the same rules |
| `roster.json` | Simulated assignment roster, labelled `context_origin: simulated` |
| `make_events_cmapss.py` | CMAPSS adapter: test predictions to events JSONL |
| `make_events_scania.py` | Scania APS adapter: the same, for the tabular module |
| `make_events_casting.py` | Casting defect adapter: the same, for the vision module |
| `make_events_neu.py` | NEU steel surface adapter: the same, for the defect-type module |
| `make_events_mvtec.py` | MVTec adapter: the same, for the four component anomaly detectors |
| `out/` | Generated event batches (demo input for the n8n workflow) |

## Usage

```bash
python events/make_events_cmapss.py
python events/make_events_scania.py
python events/make_events_casting.py
python events/make_events_neu.py
python events/make_events_mvtec.py
python events/validate_event.py events/out/cmapss_events_full_fleet.jsonl
python events/validate_event.py events/out/scania_events.jsonl
python events/validate_event.py events/out/casting_events.jsonl
python events/validate_event.py events/out/neu_events.jsonl
python events/validate_event.py events/out/mvtec_events.jsonl
```

## CMAPSS priority mapping (charter 7.1)

Predicted RUL in cycles: `<= 10 -> P1`, `<= 25 -> P2`, `<= 50 -> P3`,
above 50 -> `P4`. Risk score: `1 - clip(pred_RUL, 0, 125) / 125`.

## Scania APS priority mapping (charter 7.1)

Predicted failure probability: `>= 0.90 -> P1`, `>= 0.50 -> P2`, at or above the
model's decision threshold -> `P3`, below it -> no event. Risk score is the
probability itself.

Two things differ from the CMAPSS mapping and both are deliberate.

**The bands are confidence bands, not distances from the threshold.** The
decision threshold is very low, about 0.003, because the dataset's own cost
metric prices a missed APS failure at fifty times a needless workshop check. So
most flags are precautionary. A flag at 0.004 and a flag at 0.99 are the same
decision, check the truck, and a very different conversation, and giving both a
P1 would spend the fifteen-minute P1 window on precautionary checks.

**Records below the threshold produce no event at all.** CMAPSS publishes one
event per engine, P4 included, because 707 engines is a fleet an operator
watches. The Scania test set is 16,000 service records of which 778 are flagged;
publishing 15,222 P4 events would bury the store to say nothing. The denominator
is printed on every run and recorded in the model card.

## Casting defect priority mapping (charter 7.1)

Predicted defect probability: `>= 0.99 -> P3`, operating point to 0.99 -> `P2`,
below the operating point -> no event. No P1 in version 1.

**The bands descend the opposite way to the other two modules and the reason is
measured.** Banding by descending confidence produced 447 P1 events out of one
715-image batch, which is 447 immediate alerts on a fifteen-minute clock. On that
batch every one of the 447 confident flags was genuinely defective, while the 13
uncertain ones were defective 6 times out of 13. A confident defect is the
routine case; the uncertain band is where the line stops, because the part can be
neither passed nor scrapped without a person. So the uncertain band gets the
shorter clock.

No P1 because no single part on an inspection line is a fifteen-minute
emergency. The signal that would justify one is a defect **rate**, which is a
batch-level event, and it is not built because this dataset carries no honest
baseline rate: its test split is 63 percent defective by curation.

## NEU steel surface priority mapping (charter 7.1)

Model confidence, the largest of six softmax outputs: `>= 0.90 -> P3`, below it
-> `P2`. No P1 and no P4. Risk score is the confidence itself.

**Every classified surface produces an event.** Casting and Scania publish only
what they flag, because a pass is the normal case. NEU-DET has no good-surface
class: all six of its classes are defects, so there is no pass to leave
unpublished, and this adapter behaves like the CMAPSS one instead.

**Priority comes from confidence and never from the defect class.** Ranking these
six defects by severity would need metallurgical judgement this project does not
have. The defect type rides in `risk_type`, which is the predicted class rather
than a fixed string, and the evidence object carries the whole six-way probability
vector so a consumer can see the runner-up. This is the first module whose
`risk_type` varies between its own events.

**The band edge is declared, not calibrated, and the events say so.** Every event
carries `evidence.threshold_basis`, which reads `declared` here. The intended rule
was to take the lowest confidence at which the accepted predictions on the
selection set are right at least 99 per cent of the time; the model classified all
216 selection images correctly, so every threshold met the target and the rule
returned 0.0, which would leave the P2 band permanently empty. 0.90 is an Arkon
assumption in the same sense as casting's cost ratios. The adapter reads it from
the metrics file rather than defining it, so the two cannot drift apart. Reasoning
in `docs/Model_Card_NEU_Surface.md` section 5.

**This was the second module in the `visual_inspection` domain**, and MVTec is now the third. No contract change
was needed for that: the domain was already in the enum, already in `roster.json`
and already in the assistant's assignment rules. What did change is the
`source_module` enum, which gained `neu_surface` in both
`arkon_event_schema.json` and `validate_event.py`. A consequence worth knowing: an
incident query filtered by `business_domain=visual_inspection` now returns two
modules, so that field has stopped being a one-to-one proxy for a module.
Filtering by `source_module` still separates them.

## MVTec component anomaly priority mapping (charter 7.1)

Anomaly score against two edges read off held-out sound parts:
`above the ceiling -> P2`, `above the threshold -> P3`, below it the part is not
published. No P1 and no P4. Risk score is `score / (score + threshold)`, which is
bounded, never saturates, and puts the threshold at exactly 0.5 for every
category whatever its raw distances look like. The raw distance rides in
`evidence.prediction`.

**Four models behind one event stream.** grid, metal_nut, screw and transistor
are four imaging setups with four memory banks and four thresholds, so the
threshold an event carries depends on the category that produced it. The category
rides in `evidence.category`, and the adapter refuses to run if a threshold in
the prediction table disagrees with the one in the metrics file, because that
would mean one of the two files is stale.

**The part identity carries the whole path, and it took a defect to notice.**
`evidence.record_id` is `MVTEC-<CATEGORY>-<DEFECT TYPE>-<FILE STEM>`, because
MVTec numbers its test images from `000` inside *every* defect-type folder:
`grid/test/bent/000.png` and `grid/test/broken/000.png` are two different parts.
The adapter first carried the category and the file stem only, which left 309
events sharing 82 record ids. Nothing here rejected that - the contract asks for a
record id, not for a unique one - and the cost lands downstream, where the
Steering Cell suppresses duplicates on `record_id` plus `priority` for 24 hours: a
full replay would have recorded 106 incidents and suppressed 203 flagged parts as
duplicates of parts they are not. Fixed 2026-09-02. **The other four adapters were
checked for the same class and each produces one record id per event.** The rule
this leaves behind applies to every future adapter: a deduplication key is a claim
that two records describe the same thing, so an adapter has to make the identity
unique over everything the dataset varies, not over the part of the path that
happens to be visible.

**Only flagged parts produce an event**, like casting and Scania. This dataset
has a sound class and the sound-or-not decision is the whole point of the module,
so publishing every pass would bury the incident store. NEU publishes everything
only because NEU has no sound class at all.

**The priority says how unusual, never how dangerous.** The module is fitted on
sound parts alone and has never seen a defect, so it has no basis for ranking a
scratch against a bent lead against a flipped nut. What it can say is whether any
held-out sound part ever scored this high: above the ceiling, none did. There is
no P1 band for the same reason, since P1 in the charter means safety-relevant.

**Both edges come from sound parts and neither has seen a defect.** The threshold
is the lowest score that flags no more than 5 per cent of the calibration parts,
the ceiling is the highest score any of them reached, and
`evidence.threshold_basis` says so on every event. This is the casting lesson
applied rather than restated: casting searched a cost curve for an optimum and
the optimum moved by a factor of five between identical runs, so this module
declares a budget and reads a quantile instead. Reasoning in
`docs/Model_Card_MVTec_Anomaly.md` section 5.

**This is the third module in the `visual_inspection` domain**, and it needed no
contract change beyond the `source_module` enum, which gained `mvtec_anomaly` in
both `arkon_event_schema.json` and `validate_event.py`. The consequence the NEU
section records gets one step worse: a query filtered by
`business_domain=visual_inspection` now returns three modules across three
departments. Filtering by `source_module` still separates them.

## Data integrity

Model evidence is real (held-out test-set predictions, including the true
test RUL label for honesty checks). The `operational_context` block is
simulated with a fixed seed and labelled, per charter section 5. The two
never mix in model metrics.
