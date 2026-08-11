# Arkon Risk Events

Shared event layer between the model modules and the n8n Quality Steering
Cell. Contract owner: `docs/Project_Charter.md` sections 6 and 7.

| File | Purpose |
|---|---|
| `arkon_event_schema.json` | Formal JSON Schema of the event contract |
| `validate_event.py` | Stdlib validator implementing the same rules |
| `roster.json` | Simulated assignment roster, labelled `context_origin: simulated` |
| `make_events_cmapss.py` | CMAPSS adapter: test predictions to events JSONL |
| `out/` | Generated event batches (demo input for the n8n workflow) |

## Usage

```bash
python events/make_events_cmapss.py
python events/validate_event.py events/out/cmapss_events_FD001.jsonl
```

## CMAPSS priority mapping (charter 7.1)

Predicted RUL in cycles: `<= 10 -> P1`, `<= 25 -> P2`, `<= 50 -> P3`,
above 50 -> `P4`. Risk score: `1 - clip(pred_RUL, 0, 125) / 125`.

## Data integrity

Model evidence is real (held-out test-set predictions, including the true
test RUL label for honesty checks). The `operational_context` block is
simulated with a fixed seed and labelled, per charter section 5. The two
never mix in model metrics.
