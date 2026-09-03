# Model Card: NHTSA Consumer Complaints Field Quality

**Module:** Arkon natural language processing, component classification and field-quality trend detection
**Department (fictional):** Field Quality
**Version:** `nhtsa_tfidf_ovr_v1`
**Built:** 2026-09-03, as a notebook trio with no training script behind it
**Notebooks:** `notebooks/04_nlp/01_nhtsa_complaints/`
**Metrics files:** `models/checkpoints/nhtsa/nhtsa_nlp_meta.json` and the two processed
artifacts beside the data. Every number in this card is read from one of them by a
generator, so the card and the run cannot drift apart.

---

## 1. Intended use

This module reads the free text of a consumer vehicle complaint, says which vehicle
components the text is about, and watches the resulting rates for movements a
manufacturer's own recent history does not explain. It is the seventh Arkon model
module and the only one in the `field_quality` domain.

**It is the first Arkon module whose input is not a measurement.** The six before it
read a sensor trace, a service record or a photograph of a part. This one reads what
a member of the public wrote about their own vehicle, in capitals, often
unpunctuated, sometimes transcribed by a clerk to a template. That difference is not
a detail of the data: it changes what the module is allowed to claim, and every
limitation in section 6 follows from it.

**What it is for.** A field-quality function receives thousands of unstructured
reports a month and has to notice, early, that one component on one manufacturer's
vehicles is being reported more than it used to be. The module classifies the text
and publishes a Steering Cell event for each manufacturer-component-month that moved
further than its own trailing baseline explains.

**What it is not for.** It cannot say that a vehicle has a fault. It says a text is
about a component. A complaint is an allegation, this dataset verifies none of them,
and NHTSA's own publication says the same. Nothing downstream of this module should
read one of its events as evidence that a part failed.

---

## 2. Data

**NHTSA consumer complaints received 2020 through 2024**, one tab-delimited file of
418,884 rows and 326,670,366 bytes, published by the Office of
Defects Investigation. Field 20 is the narrative and field 12 is the component.
Provenance, the archive SHA-256 and the immutability rule are in
`data/07_nhtsa_complaints/README.md`.

### The published layout has 49 columns and the file has 51

Every line carries 51 tab-separated fields. Fields 1 to
49 align with the published NHTSA layout, which was
checked by content rather than by name: field 46 holds the `V`/`T`/`E`/`C`
product-type codes, field 21 the `IVOQ`/`EVOQ`/`LETR` complaint-type codes, field 28
the drive-layout codes and field 30 the fuel codes, each exactly where the layout
puts them. **Fields 50 and 51 are empty on all 418,884 lines.** A reader
given 49 names either fails or shifts every column
silently, and the dataset README asks for precisely this validation.

**Two `read_csv` defaults corrupt this file and neither announces itself.** The
default quote handling loses **78 rows**, because
34,696 narratives contain a double quote and
the reader treats it as the start of a quoted field. The default missing-value list
turns a narrative whose entire text is `N/A` into an absent value, and there are
50 of those. The notebooks read it with
`quoting=csv.QUOTE_NONE` and `keep_default_na=False`, and assert the row count
afterwards.

### The row is not the complaint, and the duplication is exact

418,884 rows carry **291,999 complaints**. A complaint appears
on one row per component it names, and **all 126,885
extra rows repeat the first row's narrative byte for byte** - not similar, identical,
checked by string equality. Training at row level would put the same text on both
sides of any split that does not respect the complaint id, tens of thousands of times.

This is the casting and GC10 lesson at its easiest setting. Casting shipped 64
byte-identical images across its split. GC10 could not answer the equivalent question
at all, because nothing in it was identical and similarity ran as a continuous ridge
with no gap. Here the duplication is exact and total, so the split unit is a fact
rather than a judgement.

**30.2% of complaints name more than one component**,
88,185 of them, which is why the target is a set rather
than one value.

### The label column is two labellings, and the seam is a single day

The dataset README asks for a temporal split. A temporal split assumes the label means
the same thing at both ends of the window, and here it does not.

**On 20201104, `ELECTRONIC STABILITY CONTROL (ESC)` stops and three classes start.** The retiring
class runs at 4 to 17 rows a day through 20201103 and is
zero from the next day. `FORWARD COLLISION AVOIDANCE`, `LANE DEPARTURE`
and `BACK OVER PREVENTION` all begin real volume on that same day. Across the
seam, forward collision avoidance moves by 58 times its previous share and
lane departure by 47; the retiring class falls to
0.038 of its own. This is not drift, it is an
intake form changing.

The window therefore starts at the seam. It costs
70,739 rows and
50,170 complaints, which is the largest single exclusion
in the table below, and it is the GC10 rule applied again: the label is whatever the
file holds, and this file holds two of them.

**The seam removes the discontinuity. It does not remove the drift.** Inside the
surviving window 7 of 24 classes differ
between the training window and the held-out year by more than half their own share,
`ENGINE AND ENGINE COOLING` furthest at 2.72 times. That is the
honest situation for a field-quality module and section 4 reports it beside the score
rather than under it.

### Five exclusions, each counted

| Exclusion | Complaints |
|---|---|
| received before the taxonomy seam 20201104 | 50,170 |
| not unambiguously about a vehicle | 3,908 |
| no component label left after the non-component values | 17,649 |
| narrative shorter than 30 characters | 1,940 |
| narrative is a pointer to a document not in the dataset | 611 |
| every label below the class floor | 1,629 |
| narrative already present in an earlier split | 362 |
| **kept** | **215,730** |

`UNKNOWN OR OTHER` is the third largest value in the whole file at
9.8% of rows, and it is not a component: it is what the
form records when the person filing could not choose one. A model predicting it would
be modelling the reporter rather than the vehicle, so it is excluded with `NONE` and
`Other/I am not sure`. **That exclusion is a decision, not a cleanup**, and it is the
reason the module has no way to answer "none of these".

The pointer exclusion removes complaints whose entire narrative reads `See attached
document for complaint`, pointing at a document this dataset does not contain. One such
text is filed under 331 distinct complaint ids.

### Duplicate narratives across the split boundary

939 narratives in the raw file appear under more than one
complaint id, covering 3,623 complaints, one of them
under 331 ids at once. 247
of those groups span more than one year, so splitting on the date does not separate
them, and neither does the complaint id that fixes the much larger within-complaint
duplication.

After the exclusions, **362 later copies were removed**,
323 from the held-out year and
39 from the calibration window. No
narrative now appears in two splits, and the notebook asserts it rather than hoping.

**That biases the held-out year** against template and campaign complaints, which are
exactly the repeated ones. Section 6 limitation 5.

### The three windows

| Split | Complaints | From | To | Purpose |
|---|---|---|---|---|
| train | 126,154 | 20201104 | 20230630 | fitted |
| selection | 29,537 | 20230701 | 20231231 | thresholds calibrated, never fitted |
| test | 60,039 | 20240101 | 20241231 | scored once |

**24 classes**, floored at 500 training
complaints measured on the training window alone, because a floor read off the whole
dataset would let the held-out year choose the task.
20 classes fell below it, the largest being
CHILD SEAT, COMMUNICATION, COMMUNICATIONS, Chest Clip, Buckle, Harness. Mean labels per complaint
1.359.

---

## 3. Method

TF-IDF over word unigrams and bigrams, `min_df=5`, sublinear term
frequency, 202,240 terms; one-vs-rest logistic regression, liblinear,
C=1.0, one binary problem per class. Fitted in 77 seconds.

**No transformer, and the reason is a project convention rather than a preference.**
The environment has neither `transformers` nor `spacy` nor `nltk`. Adding one would be
a new dependency introduced for a single number, which this repository's conventions
ask to be flagged rather than done quietly. A linear model over TF-IDF is also the
approach whose failures are legible: every prediction traces back to words that are in
the text, which matters for a module whose output a person has to challenge.

**Bigrams are in the shipped model and are worth almost nothing.** They are
184,015 of the 202,240
features, 11 times the unigram
vocabulary on their own, and the ablation puts them at
**+0.0019 micro F1** and
+0.0008 macro F1. They are kept because they cost
seconds and change nothing, and the number is recorded because it is the kind of
addition that usually gets asserted to be worth having.

---

## 4. Performance

Scored once on 60,039 complaints received in 2024, over
24 component classes, from the narrative text alone.

| Arm | micro F1 | macro F1 | micro precision | micro recall | exact set | any label hit |
|---|---|---|---|---|---|---|
| always "ENGINE" | 0.1982 | 0.0158 | 0.2342 | 0.1718 | 0.1300 | 0.2342 |
| prevalence only, no text | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| unigrams only | 0.6848 | 0.6297 | 0.6053 | 0.7884 | 0.4065 | 0.9223 |
| model at 0.5 | 0.6645 | 0.5759 | 0.8529 | 0.5443 | 0.4979 | 0.7081 |
| **model, per-class thresholds** | **0.6867** | **0.6306** | 0.6036 | 0.7962 | 0.4076 | 0.9261 |

**The two subset measures bracket the honest reading.**
92.6% of complaints get at least one of their components right.
40.8% get the exact set. A multi-label task has no single accuracy,
and quoting only the friendlier number would be the kind of claim this project keeps
finding in its own documents.

**Per-class thresholds buy recall and cost exact matches**, which is a trade rather
than an improvement: micro recall rises from 0.5443 to
0.7962 and the any-label-hit rate from
70.8% to 92.6%, while the exact-set
rate falls from 49.8% to 40.8%. Micro F1 moves
+0.0221 and macro F1
+0.0547. The thresholds are kept because the
module feeds a trend detector that needs coverage, not exact sets.

**The prevalence-only reference scores zero, and that is informative rather than
broken.** No class is present in more than half of complaints, so a model that ignores
the text predicts nothing at all under a 0.5 rule. The always-`ENGINE`
reference at 0.1982 micro F1 is the real floor.

### Per class, at the shipped thresholds

| Class | Train | Test support | Predicted | Precision | Recall | F1 | Threshold |
|---|---|---|---|---|---|---|---|
| FUEL SYSTEM, GASOLINE | 1,637 | 1,703 | 2,005 | 0.824 | 0.971 | **0.892** | 0.06 |
| ENGINE AND ENGINE COOLING | 2,358 | 3,062 | 3,442 | 0.770 | 0.866 | **0.815** | 0.14 |
| SERVICE BRAKES, HYDRAULIC | 1,993 | 1,474 | 2,058 | 0.672 | 0.938 | **0.783** | 0.05 |
| SEAT BELTS | 1,976 | 980 | 1,221 | 0.661 | 0.823 | **0.733** | 0.06 |
| EXTERIOR LIGHTING | 5,028 | 1,943 | 2,658 | 0.628 | 0.859 | **0.725** | 0.07 |
| STRUCTURE | 7,324 | 3,582 | 4,864 | 0.629 | 0.854 | **0.725** | 0.12 |
| STEERING | 13,677 | 5,970 | 9,796 | 0.571 | 0.938 | **0.710** | 0.06 |
| SERVICE BRAKES | 11,947 | 5,788 | 8,261 | 0.601 | 0.858 | **0.707** | 0.11 |
| ENGINE | 28,364 | 14,059 | 22,756 | 0.570 | 0.922 | **0.704** | 0.15 |
| POWER TRAIN | 18,779 | 9,199 | 12,249 | 0.615 | 0.819 | **0.702** | 0.17 |
| AIR BAGS | 8,791 | 3,676 | 6,487 | 0.541 | 0.954 | **0.690** | 0.05 |
| VISIBILITY/WIPER | 4,888 | 1,524 | 2,150 | 0.586 | 0.826 | **0.685** | 0.10 |
| SUSPENSION | 6,501 | 1,933 | 2,376 | 0.617 | 0.758 | **0.680** | 0.14 |
| ELECTRICAL SYSTEM | 24,395 | 11,475 | 14,015 | 0.611 | 0.747 | **0.672** | 0.24 |
| SEATS | 1,916 | 776 | 961 | 0.578 | 0.715 | **0.639** | 0.11 |
| FORWARD COLLISION AVOIDANCE | 7,933 | 3,751 | 4,510 | 0.584 | 0.702 | **0.638** | 0.13 |
| BACK OVER PREVENTION | 1,771 | 1,048 | 1,288 | 0.562 | 0.691 | **0.620** | 0.08 |
| FUEL/PROPULSION SYSTEM | 8,361 | 4,275 | 4,253 | 0.615 | 0.612 | **0.614** | 0.18 |
| VISIBILITY | 1,850 | 552 | 645 | 0.495 | 0.578 | **0.533** | 0.18 |
| WHEELS | 2,239 | 776 | 666 | 0.575 | 0.494 | **0.531** | 0.12 |
| LATCHES/LOCKS/LINKAGES | 1,144 | 414 | 218 | 0.748 | 0.394 | **0.516** | 0.43 |
| LANE DEPARTURE | 1,910 | 1,253 | 695 | 0.646 | 0.358 | **0.461** | 0.19 |
| EQUIPMENT | 526 | 161 | 19 | 0.947 | 0.112 | **0.200** | 0.22 |
| VEHICLE SPEED CONTROL | 5,495 | 2,472 | 361 | 0.618 | 0.090 | **0.157** | 0.52 |

**The amount of training data does not order this table**, which is the GC10 finding
arriving on a third architecture. The Spearman correlation between training support and
per-class F1 is **0.257**. The best class,
`FUEL SYSTEM, GASOLINE` at F1 0.892, has 1,637 training complaints;
the worst, `VEHICLE SPEED CONTROL` at 0.157, has 5,495, more than
three times as many.

**What appears to order it is how specific the component's vocabulary is**, and that is
offered as the reading the data supports rather than as a measured fact, because
nothing here regressed F1 on a vocabulary measure. The classes at the top name things a
complaint says in words: a gasoline fuel system, engine cooling, hydraulic brakes, seat
belts. The ones at the bottom are diffuse. `VEHICLE SPEED CONTROL` at F1
0.157 covers cruise control, unintended acceleration and throttle response,
which a complaint describes in the same words other classes use, and the
precision-first threshold rule then pushes its threshold to 0.52 and
its recall to 0.090. **The rule sacrifices that class and `EQUIPMENT`
almost entirely to hold its precision target**, and it does so silently, which is worth
knowing before the target is reused.

### Does it reproduce

**Yes, exactly, and it is the first Arkon module of which that is true.** A refit at
the same seed moved no predicted probability by more than
**0.0e+00** over 1,440,936 predictions, and micro
F1 is identical to six decimal places. liblinear is a deterministic coordinate solver
on a fixed sparse matrix, so this is the expected result rather than a lucky one. It is
measured because casting and GC10 both expected the same and got a different answer,
and GC10's divergence reached its operating point.

---

## 5. Priority mapping (charter section 7.1)

Two thresholds, like GC10 and for a different reason: one decides whether a movement is
published at all, and a second decides how urgent it is.

    Poisson tail p < 3.25e-06   the movement is published
    risk score >= 0.75                     P2
    risk score <  0.75                     P3
    otherwise                          nothing is published

Risk score is `ratio / (ratio + 1)` where ratio is observed over expected: bounded,
never saturating, and exactly 0.5 when a cell sits on its own baseline. That is the
shape MVTec uses to turn an unbounded distance into a score, reused here.

**No P1**, because P1 in section 7.1 means safety-relevant and this module cannot judge
safety. **No P4**, because only cells that cleared the gate are published.

### The unit is a cell, not a complaint

The held-out year holds 60,039 complaints. One event each would be more
than four times everything the incident store has ever held, which is Scania's 15,222
suppressed P4 events in another costume. The classifier's predictions are aggregated
into manufacturer-component-month cells; **3,080 cells were tested and
25 published**.

### The baseline is trailing, and both sides of it are the model's own output

The expected count for a cell is its manufacturer's rate for that component over the
preceding six months, applied to that manufacturer's complaint volume in the observed
month (trailing 6 months, minimum 3). Two properties of it were chosen rather than inherited.

**Both the baseline and the observation are model predictions.** If the baseline came
from the labels and the observation from predictions, a model that over-predicts a
class by twenty per cent would flag every cell of that class for ever, and the flag
would be measuring the model rather than the fleet.

**And both are out of sample.** The model was fitted on the training window, so its
predictions there are optimistic in a way its predictions on 2024 are not. The trailing
window only ever covers months the model never fitted on.

**The rate adjustment is not cosmetic.** Complaint volume rises
17.6% from the first year of the raw file to the last, so an
unadjusted count comparison between two periods would find a trend in every cell.

### The gate is corrected for how many cells are tested

3,080 cells are tested. An uncorrected 1% test
would produce about 31 false alarms a year by
construction, so the family alpha 0.01 is divided by the number of
cells, giving 3.25e-06.

### The band edge is declared, and this is the third module in a row

**The rule could not be asked.** It needed 30 flagged
calibration cells to answer from and the calibration window produced
5. That shortfall is structural rather than bad luck:
the calibration window is six months, a cell needs three months of trailing history
before it can be tested at all, and the corrected alpha then flags well under one per
cent of what remains.

**This rule shape has now failed three times, in three different directions.** NEU
declared it and it returned 0.0, because the model was right about every selection
image so every threshold met the target. GC10 declared it and it returned nothing,
because no threshold ever met the target. Here it cannot run for want of a sample. A
rule that answers only when the data sits in the middle of its range is a finding about
the rule rather than about any of the three models.

### And the ordering it produces carries no information

This is the sharper half, and it is measured rather than suspected. The label-driven
trend gives the set of cells that genuinely moved, so the published batch can be scored
band by band.

| Edge | P2 | P3 | P2 agreement | P3 agreement |
|---|---|---|---|---|
| 0.60 | 23 | 2 | 0.522 | 0.500 |
| 0.65 | 19 | 6 | 0.579 | 0.333 |
| 0.70 | 11 | 14 | 0.545 | 0.500 |
| **0.75** | **9** | **16** | **0.444** | **0.562** |
| 0.80 | 4 | 21 | 0.250 | 0.571 |
| 0.85 | 2 | 23 | 0.500 | 0.522 |

The Spearman correlation between the risk score and whether the labels confirm the cell
is **-0.056**, and at the higher edges the ordering
inverts: the largest apparent movements are the ones the labels do not confirm. That is
consistent with the clustering below - a very large ratio is more often the classifier
misreading one manufacturer than the fleet actually moving.

**So the band says how large the movement is and never how certain it is that the
movement is real.** The events carry `evidence.band_basis: declared`, the
summary states the size, and the recommended action for P2 says in words that the
module cannot tell whether the vehicles or the reporting changed.

### Priority never comes from the reported harm

Each complaint carries CRASH, FIRE, INJURED and DEATHS: 19,125 rows say a
crash, 8,015 a fire, 11,419 an injury and
411 a death. They look like a severity and they are not:
they are what the person filing said happened, verified by nobody, and they are an
**input** to this module rather than an output of it. Ranking events by them would be
this module asserting a safety judgement it has no basis for, which is the rule NEU and
MVTec both set for their own defect classes. This is a third variant of it and the
sharpest, because these fields are not even the module's own estimate.

### What the published batch is worth

The honesty check the other six modules cannot run: the identical trend procedure over
the held-out labels instead of the predictions.

| Measure | Value |
|---|---|
| Cells published from model predictions | 25 |
| Cells flagged from the true labels | 19 |
| Both | 13 |
| Precision against the label-driven trend | **0.520** |
| Recall against the label-driven trend | **0.684** |

**About half of what this module publishes is not confirmed by the labels.** That is
the number to quote about it. It is a monitor that raises roughly two alarms to find
one real movement, and finds about two thirds of the movements there are.

### The events are not independent

Every other Arkon module publishes one event per physical thing it inspected, so two
events are two parts. Here one underlying cause can move several cells at once.
8 of 25 events share a manufacturer
and a month with another event, across 20 groups, and
**the largest group is 4 events from one manufacturer in one month,
none of which the labels confirm.** An operator would receive those as
4 separate alerts.

5 events come from one manufacturer-component pair
that fired in five separate months. The Steering Cell deduplicates on `record_id` plus
priority for 24 hours and these carry different months, so it does not suppress them,
and it should not: each month is a new observation. It is still worth knowing that one
sustained shift becomes 5 incidents.

---

## 6. Limitations

1. **It cannot say a vehicle has a fault.** It says a text is about a component. A
   complaint is an unverified allegation and this dataset verifies none of them.
   Nothing downstream should read an event as evidence that a part failed.

2. **About half its published movements are not confirmed by the labels.** Precision
   against the label-driven trend is 0.520 on
   25 events. Recall is 0.684.

3. **The priority ranks size, not truth.** Correlation between the risk score and label
   agreement is -0.056 and the ordering inverts at
   the top. A P2 here means a larger movement, not a more certain one.

4. **It has no "none of these" answer.** `UNKNOWN OR OTHER` was excluded as a
   non-component, which removed
   17,649 complaints. Incoming text that fits none of the
   24 classes will be forced into whichever ones clear their
   thresholds, and 9.8% of the raw file is exactly that
   kind of text (41,033 rows).

5. **The held-out year is biased against template complaints.**
   362 later copies of narratives already seen in an earlier
   split were removed, 323 of them from the
   test window, and those are precisely the campaign and form-letter complaints. The
   split is clean at the cost of being slightly unrepresentative, and both halves of
   that are true.

6. **The label prior drifts inside the surviving window.**
   7 of 24 classes differ between train
   and test by more than half their own share. The seam at 20201104 removed a
   discontinuity, not the drift.

7. **Two classes are sacrificed by the threshold rule.** `VEHICLE SPEED CONTROL` and
   `EQUIPMENT` hold recall of 0.090 and 0.112: the
   precision-first rule raises their thresholds until they almost never fire. The
   module effectively does not detect them.

8. **Narratives are truncated at 2,048 characters** by the publisher,
   986 rows in the raw file sitting exactly at the cap. Whatever a long
   complaint says at the end is not in the file and was never available to the model.
   3,086 narratives are 25 characters or shorter.

9. **`evidence.threshold` is a count, not a score.** For every other module it is a cut
   on a model output. Here `prediction` and `threshold` are the observed and the
   expected complaint count. The contract permits it, and a consumer that assumes the
   two are comparable across modules is wrong about this one.

10. **One month is the resolution.** A movement inside a month is invisible, and a cell
    is published up to a month after the complaints arrived.

---

## 7. Reproduction

```bash
# 1. The dataset must be in place at data/07_nhtsa_complaints/raw/
#    (326,670,366 bytes; restore with data/download_datasets.sh)

# 2. The notebooks, in order. 01 and 02 take about four minutes each;
#    03 takes about eight, of which five are three one-vs-rest fits.
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/04_nlp/01_nhtsa_complaints/01_nhtsa_eda.ipynb
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/04_nlp/01_nhtsa_complaints/02_nhtsa_preprocessing.ipynb
jupyter nbconvert --to notebook --execute --inplace \
  notebooks/04_nlp/01_nhtsa_complaints/03_nhtsa_modeling.ipynb

# 3. The events the Steering Cell consumes
python events/make_events_nhtsa.py
python events/validate_event.py events/out/nhtsa_events.jsonl

# 4. The README figure, from the metrics file alone
python tools/make_result_plots.py nhtsa_figure
```

Seed 42, Python 3.12.10. The module reproduces exactly, see section 4.
