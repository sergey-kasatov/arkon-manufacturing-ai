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
| `out/` | Generated event batches (demo input for the n8n workflow) |

## Usage

```bash
python events/make_events_cmapss.py
python events/make_events_scania.py
python events/make_events_casting.py
python events/make_events_neu.py
python events/validate_event.py events/out/cmapss_events_full_fleet.jsonl
python events/validate_event.py events/out/scania_events.jsonl
python events/validate_event.py events/out/casting_events.jsonl
python events/validate_event.py events/out/neu_events.jsonl
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

**This is the second module in the `visual_inspection` domain.** No contract change
was needed for that: the domain was already in the enum, already in `roster.json`
and already in the assistant's assignment rules. What did change is the
`source_module` enum, which gained `neu_surface` in both
`arkon_event_schema.json` and `validate_event.py`. A consequence worth knowing: an
incident query filtered by `business_domain=visual_inspection` now returns two
modules, so that field has stopped being a one-to-one proxy for a module.
Filtering by `source_module` still separates them.

## Data integrity

Model evidence is real (held-out test-set predictions, including the true
test RUL label for honesty checks). The `operational_context` block is
simulated with a fixed seed and labelled, per charter section 5. The two
never mix in model metrics.
