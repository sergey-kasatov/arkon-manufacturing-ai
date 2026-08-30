# Model Card: Scania APS Failure Classification

Module 02 of the Arkon platform. Decides whether a heavy truck's service issue
belongs to the air pressure system, and feeds the Quality Steering Cell through
the risk event adapter.

- **Version:** v1, trained 2026-08-30
- **Artifacts:** `models/checkpoints/scania/scania_xgboost_v1.pkl`,
  preprocessing in `data/02_scania/processed/preprocessing_scania.pkl`,
  metrics in `models/checkpoints/scania/scania_aps_meta.json`
- **Training code:** `notebooks/02_ml/scania_aps.py`
- **Event adapter:** `events/make_events_scania.py`

---

## 1. Intended use

Rank truck service records by the probability that the fault is in the air
pressure system, so the Quality Steering Cell can route a workshop check. A
prediction above the decision threshold becomes an Arkon risk event and, at P1
or P2, a Telegram alert to a human.

**Not intended for:** any real maintenance, roadworthiness or safety decision.
The data is a 2016 research release from Scania with anonymised features, the
operational context around it is fabricated, and no vehicle-safety process was
followed. Per the project charter, a risk score is not a production stop
decision.

## 2. Why this module exists beside CMAPSS

The two modules answer different questions on purpose, and the second one closes
a gap the first one names.

**CMAPSS model card, limitation 5:** "Errors are symmetric, the cost is not.
RMSE penalises over- and under-prediction equally. Predicting more life than an
engine has is the expensive direction, and this model is not tuned for that
asymmetry."

This dataset ships the asymmetry as its metric:

```text
cost = 10 * false positives + 500 * false negatives
```

10 is an unnecessary check by a mechanic at a workshop. 500 is a missed faulty
truck, which may break down. Fifty to one. So here the decision threshold is not
a default to leave alone, it is the model's main lever, and section 5 measures
what it is worth.

## 3. Data

APS Failure and Operational Data for Scania Trucks, the IDA 2016 Industrial
Challenge release. Features are anonymised operational counters and histogram
bins; the identity of each is proprietary and is not in the release.

| Split | Rows | Positive (APS failure) | Share |
|---|---|---|---|
| Train | 60,000 | 1,000 | 1.67% |
| Test | 16,000 | 375 | 2.34% |

170 features. **8.3% of all training cells are missing**, and the missingness is
very unevenly spread: the worst column, `br_000`, is missing in 82.1% of rows.

The train and test split is the one supplied with the dataset. The validation
used for every choice in section 4 is five-fold stratified cross-validation over
the training rows only.

## 4. How the shipped configuration was chosen

Two binary choices, four candidates, and the winner picked on out-of-fold cost.
The test set was scored once, after the choice was made.

| Choice | Options |
|---|---|
| Missing values | keep as NaN so XGBoost learns a default direction per split, or fill with the training median |
| Class imbalance | `scale_pos_weight` on, or off |

Every candidate gets its decision threshold tuned the same way: five-fold
stratified cross-validation produces one out-of-fold probability per training
row, and the threshold that minimises cost on those is that run's threshold. The
search is exact rather than a grid, because the scores cluster hard at zero and a
fixed grid can step over the optimum.

**The whole selection runs three times, on three fold seeds, and that is the
finding.** The first version of this card used one seed and reported two
confident conclusions: that median imputation beats leaving NaN, and that class
weighting hurts once the threshold is tuned. Repeating the selection with two
more seeds produced **three different winners**.

| Candidate | Mean out-of-fold cost | Seed 42 | Seed 7 | Seed 2026 | Threshold |
|---|---|---|---|---|---|
| **NaN kept, no class weighting** | **35,403** | 35,900 | **35,010** | 35,300 | **0.002366** |
| Imputed, no class weighting | 35,870 | **35,670** | 35,240 | 36,700 | 0.004735 |
| Imputed, class weighting | 36,410 | 37,360 | 36,860 | **35,010** | 0.005134 |
| NaN kept, class weighting | 36,830 | 35,940 | 37,990 | 36,560 | 0.005436 |

Spread between best and worst candidate: **4.0 percent**. Winner by seed: 42
picks imputed-plain, 7 picks NaN-plain, 2026 picks imputed-weighted.

**So the honest conclusion is that neither structural choice matters on this
dataset.** They sit inside the noise of the selection, and a rule that resolves a
near-tie by one coin flip will report whichever way that flip landed as a
finding. The shipped rule takes the lowest mean over the three seeds, which picks
NaN kept with no class weighting, and its threshold is the mean of the three.

**Out-of-fold cost is a ranking device, not a number to compare with the test
figure.** It is computed over 60,000 rows containing 1,000 positives, from models
each trained on four fifths of the data; the test cost is over 16,000 rows with
375 positives. The two are not on the same scale and are never compared here.

## 5. Performance

Test set, 16,000 rows, scored once at the threshold chosen in section 4.

| Metric | Value |
|---|---|
| **Total cost** | **10,660** |
| False positives (needless checks) | 416 |
| False negatives (missed failures) | 13 |
| True positives | 362 |
| Recall | 0.9653 |
| Precision | 0.4653 |
| ROC AUC | 0.9952 |
| PR AUC | 0.9286 |

### What each change is worth

Every row is the same pipeline with one thing changed, scored on the test set.

| Configuration | Cost | False positives | False negatives |
|---|---|---|---|
| **Shipped** (NaN kept, no weighting, tuned threshold) | **10,660** | 416 | 13 |
| Imputed, class weighting, tuned threshold | 9,880 | 438 | 11 |
| NaN kept, class weighting, tuned threshold | 10,800 | 380 | 14 |
| Imputed, no weighting, tuned threshold | 12,050 | 305 | 18 |
| Logistic regression, tuned threshold | 15,330 | 533 | 20 |
| **Shipped model at the default threshold 0.5** | **40,650** | 15 | 81 |

Two rows carry the whole module, and they are not the ones a leaderboard would
look at.

**The threshold is worth 29,990 cost, a factor of 3.8.** The same model, the same
probabilities, one decision: 0.5 catches 294 of 375 failures, the tuned threshold
catches 362. Nothing else in this project comes close to that return for that
little work, and it is invisible to accuracy, which is above 99 percent at either
threshold.

**Everything structural is worth nothing measurable.** The four candidates span
9,880 to 12,050 on the test set and 4.0 percent on out-of-fold cost, and they
rank differently on every seed. Reporting one of them as a finding would have
been reporting a coin flip.

**The honest protocol cost 780.** The configuration that scores best on the test
set, imputed with class weighting at 9,880, is not the one that won on out-of-fold
data. Picking it would mean choosing on the test set, which is how a number stops
meaning anything. The gap is recorded rather than harvested.

### Against the published challenge results

The dataset description lists the top three of the IDA 2016 challenge on this
same test set with this same metric.

| | Cost | False positives | False negatives |
|---|---|---|---|
| Challenge 1st | 9,920 | 542 | 9 |
| Challenge 2nd | 10,900 | 490 | 12 |
| **This model** | **10,660** | 416 | 13 |
| Challenge 3rd | 11,480 | 398 | 15 |

A carefully thresholded gradient-boosting baseline lands between second and third
place on a ten-year-old public benchmark. That is the right size of claim. It is
worth noting what the first version of this card said instead: the single-seed
selection happened to pick a configuration scoring 9,750, which is below the
challenge winner, and it would have been written up as beating them. The number
was real; the procedure that produced it was one coin flip, and the same coin
lands on 12,050 for a different seed.

## 6. Limitations

1. **Precision is 0.47.** More than half of the flagged trucks are fine. That is not a
   defect, it is what the cost metric asks for: at fifty to one, buying one
   caught failure with fifty needless checks still pays. It does mean the
   workshop sees roughly twice the work the failures alone would justify, and an
   operator told only "flagged" and not "probability 0.004" will lose confidence
   in the system. The priority bands in section 7 exist for that reason.
2. **The features are anonymised, so nothing here is diagnosable.** The model
   says a truck is likely to have an APS fault and cannot say which part or why.
   No feature importance in this module means anything a mechanic can act on.
3. **The threshold is tuned to one cost ratio and one prevalence**, and it is the
   only thing here that a measurement supports. 10 to 500 is
   the challenge's ratio, not a measured Arkon figure, and the test prevalence
   (2.34%) is higher than the training prevalence (1.67%). A different fleet
   mix moves the optimum, and nothing in the pipeline detects that it has moved.
4. **No calibration.** The scores are ranked well, with ROC AUC 0.995, but a
   probability of 0.004 is not a claim that 4 trucks in 1,000 fail. The bands in
   section 7 use the scores as confidence ordering, not as calibrated
   probabilities, and they would need calibration before anyone read them as odds.
5. **No temporal structure.** Rows are independent service records with no truck
   identity and no time. A real deployment would see the same truck repeatedly
   and should not treat each visit as a fresh draw.
6. **Hyperparameters were chosen and left.** They are the CMAPSS module's, minus
   two levels of depth. They were not tuned, and this card does not claim they
   were.
7. **Fabricated operational context.** Depots, assignees and escalation contacts
   attached to the events are invented and labelled `context_origin: simulated`
   in every event. No real person or fleet appears anywhere.

## 7. Priority mapping (charter section 7.1)

Each module documents its own risk-score-to-priority thresholds next to the
model. This one uses the predicted failure probability directly.

| Priority | Band | Test count | What the operator does |
|---|---|---|---|
| P1 | probability >= 0.90 | 240 | Hold the truck, book the workshop before the next run |
| P2 | 0.50 to 0.90 | 69 | Book an APS check within the shift |
| P3 | decision threshold (0.0024) to 0.50 | 469 | Add an APS check to the next planned service slot |
| P4 | below the threshold | not published | Nothing. No event is emitted |

**P1 is justified by what the system does, not by the number.** The air pressure
system drives braking and gear changes on a heavy truck, so a confident
prediction is safety-relevant, which is the charter's own P1 definition.

**The bands are confidence bands, not distances from the threshold**, because the
threshold sits at 0.0024 and almost every flag is precautionary. A flag at 0.003
and a flag at 0.99 are the same decision and a very different conversation, and
giving both a P1 would spend the fifteen-minute P1 window on precautionary
checks.

**Below the threshold, nothing is published.** CMAPSS emits one event per engine,
P4 included, because 707 engines is a fleet an operator watches. Here 15,222 of
16,000 records are below the threshold, and publishing them as P4 would bury the
incident store to say nothing. The denominator is printed on every adapter run.

Like the CMAPSS thresholds, these are recorded as a tuning input rather than a
validated optimum. Only the decision threshold itself was optimised, and only
against the challenge cost ratio.

## 8. Reproduction

```bash
python notebooks/02_ml/scania_aps.py
python events/make_events_scania.py
python events/validate_event.py events/out/scania_events.jsonl
```

Reads the raw files from `data/02_scania/raw`, writes the model, the
preprocessing, the test predictions and the metrics JSON. Deterministic: fixed
seeds, fixed folds, no sampling. The script re-runs the three-seed candidate
selection and the whole ablation of section 5 on every execution, so the claims
above stay checkable rather than becoming folklore. The selection is the slow
part, sixty model fits, and it is deliberately not cached: a cached selection is
how a stale winner survives a change to the data.
