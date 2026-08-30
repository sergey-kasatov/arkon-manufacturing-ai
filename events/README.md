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
| `out/` | Generated event batches (demo input for the n8n workflow) |

## Usage

```bash
python events/make_events_cmapss.py
python events/make_events_scania.py
python events/validate_event.py events/out/cmapss_events_full_fleet.jsonl
python events/validate_event.py events/out/scania_events.jsonl
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
watches. The Scania test set is 16,000 service records of which 738 are flagged;
publishing 15,262 P4 events would bury the store to say nothing. The denominator
is printed on every run and recorded in the model card.

## Data integrity

Model evidence is real (held-out test-set predictions, including the true
test RUL label for honesty checks). The `operational_context` block is
simulated with a fixed seed and labelled, per charter section 5. The two
never mix in model metrics.
