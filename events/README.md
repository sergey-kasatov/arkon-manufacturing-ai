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
| `make_events_gc10.py` | GC10 adapter: the same, for the detection module, and the first whose event carries a list |
| `make_events_nhtsa.py` | NHTSA adapter: the same, for the text module, and the first whose event is about a signal rather than a part |
| `out/` | Generated event batches (demo input for the n8n workflow) |

## Usage

```bash
python events/make_events_cmapss.py
python events/make_events_scania.py
python events/make_events_casting.py
python events/make_events_neu.py
python events/make_events_mvtec.py
python events/make_events_gc10.py
python events/make_events_nhtsa.py
python events/validate_event.py events/out/cmapss_events_full_fleet.jsonl
python events/validate_event.py events/out/scania_events.jsonl
python events/validate_event.py events/out/casting_events.jsonl
python events/validate_event.py events/out/neu_events.jsonl
python events/validate_event.py events/out/mvtec_events.jsonl
python events/validate_event.py events/out/gc10_events.jsonl
python events/validate_event.py events/out/nhtsa_events.jsonl
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
departments, and four once GC10 lands below. Filtering by `source_module` still
separates them.

## GC10 steel sheet defect priority mapping (charter 7.1)

Two thresholds, where every other module has one. A detector needs one to decide
what counts as a box at all and a second to decide how sure it is about the sheet,
because the event it publishes is about the sheet.

    best box score >= 0.90    the located defect is recorded against the coil, P3
    best box score <  0.90    a person looks before the coil is dispositioned, P2
    no box above 0.60          nothing is published

Risk score is the best box's score. No P1 and no P4.

**One event per sheet, and the boxes ride inside it.** Every adapter before this one
publishes one measurement per record. A detector publishes n boxes on one sheet and
35 per cent of these sheets carry more than one, up to eleven, so `evidence` carries
a `detections` list with a class, a score and a box for each.

**The alternative was measured against the platform rather than argued about.** One
event per box would give up to eleven events carrying one sheet identity and usually
one priority, and intake deduplicates on `record_id` plus `priority` for 24 hours, so
ten of the eleven would be suppressed as duplicates of a defect they are not. That is
the MVTec identity defect arriving by a different route. A sheet is also the unit an
operator disposes of: eleven defects on one sheet is one decision.

**This was expected to need a contract change and did not.** `evidence` is declared
with `additionalProperties: true` in `arkon_event_schema.json`, and `validate_event.py`
checks only that the four required keys are present, so a list fits where the contract
already stood. The one closed enum that changed is `source_module`, which gained
`gc10_detect` in both files, exactly as `neu_surface` and `mvtec_anomaly` did. Charter
section 6 now records what `evidence` may hold, because it was true before this module
and nobody had written it down.

**A sheet with no detection publishes nothing, and that is not a pass.** Casting,
Scania and MVTec also suppress their negative case, and they do it because a sound
part is the normal one. This module suppresses its silent case for a different reason
and the difference belongs on the record: GC10 contains no sheet anyone certified
clean, and the eight that carry no annotation were dropped rather than assumed clean,
so the module was fitted and scored only on sheets that contain a defect. It has never
seen sound steel. **"No detection" is a failure to find, not a statement that the sheet
is good**, and anything downstream that reads silence as a pass is wrong. On the test
split 29 of 339 sheets are silent.

**Priority comes from the best box's confidence, never from the defect class and
never from its size.** The class rule is the NEU precedent: ranking a crease against
an oil spot by severity needs metallurgical judgement this project does not have. The
size rule is the less obvious half, because box area is measurable and available and
would look like a measurement: a large water spot is cosmetic and a small crease may
not be, and nothing in this module can tell the difference. That is the MVTec lesson,
whose card says the priority may say how unusual and never how dangerous.

**Both edges are declared targets rather than measured costs.** The detection
threshold 0.60 is the lowest score at which precision on the selection split
reaches 0.60, and the band edge 0.90 is the lowest best-box score at which the
sheet's top detection is correct at least 90 per cent of the time. 0.60 and 90 per
cent are Arkon assumptions in the same sense as casting's cost ratios; this dataset
ships no statement of what a false trip costs against a missed defect. Every event
carries `evidence.threshold_basis` and `evidence.detection_threshold_basis` so a
consumer can see which of the two was calibrated. Reasoning in
`docs/Model_Card_GC10_Detection.md` section 5.

**This is the fourth module in the `visual_inspection` domain.** The consequence the
NEU and MVTec sections record gets one step worse: a query filtered by
`business_domain=visual_inspection` now returns four modules across four departments,
and the roster assigns all four to the same two QC Engineers. Filtering by
`source_module` still separates them.

**The `field_quality` domain below is the counter-example**, and it is worth naming
because it is what the domain field was supposed to do: one module, one department,
one role, so filtering by domain and filtering by module give the same answer.
That is now true of exactly one of the four domains.


## NHTSA field-quality priority mapping (charter 7.1)

Two thresholds, like GC10, and for a different reason: one decides whether a movement
is published at all and the second decides how urgent it is.

    Poisson tail p < 3.25e-06   the movement is published
    risk score >= 0.75                     P2
    risk score <  0.75                     P3
    otherwise                          nothing is published

Risk score is `ratio / (ratio + 1)`, observed over expected: bounded, never
saturating, and exactly 0.5 when a cell sits on its own baseline. That is the shape
MVTec uses on an unbounded distance, reused here. No P1 and no P4.

**The first module that needed no change to this contract at all.** `nhtsa_nlp` was
already in the `source_module` enum of both `arkon_event_schema.json` and
`validate_event.py`, and `field_quality` was already in `business_domain` with a role
behind it in `roster.json`. Every module from NEU onward has added a name to that one
closed enum; this one adds nothing, because the reservation was made when the enum was
written.

**The event is about a signal, not a part.** Every earlier adapter publishes a
measurement of a physical thing the module inspected. A complaint is a report written
by a member of the public about their own vehicle, and nothing in this dataset verifies
any of it. `evidence.record_id` therefore names a manufacturer, a component and a
month rather than a part, `context_origin` stays `real` because the complaints are
real, and the summary says in words that these are public reports rather than an
inspection.

**One event per cell, not per complaint.** The held-out year holds
60,039 complaints, and one event each would be more than
four times everything the incident store has ever held. That is Scania's 15,222
suppressed P4 events in another costume, and the same answer applies: a field-quality
function does not act on one report, it acts when a rate moves.
3,080 manufacturer-component-month cells were tested
against their own trailing baselines and 25 published.

**`evidence.prediction` and `evidence.threshold` are two counts here, not a score and
a cut.** For every other module `threshold` is a decision boundary on a model output.
Here `prediction` is the observed complaint count and `threshold` is what the cell's
own history predicted. The contract permits it, since it constrains neither to a type
beyond being present, and it is recorded because a consumer comparing `threshold`
across modules would be comparing two different kinds of number.

**The band edge is declared, and this is the third module in a row.** The rule could
not be asked: it needs 30 flagged calibration cells and the
calibration window produced 5. **The rule shape has
now failed three times in three different directions** - NEU returned 0.0 because every
threshold met the target, GC10 returned nothing because none did, and this one cannot
run for want of a sample. That is a finding about the rule rather than about any of the
three models.

**And the ordering it produces was measured, which no other module can do.** This
module has a reference: the identical trend procedure run over the held-out labels
instead of the predictions. Scored against it, the Spearman correlation between the
risk score and whether a cell is confirmed is
**-0.056**, and above a 0.80 edge the ordering
inverts. **So the priority says how large the movement is and never how certain it is
that the movement is real**, which the P2 recommended action states in words.

**Priority never comes from the reported harm.** Each complaint carries CRASH, FIRE,
INJURED and DEATHS. Those look like a severity and are not: they are what the person
filing said happened, verified by nobody, and they are an input to this module rather
than an output of it. This is the third variant of the NEU and MVTec rule and the
sharpest, because these fields are not even the module's own estimate.

**What the batch is worth, and it is the only Arkon module that can say.** Precision
0.520 and recall 0.684 against the
label-driven trend, on 25 published cells against
19 the labels flag. **About half of what it publishes is
not confirmed.** It is a monitor that raises roughly two alarms to find one real
movement.

**The events are not independent, which is new for this platform.**
8 of 25 share a manufacturer and a
month with another event, and the largest group is 4 events from one
manufacturer in one month, none of which the labels confirm. One cause moves several
cells, and an operator receives them as separate alerts. Dedup on `record_id` plus
priority does not merge them and should not, because they are different components.
Reasoning in `docs/Model_Card_NHTSA_Field_Quality.md` section 5.

## Data integrity

Model evidence is real (held-out test-set predictions, including the true
test RUL label for honesty checks). The `operational_context` block is
simulated with a fixed seed and labelled, per charter section 5. The two
never mix in model metrics.
