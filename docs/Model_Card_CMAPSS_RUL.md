# Model Card: CMAPSS Remaining Useful Life

Module 01 of the Arkon platform. Predicts the remaining useful life (RUL) of a
turbofan engine in cycles, and feeds the Quality Steering Cell through the risk
event adapter.

- **Version:** full-fleet v1, trained 2026-08-30 by the script. Re-derived from
  the raw files by the notebooks twice, and the two runs prove different things:
  - **2026-08-31, the notebook against the script.** All nine headline
    measurements identical. Regenerating the metrics file moved 21 of its 255
    stored values, every one inside `linear_regression` and every one in the last
    digit, largest relative difference 1.1e-15; no XGBoost value and no ablation
    value moved. That is agreement between two independent implementations.
  - **2026-09-01, the notebook against itself.** Nothing moved at all: 255 of 255
    values identical, the prediction table identical by hash, and both result
    figures identical byte for byte. That is determinism, which is the weaker
    claim and the one a reader can check without the script.
- **Artifacts:** `models/checkpoints/cmapss/cmapss_xgboost_full_fleet.pkl`,
  preprocessing in `data/01_cmapss/processed/preprocessing_full_fleet.pkl`,
  metrics in `models/checkpoints/cmapss/cmapss_full_fleet_meta.json`
- **Training code:** `notebooks/01_timeseries/cmapss_full_fleet.py`, and the
  notebook trio `01_cmapss_eda.ipynb`, `02_cmapss_preprocessing.ipynb` and
  `03_cmapss_modeling.ipynb` in the same folder, which build the same experiment
  without importing anything from the script and compare their result against
  this card's numbers on every run
- **Supersedes:** the FD001-only baseline of 2026-08-11, RMSE 17.11 against this
  model's 11.01, whose metrics are kept at
  `models/checkpoints/cmapss/cmapss_xgb_v1_meta.json`. The notebooks that produced
  it were rebuilt on the full fleet on 2026-08-31 and now reproduce this model

---

## 1. Intended use

Rank engines by urgency of inspection inside a simulated engine-testing
operation, so the Quality Steering Cell can route attention. A prediction below
a priority threshold becomes an Arkon risk event (`events/make_events_cmapss.py`)
and, at P1 or P2, a Telegram alert to a human.

**Not intended for:** any real airworthiness, maintenance or safety decision.
The data is a NASA simulation, the operational context around it is fabricated,
and no aviation regulatory process was followed. Per the project charter, a risk
score is not a production stop decision.

## 2. Data

NASA CMAPSS Turbofan Engine Degradation Simulation, all four subsets. Each
engine starts with unknown initial wear, develops a fault, and in the training
set runs to failure; test series stop before failure and the true remaining life
is supplied separately.

| Subset | Train rows | Test rows | Train engines | Operating conditions | Fault modes |
|---|---|---|---|---|---|
| FD001 | 20,631 | 13,096 | 100 | 1 | 1 (HPC) |
| FD002 | 53,759 | 33,991 | 260 | 6 | 1 (HPC) |
| FD003 | 24,720 | 16,596 | 100 | 1 | 2 (HPC, Fan) |
| FD004 | 61,249 | 41,214 | 249 | 6 | 2 (HPC, Fan) |
| **Total** | **160,359** | **104,897** | **709** | 6 distinct | 2 |

Note: the dataset's own `readme.txt` states 248 train and 249 test trajectories
for FD004. The files contain the reverse. The counts above are measured.

## 3. Preprocessing

- **Target:** RUL per row, capped at 125 cycles (piecewise linear RUL, standard
  for this dataset). Degradation is not meaningfully observable in early cycles,
  so an uncapped target mostly teaches the model to predict "healthy".
- **Operating regimes:** the three operating settings, rounded, separate exactly
  six regimes. FD002 and FD004 use all six; FD001 and FD003 sit in the first.
  No clustering is required, and the assignment is deterministic.
- **Normalisation:** `StandardScaler` fitted **per regime on the training set
  only**. A single global scaler is wrong here: sensor readings shift with the
  operating regime, and global scaling flattens the within-regime degradation
  signal that carries the RUL information.
- **Sensors dropped:** `s1`, `s5`, `s18`, `s19` - constant inside every regime.
  The FD001-only pipeline additionally dropped `s6`, `s10` and `s16` as "flat";
  they are constant in FD001 but do vary across the fleet, so they are kept.
- **Temporal features, window 20 cycles.** Per engine, and using only past and
  current cycles: the rolling mean of each sensor (the smoothed level), the
  rolling standard deviation (volatility, which rises as a fault develops), and
  the drift of each sensor from that engine's own first 20 cycles (how far it has
  moved from its own healthy baseline, which cancels unit-to-unit variation).
  Without these the module is tabular regression on time-indexed rows, with the
  raw cycle counter as its only view of time. Section 5 measures what they are
  worth.
- **Features (70):** 17 scaled sensors, 51 temporal features derived from them,
  the cycle counter, and the regime code.

## 4. Performance

XGBoost, 600 trees, depth 8, learning rate 0.05, histogram method. Training
takes seconds on CPU; no GPU is used or needed at this data size.

Two figures are reported because a single number would flatter the model. The
**all rows** figure scores every test row and is what the previous notebook
reported. The **last cycle** figure scores one prediction per engine at its final
observed cycle, which is the actual CMAPSS benchmark task.

| Scope | RMSE | MAE | R2 | n |
|---|---|---|---|---|
| All test rows, whole fleet | 10.05 | 6.13 | 0.860 | 104,897 |
| Last cycle per engine, whole fleet | 11.01 | 7.62 | 0.932 | 707 |
| FD001, last cycle | 9.69 | 6.78 | 0.942 | 100 |
| FD002, last cycle | 11.07 | 7.78 | 0.934 | 259 |
| FD003, last cycle | 10.92 | 7.58 | 0.922 | 100 |
| FD004, last cycle | 11.48 | 7.80 | 0.929 | 248 |

Linear regression on the same features reaches RMSE 14.36 on all rows, so the
gradient boosting is doing real work rather than fitting a trend.

The result that matters is the **evenness**: FD004, with six operating regimes
and two fault modes, scores about as well as FD001 with one of each. The per
regime normalisation is what makes that possible.

## 5. What actually produced the improvement

The starting point was the FD001-only baseline at RMSE 17.11. Three changes were
measured one at a time rather than assumed, and they are very unequal.

**Feature ablation, whole fleet, benchmark task, identical hyperparameters:**

| Feature set | RMSE |
|---|---|
| Scaled sensors only | 18.42 |
| Sensors plus the cycle counter | 16.75 |
| **Sensors, cycle counter and temporal features** | **11.43** |

The temporal features are worth 5.32 RMSE, far more than anything else in this
project. That is the whole argument for treating the module as a time series: a
model that sees one snapshot at a time can only infer elapsed time from the raw
cycle counter, and a degradation trajectory is not visible in a single row.

**Everything else. These rows are not all measured on the same thing, so the basis
is written per row rather than promised once in a caption:**

| Change | RMSE gain | Measured on |
|---|---|---|
| Adding temporal features | **5.32** | benchmark task, 707 engines, whole fleet |
| Adding the cycle counter | 1.67 | benchmark task, 707 engines, whole fleet |
| Training on all four subsets instead of FD001 | 0.92 | benchmark task, 100 FD001 engines |
| the same change, every test row | 0.77 | 13,096 FD001 rows |
| Larger model (600 trees / depth 8 instead of 300 / 6) | ~0.1 | not measured by this pipeline |
| Adding sensors s6, s10, s16 | ~0.02 | not measured by this pipeline |

**The bases differ because one of them has to.** The feature ablation retrains on
the same fleet each time, so it can be scored on all 707 test engines. The data
ablation cannot: its FD001-only arm has never seen FD002, FD003 or FD004, and the
only test set both arms can fairly be shown is FD001. So the first two rows and
the third are separated by a genuine constraint, not by carelessness, and the
ratio between them is not a like-for-like ratio however it is written.

The last two rows are older figures from the FD001-era experiments. Nothing in
`cmapss_full_fleet_meta.json` measures them: the file records the shipped
hyperparameters and the reduced ones the ablation uses, but never scores one
against the other, and s6, s10 and s16 are kept by this pipeline rather than
added to it. They are marked with a tilde and kept because they are the right
order of magnitude for what a reader would otherwise assume, not because this
model card can produce them.

Two things in that table are worth reading carefully.

First, the earlier pipeline dropped `cycle` along with the engine identifier
(`DROP_COLS = ['unit', 'cycle', 'RUL']`), losing a strong predictor for free.

Second, the value of the extra data **depends on the features**. With snapshot
features only, adding FD002, FD003 and FD004 was worth 0.17 RMSE on FD001. With
temporal features it is worth 0.77, four and a half times more. Both are across
every FD001 test row, which is the fourth row of the table above and not the
third, so the two are comparable with each other. More operating
regimes and fault modes help a model that learns trajectories, and barely help a
model that learns levels. The intuitive claim that "more data made it better" is
true only in the second setup, which is why both numbers are recorded here.

## 6. Limitations

1. **The model still uses the cycle counter, and that support is weaker in
   reality.** Using `cycle` is legitimate - it is known at prediction time and is
   not leakage - but in CMAPSS every engine runs from new to failure, so the
   counter almost directly encodes accumulated wear. In a real plant the counter
   resets after an overhaul and the fleet contains engines of mixed history. The
   temporal features reduce this dependence substantially, because drift from an
   engine's own baseline survives a counter reset while the raw counter does not,
   but the feature is still present and still contributes.
2. **Feature engineering, not sequence modelling.** Rolling statistics over a
   fixed 20-cycle window are a hand-built view of the trajectory. A sequence
   model over sliding windows is the standard approach in the CMAPSS literature
   and would learn the shape rather than be told which summaries to look at. The
   window length itself was set once and not tuned.
3. **Simulated data throughout.** CMAPSS is a simulation, not measurements from a
   real fleet. Sensor noise is synthetic and the fault progressions are generated.
4. **Fabricated operational context.** Shifts, assignees and escalation contacts
   attached to the events are invented and labelled `context_origin: simulated`
   in every event. No real person or plant appears anywhere.
5. **Errors are symmetric, the cost is not.** RMSE penalises over- and
   under-prediction equally. Predicting more life than an engine has is the
   expensive direction, and this model is not tuned for that asymmetry. A
   production version would use an asymmetric loss or a calibrated safety margin.
6. **RUL is capped at 125.** The model cannot distinguish a healthy engine from a
   very healthy one, by design. That is correct for triage and wrong for anything
   that needs a true long-horizon estimate.
7. **No uncertainty estimate.** A single point prediction per engine, with no
   interval. A threshold decision near the boundary therefore carries unknown
   confidence, which is exactly where an operator would want it.
8. **No temporal validation split.** The train and test split is the one supplied
   with the dataset. There is no held-out validation set, so the hyperparameters
   were not tuned in a way that could be called honest tuning; they were chosen
   and left.

## 7. Reproduction

```bash
python notebooks/01_timeseries/cmapss_full_fleet.py
```

Reads the raw files from `data/01_cmapss/raw/CMaps`, writes processed data,
models, and the metrics JSON. Deterministic: fixed random seed, no sampling.
The script also re-runs the ablation in section 5 on every execution, so the
claim above stays checkable rather than becoming folklore.

The notebook trio is the second route to the same numbers, and the one to read
rather than run:

```bash
jupyter nbconvert --to notebook --execute --inplace notebooks/01_timeseries/01_cmapss_eda.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/01_timeseries/02_cmapss_preprocessing.ipynb
jupyter nbconvert --to notebook --execute --inplace notebooks/01_timeseries/03_cmapss_modeling.ipynb
```

They define the columns, the loading, the operating regimes and the temporal
features themselves rather than importing them from `cmapss_full_fleet.py`, so
their agreement with this card is a reproduction and not a tautology. Two cells
carry that agreement instead of asserting it: notebook 02 section 10 compares the
kept sensors, the regimes and the feature columns against
`preprocessing_full_fleet.pkl`, and notebook 03 section 11 reads the metrics file
before anything is trained and prints a line-by-line comparison at the end - nine
measurements, largest absolute difference 0.000.
